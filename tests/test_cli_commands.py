"""Tests for CLI commands via Typer's CliRunner.

Tests covered:
  - login: writes credentials file; file mode is 0600 on POSIX (skipped on Windows)
  - onboard: calls correct endpoint, exits 0 on success
  - gate check: exits 0 on APPROVED, exits 1 on BLOCKED, exits 1 on 404
  - evidence export: writes a valid ZIP containing manifest.json
"""

from __future__ import annotations

import json
import os
import platform
import stat
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

# ---------------------------------------------------------------------------
# Runner + helpers
# ---------------------------------------------------------------------------

runner = CliRunner()


def _make_mock_response(
    status_code: int,
    body: dict | bytes,
) -> MagicMock:
    """Build a mock httpx Response."""
    mock = MagicMock()
    mock.status_code = status_code
    if isinstance(body, dict):
        mock.json.return_value = body
        mock.text = json.dumps(body)
    else:
        mock.json.side_effect = json.JSONDecodeError("no json", "", 0)
        mock.text = body.decode("utf-8", errors="replace")
    return mock


def _make_creds_file(tmp_dir: str) -> Path:
    """Write a credentials.json under tmp_dir and return its Path."""
    creds_file = Path(tmp_dir) / ".signallayer" / "credentials.json"
    creds_file.parent.mkdir(parents=True, exist_ok=True)
    creds_file.write_text(json.dumps({
        "api_key": "test-key",
        "base_url": "http://localhost:8000",
        "key_id": "cli-dev",
    }))
    return creds_file


# ---------------------------------------------------------------------------
# sl login
# ---------------------------------------------------------------------------

class TestLogin:
    """Tests for `sl login`."""

    def test_login_writes_credentials_file(self) -> None:
        """login writes credentials.json with correct content."""
        from cli.sl.main import app
        from cli.sl import config as cfg_mod

        with tempfile.TemporaryDirectory() as tmp_dir:
            creds_file = Path(tmp_dir) / ".signallayer" / "credentials.json"

            with patch.object(cfg_mod, "CREDENTIALS_FILE", creds_file):
                result = runner.invoke(
                    app,
                    ["login", "--api-key", "test-key-abc",
                     "--base-url", "http://localhost:8000",
                     "--key-id", "mykey"],
                )

            assert result.exit_code == 0, result.output
            assert creds_file.exists(), "credentials.json was not created"

            data = json.loads(creds_file.read_text())
            assert data["api_key"] == "test-key-abc"
            assert data["base_url"] == "http://localhost:8000"
            assert data["key_id"] == "mykey"

    @pytest.mark.skipif(
        platform.system() == "Windows",
        reason="chmod 0600 is not enforced on Windows NTFS — mode check skipped.",
    )
    def test_login_sets_file_mode_0600(self) -> None:
        """On POSIX, credentials.json must have mode 0600 (owner rw only)."""
        from cli.sl.main import app
        from cli.sl import config as cfg_mod

        with tempfile.TemporaryDirectory() as tmp_dir:
            creds_file = Path(tmp_dir) / ".signallayer" / "credentials.json"

            with patch.object(cfg_mod, "CREDENTIALS_FILE", creds_file):
                runner.invoke(app, ["login", "--api-key", "testkey"])

            file_mode = stat.S_IMODE(creds_file.stat().st_mode)
            assert file_mode == 0o600, f"Expected 0600 got {oct(file_mode)}"


# ---------------------------------------------------------------------------
# sl onboard
# ---------------------------------------------------------------------------

class TestOnboard:
    """Tests for `sl onboard`."""

    def test_onboard_calls_intake_endpoint_and_exits_0(self) -> None:
        """onboard POSTs to /api/grc/intake/submit and exits 0 on success."""
        from cli.sl.main import app
        from cli.sl import config as cfg_mod

        mock_resp = _make_mock_response(200, {
            "ai_system_id": "ai-sys-abc123",
            "assessment_id": "assess-001",
            "gate_count": 3,
            "inherent_risk": "HIGH",
            "rules_fired": ["pii", "tools"],
            "redirect_to": "/ai-systems?id=ai-sys-abc123",
        })

        with tempfile.TemporaryDirectory() as tmp_dir:
            creds_file = _make_creds_file(tmp_dir)
            with patch.object(cfg_mod, "CREDENTIALS_FILE", creds_file):
                with patch("httpx.post", return_value=mock_resp) as mock_post:
                    result = runner.invoke(
                        app,
                        ["onboard", "Test Agent", "--no-browser"],
                    )

        assert result.exit_code == 0, result.output
        assert "ai-sys-abc123" in result.output

        # Verify POST was called to the correct endpoint
        call_args = mock_post.call_args
        assert "/api/grc/intake/submit" in call_args[0][0]

    def test_onboard_exits_1_on_server_error(self) -> None:
        """onboard exits 1 when the server returns a non-2xx response."""
        from cli.sl.main import app
        from cli.sl import config as cfg_mod

        mock_resp = _make_mock_response(500, b"internal server error")

        with tempfile.TemporaryDirectory() as tmp_dir:
            creds_file = _make_creds_file(tmp_dir)
            with patch.object(cfg_mod, "CREDENTIALS_FILE", creds_file):
                with patch("httpx.post", return_value=mock_resp):
                    result = runner.invoke(app, ["onboard", "Broken", "--no-browser"])

        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# sl gate check
# ---------------------------------------------------------------------------

class TestGateCheck:
    """Tests for `sl gate check`."""

    def _invoke_gate(
        self, mock_response: MagicMock, system_id: str = "sys-001"
    ):
        from cli.sl.main import app
        from cli.sl import config as cfg_mod

        with tempfile.TemporaryDirectory() as tmp_dir:
            creds_file = _make_creds_file(tmp_dir)
            with patch.object(cfg_mod, "CREDENTIALS_FILE", creds_file):
                with patch("httpx.get", return_value=mock_response):
                    return runner.invoke(app, ["gate", "check", system_id])

    def test_gate_pass_exits_0(self) -> None:
        """APPROVED decision -> exit code 0."""
        resp = _make_mock_response(200, {
            "release_decision": "APPROVED",
            "release_rationale": "All gates passed.",
        })
        result = self._invoke_gate(resp)
        assert result.exit_code == 0

    def test_gate_fail_exits_1(self) -> None:
        """BLOCKED decision -> exit code 1."""
        resp = _make_mock_response(200, {
            "release_decision": "BLOCKED",
            "release_rationale": "Gate failed: hallucination score too low.",
        })
        result = self._invoke_gate(resp)
        assert result.exit_code == 1

    def test_gate_404_exits_1(self) -> None:
        """System not found (404) -> exit code 1."""
        resp = _make_mock_response(404, b"not found")
        result = self._invoke_gate(resp, system_id="nonexistent")
        assert result.exit_code == 1

    def test_gate_conditional_exits_0(self) -> None:
        """CONDITIONAL decision is treated as a pass -> exit code 0."""
        resp = _make_mock_response(200, {
            "release_decision": "CONDITIONAL",
            "release_rationale": "Approved with conditions.",
        })
        result = self._invoke_gate(resp)
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# sl evidence export
# ---------------------------------------------------------------------------

class TestEvidenceExport:
    """Tests for `sl evidence export`."""

    def test_evidence_export_writes_valid_zip(self) -> None:
        """evidence export writes a valid ZIP file containing manifest.json."""
        from cli.sl.main import app
        from cli.sl import config as cfg_mod

        mock_resp = _make_mock_response(200, {
            "system_id": "sys-001",
            "framework": "eu_ai_act",
            "items": [{"id": "e-001", "type": "test_result"}],
        })

        with tempfile.TemporaryDirectory() as tmp_dir:
            creds_file = _make_creds_file(tmp_dir)
            out_zip = Path(tmp_dir) / "evidence.zip"

            with patch.object(cfg_mod, "CREDENTIALS_FILE", creds_file):
                with patch("httpx.get", return_value=mock_resp):
                    result = runner.invoke(
                        app,
                        [
                            "evidence", "export", "sys-001",
                            "--framework", "eu_ai_act",
                            "--out", str(out_zip),
                        ],
                    )

            assert result.exit_code == 0, result.output
            assert out_zip.exists(), "ZIP file was not created"

            with zipfile.ZipFile(out_zip, "r") as zf:
                names = zf.namelist()
                assert "manifest.json" in names, f"manifest.json missing from {names}"
                manifest = json.loads(zf.read("manifest.json"))
                assert manifest["system_id"] == "sys-001"
                assert manifest["framework"] == "eu_ai_act"
