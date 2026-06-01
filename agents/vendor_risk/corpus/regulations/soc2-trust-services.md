# SOC 2 Trust Services Criteria — Type I vs Type II

## Type I vs Type II
- **Type I**: Description of controls AT A POINT IN TIME. Lower assurance.
  Adequate for early-stage vendors but never a substitute for Type II in
  production onboarding.
- **Type II**: Description of controls AND TEST OF OPERATING EFFECTIVENESS
  over a period (typically 6-12 months). Required by TPRM Policy v3.2 for
  MEDIUM and above.

## Detection
- A SOC2 report whose audit period is a single date is TYPE I.
- A SOC2 report claiming "Type II" but with no observation window is
  ambiguous and must be flagged.

## TPRM Verification
- If a vendor presents Type I where Type II is required, downgrade trust
  and flag as a HIGH adversarial-signal concern.
