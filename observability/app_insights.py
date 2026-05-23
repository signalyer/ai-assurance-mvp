"""Azure Monitor / App Insights exporter wiring via OpenTelemetry SDK.

``init_app_insights`` is designed to be called exactly once from
``dashboard.py`` at startup.  It is idempotent (subsequent calls are no-ops),
never raises, and degrades silently when the connection string is absent or
the SDK is not installed.
"""
from __future__ import annotations

import logging

_log = logging.getLogger(__name__)

_initialised: bool = False


def init_app_insights(connection_string: str | None) -> None:
    """Configure the OpenTelemetry / Azure Monitor exporter.

    If *connection_string* is ``None`` or empty the function logs an info
    message and returns immediately -- the application continues without
    telemetry rather than failing.

    Any exception raised during SDK configuration is caught and logged at
    ERROR level.  The function NEVER propagates an exception to the caller.

    Args:
        connection_string: The ``APPLICATIONINSIGHTS_CONNECTION_STRING`` value
                           read from environment variables by the caller.
                           Must be of the form
                           ``InstrumentationKey=<guid>;...``.
    """
    global _initialised

    if _initialised:
        _log.debug("app_insights_already_initialised skipping")
        return

    if not connection_string or not connection_string.strip():
        _log.info("app_insights_disabled reason=no_connection_string")
        return

    try:
        # These imports are intentionally deferred so the module can be
        # loaded even if the azure-monitor SDK is not installed.
        from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.resources import Resource, SERVICE_NAME

        resource = Resource.create({SERVICE_NAME: "ai-assurance-platform"})
        provider = TracerProvider(resource=resource)

        exporter = AzureMonitorTraceExporter(
            connection_string=connection_string.strip()
        )
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)

        _initialised = True
        # Do NOT log any portion of the connection string — the InstrumentationKey
        # GUID grants write access to the telemetry workspace.
        _log.info("app_insights_initialised connection_string_present=true")
    except ImportError as exc:
        _log.error(
            "app_insights_sdk_missing error=%s hint=install azure-monitor-opentelemetry-exporter",
            exc,
        )
    except Exception as exc:
        _log.error("app_insights_init_failed error=%s", exc)
