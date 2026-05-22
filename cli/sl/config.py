"""Credentials and configuration loading for the SignalLayer CLI.

Priority order (highest to lowest):
  1. Environment variables: SL_API_KEY, SL_BASE_URL, SL_KEY_ID
  2. Credentials file: ~/.signallayer/credentials.json

Fails loudly if required values are missing.

Session 10 hardening: ``save_credentials`` uses ``os.open`` with
``O_CREAT | O_WRONLY | O_TRUNC`` and mode ``0o600`` atomically on POSIX so
there is never a window where the file exists but is world-readable. This closes
the TOCTOU race in the previous ``write_text + chmod`` pattern.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import TypedDict


CREDENTIALS_FILE = Path.home() / ".signallayer" / "credentials.json"

DEFAULT_BASE_URL = "https://aigovern.sandboxhub.co"


class Credentials(TypedDict):
    """All credential fields the CLI needs."""

    api_key: str
    base_url: str
    key_id: str


def credentials_path() -> Path:
    """Return the path to the credentials file."""
    return CREDENTIALS_FILE


def load_credentials() -> Credentials:
    """Load credentials from env vars or credentials file.

    Raises:
        SystemExit: If required credentials (api_key) are missing.
    """
    api_key = os.environ.get("SL_API_KEY", "")
    base_url = os.environ.get("SL_BASE_URL", "")
    key_id = os.environ.get("SL_KEY_ID", "")

    if not api_key and CREDENTIALS_FILE.exists():
        try:
            raw = json.loads(CREDENTIALS_FILE.read_text(encoding="utf-8"))
            api_key = api_key or raw.get("api_key", "")
            base_url = base_url or raw.get("base_url", "")
            key_id = key_id or raw.get("key_id", "")
        except (json.JSONDecodeError, OSError):
            pass

    if not api_key:
        raise SystemExit(
            "Missing required credential: api_key.\n"
            "Run `sl login --api-key <key>` or set SL_API_KEY environment variable."
        )

    base_url = base_url or DEFAULT_BASE_URL
    key_id = key_id or "cli-key"

    return Credentials(api_key=api_key, base_url=base_url, key_id=key_id)


def save_credentials(api_key: str, base_url: str, key_id: str) -> Path:
    """Persist credentials to ~/.signallayer/credentials.json with mode 0600.

    On POSIX the file is created atomically with mode 0600 via ``os.open`` with
    ``O_CREAT | O_WRONLY | O_TRUNC``. This closes the TOCTOU window that existed
    in the previous ``write_text + chmod`` approach where the file was temporarily
    world-readable between creation and permission tightening.

    On Windows the file is written normally; NTFS ACLs must be tightened manually:
        icacls "%USERPROFILE%\\.signallayer\\credentials.json"
            /inheritance:r /grant:r "%USERNAME%:(R,W)"

    Args:
        api_key: The HMAC secret / API key.
        base_url: The platform base URL.
        key_id: The key identifier sent in X-SL-Key-Id header.

    Returns:
        Path to the credentials file written.
    """
    CREDENTIALS_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"api_key": api_key, "base_url": base_url, "key_id": key_id}, indent=2)

    if sys.platform != "win32":
        # POSIX: open with mode 0o600 atomically -- no world-readable window.
        fd = os.open(
            str(CREDENTIALS_FILE),
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            0o600,
        )
        try:
            os.write(fd, payload.encode("utf-8"))
        finally:
            os.close(fd)
    else:
        # Windows: os.open mode bits are not enforced; write normally.
        # Callers on Windows should secure the file via icacls:
        #   icacls "%USERPROFILE%\.signallayer\credentials.json"
        #          /inheritance:r /grant:r "%USERNAME%:(R,W)"
        CREDENTIALS_FILE.write_text(payload, encoding="utf-8")

    return CREDENTIALS_FILE
