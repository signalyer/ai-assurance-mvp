# SESSION-50 — SPA login UX for Entra OIDC

**Status entering S50:** S49 engine work landed on prod (`2c69a13`). Entra OIDC is **live and verified end-to-end** for the 3 launch users (praveen@ / pravdev@ / rajesh@). The remaining work is purely SPA-side: surface the "Sign in with Microsoft" CTA on both portal login pages, consume the `GET /api/auth/config` feature flags, and prepare for the post-demo bcrypt cutover.

**Theme:** Make Entra the front-door login experience for end users. Bcrypt stays as a backup-button (when `allow_demo_auth=true`) so the demo continues working unchanged.

## Locked decisions (from S49 close)

- 2 portals, 2 roles, 2 Entra groups (1:1 mapping). No sub-role refinement at launch.
- Engine `/api/auth/config` is the single source of truth for which CTAs to render. SPA reads it on login-page mount; never hardcodes auth-path availability.
- Bcrypt UI stays visible while `allow_demo_auth=true`. Hidden (or shown as a disabled "demo accounts disabled" hint) when `allow_demo_auth=false`.
- Engine cookie chain on `.aigovern.sandboxhub.co` is unchanged. SPA does NOT call `/auth/oidc/login` directly — it `window.location.href = …` to it, so the browser performs the full redirect roundtrip and the engine sets the cookie at the parent domain.

## STEP 1 — `GET /api/auth/config` consumption helper (~30 min)

Shared TypeScript module in both SPAs (`team-portal/src/shared/api/authConfig.ts` and `ciso-console/src/shared/api/authConfig.ts`):

```typescript
export interface AuthConfig {
  allow_demo_auth: boolean;
  oidc_enabled: boolean;
}

export async function fetchAuthConfig(): Promise<AuthConfig> {
  const resp = await fetch(`${import.meta.env.VITE_API_BASE_URL}/auth/config`, {
    credentials: 'include',
  });
  if (!resp.ok) {
    // Conservative default: assume bcrypt only. Prevents an OIDC button
    // appearing during a transient engine outage and confusing the user.
    return { allow_demo_auth: true, oidc_enabled: false };
  }
  return resp.json();
}
```

Module-level signal (`authConfig`) populated on first call; cache for the page lifetime — the values do not change mid-session.

**Acceptance:** typecheck clean; `fetchAuthConfig()` returns the expected shape against `https://aigovern.sandboxhub.co/api/v1/auth/config`.

## STEP 2 — `LoginPage.tsx` rework (both portals, ~60 min)

Both `team-portal/src/pages/login/LoginPage.tsx` and `ciso-console/src/pages/login/LoginPage.tsx`:

- On mount: `await fetchAuthConfig()`.
- **If `oidc_enabled`**: render a primary CTA "Sign in with Microsoft" button. On click: `window.location.href = "https://aigovern.sandboxhub.co/auth/oidc/login?next=" + encodeURIComponent(deepLink || "/")`.
- **If `allow_demo_auth`**: render the existing username/password form, but as a *secondary* option below the Microsoft button. Heading: "Use demo credentials" (was the only option pre-S50; now demoted).
- **If only `allow_demo_auth`** (oidc disabled): primary = bcrypt form (revert to current S49-pre layout).
- **If only `oidc_enabled`** (demo disabled): hide the bcrypt form. The "Sign in with Microsoft" button is the only path.
- **If both false** (misconfiguration): show an error banner "Authentication is misconfigured. Contact your administrator." Should never ship to prod.

Visual: Microsoft button uses the official MS button styling (white background, MS logo, "Sign in with Microsoft" text) per Microsoft's brand guidelines. Logo SVG inlined in `src/shared/components/MicrosoftLogo.tsx`.

**Acceptance:** preview both portals; verify CTA renders correctly for all 4 (allow×oidc) combinations via preview_eval to manually toggle `/api/auth/config` response.

## STEP 3 — Deep-link preservation (~20 min)

When an unauthenticated user hits a deep link (e.g. `/findings/abc-123`), `SessionAuthMiddleware` already redirects to `/login?next=/findings/abc-123` on the engine side. The SPAs need to:
- Read `next` from URL params on login-page mount.
- Pass it through to both the bcrypt form (`<input type="hidden" name="next" value={next}>`) AND the OIDC link (`?next=…`).
- Validate it's a relative path (starts with `/`) before using — engine does the same check but defense-in-depth.

**Acceptance:** browse to a portal deep link unauthenticated, sign in via Microsoft, land on the original deep link (not the role-default landing).

## STEP 4 — Smoke + manual verification (~30 min)

- Extend `deploy/smoke_portal.ps1` + `deploy/smoke_gov.ps1` to assert that the login page DOM includes the "Sign in with Microsoft" string when `oidc_enabled=true` (curl + grep).
- Manual: open both portals in incognito, click "Sign in with Microsoft", complete Entra prompt, land on the right portal. Test deep-link preservation with `?next=/some/path`.

## STEP 5 — Optional: prepare bcrypt cutover script (~20 min)

A one-line script `deploy/disable_demo_auth.ps1` that flips `ALLOW_DEMO_AUTH=false` on both production and staging slots, waits for restart, verifies `/api/auth/config` returns `allow_demo_auth=false`, then exits. The script is the *only* sanctioned way to flip the flag in prod — manual `az` commands risk forgetting the staging slot. Not run until post-demo.

**Acceptance:** script exists, has a dry-run mode (default), and a confirmation prompt before flipping.

## Outstanding questions

1. **Microsoft button copy**: "Sign in with Microsoft" or "Sign in with Entra ID"? Microsoft's brand guidelines say the former; some enterprise auth UIs use the latter. Default: "Sign in with Microsoft".
2. **Bcrypt form post-S50 placement**: secondary CTA below the Microsoft button, or hidden behind a "Use a demo account" disclosure link? Default: visible secondary CTA — minimizes demo flow friction.
3. **Logo licensing**: inline SVG vs CDN-hosted PNG? Default: inline SVG (no external dependency, no caching concerns).

## Target end-state (S50)

Both SPA login pages render the Microsoft button as the primary CTA. Bcrypt form is the secondary path while the demo window is open; hidden after `ALLOW_DEMO_AUTH=false` is flipped. Deep links survive the OIDC roundtrip. Smoke scripts assert the right CTA renders.

## Working rules in effect

- Global `~/.claude/CLAUDE.md` — SignalLayerDev, absolute paths in deploys.
- Project [CLAUDE.md](../../CLAUDE.md) — read [ARCHITECTURE.md](../../ARCHITECTURE.md) first.
- ADR-002 prod auth model (locked 2026-05-26): 2 roles, 2 groups, 3 launch users, KV-scoped client secret, one-way bcrypt cutover.
- Compound rules through S49: 24a-d, 25a-b, 26a-b, 27a + polymorphic, 28a-c, 38a, S43 #1, S44 #1, S45 #1, S45 #2, S46 #1, S47 #1, S47 #2, S48 #1, **S49 #1** (X-Forwarded-Proto), **S49 #2** (httpx TestClient https), **S49 #3** (PS 7 redirect inspection via curl.exe).
