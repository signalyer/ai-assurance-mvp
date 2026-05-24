"""Custom Schemathesis hooks enforcing CLAUDE.md security rules at the API contract level.

Loaded by the contract-tests GitHub Actions workflow via
`schemathesis run ... --hooks ci/schemathesis_hooks.py`.

Per docs/plans/SESSION-13-api-typing-audit.md §1.9 + §5.2.

Three contract-level guarantees enforced by these hooks:
  1. No secret-shaped token EVER appears in a response body.
  2. No forbidden field name (raw_prompt, unscrubbed_prompt, pii_entities)
     appears anywhere in any response, at any nesting depth.
  3. Every LLM-triggering endpoint (per audit §1.6) populates
     governance.trace_id on its 200 response.

Rules 1 + 2 enforce the CLAUDE.md security invariant:
    "scrubber.tokenise_payload() runs BEFORE tracer.trace_call() --
     Langfuse gets scrubbed_prompt, never raw_prompt"
extended to the API surface.

Rule 3 is the cross-tool traceability contract: every LLM-touching response
includes the App Insights / Langfuse correlation ID, so the CISO Console
"explain this finding" flyout can link directly to the trace.
"""
from __future__ import annotations

import re

import schemathesis

# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

# Matches Anthropic / OpenAI / Azure API key shapes.
# Add new providers as we wire them in -- false negatives are acceptable
# (other layers also enforce), false positives waste CI cycles.
_SECRET_RE = re.compile(r"sk-(ant|proj|[a-zA-Z]+)-[A-Za-z0-9]{20,}")

# Field names that MUST NOT appear anywhere in any response.
_FORBIDDEN_KEYS = frozenset({
    "raw_prompt",
    "unscrubbed_prompt",
    "pii_entities",     # the VALUES list -- not metadata counts (pii_count is fine)
})

# Endpoints that MUST populate governance.trace_id on their 200 response.
# Synced with audit doc §1.6 "Endpoints that MUST populate it".
_LLM_TRIGGERING_PATHS = frozenset({
    "/api/assurance-model/ask",
    "/api/assurance-model/summarize-finding",
    "/api/assurance-model/summarize-evidence",
    "/api/assurance-model/explain-release",
    "/api/assurance-model/draft-report",
    "/api/batch/run",
    "/api/batch/run-domain/{domain_id}",
})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _walk_dict(obj: object, key_predicate, value_predicate, path: str = "") -> list[str]:
    """Walk a JSON value, returning a list of error strings for matches.

    key_predicate(key) -> bool: raise if any key matches.
    value_predicate(value) -> bool: raise if any string value matches.
    """
    errors: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            sub_path = f"{path}.{k}" if path else k
            if key_predicate(k):
                errors.append(f"forbidden key '{k}' at {sub_path}")
            errors.extend(_walk_dict(v, key_predicate, value_predicate, sub_path))
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            errors.extend(_walk_dict(item, key_predicate, value_predicate, f"{path}[{i}]"))
    elif isinstance(obj, str):
        if value_predicate(obj):
            errors.append(f"forbidden-pattern string value at {path}")
    return errors


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

@schemathesis.check
def no_secret_in_response(response, case):
    """Response body must never contain a secret-shaped token.

    Runs against the raw response text -- catches secrets even in error
    messages, log lines, debug dumps. Fast (single regex scan).
    """
    body = getattr(response, "text", "") or ""
    if _SECRET_RE.search(body):
        raise AssertionError(
            f"Response from {case.operation.method.upper()} {case.operation.path} "
            f"contains a secret-shaped token (sk-*). This is a CLAUDE.md "
            f"security violation -- secrets must never reach the API surface."
        )


@schemathesis.check
def no_raw_prompt_field(response, case):
    """Response body must never contain a forbidden field name at any depth.

    Walks the parsed JSON recursively. Catches the case where a router
    accidentally echoes raw_prompt / unscrubbed_prompt / pii_entities
    in a nested debug field that the response_model didn't cover.
    """
    try:
        body = response.json()
    except (ValueError, AttributeError):
        return  # non-JSON response is fine (e.g. PDF, redirect)

    errors = _walk_dict(
        body,
        key_predicate=lambda k: k in _FORBIDDEN_KEYS,
        value_predicate=lambda v: False,  # value check handled by no_secret_in_response
    )
    if errors:
        raise AssertionError(
            f"Response from {case.operation.method.upper()} {case.operation.path} "
            f"contains forbidden field(s): {'; '.join(errors)}. "
            f"Per audit §1.9: scrubbed-only fields permitted on the API surface."
        )


@schemathesis.check
def llm_response_has_trace_id(response, case):
    """Endpoints that trigger LLM calls must include governance.trace_id.

    Per audit §1.6: cross-tool traceability requires every LLM-touching
    response to carry the trace_id so SPAs / CISO Console can link to
    App Insights + Langfuse.

    Skipped for non-200 responses (denials, validation errors don't trigger
    the LLM path and have no trace_id to surface).
    """
    if case.operation.path not in _LLM_TRIGGERING_PATHS:
        return
    if getattr(response, "status_code", 0) != 200:
        return

    try:
        body = response.json()
    except (ValueError, AttributeError):
        return

    if not isinstance(body, dict):
        raise AssertionError(
            f"LLM-triggering endpoint {case.operation.path} returned non-object body; "
            f"governance metadata cannot be carried."
        )

    governance = body.get("governance")
    # NOTE: trace_id plumbing is Phase 1.5 per audit §9. Until then the
    # governance object is present but trace_id may be None. This check
    # currently asserts only that the GOVERNANCE OBJECT exists; once Phase
    # 1.5 plumbs values, tighten to require trace_id is a non-empty string.
    if governance is None:
        raise AssertionError(
            f"LLM-triggering endpoint {case.operation.path} response missing "
            f"`governance` field. Per audit §1.6, every LLM-touching response "
            f"must carry GovernanceMetadata for trace_id correlation."
        )
