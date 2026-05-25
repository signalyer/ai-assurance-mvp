# SESSION-45 — V2 LIVE cutover (CUT-2)

## State at start (post-S44)
- **A1 OpenAPI: 40/40 ✅** | **A5 CISO Console: 10/10 ✅**
- **A6/A7 logic + smoke probe + cred provisioning script: ready** (env vars + cred-push pending)
- **Bicep: both SWA modules wired** (`deployTeamPortal` / `deployCisoConsole` toggles default off)
- **Smoke split: smoke_api / smoke_portal / smoke_gov + wrapper** (defaults to staging *.azurestaticapps.net hosts)
- **smoke_api Scenario 7: A6/A7 contract** verified locally; remote run pending engineer + ciso passwords

## Locked decisions
- Env-var-flip pattern over redeploys (S25 cookie-domain precedent, S43 PORTAL_URL/GOV_URL)
- Append-only cred provisioning (S44 — never rotate stakeholder passwords mid-cutover)
- SWA-CLI deploy (no repoUrl/branch on the SWA resource)
- Staging hostnames remain reachable post-cutover (for rollback verification)

## Plan — 7-step cutover checklist

**STEP 1 — Provision both SWAs as Azure resources (~5 min)**
```powershell
az account set --subscription "SignalLayerDev"
az deployment group create `
  --resource-group rg-aigovern-dev `
  --template-file deploy/bicep/main.bicep `
  --parameters @deploy/bicep/parameters.dev.json `
  --parameters deployTeamPortal=true deployCisoConsole=true
```
Verify: `teamPortalHostname` and `cisoConsoleHostname` outputs are populated
(non-empty *.azurestaticapps.net hostnames).

**STEP 2 — Deploy SPA artefacts via SWA CLI (~10 min)**
```powershell
# Get deployment tokens (one-time per SWA — store in Key Vault for re-use)
$portalTok = az staticwebapp secrets list --name swa-aigovern-portal-dev `
  --resource-group rg-aigovern-dev --query "properties.apiKey" -o tsv
$govTok    = az staticwebapp secrets list --name swa-aigovern-gov-dev `
  --resource-group rg-aigovern-dev --query "properties.apiKey" -o tsv

# Build + deploy Team Workspace
cd team-portal && npm ci && npm run build
swa deploy ./dist --deployment-token $portalTok

# Build + deploy CISO Console
cd ../ciso-console && npm ci && npm run build
swa deploy ./dist --deployment-token $govTok
```
Verify: `pwsh deploy/smoke_portal.ps1` + `pwsh deploy/smoke_gov.ps1` both exit 0
against the *.azurestaticapps.net defaults.

**STEP 3 — Bind custom DNS (~15 min for propagation)**
- Add CNAMEs in sandboxhub.co zone:
  - `portal.aigovern.sandboxhub.co` → `swa-aigovern-portal-dev.{N}.azurestaticapps.net`
  - `gov.aigovern.sandboxhub.co` → `swa-aigovern-gov-dev.{N}.azurestaticapps.net`
- Bind via Azure Portal or `az staticwebapp hostname set` (validates CNAME first).
- Wait for SSL cert provisioning (Azure-managed, ~5 min after CNAME validation).

**STEP 4 — Provision missing role hashes (~5 min)**
```powershell
python deploy/add-missing-creds.py                    # appends ENGINEER + OPERATOR
az webapp config appsettings set `
  --name app-aigovern-dev `
  --resource-group rg-aigovern-dev `
  --settings @deploy/appsettings.json
```
The appsettings.json re-push is a no-op for existing settings (same values);
only the two new DEMO_USER_*_HASH entries change. Capture the new plaintext
passwords from `deploy/creds.txt` for the stakeholder handoff.

**STEP 5 — Flip A6/A7 redirect targets (~2 min)**
```powershell
az webapp config appsettings set `
  --name app-aigovern-dev `
  --resource-group rg-aigovern-dev `
  --settings `
    PORTAL_URL=https://portal.aigovern.sandboxhub.co/ `
    GOV_URL=https://gov.aigovern.sandboxhub.co/
```
Trigger app restart (App Service config changes auto-restart). Verify via
`smoke_api.ps1` Scenario 7:
```powershell
$env:SMOKE_TARGET_URL  = "https://api.aigovern.sandboxhub.co"
$env:SMOKE_ENGINEER_PW = "<from creds.txt>"
$env:SMOKE_CISO_PW     = "<from creds.txt>"
$env:PORTAL_URL        = "https://portal.aigovern.sandboxhub.co/"
$env:GOV_URL           = "https://gov.aigovern.sandboxhub.co/"
pwsh deploy/smoke_api.ps1
```
Scenario 7 must exit PASS for A6 + A7 acceptance to close.

**STEP 6 — V1→V2 302 at apex (~10 min)**
Apex `aigovern.sandboxhub.co` currently serves V1 (engine + static/* SPAs).
Add a role-aware 302 at `/` per V2-PORTAL-SPLIT line 227:
```
aigovern.sandboxhub.co/  →  302  Location: portal.* (if engineer/operator/aigov)
                                 Location: gov.*    (if ciso/audit/mrm/cro)
                                 Location: /login   (if unauthenticated)
```
Options to evaluate at session start:
  - (a) Add a new `GET /` handler in `dashboard.py` that checks the cookie
        and emits the 302. Lowest blast radius; keeps the engine in control.
  - (b) Front-door rewrite rule (Azure Front Door). Requires AFD provisioning
        — bigger change. Defer if not already in scope.
Decide via the same env-var pattern: `V2_APEX_REDIRECT=true` toggle so the
behavior can be flipped off instantly for rollback. Recommend (a).

**STEP 7 — Full smoke + rollback verification (~10 min)**
```powershell
$env:SMOKE_TARGET_URL = "https://api.aigovern.sandboxhub.co"
$env:SMOKE_PORTAL_URL = "https://portal.aigovern.sandboxhub.co/"
$env:SMOKE_GOV_URL    = "https://gov.aigovern.sandboxhub.co/"
$env:SMOKE_USER       = "demo-aigov"
$env:SMOKE_PASSWORD   = "<password>"
pwsh deploy/smoke_e2e.ps1
```
Aggregate exit 0 = V2 LIVE acceptance. **A12 (V1→V2 302) + A13 (DNS) closed.**

Rollback verification (DO this — not just IF needed):
- Unset PORTAL_URL + GOV_URL on App Service → confirm Scenario 7 falls back to "/"
- Toggle V2_APEX_REDIRECT=false → confirm apex serves V1 again
- Staging hostnames remain reachable throughout (no DNS reuse)

## Target end-state
| Item | Start | Target |
|---|---|---|
| A1 / A5 | ✅ / ✅ | ✅ / ✅ (no change) |
| A6 / A7 | logic ✓, env vars pending | **closed via STEP 5 smoke** |
| A4 (Team Workspace renders) | logic ✓ | **closed via STEP 2 + smoke_portal** |
| A5 (CISO Console renders) | logic ✓ | **closed via STEP 2 + smoke_gov** |
| A12 (V1→V2 302) | not started | **closed via STEP 6** |
| A13 (DNS cutover) | not started | **closed via STEP 3** |
| **V2 LIVE** | pending | **LIVE** |

## After S45
- S46+ background work: A15 (P1v3 + staging slot + App Insights tightening),
  V1 deprecation cleanup (delete `static/*.html` once portal proves stable for
  N days), CSM polish based on stakeholder feedback.
- Once V2 stable: collapse smoke_e2e.ps1 wrapper — CI invokes the three
  children directly.

## Out of scope (S45)
- App Insights staging slot (independent infra track)
- Garak sidecar (cut from V2 scope)
- V1 deletion (deprecation window first)

## Rollback strategy
Every cutover step is independently reversible:
1. SWA provisioning → leave running (cheap, dual-stack reduces risk)
2. SPA deploys → SWA CLI rollback to previous deploy ID
3. DNS → delete CNAMEs, traffic returns to apex
4. Cred hashes → no rollback needed (additive)
5. PORTAL_URL/GOV_URL → unset env vars; defaults to "/" (V1 behavior)
6. V2_APEX_REDIRECT → set to false (apex serves V1)
7. Final state → roll backwards through 6→1 if needed

No step requires a redeploy of the engine. All gates are env-var or DNS.
