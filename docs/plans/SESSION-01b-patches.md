# SESSION-01b — Tracer Patch + Decorator Wiring
# Date: 2026-05-22 (planned)
# Context cost: MEDIUM

## What this session builds
Integration of the scrubber into the tracer pipeline via the `@scrub_pii` decorator.

TWO new files:
1. `middleware/scrubber.py` — `@scrub_pii` decorator
2. Modifications to 4 existing files (see below)

NO new JSONL or vault files — all scrubber/vault code from 01a is reused.

## Pre-conditions
- [ ] `scrubber.py` exists and passes all smoke tests (Session 01a ✓)
- [ ] `domain/deid_vault.py` exists and passes all smoke tests (Session 01a ✓)
- [ ] `ARCHITECTURE.md` lists scrubber.py + deid_vault.py as "Built (2026-05-21)"
- [ ] Requirements.txt includes presidio-analyzer, presidio-anonymizer, cryptography (Session 01a ✓)
- [ ] `SESSION_SECRET` env var set (reuse from 01a)
- [ ] `SCRUBBER_ENABLED=true`, `DEID_VAULT_TTL_SECONDS=3600` in `.env` (can add in this session)

## Files to create
1. `middleware/scrubber.py` (new)
   - Public API: `@scrub_pii(scope: str = "default")` decorator
   - Decorator chain position: BEFORE `@trace_llm_call`
   - Signature: wraps async functions that take a `prompt` kwarg or positional arg
   - Pre-call: tokenise_payload(prompt) → returns (scrubbed, vault_id)
   - Post-call: log vault_id to trace metadata
   - Fail-closed: if vault_id empty, do NOT call wrapped function (drop the trace)
   - Type hints on all parameters; docstring on the decorator

## Files to modify
1. `tracer.py` — add vault_id awareness
   - Modify `trace_call()` to accept optional `vault_id` parameter
   - If vault_id provided, log it in metadata (don't change the prompt storage)
   - Always use `prompt` passed to trace_call, never raw_prompt
   - Line ~41-61: function signature and docstring

2. `evaluator.py` — wire @scrub_pii before trace call
   - Find the call site that invokes tracer.trace_call()
   - Ensure scrubber.tokenise_payload() called before tracer.trace_call()
   - Pass vault_id to tracer.trace_call() metadata

3. `api/demo_run.py` — apply decorator to entry point
   - Find the function that calls evaluator.py (e.g., demo_run_llm())
   - Add `@scrub_pii(scope="demo-run")` decorator
   - Verify that decorated function receives prompt as kwarg or first positional arg

4. `dashboard.py` — mount @scrub_pii at middleware level (optional)
   - OR: document that scrubbing happens at call-site level, not middleware
   - Decision: per DECISIONS.md, scrubbing is call-site-driven (tight control), not blanket

## Architectural constraints (copied from ARCHITECTURE.md)
- `scrubber.tokenise_payload()` runs BEFORE `tracer.trace_call()` — verify at every call site
- Langfuse receives `scrubbed_prompt`, never `raw_prompt`
- No PII in any log, JSONL, or trace
- Fail-closed: if scrubber errors or vault_id empty, do NOT trace (drop locally)
- Type hints on every public function; docstring on every public function
- Decorator chain order: `@policy_gate` → `@scrub_pii` → `@trace_llm_call` → `@evaluate_response`

## What NOT to build in this session
- Do NOT touch policy engine, guardrails, or RAG
- Do NOT add memory tiers (T2, T3, T4) — memory is Session 04
- Do NOT touch any UI files
- Do NOT build Postgres materialized views (Session 09)
- Do NOT build provider abstraction (Session 05)

## Acceptance criteria
```bash
# Module imports succeed
python -c "from middleware.scrubber import scrub_pii; print('OK')"

# Decorator preserves function signature
python -c "
from middleware.scrubber import scrub_pii

@scrub_pii(scope='test')
async def dummy_fn(prompt: str) -> str:
    return f'Response to: {prompt}'

assert hasattr(dummy_fn, '__name__'), 'FAIL: decorator lost __name__'
assert 'dummy_fn' in str(dummy_fn.__name__), 'FAIL: __name__ incorrect'
print('OK: decorator preserves signature')
"

# Scrubbing + tracing integration (end-to-end)
python -c "
import asyncio
from middleware.scrubber import scrub_pii

call_log = []

@scrub_pii(scope='e2e-test')
async def mock_llm_call(prompt: str) -> str:
    # Simulate scrubber + trace call
    call_log.append({'prompt': prompt})
    return 'Response'

# Test: prompt with PII should be scrubbed
pii_prompt = 'What is john@example.com email for?'
result = asyncio.run(mock_llm_call(pii_prompt))

assert len(call_log) == 1, 'FAIL: call_log not populated'
logged_prompt = call_log[0]['prompt']
assert 'john@example.com' not in logged_prompt, 'FAIL: email leaked to call_log'
print('OK: PII scrubbed before call')
"

# Tracer receives scrubbed prompt + vault_id
python -c "
from tracer import trace_call

# Mock trace call with vault_id
trace_id = trace_call(
    model='test-model',
    prompt='[EMAIL_ADDRESS_001]',  # Scrubbed
    response='Response',
    latency_ms=100,
    tokens_used=20,
    metadata={'vault_id': 'test-vault-001'}
)

assert trace_id, 'FAIL: trace_call returned empty trace_id'
print('OK: tracer accepts vault_id in metadata')
"

# No raw PII in Langfuse traces
# (Manual inspection: curl -s https://cloud.langfuse.com/api/traces | grep 'john@example.com' should return nothing)
```

## Decorator implementation guide (start here)
The `@scrub_pii` decorator should:
1. Intercept the wrapped function call
2. Extract `prompt` from kwargs or first positional arg (flexible detection)
3. Call `scrubber.tokenise_payload(prompt, scope)` → (scrubbed, vault_id)
4. If vault_id empty, log error + skip wrapped function call (fail-closed)
5. Replace prompt arg with scrubbed version
6. Call wrapped function with scrubbed prompt
7. Return result as-is
8. Caller's responsibility: pass vault_id to tracer.trace_call(metadata={'vault_id': vault_id})

## End of session actions
1. Confirm all acceptance criteria PASS
2. Update `ARCHITECTURE.md`:
   - Move `tracer.py`, `evaluator.py`, `api/demo_run.py` from "In Progress" to "Built (2026-05-22)"
   - Move `@scrub_pii` decorator from "In Progress" to "Built"
   - Update env vars: mark `SCRUBBER_ENABLED`, `DEID_VAULT_TTL_SECONDS` as "Active (01b)"
3. Append to `DECISIONS.md`:
   - Decision: call-site-driven scrubbing vs middleware-level (chose call-site for tighter control)
   - Any deviations from the decorator design above
4. Write `docs/plans/SESSION-02-policy-engine.md` for the next session
5. List any deviations or open issues at the end of session output
6. Run `/verify` one final time before declaring complete

## Notes for implementation
- Async function wrapping: use `functools.wraps` + `async def` wrapper
- Prompt detection: check kwargs first for `prompt=`, then positional args (safer than index)
- Fail-closed means: if scrubber.tokenise_payload returns ("", ""), do NOT call the wrapped function
- This breaks the demo run if scrubbing fails, but that's intentional — fail audibly, don't silently skip
