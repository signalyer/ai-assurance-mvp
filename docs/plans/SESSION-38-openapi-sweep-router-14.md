# SESSION-38 — Parallel Tier 1 batch sweep (5 routers) + Tier 2 verify batch + 28a observation #5

## Big shift this session
**Compound 24b amended in S37 closeout: per-router → per-coupling-tier.**
This session executes the first parallel batch sweep. Target outcome:
**counter 22 → 27/40 in one session** (Tier 1 batch of 5) plus **Tier 2
verify of 2** (potentially → 29/40).

## Carryover from S37
- Counter **22/40 fully typed**. Partials bucket effectively dry per S37 audit.
- 28a observation #4 = YES (bb2a520). Tally **6/9** closeouts fired. **S37 closeout commit `8e97454` is observation #5 — decision gate this session.**
- 28c (NEW): batch verification audits when partials-staleness is systemic.

## Step 0 — Compound 28a observation #5 (DECISION GATE, ≤2 min)
```bash
gh run list --commit=8e97454 --limit 5
```

Tally update of last 5 closeouts (S33-S37):
| Session | Closeout commit | Mix type | Triggered deploy? |
|---|---|---|---|
| S33 | (prior data) | (prior) | YES |
| S34 | (prior data) | doc-only modify | NO |
| S35 | `8933b34` | doc-only modify | NO |
| S36 | `bb2a520` | modify + delete + add | YES |
| S37 | `8e97454` | modify + delete + add | (fill at S38 start) |

**Decision rule:** if S37 fired → 3/5 last closeouts fired → schedule
dedicated `paths-ignore` fix as S39 Track A (likely root cause: file
delete+add bypasses glob). If S37 did NOT fire → 2/5 → observation
continues, gate moves to S38 closeout commit (obs #6).

## Step 1 — Tier 2 verify batch (parallel `Explore` agents)
Spawn **2 Explore subagents in one message** to confirm both partials
are 26a-final (no code change needed):

**Agent A:** Verify `api/reports.py` is 26a-conformant final state.
- Read full file, list each route's response_model/operation_id
- Confirm 3 export endpoints (.json/.csv/.pdf) are bare-by-design Response subclasses
- Confirm S26 ARCHITECTURE entry matches current file state
- Return: PASS/FAIL with route-by-route table

**Agent B:** Visual check `api/assurance_model.py` (5/12/12 grep
over-counts per S37 audit).
- Read full file, distinguish actual `response_model=`/`operation_id=`
  decorator usage from docstring/comment mentions
- Return: true count + sweep status (final / partial / needs work)

If both confirm 26a-final → counter +2 → **24/40**.
If either needs sweep work → fold into Tier 1 batch below.

## Step 2 — Tier 1 batch sweep (parallel `implementer` subagents)
**Pre-flight grep gate (≤2 min):** Run consumer-coupling check on all
Tier 1 candidates:
```bash
for f in agent_notifications metrics traces evaluate assessment demo_run aws_demo framework usage; do
  echo "=== api/$f.py ===" ; grep -rE "/api/[^\"']*$f" static/ team-portal/src/ 2>/dev/null | head -3
done
```
Any router with live SPA consumer → drop to Tier 3 for a later session.
Goal: confirm 5 truly zero-coupling routers for the batch.

**Spawn 5 `implementer` subagents in one message** (parallel). Pick the
5 simplest of: `agent_notifications` (1 SSE), `metrics` (1 Prometheus),
`traces` (1), `evaluate` (1), `assessment` (2), `usage` (3). Each
agent's prompt template:

```
Apply the locked S25-31 OpenAPI sweep pattern to api/<ROUTER>.py:
1. Read the router end-to-end. Read its domain dependencies.
2. For each route:
   - JSON-returning → draft strict Pydantic v2 model per compound 27a
     (list[dict] only for asymmetric/polymorphic payloads)
   - SSE/binary/204 Response subclass → operation_id only per 26a;
     document the gap in module docstring (prose-style per 28b — NO
     literal `response_model=` or `operation_id=` tokens)
   - operation_id convention: <prefix>_<verb>[_<noun>]
3. Add `from __future__ import annotations` if missing.
4. `python -c "import api.<ROUTER>"` must pass.
5. Run 24c probe (grep -cE '^@router\.', grep -c 'response_model=',
   grep -c 'operation_id=') AND visual confirm — return final counts.
6. Return: list of changes + final 24c counts + any notes.

Do NOT regen the OpenAPI spec — main session does that once after all
5 land.
Do NOT commit — main session does single Track A commit covering all 5.
```

## Step 3 — Aggregate + spec regen + Track A commit
After all 5 implementers return:
1. Visual review each diff (5 small files)
2. Run `python scripts/export_openapi.py` ONCE (24d, single regen for all 5)
3. Single Track A commit:
   `"Feat: SESSION-38 Track A — Tier 1 batch sweep (5 routers via parallel implementers)"`

## Step 4 — Track B closeout
- ARCHITECTURE.md S38 entry: counter → 27/40 (or 29/40 if Tier 2 also bumps); 28a obs #5 outcome + gate decision; first-ever batch sweep notes (parallel pattern worked / hit issues)
- New `docs/plans/SESSION-39-*.md`:
  - If 28a gate fired: S39 = paths-ignore fix (Track A workflow change)
  - If not: S39 = second Tier 1 batch (remaining 4 untouched: demo_run, aws_demo, framework, usage if not all 5 picked above + start CISO Console scaffold in parallel worktree)
- Delete this plan file
- Commit + push

## Parallel work outside this session
- **CISO Console scaffold (A5)** — should start in `phase/cm-ciso-console` worktree this session or S39. Independent of sweep. Owner: separate execution context. Engine routes consumed by Console are already typed.
- **App Insights + staging slot (A15)** — Azure provisioning track. Background, no code dependency.

## Compound rules in force
- 24a: per-router sweep core — still valid for Tier 3
- **24b (AMENDED in S37)**: per-coupling-tier; Tier 1 batches up to 5
- 24c: grep-recount + visual check (S37 lesson)
- 24d: regen spec via `scripts/export_openapi.py` ONCE per session even for batches
- 25a/25b: SPA consumer compat check (now the pre-flight gate for tier assignment)
- 26a: bare-by-design for binary/204/SSE
- 27a: strict-by-default Pydantic v2
- 28a: paths-ignore observation — **decision gate at S38 Step 0**
- 28b: docstrings prose-style, no literal `response_model=`/`operation_id=`
- **28c (NEW from S37)**: batch verification audits when staleness is systemic — Tier 2 batch this session

## Out of scope
- Tier 3 routers (guide.py, demo.py, demo_control.py) — separate session each
- Any workflow change UNLESS 28a gate fires
- CISO Console code (parallel worktree, not this conversation)
