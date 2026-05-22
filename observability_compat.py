"""Observability compatibility shim.

Provides safe fallback stubs for all ``observability.counters`` functions so
that modules which call counter hooks continue to import cleanly even when the
full observability package has not yet been installed (e.g. test environments
where ``prometheus-client`` is absent or ``observability/counters.py`` does not
exist yet).

Usage in each instrumented module::

    try:
        from observability.counters import record_scrub, record_policy_deny  # etc.
    except ImportError:
        from observability_compat import record_scrub, record_policy_deny  # etc.

This file lives at the repo root beside ``dashboard.py``.

Session 10 — AI Assurance Platform.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Safe no-op stubs — all counter calls must be non-raising by contract.
# ---------------------------------------------------------------------------


def record_scrub(detected_count: int = 0) -> None:
    """Stub: increment scrub counter by *detected_count* PII entities."""


def record_policy_deny() -> None:
    """Stub: increment policy-deny counter by 1."""


def record_pii_leak() -> None:
    """Stub: increment PII-leak-attempt counter by 1."""


def record_opa_unreachable() -> None:
    """Stub: increment OPA-unreachable counter by 1."""


def record_vault_error() -> None:
    """Stub: increment vault-decryption-error counter by 1."""


def record_audit_chain_break() -> None:
    """Stub: increment audit-chain-break counter by 1."""


def record_rtf_cascade(status: str) -> None:
    """Stub: increment RTF-cascade counter labelled with *status*."""


def record_eval_failure() -> None:
    """Stub: increment eval-failure counter by 1."""


__all__ = [
    "record_scrub",
    "record_policy_deny",
    "record_pii_leak",
    "record_opa_unreachable",
    "record_vault_error",
    "record_audit_chain_break",
    "record_rtf_cascade",
    "record_eval_failure",
]
