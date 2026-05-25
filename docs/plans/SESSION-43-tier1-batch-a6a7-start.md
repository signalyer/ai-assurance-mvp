# SESSION-43 — Final Tier 1 batch (A1 → 40/40) + A6/A7 role-aware redirect start

## State at start
- A1 OpenAPI: **36/40 (90%)** — 4 routers remaining, all suspected Tier 1
- A5 CISO Console: **10/10 ✅ DONE** (S42)
- Compound 28a: **CLOSED + VALIDATED** (S42)
- A6 / A7 (role-aware redirects): **NOT STARTED** — V2 cutover blocker

## Locked decisions (don't re-litigate)
24b amendment (Tier 1 parallel batch up to 5 implementers), 38a (38a coupling grep pre-flight), 27a + polymorphic sub-rule, 26a (SSE/204/PlainText = op_id only), 24d (regen ONCE).

## Plan

**STEP 0 — Discover the 4 remaining routers (~5 min)**
The counter `36/40` doesn't trivially map to file count (some routers count as multi-surface in the audit). Pre-flight:
```bash
# A. Enumerate routers with zero response_model (Tier 1 candidates)
for f in api/*.py; do
  [[ "$f" == *"__init__"* || "$f" == *"_models"* || "$f" == *"_errors"* ]] && continue
  c=$(grep -c "response_model=" "$f" 2>/dev/null || echo 0)
  echo "$c $f"
done | sort -n
# B. Cross-check ARCHITECTURE.md sessions 25-42 for "swept" routers
# C. Per S42 audit: api/evaluate.py (1 model — verify all routes typed),
#    api/traces.py (1 model — verify), api/metrics.py (Prometheus PlainText,
#    26a-exempt), api/agent_notifications.py (SSE, 26a-exempt)
```
Likely candidates remaining (subject to verification): any router still
returning bare `dict` on at least one route. The 4 unswept ones become the
batch. If `metrics.py` / `agent_notifications.py` are the candidates, the
sweep is a docstring update only (mark them 26a-exempt explicitly).

**STEP 1 — 38a coupling grep across the 4 candidates (~3 min)**
For each candidate router, grep static/ + team-portal/ + ciso-console/ for
`api/<prefix>`. If ANY has SPA hits → that router is Tier 3, fan-out limited
to ≤2 routers OR demote that one to sequential. Otherwise all 4 are Tier 1
→ fan-out 4 implementers via parallel Agent calls in a single message.

**STEP 2 — Fan-out Tier 1 batch (~25 min parallel, sequential if any Tier 3)**
Spawn 4 implementer subagents in ONE message (parallel). Each handles:
- One router file
- Mirror domain shapes; strict Pydantic per 27a; document 26a exemptions in
  module docstring per 28b prose pattern
- Single commit per router (no spec regen — main session regens once after
  all 4 land)

Per S38 precedent (7 routers in one batch), this is well within fan-out limits.

**STEP 3 — Spec regen ONCE + commit roll-up (~5 min)**
After all 4 implementers return:
- `python scripts/export_openapi.py` (24d)
- Verify diff includes new schemas + op_ids only
- Either fold all 4 into a single roll-up commit OR keep them separate
  depending on agent commit behavior. Single commit preferred per S38.
- **Counter: 36 → 40/40 ✅ A1 ACCEPTANCE CLOSED**

**STEP 4 — A6/A7 role-aware login redirect (sequential, foreground, ~20 min)**
First V2 cutover-track work. After A1 closes, the path forward is:
- Engineer → team-portal SPA (existing)
- CISO → ciso-console SPA (existing, A5 done S42)
- demo-readonly / demo-reviewer → ciso-console (read-only role per V2-PORTAL-SPLIT.md §3)
- demo-risk → team-portal (existing)

Discovery:
- Read [middleware/auth.py](middleware/auth.py) — find the post-login redirect logic
- Read [api/auth.py](api/auth.py) or equivalent — POST /api/login response
- Read [static/login.html](static/login.html) — current redirect target

Implementation (estimated 1 commit):
- Add role-to-portal-URL mapping in a shared helper
- Update POST /login response to include `redirect_url` derived from role
- Update login.html to honor `redirect_url` from response (fallback to /)
- Add smoke probe: per-role login → verify Location header / redirect target

Defer to S44 if discovery uncovers larger scope (e.g. requires CORS work on
SPA dirs, or session-cookie domain rework).

**STEP 5 — Closeout**
- ARCHITECTURE.md S43 entry: A1 **40/40 ✅**, A6/A7 status
- Write SESSION-44 plan: finish A6/A7 (if not done) + smoke_portal.ps1 + smoke_gov.ps1
- Delete this plan
- Push

## Target end-state
| Item | Start | Target end |
|---|---|---|
| A1 OpenAPI | 36/40 | **40/40 ✅** |
| A5 CISO Console | 10/10 ✅ | 10/10 ✅ (no change) |
| A6/A7 redirects | 0 | partial or done |
| Sessions to V2 cutover | ~3 | ~2 |

## After S43
- **S44 (CUT-1):** Finish A6/A7 + smoke_portal.ps1 + smoke_gov.ps1
- **S45 (CUT-2):** A12 V1→V2 302 + A13 DNS rehearsal + rollback verification → **V2 LIVE**
- Background: INFRA-1 (P1v3) + INFRA-2 (App Insights staging) for A15

## Out of scope (S43)
- A12/A13 cutover (S45)
- Final A6/A7 polish if discovery is bigger than ~20 min (defer S44)
- App Insights / P1v3 / staging slot
- Garak sidecar (cut from V2)
