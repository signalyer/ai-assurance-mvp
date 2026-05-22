# SESSION-07 Plan — Multi-Agent + Agent Library (Day 7)

**Date:** 2026-05-21 | **Status:** Pre-execution review · awaiting 4 architectural decisions + explicit approval

---

## Pre-Execution Review (6 items required)

### 1. Decorator Chain Order (UNCHANGED)

```python
@policy_gate           # L2 · OPA policy evaluation · fail-closed
→ @scrub_pii          # L3 · Presidio + Fernet vault
→ @guardrails         # L3 · injection + topic + safety
→ @trace_llm_call     # L5 · Langfuse with scrubbed payload
→ @evaluate_response  # L5 · DeepEval 6-metric + gates
async def agent(query: str) -> str:
    ...
```

**No changes to decorator order in Session 07.** All new code respects this chain.

---

### 2. Every CREATE File with One-Line Purpose

| File | Purpose |
|---|---|
| `domain/agents.py` | Agent registry, library catalog, versioning logic; public API: `create_agent`, `publish_version`, `list_agents`, `get_agent_by_id` |
| `domain/agent_bindings.py` | AgentBinding schema + repository operations; public API: `bind_agent_to_system`, `list_bindings_for_system`, `update_binding_version`, `unbind_agent` |
| `domain/agent_subscribers.py` | Subscription tracking for reusable agents; public API: `subscribe_to_agent`, `list_subscribers`, `notify_subscribers_on_publish` |
| `api/agents.py` | FastAPI router (5 endpoints): GET `/agents`, POST `/agents`, GET `/agents/{id}`, POST `/agents/{id}/publish`, GET `/agents/{id}/subscribers` |
| `api/agent_bindings.py` | FastAPI router (4 endpoints): GET `/systems/{system_id}/bindings`, POST `/systems/{system_id}/bindings`, PATCH `/systems/{system_id}/bindings/{binding_id}`, DELETE `/systems/{system_id}/bindings/{binding_id}` |
| `static/agent-library.html` | Publish/subscribe UI; agent browser with version history; filter by team/status/reusability |
| `migrations/001_add_agents_and_bindings.py` | Postgres schema: `agents`, `agent_versions`, `agent_bindings`, `agent_subscribers` tables |
| `tests/test_agents_unit.py` | Unit tests for agent CRUD, versioning, subscription logic (50 cases) |
| `tests/test_agent_bindings_integration.py` | Integration tests: bind agent to system, version pin, pin override (20 cases) |

---

### 3. Every MODIFY File with Exact Change

| File | Change |
|---|---|
| `domain/models.py` | ADD: `Agent`, `AgentVersion`, `AgentBinding`, `AgentOwnerType` enums (CUSTOM, REUSABLE); ADD: `agent_bindings` field to AISystem (list of AgentBinding IDs) |
| `domain/repository.py` | ADD: `append_agents_jsonl`, `append_agent_bindings_jsonl`, `read_agents_jsonl`, `read_agent_bindings_jsonl` (4 public functions) |
| `dashboard.py` | MOUNT: `api.agents.router`, `api.agent_bindings.router` at `/api/agents` and `/api/systems/{id}/bindings` |
| `domain/framework_coverage.py` | MODIFY: `framework_matrix()` to compute weakest-link risk tier across all bound agents in a system |
| `domain/release_gate_engine.py` | MODIFY: `evaluate_system_gates()` to check all agent binding versions; fail system if any agent fails gates |
| `domain/runtime_engine.py` | MODIFY: `assemble_context()` to load agent-specific Tier 2 episodic memory per bound agent (not system-wide) |
| `static/ai-systems.html` | ADD: "Bound Agents" section on System detail with agent cards (version, owner, last updated, upgrade button) |
| `requirements.txt` | ADD: no new dependencies (Postgres driver, FastAPI already present) |
| `migrate.py` | ADD: call to migration 001 if Postgres has `agents` table missing |

---

### 4. Two Most Critical Architectural Constraints

**Constraint 1: Weakest-Link Governance**
- A System's risk tier = MAX(agent.risk_tier for each bound agent)
- A System's release gate status = FAIL if ANY bound agent fails its gates
- A System's framework coverage = aggregated from all bound agents' controls
- **Implication:** You cannot release a High-Risk system if any bound agent is Critical; you cannot claim NIST-GOVERN-1.1 coverage if any agent lacks it.

**Constraint 2: Version Pinning & Notification Atomicity**
- When a reusable Agent publishes v2, all subscribers receive a notification event WITHIN 30s
- Subscribers can explicitly pin to v1 (blocking auto-upgrade) or accept v2 upgrade with "upgrade_accepted_at" timestamp
- Binding state machine: `pinned_version=v1` (no upgrades) → `pinned_version=null` (auto-accept v2) → `pinned_version=v2` (pinned again)
- **Implication:** Subscription tracking must be real-time via either (a) polling, (b) SSE, or (c) Postgres LISTEN/NOTIFY; we decide this in the 4 questions below.

---

### 5. Explicit "Will NOT Build" List

This session does **NOT** include:

- **Agent orchestration logic** (multi-agent workflows, tool chaining) — v2 feature
- **Agent-specific policies** (team-owned policies for agents) — Day 8 / Session 08
- **Agent performance analytics dashboard** (per-agent eval trends) — Day 11 / Session 11
- **Agent reusability score** (how many systems use this agent) — Day 11 / Session 11
- **Agent rollback mechanism** (unpublish a version) — Day 8
- **Multi-tenant agent sharing across orgs** — v2 feature (v1 is single-tenant)
- **Agent marketplace / external catalog** — v2 feature
- **Custom DSL for agent composition** — v2 feature
- **Agent audit trail** (who published v2, when, what changed) — tracked in events.jsonl, but no dedicated audit page for agents yet

---

### 6. Acceptance Criteria with Runnable Assertions

#### Unit Tests (50 cases total)

```bash
# Run: pytest tests/test_agents_unit.py -v
# Expected: 50 passed

[Includes]
- Agent CRUD (create, read by id, list, update metadata)
- Version semantics (v1.0.0 → v1.0.1 → v2.0.0; semver enforcement)
- Ownership (team-owned vs reusable enum enforcement)
- Subscription state machine (pin v1 → unpin → pin v2)
- AgentBinding lifecycle (bind → update version → unbind)
```

#### Integration Tests (20 cases total)

```bash
# Run: pytest tests/test_agent_bindings_integration.py -v
# Expected: 20 passed

[Includes]
- Bind agent v1 to system → query runtime loads agent context
- Publish agent v2 → all subscribers notified within 30s (mocked time)
- Pin subscriber to v1 → v2 publish does NOT trigger "upgrade available" for that subscriber
- Unbind agent → system falls back to solo (0 agents bound means system is unbound; allowed)
- WeakestLinkRiskTier: 1 Critical agent + 3 Low agents → system is Critical
- WeakestLinkGates: 1 agent fails gate X → system fails gate X
```

#### API Contract Tests (5 endpoints, 3 cases each)

```bash
# Smoke: curl https://localhost/api/agents → 200 JSON
curl -H "Authorization: Bearer $(sl auth)" https://localhost/api/agents
# Expected: [{"id": "ai-agent-001", "name": "...", "owner_type": "REUSABLE", ...}, ...]

curl -X POST https://localhost/api/agents \
  -H "Content-Type: application/json" \
  -d '{"name":"my-agent", "team":"payments", "owner_type":"CUSTOM"}' \
  -H "Authorization: Bearer $(sl auth)"
# Expected: 201 {"id": "ai-agent-NEW", ...}

curl https://localhost/api/systems/ai-sys-001/bindings
# Expected: 200 [{"agent_id": "ai-agent-001", "system_id": "ai-sys-001", "version": "v1.0.0", "pinned": false, ...}]
```

#### UI Verification (manual, 1 scenario)

```
1. Navigate to /agent-library
2. Search for "payments" agent
3. Click agent card → see version history (v1.0.0 · 2026-05-01, v1.0.1 · 2026-05-10, v2.0.0 · 2026-05-21)
4. Click "Publish v2.0.1"
5. Within 30s, see notifications on all subscriber system detail pages: "Agent {name} v2.0.1 available. Upgrade? [Yes] [No]"
6. Click [Yes] → binding.pinned_version updates, agent context re-loaded on next call
```

#### Framework Coverage Regression Test

```bash
# Verify: framework coverage still computes per system; now also per agent
curl https://localhost/api/frameworks/NIST_AI_RMF/system/ai-sys-001
# Expected: 200 {"coverage": "Covered", "pct": 95, "agents": [{"id": "ai-agent-001", "coverage": "Partial", "pct": 80}, ...]}
```

#### Release Gate Regression Test

```bash
# Verify: release gates evaluate agent bindings, not just system properties
# Setup: bind Critical-tier agent to Normal system; agent fails hallucination gate
curl https://localhost/api/systems/ai-sys-001/gates
# Expected: 200 {"status": "FAIL", "failed_reason": "Agent ai-agent-001 (v1.0.0): hallucination gate failed (0.45 < 0.70 threshold)"}
```

#### Migration Test

```bash
# Run: python migrate.py
# Expected: Postgres tables created (agents, agent_versions, agent_bindings, agent_subscribers)
# Expected: Legacy ai-sys-001 migrated to System(id=ai-sys-001) + AgentBinding(system=ai-sys-001, agent=ai-agent-legacy-001, version=v0.0.0)
# Expected: entry in events.jsonl: {"type": "AGENT_BINDING_CREATED", "agent_id": "ai-agent-legacy-001", "system_id": "ai-sys-001", "version": "v0.0.0", "migrated": true}
```

---

## 4 Architectural Decisions (AWAITING USER INPUT)

Before any code is written, **choose one option per decision** and reply with explicit "Y" / "go" / "approved":

### Decision 1: Agent Storage Strategy

**Question:** Where should agents and versions be stored?

**Option A: Extend repository.py JSONL pattern (RECOMMENDED)**
- Pros: Consistency with existing T2/T3 storage; single-source JSONL for events + agents; replay semantics work
- Cons: JSONL append-only means version history is immutable by design (good for audit, can't edit published versions)
- Implementation: `append_agents_jsonl(agent)`, `read_agents_jsonl()`, `append_agent_bindings_jsonl(binding)`, read_agent_bindings_jsonl()`
- Also provision Postgres `agents`, `agent_versions`, `agent_bindings` tables as materialized views (replay from JSONL)

**Option B: Postgres-primary with JSONL audit trail**
- Pros: Fast queries (no JSONL replay); native schema enforcement
- Cons: SSOT splits between Postgres (live data) and JSONL (audit); adds complexity
- Implementation: Direct INSERT/UPDATE on agents table; append version history separately to audit JSONL

**Option C: Key-value store (e.g., Redis)**
- Pros: Fast; cache-friendly
- Cons: Non-durable; requires backup sync to JSONL; adds operational complexity (Redis not in current infra)

**→ Recommendation: Option A (extend JSONL pattern).** Keeps single SSOT + replay semantics.

**Your choice:** A / B / C?

---

### Decision 2: Version Pinning & Semver Enforcement

**Question:** How should agent versions be pinned and what format should they use?

**Option A: Semver in YAML manifests (RECOMMENDED)**
- Agents get a `manifest.yaml` file (per agent dir): `version: "1.0.0"`, `owner_type: "REUSABLE"`, `team: "payments"`, `changelog: "..."`
- Bindings store `pinned_version: "1.0.0" | null` (null = auto-accept latest)
- DeepEval compares: `binding.pinned_version ? binding.pinned_version : agent.latest_version`
- Semver format enforced via regex: `^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$`

**Option B: Database-tracked versions**
- `agent_versions` table with `version_id`, `agent_id`, `semantic_version`, `created_at`
- Bindings store FK to `agent_versions.version_id` (immutable after publish)
- More schema control; easier to query "all agents at v2.0+"

**Option C: Hash-based immutable versions**
- Each publish generates a SHA-256 hash of agent config; bindings pin to hash
- Deterministic, audit-friendly
- Cons: Less human-readable than semver

**→ Recommendation: Option A (YAML + semver).** Aligns with framework YAML pattern; simple, legible, git-friendly.

**Your choice:** A / B / C?

---

### Decision 3: Subscriber Notification Mechanism

**Question:** How should subscribers receive "Agent {name} v2.0.0 published" notifications within 30s?

**Option A: Polling endpoint (simplest for v1)**
- Subscribers poll GET `/api/agents/{agent_id}/latest` every 10s (client-side polling)
- Server compares client's `pinned_version` vs agent's `latest_version`
- If mismatch + client not pinned → UI shows "Upgrade available: v2.0.0"
- Pros: No server-side state; simple; works on App Service
- Cons: 10s latency (not 30s SLA); high poll volume at scale
- SLA: "within 30s" means 50th percentile ~15s (if polling every 10s)

**Option B: Server-Sent Events (SSE) stream**
- Server sends event stream to connected clients when agent publishes
- Subscriber client opens `/api/agents/subscribe?system_id=ai-sys-001` (WebSocket alt.)
- On publish, server emits to all connected subscribers in <100ms
- Pros: Real-time; low latency (100ms vs 10s polling)
- Cons: Requires persistent connections; stateful on server; harder to scale across App Service instances

**Option C: Postgres LISTEN/NOTIFY (PostgreSQL-native pubsub)**
- On agent publish, trigger NOTIFY channel `agent_update_{agent_id}`
- Subscribers open long-poll or WebSocket to `/api/agents/{agent_id}/listen`
- Database notifies all listeners within <100ms
- Pros: Real-time; SSOT in database; distributed across Postgres replicas
- Cons: Requires Postgres client library (psycopg3); adds I/O to Postgres

**→ Recommendation: Option A (polling) for v1.** 30s SLA is achievable with 10s polling; SSE/LISTEN are v2 optimizations. If "within 30s" is critical, Option B (SSE) is next best.

**Your choice:** A / B / C?

---

### Decision 4: ai-sys-001 Migration Strategy

**Question:** How should the existing `ai-sys-001` be migrated to the new Agent-aware schema?

**Option A: Automatic migration on first load (RECOMMENDED)**
- On first run of `migrate.py`, check if `ai-sys-001` exists in current AISystem store
- If yes: create `ai-agent-legacy-001` (CUSTOM owner, team="legacy")
- Create AgentBinding(agent_id="ai-agent-legacy-001", system_id="ai-sys-001", version="v0.0.0", pinned=true)
- Log event: `{"type": "AGENT_BINDING_CREATED", "migrated": true, "from_version": "N/A"}`
- Next demo run uses new schema automatically
- Pros: Zero manual intervention; clean cutover; events.jsonl captures the migration
- Cons: Automation could be surprising if undocumented

**Option B: One-time manual script**
- User runs `python scripts/migrate_ai_sys_001.py` explicitly
- Script prompts: "Migrate ai-sys-001 to new schema? [Y/n]"
- Same output as Option A, but explicit consent
- Pros: Clear intent; user controls timing
- Cons: Extra step; manual; easy to forget

**Option C: No migration — create new test systems only**
- Keep ai-sys-001 as-is (legacy, no agents)
- Seed 6 new test systems with agents already bound
- Demo uses the new systems; ignore ai-sys-001
- Pros: No risk of breaking existing demo data
- Cons: Leaves dead code; confusing (two kinds of systems)

**→ Recommendation: Option A (automatic on migrate.py).** Clean; auditable in events.jsonl; no dead code.

**Your choice:** A / B / C?

---

## Implementation Plan (if approved)

**On approval ("Y" / "go" / "approved"), spawn 3 parallel sub-agents:**

1. **Implementer #1: Domain + Repository + Models** (40% effort)
   - Add Agent, AgentVersion, AgentBinding, AgentOwnerType to models.py
   - Extend repository.py with 4 JSONL functions
   - Implement domain/agents.py (registry, versioning, publish logic)
   - Implement domain/agent_bindings.py (bind/unbind/update)
   - Implement domain/agent_subscribers.py (notify logic)
   - Migration script (migrate.py)
   - 50 unit tests

2. **Implementer #2: API + UI + Integration** (30% effort)
   - api/agents.py router (5 endpoints)
   - api/agent_bindings.py router (4 endpoints)
   - static/agent-library.html (publish/subscribe UI)
   - static/ai-systems.html (Bound Agents section)
   - 20 integration tests
   - Update dashboard.py routing

3. **Implementer #3: Governance Integration** (30% effort)
   - Modify framework_coverage.py (weakest-link aggregation)
   - Modify release_gate_engine.py (agent-aware gates)
   - Modify runtime_engine.py (agent-specific memory tiers)
   - Seeded test data (6 agents: 3 team-owned, 3 reusable)
   - Regression tests (framework coverage, gates, memory)

**Then (all agents complete):**
- Run full test suite: `pytest tests/` (66 new + 96 regression = 162 total expected)
- Spawn code-reviewer + security-reviewer in parallel
- Update ARCHITECTURE.md, DECISIONS.md, HANDOFF.md
- Commit with message: `Feat: Session 07 — Multi-Agent + Agent Library (Day 7)`

---

## Success Definition

Session 07 is complete when ALL of the following pass:

- [ ] `pytest tests/test_agents_unit.py` → 50 passed
- [ ] `pytest tests/test_agent_bindings_integration.py` → 20 passed
- [ ] `curl https://localhost/api/agents` → 200 with at least 6 agents
- [ ] Publish agent v2 → subscriber notified within 30s
- [ ] Bind agent v1 to system; framework coverage updates; gates evaluate agent failure
- [ ] Framework matrix shows per-agent coverage breakdown
- [ ] UI: /agent-library renders 6 seeded agents with version history; /ai-systems shows Bound Agents section
- [ ] Migration: legacy ai-sys-001 auto-migrated with AgentBinding created
- [ ] All 96 regression tests still pass
- [ ] Code review: no blocker findings
- [ ] Security review: no blocker findings

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Polling SLA (30s) missed due to client timing | MED | MED | Test with synthetic 10s polling; if 30s tight, escalate to Option B (SSE) |
| Weakest-link aggregation breaks existing gates | MED | HIGH | Regression tests validate gates still work; framework_coverage changes are additive |
| JSONL migration loses data on corrupt file | LOW | CRITICAL | Pre-flight check: validate existing events.jsonl before migrate.py; checkpoint backup |
| Agent versioning conflict with frameworks YAML | LOW | LOW | agents use semver.yaml, frameworks use bare yaml; no conflict; version fields namespaced |

---

## Next Steps

1. **Reply with 4 decisions** (A/B/C choices for each decision above)
2. **Reply with "approved" or "go"** when ready to execute
3. **On approval:** I spawn 3 sub-agents in ONE message, TaskCreate up front, track with task IDs
4. **Then:** Run all tests, parallel code + security review, update docs, commit

**No code is written until all 4 decisions are locked + explicit approval given.**
