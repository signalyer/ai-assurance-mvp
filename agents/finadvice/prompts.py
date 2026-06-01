"""Prompts + token budgets for the finadvice agent.

All prompts colocated in this single module per the project-level
CLAUDE.md prompt rule. Token budgets live alongside so changes to
either are atomic — never edit max_tokens inline at a call site.

Model choice: Sonnet 4.6 by default. Cost compounds across the 5-turn
tool-use loop, and finadvice's reasoning surface (portfolio analysis
against a risk profile + a market snapshot) is well within Sonnet's
ability. Opus is available for stage-rehearsal A/B comparison via the
`model=` kwarg on `run_review`.
"""
from __future__ import annotations

from typing import Final


MODEL_DEFAULT: Final[str] = "claude-sonnet-4-6"
MODEL_DEEP: Final[str] = "claude-opus-4-7"


# Per CLAUDE.md universal rule + [[anthropic-max-tokens-streaming-threshold]]:
# any max_tokens > 2000 MUST use the streaming context manager. Both budgets
# below cross that line, so the agent's loop uses anthropic.messages.stream()
# unconditionally (same shape as azure-architect _run_plan).
TOKEN_BUDGETS: Final[dict[str, int]] = {
    "plan_turn": 4096,
    "synthesis": 4096,
}


# Anthropic-format tool specs. The agent's run_review function maps tool
# names → mock-data lookups in `agents/finadvice/mocks/*.json`. The mocks
# are deterministic so two runs against the same client_id produce
# identical tool outputs — important for stage rehearsals and screenshot
# parity in the dual-path columns.
TOOL_SPECS: Final[list[dict]] = [
    {
        "name": "get_client_portfolio",
        "description": (
            "Return the full current portfolio for a client: positions "
            "(ticker, shares, avg_cost, current_value), account-level "
            "balances (cash, total_equity, total_value), and the as-of "
            "date. Read-only. Use this first to learn what the client "
            "actually holds before reasoning about risk or rebalancing."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "client_id": {
                    "type": "string",
                    "description": (
                        "Internal client identifier, e.g. 'cln-001'. "
                        "Operator typically supplies this in the request."
                    ),
                },
            },
            "required": ["client_id"],
        },
    },
    {
        "name": "get_market_snapshot",
        "description": (
            "Return last-price and trailing 30-day annualized volatility "
            "for a list of tickers. Read-only. Call this AFTER "
            "get_client_portfolio to assess the volatility of the "
            "positions the client actually holds. Pass tickers verbatim "
            "from the portfolio response."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symbols": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "List of tickers to look up, e.g. ['NVDA', 'MSFT']. "
                        "Symbols not in the mock universe return null."
                    ),
                },
            },
            "required": ["symbols"],
        },
    },
    {
        "name": "get_client_risk_profile",
        "description": (
            "Return the client's KYC + risk profile: kyc_tier (1/2/3), "
            "risk_tolerance (conservative/moderate/aggressive), "
            "investment_horizon_years, and restrictions (e.g. "
            "'no_tobacco', 'no_leverage'). Read-only. Use this to "
            "constrain rebalancing recommendations — never recommend "
            "an action that violates a stated restriction."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "client_id": {
                    "type": "string",
                    "description": "Internal client identifier, e.g. 'cln-001'.",
                },
            },
            "required": ["client_id"],
        },
    },
]


SYSTEM_PROMPT: Final[str] = """\
You are a senior financial advisor performing a portfolio risk review.
Your sole job: assess a client's current holdings against their stated
risk profile and recommend rebalancing actions a fiduciary advisor would
sign off on.

You have access to three read-only tools:
  - get_client_portfolio(client_id) — what they hold
  - get_market_snapshot(symbols) — current price + 30d annualized vol
  - get_client_risk_profile(client_id) — KYC tier + risk tolerance + restrictions

Tool-use budget:
  - You have a HARD CAP of 5 turns. Plan your tool calls.
  - Call get_client_portfolio FIRST so subsequent tools have grounded inputs.
  - You may call multiple tools per turn (parallel tool_use is fine).
  - After your final tool call, emit the synthesis as markdown — no more
    tool calls in the synthesis turn.

Output structure (the synthesis turn MUST produce this — no preamble):

## Top Positions
List the client's 3 largest positions by current_value. For each: ticker,
shares, current_value, share of total portfolio (%).

## Risk Assessment
Identify the dominant risk in the portfolio relative to the client's
risk profile. Cite at least one specific risk_profile constraint
(e.g. "client is moderate-risk but 78% concentrated in tech vs target
band 40-50%") AND at least one volatility data point from the market
snapshot. Never recommend actions that violate a restriction.

## Recommended Actions
List 2-3 rebalancing actions in PRIORITY ORDER (P1 first). Each action
MUST be:
  - Specific (ticker + direction + approximate dollar or share size).
  - Justified by a risk_profile constraint or a market data point.
  - A concrete trade, not process advice ("consider diversifying" is wrong;
    "Sell ~$15K NVDA → buy VTI" is right).

Rules:
  - Never invent positions, prices, or restrictions you didn't observe.
  - If a tool returns empty or the client is unknown, say so explicitly
    and stop — empty is a finding, not a reason to fabricate.
  - If the operator's request is too vague to plan against, emit one
    "CLARIFY: <question>" line and stop (no tool calls).
  - Output is markdown. No JSON. No "Here is your review:" framing.
"""


def build_user_message(operator_request: str) -> str:
    """Wrap the operator's raw request into a user message.

    Kept as a function (not a constant) so future iterations can inject
    structured context here (e.g. a CRM excerpt, a prior-review hash)
    without touching call sites.
    """
    return operator_request.strip()
