"""Tool implementations for the vendor_risk agent (S82d V0).

Six tools, mirroring the Anthropic-format specs in `prompts.TOOL_SPECS`:
  - search_tprm_corpus(query, top_k)         retrieval over corpus/
  - lookup_subprocessor_risk(vendor_name)    subprocessor-risk-db.json
  - parse_vendor_document(doc_type)          fixture meta.json `documents`
  - check_regulatory_requirements(framework) corpus/regulations/<f>.md
  - compare_to_baseline(vendor_name)         prior assessment lookup
  - escalate_to_human(reason, residual_risk) SIDE-EFFECT state flip

All tools are SYNCHRONOUS (in-memory file reads). The agent's tool-use
loop dispatches them inline — there is no async work to gather. If S82e
adds expensive retrieval (e.g. real BM25 index build) we revisit.

Retrieval (V0): a token-overlap score against title + body excerpt.
Stand-in for rank-bm25; cheap, deterministic, requires no new dependency.
S82e candidate: swap to `rank-bm25` if calibration shows quality demands.

State (escalate_to_human): the agent dispatcher maintains a per-run state
dict and passes it as the `_state` kwarg via the dispatch closure. The
escalate tool flips state["escalation_triggered"] = True and appends the
escalation reason. This is the canonical pattern for SIDE-EFFECT tools
in tool-use loops — derive structured state from the tool call, not
from regexing the model's text output.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

CORPUS_DIR: Path = Path(__file__).resolve().parent / "corpus"
FIXTURES_DIR: Path = Path(__file__).resolve().parent / "eval" / "fixtures"

_MANIFEST: dict[str, Any] | None = None
_DOC_BODY_CACHE: dict[str, str] = {}
_SUBPROCESSOR_DB: dict[str, Any] | None = None
_INTERNAL_SYSTEMS: dict[str, Any] | None = None
_ASSESSMENTS_INDEX: dict[str, str] | None = None  # vendor_name (lowercased) → doc_id


def _load_manifest() -> dict[str, Any]:
    """Lazy-load the corpus manifest. Memoized for the process lifetime."""
    global _MANIFEST
    if _MANIFEST is None:
        _MANIFEST = json.loads((CORPUS_DIR / "manifest.json").read_text(encoding="utf-8"))
    return _MANIFEST


def _load_doc_body(doc_id: str) -> str:
    """Return the markdown body for a corpus doc_id (memoized)."""
    if doc_id in _DOC_BODY_CACHE:
        return _DOC_BODY_CACHE[doc_id]
    manifest = _load_manifest()
    entry = next((d for d in manifest["docs"] if d["doc_id"] == doc_id), None)
    if entry is None:
        body = ""
    else:
        path = CORPUS_DIR / entry["path"]
        body = path.read_text(encoding="utf-8") if path.exists() else ""
    _DOC_BODY_CACHE[doc_id] = body
    return body


def _load_subprocessor_db() -> dict[str, Any]:
    """Lazy-load the subprocessor risk database."""
    global _SUBPROCESSOR_DB
    if _SUBPROCESSOR_DB is None:
        _SUBPROCESSOR_DB = json.loads(
            (CORPUS_DIR / "subprocessor-risk-db.json").read_text(encoding="utf-8")
        )
    return _SUBPROCESSOR_DB


def _load_internal_systems() -> dict[str, Any]:
    """Lazy-load the internal-systems inventory."""
    global _INTERNAL_SYSTEMS
    if _INTERNAL_SYSTEMS is None:
        _INTERNAL_SYSTEMS = json.loads(
            (CORPUS_DIR / "internal-systems-inventory.json").read_text(encoding="utf-8")
        )
    return _INTERNAL_SYSTEMS


def _build_assessments_index() -> dict[str, str]:
    """Map lowercased vendor names to assessment doc_ids by scanning corpus."""
    global _ASSESSMENTS_INDEX
    if _ASSESSMENTS_INDEX is not None:
        return _ASSESSMENTS_INDEX
    manifest = _load_manifest()
    index: dict[str, str] = {}
    for entry in manifest["docs"]:
        if not entry["doc_id"].startswith("assess-"):
            continue
        body = _load_doc_body(entry["doc_id"])
        match = re.search(r"\*\*Vendor\*\*:\s*([^\n]+)", body)
        if match:
            full = match.group(1).strip()
            index[full.lower()] = entry["doc_id"]
            # Also index the leading name token (before any parenthetical
            # qualifier) so "QuantumLog" matches an entry written as
            # "QuantumLog (log aggregation SaaS)".
            head = full.split("(")[0].strip()
            if head:
                index[head.lower()] = entry["doc_id"]
    _ASSESSMENTS_INDEX = index
    return index


_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-]+")


def _tokenize(text: str) -> list[str]:
    return [w.lower() for w in _WORD_RE.findall(text)]


def _score_overlap(query_tokens: set[str], body: str, title: str) -> float:
    """Token-overlap retrieval score. Title hits weighted 3x body hits."""
    body_tokens = set(_tokenize(body))
    title_tokens = set(_tokenize(title))
    if not query_tokens:
        return 0.0
    body_overlap = len(query_tokens & body_tokens)
    title_overlap = len(query_tokens & title_tokens)
    raw = body_overlap + 3 * title_overlap
    return round(raw / max(1, len(query_tokens)), 4)


# --- Public tool callables ---------------------------------------------------


def search_tprm_corpus(tool_input: dict[str, Any]) -> dict[str, Any]:
    """Retrieve top-k corpus docs by token-overlap to the query."""
    query = (tool_input or {}).get("query", "").strip()
    top_k = max(1, min(int((tool_input or {}).get("top_k", 3) or 3), 10))
    if not query:
        return {"error": "query is required and must be non-empty.", "results": []}
    query_tokens = set(_tokenize(query))
    manifest = _load_manifest()
    scored: list[tuple[float, dict[str, Any]]] = []
    for entry in manifest["docs"]:
        body = _load_doc_body(entry["doc_id"])
        score = _score_overlap(query_tokens, body, entry["title"])
        if score > 0:
            snippet = body[:280].replace("\n", " ").strip()
            scored.append((score, {
                "doc_id": entry["doc_id"],
                "title": entry["title"],
                "snippet": snippet,
                "score": score,
            }))
    scored.sort(key=lambda x: -x[0])
    return {"query": query, "results": [r for _, r in scored[:top_k]]}


def lookup_subprocessor_risk(tool_input: dict[str, Any]) -> dict[str, Any]:
    """Return the structured risk record for a named subprocessor."""
    vendor_name = (tool_input or {}).get("vendor_name", "").strip()
    if not vendor_name:
        return {"error": "vendor_name is required."}
    db = _load_subprocessor_db()
    record = db["vendors"].get(vendor_name)
    if record is None:
        normalised = vendor_name.lower()
        for k, v in db["vendors"].items():
            if k.lower() == normalised:
                record = v
                break
    if record is None:
        return {"error": f"Subprocessor {vendor_name!r} not in database.", "vendor_name": vendor_name}
    return {"vendor_name": vendor_name, **record}


def parse_vendor_document(
    tool_input: dict[str, Any], *, fixture_meta: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Return one document body from the vendor's package.

    `fixture_meta` is the loaded meta.json for the current case, passed in
    by the agent dispatcher. When None (out-of-band tool calls), returns
    a structured error so the model can self-correct on the next turn.
    """
    doc_type = (tool_input or {}).get("doc_type", "").strip().lower()
    if not doc_type:
        return {"error": "doc_type is required."}
    if fixture_meta is None:
        return {
            "error": "No vendor package is bound to this run. parse_vendor_document is only available when invoked with a fixture.",
            "doc_type": doc_type,
        }
    documents = fixture_meta.get("documents") or {}
    if doc_type not in documents:
        return {
            "doc_type": doc_type,
            "body": "",
            "metadata": {"present": False, "available_doc_types": sorted(documents.keys())},
        }
    return {
        "doc_type": doc_type,
        "body": documents[doc_type],
        "metadata": {
            "present": True,
            "vendor_name": fixture_meta.get("vendor_name", ""),
            "category": fixture_meta.get("category", ""),
        },
    }


def check_regulatory_requirements(tool_input: dict[str, Any]) -> dict[str, Any]:
    """Return the clause text for a regulatory framework."""
    framework = (tool_input or {}).get("framework", "").strip().lower()
    if not framework:
        return {"error": "framework is required."}
    manifest = _load_manifest()
    match = next(
        (d for d in manifest["docs"] if framework in (d.get("frameworks") or [])),
        None,
    )
    if match is None:
        known = sorted({
            f for d in manifest["docs"] for f in (d.get("frameworks") or [])
        })
        return {"error": f"Unknown framework {framework!r}. Known: {known}."}
    return {
        "framework": framework,
        "doc_id": match["doc_id"],
        "title": match["title"],
        "clauses": _load_doc_body(match["doc_id"]),
    }


def compare_to_baseline(tool_input: dict[str, Any]) -> dict[str, Any]:
    """Return the prior assessment for this vendor, or {error: 'no prior'}."""
    vendor_name = (tool_input or {}).get("vendor_name", "").strip()
    if not vendor_name:
        return {"error": "vendor_name is required."}
    index = _build_assessments_index()
    doc_id = index.get(vendor_name.lower())
    if doc_id is None:
        return {"error": "no prior", "vendor_name": vendor_name}
    body = _load_doc_body(doc_id)
    tier_match = re.search(r"\*\*Risk tier\*\*:\s*(LOW|MEDIUM|HIGH|CRITICAL)", body)
    date_match = re.search(r"\*\*Date\*\*:\s*([0-9\-]+)", body)
    return {
        "vendor_name": vendor_name,
        "doc_id": doc_id,
        "prior_risk_tier": tier_match.group(1) if tier_match else "",
        "prior_assessed_date": date_match.group(1) if date_match else "",
        "body": body,
    }


def escalate_to_human(
    tool_input: dict[str, Any], *, state: dict[str, Any] | None = None
) -> dict[str, Any]:
    """SIDE EFFECT: flip state['escalation_triggered'] = True.

    `state` is the per-run mutable dict managed by the agent loop. When
    None (defensive), the tool still returns a well-formed escalation
    record but the agent will not detect it — callers MUST pass state.
    """
    reason = (tool_input or {}).get("reason", "").strip()
    residual_risk = (tool_input or {}).get("residual_risk", "").strip().upper()
    if not reason:
        return {"error": "reason is required."}
    if residual_risk not in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}:
        return {"error": f"residual_risk must be one of LOW|MEDIUM|HIGH|CRITICAL, got {residual_risk!r}."}
    if state is not None:
        state["escalation_triggered"] = True
        state.setdefault("escalation_reasons", []).append(reason)
        state["escalation_residual_risk"] = residual_risk
    ticket_id = f"HITL-{abs(hash((reason, residual_risk))) % 1_000_000:06d}"
    return {
        "escalated": True,
        "ticket_id": ticket_id,
        "reason": reason,
        "residual_risk": residual_risk,
    }


# --- Helpers used by the agent body ------------------------------------------


def load_fixture_meta(fixture_ref: str) -> dict[str, Any]:
    """Load a fixture's meta.json. Accepts both 'fixtures/<name>/' and '<name>'.

    Raises FileNotFoundError if the meta.json is missing — the agent body
    should catch and surface that as a structured error response rather
    than crashing the run.
    """
    name = fixture_ref.strip().rstrip("/")
    if name.startswith("fixtures/"):
        name = name[len("fixtures/"):]
    path = FIXTURES_DIR / name / "meta.json"
    if not path.exists():
        raise FileNotFoundError(f"Fixture meta not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def detect_internal_system_tokens(text: str) -> list[str]:
    """Return internal-system IDs referenced in `text`. Used by the agent
    to flag mis-routing (EXT path with internal tokens) — defense in depth.
    """
    systems = _load_internal_systems()["systems"]
    hits: list[str] = []
    upper = text.upper()
    for sys_entry in systems:
        if sys_entry["id"] in upper or sys_entry["name"].upper() in upper:
            hits.append(sys_entry["id"])
    return hits
