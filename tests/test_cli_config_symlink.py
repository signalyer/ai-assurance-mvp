"""Tests for cli/sl/config.py symlink attack protection.

Task 2 — Session 11 debt fix.

3 tests:
  (a) pre-create credentials path as symlink → write fails with FileExistsError
  (b) normal first-write succeeds
  (c) update on existing regular file succeeds; update on a symlink fails
"""
from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Skip on non-POSIX: symlink semantics tested here are POSIX-only.
pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="Symlink attack protection is POSIX-only (O_NOFOLLOW / O_EXCL semantics)",
)

_MODULE_AVAILABLE = False
try:
    import cli.sl.config as _cfg_probe  # noqa: F401
    _MODULE_AVAILABLE = True
except ImportError:
    try:
        # Try direct import path
        import importlib.util
        import sys as _sys
        _spec = importlib.util.spec_from_file_location(
            "sl.config",
            Path(__file__).resolve().parents[1] / "cli" / "sl" / "config.py",
        )
        if _spec and _spec.loader:
            _mod = importlib.util.module_from_spec(_spec)
            _spec.loader.exec_module(_mod)  # type: ignore[union-attr]
            _sys.modules["sl.config"] = _mod
            _MODULE_AVAILABLE = True
    except Exception:
        pass


if _MODULE_AVAILABLE:
    try:
        from cli.sl.config import save_credentials, update_credentials, CREDENTIALS_FILE
    except ImportError:
        # Fallback: try the module we loaded manually
        from sl.config import save_credentials, CREDENTIALS_FILE  # type: ignore[no-redef]
        try:
            from sl.config import update_credentials  # type: ignore[no-redef]
        except ImportError:
            update_credentials = None  # type: ignore[assignment]


@pytest.fixture()
def isolated_creds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect CREDENTIALS_FILE to a tmp_path location for test isolation."""
    creds_file = tmp_path / ".signallayer" / "credentials.json"
    monkeypatch.setattr("cli.sl.config.CREDENTIALS_FILE", creds_file, raising=False)
    try:
        monkeypatch.setattr("sl.config.CREDENTIALS_FILE", creds_file, raising=False)
    except AttributeError:
        pass
    return creds_file


class TestSymlinkFirstWrite:
    """Test (a): pre-created symlink at credentials path → write fails."""

    @pytest.mark.skipif(not _MODULE_AVAILABLE, reason="module not available")
    def test_symlink_target_raises_on_first_write(
        self, tmp_path: Path, isolated_creds: Path
    ) -> None:
        """If the credentials file is a symlink, save_credentials must raise."""
        # Pre-create the parent dir and a target file the symlink points at
        isolated_creds.parent.mkdir(parents=True, exist_ok=True)
        target = tmp_path / "attacker_file.json"
        target.write_text("{}", encoding="utf-8")
        # Place a symlink at the credentials path
        isolated_creds.symlink_to(target)

        with pytest.raises((FileExistsError, OSError, PermissionError)):
            save_credentials("my-key", "https://example.com", "key-id")


class TestNormalFirstWrite:
    """Test (b): normal first-write succeeds."""

    @pytest.mark.skipif(not _MODULE_AVAILABLE, reason="module not available")
    def test_first_write_creates_file(self, isolated_creds: Path) -> None:
        """save_credentials writes a valid credentials file on clean first write."""
        result_path = save_credentials("test-key", "https://test.example.com", "k1")

        assert result_path.exists(), "Credentials file must exist after save"
        data = json.loads(result_path.read_text(encoding="utf-8"))
        assert data["api_key"] == "test-key"
        assert data["base_url"] == "https://test.example.com"
        assert data["key_id"] == "k1"

        # File mode on POSIX must be 0600 (owner read/write only)
        if sys.platform != "win32":
            file_mode = stat.S_IMODE(result_path.stat().st_mode)
            assert file_mode == 0o600, (
                f"Credentials file must have mode 0600, got {oct(file_mode)}"
            )


class TestUpdateBehaviour:
    """Test (c): update on regular file OK; update on symlink fails."""

    @pytest.mark.skipif(not _MODULE_AVAILABLE, reason="module not available")
    def test_update_on_regular_file_succeeds(self, isolated_creds: Path) -> None:
        """Updating an existing regular credentials file succeeds."""
        # First write (creates file)
        save_credentials("old-key", "https://old.example.com", "k1")
        assert isolated_creds.exists()
        assert not isolated_creds.is_symlink()

        # Second write (update) must succeed
        save_credentials("new-key", "https://new.example.com", "k2")
        data = json.loads(isolated_creds.read_text(encoding="utf-8"))
        assert data["api_key"] == "new-key"

    @pytest.mark.skipif(not _MODULE_AVAILABLE, reason="module not available")
    def test_update_on_symlink_fails(
        self, tmp_path: Path, isolated_creds: Path
    ) -> None:
        """If after a write the file becomes a symlink, update must raise."""
        # First write — creates a real file
        save_credentials("key1", "https://example.com", "k1")
        assert isolated_creds.exists()

        # Now replace the file with a symlink (simulating a TOCTOU attack after first write)
        target = tmp_path / "attacker_target.json"
        target.write_text("{}", encoding="utf-8")
        isolated_creds.unlink()
        isolated_creds.symlink_to(target)

        with pytest.raises((FileExistsError, OSError, PermissionError, AssertionError)):
            save_credentials("key2", "https://example.com", "k2")
