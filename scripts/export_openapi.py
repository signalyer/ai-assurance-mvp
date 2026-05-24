"""Export FastAPI's OpenAPI schema to docs/openapi-v1.json.

Run automatically via pre-commit hook (see .pre-commit-config.yaml).
Committing the artifact means API changes are visible in PR review diffs --
contract drift becomes a code-review concern instead of a post-deploy
archaeology task.

Per docs/plans/SESSION-13-api-typing-audit.md §6.

Usage:
    python scripts/export_openapi.py            # writes docs/openapi-v1.json
    python scripts/export_openapi.py --check    # exit 1 if artifact would change
    python scripts/export_openapi.py --stdout   # print to stdout instead

Exit codes:
    0  artifact written (or already up-to-date in --check mode)
    1  --check mode and artifact would change (drift detected)
    2  internal error (couldn't import dashboard, etc.)
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Ensure noop backends so dashboard import doesn't hit Langfuse / Postgres / etc.
# Matches the CI workflow env (.github/workflows/contract-tests.yml).
_NOOP_BACKENDS = {
    "EVAL_BACKEND": "noop",
    "SCRUBBER_BACKEND": "regex",
    "TRACER_BACKEND": "noop",
    "MEMORY_BACKEND": "noop",
    "RAG_BACKEND": "noop",
    "POLICY_BACKEND": "noop",
    # Suppress the startup drift check during export -- circular dependency
    # otherwise (script generates artifact <-> dashboard checks artifact).
    "SL_OPENAPI_SKIP_STARTUP_CHECK": "true",
}
for k, v in _NOOP_BACKENDS.items():
    os.environ.setdefault(k, v)


def _generate() -> dict:
    """Import dashboard.py and return the OpenAPI spec dict."""
    # Ensure repo root is on sys.path so `import dashboard` works
    repo_root = Path(__file__).resolve().parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from dashboard import app  # type: ignore[import]
    return app.openapi()


def _serialize(spec: dict) -> str:
    """Deterministic JSON serialization (sort_keys for stable diffs)."""
    return json.dumps(spec, indent=2, sort_keys=True) + "\n"


def main(argv: list[str]) -> int:
    repo_root = Path(__file__).resolve().parent.parent
    artifact = repo_root / "docs" / "openapi-v1.json"

    check_mode = "--check" in argv
    stdout_mode = "--stdout" in argv

    try:
        spec = _generate()
    except Exception as exc:                                  # noqa: BLE001
        print(f"ERROR: failed to generate OpenAPI spec: {exc!r}", file=sys.stderr)
        return 2

    serialized = _serialize(spec)

    if stdout_mode:
        sys.stdout.write(serialized)
        return 0

    if check_mode:
        if not artifact.exists():
            print(f"DRIFT: {artifact} does not exist. Run scripts/export_openapi.py.")
            return 1
        existing = artifact.read_text(encoding="utf-8")
        if existing != serialized:
            print(
                f"DRIFT: {artifact.relative_to(repo_root)} does not match "
                "current code. Run `python scripts/export_openapi.py` and "
                "commit the diff."
            )
            return 1
        print(f"OK: {artifact.relative_to(repo_root)} matches current code.")
        return 0

    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(serialized, encoding="utf-8")
    print(f"Wrote {artifact.relative_to(repo_root)} ({len(serialized)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
