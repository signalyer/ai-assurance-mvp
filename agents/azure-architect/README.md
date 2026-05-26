# Azure Deployment Architect

**Workload-track agent built against the AI Assurance Platform (aigovern.sandboxhub.co) as the V1→V2 dogfood POC.**

Reads a target Azure subscription via ARM read APIs, walks every resource group, infers relationships (private endpoints, peering, role assignments), returns a logical architecture diagram (Mermaid + SVG) and a per-resource configuration JSON manifest.

- **Autonomy:** `draft` (produces documents for human review; no writes against Azure)
- **Models:** Claude Opus 4.7 (synthesis) · Claude Haiku 4.5 (per-resource summarization)
- **Tools:** 6 ARM read tools — see `tools/arm_read.py`
- **Risk classification (expected):** MEDIUM

## Risk classification — engine output

> _Populated from the live wizard panel in P1 (intake). Paste the engine's rationale verbatim, not a paraphrase._

- **Inherent risk:** _<from wizard>_
- **Driver factors:** _<from wizard>_
- **Required gates:** _<from wizard>_
- **AI System ID:** _<from wizard redirect URL>_

## POC phase log

Each phase exit-gate output is captured here as the runbook (`docs/plans/AZURE-ARCHITECT-POC.md`) closes.

- [ ] P1 — Intake
- [ ] P2 — SDK onboarding
- [ ] P3 — Governance scaffolding
- [ ] P4 — Agent core dev
- [ ] P5 — Memory + RAG
- [ ] P6 — Evaluation suite
- [ ] P7 — Adversarial probing
- [ ] P8 — Release gates
- [ ] P9 — Runtime readiness
- [ ] P10 — CISO sign-off

## Repository layout

```
agents/azure-architect/
├── README.md                       # this file
├── pyproject.toml
├── agent.py                        # entry point (decorator stack from SDK)
├── tools/
│   ├── arm_read.py                 # 6 ARM read tools
│   ├── mermaid_render.py           # diagram renderer
│   └── schemas.py                  # Pydantic v2 return schemas
├── prompts/
│   ├── system.md                   # Opus synthesis prompt
│   └── per_resource.md             # Haiku per-resource prompt
├── eval/
│   ├── dataset.jsonl               # 5 worked-example manifests
│   └── mermaid_compiles_metric.py  # custom DeepEval metric
├── policies/
│   └── azure-architect.rego        # OPA read-only allowlist
├── examples/                       # P4 exit-gate outputs (2 topologies)
├── CHANGELOG.md                    # P6 prompt-iteration log
├── SECURITY.md                     # P7 adversarial mitigations
├── EXCEPTIONS.md                   # P8 release-gate waivers
└── .env.example                    # placeholders only; .env never committed
```

See `docs/plans/AZURE-ARCHITECT-POC.md` for the full P1-P10 runbook.
