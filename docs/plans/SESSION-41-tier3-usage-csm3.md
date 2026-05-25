# SESSION-41 — Tier 3 sweep api/usage.py + CSM-3 (3 CISO Console surfaces)

## State at start
- A1 OpenAPI: **34/40 (85%)** — 3 Tier 3 routers left (usage, guide, + final Tier 3 candidate)
- A5 CISO Console: **6/10 (60%)** — 4 stubs left (evidence, analytics, policies, reports)
- RTF reject: ✅ closed in S40
- Compound 28a tally: **3/7** (still below 3/5 decision gate)

## Locked decisions (don't re-litigate)
Carry forward from S40: 24b amendment (per-coupling-tier batching), 38a (consumer-coupling grep gate), 27a (strict Pydantic v2 default), 26a (SSE/204/PlainText = op_id only), 24d (regen spec ONCE via export_openapi.py). Garak sidecar still out-of-scope V2.

## Plan
**STEP 0 — Compound 28a observation #8 (≤2 min)**
```bash
gh run list --commit=e40fccd --limit 5
```
CSM-2 commit `e40fccd` is pure `ciso-console/**` (zero engine code). If `deploy` fired → tally **4/8 (≥3/5)** → **decision gate trips**. Action: add `team-portal/**` + `ciso-console/**` to `.github/workflows/deploy.yml` `paths-ignore` block, but verify `deploy/build-zip.py` whitelist excludes them first (S19c). If `deploy` didn't fire (unlikely given S40 obs #7) → tally stays 3/7-ish; observation continues.

**STEP 1 — Tier 3 sweep api/usage.py (sequential, main, ~15 min)**
- Read consumers via `grep -rn "api/usage" --include="*.html" --include="*.tsx"`.
- Expected: usage_analytics.html or analytics-related SPAs.
- Mirror domain.usage_analytics shapes; strict Pydantic v2; `usage_*` op_id prefix.
- Verify no SSE/streaming routes; if any, document in module docstring per 26a.
- Import probe + 24c grep + spec regen once at end.
- Single Track A commit.
- Counter: **34 → 35/40**.

**STEP 2 — Spawn CSM-3 in background worktree (PARALLEL with STEP 1)**
Spawn 1 implementer subagent, `run_in_background: true`. Anticipate worktree isolation may not take — accept either outcome (net-new files in `ciso-console/src/pages/`).

Deliverable: 3 CISO Console surfaces (replace stubs):
1. **Evidence** (`src/pages/evidence/EvidencePage.tsx`)
   - V1 ancestor: `static/evidence.html`
   - Endpoints: GET /api/grc/evidence (list), GET /api/grc/evidence/{id} (detail), POST /api/grc/evidence/{id}/verify (CISO action)
   - Verify endpoint name in `api/evidence.py` (or wherever it lives) before wiring.
2. **Analytics** (`src/pages/analytics/AnalyticsPage.tsx`)
   - V1 ancestor: `static/analytics.html`
   - Endpoints: GET /api/analytics/trends (per S12B smoke path)
   - Pure read; charts as text/percent breakdowns (no chart-library dep — match team-portal Portfolio pattern).
3. **RTF Operator Deep View** (`src/pages/rtf/RtfOperatorDeepPage.tsx` — NEW route, add to Sidebar.tsx)
   - V1 ancestor: forensics portion of `static/right-to-forget.html`
   - Endpoints: GET /api/right-to-forget (list), GET /api/right-to-forget/{id} (detail with per-store SHA-256), GET /api/audit/verify?window=N (chain proof)
   - Operator-level forensics: per-store digest table + chain hash + verify-now button.
   - Distinct from CSM-1's RTF Approval Queue (that one is action-oriented; this is forensics-oriented).

Constraints: tsc --noEmit + vite build must pass; no commits; reuse client.ts + shared components.

**STEP 3 — Aggregate + commit**
After CSM-3 returns:
- Review diff; git add ciso-console/src/pages/evidence ciso-console/src/pages/analytics ciso-console/src/pages/rtf + Sidebar.tsx
- Commit Track B: "Feat: CSM-3 — CISO Console surfaces 7-9 (Evidence + Analytics + RTF Forensics)"
- Track A spec regen + commit if not yet done
- ARCHITECTURE.md S41 entry: counter → 35/40, A5 9/10, 28a obs #8 outcome
- Write SESSION-42 plan: guide.py sweep + CSM-4 (Policies + Reports + final A5 surface)
- Delete this plan
- Push

## Target end-state
| Item | Start | Target end |
|---|---|---|
| A1 OpenAPI sweep | 34/40 | 35/40 |
| A5 CISO Console | 6/10 | 9/10 |
| Compound 28a | 3/7 | 3/8 or 4/8 (decision-gate maybe) |
| Sessions to V2 cutover | ~4-5 | ~3-4 |

## Out of scope (S41)
- Tier 3 sweep beyond usage.py (guide → S42)
- CSM-4 surfaces (Policies, Reports → S42)
- A6/A7 role-aware redirect (S43)
- V1→V2 cutover, DNS rehearsal (S43-44)
- App Insights / P1v3 / staging slot
- Garak sidecar (cut from V2)
