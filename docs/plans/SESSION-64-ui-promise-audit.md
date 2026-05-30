# SESSION 64 — UI-promise audit + G-3 + G-2

**Date:** 2026-05-29
**Branch:** main
**Tip going in:** `5a44d49` (S63 close)
**Scope:** Discharge the quadruple-overdue UI-promise audit ([[ui-promise-audit-owed]]). Surface F-018-class gaps. Fix the two highest-leverage P1s in-session.

## What changed

| File | Change |
|---|---|
| [team-portal/src/pages/adversarial/AdversarialPage.tsx](../../team-portal/src/pages/adversarial/AdversarialPage.tsx) | **G-3:** Added `credentials: 'include'` to the raw `fetch()` SSE call. Without it, the default `same-origin` silently drops the session cookie cross-subdomain (portal → apex), producing a 401 in prod. Same shape as F-019. |
| [team-portal/src/pages/onboarding/OnboardingPage.tsx](../../team-portal/src/pages/onboarding/OnboardingPage.tsx) | **G-2:** Added `revokeKey()` + `mintFreshKey()` + revoke notice banner + Revoke button on the existing-key card. Also fixed `rotateKey()` to actually call `/revoke` on the prior key first (the comment had flagged this as a "separate S56 affordance" — S64 closed it). `bootstrapKey()` now early-returns if `revokeNotice` is set so a fresh wizard mount doesn't silently auto-mint after the operator explicitly revoked. |

## Decisions locked

- **Revoke is a separate affordance from Rotate.** Operator may want to kill a key without immediately replacing it (suspected leak, system decommission). Rotate now semantically means "revoke + mint" as one operation; Revoke is revoke-only with a banner + explicit "Issue Fresh Key" follow-up.
- **`window.confirm` is sufficient for revoke confirmation.** Matches the RTF approve flow and avoids a heavier modal dependency for a single irreversible action.
- **UI-promise audit cadence:** re-run every ~10 sessions or after any V2 surface expansion. Memory [[ui-promise-audit-owed]] updated to reflect discharge baseline.

## UI-promise audit findings

| ID | Verb | Status |
|---|---|---|
| **G-1** | Approve/reject AI System revision (CISO Console) | **Carried to S65+** — net-new Revisions Queue page is too large for this session |
| **G-2** | Revoke SDK key | **CLOSED in S64** |
| **G-3** | Adversarial probe — cross-subdomain cookie drop | **CLOSED in S64** |
| **G-4** | Add evidence to existing system (F-023 carry-forward) | Still deferred |

Edge cases surfaced for future review: `assurance_model.py` summarize/explain endpoints (4 unbound POSTs — may have been intended as click-to-explain affordances), `POST /memory/episodes` (likely intentionally agent-only).

## Verification

- ✅ `npm run build` clean — `tsc --noEmit && vite build` both pass; 48 modules transformed in 398ms.
- ⚠️ **G-3 cross-subdomain behavior cannot be verified locally** — Vite proxy is single-origin so `same-origin` and `include` are observationally identical. Honest verification = prod after deploy.
- ⚠️ **G-2 wizard interaction not preview-verified** — UX is straightforward but a future session that exercises the wizard end-to-end (issue → revoke → mint fresh → verify signal) would close the loop. The build clean + the engine endpoint contract being unchanged is the minimum bar.

## Carry-forward to S65

- **G-1** — CISO Console Revisions Queue page (~2-3 hr scope).
- **G-4 (F-023)** — add-evidence-to-existing-system surface.
- **Edge-case decision:** are the 4 `assurance_model.py` summarize/explain endpoints supposed to be wired into Findings/Release pages? If yes, becomes G-5..G-8.
- **STEP 4 spillover** (Mermaid + per-tool eval rubric) — still deferred since S60.
- **Remaining ARM read stubs** — `list_subscriptions`, `list_role_assignments`, `get_network_topology`. Property-bag tools (`get_storage_account_properties`, `get_key_vault_properties`) likely redundant given `get_resource_metadata`.

## Outstanding questions

None for S64.
