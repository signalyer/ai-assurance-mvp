"""Azure Monitor / App Insights wiring via the GA distro.

``init_app_insights`` is designed to be called exactly once from
``dashboard.py`` at startup, BEFORE ``from fastapi import FastAPI``.
It is idempotent (subsequent calls are no-ops), never raises, and
degrades silently when the connection string is absent or the SDK is
not installed.

S77 #2: Switched from the beta `azure-monitor-opentelemetry-exporter`
(which crashed on cold start with `cannot import name 'LogData'` against
current opentelemetry-sdk releases) to the GA distro
`azure-monitor-opentelemetry`. The distro pins compatible exporter +
SDK versions AND bundles FastAPIInstrumentor (auto-enabled). The prior
manual TracerProvider / BatchSpanProcessor wiring is no longer needed.

Ordering note: `configure_azure_monitor()` MUST run before
`from fastapi import FastAPI` is imported. Otherwise the FastAPI
instrumentor binds to the no-op default tracer provider. See:
  https://learn.microsoft.com/troubleshoot/azure/azure-monitor/app-insights/telemetry/opentelemetry-troubleshooting-python
"""
from __future__ import annotations

import logging

_log = logging.getLogger(__name__)

_initialised: bool = False


def init_app_insights(connection_string: str | None) -> None:
    """Configure Azure Monitor OpenTelemetry for the current process.

    If *connection_string* is ``None`` or empty the function logs an info
    message and returns immediately -- the application continues without
    telemetry rather than failing.

    Any exception raised during SDK configuration is caught and logged at
    ERROR level. The function NEVER propagates an exception to the caller.

    Side-effects when the call succeeds:
      - Sets the global OpenTelemetry TracerProvider, MeterProvider, and
        LoggerProvider to Azure Monitor exporters.
      - Enables all distro-bundled instrumentations including FastAPI,
        Requests, and Django, which create spans automatically.

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
        # Deferred import so the module can be loaded even when the distro
        # is not installed (e.g. in some dev / test environments).
        from azure.monitor.opentelemetry import configure_azure_monitor

        configure_azure_monitor(connection_string=connection_string.strip())

        _initialised = True
        # Do NOT log any portion of the connection string -- the
        # InstrumentationKey GUID grants write access to the workspace.
        _log.info(
            "app_insights_initialised "
            "connection_string_present=true "
            "fastapi_instrumented=auto"
        )
    except ImportError as exc:
        _log.error(
            "app_insights_sdk_missing error=%s hint=install azure-monitor-opentelemetry",
            exc,
        )
    except Exception as exc:
        _log.error("app_insights_init_failed error=%s", exc)
