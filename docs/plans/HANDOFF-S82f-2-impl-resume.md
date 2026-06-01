# Resume — vendor_risk S82f-2 implementation

## Where I am

S82f-2 design phase complete in the previous session. Two commits landed:

- `b5328c9` — ext-04-clean-cdn rebaselined LOW→MEDIUM. Re-run via
  existing harness (`run-a58a4fcad461`, tier=MEDIUM, 39.5s). **EXT now
  10/10 tier-match (100%).** Calibration log row 4b appended; row 4
  preserved as historical record.
- `8947e16` — **ADR-004 Accepted.** vendor_risk INT runtime-flag flow.
  Option B (sticky PATCH on AISystem row with 24h TTL, server-side
  persisted). Path A resolved (add `TPRM_ANALYST` to ROLES, don't
  collapse to `audit`). File: `docs/adr/ADR-004-vendor-risk-int-runtime-flag-flow.md`.

Engine sha at start of this session: `8947e16`. Tree clean (untracked
`team-portal/.claude/` is unrelated; leave it).

## Decisions already made (don't re-litigate)

- **Flag-flow design:** Option B from ADR-004. Sticky PATCH on
  `/api/ai-systems/{id}/runtime-flags`, server-side persistence in
  `data/ai_systems.jsonl`, 24h default TTL, single-signer (CISO) for
  now with `tprm-analyst` added in parallel.
- **Role-mismatch resolution:** Path A. Add `TPRM_ANALYST` to
  `middleware/auth.py:ROLES` + provision `DEMO_USER_TPRM_ANALYST_HASH`
  + add demo user. Do NOT collapse to `audit` — that would conflate
  second-line risk function (TPRM analyst) with third-line assurance
  (audit) and Phase 9 would force the split anyway.
- **ext-04 rebaseline:** locked. Don't second-guess. Agent behavior is
  correct; the dataset was the outlier.
- **assert_no_egress() priority:** defense-in-depth, not Sev-1. The
  rego gate is the primary control and is proven (8/8 DENY in S82f-1c).
  Wire it in the same session as Option B, but it's not the critical
  path for unblocking calibration.

## Key files to load

### ADR + design
- `docs/adr/ADR-004-vendor-risk-int-runtime-flag-flow.md` — **read first**.
  Section 6 (Files to Add or Modify) is the implementation checklist;
  Section 5 (Consequences) is the test plan; Section 8 (Open Questions)
  has carry-overs that are NOT closed by this work (TTL tuning for Phase 9).

### Files to modify (per ADR-004 Section 6)
- `domain/models.py` — add `RuntimeFlags` Pydantic v2 model;
  add `runtime_flags: Optional[RuntimeFlags] = None` to `AISystem`
- `storage.py` — add `read_system_runtime_flags(system_id)` and
  `patch_system_runtime_flags(system_id, flags)` via canonical
  `_append_jsonl` / `_read_jsonl` pattern
- `domain/agent_runner.py:200-205` — dispatcher policy_evaluate call site.
  Inject persisted flag values into `input_data` for INT systems
  (effective_system_id starts with `"sys-vendor-risk-int-"`)
- `api/ai_system_edit.py` — new route
  `PATCH /api/ai-systems/{id}/runtime-flags`, RBAC-gated to `ciso`
  (and later `tprm-analyst`); emits audit chain event at PATCH time
- `middleware/auth.py:49` — `ROLES` tuple → append `"TPRM_ANALYST"`;
  add `DEMO_USER_TPRM_ANALYST_HASH` to env + bootstrap (mirror existing
  CISO demo-user pattern)
- `policies/vendor-risk-int.rego` — **no change** (the role string
  `"tprm-analyst"` already matches what auth will now emit; the rego is
  correct)
- `docs/SOP-agent-onboarding.md` Phase 8 — add the three-step failure-mode
  drill sub-step (attest → ALLOW; expire → DENY; re-attest → ALLOW)
- `agents/vendor_risk/eval/run_calibration.py` — pre-flight PATCH the
  flags before INT fixtures submit; post-flight clear (or let expire)
- `agents/vendor_risk/agent.py` — wire `assert_no_egress()` on INT
  execution path (defense-in-depth)

### Reference
- `policies/vendor-risk-int.rego:69-86` — the gate (read-only)
- `docs/sop-vendor-risk/07-staged-calibration-log.md` — INT 0/8 LLM
  behavior; calibration thresholds recommendation
- `agents/vendor_risk/eval/dataset-internal.jsonl` — 8 INT fixtures to
  re-run once flags wire
- `CLAUDE.md` — 4 new 2026-06-01 rules from S82f-1c still apply

## Outstanding questions (need user input)

1. **Demo user provisioning detail.** When adding `TPRM_ANALYST`,
   should the demo user share the same App Service env-hash pattern
   used for other demo users (e.g., `DEMO_USER_TPRM_ANALYST_HASH`),
   and should there be a separate magic-link login route, or piggyback
   on the existing demo login flow?
2. **TTL default — 24h confirmed for calibration?** ADR-004 recommends
   24h for calibration and 4-8h for production. S82f-2 only needs the
   calibration default. Lock at 24h or pick a different starting value?
3. **Order of operations for AssertNoEgress.** Wire it before the
   PATCH endpoint is built (defensive-first), after (calibration-first),
   or in parallel? ADR is silent; my read is "in parallel" — they
   touch different files.

## Next concrete actions (in order)

1. Add `RuntimeFlags` model in `domain/models.py` + extend `AISystem`.
2. Add `storage.read_system_runtime_flags()` and
   `storage.patch_system_runtime_flags()`. Test locally:
   `python -c "from storage import *"` passes.
3. Add `PATCH /api/ai-systems/{id}/runtime-flags` route in
   `api/ai_system_edit.py`. RBAC `ciso`. Emits audit chain event.
4. Patch dispatcher (`domain/agent_runner.py:200`) to inject flags for
   INT systems.
5. `middleware/auth.py` ROLES extension + `DEMO_USER_TPRM_ANALYST_HASH`
   env + bootstrap.
6. Wire `assert_no_egress()` on INT execution path
   (`agents/vendor_risk/agent.py`).
7. Update `docs/SOP-agent-onboarding.md` Phase 8 with the failure-mode
   drill sub-step.
8. Update `deploy/build-zip.py::INCLUDE` audit — do all new modules
   land in the zip? (Per 2026-06-01 rule: eager-imported top-level
   packages and deferred-execution imports both need INCLUDE entries.)
9. **STAGED deploy.** Confirm `/api/health` returns ready, then PATCH
   the INT system's runtime flags with `attested_by=demo-ciso`,
   `justification="S82f-2 calibration"`.
10. Update `agents/vendor_risk/eval/run_calibration.py` to drive the
    flag lifecycle.
11. Re-run 8 INT fixtures. Update
    `docs/sop-vendor-risk/07-staged-calibration-log.md` row 11-18.
12. Add regression test in `tests/` (or wherever the project's policy
    tests live): "vendor_risk INT with required flags unset → DENY @
    policy_gate" — directly satisfies ADR-004 Section 5 SOP Phase 8
    drill requirement.
13. Lock thresholds in `agents/vendor_risk/eval/thresholds.json`.
14. Commit per logical unit; at end, run `/verify` and update
    `ARCHITECTURE.md` if vendor_risk surfaces there.

## Engine state at session start

- sha: `8947e16` — STAGED (assumed; redeploy after step 8)
- `/api/agent-runs` + `/api/agent-runs/{run_id}` live (role-gated)
- SDK keys (kept per user): `slk_b3aebe21` (ext) / `slk_7e903e17` (int)
- `/home/data/agent_runs.jsonl` empty at session start
- ext-04 dataset MEDIUM-labeled; harness proven against new label

## Operator session cookie

To re-run the calibration harness:
- `AIGOVERN_BASE_URL=https://aigovern.sandboxhub.co`
- `AIGOVERN_COOKIE=aigovern_session=<value>` — fetch from
  Application → Cookies for demo-ciso login
- See `agents/vendor_risk/eval/run_calibration.py:13-22` for env contract

## Working rules in effect

- Project `CLAUDE.md` — read it. 4 new 2026-06-01 rules from S82f-1c:
  - deferred-execution imports are deploy dependencies → audit
    `deploy/build-zip.py::INCLUDE` for any new top-level package
  - operator role must thread from session cookie to policy_engine →
    when adding the runtime-flag injection, mirror the operator_role
    threading pattern (don't drop the role field)
  - persistence paths via DATA_ROOT → any new JSONL store must use
    the canonical pattern from `domain/audit_chain.py`
  - INT rego enforces no-egress at the boundary → the runtime
    `assert_no_egress()` is defense-in-depth, not primary
- Global `~/.claude/CLAUDE.md` — strong typing, Pydantic v2, parallel
  async, sub-agents for independent workstreams
- `from __future__ import annotations` at top of every Python file
- `python -c "import <module>"` must pass before next file
- Anthropic streaming for `max_tokens > 2000` (not relevant here; INT
  is no-egress)
- JSONL via `storage.py` only

## Token budget

This is **Implementation** (≈ Refactoring shape per the workflow band
table). Normal < 500K; Review Required at 500K-1M. Spawning
implementer subagents for the independent file changes (steps 1, 2, 5,
6 can run in parallel) keeps the main context lean. After the parallel
batch, code-reviewer + security-reviewer in parallel before the deploy
step.

## Confidence

High that the ADR captures the right design. Medium that the
implementation will fit in 1 session — the file count is moderate (8
files, but most edits are small) and the test/deploy cycle adds ~30
min. If it spills, the next session picks up at step 9 (deploy) with
all code committed.
