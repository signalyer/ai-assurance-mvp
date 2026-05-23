"""Guardrails decorator orchestrating injection detection, topic enforcement, and content safety."""
from __future__ import annotations

import asyncio
import functools
import json
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any, Callable, Optional

from middleware.injection import detect_injection, InjectionResult
from guardrails.nemo_adapters import validate_topic, TopicValidationResult
from guardrails.llama_guard_adapter import evaluate_content, LlamaGuardResult
from storage import _append_jsonl


_TEXT_FIELDS = ("response_text", "actual_output", "text", "response", "output", "content")


def _extract_text(value: Any) -> str:
    """Coerce a wrapped-function return value to text for safety scanning.

    Guardrails decorators wrap handlers that may return either a raw string
    or a structured run dict (e.g. _build_run() output in api/demo_run.py).
    LlamaGuard's pattern matcher requires a string — passing a dict raises
    AttributeError on .lower(). This helper centralises the coercion so the
    decorator contract stays loose without losing safety coverage.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in _TEXT_FIELDS:
            v = value.get(key)
            if isinstance(v, str) and v:
                return v
        return ""
    return str(value)


class GuardrailViolationError(Exception):
    """Raised when guardrail enforcement fails."""
    def __init__(self, message: str, violation_type: str, details: dict):
        super().__init__(message)
        self.violation_type = violation_type
        self.details = details


@dataclass
class GuardrailResult:
    """Result of guardrail enforcement."""
    passed: bool
    violations: list[str]                      # List of violation reasons
    injection_result: Optional[InjectionResult] = None
    topic_result: Optional[TopicValidationResult] = None
    safety_result: Optional[LlamaGuardResult] = None
    metadata: dict = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class GuardrailsMiddleware:
    """Orchestrates multiple guardrail checks."""

    def __init__(
        self,
        enable_injection: bool = True,
        enable_nemo: bool = True,
        enable_llama_guard: bool = True,
        strict: bool = False,
    ):
        """Initialize guardrails middleware.

        Args:
            enable_injection: Enable prompt injection detection
            enable_nemo: Enable NeMo topic enforcement
            enable_llama_guard: Enable Llama Guard 3 content safety
            strict: If True, any failure raises GuardrailViolationError
        """
        self.enable_injection = enable_injection
        self.enable_nemo = enable_nemo
        self.enable_llama_guard = enable_llama_guard
        self.strict = strict

    async def check_input(
        self,
        prompt: str,
        workload_id: Optional[str] = None,
        allowed_topics: Optional[list[str]] = None,
    ) -> GuardrailResult:
        """Check input (prompt) for injection and topic violations.

        Args:
            prompt: The user prompt
            workload_id: Workload context for topic enforcement
            allowed_topics: List of allowed topics for this workload; auto-set for known workloads

        Returns:
            GuardrailResult with pass/fail status and details
        """
        violations = []
        injection_result = None
        topic_result = None

        # 1. Injection detection
        if self.enable_injection and prompt:
            injection_result = detect_injection(prompt)
            if injection_result.is_injection:
                violations.append(f"Injection detected: {injection_result.reason}")

        # 2. Topic enforcement (NeMo)
        # Auto-set allowed_topics for known workloads
        if self.enable_nemo and workload_id and not allowed_topics:
            from guardrails.nemo_adapters import TopicClassifier
            if workload_id == "financial_advisor":
                allowed_topics = TopicClassifier.ALLOWED_TOPICS_DEFAULT

        if self.enable_nemo and workload_id and allowed_topics:
            topic_result = validate_topic(prompt, workload_id, allowed_topics)
            if not topic_result.is_valid:
                violations.append(f"Topic violation: {topic_result.reason}")

        passed = len(violations) == 0

        result = GuardrailResult(
            passed=passed,
            violations=violations,
            injection_result=injection_result,
            topic_result=topic_result,
            metadata={
                "check_type": "input",
                "workload_id": workload_id,
            }
        )

        await self._log_guardrail_check(result, prompt[:200] if prompt else "")

        return result

    async def check_output(
        self,
        response: Any,
        context: Optional[dict] = None,
    ) -> GuardrailResult:
        """Check output (response) for unsafe content.

        Args:
            response: The LLM response. May be a str, or a dict produced by
                _build_run() containing a text field. Non-string inputs are
                coerced via _extract_text() so the decorator stays compatible
                with handlers that return structured run records.
            context: Optional context dict

        Returns:
            GuardrailResult with pass/fail status and details
        """
        text = _extract_text(response)

        violations = []
        safety_result = None

        # Llama Guard 3 content safety check
        if self.enable_llama_guard and text:
            safety_result = evaluate_content(text)
            if not safety_result.safe:
                violations.append(f"Unsafe content: {', '.join(safety_result.violations)}")

        passed = len(violations) == 0

        result = GuardrailResult(
            passed=passed,
            violations=violations,
            safety_result=safety_result,
            metadata={
                "check_type": "output",
                "response_length": len(text) if text else 0,
            }
        )

        await self._log_guardrail_check(result, text[:200] if text else "")

        return result

    async def _log_guardrail_check(self, result: GuardrailResult, text_sample: str) -> None:
        """Log guardrail check to audit trail.

        Args:
            result: The GuardrailResult
            text_sample: Sample text for context
        """
        try:
            log_entry = {
                "timestamp": datetime.utcnow().isoformat(),
                "passed": result.passed,
                "violations": result.violations,
                "check_type": result.metadata.get("check_type"),
                "text_sample": text_sample[:100],
            }
            _append_jsonl("data/guardrail_violations.jsonl", log_entry)
        except Exception as e:
            print(f"Warning: guardrail logging failed: {e}")


def guardrails(
    enable_injection: bool = True,
    enable_nemo: bool = True,
    enable_llama_guard: bool = True,
    strict: bool = False,
    workload_id_arg: str = "workload_id",
    allowed_topics_arg: str = "allowed_topics",
) -> Callable:
    """Decorator for guardrail enforcement on LLM-calling functions.

    Usage:
        @guardrails(enable_injection=True, enable_nemo=True)
        async def my_llm_call(prompt: str, workload_id: str = None) -> str:
            # LLM call here
            return response

    Args:
        enable_injection: Enable injection detection on input
        enable_nemo: Enable topic enforcement on input
        enable_llama_guard: Enable content safety on output
        strict: Raise exception on any violation (default: soft warnings)
        workload_id_arg: Name of workload_id parameter
        allowed_topics_arg: Name of allowed_topics parameter

    Returns:
        Decorated function with guardrail checks
    """

    def decorator(func: Callable) -> Callable:
        middleware = GuardrailsMiddleware(
            enable_injection=enable_injection,
            enable_nemo=enable_nemo,
            enable_llama_guard=enable_llama_guard,
            strict=strict,
        )

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs) -> Any:
            # Extract arguments
            prompt = kwargs.get("prompt") or (args[0] if args else "")
            workload_id = kwargs.get(workload_id_arg)
            allowed_topics = kwargs.get(allowed_topics_arg)

            # Check input (injection + topic)
            input_result = await middleware.check_input(
                prompt=prompt,
                workload_id=workload_id,
                allowed_topics=allowed_topics,
            )

            if not input_result.passed:
                error_msg = "; ".join(input_result.violations)
                if strict:
                    raise GuardrailViolationError(
                        f"Input guardrail violation: {error_msg}",
                        violation_type="input",
                        details=asdict(input_result),
                    )
                # Soft warning: log but continue
                print(f"WARNING: Input guardrail violation: {error_msg}")

            # Call the actual function
            response = await func(*args, **kwargs)

            # Check output (content safety)
            output_result = await middleware.check_output(
                response=response,
                context={"workload_id": workload_id},
            )

            if not output_result.passed:
                error_msg = "; ".join(output_result.violations)
                if strict:
                    raise GuardrailViolationError(
                        f"Output guardrail violation: {error_msg}",
                        violation_type="output",
                        details=asdict(output_result),
                    )
                # Soft warning: log but return (don't suppress response)
                print(f"WARNING: Output guardrail violation: {error_msg}")

            # Attach guardrail results to kwargs for downstream handlers
            kwargs["guardrail_result"] = GuardrailResult(
                passed=input_result.passed and output_result.passed,
                violations=input_result.violations + output_result.violations,
                injection_result=input_result.injection_result,
                topic_result=input_result.topic_result,
                safety_result=output_result.safety_result,
            )

            return response

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs) -> Any:
            # For sync functions, run async checks in event loop
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(async_wrapper(*args, **kwargs))

        # Detect if function is async
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    return decorator


def guardrails_stats() -> dict:
    """Return guardrails enforcement statistics.

    Returns:
        Dict with counts of violations by type, pass rate, etc.
    """
    try:
        with open("data/guardrail_violations.jsonl", "r") as f:
            entries = [json.loads(line) for line in f]

        if not entries:
            return {
                "total_checks": 0,
                "passed": 0,
                "failed": 0,
                "pass_rate": 0.0,
                "by_type": {}
            }

        passed = len([e for e in entries if e.get("passed")])
        failed = len(entries) - passed

        # Count by violation type
        by_type = {}
        for e in entries:
            for violation in e.get("violations", []):
                violation_type = violation.split(":")[0]  # e.g., "Injection" from "Injection detected: ..."
                by_type[violation_type] = by_type.get(violation_type, 0) + 1

        return {
            "total_checks": len(entries),
            "passed": passed,
            "failed": failed,
            "pass_rate": passed / len(entries) if entries else 0.0,
            "by_type": by_type,
        }
    except FileNotFoundError:
        return {
            "total_checks": 0,
            "passed": 0,
            "failed": 0,
            "pass_rate": 0.0,
            "by_type": {}
        }
