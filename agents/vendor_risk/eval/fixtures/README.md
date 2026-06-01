# Vendor package fixtures

One directory per case `input_vendor_package_ref` from
`dataset-external.jsonl` + `dataset-internal.jsonl`. Each fixture is the
analog of a real vendor onboarding package: SOC 2, ISO cert, DPA, MSA,
subprocessor list, optional pentest/BCP/insurance.

S82c authors 4 sample fixtures only (`01-clean-saas`, `05-edge-carveout-eu`,
`08-adv-pdf-injection`, `11-mnpi-deal-context`) — enough to test the
runner's path resolution. The remaining 14 are authored in S82e (Phase 6
iteration), which is also when the corpus body is written. Until then,
those case rows resolve to `_missing/` and the runner will surface a
clear "fixture not found" failure when --null-baseline is dropped.

## Fixture layout convention

```
<package_ref>/
├── README.md           # human-readable summary of the vendor + scenario
├── soc2.txt            # SOC2 report excerpt (Type II unless category=adversarial)
├── iso27001.txt        # ISO 27001 cert excerpt + expiry date
├── dpa.txt             # DPA / SCC text
├── msa.txt             # MSA excerpt
├── subprocessors.json  # subprocessor list
└── meta.json           # category, expected output anchors, adversarial notes
```

## Why text and not real PDFs

PDFs add parser dependency surface. The agent's `parse_vendor_document`
tool will pre-process real PDFs in production; the eval harness uses
text fixtures so the metric scorers are deterministic. Real-PDF
adversarial parsing is its own eval lane (added in S82e).
