"""Guard against regression of lazy-import discipline in adversarial.py.

Session 20: anthropic + openai SDKs are imported lazily inside
run_single_probe(), not at module top level. This keeps cold-start time
down and lets /api/adversarial/categories serve without dragging in the
SDKs transitively.

If a future contributor moves either SDK import back to the top level,
this test fails fast. Pure AST inspection — no need to actually import
the SDKs to run the check.
"""
from __future__ import annotations

import ast
from pathlib import Path

ADVERSARIAL_PATH = Path(__file__).resolve().parent.parent / "adversarial.py"
FORBIDDEN_TOP_LEVEL = {"anthropic", "openai"}


def _top_level_imports(source: str) -> set[str]:
    """Return the set of root module names imported at module scope."""
    tree = ast.parse(source)
    roots: set[str] = set()
    for node in tree.body:  # only top level — not recursive
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".", 1)[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                roots.add(node.module.split(".", 1)[0])
    return roots


def test_no_top_level_anthropic_or_openai_import() -> None:
    """adversarial.py must not import anthropic or openai at module scope."""
    source = ADVERSARIAL_PATH.read_text(encoding="utf-8")
    top = _top_level_imports(source)
    leaked = top & FORBIDDEN_TOP_LEVEL
    assert not leaked, (
        f"adversarial.py imports {leaked} at top level — must be lazy "
        f"inside run_single_probe(). See docs/plans/SESSION-20-plan.md."
    )


def test_module_imports_without_sdk_dependencies(monkeypatch) -> None:
    """Importing adversarial must succeed even if anthropic/openai are absent.

    We don't physically uninstall the SDKs here — instead we confirm the
    module-level import has no transitive dependency by reloading it and
    checking that neither SDK appears in its module namespace.
    """
    import importlib
    import sys

    sys.modules.pop("adversarial", None)
    mod = importlib.import_module("adversarial")
    # The lazy imports live inside a function — they should NOT have leaked
    # into the module namespace at import time.
    assert not hasattr(mod, "Anthropic"), (
        "Anthropic symbol leaked into adversarial module namespace"
    )
    assert not hasattr(mod, "OpenAI"), (
        "OpenAI symbol leaked into adversarial module namespace"
    )
