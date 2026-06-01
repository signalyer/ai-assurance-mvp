# Resume — AI Assurance Platform · S79 (showcase arc kickoff)

## Where I am
S77 + S78 closed the prod gaps: schema bootstrap works, App Insights is on
the GA distro, and the streaming dispatcher writes T2 episodes on every
SSE completion. Live SHA `8f41366`. The platform is structurally ready
for an end-to-end SignalLayer-team showcase. The next 8 sessions
(S79–S86) wire, polish, and rehearse that showcase. This session is S79
— the demo-loop wiring session.

## Scope of the 8-session arc (locked S78)
S79 demo-loop wiring (dual-path) · S80 end-user surface + guardrails ·
S81 cross-portal + audit chain · S82 live observability + cost ·
S83 reports + RTF · S84 UI-promise audit + RBAC SPA · S85 Tier-3 health ·
S86 full dry-run + fix-everything-found.
Full breakdown: see chat just before this handoff was written, or the
plan file for each session as they get authored.

## Decisions already made — don't re-litigate
- **Wrap point** = `_stream_live_assurance_response` in `api/assurance_model.py`. Decorator chain runs procedurally there (policy gate → sanitize → audit → episode). No new decorator file needed.
- **`workload_id`** = `req.ai_system_id or req.use_case or "unknown"`. System-level for now; introduce a `workload` abstraction only when a second dimension shows up.
- **Internal-path provider** for the showcase = `simulate_response` wired into the dispatcher (not Azure OpenAI in-tenant, not vLLM). Instant, deterministic, governance-correct. Demonstrates "every byte policed regardless of destination."
- **Showcase audience** = SignalLayer team (not customer / not Microsoft). Tier 4 items skipped: adversarial UI, drift alerts, mobile, multi-tenant, prod-grade Key Vault.
- **Episode persistence is non-fatal** to the SSE response (try/except + `_log.exception`).

## S79 concrete deliverables
1. Verify intake → portfolio visibility for 2 new test systems (run live, fix any drift).
2. Verify Agent Library publish + bind + Accept-Upgrade still work.
3. **Add LOCAL dispatcher branch** in `api/assurance_model.py` calling a new `stream_local_response` generator in `domain/assurance_providers.py`. Generator wraps `simulate_response` and yields the same `("delta", text)` / `("done", usage_dict)` contract. Provider entry: register a `local-simulated` provider in `PROVIDERS` if not present.
4. **Refactor `agents/azure-architect/agent.py`** to route through the dispatcher chain instead of calling `write_episode` inline (currently bypasses policy/scrub/guardrails).
5. Grep all other `write_episode` callers; bring each through the chain or document why it's intentionally direct (e.g. `api/sdk_episodes.py` writes from external SDK and IS the entry point — fine).
6. Wire eval suite UI to read **real episodes** (S70b carryover). Suite run → scores write to `episodes.eval_scores`.
7. Auto-create finding when an eval score drops below threshold (new glue in `domain/findings_workflow.py`).

## Key files to load
- `api/assurance_model.py` — dispatcher (S78 wrap site)
- `domain/assurance_providers.py` — `stream_anthropic_response`, `stream_bedrock_response`, `simulate_response`, `PROVIDERS`
- `domain/agent_memory.py` — `write_episode` chain
- `agents/azure-architect/agent.py` — inline write_episode call site to refactor
- `domain/findings_workflow.py` — eval-failure → finding glue
- `api/evals_v2.py` + `team-portal/src/pages/evals/*` — UI rewiring
- `docs/plans/SESSION-70b-eval-ui-real-and-agent-memory.md` — eval-UI carryover context
- `docs/plans/HANDOFF-S78-resume.md` — prior session state

## Outstanding questions (need user input)
1. **2 demo system names + use cases?** e.g. `sys-demo-finadvice-001` (external, Anthropic) and `sys-demo-compliance-001` (internal, simulated). Or pick your own.
2. **Eval-failure threshold for auto-finding?** Suggested: any score < 0.6 creates a P2 finding; < 0.4 creates a P1.
3. **One end-user-facing question prompt to seed the demo flow?** Used in S80 for the end-user surface.

## Next concrete action
After confirming the 3 outstanding questions, start with step 3 (LOCAL
dispatcher branch + stream gen + provider entry) — it's the smallest
self-contained piece and unblocks the dual-path narrative immediately.

## Working rules in effect
All prior rules. Key locks for S79:
- [[lazy-imports-skip-module-load-bootstrap]] — eager import any new module whose bootstrap matters.
- [[anthropic-max-tokens-streaming-threshold]] — streaming context manager only.
- [[bare-except-hides-broken-integrations]] — logger.exception, never bare pass.
- [[ui-promise-audit-owed]] — every operator verb shipped in S79 must have a UI binding before close.
