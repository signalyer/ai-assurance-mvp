"""ARM read tools — 5 async functions wrapping azure.mgmt.* packages.

P4 Day-1 deliverable. Skeleton-only in S55 prep: signatures, docstrings,
JSON-schema-pinned return types, NotImplementedError bodies. Day-1 of P4
fills in azure.mgmt.* calls + unit tests against fixture data.

Auth contract: every function expects an azure.identity credential injected
via the agent's startup path (`agent.py::_init_azure_credential`). No env-var
sniffing inside individual tool functions — keeps the trust boundary at
one explicit init site, per CLAUDE.md universal rule "SDK Client
Initialisation: always at module/global scope".
"""

from __future__ import annotations

from typing import Protocol

from .schemas import (
    NetworkTopologyOut,
    ResourceGroupsListOut,
    ResourceMetadata,
    RoleAssignmentsListOut,
    SubscriptionsListOut,
)


# ---------------------------------------------------------------------------
# Credential protocol — duck-types azure.identity.TokenCredential without
# importing the real package, so this module is unit-testable in isolation.
# ---------------------------------------------------------------------------


class _Cred(Protocol):
    def get_token(self, *scopes: str) -> object: ...  # pragma: no cover


# ---------------------------------------------------------------------------
# Tool 1 — list_subscriptions
# ---------------------------------------------------------------------------


async def list_subscriptions(credential: _Cred) -> SubscriptionsListOut:
    """Enumerate every subscription the caller has Reader on.

    Wraps `azure.mgmt.subscription.SubscriptionClient.subscriptions.list`.
    The SDK call is synchronous; wrap with asyncio.to_thread in P4.

    Args:
        credential: An azure.identity credential. ManagedIdentityCredential
            in production; DefaultAzureCredential in dev.

    Returns:
        Strict SubscriptionsListOut. Empty list is a valid result (caller
        has zero subscriptions).
    """
    raise NotImplementedError("P4 Day-1 — wrap azure.mgmt.subscription.SubscriptionClient")


# ---------------------------------------------------------------------------
# Tool 2 — list_resource_groups
# ---------------------------------------------------------------------------


async def list_resource_groups(
    credential: _Cred, subscription_id: str
) -> ResourceGroupsListOut:
    """List every resource group in one subscription.

    Wraps `azure.mgmt.resource.ResourceManagementClient.resource_groups.list`.

    Args:
        credential: Azure credential.
        subscription_id: Target subscription GUID.

    Returns:
        Strict ResourceGroupsListOut.
    """
    raise NotImplementedError("P4 Day-1 — wrap ResourceManagementClient.resource_groups.list")


# ---------------------------------------------------------------------------
# Tool 3 — get_resource_metadata
# ---------------------------------------------------------------------------


async def get_resource_metadata(
    credential: _Cred, resource_id: str
) -> ResourceMetadata:
    """Fetch detailed metadata for one Azure resource.

    Wraps `azure.mgmt.resource.ResourceManagementClient.resources.get_by_id`.

    Args:
        credential: Azure credential.
        resource_id: Full ARM resource ID
            (e.g. `/subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.Web/sites/<name>`).

    Returns:
        Strict ResourceMetadata. The `properties` field is intentionally
        a polymorphic dict — schema varies per ARM resource type.

    Raises:
        ValueError: If `resource_id` is malformed.
    """
    raise NotImplementedError("P4 Day-1 — wrap ResourceManagementClient.resources.get_by_id")


# ---------------------------------------------------------------------------
# Tool 4 — list_role_assignments
# ---------------------------------------------------------------------------


async def list_role_assignments(
    credential: _Cred, scope: str
) -> RoleAssignmentsListOut:
    """List RBAC role assignments at the given scope.

    Wraps `azure.mgmt.authorization.AuthorizationManagementClient.role_assignments.list_for_scope`.

    Args:
        credential: Azure credential.
        scope: ARM scope string — subscription, RG, or individual resource ID.

    Returns:
        Strict RoleAssignmentsListOut. Includes inherited assignments by
        default — exclude inheriting parent scopes when summarizing the
        access matrix to avoid double-counting.
    """
    raise NotImplementedError("P4 Day-1 — wrap AuthorizationManagementClient.role_assignments")


# ---------------------------------------------------------------------------
# Tool 5 — get_network_topology
# ---------------------------------------------------------------------------


async def get_network_topology(
    credential: _Cred, subscription_id: str
) -> NetworkTopologyOut:
    """Walk VNets, peerings, and private endpoints in a subscription.

    Wraps:
        - `azure.mgmt.network.NetworkManagementClient.virtual_networks.list_all`
        - `...virtual_network_peerings.list` (per VNet, batched via asyncio.gather)
        - `...private_endpoints.list_by_subscription`

    Args:
        credential: Azure credential.
        subscription_id: Target subscription GUID.

    Returns:
        Strict NetworkTopologyOut.
    """
    raise NotImplementedError("P4 Day-1 — wrap NetworkManagementClient (3 sub-calls, parallelize)")
