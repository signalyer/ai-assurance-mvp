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
    "api",
    "domain",
    "middleware",
    "static",
    "storage.py",
    "tracer.py",
    "audit.py",
    "guardrails.py",
    "evaluator.py",
    "adversarial.py",
    "mock_data.py",
    "pdf_report.py",
    "report.py",
    "domains.py",
    "domains",
    "data",
    # Session 10 observability — was missing from the deploy package, which
    # silently disabled telemetry on Azure because the try/ImportError in
    # dashboard.py swallowed the missing-module error. Added Day-12.
    "observability",
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

        # Slim requirements -> requirements.txt in zip
        slim = ROOT / "requirements-deploy.txt"
        if not slim.exists():
            raise SystemExit("requirements-deploy.txt missing")
        zf.write(slim, arcname="requirements.txt")
        file_count += 1

    size_kb = OUT_ZIP.stat().st_size / 1024
    print(f"Built {OUT_ZIP} ({file_count} files, {size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
