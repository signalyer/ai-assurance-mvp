# SESSION-34 — Track A tenth per-router OpenAPI sweep

## Carry-over state at session start
- 9 routers shipped by this initiative through S33 (security, reports,
  analytics, connectors, evidence, domains_api, adversarial, frameworks,
  projection)
- "20/36 fully typed" estimate is now two sessions stale (S31, S32, S33
  all carried it without recounting) — **first job is an empirical recount**
- Compound rules 24a–24d, 25a–25b, 26a–26b, 27a, 28a in force; 24d new
  this past session (always use `scripts/export_openapi.py`, never raw
  `app.openapi()`)
- Compound 28a regression has 2 confirmed data points (S30→S31, S31→S32)
  and 1 pending check (S32→S33 closeout commit `ca20d85`); S33 closeout
  will be a fourth data point — verify and decide whether to schedule
  the dedicated fix session in S35

## Step 1 — Empirical recount (≤5 min, before picking target)
```bash
cd C:\ai-assurance-mvp
for f in api/*.py; do
  total=$(grep -cE '^@router\.(get|post|put|patch|delete)' "$f")
  typed=$(grep -cE 'response_model=' "$f")
  ops=$(grep -cE 'operation_id=' "$f")
  echo "$f routes=$total response_model=$typed operation_id=$ops"
done | sort
```
This is the canonical 24c probe extended across the directory. Output
goes into the S34 closeout for the next session's carry-over.

## Step 2 — Pick target from genuinely-partial routers
Smallest-delta candidates (apply 24c on whichever you pick):
- `api/traces.py` (1 route, untyped) — tracer-adjacent, but the surface
  is just `GET /traces`; one strict response model + one op_id
- `api/agent_notifications.py` (1 SSE route) — op_id only per S31 rule,
  document the gap in module docstring
- `api/metrics.py` (1)
- `api/evaluate.py` (1)
- `api/assessment.py` (2)

Defer: `api/guide.py` (9 routes, high SPA coupling — own session).

## Step 3 — Apply the locked S25-S33 pattern
1. Grep `static/` + `team-portal/` for `/api/<prefix>/` consumers
2. Read router + consumer end-to-end; read upstream domain shapes if
   response model is bound to a dataclass / Pydantic model
3. Draft Pydantic v2 BaseModels inline (`extra="forbid"` by default;
   `list[dict]` only for genuinely polymorphic payloads per 27a)
4. Add `response_model=` + `operation_id="<prefix>_<resource>_<verb>"`
   to every route
5. **Regenerate spec via `python scripts/export_openapi.py` (24d)** —
   never raw `app.openapi()`
6. Verify diff is exactly {new schemas + new operationIds}; no removed
   routes; no shape changes to prior schemas
7. SSE / binary-response routes: `operation_id` only, no `response_model`;
   document the intentional gap in file docstring (S31 + S32 rules)

## Step 4 — Two-commit close
- `Feat: SESSION-34 Track A — tenth per-router OpenAPI sweep (<file>)`
  with the recount appended to the body so future sessions inherit
  the fresh count without re-running the loop
- `Docs: SESSION-34 closeout — ARCHITECTURE.md S34 entry + SESSION-35 plan`

## Open issues carried forward
- **Compound 28a regression** — likely 4 data points after S33 closeout;
  if confirmed, schedule a dedicated fix session in S35. Suspected GitHub
  Actions `paths-ignore` quirk around file delete+add in same push
- **EvidenceOut name collision** between `api/frameworks.py` + `api/grc.py:491`
  — fix when a future session touches `api/grc.py` (~3 lines)
- **MatrixCellOut** at `api/frameworks.py:83` — dead code, leave unless
  `guide.py`-class sweep touches the file
- **Track C cookie-domain manual verify** (S22, deferred)
- **ADR-001 Garak sidecar** — Accepted, unscheduled
- **storage.py:101 `calculate_analytics()`** 8-vs-10 keys asymmetry — STRETCH only

## Compound rules earned by predecessors
| # | Rule | Session |
|---|---|---|
| 24a | Per-router sweep, never bulk | S25 |
| 24b | Don't touch out-of-router collisions mid-sweep | S26 |
| 24c | Grep-recount the target before commit (planned list goes stale) | S31/S32 |
| 24d | Always use `scripts/export_openapi.py`, never raw `app.openapi()` | S33 |
| 25a | Permissive (`extra="allow"`) only for genuinely asymmetric payloads | S26 |
| 25b | `ci` profile is the only committable export | S25 |
| 26a | Routes returning `Response` subclass still get OpenAPI schema via `response_model` | S26 |
| 26b | Permissive + pinned discriminators beats union-of-six for multi-builder dispatch | S26 |
| 27a | Strict by default; `list[dict]` only for asymmetric/polymorphic | S27 |
| 28a | (open issue) doc-only paths-ignore globs may not catch delete+add commits | S29/S30/S31 |
