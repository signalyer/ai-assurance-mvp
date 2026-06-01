"""Financial Advisor Risk Reviewer — demo agent.

Mirrors agents/azure-architect/ in shape (SDK decorator chain, 5-turn
tool-use loop, write_episode at synthesis) but with finance-flavored
tools and deterministic mock data so the demo is reproducible without
live financial APIs.

This is the first runner-invocable agent (per agents/_registry.py).
Directory name `finadvice` is a valid Python module path on purpose
(no hyphen) so the runner can `importlib.import_module("agents.finadvice.agent")`.
"""
from __future__ import annotations
