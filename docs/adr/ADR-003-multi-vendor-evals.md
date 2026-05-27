# ADR-003 — Multi-vendor eval suite integration

- **Status:** Proposed (Session 57, 2026-05-27). Awaiting acceptance before scaffolding begins.
- **Deciders:** Praveen Kosuri
- **Supersedes:** none
- **Related:** ADR-001 (sidecar pattern), Session 05 (`providers/` Protocol layer), Session 09 (SDK evaluator hooks), Session 56 #1 (JSONL fallback at proxy layer), Session 57a (offline `run_eval.py` precedent)
- **Context anchors:** [providers/protocols.py:87-109](../../providers/protocols.py) (`EvaluatorBackend`), [providers/config.py:43-47](../../providers/config.py) (`EvalBackendChoice`), [evaluator.py](../../evaluator.py), [api/evals.py](../../api/evals.py), [team-portal/src/pages/evals/SystemEvalCard.tsx](../../team-portal/src/pages/evals/SystemEvalCard.tsx), [agents/azure-architect/eval/run_eval.py](../../agents/azure-architect/eval/run_eval.py)

---

## 1. Context

`EVAL_BACKEND` is currently a binary choice: `deepeval | noop` ([providers/config.py:43-47](../../providers/config.py)). DeepEval ships 5 metrics (hallucination, relevancy, faithfulness, toxicity, PII leakage) wrapped in [providers/backends/deepeval_evaluator.py](../../providers/backends/deepeval_evaluator.py), proxied through [evaluator.py](../../evaluator.py)'s `evaluate_response()` decorator. The seam is clean: any new backend file under `providers/backends/` that satisfies the `EvaluatorBackend` Protocol can drop in without touching engine code.

Users request the ability to **run eval suites from different vendors** — explicitly named: DeepEval (have), Promptfoo, Ragas, OpenAI evals, Anthropic evals. The use case is the platform's value proposition: "AI Assurance does not lock you into one eval framework — bring your own; we federate." This is consistent with the broader posture (self-hosted guardrails, posture-aware policies, .rego visibility) — pluralism *is* the product, not a complication of it.

### Critical finding before option analysis

Verification of each vendor's current API shape (WebFetch this session) surfaced a category mismatch the request implicitly missed:

| Vendor | What it actually is | Integration shape |
|---|---|---|
| **DeepEval** | Python lib, metric-per-test | Native import (have) |
| **Ragas** | Python lib, RAG-specific metrics | Native import |
| **Promptfoo** | Node.js CLI + YAML config | Subprocess shell-out + JSON parse |
| **OpenAI evals** ([github.com/openai/evals](https://github.com/openai/evals)) | Python harness + registry of YAML evals; README directs new users to the OpenAI Dashboard, suggesting OSS framework is lower-priority maintenance | Native import (heavy; ~150 MB deps; cherry-pick templates) |
| **Anthropic evals** ([github.com/anthropics/evals](https://github.com/anthropics/evals)) | **Dataset collection, not a harness.** 5 commits total. Model-written eval datasets from the "Discovering Language Model Behaviors with Model-Written Evaluations" paper. No API. No CLI. | **Cannot be a backend.** Source of test inputs to feed INTO another harness. |

This means a literal "5-backend" design is wrong. The correct shape is **4 vendor harnesses + 1 dataset source**, where Anthropic's datasets become reusable input feeding any of the 4 harnesses (most naturally DeepEval or a custom Ragas-style judge loop).

## 2. Decision drivers

| Driver                                                  | Weight |
|---------------------------------------------------------|--------|
| Slim-deploy invariant (ADR-001 §2; Session 12 outage)   | HARD CONSTRAINT |
| Preserve existing `EvaluatorBackend` Protocol contract  | High   |
| Federated metric vocab over forced normalization        | High   |
| Vendor-extension cost (adding #5+ later) is bounded     | High   |
| Subprocess/sidecar avoidance unless strictly required   | Medium |
| UI honesty — per-vendor metric shape, not fake parity   | High   |
| Auditability (each run cites vendor, version, raw scores) | High   |
| Cost gate per run (LLM-judge evals burn provider tokens) | Medium |

## 3. Options considered

### Option A — Normalize: single canonical metric set across all vendors

Force every backend to return the same 5-7 keys (e.g. `hallucination`, `faithfulness`, `relevancy`, `toxicity`, `pii_leakage`, `context_precision`). Each backend internally maps its native metrics into the canonical names.

| | |
|---|---|
| **Pros** | One UI card design. Easy comparison across vendors. No per-vendor frontend work. |
| **Cons** | **Loses the differentiation that justifies multi-vendor in the first place.** Ragas's `context_precision`/`recall` have no DeepEval analog; collapsing them into "relevancy" lies to the user. Promptfoo's assertions (`equals`, `contains-json`, `llm-rubric`) are deterministic; mashing them into a 0-1 score throws away the binary signal. OpenAI evals templates score on accuracy against a golden set — different paradigm entirely. Audit story degrades — auditors see "0.82 faithfulness" with no provenance back to *whose* faithfulness definition produced it. |
| **Verdict** | **Rejected.** Inconsistent with the platform's audit posture (every score must trace to its origin) and undermines the multi-vendor value prop. |

### Option B — Federate: each backend returns its native metric shape; UI renders per-vendor

Extend the `EvaluatorBackend` Protocol's `evaluate()` return type to include `vendor`, `vendor_version`, and `raw_metrics` (vendor-shaped dict). UI gets a per-vendor card component (`DeepEvalResultCard`, `RagasResultCard`, etc.). A small shared shape covers the audit envelope (timestamp, run_id, vendor, status), but metric keys are passed through unchanged.

| | |
|---|---|
| **Pros** | Honest. Auditable. Matches S57a's `run_eval.py` precedent (6 metric types from mixed sources, each cited). Extending to vendor #6 is bounded — one backend file + one card component. Aligns with [providers/backends/](../../providers/backends/) Protocol pattern that already proved out for scrubber/tracer/memory/rag. |
| **Cons** | More frontend work (one card per vendor, ~150 LOC each). No magic "average score across vendors" — but that was a fake number anyway. |
| **Verdict** | **Adopted.** Right answer. |

### Option C — Hybrid: federate raw, additionally compute a normalized "platform score"

Federate as in B, but ALSO derive a single platform-level score (e.g., weighted average of `faithfulness`-class metrics across whichever vendors ran). Surfaces both views.

| | |
|---|---|
| **Pros** | Gives stakeholders the "one number" they ask for in demos. Preserves audit detail beneath. |
| **Cons** | The weighted average is fiction — weights are arbitrary and the per-vendor metrics aren't actually measuring the same thing. Will be cited in slide decks as if it's a real score. Once published, very hard to retract. |
| **Verdict** | **Rejected for v1.** Revisit if buyer feedback demands a synthetic score, AND we can defend the weighting methodology in an audit. |

### Option D — Each vendor runs in a dedicated subprocess/sidecar (ADR-001 pattern)

Mirror ADR-001 (Garak): each vendor runs in its own container; engine talks to it over HTTP.

| | |
|---|---|
| **Pros** | Hard fault isolation. Heavy deps stay out of the dashboard zip. |
| **Cons** | Overkill for DeepEval/Ragas (lightweight Python libs, already in deploy). Operational cost: 4 new sidecars to maintain. Garak earned its sidecar because of 1.5 GB torch deps; DeepEval is ~80 MB and Ragas is ~50 MB. |
| **Verdict** | **Apply selectively, not universally.** See §4 — sidecar only where deploy-size is the deciding factor. |

## 4. Decision

**Adopt Option B (federated) with selective Option D (sidecar) for two specific vendors.** Specifically:

### 4.1 Protocol extension

Extend `EvaluatorBackend` in [providers/protocols.py](../../providers/protocols.py):

```python
@runtime_checkable
class EvaluatorBackend(Protocol):
    vendor: str             # stable identifier, e.g. "deepeval", "ragas"
    vendor_version: str     # the installed library/CLI version
    metric_schema: dict     # {metric_name: {type: "score"|"bool"|"label", range: ..., direction: "higher_is_better"|"lower_is_better"}}

    def evaluate(
        self,
        input_prompt: str,
        actual_output: str,
        context: list[str],
        expected_output: str = "",   # required by OpenAI evals templates
    ) -> dict:
        """Returns:
            {
              "vendor": str,
              "vendor_version": str,
              "raw_metrics": dict,        # vendor-native shape
              "status": "ok"|"partial"|"error",
              "duration_ms": int,
              "cost_usd_est": float,      # 0.0 when no LLM-judge calls
              "errors": list[str],
            }
        """
```

Old callers of the current 5-key dict shape get a thin adapter — `evaluate_response()` continues to return the legacy 5 keys when `EVAL_BACKEND=deepeval` so nothing in [api/evals.py](../../api/evals.py) or [agents/azure-architect/eval/run_eval.py](../../agents/azure-architect/eval/run_eval.py) breaks during cutover.

### 4.2 Config extension

Extend `EvalBackendChoice` in [providers/config.py:43-47](../../providers/config.py):

```python
class EvalBackendChoice(str, Enum):
    deepeval = "deepeval"      # native Python, have
    ragas = "ragas"            # native Python, RAG-focused
    promptfoo = "promptfoo"    # subprocess shell-out (Node CLI)
    openai_evals = "openai_evals"  # native Python, heavy
    noop = "noop"
```

`EVAL_BACKEND` becomes a comma-separated list (e.g. `EVAL_BACKEND=deepeval,ragas`). Validator splits + per-token enum validation. Empty/missing → defaults to `deepeval` (backward compat).

### 4.3 Per-vendor backend modules

| Vendor | Module | Integration shape | Sidecar? |
|---|---|---|---|
| DeepEval | [providers/backends/deepeval_evaluator.py](../../providers/backends/deepeval_evaluator.py) (exists) | Native import | No |
| Ragas | `providers/backends/ragas_evaluator.py` (NEW) | Native import; LLM-judge defaults to Claude via existing `ANTHROPIC_API_KEY` | No |
| Promptfoo | `providers/backends/promptfoo_evaluator.py` (NEW) | `subprocess.run(["promptfoo", "eval", "-o", tmpfile])` + JSON parse | **No** — Node binary baked into deploy image (~80 MB), small enough |
| OpenAI evals | `providers/backends/openai_evals_evaluator.py` (NEW) | Native import — but **sidecar** because of ~150 MB deps + heavy registry | **Yes** — Container App `ca-aigovern-openai-evals-dev`, ADR-001 pattern. HTTP+SSE same as Garak. |

The two `No` rows ship inside the dashboard deploy. The one `Yes` row mirrors ADR-001's Garak sidecar — same template, same `cae-aigovern-dev` Container Apps environment, scale-to-zero.

**Anthropic evals is NOT a backend.** It's a dataset source. Land it as: `eval/datasets/anthropic_model_written/` — a vendored snapshot of the JSONL persona/sycophancy/bias datasets, loaded by `agents/*/eval/run_eval.py` and the new vendor backends as a *test input set*. The runner cites `dataset_source: "anthropic/evals@<commit>"` in every run summary. Version-pinned so a future Anthropic update doesn't silently re-grade history.

### 4.4 UI extension

[team-portal/src/pages/evals/SystemEvalCard.tsx](../../team-portal/src/pages/evals/SystemEvalCard.tsx) gets:

1. **Suite picker** — multi-select chip group: `[DeepEval] [Ragas] [Promptfoo] [OpenAI evals]`. Default = whatever `EVAL_BACKEND` env says.
2. **Per-vendor result cards** — one card component per vendor, each owns its own metric layout:
   - `DeepEvalResultCard` — 5 progress bars (existing pattern)
   - `RagasResultCard` — 4 RAG-specific metric bars (faithfulness, answer_relevancy, context_precision, context_recall)
   - `PromptfooResultCard` — pass/fail assertion table
   - `OpenAIEvalsResultCard` — accuracy against golden set + per-sample breakdown
3. **Shared envelope** above each card: vendor name + version + cost estimate + duration + raw-JSON expander for auditors.

Mirrors the federated approach already proven in [agents/azure-architect/eval/run_eval.py](../../agents/azure-architect/eval/run_eval.py) (mixed metric types, each cited).

### 4.5 Engine endpoint

Extend `POST /grc/evals/v2/run/{ai_system_id}` to accept `{"suites": ["deepeval", "ragas", ...]}`. Engine spawns each backend via `asyncio.gather()` (memory: [[batch-llm-calls-always]] — they run in parallel). Each backend writes its raw result to `data/evals.jsonl` with `trace_id` join key (existing S56 #1 pattern, no new JSONL fallback needed). Per-suite cost estimate aggregated in the response envelope.

### 4.6 Policy gate

Each suite becomes an allowlisted action in [policies/base.rego](../../policies/base.rego):
```rego
allowed_eval_suites := {"deepeval", "ragas", "promptfoo", "openai_evals"}
deny[msg] { input.action == "eval.run"; not allowed_eval_suites[input.suite]; msg := sprintf("eval suite %q not allowed", [input.suite]) }
```

Per-tenant policy can restrict which suites are available (e.g. cost-gate `openai_evals` to CISO role only). Sha256 of the policy file visible in the F-018 RegoBundlesPanel (S57 close).

## 5. Consequences

### Positive
- One Protocol contract grows the platform to N vendors without engine changes — same pattern as scrubber/tracer (S5).
- Honest, auditable per-vendor results. Audit envelope cites vendor + version + dataset source + cost.
- Multi-vendor IS the value prop — pluralism shipped as a feature, not concealed.
- Anthropic dataset reuse is bounded (vendored snapshot at known commit; no live dependency on a 5-commit upstream repo).
- Cost transparency: per-run `cost_usd_est` enables `release-gate` style budget rules later.
- Adding vendor #6 (e.g. Patronus, Braintrust, Galileo) is bounded — one backend module + one card component, no engine change.

### Negative
- Frontend work: 3 new per-vendor result card components (~150 LOC each).
- OpenAI evals sidecar = new Azure resource (`ca-aigovern-openai-evals-dev`). Idle cost ~$0 (scale-to-zero), but new deploy pipeline + Dockerfile to maintain (~200 LOC + bicep file).
- Promptfoo subprocess requires Node 22 in the deploy image. Current Python image (`mcr.microsoft.com/azure-functions/python:4-python3.12` or App Service equivalent) does NOT include Node. Three options to resolve at implementation time: (a) custom image with apt-get install nodejs, (b) Promptfoo also moves to sidecar, (c) bundle a Node binary in the zip. Recommendation: (a) if deploy image swap is acceptable, otherwise (b).
- LLM-judge metrics (Ragas, OpenAI evals model-graded templates) burn LLM tokens. Per-run cost can spike under high concurrency. Cost-gate via policy required before the OpenAI evals sidecar goes live.
- DeepEval's "current 5 keys" contract becomes a legacy adapter — small ongoing maintenance tax until V2 cutover decommissions the legacy shape.

### Neutral / open
- **Anthropic datasets vendor commit pin** — TBD which subset to vendor (persona, sycophancy, bias, AI risk — picking all 4 is ~50 MB of JSONL; picking 1 is ~12 MB).
- **Dataset rotation policy** — when Anthropic publishes a new dataset version, do we re-grade history? Default: no, datasets are pinned per `ai_system` version (S07 binding semantics).
- **Cross-vendor RAG context handling** — Ragas requires `context` (retrieved chunks); DeepEval makes it optional. The unified Protocol passes `context: list[str]`; backends that don't use it ignore it. No issue.

## 6. Rejected for now (revisit triggers)

- **Anthropic evals as harness (literal request interpretation):** revisit only if Anthropic ships an actual eval harness in that repo (currently 5 commits; no signs of it). Re-classify if upstream activity changes.
- **Single-process OpenAI evals:** revisit if deploy-image budget grows past 4 GB and the slim-deploy invariant is intentionally lifted (same trigger as ADR-001 Option A).
- **Cross-vendor normalized "platform score":** revisit when buyers explicitly demand it AND we can defend the weighting methodology in an audit-class document.
- **Vendor #6+ (Patronus, Braintrust, Galileo):** revisit when a customer asks. Adding them is bounded under this ADR; no design change needed.

## 7. Implementation plan (NOT in this session)

Sequence after this ADR is accepted:

| # | Scope | Estimate | Blocks |
|---|---|---|---|
| 1 | Protocol + Config extension; legacy adapter for `deepeval` 5-key shape | 1 session | All downstream |
| 2 | `ragas_evaluator.py` backend + `RagasResultCard.tsx` (worked example) | 1 session | — |
| 3 | Suite picker + multi-suite engine endpoint + per-vendor card framework | 1 session | 4, 5, 6 |
| 4 | `promptfoo_evaluator.py` backend + Node-in-deploy resolution + `PromptfooResultCard.tsx` | 1 session | — |
| 5 | `openai_evals_evaluator.py` + sidecar (Dockerfile + bicep + HTTP+SSE bridge) + `OpenAIEvalsResultCard.tsx` | 2 sessions (sidecar + UI, mirroring ADR-001 split) | — |
| 6 | Anthropic datasets vendoring + dataset-source citation in run envelope | 0.5 session | — |
| 7 | Policy-gate suite allowlist + per-role cost-gate; .rego sha256 in F-018 panel | 0.5 session | — |
| 8 | OpenAPI regen + contract-tests update + integration test (multi-suite run end-to-end) | 0.5 session | Ship gate |

**Total: ~7 sessions.** Items 2-7 can interleave with other work; 1 and 8 are sequential bookends.

---

## Appendix — what we explicitly do NOT do

- We do **not** normalize metric vocabularies across vendors into a single "platform score" (Option A / C rejected). Federated per-vendor cards only.
- We do **not** treat `github.com/anthropics/evals` as a harness backend. It's a dataset source — vendored snapshot, cited per run.
- We do **not** put DeepEval or Ragas in a sidecar — their deps are light enough to stay in-process.
- We do **not** add vendor SDKs to `requirements.txt` blindly. Each backend's heavy import goes in `requirements-deploy.txt` only if its sidecar decision is "in-process" (mirrors ADR-001 §6 "Rejected" list and the Session 12 outage lesson).
- We do **not** ship an "aggregated faithfulness score" UI element. Each vendor's faithfulness lives in its own card, with its own definition cited.
- We do **not** allow user-supplied YAML eval registries to be uploaded through the UI (same posture as F-018 .rego: ships via git → CI, never via upload). Future ADR if customers demand BYO eval config.
