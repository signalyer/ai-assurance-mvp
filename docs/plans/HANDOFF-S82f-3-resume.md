# Resume — vendor_risk S82f-3 (post-S82f-2)

## Where I am

S82f-2 closed. INT calibration **unblocked**. Pre-baseline 0/8 → post-deploy
**8/8 fixtures cleared `policy_gate`** and ran to `chain.done`.

Five commits shipped (`f41ca70..4f9b917`):
- `77b3184` — RuntimeFlags model + storage overlay + repository fold
- `d4217d8` — PATCH runtime-flags endpoint + TPRM_ANALYST role
- `adb1a3f` — dispatcher injects runtime_flags for vendor_risk INT
- `590b920` — overlay regression suite (9 tests) + SOP Phase 8 drill +
  calibration pre-flight
- `4f9b917` — calibration log rows 11b–18b + ARCHITECTURE summary

Engine sha at calibration: `590b9205`. Tree clean (untracked
`team-portal/.claude/` is unrelated; leave it). All 35 targeted tests pass
(9 overlay + 23 policy + 3 deploy-completeness).

## Decisions already made (don't re-litigate)

- **Storage shape:** overlay at `data/system_runtime_flags.jsonl` with
  latest-wins + TTL-gated read, audit-chain `RUNTIME_FLAGS_ATTESTED` event
  emitted at PATCH time. Mirrors `_fold_runtime_status` precedent.
  `ai_systems.jsonl` was NOT mutated (it's intake-only per `repository.py:47`).
- **TTL default:** 24h (86400s) for calibration. Phase 9 will tighten to
  4–8h per ADR-004 §8 Q3 via `RUNTIME_FLAG_TTL_SECONDS` env.
- **Role:** Path A — `TPRM_ANALYST` added to `middleware/auth.py:ROLES`.
  Demo user `demo-tprm-analyst` requires `DEMO_USER_TPRM_ANALYST_HASH` app
  setting; not blocking because `demo-ciso` alone satisfies the rego role
  gate.
- **`assert_no_egress()` wiring:** deferred per ADR-004 §8 Q2.

## Outstanding (carry forward)

### 1. Tier-match calibration on INT — 2/8 (25%)

Post-unblock tier distribution:

| Fixture | Expected | Actual | Direction |
|---|---|---|---|
| int-01-mnpi-deal-context | MEDIUM | HIGH | over-tier |
| int-02-mnpi-active-deal | HIGH | HIGH | ✅ |
| int-03-mnpi-board-package | HIGH | CRITICAL | over-tier |
| int-04-intref-core-banking | HIGH | MEDIUM | under-tier |
| int-05-intref-trading-platform | HIGH | MEDIUM | under-tier |
| int-06-intref-customer-pii-export | HIGH | MEDIUM | under-tier |
| int-07-hitl-critical-resid | CRITICAL | MEDIUM | under-tier |
| int-08-hitl-high-resid-mnpi | HIGH | HIGH | ✅ |

Pattern: model is conservative on MNPI/board cues (over-tier), and is not
gripping internal-system-references as a HIGH/CRITICAL signal (under-tier).
The HITL-critical fixture flagged MEDIUM is particularly concerning if
production-bound.

This is Phase-6 iterate territory: SYSTEM_PROMPT_INT in
`agents/vendor_risk/prompts.py` needs sharpening on internal-ref
classification + (probably) a softer rubric on MNPI-as-board-package.
Worked-example calibration is the right approach (per global CLAUDE.md
PROMPT CALIBRATION rule).

### 2. `assert_no_egress()` wiring (defense-in-depth)

Defined and tested in `agents/vendor_risk/agent.py:assert_no_egress`, NOT
wired on `_execute_run`. Today INT still calls Anthropic (cloud), so
wrapping `_execute_run` would break every INT run. Sequence:
  1. Local-provider swap for INT (route to `local-simulated` per
     `domain/assurance_providers.py`), OR
  2. Build a loopback-only inference path, then wrap.

The rego gate is already proven enforcing (10 tests across two files); the
runtime tripwire is defense-in-depth not Sev-1. Track as an open finding.

### 3. `DEMO_USER_TPRM_ANALYST_HASH` provisioning

Out-of-band App Service config. Pick a password, generate the bcrypt hash,
set the app setting. Not blocking anything until you want a demo user with
the `tprm-analyst` role for testing dual-signer flows in Phase 10.

### 4. Calibration log rows 11–18 vs 11b–18b

Original rows 11–18 (the DENY baseline) preserved as historical record;
new rows 11b–18b carry the post-unblock LLM-successful runs. Consistent
with the ext-04 / 4b precedent. Audit-chain coverage now 18/18 (was 10/18).

## Key files

- `docs/adr/ADR-004-vendor-risk-int-runtime-flag-flow.md` — design source of truth
- `docs/sop-vendor-risk/07-staged-calibration-log.md` — rows 11b–18b + S82f-2 summary
- `tests/test_runtime_flags_overlay.py` — 9 tests, ADR §5 drill regression
- `agents/vendor_risk/prompts.py` — where the Phase-6 tier-match iteration would land
- `agents/vendor_risk/eval/dataset-internal.jsonl` — 8 INT fixtures to iterate against

## Next concrete action

Open an S82f-3 plan focused on INT tier-match iteration:
1. Read int-04 / int-05 / int-06 / int-07 fixtures; identify the
   internal-ref signal the model is missing.
2. Tighten `SYSTEM_PROMPT_INT` with an explicit
   internal-system-reference → HIGH rule + worked example.
3. Re-run only the under-tier fixtures via
   `python -m agents.vendor_risk.eval.run_calibration --case int-04-…`.
4. Iterate until ≥6/8 tier match; consider whether int-01/int-03 fixtures
   need rebaselining (over-tier MNPI calls may be the model being correct
   and the dataset being too lenient).

## Working rules in effect

- `~/.claude/CLAUDE.md` — session management, 60% compact rule, token bands,
  global standards
- `C:/ai-assurance-mvp/CLAUDE.md` — project rules incl. the four 2026-06-01
  rules from S82f-1c (DATA_ROOT, build-zip INCLUDE, operator_role
  threading, rego-vs-runtime layering); the new S82f-2 surfaces all comply.
- `from __future__ import annotations` at top of every Python file
- `python -c "import <module>"` smoke before next file
- Pre-flight PATCH attestation before any INT calibration run

## Engine state at session start

- sha: `4f9b917` pushed; CD pipeline running. Pre-S82f-3 verify: confirm
  `/api/health` returns `4f9b917...` derivative before driving any work.
- `/api/agent-runs` + `/api/agent-runs/{run_id}` live (role-gated)
- SDK keys (kept per user): `slk_b3aebe21` (ext) / `slk_7e903e17` (int)
- `data/system_runtime_flags.jsonl` carries demo-ciso 2026-06-01 attestation
  (expires 2026-06-02 19:03:34Z); harness will PATCH a fresh one pre-flight
  anyway.

## Operator session cookie

To re-run the calibration harness:
- `AIGOVERN_BASE_URL=https://aigovern.sandboxhub.co`
- `AIGOVERN_COOKIE=aigovern_session=<value>` — fetch from Application →
  Cookies for demo-ciso login (cookies rotate every 10 min via sliding TTL)
- The harness pre-flight PATCH'es runtime-flags automatically before
  submitting INT fixtures.

## Workflow + token bands

S82f-3 is **Refactoring/Calibration** — Normal < 500K, Review Required at
500K-1M. Sub-agents for independent workstreams; main context lean.
