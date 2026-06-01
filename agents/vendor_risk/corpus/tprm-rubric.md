# TPRM Risk Tier Rubric

## Tier Definitions

### LOW
No material concerns. All P0 documents current. Subprocessor risk scores all
below 30. No PII or restricted data in scope. No carve-outs. No conflicts.

### MEDIUM
1-3 documented gaps that can be remediated. Examples:
- Stale ISO certificate where SOC2 is current (partial compensating control).
- DPA-bound PII processing where everything else is clean (PII scope alone
  bumps an otherwise-LOW vendor to MEDIUM).
- Single missing optional document (BCP, pentest summary).

### HIGH
Any one of:
- DPA carve-out detected.
- Conflicting clauses between DPA and MSA.
- Adversarial signal in vendor documents (prompt injection, Type I/II
  confusion, ambiguous encryption claims).
- Subprocessor with known_issues entry.
- Internal system integration.

### CRITICAL
Residual risk remains CRITICAL after proposed mitigations. Examples:
- Material non-public information (MNPI) exposure that cannot be mitigated
  by contract.
- Vendor unable to provide SOC2 Type II AND ISO 27001 AND no compensating
  pentest evidence.
- Subprocessor risk_score > 80 with no alternative.

## Decision Rules
- A LOW finding does NOT downgrade an otherwise-MEDIUM tier (concerns are
  additive in severity, not averaged).
- A single HIGH-severity concern sets the tier to HIGH minimum.
- Mitigations downgrade RESIDUAL tier, not INHERENT tier — surface both
  when they diverge.
