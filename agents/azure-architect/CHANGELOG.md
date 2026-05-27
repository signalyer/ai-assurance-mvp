# Changelog — Azure Deployment Architect

P6 (Evaluation suite) discipline: every prompt iteration is logged here with
before/after scores against `eval/dataset.jsonl`. The platform's eval card
links back to commit SHAs that touched `prompts/system.md` or
`prompts/per_resource.md`, so this log is the cross-reference.

Format per entry:

```
## YYYY-MM-DD · commit <sha> · <prompt-file>
**Change:** one sentence
**Before:** hallucination=X relevancy=X faithfulness=X pii_leakage=X mermaid_compiles=X/5
**After:**  hallucination=X relevancy=X faithfulness=X pii_leakage=X mermaid_compiles=X/5
**Rationale:** what the prior version got wrong on which dataset row
```

---

_(First entry written during P6 calibration.)_

## 2026-05-27 · working tree · eval/run_eval.py
**Change:** Added the offline P6 eval runner around the existing manifest dataset and Mermaid compile metric.
**Before:** hallucination=N/A relevancy=N/A faithfulness=N/A pii_leakage=N/A mermaid_compiles=metric-only
**After:**  schema_valid, diagram_expected_terms, manifest_coverage, expected_notes, no_pii_leakage, and mermaid_compiles are scored per dataset row; run summaries persist to JSONL.
**Rationale:** The dataset and custom metric existed, but there was no repeatable way to score candidate outputs, persist run history, or fail missing/malformed outputs before live P4 agent output is available.

## 2026-05-27 · working tree · tests/test_azure_architect_eval.py
**Change:** Added edge-case tests for strict schema extras, PII leakage, required broken-topology notes, duplicate candidate rows, and Mermaid compile failures.
**Before:** edge-case coverage=missing
**After:**  edge-case coverage=5 explicit cases; total focused tests=9
**Rationale:** The runner should fail loudly when output is malformed, unsafe, stale, or unparsable even if the happy path looks clean.
