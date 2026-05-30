"""Tests for signallayer.write_episode — the S71 SDK-level helper.

Confirms the SDK wraps ``POST /api/sdk/episodes`` with HMAC signing and
returns a typed ``Result`` discriminating Ok[episode_id] vs Err. The
``SignalLayerClient`` is patched so no real HTTP traffic is generated.
"""
from __future__ import annotations

import os
import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# Ensure sdk/signallayer is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "sdk"))

import signallayer
from signallayer.client import Err, Ok
from signallayer.errors import AuthError


def test_public_surface_exports_result_types() -> None:
    """`from signallayer import Err, Ok, write_episode` must succeed.

    Regression guard for the S71 smoke bug where agent.py raised
    ImportError on this exact import because Err/Ok were only exposed via
    signallayer.client, not the package top level.
    """
    import importlib
    mod = importlib.reload(signallayer)
    assert hasattr(mod, "write_episode")
    assert hasattr(mod, "Err")
    assert hasattr(mod, "Ok")
    assert "Err" in mod.__all__
    assert "Ok" in mod.__all__
    assert "write_episode" in mod.__all__


@pytest.fixture(autouse=True)
def _init_sdk() -> None:
    """Re-initialise the SDK with stable creds before each test."""
    signallayer.init(
        api_key="kid:secret",
        base_url="http://fake.local",
        key_id="kid",
    )


def test_write_episode_happy_path_returns_ok_with_id() -> None:
    """A 201 with ``{"episode_id": "..."}`` becomes Ok[str]."""
    fake_client = MagicMock()
    fake_client.post.return_value = Ok(value={"episode_id": "ep-abc"}, status_code=201)

    with patch.object(signallayer, "get_client", return_value=fake_client):
        result = signallayer.write_episode(
            workload_id="azure-architect",
            prompt="scrubbed prompt",
            response="scrubbed response",
            outcome="success",
            metadata={"vault_id": "v-1", "trace_id": "t-1"},
        )

    assert isinstance(result, Ok)
    assert result.value == "ep-abc"
    assert result.status_code == 201

    # Confirm the SDK posted to the right path with a full body.
    fake_client.post.assert_called_once()
    args, kwargs = fake_client.post.call_args
    assert args[0] == "/api/sdk/episodes"
    body = kwargs["json_body"]
    assert body["workload_id"] == "azure-architect"
    assert body["outcome"] == "success"
    assert body["metadata"]["vault_id"] == "v-1"
    # ttl_seconds omitted when None — engine decides default
    assert "ttl_seconds" not in body


def test_write_episode_includes_ttl_when_provided() -> None:
    """ttl_seconds is forwarded to the engine when caller specifies it."""
    fake_client = MagicMock()
    fake_client.post.return_value = Ok(value={"episode_id": "ep-1"}, status_code=201)

    with patch.object(signallayer, "get_client", return_value=fake_client):
        signallayer.write_episode(
            workload_id="w",
            prompt="p",
            response="r",
            outcome="success",
            ttl_seconds=3600,
        )

    body = fake_client.post.call_args.kwargs["json_body"]
    assert body["ttl_seconds"] == 3600


def test_write_episode_auth_err_propagates() -> None:
    """Err from the underlying client (e.g. 401) passes through unchanged."""
    err = Err(error=AuthError("auth failed"), status_code=401, message="auth failed")
    fake_client = MagicMock()
    fake_client.post.return_value = err

    with patch.object(signallayer, "get_client", return_value=fake_client):
        result = signallayer.write_episode(
            workload_id="w",
            prompt="p",
            response="r",
            outcome="success",
        )

    assert isinstance(result, Err)
    assert result.status_code == 401


def test_write_episode_missing_episode_id_returns_empty_string() -> None:
    """If the engine returned 200 but no episode_id, surface Ok with ``""``."""
    fake_client = MagicMock()
    fake_client.post.return_value = Ok(value={"unexpected": True}, status_code=200)

    with patch.object(signallayer, "get_client", return_value=fake_client):
        result = signallayer.write_episode(
            workload_id="w",
            prompt="p",
            response="r",
            outcome="success",
        )

    assert isinstance(result, Ok)
    assert result.value == ""
