"""Microsoft Entra OIDC bridge (engine-level, ADR-002).

Authenticates users against the signallayer.ai Entra tenant and resolves
their security-group membership to one of two engine roles:

    - "ciso"     (group: aigovern-ciso-console) → lands on gov.aigovern.sandboxhub.co
    - "engineer" (group: aigovern-team-portal)  → lands on portal.aigovern.sandboxhub.co

Sub-roles (audit/mrm/cro/operator/aigov) are NOT issued in prod sessions per
ADR-002 §4. The 7-role engine machinery (`require_role`) still exists and
"ciso" remains in its allowlists; we simply never grant the others via OIDC.

This module is **pure helpers**. The route handlers (`/auth/oidc/login` and
`/auth/oidc/callback`) live in `api/auth_oidc.py` to keep concerns separate.

Configuration (env vars, all required when OIDC is in use):
    OIDC_TENANT_ID                  Entra tenant GUID (signallayer.ai)
    OIDC_CLIENT_ID                  App registration GUID
    OIDC_CLIENT_SECRET              Client secret (sourced from Key Vault
                                    via App Service KV reference syntax)
    OIDC_CISO_CONSOLE_GROUP_OID     Object ID of `aigovern-ciso-console`
    OIDC_TEAM_PORTAL_GROUP_OID      Object ID of `aigovern-team-portal`

Failure policy: fail-loudly. Missing env vars raise RuntimeError at first
use (via `_oauth_client()`); silent defaulting would mask misconfiguration.

See:
    docs/adr/ADR-002-entra-oidc.md
    docs/plans/SESSION-49-entra-oidc-engine.md
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Any

logger = logging.getLogger(__name__)

# Microsoft v2.0 OIDC discovery endpoint template. Tenant ID is interpolated
# at registration time so the issuer + JWKs URIs are tenant-scoped.
_DISCOVERY_URL_TEMPLATE = (
    "https://login.microsoftonline.com/{tenant_id}/v2.0/.well-known/"
    "openid-configuration"
)

# OIDC scopes. `openid` is required; `email` + `profile` populate
# `preferred_username` / `email` / `name` claims in the ID token. We do NOT
# request any Microsoft Graph scopes — group resolution comes from the
# `groups` claim, not from a Graph call (ADR-002 §4 "we do not call Graph").
_SCOPES = "openid email profile"


# ---------------------------------------------------------------------------
# Env-driven configuration helpers
# ---------------------------------------------------------------------------
# Pattern mirrors `_user_hashes()` in middleware/auth.py — read env on demand
# so tests can monkeypatch.setenv without import-order gymnastics.


def _required_env(name: str) -> str:
    """Return the env var or raise RuntimeError naming the missing variable.

    Mirrors the global CLAUDE.md "fail loudly with: Missing required
    environment variable: <NAME>" convention.
    """
    val = os.getenv(name, "").strip()
    if not val:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return val


def _group_role_map() -> dict[str, str]:
    """Build the {group-OID → role} map from env.

    Returns a fresh dict per call; both OIDs must be set. We log the mapping
    with OID values masked to the last 6 characters so an operator can audit
    that the right groups are wired without leaking the full OIDs to logs.
    """
    ciso_oid = _required_env("OIDC_CISO_CONSOLE_GROUP_OID")
    team_oid = _required_env("OIDC_TEAM_PORTAL_GROUP_OID")
    mapping = {ciso_oid: "ciso", team_oid: "engineer"}
    logger.debug(
        "OIDC group map: ciso=…%s engineer=…%s",
        ciso_oid[-6:], team_oid[-6:],
    )
    return mapping


def _mask_oid(oid: str) -> str:
    """Return the last 6 chars of an OID for audit logging (never the full value)."""
    return f"…{oid[-6:]}" if len(oid) > 6 else "…"


# ---------------------------------------------------------------------------
# authlib client (lazy / cached)
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _oauth_registry() -> Any:
    """Return the process-wide authlib OAuth registry with Entra registered.

    Cached because authlib's OAuth() instance holds the registered client
    config; rebuilding it per request would re-parse the discovery doc.

    Raises RuntimeError if any required env var is missing — this is the
    fail-loudly point. Callers (the OIDC route handlers) should let the
    exception propagate; the dashboard process should NOT start serving OIDC
    routes if Entra is mis-configured.
    """
    # Lazy import — authlib is only on the OIDC code path; importing it at
    # module load would drag it into every dashboard startup even when
    # ALLOW_DEMO_AUTH=true and OIDC is unused.
    from authlib.integrations.starlette_client import OAuth  # type: ignore[import-untyped]

    tenant_id = _required_env("OIDC_TENANT_ID")
    client_id = _required_env("OIDC_CLIENT_ID")
    client_secret = _required_env("OIDC_CLIENT_SECRET")

    oauth = OAuth()
    oauth.register(
        name="entra",
        client_id=client_id,
        client_secret=client_secret,
        server_metadata_url=_DISCOVERY_URL_TEMPLATE.format(tenant_id=tenant_id),
        client_kwargs={"scope": _SCOPES, "prompt": "select_account"},
    )
    logger.info(
        "OIDC registered: tenant=%s client=%s",
        _mask_oid(tenant_id), _mask_oid(client_id),
    )
    return oauth


def oauth_client() -> Any:
    """Return the registered Entra OAuth2 client (`oauth.entra`).

    Public surface used by route handlers in `api/auth_oidc.py`. Exposed as
    a function (not a module-level attribute) to preserve laziness — env
    var validation only happens when OIDC is actually invoked.
    """
    return _oauth_registry().entra


def is_oidc_enabled() -> bool:
    """Return True iff the minimum env vars for OIDC are present.

    Used by `/api/auth/config` to tell the SPAs whether to render the
    "Sign in with Microsoft" CTA. Does NOT validate that the values are
    *correct* — only that they exist. A misconfigured tenant ID will still
    return True here; the actual OIDC handshake will fail at callback time.
    This is the right trade-off: we want the SPA to show the CTA even
    during pre-flight setup, not hide it because a typo slipped past.
    """
    return all(
        os.getenv(var, "").strip()
        for var in ("OIDC_TENANT_ID", "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET")
    )


# ---------------------------------------------------------------------------
# Claim → role / UPN resolution
# ---------------------------------------------------------------------------


def resolve_role_from_groups(group_oids: list[str]) -> str | None:
    """Resolve a list of Entra group OIDs to an engine role.

    Args:
        group_oids: The `groups` claim from the Entra ID token. Each entry
                    is a security-group object ID (GUID string).

    Returns:
        "ciso" if the user is in `aigovern-ciso-console` (wins ties even
            when also in `aigovern-team-portal` — higher-privilege landing).
        "engineer" if the user is in `aigovern-team-portal` only.
        None if the user is in neither group. Callers MUST treat None as
            access denial — no session cookie should be issued.

    Raises:
        RuntimeError: if the group-OID env vars are missing (propagated
                      from `_group_role_map()`). Better to 500 a denied
                      login than silently default everyone to "engineer".
    """
    mapping = _group_role_map()
    matched_roles = {mapping[oid] for oid in group_oids if oid in mapping}
    if "ciso" in matched_roles:
        return "ciso"
    if "engineer" in matched_roles:
        return "engineer"
    return None


def extract_upn_from_claims(claims: dict[str, Any]) -> str:
    """Extract the user-principal-name from an Entra ID-token claims dict.

    Entra emits the human-readable identifier in several possible fields
    depending on tenant configuration. We prefer in order:
        1. `preferred_username` — populated by the `profile` scope, this
           is the modern recommendation and matches what Entra shows the
           user in the sign-in UI.
        2. `upn` — legacy claim, still emitted for federated accounts.
        3. `email` — last resort; only present when the `email` scope is
           granted AND the account has a verified email address.

    Returns the value lowercased so the cookie payload is canonical for
    downstream comparisons. Raises ValueError if none of the three are
    present — that indicates a misconfigured Entra app and should fail
    the login rather than synthesise a fake UPN.
    """
    for key in ("preferred_username", "upn", "email"):
        val = claims.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip().lower()
    raise ValueError(
        "OIDC claims contained none of preferred_username/upn/email — "
        "check that the app registration grants 'profile' + 'email' scopes "
        "and that admin consent has been granted."
    )


def is_group_overage(claims: dict[str, Any]) -> bool:
    """Return True if the ID token signals group-claim overage (200+ groups).

    Entra omits the `groups` claim and emits `_claim_names` pointing to a
    Microsoft Graph endpoint when a user is in more than 200 groups. Per
    ADR-002 §4 we treat this as denial and log a warning — Graph lookup is
    deferred until a real user actually hits the cap.

    Detection: `_claim_names` exists AND maps `"groups"` to a source key.
    Any other use of `_claim_names` (e.g. for non-group claims, hypothetical
    future Entra behaviour) returns False — only the groups-overage case is
    relevant to our auth flow.
    """
    claim_names = claims.get("_claim_names")
    if not isinstance(claim_names, dict):
        return False
    return "groups" in claim_names


# ---------------------------------------------------------------------------
# Test seam (intentionally exposed)
# ---------------------------------------------------------------------------


def _reset_cache_for_tests() -> None:
    """Clear the lru_cache around `_oauth_registry`.

    Tests that monkeypatch OIDC_* env vars across test cases need a way to
    force the registry to be rebuilt with the new values. Production code
    never calls this. Underscored to flag it as a test seam.
    """
    _oauth_registry.cache_clear()
