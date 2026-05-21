"""De-identification vault with Fernet encryption and TTL enforcement.

Backs up PII token mappings to encrypted JSONL storage. Keys are derived from
Azure Key Vault (if available) or SESSION_SECRET (HKDF). All mappings are
encrypted before disk write. Lookups enforce TTL expiry.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Vault storage file
_DATA_DIR = Path(__file__).resolve().parents[1] / "data"
_DATA_DIR.mkdir(exist_ok=True)
VAULT_FILE = _DATA_DIR / "deid_vault.jsonl"

# Encryption state
_fernet_cipher = None


def _derive_fernet_key() -> bytes:
    """
    Derive Fernet encryption key from Azure Key Vault or SESSION_SECRET.

    If AZURE_KEYVAULT_URI is set, fetch DEID_VAULT_KEY from Key Vault (read-only).
    Otherwise, derive from SESSION_SECRET via HKDF-SHA256 (dev/MVP).

    Returns:
        32-byte key suitable for Fernet
    """
    try:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF
        from cryptography.hazmat.backends import default_backend
        import base64

        # Try Azure Key Vault first (read-only path)
        kv_uri = os.getenv("AZURE_KEYVAULT_URI")
        if kv_uri:
            try:
                from azure.identity import DefaultAzureCredential
                from azure.keyvault.secrets import SecretClient

                credential = DefaultAzureCredential()
                client = SecretClient(vault_url=kv_uri, credential=credential)
                secret = client.get_secret("DEID-VAULT-KEY")
                key_b64 = secret.value
                key_bytes = base64.urlsafe_b64decode(key_b64)
                if len(key_bytes) == 32:
                    logger.info("Loaded DEID_VAULT_KEY from Azure Key Vault")
                    return key_bytes
            except Exception as e:
                logger.warning(f"Failed to load DEID_VAULT_KEY from Key Vault: {e}; falling back to SESSION_SECRET")

        # Fallback: derive from SESSION_SECRET
        session_secret = os.getenv("SESSION_SECRET", "dev-default-secret")
        if session_secret == "dev-default-secret":
            logger.warning("SESSION_SECRET not set; using dev default (insecure)")

        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b"deid_vault",
            info=b"fernet_key",
            backend=default_backend(),
        )
        key = hkdf.derive(session_secret.encode())
        return base64.urlsafe_b64encode(key)

    except Exception as e:
        logger.error(f"Key derivation failed: {e}")
        raise


def _get_cipher():
    """Get or create Fernet cipher. Lazy-loads on first use."""
    global _fernet_cipher
    if _fernet_cipher is not None:
        return _fernet_cipher

    try:
        from cryptography.fernet import Fernet

        key = _derive_fernet_key()
        _fernet_cipher = Fernet(key)
        return _fernet_cipher
    except Exception as e:
        logger.error(f"Failed to initialize Fernet cipher: {e}")
        raise


def store(vault_id: str, mapping: dict[str, str], ttl_seconds: Optional[int] = None) -> None:
    """
    Store an encrypted token mapping in the vault.

    Args:
        vault_id: Unique identifier for this mapping (e.g., scope_hash)
        mapping: Dict of token -> original text (e.g., {"PERSON_001": "John Smith"})
        ttl_seconds: Seconds until expiry. Defaults to DEID_VAULT_TTL_SECONDS env var
    """
    if not mapping:
        return

    try:
        import storage

        # Get TTL from env or use 1 hour default
        if ttl_seconds is None:
            ttl_seconds = int(os.getenv("DEID_VAULT_TTL_SECONDS", "3600"))

        now = datetime.now(timezone.utc)
        expires_at = (now + timedelta(seconds=ttl_seconds)).isoformat()

        # Encrypt the mapping
        cipher = _get_cipher()
        plaintext = json.dumps(mapping)
        ciphertext = cipher.encrypt(plaintext.encode()).decode()

        # Append to JSONL
        record = {
            "vault_id": vault_id,
            "ciphertext": ciphertext,
            "created_at": now.isoformat(),
            "expires_at": expires_at,
            "ttl_seconds": ttl_seconds,
        }
        storage._append_jsonl(VAULT_FILE, record)

        logger.debug(f"Stored vault entry {vault_id} with TTL {ttl_seconds}s")

    except Exception as e:
        logger.error(f"Vault store failed: {e}", exc_info=True)
        raise


def lookup(vault_id: str) -> Optional[dict[str, str]]:
    """
    Retrieve and decrypt a token mapping from the vault.

    Returns None if the entry is not found or has expired.

    Args:
        vault_id: Lookup key

    Returns:
        Token mapping dict, or None on miss/expiry
    """
    if not vault_id:
        return None

    try:
        import storage

        if not VAULT_FILE.exists():
            return None

        cipher = _get_cipher()
        now = datetime.now(timezone.utc)

        # Scan JSONL for matching entry (O(n), acceptable for v1)
        records = storage._read_jsonl(VAULT_FILE)
        for record in records:
            if record.get("vault_id") == vault_id:
                # Check expiry
                expires_at_str = record.get("expires_at")
                if expires_at_str:
                    expires_at = datetime.fromisoformat(expires_at_str)
                    if now > expires_at:
                        logger.debug(f"Vault entry {vault_id} has expired")
                        return None

                # Decrypt
                ciphertext = record.get("ciphertext")
                if ciphertext:
                    plaintext = cipher.decrypt(ciphertext.encode()).decode()
                    mapping = json.loads(plaintext)
                    logger.debug(f"Retrieved vault entry {vault_id}")
                    return mapping

        logger.debug(f"Vault entry {vault_id} not found")
        return None

    except Exception as e:
        logger.error(f"Vault lookup failed: {e}", exc_info=True)
        return None


def vault_stats() -> dict:
    """
    Return vault statistics: total entries, active (non-expired), expired, oldest, newest.

    Returns:
        Dict with keys: total, active, expired, oldest, newest (timestamp)
    """
    try:
        import storage

        if not VAULT_FILE.exists():
            return {
                "total": 0,
                "active": 0,
                "expired": 0,
                "oldest": None,
                "newest": None,
            }

        records = storage._read_jsonl(VAULT_FILE)
        now = datetime.now(timezone.utc)
        active = 0
        expired = 0
        timestamps = []

        for record in records:
            expires_at_str = record.get("expires_at")
            created_at_str = record.get("created_at")

            if created_at_str:
                timestamps.append(created_at_str)

            if expires_at_str:
                expires_at = datetime.fromisoformat(expires_at_str)
                if now > expires_at:
                    expired += 1
                else:
                    active += 1
            else:
                active += 1

        timestamps.sort()

        return {
            "total": len(records),
            "active": active,
            "expired": expired,
            "oldest": timestamps[0] if timestamps else None,
            "newest": timestamps[-1] if timestamps else None,
        }

    except Exception as e:
        logger.error(f"vault_stats failed: {e}", exc_info=True)
        return {
            "total": 0,
            "active": 0,
            "expired": 0,
            "oldest": None,
            "newest": None,
        }


if __name__ == "__main__":
    # Smoke test
    print("Testing deid_vault...")

    # Store
    test_mapping = {"PERSON_001": "John Smith", "EMAIL_002": "john@example.com"}
    vault_id = "smoke-test-001"
    store(vault_id, test_mapping, ttl_seconds=60)
    print(f"✓ Stored {len(test_mapping)} entries")

    # Lookup
    retrieved = lookup(vault_id)
    assert retrieved == test_mapping, "Lookup mismatch!"
    print(f"✓ Retrieved {len(retrieved)} entries")

    # Stats
    stats = vault_stats()
    assert stats["total"] > 0, "Stats missing entries!"
    print(f"✓ Stats: {stats}")

    # Expiry test
    store("ttl-test", {"A": "B"}, ttl_seconds=1)
    import time
    time.sleep(2)
    expired = lookup("ttl-test")
    assert expired is None, "Expiry check failed!"
    print("✓ TTL enforcement working")

    print("✓ All smoke tests passed")
