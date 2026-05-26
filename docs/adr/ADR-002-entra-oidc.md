# ADR-002 — Engine-level Microsoft Entra OIDC authentication

- **Status:** Accepted (Session 49, 2026-05-26). Implementation target: S49 (engine middleware + KV + group mapping + bcrypt fallback flag) and S50 (SPA login UX on both portals).
- **Deciders:** Praveen Kosuri
- **Supersedes:** none. Extends [middleware/auth.py](../../middleware/auth.py) (bcrypt SessionAuthMiddleware, Sessions 25 + 43).
- **Related:** Session 25 (parent-domain session cookie), Session 43 (role-aware landing — `_default_target_for_user`), Session 47 (SPA cross-origin API), Session 48 (smoke probe expansion + commitment to engine-level OIDC).
- **Context anchors:** [middleware/auth.py:120](../../middleware/auth.py) (`_verify`), [middleware/auth.py:177](../../middleware/auth.py) (`SessionAuthMiddleware.dispatch`), [middleware/auth.py:228](../../middleware/auth.py) (`/api/auth/login`), [middleware/auth.py:86](../../middleware/auth.py) (`_default_target_for_user`).

---

## 1. Context

The platform currently authenticates demo users via bcrypt-hashed passwords
stored as App Service settings (`DEMO_USER_<ROLE>_HASH`). The
`SessionAuthMiddleware` (`middleware/auth.py`) issues a signed session cookie
on the parent domain `.aigovern.sandboxhub.co` so that
`portal.aigovern.sandboxhub.co` (Team Workspace SPA) and
`gov.aigovern.sandboxhub.co` (CISO Console SPA) share a single SSO session
with the engine at `aigovern.sandboxhub.co`.

This works for demo theatre but fails the first real customer conversation:
- No directory integration. Onboarding is "hand me your password hash."
- No MFA. Demo hashes are static, no second factor.
- No off-boarding story. Removing a user requires a redeploy.
- No group → role provenance. Roles are baked into the username string
  (`demo-ciso` → role `ciso`), not derived from identity claims.

**Production model (locked, 2026-05-26):** Entra OIDC is the **only** auth
path in production. bcrypt remains live exclusively for the demo window so
the pre-seeded `demo-ciso` / `demo-engineer` / ... accounts continue to work
for stakeholder demos; the moment the demo window closes, bcrypt is hard-
gated off (`ALLOW_DEMO_AUTH=false`) and stays off. There is no "permanent
bcrypt fallback" — the flag exists for a one-way cutover, not as a long-
term option.

**Role model (locked, prod): 2 roles, 1:1 with portals.** The 7-role
taxonomy in [middleware/auth.py:47](../../middleware/auth.py) (`CRO`,
`CISO`, `AUDIT`, `MRM`, `AIGOV`, `OPERATOR`, `ENGINEER`) was a *demo
stagecraft* device — it gave the demo distinct visual personas. In prod
the meaningful distinction is **which portal you land on**, not which
of 7 sub-personas you wear:
- `ciso` — sees gov.aigovern.sandboxhub.co (CISO Console: cross-team
  visibility across all AI systems, findings, and assurance work).
- `engineer` — sees portal.aigovern.sandboxhub.co (Team Workspace:
  the developer's own work surface).

**Launch users (signallayer.ai AAD, 2026-05-26):** 3 named accounts —
1 CISO with cross-team visibility, 2 developers each doing their own
work in the team portal. Demonstrates the full "developers register
and run; CISO observes across teams" loop with real users.

Sub-roles (`audit`/`mrm`/`cro`/`operator`/`aigov`) are NOT issued in prod
sessions. The existing 7-role engine machinery (`require_role("audit",
"ciso")` etc.) stays as-is — harmless, and `ciso` remains in those
allowlists — but no one is granted those roles at the OIDC layer until
a real customer requires the distinction.

Users with no portal group get **denied** — not defaulted, not silently
downgraded.

S48 STEP 4 reconfirmed the commitment to Microsoft Entra OIDC and explicitly
ruled out SWA-level (Static Web Apps) auth integration. Reasoning anchored
here so it isn't re-litigated: SWA auth terminates at the static host, issues
a `StaticWebAppsAuthCookie` scoped to `*.azurestaticapps.net` (or a single
custom SWA domain), and the engine at `aigovern.sandboxhub.co` would have to
trust that cookie out-of-band. That breaks the **single parent-domain cookie
chain** Session 25 paid for, and forces a second auth concept (SWA cookie +
engine cookie) at every API call boundary.

Three things we *want* from Entra OIDC:

1. **Directory truth.** Users provisioned in Entra; group memberships
   determine role; off-boarding is a tenant action.
2. **MFA.** Tenant-level conditional access policies apply automatically.
3. **Group-claim → role mapping.** A user in `signallayer-ciso` security
   group authenticates with role `ciso`, no per-user provisioning.

Three things we want to **keep**:

1. **Single parent-domain cookie.** `aigovern_session` on
   `.aigovern.sandboxhub.co` survives unchanged. Downstream RBAC
   (`require_role`), session activity tracking (`usage_analytics`), and
   role-aware landing (`_default_target_for_user`) all continue working.
2. **Bcrypt demo path during the demo window.** Stakeholder demos run on
   pre-seeded demo accounts (`demo-ciso`, `demo-engineer`, ...) with known
   passwords. Killing bcrypt before the demo would break the demo.
3. **Slim deploy.** `requirements-deploy.txt` already pays the dep-bloat
   tax (Session 12 outage). Adding an auth lib must be cheap.

## 2. Decision drivers

| Driver                                                  | Weight |
|---------------------------------------------------------|--------|
| Single parent-domain cookie chain (Session 25)          | HARD CONSTRAINT |
| Slim deploy invariant (Session 12 / 19c)                | High   |
| Preserve `require_role()` + `_default_target_for_user()` semantics | High   |
| Demo continuity — bcrypt path remains live until cutoff | High   |
| Group-claim driven role mapping (zero per-user config)  | High   |
| Minimise net-new auth surfaces in the SPAs              | Medium |
| Secret hygiene — no Entra client secret in app settings | Medium |
| Future-proof for multi-tenant (V2)                      | Low    |

## 3. Options considered

### Option A — SWA-level auth (`staticwebapp.config.json` with Entra provider)

| | |
|---|---|
| **Pros** | Zero engine code change. SWA terminates auth; engine sees a header (`x-ms-client-principal`) it can trust if it's behind SWA's reverse proxy. |
| **Cons** | **Violates HARD CONSTRAINT.** Engine lives at `aigovern.sandboxhub.co` (App Service), SPAs live at `portal.*` / `gov.*` (SWA). The `x-ms-client-principal` header is only injected by SWA's reverse proxy on requests routed *through* SWA. Cross-origin SPA → engine API calls (the Session 47 model) bypass SWA entirely. Would force re-routing all `/api/*` traffic through SWA, doubling network hops and re-introducing a single point of failure SWA wasn't built for. Also: cannot mix bcrypt + Entra on the SWA gate. |
| **Verdict** | **Rejected** (S48 STEP 4). Reconfirmed here for record. |

### Option B — Engine-level OIDC via `msal` (Microsoft Authentication Library for Python)

| | |
|---|---|
| **Pros** | First-party Microsoft library. Direct mapping to Entra docs / Stack Overflow. Built-in token cache. |
| **Cons** | MSAL is built around the *application acquiring tokens* (confidential/public client). The OIDC sign-in code path is doable but undocumented — the canonical samples wrap MSAL inside a Flask/FastAPI handler with manual state/nonce management. No native FastAPI middleware integration. Pulls in `cryptography` + `msal` + transitive (~12 MB zipped). Token-cache abstractions are oriented to *outbound* tokens, not *inbound* user sessions. |
| **Verdict** | **Rejected.** authlib is a cleaner fit for the inbound web-login flow we need. MSAL would be the right answer if the engine were *calling* downstream Microsoft Graph APIs on the user's behalf (OBO flow) — not in scope. |

### Option C — Engine-level OIDC via `authlib` (chosen)

| | |
|---|---|
| **Pros** | Purpose-built for OIDC web-login flows. First-class `authorize_redirect` + `authorize_access_token` helpers that handle state/nonce/PKCE automatically. Composes cleanly into FastAPI: register a `StarletteOAuth2App`, mount two routes (`/auth/oidc/login`, `/auth/oidc/callback`). Stays out of `SessionAuthMiddleware` — the OIDC callback writes the same signed `aigovern_session` cookie the bcrypt path writes today, so middleware dispatch is unchanged. Small dep footprint (~3 MB). Battle-tested in FastAPI ecosystem. |
| **Cons** | Not a Microsoft-blessed library. Entra-specific quirks (group overage claim, tenant-restricted issuer validation) need explicit handling. We own that mapping code. |
| **Verdict** | **Chosen.** Cost is well-scoped (one bridge file: `middleware/oidc.py`); benefit is direct (zero changes to existing middleware contract). |

### Option D — Run Entra as an OIDC provider but keep the bcrypt path permanently

Considered as a fallback. Rejected because the demo-fallback flag
(`ALLOW_DEMO_AUTH`) gives us the same property *temporarily* without
committing to two permanent code paths.

## 4. Decision

**Adopt Option C (authlib at the engine layer)** with the following
sub-decisions:

1. **Where OIDC lives:** new file `middleware/oidc.py`, paired with a new
   router `api/auth_oidc.py`. `SessionAuthMiddleware` in `middleware/auth.py`
   is **not modified** beyond adding two PUBLIC_PREFIXES entries
   (`/auth/oidc/login`, `/auth/oidc/callback`). The OIDC callback handler
   issues the same `aigovern_session` cookie the bcrypt `/api/auth/login`
   handler issues today (same payload shape `{"u": user, "sid": sid}`, same
   `usage_analytics.session_start` call, same `_default_target_for_user`
   target computation). Downstream code (`require_role`,
   `_default_target_for_user`, `usage_analytics`) sees no diff between an
   OIDC-issued session and a bcrypt-issued session — by design.

2. **Redirect URI naming:** `/auth/oidc/callback` (engine-relative). The
   Entra app registration's redirect URI is
   `https://aigovern.sandboxhub.co/auth/oidc/callback`. Rejected
   `/auth/callback/entra` — keeps the OIDC concept first in the path so the
   future addition of e.g. SAML or another IdP slots in cleanly
   (`/auth/saml/callback`).

3. **Secret storage:** Entra client secret lives in **Azure Key Vault**
   (`kv-aigovern-sl-dev`, eastus). App Service managed identity gets a
   `Key Vault Secrets User` role assignment. The engine reads the secret
   at startup via the App Service Key Vault reference syntax
   (`@Microsoft.KeyVault(SecretUri=...)`) so the secret never appears in
   environment variables visible to `az webapp config appsettings list`.

   This is a **documented exception** to the global CLAUDE.md "no Key Vault
   for demo builds" rule. Rationale: OAuth client secrets are not demo data
   — leaking one would let a third party impersonate the app to Entra,
   compromising every tenant member's auth flow. The exception is scoped to
   this one secret; bcrypt hashes, Anthropic key, Postgres conn-string, etc.
   stay in App Service config per existing convention.

4. **Group-claim → role mapping (single-tier, 1:1 with portals):** one
   module-level dict in `middleware/oidc.py`, NOT per-user assignment in
   Entra. Form:

   ```python
   _GROUP_ROLE_MAP: dict[str, str] = {
       "<CISO_CONSOLE_GROUP_OID>": "ciso",
       "<TEAM_PORTAL_GROUP_OID>":  "engineer",
   }
   ```

   The callback handler:
   - Reads `groups` claim from the ID token (Entra emits group OIDs when
     "Groups claim" is configured in the app registration).
   - Intersects user's groups with `_GROUP_ROLE_MAP`. **Zero matches →
     access denied** (explicit page, no session cookie issued).
     One match → role assigned. Two matches (user in both groups) → `ciso`
     wins (higher-privilege landing — CISO Console).
   - Landing URL derives from role via the existing
     `_default_target_for_user` (`ciso` → GOV_URL, `engineer` → PORTAL_URL).
     No changes to that function.

   **Group-overage handling:** if the user is in more than 200 groups,
   Entra omits `groups` and emits `_claim_names`/`_claim_sources`. Initial
   implementation treats this as **denial** (same as no portal group) and
   logs a warning. Microsoft Graph lookup for the full group list is
   deferred — no launch user is anywhere near 200 groups.

5. **Cookie payload extension (separates identity from authorization):**
   the signed session cookie payload grows from `{"u","sid"}` to
   `{"u","sid","r"}` where `r` is the resolved engine role
   (`ciso`/`audit`/`mrm`/`cro`/`engineer`/`operator`/`aigov`). Rationale:
   the existing `require_role` reads role by parsing the username
   (`user.replace("demo-", "", 1)`, [middleware/auth.py:344](../../middleware/auth.py)),
   which only worked because demo usernames *encoded* the role. With OIDC,
   `u` becomes the user's UPN (e.g. `praveen@signallayer.ai`); the role
   has to live somewhere else in the payload.

   Both auth paths write `r`:
   - **OIDC callback:** `r = resolved_role_from_groups()`.
   - **bcrypt login:** `r = username.replace("demo-", "", 1)` (the existing
     derivation, computed at *login* time instead of at every RBAC check).

   `require_role` is updated to read `payload["r"]` instead of parsing
   `payload["u"]`. `_default_target_for_user` is updated to take an
   optional role parameter (preserves backward compat for any callers that
   still pass only the username). Cookie shape change is forward-only —
   sessions issued before the deploy expire within 10 minutes (sliding
   TTL), so no migration step is needed; users with an in-flight session
   at cutover get bounced to /login once on their next idle window.

6. **bcrypt fallback gating (one-way demo cutover, not a long-term option):**
   new env var `ALLOW_DEMO_AUTH` (default `true` through the demo window).
   When `true`, the existing `POST /api/auth/login` form endpoint stays
   live and bcrypt-verifies as today. When `false`, the endpoint returns
   `403 demo_auth_disabled` and the login UI hides the password form.
   The flip from `true` to `false` is a one-way trip — once Entra is live
   in prod with real users, bcrypt does not come back. The flag is
   App-Service-config only; no code redeploy required to flip.

7. **Login UI changes (S50, scoped here for completeness):**
   Both `team-portal/src/pages/login/LoginPage.tsx` and
   `ciso-console/src/pages/login/LoginPage.tsx` add a
   "Sign in with Microsoft" button that redirects to
   `https://aigovern.sandboxhub.co/auth/oidc/login?next=<deep-link>`. The
   button is the *primary* CTA when `ALLOW_DEMO_AUTH=false`; the password
   form is the primary CTA when `ALLOW_DEMO_AUTH=true` (demo window). A
   `GET /api/auth/config` endpoint returns `{allow_demo_auth: bool}` so the
   SPAs render the correct primary CTA without a hardcoded build flag.

## 5. Consequences

### Positive
- Engine cookie chain (`.aigovern.sandboxhub.co`) intact. SPAs see no
  cross-origin auth change.
- `SessionAuthMiddleware.dispatch` and `usage_analytics` — unchanged.
  `require_role` and `_default_target_for_user` get **minimal** updates
  (read role from payload instead of parsing username); both auth paths
  write the same `r` field at login time. Integration is additive at the
  *issuance* layer with one surgical change at the *consumption* layer.
- MFA + off-boarding inherited from Entra tenant policies. Adding a user
  to the right Entra group is the entire onboarding workflow.
- Minimal group model (1 group = 1 portal = 1 role) — onboarding is a
  single Entra group-add per user.
- Fail-closed by default: no group → access denied, never silently
  defaulted.
- Identity and authorization separated in the cookie payload (`u` = UPN,
  `r` = role). Future auth paths (SAML, another IdP) drop in trivially.
- Client secret protected by Key Vault + managed identity — not just an
  app setting.
- bcrypt cutover is a one-way config flip, not a redeploy.

### Negative
- New Azure resource (`kv-aigovern-sl-dev`) to provision and manage. Cost is
  trivial (~$0.03/10k operations) but it's one more thing to monitor.
- Cookie payload shape change (`{"u","sid"}` → `{"u","sid","r"}`) means
  in-flight sessions at cutover are invalidated. Real impact: users bounce
  to /login once. Mitigated by the 10-min sliding TTL — full bleed-out
  inside one idle cycle.
- Group-overage edge case (200+ groups) is denied-and-logged rather than
  resolved via Graph lookup. Real exposure is zero today; deferred.
- `require_role`'s old "parse role from username" code path is dead after
  the cutover — keeping it would just be confusing. Removed in this change,
  not gated. Tests that mock cookie payloads need the new `r` field.

### Neutral / open
- Tenant: assumed `signallayer.ai`. Multi-tenant (customer Entra tenants)
  is a V2 concern — `_PORTAL_GROUP_MAP` becomes per-tenant then.
- Logout: Entra single-sign-out (`end_session_endpoint`) is **not** wired
  in v1. Logout clears the engine session cookie only. Acceptable; follow-
  up if customers ask.
- Multi-tenant V2: tracked in `docs/plans/V2-PORTAL-SPLIT.md`.

## 6. Rejected for now (revisit triggers)

- **Option A (SWA auth):** revisit only if SPAs are merged into a single
  origin with the engine (i.e. abandoning the SWA-distinct-from-engine
  topology). Not on any roadmap.
- **Option B (MSAL):** revisit if the engine starts calling Microsoft Graph
  on the user's behalf (OBO flow). Pure inbound auth stays on authlib.
- **Per-user Entra assignment (groups skipped):** revisit only if a customer
  requires role assignment without security-group membership — operationally
  worse, no benefit until then.

## 7. Implementation plan (this session — S49)

See `docs/plans/SESSION-49-entra-oidc-engine.md` for the full step list.
Summary:

1. Entra app registration `aigovern-engine-oidc` in `signallayer.ai`
   tenant. Redirect URI `https://aigovern.sandboxhub.co/auth/oidc/callback`.
   Configure "Groups claim" → Security groups → emit as group OID.
   Generate client secret (24-month expiry).
2. Create 2 Entra security groups in `signallayer.ai` tenant:
   `aigovern-ciso-console` and `aigovern-team-portal`. Assign launch
   users: 1 CISO → `aigovern-ciso-console`; 2 developers →
   `aigovern-team-portal`. Capture both group OIDs. Sub-role groups are
   NOT created at launch (see §1 — Tier 2 ships empty).
3. Provision `kv-aigovern-sl-dev` in eastus. Store client secret as
   `entra-oidc-client-secret`. Grant `app-aigovern-dev` managed identity
   the `Key Vault Secrets User` role on the vault.
4. App Service settings:
   - `OIDC_TENANT_ID=<tenant-guid>`
   - `OIDC_CLIENT_ID=<app-guid>`
   - `OIDC_CLIENT_SECRET=@Microsoft.KeyVault(SecretUri=...)`
   - `ALLOW_DEMO_AUTH=true` (flipped to `false` post-demo, one-way)
5. `middleware/oidc.py` + `api/auth_oidc.py` — authlib bridge, callback
   handler, single-tier group resolver (`_GROUP_ROLE_MAP`), session-cookie
   issuance writing `{"u": upn, "sid": sid, "r": role}` where `role` is
   `ciso` or `engineer`.
6. `middleware/auth.py` — three surgical edits:
   (a) extend `PUBLIC_PREFIXES` with `/auth/oidc/`.
   (b) `POST /api/auth/login` gains an `ALLOW_DEMO_AUTH` gate (returns 403
       when false); the success path is extended to write `r` into the
       cookie payload (computed as `username.replace("demo-", "", 1)`).
   (c) `require_role._check` reads `payload["r"]` instead of parsing
       `payload["u"]`; raises 401 if `r` is missing.
   `SessionAuthMiddleware.dispatch` and `_default_target_for_user` are
   untouched (the latter already accepts either a role-encoded username
   or a raw role string).
7. `dashboard.py` — mount `api.auth_oidc.router`.
8. `requirements-deploy.txt` — add `authlib>=1.3.0`.
9. Integration smoke: extend `deploy/smoke_e2e.ps1` with probes that assert:
   - `GET /auth/oidc/login` returns 302 to `login.microsoftonline.com`
   - `GET /api/auth/config` returns the expected `allow_demo_auth` flag
   - bcrypt login still succeeds when `ALLOW_DEMO_AUTH=true`
   - bcrypt login returns 403 when `ALLOW_DEMO_AUTH=false` (then flip back
     for the rest of the smoke run)
10. SPA login button + `/api/auth/config` consumption — **S50**, not S49.

## 8. Open questions for sign-off

These are explicitly flagged from the S49 handoff; assumptions baked into
the ADR above. Confirm or correct before code lands:

1. **Tenant:** assumed `signallayer.ai`. Confirm.
2. **Redirect URI:** chosen `/auth/oidc/callback`. Confirm (vs. the handoff's
   alternative `/auth/callback/entra`).
3. **Key Vault name:** chosen `kv-aigovern-sl-dev` in eastus. Confirm (vs.
   co-locating in an existing vault).
4. **Group OIDs:** TBD — 2 OIDs needed (`aigovern-ciso-console`,
   `aigovern-team-portal`). Group creation can be done out-of-band during
   S49 code work; OIDs get pasted into `middleware/oidc.py` at the end.
5. **Launch user UPNs:** confirm the 3 named UPNs (1 CISO, 2 developers)
   so group assignments can be done in the same Entra admin pass.
6. **bcrypt cutover trigger:** confirm `ALLOW_DEMO_AUTH=true` through the
   demo window, flipped to `false` immediately after the final
   stakeholder demo. Once flipped, the flag stays false in prod
   permanently.

---

## Appendix — what we explicitly do NOT do

- We do **not** modify `SessionAuthMiddleware.dispatch`. OIDC issuance and
  bcrypt issuance both produce a `{"u","sid","r"}` cookie; dispatch is
  shape-agnostic to the new `r` field.
- We do **not** call Microsoft Graph from the engine. Group OIDs come from
  the `groups` claim, period. Graph lookup is a deferred follow-up for the
  overage case.
- We do **not** wire Entra single-sign-out in v1. Logout clears the engine
  cookie only.
- We do **not** add MSAL or any Microsoft-branded auth library to
  `requirements-deploy.txt`. authlib + the stdlib are sufficient for the
  inbound OIDC flow.
- We do **not** store the client secret in App Service config. Key Vault
  reference only.
