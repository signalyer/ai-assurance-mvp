"""Scan the deploy zip for top-level 3rd-party imports outside the slim allowlist.

Catches missing-deps before redeploying. Lists every (file, module) pair where
a top-level import references a package that isn't in requirements-deploy.txt
and isn't a stdlib module.
"""

from __future__ import annotations

import ast
import sys
import sysconfig
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ZIP_PATH = ROOT / "deploy" / "app.zip"

# Packages provided by requirements-deploy.txt (and their commonly-imported names).
SLIM_DEPS = {
    "fastapi", "starlette",
    "uvicorn", "gunicorn",
    "pydantic", "pydantic_core",
    "anthropic", "openai",
    "bcrypt", "itsdangerous",
    "dotenv",
    "multipart",
    "dateutil",
}


def stdlib_modules() -> set[str]:
    base = set(sys.stdlib_module_names) if hasattr(sys, "stdlib_module_names") else set()
    base.update({"typing", "dataclasses", "enum", "abc"})
    return base


STDLIB = stdlib_modules()


def first_party_modules() -> set[str]:
    """Modules shipped in our zip (top-level)."""
    out = set()
    with zipfile.ZipFile(ZIP_PATH) as zf:
        for n in zf.namelist():
            if "/" in n:
                top = n.split("/", 1)[0]
                out.add(top)
            elif n.endswith(".py"):
                out.add(n[:-3])
    return out


FIRST_PARTY = first_party_modules()


def top_modules_in(file_text: str) -> list[str]:
    """Return root module names from top-level imports in a file."""
    try:
        tree = ast.parse(file_text)
    except SyntaxError:
        return []
    out: list[str] = []
    # Only inspect direct children of the module body (i.e., top-level).
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.append(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                continue  # relative import
            if node.module:
                out.append(node.module.split(".")[0])
    return out


def main() -> int:
    misses: list[tuple[str, str]] = []
    with zipfile.ZipFile(ZIP_PATH) as zf:
        for name in zf.namelist():
            if not name.endswith(".py"):
                continue
            text = zf.read(name).decode("utf-8", errors="ignore")
            for mod in top_modules_in(text):
                if not mod:
                    continue
                if mod in STDLIB or mod in SLIM_DEPS or mod in FIRST_PARTY:
                    continue
                misses.append((name, mod))

    if not misses:
        print("OK: no top-level 3rd-party imports outside slim deps.")
        return 0

    # De-dupe + sort
    print(f"FOUND {len(misses)} suspect imports:")
    seen: set[tuple[str, str]] = set()
    for f, m in sorted(set(misses)):
        if (f, m) in seen:
            continue
        seen.add((f, m))
        print(f"  {f}: {m}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
