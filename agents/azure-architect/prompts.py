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
    # S62 bump 2048 → 4096 (mid-run tool_use truncation).
    # S63 bump 4096 → 8192: with the drill-down trio live
    # (list_rgs → list_resources → get_resource_metadata × N parallel),
    # synthesis volume scales with N. Live run plan-867aa0931a0a fanned
    # 3 parallel drill-downs and hit stop=max_tokens mid-verdict-table at
    # 4096. 5-turn cap × 8192 = 40K bounded; intermediate tool turns
    # rarely exceed 500 output tokens, so the headroom is for the
    # synthesis turn specifically.
    "plan_turn": 8192,
}


# Tool specs for the Anthropic tool_use API. ONLY include tools whose bodies
# are implemented in tools/arm_read.py — the rego allowlist will deny anything
# else at runtime, so advertising un-implemented tools to the model would just
# waste turns. Add a tool here when its body lands, never before.
PLAN_TOOL_SPECS: Final[list[dict]] = [
    {
        "name": "list_resource_groups",
        "description": (
            "List every resource group in a single Azure subscription. "
            "Read-only. Returns name, location, tags, and provisioning_state "
            "for each group. Use this as the first step in any subscription "
            "audit to enumerate scope before drilling into individual resources."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "subscription_id": {
                    "type": "string",
                    "description": "Azure subscription GUID. Required.",
                },
            },
            "required": ["subscription_id"],
        },
    },
    {
        "name": "list_resources_in_group",
        "description": (
            "List every resource inside ONE resource group. Read-only. "
            "Returns id, name, type (e.g. Microsoft.Web/sites), location, "
            "sku, kind, and tags for each resource. Call this AFTER "
            "list_resource_groups to drill into a specific group — pass "
            "the resource_group name verbatim from the prior tool's output. "
            "Use this when the WAF review needs per-RG inventory (resource "
            "types, SKUs, regional spread). Do NOT call it for every RG in "
            "a large subscription — budget your remaining turns first."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "subscription_id": {
                    "type": "string",
                    "description": "Azure subscription GUID. Required.",
                },
                "resource_group": {
                    "type": "string",
                    "description": (
                        "Name of the resource group to enumerate. Must match "
                        "a name returned by a prior list_resource_groups call."
                    ),
                },
            },
            "required": ["subscription_id", "resource_group"],
        },
    },
    {
        "name": "get_resource_metadata",
        "description": (
            "Fetch the full metadata for ONE Azure resource by its ARM "
            "resource ID. Read-only. Returns id, name, type, location, "
            "resource_group, sku, tags, and the polymorphic `properties` "
            "blob (schema varies per resource type — e.g. storage account "
            "returns encryption + access tier + network rules; key vault "
            "returns soft-delete + purge protection). Call this AFTER "
            "list_resources_in_group when the WAF review needs per-resource "
            "depth: specific SKU tier, encryption posture, network exposure, "
            "soft-delete state. Pass `resource_id` verbatim from the prior "
            "tool's `id` field. Costs one extra ARM round-trip per call "
            "(provider api_version lookup) so budget your remaining turns — "
            "don't call it for every resource in a large RG."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "resource_id": {
                    "type": "string",
                    "description": (
                        "Full ARM resource ID, e.g. "
                        "/subscriptions/<sub>/resourceGroups/<rg>/providers/"
                        "Microsoft.Storage/storageAccounts/<name>. Must match "
                        "the `id` field from a prior list_resources_in_group "
                        "result."
                    ),
                },
            },
            "required": ["resource_id"],
        },
    },
]


PLAN_SYSTEM_PROMPT: Final[str] = """\
You are the Azure Deployment Architect operating in PLAN mode. Your job is to
audit an Azure subscription against the Well-Architected Framework by calling
read-only inspection tools, then synthesising findings into a structured review.

You have access to read-only Azure inspection tools. Use them deliberately:
  - Call the smallest tool that answers the question. Don't enumerate every
    resource group when the user asked about one workload.
  - You have a HARD CAP of 5 turns. Budget your calls — if you've used 3 turns
    on inventory, you have at most 2 left for synthesis.
  - After your final tool call, emit the synthesis as markdown text (no more
    tool calls). The synthesis MUST use the same WAF pillar structure as the
    architecture review prompt: Reliability, Security, Cost Optimization,
    Operational Excellence, Performance Efficiency, then a Verdict section.

Rules:
  - Never invent resource names or properties you didn't observe via a tool.
  - If a tool returns empty, say so explicitly — empty is a finding.
  - If the operator's request is too vague to plan against, emit one CLARIFY
    line and stop (no tool calls).
  - Output the final synthesis as plain markdown. No JSON, no preamble.
"""


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
