# Phase 0 — Intent & Pre-Intake — vendor_risk

**SOP reference:** [docs/SOP-agent-onboarding.md](../SOP-agent-onboarding.md) · Phase 0
**Session:** S82a (Block A — Specs before code)
**Date:** 2026-06-01
**Owner attestation:** Praveen Kosuri (acting as Business Owner + Operator)

## Use case (one paragraph)

The internal Third-Party Risk Management (TPRM) team performs a structured
risk assessment on every new vendor before contract signing. Today this is
a 5-day cross-functional workflow involving security review, privacy review,
contract review, and a final risk rating. `vendor_risk` is an advisory
agent that ingests a vendor's submitted onboarding package (security
questionnaire, SOC 2 Type II, ISO 27001 cert, DPA, subprocessor list,
optional pentest + BCP + insurance) and produces a structured risk
assessment with per-category risk tiers, specific concerns with source
citations, required mitigations, contract clause requirements, and an HITL
escalation when residual risk exceeds threshold. The agent does not
auto-approve vendors; humans always make the final call.

## Measurable success criterion

- **Primary:** Reduce mean cycle time from "vendor package received" to
  "structured risk assessment ready for human reviewer" from 5 business
  days to 4 hours.
- **Secondary:** Achieve ≥90% inter-rater agreement between agent output
  and human reviewer on the locked eval dataset (Phase 4).
- **Floor (non-negotiable):** Zero PII leakage to external LLM provider
  across all runs. Zero false-approval on cases that should HITL-escalate.

## Regulatory exposure forecast

Coded into the platform via `RegulatoryExposure` enums:
- **SOX** — vendor IT general controls flow through to internal SOX scope
- **GLBA** — vendor handling of customer non-public personal information
- **FFIEC Appendix J** — third-party risk management for FFIEC-supervised entities
- **GDPR Art. 28** — data processor obligations + DPA requirements
- **CCPA** — service provider classification + contractual restrictions

Additional un-coded dimensions documented for human awareness (not enum-mapped):
- **EU DORA Art. 28-30** — ICT third-party risk for EU financial entities
- **NYDFS Part 500.11** — third-party service provider security policy
- **HIPAA Business Associate Agreement** — when vendors process PHI

The agent must support the coded enums in its output; the un-coded
dimensions appear as free-text concerns in the assessment.

## Build-vs-buy decision

Considered:
- **OneTrust Vendorpedia / Prevalent / BitSight** — commercial TPRM platforms
  that include some AI assist. Rejected for this demo because (a) we need
  the agent to be governed by SignalLayer's own platform end-to-end, which
  external tools defeat; (b) commercial tools are opaque about their
  prompting + retrieval, which contradicts the platform's transparency
  premise.
- **Internal build** — chosen. The build itself becomes the canonical SOP
  execution exemplar. The agent ships as `agents/vendor_risk/` and is
  governed by `sys-vendor-risk-ext-001` (external cloud LLM path) and
  `sys-vendor-risk-int-001` (internal-only on-prem path).

## Stakeholder sign-off

| Role | Sign-off | Date | Notes |
|---|---|---|---|
| Business Owner | Praveen Kosuri | 2026-06-01 | Self-attested; solo demo scale |
| Technical Owner | Praveen Kosuri | 2026-06-01 | Self-attested |
| CISO | Praveen Kosuri | 2026-06-01 | Self-attested; full attestation in Phase 2 |
| Compliance | Praveen Kosuri | 2026-06-01 | Self-attested; control coverage in Phase 3 |

Solo-role limitation explicitly acknowledged. The SOP doc artifacts shape
the audit trail; the role labels mark which lens applied to each decision.

## Expected autonomy ceiling

**ADVISORY + HITL_ESCALATION**. The agent produces recommendations and
calls a side-effect `escalate_to_human` tool when residual risk crosses
threshold. Humans approve every onboarding decision. The agent never
auto-approves or auto-rejects a vendor.

## Two-system deployment posture

| System | Provider | Data Classification | Use Case |
|---|---|---|---|
| `sys-vendor-risk-ext-001` | Anthropic (cloud) | Vendor-disclosed documents only (`PUBLIC` + `INTERNAL`) | Standard analysis where input is vendor's own disclosures, already shared with the vendor; safe to send to external LLM |
| `sys-vendor-risk-int-001` | Local deterministic | `PII`, `NPI`, internal system references, MNPI scope | Analysis requires referencing OUR confidential context (our customer data classes, our internal system inventory, M&A pipeline vendors). Prompt never leaves the network. |

Routing decision is data-classification driven: the `policy_gate` reads
`scrub_pii` output and routes to the internal system when sensitive token
types are detected.

## Exit criteria for Phase 0

- This document committed
- Stakeholder list complete (even if all self-attested)
- Use case + success criterion expressible to a non-engineering reviewer
- Regulatory exposure enumerated and split into coded vs un-coded

✅ All criteria met by this document.

## Next phase

[Phase 1 — Intake & Classification](01-intake-receipt-ext.md) (also S82a)
