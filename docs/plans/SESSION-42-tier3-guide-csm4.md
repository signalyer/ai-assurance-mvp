# SESSION-42 — Tier 3 sweep api/guide.py + CSM-4 (Policies + Reports → A5 10/10)

## State at start
- A1 OpenAPI: **35/40 (88%)** — `api/guide.py` is the last *known* Tier 3 sweep; 4 unspecified routers remain (suspected Tier 1).
- A5 CISO Console: **9/10 (90%)** — 2 stubs left (Policies, Reports). RTF Forensics bonus surface already shipped S41.
- Compound 28a: **CLOSED** (action landed S41 — `paths-ignore` extended to `team-portal/**` + `ciso-console/**`).
- 27a polymorphic-payload sub-rule: codified S41; apply to any remaining Tier 3 with variable-keyed dicts.

## Locked decisions (don't re-litigate)
24b amendment (per-coupling-tier batching), 38a (consumer-coupling grep gate), 27a + polymorphic sub-rule, 26a (SSE/204/PlainText = op_id only), 24d (regen spec ONCE), Garak sidecar out-of-scope V2.

## Plan
**STEP 0 — Validate 28a action (≤1 min)**
```bash
gh run list --commit=<any-S42-SPA-only-commit> --limit 5
```
After CSM-4 lands, confirm `deploy` did NOT fire for the SPA-only commit. If it did, the `paths-ignore` fix is broken — bisect and debug. Otherwise close the loop in ARCHITECTURE.md: "28a action validated — paths-ignore working as designed."

**STEP 1 — Tier 3 sweep api/guide.py (sequential, main, ~15 min)**
- 38a coupling grep: `grep -rn "api/guide" --include="*.html" --include="*.tsx"`. Expected hits: static/governance-guide.html or similar; possibly the team-portal SDK Quickstart page (S17).
- Read domain.governance_guide for shapes.
- If responses are bounded dataclasses → mirror with strict Pydantic per 27a.
- If responses are polymorphic (e.g. guide steps with variable payload) → apply S41 polymorphic sub-rule.
- Operation_ids `guide_*`.
- Single Track A commit + spec regen ONCE.
- Counter: **35 → 36/40**.

**STEP 2 — Spawn CSM-4 in background (PARALLEL with STEP 1)**
Spawn implementer subagent, `run_in_background: true`, no worktree (pattern accepted post-CSM-1/2/3).

Deliverable: 2 surfaces (final A5 closure):
1. **Policies** (`src/pages/policies/PoliciesPage.tsx`)
   - V1 ancestor: `static/policies.html`
   - Endpoints: discover via `grep "prefix.*polic" api/*.py`. Likely GET /api/policies (list) + GET /api/policies/{id} (detail). Check for OPA policy text rendering needs.
   - CISO-specific: edit-mode disabled (read-only); show policy text + last-eval results + bound systems.
2. **Reports** (`src/pages/reports/ReportsPage.tsx`)
   - V1 ancestor: `static/reports.html`
   - Endpoints: discover via `grep "prefix.*report" api/*.py`. Likely GET /api/reports (list) + POST /api/reports/{id}/generate (PDF export).
   - CISO-specific: generate + download buttons enabled.

Constraints: tsc --noEmit + vite build PASS; no commits; reuse client.ts + shared components.

**STEP 3 — Aggregate + commit**
After CSM-4 returns:
- Commit Track B: "Feat: CSM-4 — CISO Console final surfaces (Policies + Reports) → A5 10/10 ✅"
- ARCHITECTURE.md S42 entry: counter → 36/40, A5 **10/10 ✅**, 28a action validation
- Write SESSION-43 plan: 4 unspecified routers (likely Tier 1 batch via parallel implementers — pre-flight 38a grep on all 4 to confirm tier) + start A6/A7 role-aware redirect
- Delete this plan
- Push

## Target end-state
| Item | Start | Target end |
|---|---|---|
| A1 OpenAPI sweep | 35/40 | 36/40 |
| A5 CISO Console | 9/10 | **10/10 ✅** |
| Compound 28a | CLOSED | validated |
| Sessions to V2 cutover | ~3-4 | ~2-3 |

## After S42
- **S43:** Tier 1 batch (4 unspecified routers, parallel implementers) + START A6/A7 role-aware login redirect → A1 likely **40/40 ✅** + A6/A7 in-flight
- **S44 (CUT-1):** Finish A6/A7 + smoke_portal.ps1 + smoke_gov.ps1
- **S45 (CUT-2):** A12 V1→V2 302 + A13 DNS rehearsal + rollback verification

V2 acceptance closes in ~3 more sessions at current cadence.

## Out of scope (S42)
- Tier 1 batch sweep of the 4 unspecified routers (S43)
- A6/A7 role-aware redirect work (S43+)
- A12/A13 cutover (S44-45)
- App Insights / P1v3 / staging slot (parallel infra track)
- Garak sidecar (cut from V2)
