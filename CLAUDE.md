# CLAUDE.md — AI Assurance Platform | aigovern.sandboxhub.co

## Before every task
Read ARCHITECTURE.md before writing any code.
Confirm by stating the current decorator chain order and
the three most recent "in progress" files.

## Code standards
- Full updated files only — never partial functions or snippets
- Type hints on all parameters and return values
- Docstring on every public function
- `from __future__ import annotations` at top of every Python file
- Pydantic v2 for domain models — ConfigDict, not Config class
- Read every existing file before modifying it
- `python -c "import <module>"` must pass before next file

## Security rules (never violate)
- scrubber.tokenise_payload() runs BEFORE tracer.trace_call()
  Langfuse gets scrubbed_prompt — never raw_prompt
- Policy engine errors → default DENY, never ALLOW
- No SaaS guardrails — all self-hosted, no external prompt routing
- No secrets in code — all config via environment variables

## Storage rules
- JSONL only via storage.py _append_jsonl() and _read_jsonl()
- No direct file writes outside storage.py pattern

## File placement
- New root modules: beside tracer.py (scrubber.py, providers.py)
- New domain: domain/<name>.py — follow domain/repository.py
- New API routers: api/<name>.py — mount in dashboard.py
- New UI: static/<name>.html — follow static/runtime.html
- New middleware: middleware/<name>.py
- Policy files: policies/<name>.rego

## When blocked
Stop. State the blocker. Never fake output. Never work around silently.

## End of every session
1. Run /verify — show all output
2. Update ARCHITECTURE.md — move completed items
3. Write next session plan file to docs/plans/
4. List deviations and open issues

## Compound engineering rule
Every mistake I correct → add a new rule to this file immediately.
Label it with the date. This file grows with experience.

### 2026-06-01 — Eager-imported top-level packages must be in deploy/build-zip.py INCLUDE
When dashboard.py adds a NEW top-level package eager import
(`from <pkg>...` or `import <pkg>` at module scope),
deploy/build-zip.py::INCLUDE must list `"<pkg>"` in the same commit.
Otherwise the engine container crashes on startup with
ModuleNotFoundError and /api/health 502s with the SCM "Application Error"
page — no error in the path that fails because the path never opens.
S80 ate one CD round-trip on this: agents._registry was eager-imported
but agents/ was never in the include list. See [[appservice-deploy-python]]
failure mode #1 and [[lazy-imports-skip-module-load-bootstrap]] — this
rule is the deploy-side mirror of the latter.

### 2026-06-01 — Agent onboarding follows docs/SOP-agent-onboarding.md; eval is the spec
Any plan that adds, modifies, or promotes an agent MUST cite
`docs/SOP-agent-onboarding.md` and explicitly account for all 13 phases
(executed / waived-with-reason / deferred-with-date).

The SOP is **eval-co-evolved**: Phase 4 (Behavioral Spec — dataset.jsonl,
per-metric thresholds, MRM sign-off) gates Phase 5 (V0 Build). Writing
agent code before the eval skeleton exists violates the SOP and the
global CLAUDE.md PROMPT CALIBRATION rule (the worked-example calibration
the global rule requires IS the seed eval).

Agents that explicitly cannot complete the SOP (PoCs, demos, spikes)
MUST set `demo_only=True` in their `AgentSpec` (`agents/_registry.py`).
The flag propagates to API and UI so consumers see "DEMO ONLY —
not production-governed." `demo_only=True` is honest, not aspirational —
removing the flag requires executing the missing phases.

S80 added `finadvice` skipping 11/13 phases (notably Phase 4 — no eval
suite); S81b marks it `demo_only=True`. Same for `azure-architect`.

### 2026-06-01 — Agent default_system_id must be backed by an AI system row
When a new agent is registered in `agents/_registry.py` with a
`default_system_id`, that id must also exist as an `AISystem` entry in
`domain/seed.py::AI_SYSTEMS` (or be persisted via the intake/submit flow).
Otherwise the agent runs cleanly + the audit chain writes correctly +
the AI Systems page silently does not list it — audit join keys point at
nothing, governance surfaces lose coverage, and the operator can't see
the system the agent supposedly governs.

Calibration for any new agent MUST include: open team-portal AI Systems
page, confirm the new `default_system_id` is visible. This is the
required UI binding check per [[ui-promise-audit-owed]] (F-018/F-022/F-023
class — plan described a thing, no surface binding).

Cheapest fix: add a seed row in `domain/seed.py::AI_SYSTEMS`. That file
is the auto-loaded source of truth (5 → 7 systems as of S81 carryover);
`domain/seed_systems.py::seed_test_systems()` is a DIFFERENT mechanism
that is never invoked from `dashboard.py` lifespan today — don't add new
systems there. S80 closed without this; S81 backfill added finadvice and
azure-architect.

### 2026-06-01 — Never persist secrets to App Service `/home`; surface via tagged CRITICAL log
App Service Linux mounts `/home` via Azure Files (CIFS) with a fixed
permissive umask. `os.chmod(path, 0o600)` against any file under `/home`
silently no-ops — the file lands at `0777` regardless of the chmod call,
and there is no exception raised that code can catch. The provisioner
LOOKS correct on Windows/local dev (where chmod works) and SILENTLY
ships a world-readable secret to prod.

Rule: Bootstrap-minted secrets MUST be surfaced via a single
CRITICAL-level log line tagged `SECRET_BOOTSTRAP_DO_NOT_LEAK` (or an
equivalent grep-able sentinel), captured by App Insights, retrieved by
the operator via a tagged Kusto query, and aged out per the workspace
retention policy. Never write secret material to `/home`, never trust a
chmod against it.

S82f-1 wrote vendor_risk SDK secrets to `/home/.s82f-secrets-*.txt`
expecting 0600; S82f-1b verification found the actual mode was 0777.
See [[appservice-home-permissions]] and the deploy-side mirror
[[appservice-deploy-python]].

### 2026-06-01 — Deferred-execution imports are still deploy dependencies
A module imported only inside lazy-loaded code (e.g. an agent the registry
loads on demand) is still a deploy-time dependency. The fact that no
eager import touches it means the failure surfaces on first invocation,
not at startup — `/api/health` will report `status=ready` while the
chain detonates with `ModuleNotFoundError` on the first real call.

S82f-1c: `sdk/signallayer/` was never in `deploy/build-zip.py::INCLUDE`.
`agents/vendor_risk/agent.py` does `import signallayer` at module scope
but the agent is lazy-loaded by `agents._registry.load_agent_inner`, so
the missing import only fired when the first calibration run executed.

This is the **deferred-execution variant** of the 2026-06-01 eager-import
rule. Any import touched by ANY agent or lazily-loaded domain module
must be in `INCLUDE` (or `INCLUDE_REMAP` if the source path differs from
the import name). The calibration / first-invocation pass IS the
integration test for this.

### 2026-06-01 — Operator role must thread from session cookie to policy_engine
`domain/agent_runner.py::stream_agent_run_with_chain_events` had the user
dict from `middleware.auth._read_cookie` but the `policy_evaluate` call
only passed `{prompt}`. Any rego policy gating on `required_operator_roles`
saw `operator_role=''` and DENIED every call.

S82f-1c: every vendor_risk run via agent-runner returned
`policy_gate: DENY workload_operator_role_not_allowed` until the
dispatcher was patched to forward `operator_role` from the user dict.

Rule: any new field on the session cookie that a policy could use MUST
be added to `policy_evaluate(input_data=...)` at the same time. Grep
`policy_evaluate(` and verify every call site forwards every
auth-derived field a policy might test. Policy-side mirror of
[[signed-token-refresh-must-preserve-every-payload-field]].

### 2026-06-01 — Persistence paths must resolve via DATA_ROOT
Any new JSONL store added under `data/` MUST resolve its path through
the canonical pattern from `domain/audit_chain.py`:

```python
_DATA_DIR: Path = Path(os.environ.get("DATA_ROOT") or
                       (Path(__file__).resolve().parents[1] / "data"))
```

Bare `Path("data") / "x.jsonl"` resolves against the engine's cwd. On
App Service the writable data dir is `/home/data/` (via `DATA_ROOT`),
NOT the cwd. The bare-Path version silently writes to (or fails to
write to) some path nobody reads. If wrapped in best-effort try/except
(as persistence-side code often is) the failure surfaces as
"feature works locally, returns empty in prod" with no error in logs.

S82f-1c: `/api/agent-runs` returned `count:0` for hours of calibration
runs until commit `c19d455` aligned the path resolution.

Rule: grep `Path("data")` before any commit that adds persistence.
Should be zero hits outside canonical `_DATA_DIR` declarations.

### 2026-06-01 — INT vendor_risk policy gate already enforces no-egress
S82f-1b handoff predicted "INT runs WILL make outbound Anthropic calls
— `assert_no_egress()` exists but isn't wired into the execution path."
S82f-1c calibration found the OPPOSITE: all 8 INT runs DENIED at
`policy_gate` on `workload_required_flag_not_set` (rule requires
`dlp_completed` + `network_egress_lock_engaged`), so no LLM call fired.

The rego gate enforces the INT-no-egress contract at the policy
boundary even without the runtime `assert_no_egress()` wired on the
execution path. The runtime assertion remains valuable as
defense-in-depth, but it's not the primary control.

Rule: when documenting a "this isn't wired yet" caveat, audit whether
another control already covers the same invariant. The defense-in-depth
layer might already exist.

## Workflow + token bands
Operating rules (workflow classification, token bands, review/stop/cost
control) live in global `~/.claude/CLAUDE.md` under SESSION MANAGEMENT.
Project may tighten bands here if a project-shape reason exists; do not
restate the rules themselves.
