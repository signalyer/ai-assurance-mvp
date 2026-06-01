"""vendor_risk CLI — invoke the agent against a fixture for calibration.

Usage:
    PYTHONPATH=. python -m agents.vendor_risk.cli --fixture 01-clean-saas
    PYTHONPATH=. python -m agents.vendor_risk.cli --fixture 11-mnpi-deal-context --system int
    PYTHONPATH=. python -m agents.vendor_risk.cli --fixture 08-adv-pdf-injection --deep

Notes:
  - Always runs the EVAL seam (`_run_vendor_risk_inner`) — undecorated.
    The decorated `run_vendor_risk` requires SignalLayer env to be set;
    the CLI's purpose here is V0 calibration of the inner reasoning, not
    a governance smoke-test. To exercise the decorated path, drive it
    through the SPA Agent Runner or call run_vendor_risk directly with
    SL_* env set.
  - Output is the eval-contract dict as JSON, plus a `_meta` block with
    run timing.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agents.vendor_risk.agent import _run_vendor_risk_inner  # noqa: E402
from agents.vendor_risk.prompts import SYSTEM_ID_EXT, SYSTEM_ID_INT  # noqa: E402


def _resolve_case(fixture_name: str, system: str) -> dict:
    """Build a synthetic dataset row for the CLI invocation.

    Mirrors the schema of `agents/vendor_risk/eval/dataset-*.jsonl` rows
    so `_run_vendor_risk_inner` can consume it unchanged.
    """
    system_id = SYSTEM_ID_INT if system == "int" else SYSTEM_ID_EXT
    return {
        "id": f"cli-{fixture_name}-{system}",
        "label": f"CLI invocation against fixture {fixture_name} (system={system})",
        "system": system,
        "category": "cli",
        "input_vendor_package_ref": f"fixtures/{fixture_name}/",
        "expected_routing": system_id,
    }


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run vendor_risk against one fixture.")
    parser.add_argument("--fixture", required=True, help="Fixture directory name under agents/vendor_risk/eval/fixtures/, e.g. '01-clean-saas'.")
    parser.add_argument("--system", choices=["ext", "int"], default="ext", help="System path (ext = cloud LLM, int = internal-only). Default ext.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    case = _resolve_case(args.fixture, args.system)
    output = _run_vendor_risk_inner(case)
    print(json.dumps(output, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
