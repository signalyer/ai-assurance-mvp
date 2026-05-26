"""Render Mermaid diagram source to SVG.

Two backends supported (decision deferred to P4 Day-3):
    1. Local `mermaid-cli` (npm `@mermaid-js/mermaid-cli`) — fast, offline,
       no network egress, but adds a node-runtime dependency to the agent.
    2. Hosted `kroki.io` — zero deps, but every render hits a third-party.
       Mermaid source may contain inferred resource names; treat as PII-
       adjacent and prefer (1) unless explicitly waived.

Default in S55-prep skeleton: option (1). The agent's policy MUST forbid
sending un-scrubbed Mermaid source to kroki.io — that's an OPA rule, not
a code rule. See `policies/azure-architect.rego`.
"""

from __future__ import annotations

from .schemas import MermaidRenderOut


async def render_mermaid_diagram(source: str) -> MermaidRenderOut:
    """Compile Mermaid source to SVG via mermaid-cli.

    P4 Day-3 deliverable. The compile-or-not signal IS the eval metric —
    `mermaid_compiles_metric.py` reads `parse_ok` from this exact return.

    Args:
        source: Mermaid diagram source (graph TD, graph LR, etc.).

    Returns:
        MermaidRenderOut with `parse_ok=True, svg=<bytes>` on success or
        `parse_ok=False, error=<str>` on parse failure.
    """
    raise NotImplementedError("P4 Day-3 — shell out to `mmdc -i - -o -`; capture stderr on non-zero exit")
