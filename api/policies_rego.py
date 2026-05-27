"""F-018: read-only listing of enforced .rego policy bundles.

The .rego files in policies/ are CODE — they ship via git → CI, not via
a CISO Console upload UI. F-018 (POC-RETROSPECTIVE.md) documented the
plan-vs-reality gap: docs/plans/AZURE-ARCHITECT-POC.md §P3 step 2
promised an upload flow that doesn't exist.

The compliance-audit answer is "operator can SEE what is enforced",
which this endpoint serves. The CISO Console renders this as a
read-only "Active enforced policies" panel adjacent to PoliciesPage
(which lists the mock control library, not .rego artifacts).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

router = APIRouter(prefix="/api/v1", tags=["policies-rego"])


# policies/ lives at the engine root, one level up from api/
_POLICIES_DIR = Path(__file__).resolve().parent.parent / "policies"


class RegoPolicyOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str  # filename without .rego
    filename: str
    size_bytes: int
    sha256: str
    package: str  # the `package <name>` line from the file, or "" if absent
    summary: str  # first non-empty comment line (best-effort doc)


class RegoListOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[RegoPolicyOut]
    count: int
    source_dir: str


def _parse_rego_header(text: str) -> tuple[str, str]:
    """Return (package_name, summary) from a .rego file body."""
    package = ""
    summary = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if not package and line.startswith("package "):
            package = line[len("package "):].strip()
            continue
        if not summary and line.startswith("#"):
            summary = line.lstrip("#").strip()
        if package and summary:
            break
    return package, summary


@router.get("/policies/rego", response_model=RegoListOut, operation_id="policies_rego_list")
def list_rego_policies() -> RegoListOut:
    """Enumerate active .rego bundles on disk. Read-only — never accepts uploads."""
    items: list[RegoPolicyOut] = []
    if _POLICIES_DIR.exists():
        for path in sorted(_POLICIES_DIR.glob("*.rego")):
            try:
                raw = path.read_bytes()
            except OSError:
                continue
            text = raw.decode("utf-8", errors="replace")
            package, summary = _parse_rego_header(text)
            items.append(RegoPolicyOut(
                name=path.stem,
                filename=path.name,
                size_bytes=len(raw),
                sha256=hashlib.sha256(raw).hexdigest(),
                package=package,
                summary=summary,
            ))
    return RegoListOut(
        items=items,
        count=len(items),
        source_dir=str(_POLICIES_DIR),
    )
