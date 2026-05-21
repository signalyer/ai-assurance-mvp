# SESSION 06 — Framework Coverage Matrix
# Date: 2026-05-21 (planned)
# Context cost: HIGH (10 new files, 6 modified, 0 deleted; plus framework_refs backfill across ~30 items)
# Status: PENDING APPROVAL

## What this session will build
The 6-framework coverage matrix (NIST AI RMF + NIST AI 600-1 + OWASP LLM Top 10 + OWASP Agentic AI Top 10 + EU AI Act + ISO 42001 + SR 11-7 + FFIEC) with a US-FinServ overlay. Matrix UI, drill-down to evidence, PDF export Packs (NIST / OWASP / EU AI Act), and full framework_refs backfill.

## User decisions (locked 2026-05-21)
1. **Framework defs:** YAML only for the new ones (EU AI Act, ISO 42001, SR 11-7, FFIEC + US-FinServ overlay). Existing 4 stay in Python.
2. **PDF Packs:** Extend `pdf_report.py` with 3 new functions (reuse reportlab setup + evidence-table renderer).
3. **Backfill:** Full backfill on all 30 items (15 controls + 6 scorers + 6 gates + 3 policies).
4. **UI:** New `static/frameworks.html` matrix page + extend `static/ai-systems.html` with a Frameworks tab.

## Pre-conditions (ALL MET)
- [x] Sessions 01-05 complete · 52 acceptance tests pass · provider abstraction live
- [x] `domain/framework_coverage.py` exists with 4 hardcoded framework catalogs and `item_coverage()` / `framework_overview()` engines
- [x] `domain/controls.py` has `framework_mappings` field on each control
- [x] `pdf_report.py` exists; reportlab pinned

## Files to CREATE (10)
1. **`frameworks/__init__.py`** — Package marker
2. **`frameworks/loader.py`** — YAML loader; validates schema, returns `list[FrameworkItem]`; fails closed on schema violation
3. **`frameworks/eu_ai_act.yaml`** — EU AI Act high-risk obligations (Articles 9-15: risk management, data governance, technical documentation, record-keeping, transparency, human oversight, accuracy/robustness)
4. **`frameworks/iso_42001.yaml`** — ISO/IEC 42001:2023 clauses (4-10: context, leadership, planning, support, operation, evaluation, improvement)
5. **`frameworks/sr_11_7.yaml`** — Fed SR 11-7 model risk management (development, implementation, use, validation, governance)
6. **`frameworks/ffiec.yaml`** — FFIEC IT Examination Handbook AI/ML supplements (model governance, third-party risk, change management)
7. **`frameworks/us_finserv_overlay.yaml`** — US-FinServ posture overlay mapping additional requirements over base frameworks
8. **`api/frameworks.py`** — 4 endpoints: GET /api/frameworks/matrix, GET /api/frameworks/{framework}, GET /api/frameworks/{framework}/system/{id}, POST /api/frameworks/{framework}/export
9. **`static/frameworks.html`** — Console-style matrix page (systems × frameworks); cell color-coded by coverage %; click → drill modal with evidence list + SHA-256 hashes
10. **`tests/test_session_06_framework_coverage.py`** — 14 acceptance tests (catalog load, coverage compute, matrix render, drill-down, PDF generation, backfill verification)

## Files to MODIFY (6)
1. **`domain/framework_coverage.py`** — Add YAML catalog loading at module init (merge with existing 4 hardcoded catalogs); add `framework_matrix(system_ids: list[str]) -> dict` returning the matrix data structure; preserve all existing public APIs unchanged
2. **`domain/controls.py`** — Backfill `framework_mappings` on all 15 controls to cover all 6 framework families + US-FinServ overlay (where applicable). No new controls, only annotations.
3. **`domain/release_gate_engine.py`** — Backfill `framework_refs` on all 6 gates; annotate which framework clauses each gate enforces.
4. **`domain/assessment_engine.py`** — Backfill `framework_refs` on the 6 scorers; annotate which framework clauses each scorer evaluates.
5. **`pdf_report.py`** — Add 3 new functions: `generate_nist_pack(system_id)`, `generate_owasp_pack(system_id)`, `generate_eu_ai_act_pack(system_id)`. Each renders evidence with inline framework citations (clause + finding hash). Reuses existing reportlab setup.
6. **`dashboard.py`** — Mount `api/frameworks.py` router; serve `static/frameworks.html` at `/frameworks`.
7. **`static/ai-systems.html`** — Add "Frameworks" tab to AI System detail showing per-system coverage across all 6 frameworks (read-only). (7th MODIFY — sprint exceeds the typical 6-file cap but each change is small; flagging for visibility.)

## Files to DELETE (0)

## Architectural Constraints (NON-NEGOTIABLE)
1. **Coverage is computed, never hardcoded:** Every cell in the matrix is derived from controls + findings + evidence + release gates. No hardcoded percentages anywhere.
2. **YAML fail-closed:** Unknown framework slug, malformed YAML, missing required fields → raise at module load with line number + path. Never silently skip a framework file.
3. **Framework_refs are auditable:** Each `framework_ref` annotation on a control/gate/scorer/policy includes `framework` + `clause` (text) + optional `subclause`. No "see also" prose.
4. **Backward compat:** All existing API endpoints and UI pages unchanged. No public signatures on `domain/framework_coverage.py` change.
5. **PDF Packs render real evidence:** Each Pack PDF includes SHA-256 hashes for every evidence item cited. No mock data in PDFs.
6. **US-FinServ overlay is additive:** Overlay applies ONLY when system's posture = `us-finserv`; never replaces base framework requirements, only adds to them.

## Two most critical architectural risks
1. **Backfill churn:** Annotating 30 items with framework_refs across 6 frameworks is mechanical but error-prone. Mistakes will misrepresent coverage. Mitigation: ground-truth seed file (`tests/fixtures/expected_coverage.json`) with hand-verified coverage % for each (framework, system) pair; acceptance tests assert matrix matches ground truth.
2. **YAML schema drift:** As new frameworks get added (Phase 2), YAML schema will need to evolve. Mitigation: Pydantic schema in `frameworks/loader.py` validates at load time; schema version field in each YAML; loader rejects unknown schema versions.

## Will NOT build in this session
- ❌ Right-to-forget for framework data (Session 08)
- ❌ Custom framework authoring UI (admin can write YAML files directly; UI defer to Phase 2)
- ❌ Framework comparison view (side-by-side delta between frameworks)
- ❌ Versioning of framework definitions (assume YAML files are git-versioned, no in-app history)
- ❌ Translation of clauses (English only)
- ❌ Integration with external framework feeds (OSCAL, etc.) — defer to Phase 2
- ❌ More than 3 PDF Packs (NIST/OWASP/EU AI Act). ISO/SR 11-7/FFIEC Packs in Session 11.

## Acceptance Criteria — 14 tests

### Group 1: Framework loader (3 tests)
```bash
# Test 1: All 5 YAML files load cleanly
python -c "from frameworks.loader import load_all_frameworks; items = load_all_frameworks(); print(f'OK loaded {len(items)} items across 5 files')"

# Test 2: Malformed YAML fails closed
python -c "
import tempfile, os
from frameworks.loader import load_yaml_framework
bad = tempfile.NamedTemporaryFile('w', suffix='.yaml', delete=False); bad.write('not: valid: yaml: ::'); bad.close()
try: load_yaml_framework(bad.name)
except Exception as e: print(f'OK fail-closed: {type(e).__name__}')
finally: os.unlink(bad.name)
"

# Test 3: Unknown framework slug rejected
python -c "
from frameworks.loader import load_yaml_framework
import tempfile, os
bad = tempfile.NamedTemporaryFile('w', suffix='.yaml', delete=False)
bad.write('framework: unknown_framework_xyz\\nitems: []\\n'); bad.close()
try: load_yaml_framework(bad.name)
except ValueError as e: print(f'OK unknown framework rejected: {e}')
finally: os.unlink(bad.name)
"
```

### Group 2: Catalog merge + coverage (4 tests)
```bash
# Test 4: framework_catalog returns merged Python + YAML items
python -c "
from domain.framework_coverage import framework_catalog
from domain.models import FrameworkName
items_eu = framework_catalog(FrameworkName.EU_AI_ACT.value)
assert len(items_eu) >= 5, f'expected 5+ EU AI Act items, got {len(items_eu)}'
print(f'OK EU AI Act catalog: {len(items_eu)} items')
"

# Test 5: item_coverage computes from controls (no hardcoded %)
python -c "
from domain.framework_coverage import item_coverage
from domain.models import FrameworkName
cov = item_coverage(FrameworkName.EU_AI_ACT.value, 'Art.10-data-governance', scope='ai-sys-001')
assert 0 <= cov.coverage_pct <= 100
assert cov.controls_total > 0
print(f'OK Art.10 coverage: {cov.coverage_pct}% across {cov.controls_total} controls')
"

# Test 6: framework_matrix returns 6x6 grid
python -c "
from domain.framework_coverage import framework_matrix
matrix = framework_matrix(['ai-sys-001','ai-sys-002','ai-sys-003','ai-sys-004','ai-sys-005','ai-sys-006'])
assert len(matrix['rows']) == 6 and len(matrix['frameworks']) == 6
print(f'OK matrix: {len(matrix[\"rows\"])} systems x {len(matrix[\"frameworks\"])} frameworks')
"

# Test 7: US-FinServ overlay applies only on posture=us-finserv
python -c "
from domain.framework_coverage import item_coverage
from domain.models import FrameworkName
cov_fs = item_coverage(FrameworkName.EU_AI_ACT.value, 'Art.9-risk-management', scope='ai-sys-finserv-001')
cov_base = item_coverage(FrameworkName.EU_AI_ACT.value, 'Art.9-risk-management', scope='ai-sys-001')
assert cov_fs.overlay_items_total >= cov_base.overlay_items_total
print('OK overlay additive only on us-finserv posture')
"
```

### Group 3: API endpoints (3 tests)
```bash
# Test 8: matrix endpoint returns 200 + 6x6 grid
python -c "
from fastapi.testclient import TestClient
from dashboard import app
c = TestClient(app)
r = c.get('/api/frameworks/matrix', headers={'X-Demo-Role':'demo-ciso'})
assert r.status_code == 200
data = r.json()
assert len(data['rows']) >= 1
print(f'OK /api/frameworks/matrix: {len(data[\"rows\"])} systems')
"

# Test 9: drill-down endpoint returns evidence with SHA-256
python -c "
from fastapi.testclient import TestClient
from dashboard import app
c = TestClient(app)
r = c.get('/api/frameworks/eu-ai-act/system/ai-sys-001', headers={'X-Demo-Role':'demo-ciso'})
assert r.status_code == 200
data = r.json()
assert all('evidence_hash' in item for item in data['items'] if item.get('evidence'))
print('OK drill-down returns SHA-256 evidence hashes')
"

# Test 10: PDF export endpoint returns valid PDF bytes
python -c "
from fastapi.testclient import TestClient
from dashboard import app
c = TestClient(app)
r = c.post('/api/frameworks/nist-ai-rmf/export', json={'system_id':'ai-sys-001'}, headers={'X-Demo-Role':'demo-ciso'})
assert r.status_code == 200
assert r.content[:4] == b'%PDF'
print(f'OK NIST Pack PDF: {len(r.content)} bytes')
"
```

### Group 4: Backfill verification (2 tests)
```bash
# Test 11: All 15 controls have framework_mappings for all 6 frameworks
python -c "
from domain.controls import CONTROLS
from domain.models import FrameworkName
target_frameworks = {f.value for f in FrameworkName}
gaps = []
for c in CONTROLS:
    mapped = {m.framework for m in c.framework_mappings}
    missing = target_frameworks - mapped
    if missing: gaps.append((c.id, missing))
assert not gaps, f'gaps: {gaps[:3]}'
print(f'OK all {len(CONTROLS)} controls mapped to all {len(target_frameworks)} frameworks')
"

# Test 12: All 6 release gates have framework_refs
python -c "
from domain.release_gate_engine import GATE_DEFS
unmapped = [g for g in GATE_DEFS if not getattr(g, 'framework_refs', None)]
assert not unmapped, f'unmapped gates: {[g.id for g in unmapped]}'
print(f'OK all {len(GATE_DEFS)} gates have framework_refs')
"
```

### Group 5: UI smoke (2 tests)
```bash
# Test 13: /frameworks page serves
python -c "
from fastapi.testclient import TestClient
from dashboard import app
c = TestClient(app)
r = c.get('/frameworks', headers={'X-Demo-Role':'demo-ciso'})
assert r.status_code == 200
assert b'<table' in r.content or b'<div class=\"matrix' in r.content
print('OK /frameworks matrix page renders')
"

# Test 14: ai-systems.html Frameworks tab renders
python -c "
from fastapi.testclient import TestClient
from dashboard import app
c = TestClient(app)
r = c.get('/ai-systems', headers={'X-Demo-Role':'demo-ciso'})
assert r.status_code == 200
assert b'data-tab=\"frameworks\"' in r.content or b'id=\"frameworks-tab\"' in r.content
print('OK Frameworks tab on ai-systems page')
"
```

## Execution plan (sub-agent parallelization)
Three sub-agents in **one message**:
- **Agent A (implementer):** Build `frameworks/` package — loader + 5 YAML files. Schema validation via Pydantic. Loader returns merged catalog when called by `framework_coverage.py`.
- **Agent B (implementer):** Backfill — annotate `framework_mappings` on all 15 controls + `framework_refs` on 6 gates + 6 scorers + 3 policies. Update `domain/framework_coverage.py` to merge YAML catalogs + add `framework_matrix()` function.
- **Agent C (implementer):** Build API + UI + PDF — `api/frameworks.py` (4 endpoints), `static/frameworks.html` (matrix page), Frameworks tab on `ai-systems.html`, 3 new PDF functions in `pdf_report.py`. Mount router in `dashboard.py`.

Main thread: run all 14 new + 52 regression tests + spawn code-reviewer + security-reviewer in parallel.

## Decision Log entries to add
- Framework definitions: YAML for new frameworks vs Python for existing (hybrid model)
- PDF Pack strategy: extend pdf_report.py vs new module (chose extend)
- Backfill scope: full annotation across 30 items vs critical-path only (chose full)
- Matrix UI: dedicated page + per-system tab (both per Day 6 spec)

## End-of-Session Actions
1. All 14 new + 52 regression tests pass
2. Code-reviewer + security-reviewer in parallel
3. ARCHITECTURE.md updated · DECISIONS.md appended · SESSION-07 plan written · HANDOFF.md updated
4. Two commits: feat (matrix + YAML + backfill) + docs
