"""Azure Monitor / App Insights wiring via the azure-monitor-opentelemetry distro.

``init_app_insights`` is designed to be called exactly once from
``dashboard.py`` at startup *before* the FastAPI app is constructed.  It is
idempotent (subsequent calls are no-ops), never raises, and degrades silently
when the connection string is absent or the SDK is not installed.

``instrument_fastapi`` is a separate hook that must be called *after* the
FastAPI app object exists, because FastAPI cannot be auto-instrumented at
SDK-import time (no entry-point hook).  Calling both yields the full
trace + metric + log pipeline.

Day-12 history (2026-05-23): the previous implementation wired only an
``AzureMonitorTraceExporter`` + ``BatchSpanProcessor`` and never installed
any auto-instrumentation, so spans were never created and the workspace
remained empty.  Switching to the distro fixes that silently-broken
configuration.
"""
from __future__ import annotations

import logging
from typing import Any

_log = logging.getLogger(__name__)

_initialised: bool = False
_instrumented: bool = False


def init_app_insights(connection_string: str | None) -> None:
    """Configure the Azure Monitor distro: traces + metrics + logs.

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
        # Deferred import: module loads even if the SDK isn't installed.
        from azure.monitor.opentelemetry import configure_azure_monitor

        # configure_azure_monitor() is the all-in-one distro entrypoint.  It:
        #   - sets the global TracerProvider with AzureMonitorTraceExporter
        #   - sets the global MeterProvider with AzureMonitorMetricExporter
        #   - sets the global LoggerProvider with AzureMonitorLogExporter
        #   - auto-instruments requests/urllib3/logging/dbapi
        # The FastAPI instrumentation is wired separately via
        # ``instrument_fastapi(app)`` because FastAPI lacks an SDK-time hook.
        configure_azure_monitor(
            connection_string=connection_string.strip(),
            # Service name surfaces as cloud_RoleName in App Insights and
            # is the field most KQL dashboards group on.
            resource_attributes={"service.name": "ai-assurance-platform"},
        )

        _initialised = True
        # Do NOT log any portion of the connection string -- the
        # InstrumentationKey GUID grants write access to the workspace.
        _log.info("app_insights_initialised connection_string_present=true")
    except ImportError as exc:
        _log.error(
            "app_insights_sdk_missing error=%s hint=install azure-monitor-opentelemetry",
            exc,
        )
    except Exception as exc:
        _log.error("app_insights_init_failed error=%s", exc)


def instrument_fastapi(app: Any) -> None:
    """Attach OpenTelemetry auto-instrumentation to a FastAPI app instance.

    Must be called once after the FastAPI ``app = FastAPI(...)`` line.  Safe
    to call when telemetry is disabled (no-op).  Idempotent: subsequent
    calls return without re-instrumenting.

    Args:
        app: The FastAPI application instance to instrument.  Typed as Any
             to avoid importing FastAPI in this module.
    """
    global _instrumented

    if _instrumented:
        _log.debug("app_insights_fastapi_already_instrumented skipping")
        return

    if not _initialised:
        # If the distro isn't initialised (e.g. no connection string),
        # instrumenting FastAPI is a wasted no-op -- spans would have
        # nowhere to go.  Skip silently.
        _log.debug("app_insights_fastapi_skipped reason=distro_not_initialised")
        return

    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)
        _instrumented = True
        _log.info("app_insights_fastapi_instrumented")
    except ImportError as exc:
        _log.error(
            "app_insights_fastapi_sdk_missing error=%s hint=install opentelemetry-instrumentation-fastapi",
            exc,
        )
    except Exception as exc:
        _log.error("app_insights_fastapi_instrument_failed error=%s", exc)
