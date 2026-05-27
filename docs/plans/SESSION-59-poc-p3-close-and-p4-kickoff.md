# SESSION-59 — POC P3 close + P4 agent core kickoff

**Status entering S59:** S57 closed STEP 0 of the original S57 plan (CISO Console SPA deployed; F-018 RegoBundlesPanel live end-to-end after one-line router-prefix fix). STEPS 1-4 of the S57 plan carry forward to S59 unchanged in scope. S57a shipped an offline P6 eval harness in parallel; that arc has its own plan at [SESSION-58-azure-architect-eval-calibration.md](SESSION-58-azure-architect-eval-calibration.md).

S59 picks **one** arc — the user's call at session start:
- **Arc A (this plan):** Walk POC P3 to completion (~50 min operator work) → start P4 agent core (~2.5-3 hr, the bulk).
- **Arc B (alternative):** S58 eval calibration — needs `mmdc` install + a way to generate real candidate outputs (blocked on P4).

Arc A is recommended because Arc B is blocked on P4 anyway.

---

## STEP 1 — POC P3 framework matrix walkthrough (~30 min)

**Surface:** CISO Console → AI Systems → `ai-sys-bae72e75` → Framework Coverage tabs (at `gov.aigovern.sandboxhub.co`).

**Action:**
1. Open the system page for the azure-architect AI system.
2. Tab through EU AI Act / ISO 42001 / OWASP LLM Top 10 / NIST AI RMF.
3. Screenshot each tab into `agents/azure-architect/poc-evidence/p3-framework-matrix/`.
4. For every RED cell, capture: framework, clause/control, why-red, what-evidence-clears-it.

**Acceptance:** Four screenshots saved. Triage table appended to `agents/azure-architect/POC-RETROSPECTIVE.md` for any RED cells — `F-019..` if platform-level fix needed, otherwise operator-correctable gap documented inline.

---

## STEP 2 — Generate EU AI Act PDF Pack (~10 min)

**Surface:** CISO Console → Reports → EU AI Act PDF Pack (per [pdf_report.py](../../pdf_report.py) `generate_eu_ai_act_pack`).

**Action:** Generate for `ai-sys-bae72e75`. Save under `agents/azure-architect/poc-evidence/p3-eu-ai-act-pack/`.

**Acceptance:** PDF downloads cleanly, contains system name + framework's mapped controls. Note the sha256 in the retro entry — same audit-trail pattern as the .rego bundles in F-018.

---

## STEP 3 — Update intake Step 5 evidence URLs (~10 min)

**Surface:** Team Portal → AI Systems → `ai-sys-bae72e75` → Edit → Step 5 evidence URLs.

**Action:** Add two entries:
- The canonical .rego bundle URL (now `https://aigovern.sandboxhub.co/api/v1/policies/rego#azure-architect` per S57 #1 fix; the alias middleware accepts both v1 and bare /api/).
- The EU AI Act PDF Pack URL (or sha256 if stored locally).

**Acceptance:** Step 5 saves; re-open shows persisted entries; system's evidence completeness % ticks up.

**P3 EXIT GATE.** If green, mark POC P3 CLOSED in `POC-RETROSPECTIVE.md` and proceed to STEP 4.

---

## STEP 4 — P4 kickoff: agent core (~2.5-3 hours)

**Reference:** [docs/plans/AZURE-ARCHITECT-POC.md §P4 §92-123](AZURE-ARCHITECT-POC.md).

**Sketch (refine at session start):**
1. **Tool layer** wrapping `azure.mgmt.*` for inspection. Minimum: `list_resource_groups`, `list_vnets`, `list_storage_accounts`, `validate_arm_template`. Each wrapped with `@signallayer.tool_call(action="<verb>")` so `@policy_gate` evaluates per-call.
2. **Orchestration loop** — agent picks a tool, calls it, integrates result, decides next step. Anthropic tool_use API; cap at 5 turns per request to bound cost.
3. **Mermaid synthesis** — agent emits diagram as Mermaid; engine renders / persists. Feeds the S57a eval harness as the missing "real candidate outputs" input → unblocks SESSION-58.
4. **Per-tool trace + eval** — each tool call goes through trace_call / evaluate_response (S56 #1 JSONL fallback already in place).

**S59 ambition:** ship items 1 + 2 with one working tool end-to-end (probably `list_resource_groups` — smallest real verb). Items 3 + 4 spill to S60.

**Acceptance:**
- `python agents/azure-architect/agent.py --plan "audit my prod subscription"` runs a multi-turn loop calling ≥1 Azure tool, receiving the result, producing a summary.
- Each tool call appears as a separate `trace_id` in `data/traces.jsonl`.
- `@policy_gate` evaluates each tool call (.rego allowlist enforced; modifications denied).
- Cost per `--plan` run: under $0.50 on Sonnet 4.6 (Opus deferred).

**Locked decisions to make at session-start (before code):**
- Tool-use turns cap (5? 10?). Higher = more flexibility, more cost.
- Intermediate state surfacing: printed inline like `--review`, or persisted to a new `data/plans.jsonl` for CISO Console to render later?
- Sonnet vs Opus default for `--plan`. Recommended: Sonnet 4.6 — tool calls don't need deep reasoning per turn; cost compounds across turns.
- **New for S59:** how should P4's synthesis output land in `agents/azure-architect/eval/dataset.jsonl` candidate format so S57a's runner can score it? Either P4 writes directly to a candidate JSONL, or a small adapter projects `data/plans.jsonl` → candidate shape. Decide before STEP 4 ends so S58 isn't re-blocked.

---

## Carry-forward (lower priority — do if time, else S60)

- **Probe 10** — synthetic key-survives-deploy. ~15 min with `$env:SMOKE_DEMO_PASSWORD_CISO`.
- **F-012** — multi-cloud intake (wizard is AWS-only). Own session.
- **Output-guardrails false positive** — S55 #14's benign Azure review flagged as `harmful_activity`.
- **Cosmetic** — `PoliciesPage` "No policies match the current filters" below the new RegoBundlesPanel; mock GRC list is empty (S57 close note).
- **UI-promise audit** — sweep operator verbs in docs vs UI reality. F-014 + F-018 + S57 #1 are the same class.

---

## Working rules in effect

- Direct-to-prod deploys (no Cosmos/Blob yet).
- After each P4 commit expect `docs/openapi-v1.json` drift; regenerate via `python scripts/export_openapi.py` and commit in the same push (S56 #3 pattern).
- Any new tool added to the agent gets a matching rule in `policies/azure-architect.rego` AND a sha256 visible in the CISO Console "Active enforced policies" panel — F-018 contract (now end-to-end-verified).
- Any new trace OR eval source goes through the JSONL fallback path (S56 #1) — no silent-drop integrations.
- **New for S59:** any new API endpoint registers with `prefix="/api"` (NOT `/api/v1`) per S57 #1 + [[auth-shadows-404]]. Verify with `[r.path for r in router.routes]` before deploy.

---

## Compound rules in memory (relevant)

- [[auth-shadows-404]] (S57 #1) — unauth 401 can mask a real 404 when auth runs after path-rewriting middleware.
- [[bare-except-hides-broken-integrations]] (S56 #1) — adding logs in `except` exposes silently-broken integrations.
- [[two-origins-spa-vs-engine]] (S55 #1) — check response BODY not just status.
- [[wizard-mounts-create-resources]] (S55 #2) — list-then-create, never POST on mount.
- [[slot-sticky-settings]] (S54 #2) — `--slot-settings KEY=VALUE` for sticky overrides.
- [[run-commands-dont-defer]] (S54 #1) — execute, don't present a menu.
- [[bash-cwd-persistence]] — Bash tool CWD persists across calls; use absolute paths or fresh `cd` per logical step.
