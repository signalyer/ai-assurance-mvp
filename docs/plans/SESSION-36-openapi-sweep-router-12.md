# SESSION-36 — Track A twelfth router (api/agent_bindings.py) + compound 28a observation #3

## Carryover from S35
- S35 shipped 11th sweep (`api/rag.py`, 4/4/4) → sweep counter **20/40**.
- Compound 28a status: **intermittent, observation phase.**
  - S29-S33 closeouts (5/5) triggered deploy.
  - S34 closeout `d5b36de` did NOT (first break).
  - S35 reframe `0d8ff1c` did NOT.
  - S35 closeout (TBD this session start) is observation point #3.
  - **Decision gate still pending: at point #5, if ≥3 triggered, schedule fix.**

## Step 0 — Compound 28a data point #3 (≤2 min)
At session start:
```bash
gh run list --commit=<S35-closeout-sha> --limit 5
```
Record outcome in the table below. Do NOT modify `.github/workflows/deploy.yml`
this session regardless of result — observation phase continues until S37.

| Session | Closeout commit | Triggered deploy? |
|---|---|---|
| S35 | (fill at S36 start) | (fill at S36 start) |
| S36 | (TBD) | (TBD) |
| S37 | (TBD) | (TBD) |

## Step 1 — Apply compound 24c probe to S36 target
```bash
grep -cE '^@router\.(get|post|put|delete|patch)' api/agent_bindings.py
grep -c 'response_model=' api/agent_bindings.py
grep -c 'operation_id=' api/agent_bindings.py
```
Expected per S34 recount: **4 / 3 / 4** (1 missing response_model).

If the probe diverges from 4/3/4, pivot per compound 24c — don't burn
the session on a stale target (S31 + S32 lesson).

## Step 2 — Track A sweep
1. Identify the route missing `response_model=` (one of 4 — likely DELETE
   or a status endpoint). Confirm whether it returns JSON or a `Response`
   subclass per compound 26a.
2. If JSON: draft Pydantic v2 model (strict per 27a unless polymorphic).
3. If `Response` subclass for binary/204: leave response_model off,
   document gap in module docstring per S31 rule.
4. Grep static/ + team-portal/ for consumers; verify wire compat.
5. `python -c "import api.agent_bindings"` → must pass.
6. Recount 24c → expect 4/4/4 (or 4/3/4 if one route is intentionally
   bare per the binary/SSE/204 rule).
7. Regen spec via `python scripts/export_openapi.py` (compound 24d).

## Step 3 — Track A commit
"Feat: SESSION-36 Track A — twelfth per-router OpenAPI sweep (api/agent_bindings.py)"

## Step 4 — Track B closeout
- ARCHITECTURE.md S36 entry (sweep tick → 21/40; 28a observation #3 result)
- New `docs/plans/SESSION-37-*.md` (next sweep target per partial list)
- Delete this plan file

Candidate S37 target from the partials list (S35-updated):
- `api/analytics.py` (5/3/5 — 2 missing response_model)
- `api/reports.py` (6/3/6 — 3 missing response_model)
- `api/assurance_model.py` (5/12/12 — grep over-counts, needs visual)

Closest to S36 shape (single response_model add) is none; analytics.py
is next-cleanest (2 adds).

## Out of scope
- Any workflow change for 28a — observation continues.
- More than one router this session — per compound 24b.
- Touching the Session 19 SHA round-trip — working as designed.
