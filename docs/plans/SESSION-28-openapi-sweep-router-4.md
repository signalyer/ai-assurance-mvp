# Session 28 plan — OpenAPI sweep router #4

**Date drafted:** 2026-05-24 (end of Session 27)
**Branch:** main (direct-to-main per current convention)
**Carry-over from Session 27:**
- ✓ Track A router #3 (`api/analytics.py`) — 5/66 routes done (16/66 cumulative)
- ⏸ Track A routers #4-25 — 22 routers / 50 routes remaining
- ⏸ Track C manual verification (one real-login DevTools cookie check) — still open
- ⏸ ADR-001 Garak sidecar (Accepted, unscheduled)
- ⏸ Post-deploy SHA verifier for 149bc8e — confirm `/api/health` returns
  that SHA. If it shows 069e923 or earlier, paths-ignore is now over-eager
  (Session 22 regression — investigate `.github/workflows/azure-deploy.yml`).

---

## Candidate routers (sorted by recommended order)

| Router | Routes | UI coupling | Notes |
|---|---|---|---|
| `api/connectors.py` | 4 | **low** | **Recommended next** — easy win, builds the streak |
| `api/evidence.py` | 4 | medium | Solid alternative |
| `api/domains_api.py` | 5 | medium-high | Defer — SPA dropdowns key off shape |
| `api/guide.py` | 9 | **high** | Defer to late in sweep — highest SPA surface |

## Workflow (locked by Sessions 25-27)

1. `Grep -r "api/<prefix>/" static/ team-portal/` — list every consumer FIRST.
2. Read router end-to-end + every consumer file. Note which response keys
   the UI actually reads.
3. Draft Pydantic v2 BaseModels inline. Strict for stable shapes. Permissive
   (`ConfigDict(extra="allow")`) for multi-shape returns — pin only
   discriminator fields (compound rules 25a + 26b).
4. For handlers returning `Response`/`JSONResponse`/`HTMLResponse` subclasses,
   `response_model=` still drives OpenAPI schema (compound rule 26a). For
   raw binary exports, `operation_id` only.
5. `SL_OPENAPI_EXPORT_PROFILE=ci python scripts/export_openapi.py`.
6. Spec-diff smoke + import smoke.
7. Three-file budget: `api/<router>.py` + `docs/openapi-v1.json` +
   `ARCHITECTURE.md` closeout.

## Pre-flight checklist (start of Session 28)

- [ ] Re-state decorator chain + three most recent "in progress" files.
- [ ] `curl -s https://aigovern.sandboxhub.co/api/health` — confirm prod
      SHA equals `149bc8e` (Session 27 code commit). If not, diagnose
      before starting new work.
- [ ] `Grep -r "api/connectors/" static/ team-portal/` — confirm coupling
      is still low. If unexpected consumers appear, downgrade to
      `api/evidence.py`.
- [ ] Read `api/analytics.py` (Session 27 reference) and `api/reports.py`
      (Session 26 reference) before drafting new models — pattern
      consistency matters.

## Out of scope for Session 28

- ADR-001 Garak sidecar (separate session — needs Dockerfile + bicep work).
- Bulk OpenAPI refactor across multiple routers in one session
  (compound rule 24b — per-router only).
- Anything that breaks the ≤3-file budget.

## Stretch (only if router is unusually small)

- Optional: append a comment to `storage.py:101` noting the empty-vs-
  populated key asymmetry caught by Session 27a, so future sweepers see
  it without re-reading the body. NOT a 3-file budget breaker — defer if
  the main sweep work pushes the budget.
