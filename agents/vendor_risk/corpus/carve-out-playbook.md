# DPA Carve-Out Detection Playbook

A "carve-out" is any clause in a Data Processing Agreement that excludes one
or more subprocessors from the obligations of the parent DPA — most
commonly SCC (Standard Contractual Clauses) obligations under GDPR Article 28.

## Detection Patterns
Carve-outs are usually hidden in DPA exhibits, not the main body. Look for:
- "Notwithstanding Section X, the following subprocessors are excluded from..."
- "The following entities are out of scope for SCC obligations:..."
- A subprocessor list with a footnote referencing different governing terms.
- An exhibit listing subprocessors with country codes that do NOT have a
  corresponding SCC row.

## Required Action
Carve-outs ALWAYS:
1. Surface as a concern citing this playbook AND the relevant SCC framework.
2. Trigger HITL escalation via escalate_to_human.
3. Result in a tier of at least HIGH.

A carve-out is never a LOW or MEDIUM finding regardless of the subprocessor's
own risk score.
