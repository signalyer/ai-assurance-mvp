// Auth feature-flag helper (S50 STEP 1).
//
// Wraps GET /api/auth/config — the engine's public endpoint that tells the
// SPA which login CTAs to render: "Sign in with Microsoft" (oidc_enabled)
// and/or the demo username/password form (allow_demo_auth).
//
// Values cannot change without an engine restart, so we cache the first
// successful response for the page lifetime via a module-level signal.
// Failures fall back to a conservative default — bcrypt only — so a
// transient engine outage never surfaces an OIDC button that would 404.

import { signal } from '@preact/signals';
import { apiGet } from './client';

export interface AuthConfig {
  allow_demo_auth: boolean;
  oidc_enabled: boolean;
}

const CONSERVATIVE_DEFAULT: AuthConfig = {
  allow_demo_auth: true,
  oidc_enabled: false,
};

export const authConfig = signal<AuthConfig | null>(null);

export async function fetchAuthConfig(): Promise<AuthConfig> {
  if (authConfig.value) return authConfig.value;
  const r = await apiGet<AuthConfig>('/auth/config');
  const value = r.ok ? r.data : CONSERVATIVE_DEFAULT;
  authConfig.value = value;
  return value;
}
