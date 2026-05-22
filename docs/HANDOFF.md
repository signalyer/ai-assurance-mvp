# Resume — AI Assurance Platform

**Last session ended:** 2026-05-21 (Day 7 of 12 — Sessions 01-07 complete · 7 commits ahead of origin after this commit lands)
**Repo state:** ready to commit · `main` (next commit = Session 07)
**GitHub:** https://github.com/signalyer/ai-assurance-mvp (private)

---

## Where I am
Day 7 of the 12-day production sprint complete:
- 01a/01b: Scrubber + Fernet vault + `@scrub_pii` ✓
- 02: Policy engine + OPA + `@policy_gate` ✓
- 03: Guardrails (injection + topic + safety) + `@guardrails` ✓
- 04: Memory (Postgres TTL) + RAG (Azure AI Search hybrid) ✓
- 05: Provider abstraction (5 Protocols + BaseSettings + 7 backends) ✓
- 06: Framework Coverage Matrix (6 systems × 8 frameworks) + YAML catalogs + 3 PDF Packs ✓
- 07: **Multi-Agent + Agent Library** (6 seeded agents, 6 new test systems, Postgres pubsub) ✓

Decorator chain (unchanged): `@policy_gate → @scrub_pii → @guardrails → @trace_llm_call → @evaluate_response`
Tests: 82 new (Session 07: 50 unit + 20 integration + 12 governance) — all pass. Sessions 01-06 verification smoke checks (~66 imports) all pass.

## Decisions locked (DECISIONS.md — don't re-litigate)
- Decorator chain order · fail-closed everywhere · self-hosted guardrails only
- Tier 2 = Postgres TTL · Tier 3 = Azure AI Search hybrid
- API → sync domain calls via `asyncio.to_thread`
- Backend interfaces = `typing.Protocol`; backend config = Pydantic v2 `BaseSettings`
- `legacy_guardrails.py` deleted
- Framework defs hybrid YAML/Python; matrix surfaces 8 user-facing slugs
- PDF Packs stdlib-only via `_PdfWriter`
- **NEW Session 07 decisions:**
  - Agent storage: Postgres-primary with JSONL audit trail (events.jsonl captures AGENT_PUBLISHED, AGENT_BINDING_CREATED, AGENT_BINDING_UPGRADED, AGENT_BINDING_REMOVED, AGENT_VERSION_CREATED, AGENT_CREATED)
  - Version pinning: database-tracked (separate `agent_versions` table; bindings store `version_id` FK, not semver string; semver regex-validated at both model and API boundary)
  - Notifications: Postgres LISTEN/NOTIFY (NOTIFY producer in `domain/agents.publish_version` inside transaction; LISTEN consumer in `api/agent_notifications.py` SSE endpoint with `quote_ident` channel safety + 25s keepalive)
  - No migration of ai-sys-001 — 6 NEW seeded systems instead (sys-payments-001, sys-cx-001, sys-risk-001, sys-platform-001, sys-finserv-001, sys-internal-001) each bound to 1-3 agents
  - Seed agents `framework_refs` uses `list[str]` format `"FRAMEWORK:CLAUSE"`; coverage code supports both `list[str]` and `list[dict]` for forward-compat

## Working rules in effect (memory)
- `feedback_subagents_context_default.md` — 3+ file sessions default to parallel sub-agents in single Agent-block message + parallel code-reviewer/security-reviewer after, TaskCreate tracking
- `feedback_batch_llm_calls.md` — never sequential LLM calls when asyncio.gather possible
- `feedback_appservice_deploy_python.md` — 10 failure modes to apply upfront on Python App Service deploys

## Key files to load for next session
1. `CLAUDE.md` — auto-loaded
2. `ARCHITECTURE.md` — current Built state through Session 07
3. `DECISIONS.md` — all locked decisions including 4 new Session 07 entries
4. `docs/plans/12-DAY-PRODUCTION-SPRINT.md` — Day 8 spec (Right-to-Forget + Tamper-Evident Audit)
5. `docs/plans/SESSION-07-multi-agent.md` — completed Session 07 plan (reference)
6. `domain/agents.py`, `domain/agent_bindings.py`, `domain/agent_subscribers.py` — agent layer ready to extend for Day 8

## Outstanding question for next session
Day 8 = Right-to-Forget cascade + Tamper-Evident Audit log. Decisions to lock before approval:
1. **Right-to-forget orchestration** — synchronous within request, async background job, or distributed transaction (saga pattern) across vault + Tier 2 + Tier 3 + Langfuse?
2. **Hash chain algorithm** — SHA-256 over `(prev_hash || event_json)`, or HMAC-SHA-256 with a Key Vault secret for tamper evidence?
3. **Verification endpoint scope** — full chain replay on every `/audit/verify` call, or rolling window (last N events) with checkpointing?
4. **Cascade idempotency** — store cascade_id in events.jsonl with reverse lookup, or treat each store delete as idempotent on (subject_id, store_name)?

## Next concrete action
Read `CLAUDE.md`, `ARCHITECTURE.md`, `DECISIONS.md`, then `docs/plans/12-DAY-PRODUCTION-SPRINT.md` Day 8 section. Draft `docs/plans/SESSION-08-right-to-forget.md` with 6-item pre-execution review. Ask the 4 locked-decision questions above. Wait for explicit "Y" / "go" / "approved" before spawning agents.

## Open items deferred from Session 07
- **SECURITY DEBT (must fix Day 10 hardening):** SSE endpoint at `/api/agents/{agent_id}/listen` has no per-IP rate limit and no global SSE connection cap. Each SSE client opens a dedicated Postgres LISTEN connection — at Postgres `max_connections=100` default, a single unauthenticated attacker can exhaust the pool. Track as HIGH security finding from Session 07 security review.
- **SECURITY DEBT (pre-existing, not Session 07):** `static/ai-systems.html` lines 113–241 still use raw `${s.name}`, `${s.trust_boundaries}`, `${rev.approval_status}`, etc. without escaping in the legacy table/drawer code. Only the Session 07 Bound Agents drawer section uses `_escHtmlAis` properly. Stored XSS risk if any system name or revision field contains malicious HTML. Fix in Day 10 hardening.
- **SECURITY DEBT (MEDIUM):** `publish_version` audit event (AGENT_PUBLISHED) is written outside the publish transaction — if audit write fails, NOTIFY has already fired. Move audit inside transaction in Day 8 (aligns with tamper-evident audit work).
- **SECURITY DEBT (MEDIUM):** No ownership check in `domain.agent_bindings.update_binding_version` for the (binding.agent_id, version_id) relationship — an authenticated user could PATCH a binding to point at a version_id from a different agent. API layer now gates via `get_binding(binding_id, system_id)`, but the domain function doesn't enforce. Add agent-FK check in domain Day 8.
- **CODE DEBT (LOW):** Three separate SQLAlchemy engines (one per domain module) creating up to 45 connections from the agent layer alone. Consolidate into shared `domain/_db.py` engine in Day 10 hardening.
- **CODE DEBT (LOW):** `import re as _re` and `from pydantic import field_validator` inside `AgentVersion` class body in `domain/models.py` — non-standard but functional. Refactor in Day 10.
- **Role-based authorization** missing on mutating endpoints (POST /api/agents, POST /api/agents/{id}/publish, POST/PATCH/DELETE /api/systems/{id}/bindings). All authenticated users can publish/bind/unbind. Add role checks in Day 10.
- ISO 42001 / SR 11-7 / FFIEC PDF Packs — endpoints return 501; deferred to Session 11.

## Recent commits (last 5)
```
6b77497 Feat: Session 06 — Framework Coverage Matrix (Day 6)
48b77c8 Feat: Session 05 — Provider abstraction + legacy guardrails delete
14afa3c Feat: Session 04 — Memory (Postgres TTL) + RAG (Azure AI Search hybrid)
287d627 Docs: pre-stage Session 04 — 8 tasks queued, handoff updated
af22647 Docs: Session 03 completion — DECISIONS.md, SESSION-04 plan, HANDOFF
```
(Next commit = Session 07 work)

---

## Opening prompt for the new session (paste verbatim)

```
Read docs/HANDOFF.md first, then docs/plans/12-DAY-PRODUCTION-SPRINT.md
Day 8 section.

Status: Sessions 01-07 complete · 82 + 66 acceptance/regression checks pass ·
7 commits ahead of origin/main · ready for Day 8 (Right-to-Forget +
Tamper-Evident Audit).

Do NOT spawn agents or write code yet. Do this first:

1. Draft docs/plans/SESSION-08-right-to-forget.md with the 6-item
   pre-execution review:
   - Decorator chain order (unchanged)
   - Every CREATE file with one-line purpose
   - Every MODIFY file with exact change
   - Two most critical architectural constraints
   - Explicit "Will NOT build" list
   - Acceptance criteria with runnable assertions

2. Surface 4 decisions via AskUserQuestion:
   - Cascade orchestration: sync vs async background vs saga
   - Hash chain algorithm: SHA-256 vs HMAC-SHA-256 with Key Vault secret
   - Verification scope: full replay vs rolling window
   - Cascade idempotency: cascade_id reverse lookup vs (subject_id, store) idempotent

3. Wait for explicit "Y" / "go" / "approved" before executing.

On approval: spawn 3 sub-agents in ONE message (TaskCreate up front).
Then run all new + 82 regression tests. Spawn code-reviewer + security-
reviewer in parallel. Update docs trio. Commit.

The parallel-agent + TaskCreate workflow is the default per
feedback_subagents_context_default.md memory entry.
```
