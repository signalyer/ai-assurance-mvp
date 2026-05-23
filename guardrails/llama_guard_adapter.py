"""Llama Guard 3 content safety evaluator for unsafe content detection."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from typing import Optional


@lru_cache(maxsize=512)
def _compiled_keyword(kw: str) -> re.Pattern[str]:
    r"""Compile a keyword to a word-boundary regex.

    Day-12 finding: previously this module used `kw in text_lower` substring
    matching, which caused massive false positives — "cut" matched
    "calculate", "execute", "discuss"; "harm" matched "harmless",
    "pharmaceutical"; "kill" matched "skill", "skillfully". Any LLM response
    about portfolio rebalancing got flagged as VIOLENCE+SELF_HARM, which
    crashed the demo end-to-end on 2026-05-23.

    Multi-word keywords (e.g. "kill myself") are matched literally with
    word boundaries on each end. Single-word keywords use \b\bword\b\b.
    """
    return re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE)


class UnsafeCategory(str, Enum):
    """Llama Guard 3 unsafe content categories."""
    VIOLENCE = "violence"
    HARASSMENT = "harassment"
    SELF_HARM = "self_harm"
    SEXUAL = "sexual"
    ILLEGAL = "illegal"
    HARMFUL_ACTIVITY = "harmful_activity"
    MISINFORMATION = "misinformation"
    SPAM = "spam"


@dataclass
class LlamaGuardResult:
    """Result of Llama Guard 3 content safety evaluation."""
    safe: bool
    violations: list[UnsafeCategory] = field(default_factory=list)
    categories: dict[UnsafeCategory, float] = field(default_factory=dict)  # category -> score
    score: float = 0.0                         # Overall safety score (0-1, 1 is safest)
    confidence: float = 0.9                    # Confidence in the verdict
    reason: str = ""


class LlamaGuardEvaluator:
    """Local content safety evaluator using Llama Guard 3 patterns.

    Session 03: Regex/heuristic-based safety detection (Session 05: integrate actual model).
    """

    # Keywords and patterns that trigger each category
    CATEGORY_PATTERNS = {
        UnsafeCategory.VIOLENCE: {
            "keywords": ["beat", "kill", "hurt", "injure", "punch", "stab", "shoot", "harm"],
            "severity": 0.9
        },
        UnsafeCategory.HARASSMENT: {
            "keywords": ["stupid", "idiot", "hate", "worthless", "deserve", "bullying", "insult"],
            "severity": 0.8
        },
        UnsafeCategory.SELF_HARM: {
            "keywords": ["suicide", "cut", "self-harm", "overdose", "kill myself", "self-injury"],
            "severity": 0.95
        },
        UnsafeCategory.SEXUAL: {
            "keywords": ["sex", "porn", "explicit", "nude", "sexual", "xxx"],
            "severity": 0.7
        },
        UnsafeCategory.ILLEGAL: {
            "keywords": ["steal", "robbery", "murder", "drug", "illegal", "crime", "laundering"],
            "severity": 0.85
        },
        UnsafeCategory.HARMFUL_ACTIVITY: {
            "keywords": ["hack", "malware", "exploit", "vulnerability", "ddos", "phishing"],
            "severity": 0.8
        },
        UnsafeCategory.MISINFORMATION: {
            "keywords": ["fake news", "conspiracy", "hoax", "false claim", "debunked"],
            "severity": 0.6
        },
        UnsafeCategory.SPAM: {
            "keywords": ["buy now", "click here", "limited offer", "free money", "act now"],
            "severity": 0.5
        },
    }

    @staticmethod
    def evaluate(text: str) -> LlamaGuardResult:
        """Evaluate content safety of text.

        Args:
            text: The text to evaluate

        Returns:
            LlamaGuardResult with safety verdict and category scores
        """
        if not text:
            return LlamaGuardResult(
                safe=True,
                violations=[],
                categories={},
                score=1.0,
                confidence=1.0,
                reason="Empty text",
            )

        text_lower = text.lower()
        violations = []
        category_scores = {}
        max_severity = 0.0

        # Check each category
        for category, pattern_info in LlamaGuardEvaluator.CATEGORY_PATTERNS.items():
            keywords = pattern_info["keywords"]
            severity = pattern_info["severity"]

            # Count keyword matches with word boundaries to avoid substring
            # false positives (e.g. "cut" matching "calculate"). See
            # _compiled_keyword() docstring for the bug this prevents.
            matches = sum(1 for kw in keywords if _compiled_keyword(kw).search(text_lower))
            if matches > 0:
                # Score: (matches / total_keywords) * severity
                score = min((matches / len(keywords)) * severity, 1.0)
                category_scores[category] = score

                # Violation if any keyword match (score > 0.0) — fail-closed
                if score > 0.0:
                    violations.append(category)
                    max_severity = max(max_severity, severity)

        # Safe if no violations
        safe = len(violations) == 0

        # Overall safety score: 1.0 - max_severity (1.0 = safe, 0.0 = unsafe)
        overall_score = 1.0 - max_severity if violations else 1.0

        return LlamaGuardResult(
            safe=safe,
            violations=violations,
            categories=category_scores,
            score=overall_score,
            confidence=0.85 if violations else 0.95,  # Higher confidence when no violations
            reason="Safe content" if safe else f"Unsafe categories detected: {', '.join(v.value for v in violations)}",
        )


def evaluate_content(
    text: str,
    unsafe_categories: Optional[list[UnsafeCategory]] = None,
) -> LlamaGuardResult:
    """Evaluate content safety.

    Args:
        text: The content to evaluate
        unsafe_categories: Unused in Session 03 (for future custom category weighting)

    Returns:
        LlamaGuardResult with safety evaluation
    """
    return LlamaGuardEvaluator.evaluate(text)
