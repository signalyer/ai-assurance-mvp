"""DeepEval suite — five metrics, one public function."""

import os
import re
from typing import Optional
from dotenv import load_dotenv
from deepeval.metrics import (
    HallucinationMetric,
    AnswerRelevancyMetric,
    ToxicityMetric,
    FaithfulnessMetric,
    PIILeakageMetric,
)
from deepeval.test_case import LLMTestCase

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


def evaluate_response(
    input_prompt: str,
    actual_output: str,
    expected_output: str = "",
    context: list[str] = None,
) -> dict:
    """
    Run all five metrics against a model response.

    Args:
        input_prompt: User input/question
        actual_output: Model response to evaluate
        expected_output: Expected/ideal response (optional)
        context: List of context strings (optional, required for hallucination/faithfulness)

    Returns:
        Dict with metric_name -> {score, passed, details}
    """
    if context is None:
        context = []

    model = _get_eval_model()
    results = {}

    # Build test case
    test_case = LLMTestCase(
        input=input_prompt,
        actual_output=actual_output,
        expected_output=expected_output or actual_output,
        retrieval_context=context,
    )

    # 1. Answer Relevancy
    try:
        metric = AnswerRelevancyMetric(model=model, threshold=0.5, async_mode=False)
        metric.measure(test_case)
        results["answer_relevancy"] = {
            "score": metric.score,
            "passed": metric.is_successful(),
            "details": metric.reason or "Evaluated",
        }
    except Exception as e:
        results["answer_relevancy"] = {
            "score": 0.0,
            "passed": False,
            "details": f"Error: {str(e)[:100]}",
        }

    # 2. Toxicity (no context needed)
    try:
        metric = ToxicityMetric(model=model, threshold=0.5, async_mode=False)
        metric.measure(test_case)
        results["toxicity"] = {
            "score": metric.score,
            "passed": metric.is_successful(),
            "details": metric.reason or "Evaluated",
        }
    except Exception as e:
        results["toxicity"] = {
            "score": 0.0,
            "passed": False,
            "details": f"Error: {str(e)[:100]}",
        }

    # 3. Hallucination (requires context)
    if context:
        try:
            metric = HallucinationMetric(model=model, threshold=0.5, async_mode=False)
            metric.measure(test_case)
            results["hallucination"] = {
                "score": metric.score,
                "passed": metric.is_successful(),
                "details": metric.reason or "Evaluated",
            }
        except Exception as e:
            results["hallucination"] = {
                "score": None,
                "passed": False,
                "details": f"Error: {str(e)[:100]}",
            }
    else:
        results["hallucination"] = {
            "score": None,
            "passed": None,
            "details": "Skipped (no context provided)",
        }

    # 4. Faithfulness (requires context)
    if context:
        try:
            metric = FaithfulnessMetric(model=model, threshold=0.5, async_mode=False)
            metric.measure(test_case)
            results["faithfulness"] = {
                "score": metric.score,
                "passed": metric.is_successful(),
                "details": metric.reason or "Evaluated",
            }
        except Exception as e:
            results["faithfulness"] = {
                "score": None,
                "passed": False,
                "details": f"Error: {str(e)[:100]}",
            }
    else:
        results["faithfulness"] = {
            "score": None,
            "passed": None,
            "details": "Skipped (no context provided)",
        }

    # 5. PII Leakage (built-in metric)
    try:
        metric = PIILeakageMetric(model=model, async_mode=False)
        metric.measure(test_case)
        results["pii_leakage"] = {
            "score": metric.score,
            "passed": metric.is_successful(),
            "details": metric.reason or "Evaluated",
        }
    except Exception as e:
        # Fallback to regex-based check
        has_pii, pii_details = _check_pii(actual_output)
        results["pii_leakage"] = {
            "score": 1.0 if not has_pii else 0.0,
            "passed": not has_pii,
            "details": pii_details,
        }

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
