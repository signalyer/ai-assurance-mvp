# Resume — vendor_risk SOP · S82b (Phase 2 + Phase 3)

## Where I am
S82a (Phase 0 + Phase 1) shipped clean. Commit [`2445a6f`](https://github.com/signalyer/ai-assurance-mvp/commit/2445a6f) live on prod (SHA verified via /api/health).

Both AISystem rows land on engine cold start through the canonical intake
pipeline (`api.intake.submit_intake`) via a lifespan bootstrap. NOT
hand-written seed rows. Receipts captured in `docs/sop-vendor-risk/01-intake-receipt-{ext,int}.md`.

Differential gate counts produced by the intake risk classifier:
- `sys-vendor-risk-ext-001`: 11 gates, 2 blocking, inherent_risk=HIGH, rules R5
- `sys-vendor-risk-int-001`: 15 gates, 5 blocking, inherent_risk=HIGH, rules R1+R4+R5

Pre-existing intake bug from S66 (datetime shadowed by inline import) was caught and fixed.

## 30-second user check BEFORE starting S82b work
Open https://portal.aigovern.sandboxhub.co/ai-systems, log in, confirm both
`sys-vendor-risk-ext-001` and `sys-vendor-risk-int-001` appear in the list
with `inherent_risk=HIGH` and `runtime_status=DESIGN`. If either is missing,
the bootstrap failed silently on prod (check `az webapp log tail` for `vendor_risk bootstrap` log lines). Local calibration succeeded — prod
mismatch would indicate an environmental difference (e.g. data dir
permissions, DATA_ROOT env var).

## Decisions already made — don't re-litigate (from execution contract)
- Agent name: `vendor_risk` (underscore, Python-importable). Display: "Vendor Risk Analyzer".
- Two AI Systems: `sys-vendor-risk-ext-001` (Anthropic) + `sys-vendor-risk-int-001` (local-deterministic).
- finadvice stays `demo_only=True` cautionary contrast.
- Pilot is synthetic (no calendar wait) — 50 invocations against fixtures during Phase 10.
- Pilot cohort: solo (you).
- Eval iteration cap: max 3 lock attempts.
- Cost ceiling per session: $20 in Anthropic API calls.
- Self-attestation roles documented as "Praveen Kosuri (acting as <role>)".

## S82b scope — Phase 2 (Design Review) + Phase 3 (Runtime Spec)

### Deliverables
- `docs/sop-vendor-risk/02-design-review.md` — model choice rationale, autonomy ceiling lock (ADVISORY + HITL_ESCALATION), data-flow diagram (vendor PDF → parse → scrub → RAG → LLM → output), tool inventory (6 tools with side_effect + authorization_required + rate_limit), isolation boundary, kill-switch design.
- `policies/vendor-risk-ext.rego` — rules for external system (DENY if INTERNAL_SYSTEMS or MNPI tokens detected, DENY if operator role not in allowlist, DENY if prompt > 32K tokens, DENY if injection_score > 0.7).
- `policies/vendor-risk-int.rego` — rules for internal system (REQUIRE allowed role, REQUIRE network_egress_lock=engaged, DENY external URL patterns in tool args).
- Both rego files sha256-pinned in policy registry; verify-loaded at engine startup.
- `tests/test_policy_vendor_risk.py` — negative-test DENY + positive-test ALLOW for each rule. Run in CI per `[[rego-files-were-decorative]]`.
- `docs/sop-vendor-risk/03-control-coverage.md` — matrix mapping each P0/P1 gate from S82a's intake to the runtime mechanism (rego rule, decorator, scrubber config, telemetry destination).

### Exit criteria
- Both rego files load on engine startup (sha256 confirmed in log)
- CI tests pass for both positive (ALLOW) and negative (DENY) cases per rule
- Control coverage matrix has zero unmapped P0/P1 controls (waivers explicitly documented with expiry)

### What you can run after S82b
- `curl -X POST .../agent-runner/run -d '{adversarial}'` → policy DENY observable in chain.start → chain.done short-circuit (still no agent body — just the perimeter)

### Estimated session size
~300K tokens (Architecture band, Normal). 8 P0/P1 gates to map, 2 rego files to author, ~6 negative/positive test cases per file. No external API calls.

## Key files to load at start of S82b
- `docs/SOP-agent-onboarding.md` — Phase 2 + Phase 3 sections
- `docs/plans/SESSION-82-vendor-risk-sop.md` — full arc
- `docs/sop-vendor-risk/00-intent.md` + `01-intake-receipt-*.md` — Phase 0/1 context
- `policies/` — existing rego files for pattern reference
- `agents/azure-architect/policies/` if exists — established agent-policy precedent
- `domain/policy_engine.py` — policy load + evaluate path
- `agents/vendor_risk/onboarding/intake_payload_*.json` — Phase 1 payload baselines (Phase 2 design must reflect what was declared at intake)

## Working rules in effect (memory pointers)
- `[[rego-files-were-decorative]]` — first test for any new policy file MUST be a negative-test DENY against a live call. Don't trust "the file loaded" as proof of enforcement.
- `[[grep-all-consumers-before-contract-flip]]` — when extending the policy enforcement contract, sweep all consumers.
- `[[bare-except-hides-broken-integrations]]` — policy engine errors → default DENY, never ALLOW (already canonical in project CLAUDE.md).
- `[[smoke-scripts-must-run-live-before-declaring-done]]` — S82a caught the inline-import bug via this rule. S82b should run the rego enforcement against a real curl before exit.

## Resume prompt (paste into a fresh Claude Code conversation in C:\ai-assurance-mvp\)

```
Resume vendor_risk SOP execution at S82b (Phase 2 Design Review +
Phase 3 Runtime Spec). Full plan in
docs/plans/SESSION-82-vendor-risk-sop.md. Handoff context in
docs/plans/HANDOFF-S82b-resume.md.

S82a is complete (commit 2445a6f live on prod). Both AISystem rows
(sys-vendor-risk-ext-001 with 11 gates / 2 blocking, sys-vendor-risk-int-001
with 15 gates / 5 blocking) are persisted via the canonical intake
pipeline through a lifespan bootstrap.

Start by reading the handoff doc, then read docs/SOP-agent-onboarding.md
Phase 2 and Phase 3 sections, then read the intake receipts to know which
gates need to be mapped to runtime mechanisms. Then execute S82b per the
plan — author design review doc, author both rego files, write negative/
positive tests, write control coverage matrix, verify rego loads
trigger DENY on adversarial input via live curl, commit, push, verify on
prod, write S82c handoff.

Same execution contract as S82a: self-attested roles, $20 API cost
ceiling, push to main without per-step approval, pause only on hard
blockers per the guardrails list. Use TaskCreate to track the S82b
sub-tasks.

Proceed.
```
