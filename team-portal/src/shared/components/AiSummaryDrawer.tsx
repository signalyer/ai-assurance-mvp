// AiSummaryDrawer — S68a: shared affordance for LLM-triggering endpoints
// in api/assurance_model.py (G-5..G-9 carryover from V1 static UI).
//
// Module-level signal pattern mirrors AiSystemDrawer: any caller imports
// `openAiSummary({...})` and the drawer (mounted once at shell) opens.
//
// S68a scope: all responses are status="simulated" — the endpoints are
// hardcoded sim per S67 audit (api/assurance_model.py:404). The
// "Simulated preview" badge is MANDATORY whenever status === 'simulated'
// so operators are never misled. S69 will wire real Anthropic streaming
// and the badge will drop automatically when status === 'live'.

import { useEffect, useState } from 'preact/hooks';
import { signal } from '@preact/signals';
import { apiPost } from '../api/client';
import type { AskRequest, AskResponseOut } from '../types/assurance';

interface SummaryRequest {
  url: string;          // endpoint path under /api/v1 (e.g. '/assurance-model/explain-release')
  title: string;        // drawer header
  body: AskRequest;     // request payload
}

const openRequest = signal<SummaryRequest | null>(null);

export function openAiSummary(req: SummaryRequest): void {
  openRequest.value = req;
}

export function closeAiSummary(): void {
  openRequest.value = null;
}

// Rotating loading messages per CLAUDE.md "Loading states must be meaningful".
// 3s cadence; stops rotating when the call resolves.
const LOADING_MESSAGES = [
  'Routing to provider…',
  'Validating policy decision…',
  'Drafting summary…',
  'Logging audit event…',
];

export function AiSummaryDrawer() {
  const req = openRequest.value;
  const [result, setResult] = useState<AskResponseOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [tick, setTick] = useState(0);
  const [copied, setCopied] = useState(false);

  // Issue request on open.
  useEffect(() => {
    if (!req) {
      setResult(null);
      setError(null);
      setLoading(false);
      setCopied(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    setResult(null);
    setCopied(false);
    (async () => {
      const r = await apiPost<AskResponseOut>(req.url, req.body);
      if (cancelled) return;
      if (r.ok) {
        setResult(r.data);
      } else {
        setError(r.detail);
      }
      setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [req]);

  // Rotating loading message.
  useEffect(() => {
    if (!loading) return;
    const id = window.setInterval(() => setTick((t) => t + 1), 3000);
    return () => window.clearInterval(id);
  }, [loading]);

  const isOpen = req !== null;
  const loadingMsg = LOADING_MESSAGES[tick % LOADING_MESSAGES.length];

  async function copyMarkdown(): Promise<void> {
    if (!result?.response) return;
    try {
      await navigator.clipboard.writeText(result.response);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  }

  return (
    <>
      <div class={`drawer-overlay ${isOpen ? 'open' : ''}`} onClick={closeAiSummary} />
      <aside class={`drawer ${isOpen ? 'open' : ''}`} aria-hidden={!isOpen}>
        <div class="drawer-header">
          <div class="drawer-title">{req?.title ?? 'AI Summary'}</div>
          <button class="drawer-close" onClick={closeAiSummary} aria-label="Close">×</button>
        </div>
        <div class="drawer-body">
          {loading && (
            <div class="loading" style={{ padding: '1rem 0' }}>{loadingMsg}</div>
          )}
          {error && (
            <div class="error-banner">Request failed: {error}</div>
          )}
          {result && (
            <>
              {result.status === 'simulated' && (
                <div
                  class="badge badge-medium"
                  style={{
                    display: 'block',
                    padding: '0.5rem 0.75rem',
                    marginBottom: 12,
                    lineHeight: 1.4,
                    whiteSpace: 'normal',
                  }}
                >
                  <strong>Simulated preview</strong> — provider routing + audit
                  are live; LLM text is a deterministic placeholder until S69
                  wires the real call.
                </div>
              )}
              {result.status === 'blocked' && (
                <div class="error-banner" style={{ marginBottom: 12 }}>
                  <strong>Policy blocked this request.</strong>{' '}
                  {(result.policy_decision?.reason as string) ?? 'See audit log for detail.'}
                </div>
              )}

              <div class="drawer-section">
                <div class="drawer-section-title">Response</div>
                {result.response ? (
                  <pre
                    style={{
                      whiteSpace: 'pre-wrap',
                      wordBreak: 'break-word',
                      fontSize: '0.875rem',
                      lineHeight: 1.5,
                      padding: '0.75rem',
                      background: 'var(--surface-2, #f6f7f9)',
                      border: '1px solid var(--border)',
                      borderRadius: 4,
                      margin: 0,
                    }}
                  >
                    {result.response}
                  </pre>
                ) : (
                  <div class="text-xs text-tertiary">No response text returned.</div>
                )}
              </div>

              <div class="drawer-section">
                <div class="drawer-section-title">Routing</div>
                <dl class="def-list">
                  <dt>Status</dt><dd class="font-mono">{result.status}</dd>
                  {result.provider && <><dt>Provider</dt><dd>{result.provider}</dd></>}
                  {result.model && <><dt>Model</dt><dd class="font-mono">{result.model}</dd></>}
                  <dt>Use Case</dt><dd class="font-mono">{result.use_case}</dd>
                  <dt>Audit Event</dt><dd class="font-mono text-xs">{result.audit_event_id}</dd>
                  {result.governance?.trace_id && (
                    <><dt>Trace</dt><dd class="font-mono text-xs">{result.governance.trace_id}</dd></>
                  )}
                </dl>
              </div>

              {result.sanitized_redactions.length > 0 && (
                <div class="drawer-section">
                  <div class="drawer-section-title">
                    Redacted Fields ({result.sanitized_redactions.length})
                  </div>
                  <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                    {result.sanitized_redactions.map((f) => (
                      <span key={f} class="badge badge-info">{f}</span>
                    ))}
                  </div>
                </div>
              )}

              <div class="drawer-section" style={{ display: 'flex', gap: 8 }}>
                <button
                  class="btn btn-sm btn-secondary"
                  onClick={copyMarkdown}
                  disabled={!result.response}
                >
                  {copied ? 'Copied!' : 'Copy markdown'}
                </button>
                <button class="btn btn-sm btn-secondary" onClick={closeAiSummary}>
                  Close
                </button>
              </div>
            </>
          )}
        </div>
      </aside>
    </>
  );
}
