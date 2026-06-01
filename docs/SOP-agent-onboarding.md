# Standard Operating Procedure — Agent Onboarding to Production

**Status:** canonical (S81b)
**Owner:** SignalLayer AI Assurance Platform team
**Cite this doc** in any plan that proposes adding, modifying, or promoting an
agent. The plan must explicitly account for each of the 13 phases below
(executed / waived-with-reason / deferred-with-date).

The sequence is **eval-co-evolved**: the eval is a *spec* the agent is built
to satisfy, not a quality check applied after code exists. The two
load-bearing reordering moves vs a naive build-first SOP are (a) Behavioral
Spec (Phase 4) gates V0 Build (Phase 5), and (b) Iteration (Phase 6) locks
the dataset as the regression baseline before any provisioning happens.

---

## Roles (RACI)

| Role | Owns |
|---|---|
| Operator / Builder | Agent code, prompts, tool surface, eval dataset construction, intake submission |
| Architect | Design review, model/provider choice, autonomy ceiling, isolation boundary |
| Model Risk Management (MRM, 2nd-line) | Assessment execution, metric definition + thresholds, independent eval, finding triage |
| CISO / Security | Policy authoring (.rego), red-team, kill-switch ownership |
| Compliance | Regulatory mapping, control coverage attestation, audit-record sufficiency |
| SRE / Platform | Runtime infra, SDK key issuance, monitoring/alerting, rollback |
| Business Owner | Use-case definition, residual risk acceptance, release sign-off |
| Auditor (3rd-line) | Independent verification before prod release |

No phase below is single-role. The hand-offs are the SOP.

---

## Phase 0 — Intent & Pre-Intake

**Owner:** Business Owner + Operator
**Purpose:** establish the agent should be built before code exists.

**Activities**
- Use-case definition: one paragraph + measurable success criterion in business terms.
- Regulatory forecast: EU AI Act Annex III? FFIEC high-risk model? GLBA NPI? PHI? Drives later control set.
- Build-vs-buy documented.
- Stakeholder sign-off captured.

**Exit:** documented use case · named business owner · named technical owner · expected regulatory exposure · expected autonomy ceiling.
**Artifact:** intake-ready brief.

---

## Phase 1 — Intake & Classification

**Owner:** Operator → Platform (`POST /api/grc/intake/submit`)
**Purpose:** register the system, classify inherent risk, resolve required controls.

**Activities**
1. `classify_inherent_risk()` from intake payload.
2. `AISystem` row persisted with `runtime_status=DESIGN`, `release_decision=NOT_ASSESSED`.
3. Initial `Assessment(PRE_RELEASE, IN_PROGRESS)` with framework versions pinned.
4. `ReleaseGate` per required P0/P1 control, all `NOT_RUN`, P0s blocking.
5. Evidence URLs attached (architecture diagram, IaC, IAM, RAG config, security review).

**Exit:** AISystem exists · risk classified · ≥1 assessment IN_PROGRESS · ≥1 gate per required P0 control.
**Artifacts:** `AISystem`, `Assessment`, `ReleaseGate[]`.

---

## Phase 2 — Design Review

**Owner:** Architect + CISO + MRM
**Purpose:** independent review of design before significant code or eval work.

**Activities**
- Model/provider choice reviewed vs use-case sensitivity.
- Autonomy ceiling locked (`ADVISORY`...`FULLY_AUTONOMOUS`).
- Data-flow review: what enters prompts vs RAG vs tools; where is each redacted.
- Tool inventory: `side_effect`, `authorization_required`, rate limits per tool.
- Isolation boundary: subscription / VPC / egress.
- Kill-switch design: who engages, what it does, how it's tested.

**Exit:** signed design review · autonomy ceiling locked · tool inventory complete · kill-switch path defined.
**Artifact:** design review doc + `AgentTool[]`.

---

## Phase 3 — Runtime Spec: Policy & Controls Authoring

**Owner:** CISO + Compliance + Operator
**Purpose:** the rules that govern this agent at runtime exist, are pinned, and are tested **before** any agent code runs.

**Activities**
- `policies/<system_id>.rego` authored, scoped to the new system_id, covering policy_gate, scrub_pii enforcement, guardrail thresholds.
- Sha256-pin in the policy registry (per `[[rego-files-were-decorative]]`).
- **Negative tests:** known-bad inputs that MUST trigger DENY. Run in CI.
- **Positive tests:** known-good inputs that MUST trigger ALLOW. Catches over-restriction.
- Control-to-runtime map: every required control from Phase 1 maps to a runtime mechanism, or is a documented waiver.
- Compliance attests the control set covers the declared regulatory exposure.

**Exit:** rego shipped · sha256 in registry · ≥1 negative DENY + ≥1 positive ALLOW pass · control-coverage matrix complete.
**Artifacts:** `policies/<system_id>.rego` + policy tests + coverage matrix.

---

## Phase 4 — Behavioral Spec: Eval Skeleton & Success Criteria  ⬅ load-bearing reordering

**Owner:** Operator + MRM (jointly — MRM owns metric definitions; Operator owns dataset construction)
**Purpose:** define what "good output" measurably means **before** writing the agent. The eval is the spec.

**Activities**
- Golden dataset skeleton (`agents/<name>/eval/dataset.jsonl`): start with ≥5 cases representative of the use case. Include at least one happy-path, one edge case, one regulatory-sensitive case, one adversarial.
- Metrics defined per project enum (`domain/models.py:203-210`): GROUNDEDNESS, FACTUALITY, HALLUCINATION, PII_LEAKAGE, PROMPT_INJECTION, TOXICITY, BIAS, ANSWER_RELEVANCE — plus agent-specific business metrics.
- Per-metric thresholds documented (e.g. PII_LEAKAGE ≥ 0.99, GROUNDEDNESS ≥ 0.80). Below threshold = eval-failure = blocking.
- Expected outputs for each case written by Operator + reviewed by MRM. "Worked examples with known expected values" per global CLAUDE.md calibration rule.
- Runner scaffolded (`agents/<name>/eval/run_eval.py`) — pattern from `agents/azure-architect/eval/run_eval.py`. Runs against nothing yet; produces a row with all metrics = null.
- Test harness scaffolded (`tests/test_<name>_eval.py`) — locks the runner contract.

**Exit:** dataset.jsonl committed (≥5 cases) · per-metric thresholds set · runner produces deterministic null-baseline · MRM signs off on the spec.
**Artifacts:** dataset.jsonl · run_eval.py skeleton · metric definitions · test harness.

> **Critical:** Phase 4 produces an executable spec that the agent **cannot yet pass.** That's the point — you've defined what good looks like before building anything to satisfy it.

---

## Phase 5 — V0 Build to Score  ⬅ demoted from build-first SOP

**Owner:** Operator
**Purpose:** minimum code that makes the eval runnable end-to-end. Will fail most cases. That's fine — you now have *baseline numbers*.

**Activities**
- `agents/<name>/` directory created: `agent.py`, `prompts.py`, mocks if needed.
- Decorator chain applied: `policy_gate → scrub_pii → guardrails → body`.
- Wrapper/inner pattern: `_run_<name>_inner` + `run_<name>`.
- `signallayer.write_episode` wired with typed outcome.
- Tools implemented (per Phase 2 inventory).
- Unit tests for tool dispatch + return-dict shape.
- **First eval run executed.** Record the baseline scores in `agents/<name>/eval/baseline.json`. Most metrics likely below threshold.

**Exit:** unit tests green · eval suite runs end-to-end and produces a complete score row (numbers, not nulls) · baseline recorded.
**Artifacts:** agent code · unit tests · baseline.json.

---

## Phase 6 — Iterate Build × Eval; Lock Baseline

**Owner:** Operator (drives iterations) + MRM (gates the lock)
**Purpose:** every prompt/tool/model change runs the eval; eval score gates the change; eval dataset grows as failure modes are discovered.

**Activities**
- Tight loop: change → eval → score delta → keep or revert. No change ships without a score delta.
- New failure modes encountered during iteration become new eval cases. Dataset grows (target: 12-30 cases by end of phase).
- Adversarial cases added: prompt injection variants, jailbreaks, PII smuggling, tool-call manipulation. Red-team-grown.
- Calibration rule enforced (global CLAUDE.md): document what was tightened in prompts and why.
- Cost + latency baselined alongside quality metrics — they're metrics too.
- **Lock criterion:** every metric clears threshold on ≥80% of cases (or domain-specific bar); calibration documented; no recent regression in the last 5 runs.

**Exit:** dataset frozen as regression baseline (version-tagged) · per-metric thresholds met · MRM signs the lock.
**Artifacts:** versioned dataset · iteration changelog · finalized prompts.

> After Phase 6 lock: dataset changes require a new version tag + MRM re-sign. Score regressions block deploy in CI.

---

## Phase 7 — Provisioning

**Owner:** SRE + Operator
**Purpose:** runtime substrate exists with least-privilege scoping.

**Activities**
- SDK key issued for this `system_id` (scoped, rotatable, revocable).
- Agent binding row created (`pinned=true` on a specific agent version for staging).
- Telemetry registered: Langfuse project, AppInsights operation_id, log destination, retention policy.
- Secrets in Key Vault; managed identity for service-to-service.
- IAM role for tool surface — least privilege, explicit deny on side-effect targets.

**Exit:** SDK key in vault · binding row exists · telemetry responds · IAM verified.
**Artifacts:** `AgentBinding` · `SDKKey` · IaC changes.

---

## Phase 8 — Staged (`RuntimeStatus.STAGED`)

**Owner:** Operator + SRE
**Purpose:** end-to-end execution against synthetic + shadow traffic with **all controls + locked eval running continuously**.

**Activities**
- Eval suite runs on every deploy + on schedule. Score must hold above Phase 6 baseline.
- Every chain event verified live: policy ALLOW/DENY behave; scrub redacts; guardrails fire; eval scores within thresholds; memory + audit rows joinable.
- Failure-mode drills: kill switch engages; rate limits enforced; tool-loop turn cap; rego DENY short-circuits as designed.
  - **Runtime-flag attestation drill (systems with rego `required_true_flags` — e.g. `sys-vendor-risk-int-001`):** three-step proof per ADR-004 §5.
    1. (a) PATCH `/api/ai-systems/{id}/runtime-flags` with `dlp_completed=true, network_egress_lock_engaged=true` and a justification. Next agent run → `policy_gate: ALLOW`.
    2. (b) Let TTL elapse (or PATCH a row with `expires_at` in the past). Next agent run → `policy_gate: DENY` with `policy_name=workload_required_flag_not_set`.
    3. (c) PATCH again with valid flags + a fresh `expires_at`. Next agent run → `policy_gate: ALLOW` restored.
    Record run_ids and outcomes for each step in the STAGED run log. Regression for this drill lives at `tests/test_runtime_flags_overlay.py::test_drill_*`.
- Performance + cost baseline confirmed.
- Shadow-traffic comparison: agent's recommendation vs human baseline (where available).

**Exit:** all controls demonstrated active · eval thresholds held over ≥100 runs across ≥5 days · no open CRITICAL/HIGH findings.
**Artifacts:** STAGED run log · finding inventory · shadow comparison report.

---

## Phase 9 — Pre-Release Assessment

**Owner:** MRM + CISO + Compliance + Auditor
**Purpose:** independent attestation that every required control + eval threshold is met before any real-user interaction.

**Activities**
- Formal Assessment (`PRE_RELEASE`) completed by named assessor — NOT the operator. Score computed.
- Adversarial / red-team suite run against staged deployment (OWASP LLM Top 10 + Agentic Top 10). Results recorded as findings.
- Release gates evaluated: every gate transitions to PASSED / FAILED / WAIVED. Waivers require named approver + expiry date.
- Findings triaged: every CRITICAL is REMEDIATED or RISK_ACCEPTED (with named acceptor) before promotion.
- 3rd-line auditor verifies assessment + evals + findings + waivers are evidenced and joinable.

**Exit:** Assessment `COMPLETED` with `release_recommendation` set · zero open CRITICAL · all P0 gates PASSED (no WAIVED on P0).
**Artifacts:** completed Assessment · release recommendation · signed audit log.

---

## Phase 10 — Pilot (`RuntimeStatus.PILOT`, `release_decision=CONDITIONAL_PILOT`)

**Owner:** Operator + Business Owner + SRE
**Purpose:** limited real-traffic exposure with bounded blast radius.

**Activities**
- Traffic ramp: named operators / small user cohort first; widen on metrics.
- HITL enforced on every side-effect action regardless of designed autonomy ceiling — drop only post-pilot.
- **Live-sampled eval:** sample real traffic, score offline against the locked metrics, alert on degradation vs Phase 6 baseline.
- Drift detection vs locked dataset baseline scores.
- Incident response drill: actually engage the kill switch in a controlled exercise.
- Runtime guardrail trips auto-create findings.
- Pilot duration + measurable success criteria defined upfront — not "until we feel ready."

**Exit:** pilot duration met · measured success criteria met · no unresolved CRITICAL · kill-switch exercise passed · drift within tolerance.
**Artifact:** pilot exit memo with measured outcomes vs Phase 0 success criterion.

---

## Phase 11 — Release Decision

**Owner:** Business Owner + CISO + Risk Owner
**Purpose:** explicit, dated, named go/no-go.

**Activities**
- `release_decision` flips from `CONDITIONAL_PILOT` to `APPROVED` / `HOLD` / `REJECT`.
- Conditions of approval documented: autonomy ceiling, HITL scope, monitoring SLIs, rollback procedure, scheduled re-assessment date, eval re-baseline cadence.
- Residual risk explicitly accepted by named risk owner.

**Exit:** signed release decision attached to AISystem row · `residual_risk` updated.
**Artifact:** dated, signed release decision.

---

## Phase 12 — Production (`RuntimeStatus.PRODUCTION`)

**Owner:** Operator (day-to-day) + SRE (runtime) + MRM (periodic re-assessment)
**Purpose:** ongoing operation under continuous assurance.

**Activities (continuous)**
- Runtime monitoring: event stream → Runtime page; alerts on guardrail trips, policy DENYs, eval-score drift, latency/cost anomalies.
- **Live-sampled eval:** sample of real traffic continuously scored against the locked metrics. Drift > threshold → finding.
- **Scheduled full re-eval:** monthly (or per regulatory cadence). Score deltas tracked. Below-baseline → blocking finding.
- Quarterly Assessment (`QUARTERLY`): MRM re-attests. Earlier on incident.
- Findings SLA: CRITICAL 24h · HIGH 7d · MEDIUM 30d.
- Right-to-Forget requests within regulatory window.
- Incident response: post-incident assessment auto-triggered.
- Change control: prompt/model/tool/threshold change → re-eval against locked dataset + potential re-assessment.
- Model-version pinning: track upstream provider model changes; only roll forward after eval re-baselined.

**Exit (decommission):** `DECOMMISSIONED` with data retention + audit-trail preservation per regulatory exposure.

---

## Promotion gates

| From → To | Required artifact | Sign-off |
|---|---|---|
| Pre-intake → Intake | Use case doc + business owner | Business Owner |
| Intake → Design | AISystem row · classified risk · gates created | Operator |
| Design → Runtime Spec | Reviewed design · autonomy ceiling · tool inventory | Architect + CISO |
| Runtime Spec → Behavioral Spec | `policies/<id>.rego` shipped · negative DENY passes · coverage matrix | CISO + Compliance |
| **Behavioral Spec → V0 Build** | **dataset.jsonl (≥5 cases) · per-metric thresholds · MRM sign-off** | **MRM** |
| V0 Build → Iterate | Unit tests green · eval runs end-to-end · baseline scores recorded | Operator |
| Iterate → Provisioning | Dataset frozen (version-tagged) · thresholds met on ≥80% cases | MRM |
| Provisioning → Staged | SDK key · binding · telemetry verified | SRE |
| Staged → Pre-Release | 100+ runs · controls active · no open CRIT · eval held | MRM |
| Pre-Release → Pilot | Assessment COMPLETED · gates PASSED · red-team clean | Auditor |
| Pilot → Release Decision | Pilot exit memo with measured outcomes | Business Owner + CISO |
| Release Decision → Production | Signed release decision with dated conditions | Risk Owner |

---

## Demo-only escape hatch

Agents that explicitly cannot complete all 13 phases (PoCs, internal
demos, throwaway spikes) MUST set `demo_only=True` in their
`AgentSpec` (`agents/_registry.py`). The flag propagates to:

- The `GET /api/agent-runner/agents` registry response (consumers can
  render a "DEMO ONLY — not production-governed" badge).
- The team-portal Agent Runner picker (badge rendered next to the agent
  name; tooltip explains the agent has not been through this SOP).
- The AI Systems page (when implemented in S82+).

`demo_only=True` is honest, not aspirational. Removing the flag requires
executing the missing phases and updating the registry — not the other
way round.

---

## One-line summary

Write the eval as the spec; build the agent to satisfy it; lock the
baseline before any provisioning; promote only with measured outcomes.
Build-first agent development is appropriate for spikes (`demo_only=True`)
and only spikes.
