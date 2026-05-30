# SESSION-71 — SDK episode_write decorator + LLM action surface rollout

> Two distinct work blocks. Choose at session start which one to run; both
> are bounded enough to fit a single session if focused, but doing both
> together risks Refactoring band overrun.

## Background from S70b
S70b proved the inline path: `agent.py` calls `domain.agent_memory.write_episode()`
directly after the LLM + eval. This works **from inside the engine** but not
from a customer agent box because:
1. Postgres firewall blocks arbitrary IPs (correct security posture)
2. Customer agent venv shouldn't ship sqlalchemy + psycopg2-binary just to write
   an episode

The architectural intent per `[[v1_to_v2_real_data_arc]]` is **SDK-first
telemetry**: agent → SignalLayer HTTP API → engine writes to Postgres. S69's
explain-release SSE proved one half (HTTP from server side); S71 closes the
other half (HTTP from client side) by adding `episode_write` to the SDK.

## Block A — SDK `episode_write` decorator (Recommended)
**Workflow type:** Refactoring (token band Normal <500K)

### Goal
Replace `from domain.agent_memory import write_episode` in customer agents
with a `signallayer.write_episode()` HTTP call. Customer agents no longer
need engine deps.

### Steps
1. **Engine endpoint** — `POST /api/sdk/episodes` accepting the same shape
   `write_episode()` takes (workload_id, scrubbed prompt, scrubbed response,
   outcome, metadata). Strict Pydantic v2 in + out. Auth via existing
   HMAC-SHA-256 SDK middleware (same path `policy_gate` uses).
2. **SDK function** — `signallayer/client.py::write_episode(...)` that signs
   + POSTs. Returns the discriminated `Result[EpisodeId, SignalLayerError]`.
3. **Agent migration** — in `agents/azure-architect/agent.py`, swap the
   direct `domain.agent_memory.write_episode` import for
   `signallayer.write_episode`. Same call-site shape.
4. **Remove transient deps** — `pip uninstall sqlalchemy psycopg2-binary` is
   no longer needed for the local agent venv after this lands.
5. **Engine deploy + smoke** — run the agent locally, confirm episode row
   appears in `psql` via the deployed engine's connection (not the local one).
6. **Pytest** — at least one integration test using `TestClient` against the
   new endpoint + one SDK unit test for the signer.

### Risks
- HMAC signer must match middleware byte-for-byte. Past sessions cite this
  as a recurring trap (see `cli/sl/auth.py` for the reference impl).
- Endpoint must be auth-gated at the SDK middleware (key-id + signature),
  NOT at SessionAuthMiddleware — agents have no cookies.
- Don't break the existing `domain.agent_memory.write_episode` callers
  (engine-side use is fine; only the agent migrates to SDK).

## Block B — LLM action surface rollout (originally S70 plan-A)
**Workflow type:** Architecture (token band Normal <750K)

### Goal
Port S69's streaming pattern to the remaining 3 LLM affordances on the
assurance_model router (ask, summarize-finding, summarize-evidence,
draft-report).

### Steps
1. **Engine** — switch `ask`, `summarize-finding`, `summarize-evidence`,
   `draft-report` in `api/assurance_model.py` to `_dispatch_streaming`.
2. **Prompt builders** — add 4 new use cases to
   `domain/assurance_providers.py::_build_prompt()` + `_MAX_TOKENS_BY_USE_CASE`.
3. **SPA** — wire 4 new buttons (probably on AiSystemDrawer or a new
   AI-actions menu component). Reuse S69's `<AiSummaryDrawer />` mount.
4. **ciso-console port** — mount `AiSummaryDrawer` on `ciso-console/src/app.tsx`
   so CISOs can use the same affordances. Carry the Anthropic-pin per S69.
5. **Tests + deploy + verify** per the S69 + S70b deploy playbook.

### Risks
- AiSystemDrawer is already busy. UX may need an "AI Actions" menu.
- ciso-console SPA has separate build/deploy chain — apply
  `[[spa-deploy-is-manual-swa]]` to BOTH SPAs.
- max_tokens > 2000 on any prompt → streaming context manager only.

## Cleanup carryover from S70b
- Rotate dev Postgres admin password.
- Triage `AGENTS.md` (untracked since S69).
- Triage `team-portal/cookies.txt` (untracked since S69).
- Refactor agent.py outcome logic to use `payload.get("skipped")` directly
  (canonical signal) instead of `score is None` (correlates 1:1 but
  conceptually indirect). Tiny edit; bundle with whatever else touches that
  file.
- Add an agent_memory integration test (deferred from S70b STEP 7 — needs
  decorator-chain-aware mocking that's worth its own pass).

## Done when (block A)
- Customer agent runs end-to-end with `pip uninstall sqlalchemy` (no engine deps).
- Episode row visible in Postgres via the engine's connection.
- SDK + engine tests green.
- ARCHITECTURE.md updated with S71 block.

## Done when (block B)
- All 4 LLM affordances stream live on both SPAs.
- Per-button smoke confirms each landed without disconnect.
- ARCHITECTURE.md updated with S71 block.
