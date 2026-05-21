Read ARCHITECTURE.md in full.
Generate docs/diagrams/aigovern-architecture.html.

Requirements:
- Self-contained HTML, IBM Plex Sans + Mono from Google Fonts
- Dark background #0a0c0f
- Six vertical layers matching ARCHITECTURE.md exactly:
    Layer 1: Organizational (Org sidebar label)
    Layer 2: Enterprise AI Control Plane (System sidebar label)
    Layer 3: PII / IP / Secret Scrubbing Pipeline (System)
    Layer 4: Four-tier agent memory (System)
    Layer 5: Runtime (Runtime sidebar label)
    Layer 6: LLM abstraction
- Colour scheme:
    Built:        background #5DCAA5, text white
    In progress:  transparent, border #8B5CF6 dashed 2px, text #8B5CF6
    Planned:      transparent, border #EF4444 dashed 2px, text #EF4444
    Structural:   background #9CA3AF, text white
- Legend top-left (Built / In progress / Planned / Structural)
- restore() dashed arrow on right side, from LLM abstraction back to PII layer
- Print-to-PDF ready (@media print rules, page-break-inside: avoid)

After generating:
1. Open docs/diagrams/aigovern-architecture.html
2. Verify every component in ARCHITECTURE.md "Built / In Progress / Planned"
   lists is represented on the diagram
3. Report any discrepancies — file in ARCHITECTURE.md but not on diagram, or vice versa
