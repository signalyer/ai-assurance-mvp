"""Tests for api/assurance_model.py — S69 real-LLM streaming path.

Three assertions, one isolated app:
  1. REAL_LLM_ENABLED=false + credentials present -> simulated (existing
     behavior, no regression).
  2. REAL_LLM_ENABLED=true + credentials present -> SSE stream of deltas
     followed by terminal 'done' event with status='live' and a
     positive token_estimate (asserted on the mocked usage block).
  3. REAL_LLM_ENABLED=true + credentials ABSENT -> graceful fallback to
     simulated (failure mode #1 in the S69 plan: must not 500).

The real Anthropic client is never called -- we monkeypatch the
stream_anthropic_response helper in api.assurance_model with a fake async
generator. This is the same surface the dispatcher actually depends on.

Pytest gotcha: run with `-p no:deepeval` to dodge the deepeval plugin
teardown crash under py3.14 (see project memory).
"""
from __future__ import annotations

import json
from typing import AsyncIterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixture: isolated app with only the assurance_model router mounted.
# ---------------------------------------------------------------------------

@pytest.fixture
def app() -> FastAPI:
    from api.assurance_model import router as am_router
    app = FastAPI()
    app.include_router(am_router)
    return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


# Anthropic provider is the routing target for RELEASE_DECISION_NARRATIVE.
# We force have_real_credentials to be deterministic by setting / clearing
# ANTHROPIC_API_KEY via monkeypatch in each test.


def _post_explain_release(client: TestClient) -> "any":
    """POST a representative explain-release body using SSE streaming.

    TestClient's underlying httpx.Client supports .stream() for SSE bodies.
    """
    body = {
        "ai_system_id": "ai-sys-bae72e75",
        "data_classes": [],
        "payload": {
            "gate_id": "RG-Hold-P0-Open",
            "gate_note": "1 CRITICAL P0 finding open on tool-router",
            "gate_actual": "fail (1 open critical)",
        },
        # Force Anthropic. RELEASE_DECISION_NARRATIVE is allowed on both
        # Anthropic and Bedrock; Bedrock wins the routing tiebreak (it carries
        # all three roles). For S69 we're wiring the Anthropic streaming path
        # specifically, so the test pins it. Production callers should let the
        # routing engine pick -- but until Bedrock has its own streaming
        # adapter, the live path is Anthropic-only.
        "preferred_provider": "anthropic-prod",
        "user": "pytest",
    }
    return client.stream(
        "POST", "/api/assurance-model/explain-release", json=body
    )


def _parse_sse(body_text: str) -> list[tuple[str, dict]]:
    """Parse SSE frames. sse-starlette emits `\\r\\n` line endings; normalise
    to LF, then split on blank-line frame separator."""
    normalised = body_text.replace("\r\n", "\n")
    events: list[tuple[str, dict]] = []
    for chunk in normalised.split("\n\n"):
        chunk = chunk.strip("\n")
        if not chunk:
            continue
        event_name = ""
        data_line = ""
        for line in chunk.split("\n"):
            if line.startswith("event:"):
                event_name = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data_line += line[len("data:"):].strip()
        if not event_name:
            continue
        try:
            payload = json.loads(data_line) if data_line else {}
        except json.JSONDecodeError:
            payload = {"_raw": data_line}
        events.append((event_name, payload))
    return events


# ---------------------------------------------------------------------------
# Test 1: REAL_LLM_ENABLED=false -> simulated single-event SSE.
# ---------------------------------------------------------------------------

def test_explain_release_simulated_when_flag_off(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REAL_LLM_ENABLED", "false")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-fake-creds")

    with _post_explain_release(client) as resp:
        assert resp.status_code == 200
        body = resp.read().decode("utf-8")

    events = _parse_sse(body)
    assert len(events) == 1, f"expected single done frame, got {events!r}"
    name, payload = events[0]
    assert name == "done"
    inner = json.loads(payload["data"]) if "data" in payload else payload
    # sse-starlette renders our {"event":..., "data": json_str} into:
    #   event: done
    #   data: <json_str>
    # so payload IS the parsed json_str dict directly.
    inner = payload
    assert inner["status"] == "simulated"
    assert inner["use_case"] == "release_decision_narrative"
    assert "Simulated" in (inner.get("response") or "")


# ---------------------------------------------------------------------------
# Test 2: REAL_LLM_ENABLED=true + creds + mocked stream -> live SSE with
# delta events and a terminal done with status='live' + token numbers.
# ---------------------------------------------------------------------------

def test_explain_release_streams_when_real_llm_enabled(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REAL_LLM_ENABLED", "true")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-fake-creds")

    fake_chunks = [
        "Decision: HOLD\n",
        "Why: open CRITICAL on tool-router prompt-injection bypass.\n",
        "Failed gates: RG-Hold-P0-Open.\n",
    ]

    async def fake_stream(provider, use_case, sanitized) -> AsyncIterator:
        for ch in fake_chunks:
            yield ("delta", ch)
        yield (
            "done",
            {
                "input_tokens": 320,
                "output_tokens": 184,
                "token_estimate": 504,
                "cost_estimate_usd": 0.00375,
                "model": "claude-sonnet-4-6",
                "full_text": "".join(fake_chunks),
            },
        )

    # Patch the symbol the dispatcher imported, not the source -- otherwise
    # the rebinding in api.assurance_model still points at the real helper.
    monkeypatch.setattr(
        "api.assurance_model.stream_anthropic_response", fake_stream
    )

    with _post_explain_release(client) as resp:
        assert resp.status_code == 200
        body = resp.read().decode("utf-8")

    events = _parse_sse(body)
    deltas = [p for n, p in events if n == "delta"]
    done = [p for n, p in events if n == "done"]
    assert len(deltas) == len(fake_chunks), (
        f"expected {len(fake_chunks)} delta events, got {len(deltas)}: {events!r}"
    )
    assert "".join(d["text"] for d in deltas) == "".join(fake_chunks)

    assert len(done) == 1, f"expected one done event, got {len(done)}"
    final = done[0]
    assert final["status"] == "live"
    assert final["use_case"] == "release_decision_narrative"
    assert final["token_estimate"] == 504
    assert final["cost_estimate_usd"] == pytest.approx(0.00375)
    assert final["streaming_complete"] is True
    assert "HOLD" in (final.get("response") or "")


# ---------------------------------------------------------------------------
# Test 3: REAL_LLM_ENABLED=true but ANTHROPIC_API_KEY missing -> graceful
# fallback to simulated (not a 500). Plan verification list, failure mode #1.
# ---------------------------------------------------------------------------

def test_explain_release_falls_back_to_sim_when_no_creds(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REAL_LLM_ENABLED", "true")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with _post_explain_release(client) as resp:
        assert resp.status_code == 200
        body = resp.read().decode("utf-8")

    events = _parse_sse(body)
    assert len(events) == 1
    name, payload = events[0]
    assert name == "done"
    assert payload["status"] == "simulated"


# ---------------------------------------------------------------------------
# S72: same trio for the 4 newly-streaming routes (ask / summarize-finding /
# summarize-evidence / draft-report). The dispatcher is shared with
# /explain-release, so the matrix is about (a) the use_case surfacing through
# correctly and (b) the sim text mentioning the right use case. Anthropic
# pinned because all 4 use cases are in its allowed list and Bedrock has no
# streaming adapter yet (drop pin in S71b/S73).
# ---------------------------------------------------------------------------

_S72_ROUTES = [
    # (path, use_case, sim-marker-substring, payload-extras)
    (
        "/api/assurance-model/ask",
        "system_qa",
        "HIGH inherent risk",
        {"question": "Why is this system on HOLD?"},
    ),
    (
        "/api/assurance-model/summarize-finding",
        "findings_summarization",
        "Root cause",
        {"finding_id": "F-2026-0312", "severity": "CRITICAL", "title": "Tool-router prompt-injection bypass"},
    ),
    (
        "/api/assurance-model/summarize-evidence",
        "evidence_summarization",
        "Evidence summary",
        {"evidence_sections": "Architecture diagram, IAM policy, Bedrock config", "evidence_completeness": "38%"},
    ),
    (
        "/api/assurance-model/draft-report",
        "executive_report_generation",
        "Portfolio",
        {"portfolio_stats": "6 systems · 1 prod · 2 HOLD · 3 Conditional Pilot", "top_risks": "Customer Service Copilot prompt-injection bypass"},
    ),
]


def _post_streaming(client: TestClient, path: str, extras: dict):
    body = {
        "ai_system_id": "ai-sys-bae72e75",
        "data_classes": [],
        "payload": extras,
        "preferred_provider": "anthropic-prod",
        "user": "pytest",
    }
    return client.stream("POST", path, json=body)


@pytest.mark.parametrize("path,use_case,sim_marker,extras", _S72_ROUTES)
def test_s72_route_simulated_when_flag_off(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
    path: str, use_case: str, sim_marker: str, extras: dict,
) -> None:
    monkeypatch.setenv("REAL_LLM_ENABLED", "false")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-fake-creds")

    with _post_streaming(client, path, extras) as resp:
        assert resp.status_code == 200
        body = resp.read().decode("utf-8")

    events = _parse_sse(body)
    assert len(events) == 1, f"{path}: expected single done frame, got {events!r}"
    name, payload = events[0]
    assert name == "done"
    assert payload["status"] == "simulated"
    assert payload["use_case"] == use_case
    assert sim_marker in (payload.get("response") or ""), (
        f"{path}: sim text missing marker {sim_marker!r}: {payload.get('response')!r}"
    )


@pytest.mark.parametrize("path,use_case,sim_marker,extras", _S72_ROUTES)
def test_s72_route_streams_when_real_llm_enabled(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
    path: str, use_case: str, sim_marker: str, extras: dict,
) -> None:
    monkeypatch.setenv("REAL_LLM_ENABLED", "true")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-fake-creds")

    fake_chunks = [f"Live response for {use_case}: ", "line two.\n"]
    expected_use_case = use_case  # capture before shadowing in fake_stream

    async def fake_stream(provider, use_case, sanitized) -> AsyncIterator:
        assert use_case == expected_use_case  # dispatcher must forward the right use_case
        for ch in fake_chunks:
            yield ("delta", ch)
        yield (
            "done",
            {
                "input_tokens": 200,
                "output_tokens": 120,
                "token_estimate": 320,
                "cost_estimate_usd": 0.0024,
                "model": "claude-sonnet-4-6",
                "full_text": "".join(fake_chunks),
            },
        )

    monkeypatch.setattr("api.assurance_model.stream_anthropic_response", fake_stream)

    with _post_streaming(client, path, extras) as resp:
        assert resp.status_code == 200
        body = resp.read().decode("utf-8")

    events = _parse_sse(body)
    deltas = [p for n, p in events if n == "delta"]
    done = [p for n, p in events if n == "done"]
    assert len(deltas) == len(fake_chunks), f"{path}: deltas={deltas!r}"
    assert len(done) == 1
    final = done[0]
    assert final["status"] == "live"
    assert final["use_case"] == use_case
    assert final["token_estimate"] == 320
    assert final["streaming_complete"] is True


@pytest.mark.parametrize("path,use_case,sim_marker,extras", _S72_ROUTES)
def test_s72_route_falls_back_to_sim_when_no_creds(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
    path: str, use_case: str, sim_marker: str, extras: dict,
) -> None:
    monkeypatch.setenv("REAL_LLM_ENABLED", "true")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with _post_streaming(client, path, extras) as resp:
        assert resp.status_code == 200
        body = resp.read().decode("utf-8")

    events = _parse_sse(body)
    assert len(events) == 1
    name, payload = events[0]
    assert name == "done"
    assert payload["status"] == "simulated"
    assert payload["use_case"] == use_case
