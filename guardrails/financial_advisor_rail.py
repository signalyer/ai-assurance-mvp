"""Topic and policy rail for financial advisor workload.

Enforces:
- Allowed topics: market analysis, investment strategy, risk assessment, education, compliance
- Forbidden topics: stock tips, guaranteed returns
- Post-response checks: blocks claims of guaranteed returns
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from guardrails.nemo_adapters import TopicClassifier


@dataclass
class FinancialAdvisorRailResult:
    """Result of financial advisor rail enforcement."""
    passed: bool
    violations: list[str]
    metadata: dict


class FinancialAdvisorRail:
    """Topic rail specifically for financial advisor workload."""

    # Strict forbidden phrases (any presence = violation)
    FORBIDDEN_PHRASES = [
        "guaranteed return",
        "guaranteed profit",
        "risk-free",
        "will never lose",
        "certain to gain",
        "absolutely safe",
        "no risk",
        "sure bet",
        "can't lose",
    ]

    @staticmethod
    def validate_input(prompt: str) -> FinancialAdvisorRailResult:
        """Validate input prompt against financial advisor rail.

        Args:
            prompt: The user prompt

        Returns:
            FinancialAdvisorRailResult
        """
        violations = []

        # Check forbidden phrases (strict check)
        prompt_lower = prompt.lower()
        for phrase in FinancialAdvisorRail.FORBIDDEN_PHRASES:
            if phrase in prompt_lower:
                violations.append(f"Forbidden phrase detected: '{phrase}'")

        # Check topic (allowed topics only)
        detected_topic, confidence = TopicClassifier.classify(prompt)

        allowed_topics = [
            "market_analysis",
            "investment_strategy",
            "risk_assessment",
            "financial_education",
            "compliance",
        ]

        if detected_topic and detected_topic not in allowed_topics:
            violations.append(f"Off-topic for financial advisor: '{detected_topic}'")

        return FinancialAdvisorRailResult(
            passed=len(violations) == 0,
            violations=violations,
            metadata={
                "detected_topic": detected_topic,
                "topic_confidence": confidence,
            }
        )

    @staticmethod
    def validate_output(response: str) -> FinancialAdvisorRailResult:
        """Validate output response against financial advisor rail.

        Args:
            response: The LLM response

        Returns:
            FinancialAdvisorRailResult
        """
        violations = []

        # Check forbidden phrases in response (strict)
        response_lower = response.lower()
        for phrase in FinancialAdvisorRail.FORBIDDEN_PHRASES:
            if phrase in response_lower:
                violations.append(f"Response contains forbidden phrase: '{phrase}'")

        # Additional check: "I recommend" + "buy" without caveats
        if "i recommend" in response_lower and "buy" in response_lower:
            # Check if proper disclaimers are present
            disclaimers = [
                "consult",
                "advisor",
                "not financial advice",
                "for educational",
                "do your own research",
                "past performance",
            ]
            has_disclaimer = any(d in response_lower for d in disclaimers)
            if not has_disclaimer:
                violations.append("Stock recommendation without proper disclaimers")

        return FinancialAdvisorRailResult(
            passed=len(violations) == 0,
            violations=violations,
            metadata={
                "has_recommendation": "i recommend" in response_lower,
                "response_length": len(response),
            }
        )
