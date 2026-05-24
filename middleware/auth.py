"""Session-cookie auth gate with 10-minute sliding inactivity timeout + usage logging.

Local dev: middleware is disabled when AUTH_ENABLED is unset or "false".
Prod (App Service): set AUTH_ENABLED=true plus DEMO_USER_<ROLE>_HASH app settings.

Sessions are server-side (data/usage_sessions.jsonl). Cookie carries only the
signed session_id. Each authenticated request bumps last_activity. If idle >
10 minutes, the session is killed and the user is redirected to /login.
"""

from __future__ import annotations

import os
import secrets
from typing import Callable

import bcrypt
from itsdangerous import BadSignature, URLSafeTimedSerializer
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from domain import usage_analytics as ua


SESSION_COOKIE = "aigovern_session"
SESSION_MAX_AGE = ua.INACTIVITY_TIMEOUT_S  # 10 min sliding

PUBLIC_PREFIXES = (
    "/login",
    "/api/auth/login",
    "/api/auth/logout",
    "/api/health",
    "/static/",
    "/favicon.ico",
    "/api/sdk/",  # SDK paths are authenticated by HMACAuthMiddleware, not session cookies
)

ROLES = ("CRO", "CISO", "AUDIT", "MRM", "AIGOV", "OPERATOR")
# OPERATOR added in Session 11 for the Demo Control panel. Provision
# DEMO_USER_OPERATOR_HASH to permit `demo-operator` logins in prod.


def _is_enabled() -> bool:
    return os.getenv("AUTH_ENABLED", "false").strip().lower() in ("1", "true", "yes")


def _serializer() -> URLSafeTimedSerializer:
    secret = os.getenv("SESSION_SECRET")
    if not secret:
        raise RuntimeError("SESSION_SECRET app setting is required when AUTH_ENABLED=true")
    return URLSafeTimedSerializer(secret, salt="aigovern-session-v1")


def _user_hashes() -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for role in ROLES:
        h = os.getenv(f"DEMO_USER_{role}_HASH", "").strip()
        if h:
            out[f"demo-{role.lower()}"] = h.encode("utf-8")
    return out


def _verify(username: str, password: str) -> str | None:
    hashes = _user_hashes()
    h = hashes.get(username.strip().lower())
    if not h:
        return None
    try:
        if bcrypt.checkpw(password.encode("utf-8"), h):
            return username.strip().lower()
    except ValueError:
        return None
    return None


def _read_cookie(request: Request) -> dict | None:
    """Validate the signed cookie. Returns the payload dict or None."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    try:
        data = _serializer().loads(token, max_age=SESSION_MAX_AGE)
    except BadSignature:
        return None
    return data if isinstance(data, dict) else None


def _ip_and_ua(request: Request) -> tuple[str, str]:
    headers = {k.lower(): v for k, v in request.headers.items()}
    ip = ua.client_ip_from_headers(headers)
    if not ip and request.client:
        ip = request.client.host or ""
    return ip, headers.get("user-agent", "")


def _cookie_domain() -> str | None:
    """Optional parent-domain attribute for cross-subdomain SSO.

    Unset → host-only cookie (V1 single-host behaviour, unchanged).
    Set to e.g. ".aigovern.sandboxhub.co" → portal.* and gov.* share the session.
    """
    d = os.getenv("SESSION_COOKIE_DOMAIN", "").strip()
    return d or None


def _set_session_cookie(resp, token: str) -> None:
    kwargs: dict = dict(
        max_age=SESSION_MAX_AGE,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )
    domain = _cookie_domain()
    if domain:
        kwargs["domain"] = domain
    resp.set_cookie(SESSION_COOKIE, token, **kwargs)


class SessionAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable):
        if not _is_enabled():
            return await call_next(request)

        path = request.url.path
        if any(path == p or path.startswith(p) for p in PUBLIC_PREFIXES):
            return await call_next(request)

        payload = _read_cookie(request)
        sid = (payload or {}).get("sid")
        user = (payload or {}).get("u")

        # No valid cookie OR server-side session expired -> reject.
        # Do NOT call session_end() here — under multi-worker setups the session
        # may exist in another worker's memory; let it expire naturally.
        if not sid or not user or not ua.is_session_active(sid):
            if path.startswith("/api/"):
                return JSONResponse({"error": "unauthorized"}, status_code=401)
            return RedirectResponse(url=f"/login?next={path}", status_code=302)

        # Authenticated request — bump activity + log page view
        ua.session_touch(sid)
        ip, agent = _ip_and_ua(request)
        if request.method == "GET" and not path.startswith("/api/"):
            ua.log_event("PAGE_VIEW", user=user, session_id=sid,
                         ip=ip, user_agent=agent, path=path)
        elif path.startswith("/api/"):
            ua.log_event("API_CALL", user=user, session_id=sid,
                         ip=ip, user_agent=agent, path=path)

        response = await call_next(request)
        # Sliding cookie — refresh expiry on every successful authed request
        new_token = _serializer().dumps({"u": user, "sid": sid})
        _set_session_cookie(response, new_token)
        return response


router = APIRouter(tags=["auth"])


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    from pathlib import Path
    html = (Path(__file__).resolve().parent.parent / "static" / "login.html").read_text(encoding="utf-8")
    return HTMLResponse(content=html)


@router.post("/api/auth/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form("/"),
):
    if not _is_enabled():
        return JSONResponse({"error": "auth_disabled"}, status_code=400)

    user = _verify(username, password)
    ip, agent = _ip_and_ua(request)
    if not user:
        ua.log_event("LOGIN_FAILED", user=username.strip().lower()[:32], session_id="",
                     ip=ip, user_agent=agent)
        return JSONResponse({"error": "invalid_credentials"}, status_code=401)

    sid = secrets.token_urlsafe(24)
    ua.session_start(sid, user=user, ip=ip, user_agent=agent)
    ua.log_event("LOGIN", user=user, session_id=sid, ip=ip, user_agent=agent)

    token = _serializer().dumps({"u": user, "sid": sid})
    target = next if next.startswith("/") else "/"
    resp = JSONResponse({"ok": True, "user": user, "next": target})
    _set_session_cookie(resp, token)
    return resp


@router.post("/api/auth/logout")
async def logout(request: Request):
    payload = _read_cookie(request)
    if payload and payload.get("sid"):
        sid = payload["sid"]
        ip, agent = _ip_and_ua(request)
        ua.log_event("LOGOUT", user=payload.get("u", ""), session_id=sid,
                     ip=ip, user_agent=agent)
        ua.session_end(sid)
    resp = JSONResponse({"ok": True})
    # Must mirror the domain= used at set time, or the browser keeps the
    # parent-domain cookie alive across subdomains after logout.
    domain = _cookie_domain()
    if domain:
        resp.delete_cookie(SESSION_COOKIE, path="/", domain=domain)
    else:
        resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp


# ---------------------------------------------------------------------------
# RBAC dependency factory
# ---------------------------------------------------------------------------

from fastapi import HTTPException  # noqa: E402 -- after router definition


def require_role(*allowed_roles: str):
    """Return a FastAPI dependency that enforces role-based access control.

    When ``AUTH_ENABLED=false`` (dev mode) the check is skipped and the
    dependency returns ``None`` so tests do not need credentials.

    The role is read from the ``X-Role`` header (test/SDK path) or from the
    signed session cookie (browser path, when AUTH_ENABLED=true).

    Args:
        *allowed_roles: One or more role names that are permitted.
                        The check is case-insensitive.

    Returns:
        A FastAPI dependency callable.  Raises HTTP 403 when the caller's role
        is absent or not in *allowed_roles*.

    Example::

        @router.get("/api/audit/events")
        async def list_events(
            _role: None = Depends(require_role("auditor", "ciso")),
        ) -> ...:
            ...
    """
    if not allowed_roles:
        raise ValueError(
            "require_role() must be called with at least one role. "
            "Empty allowed_roles short-circuits the dev-mode check, opening access."
        )
    allowed = frozenset(r.lower() for r in allowed_roles)

    async def _check(request: Request) -> None:
        """Inner dependency -- enforces role membership."""
        if not _is_enabled():
            # AUTH_ENABLED=false: accept X-Role header for testing convenience.
            role_header = request.headers.get("X-Role", "").lower()
            if role_header and allowed and role_header not in allowed:
                raise HTTPException(
                    status_code=403,
                    detail="insufficient_role",
                )
            return

        # AUTH_ENABLED=true: role is embedded in session cookie.
        payload = _read_cookie(request)
        if not payload:
            raise HTTPException(status_code=401, detail="unauthorized")
        user: str = (payload.get("u") or "").lower()
        # Role is the suffix after "demo-" (e.g. "demo-ciso" -> "ciso").
        role = user.replace("demo-", "", 1)
        if role not in allowed:
            raise HTTPException(status_code=403, detail="insufficient_role")

    return _check


@router.get("/api/auth/whoami")
async def whoami(request: Request):
    if not _is_enabled():
        return {"auth": "disabled", "user": None, "is_ciso": False}
    payload = _read_cookie(request)
    sid = (payload or {}).get("sid")
    user = (payload or {}).get("u")
    if not sid or not user or not ua.is_session_active(sid):
        return JSONResponse({"error": "unauthorized", "is_ciso": False}, status_code=401)
    return {"user": user, "session_id": sid, "is_ciso": user == "demo-ciso"}
