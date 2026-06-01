# Resume — AI Assurance Platform · post-S77

## Where I am
**S77 closed both S76 production gaps.** Engine at
`app-aigovern-dev.azurewebsites.net`, live SHA `3de502a`. SQLAlchemy +
psycopg2 installed, all four `domain/agent_*` schemas bootstrap at
startup, data persists across deploys (verified via 6 UniqueViolation
matches = the 6 seeded agents from the prior deploy). App Insights
GA distro `azure-monitor-opentelemetry` wired; spans flowing into
`appi-aigovern-dev` within 60s of first request (10 requests captured
in last 30 min during S77 verification).

## Commits shipped this session
- `9430985` sqlalchemy + psycopg2-binary in deploy reqs
- `5acbd4a` eager-import agent_bindings/agent_subscribers in lifespan
- `6e2b3bf` App Insights attempt #1 (beta exporter — superseded)
- `3de502a` App Insights via GA distro (live)

## Next concrete action — wire agent_memory decorator chain into prod
**The blocker is gone.** The `episodes` table is empty in prod not
because the engine is broken (it's not — S77 fixed it), but because no
prod request path calls `write_episode` through the decorator stack
`@policy_gate → @scrub_pii → @guardrails → @trace → @evaluate`.

S70b test validates the contract end-to-end. The missing piece is the
PRODUCTION caller. `agents/azure-architect/agent.py` calls
`write_episode` inline (bypassing the chain); meanwhile the real prod
traffic flows through `domain/assurance_providers.stream_bedrock_response`
(S75 dispatcher) which doesn't call write_episode at all.

Two design questions for the new session:
1. Does the decorator chain wrap the streaming dispatcher (per-call
   episode write after stream completes), or does it wrap individual
   agent entrypoints?
2. What's the workload_id mapping for non-agent surfaces (team-portal
   Ask AI, Summarize, Draft Report) — `system_id`? a new "workload"
   concept? per-conversation UUID?

## Key files to load
- `domain/agent_memory.py` — `write_episode` + decorator chain
- `domain/assurance_providers.py` — S75 Bedrock streaming dispatcher
- `agents/azure-architect/agent.py` — current inline write site
- `tests/test_agents_unit.py` (S70b) — contract test
- `api/dispatcher.py` (or wherever streaming routes live) — call sites
- `docs/plans/SESSION-70b-eval-ui-real-and-agent-memory.md` — S70b context

## Outstanding chips / open work
- 🔧 Chipped: `seed_agents` not idempotent on `agent_versions` insert (6
  IntegrityError stack traces per cold start, non-fatal but noisy)
- 🔧 RAG index `aigovern-rag-index` doesn't exist on `search-aigovern-dev`
  → Memory page T3 KPI shows `—`. Separate workstream, lower priority.
- 🔧 UI-promise audit overdue ([[ui-promise-audit-owed]])
- ⏳ Postgres password rotation (S71 carryover)
- ⏳ Seed 1 finding + 1 failed gate to unblock S76 smoke surfaces #2/#5/#8

## Decisions locked
- App Insights = GA distro `azure-monitor-opentelemetry>=1.6` only. Never
  the bare beta exporter ([[azure-monitor-use-ga-distro]]).
- `configure_azure_monitor()` runs BEFORE `from fastapi import FastAPI` —
  current dashboard.py ordering is correct, do not move.
- Eager-import any module whose module-load bootstrap matters
  ([[lazy-imports-skip-module-load-bootstrap]]).
- Kudu REST + JSONL tail remains the canonical zero-lag verification path
  for fast iterations; App Insights KQL for post-deploy span confirmation
  (~60-90s lag).

## Working rules in effect
All prior rules. Three new in S77: see memory locks above plus
[[requirements-deploy-drift]] reinforced (sqlalchemy + opentelemetry both
hit this drift class in one session).

## Session entry checklist
```powershell
az account set --subscription "SignalLayerDev"
$env:MSYS_NO_PATHCONV = "1"
cd C:/ai-assurance-mvp
git status
git log --oneline -5
```
