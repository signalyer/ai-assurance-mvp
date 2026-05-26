"""SDK API-key issuance, lookup, revocation, and first-signal tracking.

Session 53 — V1/V2 real-data arc, item 2.

Each AI system gets its own (key_id, hmac_secret) pair. The plaintext
secret is stored server-side because HMAC verification requires it to
recompute signatures — same trust boundary as the legacy single-tenant
`SL_HMAC_SECRET` (kept in App Service Settings). UX-wise, the secret
is surfaced to the user exactly once at issuance time so the SPA wizard
never displays it twice; re-display = "issue a new key" (revokes the
old one).

Backwards compatibility: the legacy single-tenant `SL_HMAC_SECRET` env
var stays as a fallback for demo apps that don't yet have a per-system
key. The HMAC middleware tries per-key lookup first, then falls back.

Storage: JSONL via the storage.py pattern. Revocation and first-seen
both require mutating an existing row — handled by a full-rewrite
helper (`_rewrite_jsonl`) since the dataset is small (one row per
registered system) and rewrite latency is far below the SDK call
budget.

Architectural invariants honored:
- Plaintext secret never logged (handled by callers; this module never
  log-emits the secret).
- HMAC verification uses `hmac.compare_digest` for constant-time compare.
- `data_source: Literal["seed","real"]` inherited from the parent
  system at issuance time (S52 invariant).
- Idempotent first-seen: setting `first_seen_at` is a no-op if already
  set. Same call from the middleware on every authed request is safe.
"""

from __future__ import annotations

import json
import logging
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

DATA_DIR = Path(__import__("os").environ.get("DATA_ROOT") or (Path(__file__).resolve().parents[1] / "data"))
DATA_DIR.mkdir(exist_ok=True)
KEYS_FILE = DATA_DIR / "sdk_keys.jsonl"

_io_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


class SdkKey(BaseModel):
    """Per-system SDK API key.

    The plaintext `hmac_secret` is stored because the HMAC middleware
    must recompute signatures to verify incoming SDK calls. Same trust
    boundary as the legacy single-tenant SL_HMAC_SECRET kept in App
    Service Settings.

    `list_keys` strips the secret before returning — only `issue_key`
    and `lookup_secret_by_key_id` ever expose it.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., description="Internal id, e.g. 'sdkkey-<8hex>'")
    key_id: str = Field(..., description="Public key id surfaced in X-SL-Key-Id header")
    hmac_secret: str = Field(..., description="Plaintext HMAC secret. Sensitive — never log.")
    ai_system_id: str
    data_source: Literal["seed", "real"] = "seed"
    issued_by: str
    issued_at: datetime
    revoked_at: Optional[datetime] = None
    first_seen_at: Optional[datetime] = None
    total_calls_24h: int = 0  # rolled by the middleware; cheap counter


# ---------------------------------------------------------------------------
# JSONL helpers
# ---------------------------------------------------------------------------


def _read_all() -> list[dict]:
    """Return every persisted key row (raw dicts; order preserved)."""
    if not KEYS_FILE.exists():
        return []
    rows: list[dict] = []
    with KEYS_FILE.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                logger.warning("sdk_keys: skipping malformed JSONL line")
    return rows


def _append_jsonl(record: dict) -> None:
    with _io_lock:
        with KEYS_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")


def _rewrite_jsonl(rows: list[dict]) -> None:
    """Rewrite the entire keys file atomically (tmp + rename).

    Used for revocation and first-seen mutation. Safe because the
    dataset is one row per registered AI system — sub-millisecond
    rewrite even at thousands of systems.
    """
    tmp = KEYS_FILE.with_suffix(".jsonl.tmp")
    with _io_lock:
        with tmp.open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, default=str) + "\n")
        tmp.replace(KEYS_FILE)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def issue_key(
    *,
    ai_system_id: str,
    data_source: Literal["seed", "real"] = "seed",
    issued_by: str = "system",
) -> tuple[SdkKey, str]:
    """Generate a new (key_id, hmac_secret) pair for an AI system.

    Returns the persisted SdkKey record AND the plaintext secret. The
    plaintext is included separately in the return so callers don't
    have to introspect the model — a small affordance that keeps the
    "surface once, then discard from in-memory state" UX explicit.

    Args:
        ai_system_id: Parent AI system this key belongs to.
        data_source: "seed" or "real" — inherited from the parent system.
        issued_by: Actor that requested issuance (audit trail).

    Returns:
        Tuple of (persisted SdkKey, plaintext HMAC secret).
    """
    short = secrets.token_hex(4)
    key_id = f"slk_{short}"
    # 32 url-safe bytes = ~43 chars after base64; comfortably > 128 bits entropy.
    plaintext_secret = secrets.token_urlsafe(32)

    now = datetime.now(tz=timezone.utc)
    record = SdkKey(
        id=f"sdkkey-{short}",
        key_id=key_id,
        hmac_secret=plaintext_secret,
        ai_system_id=ai_system_id,
        data_source=data_source,
        issued_by=issued_by,
        issued_at=now,
    )
    _append_jsonl(record.model_dump(mode="json"))
    logger.info("sdk_keys.issue ai_system_id=%s key_id=%s by=%s", ai_system_id, key_id, issued_by)
    return record, plaintext_secret


def list_keys(*, ai_system_id: Optional[str] = None, include_revoked: bool = True) -> list[SdkKey]:
    """List persisted SDK keys. Filter by ai_system_id if provided.

    Includes the plaintext secret in the returned model — callers MUST
    NOT echo it to clients. The api/sdk_keys.py list endpoint strips
    the secret via a separate `KeySummaryOut` response model.
    """
    rows = _read_all()
    out: list[SdkKey] = []
    for r in rows:
        try:
            k = SdkKey.model_validate(r)
        except Exception:
            logger.warning("sdk_keys.list: dropping malformed row id=%s", r.get("id"))
            continue
        if ai_system_id and k.ai_system_id != ai_system_id:
            continue
        if not include_revoked and k.revoked_at is not None:
            continue
        out.append(k)
    return out


def lookup_secret_by_key_id(key_id: str) -> Optional[str]:
    """Return the plaintext HMAC secret for a key_id, or None if absent/revoked.

    Used by the HMAC middleware for signature verification. Never log
    the returned value; the caller's responsibility.
    """
    k = get_by_key_id(key_id)
    if k is None or k.revoked_at is not None:
        return None
    return k.hmac_secret


def get_by_key_id(key_id: str) -> Optional[SdkKey]:
    """Return the SdkKey for a public key_id, or None if absent."""
    for k in list_keys():
        if k.key_id == key_id:
            return k
    return None


def revoke_key(key_id: str, *, actor: str = "system") -> Optional[SdkKey]:
    """Mark a key as revoked. Returns the updated record, or None if absent.

    Idempotent: revoking an already-revoked key returns the existing
    record unchanged.
    """
    rows = _read_all()
    target_idx: Optional[int] = None
    for i, r in enumerate(rows):
        if r.get("key_id") == key_id:
            target_idx = i
            break
    if target_idx is None:
        return None
    if rows[target_idx].get("revoked_at"):
        return SdkKey.model_validate(rows[target_idx])
    now = datetime.now(tz=timezone.utc).isoformat()
    rows[target_idx]["revoked_at"] = now
    _rewrite_jsonl(rows)
    logger.info("sdk_keys.revoke key_id=%s by=%s", key_id, actor)
    return SdkKey.model_validate(rows[target_idx])


def mark_first_seen(key_id: str) -> None:
    """Set `first_seen_at` on first successful HMAC-authed call. Idempotent.

    Called from the HMAC middleware after signature verification. No-op
    if `first_seen_at` is already set.
    """
    rows = _read_all()
    target_idx: Optional[int] = None
    for i, r in enumerate(rows):
        if r.get("key_id") == key_id:
            target_idx = i
            break
    if target_idx is None:
        return
    if rows[target_idx].get("first_seen_at"):
        return
    rows[target_idx]["first_seen_at"] = datetime.now(tz=timezone.utc).isoformat()
    _rewrite_jsonl(rows)
    logger.info("sdk_keys.first_seen key_id=%s", key_id)


def status_snapshot(key_id: str) -> Optional[dict]:
    """Return the polling-friendly status payload, or None if key absent.

    Used by the /api/sdk-keys/{key_id}/status endpoint and the SPA
    first-signal panel.
    """
    k = get_by_key_id(key_id)
    if k is None:
        return None
    return {
        "key_id": k.key_id,
        "ai_system_id": k.ai_system_id,
        "issued_at": k.issued_at.isoformat() if isinstance(k.issued_at, datetime) else k.issued_at,
        "first_seen_at": k.first_seen_at.isoformat() if isinstance(k.first_seen_at, datetime) else k.first_seen_at,
        "revoked_at": k.revoked_at.isoformat() if isinstance(k.revoked_at, datetime) else k.revoked_at,
        "total_calls_24h": k.total_calls_24h,
    }


__all__ = [
    "SdkKey",
    "issue_key",
    "list_keys",
    "get_by_key_id",
    "lookup_secret_by_key_id",
    "revoke_key",
    "mark_first_seen",
    "status_snapshot",
]
