# SESSION 25 — Pick a track: OpenAPI sweep (first router) OR Garak sidecar (first cut)

> **Status:** Planned. Two viable tracks; pick one at session start.
> **Created:** 2026-05-24 (end of Session 24)
> **Prereqs:** Session 24 merged (parent-domain cookie + ADR-001 Accepted + SESSION-12B §6 closed). Working tree clean. `tag day-12-complete` still valid.

---

## 1. State entering this session

- V2 Phase 1 closeout is **complete except DNS** (item A4 deferred to Session 24b)
- ADR-001 is **Accepted** — Garak sidecar implementation is unblocked
- OpenAPI sweep survey: 66 routes across ~25 files lack `response_model=` (top offenders in ARCHITECTURE.md Session 24 entry)
- Compound rules now active: 24a (cookie domain pairing), 24b (defer-and-survey on multi-file sweeps)
- Open spawned task: "Fix local dashboard import vs CI OpenAPI drift" — `dashboard.py:215` raises on local `import dashboard` without the Session 21 CI env profile. May need to land before the OpenAPI sweep to make per-router verification ergonomic.

## 2. Track A — OpenAPI sweep, first router

**Pick first.** `api/guide.py` is the top offender (9 routes) but also the most surface-area-exposed (governance guide UI consumes it). Alternative: start with `api/security.py` (5 routes) — less UI coupling, lower regression blast.

**Recommend:** `api/security.py` first. Smaller diff, fewer UI consumers, validates the pattern. Then `api/connectors.py` (4) and `api/evidence.py` (4) as the second pair. `guide.py` last.

**Per-router workflow (mirrors SESSION-13 §3.A1):**
1. Read the router file end-to-end + grep all UI/SPA consumers of the routes
2. Define Pydantic v2 `BaseModel`s inline at top of the router file (default per SESSION-13 §6) — only refactor to `api/contracts/` if duplication emerges
3. Add `response_model=` + `operationId=` to every `@router.<verb>`
4. Run `python scripts/export_openapi.py` with the `ci` profile, commit the spec diff
5. `pwsh deploy/smoke_e2e.ps1` against prod after deploy (Session 19's SHA round-trip catches regressions in ~90s)
6. If a static HTML page breaks, fix the response model to match reality — never change the response shape (would break V1 UI)

**Acceptance:** `curl https://aigovern.sandboxhub.co/openapi.json | jq '.paths."/api/security/scan".post.responses."200".content."application/json".schema'` returns a `$ref` not `{type: object}`.

**Estimated time:** 1 session per router pair (1 router for the high-coupling cases).

## 3. Track B — Garak sidecar, first cut

ADR-001 §7 six-step plan. Steps 1-3 fit one session if the user has Azure quota in hand:
1. `deploy/docker/garak/Dockerfile` — pin `garak` + minimal HTTP wrapper. Test locally with `docker build && docker run` + curl smoke.
2. `deploy/bicep/garak.bicep` — Container App `ca-aigovern-garak-dev`, internal ingress only, env var contract with engine.
3. `domain/garak_bridge.py` — subprocess-equivalent client (HTTP, since sidecar is over the wire) with timeout + result coercion to the existing `adversarial.py` `ProbeResult` shape.

Steps 4-6 (endpoint + SPA + integration test) land in Session 26.

**Acceptance:** sidecar deployed, `domain/garak_bridge.py` integration test green against the running sidecar.

**Estimated time:** 1 session if Docker + Bicep land clean; 2 if image-size or network-policy issues surface.

## 4. Track C — Session 24b DNS (if user wants the cookie change exercised end-to-end first)

Smaller scope than A or B; ~half a session:
1. `az network dns record-set cname create` on the sandboxhub.co zone
2. `az webapp config hostname add` on `app-aigovern-dev`
3. `az webapp config ssl bind` (managed cert)
4. `curl https://api.aigovern.sandboxhub.co/api/health` returns `{"status":"ready","sha":"<commit>"}`
5. Set `SESSION_COOKIE_DOMAIN=.aigovern.sandboxhub.co` on App Service
6. Verify in browser DevTools: cookie `Domain` is `.aigovern.sandboxhub.co`; login + logout both clear it

**Recommend pairing with Track A first-router** since both are short.

## 5. Out of scope (explicitly)

- App Insights instrumentation (still needs P1v3 + staging slot first)
- Multi-tenant changes (V3)
- New product features

## 6. Decision at session start

Ask the user: A (OpenAPI sweep start) / B (Garak sidecar start) / C (DNS only) / A+C combo. Default if no preference: **A+C** — keeps risk small per change and exercises Session 24's auth code path.

## 7. Sign-off

| Reviewer | Date | Status |
|---|---|---|
| Praveen (architect) | _pending_ | _pending_ |
