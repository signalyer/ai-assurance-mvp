import { signal, computed } from '@preact/signals';
import { useEffect } from 'preact/hooks';
import { apiGet } from '../../shared/api/client';

// S82f-2-extended item 4: history surface for past agent runs.
// Backend: GET /api/agent-runs (paged, newest-first) — see api/agent_runs.py.
// Shape mirrors the persisted row written by api.agent_runner._gen on
// chain.done. The `events` array can be large per row; we render the
// headline only and let the operator drill into a single run via the
// audit / Langfuse links the row already carries.

interface RunRow {
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
}

interface RunsEnvelope {
  count: number;
  runs: RunRow[];
}

const runs = signal<RunRow[]>([]);
const loading = signal<boolean>(false);
const loadError = signal<string | null>(null);
const filterAgent = signal<string>('');
const filterSystem = signal<string>('');
const limit = signal<number>(50);

const hasData = computed(() => runs.value.length > 0);

async function loadRuns(): Promise<void> {
  loading.value = true;
  loadError.value = null;
  const query: Record<string, string | number | boolean | undefined> = {
    limit: limit.value,
    agent_id: filterAgent.value.trim() || undefined,
    system_id: filterSystem.value.trim() || undefined,
  };
  const r = await apiGet<RunsEnvelope>('/agent-runs', query);
  loading.value = false;
  if (r.ok) runs.value = r.data.runs;
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

function fmtElapsed(ms: number | null | undefined): string {
  if (ms == null) return '—';
  if (ms < 1000) return `${ms.toFixed(0)} ms`;
  return `${(ms / 1000).toFixed(2)} s`;
}

export function AgentRunsPage() {
  useEffect(() => {
    void loadRuns();
    // Guard per [[never-blank-on-refresh]] — initial load only.
    // Operator can re-trigger via the Refresh button.
  }, []);

  const rows = runs.value;

  return (
    <div class="page">
      <div class="page-header">
        <div>
          <h1 class="page-title">Agent Runs</h1>
          <div class="page-subtitle">Past streamed agent executions, newest first.</div>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end' }}>
          <div>
            <label class="form-label" style={{ fontSize: 11 }}>Agent ID</label>
            <input
              class="form-input"
              style={{ width: 160 }}
              placeholder="e.g. vendor_risk"
              value={filterAgent.value}
              onInput={(e) => { filterAgent.value = (e.currentTarget as HTMLInputElement).value; }}
            />
          </div>
          <div>
            <label class="form-label" style={{ fontSize: 11 }}>System ID</label>
            <input
              class="form-input"
              style={{ width: 200 }}
              placeholder="sys-…"
              value={filterSystem.value}
              onInput={(e) => { filterSystem.value = (e.currentTarget as HTMLInputElement).value; }}
            />
          </div>
          <div>
            <label class="form-label" style={{ fontSize: 11 }}>Limit</label>
            <input
              class="form-input"
              type="number"
              min={1}
              max={500}
              style={{ width: 80 }}
              value={limit.value}
              onInput={(e) => {
                const n = Number((e.currentTarget as HTMLInputElement).value);
                if (Number.isFinite(n) && n > 0) limit.value = n;
              }}
            />
          </div>
          <button class="btn btn-sm btn-primary" disabled={loading.value} onClick={() => void loadRuns()}>
            {loading.value ? 'Loading…' : 'Refresh'}
          </button>
        </div>
      </div>

      {loadError.value && <div class="error-banner">Failed to load runs: {loadError.value}</div>}
      {loading.value && !hasData.value && <div class="loading">Loading agent runs…</div>}
      {!loading.value && !loadError.value && !hasData.value && (
        <div class="empty-state">
          No runs match. Trigger one from <code>/agent-runner</code> and refresh.
        </div>
      )}

      {hasData.value && (
        <table class="version-table">
          <thead>
            <tr>
              <th>Started</th>
              <th>Agent</th>
              <th>System</th>
              <th>User</th>
              <th>Outcome</th>
              <th>Elapsed</th>
              <th>Run ID</th>
              <th>Audit</th>
              <th>Links</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.run_id}>
                <td>{r.started_at ? new Date(r.started_at).toLocaleString() : '—'}</td>
                <td class="font-mono">{r.agent_id}</td>
                <td class="font-mono" style={{ fontSize: 11 }}>{r.system_id || '—'}</td>
                <td>{r.user || '—'}</td>
                <td style={{ color: outcomeColor(r.outcome), fontWeight: 600 }}>{r.outcome}</td>
                <td>{fmtElapsed(r.total_elapsed_ms)}</td>
                <td class="font-mono" style={{ fontSize: 10 }}>{r.run_id}</td>
                <td class="font-mono" style={{ fontSize: 10 }}>{r.audit_id || '—'}</td>
                <td style={{ display: 'flex', gap: 6 }}>
                  {r.langfuse_url && (
                    <a href={r.langfuse_url} target="_blank" rel="noopener noreferrer" style={{ fontSize: 11 }}>Langfuse</a>
                  )}
                  {r.appinsights_url && (
                    <a href={r.appinsights_url} target="_blank" rel="noopener noreferrer" style={{ fontSize: 11 }}>App Insights</a>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
