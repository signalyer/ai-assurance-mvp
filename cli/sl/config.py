"""Credentials and configuration loading for the SignalLayer CLI.

Priority order (highest to lowest):
  1. Environment variables: SL_API_KEY, SL_BASE_URL, SL_KEY_ID
  2. Credentials file: ~/.signallayer/credentials.json

Fails loudly if required values are missing.
"""

from __future__ import annotations

import json
import os
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

    Args:
        api_key: The HMAC secret / API key.
        base_url: The platform base URL.
        key_id: The key identifier sent in X-SL-Key-Id header.

    Returns:
        Path to the credentials file written.
    """
    CREDENTIALS_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {"api_key": api_key, "base_url": base_url, "key_id": key_id}
    CREDENTIALS_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # Restrict permissions — POSIX only; Windows falls back to NTFS ACL note.
    try:
        os.chmod(CREDENTIALS_FILE, 0o600)
    except (AttributeError, NotImplementedError, OSError):
        # On Windows, chmod is a no-op for most permission bits.
        # Callers on Windows should secure the file via icacls manually:
        #   icacls "%USERPROFILE%\.signallayer\credentials.json" /inheritance:r
        #         /grant:r "%USERNAME%:(R,W)"
        pass

    return CREDENTIALS_FILE
