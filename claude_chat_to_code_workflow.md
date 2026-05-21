# Claude Chat → Claude Code: Context Transfer & Best Practices
# Project: AI Assurance Platform — aigovern.sandboxhub.co
# Generated from active architecture sessions

---

## THE CORE PROBLEM

Claude Code has no memory of this chat. It starts cold every session.
You have made dozens of architectural decisions across multiple conversations:
- N-tier agentic RAG + PII pipeline design
- Four-tier agent memory architecture
- Policy engine (OPA/Cedar + MS Agent Governance Toolkit)
- Six-layer guardrails stack (LlamaFirewall → OPA → scrubber → NeMo → LLM Guard → audit)
- Platform-agnostic tool choices (providers.py adapter pattern)
- Full integration map into aigovern.sandboxhub.co

None of that exists in Claude Code's context unless you put it there explicitly.

---

## PART 1 — PIPING THIS CONVERSATION: DO IT NOW

### Method A — ARCHITECTURE.md in the repo root (recommended)

Create this file in the repo root. Claude Code reads it automatically on every session.
It is your single source of truth. Keep it updated as decisions are made.

```
ai-assurance-mvp/
├── ARCHITECTURE.md          ← Claude Code reads this first, every time
├── DECISIONS.md             ← immutable log of WHY decisions were made
├── CLAUDE.md                ← Claude Code's standing instructions
└── docs/
    ├── policy-engine.md     ← from today's policy engine session
    ├── guardrails.md        ← from today's guardrails session
    ├── rag-memory.md        ← from the RAG + agent memory session
    └── pii-scrubbing.md     ← from the scrubbing pipeline session
```

### ARCHITECTURE.md — paste this into your repo NOW

```markdown
# AI Assurance Platform — Architecture Reference
# aigovern.sandboxhub.co | Azure-native | FastAPI + vanilla HTML

## Stack
- Backend: FastAPI (dashboard.py as entry point)
- Frontend: vanilla HTML + shared.js + shared.css (no framework, no build step)
- Storage: JSONL flat files via storage.py (SQLAlchemy in requirements for future)
- Auth: SessionAuthMiddleware (middleware/auth.py)
- Observability: Langfuse Cloud (tracer.py)
- Eval: DeepEval 6-metric suite (evaluator.py)
- Adversarial: Garak probes (adversarial.py)
- Deployment: aigovern.sandboxhub.co via Azure (same AFD pattern as *.signallayer.ai)

## Architectural decisions (non-negotiable)

### PII / data governance
- SCRUBBER_ENABLED=true in prod. scrubber.py runs BEFORE tracer.py on every LLM call.
- Langfuse receives tokenised payload only — never raw PII. This is a hard constraint.
- De-id vault: domain/deid_vault.py — Fernet encryption, TTL-scoped, JSONL backend for MVP.
- RAG corpus: pre-scrubbed at index time. index_document() rejects content with PII score > 0.7.

### Policy engine (OPA)
- Authorization layer: OPA embedded via domain/policy_engine.py
- Policy files: policies/*.rego — git-backed, PR-reviewed, never edited directly in prod
- Fail-closed default: if PDP errors → DENY. Never fail-open.
- PDP evaluates metadata only: {user_role, data_classification, trust_score, jurisdiction}
- NOT content-aware — that is the guardrails layer's job

### Guardrails (six layers)
- L1 input: LLM Guard injection scanner (middleware/injection.py)
- L2 policy: OPA PEP (middleware/policy.py)
- L3 PII: scrubber.py tokenisation
- L4 topic: NeMo Guardrails Colang (guardrails/topic_rail.py)
- L5 output: guardrails.py regex + Llama Guard 3 classifier
- L6 audit: every decision emits structured span to tracer.py + audit.py
- NEVER use SaaS guardrails (Lakera etc) — all self-hosted, no external prompt routing

### Agent memory (four tiers)
- Tier 1: in-context (assembled per call, vanishes)
- Tier 2: episodic (JSONL via storage.py, compressed by agent_memory.py)
- Tier 3: semantic/RAG (Azure AI Search, pre-scrubbed corpus, rag_engine.py)
- Tier 4: procedural (domains.py + guardrails.py — do not modify)
- Memory manager: domain/agent_memory.py — build_context(), compress_episode(), selective_recall()

### Platform-agnostic adapters (providers.py — planned)
- SCRUBBER_BACKEND=presidio|gliner|aws_comprehend
- TRACER_BACKEND=langfuse|phoenix|openllmetry
- EVAL_BACKEND=deepeval|ragas|trulens
- PII_BACKEND=presidio|gliner|azure_language
- Never import tool libraries directly in application code — always via providers.py

### Decorator chain order (enforced)
@policy_gate → @scrub_pii → @trace_llm_call → @evaluate_response
L1 injection check fires inside @policy_gate.
L4 topic rail fires inside the LLM call wrapper.
L5 output filter fires inside @evaluate_response.

## Files — current state
# See DECISIONS.md for why each choice was made

### Built (do not change without checking DECISIONS.md)
- dashboard.py, storage.py, middleware/auth.py
- tracer.py (CRITICAL: patch to use scrubbed_prompt not raw prompt)
- evaluator.py (PIILeakageMetric imported but not active — activate in Step 2)
- guardrails.py (regex only — extend, do not replace)
- adversarial.py, audit.py, report.py, pdf_report.py
- domain/models.py, domain/repository.py, domain/runtime_connectors.py
- domain/assessment_engine.py, domain/release_gate_engine.py
- domain/risk_classification.py, domain/findings_workflow.py
- domain/evidence_repository.py, domain/framework_coverage.py
- domain/runtime_engine.py, domain/portfolio.py
- api/ (grc, runtime_v2, assessment, release_gates, evaluate, traces,
        findings_v2, connectors, demo_run + 10 more)
- static/ (index, ai-systems, findings, runtime, release-gates,
          evidence, governance, assessment, evals, policies, reports)

### In progress (active build — see Claude Code prompt)
- scrubber.py (root level)
- domain/deid_vault.py
- api/rag.py
- static/rag-governance.html
- Patch: api/demo_run.py (insert scrubber into _build_run)
- Patch: evaluator.py (activate PIILeakageMetric as metric 6)
- Patch: domain/models.py (add ScrubEntity, ScrubEvent, RAGChunk, RAGIndexEvent)
- Patch: dashboard.py (mount rag router)

### Planned (next sessions)
- domain/policy_engine.py (OPA wrapper)
- domain/trust_scorer.py
- domain/agent_memory.py
- domain/rag_engine.py (Azure AI Search)
- middleware/policy.py (PEP)
- middleware/injection.py (L1 injection scan)
- providers.py (adapter factory)
- policies/base.rego
- policies/pii.rego
- policies/agent_tools.rego
- policies/financial_advisor.rego
- guardrails/topic_rail.py (NeMo Colang)
- guardrails/financial_advisor.co
- api/policies.py
- static/policy-engine.html
- static/rag-governance.html

## Environment variables (.env.example — current)
LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_HOST
ANTHROPIC_API_KEY, OPENAI_API_KEY
EVAL_MODEL=gpt-4o-mini
SESSION_SECRET (required for deid_vault Fernet encryption)
SCRUBBER_ENABLED=true
DEID_VAULT_TTL_SECONDS=3600
RAG_ENABLED=false
AZURE_SEARCH_ENDPOINT, AZURE_SEARCH_KEY, AZURE_SEARCH_INDEX
RAG_EMBEDDING_MODEL=text-embedding-3-small
RAG_TOP_K=5
SCRUBBER_BACKEND=presidio
TRACER_BACKEND=langfuse
EVAL_BACKEND=deepeval
OPA_URL=http://localhost:8181

## Demo scenario
Financial advisor adversarial demo. Surfaces:
- Hallucination (LLM invents fund performance)
- PII leakage (customer name/SSN in response)
- Compliance failure (advice without suitability check)
- Injection attempt (user tries to bypass compliance rails)
- Scope violation (query outside defined advisory scope)
Models: Claude + GPT-4o-mini side-by-side comparison.
```

---

### Method B — CLAUDE.md (Claude Code's standing instructions)

This file tells Claude Code HOW to work, not WHAT to build.
Claude Code reads CLAUDE.md automatically before every session.

```markdown
# CLAUDE.md — Standing instructions for Claude Code
# Project: AI Assurance Platform | aigovern.sandboxhub.co

## Before writing any code
1. Read ARCHITECTURE.md in full
2. Read DECISIONS.md for the specific component you are touching
3. Read the existing file you are modifying before changing it
4. If you find a conflict between this file and ARCHITECTURE.md, stop and flag it

## Code standards (non-negotiable)
- Full updated files only — never inline snippets, never partial functions
- Type hints on all parameters and return values
- Docstring on every public function
- from __future__ import annotations at top of every file
- Pydantic v2 for all domain models
- Match existing import style exactly
- python -c "import <module>" must pass before moving to next file

## Security rules
- scrubber.tokenise_payload() runs before tracer.trace_call() — always
- Langfuse receives scrubbed_prompt, never raw prompt
- No PII in any log, trace, or eval payload
- Fail-closed on policy engine errors — DENY is the safe default
- SaaS guardrails are never used — self-hosted only

## Storage rules
- JSONL only via storage.py _append_jsonl() and _read_jsonl()
- No new database dependencies without explicit approval
- No direct file writes outside storage.py pattern

## Test before moving on
After every file: python -c "import <module>"
After every session: run the verification block at bottom of the Claude Code prompt

## When blocked
Stop and say what the blocker is. Never fake it. Never work around it silently.
```

---

### Method C — Session context injection (for this conversation specifically)

For the current backlog of decisions from this chat session,
run this command in Claude Code to create the docs/ reference files:

```bash
mkdir -p docs policies guardrails
```

Then in Claude Code, paste this as your first message:

---

**CONTEXT TRANSFER PROMPT — paste this at the start of every new Claude Code session:**

```
Before we start: read ARCHITECTURE.md and CLAUDE.md in full.
Confirm you have read them by listing the three most recently planned files
from the planned section of ARCHITECTURE.md.

Then read the specific file I am about to ask you to build or modify.
Do not write any code until you have confirmed you have read both.
```

---

## PART 2 — BEST PRACTICES FOR ONGOING SESSIONS

### Rule 1: Architecture decisions happen in chat, implementation in Claude Code

Use Claude (chat) for:
- Architecture decisions and trade-offs
- "Should I use X or Y?" — get the answer here with reasoning
- Reviewing what exists before building what's next
- Generating Claude Code prompts

Use Claude Code for:
- Writing, modifying, and running actual files
- Verification and testing
- Debugging build errors

Never debate architecture in a Claude Code session.
Never ask Claude Code "what should I use?" — it will invent an answer.

### Rule 2: One session = one component

Bad session scope:
"Build the policy engine, the guardrails extension, and the RAG engine"

Good session scope:
"Build domain/policy_engine.py and policies/base.rego.
Read ARCHITECTURE.md first. Verify with python -c 'from domain.policy_engine import evaluate' before finishing."

Claude Code degrades significantly across long sessions.
Context window fills. Earlier instructions get lost. Quality drops.
One component per session. Update ARCHITECTURE.md after each session.

### Rule 3: The Claude Code prompt IS the spec

Every Claude Code prompt from chat becomes a file in docs/prompts/.
This creates a replayable build history.

```
docs/
└── prompts/
    ├── 01-mvp-core.md               ← original MVP build
    ├── 02-rag-pii-scrubber.md       ← current in-progress build
    ├── 03-policy-engine.md          ← next session
    ├── 04-guardrails-extension.md   ← session after that
    └── 05-agent-memory.md           ← later
```

If Claude Code makes a mess, you replay from the prompt.
If you onboard a developer, they run the prompts in sequence.
This is your documentation AND your build system.

### Rule 4: DECISIONS.md is immutable

Every architectural decision gets logged here with:
- Date
- Decision made
- Alternatives considered
- Why this one was chosen
- What it constrains going forward

```markdown
# DECISIONS.md

## 2026-05-20 — Scrubber before Langfuse
Decision: scrubber.tokenise_payload() runs before tracer.trace_call()
Alternatives: post-hoc redaction in Langfuse, Langfuse self-hosted only
Why: Langfuse Cloud is a SaaS — even self-hosted instances should never
     receive raw PII as a defence-in-depth principle
Constrains: all future LLM wrappers must follow scrub-then-trace order

## 2026-05-20 — OPA over Cedar as primary policy engine
Decision: OPA (Rego) as primary, Cedar as secondary
Alternatives: Cedar-only, home-grown rules dict, NeMo for policy
Why: OPA is most mature, multi-cloud, git-backed, 9500+ tests.
     Cedar stronger type system but AWS-native. Home-grown = unmaintainable.
Constrains: policy files live in policies/*.rego, evaluated via OPA sidecar

## 2026-05-20 — No SaaS guardrails
Decision: all guardrails self-hosted (LLM Guard, NeMo, Llama Guard 3)
Alternatives: Lakera Guard, Azure Content Safety
Why: SaaS guardrails route prompts externally — direct PII contradiction
     for a platform whose core value prop is data never leaving the boundary
Constrains: guardrail stack must be deployable on Azure ACI/AKS with no
            external API calls in the prompt path
```

### Rule 5: Verification blocks are not optional

Every Claude Code prompt ends with a verification block.
Claude Code must run it and show you the output before the session ends.
If it skips this, reject the session and make it run the block.

Standard verification block for this project:

```bash
# 1. All modules import cleanly
python -c "import scrubber; print('scrubber OK')"
python -c "from domain.deid_vault import vault_stats; print('vault OK')"
python -c "from domain.rag_engine import rag_stats; print('rag_engine OK')"
python -c "from domain.policy_engine import evaluate; print('policy_engine OK')"
python -c "from api.rag import router; print('api/rag OK')"
python -c "from api.policies import router; print('api/policies OK')"

# 2. Server starts
uvicorn dashboard:app --port 8001 &
sleep 3
curl -s http://localhost:8001/api/rag/stats | python -m json.tool
curl -s http://localhost:8001/api/policies/stats | python -m json.tool
kill %1

# 3. Scrubber end-to-end
python -c "
from scrubber import tokenise_payload, restore_payload
text = 'Client John Smith SSN 123-45-6789 email john@example.com wants TSLA'
scrubbed, vault_id = tokenise_payload(text, 'verify-session')
assert 'john@example.com' not in scrubbed, 'FAIL: email in scrubbed'
assert '123-45-6789' not in scrubbed, 'FAIL: SSN in scrubbed'
restored = restore_payload(scrubbed, vault_id)
assert 'john@example.com' in restored, 'FAIL: email not restored'
print('PASS: scrubber end-to-end')
"
```

### Rule 6: Update ARCHITECTURE.md at the end of every session

The last instruction in every Claude Code prompt:

```
After verification passes:
Update the "In progress" and "Planned" sections of ARCHITECTURE.md
to reflect what was built in this session.
Move completed items from "In progress" to a new "Completed" section with today's date.
```

### Rule 7: Build sequence is fixed — do not let Claude Code reorder it

Current fixed sequence for aigovern:

```
Session 1 (active): scrubber.py + deid_vault.py + rag.py + rag-governance.html
                    + patch demo_run.py + patch evaluator.py

Session 2:          policy_engine.py + trust_scorer.py + middleware/policy.py
                    + policies/*.rego + api/policies.py + policy-engine.html

Session 3:          guardrails extension + middleware/injection.py
                    + guardrails/topic_rail.py + Llama Guard 3 integration

Session 4:          agent_memory.py + rag_engine.py (Azure AI Search)

Session 5:          providers.py adapter factory
```

If Claude Code tries to build Session 3 components during Session 1,
stop it. The sequence exists because components depend on each other.

---

## PART 3 — COPY-PASTE TEMPLATES

### Template: Start of every Claude Code session

```
Read ARCHITECTURE.md and CLAUDE.md before writing any code.

Confirm you have read them by answering:
1. What is the decorator chain order for LLM calls?
2. What does scrubber.tokenise_payload() run before?
3. What files are currently "in progress"?

Then proceed with the following task:
[TASK HERE]
```

### Template: Architecture decision from chat → DECISIONS.md entry

```
Add this to DECISIONS.md:

## [DATE] — [DECISION TITLE]
Decision: [what was decided]
Alternatives: [what was considered]
Why: [reasoning]
Constrains: [what future decisions this forecloses]
```

### Template: End of Claude Code session

```
Before ending this session:
1. Run the full verification block
2. Update ARCHITECTURE.md — move completed items, update in-progress
3. Create docs/prompts/[NN]-[component-name].md with the prompt used this session
4. List any blockers or open questions for the next session
```

---

## SUMMARY: THE WORKFLOW

```
Claude Chat (this interface)
  ├── Architecture decisions → DECISIONS.md
  ├── Trade-off analysis → docs/*.md
  ├── Claude Code prompts → docs/prompts/*.md
  └── ARCHITECTURE.md updates

         ↓ copy prompt file into Claude Code

Claude Code (terminal)
  ├── Reads ARCHITECTURE.md + CLAUDE.md first (always)
  ├── Builds one component per session
  ├── Runs verification block
  └── Updates ARCHITECTURE.md before ending

         ↓ next decision needed?

Back to Claude Chat — never debate architecture in Claude Code
```

This workflow means every Claude Code session starts fully informed,
every decision is traceable, and the repo self-documents as it grows.
```
