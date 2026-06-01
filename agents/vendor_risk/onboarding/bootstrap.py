"""Lifespan bootstrap for vendor_risk's two AI Systems.

Ensures sys-vendor-risk-ext-001 and sys-vendor-risk-int-001 exist in
data/ai_systems.jsonl on every engine cold start by going through the
canonical intake pipeline (api.intake.submit_intake) with a deterministic
system_id_override. Idempotent — skips systems that already exist.

This is the load-bearing piece that makes S82a's Phase 1 honest: rather
than hand-writing seed rows in domain/seed.py (the S81b finadvice
workaround we're now treating as a cautionary anti-pattern), the rows
land through the real intake pipeline with real risk classification,
real assessment, and real release gates. See [[agent-default-system-id-needs-seed]]
and docs/SOP-agent-onboarding.md Phase 1.

Per [[deploy-zip-overwrites-runtime-data]]: data/*.jsonl is wiped on no-op
runtime data (the deploy zip excludes data/), so this bootstrap re-runs
on every cold container start. The intake submission is fully repeatable
because system_id_override is deterministic.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Final

_log = logging.getLogger(__name__)

_PAYLOAD_DIR: Final[Path] = Path(__file__).resolve().parent
_SYSTEMS: Final[tuple[tuple[str, str], ...]] = (
    ("sys-vendor-risk-ext-001", "intake_payload_ext.json"),
    ("sys-vendor-risk-int-001", "intake_payload_int.json"),
)


def _existing_system_ids() -> set[str]:
    """Read data/ai_systems.jsonl and return the set of currently-present ids.

    Tolerates missing file (fresh container) and individual malformed lines —
    a malformed line should not cause us to re-submit existing intake records.
    """
    # Lazy import: api.intake module-load isn't free and we only need the path.
    from domain.repository import SYSTEMS_FILE

    if not SYSTEMS_FILE.exists():
        return set()

    ids: set[str] = set()
    with SYSTEMS_FILE.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                sid = row.get("id")
                if isinstance(sid, str):
                    ids.add(sid)
            except json.JSONDecodeError:
                continue
    return ids


def _load_payload(filename: str) -> dict:
    """Load a JSON payload file from this onboarding directory."""
    path = _PAYLOAD_DIR / filename
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


async def ensure_vendor_risk_systems() -> dict[str, str]:
    """Submit intake for both vendor_risk systems if absent.

    Returns a dict mapping system_id -> 'created' | 'exists' | 'failed:<reason>'
    so the lifespan logger can report a clear summary line. Never raises —
    bootstrap failures must not kill engine startup (per the seed_agents
    pattern already in dashboard.py).
    """
    # Lazy import: api.intake imports a lot; defer until lifespan call.
    from api.intake import IntakePayload, submit_intake

    existing = _existing_system_ids()
    results: dict[str, str] = {}

    for system_id, payload_filename in _SYSTEMS:
        if system_id in existing:
            results[system_id] = "exists"
            _log.info(f"[vendor_risk bootstrap] {system_id} already present — skipping")
            continue

        try:
            payload_dict = _load_payload(payload_filename)
            payload = IntakePayload.model_validate(payload_dict)
            out = await submit_intake(payload, system_id_override=system_id)
            results[system_id] = "created"
            _log.info(
                f"[vendor_risk bootstrap] {system_id} created — "
                f"assessment={out.assessment_id} gates={out.gate_count} "
                f"risk={out.inherent_risk} status={out.status}"
            )
            if out.status == "draft":
                _log.warning(
                    f"[vendor_risk bootstrap] {system_id} landed as DRAFT — "
                    f"reason: {out.draft_reason}"
                )
        except Exception as exc:  # noqa: BLE001 — bootstrap must never kill startup
            reason = f"{type(exc).__name__}: {exc}"
            results[system_id] = f"failed:{reason}"
            _log.exception(f"[vendor_risk bootstrap] {system_id} failed to create")

    return results
