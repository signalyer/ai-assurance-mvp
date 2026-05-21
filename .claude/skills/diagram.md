# Skill: Architecture Diagram Generation

When asked to generate or update the architecture diagram:

1. Read ARCHITECTURE.md in full — it is the source of truth
2. Generate docs/diagrams/aigovern-architecture.html
3. Self-contained HTML — IBM Plex Sans + Mono from Google Fonts
4. Dark background: #0a0c0f

## Colour scheme (mandatory)

| Status       | Background | Border             | Text     |
|--------------|------------|--------------------|----------|
| Built        | #5DCAA5    | none               | white    |
| In progress  | transparent| #8B5CF6 dashed 2px | #8B5CF6  |
| Planned      | transparent| #EF4444 dashed 2px | #EF4444  |
| Structural   | #9CA3AF    | none               | white    |

## Layer structure (top to bottom)

- **Layer 1 — Organizational** (Org label, left sidebar)
  - 4 boxes: Risk inventory · Governance body · RACI · Regulatory posture (all Planned)
- **Layer 2 — Enterprise AI Control Plane** (System label)
  - Row 1: AI Gateway · Policy/Guardrail Engine · Agent Tool Registry/RBAC · Usage/Cost/Rate Controls (Built)
  - Row 2: Eval & Testing Service · Observability & Audit · Release Gates / Assessment Engine (Built / Built-leaky / Built)
  - Row 3: PII/IP/Secret Scrubbing Pipeline wide box (In progress) — scrubber.py · deid_vault.py · @scrub_pii
- **Layer 3 — Four-tier agent memory** (System label continues)
  - 4 tier boxes: T1 In-context (Planned) · T2 Episodic (Planned) · T3 RAG (Planned) · T4 Procedural (Built)
  - Wide box: agent_memory.py (Planned)
  - Wide box: rag_engine.py (Planned)
- **Layer 4 — Runtime** (Runtime label)
  - 3 boxes: Langfuse Cloud (Built, ⚠ leaky) · DeepEval 6-metric (In progress, 5→6) · Decorator chain (In progress)
- **Layer 5 — LLM abstraction** (amber #F59E0B fill)
  - Claude + GPT-4o-mini + Bedrock · "No PII / secrets / IP crosses this boundary"

## Right side
Dashed restore() arrow from LLM abstraction layer back up to PII scrubbing layer.

## Top-left
Legend showing the 4 statuses with their colour swatches.

## Bottom
Build plan summary text: current session, next session, blockers.

## After generating
- Open docs/diagrams/aigovern-architecture.html in browser
- Verify all layers match ARCHITECTURE.md state
- Report any discrepancies
