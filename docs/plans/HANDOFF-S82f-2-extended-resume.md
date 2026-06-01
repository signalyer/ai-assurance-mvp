# Resume — vendor_risk demo path (post-S82f-2 extended)

## Where I am

vendor_risk runs end-to-end in the SPA. Demo path proven: `demo-ciso` →
`portal.aigovern.sandboxhub.co/agent-runner` → pick `vendor_risk` → paste
ext-01 prompt → policy_gate ALLOW → real fixture parsing → MEDIUM tier
via Art.28 detection → audit written. **Last verified run:
`run-15015488b294`, `aud-214ee7c989b0`, 50.63s.**

Engine sha: `f53fefb`. SPA bundle: `index-BLwvrRIV.js`. Tree clean.

12 commits shipped today (`f41ca70..f53fefb`).

## Decisions already made (don't re-litigate)

- **ADR-004 Option B** for runtime-flag flow. Overlay at
  `data/system_runtime_flags.jsonl`. INT calibration unblocked 0/8 → 8/8.
- **Path A** for role: `TPRM_ANALYST` added to `middleware/auth.py:ROLES`.
- **Demo + internal-use scope only.** No multi-tenant, no external
  MRM/audit review cycles, no dual-signer, no DR. User confirmed this
  explicitly in-session.
- **Dispatcher inspect-filters agent_kwargs.** `system_id` +
  `vendor_package_ref` threaded to inner when signature accepts; safe
  for agents that don't declare them.
- **Banner suppression on clean SSE EOF.** `terminalEventSeen` signal
  guards the connectionBanner — real errors still surface.

## Outstanding

1. **Verify f53fefb banner fix in browser.** User hadn't re-run yet at
   session end. First action: hard-refresh `/agent-runner`, run ext-01,
   confirm no "Connection lost" banner. ~1 min.

2. **Outcome shows REVIEW not SUCCESS.** The dispatcher emits
   `outcome="review"` when `stop_reason` is neither `end_turn` nor
   `turn_cap_reached`. Last successful run hit Done REVIEW @ 50.63s.
   Worth a `domain/agent_runner.py:422` review to understand why
   vendor_risk's stop_reason maps to review instead of success.

3. **INT calibration tier-match (S82f-3 work).** Locked baseline INT
   2/8 vs EXT 10/10. Phase-6 prompt iteration in
   `agents/vendor_risk/prompts.py::SYSTEM_PROMPT_INT`. Under-tier on
   internal-system-references; over-tier on MNPI board cues.

4. **No SPA history view for past runs.** `/api/agent-runs` returns
   history; no page renders it. Curl + DEMO-PROMPTS.md operational
   helpers cover post-mortem until a "Run details" page lands.

5. **`DEMO_USER_TPRM_ANALYST_HASH`** — App Service app-setting
   provisioning (out-of-band) for dual-signer demos.

6. **assert_no_egress wiring** — ADR-004 §8 Q2 defense-in-depth.
   Requires local-provider swap first (INT today calls Anthropic).

7. **finadvice + azure-architect missing from domain Agent registry.**
   Same backfill pattern as `197a6ec`. Three agents in runtime registry,
   one in domain registry. Catalog will show 7 instead of 9.

8. **App.tsx/app.tsx casing on Windows.** `npm run build` fails tsc
   gate; `npx vite build` bypasses. Normalize the filename casing in
   git, OR add a `build:fast` script.

9. **swa-cli.config.json missing.** Every manual deploy requires
   `--resource-group rg-aigovern-dev --app-name swa-aigovern-portal-dev`
   on the CLI. Drop a swa-cli.config.json in team-portal/ to make
   `swa deploy ./dist --env production` work bare.

10. **vendor_risk eval invisible in the SPA Evals page.** Two
    incompatible eval schemas in the codebase: `data/evals.jsonl`
    (per-LLM-call rows, what `/api/evals/recent` reads) vs
    `data/vendor_risk_eval_runs.jsonl` (suite-level aggregates, what
    `run_eval.py` writes). Same class of gap as runtime-vs-domain agent
    registry. **Recommended fix: E1** — new
    `GET /api/agents/{id}/eval-summary` endpoint reading
    `vendor_risk_eval_runs.jsonl` + `baseline.json`, returning
    `{baseline, last_run, pass_rate, per_case_results}`. Render in an
    "Eval" tab on the Agent Library detail modal. Schema-honest. ~0.5
    session. Alternatives: E2 (schema bridge — write per-case rows to
    `evals.jsonl` with workload_id, conflates shapes) or E3 (static
    markdown render of iteration-log + baseline + calibration log).

## Key files

- `docs/sop-vendor-risk/DEMO-PROMPTS.md` — 8 copy-paste demo prompts
- `scripts/Test-VendorRisk.ps1` — CLI fallback (`-List`, `-DryRun`, run by id)
- `docs/adr/ADR-004-vendor-risk-int-runtime-flag-flow.md` — design source
- `docs/sop-vendor-risk/07-staged-calibration-log.md` — rows 11b–18b
- `tests/test_runtime_flags_overlay.py` — 9-test ADR §5 drill regression
- `agents/vendor_risk/prompts.py` — Phase-6 iteration target (S82f-3)

## Next concrete action

Verify f53fefb in the browser (step 1 above). If clean:

- If demo-readiness is the priority: pursue items 7 (other-agent
  domain backfill) + 9 (swa-cli.config) + 4 (SPA history view) — all
  small surface, all visibility for a demo audience.
- If model-accuracy is the priority: S82f-3 in a fresh session (item 3).
  Open the four under-tier INT fixtures, sharpen
  `SYSTEM_PROMPT_INT`, iterate until ≥6/8 tier match.

## Engine state at session start

- sha: `f53fefb` — engine deployed
- SPA bundle: `index-BLwvrRIV.js` — deployed to swa-aigovern-portal-dev
- INT runtime-flag attestation: PATCH'd 2026-06-01 ~19:03Z, **expires
  2026-06-02 ~19:03Z**. Re-PATCH via curl or harness pre-flight after that.
- SDK keys: `slk_b3aebe21` (ext) / `slk_7e903e17` (int)

## Operator session cookie

- `AIGOVERN_BASE_URL=https://aigovern.sandboxhub.co`
- `AIGOVERN_COOKIE=aigovern_session=<fresh demo-ciso cookie>`
- For the SPA: log in as demo-ciso → lands on `gov.aigovern.sandboxhub.co`
  → manually navigate to `portal.aigovern.sandboxhub.co/agent-runner`
  (parent-domain cookie carries the session)

## Working rules in effect

- `~/.claude/CLAUDE.md` — session management, 60% compact rule, token bands
- `C:/ai-assurance-mvp/CLAUDE.md` — project rules, four 2026-06-01 rules
  from S82f-1c still apply
- New lesson worth a memory entry next session: **grep the deployed SPA
  bundle, not source, when validating SPA-side claims**. I incorrectly
  said "the SPA enumerates agents dynamically, vendor_risk is there"
  based on source — the deployed bundle didn't have the /agent-runner
  route at all. Mirror of `[[spa-deploy-is-manual-swa]]` at verify step.
