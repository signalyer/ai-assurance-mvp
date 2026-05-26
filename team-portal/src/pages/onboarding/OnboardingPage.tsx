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
import { apiPost } from '../../shared/api/client';
import { FirstSignalPanel } from './FirstSignalPanel';
import type { IssuedKey } from './types';

// Module-level signals — survive minor re-renders, isolated per wizard run.
// Reset when a new system_id is mounted (see useEffect below).
const issuedKey = signal<IssuedKey | null>(null);
const issueError = signal<string | null>(null);
const issuing = signal<boolean>(false);
// S55 #8: default the secret to revealed. It's shown ONCE; masking by default
// adds friction without a real security gain (the user already authenticated
// to reach this page, and the secret is on screen either way). The Hide
// button remains for shoulder-surf scenarios.
const secretRevealed = signal<boolean>(true);
const copied = signal<'secret' | 'install' | 'env' | 'snippet' | null>(null);
const currentStep = signal<1 | 2 | 3>(1);
const firstSignalArrived = signal<boolean>(false);
const mountedSystemId = signal<string>('');

async function issueKey(aiSystemId: string): Promise<void> {
  if (issuing.value || issuedKey.value) return;
  issuing.value = true;
  issueError.value = null;
  const r = await apiPost<IssuedKey>('/sdk-keys', { ai_system_id: aiSystemId });
  if (!r.ok) {
    issueError.value = r.detail;
    issuing.value = false;
    return;
  }
  issuedKey.value = r.data;
  issuing.value = false;
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
      issueError.value = null;
      secretRevealed.value = false;
      copied.value = null;
      currentStep.value = 1;
      firstSignalArrived.value = false;
      mountedSystemId.value = systemId;
    }
    void issueKey(systemId);
  }, [systemId]);

  if (!systemId) {
    return <div class="empty-state">No system id in URL.</div>;
  }

  const key = issuedKey.value;

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
            {issuing.value && <div class="loading">Issuing a new key…</div>}
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

      {/* STEP 3 — Verify */}
      {currentStep.value === 3 && key && (
        <>
          <FirstSignalPanel
            keyId={key.key_id}
            aiSystemId={key.ai_system_id}
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
