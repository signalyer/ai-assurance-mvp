# AI Assurance Platform — Architecture Reference
# aigovern.sandboxhub.co | Azure | FastAPI + vanilla HTML

> **Source of truth.** Updated at the end of every Claude Code session via `/handoff`.
> For the holistic six-layer model and competitive positioning, see `docs/target-architecture.md`.
> For the WHY behind decisions, see `DECISIONS.md`.

## Stack
Backend: FastAPI (`dashboard.py` entry point)
Frontend: vanilla HTML + `static/shared.js` + `static/shared.css` (no framework, no build)
Storage: JSONL flat files via `storage.py`
Auth: SessionAuthMiddleware (`middleware/auth.py`) — 10-min sliding sessions
Observability: Langfuse Cloud (`tracer.py`) — ⚠ currently leaking raw prompts; fix in Session 01b
Eval: DeepEval (5 metrics today; extending to 6) — `evaluator.py`
Adversarial: Garak — `adversarial.py`
Deployment: Azure App Service Linux Python 3.12 at aigovern.sandboxhub.co

## Architectural decisions (non-negotiable)
- Decorator order: `@policy_gate` → `@scrub_pii` → `@guardrails` → `@trace_llm_call` → `@evaluate_response`
- Scrubber: `tokenise_payload()` runs BEFORE `trace_call()` — hard constraint
- Langfuse: receives `scrubbed_prompt` only — never raw prompt
- Policy engine: OPA fail-closed — error → DENY, never ALLOW
- Guardrails: self-hosted only — no SaaS tools in prompt path; fail-closed on injection/topic/safety violations
- RAG corpus: pre-scrubbed at index time — `index_document()` rejects PII > 0.7
- Memory tiers: T1 in-context · T2 episodic JSONL · T3 RAG (Azure AI Search) · T4 procedural
- DeepEval 6-metric suite: hallucination, relevancy, faithfulness, toxicity, PII leakage, scrub score
- Single-tenant for v1; multi-tenant later

## Files — Built ✓
### Root
`dashboard.py`, `storage.py`, `tracer.py` (⚠ leaks raw prompts), `evaluator.py`,
`guardrails.py` (regex-only), `adversarial.py`, `audit.py`, `report.py`,
`pdf_report.py`, `mock_data.py`, `domains.py` (Tier 4 procedural memory)

### Domain (`domain/`)
`models.py`, `repository.py`, `runtime_connectors.py`, `assessment_engine.py`,
`release_gate_engine.py`, `risk_classification.py`, `findings_workflow.py`,
`evidence_repository.py`, `framework_coverage.py`, `runtime_engine.py`,
`portfolio.py`, `notifications.py`, `governance_guide.py`, `assurance_providers.py`,
`usage_analytics.py`, `reports.py`, `ai_system_edit.py`, `aws_demo_flow.py`

### API (`api/`)
`grc.py`, `runtime_v2.py`, `assessment.py`, `release_gates.py`, `evaluate.py`,
`traces.py`, `findings_v2.py`, `connectors.py`, `demo_run.py`, `reports.py`,
`guide.py`, `assurance_model.py`, `usage.py`, `ai_system_edit.py`, `aws_demo.py`, `demo.py`

### Middleware (`middleware/`)
`auth.py` (5-role: demo-ciso, demo-risk, demo-engineer, demo-reviewer, demo-readonly)

### UI (`static/`)
`index.html` (Command Center), `ai-systems.html`, `findings.html`, `runtime.html`,
`release-gates.html`, `evidence.html`, `governance.html`, `assessment.html`,
`evals.html`, `policies.html`, `reports.html`, `connectors.html`,
`assurance-providers.html`, `framework-sop.html`, `analytics.html`,
`demo.html`, `demo-aws-analyzer.html`, `login.html`, `shared.js`, `shared.css`

## Files — Built (2026-05-21, Sessions 01a + 01b + 02)
### Session 01a (PII scrubbing core)
`scrubber.py` (Presidio NER + regex layer, fail-closed), `domain/deid_vault.py` (Fernet encrypted vault with TTL)

### Session 01b (decorator wiring + tracer patch)
`middleware/scrubber.py` (@scrub_pii decorator), `tracer.py` (hardened: vault_id required when SCRUBBER_ENABLED), `api/demo_run.py` (scrubs prompts before trace_call, vault_id in metadata)

### Session 02 (policy engine + OPA)
`domain/policy_engine.py` (OPA HTTP client + local Python fallback, 5 categories, fail-closed), `domain/trust_scorer.py` (time-decayed trust score from policy history, half-life 7 days), `middleware/policy.py` (@policy_gate decorator, raises PolicyDeniedError on DENY), `policies/base.rego` (org-mandatory), `policies/pii.rego` (posture: us-finserv, gdpr, hipaa), `policies/agent_tools.rego` (team tool authorization), `policies/financial_advisor.rego` (risk-tier critical handling)

### Session 03 (guardrails — NeMo + Llama Guard 3)
`middleware/injection.py` (prompt injection detection via regex + heuristics), `middleware/guardrails.py` (@guardrails decorator orchestrating injection/topic/safety checks), `guardrails/nemo_adapters.py` (topic classification + topic enforcement), `guardrails/llama_guard_adapter.py` (content safety evaluation — 8 categories), `guardrails/financial_advisor_rail.py` (topic rail + guardrail rules for financial advisor), `guardrails/config/financial_advisor_rails.yaml` (NeMo topic rail YAML config)

## Files — In Progress
None — Sessions 01, 02, and 03 fully complete.

### RAG-related (Session 04)
- `api/rag.py` — new
- `static/rag-governance.html` — new

## Files — Planned
### Session 04 — Memory + RAG
- `domain/agent_memory.py` — `build_context()`, `write_episode()`,
  `compress_episode()`, `selective_recall()`
- `domain/rag_engine.py` — Azure AI Search wrapper with index-time scrubbing
- Tier 2 episodic store: `data/episodes_{workload_id}.jsonl`

### Session 05 — Provider Abstraction
- `providers.py` — env-var-driven backend swap (scrubber/tracer/eval backends)

### Session 06 — API + UI
- `api/policies.py`, `static/policy-engine.html`, `static/rag-governance.html`

### Session 07 — Diagrams + Demo
- `docs/diagrams/aigovern-architecture.html` (regen final)
- Demo prep for financial advisor adversarial scenario

### Sessions 08–10 — Organizational Layer (added beyond the 7-session guide)
- `domain/risk_inventory.py`, `domain/governance_body.py`, `domain/raci.py`,
  `domain/regulatory_posture.py`
- Three UI pages

## Environment variables
### Existing (set on app-aigovern-dev)
- `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`
- `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`
- `EVAL_MODEL=gpt-4o-mini`
- `SESSION_SECRET`

### Added (Session 01a + 01b, applied to Azure App Service)
- `SCRUBBER_ENABLED=true` — Presidio scrubber active
- `DEID_VAULT_TTL_SECONDS=3600` — Default vault entry TTL
- `AZURE_SEARCH_ENDPOINT=https://search-aigovern-dev.search.windows.net` — RAG backend (Session 04)
- `AZURE_SEARCH_KEY` — Azure AI Search admin key (provisioned 2026-05-21)
- `AZURE_SEARCH_INDEX=aigovern-rag-index` — RAG index name
- `POSTGRES_HOST=psql-aigovern-dev.postgres.database.azure.com` — Provisioned westus2
- `POSTGRES_USER=pgadmin`, `POSTGRES_PASSWORD`, `POSTGRES_DATABASE=postgres`
- `DATABASE_URL=postgresql://...` — Full connection string with sslmode=require
- `RAG_EMBEDDING_MODEL=text-embedding-3-small`, `RAG_TOP_K=5`

### Added (Session 02)
- `POLICIES_ENABLED=true` — Policy engine + @policy_gate decorator active
- `OPA_URL` (optional) — OPA sidecar HTTP endpoint; falls back to local Python evaluator

### Added (Session 03)
- `GUARDRAILS_ENABLED=true` — Guardrails enforcement active (injection/topic/safety)
- `INJECTION_DETECTION=true` — Prompt injection detection enabled
- `TOPIC_ENFORCEMENT=true` — Topic validation for workloads enabled
- `LLAMA_GUARD_ENABLED=true` — Llama Guard 3 content safety enabled

### To add (per upcoming sessions)
- `SCRUBBER_BACKEND=presidio` (Session 05)
- `TRACER_BACKEND=langfuse` (Session 05)
- `EVAL_BACKEND=deepeval` (Session 05)
- `OPA_URL=http://localhost:8181` (Session 02)
- `RAG_ENABLED=false` (Session 04, default off)
- `AZURE_SEARCH_ENDPOINT`, `AZURE_SEARCH_KEY` (Session 04)
- `AZURE_SEARCH_INDEX=aigovern-rag-index` (Session 04)
- `RAG_EMBEDDING_MODEL=text-embedding-3-small`, `RAG_TOP_K=5` (Session 04)

## Demo scenario
Financial advisor adversarial: hallucination + PII leakage + compliance failure +
prompt injection attempt + scope violation.
Side-by-side: Claude Sonnet 4.6 vs GPT-4o-mini.

## Verification commands
```bash
python -c "import scrubber; print('scrubber OK')"                              # after Session 01a
python -c "from domain.deid_vault import vault_stats; print('vault OK')"       # after Session 01a
python -c "from domain.policy_engine import evaluate; print('policy OK')"      # after Session 02
python -c "from middleware.injection import detect_injection; print('injection OK')"  # after Session 03
python -c "from middleware.guardrails import guardrails; print('guardrails OK')"     # after Session 03
python -c "from guardrails.nemo_adapters import validate_topic; print('nemo OK')"   # after Session 03
python -c "from guardrails.llama_guard_adapter import evaluate_content; print('llama_guard OK')"  # after Session 03
python -c "from domain.agent_memory import build_context; print('memory OK')"  # after Session 04
python -c "from domain.rag_engine import rag_stats; print('rag OK')"           # after Session 04
uvicorn dashboard:app --port 8001 &
curl -s http://localhost:8001/api/rag/stats                                    # after Session 04
curl -s http://localhost:8001/api/policies/stats                               # after Session 02
curl -s http://localhost:8001/api/guardrails/stats                             # after Session 03

# End-to-end scrubber smoke (after Session 01a)
python -c "
from scrubber import tokenise_payload, restore_payload
text = 'Client John Smith SSN 123-45-6789 email john@example.com'
scrubbed, vault_id = tokenise_payload(text, 'verify')
assert 'john@example.com' not in scrubbed, 'FAIL: email leaked'
assert '123-45-6789' not in scrubbed, 'FAIL: SSN leaked'
restored = restore_payload(scrubbed, vault_id)
assert 'john@example.com' in restored, 'FAIL: email not restored'
print('PASS: scrubber end-to-end')
"
```
