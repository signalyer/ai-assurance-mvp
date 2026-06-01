"""Build deploy zip with forward-slash paths (Linux App Service requires it).

Stages selected source into a temp dir, swaps requirements.txt for the slim
requirements-deploy.txt, then writes deploy/app.zip via Python's zipfile (which
always uses forward slashes regardless of host OS).
"""

from __future__ import annotations

import os
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_ZIP = Path(__file__).resolve().parent / "app.zip"

# Whitelist of source paths to ship.
INCLUDE = [
    "dashboard.py",
    "__version__.py",  # Session 13 — imported by dashboard.py line 72 for FastAPI(version=...)
    "api",
    "domain",
    "middleware",
    "static",
    "storage.py",
    "tracer.py",
    "audit.py",
    "scrubber.py",  # Session 01a — Presidio scrubber, imported by api/demo_run.py
    "observability_compat.py",  # Session 10 — counter shims used by middleware + audit_chain
    "providers",  # Session 05 — provider abstraction (deferred imports in scrubber/tracer/evaluator/agent_memory/rag_engine)
    # Session 03 replaced the legacy guardrails.py FILE with a guardrails/
    # PACKAGE (nemo_adapters, llama_guard_adapter, financial_advisor_rail,
    # config/financial_advisor_rails.yaml). api/security.py imports from this
    # package at module load, so it MUST be in the zip. Day-12 root cause:
    # this entry was renamed from 'guardrails.py' but the package replacement
    # was never added, so dashboard.py crashed at import on every fresh
    # antenv (ModuleNotFoundError: No module named 'guardrails').
    "guardrails",
    "frameworks",  # Session 06 -- YAML loader + 5 framework YAMLs
    "observability",  # Session 10 -- structured logging + middleware + counters
    "policies",  # Session 02 -- .rego policy bundles loaded by domain/policy_engine
    "evaluator.py",
    "adversarial.py",
    "mock_data.py",
    "pdf_report.py",
    "report.py",
    "domains.py",
    "domains",
    # S55 #2 / F-009: do NOT ship data/. Every JSONL under data/ is runtime-
    # writable state (SDK keys, AI systems, findings, audit chain, etc.).
    # Including the local repo's data/ in the zip overwrites all runtime
    # state on every deploy — wiping every customer-issued SDK key, every
    # registered AI system, every finding, etc. storage._read_jsonl()
    # returns [] on missing files and storage._append_jsonl() creates them
    # in append mode, so a fresh App Service container handles the empty
    # state gracefully. Demo seed data lives in domain/seed.py (Python),
    # not data/*.jsonl. — see POC-RETROSPECTIVE.md F-009.
    #
    # S80: agents/ holds the Agent Runner registry + per-agent modules
    # (currently agents/_registry.py + agents/finadvice/). dashboard.py
    # eager-imports agents._registry at startup per
    # [[lazy-imports-skip-module-load-bootstrap]] — omitting it from the
    # zip produces a container ModuleNotFoundError with no obvious symptom
    # in /api/health (S80 close root cause). agents/finadvice/mocks/*.json
    # ARE included on purpose: deterministic code-shaped fixtures, not
    # runtime data (different from data/*.jsonl above). .env files inside
    # any agents subdir are blocked by FORBID_FILES.
    "agents",
]

# S82f-1c: the in-repo SDK package lives at sdk/signallayer/ but agent code
# does `import signallayer` (top-level). Without this remap the engine
# resolves at deploy time but the first vendor_risk run fails with
# ModuleNotFoundError mid-chain (not at startup — agents are lazy-loaded).
# Tuple form: (source-path-relative-to-repo, arcname-base-in-zip).
INCLUDE_REMAP: list[tuple[str, str]] = [
    ("sdk/signallayer", "signallayer"),
]
# Note: encryption.py (cryptography), run.py + ragas_evaluator.py (deepeval/ragas/garak)
# intentionally NOT included — they pull heavy deps and aren't on the dashboard runtime path.
# evaluator.py IS included; its deepeval import is now lazy.

# Never ship.
FORBID_FILES = {".env", "local.env", "local.settings.json", "audit.log", "dashboard.log"}
FORBID_DIRS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".venv", "venv", "node_modules", ".git"}
FORBID_SUFFIX = {".pyc", ".log"}


def should_skip(relpath: Path) -> bool:
    parts = set(relpath.parts)
    if parts & FORBID_DIRS:
        return True
    if relpath.name in FORBID_FILES:
        return True
    if relpath.suffix in FORBID_SUFFIX:
        return True
    return False


def _resolve_sha() -> str:
    """Return the build SHA. Prefers GITHUB_SHA (CI), falls back to git, then 'unknown'."""
    sha = os.getenv("GITHUB_SHA", "").strip()
    if sha:
        return sha
    try:
        import subprocess
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=str(ROOT), stderr=subprocess.DEVNULL
        )
        return out.decode("ascii").strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def main() -> None:
    if OUT_ZIP.exists():
        OUT_ZIP.unlink()

    file_count = 0
    with zipfile.ZipFile(OUT_ZIP, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for item in INCLUDE:
            src = ROOT / item
            if not src.exists():
                print(f"WARN: missing (skipped): {item}", file=sys.stderr)
                continue

            if src.is_file():
                rel = Path(item)
                if should_skip(rel):
                    continue
                zf.write(src, arcname=rel.as_posix())
                file_count += 1
                continue

            for dirpath, dirnames, filenames in os.walk(src):
                dirnames[:] = [d for d in dirnames if d not in FORBID_DIRS]
                for fname in filenames:
                    abs_path = Path(dirpath) / fname
                    rel = abs_path.relative_to(ROOT)
                    if should_skip(rel):
                        continue
                    zf.write(abs_path, arcname=rel.as_posix())
                    file_count += 1

        # S82f-1c: remapped includes (source dir → renamed top-level dir in zip)
        for src_rel, arc_base in INCLUDE_REMAP:
            src = ROOT / src_rel
            if not src.exists():
                print(f"WARN: missing remap source (skipped): {src_rel}", file=sys.stderr)
                continue
            for dirpath, dirnames, filenames in os.walk(src):
                dirnames[:] = [d for d in dirnames if d not in FORBID_DIRS]
                for fname in filenames:
                    abs_path = Path(dirpath) / fname
                    rel = abs_path.relative_to(src)
                    if should_skip(rel):
                        continue
                    arcname = (Path(arc_base) / rel).as_posix()
                    zf.write(abs_path, arcname=arcname)
                    file_count += 1

        # Slim requirements -> requirements.txt in zip
        slim = ROOT / "requirements-deploy.txt"
        if not slim.exists():
            raise SystemExit("requirements-deploy.txt missing")
        zf.write(slim, arcname="requirements.txt")
        file_count += 1

        # Bake the build SHA into the zip. /api/health reads BUILD_SHA at startup
        # so deploy verification can confirm prod matches the intended commit.
        sha = _resolve_sha()
        zf.writestr("BUILD_SHA", sha + "\n")
        file_count += 1
        print(f"BUILD_SHA baked: {sha}")

    size_kb = OUT_ZIP.stat().st_size / 1024
    print(f"Built {OUT_ZIP} ({file_count} files, {size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
