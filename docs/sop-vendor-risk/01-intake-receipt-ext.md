# Phase 1 — Intake Receipt — sys-vendor-risk-ext-001

**SOP reference:** [docs/SOP-agent-onboarding.md](../SOP-agent-onboarding.md) · Phase 1
**Session:** S82a
**Date:** 2026-06-01
**Intake payload:** [agents/vendor_risk/onboarding/intake_payload_ext.json](../../agents/vendor_risk/onboarding/intake_payload_ext.json)
**Bootstrap:** [agents/vendor_risk/onboarding/bootstrap.py](../../agents/vendor_risk/onboarding/bootstrap.py)

## Intake submission (canonical pipeline — `api/intake.py::submit_intake`)

The submission was made programmatically via the lifespan bootstrap, not
via the wizard SPA. The bootstrap uses `system_id_override` to produce a
deterministic system_id (`sys-vendor-risk-ext-001`) so SOP audit
references resolve across cold starts. The HTTP `/intake/submit` endpoint
does NOT expose this override — only programmatic callers can use it.

## Live calibration result (local engine, 2026-06-01)

```json
{
  "ai_system_id": "sys-vendor-risk-ext-001",
  "assessment_id": "assess-8b8a537b",
  "gate_count": 11,
  "inherent_risk": "HIGH",
  "rules_fired": ["R5"],
  "redirect_to": "/ai-systems?id=sys-vendor-risk-ext-001",
  "status": "active",
  "draft_reason": null
}
```

Note: assessment ID values vary per submission (random uuid suffix). The
prod engine will produce a different `assessment_id` on its first
bootstrap call, but the `system_id` and `gate_count` are deterministic
because they derive from the payload + risk classification.

## What the risk classifier saw

Rule R5 fired. Looking at `domain/risk_classification.py`, R5 typically
corresponds to a high-impact business workflow combined with regulated
data — appropriate for vendor risk: vendor onboarding feeds procurement
contracts that materially affect business operations.

Inherent risk: **HIGH** — vendor risk decisions are advisory but feed
contract execution that's hard to unwind.

## Release gates created (11 total, 2 blocking)

| Gate name | Blocking | Initial status |
|---|---|---|
| Model Inventory Required | no | NOT_RUN |
| Business Owner Required | no | NOT_RUN |
| Technical Owner Required | no | NOT_RUN |
| **Critical Findings Block Production Release** | **YES** | NOT_RUN |
| RAG Source Quarantine Required | no | NOT_RUN |
| AWS Private Connectivity for Regulated Workloads | no | NOT_RUN |
| Vector Store Access Control Required | no | NOT_RUN |
| **Tool Authorization Mandatory** | **YES** | NOT_RUN |
| Groundedness Threshold Required | no | NOT_RUN |
| Full Audit Logging Required | no | NOT_RUN |
| Evidence Immutability Required | no | NOT_RUN |

Both blocking gates must reach PASSED before Phase 11 release decision.
Non-blocking gates can ship as PASSED, WAIVED-with-expiry, or FAILED
(with risk acceptance).

## Why this system has FEWER gates than the internal sibling

The external system declared `data_classes: ["public", "internal"]` — no
PII, NPI, PCI, or credit data on this path. As a result, P0 controls like
"No Raw PII/NPI/PCI in Prompts," "DLP Before Model Context Assembly,"
"No Persistent Memory for Restricted Data," and "Macie Scan Required" did
not fire. The internal sibling [sys-vendor-risk-int-001](01-intake-receipt-int.md)
shows 15 gates including those four.

This differentiation is exactly the demo argument: the same agent code,
the same RAG corpus, but the data-classification posture of each deployment
drives the control set. Governance is per-deployment, not per-agent.

## Exit criteria for Phase 1 (this system)

- ✅ AISystem row persisted in `data/ai_systems.jsonl` with id `sys-vendor-risk-ext-001`
- ✅ Assessment row persisted with status IN_PROGRESS, framework versions pinned
- ✅ 11 ReleaseGate rows persisted, all NOT_RUN, 2 blocking
- ✅ Inherent risk classified (HIGH), rules_fired captured (R5)
- ✅ Regulatory exposure mapped: SOX, GLBA, FFIEC, GDPR
- ✅ Bootstrap is idempotent (verified by second-call returning "exists")

## Next phase

[Phase 2 — Design Review](02-design-review.md) (S82b)
