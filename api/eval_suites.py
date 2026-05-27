"""ADR-003: read-only catalog of available eval suites.

The CISO Console and Team Portal UIs render a per-system "Suite picker"
listing the multi-vendor catalog from ADR-003 §4.3. This endpoint surfaces
the catalog with each entry's actual status — `enabled` for whichever
vendor `EVAL_BACKEND` currently points at, `roadmap` for the rest.

NO suite-uploads or vendor-config writes. Same posture as F-018 .rego:
vendors ship via code changes (ADR-003 §7 rollout), never via the UI.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from providers.config import EvalBackendChoice, ProviderSettings

router = APIRouter(prefix="/api", tags=["eval-suites"])


# Static catalog mirroring ADR-003 §4.3. Versions for inactive vendors are
# `null` because nothing is installed; once the backend module lands in
# the deploy, the vendor backend itself reports its installed version
# (e.g. providers.backends.deepeval_evaluator._read_deepeval_version()).
_CATALOG: list[dict] = [
    {
        "vendor": "deepeval",
        "label": "DeepEval",
        "description": "5-metric suite: answer_relevancy, toxicity, hallucination, faithfulness, pii_leakage.",
        "integration": "native-python",
        "adr_ref": "ADR-003 §4.3",
        "status": "roadmap",  # overridden below if active
    },
    {
        "vendor": "ragas",
        "label": "Ragas",
        "description": "RAG-specific metrics: faithfulness, answer_relevancy, context_precision, context_recall.",
        "integration": "native-python",
        "adr_ref": "ADR-003 §7 Step 2",
        "status": "roadmap",
    },
    {
        "vendor": "promptfoo",
        "label": "Promptfoo",
        "description": "Assertion-based eval runner (Node CLI). Subprocess shell-out + JSON parse.",
        "integration": "node-cli-subprocess",
        "adr_ref": "ADR-003 §7 Step 4",
        "status": "roadmap",
    },
    {
        "vendor": "openai_evals",
        "label": "OpenAI evals",
        "description": "Registry of YAML evals (github.com/openai/evals). Container App sidecar (heavy deps).",
        "integration": "sidecar-http",
        "adr_ref": "ADR-003 §7 Step 5",
        "status": "roadmap",
    },
]


class SuiteEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    vendor: str
    label: str
    description: str
    integration: str
    adr_ref: str
    status: str  # "enabled" | "roadmap"
    vendor_version: str = ""  # populated only when status=="enabled"


class SuiteCatalogOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[SuiteEntry]
    active_vendor: str
    adr: str


def _build_catalog() -> SuiteCatalogOut:
    settings = ProviderSettings()
    active = settings.eval_backend.value if isinstance(settings.eval_backend, EvalBackendChoice) else str(settings.eval_backend)

    # Best-effort version probe — only for the active backend so we don't
    # force-import vendor SDKs we don't have installed.
    active_version = ""
    if active == "deepeval":
        try:
            from providers.backends.deepeval_evaluator import _read_deepeval_version
            active_version = _read_deepeval_version()
        except Exception:  # noqa: BLE001
            active_version = "unknown"

    items: list[SuiteEntry] = []
    for entry in _CATALOG:
        is_active = entry["vendor"] == active
        items.append(SuiteEntry(
            vendor=entry["vendor"],
            label=entry["label"],
            description=entry["description"],
            integration=entry["integration"],
            adr_ref=entry["adr_ref"],
            status="enabled" if is_active else "roadmap",
            vendor_version=active_version if is_active else "",
        ))

    return SuiteCatalogOut(
        items=items,
        active_vendor=active,
        adr="docs/adr/ADR-003-multi-vendor-evals.md",
    )


@router.get("/evals/suites", response_model=SuiteCatalogOut, operation_id="eval_suites_list")
def list_suites() -> SuiteCatalogOut:
    """Return the multi-vendor eval suite catalog.

    Each entry includes `status` of `enabled` (currently wired as the active
    backend) or `roadmap` (declared in ADR-003 but not yet implemented).
    """
    return _build_catalog()
