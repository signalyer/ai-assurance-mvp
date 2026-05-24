"""URL-version alias middleware: /api/v1/* -> /api/*.

V2 SPAs (Team Workspace + CISO Console) and the signallayer SDK target
/api/v1/* as the published surface. V1 static HTML keeps using /api/*.
This middleware lets both paths reach the same handler set without
duplicating route declarations in OpenAPI (which would double Schemathesis
runtime and confuse codegen).

Per docs/plans/SESSION-13-api-typing-audit.md §1.5.

The alias is **incoming-only**: /api/v1/foo -> rewrites scope to /api/foo
before downstream routing. The original /api/foo is unchanged and is what
appears in /openapi.json (no v1 duplication). The published spec advertises
/api/v1/* via app.servers + the request path; that mismatch is documented
and accepted -- the cost of duplicated OpenAPI entries is higher than the
cost of a header-mismatch quirk during the V1 cutover window.

Removed in V2 Phase 5 (DNS cutover) once V1 static HTML is decommissioned.
"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_PREFIX = "/api/v1/"
_REPLACEMENT = "/api/"


class ApiVersionAliasMiddleware(BaseHTTPMiddleware):
    """Rewrites /api/v1/* paths to /api/* before downstream routing.

    Only the request scope is rewritten; the response is unchanged. The
    downstream handler sees /api/foo and is unaware of the alias. Tests
    in tests/test_api_version_alias.py assert response-body parity.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        if path.startswith(_PREFIX):
            new_path = _REPLACEMENT + path[len(_PREFIX):]
            # Rewrite the ASGI scope so downstream routing sees /api/...
            request.scope["path"] = new_path
            # raw_path is the byte-string equivalent; routers may consult either
            request.scope["raw_path"] = new_path.encode("utf-8")
        return await call_next(request)
