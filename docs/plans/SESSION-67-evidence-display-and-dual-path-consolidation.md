# SESSION-67 — Evidence Drawer Display + `get_ai_system` Dual-Path Consolidation
# Date: 2026-05-31 (planned)
# Context cost: MEDIUM

## What this session builds
Close-out of S66's two named carry-forwards:

1. **Drawer Evidence display.** S66 added evidence add/list inside the Edit
   modal, but the standalone `AiSystemDrawer` def-list view does NOT yet
   surface newly-added rows. Operators editing → adding evidence → closing
   → reopening the drawer don't see what they just added until they re-open
   Edit. Surface the layered store's evidence in the drawer too.

2. **`get_ai_system` dual-path consolidation.** S66 deferred refactoring the
   bundled `api/grc.py::get_ai_system` handler (which still surfaces
   `mock_data.EVIDENCE` filtered) — the new endpoints read the canonical
   layered `evidence_for()` store, the old detail handler doesn't. Two read
   paths returning different evidence for the same system is a contract
   trap. Unify on `evidence_for()`.

## Pre-conditions
- [ ] Engine tip is `f496106` (S66) or later
- [ ] Both SPAs deployed at S66 tip (team-portal `index-DV_nv_8B.js`; ciso `index-bVhd18Tk.js`)
- [ ] `pytest tests/ -k evidence` baseline — capture pre-change pass count
- [ ] One demo system (e.g. `sys-payments-001`) has at least one evidence row
      visible via the OLD path (`/api/grc/ai-systems/sys-payments-001`)
      AND one row via the NEW path (`/api/grc/ai-systems/sys-payments-001/evidence`)
      so the consolidation can be tested against a real diff

## Files to create
NONE. S67 is a consolidation session — touches existing files only.

## Files to modify
1. `api/grc.py`
   - In `get_ai_system` (≈line 748): replace
     `evidence = [e for e in EVIDENCE if e["system_id"] == system_id]`
     with a call to `domain.repository.evidence_for(system_id)`, mapped to
     the existing detail-view evidence shape.
   - Verify `AiSystemDetailOut.evidence` field type accepts the canonical
     shape; adjust mapper if needed. The detail view currently relies on
     `EVIDENCE`'s dict shape (`system_id` key), not the Pydantic
     `Evidence` model's `ai_system_id`.
   - Run `pytest tests/ -k "grc or evidence"` after — expect the same pass
     count, with one assertion update if any test pinned mock_data row counts.

2. `team-portal/src/pages/ai-systems/AiSystemDrawer.tsx`
   - Surface the evidence list as a section in the drawer (chip group or
     compact table — match the existing drawer section style).
   - Fetch via `GET /grc/ai-systems/{id}/evidence` on drawer open.
   - Read-only here (add is in Edit modal).
   - Use the same `EvidenceRow` type from
     `AiSystemEditModal.tsx` (extract to `types.ts` if not already shared).

3. `team-portal/src/pages/ai-systems/types.ts` (if needed)
   - Move `EvidenceRow` + `EvidenceListResponse` types here from
     `AiSystemEditModal.tsx` so the drawer can import them without a
     circular path.

## Architectural constraints (from CLAUDE.md + DECISIONS)
- JSONL only via `_append_jsonl()` / `_read_jsonl()` pattern — already
  satisfied by S66's `append_evidence()` helper; no new I/O paths.
- `get_ai_system` consolidation MUST NOT regress the seed evidence rows.
  The 5 mock systems each have curated evidence chips operators expect to
  see; if `evidence_for()` returns fewer rows than `mock_data.EVIDENCE`
  for any seed system, fix `seed.py` to add the missing rows BEFORE
  flipping the handler.
- Drawer evidence read MUST go through the shared `apiGet` client (not raw
  `fetch`) — `[[raw-fetch-drifts-from-shared-client]]` applies here too.

## What NOT to build in this session
- Do NOT touch `assurance_model.py` consumers (G-5..G-9) — those are
  scoped for a dedicated session.
- Do NOT add Drawer evidence delete/edit affordances — append-only is the
  S66 decision, preserve it.
- Do NOT extend the curated 12-entry EvidenceType dropdown — operator
  feedback should drive that, not preemptive enrichment.
- Do NOT touch the ARM read stubs or Mermaid spillover.

## Verification
- `pytest tests/ -k "grc or evidence"` — same pass count as baseline.
- `python -c "from domain.repository import evidence_for; ..."` — count
  parity against `mock_data.EVIDENCE` filter for each of the 5 seed systems.
- Smoke: open Edit modal on a system → add evidence → close → open Drawer
  → confirm the new row appears in the drawer's evidence section.
- After SPA deploy: bundle-hash compare on `portal.aigovern.sandboxhub.co`
  + string-grep for new drawer evidence labels.
- `/verify` block in ARCHITECTURE.md — all PASS.

## Deploy
- Engine: CI auto-deploys on push (paths include `api/`, `domain/`).
- SPA: manual `swa deploy --env production` per `[[spa-deploy-is-manual-swa]]`.

## Open carry-forward NOT addressed by S67 (for S68+)
- **G-5..G-9** — V1→V2 carryover gaps on `assurance_model.py` endpoints
  (Summarize finding / Explain release / Summarize evidence / Draft report /
  Ask). 4-5 SPA surface adds; multi-session arc.
- **STEP 4 spillover** (Mermaid synthesis + per-tool eval rubric) — deferred
  since S60.
- **Remaining ARM read stubs** — `list_subscriptions`, `list_role_assignments`,
  `get_network_topology`. Property-bag tools downgraded (S63 decision).
- **F-021** — framework mapping data for `ai-sys-bae72e75`.
