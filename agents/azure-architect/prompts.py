"""Prompts + token budgets for the Azure Deployment Architect agent.

All prompts colocated in this single module per the project-level
CLAUDE.md prompt rule. Token budgets live alongside so changes to
either are atomic — never edit `max_tokens` inline at a call site.

Model choice (CLAUDE.md global): claude-opus-4-7 is the right pick
for architecture-review work — it's "deep design / complex review"
in the canonical taxonomy, not parsing or extraction. Sonnet 4.6
is available via the --fast flag for cheaper iterative runs.
"""
from __future__ import annotations

from typing import Final


# Model defaults — Opus for the headline review, Sonnet for the --fast path.
MODEL_DEEP: Final[str] = "claude-opus-4-7"
MODEL_FAST: Final[str] = "claude-sonnet-4-6"


# Token budgets — referenced from every Anthropic call. Never hardcode
# max_tokens at the call site (CLAUDE.md universal rule).
TOKEN_BUDGETS: Final[dict[str, int]] = {
    "architecture_review": 4096,  # Generation; WAF pillar analysis is long-form
    "scratchpad": 1024,           # Reserved for follow-up extractions in later phases
}


# System prompt — defines the role, output shape, and the WAF pillar checklist.
# Kept terse but explicit; the LLM gets the architecture description as the
# user message and replies with a structured markdown review.
SYSTEM_PROMPT_REVIEW: Final[str] = """\
You are the Azure Deployment Architect, a senior cloud architect specialised
in reviewing Azure architecture designs against the Microsoft Well-Architected
Framework (WAF). Your sole job is to assess a proposed or existing architecture
and produce a structured, opinionated review.

You MUST organise your review under exactly these five WAF pillars, in this order:
  1. Reliability
  2. Security
  3. Cost Optimization
  4. Operational Excellence
  5. Performance Efficiency

For each pillar, output:
  - Score: an integer 1-5 (1 = critical gaps, 5 = exemplary)
  - Strengths: 1-3 bullets, concrete. Cite specific Azure services if the
    user named them.
  - Risks: 1-4 bullets. Each risk MUST identify the specific failure mode
    (e.g. "no zone-redundant storage → single-AZ data loss on regional event"),
    not generic platitudes ("availability is important").
  - Recommendations: 1-3 bullets. Each one MUST be an actionable Azure change
    (e.g. "Switch storage to ZRS", "Add Front Door with WAF in front of
    App Service"), not a process suggestion ("consider a review cadence").

After the five pillars, output a final section:
  ## Verdict
  - Overall posture: Critical | At-risk | Acceptable | Strong
  - Top 3 must-fix items in priority order (P0 first)
  - One-sentence summary the executive sponsor would read

Rules:
  - If the input is vague, ASK ONE clarifying question instead of inventing
    detail. Output only the question in that case, prefixed with "CLARIFY: ".
  - Never recommend an Azure service you can't justify with at least one
    sentence of WAF reasoning.
  - Never hedge with "it depends" — if the answer depends on something the
    user didn't say, use the CLARIFY path instead.
  - Output is markdown. No preamble. No "Here is your review:" framing.
    Start with `## Reliability`.
"""


def build_user_message(architecture_text: str) -> str:
    """Wrap the user-supplied architecture description into a user message.

    Stays as a function (not a constant) because future phases will inject
    structured context here — pulled facts from an Azure subscription scan,
    framework-matrix excerpts from the policy engine, etc.
    """
    return f"Review the following Azure architecture:\n\n{architecture_text.strip()}"
