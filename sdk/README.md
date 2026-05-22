# SignalLayer Python SDK

Python SDK for the [SignalLayer AI Assurance Platform](https://aigovern.sandboxhub.co).

## Install (editable, internal development)

```bash
pip install -e ./sdk
```

## 60-second quickstart

```python
import os
import signallayer

# 1. Initialise once at startup (reads SL_API_KEY + SL_API_BASE_URL from env if not passed)
signallayer.init(
    api_key=os.environ["SL_API_KEY"],
    base_url=os.environ["SL_API_BASE_URL"],
)

# 2. Decorate your LLM-calling function with the platform chain
#    Order is MANDATORY: policy_gate → scrub_pii → guardrails → trace → evaluate
@signallayer.policy_gate(action="llm_call")
@signallayer.scrub_pii(scope="billing")
@signallayer.guardrails()
async def call_llm(prompt: str, workload_id: str = "billing-agent") -> str:
    # Your LLM call here (Anthropic, OpenAI, etc.)
    return f"Response to: {prompt}"

# 3. Assert the chain is in the correct order at import time
signallayer.guard(call_llm)

# 4. Call it
import asyncio
result = asyncio.run(call_llm(prompt="What is the balance?"))
print(result)
```

## HTTP client (signed API calls)

```python
client = signallayer.get_client()
result = client.get("/api/health")

if isinstance(result, signallayer.client.Ok):
    print(result.value)
else:
    print(f"Error: {result.error}")
```

## Runnable example

```bash
SL_API_KEY=dev:secret SL_API_BASE_URL=http://localhost:8000 python sdk/examples/billing_agent.py
```

## Decorator chain

```
@policy_gate  (outermost)
  @scrub_pii
    @guardrails
      @trace      # alias for tracer.trace_call
        @evaluate # alias for evaluator.evaluate_response (innermost)
```

Use `signallayer.guard(fn)` after stacking decorators to assert the order at import time.
It raises `DecoratorOrderError` on wrong order or `ChainBrokenError` on missing decorators.

## Error types

| Exception | When raised |
|---|---|
| `SignalLayerError` | Base class for all SDK errors |
| `AuthError` | API returned 401 (bad key or signature) |
| `PolicyDeniedError` | API returned 403 (policy DENY) |
| `DecoratorOrderError` | `guard()` detected wrong decorator order |
| `ChainBrokenError` | `guard()` detected a missing required decorator |
