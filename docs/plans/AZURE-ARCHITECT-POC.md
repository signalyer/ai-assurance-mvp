# Azure Deployment Architect — Customer POC plan

**Workload track, not platform track.** This is the agent we build *with* the platform to demo every V2 feature end-to-end. Calendar duration ≈ 10 working days for one engineer + ~6 hours CISO time across approval gates. Runs *after* [SESSION-54](./SESSION-54-arc-close.md) closes the V1→V2 arc.

**Treat this document as a runbook.** Each phase has a time-box, exit gate, and named artifact. Phase numbers (P1-P10) are dev phases, not platform sessions.

## The agent under development

**Name:** Azure Deployment Architect
**Purpose:** Reads a target Azure subscription via ARM read APIs, walks every resource group, infers relationships (private endpoints, peering, role assignments), returns a logical architecture diagram (Mermaid + SVG) and a per-resource configuration JSON manifest.
**Autonomy:** `draft` — produces documents for human review; no writes against Azure.
**Models:** Claude Opus 4.7 (synthesis), Claude Haiku 4.5 (per-resource summarization).
**Tools:** 6 ARM read tools (`list_subscriptions`, `list_resource_groups`, `get_resource_metadata`, `list_role_assignments`, `get_network_topology`, `render_mermaid_diagram`).
**Risk classification expected:** MEDIUM (tool use + sensitive infra metadata + cross-subscription scope, mitigated by read-only and HITL).

## Repository layout (to create under monorepo `agents/`)

```
agents/azure-architect/
├── README.md
├── pyproject.toml
├── agent.py                          # entry point with decorator stack
├── tools/
│   ├── arm_read.py                   # 5 ARM tools
│   └── mermaid_render.py             # diagram renderer
├── prompts/
│   ├── system.md
│   └── per_resource.md
├── eval/
│   ├── dataset.jsonl                 # 5 worked-example manifests
│   └── mermaid_compiles_metric.py    # custom DeepEval metric
├── policies/
│   └── azure-architect.rego          # OPA policy (read-only allowlist)
└── .env.example                      # SL_KEY_ID, SL_API_KEY, etc — never committed real
```

---

## P1 · Intake (~3 hours)

**Activities**
1. Flip Team Portal Data Mode toggle to V2 — confirm empty-state CTAs render.
2. Click `Register your first system →` → 5-step wizard.
3. Step 1 — Business Context: name `Azure Deployment Architect`, business owner `Sarah Chen, VP Platform Engineering`, technical owner self, domain `Platform Engineering`, user population `internal`, customer impact `indirect`.
4. Step 2 — Architecture: cloud `Azure` (or AWS+note), Anthropic via direct API, models `claude-opus-4-7` + `claude-haiku-4-5`, RAG ON, vector store `Azure AI Search`, tools as listed above, external integrations `Azure Resource Manager`.
5. Step 3 — Data Classification: `Internal`, `Confidential`; data enters prompts ON; data enters RAG OFF; tools return sensitive ON; logs may contain sensitive ON.
6. Step 4 — Agent Autonomy: `draft`, can call tools ON, can write data OFF, customer comms OFF, FS workflow OFF, human approval ON.
7. Step 5 — Evidence Upload: Confluence URL for arch diagram, IAM policy URL for Reader role JSON; leave eval + security review blank.

**Exit gate**
AI System record with `data_source="real"`, inherent risk MEDIUM, required gates bound, redirect to `/onboarding/{ai_system_id}` fires.

**Artifacts**
Screenshots of live risk panel; link to system detail page; risk classification rationale captured in the agent repo `README.md`.

---

## P2 · SDK onboarding (~2 hours)

**Activities**
1. Wizard auto-fires `POST /api/sdk-keys`; copy `key_id` + `hmac_secret` into `agents/azure-architect/.env`. **Never commit.**
2. Copy the generated snippet into `agents/azure-architect/agent.py`.
3. Step 2 install snippet — `pip install -e ./sdk` from the monorepo root.
4. Implement a 5-line dry-run that calls Anthropic with a fixed prompt through the decorator chain.
5. Run `python agent.py --dry-run` — observe wizard's Step 3 flip green within 30s.

**Exit gate**
`first_seen_at` non-null in `data/sdk_keys.jsonl`; wizard "Done" button enabled.

**Artifacts**
Sanitized `.env.example` committed; `agent.py` skeleton committed with decorator stack visible.

---

## P3 · Governance scaffolding (~4 hours)

**Activities**
1. Author `policies/azure-architect.rego` — read-only tool allowlist, mutation denylist (template in the [Phase 1-10 walkthrough](../architecture/azure-architecture.md) §3.2 or in the parent chat context).
2. CISO Console → Policy Governance → upload policy → verify it lands in fail-closed evaluator.
3. CISO Console → Framework Coverage → drill into the new system → tab through EU AI Act / ISO 42001 / OWASP LLM Top 10 / NIST AI RMF. Note any RED cells.
4. Generate EU AI Act PDF Pack as baseline framework evidence.
5. Update intake's Step 5 evidence URLs with the policy artifact + EU AI Act pack.

**Exit gate**
OPA policy active; framework matrix has no unjustified RED cells; one PDF pack archived.

**Artifacts**
`.rego` file committed; PDF pack stored in evidence bucket (or linked from intake); framework matrix screenshot.

---

## P4 · Agent core development (~3 days)

**Day 1 — Tool layer**
- `tools/arm_read.py` — 6 async functions wrapping `azure.mgmt.*` packages.
- Each tool returns structured JSON with a versioned schema (`schema_version: "1.0"` field).
- JSON-schema-pin every return shape using Pydantic v2 models in `tools/schemas.py`.
- Unit tests using Azure SDK fixtures.

**Day 2 — Orchestration loop**
```
list_subscriptions
  └→ for each sub: list_resource_groups
       └→ for each rg: get_resource_metadata (batched, 5 at a time, asyncio.gather)
            └→ Claude Haiku: summarize the resource in 1 sentence
get_network_topology       # peerings + private endpoints
list_role_assignments      # access matrix
Claude Opus: synthesize → Mermaid diagram + JSON manifest
render_mermaid_diagram     # local mermaid-cli or kroki.io
```
Every Claude call routes through the decorated function (P2's `agent.py`).

**Day 3 — Output rendering + edge cases**
- Mermaid generation prompt in `prompts/system.md`.
- Per-resource summarization prompt in `prompts/per_resource.md`.
- Edge cases: subscription with zero RGs (empty diagram); RG with circular references; resources the Reader role can list but not detail-read.
- End-to-end against a real test subscription with a 1-RG and a 3-RG hub-spoke example.

**Exit gate**
End-to-end runs emit a valid Mermaid diagram + JSON manifest for at least 2 distinct subscription topologies.

**Artifacts**
`agents/azure-architect/` committed; 2 example output diagrams + manifests in `agents/azure-architect/examples/`.

**During Day 1-3 — keep three tabs open**
- Team Portal Runtime page → real-time event stream
- Team Portal Memory page → episodic memory accruing
- CISO Console Findings inbox → policy denials / guardrail violations land here

---

## P5 · Memory + RAG (~4 hours)

**Activities**
1. `MEMORY_BACKEND=postgres` if Postgres is provisioned; else `noop` and skip Tier-2 demo.
2. RAG: index 50-100 chunks of Azure documentation (Bicep schema docs, ARM resource type references, networking guidance) via `POST /api/rag/documents`.
3. Test retrieval via `POST /api/rag/search` — confirm top-3 hits for `"private endpoint DNS zone"` are coherent.
4. Wire RAG retrieval into `agent.py`: prefix Opus synthesis call with top-K=5 retrieved chunks.

**Exit gate**
Memory inspector shows episodes per run; RAG search returns coherent top-3.

**Artifacts**
Indexed corpus document count screenshot; memory stats screenshot.

---

## P6 · Evaluation suite (~6 hours)

**Activities**
1. Build 5-manifest worked-example dataset in `eval/dataset.jsonl`:
   - Simple: 1 RG, web app + storage
   - Hub-spoke: 3 VNets with peering
   - HIPAA-isolated: private endpoints + KV
   - Multi-region: paired VNets across regions
   - Broken: invalid deployment with circular refs
2. Each row = `{input_subscription_manifest, expected_diagram, expected_json}`.
3. Author `eval/mermaid_compiles_metric.py` — custom DeepEval metric returning 0/1 on Mermaid parse validity.
4. Team Portal → Evals → your system card → **Run Simulated Eval Suite** button.
5. Calibrate prompt iteratively until ≥4/5 pass with hallucination ≥ 0.85, relevancy ≥ 0.80, faithfulness ≥ 0.85, PII leakage = 1.0, mermaid_compiles = 1.0.
6. Document each prompt iteration in `agents/azure-architect/CHANGELOG.md`.

**Exit gate**
Eval card shows ≥4/5 passing; custom metric registered and scored.

**Artifacts**
`eval/dataset.jsonl` committed; eval run history visible on Team Portal; `CHANGELOG.md` documenting prompt tightening with before/after scores.

---

## P7 · Adversarial probing (~4 hours)

**Activities**
1. Team Portal → Adversarial Suite → select categories `prompt_injection`, `system_prompt_leakage`, `tool_misuse`, `encoding_attacks`.
2. Click **Run Suite** — watch SSE-streamed results.
3. For each failed probe:
   - Reproduce: copy prompt from trace → run locally
   - Mitigate: tighten system prompt OR add guardrail rule (Llama Guard topic / NeMo rail) OR add OPA policy clause
   - Close finding with evidence link to commit SHA

**Exit gate**
Zero open CRITICAL findings; all HIGH findings have documented mitigations.

**Artifacts**
Adversarial probe report (downloadable from SPA); list of mitigations applied with finding IDs in `agents/azure-architect/SECURITY.md`.

---

## P8 · Release gate evaluation (~3 hours)

**Activities**
1. CISO Console → Release Gates → your system card.
2. For each blocking gate failure:
   - Click into the gate → see the engine's reason
   - Fix the underlying condition → re-run the relevant evaluator
   - OR request a time-bound exception with documented rationale (CISO authority)
3. Target rollup: **CONDITIONAL_PILOT** (zero blocking failures).

**Typical gate set (for MEDIUM risk)**
`G_EVAL_RECENT`, `G_HALLUCINATION`, `G_PII_LEAKAGE`, `G_ADVERSARIAL_CLEAN`, `G_POLICY_UPLOADED`, `G_FRAMEWORK_COVERAGE`, `G_RISK_REVIEWED`, `G_AUDIT_CHAIN_CLEAN`, `G_RTF_RUNBOOK_DOCUMENTED`

**Exit gate**
Release Gates rollup is CONDITIONAL_PILOT.

**Artifacts**
Gate-by-gate decision log; exception waivers documented in `agents/azure-architect/EXCEPTIONS.md`.

---

## P9 · Runtime readiness (~3 hours)

**Activities**
1. Team Portal → Agent Library → New Agent → register at v1.0.0.
   - Inherent risk MEDIUM
   - Owner: your team
   - Description: "Generates logical architecture diagrams from Azure subscriptions"
   - Publish v1.0.0 with changelog.
2. Subscribe consumers (any internal system that will call this agent) via Subscribers tab — they get pg_notify on upgrade.
3. Team Portal → Runtime → your system → flip state from NOT_LIVE → STANDARD; configure kill-switch.
4. Runtime → Approval Queue → Request approval → routes to demo-ciso with links to eval report, adversarial report, OPA policy, framework matrix.

**Exit gate**
Approval request visible on CISO Console; agent v1.0.0 in Agent Library.

**Artifacts**
Agent Library entry screenshot; runtime state audit log.

---

## P10 · CISO sign-off + reports (~1 hour CISO + 30 min eng)

**Activities (CISO acts; engineer observes)**
1. CISO Console → Findings Inbox → confirm zero open CRITICAL/HIGH.
2. CISO Console → Release Gates → verify rollup is CONDITIONAL_PILOT (or PILOT if all blocking green).
3. CISO Console → Framework Coverage → scan for unjustified RED cells.
4. CISO Console → Evidence Bundles → confirm every gate has evidence linked.
5. CISO Console → Audit Chain → Verify → `GET /api/audit/verify?window=500&full=true` → expect **CLEAN**.
6. CISO Console → Reports → generate PDF packs for NIST AI RMF, EU AI Act, ISO 42001, OWASP LLM Top 10.
7. Runtime → Approval Queue → Approve with comments → state auto-transitions to PRODUCTION.

**Exit gate**
Runtime state PRODUCTION; PDF packs archived; audit chain CLEAN over 30 days.

**Artifacts**
4 signed PDF packs in evidence bucket; approval audit-chain entry; post-launch monitoring checklist signed off.

---

## POC closeout deliverables

- `agents/azure-architect/` directory with full code + tests + docs
- `agents/azure-architect/POC-RETROSPECTIVE.md` — every friction point found, organized into "platform gap" vs "agent code" vs "doc gap" buckets. **This feeds Session 55.**
- 4 framework PDF packs
- Runtime state PRODUCTION on a real-mode AI system in the V2 portal

## Calendar mapping

| Day | Phases | Notes |
|---|---|---|
| 1 | P1, P2, P3 | Intake + onboarding + governance |
| 2-4 | P4 | Agent core dev |
| 5 AM | P5 | Memory + RAG |
| 5-6 | P6 | Eval suite |
| 7 | P7 | Adversarial |
| 8 | P8 | Release gates |
| 9 | P9 | Runtime readiness |
| 10 | P10 | CISO sign-off |

If P4 slips (most likely), absorb from P5/P6 day; never compress P7/P8 (those are governance gates, not engineering velocity).
