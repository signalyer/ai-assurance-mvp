# Resume — vendor_risk SOP · S82e (Phase 6 — Iterate × Lock Baseline)

## Where I am
S82d shipped. V0 agent body is implemented and the first real eval
baseline is on disk:
[`agents/vendor_risk/eval/baseline.json`](../../agents/vendor_risk/eval/baseline.json)
(run_id `vendor-risk-eval-2026-06-01T143329806832Z`, 18 cases, mode=live).

### Honest baseline (per-metric pass rate over 18 cases)

| Metric | Pass | Threshold | Tier | Status |
|---|---:|---:|---|---|
| `pii_leakage` | 18/18 (100%) | 1.0 | P0 | PASS |
| `prompt_injection_resisted` | 18/18 (100%) | 1.0 | P0 | PASS |
| `routing_correct` | 18/18 (100%) | 1.0 | P0 | PASS |
| `carve_out_detected` | 17/18 (94%) | 1.0 | P0 | **1 miss** |
| `escalation_triggered_when_required` | 16/18 (89%) | 1.0 | P0 | **2 misses** (1 spurious on int-01, 1 missed) |
| `conflicts_flagged` | 15/18 (83%) | 0.9 | P1 | below |
| `risk_tier_correct` | 3/18 (17%) | 0.85 | P1 | far below — model defaults to MEDIUM |
| `citation_correct` | 0/18 (0%) | 0.9 | P1 | **agent not emitting doc_ids in citations** |
| `groundedness` | 0/18 (0%) | 0.8 | P2 | follows from citations=0 |

Suite status: `FAIL` (expected — V0 is the floor, S82e is the climb).
Zero PASS cases (every case fails on at least citation/groundedness).

## What's done in S82d (committed)

### Code
- `agents/vendor_risk/prompts.py` — SYSTEM_PROMPT_EXT/INT with the JSON
  output schema inlined per CLAUDE.md JSON Schema Rule, TOKEN_BUDGETS
  (4096 streaming-mandated), 6 TOOL_SPECS in Anthropic format,
  build_user_message helper, system_id constants.
- `agents/vendor_risk/tools.py` — six tool implementations:
  `search_tprm_corpus` (token-overlap retrieval — V0 stand-in for BM25),
  `lookup_subprocessor_risk`, `parse_vendor_document` (closure-bound to
  fixture meta), `check_regulatory_requirements`, `compare_to_baseline`,
  `escalate_to_human` (SIDE EFFECT — flips `state["escalation_triggered"]`).
  Plus `load_fixture_meta` + `detect_internal_system_tokens` helpers.
- `agents/vendor_risk/agent.py` — three entry points share one body:
  - `_run_vendor_risk_inner(case)` — sync eval seam consumed by
    `run_eval._invoke_agent_or_none`. Bypasses the SignalLayer decorator
    chain so the eval runs offline against the inner reasoning.
  - `_run_review_inner(prompt, **kw)` — async runner seam for the SPA
    dispatcher (accepts `event_sink` per S80 LBD-1).
  - `run_vendor_risk` — decorated CLI surface
    (`@policy_gate → @scrub_pii → @guardrails → body`).
  - `_execute_run` is the shared streaming tool-use loop, 5-turn cap,
    output coercion (handles JSON, code-fence-wrapped JSON, and
    invalid-JSON fallback).
- `agents/vendor_risk/cli.py` — `python -m agents.vendor_risk.cli
  --fixture <name> --system ext|int`.
- `agents/_registry.py` — `vendor_risk` registered with
  `demo_only=True`, `default_system_id=sys-vendor-risk-ext-001`,
  `module_path=agents.vendor_risk.agent`, `entrypoint=run_vendor_risk`,
  `inner_entrypoint=_run_review_inner`.

### Corpus seed (12 markdown + 2 JSON)
- `corpus/manifest.json` — 13 doc entries indexed by doc_id.
- `corpus/tprm-policy.md`, `tprm-rubric.md`, `carve-out-playbook.md`
- `corpus/regulations/{gdpr-art28,dora,nydfs-500,ffiec-appendix-j,glba,scc-2021,soc2-trust-services}.md`
- `corpus/assessments/{2025q1-acmecorp,2024q4-bytehost,2024q3-quantumlog}.md`
- `corpus/subprocessor-risk-db.json` — 11 vendors incl. 3 HIGH-risk
  (EuroDataPro carve-out pattern, NorthPole non-adequate region,
  RogueStore breached).
- `corpus/internal-systems-inventory.json` — 5 internal systems for
  INT routing detection.

### Fixtures
- `agents/vendor_risk/eval/fixtures/_generate.py` — one-shot
  deterministic generator. Run from repo root:
  `python -m agents.vendor_risk.eval.fixtures._generate`.
- All 18 fixture `meta.json` files written. Each carries:
  `case_id, vendor_name, category, scenario, expected_anchors,
  adversarial_notes, subprocessors[], regulatory_scope[], documents{}`.

### Tests
- `tests/test_vendor_risk_unit.py` — **39/39 green**. Covers each
  tool (happy + error paths), output-coercion contract (valid JSON,
  code-fence, parse-failure), 18-fixture parametrised resolution test,
  registry binding.

### Eval baseline
- `agents/vendor_risk/eval/baseline.json` — 35 KB, per-case + per-metric.
- `data/vendor_risk_eval_runs.jsonl` — append-only run log (this run is
  the first real entry).

## Decisions made in S82d — don't re-litigate
- Token-overlap retrieval scoring instead of `rank-bm25` in V0.
  Stand-in. S82e can swap if calibration shows quality demands it.
- Eval seam (`_run_vendor_risk_inner`) bypasses the SignalLayer
  decorator chain. Eval inputs are synthetic fixtures (no real PII);
  the governance perimeter is tested by S82b's rego tests and S82f's
  staged run, not by every eval invocation. This lets the eval run
  offline without SL_* env.
- `escalate_to_human` is the ONE side-effect tool and tracks state via
  a closure-bound dict (`state["escalation_triggered"]`) rather than
  regexing the model's text output.
- `demo_only=True` on the registry entry. Flips to `False` only after
  S82i (per `[[sop-agent-onboarding]]`).
- Fixture `meta.json` schema is the canonical fixture format; the
  generator `_generate.py` is the source of truth. Add new cases there,
  not by hand-editing the meta files.

## S82e scope — Phase 6 (Iterate × Lock Baseline)

### Primary failure modes to attack (in priority order)

1. **`citation_correct` 0% — the agent is not populating the citations
   array with doc_ids.** Inspect 2-3 cases' raw assistant turns
   in the agent run to see whether the model is (a) not calling
   `search_tprm_corpus` at all on those cases, (b) calling it but not
   citing in the JSON, or (c) citing arbitrary strings instead of
   doc_id values. Fix in SYSTEM_PROMPT_EXT/INT — likely add a worked
   example showing `"citations": ["carve-out-playbook", "gdpr-art28"]`.
2. **`risk_tier_correct` 17% — model defaults to MEDIUM.** The rubric
   doc (`corpus/tprm-rubric.md`) exists but the agent isn't using it.
   Two paths: (a) inline rubric anchors directly into SYSTEM_PROMPT so
   the model doesn't need retrieval to access them; (b) make
   `search_tprm_corpus` first call in every run with query=rubric.
3. **`escalation_triggered_when_required` 89% — 1 spurious + 1 missed.**
   The spurious one (`int-01-mnpi-deal-context`) escalated when
   `expected_hitl=false` (MEDIUM tier). Tighten escalation criteria in
   the prompt: HITL is only for HIGH/CRITICAL residual or carve-out or
   MNPI+HIGH-residual — NOT every MNPI run.
4. **`conflicts_flagged` 83% — 3 misses, probably under-counting.**
   Likely related to the DPA/MSA conflict case (ext-07). Verify
   `parse_vendor_document` is being called for both docs.
5. **`carve_out_detected` 94% — 1 miss.** Identify which case (likely
   ext-05) and trace why.

### Deliverables (per Phase 6)
- Iteration log `agents/vendor_risk/eval/iteration-log.md` —
  per-iteration: change description + per-metric score delta + decision
  (keep/revert). Required by global CLAUDE.md PROMPT CALIBRATION rule.
- Tighten `SYSTEM_PROMPT_EXT` / `SYSTEM_PROMPT_INT` until every metric
  clears its threshold on ≥80% of cases.
- Grow datasets to ~22-25 cases as new failure modes surface.
- Author remaining adversarial fixture content (richer document bodies
  in `_generate.py`) — the V0 generator emits minimal bodies that may
  not exercise some failure modes.
- Lock: version-tag dataset as `dataset-v1.jsonl`.
  `docs/sop-vendor-risk/06-lock-signoff.md` self-attested.
- `tests/test_vendor_risk_eval_regression.py` — CI gate that fails when
  any metric regresses below current baseline. Wire into the CI run.

### Exit criteria (per plan)
- All metrics clear threshold on ≥80% of cases.
- Regression test in CI passes against current code.
- Iteration log committed with calibration record per global CLAUDE.md.
- Locked dataset version tagged.

### Estimated session size
~500K tokens (Refactor band, Review Required threshold). Heaviest work
is iteration cycles — each cycle runs the full 18-case suite (~$2-4
Anthropic). Budget 3-5 cycles. Total session API cost: ~$10-20.

## Key files to load at start of S82e
- [`agents/vendor_risk/eval/baseline.json`](../../agents/vendor_risk/eval/baseline.json) — what we're climbing from.
- [`agents/vendor_risk/prompts.py`](../../agents/vendor_risk/prompts.py) — primary surface to tune.
- [`agents/vendor_risk/agent.py`](../../agents/vendor_risk/agent.py) — `_coerce_output` is where parse failures land; may need looser tolerance.
- [`agents/vendor_risk/eval/metrics.py`](../../agents/vendor_risk/eval/metrics.py) — re-read to confirm scorer semantics before "fixing" the agent.
- [`docs/SOP-agent-onboarding.md`](../SOP-agent-onboarding.md) — Phase 6 checklist.

## Working rules in effect
- `[[anthropic-max-tokens-streaming-threshold]]` — STILL in effect.
  Synthesis runs at 4096; streaming context manager mandatory.
- `[[bare-except-hides-broken-integrations]]` — every tool failure is
  printed to stderr; never swallow.
- Project CLAUDE.md JSON Schema Rule — the schema in SYSTEM_PROMPT is
  load-bearing. When you tighten it, run unit tests immediately to
  make sure `_coerce_output` still parses.
- Project CLAUDE.md "scrubber before tracer" — unchanged. Eval seam
  bypasses but documented.

## Resume prompt (paste into a fresh Claude Code conversation in C:\ai-assurance-mvp\)

```
Resume vendor_risk SOP execution at S82e (Phase 6 — Iterate × Lock Baseline).
Full plan in docs/plans/SESSION-82-vendor-risk-sop.md. Honest baseline
in agents/vendor_risk/eval/baseline.json (S82d landed; suite FAILs, 0/18
pass, but P0 PII/injection/routing are 100%).

Primary failure modes to attack in priority order:
  1. citation_correct 0% — agent isn't populating citations[] with doc_ids
  2. risk_tier_correct 17% — model defaults to MEDIUM; inline the rubric
  3. escalation_triggered_when_required 89% — tighten HITL criteria
  4. conflicts_flagged 83% — verify multi-doc parsing on ext-07
  5. carve_out_detected 94% — investigate the one miss

Same execution contract as S82a-d: self-attested roles, push to main
without per-step approval, pause only on hard blockers. Use TaskCreate.
Anthropic streaming required. Budget ~$15 in API across 3-5 iteration
cycles. Author iteration-log.md per cycle.

Proceed.
```
