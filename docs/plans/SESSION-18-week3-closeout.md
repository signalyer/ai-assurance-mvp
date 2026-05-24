# Session 18 Plan — V2 Phase 2 Week 3 close-out

**Date drafted:** 2026-05-24 (end of Session 17)
**Branch:** continue on `phase/14-team-workspace-scaffold` (PR [#1](https://github.com/signalyer/ai-assurance-mvp/pull/1) is draft)
**Starting state:** Team Workspace = 9/12 surfaces. Three remain.

## Where I am

Session 17 shipped 4 surfaces in one branch (Memory · SDK Quickstart · RTF
engineer · My Portfolio) with zero engine endpoint changes. All verified
end-to-end through the running preview. Branch is clean at `47af837`, pushed
to origin, draft PR open.

Per `docs/plans/V2-PORTAL-SPLIT.md` §3, three Team Workspace surfaces remain:

| # | Surface | Status | Notes |
|---|---|---|---|
| #5 | Adversarial test runner | Net-new | First async-job UX in Team Workspace |
| #9 | RAG corpus management | Net-new | First mutation surface on `/api/rag/*` |
| #3 | Per-system 6-layer config | **Deferred** | Risk register §9 — needs "request change" workflow first |

## Decisions already locked (don't re-litigate)

- **Findings stays CISO-only** — V2-PORTAL-SPLIT.md §3 Decision Log, 2026-05-24
- **#3 6-layer config is deferred** until the CISO Console approval workflow
  exists. Shipping a Settings page where engineers flip scrubber backends
  invites exactly the failure mode the V2 risk register §9 flags as `High`.
  Do NOT pick this up in Session 18 unless the user explicitly says so.
- **Zero-engine-impact pattern** on phase/14 branch — preserve it. If a
  surface genuinely needs an engine change (e.g., scope filter), make it a
  separate commit with explicit ADR-style justification in the PR body.
- **Hardcoded actor = "demo-engineer"** for all write paths until session
  auth wires the real one in V2 Phase 3.
- **PR stays draft** until Week 3 is feature-complete. Marking ready-for-
  review = signal to merge.

## Key files to load

- [ARCHITECTURE.md](../../ARCHITECTURE.md) — Session 17 surface section
  is the freshest summary
- [docs/plans/V2-PORTAL-SPLIT.md](../V2-PORTAL-SPLIT.md) §3 (with Decision
  Log) + §9 (risk register — re-read before picking #3)
- [team-portal/src/pages/portfolio/PortfolioPage.tsx](../../team-portal/src/pages/portfolio/PortfolioPage.tsx)
  — newest pattern template: `computed()` projections off an existing
  endpoint, zero-engine surface. Mirror for #11-shaped reads.
- [team-portal/src/pages/rtf/RtfRequestPage.tsx](../../team-portal/src/pages/rtf/RtfRequestPage.tsx)
  — newest mutation template: client-side validation mirroring server
  validator, success banner, list reload on submit. Mirror for #9 corpus
  mutations.
- [api/rag.py](../../api/rag.py) — Session 04 RAG endpoints
  (read first before #9 — confirm mutation endpoints exist or whether
  surface #9 forces an engine change)

## Outstanding questions (need user input)

1. **Path for Session 18:** ship #9 RAG corpus, ship #5 Adversarial runner,
   or pause portal work to address V2 Phase 1 items (OpenAPI hardening,
   contract tests in CI per V2 §5)?
2. **#5 adversarial runner needs an async job UX.** Garak runs are slow
   (minutes). The existing Team Workspace has no precedent for long-running
   job polling — is the right pattern (a) optimistic queue + polling endpoint,
   (b) SSE like Agent Library publish flow, or (c) defer until V2 Phase 3
   when projection worker is consumed by SPAs?
3. **PR #1 management:** mark ready-for-review after Session 18 ships the
   remaining surfaces, or roll all of Week 3 + Phase 1 engine hardening into
   one merge?

## Next concrete action

If unblocked toward #9 (RAG corpus): first read [api/rag.py](../../api/rag.py)
end-to-end to confirm mutation endpoints exist. If they don't, the surface
forces an engine change — STOP and surface the scope shift before building.

If unblocked toward #5 (Adversarial runner): first read
[adversarial.py](../../adversarial.py) and check whether Garak is invoked
synchronously or already has a job-queue wrapper. The answer dictates the
SPA pattern.

If pausing portal work for V2 Phase 1: see
[docs/plans/SESSION-13-v2-engine-hardening.md](SESSION-13-v2-engine-hardening.md)
if it exists, otherwise V2-PORTAL-SPLIT.md §5 "Engine-side changes".

## Working rules in effect

- Project [CLAUDE.md](../../CLAUDE.md): read every file before modifying;
  full files only; scrubber-before-tracer; OPA fail-closed; storage.py for
  JSONL only
- Global `~/.claude/CLAUDE.md`: Azure SignalLayerDev, MSYS_NO_PATHCONV,
  full TypeScript discipline, prompt schemas inline
- **Compound rule from Session 16:** when a "graceful degradation" path
  exists in an engine module (e.g. `_inmem_*`), every related function needs
  the same fallback — depth gaps only surface when UI exercises them.
- **Compound rule from Session 17:** verify surface placement against the
  V2 plan §3, not against handoff docs — handoffs drift. Session 17 caught
  a Findings misplacement (Team vs CISO) by reading V2 plan first.
- **Compound rule from Session 17:** preview-server input dispatch via
  descriptor-setter doesn't propagate through Preact signal handlers
  reliably. Verify write paths via direct `fetch` from preview_eval
  rather than synthetic input events.
- preview_eval is the verification mechanism — preview_screenshot is flaky
  in this stack; preview_snapshot + DOM reads are reliable.

## Deviations from Session 17 plan

None — all four Session 17 surfaces shipped + verified + pushed. PR is current.

## Open issues

- `.jsonl` files in `data/` are tracked despite being in `.gitignore` (every
  session needs `git add -f`). Cleaner to either fully untrack
  (`git rm --cached`) or remove from `.gitignore`. Carried over from
  Session 16; not blocking.
- `EVAL_BACKEND=noop` is required on `app-aigovern-dev` to avoid the 800MB
  deepeval transitive. Captured in SESSION-12B §6; not in Bicep/IaC.
