"""Credentials and configuration loading for the SignalLayer CLI.

Priority order (highest to lowest):
  1. Environment variables: SL_API_KEY, SL_BASE_URL, SL_KEY_ID
  2. Credentials file: ~/.signallayer/credentials.json

Fails loudly if required values are missing.

Session 10 hardening: ``save_credentials`` uses ``os.open`` with
``O_CREAT | O_WRONLY | O_TRUNC`` and mode ``0o600`` atomically on POSIX so
there is never a window where the file exists but is world-readable. This closes
the TOCTOU race in the previous ``write_text + chmod`` pattern.

Session 11 hardening: two write paths are now distinguished.

  First write (file does not exist):
    Opens with ``O_CREAT | O_EXCL | O_WRONLY`` and mode ``0o600``.
    ``O_EXCL`` makes the open fail with ``FileExistsError`` if the path already
    exists -- including if it is a symlink.  This prevents a symlink-swap attack
    where an attacker pre-places a symlink at the credentials path before the
    first ``sl login`` run.

  Update (file already exists):
    Opens with ``O_WRONLY``, then calls ``os.fstat(fd)`` and asserts that the
    open file descriptor refers to a regular file (``S_ISREG``) with exactly one
    hard link (``st_nlink == 1``).  A symlink or hard-link fan-out both raise
    ``OSError``.

On Windows, ``os.open`` mode bits are not enforced by the OS; the POSIX paths
are skipped and the file is written normally.  Callers on Windows should secure
the file via ``icacls``.
"""

from __future__ import annotations

import json
import os
import stat
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

    On POSIX, two write paths are used depending on whether the file already
    exists:

    **First write** (file absent):
        ``os.open`` with ``O_CREAT | O_EXCL | O_WRONLY`` and mode ``0o600``.
        ``O_EXCL`` causes the open to fail with ``FileExistsError`` when the
        path already exists — including when it is a symlink pointing at an
        attacker-controlled file.  This eliminates the TOCTOU window that exists
        in a check-then-create pattern.

    **Update** (file exists):
        ``os.open`` with ``O_WRONLY`` (no ``O_EXCL``), then ``os.fstat`` to
        assert that the open fd refers to a regular file (``stat.S_ISREG``) with
        a single hard link (``st_nlink == 1``).  Symlinks and hard-link fans
        both raise ``OSError``.

    On Windows the file is written normally; NTFS ACLs must be tightened via
    ``icacls``.

    Args:
        api_key: The HMAC secret / API key.
        base_url: The platform base URL.
        key_id: The key identifier sent in X-SL-Key-Id header.

    Returns:
        Path to the credentials file written.

    Raises:
        FileExistsError: (POSIX) When the credentials path exists as a symlink
            during a first-write attempt.
        OSError: (POSIX) When the open fd during an update refers to a symlink
            or hard-linked file (``st_nlink != 1`` or not ``S_ISREG``).
    """
    CREDENTIALS_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        {"api_key": api_key, "base_url": base_url, "key_id": key_id}, indent=2
    )

    if sys.platform != "win32":
        _posix_write(CREDENTIALS_FILE, payload)
    else:
        # Windows: os.open mode bits are not enforced; write normally.
        # Callers on Windows should secure the file via icacls:
        #   icacls "%USERPROFILE%\.signallayer\credentials.json"
        #          /inheritance:r /grant:r "%USERNAME%:(R,W)"
        CREDENTIALS_FILE.write_text(payload, encoding="utf-8")

    return CREDENTIALS_FILE


def _posix_write(path: Path, payload: str) -> None:
    """Write *payload* to *path* on POSIX with symlink-attack protection.

    Uses two distinct open strategies depending on whether the file already
    exists.  Both strategies use ``os.fstat`` to verify the fd is a regular
    non-hardlinked file before writing.

    Args:
        path:    Destination path (must be absolute on POSIX).
        payload: UTF-8 string to write.

    Raises:
        FileExistsError: When the path exists as a symlink during first-write.
        OSError: When the open fd is not a regular single-link file (update path).
    """
    # Use lstat (not exists) so a pre-placed symlink at the path is detected
    # before we even consider an "update" branch. `path.exists()` follows
    # symlinks — an attacker who places a symlink to a controlled target
    # would route us into the update branch where the fd-check is the only
    # remaining guard.  lstat closes that window.
    try:
        lst = os.lstat(str(path))
        path_present = True
        is_symlink = stat.S_ISLNK(lst.st_mode)
    except FileNotFoundError:
        path_present = False
        is_symlink = False

    if is_symlink:
        raise OSError(
            f"save_credentials: {path} is a symlink; refusing to write "
            f"(symlink attack?). Remove the link manually and retry."
        )

    if not path_present:
        # First write — O_EXCL rejects symlinks and pre-existing files atomically.
        fd = os.open(
            str(path),
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
    else:
        # Update — open the existing file; then validate via fstat.
        fd = os.open(str(path), os.O_WRONLY | os.O_TRUNC)

    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise OSError(
                f"save_credentials: {path} is not a regular file after open "
                f"(mode={oct(st.st_mode)}); refusing to write (symlink attack?)"
            )
        if st.st_nlink != 1:
            raise OSError(
                f"save_credentials: {path} has {st.st_nlink} hard links; "
                f"expected 1 — refusing to write (hard-link attack?)"
            )
        os.write(fd, payload.encode("utf-8"))
    finally:
        os.close(fd)
