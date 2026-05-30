// OnboardingPage — 3-step post-registration wizard (S53 STEP 2).
//
// Route: /onboarding/:system_id. Entered automatically on successful intake
// submit (see RegisterSystemPage.tsx); also reachable directly via URL.
//
// Step 1: Auto-fire POST /api/sdk-keys; surface the plaintext hmac_secret
//         exactly ONCE behind a "Show secret" toggle. The secret is held
//         only in the module-level signal — never in localStorage, never
//         re-fetched. Refresh = the secret is gone and the user must
//         issue a new key (which revokes the old one).
//
// Step 2: Copy-paste install snippet pre-wired with the new key_id +
//         engine base URL + workload_id derived from the system id.
//
// Step 3: <FirstSignalPanel /> polls the engine until first_seen_at flips.
//         Done button stays disabled until then.

import { signal, computed } from '@preact/signals';
import { useEffect } from 'preact/hooks';
import { useRoute } from 'wouter-preact';
import { apiGet, apiPost } from '../../shared/api/client';
import { FirstSignalPanel } from './FirstSignalPanel';
import type { IssuedKey } from './types';

// F-013 fix: a returning key as seen by the list endpoint. No hmac_secret
// — that's surfaced once at issuance and never recoverable.
interface ExistingKeySummary {
  id: string;
  key_id: string;
  ai_system_id: string;
  data_source: string;
  issued_by: string;
  issued_at: string;
  first_seen_at: string | null;
  revoked_at: string | null;
  total_calls_24h: number;
}
interface ExistingKeyListOut {
  keys: ExistingKeySummary[];
  total: number;
}

// Module-level signals — survive minor re-renders, isolated per wizard run.
// Reset when a new system_id is mounted (see useEffect below).
const issuedKey = signal<IssuedKey | null>(null);
const issueError = signal<string | null>(null);
const issuing = signal<boolean>(false);
// G-2 (S64): Revoke is a separate affordance from Rotate. revoking gates the
// button to prevent double-click double-POST; revokeNotice surfaces the
// "you revoked key X" one-time banner so the operator has visual proof the
// security primitive fired (key revocation is the only operator action that
// is irreversible AND silent if the UI doesn't confirm it).
const revoking = signal<boolean>(false);
const revokeNotice = signal<string | null>(null);
// S55 #8: default the secret to revealed. It's shown ONCE; masking by default
// adds friction without a real security gain (the user already authenticated
// to reach this page, and the secret is on screen either way). The Hide
// button remains for shoulder-surf scenarios.
const secretRevealed = signal<boolean>(true);
const copied = signal<'secret' | 'install' | 'env' | 'snippet' | null>(null);
const currentStep = signal<1 | 2 | 3>(1);
const firstSignalArrived = signal<boolean>(false);
const mountedSystemId = signal<string>('');

// F-013 fix: a non-secret view of an already-issued key. Surfaced to the user
// when they re-enter the wizard for a system that already has a usable key —
// preventing the prior behavior of silently minting a new key on every mount
// (which orphaned the user's saved .env and broke the Verify Signal gate).
const existingKey = signal<ExistingKeySummary | null>(null);

async function bootstrapKey(aiSystemId: string): Promise<void> {
  if (issuing.value || issuedKey.value || existingKey.value) return;
  // G-2 (S64): if the operator just revoked, don't auto-mint — they should
  // explicitly hit "Issue Fresh Key". Auto-mint after revoke would defeat
  // the purpose of having a revoke-only affordance (and silently re-introduce
  // the [[wizard-mounts-create-resources]] class).
  if (revokeNotice.value) return;
  issuing.value = true;
  issueError.value = null;

  // 1. List existing keys. Reuse the most recent un-revoked one if present.
  const list = await apiGet<ExistingKeyListOut>('/sdk-keys', { ai_system_id: aiSystemId, include_revoked: false });
  if (list.ok && list.data.keys.length > 0) {
    // F-013 follow-up: prefer keys already verified (first_seen_at populated)
    // over merely-recent ones. F-013 left a trail of orphan keys on systems
    // where the operator visited the wizard multiple times before this fix;
    // "most recent un-revoked" would pick a never-used orphan and FirstSignalPanel
    // would poll a key the agent's .env doesn't sign with. Verified-first means
    // the wizard finds the key the operator's agent is actually using.
    const candidates = list.data.keys
      .filter((k) => k.revoked_at === null)
      .sort((a, b) => {
        const aVerified = a.first_seen_at !== null ? 1 : 0;
        const bVerified = b.first_seen_at !== null ? 1 : 0;
        if (aVerified !== bVerified) return bVerified - aVerified;
        return b.issued_at.localeCompare(a.issued_at);
      });
    const chosen = candidates[0];
    if (chosen) {
      existingKey.value = chosen;
      // If first_seen_at is already populated, the system is already verified
      // — skip ahead to Step 3 so the user sees the green state immediately.
      if (chosen.first_seen_at) {
        firstSignalArrived.value = true;
        currentStep.value = 3;
      }
      issuing.value = false;
      return;
    }
  }

  // 2. No existing usable key — mint one (original behavior).
  const r = await apiPost<IssuedKey>('/sdk-keys', { ai_system_id: aiSystemId });
  if (!r.ok) {
    issueError.value = r.detail;
    issuing.value = false;
    return;
  }
  issuedKey.value = r.data;
  issuing.value = false;
}

async function rotateKey(aiSystemId: string): Promise<void> {
  // Explicit user action: revoke the current key (if any) and mint a new one.
  // G-2 (S64): rotation now properly calls /revoke on the prior key first —
  // previously the comment here flagged that "the user must explicitly hit
  // /revoke first" and that revocation was a "separate S56 affordance".
  // S64 added both: revokeKey() below for revoke-only, and rotateKey now
  // calls it for "revoke + mint" as one operation. Revoke is best-effort —
  // if it fails (e.g. key already revoked server-side), the mint still
  // proceeds because the contract is "after this completes, the operator
  // has a fresh usable key", not "revoke must succeed."
  const priorKeyId = existingKey.value?.key_id ?? issuedKey.value?.key_id ?? null;
  existingKey.value = null;
  issuedKey.value = null;
  issuing.value = true;
  issueError.value = null;
  if (priorKeyId) {
    await apiPost<{ key_id: string; revoked_at: string }>(`/sdk-keys/${priorKeyId}/revoke`, {});
  }
  const r = await apiPost<IssuedKey>('/sdk-keys', { ai_system_id: aiSystemId });
  if (!r.ok) {
    issueError.value = r.detail;
    issuing.value = false;
    return;
  }
  issuedKey.value = r.data;
  issuing.value = false;
}

async function revokeKey(keyId: string): Promise<void> {
  // G-2 (S64): revoke-only — operator wants to kill a key without immediately
  // replacing it (e.g. suspected leak, system being decommissioned). After
  // success the wizard returns to a clean "no usable key" state with a banner
  // confirming the revocation. Issuing a fresh key is a separate explicit
  // action via "Issue Fresh Key" below.
  if (revoking.value) return;
  // window.confirm is the lightest-weight modal; matches the RTF approve flow.
  // Revocation is irreversible so the confirm is mandatory, not optional.
  if (!window.confirm(`Revoke SDK key ${keyId}? Any agents still signing with this key will start failing immediately. This cannot be undone.`)) return;
  revoking.value = true;
  issueError.value = null;
  const r = await apiPost<{ key_id: string; revoked_at: string }>(`/sdk-keys/${keyId}/revoke`, {});
  revoking.value = false;
  if (!r.ok) {
    issueError.value = `Revoke failed: ${r.detail}`;
    return;
  }
  existingKey.value = null;
  issuedKey.value = null;
  revokeNotice.value = `Key ${r.data.key_id} revoked at ${r.data.revoked_at}.`;
}

async function mintFreshKey(aiSystemId: string): Promise<void> {
  // G-2 (S64): explicit mint, separate from bootstrap (which is the on-mount
  // auto-discovery path). Used after revokeKey to give the operator a
  // dedicated action button rather than auto-minting on their behalf —
  // F-013 [[wizard-mounts-create-resources]] showed how unconditional
  // mint-on-mount produces orphan keys; making this explicit avoids
  // re-introducing that class.
  if (issuing.value) return;
  issuing.value = true;
  issueError.value = null;
  revokeNotice.value = null;
  const r = await apiPost<IssuedKey>('/sdk-keys', { ai_system_id: aiSystemId });
  issuing.value = false;
  if (!r.ok) {
    issueError.value = r.detail;
    return;
  }
  issuedKey.value = r.data;
}

function copyTo(text: string, key: NonNullable<typeof copied.value>): void {
  void navigator.clipboard.writeText(text).then(() => {
    copied.value = key;
    window.setTimeout(() => { if (copied.value === key) copied.value = null; }, 1500);
  }).catch(() => {});
}

function workloadIdFor(systemId: string): string {
  return systemId.toLowerCase().replace(/[^a-z0-9_-]/g, '-');
}

const engineBaseUrl = computed<string>(() => {
  // F-015: the SPA (portal.aigovern.sandboxhub.co) and the engine
  // (aigovern.sandboxhub.co) are on different origins in prod — the previous
  // window.location.host fallback emitted the SWA host, which 200s every
  // request with index.html and silently breaks every operator's .env.
  // VITE_API_BASE_URL is the SPA's authoritative view of the engine
  // (e.g. https://aigovern.sandboxhub.co/api/v1). Strip the /api/v* suffix
  // because the SDK base_url is the origin, not the versioned API root.
  const apiBase = (import.meta as any).env?.VITE_API_BASE_URL as string | undefined;
  if (apiBase) {
    try {
      return new URL(apiBase).origin;
    } catch {
      // fall through to legacy heuristic
    }
  }
  if (typeof window === 'undefined') return 'https://aigovern.sandboxhub.co';
  const h = window.location.hostname;
  if (h === 'localhost' || h === '127.0.0.1') return 'http://localhost:8000';
  return `${window.location.protocol}//${window.location.host}`;
});

function envFor(key: IssuedKey): string {
  const wid = workloadIdFor(key.ai_system_id);
  return `# .env (local dev — never commit)
SL_KEY_ID=${key.key_id}
SL_API_KEY=${key.hmac_secret}
SL_API_BASE_URL=${engineBaseUrl.value}
SL_WORKLOAD_ID=${wid}
`;
}

function snippetFor(key: IssuedKey): string {
  const wid = workloadIdFor(key.ai_system_id);
  return `import os
import asyncio
import signallayer

# 1. Initialise once at startup.
signallayer.init(
    key_id=os.environ["SL_KEY_ID"],
    api_key=os.environ["SL_API_KEY"],
    base_url=os.environ["SL_API_BASE_URL"],
)

# 2. Decorate your LLM-calling function with the platform chain.
#    Order is MANDATORY: policy_gate → scrub_pii → guardrails → trace → evaluate
@signallayer.policy_gate(action="llm_call")
@signallayer.scrub_pii(scope="${key.ai_system_id}")
@signallayer.guardrails()
async def call_llm(prompt: str, workload_id: str = "${wid}") -> str:
    # Your LLM call here (Anthropic, OpenAI, etc.)
    return f"Response to: {prompt}"

# 3. Assert the decorator chain at import time (fails fast on misorder).
signallayer.guard(call_llm)

# 4. Call it — the engine will receive the first signal within seconds.
result = asyncio.run(call_llm(prompt="ping"))
print(result)
`;
}

const INSTALL_CMD = 'pip install -e ./sdk';

interface CodeBlockProps {
  label: string;
  text: string;
  copyKey: NonNullable<typeof copied.value>;
  language?: string;
  masked?: boolean;
}

function CodeBlock({ label, text, copyKey, language, masked }: CodeBlockProps) {
  const isCopied = copied.value === copyKey;
  const display = masked ? text.replace(/./g, '•') : text;
  return (
    <div style={{ marginBottom: '0.75rem' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.25rem' }}>
        <span style={{ fontSize: '11px', color: 'var(--text-secondary)', textTransform: 'uppercase', fontWeight: 600 }}>
          {label}{language ? <span style={{ marginLeft: '0.5rem', opacity: 0.6 }}>· {language}</span> : null}
        </span>
        <button class="btn btn-sm" onClick={() => copyTo(text, copyKey)}>
          {isCopied ? 'Copied!' : 'Copy'}
        </button>
      </div>
      <pre style={{
        background: 'var(--bg-input)', border: '1px solid var(--border-strong)',
        borderRadius: '6px', padding: '0.875rem 1rem',
        fontFamily: 'Monaco, Menlo, Consolas, monospace', fontSize: '12px',
        whiteSpace: 'pre', overflowX: 'auto', lineHeight: 1.55,
        color: 'var(--text-primary)', margin: 0,
      }}>{display}</pre>
    </div>
  );
}

export function OnboardingPage() {
  const [, params] = useRoute<{ system_id: string }>('/onboarding/:system_id');
  const systemId = params?.system_id ?? '';

  useEffect(() => {
    if (!systemId) return;
    // Reset wizard state on a new system_id mount.
    if (mountedSystemId.value !== systemId) {
      issuedKey.value = null;
      existingKey.value = null;
      issueError.value = null;
      secretRevealed.value = false;
      copied.value = null;
      currentStep.value = 1;
      firstSignalArrived.value = false;
      // G-2 (S64): clear revoke-state too — a banner from a prior system
      // would otherwise leak onto a fresh wizard mount.
      revokeNotice.value = null;
      revoking.value = false;
      mountedSystemId.value = systemId;
    }
    void bootstrapKey(systemId);
  }, [systemId]);

  if (!systemId) {
    return <div class="empty-state">No system id in URL.</div>;
  }

  const key = issuedKey.value;
  // F-013: existingKey is the un-revoked key found on mount (no plaintext
  // secret — that was surfaced once at issuance). When set, Steps 1/2/3
  // render in "returning user" mode: no secret reveal, no snippet (the user
  // already has the .env from the first visit), only the key_id + a Rotate
  // affordance + the FirstSignalPanel pointed at the existing key_id.
  const existing = existingKey.value;
  const activeKeyId = key?.key_id ?? existing?.key_id ?? '';
  const activeSystemId = key?.ai_system_id ?? existing?.ai_system_id ?? systemId;

  return (
    <div>
      <div class="page-header">
        <div>
          <div class="page-title">Onboard your AI system</div>
          <div class="page-subtitle">
            Issue an SDK key, drop in the decorator stack, and verify the first signal.
            System ID: <code>{systemId}</code>
          </div>
        </div>
        <div class="page-actions">
          <a class="btn btn-sm" href={`/ai-systems`}>Skip to AI Systems</a>
        </div>
      </div>

      <div class="step-rail">
        {[1, 2, 3].map((n) => {
          const labels: Record<number, string> = { 1: 'Issue Key', 2: 'Install Snippet', 3: 'Verify Signal' };
          const cls = n === currentStep.value ? 'active' : n < currentStep.value ? 'done' : '';
          return (
            <div class={`step-rail-item ${cls}`} key={n} onClick={() => { currentStep.value = n as 1 | 2 | 3; }}>
              <span class="step-num">{n < currentStep.value ? '✓' : n}</span>
              <span>{labels[n]}</span>
            </div>
          );
        })}
      </div>

      {issueError.value && (
        <div class="error-banner">Key issuance failed: {issueError.value}</div>
      )}

      {/* STEP 1 — Issue */}
      {currentStep.value === 1 && (
        <div class="card">
          <div class="card-header">
            <div>
              <div class="card-title">1 · SDK API key</div>
              <div class="card-subtitle">
                The HMAC secret is displayed only once. Copy it now — there is no way to retrieve it
                later. Lost secrets are recovered by issuing a new key (which revokes the old one).
              </div>
            </div>
          </div>
          <div style={{ padding: '1rem 1.25rem' }}>
            {issuing.value && <div class="loading">Loading SDK key for this system…</div>}
            {/* F-013: returning-user state — a usable key already exists.
                The plaintext secret is unrecoverable, so we surface the key_id
                and direct the operator to the .env they saved on first visit. */}
            {!key && existing && (
              <>
                <div style={{ background: 'var(--bg-input)', border: '1px solid var(--border-strong)', borderRadius: '6px', padding: '0.875rem 1rem', marginBottom: '1rem' }}>
                  <div style={{ fontSize: '13px', fontWeight: 600, marginBottom: '0.25rem' }}>
                    An SDK key already exists for this AI system.
                  </div>
                  <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                    The plaintext secret was shown only once at issuance and can&apos;t be retrieved.
                    Use the <code>.env</code> you saved when you first issued this key. If you&apos;ve
                    lost it, rotate to a new key (the existing one stays valid; revoke it via the
                    AI System detail page once the new one is in use).
                  </div>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '160px 1fr', gap: '0.5rem 1rem', fontSize: '13px' }}>
                  <div style={{ color: 'var(--text-secondary)' }}>Key ID</div>
                  <div class="mono">{existing.key_id}</div>
                  <div style={{ color: 'var(--text-secondary)' }}>AI System</div>
                  <div class="mono">{existing.ai_system_id}</div>
                  <div style={{ color: 'var(--text-secondary)' }}>Data Source</div>
                  <div><span class={`badge ${existing.data_source === 'real' ? 'badge-high' : ''}`}>{existing.data_source}</span></div>
                  <div style={{ color: 'var(--text-secondary)' }}>Issued At</div>
                  <div>{existing.issued_at}</div>
                  <div style={{ color: 'var(--text-secondary)' }}>First Seen</div>
                  <div>{existing.first_seen_at ?? <span style={{ color: 'var(--text-secondary)' }}>— never (still waiting)</span>}</div>
                </div>
                <div style={{ marginTop: '1rem', display: 'flex', gap: '0.5rem', justifyContent: 'flex-end' }}>
                  {/* G-2 (S64): Revoke is the security primitive — it kills the
                      key without minting a replacement. Distinct from Rotate
                      (which revokes + mints in one step). Disabled while a
                      revoke is in flight to prevent double-POST. */}
                  <button
                    class="btn btn-sm"
                    disabled={revoking.value}
                    onClick={() => { void revokeKey(existing.key_id); }}
                    title="Mark this key as revoked. Agents signing with it will start failing immediately."
                  >
                    {revoking.value ? 'Revoking…' : 'Revoke key'}
                  </button>
                  <button class="btn btn-sm" onClick={() => { void rotateKey(systemId); }}>
                    Rotate — revoke + issue new
                  </button>
                  <button class="btn btn-sm btn-primary" onClick={() => { currentStep.value = 3; }}>
                    Skip to Verify
                  </button>
                </div>
              </>
            )}
            {/* G-2 (S64): post-revoke clean state. No usable key + explicit
                Issue Fresh Key button. revokeNotice is the visual proof the
                revocation fired — without it the page would just look empty
                and the operator would wonder if anything happened. */}
            {!key && !existing && revokeNotice.value && (
              <>
                <div style={{ background: 'var(--bg-input)', border: '1px solid var(--border-strong)', borderRadius: '6px', padding: '0.875rem 1rem', marginBottom: '1rem' }}>
                  <div style={{ fontSize: '13px', fontWeight: 600, marginBottom: '0.25rem' }}>
                    {revokeNotice.value}
                  </div>
                  <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                    Any agents still signing with this key will start receiving 401 from the engine.
                    Issue a fresh key below to continue onboarding.
                  </div>
                </div>
                <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                  <button
                    class="btn btn-sm btn-primary"
                    disabled={issuing.value}
                    onClick={() => { void mintFreshKey(systemId); }}
                  >
                    {issuing.value ? 'Issuing…' : 'Issue Fresh Key'}
                  </button>
                </div>
              </>
            )}
            {key && (
              <>
                <div style={{ display: 'grid', gridTemplateColumns: '160px 1fr', gap: '0.5rem 1rem', fontSize: '13px' }}>
                  <div style={{ color: 'var(--text-secondary)' }}>Key ID</div>
                  <div class="mono">{key.key_id}</div>
                  <div style={{ color: 'var(--text-secondary)' }}>AI System</div>
                  <div class="mono">{key.ai_system_id}</div>
                  <div style={{ color: 'var(--text-secondary)' }}>Data Source</div>
                  <div><span class={`badge ${key.data_source === 'real' ? 'badge-high' : ''}`}>{key.data_source}</span></div>
                  <div style={{ color: 'var(--text-secondary)' }}>Issued By</div>
                  <div>{key.issued_by}</div>
                </div>
                <div style={{ marginTop: '1rem' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.25rem' }}>
                    <span style={{ fontSize: '11px', color: 'var(--text-secondary)', textTransform: 'uppercase', fontWeight: 600 }}>
                      HMAC Secret · plaintext · shown once
                    </span>
                    <div style={{ display: 'flex', gap: '0.5rem' }}>
                      <button class="btn btn-sm" onClick={() => { secretRevealed.value = !secretRevealed.value; }}>
                        {secretRevealed.value ? 'Hide' : 'Show'} secret
                      </button>
                      <button class="btn btn-sm" onClick={() => copyTo(key.hmac_secret, 'secret')}>
                        {copied.value === 'secret' ? 'Copied!' : 'Copy secret'}
                      </button>
                      {/* S55 #8: one-click .env bundle so the operator doesn't have to */}
                      {/* hand-assemble SL_KEY_ID / SL_API_KEY / SL_API_BASE_URL / SL_WORKLOAD_ID. */}
                      <button class="btn btn-sm btn-primary" onClick={() => copyTo(envFor(key), 'env')}>
                        {copied.value === 'env' ? 'Copied!' : 'Copy as .env'}
                      </button>
                    </div>
                  </div>
                  <CodeBlock label="Secret" text={key.hmac_secret} copyKey="secret" masked={!secretRevealed.value} />
                </div>
                <div style={{ marginTop: '1rem', display: 'flex', justifyContent: 'flex-end' }}>
                  <button class="btn btn-sm btn-primary" onClick={() => { currentStep.value = 2; }}>
                    I&apos;ve copied the secret — Next
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {/* STEP 2 — Snippet */}
      {currentStep.value === 2 && key && (
        <>
          <div class="card">
            <div class="card-header">
              <div>
                <div class="card-title">2 · Install &amp; configure</div>
                <div class="card-subtitle">
                  Pre-wired for <strong>{key.ai_system_id}</strong>. The snippet shows the plaintext secret in
                  the env file — handle it like any other production credential.
                </div>
              </div>
            </div>
            <div style={{ padding: '0.875rem 1.25rem' }}>
              <CodeBlock label="Install" text={INSTALL_CMD} copyKey="install" language="bash" />
              <CodeBlock label="Env file" text={envFor(key)} copyKey="env" language=".env" />
              <CodeBlock label="Decorator stack" text={snippetFor(key)} copyKey="snippet" language="python" />
            </div>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '0.5rem' }}>
            <button class="btn btn-sm" onClick={() => { currentStep.value = 1; }}>Back</button>
            <button class="btn btn-sm btn-primary" onClick={() => { currentStep.value = 3; }}>
              I&apos;ve installed it — Next
            </button>
          </div>
        </>
      )}

      {/* STEP 3 — Verify (F-013: works for both freshly-issued AND existing keys) */}
      {currentStep.value === 3 && activeKeyId && (
        <>
          <FirstSignalPanel
            keyId={activeKeyId}
            aiSystemId={activeSystemId}
            onArrived={() => { firstSignalArrived.value = true; }}
          />
          <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '0.5rem' }}>
            <button class="btn btn-sm" onClick={() => { currentStep.value = 2; }}>Back</button>
            <button
              class="btn btn-sm btn-primary"
              disabled={!firstSignalArrived.value}
              onClick={() => { window.location.href = `/ai-systems`; }}
            >
              {firstSignalArrived.value ? 'Done — go to AI Systems' : 'Waiting for first signal…'}
            </button>
          </div>
        </>
      )}
    </div>
  );
}
