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
