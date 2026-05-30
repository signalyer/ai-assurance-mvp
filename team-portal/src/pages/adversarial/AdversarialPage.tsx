// Adversarial probe runner — Team Workspace surface #5.
// First SSE-streaming surface in the portal: opens an EventSource to
// /api/adversarial/run and fills the results table one probe at a time
// (each probe blocks on a real LLM call; the suite takes 40-60s).
//
// Per Session 17 compound rule: write paths verified via direct fetch /
// EventSource in preview_eval, not synthetic input events. The Run button
// is the only user-triggered mutation; everything else is render-only.

import { signal, computed } from '@preact/signals';
import { useEffect } from 'preact/hooks';
import { apiGet } from '../../shared/api/client';
import type {
  CategoriesResponse,
  StreamEvent,
  ProbeEvent,
  Severity,
} from './types';

const PROVIDER_OPTIONS: Array<{ value: 'anthropic' | 'openai'; label: string }> = [
  { value: 'anthropic', label: 'Anthropic' },
  { value: 'openai', label: 'OpenAI' },
];

const DEFAULT_MODELS: Record<'anthropic' | 'openai', string> = {
  anthropic: 'claude-sonnet-4-6',
  openai: 'gpt-4o-mini',
};

const categories = signal<string[]>([]);
const totalProbes = signal<number>(0);
const catsLoading = signal<boolean>(true);
const catsError = signal<string | null>(null);

const selected = signal<Record<string, boolean>>({});
const provider = signal<'anthropic' | 'openai'>('anthropic');
const modelName = signal<string>(DEFAULT_MODELS.anthropic);

const running = signal<boolean>(false);
const startedAt = signal<number | null>(null);
const elapsedMs = signal<number>(0);
const probeResults = signal<ProbeEvent[]>([]);
const summary = signal<StreamEvent | null>(null);
const streamError = signal<string | null>(null);
const expectedTotal = signal<number>(0);

const completedCount = computed<number>(() => probeResults.value.length);

const selectedList = computed<string[]>(() =>
  Object.entries(selected.value).filter(([, v]) => v).map(([k]) => k),
);

const canRun = computed<boolean>(() => {
  if (running.value) return false;
  if (catsLoading.value || catsError.value) return false;
  if (selectedList.value.length === 0) return false;
  if (!modelName.value.trim()) return false;
  return true;
});

async function loadCategories(): Promise<void> {
  catsLoading.value = true;
  catsError.value = null;
  const r = await apiGet<CategoriesResponse>('/adversarial/categories');
  if (r.ok) {
    categories.value = r.data.categories;
    totalProbes.value = r.data.total_probes;
    // Select all by default
    const sel: Record<string, boolean> = {};
    for (const c of r.data.categories) sel[c] = true;
    selected.value = sel;
  } else {
    catsError.value = r.detail;
  }
  catsLoading.value = false;
}

function resetRun(): void {
  probeResults.value = [];
  summary.value = null;
  streamError.value = null;
  expectedTotal.value = 0;
  startedAt.value = Date.now();
  elapsedMs.value = 0;
}

// EventSource doesn't support POST. We use fetch + ReadableStream to consume
// the text/event-stream response and parse SSE frames manually. Same wire
// contract as EventSource, just without the GET-only constraint.
async function runSuite(): Promise<void> {
  if (!canRun.value) return;
  running.value = true;
  resetRun();

  const timer = setInterval(() => {
    if (startedAt.value) elapsedMs.value = Date.now() - startedAt.value;
  }, 250);

  try {
    const base = (import.meta.env.VITE_API_BASE_URL ?? '/api/v1').replace(/\/+$/, '');
    // credentials: 'include' is mandatory here. Team Portal lives at
    // portal.aigovern.sandboxhub.co; the engine answers at the apex
    // aigovern.sandboxhub.co. The default 'same-origin' silently drops the
    // session cookie cross-subdomain, producing a 401 in prod while dev
    // (single-origin Vite proxy) passes. Same shape as F-019
    // ([[raw-fetch-drifts-from-shared-client]]); every shared-client call
    // uses 'include' already. EventSource isn't an option (POST + body), so
    // we keep the raw fetch but match the shared client's credentials.
    const resp = await fetch(`${base}/adversarial/run`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify({
        model_provider: provider.value,
        model_name: modelName.value.trim(),
        categories: selectedList.value,
      }),
    });
    if (!resp.ok) {
      streamError.value = `HTTP ${resp.status} — ${await resp.text()}`;
      return;
    }
    if (!resp.body) {
      streamError.value = 'Response had no body to stream';
      return;
    }
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      // Process complete SSE frames (separated by \n\n)
      let idx: number;
      while ((idx = buf.indexOf('\n\n')) !== -1) {
        const frame = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        const dataLine = frame.split('\n').find((l) => l.startsWith('data: '));
        if (!dataLine) continue;
        try {
          const ev = JSON.parse(dataLine.slice(6)) as StreamEvent;
          handleEvent(ev);
        } catch (err) {
          console.warn('Failed to parse SSE frame', frame, err);
        }
      }
    }
  } catch (err) {
    streamError.value = err instanceof Error ? err.message : 'Stream failed';
  } finally {
    clearInterval(timer);
    running.value = false;
  }
}

function handleEvent(ev: StreamEvent): void {
  if (ev.event === 'start') {
    expectedTotal.value = ev.total_probes;
  } else if (ev.event === 'probe') {
    probeResults.value = [...probeResults.value, ev];
  } else if (ev.event === 'done') {
    summary.value = ev;
  } else if (ev.event === 'error') {
    streamError.value = ev.detail ? `${ev.message}: ${ev.detail}` : ev.message;
  }
}

// --- Helpers ---
function severityClass(s: Severity): string {
  if (s === 'CRITICAL') return 'critical';
  if (s === 'HIGH') return 'pill-failure';
  if (s === 'MEDIUM') return 'pill-review';
  return 'pill-success';
}

function resistClass(resisted: boolean | null): string {
  if (resisted === true) return 'pill-success';
  if (resisted === false) return 'pill-failure';
  return 'pill-review';
}

function resistLabel(resisted: boolean | null, error: string | null | undefined): string {
  if (error) return 'ERROR';
  if (resisted === true) return 'RESISTED';
  if (resisted === false) return 'BYPASSED';
  return '—';
}

function fmtSecs(ms: number): string {
  return `${(ms / 1000).toFixed(1)}s`;
}

function prettyCategory(c: string): string {
  return c.replace(/_/g, ' ');
}

export function AdversarialPage() {
  useEffect(() => { void loadCategories(); }, []);

  const cats = categories.value;
  const sumEv = summary.value;
  const sum = sumEv && sumEv.event === 'done' ? sumEv.summary : null;
  const expected = expectedTotal.value || (cats.length > 0
    ? cats.filter((c) => selected.value[c]).length
    : 0);
  const progressPct = expected > 0
    ? Math.min(100, Math.round((completedCount.value / expected) * 100))
    : 0;

  return (
    <div>
      <div class="page-header">
        <div>
          <div class="page-title">Adversarial Suite</div>
          <div class="page-subtitle">
            Probe a model with jailbreaks, prompt injections, data exfiltration attempts, harm generation, and compliance bypass prompts. Each probe is a real LLM call — a full suite takes ~40-60s and streams results probe-by-probe. Requires ANTHROPIC_API_KEY or OPENAI_API_KEY on the engine.
          </div>
        </div>
        <div class="page-actions">
          <button class="btn btn-sm" onClick={() => void loadCategories()} disabled={running.value}>
            Refresh categories
          </button>
        </div>
      </div>

      {catsError.value && <div class="error-banner">Failed to load categories: {catsError.value}</div>}

      <div class="card">
        <div class="card-header">
          <div>
            <div class="card-title">Configure run</div>
            <div class="card-subtitle">
              Pick categories to test. {totalProbes.value > 0 && `Full suite is ${totalProbes.value} probes across ${cats.length} categories.`}
            </div>
          </div>
        </div>
        <div style={{ padding: '0.875rem 1rem', display: 'grid', gap: '0.75rem' }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '0.5rem 1rem', alignItems: 'center' }}>
            <label style={{ fontSize: '11px', color: 'var(--text-secondary)', textTransform: 'uppercase' }}>
              Provider
            </label>
            <div style={{ display: 'inline-flex', gap: '0.375rem' }}>
              {PROVIDER_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  class={`btn btn-sm ${provider.value === opt.value ? 'btn-primary' : ''}`}
                  onClick={() => {
                    provider.value = opt.value;
                    modelName.value = DEFAULT_MODELS[opt.value];
                  }}
                  disabled={running.value}
                >
                  {opt.label}
                </button>
              ))}
            </div>
            <label style={{ fontSize: '11px', color: 'var(--text-secondary)', textTransform: 'uppercase' }}>
              Model
            </label>
            <input
              type="text"
              class="filter-select mono"
              style={{ width: '100%', maxWidth: '320px' }}
              value={modelName.value}
              maxLength={128}
              onInput={(e) => { modelName.value = (e.target as HTMLInputElement).value; }}
              disabled={running.value}
            />
          </div>

          <div>
            <div style={{ fontSize: '11px', color: 'var(--text-secondary)', textTransform: 'uppercase', marginBottom: '0.375rem' }}>
              Categories ({selectedList.value.length} of {cats.length} selected)
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: '0.5rem' }}>
              {cats.map((c) => (
                <label key={c} style={{
                  display: 'flex', alignItems: 'center', gap: '0.5rem',
                  padding: '0.5rem 0.75rem', border: '1px solid var(--border)',
                  borderRadius: '6px', fontSize: '13px', cursor: running.value ? 'not-allowed' : 'pointer',
                  opacity: running.value ? 0.6 : 1,
                }}>
                  <input
                    type="checkbox"
                    checked={!!selected.value[c]}
                    onChange={(e) => {
                      selected.value = { ...selected.value, [c]: (e.target as HTMLInputElement).checked };
                    }}
                    disabled={running.value}
                  />
                  <span style={{ textTransform: 'capitalize' }}>{prettyCategory(c)}</span>
                </label>
              ))}
            </div>
          </div>

          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.5rem', alignItems: 'center' }}>
            {running.value && (
              <span style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>
                Streaming · {completedCount.value}/{expected} probes · {fmtSecs(elapsedMs.value)} elapsed
              </span>
            )}
            <button
              class="btn btn-sm btn-primary"
              onClick={() => void runSuite()}
              disabled={!canRun.value}
            >
              {running.value ? 'Running…' : `Run ${selectedList.value.length} categor${selectedList.value.length === 1 ? 'y' : 'ies'}`}
            </button>
          </div>

          {expected > 0 && (running.value || completedCount.value > 0) && (
            <div style={{
              height: '6px', borderRadius: '3px', background: 'var(--border)', overflow: 'hidden',
            }}>
              <div style={{
                height: '100%', width: `${progressPct}%`,
                background: 'var(--accent)', transition: 'width 0.25s ease',
              }} />
            </div>
          )}

          {streamError.value && <div class="error-banner">Stream error: {streamError.value}</div>}
        </div>
      </div>

      {sum && (
        <div class="kpi-row">
          <div class="kpi-card">
            <div class="kpi-label">Security score</div>
            <div class="kpi-value">{(sum.security_score * 100).toFixed(1)}%</div>
            <div class="kpi-trend">{sum.resisted_count} resisted · {sum.failed_count} bypassed</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">Risk level</div>
            <div class="kpi-value">
              <span class={`pill ${severityClass(sum.risk_level)}`}>{sum.risk_level}</span>
            </div>
            <div class="kpi-trend">worst-severity failure</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">Critical failures</div>
            <div class="kpi-value critical">{sum.failed_by_severity.CRITICAL ?? 0}</div>
            <div class="kpi-trend">HIGH: {sum.failed_by_severity.HIGH ?? 0} · MED: {sum.failed_by_severity.MEDIUM ?? 0}</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">Model</div>
            <div class="kpi-value" style={{ fontSize: '14px', lineHeight: 1.4 }}>
              <span class="mono">{sum.model}</span>
            </div>
            <div class="kpi-trend">{sum.provider} · {sum.total_probes} probes</div>
          </div>
        </div>
      )}

      {(probeResults.value.length > 0 || running.value) && (
        <div class="card">
          <div class="card-header">
            <div>
              <div class="card-title">Probe results</div>
              <div class="card-subtitle">Streamed in order as the engine completes each probe.</div>
            </div>
          </div>
          {probeResults.value.length === 0 && running.value && (
            <div class="loading">Waiting for first probe to complete…</div>
          )}
          {probeResults.value.length > 0 && (
            <table class="data-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Category</th>
                  <th>Probe</th>
                  <th>Severity</th>
                  <th>Outcome</th>
                  <th>Confidence</th>
                  <th>Latency</th>
                  <th>Reason</th>
                </tr>
              </thead>
              <tbody>
                {probeResults.value.map((p) => (
                  <tr key={`${p.index}-${p.probe_name}`}>
                    <td><span class="mono">{p.index}/{p.total}</span></td>
                    <td style={{ textTransform: 'capitalize' }}>{prettyCategory(p.category)}</td>
                    <td>{p.probe_name}</td>
                    <td><span class={`pill ${severityClass(p.severity)}`}>{p.severity}</span></td>
                    <td>
                      <span class={`pill ${resistClass(p.resisted)}`}>
                        {resistLabel(p.resisted, p.error)}
                      </span>
                    </td>
                    <td>{p.confidence || '—'}</td>
                    <td><span class="mono">{p.latency_ms}ms</span></td>
                    <td style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                      {p.error ? <span class="critical">{p.error}</span> : (p.reason || '—')}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}
