# SESSION-29 — Track A OpenAPI sweep, router #5

## Default target
`api/evidence.py` (4 routes, medium coupling). Alternative: `api/domains_api.py`
(5 routes, medium-high). Defer `api/guide.py` (9, high SPA coupling).

## Why evidence.py
Sweep progress is 4/25 routers (20/66 routes). Sessions 25-28 burned through
the four lowest-coupling routers (security, reports, analytics, connectors —
the last had zero UI consumers). `evidence.py` is the next rung: 4 routes,
medium coupling means at least one UI consumer to inspect, but small enough
that the 3-file budget holds comfortably.

## Workflow (locked Sessions 25-28)
1. **Project CLAUDE.md ritual.** State decorator chain + 3 most-recent
   "in progress" files.
2. **Verify deploy SHA.** `curl -s https://aigovern.sandboxhub.co/api/health`
   should report the most recent code SHA on main. If a doc-only SHA shows,
   note the paths-ignore regression is still live (Session 28 open issue) —
   does not block this session.
3. **UI-consumer grep FIRST.** `Grep -r "/api/evidence/" static/ team-portal/`
   before any code edit. If hits exist, read every consumer end-to-end.
4. **Read `api/evidence.py` + every consumer** before drafting models.
5. **Draft Pydantic v2 models.** Strict by default per compound rule 27a.
   Use `ConfigDict(extra="allow")` only if a handler genuinely returns
   asymmetric shapes (empty-vs-populated path, polymorphic rollup).
6. **Wire `response_model=` + `operation_id="evidence_<resource>_<verb>"`.**
   Verb convention: HTTP-ish (`_get`) for reads, semantic (`_run`, `_list`,
   `_create`) where the POST/GET semantics dominate. See analytics + reports
   + connectors for precedent.
7. **Regenerate spec.** `SL_OPENAPI_EXPORT_PROFILE=ci python scripts/export_openapi.py`
8. **Inspect diff.** New schemas + new operationIds only. No removed routes,
   no shape changes to prior schemas.
9. **Smoke.** `python -c "import api.evidence"` + TestClient against
   `dashboard.app` for each route — confirm 200 + shape matches model.
10. **Close.** ARCHITECTURE.md Session 29 entry + bump sweep progress to 5/25
    + this plan file replaced by SESSION-30. Two-commit pattern (code + docs).

## Three-file budget
- `api/evidence.py`
- `docs/openapi-v1.json`
- `ARCHITECTURE.md`

If the consumer grep surfaces UI files that need shape-tightening to match
strict models, that's a Session-29 spillover — keep this session's scope to
**non-breaking** response_model wrapping (permissive where consumer would
otherwise break). Tighten in Session 30.

## Open items carried from Session 28
- **paths-ignore regression** in `.github/workflows/azure-deploy.yml` —
  doc-only commits trigger App Service redeploy (Session 22 fix has
  regressed). Out of scope for Session 29 sweep; needs its own focused
  workflow-fix session with a doc-only test commit to confirm the filter.
  No runtime impact, only wasted deploy cycles.
- **Track C manual login verification** still open: load
  https://aigovern.sandboxhub.co/login → DevTools → Cookies → confirm
  `session` has `Domain=.aigovern.sandboxhub.co` → logout → confirm
  removed. Rollback path: `az webapp config appsettings delete --name
  app-aigovern-dev --resource-group rg-aigovern-dev --setting-names
  SESSION_COOKIE_DOMAIN`.
- **ADR-001 Garak sidecar** Accepted, unscheduled (ADR §7 steps 1-6).
- **Hidden contract trap** `storage.py:101` `calculate_analytics()`
  empty-vs-populated asymmetry (8 vs 10 keys). One-line comment worth
  adding — STRETCH ONLY, do not break the 3-file budget for it.

## Working rules in effect
- Project CLAUDE.md: read every file before editing; full files only;
  scrubber before tracer; policy fail-closed; ≤3-file change rule;
  end-of-session = /verify + ARCHITECTURE.md + next plan + commit.
- Global ~/.claude/CLAUDE.md: Azure SignalLayerDev,
  `MSYS_NO_PATHCONV=1`, /compact at ~60%.
- Compound rules 19a-d, 20a-b, 21a-b, 22a-b, 23a-b, 24a-b, 25a-b,
  26a-b, 27a — all in ARCHITECTURE.md.
- Direct-to-main; two-commit pattern (code + docs); Session 22
  paths-ignore (currently regressed — see open items); Session 19 SHA
  round-trip verifies every code deploy.
- Local `import dashboard` logs `openapi.drift.production_warn` —
  EXPECTED, not a defect (compound 25b).
