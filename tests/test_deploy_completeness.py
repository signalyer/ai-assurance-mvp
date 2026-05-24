"""Deploy zip completeness test.

Catches the class of bug that detonated Session 12 (deploy outage from
INCLUDE whitelist drift) and Session 19 (`__version__.py` never shipped
since Session 13). Both failures had the same shape: a file referenced at
import time by `dashboard.py` was missing from `deploy/build-zip.py`'s
INCLUDE list, the stale prod container masked the gap, and the next fresh
Oryx rebuild crashed on cold start.

The test builds the deploy zip the same way CI does, extracts it to a
temporary directory, then runs `python -c "import dashboard"` in a fresh
subprocess with that directory as the only source root. This mimics what
App Service Linux does on every fresh antenv build — the exact moment the
two prior bugs surfaced.

If a required *Python package* is missing from the *test environment*
(not from the zip), the test skips rather than fails — the test is about
the zip's source-file completeness, not whether the developer has every
heavy SDK installed locally. The CI environment must have
`requirements-deploy.txt` installed for the test to be meaningful; it does.
"""
from __future__ import annotations

import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
BUILD_SCRIPT = REPO_ROOT / "deploy" / "build-zip.py"
ZIP_PATH = REPO_ROOT / "deploy" / "app.zip"


def _run(cmd: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """Run a subprocess and capture stdout/stderr as text."""
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


@pytest.fixture(scope="module")
def built_zip(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build the deploy zip into a session-scoped tmp location.

    We do NOT use the repo's `deploy/app.zip` path because a developer may
    have a stale zip lying around. Always build fresh.
    """
    out_dir = tmp_path_factory.mktemp("deploy-zip-build")
    out_zip = out_dir / "app.zip"

    # build-zip.py writes to deploy/app.zip hardcoded; run it, then copy.
    proc = _run(
        [sys.executable, str(BUILD_SCRIPT)],
        cwd=REPO_ROOT,
    )
    assert proc.returncode == 0, (
        f"build-zip.py failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    )
    assert ZIP_PATH.exists(), "build-zip.py reported success but app.zip missing"

    out_zip.write_bytes(ZIP_PATH.read_bytes())
    return out_zip


@pytest.fixture(scope="module")
def extracted_zip(built_zip: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Extract the built zip to a fresh directory and return that root."""
    extract_root = tmp_path_factory.mktemp("deploy-zip-extract")
    with zipfile.ZipFile(built_zip, "r") as zf:
        zf.extractall(extract_root)
    return extract_root


def test_build_sha_baked(extracted_zip: Path) -> None:
    """Session 19 invariant: every zip carries a BUILD_SHA artifact."""
    sha_file = extracted_zip / "BUILD_SHA"
    assert sha_file.exists(), "BUILD_SHA missing from deploy zip"
    content = sha_file.read_text().strip()
    assert content, "BUILD_SHA file empty"


def test_dashboard_imports_from_zip_contents(extracted_zip: Path) -> None:
    """The Session 12 / Session 19 root-cause test.

    Run `import dashboard` in a fresh interpreter whose only Python source
    root is the extracted zip. Any `ModuleNotFoundError` for a *first-party*
    module (e.g. `frameworks`, `providers`, `__version__`) means the
    INCLUDE list in build-zip.py has drifted from the import graph.

    Missing *third-party* packages (e.g. `fastapi`, `dotenv`) surface as a
    skip — the test environment is responsible for those, not the zip.
    """
    # Clean environment: nothing from the developer's shell leaks in.
    env: dict[str, str] = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(extracted_zip),
        "PYTHONDONTWRITEBYTECODE": "1",
        # Don't trigger App Insights / metrics / etc. on bare import.
        "APPLICATIONINSIGHTS_CONNECTION_STRING": "",
        "METRICS_ENABLED": "false",
        # Match the SESSION-12B App Service runtime to avoid pulling deepeval.
        "EVAL_BACKEND": "noop",
        "SCRUBBER_BACKEND": "regex",
        "TRACER_BACKEND": "noop",
        "MEMORY_BACKEND": "noop",
        "RAG_BACKEND": "noop",
    }
    if sys.platform == "win32":
        # Preserve Windows DLL search path so the interpreter can start at all.
        for k in ("SYSTEMROOT", "SYSTEMDRIVE", "TEMP", "TMP"):
            v = os.environ.get(k)
            if v:
                env[k] = v

    proc = _run(
        [sys.executable, "-c", "import dashboard; print('OK')"],
        cwd=extracted_zip,
        env=env,
    )

    if proc.returncode == 0:
        assert "OK" in proc.stdout
        return

    # Distinguish "zip is incomplete" from "test env is missing third-party deps".
    stderr = proc.stderr
    third_party_hint = _detect_missing_third_party(stderr)
    if third_party_hint:
        pytest.skip(
            f"Test env missing third-party package: {third_party_hint}. "
            "Install requirements-deploy.txt to run this test for real. "
            "This skip does NOT validate zip completeness."
        )

    pytest.fail(
        "Importing dashboard from extracted deploy zip failed.\n"
        "This is the Session 12 / Session 19 failure mode: INCLUDE list in\n"
        "deploy/build-zip.py is missing a first-party module referenced at\n"
        "import time. Add the missing entry to INCLUDE and re-run.\n\n"
        f"STDOUT:\n{proc.stdout}\n\nSTDERR:\n{stderr}"
    )


# Conservative list — anything outside this set in a ModuleNotFoundError is
# treated as a first-party miss (i.e. the zip is incomplete). Keep narrow.
_THIRD_PARTY_PREFIXES: tuple[str, ...] = (
    "fastapi", "starlette", "pydantic", "pydantic_settings", "pydantic_core",
    "dotenv", "uvicorn", "httpx", "httpcore", "anthropic", "openai",
    "psycopg", "psycopg2", "psycopg_pool", "cryptography", "azure",
    "opentelemetry", "prometheus_client", "portalocker", "cachetools",
    "presidio_analyzer", "presidio_anonymizer", "spacy", "yaml",
    "typer", "click", "deepeval", "ragas", "garak",
    "langfuse", "redis", "boto3", "botocore",
)


def _detect_missing_third_party(stderr: str) -> str | None:
    """Return the third-party module name if stderr indicates one is missing."""
    marker = "No module named "
    if marker not in stderr:
        return None
    # Last occurrence is the deepest in the import chain; pull its quoted name.
    tail = stderr.rsplit(marker, 1)[1].strip()
    # Forms: 'No module named 'foo'' or 'No module named 'foo.bar''
    if not tail or tail[0] not in ("'", '"'):
        return None
    quote = tail[0]
    end = tail.find(quote, 1)
    if end < 0:
        return None
    name = tail[1:end]
    top = name.split(".", 1)[0]
    if top in _THIRD_PARTY_PREFIXES:
        return top
    return None


def test_include_list_documented_excludes_still_excluded() -> None:
    """Session 12 comment in build-zip.py:53 lists deliberate exclusions.

    Lock that intent: if a future session quietly adds e.g. `garak` to the
    INCLUDE whitelist, this test fails and forces the change through
    review. The exclusions encode the slim-deploy invariant (see
    ADR-001-garak.md).
    """
    text = BUILD_SCRIPT.read_text(encoding="utf-8")
    forbidden_in_include = ("garak", "ragas", "encryption.py")
    # Pull the INCLUDE list block by simple bracket slicing.
    start = text.index("INCLUDE = [")
    end = text.index("]", start)
    include_block = text[start:end]
    for name in forbidden_in_include:
        assert name not in include_block, (
            f"{name!r} appeared in deploy/build-zip.py INCLUDE list. "
            "This violates the slim-deploy invariant documented at "
            "build-zip.py:53 and ADR-001-garak.md §2. If this is intentional, "
            "update the ADR and this test together."
        )


def test_forbidden_files_not_in_zip(extracted_zip: Path) -> None:
    """No secrets / local artifacts should ever ship."""
    forbidden = {".env", "local.env", "local.settings.json", "audit.log", "dashboard.log"}
    found: list[str] = []
    for path in extracted_zip.rglob("*"):
        if path.is_file() and path.name in forbidden:
            found.append(str(path.relative_to(extracted_zip)))
    assert not found, f"Forbidden files in deploy zip: {found}"
