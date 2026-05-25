# SESSION-38 — Track A fourteenth router + compound 28a observation #5 (decision gate)

## Carryover from S37
- S37 verified `api/analytics.py` as already-final-since-S27 (5/3/5 = 3 JSON + 2 bare exports per 26a). No code change. Counter **22/40**.
- Third consecutive partial-list staleness (S31, S32-original, S37). Partials bucket effectively dry.
- Compound 28a observation #4 = **YES (deploy fired)** for bb2a520 (S36 closeout, mixed modify+delete+add). Tally **6 fired / 3 missed** of last 9. State: intermittent. **Observation point #5 at S38 start is the decision gate.**

## Step 0 — Compound 28a data point #5 (DECISION GATE, ≤2 min)
```bash
gh run list --commit=<S37-closeout-sha> --limit 5
```

| Session | Closeout commit | Mix type | Triggered deploy? |
|---|---|---|---|
| S35 | `8933b34` | doc-only modify | NO |
| S36 | `bb2a520` | modify + delete + add | YES |
| S37 | (fill at S38 start) | (fill) | (fill) |

**Decision rule:** if ≥3 of recent 5 closeouts (S33-S37) fired deploy,
schedule dedicated `paths-ignore` fix as S39 Track A. If <3, continue
observation (workflow unchanged).

Current count of last 5 closeouts: S33 YES, S34 NO, S35-reframe NO,
S35 NO, S36 YES = **2/5 fired so far**. S37 result tips the gate.

## Step 1 — Apply compound 24c+visual to `api/reports.py`
S37 quick-probe returned 6/3/6 (mirroring analytics.py shape). Per S26
ARCHITECTURE entry: 3 JSON routes typed strict/permissive, 3 export
endpoints (`.json`/`.csv`/`.pdf`) get `operation_id` only per 26a.
**Expected: already-final, no code change.** Visual check the module
docstring + each `@router` decorator to confirm.

If confirmed already-final:
- Counter 22 → 23 (verification-only sweep)
- Note S38 outcome in ARCHITECTURE S38 entry
- Pivot Step 2 to next router

If actually missing models (unexpected):
- Standard 24c → draft Pydantic v2 models → 24d regen → commit

## Step 2 — Pivot to next router
Per S37 audit, two viable next paths:

**Path A (recommended): start untouched list with smallest router.**
- `api/agent_notifications.py` — 1 SSE route. Per S31 rule, `operation_id=` only, document gap in docstring. ~10-line change.
- `api/metrics.py` — 1 route (Prometheus exposition). Special-shape per S36 partials note. `operation_id=` only.
- `api/traces.py` — 1 route. Likely needs `response_model=` + `operation_id=`.

**Path B: visual check `api/assurance_model.py`.** 5/12/12 raw grep
suggests heavy docstring/comment pollution (per 28b lesson). Visual
confirm — may already be fully typed with grep over-counting.

Pick Path A if S38 budget allows two routers (reports verify + one small
untouched); pick Path B if reports verify takes longer than expected.

## Step 3 — Track A commit (if any code change)
"Feat: SESSION-38 Track A — fourteenth per-router OpenAPI sweep (api/<target>.py)"

If verification-only (no code change), skip Track A commit; closeout-only.

## Step 4 — Track B closeout
- ARCHITECTURE.md S38 entry (sweep tick → 23/40 or 24/40; 28a observation #5 + decision gate outcome)
- New `docs/plans/SESSION-39-*.md` (next target per S38 outcome)
- Delete this plan file
- Commit + push

## Compound rules in force
- 24a/24b: per-router sweep, never bulk
- 24c: grep-recount + **visual check** before declaring partial (S37 lesson — raw greps mislead under 26a)
- 24d: regen spec via `scripts/export_openapi.py`, never raw `app.openapi()`
- 25a/25b: SPA consumer compat check (grep static/ + team-portal/)
- 26a: bare-by-design for binary/204/SSE — document gap in module docstring
- 27a: strict-by-default Pydantic v2; `list[dict]` only for asymmetric/polymorphic
- 28a: paths-ignore glob behavior — **decision gate this session at observation point #5**
- 28b: docstrings must not embed literal `response_model=`/`operation_id=` tokens

## Out of scope
- Any workflow change for 28a UNLESS decision gate fires (≥3/5)
- More than two routers (one verify + one new) per compound 24b
- Touching the Session 19 SHA round-trip — working as designed
