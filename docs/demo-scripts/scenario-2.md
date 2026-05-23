# Scenario 2 — Team Payments · Gate Failure → Governance Hold → Recovery

**Audience cue:** show how a real eval regression blocks a release without a human-in-the-loop bottleneck.
**Real components exercised:** release-gate engine (`domain/release_gate_engine.py`) · DeepEval 6-metric scorer · OPA `release_approval.rego` · governance review queue.
**Duration:** ~30s.

## Talk track

"This is the Payments team's billing-classification agent. Their nightly eval suite just ran. I'll trigger the release gate against the latest scores."

"The gate fails because hallucination rate crossed the Tier B threshold for a HIGH-risk system. Notice what didn't happen: nobody got paged in the middle of the night. The system entered a governance hold automatically — an event landed on the audit chain, the policy decision is captured, and the system's status flipped from `deployable` to `hold`. The team's AI Gov lead sees a queued review the next morning, approves a waiver if appropriate, and the system moves back to `deployable`. The waiver itself becomes a versioned artifact tied to the eval run that triggered it."

## What's NOT shown

- Slack / email notifier — Phase 2.
- Auto-rollback to last-known-good version — Phase 2.

## If asked

- *"What stops a team from just approving its own waivers?"* — Org-mandatory policies in `policies/org/` require AI Gov co-signature for HIGH-risk system waivers. Same Rego file as the gate.
- *"What's the false-positive rate?"* — Calibration kappa ≥ 0.7 per scorer (sprint plan §5 Day 2). False positives are a known cost; we tune by adjusting Tier B thresholds, not by relaxing the gate.
