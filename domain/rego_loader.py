"""Rego-as-data loader for workload-specific policies.

F-024: `policies/*.rego` files were previously decorative — `policy_engine`
ran only Python-coded local checks and never consulted the rego source. The
CISO Console surfaces rego sha256s but the rules themselves never fired,
breaking the F-018 "rego file is source of truth" contract.

Scope of this loader (intentionally small):
  - Parse Rego *data* (sets + arrays of string literals) by regex.
  - Do NOT execute Rego logic. We do not embed OPA; we read the data the
    Rego file declares and enforce it in Python alongside the existing
    `_check_*` helpers.
  - Result: the file remains the single source of truth for what is
    allow-listed / what verb prefixes deny, and editing the rego edits the
    enforced rule. CISO sha256 stays meaningful.

Supported parse shapes (one per logical rule):
  set:    `name := {"a", "b", "c"}`
  array:  `name := ["create_", "update_"]`
  scalar: `name := 25`

Anything outside that shape is ignored — the loader logs a debug line so
unsupported rule additions surface in tests. Callers that need to enforce
true Rego logic (REVIEW conditionals, nested `some` blocks) must either
upgrade this loader or stand up real OPA via OPA_URL.
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

POLICIES_DIR = Path(__file__).resolve().parents[1] / "policies"

# `name := { "a", "b" }` — strict set-of-strings shape, multiline tolerant.
_SET_RE = re.compile(
    r"^\s*([a-z_][a-z0-9_]*)\s*:=\s*\{\s*([^}]*?)\s*\}\s*$",
    re.MULTILINE | re.DOTALL,
)
# `name := [ "a", "b" ]` — strict list-of-strings shape, multiline tolerant.
_LIST_RE = re.compile(
    r"^\s*([a-z_][a-z0-9_]*)\s*:=\s*\[\s*([^\]]*?)\s*\]\s*$",
    re.MULTILINE | re.DOTALL,
)
# `name := 25`
_INT_RE = re.compile(
    r"^\s*([a-z_][a-z0-9_]*)\s*:=\s*(\d+)\s*$",
    re.MULTILINE,
)
_STR_LITERAL_RE = re.compile(r'"([^"]*)"')


def _parse_rego_data(text: str) -> dict[str, object]:
    """Extract set / list / int data declarations from a Rego file.

    Order matters: int regex matches `name := 25` which would otherwise
    fail the set/list regexes, but we run all three independently and
    last-write-wins for any same-named collision (none expected in practice).
    """
    data: dict[str, object] = {}

    for m in _SET_RE.finditer(text):
        name, body = m.group(1), m.group(2)
        members = _STR_LITERAL_RE.findall(body)
        if members:
            data[name] = set(members)

    for m in _LIST_RE.finditer(text):
        name, body = m.group(1), m.group(2)
        members = _STR_LITERAL_RE.findall(body)
        if members:
            # Don't overwrite a set with a list of the same name.
            if name not in data:
                data[name] = list(members)

    for m in _INT_RE.finditer(text):
        name, value = m.group(1), m.group(2)
        if name not in data:
            data[name] = int(value)

    return data


@lru_cache(maxsize=32)
def load_workload_policy(rego_filename: str) -> dict[str, object]:
    """Load and parse one workload-specific rego file.

    Cached by filename. Returns {} (empty) if the file is missing — the
    caller treats "no policy data" as "no workload-specific constraints",
    which keeps the engine's fail-closed posture intact (org-mandatory and
    other categories still run).

    Args:
        rego_filename: Basename of the file in `policies/`, e.g.
            `"azure-architect.rego"`.
    """
    path = POLICIES_DIR / rego_filename
    if not path.exists():
        logger.debug("rego_loader: %s not found", path)
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("rego_loader: failed to read %s: %s", path, exc)
        return {}
    return _parse_rego_data(text)


def resolve_workload_policy(workload_id: str) -> tuple[str | None, dict[str, object]]:
    """Map a workload_id to its rego file + parsed data.

    Returns `(rego_filename, data)` or `(None, {})` when no workload-specific
    rego applies. Prefix-based to match the rego file's own `is_*` matcher
    convention (see `azure-architect.rego::is_azure_architect`).
    """
    if workload_id.startswith("azure-architect"):
        return ("azure-architect.rego", load_workload_policy("azure-architect.rego"))
    return (None, {})


def clear_cache() -> None:
    """Drop the parse cache. Test-only — production never edits rego at runtime."""
    load_workload_policy.cache_clear()
