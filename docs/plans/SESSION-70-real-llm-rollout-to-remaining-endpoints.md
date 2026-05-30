# SESSION-70 — Roll real Anthropic streaming to the other 4 endpoints + CISO Console drawer parity
# Date: planned 2026-05-31 (next)
# Context cost: MEDIUM (engine prompt builders + SPA wire-up across two SPAs)
#
# Prereq: S69 shipped — `explain-release` is on the live LLM path with
# `REAL_LLM_ENABLED=true` on prod. Engine `8a942b6`. Team-portal SPA
# `index-CaTHiUwg.js`. CISO Console SPA `index-bVhd18Tk.js` (unchanged,
# S69 wasn't a CISO-side ship).

## Scope

S69b. Apply the streaming pattern to the other four LLM-triggering
endpoints AND ship the drawer on CISO Console.

**Engine work (api/assurance_model.py):**
- Switch `POST /ask`, `/summarize-finding`, `/summarize-evidence`,
  `/draft-report` from `_dispatch` to `_dispatch_streaming`.
- Each becomes an SSE endpoint — drop their `response_model=AskResponseOut`
  on the FastAPI route (mirroring what S69 did for `/explain-release`).
- Existing `_dispatch` should NOT be deleted — keep it as a sync fallback
  for any future non-LLM-triggering route + so the codebase keeps the
  reference for what the legacy contract was.

**Engine work (domain/assurance_providers.py):**
- Extend `_build_prompt()` with branches for the other four use cases:
  - `FINDINGS_SUMMARIZATION` — frame for plain-English finding summary;
    target ~180 words; structure mirrors the existing simulate_response
    text in domain/assurance_providers.py:742-750.
  - `EVIDENCE_SUMMARIZATION` — frame for redacted-metadata-only evidence
    completeness + gap framing. Calibration target: lines 763-771.
  - `EXECUTIVE_REPORT_GENERATION` — board-ready exec summary, slightly
    longer (~250 words); calibration target: lines 773-781.
  - `SYSTEM_QA` — Q&A about a specific AI system. Use the `question`
    payload field; target ~150 words. Calibration target: lines 783-790.
- Verify `_MAX_TOKENS_BY_USE_CASE` budgets are right for each — S69 set
  them but only release-narrative was exercised. Bump if needed.

**Prompt calibration (mandatory per CLAUDE.md "calibration before suite"):**
- For each new prompt, run against real data (NOT synthetic) end-to-end
  through the live engine with `REAL_LLM_ENABLED=true` and a small known
  payload. Compare structure + fact-claims against the worked example
  (the simulate_response text). Tighten prompt anchors / explicit
  framework refs if drift observed. Document tightening in commit msg.

**Frontend work — team-portal:**
- G-5 (Summarize finding) — first call site needs adding. Two options:
  (a) New FindingsPage.tsx with a list + Summarize button on each row;
  (b) Add Summarize button on existing finding rows in AiSystemDrawer's
  findings section. **Pick (b)** for S70 (smaller surface, same shared
  drawer pattern, no new page route).
- G-7 (Ask about system) — surface "Ask" button on AiSystemDrawer header.
  Opens AiSummaryDrawer routed at `/assurance-model/ask` with a question
  input (consider a small modal-within-drawer for the question text).
- G-8 (Summarize evidence) — Summarize button in AiSystemDrawer's
  Evidence section header. Body: `{ai_system_id, payload: {}}`.
- G-9 (Draft executive report) — top-of-page button on AiSystemsPage
  or a route on `/reports`. Defer the page route to S70b if a new page
  is needed — for S70, surface as a button somewhere visible.
- Every call site MUST go through the shared `openAiSummary({url, title,
  body})` API. Any drift here would be a F-019 / [[raw-fetch-drifts-
  from-shared-client]] repeat.
- Decide for each whether the Anthropic pin is needed. Same routing
  logic as S69: Bedrock outranks Anthropic for FINDINGS_SUMMARIZATION,
  EXECUTIVE_REPORT_GENERATION, and SYSTEM_QA (it has all three roles).
  EVIDENCE_SUMMARIZATION — Bedrock NOT in allowed_use_cases for this
  one (only OpenAI, Anthropic, Local/VPC). So evidence summarization
  routes to OpenAI first if creds present, else Anthropic. **OpenAI
  is currently sim-only on the live path — stream_anthropic_response
  is Anthropic-specific.** Pin Anthropic for evidence too, until S71
  ships the OpenAI streaming adapter.

**Frontend work — CISO Console parity (ciso-console/src/):**
- Port `shared/api/client.ts` apiSse + `shared/components/AiSummaryDrawer.tsx`
  + `shared/types/assurance.ts` into the ciso-console source tree.
  Easiest: copy the team-portal files verbatim; the only shell-specific
  thing is the `<AiSummaryDrawer />` mount in `ciso-console/src/app.tsx`.
- Surface the same five LLM-triggering buttons in CISO Console wherever
  the operator is. Probably: Findings page (G-5), AI Systems detail
  (G-6 release explain + G-7 ask), Evidence page (G-8), Reports surface
  (G-9). Walk the ciso-console source first to see which surfaces exist.

**Tests:**
- Extend `tests/test_api_assurance_model.py` with one streaming-path test
  per new endpoint. Mock the helper same way S69 did — patch
  `api.assurance_model.stream_anthropic_response` with a fake async
  generator. Run with `-s -p no:deepeval`.
- One test per blocked path is overkill — S69 already covers
  the blocked/sim/live state machine. Just one test per new endpoint
  proving the route emits an SSE stream with `status='live'`.

## Verification

1. `pytest tests/test_api_assurance_model.py -p no:deepeval` — all green.
2. Build both SPAs (`npm run build` in team-portal + ciso-console);
   confirm no TS errors.
3. Smoke each endpoint live on prod: log into portal, click each
   button, confirm the live LLM response renders progressively with
   the streaming cursor, badge drops, token + cost rows appear.
4. Bundle-hash + string-grep verify on `portal.aigovern.sandboxhub.co`
   AND `gov.aigovern.sandboxhub.co` (CISO Console).
5. Cost check: after smoking all 5 buttons, query
   `/api/assurance-providers/audit/list` and confirm `decision=live`
   rows for each use case with realistic token + cost numbers.

## Deploy

- Engine: `git commit` + `python deploy/build-zip.py` + `az webapp deploy`.
  Per [[appservice-deploy-python]] + [[requirements-deploy-drift]]: NO
  new module-load imports are expected in S70 (the SSE infra is already
  in place from S69). Verify before zipping by grepping for new
  `from X import Y` in `api/` / `domain/`.
- SPAs: manual `swa deploy` per SPA dir per [[spa-deploy-is-manual-swa]]
  + [[bash-cwd-persistence]]. Two deploys: team-portal AND ciso-console.

## Open carry-forward NOT addressed by S70

- **S71 — OpenAI streaming adapter** (drops Anthropic-pin on evidence
  summarization; also unblocks Bedrock workloads when AWS creds get
  configured)
- **S71b — Bedrock streaming adapter** (drops the Anthropic pin on the
  other 3 endpoints; production-runtime workloads can also use it)
- **S72 — F-021 framework mapping data for ai-sys-bae72e75**
- **S72 — Remaining ARM read stubs** (list_subscriptions,
  list_role_assignments, get_network_topology)
- **S74 — UI-promise audit re-run** per [[ui-promise-audit-owed]]
- **Triage `AGENTS.md` + `team-portal/cookies.txt`** — both pre-existed
  S69; never decided whether to commit, gitignore, or delete

## Open questions for S70 start

1. AiSystemDrawer is getting busy — Explain on gates, Ask on header,
   Summarize on evidence, Summarize on findings. Do we need a single
   "AI Actions" menu instead of inline buttons everywhere? Probably
   defer to a UX pass; for S70 stick with inline.
2. OpenAI streaming adapter — when, S71 or sooner? The Anthropic pin
   for evidence-summarization is technically a behavioral regression
   from the routing engine's preference. If we care, S71 immediately
   after S70.
3. Cost guardrails: now that the live path is on, do we want a
   per-session or per-day cost ceiling enforced in `_dispatch_streaming`
   (refuse to start the stream if cumulative cost > $X today)? Defer
   to a dedicated cost-controls session — not S70 scope.

## Lessons folded from S69
- `requirements-deploy.txt` is the source of truth for runtime imports.
  Grep it before zipping. Memory: `feedback_requirements_deploy_drift.md`.
- The routing engine picks based on role-stack first, credentials never
  — so the live LLM path can silently fall back to sim when the routed
  provider has no creds. Until S71/S71b, SPA pins Anthropic.
- 401 from a deploy probe (vs 404 or 503) is the cleanest signal that
  the route shipped + auth middleware is doing its job.
