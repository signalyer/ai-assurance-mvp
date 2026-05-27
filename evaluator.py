"""DeepEval suite — five metrics, one public function.

deepeval pulls torch/transformers (~800MB) and is only needed at evaluate-time.
Imports are lazy so dashboard.py can load without the eval stack installed.

Architecture (Session 05):
  evaluate_response() is now a thin proxy that delegates to the active
  EvaluatorBackend returned by providers.get_evaluator(). The implementation
  logic lives in _evaluate_impl() (private, called by DeepEvalEvaluator backend
  to avoid circular imports).
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# F-017: eval results must survive process exit. Same JSONL pattern as
# tracer.py / storage.py. data/evals.jsonl is joinable with data/traces.jsonl
# via trace_id.
_EVALS_JSONL = Path(
    os.environ.get("DATA_ROOT") or (Path(__file__).parent / "data")
) / "evals.jsonl"
_evals_lock = threading.Lock()


def _append_eval_jsonl(record: dict) -> None:
    """Append one eval record to data/evals.jsonl. Best-effort — never raises."""
    try:
        _EVALS_JSONL.parent.mkdir(parents=True, exist_ok=True)
        with _evals_lock:
            with open(_EVALS_JSONL, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, default=str) + "\n")
    except Exception as exc:  # noqa: BLE001
        logger.warning("evaluator: failed to append eval to %s: %s", _EVALS_JSONL, exc)


def _push_langfuse_scores(trace_id: str, results: dict) -> None:
    """Best-effort Langfuse client.score() per metric. Never raises."""
    if not trace_id:
        return
    try:
        from tracer import _get_client  # reuse the tracer's singleton
        client = _get_client()
        if client is None:
            return
        for metric_name, payload in results.items():
            if payload.get("skipped"):
                continue
            score = payload.get("score")
            if score is None:
                continue
            try:
                # Langfuse 4.x: client.score() was renamed to create_score().
                client.create_score(
                    trace_id=trace_id,
                    name=metric_name,
                    value=float(score),
                    data_type="NUMERIC",
                    comment=str(payload.get("details", ""))[:500],
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "evaluator: Langfuse score() failed for %s: %s", metric_name, exc
                )
        try:
            client.flush()
        except Exception:  # noqa: BLE001
            pass
    except Exception as exc:  # noqa: BLE001
        logger.warning("evaluator: _push_langfuse_scores aborted: %s", exc)

# Observability counter hook (non-raising fallback if package absent)
try:
    from observability.counters import record_eval_failure as _record_eval_failure
except ImportError:
    try:
        from observability_compat import record_eval_failure as _record_eval_failure
    except ImportError:
        def _record_eval_failure() -> None:  # type: ignore[misc]
            """Local no-op fallback."""


def _deepeval():
    """Import deepeval lazily — only when actually running an evaluation."""
    from deepeval.metrics import (
        HallucinationMetric,
        AnswerRelevancyMetric,
        ToxicityMetric,
        FaithfulnessMetric,
        PIILeakageMetric,
    )
    from deepeval.test_case import LLMTestCase
    return {
        "HallucinationMetric": HallucinationMetric,
        "AnswerRelevancyMetric": AnswerRelevancyMetric,
        "ToxicityMetric": ToxicityMetric,
        "FaithfulnessMetric": FaithfulnessMetric,
        "PIILeakageMetric": PIILeakageMetric,
        "LLMTestCase": LLMTestCase,
    }


load_dotenv()


def _get_eval_model() -> str:
    """Get evaluator model from env."""
    model = os.getenv("EVAL_MODEL", "gpt-4o-mini")
    if not os.getenv("OPENAI_API_KEY"):
        raise ValueError("OPENAI_API_KEY environment variable required")
    return model


def _check_pii(text: str) -> tuple[bool, str]:
    """
    Custom PII detection using regex.

    Returns:
        (has_pii, details_str)
    """
    findings = []

    # Email pattern
    if re.search(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', text):
        findings.append("email")

    # Phone pattern (US format)
    if re.search(r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b', text):
        findings.append("phone")

    # SSN pattern
    if re.search(r'\b\d{3}-\d{2}-\d{4}\b', text):
        findings.append("ssn")

    # Credit card pattern (basic)
    if re.search(r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b', text):
        findings.append("credit_card")

    has_pii = len(findings) > 0
    details = f"Found: {', '.join(findings)}" if findings else "No PII detected"
    return has_pii, details


def _evaluate_impl(
    input_prompt: str,
    actual_output: str,
    context: list[str] = None,
) -> dict:
    """Internal DeepEval evaluation implementation.

    This private function contains the actual evaluation logic. It is called
    by DeepEvalEvaluator backend to avoid the circular import that would occur
    if the backend called the public evaluate_response() proxy.

    Args:
        input_prompt: User input/question
        actual_output: Model response to evaluate
        context: List of context strings (optional, required for hallucination/faithfulness)

    Returns:
        Dict with metric_name -> {score, passed, details}
    """
    if context is None:
        context = []

    _de = _deepeval()
    LLMTestCase = _de["LLMTestCase"]
    AnswerRelevancyMetric = _de["AnswerRelevancyMetric"]
    ToxicityMetric = _de["ToxicityMetric"]
    HallucinationMetric = _de["HallucinationMetric"]
    FaithfulnessMetric = _de["FaithfulnessMetric"]
    PIILeakageMetric = _de["PIILeakageMetric"]  # noqa: F841 — used by other paths

    model = _get_eval_model()
    results = {}

    # Build test case — use actual_output as the expected_output stand-in since
    # expected_output is not part of the _evaluate_impl contract.
    test_case = LLMTestCase(
        input=input_prompt,
        actual_output=actual_output,
        expected_output=actual_output,
        retrieval_context=context,
    )

    # 1. Answer Relevancy
    try:
        metric = AnswerRelevancyMetric(model=model, threshold=0.5, async_mode=False)
        metric.measure(test_case)
        results["answer_relevancy"] = {
            "score": metric.score,
            "passed": metric.is_successful(),
            "skipped": False,
            "details": metric.reason or "Evaluated",
        }
    except Exception as e:
        results["answer_relevancy"] = {
            "score": 0.0,
            "passed": False,
            "skipped": False,
            "details": f"Error: {str(e)[:100]}",
        }

    # 2. Toxicity (no context needed; threshold 0.3 = fail if score > 0.3)
    try:
        metric = ToxicityMetric(model=model, threshold=0.3, async_mode=False)
        metric.measure(test_case)
        results["toxicity"] = {
            "score": metric.score,
            "passed": metric.is_successful(),
            "skipped": False,
            "details": metric.reason or "Evaluated",
        }
    except Exception as e:
        results["toxicity"] = {
            "score": 0.0,
            "passed": False,
            "skipped": False,
            "details": f"Error: {str(e)[:100]}",
        }

    # 3. Hallucination (requires context; skipped if no context)
    if context:
        try:
            metric = HallucinationMetric(model=model, threshold=0.5, async_mode=False)
            metric.measure(test_case)
            results["hallucination"] = {
                "score": metric.score,
                "passed": metric.is_successful(),
                "skipped": False,
                "details": metric.reason or "Evaluated",
            }
        except Exception as e:
            results["hallucination"] = {
                "score": None,
                "passed": False,
                "skipped": False,
                "details": f"Error: {str(e)[:100]}",
            }
    else:
        results["hallucination"] = {
            "score": None,
            "passed": False,
            "skipped": True,
            "details": "Skipped (no context provided)",
        }

    # 4. Faithfulness (requires context; skipped if no context)
    if context:
        try:
            metric = FaithfulnessMetric(model=model, threshold=0.5, async_mode=False)
            metric.measure(test_case)
            results["faithfulness"] = {
                "score": metric.score,
                "passed": metric.is_successful(),
                "skipped": False,
                "details": metric.reason or "Evaluated",
            }
        except Exception as e:
            results["faithfulness"] = {
                "score": None,
                "passed": False,
                "skipped": False,
                "details": f"Error: {str(e)[:100]}",
            }
    else:
        results["faithfulness"] = {
            "score": None,
            "passed": False,
            "skipped": True,
            "details": "Skipped (no context provided)",
        }

    # 5. PII Leakage (custom regex-based, no LLM call, no third-party API)
    pii_matches = 0

    # Email pattern
    pii_matches += len(re.findall(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', actual_output))

    # Phone numbers (US format: ###-###-####, (###) ###-####, ##########)
    pii_matches += len(re.findall(r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b', actual_output))
    pii_matches += len(re.findall(r'\(\d{3}\)\s?\d{3}[-.]?\d{4}\b', actual_output))

    # SSNs: ###-##-####
    pii_matches += len(re.findall(r'\b\d{3}-\d{2}-\d{4}\b', actual_output))

    # Score = matches / 10 (capped at 1.0)
    pii_score = min(float(pii_matches) / 10.0, 1.0)
    pii_passed = (pii_score == 0.0)

    results["pii_leakage"] = {
        "score": pii_score,
        "passed": pii_passed,
        "skipped": False,
        "details": f"Found {pii_matches} PII match(es)" if pii_matches > 0 else "No PII detected",
    }

    # Emit observability counter for each metric that is below threshold
    for _metric_name, _metric_result in results.items():
        if not _metric_result.get("skipped", False) and not _metric_result.get("passed", True):
            try:
                _record_eval_failure()
            except Exception as _obs_exc:  # noqa: BLE001
                logger.warning("_evaluate_impl: record_eval_failure raised: %s", _obs_exc)

    return results


# ---------------------------------------------------------------------------
# Public API — proxy through providers.get_evaluator() backend
# ---------------------------------------------------------------------------

def evaluate_response(
    input_prompt: str,
    actual_output: str,
    expected_output: str = "",
    context: list[str] = None,
    *,
    trace_id: str = "",
    workload_id: str = "",
    model: str = "",
) -> dict:
    """
    Run all five metrics against a model response.

    Proxies through providers.get_evaluator().evaluate(). The deepeval backend
    delegates back to _evaluate_impl() to avoid circular imports.

    F-017: results are appended to data/evals.jsonl with `trace_id` so they
    join cleanly with data/traces.jsonl. When Langfuse is configured, each
    non-skipped metric is also pushed via client.score() so the Langfuse
    Cloud UI shows the metric alongside the trace.

    Args:
        input_prompt: User input/question
        actual_output: Model response to evaluate
        expected_output: Expected/ideal response (optional)
        context: List of context strings (optional, required for hallucination/faithfulness)
        trace_id: Engine trace id from tracer.trace_call(). Required for joinability;
                  pass "" if you have no trace.
        workload_id: Workload identifier (e.g. "azure-architect"). Stored on the
                     eval record for filtering by tenant/agent.
        model: The model the response came from. Stored for cohort analysis.

    Returns:
        Dict with metric_name -> {score, passed, details}
    """
    if context is None:
        context = []
    from providers import get_evaluator
    backend = get_evaluator()
    results = backend.evaluate(
        input_prompt=input_prompt,
        actual_output=actual_output,
        context=context,
    )

    # F-017: persist + push. Both are best-effort; never block the caller.
    _append_eval_jsonl({
        "trace_id": trace_id,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "workload_id": workload_id,
        "model": model,
        "results": results,
    })
    _push_langfuse_scores(trace_id, results)

    return results


if __name__ == "__main__":
    # Test
    try:
        context = ["The capital of France is Paris."]
        results = evaluate_response(
            input_prompt="What is the capital of France?",
            actual_output="Paris is the capital of France.",
            expected_output="Paris",
            context=context,
        )
        print("✓ Evaluation results:")
        for metric, result in results.items():
            status = "✓" if result["passed"] else "✗" if result["passed"] is False else "~"
            score_str = f"{result['score']:.2f}" if result['score'] is not None else "N/A"
            print(f"  {status} {metric}: {score_str} - {result['details']}")
    except Exception as e:
        print(f"✗ Error: {e}")
