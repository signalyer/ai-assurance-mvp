# Session 26 plan — OpenAPI sweep (router #2) or Track C (DNS)

**Date drafted:** 2026-05-24 (end of Session 25)
**Branch:** main (direct-to-main per current convention)
**Carry-over from Session 25:**
- ✓ Track A router #1 (`api/security.py`) — 5/66 routes done
- ✓ Drift gate fix (dashboard.py) — closed spawned-task chip
- ✓ Track C (parent-domain cookie activation) — `SESSION_COOKIE_DOMAIN`
  flipped on `app-aigovern-dev`; custom hostname + TLS bind was already
  provisioned out-of-band. One real-login DevTools verification pending.
- ⏸ Track A routers #2-25 — 24 routers / 61 routes remaining

---

## Session 26 candidate tracks

### A — Second OpenAPI router (recommended default)

Pattern locked by Session 25. Pick from the remaining list by risk-coupling:

| Router | Routes | UI coupling | Recommended slot |
|---|---|---|---|
| `api/reports.py` | 6 | medium | **Recommended next** — moderate count, stable consumer shape |
| `api/analytics.py` | 5 | medium | Good alternative |
| `api/domains_api.py` | 5 | medium-high | Defer — SPA dropdowns depend on shape |
| `api/connectors.py` | 4 | low | Easy second sweep if reports/analytics deferred |
| `api/evidence.py` | 4 | medium | Reasonable |
| `api/guide.py` | 9 | **high** | **Defer to late in sweep** — highest SPA surface |

**Workflow (per Session 25b pattern):**
1. `Grep -r "api/<prefix>/" static/ team-portal/` — list every consumer.
2. Read the router end-to-end + every consumer file.
3. Draft Pydantic v2 BaseModels inline. Use `ConfigDict(extra="allow")` for
   permissive (multi-shape return) endpoints, strict pinning for stable shapes.
4. Add `response_model=` + `operation_id="<prefix>_<resource>_<verb>"` to every route.
5. `SL_OPENAPI_EXPORT_PROFILE=ci python scripts/export_openapi.py`.
6. `git diff docs/openapi-v1.json | grep -E 'operationId|<NewModelName>'` — visual smoke.
7. Commit. Deploy auto-fires (code change in `api/`).
8. Post-deploy: smoke against prod if UI consumers exist.

### ~~B — Track C: DNS + parent-domain cookie activation~~ ✓ Closed Session 25

Platform side complete. Only remaining work is the one-real-login DevTools
verification — not a full session, just a single sanity check on next login:

1. Open `https://aigovern.sandboxhub.co/login`, log in as any demo user.
2. DevTools → Application → Cookies → confirm `session` shows
   `Domain=.aigovern.sandboxhub.co` (NOT host-only / NOT `aigovern.sandboxhub.co`
   without leading dot).
3. Click logout → confirm the `session` cookie is removed (Session 24a:
   parent-domain set must be paired with parent-domain delete).
4. If anything diverges, the env var to roll back is
   `az webapp config appsettings delete --name app-aigovern-dev --resource-group rg-aigovern-dev --setting-names SESSION_COOKIE_DOMAIN`.

### C — Garak sidecar first cut (ADR-001 §7 steps 1-3)

Lower priority unless V2 SPA cutover is being scheduled. Heavy lift
(Dockerfile + Container App bicep + bridge module). Estimated full session
+ Session 27 closeout. ADR-001 is Accepted — implementation is unblocked
but unscheduled.

---

## Recommended default: A (router #2)

Default to `api/reports.py` unless DNS ops are convenient to run alongside
the next development window. Track A is the highest-leverage carry-over —
each per-router PR is small, the pattern is now locked, and the V2 SPA
needs the typed contracts for codegen.

---

## Pre-flight checklist (start of Session 26)

- [ ] State decorator chain order from ARCHITECTURE.md §20.
- [ ] Read Session 25 "Files — Built" entry + compound rules 25a-b.
- [ ] Pick router or Track C.
- [ ] If router: grep consumers BEFORE editing (SESSION-13 §6 hard rule).
- [ ] Confirm `SL_OPENAPI_EXPORT_PROFILE=ci` for any spec regeneration.
- [ ] ≤3 files of substantive change. Closeout docs are additive.

## Out-of-scope this session

- Garak code (defer to a dedicated session).
- Bulk OpenAPI sweep across multiple routers (SESSION-13 §6 + compound 24b
  warn against this).
- Bicep parameterisation of the SESSION-12B §6 backend pins (needs a
  staging slot first).
