"""Process-local Prometheus counters and histograms for the AI Assurance Platform.

All public functions are safe to call even when ``prometheus_client`` is not
installed -- they degrade silently to no-ops rather than crashing the
application.  Idempotent registration is guaranteed: importing this module
multiple times (or reloading it in tests) never raises ``ValueError``.
"""
from __future__ import annotations

import logging
import time
from collections import deque
from threading import Lock

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional prometheus_client import
# ---------------------------------------------------------------------------
try:
    import prometheus_client as _prom
    from prometheus_client import Counter, Histogram, CollectorRegistry, REGISTRY

    _PROMETHEUS_AVAILABLE = True
except Exception:  # broad: covers ImportError + any init failure
    _PROMETHEUS_AVAILABLE = False
    _prom = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Metric registration helpers
# ---------------------------------------------------------------------------

def _make_counter(name: str, documentation: str, labelnames: list[str] | None = None) -> object:
    """Register and return a Counter, or a no-op sentinel if unavailable.

    Catches ``ValueError`` raised by prometheus_client when a metric with the
    same name is already registered (can happen during test module reloads).
    """
    if not _PROMETHEUS_AVAILABLE:
        return _NoOpCounter()
    try:
        labels = labelnames or []
        return Counter(name, documentation, labels)
    except ValueError:
        # Already registered -- retrieve from registry.
        return REGISTRY._names_to_collectors.get(name) or _NoOpCounter()
    except Exception as exc:
        _log.error("counter_registration_failed name=%s error=%s", name, exc)
        return _NoOpCounter()


class _NoOpCounter:
    """Sentinel used when prometheus_client is absent or registration fails."""

    def inc(self, amount: float = 1) -> None:  # noqa: D401
        """No-op increment."""

    def labels(self, **_kwargs: object) -> _NoOpCounter:  # noqa: D401
        """Return self for chained .labels(...).inc() calls."""
        return self


# ---------------------------------------------------------------------------
# Metric definitions  (module-level singletons)
# ---------------------------------------------------------------------------

_scrub_pii_detected = _make_counter(
    "scrub_pii_detected_total",
    "Number of PII tokens detected and scrubbed.",
)

_eval_failure = _make_counter(
    "eval_failure_total",
    "Number of evaluation scores that fell below the pass threshold.",
)

_policy_deny = _make_counter(
    "policy_deny_total",
    "Number of requests denied by the policy engine.",
)

_pii_leak_attempt = _make_counter(
    "pii_leak_attempt_total",
    "Number of PII injection / leak attempts detected by the injection guard.",
)

_opa_unreachable = _make_counter(
    "opa_unreachable_total",
    "Number of times the OPA sidecar was unreachable and the fallback path was taken.",
)

_vault_error = _make_counter(
    "vault_error_total",
    "Number of Fernet decryption failures in the de-id vault.",
)

_audit_chain_break = _make_counter(
    "audit_chain_break_total",
    "Number of times the audit chain verify returned a non-CLEAN status.",
)

_rtf_cascade = _make_counter(
    "rtf_cascade_total",
    "Right-to-Forget cascade completions labelled by status.",
    ["status"],
)

_rtf_sidecar_unsigned = _make_counter(
    "rtf_sidecar_unsigned_total",
    "Number of RTF sidecar entries that were unsigned or had an invalid HMAC signature.",
)

# S46 — V1 surface deprecation. Cumulative Prometheus counter for long-term
# trend visibility, plus an in-process deque of recent hit timestamps for the
# 24h-window readout surfaced via /api/health. Process-local is intentional:
# when the worker recycles the rolling figure resets to zero, which is the
# conservatively-correct answer ("has anyone hit V1 since process start?").
_v1_surface_hits = _make_counter(
    "v1_surface_hits_total",
    "Number of HTTP hits to legacy V1 navigation pages (deprecated; removal 2026-07-02).",
    ["route"],
)

_V1_HIT_WINDOW_SECONDS = 24 * 60 * 60
_v1_hit_timestamps: deque[float] = deque()
_v1_hit_lock = Lock()

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_scrub(detected_count: int) -> None:
    """Increment the PII-scrub counter by the number of detected tokens.

    Args:
        detected_count: Number of PII tokens that were detected and scrubbed
                        in a single payload.  May be 0 when the scrubber ran
                        but found nothing -- caller decides whether to invoke.
    """
    try:
        _scrub_pii_detected.inc(max(0, detected_count))
    except Exception as exc:
        _log.debug("record_scrub_noop error=%s", exc)


def record_eval_failure() -> None:
    """Increment the evaluation-failure counter by one."""
    try:
        _eval_failure.inc()
    except Exception as exc:
        _log.debug("record_eval_failure_noop error=%s", exc)


def record_policy_deny() -> None:
    """Increment the policy-deny counter by one."""
    try:
        _policy_deny.inc()
    except Exception as exc:
        _log.debug("record_policy_deny_noop error=%s", exc)


def record_pii_leak() -> None:
    """Increment the PII-leak-attempt counter by one."""
    try:
        _pii_leak_attempt.inc()
    except Exception as exc:
        _log.debug("record_pii_leak_noop error=%s", exc)


def record_opa_unreachable() -> None:
    """Increment the OPA-unreachable counter by one."""
    try:
        _opa_unreachable.inc()
    except Exception as exc:
        _log.debug("record_opa_unreachable_noop error=%s", exc)


def record_vault_error() -> None:
    """Increment the vault-decryption-error counter by one."""
    try:
        _vault_error.inc()
    except Exception as exc:
        _log.debug("record_vault_error_noop error=%s", exc)


def record_audit_chain_break() -> None:
    """Increment the audit-chain-break counter by one."""
    try:
        _audit_chain_break.inc()
    except Exception as exc:
        _log.debug("record_audit_chain_break_noop error=%s", exc)


def record_rtf_sidecar_unsigned() -> None:
    """Increment the counter for RTF sidecar entries with absent or invalid HMAC signatures."""
    try:
        _rtf_sidecar_unsigned.inc()
    except Exception as exc:
        _log.debug("record_rtf_sidecar_unsigned_noop error=%s", exc)


def record_v1_surface_hit(route: str) -> None:
    """Record a hit to a legacy V1 navigation page.

    Increments the cumulative Prometheus counter (labelled by route) and
    appends the timestamp to the 24h rolling window used by /api/health.
    Both operations are best-effort and never raise.

    Args:
        route: The V1 URL path (e.g. ``"/ai-systems"``) used as the counter label.
    """
    try:
        _v1_surface_hits.labels(route=route).inc()
    except Exception as exc:
        _log.debug("record_v1_surface_hit_counter_noop route=%s error=%s", route, exc)
    try:
        now = time.time()
        with _v1_hit_lock:
            _v1_hit_timestamps.append(now)
            cutoff = now - _V1_HIT_WINDOW_SECONDS
            while _v1_hit_timestamps and _v1_hit_timestamps[0] < cutoff:
                _v1_hit_timestamps.popleft()
    except Exception as exc:
        _log.debug("record_v1_surface_hit_deque_noop error=%s", exc)


def get_v1_surface_hits_24h() -> int:
    """Return the count of V1 navigation hits in the trailing 24 hours.

    Process-local: resets when the worker recycles. Used by /api/health to
    drive the V1-deletion observation criterion (7 consecutive days under
    5 hits/day catches lingering bookmarks and external links).
    """
    try:
        now = time.time()
        cutoff = now - _V1_HIT_WINDOW_SECONDS
        with _v1_hit_lock:
            while _v1_hit_timestamps and _v1_hit_timestamps[0] < cutoff:
                _v1_hit_timestamps.popleft()
            return len(_v1_hit_timestamps)
    except Exception as exc:
        _log.debug("get_v1_surface_hits_24h_noop error=%s", exc)
        return 0


def record_rtf_cascade(status: str) -> None:
    """Increment the RTF-cascade counter labelled by *status*.

    Args:
        status: Outcome label, e.g. ``"COMPLETED"``, ``"PARTIAL_FAILURE"``,
                ``"FAILED"``.  Kept as a free string; callers are responsible
                for using consistent values.
    """
    try:
        _rtf_cascade.labels(status=status).inc()
    except Exception as exc:
        _log.debug("record_rtf_cascade_noop status=%s error=%s", status, exc)
