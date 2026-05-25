# SESSION-44 — Smoke split (smoke_portal.ps1 + smoke_gov.ps1) + ENGINEER provisioning + login redirect smoke

## State at start
- **A1 OpenAPI: 40/40 ✅ DONE** (S43 close-out via api/reports.py 28b prose)
- **A5 CISO Console: 10/10 ✅ DONE** (+ 1 bonus RTF Forensics)
- **A6/A7 redirect logic: shipped** (middleware/auth.py — env-var driven, defaults to "/" until cutover)
- A12/A13: cutover work — S45
- A15: 🟡 Bicep ✓; P1v3 + staging slot independent

## Locked decisions
- 24b/24d/25a-b/26a/27a + polymorphic sub-rule/28a-c (closed)/38a all in force
- A6/A7 env-var pattern: `PORTAL_URL` + `GOV_URL` flip at S45, no redeploy
- ENGINEER role added S43; provisioning lands S44

## Plan

**STEP 1 — Provision DEMO_USER_ENGINEER_HASH (~5 min)**
Generate bcrypt hash for a demo-engineer password matching the convention used
for other roles (per CLAUDE.md `~/.claude/templates/CLAUDE-azure-functions.md`
hash-generation pattern). Set on app-aigovern-dev via:
```powershell
az functionapp config appsettings set `
  --name app-aigovern-dev `
  --resource-group rg-aigovern-dev `
  --settings "DEMO_USER_ENGINEER_HASH=<bcrypt>"
```
Document the demo-engineer username + password rotation policy alongside the
other DEMO_USER_*_HASH entries in ARCHITECTURE.md.

**STEP 2 — Split deploy/smoke_e2e.ps1 → smoke_portal.ps1 + smoke_gov.ps1 (~30 min)**
Per V2-PORTAL-SPLIT §A4/A5:
- `smoke_portal.ps1` — verifies Team Workspace SPA loads (10 V1 surfaces). For
  now: targets `swa-aigovern-portal-dev.azurestaticapps.net` (custom DNS lands
  S45). At cutover, change target to `portal.aigovern.sandboxhub.co`.
- `smoke_gov.ps1` — verifies CISO Console (10 surfaces + 1 bonus RTF
  Forensics). Currently targets `swa-aigovern-gov-dev.azurestaticapps.net`;
  cutover updates to `gov.aigovern.sandboxhub.co`.
- Engine API probes stay in a third file `smoke_api.ps1` or remain inline in
  both per V2-PORTAL-SPLIT §180.
- Keep original `smoke_e2e.ps1` as a thin wrapper that calls all three until
  S45 cutover lands; delete after V2 live.

**STEP 3 — Login redirect smoke probe (~10 min)**
Add a probe to `smoke_api.ps1` (or wherever auth health lives) that:
1. POSTs to `/api/auth/login` with `username=demo-engineer&password=<>&next=/`
2. Asserts response JSON `next` == `$env:PORTAL_URL` (or `/` if unset)
3. Repeats for `demo-ciso` → asserts `next` == `$env:GOV_URL` (or `/`)
4. Repeats with `next=/deep-link` and asserts the deep link survives
This is the runtime proof for A6/A7 acceptance criteria.

**STEP 4 — V2-PORTAL-SPLIT Bicep additions (~15 min — IF time permits)**
Per §171: two new Static Web Apps `swa-aigovern-portal-dev` +
`swa-aigovern-gov-dev` in `eastus2`. Bicep modules in `deploy/bicep/`. Do NOT
deploy yet — defer to S45. Just the IaC + a comment that GitHub Actions
deployment wiring lands at cutover.

**STEP 5 — Closeout**
- ARCHITECTURE.md S44 entry
- Write SESSION-45 plan (V1→V2 302 + DNS rehearsal + env-var flip)
- Delete this plan
- Push

## Target end-state
| Item | Start | Target |
|---|---|---|
| A6/A7 | logic ✓, env vars pending | logic ✓, ENGINEER provisioned, smoke probe ✓, env vars pending S45 |
| smoke harness | single smoke_e2e.ps1 | smoke_portal + smoke_gov + smoke_api (wrapper retained) |
| Bicep | 1 SWA (apex) | 3 SWAs (apex + portal + gov, gov+portal not yet deployed) |
| Sessions to V2 cutover | ~2 | ~1 (S45 = cutover) |

## Out of scope (S44)
- Actual SWA provisioning (deferred to S45 with DNS)
- DNS CNAME changes
- App Insights / P1v3 / staging slot (independent infra track)

## After S44
- **S45 (CUT-2 — V2 LIVE):** Provision portal+gov SWAs, set PORTAL_URL+GOV_URL
  env vars, add V1→V2 302 redirect at apex `aigovern.sandboxhub.co`, DNS
  rehearsal, full smoke pass on custom-DNS, rollback verification. **V2 LIVE.**
