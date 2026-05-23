# Scenario 6 — Auditor Visit · Framework Coverage Export

**Audience cue:** the auditor wants a single artifact, today, that maps every control they care about to evidence with a verifiable hash.
**Real components exercised:** `domain/framework_coverage.py` matrix · `pdf_report.py` generators (NIST + OWASP + EU AI Act + ISO 42001 + SR 11-7 + FFIEC) · `domain/pdf_pack_base.py` shared `_PdfWriter` (new in Session 11) · SHA-256 footer.
**Duration:** ~20s.

## Talk track

"The auditor on-site asked for our NIST AI RMF coverage for the billing-classification system. One click."

"The pack you just generated is deterministic at minute granularity. The SHA-256 in the footer is the same number you'll see in our audit log for this export event — so the auditor can verify, six months from now, that the file they were handed is the file we recorded handing them. Coverage is 17 of the 20 top NIST subcategories. The 3 partials drill straight to the control that's not yet fully evidenced — no editorialization, no rounding."

"Same flow today for OWASP LLM Top 10, EU AI Act Annex IV, ISO/IEC 42001, SR 11-7, and FFIEC. The Session-11 refactor moved the shared PDF scaffolding into `domain/pdf_pack_base.py` so adding a seventh framework next quarter is a single new file, not a copy-paste."

## What's NOT shown

- Per-control evidence diff between two export dates — Phase 2.
- HIPAA / GDPR / FedRAMP / DORA packs — Phase 2 (sprint plan §8).
- External blockchain anchor for the export hash — Phase 2.

## If asked

- *"What if the auditor needs custom framework X?"* — Drop a YAML in `frameworks/` plus a generator in `pdf_report.py`. The pack base does the heavy lifting; the new generator is ~100 lines.
- *"How do you handle a control that's covered by multiple controls?"* — `framework_refs` field on every control is many-to-many. The matrix renders the union and drills to all evidence sources.
