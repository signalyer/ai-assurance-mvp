# SESSION 33 — Track A · per-router OpenAPI sweep #9

## Status going in
Post-S32, sweep count = **8 routers shipped by this initiative**.
Empirical project state: **20/36 routers fully typed**; remaining
partial + untyped buckets need a recount at the front of S33 because
the planned-target list has gone stale twice in a row (S31, S32 both
pivoted off the named target on import).

## Compound 24c (new — added in S32 closeout)
Before locking the sweep target, run the recount probe:

```powershell
$target = "api/projection.py"
$rm = (Select-String -Path $target -Pattern 'response_model=' -SimpleMatch).Count
$op = (Select-String -Path $target -Pattern 'operation_id='   -SimpleMatch).Count
$rt = (Select-String -Path $target -Pattern '^@router\.'      -AllMatches).Count
"$target  routes=$rt  response_model=$rm  operation_id=$op"
```

If `op == rt` and `rm >= rt - <known-binary-routes>`, target is
already swept — pivot before reading the whole file.

## Recommended primary target — `api/projection.py`
3 routes, 1 typed today:

| Route | Today | S33 plan |
|---|---|---|
| `GET /status` | `response_model=ProjectionStatusResponse` | + `operation_id="projection_status_get"`, confirm `extra="forbid"` |
| `POST /replay` | untyped | + new `ProjectionReplayResponse` model, `operation_id="projection_replay"` |
| `GET /views/{view}` | untyped | + new `ProjectionViewPageResponse` model (page envelope + frozenset-whitelist enum if simple), `operation_id="projection_views_get"` |

Strict mode (`extra="forbid"`) on all new models per compound 27a.

## Alternative — `api/traces.py`
1 route, 0 typed. Smallest possible delta but tracer-adjacent —
adds audit-surface review burden the projection sweep doesn't.
Worth its own focused session, not bundled.

## Defer
- `api/guide.py` (9 routes, high SPA coupling — full design pass needed)
- `api/agent_bindings.py` (already 4/4, confirmed in S32)
- `api/findings_v2.py` (already 5/5, confirmed in S31)

## Carryover non-blockers
- **Compound 28a regression** — doc-only commits with file delete+add
  trigger deploy. Twice reproduced (S30→S31, possibly S31→S32 — check
  after S33 push). Needs a dedicated fix-session.
- **EvidenceOut name collision** between `api/frameworks.py` and
  `api/grc.py:491`. Future session that touches `api/grc.py` should
  rename `frameworks.py`'s class to `FrameworksEvidenceOut` + regen
  openapi artifact (~3 lines).
- `MatrixCellOut` at `api/frameworks.py:83` is dead code. Leave
  unless a guide.py-class sweep touches the file for other reasons.
- Track C cookie-domain manual verify (S22) — still open.
- ADR-001 Garak sidecar — Accepted, unscheduled.
- `storage.py:101 calculate_analytics()` 8-vs-10 keys asymmetry —
  STRETCH only.

## Working rules
- Read-before-edit, full files, ≤3-file budget.
- Two-commit pattern: Feat (code + openapi-v1.json), then Docs
  (ARCHITECTURE.md + this file replaced).
- `dashboard.app.openapi_schema = None` is required before
  re-calling `app.openapi()` post-import; the artifact validator at
  `dashboard.py:222` caches an empty spec into the app at import
  time. (Captured behaviour, not a bug to fix this session.)
- Local `import dashboard` logs `openapi.drift.production_warn` —
  EXPECTED (compound 25b).
- Revert any `data/*.jsonl` pollution before commit (S28 lesson).

## Next concrete action
Run the 24c recount probe against `api/projection.py`, then read it
end-to-end, then design the two new response models against the
domain return shapes (look in `domain/projection.py` for the
authoritative dict keys produced by `replay()` and the view
projections).
