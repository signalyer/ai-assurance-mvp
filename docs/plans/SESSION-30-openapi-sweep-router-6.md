# SESSION-30 — Track A OpenAPI sweep, router #6

## Default target
`api/domains_api.py` (5 routes, medium-high coupling).
Alternative: `api/findings_v2.py` or `api/runtime_v2.py`.
Defer `api/guide.py` (9, high SPA coupling).

## Why domains_api.py
Sweep progress is 5/25 routers (24/66 routes). Sessions 25-29
burned through the five lowest-coupling routers (security, reports,
analytics, connectors, evidence — the first four ranged from
zero-to-one live UI consumer; evidence had exactly one). `domains_api.py`
is the next rung up: **6 live consumers** found in Session 29
discovery grep — meaningfully higher coupling than evidence, but
still tractable inside the 3-file budget.

### Consumer surface (verified at S29 closeout)
- `static/compare.html:124` — `fetch('/api/domains')`
- `static/domains.html:209` — `fetch('/api/domains/')`
- `static/domains.html:240` — `fetch('/api/domains/${id}')`
- `static/domains.html:414` — `fetch('/api/domains/${id}', PUT)`
- `static/domains.html:439` — `fetch('/api/domains/${currentDomain.id}', DELETE)`
- `static/memory.html:374` — `apiFetch('/api/domains')`
- `team-portal/src/pages/memory/types.ts:2` — comment notes shared workload picker

Likely decision per route (confirm at read time):
- **List endpoints** (`/api/domains`, `/api/domains/`) — consumed by
  workload pickers in compare.html + memory.html. Pickers iterate
  results and read a small subset of fields. Lean **`list[dict]`**
  per connectors pattern (compound 27a's asymmetric case) to keep
  the OpenAPI surface decoupled from every domain schema bump.
- **Single-record GET `/{domain_id}`** — consumed by domains.html
  for the edit modal which reads many fields. Strict mirror likely
  fits per evidence pattern.
- **PUT/DELETE** — confirm shape at read.

## Workflow (locked Sessions 25-29)
1. **Project CLAUDE.md ritual.** State decorator chain + 3 most-recent
   "in progress" files (expect None per S25 cleanup).
2. **Verify deploy SHA.** `curl -s https://aigovern.sandboxhub.co/api/health`
   should report S29's code or doc SHA on main. If `paths-ignore`
   regression is still live, both will appear — does not block.
3. **UI-consumer re-grep.** Re-verify the 6-consumer surface above is
   still current. `Grep -r "/api/domains" static/ team-portal/` before
   any edit.
4. **Read `api/domains_api.py` + every consumer end-to-end** before
   drafting models. Pay attention to which fields each consumer reads
   — that determines strict-vs-`list[dict]` per route.
5. **Draft Pydantic v2 models.** Strict-by-default per compound rule
   27a, BUT list endpoints feeding pickers are good `list[dict]`
   candidates per compound 27a's asymmetric case (decouple OpenAPI
   from every domain schema bump).
6. **Wire `response_model=` + `operation_id="domains_<resource>_<verb>"`.**
   Verb convention: HTTP-ish (`_get`, `_update`, `_delete`) for
   REST verbs; semantic (`_run`, `_list`, `_create`) where the POST
   semantics dominate.
7. **Regenerate spec.** `SL_OPENAPI_EXPORT_PROFILE=ci python scripts/export_openapi.py`
8. **Inspect diff.** New schemas + new operationIds only. No removed
   routes, no shape changes to prior schemas.
9. **Smoke.** `python -c "import api.domains_api"` + TestClient
   against `dashboard.app` for each route — confirm 200 + shape
   matches model.
10. **Close.** ARCHITECTURE.md Session 30 entry + bump sweep progress
    to 6/25 + this plan file replaced by SESSION-31. Two-commit
    pattern (code + docs).

## Three-file budget
- `api/domains_api.py`
- `docs/openapi-v1.json`
- `ARCHITECTURE.md`

If consumer grep surfaces UI files that would break under strict
models, fall back to `list[dict]` for that route — do **not**
spillover into UI changes. This sweep stays non-breaking.

## Open items carried from Session 29
- **paths-ignore regression** in `.github/workflows/azure-deploy.yml`
  still uncorrected. Session 29 code + doc closeout both likely
  triggered deploys. **Strongly recommend a dedicated workflow-fix
  session before Session 30 starts** — otherwise S30's two-commit
  pattern will double-deploy again and pile noise onto the SHA
  round-trip diagnostic. Single-file scope: update `paths-ignore`
  in `.github/workflows/azure-deploy.yml` and verify with a
  doc-only test commit.
- **Track C manual login verification** still open: load
  https://aigovern.sandboxhub.co/login → DevTools → Cookies →
  confirm `session` has `Domain=.aigovern.sandboxhub.co` → logout
  → confirm removed. Rollback: `az webapp config appsettings delete
  --name app-aigovern-dev --resource-group rg-aigovern-dev
  --setting-names SESSION_COOKIE_DOMAIN`.
- **ADR-001 Garak sidecar** Accepted, unscheduled (ADR §7 steps 1-6).
- **Hidden contract trap** `storage.py:101` `calculate_analytics()`
  empty-vs-populated asymmetry (8 vs 10 keys). One-line comment
  worth adding — STRETCH ONLY, do not break the 3-file budget for it.

## Working rules in effect
- Project CLAUDE.md: read every file before editing; full files only;
  scrubber before tracer; policy fail-closed; ≤3-file change rule;
  end-of-session = /verify + ARCHITECTURE.md + next plan + commit.
- Global ~/.claude/CLAUDE.md: Azure SignalLayerDev,
  `MSYS_NO_PATHCONV=1`, /compact at ~60%.
- Compound rules 19a-d, 20a-b, 21a-b, 22a-b, 23a-b, 24a-b, 25a-b,
  26a-b, 27a — all in ARCHITECTURE.md.
- Direct-to-main; two-commit pattern (code + docs); Session 22
  paths-ignore (currently regressed — see open items); Session 19
  SHA round-trip verifies every code deploy.
- Local `import dashboard` logs `openapi.drift.production_warn` —
  EXPECTED, not a defect (compound 25b).

## Pattern reminders for the strict-vs-list[dict] decision
- **Evidence pattern (S29):** every shape upstream is deterministic
  (dataclass or stable Pydantic model) + the consumer reads many
  fields + single-record fetch → **strict mirror** wins.
- **Connectors pattern (S28):** domain-payload lists at the API
  boundary → **`list[dict]`** wins, because binding to full domain
  Pydantic models re-validates on response and couples this router's
  OpenAPI surface to every domain schema bump.
- **Analytics pattern (S27):** genuinely asymmetric shape (empty
  vs populated history) → `ConfigDict(extra="allow")` with Optional
  fields on the asymmetric keys.

Pick per route based on what each consumer actually reads.
