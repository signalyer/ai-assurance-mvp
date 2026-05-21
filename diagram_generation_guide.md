# Architecture Diagram Generation in Claude Code
# Project: AI Assurance Platform — aigovern.sandboxhub.co

---

## THE DIRECT ANSWER

No single MCP gives you exactly what you see in that image natively inside Claude Code.
That image was generated in Claude chat (this interface) using the SVG/HTML visualizer.

In Claude Code, you have three realistic options ranked by output quality vs setup cost:

---

## OPTION 1 — draw.io MCP (closest to that image, editable)
Recommended. Gives you polished, exportable, editable diagrams.

### What it produces
- Full draw.io XML diagrams opened in diagrams.net
- Exportable to PNG, SVG, PDF
- Editable by hand after generation
- Closest visual quality to the image in your upload

### Setup (Claude Code)
```bash
# 1. Install the draw.io MCP
npm install -g @jgraph/drawio-mcp

# 2. Add to ~/.claude/claude_desktop_config.json
{
  "mcpServers": {
    "drawio": {
      "command": "drawio-mcp"
    }
  }
}

# 3. Add project instructions for Claude Code
# Create .claude/commands/diagram.md in your repo (see below)
```

### Claude Code prompt (after MCP installed)
```
Read ARCHITECTURE.md in full.

Generate a draw.io architecture diagram of the complete AI Assurance Platform
showing all six layers:
1. Organizational layer (planned — risk inventory, governance body, RACI)
2. Enterprise AI Control Plane (built components + PII scrubbing pipeline in-progress)
3. Four-tier agent memory (planned — Tiers 1-4, agent_memory.py, rag_engine.py)
4. Runtime layer (built — Langfuse, DeepEval 6-metric, decorator chain)
5. LLM abstraction (Claude + GPT-4o-mini)
6. Six-layer guardrails stack (L1-L6)

Use this colour scheme:
- Built: #5DCAA5 (teal green)
- In progress: #8B5CF6 (purple, dashed border)
- Planned: #EF4444 (red)
- Structural/always-on: #9CA3AF (grey)

Layout: vertical stack, left sidebar shows layer labels (Org / System / Runtime).
Include a legend. Include the restore() vault arrow on the right side.
Save to docs/diagrams/aigovern-architecture.drawio
```

---

## OPTION 2 — Mermaid → Excalidraw MCP (fastest setup, good quality)

### What it produces
- Excalidraw .excalidraw.md files (open in Obsidian or excalidraw.com)
- Token-efficient: Claude writes 30-50 tokens of Mermaid, tool converts to styled diagram
- Editable canvas output
- Slightly less control over exact visual styling than draw.io

### Setup
```bash
# Clone and build the MCP
git clone https://github.com/yannick-cw/mermaid-to-excalidraw-mcp
cd mermaid-to-excalidraw-mcp
npm install && npm run build

# Add to ~/.claude/claude_desktop_config.json
{
  "mcpServers": {
    "mermaid-excali": {
      "command": "node",
      "args": ["/absolute/path/to/mermaid-to-excalidraw-mcp/dist/index.js"]
    }
  }
}
```

### Claude Code prompt
```
Read ARCHITECTURE.md.

Generate a Mermaid architecture diagram of the AI Assurance Platform.
Use the flowchart TD (top-down) type.
Group components into subgraphs matching the six layers.
Apply these styles:
- Built components: fill:#5DCAA5,color:#fff
- In-progress: fill:#8B5CF6,color:#fff,stroke-dasharray:5
- Planned: fill:#EF4444,color:#fff
- Structural: fill:#9CA3AF,color:#fff

Convert to Excalidraw and save to docs/diagrams/aigovern-architecture.excalidraw.md
```

---

## OPTION 3 — Self-contained HTML (no MCP, works today, matches the image exactly)

This is what was used to generate all diagrams in this chat session.
Claude Code can write the same HTML files directly — no MCP needed.
The output is a standalone HTML file you open in a browser and screenshot or print to PDF.

### Claude Code prompt (no setup required)
```
Read ARCHITECTURE.md in full.

Generate docs/diagrams/aigovern-architecture.html as a self-contained HTML file.

Requirements:
- Recreate the architecture diagram exactly as described in ARCHITECTURE.md
- Six vertical layers with the same colour scheme from the legend:
  Built=#5DCAA5, InProgress=#8B5CF6 dashed, Planned=#EF4444, Structural=#9CA3AF
- Left sidebar layer labels: Org / System / Runtime
- Include a restore() vault dashed arrow on the right side
- Legend in top-left corner
- Font: IBM Plex Sans + IBM Plex Mono (Google Fonts)
- Dark background (#0a0c0f) matching the existing HTML artifacts
- Self-contained: all CSS inline, no external dependencies except Google Fonts
- Print-to-PDF ready: @media print styles included

After generating:
1. Verify the file opens in a browser: open docs/diagrams/aigovern-architecture.html
2. Check all six layers render with correct colours
3. Confirm legend matches ARCHITECTURE.md status categories
```

### Why this works without MCP
Claude Code can write arbitrary HTML/CSS/SVG files to disk.
The HTML visualizer I used in chat produces the same output format.
You open the file in Chrome → Print → Save as PDF → done.
Quality: identical to the image you uploaded.

---

## OPTION 4 — Mermaid in Markdown (simplest, worst visual quality)

Not recommended for the image quality you want.
Mermaid renders as code diagrams — functional but not polished.
Include only for completeness.

```bash
# Claude Code writes this natively without any MCP
# Just ask: "Generate a Mermaid diagram of the architecture and save to docs/ARCHITECTURE.mmd"
```

---

## COMPARISON

| Option       | Setup    | Visual quality | Editable | Exportable | MCP needed |
|--------------|----------|----------------|----------|------------|------------|
| draw.io MCP  | Medium   | ★★★★★         | ✓ canvas | ✓ PNG/SVG  | ✓ yes      |
| Mermaid→Excalidraw | Medium | ★★★★      | ✓ canvas | ✓          | ✓ yes      |
| HTML/SVG     | None     | ★★★★★         | ✗ code   | ✓ PDF      | ✗ no       |
| Mermaid only | None     | ★★☆           | ✗ code   | ✓ image    | ✗ no       |

---

## RECOMMENDATION FOR AIGOVERN

**Right now**: Use Option 3 (HTML). Zero setup. Claude Code generates the file,
you open it in Chrome, print to PDF. Matches the image quality exactly.
Add this to CLAUDE.md:

```markdown
## Diagram generation
When asked to generate an architecture diagram:
1. Read ARCHITECTURE.md in full first
2. Generate docs/diagrams/<name>.html as self-contained HTML
3. Use IBM Plex Sans + Mono fonts, dark background (#0a0c0f)
4. Colours: Built=#5DCAA5, InProgress=#8B5CF6 dashed, Planned=#EF4444, Structural=#9CA3AF
5. Match the six-layer structure in ARCHITECTURE.md exactly
6. Open and visually verify before marking done
```

**After Session 1 (scrubber build) is done**: Add draw.io MCP.
Gives you editable diagrams that update as the codebase changes.
The workflow becomes: Claude Code reads ARCHITECTURE.md → generates .drawio →
you open in diagrams.net → export PNG for presentations.

---

## CLAUDE CODE SKILL FILE (add to .claude/skills/diagram.md)

```markdown
# Skill: Architecture Diagram Generation

When asked to generate or update the architecture diagram:

1. Always read ARCHITECTURE.md first — it is the source of truth
2. Generate docs/diagrams/aigovern-architecture.html (self-contained HTML)
3. Colour scheme (mandatory):
   - Built: background #5DCAA5, text white
   - In progress: background transparent, border #8B5CF6 dashed, text #8B5CF6
   - Planned: background transparent, border #EF4444 dashed, text #EF4444
   - Structural/always-on: background #9CA3AF, text white
4. Layer structure (top to bottom):
   - Org layer (left label: "Org")
   - System layer containing: Enterprise Control Plane + PII Pipeline + Agent Memory (left label: "System")
   - Runtime layer (left label: "Runtime")
   - LLM abstraction
5. Right side: dashed restore() arrow from LLM abstraction back up to PII scrubbing layer
6. Top-left legend: Built / In progress / Planned / Structural
7. After generating: open docs/diagrams/aigovern-architecture.html in browser to verify
8. Update the diagram any time ARCHITECTURE.md changes
```
