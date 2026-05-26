"""Microsoft Entra OIDC login + callback endpoints (ADR-002, S49).

Two routes:

    GET /auth/oidc/login?next=<deep-link>
        Redirects the browser to Entra's authorize endpoint. The `next`
        deep-link is stashed in the short-lived Starlette session cookie
        so the callback can honour it.

    GET /auth/oidc/callback
        Entra redirects here after the user authenticates. We exchange the
        authorization code for tokens, resolve the user's group membership
        to an engine role, and issue the same `aigovern_session` cookie
        the bcrypt path issues — invariant per ADR-002 §4.

This module intentionally imports private helpers from `middleware.auth`
(`_serializer`, `_set_session_cookie`, `_default_target_for_user`,
`_ip_and_ua`). Reusing them is the load-bearing claim of ADR-002: OIDC and
bcrypt issue identical cookie payloads. Duplicating the helpers here would
defeat that invariance.
"""

from __future__ import annotations

import logging
import secrets
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from domain import usage_analytics as ua
from middleware import oidc as oidc_mod
from middleware.auth import (
    _default_target_for_user,
    _ip_and_ua,
    _serializer,
    _set_session_cookie,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["auth"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _callback_redirect_uri(request: Request) -> str:
    """Compute the absolute redirect URI for the Entra callback.

    Must exactly match the redirect URI registered in the Entra app
    registration. We construct it from `request.url_for` so the scheme +
    host + path are all consistent with how the engine is being reached
    (handles localhost dev and the prod custom domain identically).
    """
    return str(request.url_for("oidc_callback"))


def _safe_next(value: str | None) -> str | None:
    """Return `value` if it is a safe relative path, else None.

    Mirrors the existing check in `middleware.auth.login_submit` —
    the deep-link target must start with "/" so an attacker cannot
    pass an absolute URL to a different host. None means "fall back to
    role-derived default".
    """
    if not value:
        return None
    return value if value.startswith("/") else None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/auth/oidc/login", name="oidc_login")
async def oidc_login(request: Request, next: str | None = None):
    """Kick off the OIDC authorization-code flow.

    Stashes a sanitised `next` deep-link in the Starlette session (a
    short-lived cookie used only for the redirect roundtrip; NOT the
    long-lived `aigovern_session` cookie) and 302s to Entra.

    authlib handles state + nonce + PKCE generation; we don't reinvent it.
    """
    safe = _safe_next(next)
    if safe:
        request.session["oidc_next"] = safe
    else:
        # Explicit clear so a stale value from a prior aborted login doesn't
        # bleed into this one.
        request.session.pop("oidc_next", None)

    redirect_uri = _callback_redirect_uri(request)
    client = oidc_mod.oauth_client()
    return await client.authorize_redirect(request, redirect_uri)


@router.get("/auth/oidc/callback", name="oidc_callback")
async def oidc_callback(request: Request):
    """Complete the OIDC flow: exchange code → resolve role → issue cookie."""
    client = oidc_mod.oauth_client()

    # authlib raises on state/nonce mismatch, expired code, network errors,
    # etc. We catch broadly and surface a denial page rather than 500 —
    # the user's browser is on this URL, they need to see *something*.
    try:
        token = await client.authorize_access_token(request)
    except Exception as exc:  # noqa: BLE001 — broad on purpose, see above
        logger.warning("OIDC token exchange failed: %s", exc)
        return _denial_response(
            "Sign-in did not complete. Please try again. "
            "If the problem persists, contact your administrator.",
        )

    claims: dict[str, Any] = token.get("userinfo") or {}
    if not claims:
        # Fall back to parsing the id_token directly if userinfo wasn't
        # populated. authlib usually fills `userinfo` from the id_token
        # when the `openid` scope is granted; defensive belt-and-braces.
        claims = token.get("id_token_claims") or {}

    if oidc_mod.is_group_overage(claims):
        upn_for_log = claims.get("preferred_username") or claims.get("upn") or "<unknown>"
        logger.warning(
            "OIDC group overage for user=%s — denying (Graph lookup not implemented)",
            upn_for_log,
        )
        return _denial_response(
            "Your account belongs to too many directory groups for this "
            "system to evaluate access. Contact your administrator.",
        )

    try:
        upn = oidc_mod.extract_upn_from_claims(claims)
    except ValueError as exc:
        logger.warning("OIDC missing UPN claim: %s", exc)
        return _denial_response(
            "Sign-in succeeded but the directory did not return a usable "
            "username. Contact your administrator.",
        )

    group_oids = [g for g in (claims.get("groups") or []) if isinstance(g, str)]
    role = oidc_mod.resolve_role_from_groups(group_oids)

    ip, agent = _ip_and_ua(request)

    if role is None:
        ua.log_event(
            "LOGIN_DENIED_NO_GROUP",
            user=upn[:64],
            session_id="",
            ip=ip,
            user_agent=agent,
        )
        logger.info("OIDC denial — no portal group: user=%s groups=%d", upn, len(group_oids))
        return _denial_response(
            "Your account is not provisioned for access. Ask your "
            "administrator to add you to the AI Governance CISO Console "
            "or Team Portal security group.",
        )

    # --- Issue the engine session cookie ---------------------------------
    # Shape mirrors `middleware.auth.login_submit` exactly except `u` is
    # the real UPN (not `demo-<role>`) and `r` is always set.
    sid = secrets.token_urlsafe(24)
    ua.session_start(sid, user=upn, ip=ip, user_agent=agent)
    ua.log_event("LOGIN", user=upn, session_id=sid, ip=ip, user_agent=agent)
    logger.info("OIDC login: user=%s role=%s sid=%s", upn, role, sid[:8])

    token_str = _serializer().dumps({"u": upn, "sid": sid, "r": role})

    # Determine landing URL: honour the saved `next` deep-link if present,
    # else fall back to the role-derived default.
    saved_next = request.session.pop("oidc_next", None)
    target = _safe_next(saved_next) or _default_target_for_user(role)

    response = RedirectResponse(url=target, status_code=302)
    _set_session_cookie(response, token_str)
    return response


# ---------------------------------------------------------------------------
# Denial page
# ---------------------------------------------------------------------------
# Rendered when an OIDC sign-in succeeded at Entra but failed our engine-side
# checks (no portal group, group overage, missing claims). We deliberately
# do NOT redirect to /login — that would imply "try the password form" which
# in prod is gated off (ALLOW_DEMO_AUTH=false). A static HTML page is the
# honest answer.


_DENIAL_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>Access not provisioned — AI Governance</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
                Roboto, sans-serif; max-width: 560px; margin: 6rem auto;
                padding: 0 1.5rem; color: #1f2937; line-height: 1.55; }}
        h1   {{ font-size: 1.4rem; margin-bottom: 0.5rem; }}
        p    {{ color: #4b5563; }}
        .id  {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
                font-size: 0.85rem; color: #6b7280; margin-top: 2rem; }}
    </style>
</head>
<body>
    <h1>Access not provisioned</h1>
    <p>{message}</p>
    <p class="id">If you contact support, mention reference: {ref}</p>
</body>
</html>
"""


def _denial_response(message: str) -> HTMLResponse:
    """Render a 403 HTML page explaining the denial.

    Uses an ephemeral reference token (not stored) so a user reporting the
    issue gives the operator something to grep the logs for, without us
    needing a persistent denial table.
    """
    ref = secrets.token_urlsafe(8)
    logger.info("OIDC denial reference: %s", ref)
    html = _DENIAL_HTML_TEMPLATE.format(message=message, ref=ref)
    return HTMLResponse(content=html, status_code=403)
