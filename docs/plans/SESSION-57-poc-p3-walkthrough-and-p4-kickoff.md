# SESSION-57 — POC P3 UI walkthrough + P4 agent core kickoff

**Status entering S57:** Three observability gaps (F-016 / F-017 / F-018) closed in S56. Engine on `d90ea50`. Agent runs end-to-end with traces + evals now persisted to `data/{traces,evals}.jsonl` and joinable by `trace_id`. CISO Console gained a read-only "Active enforced policies" panel (waits for SPA pipeline run to go live). POC P2 closed; POC P3 has its `.rego` artifact live; remaining P3 actions are operator-driven UI walkthroughs against surfaces that DO exist.

**Theme:** Walk POC P3 to actual completion (operator verbs, not platform code), then start P4 agent core. P3 is ~90 min if no RED cells surface; P4 is the main arc of the session.

---

## STEP 0 — Trigger CISO Console SPA pipeline (~5 min)

**Why:** S56 #2's `RegoBundlesPanel` is in the bundle but waits on the next SPA deploy run to go live at `gov.aigovern.sandboxhub.co`.

**Action:** `gh workflow run deploy-ciso-console.yml --ref main` (or the equivalent — check `.github/workflows/`). If no SPA workflow exists, deploy via `swa deploy` against the gov SWA token (S52 pattern). Verify `index-*.js` bundle hash changes on `gov.aigovern.sandboxhub.co`.

**Acceptance:** Logged-in CISO sees "Active enforced policies" card on `/policies` showing 5 .rego bundles (agent_tools, azure-architect, base, financial_advisor, pii) with sha256 prefixes.

---

## STEP 1 — POC P3 framework matrix walkthrough (~30 min)

**Surfaces that exist:** CISO Console → AI Systems → `ai-sys-bae72e75` → Framework Coverage tabs.

**Action:**
1. Open the system page for the azure-architect AI system.
2. Tab through EU AI Act / ISO 42001 / OWASP LLM Top 10 / NIST AI RMF.
3. Screenshot each tab for the POC evidence pack.
4. For every RED cell, capture: framework, clause/control, why it's red, what evidence would clear it.

**Acceptance:** Four screenshots saved under `agents/azure-architect/poc-evidence/p3-framework-matrix/`. Triage table appended to `agents/azure-architect/POC-RETROSPECTIVE.md` for any RED cells — `F-019..` if any need platform-level fixes; otherwise document the operator-correctable gap.

---

## STEP 2 — Generate EU AI Act PDF Pack (~10 min)

**Surface:** CISO Console → Reports → EU AI Act PDF Pack (per [pdf_report.py](../../pdf_report.py) `generate_eu_ai_act_pack`).

**Action:** Generate for `ai-sys-bae72e75`. Confirm download. Save under `agents/azure-architect/poc-evidence/p3-eu-ai-act-pack/`.

**Acceptance:** PDF downloads cleanly, opens without errors, and contains the system's name + the framework's mapped controls. Note the file's sha256 in the retro entry — same audit-trail pattern as `.rego` bundles.

---

## STEP 3 — Update intake Step 5 evidence URLs (~10 min)

**Surface:** Team Portal → AI Systems → `ai-sys-bae72e75` → Edit → Step 5 evidence URLs.

**Action:** Add two entries:
- `https://aigovern.sandboxhub.co/api/v1/policies/rego#azure-architect` (or whatever the canonical URL is for the .rego bundle — derive from the F-018 endpoint shape)
- The EU AI Act PDF Pack URL (or sha256 if the pack is stored locally)

**Acceptance:** Step 5 saves cleanly; subsequent re-open shows both entries persisted; the system's evidence completeness % ticks up.

**P3 EXIT GATE.** If all three steps green, mark POC P3 CLOSED in `POC-RETROSPECTIVE.md` and proceed to STEP 4.

---

## STEP 4 — P4 kickoff: agent core (tools + orchestration) (~2.5–3 hours, the bulk of S57)

**Reference:** [docs/plans/AZURE-ARCHITECT-POC.md §P4 §92–123](AZURE-ARCHITECT-POC.md).

**What P4 needs (sketch — refine in-session):**
1. **Tool layer** wrapping `azure.mgmt.*` for the agent to actually inspect / propose changes. At minimum: `list_resource_groups`, `list_vnets`, `list_storage_accounts`, `validate_arm_template`. Each tool wrapped with `@signallayer.tool_call(action="<verb>")` so policy_gate evaluates per-call.
2. **Orchestration loop** — the agent picks a tool, calls it, integrates the result, decides next step. Anthropic tool_use API; ~5 turns max per request to bound cost.
3. **Mermaid synthesis** — agent emits an architecture diagram as Mermaid; engine renders / persists.
4. **Per-tool trace + eval** — each tool call goes through the same trace_call / evaluate_response pipeline that the `--review` action just got in S56. JSONL persistence already in place.

**S57 ambition:** ship STEPS 1 + 2 with one working tool end-to-end (probably `list_resource_groups` — the smallest verb that's still real). 3 + 4 spill to S58.

**Acceptance:**
- `python agents/azure-architect/agent.py --plan "audit my prod subscription"` runs a multi-turn loop where the agent calls at least one Azure tool, receives the result, and produces a summary.
- Each tool call appears as a separate trace_id in `data/traces.jsonl`.
- @policy_gate evaluates each tool call (.rego allowlist enforced — modifications denied).
- Cost per `--plan` run: under $0.50 on Sonnet 4.6 (Opus deferred; benchmark with `--fast` default).

**Locked decisions to make at session-start (before code):**
- Tool-use turns cap (5? 10?). Higher = more agent flexibility, more cost.
- How to surface intermediate state (printed inline like `--review`, or persisted to a new `data/plans.jsonl` for the CISO Console to render later)?
- Sonnet vs Opus default for `--plan`. Recommended: Sonnet 4.6 — tool calls don't need deep reasoning per turn; cost compounds across turns.

---

## Carry-forward (lower priority — do if time, else S58)

- **Probe 10** — synthetic key-survives-deploy test. Requires `$env:SMOKE_DEMO_PASSWORD_CISO` and a CI round-trip. ~15 min. Closes F-009/F-011 detection gap.
- **F-012** — multi-cloud intake (wizard is AWS-only). Material work; probably a session of its own.
- **Output-guardrails false positive** — S55 #14's live run warned `harmful_activity` on a benign Azure architecture review. Worth a retro entry + small fix.
- **UI-promise audit** — full sweep of operator verbs in `docs/plans/AZURE-ARCHITECT-POC.md` and the README against what the UI actually does. F-014 + F-018 are both instances of this class; there are likely more.

---

## Working rules in effect

- Direct-to-prod deploys remain in force (no Cosmos/Blob migration yet).
- After each P4 commit, expect `docs/openapi-v1.json` to drift; regenerate via `python scripts/export_openapi.py` and commit in the same push to keep CI green (S56 #3 pattern).
- Any new tool added to the agent gets a corresponding rule in `policies/azure-architect.rego` AND a sha256 visible in the CISO Console "Active enforced policies" panel — F-018 contract.
- Any new trace OR eval source goes through the JSONL fallback path established in S56 #1 — no silent-drop integrations.

---

## Compound rules already in memory (relevant to this session)

- [[bare-except-hides-broken-integrations]] (S56 #1) — when adding logs in `except`, expect to find broken integrations the swallow was hiding. Watch for it when wrapping Azure SDK calls.
- [[two-origins-spa-vs-engine]] (S55 #1) — check response BODY, not just status, when probing the SPA vs engine.
- [[wizard-mounts-create-resources]] (S55 #2) — list-then-create, never POST on mount.
- [[slot-sticky-settings]] (S54 #2) — any setting touched out-of-band on the web app must be applied `--slot-settings KEY=VALUE`.
- [[run-commands-dont-defer]] (S54 #1) — execute, don't present an Option-1/Option-2 menu.
