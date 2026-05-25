# SESSION-37 — Track A thirteenth router (api/analytics.py) + compound 28a observation #4

## Carryover from S36
- S36 shipped 12th sweep (`api/agent_bindings.py`, 4/3/4 — DELETE bare-by-design per 26a, document-the-gap sweep per S31). Sweep counter **21/40**.
- New **compound 28b** captured: docstrings must not embed literal `response_model=` or `operation_id=` tokens (inflates 24c grep). Probe twice — pre and post edit — to catch.
- Compound 28a status: **intermittent, observation phase** — 5 fired / 3 missed; last three closeouts all missed (S34, S35 reframe, S35 closeout).

## Step 0 — Compound 28a data point #4 (≤2 min)
At session start:
```bash
gh run list --commit=<S36-closeout-sha> --limit 5
```
Record outcome in the table below. **Workflow stays unchanged.**
Decision gate at observation point #5 stands: if ≥3 of next 5 closeouts
re-trigger deploy, schedule dedicated fix.

| Session | Closeout commit | Triggered deploy? |
|---|---|---|
| S35 | `8933b34` | NO (recorded at S36 start) |
| S36 | (fill at S37 start) | (fill at S37 start) |
| S37 | (TBD) | (TBD) |

## Step 1 — Apply compound 24c probe to S37 target
```bash
grep -cE '^@router\.(get|post|put|delete|patch)' api/analytics.py
grep -c 'response_model=' api/analytics.py
grep -c 'operation_id=' api/analytics.py
```
Expected per S35-updated partials: **5 / 3 / 5** (2 missing response_model).

If probe diverges, pivot per compound 24c — don't burn the session on a stale target (S31 + S32 lesson).

## Step 2 — Track A sweep
1. Identify the 2 routes missing `response_model=`. For each:
   - If JSON: draft strict Pydantic v2 model per 27a (`list[dict]` only if asymmetric/polymorphic)
   - If `Response` subclass for binary/204/SSE: leave bare, document gap in module docstring per S31 rule
2. Grep `static/` + `team-portal/` for `/api/analytics` consumers; verify wire compat
3. `python -c "import api.analytics"` → must pass
4. Recount 24c — expect 5/5/5 (or 5/4/5 if one is intentionally bare)
5. **Apply compound 28b**: re-run probe AFTER any docstring edits; ensure no `response_model=` / `operation_id=` literals in prose
6. Regen spec via `python scripts/export_openapi.py` (compound 24d)

## Step 3 — Track A commit
"Feat: SESSION-37 Track A — thirteenth per-router OpenAPI sweep (api/analytics.py)"

## Step 4 — Track B closeout
- ARCHITECTURE.md S37 entry (sweep tick → 22/40; 28a observation #4 result)
- New `docs/plans/SESSION-38-*.md` (next sweep target — `api/reports.py` 6/3/6 likely candidate)
- Delete this plan file
- Commit + push

## Compound rules in force (declared by session of origin)
- 24a/24b: per-router sweep, never bulk
- 24c: grep-recount before commit (now: BEFORE and AFTER any docstring edits — per 28b)
- 24d: regen spec via `scripts/export_openapi.py`, never raw `app.openapi()`
- 25a/25b: SPA consumer compat check (grep static/ + team-portal/)
- 26a: bare-by-design rule for binary/204/SSE responses
- 26b: (see ARCHITECTURE.md S26)
- 27a: strict-by-default Pydantic v2; `list[dict]` only for asymmetric/polymorphic
- 28a: GitHub Actions path-filter glob behaviour (observation phase, fix at point #5 if ≥3/5 re-trigger)
- 28b: **NEW** — docstrings must not embed literal `response_model=` / `operation_id=` tokens (inflates 24c grep recount)

## Out of scope
- Any workflow change for 28a — observation continues
- More than one router this session — per compound 24b
- Touching the Session 19 SHA round-trip — working as designed
