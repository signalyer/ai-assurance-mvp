# Sessions 55-60 — P0 hardening roadmap

**Trigger:** [Azure Architect POC](./AZURE-ARCHITECT-POC.md) reaches P10 (CISO sign-off + reports).
**Mission:** Close the 5 critical gaps an enterprise procurement / regulator would surface, demo-grade quality, without breaking V2 invariants.

## Order rationale (changed from initial proposal)

The riskiest session is the one that migrates an existing schema. P0 #2 (bias) widens the eval-metric contract from 6 to 7 — every response model surfacing eval scores must accept the new field. Mitigation: do it **last**, after three calm additive sessions have hardened the team's discipline on `extra="forbid"` migrations.

```
S55 — POC retrospective + first gap closure (1 targeted fix)
S56 — P0 #1   Model lifecycle      (cleanest seam, lowest risk)
S57 — P0 #3 + P0 #5   Cost governance + Threat model (bundled small)
S59 — P0 #4   Drift detection      (observational, low risk)
S58 — P0 #2   Bias / fairness      (HIGHEST schema risk, deliberately last)
S60 — Verification + demo script update (no new feature work)
```

S55-S60 is a **tentative** ordering. S55's retrospective may surface a friction point that justifies reshuffling — keep S56-S60 as a hypothesis until S55 confirms.

## Cross-cutting safety rails (apply to every session)

| Invariant | Why | How to protect |
|---|---|---|
| Decorator chain order | S52 hard rule | Hook new features after `@evaluate`, never inline |
| `data_source` field | S52 architectural invariant | Every new domain entity inherits `data_source: Literal["seed","real"] = "seed"` |
| Pydantic `extra="forbid"` | S52 rule | New fields always have defaults |
| Existing release gate IDs | Backward compat | New gates use unprefixed unique IDs; tier-scoped activation |
| JSONL-first storage | No new PG dep for demo | New stores follow `storage.py` pattern |
| OPA fail-closed | S02 rule | New policy categories include `default deny := true` |
| 6-metric eval contract | API consumers depend on it | Add metrics additively; never rename the original 6 |

---

## S55 · POC retrospective + first gap closure (~1 session)

**Inputs**
- `agents/azure-architect/POC-RETROSPECTIVE.md` from P10 closeout — categorized friction points (platform / agent / docs).

**Activities**
1. Triage retrospective into a backlog file at the repo root: `BACKLOG-FROM-POC.md`. Bucket each item: "ship in S56-S60", "defer", "rejected, here's why".
2. Pick the **single most painful** platform-side friction point — typically a UX gap, missing affordance, or an unexpected error path.
3. Ship the fix in the same session.
4. Update [memory/project_v1_to_v2_real_data_arc.md](../../memory/project_v1_to_v2_real_data_arc.md) to declare the arc closed (S52-S54 done, POC closed under V2).

**Common candidates for the targeted fix** (don't pick all — pick one)
- A missing field on a list response that the POC needed twice
- A confusing empty-state copy that didn't match real-mode reality
- An eval suite that succeeded but didn't surface a useful trend
- A right-to-forget cascade that left orphaned data in one tier
- An OPA policy upload UI that needed a 5-step workaround

**Deliverables**
`BACKLOG-FROM-POC.md` committed; one targeted fix shipped + smoke probe added (probe 9 reserved for cost in S57; this is the existing 1-8 augmented or a new module).

**Risk to V2**
Depends on the chosen fix. Time-box: if the fix touches more than 3 files, defer and pick something smaller.

---

## S56 · P0 #1 — Model lifecycle management

**MVP scope**: registry + gate + UI. **Not** real shadow-deploy.

### Files
- `domain/model_versions.py` — NEW. `ModelPin` Pydantic v2 model + `pin_model`, `list_pins`, `validate_pin`, `get_current_pin`. JSONL store `data/model_pins.jsonl`.
- `api/model_versions.py` — NEW. 4 endpoints under `/api/model-pins`:
  - `POST /` body `{ai_system_id, model_id}` → 201 with pin record
  - `GET /by-system/{ai_system_id}` → list of all pins for a system, current first
  - `POST /{pin_id}/validate` → triggers the existing eval suite, stamps `last_validated_at` + `last_eval_run_id` on success
  - `GET /{pin_id}` → single pin detail
- [api/evaluate.py](../../api/evaluate.py) or wherever the eval-suite endpoint lives — add 3-line stamp call to update current pin's `last_validated_at`.
- [domain/release_gate_engine.py](../../domain/release_gate_engine.py) — add gate `G_MODEL_PINNED`:
  - Condition: current pin's `last_validated_at` within last 30 days
  - Risk tier filter: HIGH or CRITICAL only (use existing risk-tier mechanism)
  - Severity: blocking
- Team Portal: `team-portal/src/pages/model-versions/ModelVersionsPage.tsx` — NEW. Route `/model-versions/:system_id`. Timeline of pin history, "Pin new model" action, "Run validation" button.
- Sidebar: add to [team-portal/src/shared/components/Sidebar.tsx](../../team-portal/src/shared/components/Sidebar.tsx) under "Model Versions" (between Memory and SDK Quickstart).

### Tests
- `tests/test_model_versions.py` — pin/validate/list/current/gate integration

### Acceptance
Pin a model → gate AMBER (no validation) → run eval suite → gate GREEN.

### Risk to V2
**Low.** Purely additive; no existing endpoint signatures change.

### Smoke probe 9
`POST /api/model-pins` for the current system → `POST /{pin_id}/validate` → confirm gate transitions to GREEN within 30s.

---

## S57 · P0 #3 + P0 #5 — Cost governance + Threat model

Bundle one medium-effort with one half-day to fill a session.

### Files for P0 #3 (Cost)

- `observability/cost_meter.py` — NEW.
  - `ANTHROPIC_RATES` constant with per-million-token rates per model
  - `record_call(workload_id, system_id, model_id, prompt_tokens, completion_tokens) -> CostRecord`
  - Appends to `data/cost_ledger.jsonl`
- [tracer.py](../../tracer.py) — modify `_trace_call_impl` to call `record_call` after a successful Anthropic call. Wrap in `try/except` (must not raise inside tracer).
- `api/cost.py` — NEW. 3 endpoints:
  - `GET /api/cost/by-system?from=&to=` → aggregated USD per system
  - `GET /api/cost/by-workload?system_id=` → per-workload breakdown
  - `GET /api/cost/by-model?from=&to=` → per-model breakdown
- Intake form (Step 1): add `daily_budget_usd: float | None = None`, `monthly_budget_usd: float | None = None`. Default None = no enforcement.
- New alert in [deploy/bicep/alerts.bicep](../../deploy/bicep/alerts.bicep): #9 `cost-budget-exceeded` — hourly KQL on cost_ledger aggregations vs per-system budget.
- Team Portal Analytics page: new section "Cost"; CISO Console: same.

### Files for P0 #5 (Threat model)

- Intake form (Step 5): add `threat_model_url: str | None = None`. Server-side validation in [api/intake.py](../../api/intake.py): required when inherent risk is HIGH or CRITICAL.
- [domain/release_gate_engine.py](../../domain/release_gate_engine.py) — add gate `G_THREAT_MODEL`:
  - Condition: `threat_model_url` is non-null
  - Risk tier filter: HIGH or CRITICAL only
  - Severity: blocking
- Optional: `api/threat_models.py` — NEW. `POST /api/threat-models/generate` body `{ai_system_id}` → uses Claude Opus with intake answers + STRIDE prompt template → returns Markdown STRIDE doc as a string. User copies to Confluence, pastes URL back.
- AI Systems detail page: new "Threat model" tile with "View" / "Generate draft" buttons.

### Acceptance
Cost: ledger rows appear within 1 minute of an Anthropic call; analytics page shows non-zero numbers.
Threat model: intake refuses to submit a HIGH-risk system without the URL.

### Risk to V2
**Low-medium.** Tracer hook is the delicate part — wrap defensively. New intake fields default to safe values.

### Smoke probes 10 + 11
10: trigger an Anthropic call → `GET /api/cost/by-workload` returns non-zero.
11: attempt intake submission with HIGH risk + no threat_model_url → expect 422 with the right error.

---

## S58 · P0 #2 — Bias / fairness

**Highest schema risk session — deliberately scheduled last.**

### Files
- `evaluator/bias_metric.py` — NEW. Paired-counterfactual evaluator:
  - Input: prompt template with demographic anchors
  - Substitute each (anchor, swap-pair) from `evaluator/data/swap_table.json`
  - Run all N+1 variants through the agent
  - Compute `bias_score = 1.0 - mean(divergence(base, swapped))` using char-level similarity (simplest cheap metric)
- `evaluator/data/swap_table.json` — NEW. Hardcoded with disclaimer in `_meta` field: "Demo swap table. Not exhaustive. Production deployment requires labeled demographic data."
  - Names: Western, Arab, East Asian, Indian, Hispanic, African (3 each)
  - Pronouns: he/him, she/her, they/them
  - Geographic anchors: US, EU, MENA, APAC
- [domain/evaluator.py](../../domain/evaluator.py) — add `bias_score: float = 1.0` to the result schema. **Crucial:** default `1.0` so existing systems aren't suddenly "missing" the field.
- **Audit every response model that surfaces eval scores** for the new field. Specifically:
  - [api/evaluate.py](../../api/evaluate.py)
  - [api/grc.py](../../api/grc.py) (if it exposes eval rollups)
  - SPA types: `team-portal/src/pages/evals/types.ts`, `ciso-console/src/pages/findings/types.ts`
- [domain/release_gate_engine.py](../../domain/release_gate_engine.py) — add gate `G_BIAS_PARITY`:
  - Condition: latest eval run has `bias_score >= 0.85`
  - Risk tier filter: HIGH or CRITICAL only
  - Severity: blocking
- New SPA card on Evals page: "Demographic counterfactuals" panel showing per-attribute scores + drill-in to failing pairs.

### Pre-flight (do this first)
1. Grep for every consumer of `EvaluationResult` (or whatever the result type is called) — confirm extra="forbid" boundaries.
2. Add the new field to the canonical result model with the default.
3. Run full test suite; expect green.
4. Only then add the evaluator + gate.

### Acceptance
Counterfactual eval runs on a test agent with deliberately biased prompts; score < 0.5; gate AMBER (or RED if HIGH risk); fix prompt, re-run, gate GREEN.

### Risk to V2
**Medium.** The eval-result schema is the widest surface in the codebase. Mitigation above.

### Smoke probe 12
Run an eval suite that includes the new metric; assert response has `bias_score` field with a non-negative value.

---

## S59 · P0 #4 — Drift detection

**Observational only, low risk.**

### Files
- `domain/drift_monitor.py` — NEW.
  - `compute_snapshot(system_id, window_hours=24) -> DriftSnapshot`
  - Reads last-N traces from `data/events.jsonl`
  - Computes: mean prompt length, mean response length, top-20 token frequencies, top-10 prompt-prefix patterns
  - Compares against baseline (captured at first eval-suite run, stored in `data/drift_baselines.jsonl`)
  - Returns `drift_score: float ∈ [0, 1]` via cosine distance between token-freq vectors
- `data/drift_baselines.jsonl` — NEW. One baseline per system.
- `data/drift_snapshots.jsonl` — NEW. One row per (system, day).
- `api/drift.py` — NEW. `POST /api/drift/recompute?system_id=` triggers a new snapshot. `GET /api/drift/snapshots?system_id=` returns trend data. `POST /api/drift/rebaseline?system_id=` resets baseline (manual operation, audit-logged).
- Cron mechanism: For MVP demo, just invoke `POST /api/drift/recompute` from a daily cron in [deploy/smoke_*.ps1](../../deploy/) or via Azure Functions Timer if available.
- New alert in [deploy/bicep/alerts.bicep](../../deploy/bicep/alerts.bicep): #10 `drift-detected` — when latest snapshot crosses RED threshold (>0.30).
- Team Portal Evals page: new card "Production drift" with GREEN/AMBER/RED indicator + 30-day sparkline.
- Drift findings auto-emitted into CISO Console findings inbox when RED.

### Acceptance
Capture baseline; run a deliberately-changed agent (e.g. swap the system prompt) and re-run `recompute`; expect AMBER or RED with the right tokens flagged.

### Risk to V2
**Low.** Pure observation. Reads from existing event store.

### Smoke probe 13
Capture baseline; recompute; assert `drift_score` field present and ≥ 0.

---

## S60 · Verification + demo script update

**No new feature work.**

### Activities
1. Add smoke probes 9-13 to both [smoke_gov.ps1](../../deploy/smoke_gov.ps1) + [smoke_portal.ps1](../../deploy/smoke_portal.ps1) (probes 9 = cost, 10 = drift, 11 = threat-model intake, 12 = bias eval, 13 = drift recompute).
2. Re-render [docs/architecture/azure-architecture.svg](../../docs/architecture/azure-architecture.svg) — add cost meter (in engine box), drift monitor (in observability band), model pin registry (between intake and engine). Use Edge headless to refresh the PNG.
3. Update [ARCHITECTURE.md](../../ARCHITECTURE.md) with a single "Sessions 55-60 — P0 hardening" closing section.
4. Write `docs/demo-scripts/v2-with-p0-hardening.md` — the Phase 1-10 walkthrough with the 5 new capabilities woven in (cost dashboard during P4, drift detection in P6, model pin in P9, bias eval in P6, threat model in P5).
5. Final smoke run: 13/13 PASS against prod with all 1Password creds available.

### Acceptance
- All 5 P0 items shipped + visible in portal
- Smoke 13/13 GREEN
- Demo script updated
- Architecture diagram refreshed

### Risk to V2
**Zero.** No code changes.

---

## What "demo-grade" means honestly

After S60, the platform answers the top 5 procurement questions credibly:

| Question | Answer it can now give | Honest limit |
|---|---|---|
| "How do you handle model upgrades?" | Model pin registry + validation gate | Not real shadow deploy |
| "What about cost runaway?" | Per-system budgets + alert | Not real bills; estimates only |
| "Bias?" | Counterfactual eval + EU AI Act mapping | Synthetic, not population fairness |
| "Production drift?" | Daily snapshot vs baseline | Lexical only, not semantic |
| "Threat model?" | Required for HIGH/CRITICAL + Claude-drafted | Just a URL, not a structured entity |

Each "honest limit" is the right next investment for a real production-tier deployment — but the demo answers the question.

## Total effort

5 sessions of feature work + 1 verification session = ~6 sessions / 6 active days. Calendar duration depending on cadence: 2-4 weeks.

## Decision points along the way

- **After S55**: Has retrospective surfaced anything bigger than the planned P0 items? If yes, reshuffle.
- **After S57**: Cost ledger live — is the actual telemetry useful, or do we need to enrich it? Possible mini-session to fix.
- **Before S58**: Confirm eval-result schema audit complete before touching the metric contract.
- **After S60**: Decide whether to invest in P1-tier items (vendor risk, DPIA, incident lifecycle, SBOM, multi-env promotion) or call the demo phase complete and shift to a different track.
