# SESSION-49 — Engine-level Microsoft Entra OIDC

**Status entering S49:** V2 LIVE on prod sha `d6f9a8d` (engine) + `86a94e6` (SPA). S48 closed clean with 5-probe subroute smokes on both portals. Register-AI-System wizard live in Team Portal. Auth model in prod is still demo-bcrypt only — Entra integration deferred from every prior session is the S49 mission.

**Theme:** Add Microsoft Entra OIDC as the prod auth path at the engine layer (not SWA). Preserve single-cookie SSO across `portal.*` and `gov.*` subdomains. Keep bcrypt live for the demo window via `ALLOW_DEMO_AUTH` flag, gated one-way off post-demo.

## Locked decisions (from [ADR-002](../adr/ADR-002-entra-oidc.md), accepted 2026-05-26)

- **Engine-level OIDC**, not SWA-level. Preserves parent-domain cookie chain on `.aigovern.sandboxhub.co` (Session 25).
- **authlib** (Python) — not MSAL. Built for inbound OIDC web-login; clean FastAPI composition.
- **2 roles, 1:1 with portals.** `ciso` → gov subdomain, `engineer` → team portal subdomain. The 7-role demo taxonomy was stagecraft; prod auth model collapses to 2.
- **2 Entra security groups**, no sub-role groups at launch:
  - `aigovern-ciso-console` → role `ciso`
  - `aigovern-team-portal` → role `engineer`
- **3 launch users in `signallayer.ai` AAD (locked 2026-05-26):**
  - `praveen@signallayer.ai` — CISO → `aigovern-ciso-console` → lands on gov.aigovern.sandboxhub.co
  - `pravdev@signallayer.ai` — Dev 1 → `aigovern-team-portal` → lands on portal.aigovern.sandboxhub.co
  - `rajesh@signallayer.ai` — Dev 2 → `aigovern-team-portal` → lands on portal.aigovern.sandboxhub.co
- **Cookie payload extends `{u,sid}` → `{u,sid,r}`.** `u` = UPN, `r` = role. `require_role` reads `payload["r"]` directly. Drops the `demo-{role}` username-parsing hack.
- **Key Vault for the Entra client secret only** (`kv-aigovern-sl-dev`, eastus). Documented exception to the global CLAUDE.md "no KV for demo" rule, scoped to this one secret. Managed identity for engine → KV read.
- **bcrypt one-way cutover.** `ALLOW_DEMO_AUTH=true` through demo window, flipped to `false` after final stakeholder demo. Stays false in prod permanently.
- **Redirect URI:** `https://aigovern.sandboxhub.co/auth/oidc/callback`.
- **Logout:** clears engine session cookie only. Entra single-sign-out deferred.
- **Group-overage (200+ groups):** denied + logged. Graph lookup deferred — no launch user is anywhere near.
- **No changes to** `SessionAuthMiddleware.dispatch`, `usage_analytics`, `_default_target_for_user` (the existing CRO/AUDIT/MRM partitioning still routes `ciso` to gov and `engineer` to portal — already correct).

## STEP 1 — Entra side (~30 min, out-of-band, can run in parallel with code)

In Azure Portal / Entra admin center (`signallayer.ai` tenant):

1. **App registration:** `aigovern-engine-oidc`. Supported account types: single tenant. Redirect URI (Web): `https://aigovern.sandboxhub.co/auth/oidc/callback`. Capture **tenant ID** + **client (application) ID**.
2. **Client secret:** generate one, 24-month expiry. Capture the secret VALUE (only shown once).
3. **Token configuration:** add the `groups` claim. Source = "Security groups". Emit as group OID. Applies to ID token.
4. **Security groups:** create 2 groups.
   - `aigovern-ciso-console` — capture OID.
   - `aigovern-team-portal` — capture OID.
5. **User assignments:**
   - `praveen@signallayer.ai` → `aigovern-ciso-console`.
   - `pravdev@signallayer.ai` → `aigovern-team-portal`.
   - `rajesh@signallayer.ai` → `aigovern-team-portal`.
6. **API permissions:** OIDC + email + profile only (Microsoft Graph delegated). No Graph scopes beyond sign-in. Grant admin consent.

**Acceptance:** all 5 values captured into local notes (NOT committed): tenant ID, client ID, client secret VALUE, 2 group OIDs. Both groups have the right members.

## STEP 2 — Key Vault provision + managed identity (~20 min)

```powershell
$rg = "rg-aigovern-dev"
$kv = "kv-aigovern-sl-dev"
$app = "app-aigovern-dev"

# 1. Provision KV in eastus
az keyvault create --name $kv --resource-group $rg --location eastus `
  --enable-rbac-authorization true --sku standard

# 2. Store the Entra client secret captured in STEP 1
az keyvault secret set --vault-name $kv --name entra-oidc-client-secret `
  --value "<client-secret-from-step-1>"

# 3. Get App Service managed-identity principal (enable if not already)
$mi = az webapp identity assign --name $app --resource-group $rg `
  --query principalId -o tsv

# 4. Grant Key Vault Secrets User on KV scope only
$kvId = az keyvault show --name $kv --resource-group $rg --query id -o tsv
az role assignment create --assignee-object-id $mi --assignee-principal-type ServicePrincipal `
  --role "Key Vault Secrets User" --scope $kvId

# 5. Capture the secret URI for the Key Vault reference
$secUri = az keyvault secret show --vault-name $kv --name entra-oidc-client-secret `
  --query id -o tsv
Write-Host "OIDC_CLIENT_SECRET reference: @Microsoft.KeyVault(SecretUri=$secUri)"
```

**Acceptance:** `az keyvault secret show --vault-name kv-aigovern-sl-dev --name entra-oidc-client-secret` returns the value. RBAC role assignment confirmed via `az role assignment list --assignee $mi --scope $kvId`.

## STEP 3 — App Service settings (~10 min, after STEPs 1 + 2)

```powershell
az webapp config appsettings set --name app-aigovern-dev --resource-group rg-aigovern-dev `
  --settings `
    "OIDC_TENANT_ID=<tenant-id-from-step-1>" `
    "OIDC_CLIENT_ID=<client-id-from-step-1>" `
    "OIDC_CLIENT_SECRET=@Microsoft.KeyVault(SecretUri=<secret-uri-from-step-2>)" `
    "OIDC_CISO_CONSOLE_GROUP_OID=<group-oid-from-step-1>" `
    "OIDC_TEAM_PORTAL_GROUP_OID=<group-oid-from-step-1>" `
    "ALLOW_DEMO_AUTH=true"

# Verify the KV reference resolves (status should be "Resolved")
az webapp config appsettings list --name app-aigovern-dev --resource-group rg-aigovern-dev `
  --query "[?name=='OIDC_CLIENT_SECRET']"
```

**Acceptance:** All 6 settings present. `OIDC_CLIENT_SECRET` KV reference shows `Resolved` status (not `Initialized` or `Error`). App restarts cleanly.

## STEP 4 — Engine code: `middleware/oidc.py` + `api/auth_oidc.py` (~90 min)

New files. Adopts authlib's `StarletteOAuth2App` against the Entra v2.0 OIDC discovery endpoint (`https://login.microsoftonline.com/{tenant_id}/v2.0/.well-known/openid-configuration`).

**`middleware/oidc.py`** — module-level state + helpers:
- `_oauth_client()` — lazy authlib `OAuth().register(...)` keyed on env vars (`OIDC_TENANT_ID`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`). Returns the registered Entra client. Raises `RuntimeError` at first use if any env var is missing (fail-loudly, per global CLAUDE.md env-validation rule).
- `_GROUP_ROLE_MAP` — module-level dict populated from `OIDC_CISO_CONSOLE_GROUP_OID` + `OIDC_TEAM_PORTAL_GROUP_OID` env vars at import time. Logs the resolved mapping (OID values masked to last 6 chars for audit).
- `resolve_role_from_groups(group_oids: list[str]) -> str | None` — intersects with `_GROUP_ROLE_MAP`. Returns `"ciso"` if CISO group present (wins ties), else `"engineer"` if team portal group present, else `None`. `None` = denied.
- `extract_upn_from_claims(claims: dict) -> str` — prefers `preferred_username`, falls back to `upn`, falls back to `email`. Lowercased.
- `is_group_overage(claims: dict) -> bool` — true if `_claim_names` is present and references `groups`. Logged + treated as denial.

**`api/auth_oidc.py`** — 2 endpoints:
- `GET /auth/oidc/login?next=<deep-link>` — calls `client.authorize_redirect(request, redirect_uri, state=...)`. State carries a signed `next` payload (URLSafeTimedSerializer reuse from `middleware/auth.py`). Adds `prompt=select_account` so users can switch accounts during demos.
- `GET /auth/oidc/callback` — calls `client.authorize_access_token(request)`, reads `id_token` claims, runs overage check → group resolution → UPN extraction. On success: creates a `usage_analytics.session_start()` server-side session, writes the signed `{u, sid, r}` cookie via `middleware/auth._set_session_cookie()`, redirects to the deep-link (validated via the existing "starts with /" rule) or to the role-derived default (`_default_target_for_user(role=role)`). On denial: renders an HTML page explaining "no portal access — contact your admin," no cookie set, logs `LOGIN_DENIED_NO_GROUP` event.

**Tests (new):** `tests/test_oidc_middleware.py` covering:
- `resolve_role_from_groups` — CISO group present, team portal group present, both (CISO wins), neither (None), unknown OIDs (None).
- `extract_upn_from_claims` — preferred_username, upn fallback, email fallback, all three present (preferred_username wins).
- `is_group_overage` — `_claim_names` referencing `groups` → True; `_claim_names` referencing other claims → False; absent → False.
- Callback handler stubs (mocked authlib client returning a canned ID-token-claims dict) — happy path issues cookie + redirects; denial path renders HTML + no cookie.

**Acceptance:** `python -c "import middleware.oidc; import api.auth_oidc"` passes. `pytest tests/test_oidc_middleware.py -v` all green. No top-level import of authlib in `middleware/auth.py` or any pre-existing module (regression check: `grep -r "import authlib" --include="*.py" .` returns only the 2 new files).

## STEP 5 — Engine code: `middleware/auth.py` surgical edits (~45 min)

Three targeted changes in [middleware/auth.py](../../middleware/auth.py). **No changes** to `SessionAuthMiddleware.dispatch`, `_default_target_for_user`, `_set_session_cookie`, or `_serializer`.

1. **PUBLIC_PREFIXES** ([middleware/auth.py:37](../../middleware/auth.py)) — add `"/auth/oidc/"` so the OIDC redirect + callback paths are not session-gated.

2. **`POST /api/auth/login`** ([middleware/auth.py:228](../../middleware/auth.py)) — gate on `ALLOW_DEMO_AUTH`:
   ```python
   def _allow_demo_auth() -> bool:
       return os.getenv("ALLOW_DEMO_AUTH", "true").strip().lower() in ("1", "true", "yes")

   # at top of login_submit:
   if not _allow_demo_auth():
       return JSONResponse({"error": "demo_auth_disabled"}, status_code=403)
   ```
   On the success path, compute `r = user.replace("demo-", "", 1)` and write it into the cookie payload alongside `u` and `sid`. Session-record write to `usage_analytics.session_start` unchanged.

3. **`require_role._check`** ([middleware/auth.py:326](../../middleware/auth.py)) — read role from `payload["r"]`:
   ```python
   payload = _read_cookie(request)
   if not payload:
       raise HTTPException(status_code=401, detail="unauthorized")
   role = (payload.get("r") or "").lower()
   if not role:
       raise HTTPException(status_code=401, detail="unauthorized")
   if role not in allowed:
       raise HTTPException(status_code=403, detail="insufficient_role")
   ```
   Drop the old `user.replace("demo-", "", 1)` line.

4. **New endpoint `GET /api/auth/config`** — returns `{"allow_demo_auth": bool, "oidc_enabled": bool}` so S50 SPA work knows which CTA to render. `oidc_enabled = bool(os.getenv("OIDC_TENANT_ID"))`. Public endpoint, no auth gate.

**Tests:** extend `tests/test_session*.py` if a relevant file exists, else new `tests/test_auth_payload_r_field.py`:
- bcrypt login response sets cookie with `r` field matching the role suffix of the username.
- `require_role("ciso")` accepts a cookie with `r=ciso`, rejects `r=engineer`, rejects missing `r`.
- `ALLOW_DEMO_AUTH=false` makes `POST /api/auth/login` return 403.
- `GET /api/auth/config` returns expected booleans.

**Acceptance:** `pytest tests/test_auth*.py -v` all green. Manual smoke: `curl -s POST /api/auth/login` with valid demo creds returns a cookie that decodes to `{u, sid, r}` (decoded via `_serializer().loads()`).

## STEP 6 — Wire-up: `dashboard.py` + `requirements-deploy.txt` (~15 min)

- `dashboard.py` — mount `api.auth_oidc.router`. Mount **after** session auth router so the OIDC routes are reachable but defined adjacent for review clarity.
- `requirements-deploy.txt` — add `authlib>=1.3.0`. Verify the `requirements.txt` superset already declares it (dev installs match prod).
- `deploy/build-zip.py` INCLUDE allowlist — confirm `middleware/` and `api/` directories are already whitelisted (they are; both new files inherit). No build-zip changes needed.

**Acceptance:** `python -c "import dashboard"` passes locally. `python deploy/build-zip.py` produces a zip that contains both new files (`unzip -l deploy/out/aigovern.zip | grep -E 'oidc|auth_oidc'` returns 2 hits).

## STEP 7 — Smoke probes + deploy (~30 min)

Extend `deploy/smoke_e2e.ps1`:
- Probe N+1: `GET https://aigovern.sandboxhub.co/api/auth/config` → 200 with JSON `{allow_demo_auth: true, oidc_enabled: true}`.
- Probe N+2: `GET https://aigovern.sandboxhub.co/auth/oidc/login` (no auth) → 302 with `Location:` header starting with `https://login.microsoftonline.com/`.
- Probe N+3: bcrypt login as `demo-engineer` → 200 + cookie sets. Decode the cookie locally; assert payload has all three of `u`, `sid`, `r`. (cookie decode: the script can call back to a small helper endpoint `GET /api/auth/whoami` which already returns user info; extend its response to include `role` from the cookie payload.)
- Probe N+4: temporarily flip `ALLOW_DEMO_AUTH=false` via `az webapp config appsettings set`, wait for restart, repeat bcrypt login → 403. Flip back to `true` immediately. (This probe runs against staging slot, not prod, to avoid the demo-window risk.)

Deploy via the existing slot-swap CI flow on push-to-main. `/api/health` SHA round-trip confirms the new sha lands on prod.

**Acceptance:** `pwsh deploy/smoke_e2e.ps1` returns all probes PASS. Manual end-to-end Entra login: open `https://aigovern.sandboxhub.co/auth/oidc/login?next=/ai-systems`, complete Entra prompt as one of the 3 launch users, land on the correct portal (CISO → gov.*, dev → portal.*). Authed API call works cross-origin (cookie sent).

## STEP 8 — ARCHITECTURE.md + handoff (~20 min)

- Update [ARCHITECTURE.md](../../ARCHITECTURE.md) §Session 49 section: list new files (`middleware/oidc.py`, `api/auth_oidc.py`, `tests/test_oidc_middleware.py`, `tests/test_auth_payload_r_field.py`); list modified files (`middleware/auth.py`, `dashboard.py`, `requirements-deploy.txt`, `deploy/smoke_e2e.ps1`); document the cookie payload shape change (`{u,sid}` → `{u,sid,r}`) and the one-way `ALLOW_DEMO_AUTH` cutover convention.
- Draft `docs/plans/SESSION-50-spa-entra-login-cta.md` (SPA-side "Sign in with Microsoft" buttons on both portal login pages, consuming `GET /api/auth/config`).
- Commit pair (engine code + smoke) with `Feat: Engine-level Entra OIDC (ADR-002 S49 STEPs 4-7)` and `Docs: ARCHITECTURE.md + S50 plan`.

**Acceptance:** `git status` clean post-commit. Two commits pushed to main. CI deploy green. Prod `/api/health` returns the new sha.

## Outstanding questions

All resolved 2026-05-26:
- ✅ 3 launch UPNs: `praveen@`, `pravdev@`, `rajesh@signallayer.ai`.
- ✅ RG: existing `rg-aigovern-dev` (KV co-located, no new RG).
- ✅ `prompt=select_account`: kept (lets you swap between the 3 users mid-demo).

## Target end-state (S49)

Entra OIDC live at `https://aigovern.sandboxhub.co/auth/oidc/login`. 3 launch users can sign in via Entra and land on the correct portal. bcrypt path still works (demo window). `/api/auth/config` exposes feature flags for S50 SPA work. Client secret in Key Vault, not app settings. ARCHITECTURE.md and S50 plan written.

## Provisioned values (2026-05-26)

Captured during automated execution of STEPs 1-3. Recorded here so future
sessions can find them without grepping `az` output. **Client secret value
is NOT included** — it lives only in `kv-aigovern-sl-dev`.

| Identifier | Value |
|---|---|
| Tenant ID (`signallayer.ai`) | `4d71a5ab-7797-4816-8082-74b3159f1bb0` |
| App (client) ID | `bdc7b0d2-b87c-428c-bb6b-3df596c83c69` |
| App object ID | `88885ee3-f924-4038-89b2-0001cdb1d3b8` |
| Service principal object ID | `32585f93-4506-4bf6-b757-be7005fe8544` |
| CISO Console group OID | `a7f5a389-2ca1-4010-905b-eade07086d46` |
| Team Portal group OID | `a35db759-3337-43b5-81a9-2f817728820b` |
| Key Vault | `kv-aigovern-sl-dev` (eastus, RBAC) |
| Secret URI | `https://kv-aigovern-sl-dev.vault.azure.net/secrets/entra-oidc-client-secret` |
| App MI principal ID | `e09c20a6-dfd4-4bb7-8e25-6e753475871c` |
| Client secret name | `aigovern-engine-oidc-s49` (24-month expiry) |

**Live verification 2026-05-26:** `/api/auth/config` returns
`{"allow_demo_auth":true,"oidc_enabled":true}`; `/auth/oidc/login` 302s
to `login.microsoftonline.com` with `redirect_uri=https://aigovern.sandboxhub.co/auth/oidc/callback`;
end-to-end Entra login confirmed by operator for all 3 launch users.

**Deviation from ADR-002:** KV name changed from `kv-aigovern-dev` to
`kv-aigovern-sl-dev`. Global KV name `kv-aigovern-dev` was taken by a
different tenant; added `-sl-` (signallayer) disambiguator. ADR-002 §7
updated to match.

## Working rules in effect

- Global `~/.claude/CLAUDE.md` — SignalLayerDev, `$env:MSYS_NO_PATHCONV = "1"`, `/compact` at ~60%, absolute paths in multi-target deploys.
- Project [CLAUDE.md](../../CLAUDE.md) — read [ARCHITECTURE.md](../../ARCHITECTURE.md) first, full files only, scrubber→tracer order, JSONL via storage.py only, never commit secrets.
- ADR-002 prod auth model (locked 2026-05-26): 2 roles, 2 groups, 3 launch users, KV-scoped client secret, one-way bcrypt cutover.
- Compound rules: 24a-d, 25a-b, 26a-b, 27a + polymorphic, 28a-c, 38a, S43 #1, S44 #1, S45 #1, S45 #2, S46 #1, S47 #1, S47 #2, **S48 #1** (smoke scripts must run live before declaring done — applies to STEP 7).
