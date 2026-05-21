# SESSION 04 — Memory + RAG (Agent Memory + Azure AI Search)
# Date: 2026-05-21 (planned)
# Context cost: VERY HIGH
# Status: PENDING

## What this session will build
Four-tier agent memory system (in-context, episodic, RAG, procedural) integrated with Azure AI Search:
1. `domain/agent_memory.py` — Agent memory manager with `build_context()`, `write_episode()`, `compress_episode()`, `selective_recall()`
2. `domain/rag_engine.py` — Azure AI Search wrapper with index-time scrubbing and retrieval
3. `data/episodes_{workload_id}.jsonl` — Episodic memory store (Tier 2)
4. RAG corpus pre-scrubbed at index time — PII > 0.7 confidence rejected
5. Memory endpoint in `api/memory.py` — `/api/memory/episodes`, `/api/memory/recall`, `/api/memory/stats`
6. UI: `static/memory.html` — memory viewer and episode browser

## Pre-conditions (ALL MET)
- [x] Session 01a complete (scrubber + vault built)
- [x] Session 01b complete (decorator pattern + tracer hardened)
- [x] Session 02 complete (policy engine + trust scorer)
- [x] Session 03 complete (guardrails + injection/topic/safety)
- [x] Decorator chain finalized: `@policy_gate → @scrub_pii → @guardrails → @trace_llm_call → @evaluate_response`
- [x] Azure AI Search provisioned and credentials applied
- [x] Pydantic v2 + Python 3.12 environment ready
- [x] JSONL storage pattern established via `storage.py`

## Files Created
1. **`domain/agent_memory.py`** — Four-tier memory system
   - `build_context(workload_id, lookback_days=7) -> str` — fetch context from Tiers 2+3+4
   - `write_episode(workload_id, episode_data, vault_id=None) -> str` — log episode to Tier 2 JSONL
   - `compress_episode(workload_id, episode_id) -> str` — summarize episode for long-term storage
   - `selective_recall(workload_id, query, top_k=5) -> list[dict]` — search and rank memories
   - Memory schema: episode_id, timestamp, prompt, response, outcome, metadata (scrubbed)

2. **`domain/rag_engine.py`** — RAG index wrapper
   - `index_document(doc_id, content, metadata, scrub=True) -> bool` — add to index, reject if PII > 0.7
   - `search_corpus(query, top_k=5) -> list[dict]` — retrieve relevant documents
   - `rag_stats() -> dict` — index size, doc count, last update
   - Uses Azure AI Search client (HTTP + API key)
   - Field schema: id, content, metadata, embedding (from text-embedding-3-small)

3. **`api/memory.py`** — Memory API router
   - `POST /api/memory/episodes` — write episode from LLM call result
   - `GET /api/memory/episodes?workload_id={id}&limit={n}` — list episodes (scrubbed)
   - `GET /api/memory/recall?workload_id={id}&query={q}` — semantic search across memories
   - `GET /api/memory/stats` — memory system statistics

4. **`static/memory.html`** — Memory viewer UI
   - Episode browser: timeline of past interactions
   - Search: semantic search across episodic + RAG corpus
   - Context builder: display what `build_context()` returns for a workload
   - Stats: memory system usage (episode count, index size, TTL expiration)

## Files Modified
1. **`api/demo_run.py`**
   - After LLM call succeeds, write episode via `agent_memory.write_episode()`
   - Include trace_id, eval_scores, guardrail_result in episode metadata

2. **`dashboard.py`**
   - Import and mount `api/memory.py` router
   - Add link to memory.html in Command Center

3. **`ARCHITECTURE.md`**
   - Move Session 04 files to "Built" section
   - Update "Environment variables" to reflect RAG_ENABLED, AZURE_SEARCH_* vars
   - Add four-tier memory diagram

## Architectural Constraints
- ✓ Tier 2 (episodic) stored as JSONL via `storage.py` pattern — append-only
- ✓ Tier 3 (RAG) uses Azure AI Search — no local vector store (Cloud-native preference)
- ✓ Index-time scrubbing: documents with PII > 0.7 are rejected before indexing
- ✓ TTL enforcement in Python layer (Tier 2 JSONL); Azure Search retains all (legal hold)
- ✓ Memory is workload-scoped: can query episodes only for workload_id you own
- ✓ Backward compat: `RAG_ENABLED=false` disables indexing (memory/recall still work on Tier 2)
- ✓ Recall context built from Tiers 2+3+4 (episodic + RAG + procedural domains.py)

## Memory Tiers
- **T1 (in-context):** Current prompt + recent context window (~8k tokens)
- **T2 (episodic):** Per-session JSONL `data/episodes_{workload_id}.jsonl` (append-only, TTL-enforced)
- **T3 (RAG):** Azure AI Search vector corpus (full-text + semantic search, scrubbed at index time)
- **T4 (procedural):** `domains.py` — workload definitions, policies, rules (immutable in v1)

## Acceptance Criteria (12 tests total)
```bash
# 1. Module imports (3 tests)
python -c "from domain.agent_memory import build_context, write_episode; print('OK agent_memory')"
python -c "from domain.rag_engine import index_document, search_corpus; print('OK rag_engine')"
python -c "from api.memory import router; print('OK memory api')"

# 2. Agent memory (3 tests)
# Test 2a: write_episode() appends to data/episodes_{workload_id}.jsonl
# Test 2b: build_context() returns all tiers (T2 + T3 + T4)
# Test 2c: selective_recall() returns ranked results by relevance

# 3. RAG engine (3 tests)
# Test 3a: index_document() rejects docs with PII > 0.7 confidence
# Test 3b: search_corpus() returns top-k documents
# Test 3c: rag_stats() reports index size and doc count

# 4. Memory API (3 tests)
# Test 4a: POST /api/memory/episodes writes episode
# Test 4b: GET /api/memory/recall searches semantically
# Test 4c: GET /api/memory/stats returns memory metrics

# All tests in data/memory_acceptance_tests.jsonl
```

## What NOT to build in this session
- ❌ Vector embedding model training (use text-embedding-3-small)
- ❌ Hybrid search optimization (semantic + BM25 — Phase 5)
- ❌ Memory summarization via Claude API (Phase 5 optimization)
- ❌ Multi-workspace memory isolation (v2 feature)
- ❌ Real-time memory sync to Cosmos DB (deferred to Session 08+)
- ❌ Memory retention policies UI (Session 06)

## Decision Points
1. **Episodic store: JSONL vs. Postgres**
   - Session 04: JSONL (fast, simple, matches Session 01-02 pattern)
   - Session 08+: migrate to Postgres for transactions + TTL triggers

2. **RAG corpus: local vs. cloud vector store**
   - Decision: Azure AI Search (cloud-native, no infra)
   - Alternative: local Qdrant/Milvus (in-memory overhead)

3. **Recall ranking: BM25 vs. semantic similarity**
   - Session 04: semantic only (Azure Search native)
   - Session 05: hybrid (combine BM25 + semantic scores)

## End-of-Session Actions
1. All 12 acceptance tests pass
2. ARCHITECTURE.md updated to mark Session 04 files as Built
3. Decorator chain unchanged (no new decorators)
4. DECISIONS.md appended with Session 04 memory architecture trade-offs
5. Next session plan: `docs/plans/SESSION-05-provider-abstraction.md` (pluggable backends)

## Verification Commands
```bash
export RAG_ENABLED="true"
export AZURE_SEARCH_ENDPOINT="https://search-aigovern-dev.search.windows.net"
export AZURE_SEARCH_KEY="<key>"

# Smoke tests
python -c "from domain.agent_memory import build_context; print('Agent memory OK')"
python -c "from domain.rag_engine import rag_stats; print(rag_stats())"

# Integration test
python -c "
from domain.agent_memory import write_episode
episode = {
    'prompt': 'What is 2+2?',
    'response': '2+2=4',
    'outcome': 'correct'
}
episode_id = write_episode('demo-workload', episode)
print(f'Wrote episode: {episode_id}')
"

# API test
curl -X POST http://localhost:8001/api/memory/episodes \
  -H "Content-Type: application/json" \
  -d '{"workload_id": "demo", "prompt": "test", "response": "ok"}'
```
