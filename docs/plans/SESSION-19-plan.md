# Session 19 Plan — Post Week 3 close-out

**Date drafted:** 2026-05-24 (end of Session 18)
**Branch:** start on `main` at `4ad2515`. No active feature branch.
**Starting state:** Team Workspace = 11/12 surfaces. Only #3 remains
(locked-deferred per V2 risk register §9).

## Where I am

Session 18 closed cleanly. Team Workspace SPA is feature-complete except
for #3 (6-layer config), which is deliberately deferred until the CISO
Console approval workflow exists.

Engine delta landed: `/api/rag/*` and `/api/adversarial/*` are live in
main. If App Service auto-deploys from main, they're already in production
at `https://api.aigovern.sandboxhub.co` — confirm with a `/stats` curl
before assuming.

CI workflow upgraded to schemathesis v4 conventions; previous flag drift
silently failed every PR until this session.

## Decisions already locked (don't re-litigate)

- **#3 6-layer config stays deferred.** Risk register §9 flags High
  likelihood engineers break it without an approval workflow. CISO
  Console must ship the approval queue first.
- **Findings stays CISO-only** (V2-PORTAL-SPLIT.md §3 Decision Log).
- **PR strategy:** the user closed direct multi-PR work this session.
  Default to direct-to-main for small, low-risk commits on `main`;
  use a single PR per session for engine + UI deltas.
- **Hardcoded `actor = "demo-engineer"` for all write paths** until V2
  Phase 3 auth wires the real actor.
- **Zero-engine-impact preserved where possible.** Two surfaces this
  session (#9, #5) required engine work, both committed with ADR-style
  justification per the locked rule.

## Key files to load

- [ARCHITECTURE.md](../../ARCHITECTURE.md) — Session 18 surface section is
  the freshest summary
- [docs/plans/V2-PORTAL-SPLIT.md](../V2-PORTAL-SPLIT.md) §3 (Decision
  Log) + §5 (Engine-side changes still open) + §9 (risk register)
- [docs/plans/SESSION-13-v2-engine-hardening.md](SESSION-13-v2-engine-hardening.md)
  — V2 Phase 1 backlog if path is engine hardening
- [api/adversarial.py](../../api/adversarial.py) + [api/rag.py](../../api/rag.py)
  — newest engine surfaces. Pattern for future thin-router work.
- [team-portal/src/pages/adversarial/AdversarialPage.tsx](../../team-portal/src/pages/adversarial/AdversarialPage.tsx)
  — SSE consumer pattern. Mirror for any future long-running surface.

## Outstanding questions (need user input)

1. **What direction for Session 19?** Three plausible paths:
   - **(a) Production verification** — App Service redeploy from main,
     smoke-test `/api/rag/*` + `/api/adversarial/*` against real Azure
     creds, fix any deploy-time regressions.
   - **(b) CISO Console kickoff** — start the second SPA so that #3 can
     eventually unblock and approvals/Findings move out of "Team
     Workspace placeholder" status.
   - **(c) V2 Phase 1 engine hardening** — finish OpenAPI contract
     work, RBAC scope filter, projection worker consumed by SPAs (per
     V2-PORTAL-SPLIT.md §5). Unblocks #3 indirectly via approval
     workflow infrastructure.
   - **(d) Pre-existing tech debt** — adversarial.py top-level
     `Anthropic`/`OpenAI` imports + sequential probe loop (flagged in
     memory: `feedback_batch_llm_calls.md`,
     `feedback_appservice_deploy_python.md`). Both clean wins, neither
     blocking.

2. **App Service auto-deploy state?** Did the main push at `4ad2515`
   trigger a redeploy? If yes, were `/api/rag/*` + `/api/adversarial/*`
   smoke-tested against the live engine? If no auto-deploy is wired,
   that's its own work item.

## Next concrete action

Wait for direction on Q1. If unblocked toward (a): start with
`curl https://api.aigovern.sandboxhub.co/api/rag/stats` and
`curl https://api.aigovern.sandboxhub.co/api/adversarial/categories` —
both should return 200 with sensible JSON if the deploy is live.

If toward (c): re-read V2-PORTAL-SPLIT.md §5 first to see which engine
items are still open after Session 13 hardening landed.

## Working rules in effect

- Project [CLAUDE.md](../../CLAUDE.md): read every file before modifying;
  full files only; scrubber-before-tracer; OPA fail-closed; storage.py
  for JSONL only
- Global `~/.claude/CLAUDE.md`: Azure SignalLayerDev,
  MSYS_NO_PATHCONV=1, TypeScript strict, prompt schemas inline
- **Session 18a (compound):** GitHub PR head can desync from branch ref
  silently. Use `gh pr view --json headRefOid` as the canary; force
  re-sync via close+reopen if stuck.
- **Session 18b (compound):** schemathesis v4 dropped `--hooks` and
  `--hypothesis-*` flag prefixes. Use `SCHEMATHESIS_HOOKS` env var with
  a Python module path (ci.schemathesis_hooks), not `--hooks file/path`.
- **Session 18c (compound):** SSE for sync generators — drain with
  `await asyncio.to_thread(next, gen, sentinel)` per yield. `async for`
  over a sync generator blocks the event loop on each iteration.
- **Session 17 (carried):** verify surface placement against V2 plan §3,
  NOT against handoff docs — handoffs drift.
- **Session 17 (carried):** preview-server input dispatch via
  descriptor-setter doesn't propagate through Preact signal handlers
  reliably. Verify write paths via direct `fetch` in `preview_eval`,
  not synthetic input events.
- **Session 17 (carried):** `preview_eval + preview_snapshot` are
  reliable; `preview_screenshot` is flaky in this stack.
- **Verify-block:** the scrubber e2e check requires the default Presidio
  backend. Do NOT set `SCRUBBER_BACKEND=regex` when running /verify —
  regex backend omits email by design.

## Deviations from Session 18 plan

- Original plan asked Q1 = "ship #9, ship #5, or pause for hardening".
  Answer was "you decide" → I shipped both #9 and #5 in the same
  session. Brought count to 11/12 instead of 10/12.
- PR strategy changed mid-session: user instructed "don't create any
  more PRs". After PR #1 squash-merged at the stale head, the remaining
  3 post-PR commits were cherry-picked directly to main (which is
  unprotected) rather than opened as a new PR.
- GitHub PR sync got stuck for ~15 min — captured as compound rule
  Session 18a.

## Open issues

- `.jsonl` files in `data/` are tracked despite being in `.gitignore`
  (every session needs `git add -f`). Cleaner to either fully untrack
  (`git rm --cached data/*.jsonl`) or remove from `.gitignore`. Carried
  over from Session 16; not blocking.
- `EVAL_BACKEND=noop` is required on `app-aigovern-dev` to avoid the
  800MB deepeval transitive. Captured in SESSION-12B §6; not in
  Bicep/IaC.
- `adversarial.py` has top-level `from anthropic import Anthropic` and
  `from openai import OpenAI` — violates the "no top-level heavy
  imports" rule from memory. Pre-existing; flagged for cleanup.
- `adversarial.py` runs probes sequentially when they could
  `asyncio.gather` — violates the "batch LLM calls always" rule from
  memory. Pre-existing; flagged for cleanup.
- App Service auto-deploy state from main push at `4ad2515` is
  unverified. Tracked as Q2 above.
