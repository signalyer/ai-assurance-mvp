# SESSION 65 — SPA deploy + G-1 CISO Revisions Queue

**Date:** 2026-05-30
**Branch:** main
**Tip going in:** `38f9f61` (S64 close)
**Tip going out:** `b675568`
**Scope:** Two halves. (1) Ship S64's G-3 + G-2 fixes to portal — manual `swa deploy` is the canonical pattern, S64's "merged" claim was hollow until that ran. (2) Build G-1 (CISO Console Revisions Queue) end-to-end: engine helper + endpoint + new SPA surface + sidebar nav + live deploy. Closes the largest gap from S64's UI-promise audit.

## What changed

### Half 1 — Ship S64 SPA live

| File | Change |
|---|---|
| (deploy only — no source change) | `swa deploy ./dist --env production` against `swa-aigovern-portal-dev`. Token via `az staticwebapp secrets list`. Pattern per [SESSION-45](SESSION-45-v2-live-cutover.md:40); locked-manual per S48. |

### Half 2 — G-1 Revisions Queue

| File | Change |
|---|---|
| [domain/ai_system_edit.py](../../domain/ai_system_edit.py) | New `pending_revisions_across_systems()` — walks the revision store once, returns every `approval_status=='pending'` revision newest-first. Avoids SPA's N+1 alternative (fan `/edit-info` across every system to discover pending state). |
| [api/ai_system_edit.py](../../api/ai_system_edit.py) | New `GET /api/ai-systems/revisions/pending` returning `RevisionsListOut`. Declared **before** `/revisions/{revision_id}` so FastAPI's greedy path param doesn't shadow it (smoke pre-deploy confirmed route order). |
| [ciso-console/src/pages/revisions/types.ts](../../ciso-console/src/pages/revisions/types.ts) | New. Type-only; mirrors engine `RevisionOut` (`extra="allow"` → keep `[key: string]: unknown` on `Revision`). |
| [ciso-console/src/pages/revisions/RevisionsQueuePage.tsx](../../ciso-console/src/pages/revisions/RevisionsQueuePage.tsx) | New. Pattern mirrors `RtfApprovalQueuePage` — KPI row by tier (critical/material/soft), pending table, decide modal with full before/after diff, required_approver_roles surfaced, role override input. Approve / Reject for every row; Override button only renders for critical tier. |
| [ciso-console/src/app.tsx](../../ciso-console/src/app.tsx) | `/revisions` route. |
| [ciso-console/src/shared/components/Sidebar.tsx](../../ciso-console/src/shared/components/Sidebar.tsx) | Nav item between Audit Chain and RTF Approvals. |

## Decisions locked

- **SPA manual `swa deploy` is the standard cadence**, not a special promotion. Free SKU has no GH Actions integration; locked in S48. Build → token via `az` → `swa deploy --env production` → verify by bundle-hash + string-grep against the live origin. Roughly 30s once dist is warm. Should be folded into every session that touches SPA source.
- **Aggregate endpoint over client-side fan-out** for pending-revisions list. The repo's `pending_revision()` was per-system; adding `pending_revisions_across_systems()` is ~10 lines and avoids accumulated client complexity. Consistent with how `/right-to-forget?status=pending` powers the RTF queue.
- **FastAPI path order is checked pre-deploy via Python smoke** (`[r.path for r in router.routes]`), not discovered in prod. Per [[auth-shadows-404]] from S57: shadowed routes return 401 from auth middleware running before route matching, which looks identical to "endpoint missing" in curl. The smoke print is the cheaper check.
- **Override button conditional on critical tier**. Override semantics ("bypass standard approval requirement") only apply when there IS a standard requirement — soft/material revisions don't gate-block, so override is meaningless there. UX cleaner without a dead button.

## Verification

| Surface | Check | Result |
|---|---|---|
| Engine | SHA round-trip `b675568` matches commit | ✅ |
| Engine | `GET /api/ai-systems/revisions/pending` (curl, unauth) | ✅ `401` — endpoint registered, auth-gated, smoke pre-deploy proved route order |
| Team Portal SPA (S64 ship) | Bundle hash matches local; `credentials:"include"` (3×), `Revoke key`, `Issue Fresh Key` strings present | ✅ |
| CISO Console SPA | Bundle hash matches local; `Revisions Queue`, `AI System Revisions`, `Confirm Override`, etc. strings present | ✅ |
| Engine helper | `pending_revisions_across_systems()` returns real data | ✅ 1 pending found in current dev store |

## Carry-forward to S66

- **G-4 (F-023)** — add-evidence-to-existing-system surface. Mixed engine + UI; last of the S64 audit's actionable items.
- **Edge cases from S64 audit:** 4 `assurance_model.py` summarize/explain POSTs — decide if these become G-5..G-8 or are scaffolding.
- **STEP 4 spillover** (Mermaid + per-tool eval rubric) — deferred since S60.
- **Remaining ARM read stubs** — `list_subscriptions`, `list_role_assignments`, `get_network_topology`. Property-bag tools likely redundant per S63 close.
- **Memory candidate:** SPA deploy = manual `swa deploy --env production` per SPA dir. Worth a feedback memory if this isn't already captured (S48 had a compound rule for CWD sensitivity but not the full canonical sequence).

## Outstanding questions

None for S65.
