"""NeMo Guardrails topic enforcement and topic classification."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class TopicValidationResult:
    """Result of topic validation against allowed topics."""
    is_valid: bool
    detected_topic: Optional[str]
    allowed_topics: list[str]
    confidence: float                          # 0.0-1.0
    reason: str


class TopicClassifier:
    """Keyword-based topic classifier for financial advisor workload.

    Session 03: regex/keyword-based fallback.
    Session 05+: NeMo client integration for remote classification.
    """

    # Financial advisor topic definitions
    TOPICS = {
        "market_analysis": {
            "keywords": ["market", "index", "trend", "analysis", "movement", "performance"],
            "description": "Market trends and index analysis"
        },
        "investment_strategy": {
            "keywords": ["strategy", "portfolio", "allocation", "diversification", "rebalance"],
            "description": "Investment strategy and portfolio management"
        },
        "risk_assessment": {
            "keywords": ["risk", "volatility", "downside", "exposure", "hedging"],
            "description": "Risk assessment and management"
        },
        "financial_education": {
            "keywords": ["learn", "understand", "explain", "basics", "fundamentals"],
            "description": "Financial education and learning"
        },
        "compliance": {
            "keywords": ["compliance", "regulation", "sec", "finra", "aml", "kyc"],
            "description": "Compliance and regulatory topics"
        },
        "stock_tips": {
            "keywords": ["stock", "pick", "recommendation", "buy", "sell", "tip", "shortlist"],
            "description": "Stock tips and picks (FORBIDDEN)"
        },
        "guaranteed_returns": {
            "keywords": ["guaranteed", "promise", "certain", "assured", "will", "must return"],
            "description": "Guaranteed return claims (FORBIDDEN)"
        },
    }

    ALLOWED_TOPICS_DEFAULT = [
        "market_analysis",
        "investment_strategy",
        "risk_assessment",
        "financial_education",
        "compliance",
    ]

    FORBIDDEN_TOPICS = [
        "stock_tips",
        "guaranteed_returns",
    ]

    @staticmethod
    def classify(text: str) -> tuple[Optional[str], float]:
        """Classify text into a topic.

        Uses keyword matching. Confidence based on keyword density.

        Args:
            text: The text to classify

        Returns:
            Tuple of (topic_name, confidence) or (None, 0.0) if no match
        """
        if not text:
            return None, 0.0

        text_lower = text.lower()
        scores = {}

        # Score each topic by keyword matches
        for topic_name, topic_info in TopicClassifier.TOPICS.items():
            keywords = topic_info["keywords"]
            matches = sum(1 for kw in keywords if kw in text_lower)
            if matches > 0:
                confidence = min(matches / len(keywords), 1.0)  # Normalized
                scores[topic_name] = confidence

        if not scores:
            return None, 0.0

        # Return highest-scoring topic
        best_topic = max(scores, key=scores.get)
        return best_topic, scores[best_topic]

    @staticmethod
    def is_topic_allowed(topic: Optional[str], allowed_topics: list[str]) -> bool:
        """Check if topic is in allowed list.

        Args:
            topic: The detected topic
            allowed_topics: List of allowed topics

        Returns:
            True if topic is allowed
        """
        if topic is None:
            return True  # No topic detected = allowed (unclassified input)
        return topic in allowed_topics

    @staticmethod
    def is_topic_forbidden(topic: Optional[str]) -> bool:
        """Check if topic is explicitly forbidden.

        Args:
            topic: The detected topic

        Returns:
            True if topic is forbidden
        """
        if topic is None:
            return False
        return topic in TopicClassifier.FORBIDDEN_TOPICS


def validate_topic(
    text: str,
    workload_id: str,
    allowed_topics: Optional[list[str]] = None,
) -> TopicValidationResult:
    """Validate that text stays within allowed topics.

    Args:
        text: The prompt text to validate
        workload_id: Workload context (e.g., "financial_advisor")
        allowed_topics: List of allowed topics; defaults based on workload_id

    Returns:
        TopicValidationResult with validation status and confidence
    """
    if allowed_topics is None:
        allowed_topics = TopicClassifier.ALLOWED_TOPICS_DEFAULT

    # Classify the text
    detected_topic, confidence = TopicClassifier.classify(text)

    # Check if forbidden
    if TopicClassifier.is_topic_forbidden(detected_topic):
        return TopicValidationResult(
            is_valid=False,
            detected_topic=detected_topic,
            allowed_topics=allowed_topics,
            confidence=confidence,
            reason=f"Topic '{detected_topic}' is explicitly forbidden for {workload_id}",
        )

    # Check if allowed
    if detected_topic and not TopicClassifier.is_topic_allowed(detected_topic, allowed_topics):
        return TopicValidationResult(
            is_valid=False,
            detected_topic=detected_topic,
            allowed_topics=allowed_topics,
            confidence=confidence,
            reason=f"Topic '{detected_topic}' not in allowed list for {workload_id}: {allowed_topics}",
        )

    # Borderline confidence: REVIEW (is_valid=None or confidence check)
    if detected_topic and confidence < 0.5:
        return TopicValidationResult(
            is_valid=None,  # type: ignore
            detected_topic=detected_topic,
            allowed_topics=allowed_topics,
            confidence=confidence,
            reason=f"Borderline confidence ({confidence:.2f}) for topic '{detected_topic}'",
        )

    # Valid topic
    return TopicValidationResult(
        is_valid=True,
        detected_topic=detected_topic or "unclassified",
        allowed_topics=allowed_topics,
        confidence=confidence,
        reason=f"Topic '{detected_topic or 'unclassified'}' is allowed",
    )
