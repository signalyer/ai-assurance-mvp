# SESSION-39 — Second parallel batch (3 Tier 1) + first Tier 3 (assessment) + 28a obs #6

## Carryover from S38
- **Counter 29/40.** First parallel batch sweep landed clean (`216359f`). Compound 24b amendment validated.
- 28a observation #5 = NO (8e97454 did not deploy). Tally 2/5. Gate moves to S38 closeout commit (216359f or its successor).
- New compound rule 38a: pre-flight consumer-coupling grep gate is the parallelization safety net.

## Step 0 — 28a observation #6 (≤2 min)
```bash
gh run list --commit=<S38-closeout-sha> --limit 5
```
Update tally. S38 closeout will be mixed (ARCHITECTURE.md modify + delete S38 plan + add S39 plan) — same shape as S36 (YES) and S37 (NO). If fires → 3/5 last → gate fires, S39 Track A becomes paths-ignore workflow fix instead of more sweep.

## Step 1 — Tier 1 batch (3 parallel implementers)
Pre-flight grep already done in S38; the 3 zero-coupling routers remaining are confirmed:
- `api/aws_demo.py`
- `api/demo.py`
- `api/demo_control.py`

Spawn 3 `implementer` subagents in one message. Same prompt template as S38 (locked S25-31 pattern, do NOT regen spec, do NOT commit, return concise report).

operation_id conventions: `aws_demo_<verb>`, `demo_<verb>`, `demo_control_<verb>`.

## Step 2 — Tier 3 sequential: api/assessment.py
1 SPA consumer (`static/assessment.html` line ~). Read consumer first, then sweep.
- Read `static/assessment.html` — identify which fields it reads from `/api/grc/assessment/run/{id}` response
- Read `api/assessment.py` end-to-end
- Sweep with strict response_model where shape is stable; permissive only where consumer reads fields that vary
- Add operation_id per `assessment_<verb>` convention
- Verify wire compat: every field consumer reads must still be in response

Single-router work — do this sequentially in the main session, not via subagent (Tier 3 rule).

## Step 3 — Aggregate + spec regen + commits
- Visual review 3 Tier 1 diffs + assessment diff
- `python scripts/export_openapi.py` ONCE
- **Two Track A commits** (Tier 1 batch separate from Tier 3 single, for clean attribution):
  - `"Feat: SESSION-39 Track A1 — Tier 1 batch sweep (aws_demo + demo + demo_control via parallel implementers)"`
  - `"Feat: SESSION-39 Track A2 — Tier 3 sweep (api/assessment.py with SPA consumer compat)"`

## Step 4 — Track B closeout
- ARCHITECTURE.md S39 entry: counter → 33/40; 28a obs #6 outcome; first Tier 3 sweep notes
- New `docs/plans/SESSION-40-*.md`:
  - Remaining work: framework (3 SPA hits), usage (3 hits), guide (9 routes, high coupling)
  - Recommend Tier 3 one-per-session for these
- Delete this plan
- Commit + push

## After S39 — final stretch
Counter 33/40 leaves only 3 Tier 3 routers (framework, usage, guide) + ?
Recount the "/40" denominator against `api/*.py` — may already be 40/40 or close. The "10 special-shape" set may have collapsed.

**Parallel track to schedule:** CISO Console SPA (A5) scaffold in `phase/cm-ciso-console` worktree. Engine routes consumed by Console are now ≥73% typed (29/40) — sufficient to start without waiting for full sweep finish.

## Compound rules in force
- 24a: per-router sweep core (Tier 3)
- **24b (amended S37, validated S38)**: per-coupling-tier; Tier 1 batches up to 5
- 24c: grep-recount + visual
- 24d: regen spec ONCE per session
- 25a/25b: SPA consumer compat (the pre-flight gate for tier assignment)
- 26a: bare-by-design for binary/204/SSE
- 27a: strict-by-default Pydantic v2
- 28a: paths-ignore observation — gate at S39 Step 0
- 28b: docstrings prose-style
- 28c: batch verification audits when staleness systemic
- **38a (NEW)**: pre-flight consumer-coupling grep gate is the parallelization safety net
