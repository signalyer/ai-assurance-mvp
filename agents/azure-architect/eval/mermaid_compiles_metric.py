"""Custom DeepEval metric — does the generated Mermaid source compile?

P6 deliverable. Returns 0/1 binary: 1 if `mmdc` (Mermaid CLI) can render the
source to SVG without error, 0 otherwise. Slot this into the DeepEval
`metrics=[...]` list alongside hallucination / relevancy / faithfulness /
PII-leakage so the eval card surfaces all five scores side-by-side.

The platform's eval harness expects a callable with this signature:

    def metric(test_case) -> tuple[float, str]:
        return (score, reason)

where `test_case.actual_output` is the JSON envelope returned by the agent
(see prompts/system.md — it has key `mermaid_source`).

Per CLAUDE.md universal rule: this metric MUST run against real data — never
synthetic. The dataset.jsonl examples include one deliberately-broken case
(`broken-circular`) so calibration sees a known-0 score.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path


def _find_mmdc() -> str | None:
    """Return path to mermaid-cli binary, or None if missing.

    Returns:
        Absolute path to `mmdc` or None. Caller logs a friendly error in
        the None case rather than crashing the entire eval run.
    """
    return shutil.which("mmdc")


def mermaid_compiles_metric(actual_output: str) -> tuple[float, str]:
    """Returns (1.0, "ok") iff actual_output['mermaid_source'] compiles.

    Args:
        actual_output: JSON string from the agent — must parse to a dict
            containing the key `mermaid_source` (string).

    Returns:
        (score, reason) tuple. score is 1.0 (compiles) or 0.0 (fails to
        parse the envelope OR Mermaid CLI rejects the source). reason is
        a one-liner suitable for the eval card.
    """
    mmdc = _find_mmdc()
    if mmdc is None:
        return (0.0, "mermaid-cli (mmdc) not on PATH — install @mermaid-js/mermaid-cli")

    try:
        envelope = json.loads(actual_output)
    except json.JSONDecodeError as exc:
        return (0.0, f"actual_output is not valid JSON: {exc.msg}")

    if not isinstance(envelope, dict) or "mermaid_source" not in envelope:
        return (0.0, "envelope missing required key 'mermaid_source'")

    source = envelope["mermaid_source"]
    if not isinstance(source, str) or not source.strip():
        return (0.0, "'mermaid_source' is empty or non-string")

    with tempfile.TemporaryDirectory() as tmp:
        src_path = Path(tmp) / "diagram.mmd"
        out_path = Path(tmp) / "diagram.svg"
        src_path.write_text(source, encoding="utf-8")
        try:
            result = subprocess.run(
                [mmdc, "-i", str(src_path), "-o", str(out_path), "--quiet"],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            return (0.0, "mmdc timed out after 30s — diagram likely too large or has parser pathology")

        if result.returncode != 0:
            err = (result.stderr or result.stdout or "")[:200]
            return (0.0, f"mmdc exit {result.returncode}: {err.strip()}")

        if not out_path.exists() or out_path.stat().st_size == 0:
            return (0.0, "mmdc exited 0 but produced no SVG")

    return (1.0, "compiled")


__all__ = ["mermaid_compiles_metric"]
