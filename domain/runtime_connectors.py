"""Runtime event connectors.

Defines the interface real integrations will implement (Langfuse, CloudTrail,
Security Hub, GuardDuty, Macie, NeMo Guardrails, Lakera, AI/Tool gateways).
Each concrete class today returns the events tagged with its source from the
seed; replace `fetch_events` with the actual API call when wiring an integration.

The aggregator (`fetch_all_events`) is the single read path for the page.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from domain.models import RuntimeEvent, RuntimeEventSource
from domain import seed


class RuntimeConnector(ABC):
    source: RuntimeEventSource

    @abstractmethod
    def fetch_events(self, since: datetime | None = None) -> list[RuntimeEvent]:
        ...

    def name(self) -> str:
        return self.source.value


class _SeedSourceConnector(RuntimeConnector):
    """Generic stub: returns events from the seed that are tagged with this source.

    Real connectors will replace fetch_events with API calls (boto3 / Langfuse SDK / etc).
    """
    def __init__(self, source: RuntimeEventSource) -> None:
        self.source = source

    def fetch_events(self, since: datetime | None = None) -> list[RuntimeEvent]:
        events = [e for e in seed.RUNTIME_EVENTS if e.source == self.source]
        if since:
            events = [e for e in events if e.timestamp >= since]
        return events


class LangfuseConnector(_SeedSourceConnector):
    """Stub. Real impl: poll Langfuse API for scored traces / interventions."""
    def __init__(self) -> None:
        super().__init__(RuntimeEventSource.LANGFUSE)


class CloudTrailConnector(_SeedSourceConnector):
    """Stub. Real impl: boto3 LookupEvents on Bedrock + IAM + S3 data events."""
    def __init__(self) -> None:
        super().__init__(RuntimeEventSource.AWS_CLOUDTRAIL)


class SecurityHubConnector(_SeedSourceConnector):
    """Stub. Real impl: boto3 GetFindings filtered to AI workload resources."""
    def __init__(self) -> None:
        super().__init__(RuntimeEventSource.AWS_SECURITY_HUB)


class GuardDutyConnector(_SeedSourceConnector):
    """Stub. Real impl: boto3 ListFindings + GetFindings."""
    def __init__(self) -> None:
        super().__init__(RuntimeEventSource.AWS_GUARDDUTY)


class MacieConnector(_SeedSourceConnector):
    """Stub. Real impl: boto3 ListFindings filtered to in-scope S3 buckets."""
    def __init__(self) -> None:
        super().__init__(RuntimeEventSource.AWS_MACIE)


class BedrockGuardrailConnector(_SeedSourceConnector):
    """Stub. Real impl: parse Bedrock InvocationLogging guardrail-trace records."""
    def __init__(self) -> None:
        super().__init__(RuntimeEventSource.AWS_BEDROCK_GUARDRAIL)


class NemoGuardrailsConnector(_SeedSourceConnector):
    """Stub. Real impl: tail NeMo Guardrails rail-event stream."""
    def __init__(self) -> None:
        super().__init__(RuntimeEventSource.NEMO_GUARDRAILS)


class LakeraConnector(_SeedSourceConnector):
    """Stub. Real impl: Lakera Guard API for prompt-injection scoring."""
    def __init__(self) -> None:
        super().__init__(RuntimeEventSource.LAKERA)


class ToolGatewayConnector(_SeedSourceConnector):
    """Stub. Real impl: internal Tool Gateway decision log."""
    def __init__(self) -> None:
        super().__init__(RuntimeEventSource.CUSTOM_TOOL_GATEWAY)


class AIGatewayConnector(_SeedSourceConnector):
    """Stub. Real impl: AI Gateway DLP + policy decision log."""
    def __init__(self) -> None:
        super().__init__(RuntimeEventSource.CUSTOM_AI_GATEWAY)


# Registry of available connectors. Real deployments swap stubs for live SDKs.
CONNECTORS: list[RuntimeConnector] = [
    LangfuseConnector(),
    CloudTrailConnector(),
    SecurityHubConnector(),
    GuardDutyConnector(),
    MacieConnector(),
    BedrockGuardrailConnector(),
    NemoGuardrailsConnector(),
    LakeraConnector(),
    ToolGatewayConnector(),
    AIGatewayConnector(),
]


def fetch_all_events(since: datetime | None = None) -> list[RuntimeEvent]:
    """Aggregate across all connectors. Plus any seeded events tagged INTERNAL
    (legacy and platform-emitted)."""
    out: list[RuntimeEvent] = []
    for c in CONNECTORS:
        out.extend(c.fetch_events(since=since))
    # Include INTERNAL events (no connector owns them)
    for e in seed.RUNTIME_EVENTS:
        if e.source == RuntimeEventSource.INTERNAL:
            if since and e.timestamp < since:
                continue
            out.append(e)
    out.sort(key=lambda e: e.timestamp, reverse=True)
    return out


__all__ = [
    "RuntimeConnector", "CONNECTORS", "fetch_all_events",
    "LangfuseConnector", "CloudTrailConnector", "SecurityHubConnector",
    "GuardDutyConnector", "MacieConnector", "BedrockGuardrailConnector",
    "NemoGuardrailsConnector", "LakeraConnector",
    "ToolGatewayConnector", "AIGatewayConnector",
]
