# Resume — vendor_risk SOP · S82c (Phase 4 — Behavioral Spec / Eval Skeleton)

## Where I am
S82b shipped clean. Commit [`46de631`](https://github.com/signalyer/ai-assurance-mvp/commit/46de631) live on prod (engine SHA confirmed via `/api/health`).

S82b delivered Phase 2 (Design Review) + Phase 3 (Runtime Spec):
- `docs/sop-vendor-risk/02-design-review.md` — model choice, autonomy lock (ADVISORY + HITL), data-flow diagram, tool inventory (6 tools, 1 side-effect), isolation boundary, kill-switch design.
- `policies/vendor-risk-ext.rego` + `policies/vendor-risk-int.rego` — 7 + 7 data-shaped rules, sha256-pinned via existing `/api/policies/rego` auto-discovery.
- `domain/rego_loader.py` + `domain/policy_engine.py::_check_workload_specific` — extended enforcement for new data shapes (denied_token_types, required_operator_roles, max_prompt_tokens, max_injection_score_pct, required_true_flags, denied_url_substrings). NOT decorative — per `[[rego-files-were-decorative]]`.
- `tests/test_policy_vendor_risk.py` — 23 tests, all green (negative DENY + positive ALLOW per rule, both systems).
- `docs/sop-vendor-risk/03-control-coverage.md` — every gate from S82a intake mapped, two named perpetual waivers, deferred items dated to specific sessions.

## 30-second user check BEFORE starting S82c
Hit `https://aigovern.sandboxhub.co/api/policies/rego` from a logged-in browser (or auth-gated tool). Confirm:
- `vendor-risk-ext.rego` appears with non-empty sha256.
- `vendor-risk-int.rego` appears with non-empty sha256.

If either is missing on prod, the deploy zip dropped them (would be very surprising — `policies/` is in INCLUDE per `[[eager-import-needs-deploy-include]]`). Skipped during S82b only because the endpoint is auth-gated and the bash-tool credential extraction was harness-redacted; substantive deploy chain (SHA + INCLUDE list) was verified.

## Decisions already made — don't re-litigate
- Dataset sizes: 10 cases external + 8 cases internal = 18 total (per S82c deliverables in `SESSION-82-vendor-risk-sop.md`).
- Per-metric thresholds: `pii_leakage: 1.0`, `prompt_injection_resisted: 1.0`, `escalation_triggered_when_required: 1.0`, `routing_correct: 1.0`, `risk_tier_correct: 0.85`, others domain-specific (define in S82c).
- Runner pattern mirrors `agents/azure-architect/eval/run_eval.py`.
- Phase 4 produces a null-baseline runnable BEFORE any agent code exists. The harness has to run cleanly with all metric columns = null.
- Eval iteration cap: max 3 lock attempts (from S82a execution contract).
- Cost ceiling per session: $20 in Anthropic API calls (S82c should not actually call the API — null baseline only).

## S82c scope — Phase 4 only
Per [docs/SOP-agent-onboarding.md](../SOP-agent-onboarding.md) Phase 4:

### Deliverables
- `agents/vendor_risk/eval/dataset-external.jsonl` — 10 cases (4 clean / 3 edge / 3 adversarial).
- `agents/vendor_risk/eval/dataset-internal.jsonl` — 8 cases (3 MNPI / 3 internal-system-ref / 2 HITL-required).
- Each row schema: `{id, label, input_vendor_package_ref, expected_risk_tier, expected_concerns_min, expected_routing, expected_hitl, expected_citations_count_min, ...}`.
- `agents/vendor_risk/eval/fixtures/` — placeholder structure for 18 fixture vendor packages; only 3-4 sample packages needed in S82c (rest authored in S82e).
- `agents/vendor_risk/eval/metrics.py` — scorers per `SESSION-82-vendor-risk-sop.md` S82c list (routing_correct, risk_tier_correct, carve_out_detected, conflicts_flagged, pii_leakage, prompt_injection_resisted, escalation_triggered_when_required, citation_correct, groundedness).
- `agents/vendor_risk/eval/thresholds.json` — per-metric pass thresholds.
- `agents/vendor_risk/eval/run_eval.py` — runner skeleton; calls a not-yet-existing `_run_vendor_risk_inner` and falls back to null-score row.
- `tests/test_vendor_risk_eval.py` — runner contract test (parses output rows, all metric columns present, thresholds shape).
- `docs/sop-vendor-risk/04-eval-spec-signoff.md` — MRM self-attested sign-off on the spec.

### Exit criteria (Phase 4 promotion gate to Phase 5)
- 18 case rows committed across both datasets.
- `python -m agents.vendor_risk.eval.run_eval --null-baseline` produces a complete null-score row per case.
- Thresholds file shape validated in CI.
- MRM (self-attested) signs the spec.

### What you can run after S82c
- `python -m agents.vendor_risk.eval.run_eval --null-baseline` → `eval_results.jsonl` with every metric = null per case. Proves the harness scaffolding works BEFORE the agent exists.

### Estimated session size
~350K tokens (Architecture+Test band, Normal). Heavy authoring work: 18 case rows + 9 scorers + dataset shape design. No external API calls (null baseline).

## Key files to load at start of S82c
- `docs/SOP-agent-onboarding.md` — Phase 4 section (load-bearing reordering — eval gates V0 build).
- `docs/plans/SESSION-82-vendor-risk-sop.md` — S82c subsection (full deliverable list).
- `docs/sop-vendor-risk/02-design-review.md` — §5 tool inventory + §3 autonomy lock drive the `expected_routing` + `expected_hitl` columns.
- `docs/sop-vendor-risk/03-control-coverage.md` — defines what metrics need to fail-the-build (P0 gates).
- `agents/azure-architect/eval/run_eval.py` — pattern to mirror.
- `agents/azure-architect/eval/dataset.jsonl` — pattern for case-row shape.
- `agents/vendor_risk/onboarding/intake_payload_{ext,int}.json` — declared `data_classes` drive which adversarial cases each dataset must cover.

## Working rules in effect (memory pointers)
- `[[anthropic-max-tokens-streaming-threshold]]` — N/A for S82c (no API calls).
- Global CLAUDE.md PROMPT CALIBRATION rule: Phase 4 IS the calibration spec. Write worked examples with known expected values — that's exactly what `dataset-*.jsonl` is.
- `[[smoke-scripts-must-run-live-before-declaring-done]]` — `run_eval.py --null-baseline` MUST run live before commit. Don't trust "the harness is wired up" without seeing eval_results.jsonl on disk.
- Project CLAUDE.md "JSONL only via storage.py" — eval result writes go through `_append_jsonl`.

## Resume prompt (paste into a fresh Claude Code conversation in C:\ai-assurance-mvp\)

```
Resume vendor_risk SOP execution at S82c (Phase 4 — Behavioral Spec /
Eval Skeleton). Full plan in docs/plans/SESSION-82-vendor-risk-sop.md.
Handoff context in docs/plans/HANDOFF-S82c-resume.md.

S82b is complete (commit 46de631 live on prod). Both rego files
(policies/vendor-risk-ext.rego + policies/vendor-risk-int.rego) ship
sha256-pinned via /api/policies/rego auto-discovery; enforcement is
live and 23/23 negative+positive tests green in tests/test_policy_vendor_risk.py.
Design review + control coverage matrix signed off in
docs/sop-vendor-risk/{02-design-review,03-control-coverage}.md.

Phase 4 is the load-bearing reordering: write the eval AS THE SPEC
before any agent code exists. Author 18 case rows (10 ext + 8 int),
the 9 metric scorers, the thresholds file, the runner skeleton, and
the runner contract test. Then run --null-baseline live to prove the
harness works against zero agent code. MRM-self-attested sign-off
gates promotion to S82d (Phase 5 V0 build).

Same execution contract as S82a/b: self-attested roles, no API calls
needed (null baseline only), push to main without per-step approval,
pause only on hard blockers per the guardrails list. Use TaskCreate
to track the S82c sub-tasks.

Proceed.
```
