import { signal } from '@preact/signals';
import { useEffect } from 'preact/hooks';
import { Link } from 'wouter-preact';
import { apiGet } from '../../shared/api/client';

// S82f-2-extended W1: per-run drill. Backend route is the same record
// /agent-runs returns — GET /api/agent-runs/{run_id} per api/agent_runs.py.
// We re-fetch instead of passing through state so the page is link-shareable.
//
// Events seen in practice (see domain/agent_runner.py:177-578):
//   chain.start · policy_gate · scrub_pii · guardrails ·
//   llm.delta (many) · llm.done · evaluate · memory · audit ·
//   chain.done | chain.error
// llm.delta is rendered as one concatenated text block (the model's final
// answer) rather than per-token rows; everything else is a single row.

interface AnyEvent { event: string; [k: string]: unknown }

interface RunDetail {
  run_id: string;
  agent_id: string;
  system_id: string;
  user: string;
  started_at: string | null;
  ended_at: string | null;
  outcome: string;
  audit_id: string;
  operation_id: string;
  appinsights_url: string | null;
  langfuse_url: string | null;
  total_elapsed_ms: number;
  events: AnyEvent[];
}

const run = signal<RunDetail | null>(null);
const loading = signal<boolean>(false);
const loadError = signal<string | null>(null);

async function loadRun(runId: string): Promise<void> {
  loading.value = true;
  loadError.value = null;
  const r = await apiGet<RunDetail>(`/agent-runs/${encodeURIComponent(runId)}`);
  loading.value = false;
  if (r.ok) run.value = r.data;
  else loadError.value = r.detail;
}

function outcomeColor(o: string): string {
  switch (o) {
    case 'success': return 'var(--pass)';
    case 'failure':
    case 'error':
    case 'denied':
    case 'guardrail_block':
      return 'var(--critical)';
    case 'review': return 'var(--medium)';
    default: return 'var(--text-secondary)';
  }
}

function fmtMs(ms: number | null | undefined): string {
  if (ms == null) return '—';
  if (ms < 1000) return `${Number(ms).toFixed(0)} ms`;
  return `${(Number(ms) / 1000).toFixed(2)} s`;
}

function eventColor(ev: string): string {
  if (ev.startsWith('chain.error')) return 'var(--critical)';
  if (ev === 'policy_gate' || ev === 'guardrails') return 'var(--medium)';
  if (ev === 'audit' || ev === 'memory' || ev === 'evaluate') return 'var(--pass)';
  if (ev === 'llm.done' || ev === 'llm.delta') return 'var(--info, var(--text-secondary))';
  return 'var(--text-secondary)';
}

export function AgentRunDetailPage({ params }: { params: { run_id: string } }) {
  const runId = decodeURIComponent(params.run_id);

  useEffect(() => {
    void loadRun(runId);
  }, [runId]);

  const r = run.value;
  const events = r?.events ?? [];

  // Group deltas into the concatenated final answer; render everything else as
  // discrete timeline rows. Per agent_runner.py:444 llm.done carries the
  // model + token counts, so deltas are pure stream surface.
  const llmText = events
    .filter((e) => e.event === 'llm.delta')
    .map((e) => (typeof e.text === 'string' ? e.text : ''))
    .join('');
  const nonDelta = events.filter((e) => e.event !== 'llm.delta');

  return (
    <div class="page">
      <div class="page-header">
        <div>
          <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
            <Link href="/agent-runs">← All runs</Link>
          </div>
          <h1 class="page-title" style={{ fontSize: 20 }}>Run {runId}</h1>
          {r && (
            <div class="page-subtitle">
              <span class="font-mono">{r.agent_id}</span>
              {r.system_id ? <> · <span class="font-mono">{r.system_id}</span></> : null}
              {' · '}
              <span style={{ color: outcomeColor(r.outcome), fontWeight: 600 }}>{r.outcome}</span>
              {' · '}
              {fmtMs(r.total_elapsed_ms)}
            </div>
          )}
        </div>
        {r && (
          <div style={{ display: 'flex', gap: 8 }}>
            {r.langfuse_url && (
              <a class="btn btn-sm btn-secondary" href={r.langfuse_url} target="_blank" rel="noopener noreferrer">
                Langfuse trace
              </a>
            )}
            {r.appinsights_url && (
              <a class="btn btn-sm btn-secondary" href={r.appinsights_url} target="_blank" rel="noopener noreferrer">
                App Insights
              </a>
            )}
          </div>
        )}
      </div>

      {loadError.value && <div class="error-banner">Failed to load run: {loadError.value}</div>}
      {loading.value && !r && <div class="loading">Loading run…</div>}

      {r && (
        <>
          <section style={{ marginTop: 16 }}>
            <h2 style={{ fontSize: 14, marginBottom: 8 }}>Header</h2>
            <dl class="def-list">
              <dt>User</dt><dd>{r.user || '—'}</dd>
              <dt>Started</dt><dd>{r.started_at ? new Date(r.started_at).toLocaleString() : '—'}</dd>
              <dt>Ended</dt><dd>{r.ended_at ? new Date(r.ended_at).toLocaleString() : '—'}</dd>
              <dt>Outcome</dt>
              <dd style={{ color: outcomeColor(r.outcome), fontWeight: 600 }}>{r.outcome}</dd>
              <dt>Audit ID</dt><dd class="font-mono">{r.audit_id || '—'}</dd>
              <dt>Operation ID</dt><dd class="font-mono">{r.operation_id || '—'}</dd>
              <dt>Total elapsed</dt><dd>{fmtMs(r.total_elapsed_ms)}</dd>
            </dl>
          </section>

          <section style={{ marginTop: 24 }}>
            <h2 style={{ fontSize: 14, marginBottom: 8 }}>
              Chain events ({nonDelta.length})
            </h2>
            <table class="version-table">
              <thead>
                <tr><th>Step</th><th>Summary</th><th style={{ width: 90 }}>Elapsed</th></tr>
              </thead>
              <tbody>
                {nonDelta.map((e, i) => (
                  <tr key={i}>
                    <td class="font-mono" style={{ color: eventColor(e.event), fontWeight: 600, whiteSpace: 'nowrap' }}>
                      {e.event}
                    </td>
                    <td><EventSummary ev={e} /></td>
                    <td>{fmtMs(typeof e.elapsed_ms === 'number' ? e.elapsed_ms : null)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          {llmText && (
            <section style={{ marginTop: 24 }}>
              <h2 style={{ fontSize: 14, marginBottom: 8 }}>Model output (reconstructed from deltas)</h2>
              <pre style={{
                background: 'var(--bg-secondary, rgba(255,255,255,0.04))',
                padding: 12,
                borderRadius: 6,
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
                fontSize: 12,
                maxHeight: 480,
                overflow: 'auto',
              }}>{llmText}</pre>
            </section>
          )}
        </>
      )}
    </div>
  );
}

function EventSummary({ ev }: { ev: AnyEvent }) {
  switch (ev.event) {
    case 'chain.start':
      return <span style={{ color: 'var(--text-secondary)' }}>chain initialised</span>;
    case 'policy_gate':
      return (
        <span>
          <strong>{String(ev.decision ?? '?')}</strong>
          {ev.rule ? <> · rule <code>{String(ev.rule)}</code></> : null}
          {ev.reason ? <> — {String(ev.reason)}</> : null}
        </span>
      );
    case 'scrub_pii':
      return (
        <span>
          enabled={String(ev.scrubber_enabled)} · redacted={String(ev.redacted_count ?? 0)}
          {Array.isArray(ev.redacted_field_types) && ev.redacted_field_types.length
            ? <> · types: <code>{(ev.redacted_field_types as string[]).join(', ')}</code></>
            : null}
        </span>
      );
    case 'guardrails':
      return (
        <span>
          passed={String(ev.passed)}
          {Array.isArray(ev.violations) && ev.violations.length
            ? <> · violations: <code>{(ev.violations as string[]).join(', ')}</code></>
            : null}
          {ev.injection_score != null ? <> · injection={Number(ev.injection_score).toFixed(2)}</> : null}
        </span>
      );
    case 'llm.done':
      return (
        <span>
          model=<code>{String(ev.model ?? '?')}</code> ·{' '}
          in={String(ev.input_tokens ?? 0)} / out={String(ev.output_tokens ?? 0)} ·
          stop={String(ev.stop_reason ?? '?')} · turns={String(ev.turns ?? 0)} ·
          deltas={String(ev.delta_count ?? 0)}
        </span>
      );
    case 'evaluate':
      return (
        <span>
          metrics={String(ev.scored_metric_count ?? 0)}
          {typeof ev.avg_score === 'number' ? <> · avg={Number(ev.avg_score).toFixed(2)}</> : null}
          {ev.deferred_to_s85 ? <> · <em style={{ color: 'var(--text-tertiary)' }}>deferred to S85</em></> : null}
        </span>
      );
    case 'memory':
      return (
        <span>
          episode=<code>{String(ev.episode_id ?? '—')}</code> ·
          outcome=<strong>{String(ev.outcome ?? '?')}</strong>
          {ev.workload_id ? <> · workload=<code>{String(ev.workload_id)}</code></> : null}
        </span>
      );
    case 'audit':
      return (
        <span>
          audit=<code>{String(ev.audit_id ?? '?')}</code> ·
          decision={String(ev.decision ?? '?')}
          {ev.operation_id ? <> · op=<code>{String(ev.operation_id)}</code></> : null}
        </span>
      );
    case 'chain.done':
      return (
        <span>
          outcome=<strong>{String(ev.outcome ?? '?')}</strong>
          {ev.episode_id ? <> · episode=<code>{String(ev.episode_id)}</code></> : null}
        </span>
      );
    case 'chain.error':
      return (
        <span style={{ color: 'var(--critical)' }}>
          step={String(ev.step ?? '?')} · {String(ev.error_type ?? '?')}: {String(ev.message ?? '')}
        </span>
      );
    default:
      return <code style={{ fontSize: 11 }}>{JSON.stringify(ev).slice(0, 180)}</code>;
  }
}
