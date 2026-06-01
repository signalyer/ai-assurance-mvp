# AGENTS.md — AI Assurance Platform | aigovern.sandboxhub.co

## Before every task
Read ARCHITECTURE.md before writing any code.
Confirm by stating the current decorator chain order and
the three most recent "in progress" files.

## Code standards
- Full updated files only — never partial functions or snippets
- Type hints on all parameters and return values
- Docstring on every public function
- `from __future__ import annotations` at top of every Python file
- Pydantic v2 for domain models — ConfigDict, not Config class
- Read every existing file before modifying it
- `python -c "import <module>"` must pass before next file

## Security rules (never violate)
- scrubber.tokenise_payload() runs BEFORE tracer.trace_call()
  Langfuse gets scrubbed_prompt — never raw_prompt
- Policy engine errors → default DENY, never ALLOW
- No SaaS guardrails — all self-hosted, no external prompt routing
- No secrets in code — all config via environment variables

## Storage rules
- JSONL only via storage.py _append_jsonl() and _read_jsonl()
- No direct file writes outside storage.py pattern

## File placement
- New root modules: beside tracer.py (scrubber.py, providers.py)
- New domain: domain/<name>.py — follow domain/repository.py
- New API routers: api/<name>.py — mount in dashboard.py
- New UI: static/<name>.html — follow static/runtime.html
- New middleware: middleware/<name>.py
- Policy files: policies/<name>.rego

## When blocked
Stop. State the blocker. Never fake output. Never work around silently.

## End of every session
1. Run /verify — show all output
2. Update ARCHITECTURE.md — move completed items
3. Write next session plan file to docs/plans/
4. List deviations and open issues

## Compound engineering rule
Every mistake I correct → add a new rule to this file immediately.
Label it with the date. This file grows with experience.

- 2026-05-27: When a test loads a Python file from a hyphenated path with
  `importlib.util.spec_from_file_location`, Pydantic v2 postponed annotations
  may not resolve because the module is not importable by package name. Either
  insert the module into `sys.modules` before `exec_module()` or call
  `model_rebuild(_types_namespace=globals())` on models with forward refs before
  validating.
