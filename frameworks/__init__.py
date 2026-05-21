"""frameworks — YAML-driven framework catalog loader for the AI Assurance Platform.

Re-exports the public loader API and the Pydantic schema types so callers
only need to import from this package.

Example:
    from frameworks import load_all_frameworks, load_yaml_framework, FrameworkYAMLItem

    catalogs = load_all_frameworks()
    # {'eu-ai-act': [...], 'iso-42001': [...], 'sr-11-7': [...], ...}
"""

from __future__ import annotations

from frameworks.loader import (
    FrameworkYAMLItem,
    load_all_frameworks,
    load_yaml_framework,
)

__all__ = [
    "load_all_frameworks",
    "load_yaml_framework",
    "FrameworkYAMLItem",
]
