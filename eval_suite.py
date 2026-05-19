"""DeepEval suite with five core metrics for AI assurance."""

import os
from typing import Optional
from deepeval.metrics import (
    Relevance,
    Coherence,
    Faithfulness,
    CorrectKnowledge,
    Toxicity,
)
from deepeval.test_case import LLMTestCase


def _load_eval_model() -> str:
    """Load evaluator model from environment variables."""
    from dotenv import load_dotenv
    load_dotenv()

    model = os.getenv("EVAL_MODEL", "gpt-4o-mini")
    if not os.getenv("OPENAI_API_KEY"):
        raise ValueError("OPENAI_API_KEY environment variable is required for evaluators")

    return model


class EvaluationSuite:
    """Container for five core evaluation metrics."""

    def __init__(self, model: Optional[str] = None) -> None:
        """
        Initialize evaluation suite with five metrics.

        Args:
            model: OpenAI model to use for evaluation. Defaults to gpt-4o-mini.
        """
        self.model = model or _load_eval_model()

        # Metric 1: Relevance - does output address the input?
        self.relevance = Relevance(model=self.model, threshold=0.5)

        # Metric 2: Coherence - is output well-structured and logical?
        self.coherence = Coherence(model=self.model, threshold=0.5)

        # Metric 3: Faithfulness - is output faithful to context?
        self.faithfulness = Faithfulness(model=self.model, threshold=0.5)

        # Metric 4: Correctness - is output factually correct?
        self.correctness = CorrectKnowledge(model=self.model, threshold=0.5)

        # Metric 5: Toxicity - does output contain harmful content?
        self.toxicity = Toxicity(threshold=0.5)

    def evaluate_output(
        self,
        input_text: str,
        actual_output: str,
        retrieval_context: Optional[list[str]] = None,
        expected_output: Optional[str] = None,
    ) -> dict[str, dict[str, float | bool | str]]:
        """
        Run all five metrics against a single output.

        Args:
            input_text: The input prompt or question
            actual_output: The LLM output to evaluate
            retrieval_context: Optional list of context chunks for faithfulness
            expected_output: Optional expected answer for correctness

        Returns:
            Dict with metric results: {metric_name: {score: float, passed: bool, reason: str}}
        """
        # Build test case
        test_case = LLMTestCase(
            input=input_text,
            actual_output=actual_output,
            retrieval_context=retrieval_context or [],
            expected_output=expected_output or "",
        )

        results = {}

        # 1. Relevance: Does output address the question?
        try:
            self.relevance.measure(test_case)
            results["relevance"] = {
                "score": self.relevance.score,
                "passed": self.relevance.is_successful(),
                "reason": self.relevance.reason,
            }
        except Exception as e:
            results["relevance"] = {
                "score": 0.0,
                "passed": False,
                "reason": f"Error: {str(e)}",
            }

        # 2. Coherence: Is output well-structured and logical?
        try:
            self.coherence.measure(test_case)
            results["coherence"] = {
                "score": self.coherence.score,
                "passed": self.coherence.is_successful(),
                "reason": self.coherence.reason,
            }
        except Exception as e:
            results["coherence"] = {
                "score": 0.0,
                "passed": False,
                "reason": f"Error: {str(e)}",
            }

        # 3. Faithfulness: Is output faithful to retrieval context?
        try:
            self.faithfulness.measure(test_case)
            results["faithfulness"] = {
                "score": self.faithfulness.score,
                "passed": self.faithfulness.is_successful(),
                "reason": self.faithfulness.reason,
            }
        except Exception as e:
            results["faithfulness"] = {
                "score": 0.0,
                "passed": False,
                "reason": f"Error: {str(e)}",
            }

        # 4. Correctness: Is output factually correct?
        try:
            self.correctness.measure(test_case)
            results["correctness"] = {
                "score": self.correctness.score,
                "passed": self.correctness.is_successful(),
                "reason": self.correctness.reason,
            }
        except Exception as e:
            results["correctness"] = {
                "score": 0.0,
                "passed": False,
                "reason": f"Error: {str(e)}",
            }

        # 5. Toxicity: Does output contain harmful content?
        try:
            self.toxicity.measure(test_case)
            results["toxicity"] = {
                "score": self.toxicity.score,
                "passed": self.toxicity.is_successful(),
                "reason": self.toxicity.reason,
            }
        except Exception as e:
            results["toxicity"] = {
                "score": 0.0,
                "passed": False,
                "reason": f"Error: {str(e)}",
            }

        return results

    def summarize_results(self, results: dict[str, dict[str, float | bool | str]]) -> dict[str, float | int]:
        """
        Summarize evaluation results across all metrics.

        Args:
            results: Results dict from evaluate_output

        Returns:
            Dict with aggregated metrics: {passed_count, total_count, avg_score, all_passed}
        """
        scores = [r["score"] for r in results.values() if isinstance(r["score"], (int, float))]
        passed_count = sum(1 for r in results.values() if r.get("passed"))

        return {
            "passed_count": passed_count,
            "total_count": len(results),
            "avg_score": sum(scores) / len(scores) if scores else 0.0,
            "all_passed": passed_count == len(results),
        }


if __name__ == "__main__":
    # Standalone test
    suite = EvaluationSuite()
    print("✓ Evaluation suite initialized with 5 metrics")

    # Test case 1: Good response
    input_text = "What is the capital of France?"
    output_text = "The capital of France is Paris, a major city located in north-central France on the Seine River."
    context = ["France is a country in Western Europe. The capital is Paris."]

    results = suite.evaluate_output(
        input_text=input_text,
        actual_output=output_text,
        retrieval_context=context,
        expected_output="Paris",
    )

    print("\nEvaluation Results:")
    for metric, result in results.items():
        status = "✓" if result["passed"] else "✗"
        print(f"  {status} {metric}: {result['score']:.2f} - {result['reason']}")

    summary = suite.summarize_results(results)
    print(f"\nSummary: {summary['passed_count']}/{summary['total_count']} metrics passed")
    print(f"Average score: {summary['avg_score']:.2f}")
