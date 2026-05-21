# SESSION 05 — Provider Abstraction + Legacy Cleanup
# Date: 2026-05-21 (COMPLETE)
# Context cost: VERY HIGH (largest session yet — 11 new files, 7 modified, 1 deleted)
# Status: COMPLETE — 12 new + 40 regression tests pass

## What this session will build
Pluggable backend layer for scrubber / tracer / evaluator / memory / RAG, **and** delete the legacy regex-only guardrails module (replacing its callers with the new Session 03 guardrails package).

## User decisions (locked in 2026-05-21)
1. **Backend interfaces:** `typing.Protocol` (structural, zero-runtime-cost). Backend **config**: Pydantic v2 `BaseSettings` (env-var-driven, validated at startup).
2. **legacy_guardrails.py:** DELETE. Rewrite the two callers (`api/security.py`, `api/batch.py`) to use the new `middleware/injection.py` + `guardrails/llama_guard_adapter.py`.
3. **Pace:** Autopilot continues.

## Pre-conditions (ALL MET)
- [x] Sessions 01-04 complete · 40 acceptance tests pass
- [x] Decorator chain finalized: `@policy_gate → @scrub_pii → @guardrails → @trace_llm_call → @evaluate_response`
- [x] Memory architecture decided: T1 in-context · T2 Postgres · T3 Azure AI Search hybrid · T4 procedural

## Files to CREATE (11)
1. **`providers/__init__.py`** — Package init; re-export `get_scrubber`, `get_tracer`, `get_evaluator`, `get_memory_backend`, `get_rag_backend`
2. **`providers/protocols.py`** — Five `typing.Protocol` interfaces:
   - `ScrubberBackend` — `tokenise(text, scope) -> tuple[str, str]`, `restore(scrubbed, vault_id) -> str`
   - `TracerBackend` — `trace_call(model, prompt, response, latency_ms, tokens_used, metadata) -> str`
   - `EvaluatorBackend` — `evaluate(input_prompt, actual_output, context) -> dict`
   - `MemoryBackend` — `write(workload_id, prompt, response, outcome, metadata, ttl_seconds) -> str`, `read(workload_id, query, top_k, lookback_days) -> list[dict]`, `stats() -> dict`
   - `RagBackend` — `index(doc_id, content, metadata, scrub) -> bool`, `search(query, top_k, hybrid) -> list[dict]`, `stats() -> dict`
3. **`providers/config.py`** — Pydantic v2 `BaseSettings`:
   - `SCRUBBER_BACKEND` (default: `presidio`) · enum: `presidio | regex | noop`
   - `TRACER_BACKEND` (default: `langfuse`) · enum: `langfuse | stdout | noop`
   - `EVAL_BACKEND` (default: `deepeval`) · enum: `deepeval | noop`
   - `MEMORY_BACKEND` (default: `postgres`) · enum: `postgres | jsonl | noop`
   - `RAG_BACKEND` (default: `azure_search`) · enum: `azure_search | noop`
4. **`providers/registry.py`** — Factory functions returning the active backend per config; cache at module load
5. **`providers/backends/__init__.py`** — Package marker
6. **`providers/backends/scrubber_presidio.py`** — Wraps existing `scrubber.tokenise_payload`
7. **`providers/backends/scrubber_regex.py`** — Regex-only fallback (no Presidio NER)
8. **`providers/backends/tracer_langfuse.py`** — Wraps existing `tracer.trace_call`
9. **`providers/backends/memory_postgres.py`** — Wraps `domain.agent_memory`
10. **`providers/backends/rag_azure_search.py`** — Wraps `domain.rag_engine`
11. **`providers/backends/noop.py`** — No-op backends (return safe defaults) for tests/dev

## Files to MODIFY (7)
1. **`scrubber.py`** — Public functions proxy through `providers.get_scrubber()`; legacy direct callers still work
2. **`tracer.py`** — `trace_call()` proxies through `providers.get_tracer()`
3. **`evaluator.py`** — `evaluate_response()` proxies through `providers.get_evaluator()`
4. **`domain/agent_memory.py`** — Public functions proxy through `providers.get_memory_backend()` (the existing Postgres logic becomes the `postgres` backend)
5. **`domain/rag_engine.py`** — Public functions proxy through `providers.get_rag_backend()`
6. **`api/security.py`** — Replace `apply_guardrails` → `detect_injection`; replace `filter_output` → `evaluate_content`; remove `get_rail_summary` import and inline a minimal summary builder
7. **`api/batch.py`** — Replace `filter_output(text, domain)` → `evaluate_content(text)` returning `{safe, violations, score}` shape

## Files to DELETE (1)
1. **`legacy_guardrails.py`** — After api/security.py and api/batch.py migrated. Verified `grep -r "legacy_guardrails" .` returns zero matches before deletion.

## Architectural Constraints (NON-NEGOTIABLE)
1. **Backward compat:** All 40 existing acceptance tests across Sessions 01-04 must still pass unchanged. No call-site signatures change.
2. **Fail-closed on backend mismatch:** Unknown backend name in env var → raise at module load with clear message listing valid options.
3. **Backends are stateful objects:** Created once at module load (cached in `providers/registry.py`), reused per call.
4. **Config validation at startup:** Pydantic `BaseSettings` parses env vars once on import; raises if values are out of enum.
5. **Protocol contracts are the source of truth:** Every backend implementation must satisfy its Protocol (verified via `isinstance()` check using `runtime_checkable` Protocol).
6. **legacy_guardrails deletion is atomic:** No `// removed` comments left behind. `git rm`, callers rewritten in same commit.

## Two most critical architectural risks
1. **Subtle backward-compat break:** Proxying scrubber/tracer/eval through providers could change error semantics in edge cases (e.g., empty prompt). Mitigation: regression-test all 40 prior acceptance tests.
2. **Stateful backend lifecycle:** If `get_memory_backend()` creates a new Postgres engine on every call instead of caching, connection pool will exhaust. Mitigation: registry caches via module-level `lru_cache` or simple dict.

## Will NOT build in this session
- ❌ Actual second non-default backend implementations (no real LangSmith adapter — just the protocol + a `noop` stub to prove swapping works)
- ❌ Backend hot-swap UI (defer to Session 06)
- ❌ Backend selection in customer onboarding flow (defer to v2)
- ❌ Multi-language scrubber backends
- ❌ Migration of `domains.py` (Tier 4) to a provider — it's stateless config, doesn't need abstraction

## Acceptance Criteria — 12 tests
```bash
# Group 1: Provider infrastructure (4 tests)
python -c "from providers import get_scrubber, get_tracer, get_evaluator, get_memory_backend, get_rag_backend; print('OK imports')"
python -c "from providers.protocols import ScrubberBackend, TracerBackend, EvaluatorBackend, MemoryBackend, RagBackend; print('OK protocols')"
python -c "from providers.config import ProviderSettings; s=ProviderSettings(); print(f'OK defaults: scrubber={s.scrubber_backend}')"
python -c "
import os; os.environ['SCRUBBER_BACKEND']='invalid_backend_name'
try: from providers.config import ProviderSettings; ProviderSettings()
except Exception as e: print(f'OK fail-closed: {type(e).__name__}')
"

# Group 2: Backend swap (3 tests)
python -c "
import os; os.environ['SCRUBBER_BACKEND']='regex'
from providers import get_scrubber
s = get_scrubber()
result, vault_id = s.tokenise('SSN 123-45-6789', 'test')
assert '123-45-6789' not in result, 'FAIL: regex scrubber leaked SSN'
print('OK SCRUBBER_BACKEND=regex works')
"
python -c "
import os; os.environ['TRACER_BACKEND']='noop'
from providers import get_tracer
t = get_tracer()
trace_id = t.trace_call('test-model', 'prompt', 'response', 100, 50, {'vault_id': 'v1'})
assert trace_id is not None, 'FAIL: noop tracer returned None'
print('OK TRACER_BACKEND=noop works')
"
python -c "
import os; os.environ['MEMORY_BACKEND']='noop'
from providers import get_memory_backend
m = get_memory_backend()
ep_id = m.write('test', 'p', 'r', 'success', {}, None)
assert ep_id is not None, 'FAIL: noop memory returned None'
print('OK MEMORY_BACKEND=noop works')
"

# Group 3: Backward compat (3 tests) — all Session 01-04 surfaces still work
python -c "from scrubber import tokenise_payload; r,v = tokenise_payload('test', 'x'); print('OK scrubber proxy')"
python -c "from tracer import trace_call; print('OK tracer proxy')"
python -c "from domain.agent_memory import write_episode, build_context; print('OK memory proxy')"

# Group 4: Legacy cleanup verified (2 tests)
python -c "
import subprocess
result = subprocess.run(['grep', '-rln', 'legacy_guardrails', '.'], capture_output=True, text=True)
assert result.stdout.strip() == '', f'FAIL: legacy_guardrails refs remain: {result.stdout}'
print('OK no legacy_guardrails references')
" 2>&1 || python -c "
import os
for root, dirs, files in os.walk('.'):
    if '.git' in root or 'node_modules' in root: continue
    for f in files:
        if not f.endswith(('.py', '.md')): continue
        path = os.path.join(root, f)
        with open(path, encoding='utf-8', errors='ignore') as h:
            if 'legacy_guardrails' in h.read():
                print(f'FAIL: {path} still references legacy_guardrails')
                exit(1)
print('OK no legacy_guardrails references')
"
python -c "
import os
assert not os.path.exists('legacy_guardrails.py'), 'FAIL: legacy_guardrails.py still exists'
print('OK legacy_guardrails.py deleted')
"
```

## Execution plan (sub-agent parallelization)

Three sub-agents in **one message**:
- **Agent A (implementer):** Build entire `providers/` package — protocols.py, config.py, registry.py, and 6 backend modules (including 2 noop variants)
- **Agent B (implementer):** Refactor 5 root/domain modules to proxy through providers (scrubber.py, tracer.py, evaluator.py, agent_memory.py, rag_engine.py) — preserving backward compatibility
- **Agent C (implementer):** Delete legacy_guardrails.py + rewrite api/security.py and api/batch.py to use new guardrails package

Main thread: run all 12 acceptance tests + all 40 regression tests + spawn code-reviewer.

## Decision Log entries to add
- Backend interfaces: `typing.Protocol` over Pydantic BaseModel for stateful backends
- Legacy guardrails: deleted, no backward-compat shim (single-tenant project, no external consumers)
- Provider config: Pydantic v2 BaseSettings at startup vs per-call

## End-of-Session Actions
1. All 12 new + 40 regression tests pass
2. Code-reviewer + security-reviewer in parallel
3. ARCHITECTURE.md updated · DECISIONS.md appended · SESSION-06 plan written · HANDOFF.md updated
4. Two commits: feat + docs
