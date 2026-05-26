// CISO Console — login page (S50 STEP 2 + STEP 3).
//
// Renders the right CTAs based on engine feature flags from /api/auth/config:
//   - oidc_enabled + allow_demo_auth → MS button primary, demo form secondary
//   - oidc_enabled only              → MS button only
//   - allow_demo_auth only           → demo form only (pre-S50 layout)
//   - neither                        → misconfiguration banner
//
// Deep-link preservation (STEP 3): reads `?next=<path>` from the URL on
// mount, validates it's a relative path (defense-in-depth — engine does the
// same check), passes it through to BOTH the bcrypt form AND the OIDC link
// so the user lands on the original deep link after auth instead of the
// role-default page.
//
// bcrypt POST uses raw fetch with form-urlencoded body (the engine endpoint
// takes Form(...) params, not JSON). credentials:'include' is essential —
// the engine sets Domain=.aigovern.sandboxhub.co on the session cookie so
// it's readable from both portal subdomains after this POST resolves.
//
// OIDC click: window.location.href to the engine, NOT a fetch — the browser
// has to perform the full redirect roundtrip so the engine can set the
// cookie at the parent domain (a cross-origin fetch wouldn't see Set-Cookie
// land in the browser jar for the parent domain).

import { signal } from '@preact/signals';
import { useEffect } from 'preact/hooks';
import { fetchAuthConfig, authConfig } from '../../shared/api/authConfig';
import { MicrosoftLogo } from '../../shared/components/MicrosoftLogo';

const configLoading = signal<boolean>(true);
const submitting = signal<boolean>(false);
const submitError = signal<string | null>(null);

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? '/api/v1').replace(/\/+$/, '');
// OIDC endpoint lives at engine root (/auth/oidc/login), NOT under /api/.
// Strip the path portion off VITE_API_BASE_URL to get the bare engine origin.
function engineOrigin(): string {
  try {
    return new URL(API_BASE_URL, window.location.origin).origin;
  } catch {
    return window.location.origin;
  }
}

function readNext(): string {
  const params = new URLSearchParams(window.location.search);
  const raw = params.get('next');
  return raw && raw.startsWith('/') ? raw : '/';
}

async function submitBcrypt(ev: Event, next: string): Promise<void> {
  ev.preventDefault();
  submitting.value = true;
  submitError.value = null;

  const form = ev.target as HTMLFormElement;
  const fd = new FormData(form);
  const body = new URLSearchParams();
  body.set('username', String(fd.get('username') ?? ''));
  body.set('password', String(fd.get('password') ?? ''));
  body.set('next', next);

  try {
    const resp = await fetch(`${API_BASE_URL}/auth/login`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: body.toString(),
    });
    if (resp.ok) {
      const j = await resp.json().catch(() => ({}));
      window.location.href = (j && typeof j.next === 'string') ? j.next : next;
      return;
    }
    if (resp.status === 401) submitError.value = 'Invalid username or password.';
    else if (resp.status === 403) submitError.value = 'Demo accounts are disabled. Sign in with Microsoft.';
    else submitError.value = `Sign-in failed (HTTP ${resp.status}).`;
  } catch {
    submitError.value = 'Network error — try again.';
  } finally {
    submitting.value = false;
  }
}

function startOidc(next: string): void {
  const url = `${engineOrigin()}/auth/oidc/login?next=${encodeURIComponent(next)}`;
  window.location.href = url;
}

export function LoginPage() {
  useEffect(() => {
    void (async () => {
      await fetchAuthConfig();
      configLoading.value = false;
    })();
  }, []);

  const next = readNext();
  const cfg = authConfig.value;

  return (
    <div style={pageStyle}>
      <div style={cardStyle}>
        <h1 style={titleStyle}>AI Assurance Platform</h1>
        <div style={subtitleStyle}>CISO Console</div>

        {configLoading.value && (
          <div style={{ ...mutedStyle, marginTop: 20 }}>Loading sign-in options…</div>
        )}

        {!configLoading.value && cfg && !cfg.oidc_enabled && !cfg.allow_demo_auth && (
          <div style={errorBannerStyle}>
            Authentication is misconfigured. Contact your administrator.
          </div>
        )}

        {!configLoading.value && cfg?.oidc_enabled && (
          <button
            type="button"
            onClick={() => startOidc(next)}
            style={msButtonStyle}
          >
            <MicrosoftLogo />
            <span>Sign in with Microsoft</span>
          </button>
        )}

        {!configLoading.value && cfg?.oidc_enabled && cfg?.allow_demo_auth && (
          <div style={dividerStyle}>
            <span style={dividerLabelStyle}>or use demo credentials</span>
          </div>
        )}

        {!configLoading.value && cfg?.allow_demo_auth && (
          <form onSubmit={(e) => void submitBcrypt(e, next)} style={{ marginTop: cfg.oidc_enabled ? 0 : 20 }}>
            <label style={labelStyle} for="login-username">Username</label>
            <input
              id="login-username"
              name="username"
              autoComplete="username"
              required
              autoFocus={!cfg.oidc_enabled}
              style={inputStyle}
            />

            <label style={labelStyle} for="login-password">Password</label>
            <input
              id="login-password"
              name="password"
              type="password"
              autoComplete="current-password"
              required
              style={inputStyle}
            />

            <button type="submit" disabled={submitting.value} style={primaryButtonStyle}>
              {submitting.value ? 'Signing in…' : 'Sign in'}
            </button>
          </form>
        )}

        {submitError.value && (
          <div style={errorTextStyle}>{submitError.value}</div>
        )}

        <div style={footnoteStyle}>SignalLayer — Enterprise AI Assurance</div>
      </div>
    </div>
  );
}

// ============================================================
// Inline styles — match the dark theme of static/login.html so the
// transition from anonymous-engine-page to anonymous-SPA-page is
// visually seamless during the cutover.
// ============================================================

const pageStyle = {
  minHeight: '100vh',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  background: 'var(--bg-deep, #0b1020)',
  padding: '1rem',
};

const cardStyle = {
  background: 'var(--bg-card, #131a30)',
  border: '1px solid var(--border, #1f2a44)',
  borderRadius: 10,
  padding: '2rem',
  width: 360,
  maxWidth: '100%',
  boxShadow: '0 12px 48px rgba(0,0,0,0.35)',
};

const titleStyle = {
  fontSize: 18,
  margin: '0 0 4px',
  color: 'var(--text-primary, #e6ecff)',
};

const subtitleStyle = {
  fontSize: 12,
  color: 'var(--text-tertiary, #7a86a6)',
  marginBottom: '1.25rem',
};

const labelStyle = {
  display: 'block',
  fontSize: 11,
  textTransform: 'uppercase' as const,
  letterSpacing: '0.06em',
  color: 'var(--text-tertiary, #7a86a6)',
  margin: '10px 0 4px',
};

const inputStyle = {
  width: '100%',
  boxSizing: 'border-box' as const,
  background: 'var(--bg-deep, #0b1020)',
  border: '1px solid var(--border, #1f2a44)',
  color: 'var(--text-primary, #e6ecff)',
  padding: '8px 10px',
  borderRadius: 6,
  fontSize: 13,
  fontFamily: 'inherit',
};

const primaryButtonStyle = {
  marginTop: 16,
  width: '100%',
  background: 'rgba(99,102,241,0.85)',
  color: 'white',
  border: 0,
  padding: 10,
  borderRadius: 6,
  fontSize: 13,
  fontWeight: 600,
  cursor: 'pointer',
};

const msButtonStyle = {
  marginTop: 20,
  width: '100%',
  background: '#ffffff',
  color: '#1f1f1f',
  border: '1px solid #8c8c8c',
  padding: '10px 12px',
  borderRadius: 6,
  fontSize: 14,
  fontWeight: 600,
  cursor: 'pointer',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  gap: 10,
  fontFamily: '"Segoe UI", system-ui, sans-serif',
};

const dividerStyle = {
  display: 'flex',
  alignItems: 'center',
  margin: '20px 0 4px',
  color: 'var(--text-tertiary, #7a86a6)',
  fontSize: 11,
  textTransform: 'uppercase' as const,
  letterSpacing: '0.06em',
};

const dividerLabelStyle = {
  flex: 1,
  textAlign: 'center' as const,
  borderTop: '1px solid var(--border, #1f2a44)',
  paddingTop: 8,
};

const errorBannerStyle = {
  marginTop: 20,
  padding: '10px 12px',
  background: 'rgba(248,113,113,0.12)',
  border: '1px solid rgba(248,113,113,0.4)',
  borderRadius: 6,
  color: '#fca5a5',
  fontSize: 12,
};

const errorTextStyle = {
  color: '#f87171',
  fontSize: 12,
  marginTop: 10,
  minHeight: 16,
};

const mutedStyle = {
  color: 'var(--text-tertiary, #7a86a6)',
  fontSize: 12,
};

const footnoteStyle = {
  fontSize: 10,
  color: 'var(--text-tertiary, #7a86a6)',
  marginTop: 18,
  textAlign: 'center' as const,
};
