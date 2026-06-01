# Resume — vendor_risk SOP · S82d (Phase 5 — V0 Build + Baseline)

## Where I am
S82c shipped clean. Phase 4 (Behavioral Spec / Eval Skeleton) is signed
off in [`docs/sop-vendor-risk/04-eval-spec-signoff.md`](../sop-vendor-risk/04-eval-spec-signoff.md).

S82c delivered:
- `agents/vendor_risk/eval/dataset-external.jsonl` — 10 cases (4 clean / 3 edge / 3 adversarial)
- `agents/vendor_risk/eval/dataset-internal.jsonl` — 8 cases (3 MNPI / 3 internal-ref / 2 HITL-required)
- `agents/vendor_risk/eval/metrics.py` — 9 scorers (5 P0 / 3 P1 / 1 P2) with null-baseline support
- `agents/vendor_risk/eval/thresholds.json` — `v0-spec`, P0 metrics pinned at exact=1.0
- `agents/vendor_risk/eval/run_eval.py` — three modes: `--null-baseline`, `--outputs <path>`, default (raises until agent body exists)
- `agents/vendor_risk/eval/fixtures/` — 4 sample fixture `meta.json` files (rest authored in S82e)
- `tests/test_vendor_risk_eval.py` — 11 contract tests, all green
- `docs/sop-vendor-risk/04-eval-spec-signoff.md` — MRM-self-attested sign-off

Live null-baseline run: `NULL_BASELINE cases=18 passed=0 null=18` —
proves harness scaffolding works against zero agent code.

## Decisions already made — don't re-litigate
- P0 metrics (zero-tolerance): `pii_leakage`, `prompt_injection_resisted`,
  `escalation_triggered_when_required`, `routing_correct`, `carve_out_detected`.
- P1 metrics: `risk_tier_correct` (0.85), `conflicts_flagged` (0.9),
  `citation_correct` (0.9).
- P2: `groundedness` (0.8, informational in S82d).
- Agent return-dict contract (the eval's expected shape): `system_id`,
  `risk_tier`, `concerns[]`, `conflicts[]`, `citations[]`,
  `retrieved_doc_ids[]`, `escalation_triggered`, `summary`,
  `mitigations[]`, `contract_clauses[]`. See `metrics.py::_flatten_output_text`.
- Runner expects `_run_vendor_risk_inner(case: dict) -> dict` exported
  from `agents/vendor_risk/agent.py`. Inner takes the dataset row,
  resolves the fixture, runs the chain, returns the structured dict.

## S82d scope — Phase 5 only
Per [`docs/SOP-agent-onboarding.md`](../SOP-agent-onboarding.md) Phase 5:

### Deliverables
- `agents/vendor_risk/agent.py` — `_run_vendor_risk_inner` + outer
  `run_vendor_risk` with project-canonical decorator chain.
- `agents/vendor_risk/prompts.py` — SYSTEM_PROMPT, TOKEN_BUDGETS,
  build_user_message, TOOL_SPECS (6 tools, Anthropic format). Model pin
  for ext = `claude-sonnet-4-6`. Streaming required (max_tokens > 2000
  per `[[anthropic-max-tokens-streaming-threshold]]`).
- `agents/vendor_risk/tools.py` — 6 tool implementations.
- `agents/vendor_risk/corpus/` — seed corpus (~10-15 docs minimum to
  exercise BM25 retrieval; full body in S82e).
- `agents/vendor_risk/cli.py` — `python -m agents.vendor_risk.cli --fixture <name> [--system ext|int]`.
- `agents/_registry.py` — register `vendor_risk` with `demo_only=True`
  initially (flips to False after S82i). MUST cite SOP per
  `[[sop-agent-onboarding]]`.
- `agents/vendor_risk/eval/baseline.json` — first real eval scores
  (some metrics WILL fail thresholds — that's the iteration starting point).
- `tests/test_vendor_risk_unit.py` — unit tests per tool.
- Wire `eval_scores` into agent return dict so `evaluate` SSE carries
  real numbers in dispatcher.
- Fill in the 14 missing fixture `meta.json` files only as needed to
  unblock the baseline run; full content in S82e.

### Exit criteria
- Unit tests green.
- `python -m agents.vendor_risk.cli --fixture 01-clean-saas --system ext`
  produces complete JSON output end-to-end.
- `python -m agents.vendor_risk.eval.run_eval` (no flags) runs the
  full 18-case suite end-to-end and writes `baseline.json` with real
  (non-null) scores. Some metrics expected to fail — fix in S82e.

### Estimated session size
~400K tokens (Refactor band, Normal). Heaviest work: prompts +
6 tool implementations + corpus seed. Includes Anthropic API calls
on the external path — budget ~$2-4 for the 10 ext cases.

## Key files to load at start of S82d
- [`docs/SOP-agent-onboarding.md`](../SOP-agent-onboarding.md) — Phase 5.
- [`docs/sop-vendor-risk/04-eval-spec-signoff.md`](../sop-vendor-risk/04-eval-spec-signoff.md) — the contract S82d implements against.
- [`agents/vendor_risk/eval/metrics.py`](../../agents/vendor_risk/eval/metrics.py) — defines the expected return-dict shape.
- [`agents/vendor_risk/eval/run_eval.py`](../../agents/vendor_risk/eval/run_eval.py) — `_invoke_agent_or_none` is the seam to wire into.
- [`agents/azure-architect/agent.py`](../../agents/azure-architect/agent.py) — pattern to mirror for decorator chain + tool loop.
- [`policies/vendor-risk-ext.rego`](../../policies/vendor-risk-ext.rego) + [`vendor-risk-int.rego`](../../policies/vendor-risk-int.rego) — the runtime constraints the agent must respect.

## Working rules in effect
- `[[anthropic-max-tokens-streaming-threshold]]` — IN EFFECT in S82d.
  vendor_risk synthesis will exceed 2K tokens; use streaming context
  manager.
- `[[eager-import-needs-deploy-include]]` — `agents/vendor_risk` already
  in INCLUDE list (S82a). Verify when adding corpus subdirs.
- `[[lazy-imports-skip-module-load-bootstrap]]` — if vendor_risk needs
  any module-load DDL, eager-import from `dashboard.py` lifespan.
- `[[deploy-zip-overwrites-runtime-data]]` — corpus content is CODE,
  data/ stays untouched.
- Project CLAUDE.md "scrubber before tracer" — decorator order must
  match canonical chain.

## Resume prompt (paste into a fresh Claude Code conversation in C:\ai-assurance-mvp\)

```
Resume vendor_risk SOP execution at S82d (Phase 5 — V0 Build + Baseline).
Full plan in docs/plans/SESSION-82-vendor-risk-sop.md. Handoff context in
docs/plans/HANDOFF-S82d-resume.md.

S82c is complete. The eval skeleton is in place and signed off
(docs/sop-vendor-risk/04-eval-spec-signoff.md). 18 case rows, 9 scorers,
v0-spec thresholds. `python -m agents.vendor_risk.eval.run_eval --null-baseline`
runs green; 11/11 contract tests green in tests/test_vendor_risk_eval.py.

Phase 5 implements the inner agent body against that locked contract:
agents/vendor_risk/agent.py::_run_vendor_risk_inner, prompts.py, tools.py
(6 tools), seed corpus, CLI, registry entry (demo_only=True), unit tests,
and the first real eval run that writes baseline.json. Some metrics
WILL fail their thresholds — that's the S82e iteration starting point.

Same execution contract as S82a-c: self-attested roles, push to main
without per-step approval, pause only on hard blockers. Use TaskCreate
to track sub-tasks. Anthropic streaming required (max_tokens > 2000).
Budget ~$4 in API calls.

Proceed.
```
