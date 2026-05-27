"""DeepEval evaluator backend — calls evaluator._evaluate_impl.

CIRCULAR IMPORT PREVENTION:
  evaluator.evaluate_response() is a proxy:
    evaluate_response(...) -> get_evaluator().evaluate(...) -> DeepEvalEvaluator.evaluate(...)

  Calling evaluator.evaluate_response() from this method creates INFINITE RECURSION.
  Fix: call evaluator._evaluate_impl() (private function with the actual logic).

DeepEval pulls torch and transformers (~800MB) so it is imported lazily.
The module-level import in evaluator.py is also lazy — this backend
inherits that behaviour automatically by delegating rather than importing
at class definition time.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _read_deepeval_version() -> str:
    """Best-effort version probe — never raises; returns 'unknown' on failure."""
    try:
        from importlib.metadata import version  # stdlib
        return version("deepeval")
    except Exception:  # noqa: BLE001
        return "unknown"


_DEEPEVAL_METRIC_SCHEMA: dict = {
    "answer_relevancy": {"type": "score", "range": [0.0, 1.0], "direction": "higher_is_better"},
    "toxicity": {"type": "score", "range": [0.0, 1.0], "direction": "lower_is_better"},
    "hallucination": {"type": "score", "range": [0.0, 1.0], "direction": "lower_is_better"},
    "faithfulness": {"type": "score", "range": [0.0, 1.0], "direction": "higher_is_better"},
    "pii_leakage": {"type": "score", "range": [0.0, 1.0], "direction": "lower_is_better"},
}


class DeepEvalEvaluator:
    """EvaluatorBackend that delegates to evaluator._evaluate_impl."""

    # ADR-003 Protocol attrs — read once at class definition.
    vendor: str = "deepeval"
    vendor_version: str = _read_deepeval_version()
    metric_schema: dict = _DEEPEVAL_METRIC_SCHEMA

    def evaluate(
        self,
        input_prompt: str,
        actual_output: str,
        context: list[str],
    ) -> dict:
        """Run the 5-metric DeepEval suite against *actual_output*.

        Calls evaluator._evaluate_impl() (private) to avoid the infinite recursion
        that would result from calling the public evaluate_response() proxy:
          evaluate_response -> get_evaluator().evaluate -> here -> evaluate_response -> ...

        Metrics that require context (hallucination, faithfulness) are skipped
        when *context* is empty.

        Note: OPENAI_API_KEY must be set in the environment; the function will
        raise ValueError if the key is absent (inherited from evaluator.py).

        Args:
            input_prompt:  The user-facing query that produced the response.
            actual_output: The model response to evaluate.
            context:       Grounding context strings for hallucination / faithfulness.
                           Pass an empty list when no context is available.

        Returns:
            Dict mapping metric_name -> {score, passed, skipped, details}.
            Keys always present: answer_relevancy, toxicity, hallucination,
            faithfulness, pii_leakage.
        """
        logger.debug(
            "DeepEvalEvaluator.evaluate: entry prompt_length=%d output_length=%d context_items=%d",
            len(input_prompt), len(actual_output), len(context),
        )
        # Call _evaluate_impl (private) NOT evaluate_response (public proxy) — avoids recursion.
        from evaluator import _evaluate_impl

        results = _evaluate_impl(
            input_prompt=input_prompt,
            actual_output=actual_output,
            context=context,
        )
        logger.debug(
            "DeepEvalEvaluator.evaluate: exit metrics=%d",
            len(results),
        )
        return results
