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


def instrument_fastapi_app(app: object) -> None:
    """Attach OpenTelemetry's FastAPI instrumentor to *app*.

    Must be called AFTER ``init_app_insights`` has set the global
    TracerProvider, otherwise the instrumentor binds to the no-op
    default provider and never emits any spans.

    Silently no-ops when:
      - ``init_app_insights`` did not initialise (no connection string,
        or SDK missing), OR
      - ``opentelemetry-instrumentation-fastapi`` is not installed.

    Never raises -- a missing instrumentor must not crash startup.

    S77 #2: without this call, observability/app_insights.py wired the
    AzureMonitorTraceExporter but no spans were ever created for HTTP
    requests, so App Insights workspace `appi-aigovern-dev` stayed empty.
    """
    if not _initialised:
        _log.info(
            "fastapi_instrument_skipped reason=tracer_provider_not_initialised"
        )
        return

    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)  # type: ignore[arg-type]
        _log.info("fastapi_instrumented spans_per_request=true")
    except ImportError as exc:
        _log.error(
            "fastapi_instrumentor_missing error=%s hint=install opentelemetry-instrumentation-fastapi",
            exc,
        )
    except Exception as exc:
        _log.error("fastapi_instrument_failed error=%s", exc)
