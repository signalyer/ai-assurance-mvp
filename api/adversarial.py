"""FastAPI router for adversarial probe suite (jailbreak, prompt injection,
data exfiltration, harm generation, compliance bypass).

Streams per-probe results via Server-Sent Events. Each probe blocks on a real
Anthropic/OpenAI call (the underlying SDKs are sync); SSE lets the engineer
see progress in the SPA without waiting 40-60s for a single JSON response.

Session 18 — V2 Phase 2 Week 3 close-out. Surface #5. Engine layer
(adversarial.py) extended with run_adversarial_suite_streaming() generator;
this router wraps it in StreamingResponse with text/event-stream.

Endpoints:
  GET  /api/adversarial/categories  — list available probe categories
  POST /api/adversarial/run         — run suite, stream events via SSE

Important: SSE responses are NOT included in OpenAPI's standard
JSON-response contract checks. The endpoint is intentionally a POST with
a JSON body to keep argument shape ergonomic, but returns text/event-stream.
Schemathesis will validate the request shape; the stream format is
documented in adversarial.run_adversarial_suite_streaming().
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/adversarial", tags=["adversarial"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class CategoriesResponse(BaseModel):
    """Response from GET /api/adversarial/categories."""

    model_config = ConfigDict()

    categories: list[str]
    total_probes: int


class RunSuiteRequest(BaseModel):
    """Body for POST /api/adversarial/run."""

    model_config = ConfigDict(str_strip_whitespace=True)

    model_provider: Literal["anthropic", "openai"] = "anthropic"
    model_name: str = Field(default="claude-sonnet-4-6", min_length=1, max_length=128)
    categories: Optional[list[str]] = None

    @field_validator("categories")
    @classmethod
    def categories_known(cls, v: Optional[list[str]]) -> Optional[list[str]]:
        """Reject categories the engine doesn't know about, but allow None."""
        if v is None:
            return None
        try:
            import adversarial  # noqa: PLC0415
            known = set(adversarial.get_available_categories())
        except Exception:
            # If the engine module can't load, defer validation to the engine
            return v
        unknown = [c for c in v if c not in known]
        if unknown:
            raise ValueError(
                f"unknown categories: {unknown}. Known: {sorted(known)}"
            )
        # Empty list = no probes to run; reject to avoid confusing 0-probe runs
        if len(v) == 0:
            raise ValueError("categories must contain at least one entry, or be omitted to run all")
        return v


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_import_adversarial() -> Any:
    """Lazy import of adversarial module."""
    try:
        import adversarial  # type: ignore[import]
        return adversarial
    except ModuleNotFoundError as exc:
        logger.error("adversarial module not available: %s", exc)
        raise HTTPException(status_code=503, detail="Adversarial engine not available")


def _format_sse(event: dict[str, Any]) -> str:
    """Format a single dict as an SSE message.

    Uses the 'event:' field so EventSource consumers can filter by name
    (start | probe | done | error). Payload goes in the 'data:' field as JSON.
    Multiline payloads are flattened (no embedded newlines in JSON output).
    """
    event_name = str(event.get("event", "message"))
    payload = json.dumps(event, separators=(",", ":"))
    return f"event: {event_name}\ndata: {payload}\n\n"


async def _stream_suite(
    adversarial_mod: Any,
    model_provider: str,
    model_name: str,
    categories: Optional[list[str]],
) -> Any:
    """Async generator wrapping the sync engine generator.

    Each iteration of the engine generator is offloaded to a thread so the
    event loop stays responsive (engine call blocks on Anthropic/OpenAI).
    Errors are surfaced as an SSE 'error' event before the stream ends —
    not as an HTTP 500, because by that point headers are already sent.
    """
    try:
        gen = adversarial_mod.run_adversarial_suite_streaming(
            model_provider=model_provider,
            model_name=model_name,
            categories=categories,
        )
        # Drain the sync generator one yield at a time, offloading the blocking
        # work (which contains the SDK call) to a worker thread.
        sentinel = object()
        while True:
            item = await asyncio.to_thread(next, gen, sentinel)
            if item is sentinel:
                break
            yield _format_sse(item)
    except Exception as exc:                                  # noqa: BLE001
        logger.error("adversarial stream failed: %s", str(exc)[:300])
        yield _format_sse({
            "event": "error",
            "message": "Adversarial run failed mid-stream",
            "detail": str(exc)[:300],
        })


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/categories", response_model=CategoriesResponse)
async def list_categories() -> CategoriesResponse:
    """Return the available adversarial probe categories and total probe count."""
    logger.info("list_categories: entry")
    mod = _safe_import_adversarial()
    try:
        cats = await asyncio.to_thread(mod.get_available_categories)
        # Categories list is small (~5); collect counts sequentially. asyncio.gather
        # would also work but adds no real win for in-memory dict lookups.
        total = 0
        for c in cats:
            probes = await asyncio.to_thread(mod.get_probes_for_category, c)
            total += len(probes)
        logger.info("list_categories: exit categories=%d total_probes=%d", len(cats), total)
        return CategoriesResponse(categories=cats, total_probes=total)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("list_categories failed: %s", str(exc)[:200])
        raise HTTPException(status_code=500, detail="Failed to list categories")


@router.post("/run")
async def run_suite(body: RunSuiteRequest) -> StreamingResponse:
    """Run the adversarial suite and stream per-probe results via SSE.

    Response type: text/event-stream. Events fired (each with `event:` header):
      start  — once, with model + total_probes + categories
      probe  — once per probe, with index/total/resisted/severity/latency_ms
      done   — once at the end, with the full summary dict
      error  — only on engine failure, before the stream terminates

    Empty `categories` is rejected at the boundary (422) so the SPA never
    streams an empty run.
    """
    logger.info(
        "run_suite: provider=%s model=%s categories=%s",
        body.model_provider, body.model_name, body.categories or "ALL",
    )
    mod = _safe_import_adversarial()
    stream = _stream_suite(mod, body.model_provider, body.model_name, body.categories)
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={
            # Prevent intermediaries from buffering — SSE relies on prompt flush
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
