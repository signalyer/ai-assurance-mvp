"""Agents package. Per-agent modules live in subdirectories.

The registry in `_registry.py` is the single source of truth for which
agents the Agent Runner can dispatch. Agents may exist on disk without
being registered (legacy / CLI-only agents).
"""
from __future__ import annotations
