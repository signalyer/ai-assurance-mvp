"""Prompt injection detection via regex heuristics and optional LLM-based analysis."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from datetime import datetime
from enum import Enum
from typing import Optional

from storage import _append_jsonl


class InjectionAttackType(str, Enum):
    """Injection attack classification."""
    JAILBREAK = "jailbreak"                    # ignore/override instructions
    PROMPT_OVERRIDE = "prompt_override"        # e.g., "answer as if you are..."
    CONTEXT_ESCAPE = "context_escape"          # break out of context window
    PREAMBLE_INJECTION = "preamble_injection"  # inject into system prompt
    UNKNOWN = "unknown"


@dataclass
class InjectionResult:
    """Result of injection detection."""
    is_injection: bool
    confidence: float                          # 0.0-1.0
    attack_type: InjectionAttackType
    reason: str
    metadata: dict


class InjectionDetector:
    """Detects prompt injection attempts via regex patterns and heuristics."""

    # Jailbreak patterns: "ignore previous", "system:", "{{{", etc.
    JAILBREAK_PATTERNS = [
        r"ignore\s+(?:previous|prior|all|the)\s+(?:instructions|prompt|commands)",
        r"forget\s+(?:everything|all|the)\s+(?:above|previous)",
        r"disregard\s+(?:instructions|rules)",
        r"pretend\s+(?:the|you)\s+(?:previous|above)",
    ]

    # System prompt injection: "system:", "[SYSTEM]", etc.
    SYSTEM_PREFIX_PATTERNS = [
        r"^\s*(?:system|admin|secret)\s*:",
        r"\[(?:SYSTEM|ADMIN|SECRET)\]",
        r"<!--\s*system",
    ]

    # Context escape: triple braces, quote escaping
    CONTEXT_ESCAPE_PATTERNS = [
        r"\{\{\{",                              # triple brace
        r'""".*"""',                            # triple quote with content
        r"\\x[0-9a-f]{2}",                      # escaped bytes
    ]

    # Preamble injection: "pretend I said", "as if you are"
    PREAMBLE_PATTERNS = [
        r"(?:pretend|imagine|assume|act as|roleplay)\s+(?:I\s+(?:said|am)|you\s+(?:are|were))",
        r"respond\s+as\s+(?:if|though)",
        r"in\s+the\s+role\s+of",
    ]

    def __init__(self):
        """Initialize compiled regex patterns."""
        self.jailbreak_re = re.compile(
            "|".join(self.JAILBREAK_PATTERNS),
            re.IGNORECASE | re.MULTILINE
        )
        self.system_prefix_re = re.compile(
            "|".join(self.SYSTEM_PREFIX_PATTERNS),
            re.IGNORECASE | re.MULTILINE
        )
        self.context_escape_re = re.compile(
            "|".join(self.CONTEXT_ESCAPE_PATTERNS),
            re.IGNORECASE
        )
        self.preamble_re = re.compile(
            "|".join(self.PREAMBLE_PATTERNS),
            re.IGNORECASE
        )

    def detect(self, text: str) -> InjectionResult:
        """Detect injection attacks in text.

        Args:
            text: The prompt or input to check

        Returns:
            InjectionResult with detection status, confidence, and attack type
        """
        if not text or not isinstance(text, str):
            return InjectionResult(
                is_injection=False,
                confidence=0.0,
                attack_type=InjectionAttackType.UNKNOWN,
                reason="Empty or non-string input",
                metadata={}
            )

        # Check each pattern category
        checks = [
            (self.jailbreak_re, InjectionAttackType.JAILBREAK, "Jailbreak pattern detected"),
            (self.system_prefix_re, InjectionAttackType.PREAMBLE_INJECTION, "System prefix injection"),
            (self.context_escape_re, InjectionAttackType.CONTEXT_ESCAPE, "Context escape attempt"),
            (self.preamble_re, InjectionAttackType.PROMPT_OVERRIDE, "Preamble injection pattern"),
        ]

        for pattern, attack_type, reason in checks:
            if pattern.search(text):
                return InjectionResult(
                    is_injection=True,
                    confidence=0.85,  # Regex match is high confidence
                    attack_type=attack_type,
                    reason=reason,
                    metadata={"pattern_matched": pattern.pattern[:100]}
                )

        # Heuristic: suspicious length ratio (e.g., prompt longer than typical)
        if len(text) > 10000:
            return InjectionResult(
                is_injection=True,
                confidence=0.4,
                attack_type=InjectionAttackType.UNKNOWN,
                reason="Unusually long prompt (>10k chars)",
                metadata={"text_length": len(text)}
            )

        return InjectionResult(
            is_injection=False,
            confidence=0.0,
            attack_type=InjectionAttackType.UNKNOWN,
            reason="No injection patterns detected",
            metadata={}
        )


_detector = InjectionDetector()


def detect_injection(text: str, model_name: str = "gpt-4o-mini") -> InjectionResult:
    """Detect prompt injection in text.

    Uses regex patterns first; optional LLM fallback deferred to Session 05.

    Args:
        text: The prompt/input to check
        model_name: Unused in Session 03 (LLM-based detection in Session 05)

    Returns:
        InjectionResult with detection details
    """
    result = _detector.detect(text)

    # Log all injection attempts (both positive and negative for monitoring)
    try:
        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "text_hash": hash(text),
            "is_injection": result.is_injection,
            "confidence": result.confidence,
            "attack_type": result.attack_type.value,
            "reason": result.reason,
        }
        _append_jsonl("data/injection_attempts.jsonl", log_entry)
    except Exception as e:
        print(f"Warning: injection logging failed: {e}")

    return result


def injection_stats() -> dict:
    """Return injection detection statistics.

    Returns:
        Dict with counts by attack_type, detection rate, etc.
    """
    try:
        with open("data/injection_attempts.jsonl", "r") as f:
            entries = [json.loads(line) for line in f]

        if not entries:
            return {
                "total_scanned": 0,
                "injections_detected": 0,
                "detection_rate": 0.0,
                "by_attack_type": {}
            }

        injections = [e for e in entries if e.get("is_injection")]
        by_type = {}
        for attack_type in InjectionAttackType:
            count = len([e for e in injections if e.get("attack_type") == attack_type.value])
            if count > 0:
                by_type[attack_type.value] = count

        return {
            "total_scanned": len(entries),
            "injections_detected": len(injections),
            "detection_rate": len(injections) / len(entries) if entries else 0.0,
            "by_attack_type": by_type,
        }
    except FileNotFoundError:
        return {
            "total_scanned": 0,
            "injections_detected": 0,
            "detection_rate": 0.0,
            "by_attack_type": {}
        }
