# Resume — vendor_risk SOP S82f (Phase 7 + 8)

**Status:** S82f-1 attempted 2026-06-01; stopped before code shipped after
discovery surfaced three architectural gaps that weren't in the original plan.
No artifacts produced or deployed. State of repo unchanged from S82e lock
(commit `3f00754`). All S82f task IDs in TASKS are pending.

This handoff folds the three findings into a sharpened execution sequence so
the next session can ship without re-discovering them.

---

## What S82f-1 surfaced (load-bearing for the next session)

### Finding 1 — Dual agent store: registry ≠ governance catalog

`agents/_registry.py` (the runner dispatch table) and `domain.agents` (the
governance catalog backing `POST /api/systems/{sys_id}/bindings`) are
**separate stores**. `vendor_risk` is in the registry from S82d but **not yet
in the governance catalog**. `api/agent_bindings.py:269` validates the agent
via `domain.agents.get_agent(agent_id=...)` — without a catalog row, the bind
POST will 400 with `AGENT_NOT_FOUND`.

This is the same shape as memory note `[[agent-default-system-id-needs-seed]]`
— plan named the verb (bind), didn't audit the surface store.

**Fix:** add a Phase 7 bootstrap module
(`agents/vendor_risk/onboarding/sdk_provisioning.py`) that on lifespan startup
idempotently:
  1. Calls `domain.agents.create_agent(agent_id="vendor_risk", ...)` —
     `ON CONFLICT (id) DO NOTHING` already in `domain/agents.py:227` makes
     this safe on every cold start.
  2. Calls `domain.sdk_keys.issue_key()` for each of
     `sys-vendor-risk-ext-001` and `sys-vendor-risk-int-001` if not already
     present (check via `list_keys(ai_system_id=..., include_revoked=False)`).
  3. Writes plaintext HMAC secrets to `/home/.s82f-secrets-{system_id}.txt`
     mode `0o600` ONLY on first issuance — never echoes them.

Wire into `dashboard.py` lifespan immediately after the existing
`ensure_vendor_risk_systems()` call at line 198. Add to
`docs/sop-vendor-risk/07-provisioning-receipts.md` with key_id values only
(no plaintext).

### Finding 2 — `runtime_status` is a MATERIAL field (governed transition)

`domain/ai_system_edit.py:51` classifies `runtime_status` as MATERIAL, which
means edits go through the revision flow with reviewer approval and the
system enters `pending_revision`. S82f's "flip runtime_status → STAGED" is
therefore **not** a 1-line JSONL hack — it's a governed promotion that
should land via a proper API surface.

Two paths forward, pick one in the next session:

**Path A (purist, recommended):** Add a new domain function
`domain.runtime_promotion.promote_to_staged(system_id, *, signed_by, sop_phase_evidence)`
that asserts:
  - Source `runtime_status == DESIGN`
  - Target `runtime_status == STAGED`
  - All P0 release gates PASSED or WAIVED (per SOP Phase 8 exit gate)
  - 100+ STAGED runs is a Phase 8 entry deliverable, NOT a promotion
    requirement — promote then accrue runs in STAGED
  - Append `RUNTIME_STATUS_PROMOTED` event to `data/events.jsonl`
Surface as `POST /api/systems/{sys_id}/promote-to-staged`.

**Path B (pragmatic):** In the bootstrap module, treat the DESIGN→STAGED
flip as a one-time "Phase 7 provisioning event" — bypass the
MATERIAL/revision flow with an explicit comment citing this handoff doc as
the documented exception. Audit trail still lands via
`append_agent_event("RUNTIME_STATUS_PROMOTED_BOOTSTRAP", ...)`. Faster but
sets a precedent S82h+ may have to undo.

### Finding 3 — Kudu shell auth requires `--resource` or basic auth

`az rest --uri https://app-aigovern-dev.scm.azurewebsites.net/api/command`
returns 401 without `--resource`. Two options:
  - `az rest --resource https://management.core.windows.net/ ...` and confirm
    the user has Owner/Contributor on the App Service.
  - `az webapp deployment list-publishing-credentials` → use returned
    `publishingUserName:publishingPassword` as basic auth (leaks SCM creds
    into transcript — same class as Finding 1 secret-disclosure risk).

The cleaner answer is **we don't need Kudu** — Finding 1's lifespan
bootstrap eliminates the need for any ad-hoc remote shell. Retrieval of the
plaintext SDK secrets after first issuance is one-time via
`az webapp ssh --name app-aigovern-dev --resource-group rg-aigovern-dev`
(interactive, operator runs it themselves), copying from
`/home/.s82f-secrets-*.txt` to Key Vault `kv-aigovern-sl-dev`.

---

## Confirmed environment state

- `DATABASE_URL` is set on `app-aigovern-dev` → Postgres governance catalog
  persists across restarts (no `_inmem_agents` fallback)
- `DATA_ROOT=/home/data` → SDK keys JSONL persists across deploys (per memory
  note `[[deploy-zip-overwrites-runtime-data]]`)
- `LANGFUSE_HOST=https://us.cloud.langfuse.com` + public key present
- `APPLICATIONINSIGHTS_CONNECTION_STRING` set; ApplicationId
  `70699009-fd7b-478e-9e61-93b1037bde64` — needed for AppInsights deep link
  URL builder
- Key Vault: `kv-aigovern-sl-dev` exists in `rg-aigovern-dev`
- S82e regression test green at 17/18 (94.4%), all P0 metrics 1.000

**Security note:** the prod Postgres password was surfaced in this session's
tool output via `az webapp config appsettings list`. Per the SignalLayer
demo-build rule (no Key Vault for demo) this is in-scope, but the transcript
contains plaintext — redact before sharing.

---

## Sharpened S82f-1 deliverables (revised)

Execute in this order in the new session:

1. **Pick promotion path** (A vs B above) — affects design of (4).
2. **Phase 7 bootstrap module**:
   `agents/vendor_risk/onboarding/sdk_provisioning.py`
   - `ensure_vendor_risk_catalog_entry()` → idempotent
     `domain.agents.create_agent(...)`
   - `ensure_vendor_risk_sdk_keys()` → idempotent SDK key issuance, plaintext
     to `/home/.s82f-secrets-*` 0600
   - Returns dict `{system_id: status}` matching existing bootstrap pattern
3. **Wire into `dashboard.py` lifespan** after line 200.
4. **Promotion module** (per Path A or B): runs as part of lifespan OR
   exposed via new API route.
5. **Telemetry deep-link builders** (was Task #3):
   `domain/agent_runner.py` chain.done event populates real `langfuse_url`
   and `appinsights_url`. URL format spec'd in the plan; use shared
   `operation_id` schema with `system_id` as custom dimension (your S82f
   pre-session decision).
6. **Network-egress assertion** (was Task #4): context manager wrapping the
   INT LLM step in `agents/vendor_risk/agent.py`. Monitors `socket.socket()`
   opens; raises `EgressViolation` on any outbound connect during INT runs.
7. **Deploy**: push to main → CI auto-deploys. Verify per memory note
   `[[appservice-deploy-python]]` — confirm `/api/health` 200 and a clean
   container start in log stream.
8. **Verify**: GET `/api/sdk-keys?ai_system_id=sys-vendor-risk-ext-001` →
   `key_id` visible. Same for int. Confirm `vendor_risk` in
   `GET /api/agents` (governance catalog).
9. **Run 25 calibration STAGED invocations** (was Task #7) via SPA Agent
   Runner picker. 12 ext + 13 int. Capture per-metric pass rate, latency,
   cost. Write `docs/sop-vendor-risk/07-staged-calibration-log.md`.

S82f-2 (separate session) owns: WebJob 6h eval cron, remaining 75 STAGED
runs, failure-mode drills, full `08-staged-run-log.md`. Decisions already
locked: WebJob host, shared EXT operation_id schema, live runs.

---

## Files to load first in the next session

- This file (`docs/plans/HANDOFF-S82f-resume.md`)
- `docs/plans/SESSION-82-vendor-risk-sop.md` — S82f section for original plan
- `docs/SOP-agent-onboarding.md` — Phases 7 + 8
- `agents/vendor_risk/onboarding/bootstrap.py` — pattern to mirror
- `dashboard.py` lines 180-210 — lifespan wiring point
- `domain/sdk_keys.py` — `issue_key`, `list_keys`
- `domain/agents.py` lines 165-260 — `create_agent` with ON CONFLICT
- `domain/ai_system_edit.py` — to understand the MATERIAL field constraint
  before doing the runtime_status work
- `api/agent_bindings.py` — confirms the catalog validation point at line 269
- `agents/vendor_risk/agent.py` — for the egress assertion wrap
- `domain/agent_runner.py` — chain.done event location

## Working rules in effect

Same as the prior S82e/S82f session-start handoff. Reiterated points:

- Anthropic streaming required (TOKEN_BUDGETS > 2000)
- TaskCreate for multi-step tracking; mark in_progress when starting
- Decorator chain order verbatim:
  `@policy_gate → @scrub_pii → @guardrails → @trace_llm_call → @evaluate_response`
- Per project CLAUDE.md 2026-06-01 rule: any new top-level package eager-
  imported in `dashboard.py` must be in `deploy/build-zip.py INCLUDE`. The
  `agents` package is already there; new submodules under it ride along.
- Per project CLAUDE.md 2026-06-01 rule: new agent registration needs
  matching governance catalog entry — **this handoff's Finding 1 is exactly
  that rule biting.**
- Auto Mode active; bias toward acting; pause only on hard blockers.

## Token budget guidance

S82f-1 (revised) estimate: ~250-300K. Lands in Deployment Normal band.
S82f-2 estimate: ~300-400K. Lands in Review Required (75 staged runs +
WebJob + drills is dense).

## Concrete next action

In the new session: load this handoff + the S82f plan section, then
`AskUserQuestion` on **promotion path A vs B** (Finding 2). That decision
gates the bootstrap module's design.
