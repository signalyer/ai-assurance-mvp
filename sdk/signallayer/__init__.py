"""SignalLayer Python SDK — public surface.

Quick start::

    import signallayer

    signallayer.init(api_key="key_id:secret", base_url="https://aigovern.sandboxhub.co")

    @signallayer.policy_gate(action="llm_call")
    @signallayer.scrub_pii(scope="billing")
    @signallayer.guardrails()
    async def call_llm(prompt: str, workload_id: str = "billing") -> str:
        ...

    signallayer.guard(call_llm)   # raises DecoratorOrderError if chain is wrong

Decorator chain (outermost → innermost, NEVER change this order):

    @policy_gate → @scrub_pii → @guardrails → @trace → @evaluate
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

__version__: str = "0.1.0"

# ---------------------------------------------------------------------------
# Module-level config — populated by init()
# ---------------------------------------------------------------------------

_config: dict[str, Any] = {
    "api_key": None,
    "base_url": None,
    "tenant": None,
    "key_id": None,
}


def init(
    api_key: str | None = None,
    base_url: str | None = None,
    tenant: str | None = None,
    key_id: str | None = None,
) -> None:
    """Initialise the SDK with platform credentials.

    Must be called once before using the HTTP client features of the SDK.
    Decorator re-exports (``policy_gate``, ``scrub_pii``, etc.) work without
    calling ``init()`` — they delegate directly to the platform middleware.

    Environment variable fallbacks (applied when the corresponding argument is
    ``None``):
        - ``SL_API_KEY``      → ``api_key``
        - ``SL_API_BASE_URL`` → ``base_url``
        - ``SL_TENANT``       → ``tenant``

    NEVER logs or prints the api_key value.

    Args:
        api_key: API key in the format ``key_id:secret``.  Falls back to
            the ``SL_API_KEY`` environment variable.
        base_url: Platform base URL (e.g. ``"https://aigovern.sandboxhub.co"``).
            Falls back to ``SL_API_BASE_URL``.
        tenant: Optional tenant identifier sent as ``X-SL-Tenant`` header.
            Falls back to ``SL_TENANT``.
        key_id: Optional explicit key_id (S53 per-system ``slk_*`` form).
            When supplied, overrides the key_id parsed from ``api_key``
            and is sent as ``X-SL-Key-Id`` on every request. Falls back to
            ``SL_KEY_ID``. Backward-compatible: ``None`` => legacy
            ``api_key`` parsing path.

    Raises:
        ValueError: If ``api_key`` or ``base_url`` cannot be resolved from
            arguments or environment variables.
    """
    resolved_key = api_key or os.getenv("SL_API_KEY")
    resolved_url = base_url or os.getenv("SL_API_BASE_URL")
    resolved_tenant = tenant or os.getenv("SL_TENANT")
    resolved_key_id = key_id or os.getenv("SL_KEY_ID")

    if not resolved_key:
        raise ValueError(
            "Missing required: api_key (or set SL_API_KEY environment variable)"
        )
    if not resolved_url:
        raise ValueError(
            "Missing required: base_url (or set SL_API_BASE_URL environment variable)"
        )

    _config["api_key"] = resolved_key
    _config["base_url"] = resolved_url
    _config["tenant"] = resolved_tenant
    _config["key_id"] = resolved_key_id

    logger.info(
        "signallayer.init: SDK configured — base_url=%s tenant=%s version=%s",
        resolved_url,
        resolved_tenant,
        __version__,
    )


def write_episode(
    workload_id: str,
    prompt: str,
    response: str,
    outcome: str,
    metadata: dict[str, Any] | None = None,
    ttl_seconds: int | None = None,
) -> "Result":  # noqa: F821
    """Persist one Tier-2 episode via the SignalLayer engine.

    Posts to ``/api/sdk/episodes`` with HMAC signing. The engine's configured
    memory backend (postgres in prod, jsonl in dev) decides where the row
    lands; the SDK only knows about the HTTP contract.

    Replaces the S70b pattern of importing ``domain.agent_memory`` directly
    from customer agent code. Customer agents no longer need sqlalchemy +
    psycopg2 + a Postgres connection string just to record an episode.

    Args:
        workload_id: AI workload identifier (e.g. ``"azure-architect"``).
        prompt:      Pre-scrubbed prompt text (the @scrub_pii decorator on the
                     calling function should already have replaced PII).
        response:    Pre-scrubbed response text.
        outcome:     One of ``"success"``, ``"failure"``, ``"review"``.
        metadata:    Optional dict. May include ``vault_id``, ``trace_id``,
                     ``eval_scores``, ``guardrail_result``. ``vault_id`` is
                     required when the engine has ``SCRUBBER_ENABLED=true``.
        ttl_seconds: Override engine default TTL. ``None`` = engine default.

    Returns:
        ``Ok[str]`` with the episode_id on success, or ``Err`` on failure
        (auth / validation / network / DB).  Never raises for expected
        failure modes — caller pattern is
        ``if isinstance(result, Err): log; continue``.

    Requires ``init()`` to have been called first.
    """
    from .client import Err, Ok

    client = get_client()
    body: dict[str, Any] = {
        "workload_id": workload_id,
        "prompt": prompt,
        "response": response,
        "outcome": outcome,
        "metadata": metadata or {},
    }
    if ttl_seconds is not None:
        body["ttl_seconds"] = ttl_seconds

    result = client.post("/api/sdk/episodes", json_body=body)
    if isinstance(result, Ok):
        episode_id = result.value.get("episode_id", "") if isinstance(result.value, dict) else ""
        return Ok(value=episode_id, status_code=result.status_code)
    return result


def get_client() -> "SignalLayerClient":  # noqa: F821
    """Return a configured HTTP client instance.

    Requires ``init()`` to have been called first.

    Returns:
        A ``SignalLayerClient`` ready to make signed API requests.

    Raises:
        RuntimeError: If ``init()`` has not been called.
    """
    from .client import SignalLayerClient

    if not _config.get("api_key") or not _config.get("base_url"):
        raise RuntimeError(
            "signallayer.get_client() called before signallayer.init(). "
            "Call signallayer.init(api_key=..., base_url=...) first."
        )
    return SignalLayerClient(
        api_key=_config["api_key"],
        base_url=_config["base_url"],
        tenant=_config.get("tenant"),
        key_id=_config.get("key_id"),
    )


# ---------------------------------------------------------------------------
# Re-exported decorators
# ---------------------------------------------------------------------------

from .decorators import (  # noqa: E402
    evaluate,
    guardrails,
    policy_gate,
    scrub_pii,
    trace,
)

# ---------------------------------------------------------------------------
# Order guard
# ---------------------------------------------------------------------------

from .order_guard import guard  # noqa: E402

# ---------------------------------------------------------------------------
# Error types re-exported for convenience
# ---------------------------------------------------------------------------

from .errors import (  # noqa: E402
    AuthError,
    ChainBrokenError,
    DecoratorOrderError,
    PolicyDeniedError,
    SignalLayerError,
)

__all__ = [
    "__version__",
    "init",
    "get_client",
    "write_episode",
    # Decorators
    "policy_gate",
    "scrub_pii",
    "guardrails",
    "trace",
    "evaluate",
    "guard",
    # Errors
    "SignalLayerError",
    "AuthError",
    "PolicyDeniedError",
    "DecoratorOrderError",
    "ChainBrokenError",
]
