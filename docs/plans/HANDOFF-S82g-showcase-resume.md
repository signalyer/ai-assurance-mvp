# Resume — AI Assurance Platform (Showcase Track, post-W6)

## Reframe (locked decision)
This is a SKILLS SHOWCASE, not a startup MVP. Optimize for the
recruiter / hiring committee / engineering principal who will spend
20 minutes evaluating this. Prior "go get a paying pilot" advice is
out of scope. The bar is: portfolio rating 8.5 → 9.5.

## Where I am
- Engine sha a08a4c7. Team-portal bundle live: index-CI1hiHAc.js
  at portal.aigovern.sandboxhub.co.
- vendor_risk demo path proven EXT (ext-01 → MEDIUM, 50s).
- Wired today (S82f-2-extended): item 7 registry backfill, item 9
  swa-cli config, item 10/W2/W4 eval visibility + drill, item 8
  App.tsx casing, item 2 outcome mapping, item 4 /agent-runs page,
  W1 /agent-runs/{run_id} detail, W3 runtime-flag attestation panel,
  W5 vendor_risk memory wiring + deep links, W6 corpus tab + sandbox.
- Rated 8.5/10 as a showcase. Path to 9.5: 80% narrative artifacts,
  20% targeted gap closing.

## Decisions already made (don't re-litigate)
- Scope: demo + internal-use only. No multi-tenant, no production
  hardening (assert_no_egress runtime wiring, dual-signer, OIDC,
  backup/DR, cost SLOs all deferred).
- Methodology IS the showpiece. The 13-phase eval-co-evolved SOP
  (docs/SOP-agent-onboarding.md) is what differentiates this build.
- Cut surface area in favor of narrative. No new pages this session
  unless a specific UI-promise-audit gap demands it.
- vendor_risk is the only fully-onboarded agent. finadvice and
  azure-architect are demo_only=True and HURT the showcase because
  the SOP looks aspirational with 2 of 3 agents skipping it.

## Outstanding (showcase-priority order)
1. NARRATIVE — 4-min screen-record (Loom or local OBS) walking the
   demo-ciso login → /agent-runner → vendor_risk EXT ext-01 path
   end-to-end, then INT runtime-flag attestation panel on
   sys-vendor-risk-int-001. Chain events flying by IS the proof.
2. NARRATIVE — 1500-word blog post: "Eval-as-spec: why Phase 4 gates
   Phase 5 in our agent SOP." Use vendor_risk's 18-case baseline
   (17/18 PASS, ext-07 the one failure on conflicts_flagged) as
   the worked example.
3. NARRATIVE — 1-page architecture SVG of the governed chain
   (policy_gate → scrub_pii → guardrails → llm → evaluate → memory
   → audit) with event names labelled. Renders standalone — must be
   readable without the codebase open.
4. NARRATIVE — README.md rewrite. Lead with: what this proves
   (architecture + methodology), what one agent looks like end-to-end,
   how to navigate the repo for a 20-min review. Audience: principal
   engineer who has never seen this before.
5. GAP — Pick one: (a) remove finadvice + azure-architect from
   _registry.py and domain/agents.py so the showcase shows ONE
   real agent (cleanest), or (b) actually complete Phase 1-13 for
   finadvice (most ambitious). Recommend (a) for time-box.
6. GAP — S82f-3 INT prompt iteration so headline accuracy isn't 2/8.
   Reviewers WILL look at the eval tab. INT at 25% looks bad.
7. GAP — Zero ciso-console vendor_risk surfaces. Either wire 1-2
   governance views (Findings + AI Systems show vendor_risk-ext-001
   + int-001) OR add a docs note that ciso-console is "next quarter"
   so a reviewer doesn't read it as broken.

## Out of scope this session
- All "wire everything missing" requests below items 1-7.
- Production hardening (auth cutover, multi-tenant, DR, etc.).
- New agents.
- CISO Console full coverage (item 7 only the minimum to not look
  abandoned).

## Next concrete action
Read docs/SOP-agent-onboarding.md and agents/vendor_risk/eval/
iteration-log.md, then DRAFT the blog post outline (item 2) in
docs/blog/eval-as-spec-DRAFT.md. The blog frames the methodology
that anchors everything else — write it first so the recording (1)
and the diagram (3) inherit its narrative spine.

## Key files
- docs/SOP-agent-onboarding.md           — methodology canon
- agents/vendor_risk/eval/baseline.json  — 17/18 worked example
- agents/vendor_risk/eval/iteration-log.md — calibration narrative
- docs/adr/ADR-004-vendor-risk-int-runtime-flag-flow.md — INT story
- ARCHITECTURE.md                        — diagram source-of-truth
- README.md                              — recruiter-facing surface
- agents/_registry.py                    — demo_only sprawl target

## Working rules in effect
- ~/.claude/CLAUDE.md (session mgmt, 60% compact, token bands)
- C:/ai-assurance-mvp/CLAUDE.md (2026-06-01 compound rules)
- [[show-handoff-prompt-inline]] memory rule
- This session is Documentation-class. Token band Normal < 200K.
  Stop / Escalate > 500K. The work is mostly prose, not code.
