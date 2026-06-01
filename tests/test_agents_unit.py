"""Unit tests for agent registry, versioning, subscriptions, and binding lifecycle.

50 test cases covering:
  - Agent CRUD (10)
  - Version semantics (15)
  - Ownership enforcement (5)
  - Subscription state machine (10)
  - AgentBinding lifecycle (10)

All tests use mocked SQLAlchemy engine — no live DB or sqlalchemy install required.
The mocks patch both the module-level _engine and the sqlalchemy.text call inside
each function so that import errors for the optional dependency are avoided.
"""

from __future__ import annotations

import json
import sys
import types
import uuid
from datetime import datetime, timezone
from typing import Any, Optional
from unittest.mock import MagicMock, patch, call
import pytest


# ---------------------------------------------------------------------------
# Stub sqlalchemy at sys.modules level before any domain imports so that
# "from sqlalchemy import text" inside domain functions resolves to our mock.
# ---------------------------------------------------------------------------

def _make_sqlalchemy_stub() -> types.ModuleType:
    """Return a minimal stub for the sqlalchemy package."""
    sa = types.ModuleType("sqlalchemy")

    def text(sql: str) -> str:  # noqa: ANN001
        return sql  # return the SQL string as-is for mock assertions

    sa.text = text  # type: ignore[attr-defined]

    # Sub-module sqlalchemy.orm (imported transitively by some modules)
    orm = types.ModuleType("sqlalchemy.orm")
    sa.orm = orm  # type: ignore[attr-defined]
    sys.modules.setdefault("sqlalchemy", sa)
    sys.modules.setdefault("sqlalchemy.orm", orm)
    return sa


_sa_stub = _make_sqlalchemy_stub()


# ---------------------------------------------------------------------------
# Autouse reset for the in-memory agent fallback (`domain.agents._inmem_agents`).
# Tests that exercise the no-engine path call `create_agent` which writes into
# this module-level dict. Without a per-test reset, test_08 (and any later
# `list_agents` no-engine assertion) sees leftover state and fails. S74.
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _reset_inmem_agents():
    from domain import agents as _agents_mod
    _agents_mod._inmem_agents.clear()
    yield
    _agents_mod._inmem_agents.clear()


# ---------------------------------------------------------------------------
# Now safe to import domain modules
# ---------------------------------------------------------------------------

from domain.models import (  # noqa: E402
    Agent,
    AgentBinding,
    AgentOwnerType,
    AgentStatus,
    AgentSubscriber,
    AgentVersion,
    RiskLevel,
)


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

UTC = timezone.utc


def _now() -> datetime:
    return datetime.now(UTC)


def _make_agent(
    agent_id: str = "ai-agent-test-001",
    name: str = "Test Agent",
    team: str = "platform",
    owner_type: AgentOwnerType = AgentOwnerType.REUSABLE,
    inherent_risk: RiskLevel = RiskLevel.MEDIUM,
    latest_version_id: Optional[str] = None,
) -> Agent:
    now = _now()
    return Agent(
        id=agent_id,
        name=name,
        description="A test agent.",
        team=team,
        owner_type=owner_type,
        latest_version_id=latest_version_id,
        inherent_risk=inherent_risk,
        framework_refs=[],
        created_at=now,
        updated_at=now,
    )


def _make_version(
    version_id: str = "ai-agent-ver-001",
    agent_id: str = "ai-agent-test-001",
    semver: str = "1.0.0",
    status: AgentStatus = AgentStatus.DRAFT,
) -> AgentVersion:
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
) -> AgentBinding:
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
) -> AgentSubscriber:
    return AgentSubscriber(
        id=sub_id,
        agent_id=agent_id,
        system_id=system_id,
        subscribed_at=_now(),
        last_notified_version_id=None,
    )


def _mock_engine_and_conn() -> tuple[MagicMock, MagicMock]:
    """Return (engine, conn) mocks whose context managers chain correctly."""
    engine = MagicMock()
    conn = MagicMock()

    # context manager for engine.begin()
    begin_ctx = MagicMock()
    begin_ctx.__enter__ = MagicMock(return_value=conn)
    begin_ctx.__exit__ = MagicMock(return_value=False)
    engine.begin.return_value = begin_ctx

    # context manager for engine.connect()
    connect_ctx = MagicMock()
    connect_ctx.__enter__ = MagicMock(return_value=conn)
    connect_ctx.__exit__ = MagicMock(return_value=False)
    engine.connect.return_value = connect_ctx

    return engine, conn


# ===========================================================================
# GROUP 1: Agent CRUD (10 tests)
# ===========================================================================

class TestAgentCRUD:
    """Tests 1–10: create, get, list, and filter agents."""

    def test_01_agent_model_round_trips(self) -> None:
        """Agent can be constructed and serialised without error."""
        agent = _make_agent()
        data = agent.model_dump()
        assert data["id"] == "ai-agent-test-001"
        assert data["owner_type"] == AgentOwnerType.REUSABLE
        assert data["inherent_risk"] == RiskLevel.MEDIUM

    def test_02_agent_model_enum_values_preserved(self) -> None:
        """use_enum_values=False means enum instances are stored, not strings."""
        agent = _make_agent(owner_type=AgentOwnerType.CUSTOM)
        assert isinstance(agent.owner_type, AgentOwnerType)
        assert agent.owner_type == AgentOwnerType.CUSTOM

    def test_03_create_agent_calls_db_insert(self) -> None:
        """create_agent executes an INSERT when engine is available."""
        engine, conn = _mock_engine_and_conn()
        conn.execute.return_value = MagicMock()

        with patch("domain.agents._engine", engine), \
             patch("domain.repository.append_agent_event"):
            from domain.agents import create_agent
            agent = create_agent(
                name="Fraud Agent",
                description="Fraud detection.",
                team="payments",
                owner_type=AgentOwnerType.CUSTOM,
                inherent_risk=RiskLevel.HIGH,
                agent_id="ai-agent-fraud",
            )

        assert agent.id == "ai-agent-fraud"
        assert agent.team == "payments"
        conn.execute.assert_called()

    def test_04_create_agent_no_engine_returns_in_memory(self) -> None:
        """create_agent with no engine returns an in-memory Agent without crashing."""
        with patch("domain.agents._engine", None), \
             patch("domain.repository.append_agent_event"):
            from domain.agents import create_agent
            agent = create_agent(
                name="Test",
                description="desc",
                team="cx",
                owner_type=AgentOwnerType.REUSABLE,
                inherent_risk=RiskLevel.LOW,
                agent_id="ai-agent-test-nomem",
            )

        assert agent.id == "ai-agent-test-nomem"
        assert agent.name == "Test"

    def test_05_get_agent_returns_none_when_not_found(self) -> None:
        """get_agent returns None on empty result set."""
        engine, conn = _mock_engine_and_conn()
        conn.execute.return_value.fetchone.return_value = None

        with patch("domain.agents._engine", engine):
            from domain.agents import get_agent
            result = get_agent("ai-agent-missing")

        assert result is None

    def test_06_get_agent_returns_none_on_no_engine(self) -> None:
        """get_agent returns None gracefully when engine is None."""
        with patch("domain.agents._engine", None):
            from domain.agents import get_agent
            result = get_agent("ai-agent-missing")

        assert result is None

    def test_07_get_agent_maps_row_correctly(self) -> None:
        """get_agent correctly maps a DB row to an Agent model."""
        now = _now()
        fake_row = (
            "ai-agent-pay-fraud",
            "Payment Fraud Detector",
            "Detects fraud.",
            "payments",
            "CUSTOM",
            "ai-agent-ver-001",
            "HIGH",
            '["NIST_AI_RMF:GOVERN-1.1"]',
            now,
            now,
        )

        engine, conn = _mock_engine_and_conn()
        conn.execute.return_value.fetchone.return_value = fake_row

        with patch("domain.agents._engine", engine):
            from domain.agents import get_agent
            agent = get_agent("ai-agent-pay-fraud")

        assert agent is not None
        assert agent.id == "ai-agent-pay-fraud"
        assert agent.owner_type == AgentOwnerType.CUSTOM
        assert agent.inherent_risk == RiskLevel.HIGH
        assert agent.latest_version_id == "ai-agent-ver-001"

    def test_08_list_agents_returns_empty_list_no_engine(self) -> None:
        """list_agents returns [] when engine is unavailable."""
        with patch("domain.agents._engine", None):
            from domain.agents import list_agents
            result = list_agents()

        assert result == []

    def test_09_list_agents_with_team_filter(self) -> None:
        """list_agents passes team filter to query params."""
        now = _now()
        fake_row = (
            "ai-agent-cx-router", "CX Router", "Routes.", "cx",
            "CUSTOM", None, "MEDIUM", "[]", now, now,
        )

        engine, conn = _mock_engine_and_conn()
        conn.execute.return_value.fetchall.return_value = [fake_row]

        with patch("domain.agents._engine", engine):
            from domain.agents import list_agents
            results = list_agents(team="cx")

        assert len(results) == 1
        assert results[0].team == "cx"

    def test_10_list_agents_with_owner_type_filter(self) -> None:
        """list_agents passes owner_type filter to query params."""
        now = _now()
        fake_row = (
            "ai-agent-pii-redactor", "PII Redactor", "Redacts PII.", "platform",
            "REUSABLE", None, "CRITICAL", "[]", now, now,
        )

        engine, conn = _mock_engine_and_conn()
        conn.execute.return_value.fetchall.return_value = [fake_row]

        with patch("domain.agents._engine", engine):
            from domain.agents import list_agents
            results = list_agents(owner_type=AgentOwnerType.REUSABLE)

        assert len(results) == 1
        assert results[0].owner_type == AgentOwnerType.REUSABLE


# ===========================================================================
# GROUP 2: Version semantics (15 tests)
# ===========================================================================

class TestVersionSemantics:
    """Tests 11–25: semver validation, create/publish, status transitions."""

    def test_11_semver_valid_simple(self) -> None:
        """'1.0.0' is a valid semver."""
        v = _make_version(semver="1.0.0")
        assert v.semver == "1.0.0"

    def test_12_semver_valid_higher_numbers(self) -> None:
        """'2.3.4' is a valid semver."""
        v = _make_version(semver="2.3.4")
        assert v.semver == "2.3.4"

    def test_13_semver_valid_pre_release(self) -> None:
        """'2.3.4-rc.1' is a valid semver with pre-release."""
        v = _make_version(semver="2.3.4-rc.1")
        assert v.semver == "2.3.4-rc.1"

    def test_14_semver_valid_zero_patch(self) -> None:
        """'0.0.1' is a valid minimal semver."""
        v = _make_version(semver="0.0.1")
        assert v.semver == "0.0.1"

    def test_15_semver_invalid_missing_patch(self) -> None:
        """'1.0' (missing patch) must raise ValidationError."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            AgentVersion(
                id="v1", agent_id="a1", semver="1.0",
                changelog="x", status=AgentStatus.DRAFT, config={},
            )

    def test_16_semver_invalid_v_prefix(self) -> None:
        """'v1.0.0' (v prefix) must raise ValidationError."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            AgentVersion(
                id="v1", agent_id="a1", semver="v1.0.0",
                changelog="x", status=AgentStatus.DRAFT, config={},
            )

    def test_17_semver_invalid_four_parts(self) -> None:
        """'1.0.0.0' (four parts) must raise ValidationError."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            AgentVersion(
                id="v1", agent_id="a1", semver="1.0.0.0",
                changelog="x", status=AgentStatus.DRAFT, config={},
            )

    def test_18_semver_invalid_alpha(self) -> None:
        """'abc' must raise ValidationError."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            AgentVersion(
                id="v1", agent_id="a1", semver="abc",
                changelog="x", status=AgentStatus.DRAFT, config={},
            )

    def test_19_create_version_inserts_row(self) -> None:
        """create_version executes INSERT into agent_versions."""
        engine, conn = _mock_engine_and_conn()
        conn.execute.return_value = MagicMock()

        with patch("domain.agents._engine", engine), \
             patch("domain.repository.append_agent_event"):
            from domain.agents import create_version
            version = create_version(
                agent_id="ai-agent-test-001",
                semver="1.0.0",
                changelog="First.",
            )

        assert version.semver == "1.0.0"
        assert version.status == AgentStatus.DRAFT
        conn.execute.assert_called()

    def test_20_create_second_version(self) -> None:
        """Creating v1.0.1 after v1.0.0 gives separate version ids."""
        engine, conn = _mock_engine_and_conn()
        conn.execute.return_value = MagicMock()

        with patch("domain.agents._engine", engine), \
             patch("domain.repository.append_agent_event"):
            from domain.agents import create_version
            v1 = create_version("ai-agent-test-001", "1.0.0", "First.", config={})
            v2 = create_version("ai-agent-test-001", "1.0.1", "Patch.", config={})

        assert v1.id != v2.id
        assert v2.semver == "1.0.1"

    def test_21_publish_version_sets_published_status(self) -> None:
        """publish_version returns AgentVersion with status=PUBLISHED."""
        now = _now()
        draft_row = (
            "ai-agent-ver-001", "ai-agent-test-001", "1.0.0", "Initial.",
            "DRAFT", "{}", None, None,
        )
        published_row = (
            "ai-agent-ver-001", "ai-agent-test-001", "1.0.0", "Initial.",
            "PUBLISHED", "{}", now, "system",
        )

        engine, conn = _mock_engine_and_conn()
        # First .fetchone() is the FOR UPDATE lock read (draft_row),
        # second is the post-commit re-fetch (published_row)
        conn.execute.return_value.fetchone.side_effect = [draft_row, published_row]
        update_result = MagicMock()
        update_result.rowcount = 1

        with patch("domain.agents._engine", engine), \
             patch("domain.repository.append_agent_event"), \
             patch("domain.agent_subscribers.notify_subscribers_on_publish", return_value=0):
            from domain.agents import publish_version
            result = publish_version("ai-agent-ver-001", "system")

        assert result.status == AgentStatus.PUBLISHED

    def test_22_publish_already_published_raises(self) -> None:
        """publish_version raises ValueError if version is already PUBLISHED."""
        now = _now()
        already_published_row = (
            "ai-agent-ver-001", "ai-agent-test-001", "1.0.0", "Initial.",
            "PUBLISHED", "{}", now, "system",
        )

        engine, conn = _mock_engine_and_conn()
        conn.execute.return_value.fetchone.return_value = already_published_row

        with patch("domain.agents._engine", engine), \
             patch("domain.repository.append_agent_event"):
            from domain.agents import publish_version
            with pytest.raises(ValueError, match="only DRAFT versions can be published"):
                publish_version("ai-agent-ver-001", "tester")

    def test_23_publish_version_not_found_raises(self) -> None:
        """publish_version raises ValueError for unknown version_id."""
        engine, conn = _mock_engine_and_conn()
        conn.execute.return_value.fetchone.return_value = None

        with patch("domain.agents._engine", engine):
            from domain.agents import publish_version
            with pytest.raises(ValueError, match="not found"):
                publish_version("ai-agent-ver-nonexistent", "tester")

    def test_24_list_versions_returns_empty_on_no_engine(self) -> None:
        """list_versions returns [] when engine is unavailable."""
        with patch("domain.agents._engine", None):
            from domain.agents import list_versions
            result = list_versions("ai-agent-test-001")

        assert result == []

    def test_25_list_versions_maps_rows_correctly(self) -> None:
        """list_versions returns correctly typed AgentVersion instances."""
        now = _now()
        rows = [
            ("ai-agent-ver-001", "ai-agent-test-001", "1.0.0", "v1.", "PUBLISHED", "{}", now, "seed"),
            ("ai-agent-ver-002", "ai-agent-test-001", "1.0.1", "v2.", "DRAFT", "{}", None, None),
        ]

        engine, conn = _mock_engine_and_conn()
        conn.execute.return_value.fetchall.return_value = rows

        with patch("domain.agents._engine", engine):
            from domain.agents import list_versions
            versions = list_versions("ai-agent-test-001")

        assert len(versions) == 2
        assert versions[0].semver == "1.0.0"
        assert versions[0].status == AgentStatus.PUBLISHED
        assert versions[1].semver == "1.0.1"
        assert versions[1].status == AgentStatus.DRAFT


# ===========================================================================
# GROUP 3: Ownership enforcement (5 tests)
# ===========================================================================

class TestOwnershipEnforcement:
    """Tests 26–30: CUSTOM vs REUSABLE rules."""

    def test_26_custom_agent_has_custom_owner_type(self) -> None:
        """CUSTOM agent stores owner_type=CUSTOM."""
        agent = _make_agent(owner_type=AgentOwnerType.CUSTOM)
        assert agent.owner_type == AgentOwnerType.CUSTOM

    def test_27_reusable_agent_has_reusable_owner_type(self) -> None:
        """REUSABLE agent stores owner_type=REUSABLE."""
        agent = _make_agent(owner_type=AgentOwnerType.REUSABLE)
        assert agent.owner_type == AgentOwnerType.REUSABLE

    def test_28_team_field_is_required(self) -> None:
        """Agent.team is required and cannot be empty string by convention."""
        agent = _make_agent(team="payments")
        assert agent.team == "payments"

    def test_29_owner_type_enum_only_accepts_valid_values(self) -> None:
        """AgentOwnerType only accepts CUSTOM and REUSABLE."""
        assert set(AgentOwnerType.__members__.keys()) == {"CUSTOM", "REUSABLE"}

    def test_30_create_agent_with_reusable_type_succeeds(self) -> None:
        """REUSABLE agents can be created via create_agent without error."""
        with patch("domain.agents._engine", None), \
             patch("domain.repository.append_agent_event"):
            from domain.agents import create_agent
            agent = create_agent(
                name="PII Redactor",
                description="Redacts PII.",
                team="platform",
                owner_type=AgentOwnerType.REUSABLE,
                inherent_risk=RiskLevel.CRITICAL,
                agent_id="ai-agent-pii-test",
            )

        assert agent.owner_type == AgentOwnerType.REUSABLE


# ===========================================================================
# GROUP 4: Subscription state machine (10 tests)
# ===========================================================================

class TestSubscriptionStateMachine:
    """Tests 31–40: subscribe, unsubscribe, list, notify, pinned vs unpinned."""

    def test_31_subscribe_inserts_row(self) -> None:
        """subscribe executes INSERT ON CONFLICT DO NOTHING."""
        now = _now()
        engine, conn = _mock_engine_and_conn()
        conn.execute.return_value = MagicMock()
        conn.execute.return_value.fetchone.return_value = (
            "ai-sub-001", "ai-agent-test-001", "ai-sys-001", now, None
        )

        with patch("domain.agent_subscribers._engine", engine):
            from domain.agent_subscribers import subscribe
            sub = subscribe("ai-agent-test-001", "ai-sys-001")

        assert sub.agent_id == "ai-agent-test-001"
        assert sub.system_id == "ai-sys-001"

    def test_32_subscribe_no_engine_returns_in_memory(self) -> None:
        """subscribe with no engine returns in-memory subscriber without crashing."""
        with patch("domain.agent_subscribers._engine", None):
            from domain.agent_subscribers import subscribe
            sub = subscribe("ai-agent-test-001", "ai-sys-001")

        assert sub.agent_id == "ai-agent-test-001"

    def test_33_unsubscribe_executes_delete(self) -> None:
        """unsubscribe executes DELETE statement."""
        engine, conn = _mock_engine_and_conn()
        conn.execute.return_value = MagicMock()

        with patch("domain.agent_subscribers._engine", engine):
            from domain.agent_subscribers import unsubscribe
            unsubscribe("ai-agent-test-001", "ai-sys-001")

        conn.execute.assert_called()

    def test_34_unsubscribe_no_engine_is_noop(self) -> None:
        """unsubscribe with no engine completes without error."""
        with patch("domain.agent_subscribers._engine", None):
            from domain.agent_subscribers import unsubscribe
            unsubscribe("ai-agent-test-001", "ai-sys-001")  # must not raise

    def test_35_list_subscribers_returns_empty_no_engine(self) -> None:
        """list_subscribers returns [] when engine is unavailable."""
        with patch("domain.agent_subscribers._engine", None):
            from domain.agent_subscribers import list_subscribers
            result = list_subscribers("ai-agent-test-001")

        assert result == []

    def test_36_list_subscribers_maps_rows(self) -> None:
        """list_subscribers returns correctly typed AgentSubscriber instances."""
        now = _now()
        rows = [
            ("ai-sub-001", "ai-agent-pii-redactor", "ai-sys-001", now, "v-001"),
            ("ai-sub-002", "ai-agent-pii-redactor", "ai-sys-002", now, None),
        ]

        engine, conn = _mock_engine_and_conn()
        conn.execute.return_value.fetchall.return_value = rows

        with patch("domain.agent_subscribers._engine", engine):
            from domain.agent_subscribers import list_subscribers
            subs = list_subscribers("ai-agent-pii-redactor")

        assert len(subs) == 2
        assert subs[0].system_id == "ai-sys-001"
        assert subs[0].last_notified_version_id == "v-001"
        assert subs[1].last_notified_version_id is None

    def test_37_notify_subscribers_updates_unpinned_bindings(self) -> None:
        """notify_subscribers_on_publish updates only unpinned binding rows."""
        engine, conn = _mock_engine_and_conn()
        update_result = MagicMock()
        update_result.rowcount = 2  # 2 unpinned bindings updated
        conn.execute.return_value = update_result

        with patch("domain.agent_subscribers._engine", engine), \
             patch("domain.repository.append_agent_event"):
            from domain.agent_subscribers import notify_subscribers_on_publish
            count = notify_subscribers_on_publish("ai-agent-pii-redactor", "ver-002")

        assert count == 2

    def test_38_notify_subscribers_returns_zero_no_engine(self) -> None:
        """notify_subscribers_on_publish returns 0 when engine is unavailable."""
        with patch("domain.agent_subscribers._engine", None):
            from domain.agent_subscribers import notify_subscribers_on_publish
            count = notify_subscribers_on_publish("ai-agent-test-001", "ver-002")

        assert count == 0

    def test_39_mark_notified_updates_subscriber(self) -> None:
        """mark_notified executes UPDATE and succeeds on valid subscriber_id."""
        engine, conn = _mock_engine_and_conn()
        result = MagicMock()
        result.rowcount = 1
        conn.execute.return_value = result

        with patch("domain.agent_subscribers._engine", engine):
            from domain.agent_subscribers import mark_notified
            mark_notified("ai-sub-001", "ver-002")  # must not raise

        conn.execute.assert_called()

    def test_40_mark_notified_raises_on_not_found(self) -> None:
        """mark_notified raises ValueError when subscriber_id not found."""
        engine, conn = _mock_engine_and_conn()
        result = MagicMock()
        result.rowcount = 0
        conn.execute.return_value = result

        with patch("domain.agent_subscribers._engine", engine):
            from domain.agent_subscribers import mark_notified
            with pytest.raises(ValueError, match="not found"):
                mark_notified("ai-sub-missing", "ver-002")


# ===========================================================================
# GROUP 5: AgentBinding lifecycle (10 tests)
# ===========================================================================

class TestAgentBindingLifecycle:
    """Tests 41–50: bind, update, unbind, accept upgrade."""

    def test_41_bind_with_default_version_uses_latest(self) -> None:
        """bind_agent_to_system resolves version from agent.latest_version_id when none supplied."""
        now = _now()
        fake_agent_row = (
            "ai-agent-pii-redactor", "PII Redactor", "Redacts.", "platform",
            "REUSABLE", "ver-001", "CRITICAL", "[]", now, now,
        )

        engine, conn = _mock_engine_and_conn()
        conn.execute.return_value.fetchone.return_value = fake_agent_row

        with patch("domain.agents._engine", engine), \
             patch("domain.agent_bindings._engine", engine), \
             patch("domain.agent_subscribers._engine", None), \
             patch("domain.repository.append_agent_event"):
            from domain.agent_bindings import bind_agent_to_system
            binding = bind_agent_to_system("ai-agent-pii-redactor", "ai-sys-001")

        assert binding.agent_id == "ai-agent-pii-redactor"
        assert binding.version_id == "ver-001"
        assert binding.pinned is False

    def test_42_bind_with_explicit_version_sets_pinned_true(self) -> None:
        """bind_agent_to_system with explicit version_id forces pinned=True."""
        engine, conn = _mock_engine_and_conn()
        conn.execute.return_value = MagicMock()

        with patch("domain.agent_bindings._engine", engine), \
             patch("domain.agent_subscribers._engine", None), \
             patch("domain.repository.append_agent_event"):
            from domain.agent_bindings import bind_agent_to_system
            binding = bind_agent_to_system(
                "ai-agent-pii-redactor", "ai-sys-001", version_id="ver-001"
            )

        assert binding.pinned is True
        assert binding.version_id == "ver-001"

    def test_43_bind_agent_not_found_raises(self) -> None:
        """bind_agent_to_system raises ValueError when agent not found and no version given."""
        engine, conn = _mock_engine_and_conn()
        conn.execute.return_value.fetchone.return_value = None

        with patch("domain.agents._engine", engine), \
             patch("domain.agent_bindings._engine", engine):
            from domain.agent_bindings import bind_agent_to_system
            with pytest.raises(ValueError, match="not found"):
                bind_agent_to_system("ai-agent-missing", "ai-sys-001")

    def test_44_list_bindings_for_system_returns_empty_no_engine(self) -> None:
        """list_bindings_for_system returns [] when engine is unavailable."""
        with patch("domain.agent_bindings._engine", None):
            from domain.agent_bindings import list_bindings_for_system
            result = list_bindings_for_system("ai-sys-001")

        assert result == []

    def test_45_list_bindings_for_agent_maps_rows(self) -> None:
        """list_bindings_for_agent returns correctly typed AgentBinding instances."""
        now = _now()
        rows = [
            ("ai-bind-001", "ai-agent-pii-redactor", "ai-sys-001",
             "ver-001", False, None, now, now),
            ("ai-bind-002", "ai-agent-pii-redactor", "ai-sys-002",
             "ver-001", True, "ver-002", now, now),
        ]

        engine, conn = _mock_engine_and_conn()
        conn.execute.return_value.fetchall.return_value = rows

        with patch("domain.agent_bindings._engine", engine):
            from domain.agent_bindings import list_bindings_for_agent
            bindings = list_bindings_for_agent("ai-agent-pii-redactor")

        assert len(bindings) == 2
        assert bindings[0].pinned is False
        assert bindings[1].pinned is True
        assert bindings[1].upgrade_available_version_id == "ver-002"

    def test_46_update_binding_version_clears_upgrade_available(self) -> None:
        """update_binding_version sets upgrade_available_version_id to NULL."""
        now = _now()
        updated_row = ("ai-bind-001", "ai-agent-pii-redactor", "ai-sys-001",
                       "ver-002", False, None, now, now)

        engine, conn = _mock_engine_and_conn()
        update_result = MagicMock()
        update_result.rowcount = 1
        conn.execute.return_value = update_result
        conn.execute.return_value.fetchone.return_value = updated_row

        with patch("domain.agent_bindings._engine", engine):
            from domain.agent_bindings import update_binding_version
            binding = update_binding_version("ai-bind-001", "ver-002")

        assert binding.version_id == "ver-002"
        assert binding.upgrade_available_version_id is None

    def test_47_update_binding_version_not_found_raises(self) -> None:
        """update_binding_version raises ValueError if binding not found."""
        engine, conn = _mock_engine_and_conn()
        result = MagicMock()
        result.rowcount = 0
        conn.execute.return_value = result

        with patch("domain.agent_bindings._engine", engine):
            from domain.agent_bindings import update_binding_version
            with pytest.raises(ValueError, match="not found"):
                update_binding_version("ai-bind-missing", "ver-002")

    def test_48_unbind_agent_executes_delete_and_emits_event(self) -> None:
        """unbind_agent executes DELETE and appends AGENT_BINDING_REMOVED event."""
        fetch_row = ("ai-bind-001", "ai-agent-pii-redactor", "ai-sys-001")

        engine, conn = _mock_engine_and_conn()
        conn.execute.return_value.fetchone.return_value = fetch_row

        with patch("domain.agent_bindings._engine", engine), \
             patch("domain.agent_subscribers._engine", None), \
             patch("domain.repository.append_agent_event") as mock_event:
            from domain.agent_bindings import unbind_agent
            unbind_agent("ai-bind-001")

        mock_event.assert_called_once()
        event_type = mock_event.call_args[0][0]
        assert event_type == "AGENT_BINDING_REMOVED"

    def test_49_unbind_agent_not_found_raises(self) -> None:
        """unbind_agent raises ValueError when binding_id not found."""
        engine, conn = _mock_engine_and_conn()
        conn.execute.return_value.fetchone.return_value = None

        with patch("domain.agent_bindings._engine", engine):
            from domain.agent_bindings import unbind_agent
            with pytest.raises(ValueError, match="not found"):
                unbind_agent("ai-bind-missing")

    def test_50_accept_upgrade_moves_upgrade_to_version_id(self) -> None:
        """accept_upgrade sets version_id=upgrade_available_version_id and clears pending."""
        now = _now()
        # Binding with pending upgrade
        before_row = ("ai-bind-001", "ai-agent-pii-redactor", "ai-sys-001",
                      "ver-001", False, "ver-002", now, now)
        # After update
        after_row = ("ai-bind-001", "ai-agent-pii-redactor", "ai-sys-001",
                     "ver-002", False, None, now, now)

        engine, conn = _mock_engine_and_conn()
        conn.execute.return_value.fetchone.side_effect = [before_row, after_row]

        with patch("domain.agent_bindings._engine", engine), \
             patch("domain.repository.append_agent_event"):
            from domain.agent_bindings import accept_upgrade
            binding = accept_upgrade("ai-bind-001")

        assert binding.version_id == "ver-002"
        assert binding.upgrade_available_version_id is None
        assert binding.pinned is False
