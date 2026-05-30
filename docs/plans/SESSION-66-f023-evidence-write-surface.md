# SESSION 66 — F-023 evidence write surface (intake + Edit modal)

**Date:** 2026-05-30
**Branch:** main
**Tip going in:** `b675568` (S65 close)
**Tip going out:** `f496106`
**Scope:** Close G-4 (F-023) from S64's UI-promise audit, picking option B per user direction — proper Evidence records (not the minimal-string option A). Discovery during investigation expanded the scope: registration Step 5's 8 evidence URL fields were also silently dropped (not just absent from Edit modal). Fixed both halves in one cut.

## What changed

| File | Change |
|---|---|
| [domain/repository.py](../../domain/repository.py) | New `EVIDENCE_FILE = data/evidence.jsonl` + `append_evidence(Evidence)` helper. `evidence_for(system_id)` now reads the new file alongside seed/overlay/demo layers, so freshly-added rows flow into the framework completeness rollup without further wiring. |
| [api/grc.py](../../api/grc.py) | New `EvidenceRowOut`, `EvidenceListOut`, `AddEvidencePayload` models + `GET` and `POST /grc/ai-systems/{id}/evidence` endpoints. Reads via the canonical `domain.repository.evidence_for` (the layered store), distinct from the bundled `get_ai_system` detail endpoint which surfaces `mock_data.EVIDENCE` only. Newest-first sort for the modal UX. Unknown `evidence_type` returns 400 with the valid enum list. |
| [api/intake.py](../../api/intake.py) | After successful AISystem write, iterate the 8 Step 5 URL fields and materialize each present one as a typed Evidence row via `append_evidence()`. Wrapped in try/except — failure is non-fatal (intake succeeded; missing evidence becomes a ticked-down completeness %, not a 500 or a draft). |
| [team-portal/src/pages/ai-systems/AiSystemEditModal.tsx](../../team-portal/src/pages/ai-systems/AiSystemEditModal.tsx) | New `EvidencePanel` section between the editable-fields table and Change Reason. Lists existing evidence + inline add form (curated 12-entry EvidenceType dropdown, URI input, optional summary, Add button). Independent submit cycle from field-edit — adding evidence does NOT enter the revision queue. `closeEdit()` resets evidence-section state to prevent cross-mount leakage (same class as S64 G-2's banner-leak fix). `loadEvidence()` called from `loadForEdit()` so the section is populated before render. |

## URL field → EvidenceType mapping

| Intake field | EvidenceType |
|---|---|
| `architecture_diagram_url` | `ARCHITECTURE_DIAGRAM` |
| `iac_url` | `TERRAFORM_SNAPSHOT` |
| `iam_policy_url` | `IAM_POLICY_SNAPSHOT` |
| `bedrock_config_url` | `BEDROCK_CONFIG` |
| `rag_pipeline_config_url` | `RAG_CONFIG` |
| `eval_report_url` | `EVAL_RUN` |
| `logging_config_url` | `AUDIT_LOG` |
| `security_review_url` | `PEN_TEST` |

All 8 map to existing enum members — no `domain/models.py` change needed.

## Decisions locked

- **Layered store as canonical read path** for the new endpoint, not `mock_data.EVIDENCE`. The bundled `get_ai_system` handler stays unchanged to avoid disturbing the existing drawer + framework matrix wiring; the new endpoint is a clean read/write pair. Dual paths are a known tech-debt but lower-risk than refactoring `get_ai_system` in the same session.
- **Append-only at API level.** No update/delete endpoints. Mirrors the immutable audit-data semantics already implicit in the seed/overlay design. Operator-driven deletion is a separate concern (right-to-forget cascade already exists for that).
- **`hash` is optional + caller-provided.** Engine does NOT fetch external URIs at write time to compute hashes — that would create an outbound dependency for an API that should be sub-second. Future work could add a server-side hash-on-fetch job, but it's out of scope.
- **Curated 12-entry dropdown in UI, full enum in engine.** Engine accepts all 30+ EvidenceType members (400 on unknown); UI surfaces only the 12 most operator-relevant. Reduces dropdown noise without limiting power-user via API.
- **Investigation discovered scope expansion.** Original F-023 triage flagged the Edit modal gap only. Reading `api/intake.py` revealed the 8 URL fields are never persisted at registration either. Both halves are the same bug; fixing them together is half the cost of fixing them separately. Reinforces the "trace the full data path before scoping a fix" pattern.

## Verification

| Surface | Check | Result |
|---|---|---|
| Engine | SHA round-trip `f496106` matches commit | ✅ |
| Engine | `POST /api/grc/ai-systems/{id}/evidence` registered | ✅ 401 unauth (auth-gated; pre-deploy Python smoke proved route exists) |
| Engine | Round-trip write/read smoke (`append_evidence` → `evidence_for`) | ✅ probe row written, read back, cleaned |
| Portal SPA | Bundle hash matches local | ✅ both `index-DV_nv_8B.js` |
| Portal SPA | F-023 markers in live bundle | ✅ `Add Evidence`, `Architecture Diagram` (×2), `ARCHITECTURE_DIAGRAM` (×3), endpoint URL template (×2) |

## Carry-forward to S67

- **Edge cases from S64 audit** (started in S66 close): 4 `assurance_model.py` summarize/explain POSTs with no SPA consumers. Investigation in progress at session end — see findings below or in the S67 plan.
- **Drawer Evidence display.** Edit modal lists evidence inline, but the AiSystemDrawer's def-list view (the non-edit drawer) does NOT yet surface the new evidence rows. Operators editing → adding → closing → reopening drawer won't see what they just added until they re-open Edit. Worth a small follow-up.
- **`get_ai_system` evidence dual-path consolidation.** Currently `get_ai_system` returns `mock_data.EVIDENCE` filtered; the new list endpoint returns the layered store. Worth a careful unification once it can be tested against the full demo flow.
- **STEP 4 spillover** (Mermaid + per-tool eval rubric) — deferred since S60.
- **Remaining ARM read stubs** — `list_subscriptions`, `list_role_assignments`, `get_network_topology`.

## Outstanding questions

- Should the 4 `assurance_model.py` POSTs become G-5..G-8, or are they intentional scaffolding for a not-yet-built "explain this finding" / "explain this release" affordance? See S67 plan once edge-case investigation completes.
