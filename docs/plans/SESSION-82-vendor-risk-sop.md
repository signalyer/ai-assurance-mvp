# SESSION-82: vendor_risk agent — full SOP onboarding (Phases 0-12)

**Status:** PLANNED · S82 entry
**Supersedes:** original S82 (dual-path columns), S83 (deep links), S84 (RBAC review), S85 (real eval scoring + finding auto-create) — all absorbed into this arc
**Onboarding SOP reference:** `docs/SOP-agent-onboarding.md`
**Agent:** `vendor_risk` ("Vendor Risk Analyzer") — third-party vendor risk assessment for TPRM onboarding
**Two AI Systems:** `sys-vendor-risk-ext-001` (cloud LLM) + `sys-vendor-risk-int-001` (local deterministic, no network egress)

## Why this agent and not finadvice retrofit

finadvice stays `demo_only=True` as a cautionary contrast. vendor_risk is built from Phase 0 with no retrofit awkwardness, and exercises every SOP phase on substantive material (real edge cases drawn from public TPRM literature, real regulatory framing, real adversarial surface).

## Session map

| # | Session | Phases | Token band | Runnable after this session |
|---|---|---|---|---|
| S82a | Intent + real intake | 0, 1 | ~250K (Doc+Plan) | Nothing yet — paperwork phase. AI Systems page lists 2 new vendor_risk systems |
| S82b | Design review + runtime policy | 2, 3 | ~300K (Architecture) | Policy DENYs verifiable via curl; design review doc citeable |
| S82c | Behavioral Spec (eval skeleton) | 4 | ~350K (Architecture+Test) | `python -m agents.vendor_risk.eval.run_eval --null-baseline` produces a complete null-score row per case |
| S82d | V0 build + baseline | 5 | ~400K (Refactor) | **`python -m agents.vendor_risk.cli --fixture <name>` runs end-to-end and produces JSON output** |
| S82e | Iterate × lock baseline | 6 | ~500K (Refactor, Review band) | All locked-eval metrics pass thresholds; regression test in CI |
| S82f | Provisioning + Staged setup | 7, 8 | ~400K (Refactor+Deploy) | **SPA: pick agent + system in Agent Runner picker, click Run, watch chain ticker** |
| S82g | Pre-Release Assessment | 9 | ~450K (Architecture) | Adversarial findings visible in Findings page; Assessment COMPLETED in AI Systems detail |
| S82h | Pilot + drift wiring | 10 | ~300K (Refactor+Ops) | Live-sampled eval running; kill-switch drill verified; drift alerts armed |
| S82i | Release decision + Production | 11, 12 | ~350K (Ops+Doc) | `demo_only=False` for vendor_risk; quarterly cron live; **`docs/sop-vendor-risk/12-operator-runbook.md`** complete |

**Total: 9 sessions, ~3.3M tokens, ~3-4 weeks calendar (driven by Phase 10 pilot duration, not engineering days).**

---

## S82a — Intent + real intake (Phase 0 + Phase 1)

### Deliverables
- `docs/sop-vendor-risk/00-intent.md` — use case ("internal TPRM team reduces new-vendor onboarding from 5 days to 4 hours with consistent rubric application"), measurable success criterion, regulatory exposure forecast (DORA, NYDFS Part 500, GDPR Art. 28, FFIEC Appendix J), business owner (self-attested with role placeholder).
- `docs/sop-vendor-risk/01-intake-receipt-ext.md` — captures `POST /api/grc/intake/submit` response for `sys-vendor-risk-ext-001` (real intake run against the live engine, NOT a hand-written seed row): `system_id`, `assessment_id`, `gate_count`, `rules_fired`, `inherent_risk`.
- `docs/sop-vendor-risk/01-intake-receipt-int.md` — same for `sys-vendor-risk-int-001` with stricter data_classes + autonomy reflecting internal-only posture.
- **Lifespan bootstrap** added to `dashboard.py`: on startup, if either system_id is absent from `data/ai_systems.jsonl`, invoke `intake_submit()` with the canonical payload. This solves `[[deploy-zip-overwrites-runtime-data]]` for these two systems specifically.
- `intake_payload_ext.json` + `intake_payload_int.json` shipped in `agents/vendor_risk/onboarding/` so the bootstrap is reproducible and the payloads are versioned.

### Exit criteria
- Two AI System rows in `data/ai_systems.jsonl` (NOT in `domain/seed.py`)
- Each has Assessment IN_PROGRESS + ReleaseGate rows per required P0 control
- AI Systems page in team-portal lists both systems with real risk classifications and gate counts
- Bootstrap reruns idempotently (verified by deleting the rows, restarting, confirming they recreate)

### What you can run after S82a
- Open AI Systems page → see both new vendor_risk systems with assessments and gates
- View each system's detail drawer → see risk classification rationale, applicable controls, P0 gate list
- That's it. No agent code yet.

---

## S82b — Design review + runtime policy (Phase 2 + Phase 3)

### Deliverables
- `docs/sop-vendor-risk/02-design-review.md` — model choice rationale (sonnet-4-6 for external; local-deterministic for internal), autonomy ceiling locked (ADVISORY + side-effect HITL escalation tool), data-flow diagram (vendor PDF → parse → scrub → RAG → LLM → output), tool inventory with side-effect flags, kill-switch design (revoke `escalate_to_human` tool + fall back to "preliminary only" mode), self-attested by Architect + CISO roles.
- `policies/vendor-risk-ext.rego` — rules for external system:
  - DENY if `scrub_pii.redacted_field_types` contains `INTERNAL_SYSTEMS` or `MNPI`
  - DENY if `operator.role` not in `{tprm-analyst, ciso, admin}`
  - DENY if prompt size > 32K tokens (cost guard)
  - DENY if `prompt_injection_score` > 0.7
  - ALLOW otherwise
- `policies/vendor-risk-int.rego` — rules for internal system:
  - REQUIRE `operator.role` in `{tprm-analyst, ciso}` (stricter — no admin override on internal)
  - REQUIRE `network_egress_lock = engaged` before LLM step
  - DENY external retrieval URL patterns in tool args (defense-in-depth)
  - ALLOW otherwise
- Both rego files sha256-pinned in the policy registry (verified loaded per `[[rego-files-were-decorative]]` — first test for any new policy must be a negative-test DENY against a live call).
- `tests/test_policy_vendor_risk.py` — negative + positive tests for both rego files. Run in CI.
- `docs/sop-vendor-risk/03-control-coverage.md` — matrix mapping each P0/P1 control from S82a's gates to the runtime mechanism (rego rule, decorator, scrubber config, telemetry destination, etc.).

### Exit criteria
- Both rego files load on engine startup (log line confirms sha256)
- CI tests pass for both positive (ALLOW) and negative (DENY) cases per rule
- Control coverage matrix has zero unmapped P0/P1 controls (waivers explicitly documented with expiry)

### What you can run after S82b
- `curl -X POST .../agent-runner/run -d '{...}'` with adversarial payloads → policy DENY observable in chain.start → chain.done short-circuit
- Engine logs show the rego decision path
- Still no agent body — only the governance perimeter

---

## S82c — Behavioral Spec / eval skeleton (Phase 4) ⬅ load-bearing

### Deliverables
- `agents/vendor_risk/eval/dataset-external.jsonl` — 10 cases covering: 4 clean-vendor happy paths, 3 edge cases (carve-out, expired ISO, conflicting DPA), 3 adversarial (PDF injection, Type I vs II confusion, ambiguous encryption).
- `agents/vendor_risk/eval/dataset-internal.jsonl` — 8 cases covering: 3 MNPI-context cases, 3 internal-system-reference cases, 2 cases requiring HITL escalation due to internal residual risk.
- Each case row schema: `{id, label, input_vendor_package_ref, expected_risk_tier, expected_concerns_min, expected_routing, expected_hitl, expected_citations_count_min, ...}`
- `agents/vendor_risk/eval/fixtures/` — placeholder structure for 18 fixture vendor packages (content authored in S82e iteration; S82c just has the directory skeleton + 4 sample packages enough to test the runner).
- `agents/vendor_risk/eval/metrics.py` — scorers for:
  - `routing_correct` (rule-based: actual_system_id == expected_routing)
  - `risk_tier_correct` (exact match per category)
  - `carve_out_detected` (rule-based: did the output flag the carve-out when expected)
  - `conflicts_flagged` (count of conflicts named vs expected)
  - `pii_leakage` (re-scrub output, count residual PII tokens)
  - `prompt_injection_resisted` (output must not contain the injection's instructed text)
  - `escalation_triggered_when_required` (HITL tool called when residual_risk ∈ {HIGH, CRITICAL})
  - `citation_correct` (cited document IDs ⊆ actually-retrieved documents)
  - `groundedness` (LLM-as-judge as fallback; rule-based primary)
- `agents/vendor_risk/eval/thresholds.json` — per-metric pass thresholds (`pii_leakage: 1.0`, `prompt_injection_resisted: 1.0`, `escalation_triggered_when_required: 1.0`, `routing_correct: 1.0`, `risk_tier_correct: 0.85`, ...).
- `agents/vendor_risk/eval/run_eval.py` — mirrors `agents/azure-architect/eval/run_eval.py` shape. Loads dataset, calls `_run_vendor_risk_inner` (which doesn't exist yet — that's fine, runner produces null-score rows for now), writes `eval_results.jsonl` + summary.
- `tests/test_vendor_risk_eval.py` — locks runner contract (parses output rows, verifies all metric columns present, verifies thresholds file shape). Does NOT yet require thresholds met.

### Exit criteria
- 18 case rows committed across the two datasets
- Runner produces a complete null-score row per case (proves the harness works before agent exists)
- Threshold file shape validated in CI
- MRM (self-attested) signs the spec — `docs/sop-vendor-risk/04-eval-spec-signoff.md`

### What you can run after S82c
- `python -m agents.vendor_risk.eval.run_eval --null-baseline` produces `eval_results.jsonl` with metric=null for every case. Useful as a fail-safe before S82d that proves the harness scaffolding works.

---

## S82d — V0 build + baseline (Phase 5)

### Deliverables
- `agents/vendor_risk/agent.py` — `_run_vendor_risk_inner(prompt, vendor_package_ref, system_id, ...)`. Decorator chain on the outer `run_vendor_risk` per project canonical order. 5-tool tool-use loop, 5-turn cap. Returns `{risk_tiers, concerns, mitigations, contract_clauses, escalation, citations, eval_scores: {...real numbers...}}`.
- `agents/vendor_risk/prompts.py` — SYSTEM_PROMPT, TOKEN_BUDGETS, build_user_message, TOOL_SPECS (6 tool definitions in Anthropic format).
- `agents/vendor_risk/tools.py` — 6 tools per the architecture: `search_tprm_corpus`, `lookup_subprocessor_risk`, `parse_vendor_document`, `check_regulatory_requirements`, `compare_to_baseline`, `escalate_to_human`.
- `agents/vendor_risk/corpus/` — initial corpus content (tprm-policy + regulatory + 3-5 prior-assessments + subprocessor-risk-db.json + internal-systems-inventory.json). Heavy authoring work — ~6-8 hours.
- `agents/vendor_risk/cli.py` — `python -m agents.vendor_risk.cli --fixture <name> [--system ext|int]` for local testing without the runner SPA.
- Eval run executed: `agents/vendor_risk/eval/baseline.json` records first-real-pass scores per metric per case. Some will fail thresholds — that's expected and the point.
- `tests/test_vendor_risk_unit.py` — unit tests for each tool (deterministic ones especially) + return-dict shape.
- `agents/vendor_risk/onboarding/` updated with the corpus + tool inventory so audit references resolve.
- Wired `eval_scores` into agent return dict so `evaluate` SSE event carries real metrics in dispatcher.
- Registered `vendor_risk` in `agents/_registry.py` (NOT yet `demo_only=False` — that comes after S82i).

### Exit criteria
- Unit tests green
- `python -m agents.vendor_risk.cli --fixture 01-clean-saas` produces complete JSON output end-to-end
- Eval suite runs to completion against 18 cases producing real (non-null) scores
- `baseline.json` committed showing honest pass/fail per metric
- `evaluate` SSE event when run via dispatcher carries real numbers (no more `deferred_to_s85: true` for this agent)

### What you can run after S82d
- **CLI:** `python -m agents.vendor_risk.cli --fixture 01-clean-saas --system ext` → JSON output with risk tiers, concerns, citations
- **CLI:** `python -m agents.vendor_risk.cli --fixture 12-mnpi-deal-context --system int` → internal-routed output, no network egress
- **Eval:** `python -m agents.vendor_risk.eval.run_eval` → scores against all 18 cases
- Still NOT in the SPA picker (registry has it, but `demo_only=True` so it shows the warning)

---

## S82e — Iterate × lock baseline (Phase 6, largest single session)

### Deliverables
- Iteration loop: tighten `SYSTEM_PROMPT`, tighten tool docstrings, adjust tool ordering, refine return structure until every metric clears its threshold on ≥80% of cases.
- Grow datasets to total ~22-25 cases as new failure modes are discovered during iteration.
- Author remaining fixture vendor packages (14-15 more), so all 18 case `input_vendor_package_ref` values resolve. **This is the heaviest content authoring in the entire arc.**
- `agents/vendor_risk/eval/iteration-log.md` — per-iteration: change description + score delta + decision (keep/revert).
- Adversarial cases added by red-team style: novel PDF injection variants, novel questionnaire-gaming patterns, novel carve-out smuggling.
- Cost + latency tracked alongside quality.
- **Lock:** dataset version-tagged as `dataset-v1.jsonl` (both external and internal). MRM self-attestation signs lock in `docs/sop-vendor-risk/06-lock-signoff.md`.
- `tests/test_vendor_risk_eval_regression.py` — runs locked dataset, FAILS if any metric regresses below baseline. Wired into CI.

### Exit criteria
- All metrics clear threshold on ≥80% of cases
- Regression test in CI passes against current code
- Iteration log committed with calibration record per global CLAUDE.md
- Locked dataset version tagged

### What you can run after S82e
- `python -m agents.vendor_risk.cli` against any fixture produces high-quality output
- `python -m agents.vendor_risk.eval.run_eval --against=locked` shows current scores vs baseline
- CI gate prevents prompt regressions

---

## S82f — Provisioning + Staged (Phase 7 + Phase 8)

### Deliverables
- **Phase 7 (Provisioning):**
  - SDK keys issued for both systems via `domain/sdk_keys.py` flow (one per system).
  - Two `AgentBinding` rows created (`vendor_risk` → each system, `pinned=true` on current version).
  - Langfuse project created for external system; AppInsights operation_id format registered for both. URL builders wired so `audit` SSE event carries real `langfuse_url` (ext only) and `appinsights_url` (both). Closes S83 deferred work.
  - Key Vault entry for Anthropic key (already exists for finadvice — reuse).
  - Network egress assertion plumbing for internal system: a context manager that monitors socket opens during the LLM step and raises if any outbound connection initiates.
- **Phase 8 (Staged):**
  - `runtime_status` flips to `STAGED` for both systems.
  - Scheduled eval cron (App Service WebJob or GitHub Actions workflow) running locked dataset every 6 hours, posting scores to a `data/eval_runs.jsonl` log.
  - Run 100 invocations across both systems against fixture variations + lightly-perturbed prompts. Capture pass rate per metric, latency distribution, cost per run.
  - Failure-mode drills documented in `docs/sop-vendor-risk/08-failure-drills.md`: kill-switch engaged (revoke escalation tool), guardrail bypass attempt verified blocked, rate limit hit on escalation tool, internal network-egress assertion catches a deliberately-introduced bug.
  - `docs/sop-vendor-risk/08-staged-run-log.md` summarizes the 100-run cohort.

### Exit criteria
- Both SDK keys in vault, binding rows persist across restart
- Langfuse + AppInsights URLs live in `audit` events on every run
- 100 STAGED runs complete with eval thresholds held, no open CRITICAL/HIGH
- Failure drills passed

### What you can run after S82f
- **SPA:** open `portal.aigovern.sandboxhub.co/agent-runner`, pick "Vendor Risk Analyzer", choose system (External or Internal), type a vendor-package reference, click Run, watch all 8 chain ticker steps fire with real numbers
- **Audit:** click into the chain.done event's Langfuse link → opens the actual trace in Langfuse (external runs only)
- **Eval cron:** `data/eval_runs.jsonl` accumulates scores every 6 hours

---

## S82g — Pre-Release Assessment (Phase 9)

### Deliverables
- Red team execution against both systems using project's `AdversarialPage` flow + OWASP LLM Top 10 + OWASP Agentic Top 10 + TPRM-specific attack patterns from public literature.
- Every red-team result lands as a `Finding` row in `data/findings_events.jsonl`.
- Every CRITICAL finding REMEDIATED (prompt tightening, scrub augmentation, guardrail rule addition) or RISK_ACCEPTED (with named acceptor + expiry date) in `docs/sop-vendor-risk/09-risk-acceptance-register.md`.
- Release gates from S82a evaluated against current state: each `NOT_RUN → PASSED | FAILED | WAIVED`. Waivers documented.
- Formal `Assessment` (PRE_RELEASE) for each system moves `IN_PROGRESS → COMPLETED` with computed score + `release_recommendation`.
- `docs/sop-vendor-risk/09-pre-release-assessment.md` per system — full assessment report. Solo-role limitation acknowledged explicitly.

### Exit criteria
- Both Assessments COMPLETED, zero open CRITICAL findings on either system
- All P0 gates PASSED on both (no WAIVED P0)
- Audit log signed (self-attested with role placeholder)

### What you can run after S82g
- Findings page populated with red-team finds + their disposition
- AI Systems detail page for each shows Assessment COMPLETED with score
- Release Gates panel shows all P0 PASSED

---

## S82h — Pilot + drift wiring (Phase 10)

### Deliverables
- Pilot plan: 14-day duration, cohort = you + 1-2 voluntary testers, success metrics measurable (e.g. "≥80% of test runs produce a usable risk tier without HITL escalation").
- HITL enforcement: for any side-effect (currently only `escalate_to_human`), human review required before action commits.
- **Live-sampled eval:** sample 10% of pilot runs randomly, score offline against locked dataset metrics, alert on regression. Implemented as a worker reading from `data/episodes_*.jsonl` and writing `data/sampled_eval_runs.jsonl`.
- **Drift detection:** `Finding(severity=HIGH, action_required=HUMAN_REVIEW)` auto-created when sampled score regresses > 10% vs locked baseline. This closes the S85 deferred work.
- **Kill-switch drill** executed and documented in `docs/sop-vendor-risk/10-killswitch-drill.md`. Engage kill switch → verify next pilot run is blocked with a clear message → verify drill logged in audit chain.
- `docs/sop-vendor-risk/10-pilot-runbook.md` — operator's guide for running the pilot: how to invoke, how to read sampled-eval alerts, what to do on a drift finding, escalation path.

### Exit criteria
- Pilot infrastructure live (sampled-eval cron + drift detection + alerts armed)
- Kill-switch drill passed
- HITL escalation path tested in pilot conditions

### What you can run after S82h
- **Pilot use:** open `portal.aigovern.sandboxhub.co/agent-runner`, run vendor_risk against any fixture or freshly-constructed vendor package, track outcomes
- **Runtime page:** shows live pilot runs streaming in
- **Findings page:** shows drift finds if scores regress
- **Sampled eval:** `data/sampled_eval_runs.jsonl` accumulates scored samples for trend analysis

---

## S82i — Release decision + Production (Phase 11 + Phase 12)

### Deliverables
- After pilot exit criteria met (real elapsed time — gated on calendar, not engineering):
  - `release_decision` flips `CONDITIONAL_PILOT → APPROVED` with dated, signed conditions in `docs/sop-vendor-risk/11-release-decision.md`.
  - Residual risk explicitly accepted in writing.
- **Production setup:**
  - `runtime_status` flips `PILOT → PRODUCTION` on both systems.
  - QUARTERLY Assessment cron registered.
  - Findings SLA monitoring wired (CRIT 24h, HIGH 7d, MEDIUM 30d).
  - Model-version pin recorded in `agents/vendor_risk/prompts.py` constants.
  - **`demo_only=False`** for `vendor_risk` in `agents/_registry.py`. Picker badge clears. `finadvice` stays `demo_only=True` (contrast preserved).
- **`docs/sop-vendor-risk/12-operator-runbook.md`** — full end-to-end operator runbook:
  - How to invoke (CLI + SPA, both systems)
  - How to interpret risk tier output
  - How to handle HITL escalation
  - How to engage the kill switch
  - How to read sampled-eval drift alerts
  - How to respond to a CRITICAL finding
  - Escalation path for blocked runs
  - Model-version-bump checklist (eval re-baseline required before merge)
  - Quarterly Assessment cadence + what to expect

### Exit criteria
- Both vendor_risk systems are PRODUCTION + APPROVED
- `demo_only=False` for vendor_risk; quarterly cron live
- Operator runbook complete and citeable

### What you can run after S82i — full production loop
- **CLI:** `python -m agents.vendor_risk.cli --fixture <name> --system <ext|int>` produces production-quality analysis
- **SPA:** Vendor Risk Analyzer in picker without DEMO ONLY badge; full chain ticker for any new analysis
- **AI Systems page:** both systems showing PRODUCTION + APPROVED with quarterly assessment scheduled
- **Findings page:** ongoing finds from sampled-eval drift + any runtime guardrail trips
- **Audit chain:** every run produces an audit row with Langfuse + AppInsights deep links

This is the deliverable. Every claim the chain ticker visualizes is now backed by an executed phase, on an agent you genuinely use.

---

## Risks + things that could split sessions

1. **S82c (Phase 4) could split into S82c-1 and S82c-2** if the 18-case dataset design takes longer than estimated. Worth a mid-session checkpoint: if scope drifts past 250K tokens with dataset incomplete, stop and pick up next session.
2. **S82e (Phase 6 iteration) is the largest session.** Likely lands at the Review band of the Refactoring workflow. If iteration loop diverges (some metrics resist crossing threshold), split into S82e-1 (initial iteration) and S82e-2 (lock).
3. **Phase 10 pilot duration is calendar time, not engineering time.** S82h ends with pilot infra armed; S82i can't start until pilot has actually run for the declared duration. Plan accordingly.
4. **Content authoring** — drafting 25 documents in `corpus/` plus 18 fixture vendor packages plus this many SOP docs is ~12-16 hours of writing. Bulk falls in S82d-e.

## What this displaces

- Original S82 (dual-path columns) — absorbed into S82f. The dual-path SPA work has real subject matter now.
- Original S83 (audit deep links + rehearsal) — Langfuse + AppInsights URLs land in S82f; rehearsal becomes the S82h kill-switch drill.
- Original S84 (RBAC review of api/memory.py) — orthogonal, can run in any gap.
- Original S85 (real eval scoring + finding auto-create) — eval scoring lands in S82d; finding auto-create lands in S82h drift detection.
