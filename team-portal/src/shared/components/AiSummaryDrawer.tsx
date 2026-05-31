// AiSummaryDrawer — S69: streams real Anthropic deltas via SSE.
//
// S68a: drawer was apiPost-only, response was always status='simulated'.
// S69: response is an SSE stream:
//   - blocked/simulated paths emit a single terminal 'done' event with the
//     full AskResponseOut JSON (drawer behaves identically to S68a)
//   - live path emits 'delta' events (incremental text) then a terminal
//     'done' event with status='live' + token_estimate + cost_estimate_usd
//
// Drawer state machine:
//   loading=true, streamedText='', result=null  -> loading message rotates
//   first 'delta'  -> streamedText grows, cursor affordance visible
//   'done' (live)  -> result set with full text + token/cost; cursor drops
//   'done' (sim)   -> result set; "Simulated preview" badge shown
//   'done' (blocked) -> result set; error banner shown
//   abort on close -> engine sees disconnect, writes streaming_complete=false
//
// Module-level signal pattern preserved from S68a: any caller imports
// `openAiSummary({...})` and the drawer (mounted once at shell) opens.

import { useEffect, useRef, useState } from 'preact/hooks';
import { signal } from '@preact/signals';
import { apiSse } from '../api/client';
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
// 3s cadence; stops rotating when the first delta arrives OR the call resolves.
const LOADING_MESSAGES = [
  'Routing to provider…',
  'Validating policy decision…',
  'Drafting summary…',
  'Logging audit event…',
];

export function AiSummaryDrawer() {
  const req = openRequest.value;
  const [result, setResult] = useState<AskResponseOut | null>(null);
  const [streamedText, setStreamedText] = useState<string>('');
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [tick, setTick] = useState(0);
  const [copied, setCopied] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  // Issue request on open.
  useEffect(() => {
    if (!req) {
      setResult(null);
      setStreamedText('');
      setStreaming(false);
      setError(null);
      setLoading(false);
      setCopied(false);
      // Abort any in-flight stream when the drawer closes -- engine will
      // log streaming_complete=false on the audit row.
      abortRef.current?.abort();
      abortRef.current = null;
      return;
    }
    const controller = new AbortController();
    abortRef.current = controller;
    setLoading(true);
    setStreaming(false);
    setError(null);
    setResult(null);
    setStreamedText('');
    setCopied(false);

    (async () => {
      try {
        await apiSse(req.url, req.body, {
          signal: controller.signal,
          onEvent: (event, data) => {
            if (event === 'delta') {
              try {
                const chunk = JSON.parse(data) as { text?: string };
                if (chunk.text) {
                  setStreaming(true);
                  setStreamedText((prev) => prev + chunk.text);
                }
              } catch {
                // ignore malformed delta -- final done event still wins
              }
            } else if (event === 'done') {
              try {
                const final = JSON.parse(data) as AskResponseOut;
                setResult(final);
              } catch (err) {
                setError(
                  `Bad terminal event from engine: ${
                    err instanceof Error ? err.message : 'parse error'
                  }`,
                );
              }
              setLoading(false);
              setStreaming(false);
            }
          },
          onError: (err) => {
            if (controller.signal.aborted) return;
            setError(err instanceof Error ? err.message : 'Stream error');
            setLoading(false);
            setStreaming(false);
          },
        });
      } catch {
        // apiSse re-throws on error; UI state already set by onError.
        // Aborts also land here and should be silent.
      }
    })();

    return () => {
      controller.abort();
    };
  }, [req]);

  // Rotating loading message -- only while we haven't received first delta.
  useEffect(() => {
    if (!loading || streaming) return;
    const id = window.setInterval(() => setTick((t) => t + 1), 3000);
    return () => window.clearInterval(id);
  }, [loading, streaming]);

  const isOpen = req !== null;
  const loadingMsg = LOADING_MESSAGES[tick % LOADING_MESSAGES.length];

  async function copyMarkdown(): Promise<void> {
    const text = result?.response ?? streamedText;
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  }

  // Display text precedence: final result (live or sim) > streamed deltas.
  const displayText = result?.response ?? streamedText;
  const showCursor = streaming && !result;

  return (
    <>
      {/* z-index above .drawer (101) so this drawer stacks ABOVE the
          AiSystemDrawer / FindingDrawer the operator opened first.
          Without this, two drawer-overlays at z:100 fight via DOM order,
          producing the "draft report opens dim/underlapped" bug. */}
      <div
        class={`drawer-overlay ${isOpen ? 'open' : ''}`}
        style={{ zIndex: 200 }}
        onClick={closeAiSummary}
      />
      <aside
        class={`drawer ${isOpen ? 'open' : ''}`}
        style={{ zIndex: 201 }}
        aria-hidden={!isOpen}
      >
        <div class="drawer-header">
          <div class="drawer-title">{req?.title ?? 'AI Summary'}</div>
          <button class="drawer-close" onClick={closeAiSummary} aria-label="Close">×</button>
        </div>
        <div class="drawer-body">
          {loading && !streaming && !displayText && (
            <div class="loading" style={{ padding: '1rem 0' }}>{loadingMsg}</div>
          )}
          {error && (
            <div class="error-banner">Request failed: {error}</div>
          )}

          {result?.status === 'simulated' && (
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
              are live; LLM text is a deterministic placeholder. Enable
              REAL_LLM_ENABLED + Anthropic credentials to switch on the
              live path.
            </div>
          )}
          {result?.status === 'blocked' && (
            <div class="error-banner" style={{ marginBottom: 12 }}>
              <strong>Policy blocked this request.</strong>{' '}
              {(result.policy_decision?.reason as string) ?? 'See audit log for detail.'}
            </div>
          )}
          {result?.status === 'live' && result.streaming_complete === false && (
            <div class="error-banner" style={{ marginBottom: 12 }}>
              <strong>Stream ended early.</strong>{' '}
              The connection closed before the LLM finished. Audit row marked
              partial.
            </div>
          )}

          {(displayText || showCursor) && (
            <div class="drawer-section">
              <div class="drawer-section-title">Response</div>
              <pre
                style={{
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-word',
                  fontSize: '0.875rem',
                  lineHeight: 1.5,
                  padding: '0.75rem',
                  background: 'var(--bg-input)',
                  color: 'var(--text-primary)',
                  border: '1px solid var(--border)',
                  borderRadius: 4,
                  margin: 0,
                }}
              >
                {displayText}
                {showCursor && (
                  <span
                    aria-label="streaming"
                    style={{
                      display: 'inline-block',
                      width: '0.55em',
                      height: '1em',
                      marginLeft: 2,
                      background: 'currentColor',
                      verticalAlign: 'text-bottom',
                      animation: 'aiCursorBlink 1s steps(2) infinite',
                    }}
                  />
                )}
              </pre>
            </div>
          )}

          {result && (
            <>
              <div class="drawer-section">
                <div class="drawer-section-title">Routing</div>
                <dl class="def-list">
                  <dt>Status</dt><dd class="font-mono">{result.status}</dd>
                  {result.provider && <><dt>Provider</dt><dd>{result.provider}</dd></>}
                  {result.model && <><dt>Model</dt><dd class="font-mono">{result.model}</dd></>}
                  <dt>Use Case</dt><dd class="font-mono">{result.use_case}</dd>
                  <dt>Audit Event</dt><dd class="font-mono text-xs">{result.audit_event_id}</dd>
                  {typeof result.token_estimate === 'number' && (
                    <>
                      <dt>Tokens</dt>
                      <dd class="font-mono">{result.token_estimate.toLocaleString()}</dd>
                    </>
                  )}
                  {typeof result.cost_estimate_usd === 'number' && (
                    <>
                      <dt>Cost</dt>
                      <dd class="font-mono">${result.cost_estimate_usd.toFixed(5)}</dd>
                    </>
                  )}
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
