# Phase 1 — Intake Receipt — sys-vendor-risk-int-001

**SOP reference:** [docs/SOP-agent-onboarding.md](../SOP-agent-onboarding.md) · Phase 1
**Session:** S82a
**Date:** 2026-06-01
**Intake payload:** [agents/vendor_risk/onboarding/intake_payload_int.json](../../agents/vendor_risk/onboarding/intake_payload_int.json)
**Bootstrap:** [agents/vendor_risk/onboarding/bootstrap.py](../../agents/vendor_risk/onboarding/bootstrap.py)

## Intake submission

Same bootstrap path as the external sibling — `submit_intake()` called
programmatically with `system_id_override="sys-vendor-risk-int-001"`. The
two systems share an agent module + RAG corpus; they differ in data
classification, network egress allowance, and downstream control posture.

## Live calibration result (local engine, 2026-06-01)

```json
{
  "ai_system_id": "sys-vendor-risk-int-001",
  "assessment_id": "assess-a895dad2",
  "gate_count": 15,
  "inherent_risk": "HIGH",
  "rules_fired": ["R1", "R4", "R5"],
  "redirect_to": "/ai-systems?id=sys-vendor-risk-int-001",
  "status": "active",
  "draft_reason": null
}
```

## What the risk classifier saw

**Three** rules fired vs the external's one:
- **R1** — likely PII/NPI-handling rule (the internal system declared
  `data_classes: ["pii", "npi", "confidential", "credit_data"]`)
- **R4** — likely RAG-with-sensitive-data rule (`data_in_rag: true`)
- **R5** — same business-impact rule that fired on external

Inherent risk: **HIGH** (capped at HIGH; CRITICAL would require additional
factors like autonomous side-effects or external-facing user population —
this is internal + advisory).

## Release gates created (15 total, 5 blocking)

| Gate name | Blocking | Initial status |
|---|---|---|
| Model Inventory Required | no | NOT_RUN |
| Business Owner Required | no | NOT_RUN |
| Technical Owner Required | no | NOT_RUN |
| **Critical Findings Block Production Release** | **YES** | NOT_RUN |
| RAG Source Quarantine Required | no | NOT_RUN |
| AWS Private Connectivity for Regulated Workloads | no | NOT_RUN |
| Vector Store Access Control Required | no | NOT_RUN |
| **No Raw PII/NPI/PCI in Prompts** | **YES** | NOT_RUN |
| **DLP Before Model Context Assembly** | **YES** | NOT_RUN |
| **Tool Authorization Mandatory** | **YES** | NOT_RUN |
| No Persistent Memory for Restricted Data | no | NOT_RUN |
| Groundedness Threshold Required | no | NOT_RUN |
| Macie Scan Required for S3 / RAG Sources | no | NOT_RUN |
| Full Audit Logging Required | no | NOT_RUN |
| Evidence Immutability Required | no | NOT_RUN |

**Four additional gates** vs the external sibling:
- No Raw PII/NPI/PCI in Prompts (blocking)
- DLP Before Model Context Assembly (blocking)
- No Persistent Memory for Restricted Data (non-blocking)
- Macie Scan Required for S3 / RAG Sources (non-blocking)

All four exist because the internal system handles sensitive data classes
that the external system intentionally does not.

## Why this matters for the demo

When the chain ticker runs against `sys-vendor-risk-ext-001`, the policy
chain enforces 2 blocking gates. When the same agent code runs against
`sys-vendor-risk-int-001`, the policy chain enforces 5 blocking gates,
including DLP before model context, no raw PII in prompts, and no
persistent memory for restricted data. The differential is observable
in the chain events and in the AISystem detail drawer — the buyer's
governance team can see exactly which controls fire on each deployment
without reading code.

## Exit criteria for Phase 1 (this system)

- ✅ AISystem row persisted in `data/ai_systems.jsonl` with id `sys-vendor-risk-int-001`
- ✅ Assessment row persisted with status IN_PROGRESS, framework versions pinned
- ✅ 15 ReleaseGate rows persisted, all NOT_RUN, 5 blocking
- ✅ Inherent risk classified (HIGH), rules_fired captured (R1, R4, R5)
- ✅ Regulatory exposure mapped: SOX, GLBA, FFIEC, GDPR
- ✅ Bootstrap idempotent (verified)

## Phase 1 — both systems — combined exit gate

- ✅ Both AISystem rows live in `data/ai_systems.jsonl`
- ✅ Both Assessments IN_PROGRESS with the same framework version set
- ✅ Total 26 ReleaseGate rows across both systems, 7 blocking
- ✅ AI Systems page (after prod CD lands) will list both systems with
  real risk classifications and gate counts
- ✅ Lifespan bootstrap idempotent — verified locally by deleting + re-running

## Next phase

[Phase 2 — Design Review](02-design-review.md) (S82b)
