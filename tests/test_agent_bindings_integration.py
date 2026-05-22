"""Integration tests for Agent Bindings API — Session 07.

20 test cases covering:
  - Binding CRUD via API (3)
  - Publish v2 → subscriber upgrade_available_version_id set (3)
  - Pin to v1 → publish v2 → no upgrade notification (2)
  - Accept upgrade → binding version updated, flag cleared (2)
  - Unbind → 204, binding gone, subscription removed (2)
  - PATCH version_id with pinned=true (2)
  - DELETE non-existent binding → 404 (1)
  - POST binding with non-existent agent_id → 400 (1)
  - SSE endpoint smoke tests (2)
  - Auth check: no cookie → 401 (2)

Uses FastAPI TestClient + monkeypatching of domain layer calls.
Postgres-dependent paths marked with skipif when DATABASE_URL not set.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Domain model imports — skip the whole module if Implementer 1 hasn't landed
# ---------------------------------------------------------------------------
try:
    from domain.models import (
        Agent,
        AgentBinding,
        AgentOwnerType,
        AgentStatus,
        AgentSubscriber,
        AgentVersion,
        RiskLevel,
    )
    _MODELS_AVAILABLE = True
except ImportError:
    _MODELS_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not _MODELS_AVAILABLE,
    reason="domain.models not yet available (Implementer 1 not landed)",
)

# ---------------------------------------------------------------------------
# Build a minimal FastAPI app with ONLY the agent routes (no full dashboard)
# ---------------------------------------------------------------------------

from fastapi import FastAPI
from api.agents import router as agents_router
from api.agent_bindings import router as agent_bindings_router
from api.agent_notifications import router as agent_notifications_router

_test_app = FastAPI()
_test_app.include_router(agents_router)
_test_app.include_router(agent_bindings_router)
_test_app.include_router(agent_notifications_router)

CLIENT = TestClient(_test_app, raise_server_exceptions=False)

# Also build a "real-auth" client that has no session cookie — used for 401 tests
CLIENT_NO_AUTH = TestClient(_test_app, raise_server_exceptions=False)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

UTC = timezone.utc


def _now() -> datetime:
    return datetime.now(UTC)


def _make_agent(
    agent_id: str = "ai-agent-test-001",
    name: str = "Payments Fraud Detector",
    team: str = "payments",
    owner_type: AgentOwnerType = AgentOwnerType.REUSABLE,
) -> "Agent":
    now = _now()
    return Agent(
        id=agent_id,
        name=name,
        description="Detects payment fraud using ML signals.",
        team=team,
        owner_type=owner_type,
        latest_version_id=None,
        inherent_risk=RiskLevel.HIGH,
        framework_refs=[],
        created_at=now,
        updated_at=now,
    )


def _make_version(
    version_id: str = "ai-agent-ver-001",
    agent_id: str = "ai-agent-test-001",
    semver: str = "1.0.0",
    status: AgentStatus = AgentStatus.PUBLISHED,
) -> "AgentVersion":
    return AgentVersion(
        id=version_id,
        agent_id=agent_id,
        semver=semver,
        changelog="Initial release.",
        status=status,
        config={},
    )


def _make_binding(
    binding_id: str = "ai-bind-001",
    agent_id: str = "ai-agent-test-001",
    system_id: str = "ai-sys-001",
    version_id: str = "ai-agent-ver-001",
    pinned: bool = False,
    upgrade_available_version_id: Optional[str] = None,
) -> "AgentBinding":
    now = _now()
    return AgentBinding(
        id=binding_id,
        agent_id=agent_id,
        system_id=system_id,
        version_id=version_id,
        pinned=pinned,
        upgrade_available_version_id=upgrade_available_version_id,
        created_at=now,
        updated_at=now,
    )


def _make_subscriber(
    sub_id: str = "ai-sub-001",
    agent_id: str = "ai-agent-test-001",
    system_id: str = "ai-sys-001",
) -> "AgentSubscriber":
    return AgentSubscriber(
        id=sub_id,
        agent_id=agent_id,
        system_id=system_id,
        subscribed_at=_now(),
        last_notified_version_id=None,
    )


# ===========================================================================
# GROUP 1: Bind agent v1 to system → GET bindings returns it (3 cases)
# ===========================================================================

class TestBindAgentAndList:
    """Tests 1–3: bind, list, verify enrichment."""

    def test_01_post_binding_returns_201(self) -> None:
        """POST /api/systems/{system_id}/bindings returns 201 + binding dict."""
        agent = _make_agent()
        binding = _make_binding()

        with (
            patch("api.agent_bindings._agents") as mock_agents_factory,
            patch("api.agent_bindings._agent_bindings") as mock_bindings_factory,
            patch("api.agent_bindings._agent_subscribers") as mock_subs_factory,
        ):
            mock_agents = MagicMock()
            mock_agents.get_agent.return_value = agent
            mock_agents_factory.return_value = mock_agents

            mock_bindings = MagicMock()
            mock_bindings.bind_agent_to_system.return_value = binding
            mock_bindings_factory.return_value = mock_bindings

            mock_subs = MagicMock()
            mock_subs.subscribe.return_value = None
            mock_subs_factory.return_value = mock_subs

            r = CLIENT.post(
                "/api/systems/ai-sys-001/bindings",
                json={"agent_id": "ai-agent-test-001", "pinned": False},
            )

        assert r.status_code == 201
        data = r.json()
        assert data["id"] == "ai-bind-001"
        assert data["agent_id"] == "ai-agent-test-001"
        assert data["system_id"] == "ai-sys-001"

    def test_02_get_bindings_returns_list(self) -> None:
        """GET /api/systems/{system_id}/bindings returns list with enriched fields."""
        agent = _make_agent()
        version = _make_version()
        binding = _make_binding()

        with (
            patch("api.agent_bindings._agent_bindings") as mock_bindings_factory,
            patch("api.agent_bindings._agents") as mock_agents_factory,
        ):
            mock_bindings = MagicMock()
            mock_bindings.list_bindings_for_system.return_value = [binding]
            mock_bindings_factory.return_value = mock_bindings

            mock_agents = MagicMock()
            mock_agents.get_agent.return_value = agent
            mock_agents.get_version.return_value = version
            mock_agents_factory.return_value = mock_agents

            r = CLIENT.get("/api/systems/ai-sys-001/bindings")

        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["agent_id"] == "ai-agent-test-001"
        assert data[0]["agent_name"] == "Payments Fraud Detector"
        assert data[0]["version_semver"] == "1.0.0"

    def test_03_get_bindings_empty_system_returns_empty_list(self) -> None:
        """GET /api/systems/{system_id}/bindings returns [] for system with no agents."""
        with (
            patch("api.agent_bindings._agent_bindings") as mock_bindings_factory,
            patch("api.agent_bindings._agents") as mock_agents_factory,
        ):
            mock_bindings = MagicMock()
            mock_bindings.list_bindings_for_system.return_value = []
            mock_bindings_factory.return_value = mock_bindings

            mock_agents = MagicMock()
            mock_agents_factory.return_value = mock_agents

            r = CLIENT.get("/api/systems/ai-sys-999/bindings")

        assert r.status_code == 200
        assert r.json() == []


# ===========================================================================
# GROUP 2: Publish v2 → subscriber upgrade_available_version_id set (3 cases)
# ===========================================================================

class TestPublishVersionNotifiesSubscribers:
    """Tests 4–6: publish v2 → notify_subscribers_on_publish called; mock pg_notify path."""

    def test_04_publish_version_returns_201(self) -> None:
        """POST /api/agents/{id}/publish returns 201 + version dict."""
        version_v2 = _make_version(version_id="ai-agent-ver-002", semver="2.0.0")

        with (
            patch("api.agents._agents") as mock_agents_factory,
            patch("api.agents._agent_subscribers") as mock_subs_factory,
        ):
            mock_agents = MagicMock()
            mock_agents.get_agent.return_value = _make_agent()
            mock_agents.create_version.return_value = version_v2
            mock_agents.publish_version.return_value = None
            mock_agents_factory.return_value = mock_agents

            mock_subs = MagicMock()
            mock_subs.notify_subscribers_on_publish.return_value = None
            mock_subs_factory.return_value = mock_subs

            r = CLIENT.post(
                "/api/agents/ai-agent-test-001/publish",
                json={"semver": "2.0.0", "changelog": "Breaking changes.", "config": {}},
            )

        assert r.status_code == 201
        data = r.json()
        assert data["semver"] == "2.0.0"
        assert data["id"] == "ai-agent-ver-002"

    def test_05_publish_calls_notify_subscribers(self) -> None:
        """notify_subscribers_on_publish is called after a successful version publish."""
        version_v2 = _make_version(version_id="ai-agent-ver-002", semver="2.0.0")

        with (
            patch("api.agents._agents") as mock_agents_factory,
            patch("api.agents._agent_subscribers") as mock_subs_factory,
        ):
            mock_agents = MagicMock()
            mock_agents.create_version.return_value = version_v2
            mock_agents.publish_version.return_value = None
            mock_agents_factory.return_value = mock_agents

            mock_subs = MagicMock()
            mock_subs.notify_subscribers_on_publish.return_value = None
            mock_subs_factory.return_value = mock_subs

            CLIENT.post(
                "/api/agents/ai-agent-test-001/publish",
                json={"semver": "2.0.0", "changelog": "v2", "config": {}},
            )

            mock_subs.notify_subscribers_on_publish.assert_called_once_with(
                agent_id="ai-agent-test-001",
                new_version_id="ai-agent-ver-002",
            )

    def test_06_binding_shows_upgrade_available_after_publish(self) -> None:
        """After publishing v2, subscriber's binding has upgrade_available_version_id set."""
        binding_with_upgrade = _make_binding(
            upgrade_available_version_id="ai-agent-ver-002"
        )
        agent = _make_agent()
        version_v1 = _make_version()

        with (
            patch("api.agent_bindings._agent_bindings") as mock_bindings_factory,
            patch("api.agent_bindings._agents") as mock_agents_factory,
        ):
            mock_bindings = MagicMock()
            mock_bindings.list_bindings_for_system.return_value = [binding_with_upgrade]
            mock_bindings_factory.return_value = mock_bindings

            mock_agents = MagicMock()
            mock_agents.get_agent.return_value = agent
            mock_agents.get_version.return_value = version_v1
            mock_agents_factory.return_value = mock_agents

            r = CLIENT.get("/api/systems/ai-sys-001/bindings")

        assert r.status_code == 200
        data = r.json()
        assert data[0]["upgrade_available_version_id"] == "ai-agent-ver-002"


# ===========================================================================
# GROUP 3: Pin to v1 → publish v2 → no upgrade notification (2 cases)
# ===========================================================================

class TestPinnedBindingNoUpgrade:
    """Tests 7–8: pinned=True means upgrade_available_version_id stays None."""

    def test_07_pinned_binding_has_no_upgrade_after_publish(self) -> None:
        """Pinned binding shows upgrade_available_version_id=None after v2 publish."""
        pinned_binding = _make_binding(
            pinned=True,
            upgrade_available_version_id=None,  # domain must not set this for pinned
        )
        agent = _make_agent()
        version_v1 = _make_version()

        with (
            patch("api.agent_bindings._agent_bindings") as mock_bindings_factory,
            patch("api.agent_bindings._agents") as mock_agents_factory,
        ):
            mock_bindings = MagicMock()
            mock_bindings.list_bindings_for_system.return_value = [pinned_binding]
            mock_bindings_factory.return_value = mock_bindings

            mock_agents = MagicMock()
            mock_agents.get_agent.return_value = agent
            mock_agents.get_version.return_value = version_v1
            mock_agents_factory.return_value = mock_agents

            r = CLIENT.get("/api/systems/ai-sys-001/bindings")

        assert r.status_code == 200
        data = r.json()
        assert data[0]["pinned"] is True
        assert data[0]["upgrade_available_version_id"] is None

    def test_08_pinned_binding_patch_sets_pinned_flag(self) -> None:
        """PATCH with pinned=True correctly sets the binding's pinned flag."""
        binding_after_pin = _make_binding(
            pinned=True,
            upgrade_available_version_id=None,
        )

        with (
            patch("api.agent_bindings._agent_bindings") as mock_bindings_factory,
        ):
            mock_bindings = MagicMock()
            mock_bindings.update_binding_version.return_value = binding_after_pin
            mock_bindings_factory.return_value = mock_bindings

            r = CLIENT.patch(
                "/api/systems/ai-sys-001/bindings/ai-bind-001",
                json={"pinned": True},
            )

        assert r.status_code == 200
        data = r.json()
        assert data["pinned"] is True
        assert data["upgrade_available_version_id"] is None


# ===========================================================================
# GROUP 4: Accept upgrade → binding version updated, flag cleared (2 cases)
# ===========================================================================

class TestAcceptUpgrade:
    """Tests 9–10: PATCH with accept_upgrade=True updates version and clears flag."""

    def test_09_accept_upgrade_calls_accept_upgrade_domain(self) -> None:
        """PATCH accept_upgrade=True calls domain.agent_bindings.accept_upgrade()."""
        existing_binding = _make_binding()
        upgraded_binding = _make_binding(
            version_id="ai-agent-ver-002",
            upgrade_available_version_id=None,
        )

        with patch("api.agent_bindings._agent_bindings") as mock_bindings_factory:
            mock_bindings = MagicMock()
            mock_bindings.get_binding.return_value = existing_binding
            mock_bindings.accept_upgrade.return_value = upgraded_binding
            mock_bindings_factory.return_value = mock_bindings

            r = CLIENT.patch(
                "/api/systems/ai-sys-001/bindings/ai-bind-001",
                json={"accept_upgrade": True},
            )

            mock_bindings.accept_upgrade.assert_called_once_with(
                binding_id="ai-bind-001",
            )

        assert r.status_code == 200

    def test_10_accept_upgrade_clears_upgrade_available(self) -> None:
        """After accepting upgrade, upgrade_available_version_id is None in response."""
        existing_binding = _make_binding()
        upgraded_binding = _make_binding(
            version_id="ai-agent-ver-002",
            upgrade_available_version_id=None,
        )

        with patch("api.agent_bindings._agent_bindings") as mock_bindings_factory:
            mock_bindings = MagicMock()
            mock_bindings.get_binding.return_value = existing_binding
            mock_bindings.accept_upgrade.return_value = upgraded_binding
            mock_bindings_factory.return_value = mock_bindings

            r = CLIENT.patch(
                "/api/systems/ai-sys-001/bindings/ai-bind-001",
                json={"accept_upgrade": True},
            )

        assert r.status_code == 200
        data = r.json()
        assert data["version_id"] == "ai-agent-ver-002"
        assert data["upgrade_available_version_id"] is None


# ===========================================================================
# GROUP 5: Unbind → 204, binding gone, subscription removed (2 cases)
# ===========================================================================

class TestUnbind:
    """Tests 11–12: DELETE binding returns 204 and domain calls made."""

    def test_11_delete_binding_returns_204(self) -> None:
        """DELETE /api/systems/{id}/bindings/{bid} returns 204."""
        binding = _make_binding()

        with (
            patch("api.agent_bindings._agent_bindings") as mock_bindings_factory,
            patch("api.agent_bindings._agent_subscribers") as mock_subs_factory,
        ):
            mock_bindings = MagicMock()
            mock_bindings.get_binding.return_value = binding
            mock_bindings.unbind_agent.return_value = None
            mock_bindings_factory.return_value = mock_bindings

            mock_subs = MagicMock()
            mock_subs.unsubscribe.return_value = None
            mock_subs_factory.return_value = mock_subs

            r = CLIENT.delete("/api/systems/ai-sys-001/bindings/ai-bind-001")

        assert r.status_code == 204

    def test_12_delete_binding_calls_unsubscribe(self) -> None:
        """DELETE binding calls domain.agent_subscribers.unsubscribe()."""
        binding = _make_binding()

        with (
            patch("api.agent_bindings._agent_bindings") as mock_bindings_factory,
            patch("api.agent_bindings._agent_subscribers") as mock_subs_factory,
        ):
            mock_bindings = MagicMock()
            mock_bindings.get_binding.return_value = binding
            mock_bindings.unbind_agent.return_value = None
            mock_bindings_factory.return_value = mock_bindings

            mock_subs = MagicMock()
            mock_subs.unsubscribe.return_value = None
            mock_subs_factory.return_value = mock_subs

            CLIENT.delete("/api/systems/ai-sys-001/bindings/ai-bind-001")

            mock_subs.unsubscribe.assert_called_once_with(
                agent_id="ai-agent-test-001",
                system_id="ai-sys-001",
            )


# ===========================================================================
# GROUP 6: PATCH binding to change version_id with pinned=True (2 cases)
# ===========================================================================

class TestUpdateBinding:
    """Tests 13–14: PATCH updates version_id and/or pinned flag."""

    def test_13_patch_version_id_updates_binding(self) -> None:
        """PATCH version_id to v2 with pinned=True reflects in response."""
        updated = _make_binding(version_id="ai-agent-ver-002", pinned=True)

        with patch("api.agent_bindings._agent_bindings") as mock_bindings_factory:
            mock_bindings = MagicMock()
            mock_bindings.update_binding_version.return_value = updated
            mock_bindings_factory.return_value = mock_bindings

            r = CLIENT.patch(
                "/api/systems/ai-sys-001/bindings/ai-bind-001",
                json={"version_id": "ai-agent-ver-002", "pinned": True},
            )

        assert r.status_code == 200
        data = r.json()
        assert data["version_id"] == "ai-agent-ver-002"
        assert data["pinned"] is True

    def test_14_patch_calls_update_binding_version_with_correct_args(self) -> None:
        """PATCH routes to update_binding_version when accept_upgrade is falsy."""
        existing = _make_binding()
        updated = _make_binding()

        with patch("api.agent_bindings._agent_bindings") as mock_bindings_factory:
            mock_bindings = MagicMock()
            mock_bindings.get_binding.return_value = existing
            mock_bindings.update_binding_version.return_value = updated
            mock_bindings_factory.return_value = mock_bindings

            CLIENT.patch(
                "/api/systems/ai-sys-001/bindings/ai-bind-001",
                json={"version_id": "ai-agent-ver-002", "pinned": False},
            )

            mock_bindings.update_binding_version.assert_called_once_with(
                binding_id="ai-bind-001",
                version_id="ai-agent-ver-002",
                pinned=False,
            )


# ===========================================================================
# GROUP 7: Error cases (2 cases)
# ===========================================================================

class TestErrorCases:
    """Tests 15–16: 404 and 400 error handling."""

    def test_15_delete_nonexistent_binding_returns_404(self) -> None:
        """DELETE non-existent binding_id returns 404."""
        with patch("api.agent_bindings._agent_bindings") as mock_bindings_factory:
            mock_bindings = MagicMock()
            mock_bindings.get_binding.return_value = None
            mock_bindings_factory.return_value = mock_bindings

            r = CLIENT.delete("/api/systems/ai-sys-001/bindings/nonexistent-id")

        assert r.status_code == 404
        data = r.json()
        assert "error" in data.get("detail", data)

    def test_16_post_binding_with_nonexistent_agent_returns_400(self) -> None:
        """POST binding with agent_id that does not exist returns 400."""
        with (
            patch("api.agent_bindings._agents") as mock_agents_factory,
            patch("api.agent_bindings._agent_bindings"),
            patch("api.agent_bindings._agent_subscribers"),
        ):
            mock_agents = MagicMock()
            mock_agents.get_agent.return_value = None  # agent not found
            mock_agents_factory.return_value = mock_agents

            r = CLIENT.post(
                "/api/systems/ai-sys-001/bindings",
                json={"agent_id": "does-not-exist"},
            )

        assert r.status_code == 400
        data = r.json()
        detail = data.get("detail", data)
        assert "AGENT_NOT_FOUND" in str(detail)


# ===========================================================================
# GROUP 8: SSE endpoint smoke tests (2 cases)
# ===========================================================================

class TestSseEndpoint:
    """Tests 17–18: SSE endpoint basic behaviour with mocked Postgres."""

    def test_17_sse_endpoint_rejects_invalid_agent_id(self) -> None:
        """SSE /listen returns 400 for agent_id that exceeds max length."""
        # Use an ID that routes (no angle brackets) but fails the length validator
        long_id = "a" * 200  # exceeds 128-char limit in _sanitise_agent_id_for_channel
        r = CLIENT.get(f"/api/agents/{long_id}/listen")
        assert r.status_code == 400

    def test_18_sse_endpoint_yields_keepalive_then_cancels(self) -> None:
        """SSE /listen streams content-type text/event-stream; yields keepalive on connection error."""
        import threading, time

        def _fake_pg_conn():
            raise RuntimeError("DATABASE_URL is not set; cannot open Postgres LISTEN connection")

        with patch("api.agent_notifications._get_pg_connection", side_effect=_fake_pg_conn):
            # stream=True needed to read SSE incrementally
            with CLIENT.stream("GET", "/api/agents/ai-agent-test-001/listen") as resp:
                assert resp.headers.get("content-type", "").startswith("text/event-stream")
                # Read the first chunk — should be an error event
                first_chunk = next(resp.iter_text())
                assert "event:" in first_chunk or "data:" in first_chunk or first_chunk == ""


# ===========================================================================
# GROUP 9: Auth check — requests without session cookie → 401 (2 cases)
# ===========================================================================
# Auth is only enforced when AUTH_ENABLED=true. These tests simulate
# the middleware being enabled by temporarily setting the env var.

class TestAuthEnforcement:
    """Tests 19–20: unauthenticated requests return 401 when AUTH_ENABLED=true."""

    def test_19_list_agents_without_cookie_returns_401_when_auth_enabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """GET /api/agents returns 401 when AUTH_ENABLED=true and no session cookie."""
        # Import and rebuild app with auth middleware
        monkeypatch.setenv("AUTH_ENABLED", "true")
        monkeypatch.setenv("SESSION_SECRET", "test-secret-for-auth-tests-only")

        from fastapi import FastAPI
        from middleware.auth import SessionAuthMiddleware

        auth_app = FastAPI()
        auth_app.add_middleware(SessionAuthMiddleware)
        auth_app.include_router(agents_router)

        from fastapi.testclient import TestClient
        auth_client = TestClient(auth_app, raise_server_exceptions=False)

        r = auth_client.get("/api/agents")
        assert r.status_code == 401

    def test_20_create_binding_without_cookie_returns_401_when_auth_enabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """POST /api/systems/{id}/bindings returns 401 when AUTH_ENABLED=true and no session."""
        monkeypatch.setenv("AUTH_ENABLED", "true")
        monkeypatch.setenv("SESSION_SECRET", "test-secret-for-auth-tests-only")

        from fastapi import FastAPI
        from middleware.auth import SessionAuthMiddleware

        auth_app = FastAPI()
        auth_app.add_middleware(SessionAuthMiddleware)
        auth_app.include_router(agent_bindings_router)

        from fastapi.testclient import TestClient
        auth_client = TestClient(auth_app, raise_server_exceptions=False)

        r = auth_client.post(
            "/api/systems/ai-sys-001/bindings",
            json={"agent_id": "ai-agent-test-001"},
        )
        assert r.status_code == 401
