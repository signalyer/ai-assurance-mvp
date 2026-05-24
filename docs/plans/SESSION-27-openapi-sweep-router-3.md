# Session 27 plan — OpenAPI sweep router #3

**Date drafted:** 2026-05-24 (end of Session 26)
**Branch:** main (direct-to-main per current convention)
**Carry-over from Session 26:**
- ✓ Track A router #2 (`api/reports.py`) — 6/66 routes done
- ⏸ Track A routers #3-25 — 23 routers / 55 routes remaining
- ⏸ Track C manual verification (one real-login DevTools cookie check) — still open
- ⏸ ADR-001 Garak sidecar (Accepted, unscheduled)

---

## Candidate routers (sorted by recommended order)

| Router | Routes | UI coupling | Notes |
|---|---|---|---|
| `api/analytics.py` | 5 | medium | **Recommended next** — moderate count, dashboard charts read stable KPI keys |
| `api/connectors.py` | 4 | low | Easy alternative |
| `api/evidence.py` | 4 | medium | Reasonable |
| `api/domains_api.py` | 5 | medium-high | Defer until later — SPA dropdowns |
| `api/guide.py` | 9 | **high** | **Defer to late in sweep** — highest SPA surface |

## Workflow (locked by Sessions 25-26)

1. `Grep -r "api/<prefix>/" static/ team-portal/` — list every consumer FIRST (SESSION-13 §6).
2. Read router end-to-end + every consumer file. Note which response keys the UI actually reads.
3. Draft Pydantic v2 BaseModels inline. Strict for stable shapes (catalogs,
   lists with known keys). Permissive (`ConfigDict(extra="allow")`) for any
   multi-shape return — pin only the discriminator fields the UI keys off
   (compound rules 25a + 26b).
4. For handlers returning `Response`/`JSONResponse`/`HTMLResponse` subclasses,
   `response_model=` still drives OpenAPI schema without altering runtime
   serialization (compound rule 26a). For raw binary exports
   (`.csv`/`.pdf`), `operation_id` only.
5. `SL_OPENAPI_EXPORT_PROFILE=ci python scripts/export_openapi.py`.
6. `git diff docs/openapi-v1.json | grep -E 'operationId|<NewModel>'` smoke.
7. Three-file budget: api/<router>.py + docs/openapi-v1.json + ARCHITECTURE.md closeout.

## Pre-flight checklist (start of Session 27)

- [ ] State decorator chain order from ARCHITECTURE.md §20.
- [ ] Read Session 26 "Files — Built" entry + compound rules 26a-b.
- [ ] Pick router (default `api/analytics.py`).
- [ ] Grep consumers BEFORE editing.
- [ ] Confirm `SL_OPENAPI_EXPORT_PROFILE=ci` for any spec regeneration.
- [ ] ≤3 files of substantive change.

## Out-of-scope this session

- Garak code (defer; ADR-001 §7 is its own session).
- Bulk OpenAPI sweep across multiple routers (compound 24b warns against this).
- Bicep parameterisation of SESSION-12B §6 backend pins (needs staging slot).

## Open carry-overs (not blocking this session)

- **Track C manual verification** — one real-login DevTools cookie inspection
  on `https://aigovern.sandboxhub.co/login`. Confirm `session` cookie shows
  `Domain=.aigovern.sandboxhub.co`, then logout → confirm removed. Rollback:
  `az webapp config appsettings delete --name app-aigovern-dev --resource-group rg-aigovern-dev --setting-names SESSION_COOKIE_DOMAIN`.
- **ARCHITECTURE.md broader cleanup pass** — section structure has cruft
  beyond the "In Progress" cleanup done in Session 25. Worth a quiet-session
  pass when there's no router work scheduled.
- **ADR-001 Garak sidecar** — Accepted, unscheduled. ADR §7 has 6-step plan.
