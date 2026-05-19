"""Langfuse instrumentation wrapper for LLM tracing and observability."""

import os
import json
import functools
from typing import Any, Callable, Optional
from langfuse import Langfuse
from langfuse.decorators import observe


def _load_env_vars() -> dict[str, str]:
    """Load required environment variables for Langfuse configuration."""
    from dotenv import load_dotenv
    load_dotenv()

    required_vars = ["LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"]
    missing = [var for var in required_vars if not os.getenv(var)]

    if missing:
        raise ValueError(f"Missing required environment variables: {', '.join(missing)}")

    return {
        "public_key": os.getenv("LANGFUSE_PUBLIC_KEY"),
        "secret_key": os.getenv("LANGFUSE_SECRET_KEY"),
        "host": os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"),
    }


class LangfuseTracer:
    """Wrapper for Langfuse client with convenient tracing methods."""

    def __init__(self) -> None:
        """Initialize Langfuse client from environment variables."""
        env_vars = _load_env_vars()
        self.client = Langfuse(
            public_key=env_vars["public_key"],
            secret_key=env_vars["secret_key"],
            host=env_vars["host"],
        )

    def trace_llm_call(
        self,
        function_name: str,
        model: str,
        input_data: dict[str, Any],
        output_data: Any,
        metadata: Optional[dict[str, Any]] = None,
    ) -> str:
        """
        Trace a single LLM API call.

        Args:
            function_name: Name of the function making the call
            model: Model identifier (e.g., 'gpt-4', 'claude-3-sonnet')
            input_data: Dict with 'messages' or 'prompt' key
            output_data: The complete response from the LLM
            metadata: Optional dict with additional context (task_id, user_id, etc.)

        Returns:
            Trace ID string for reference
        """
        trace = self.client.trace(name=function_name)

        generation = trace.generation(
            name=f"{function_name}_{model}",
            model=model,
            input=input_data,
            output=output_data,
            metadata=metadata or {},
        )

        return trace.id

    def trace_evaluation(
        self,
        trace_id: str,
        metric_name: str,
        metric_value: float,
        passed: bool,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        """
        Log evaluation metric for a traced call.

        Args:
            trace_id: The trace ID from trace_llm_call
            metric_name: Name of the metric (e.g., 'relevance', 'coherence')
            metric_value: Numeric score or value
            passed: Boolean indicating pass/fail
            details: Optional dict with reasoning or explanation
        """
        self.client.score(
            trace_id=trace_id,
            name=metric_name,
            value=metric_value,
            comment=json.dumps(details or {}),
        )

    def flush(self) -> None:
        """Flush all pending traces to Langfuse."""
        self.client.flush()


# Decorator for automatic tracing
def trace_function(tracer: LangfuseTracer, model: Optional[str] = None) -> Callable:
    """
    Decorator to automatically trace function execution with Langfuse.

    Args:
        tracer: LangfuseTracer instance
        model: Model name to record (optional, can be overridden in function)

    Returns:
        Decorator function
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            function_name = func.__name__
            result = func(*args, **kwargs)

            # Collect input data from kwargs (excluding large objects)
            input_data = {k: v for k, v in kwargs.items() if isinstance(v, (str, int, float, bool, list, dict))}

            # Trace the call if result is dict-like with standard LLM response
            if isinstance(result, dict) and ("content" in result or "message" in result):
                tracer.trace_llm_call(
                    function_name=function_name,
                    model=model or "unknown",
                    input_data=input_data,
                    output_data=result,
                )

            return result
        return wrapper
    return decorator


if __name__ == "__main__":
    # Standalone test
    tracer = LangfuseTracer()
    print("✓ Langfuse client initialized successfully")

    # Trace a mock LLM call
    trace_id = tracer.trace_llm_call(
        function_name="test_llm_call",
        model="gpt-4",
        input_data={"prompt": "What is 2+2?"},
        output_data={"content": "The answer is 4."},
        metadata={"test": True},
    )
    print(f"✓ Traced LLM call with ID: {trace_id}")

    # Log a metric
    tracer.trace_evaluation(
        trace_id=trace_id,
        metric_name="accuracy",
        metric_value=0.95,
        passed=True,
        details={"reasoning": "Math was correct"},
    )
    print("✓ Logged evaluation metric")

    tracer.flush()
    print("✓ Flushed traces to Langfuse Cloud")
