# SESSION-40 — Tier 3 sweep router 1/3 (api/framework.py) + 28a obs #7 + CISO Console fold-in

## Carryover from S39
- **Counter 33/40.** Tier 1 bucket emptied. Only 3 Tier 3 routers remain (framework, usage, guide).
- 28a obs #6 = NO (aaca029). Tally 2/6. Observation continues.
- CISO Console scaffold (CSM-1) running in background worktree at S39 close — fold result into this session if landed.

## Step 0 — 28a observation #7 (≤2 min)
```bash
gh run list --commit=<S39-closeout-sha> --limit 5
```
S39 closeout will be mixed (modify + delete + add). If it fires AND any 2 of S35/S36/S37/S38/S39 also fired → 3/5 → gate fires.

## Step 1 — Fold CISO Console worktree if landed
Check the background agent status:
- If complete: review the worktree, merge to main, commit as `"Feat: CSM-1 — CISO Console SPA scaffold + 3 surfaces (Findings + Audit + RTF approval)"`. Verify `npm run build` in worktree before merge.
- If still running: leave it; carry to S41 fold-in.

## Step 2 — Tier 3 sweep: api/framework.py
SPA consumers (3 hits per S38 grep):
- `static/ai-systems.html` — uses `GET /api/frameworks/{slug}/system/{systemId}`
- `static/frameworks.html` — uses `GET /api/frameworks/matrix` and `GET /api/frameworks/{slug}/system/{systemId}`

Note: this is `api/framework.py` (singular, untouched), NOT `api/frameworks.py` (plural, swept S32). Verify the prefix at the top of the file before sweeping — the path collision matters.

Sequential single-router work (Tier 3 rule):
1. Read `api/framework.py` end-to-end
2. Read each SPA consumer to identify which response fields they read
3. Sweep with strict response_model where shape is stable; permissive only where consumer reads vary-by-payload fields
4. operation_id convention: `framework_<verb>[_<noun>]` (avoid collision with `frameworks_*` from S32)
5. Single Track A commit
6. Regen spec, verify diff is additive only

## Step 3 — Track B closeout
- ARCHITECTURE.md S40 entry: counter → 34/40; 28a obs #7; CISO Console fold-in status
- New `docs/plans/SESSION-41-*.md`: api/usage.py (3 SPA consumers)
- Delete this plan
- Commit + push

## Parallel CISO Console — CSM-2 spawn (if CSM-1 landed)
If CSM-1 merged this session, spawn CSM-2 implementer in fresh worktree:
- Surfaces 4-6: RTF operator deep view, Policy authoring, Framework drilldown (read-only)
- Same prompt template, increment surface count

## Compound rules in force
- 24a-24d, 25a-25b, 26a, 27a, 28a-28c, 38a — all unchanged
- Tier 3 sequential rule per 24b amendment

## Out of scope
- Touching `api/frameworks.py` (already swept S32, name collision noted at EvidenceOut)
- More than one router this session — Tier 3 sequential
