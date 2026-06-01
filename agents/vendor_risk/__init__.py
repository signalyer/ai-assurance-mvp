"""vendor_risk agent — Third-party vendor risk assessment for TPRM onboarding.

Onboarded via the canonical SOP (docs/SOP-agent-onboarding.md). See
docs/plans/SESSION-82-vendor-risk-sop.md for the 9-session execution arc.

Two AI systems back this agent:
  - sys-vendor-risk-ext-001: Anthropic cloud LLM, vendor-disclosed data only
  - sys-vendor-risk-int-001: local deterministic, no external network egress

Bootstrap (agents/vendor_risk/onboarding/bootstrap.py) ensures both system
rows exist in data/ai_systems.jsonl on engine startup, going through the
real intake pipeline (api.intake.submit_intake) rather than a hand-written
seed row. See [[agent-default-system-id-needs-seed]] and the S81b finadvice
backfill for why this matters.
"""
from __future__ import annotations
