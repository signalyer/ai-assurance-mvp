# SESSION 05 — Provider Abstraction (Pluggable Backends)
# Date: TBD (after Session 04 complete)
# Context cost: MEDIUM
# Status: PENDING

## What this session will build
A provider abstraction layer that makes scrubber, tracer, evaluator, and memory backends swappable via env vars. Today everything is hardcoded to Presidio + Langfuse + DeepEval + Postgres. After Session 05, you can swap one out by changing one env var.

## Why now
Sessions 01-04 built the right thing (compose, don't rebuild — DECISIONS.md). Session 05 makes it portable: a customer who can't use Langfuse Cloud (data sovereignty) can swap to self-hosted Langfuse or LangSmith without code changes.

## Pre-conditions (ALL MET)
- [x] Sessions 01a + 01b complete (scrubber + decorator)
- [x] Session 02 complete (policy engine)
- [x] Session 03 complete (guardrails)
- [x] Session 04 complete (memory + RAG)
- [x] All current backends working in production

## Files to Create
1. **`providers.py`** — Backend registry + factory
   - `get_scrubber()` — returns active scrubber instance (Presidio | regex-only | custom)
   - `get_tracer()` — returns active tracer (Langfuse | LangSmith | stdout | noop)
   - `get_evaluator()` — returns active evaluator (DeepEval | Anthropic-native | custom)
   - `get_memory_backend()` — returns active store (Postgres | JSONL | Cosmos)
   - `get_rag_backend()` — returns active RAG (Azure Search | Qdrant | Pinecone)

2. **`providers/scrubber_backends.py`** — Pluggable scrubber implementations
3. **`providers/tracer_backends.py`** — Pluggable tracer implementations
4. **`providers/eval_backends.py`** — Pluggable eval implementations
5. **`providers/memory_backends.py`** — Pluggable memory implementations
6. **`providers/rag_backends.py`** — Pluggable RAG implementations

## Files to Modify
1. **`scrubber.py`** — proxy through `providers.get_scrubber()`
2. **`tracer.py`** — proxy through `providers.get_tracer()`
3. **`evaluator.py`** — proxy through `providers.get_evaluator()`
4. **`domain/agent_memory.py`** — proxy through `providers.get_memory_backend()`
5. **`domain/rag_engine.py`** — proxy through `providers.get_rag_backend()`

## Architectural Constraints
- ✓ Backward compat: all existing code MUST work unchanged
- ✓ Env-var driven: SCRUBBER_BACKEND, TRACER_BACKEND, EVAL_BACKEND, MEMORY_BACKEND, RAG_BACKEND
- ✓ Fail-closed: unknown backend → import error at module load
- ✓ Type safety: every backend implements an explicit Protocol
- ✓ No business logic in providers.py — only factory + registry

## Acceptance Criteria (10 tests)
- 5 backend Protocols defined and importable
- 5 default backends register correctly
- Swap via env var works (set SCRUBBER_BACKEND=regex → uses regex-only)
- Unknown backend → ImportError with clear message
- All Session 01-04 tests still pass (regression check)

## What NOT to build
- ❌ Actual second backend implementations (only the abstraction)
- ❌ Backend hot-swap UI (Session 06)
- ❌ Backend selection in customer onboarding (v2)

## Open questions to resolve before starting
1. Should backend protocols be Pydantic or `typing.Protocol`? (Pydantic for runtime validation; Protocol for structural typing)
2. Should we drop `legacy_guardrails.py` or wrap it as a `regex-only` guardrails backend?

## Next session preview (Session 06)
- `api/policies.py` + `static/policy-engine.html` — policy management UI
- `static/rag-governance.html` — RAG corpus admin UI
- Hook into the provider layer (display active backends)
