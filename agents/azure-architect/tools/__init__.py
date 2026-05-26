"""ARM read tools + diagram renderer for the Azure Deployment Architect agent.

Re-exports the public tool surface so `agent.py` can do
`from tools import list_subscriptions, ...` without reaching into modules.
"""

from __future__ import annotations

from .arm_read import (
    get_network_topology,
    get_resource_metadata,
    list_resource_groups,
    list_role_assignments,
    list_subscriptions,
)
from .mermaid_render import render_mermaid_diagram

__all__ = [
    "list_subscriptions",
    "list_resource_groups",
    "get_resource_metadata",
    "list_role_assignments",
    "get_network_topology",
    "render_mermaid_diagram",
]
