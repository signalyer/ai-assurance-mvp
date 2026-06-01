"""SOP Phase 7 bootstrap — vendor_risk catalog row, SDK keys, status promotion.

Lifespan-invoked. All three responsibilities are co-located here because
they form one logical onboarding bundle: an agent that operators can
bind to a system needs (a) a `domain.agents` catalog entry, (b) an SDK
key per AI system it governs, and (c) those systems promoted out of
DESIGN so calibration runs can land against STAGED.

Idempotency:
    - Catalog row uses `create_agent` which is `ON CONFLICT DO NOTHING`.
    - SDK keys: `issue_key` always mints a new key, so we check
      `list_keys(ai_system_id=...)` first and skip if any active key exists.
    - Status promotion: `transition_runtime_status` returns a no-op error
      if the system is already at the destination status; we treat that
      as success.

Plaintext secret handling:
    SDK secrets are surfaced exactly once at issuance (the wizard UX
    referenced in `domain/sdk_keys.py`). For lifespan-minted keys there
    is no operator in the loop, so we persist the plaintext to
    `/home/.s82f-secrets-<system_id>.txt` with mode 0600. App Service's
    `/home/` is the only path that survives cold-start data wipes
    (per [[kudu-rest-faster-than-ssh]] and the deploy-zip rule). The
    operator pulls the file via `az webapp ssh` after deploy completes.
    Never log the secret — see `domain.sdk_keys` invariants.

Per docs/SOP-agent-onboarding.md Phase 7. The promotion to STAGED uses
the synthetic "system:bootstrap" actor — a documented first-class value
used only by lifespan bootstraps (NOT a back door). See
`domain.ai_system_edit.transition_runtime_status`.
"""
from __future__ import annotations

import logging
import os
import stat
from pathlib import Path
from typing import Final

_log = logging.getLogger(__name__)


# The catalog-row spec for vendor_risk. Kept here (rather than in
# `domain.agents._SEED_AGENTS`) so the SOP onboarding bundle for an agent
# lives as a single co-located module — easier to find, easier to extract
# into per-agent packages later.
_VENDOR_RISK_AGENT_ID: Final[str] = "vendor_risk"
_VENDOR_RISK_NAME: Final[str] = "Vendor Risk Analyzer"
_VENDOR_RISK_DESCRIPTION: Final[str] = (
    "Third-party vendor risk assessment for TPRM onboarding. Parses "
    "vendor-disclosed documents, retrieves grounding from the TPRM "
    "policy + regulatory corpus, and produces a structured risk tier "
    "with concerns, conflicts, mitigations, and citations."
)
_VENDOR_RISK_TEAM: Final[str] = "risk"
_VENDOR_RISK_FRAMEWORK_REFS: Final[list[str]] = [
    "NIST_AI_RMF:GOVERN-6.1",
    "EU_AI_ACT:Art.16",
]

# Systems this agent governs. Matches the ids seeded by `bootstrap.py`.
_GOVERNED_SYSTEMS: Final[tuple[str, ...]] = (
    "sys-vendor-risk-ext-001",
    "sys-vendor-risk-int-001",
)

# Bootstrap reason recorded on every RUNTIME_STATUS_CHANGED event we emit.
# Self-documenting in the audit log — future readers can grep this string
# to find every transition this module made.
_BOOTSTRAP_REASON: Final[str] = (
    "vendor_risk SOP Phase 7 bootstrap — 25 STAGED calibration runs (S82f)"
)
_BOOTSTRAP_ACTOR: Final[str] = "system:bootstrap"

# App Service /home survives cold starts; everything else is wiped.
_SECRETS_DIR: Final[Path] = Path(os.environ.get("VENDOR_RISK_SECRETS_DIR") or "/home")


def _write_plaintext_secret(system_id: str, key_id: str, plaintext: str) -> Path:
    """Persist a freshly-minted SDK secret to /home/ at 0600.

    Returns the path so the lifespan logger can surface it. Never logs the
    secret itself — only the path.
    """
    target = _SECRETS_DIR / f".s82f-secrets-{system_id}.txt"
    body = (
        f"# vendor_risk SDK key for {system_id}\n"
        f"# minted by sdk_provisioning lifespan bootstrap (S82f)\n"
        f"# DO NOT COMMIT — pull via `az webapp ssh` then delete\n"
        f"SL_KEY_ID={key_id}\n"
        f"SL_HMAC_SECRET={plaintext}\n"
    )
    # Write then chmod (Windows dev environments will silently no-op the chmod;
    # production target is Linux App Service where 0600 is enforced).
    target.write_text(body, encoding="utf-8")
    try:
        os.chmod(target, stat.S_IRUSR | stat.S_IWUSR)
    except (PermissionError, OSError):  # noqa: BLE001 — non-fatal on Windows
        _log.debug("chmod 0600 failed on %s (non-Linux fs?)", target)
    return target


def _ensure_catalog_row() -> str:
    """Insert the vendor_risk row into `domain.agents` if absent.

    Returns 'created' | 'exists' | 'failed:<reason>'. `create_agent` uses
    `ON CONFLICT (id) DO NOTHING` so a duplicate call is safe — we still
    bracket with try/except because the no-Postgres fallback path stores
    in-memory and can raise on schema drift.
    """
    from domain.agents import create_agent, get_agent
    from domain.models import AgentOwnerType, RiskLevel

    existing = get_agent(_VENDOR_RISK_AGENT_ID)
    if existing is not None:
        return "exists"

    try:
        create_agent(
            name=_VENDOR_RISK_NAME,
            description=_VENDOR_RISK_DESCRIPTION,
            team=_VENDOR_RISK_TEAM,
            owner_type=AgentOwnerType.REUSABLE,
            inherent_risk=RiskLevel.HIGH,
            framework_refs=_VENDOR_RISK_FRAMEWORK_REFS,
            agent_id=_VENDOR_RISK_AGENT_ID,
        )
    except Exception as exc:  # noqa: BLE001
        return f"failed:{type(exc).__name__}: {exc}"
    return "created"


def _ensure_sdk_key(system_id: str) -> str:
    """Mint an SDK key for `system_id` if no active key exists.

    Returns 'created:<path>' | 'exists' | 'failed:<reason>'. Active = not
    revoked. A revoked key does not count toward idempotency — the system
    needs at least one usable key to receive SDK calls.
    """
    from domain.sdk_keys import issue_key, list_keys

    try:
        keys = list_keys(ai_system_id=system_id, include_revoked=False)
    except Exception as exc:  # noqa: BLE001
        return f"failed:list:{type(exc).__name__}: {exc}"
    if keys:
        return "exists"

    try:
        record, plaintext = issue_key(
            ai_system_id=system_id,
            data_source="real",
            issued_by=_BOOTSTRAP_ACTOR,
        )
    except Exception as exc:  # noqa: BLE001
        return f"failed:issue:{type(exc).__name__}: {exc}"

    try:
        path = _write_plaintext_secret(system_id, record.key_id, plaintext)
    except Exception as exc:  # noqa: BLE001
        # Key exists in the store; only the side-channel handoff failed.
        # Surface this honestly — operator will need to revoke + re-mint.
        return f"failed:write_secret:{type(exc).__name__}: {exc}"
    return f"created:{path}"


def _promote_system(system_id: str) -> str:
    """Move `system_id` from DESIGN → STAGED.

    Returns 'promoted:<from>->STAGED' | 'noop:<current_status>' | 'failed:<reason>'.
    """
    from domain.ai_system_edit import promote_to_staged
    from domain.repository import get_ai_system

    sys_obj = get_ai_system(system_id)
    if sys_obj is None:
        return f"failed:system_not_found"
    if sys_obj.runtime_status.value == "STAGED":
        return "noop:STAGED"

    # IMPORTANT: pass base_status from the JSONL record (not the folded
    # value). The fold result IS the base for new transitions because we
    # already applied prior lifecycle events to it via get_ai_system. So
    # `current_runtime_status` inside `transition_runtime_status` will
    # double-apply unless we hand it the BASE. Read the raw intake record:
    from domain.repository import _read_jsonl, SYSTEMS_FILE
    from domain import seed
    base_status_str = sys_obj.runtime_status.value  # default
    for s in seed.AI_SYSTEMS:
        if s.id == system_id:
            base_status_str = s.runtime_status.value
            break
    else:
        for r in _read_jsonl(SYSTEMS_FILE):
            if r.get("id") == system_id:
                base_status_str = r.get("runtime_status", base_status_str)
                break

    event, errors = promote_to_staged(
        ai_system_id=system_id,
        base_status=base_status_str,
        actor=_BOOTSTRAP_ACTOR,
        reason=_BOOTSTRAP_REASON,
    )
    if errors:
        # "no-op: already STAGED" is a normal idempotent outcome.
        if any("no-op" in e for e in errors):
            return "noop:already_staged"
        return f"failed:{';'.join(errors)}"
    return f"promoted:{event.get('from_status')}->STAGED"


async def ensure_vendor_risk_provisioning() -> dict[str, str | dict[str, str]]:
    """Catalog + SDK keys + status promotion for vendor_risk.

    Called from `dashboard.py` lifespan AFTER `ensure_vendor_risk_systems()`
    (which creates the AISystem rows this depends on). Never raises —
    bootstrap failures must never kill engine startup.

    Returns a summary dict the lifespan logger can dump verbatim.
    """
    summary: dict[str, str | dict[str, str]] = {}

    summary["catalog"] = _ensure_catalog_row()
    _log.info("[vendor_risk provisioning] catalog=%s", summary["catalog"])

    keys: dict[str, str] = {}
    promotions: dict[str, str] = {}
    for sid in _GOVERNED_SYSTEMS:
        keys[sid] = _ensure_sdk_key(sid)
        # Promotion happens regardless of key-mint outcome — they're
        # independent invariants (a system can be STAGED without keys
        # if minting fails; the operator can re-run after fixing).
        promotions[sid] = _promote_system(sid)
        _log.info(
            "[vendor_risk provisioning] %s key=%s promote=%s",
            sid, keys[sid], promotions[sid],
        )

    summary["sdk_keys"] = keys
    summary["promotions"] = promotions
    return summary
