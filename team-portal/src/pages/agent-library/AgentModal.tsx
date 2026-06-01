import { signal } from '@preact/signals';
import { useEffect } from 'preact/hooks';
import { apiGet, apiPost } from '../../shared/api/client';
import type { AgentDetail, AgentVersion, AgentSubscriber } from './types';

type Tab = 'overview' | 'versions' | 'subscribers' | 'eval' | 'publish';

// S82f-2-extended item 10 (E1): eval visibility. Shape mirrors
// GET /api/agents/{id}/eval-summary in api/agents.py.
interface EvalPerSystem { total: number; passed: number; pass_rate: number; }
interface EvalMetric {
  name?: string;
  score?: number;
  passed?: boolean;
  details?: string;
}
interface EvalCaseSummary {
  id: string | null;
  label: string | null;
  system: string;
  category: string | null;
  passed: boolean;
  overall_score: number | null;
  failures: string[];
  metrics?: EvalMetric[];
  metric_failures: EvalMetric[];
}
interface EvalRunSummary {
  run_id: string | null;
  timestamp: string | null;
  mode: string | null;
  status: string | null;
  cases_total: number | null;
  cases_passed: number | null;
  cases_null: number | null;
  pass_rate: number | null;
  datasets: string[];
  per_system: Record<string, EvalPerSystem>;
  cases?: EvalCaseSummary[];
}
interface EvalSummary {
  agent_id: string;
  has_eval_suite: boolean;
  baseline: EvalRunSummary | null;
  latest_run: EvalRunSummary | null;
  history: EvalRunSummary[];
  trend: { runs_total: number; runs_passed: number; pass_rate_mean: number };
}

const evalSummary = signal<EvalSummary | null>(null);
const evalLoading = signal<boolean>(false);
const evalError = signal<string | null>(null);
type SseState = 'connecting' | 'open' | 'closed';

const openAgentId = signal<string | null>(null);
const currentAgent = signal<AgentDetail | null>(null);
const modalError = signal<string | null>(null);
const activeTab = signal<Tab>('overview');
const sseState = signal<SseState>('closed');

export function openAgent(id: string): void {
  openAgentId.value = id;
  activeTab.value = 'overview';
  evalSummary.value = null;
  evalError.value = null;
}

async function loadEvalSummary(id: string, includeCases: 'none' | 'baseline' | 'latest' | 'both' = 'baseline'): Promise<void> {
  evalLoading.value = true;
  evalError.value = null;
  const r = await apiGet<EvalSummary>(
    `/agents/${encodeURIComponent(id)}/eval-summary`,
    { include_cases: includeCases },
  );
  evalLoading.value = false;
  if (r.ok) evalSummary.value = r.data;
  else evalError.value = r.detail;
}

function closeAgent(): void {
  openAgentId.value = null;
  currentAgent.value = null;
  modalError.value = null;
}

async function loadAgent(id: string): Promise<void> {
  currentAgent.value = null;
  modalError.value = null;
  const r = await apiGet<AgentDetail>(`/agents/${encodeURIComponent(id)}`);
  if (r.ok) currentAgent.value = r.data;
  else modalError.value = r.detail;
}

function ownerClass(t?: string): string {
  return t === 'REUSABLE' ? 'badge-reusable' : 'badge-custom';
}
function riskClass(r?: string): string {
  return `badge-risk-${r ?? 'MEDIUM'}`;
}

// SSE lifecycle (#19). Opens on modal open, closes on modal close.
// On agent_update event → reload agent detail (versions / subscribers
// may have changed via another tab or the SDK).
function useAgentSse(id: string | null): void {
  useEffect(() => {
    if (!id) {
      sseState.value = 'closed';
      return;
    }
    sseState.value = 'connecting';
    // VITE_API_BASE_URL defaults to /api/v1; mirror that for EventSource.
    const base = (import.meta.env.VITE_API_BASE_URL ?? '/api/v1').replace(/\/+$/, '');
    const es = new EventSource(`${base}/agents/${encodeURIComponent(id)}/listen`);

    es.onopen = () => { sseState.value = 'open'; };
    es.onerror = () => { sseState.value = 'closed'; };
    es.addEventListener('agent_update', () => { void loadAgent(id); });

    return () => { es.close(); sseState.value = 'closed'; };
  }, [id]);
}

export function AgentModal() {
  const id = openAgentId.value;

  useEffect(() => {
    if (id) void loadAgent(id);
  }, [id]);

  useAgentSse(id);

  if (!id) return null;

  const a = currentAgent.value;
  const tab = activeTab.value;
  const sse = sseState.value;
  const sseLabel = sse === 'open' ? 'Live updates connected'
    : sse === 'connecting' ? 'Connecting live updates…'
    : 'Live updates offline';
  const sseDotColor = sse === 'open' ? 'var(--pass)'
    : sse === 'connecting' ? 'var(--medium)'
    : 'var(--text-tertiary)';

  return (
    <div class="modal-overlay open" onClick={(e) => {
      if (e.target === e.currentTarget) closeAgent();
    }}>
      <div class="modal">
        <div class="modal-header">
          <div>
            <div class="modal-title">{a?.name ?? 'Loading…'}</div>
            {a && (
              <div class="agent-badges" style={{ marginTop: 4 }}>
                <span class={ownerClass(a.owner_type)}>{a.owner_type ?? ''}</span>
                <span class="badge-team">{a.team ?? ''}</span>
                <span class={riskClass(a.inherent_risk)}>{a.inherent_risk ?? ''}</span>
              </div>
            )}
          </div>
          <button class="modal-close" onClick={closeAgent} aria-label="Close">×</button>
        </div>
        <div class="modal-body">
          <div class="modal-tabs">
            {(['overview', 'versions', 'subscribers', 'eval', 'publish'] as Tab[]).map((t) => (
              <div
                key={t}
                class={`modal-tab ${tab === t ? 'active' : ''}`}
                onClick={() => {
                  activeTab.value = t;
                  if (t === 'eval' && a && evalSummary.value === null && !evalLoading.value) {
                    void loadEvalSummary(a.id, 'baseline');
                  }
                }}
              >
                {t === 'overview' ? 'Overview'
                  : t === 'versions' ? 'Version History'
                  : t === 'subscribers' ? 'Subscribers'
                  : t === 'eval' ? 'Eval'
                  : 'Publish New Version'}
              </div>
            ))}
          </div>
          {modalError.value && <div class="error-banner">Failed to load agent: {modalError.value}</div>}
          {!a && !modalError.value && <div class="loading">Loading…</div>}
          {a && tab === 'overview' && <OverviewTab agent={a} />}
          {a && tab === 'versions' && <VersionsTab versions={a.versions ?? []} />}
          {a && tab === 'subscribers' && <SubscribersTab subscribers={a.subscribers ?? []} />}
          {a && tab === 'eval' && <EvalTab />}
          {a && tab === 'publish' && <PublishTab agentId={a.id} />}
        </div>
        <div class="modal-footer">
          <span style={{ fontSize: 11, color: 'var(--text-tertiary)', display: 'flex', alignItems: 'center', gap: 6 }}>
            <span
              class="sse-dot"
              style={{
                display: 'inline-block',
                width: 8,
                height: 8,
                borderRadius: '50%',
                background: sseDotColor,
              }}
            />
            <span>{sseLabel}</span>
          </span>
          <div style={{ flex: 1 }} />
          <button class="btn btn-sm btn-secondary" onClick={closeAgent}>Close</button>
        </div>
      </div>
    </div>
  );
}

function OverviewTab({ agent: a }: { agent: AgentDetail }) {
  const lastPub = a.last_published_at
    ? new Date(a.last_published_at).toLocaleString()
    : '—';
  // Convention (matches domain/agent_runner.py:496 + agents/*/agent.py):
  // the agent's workload_id for episodic memory is the agent_id slug.
  // Deep-link to /memory / /agent-runs filtered to this agent.
  const memHref = `/memory?workload_id=${encodeURIComponent(a.id)}`;
  const runsHref = `/agent-runs?agent_id=${encodeURIComponent(a.id)}`;
  return (
    <>
      <dl class="def-list">
        <dt>ID</dt><dd class="font-mono">{a.id}</dd>
        <dt>Description</dt><dd>{a.description ?? '—'}</dd>
        <dt>Team</dt><dd>{a.team ?? '—'}</dd>
        <dt>Owner Type</dt><dd>{a.owner_type ?? '—'}</dd>
        <dt>Inherent Risk</dt><dd>{a.inherent_risk ?? '—'}</dd>
        <dt>Latest Version</dt><dd class="font-mono">{a.latest_semver ?? a.latest_version ?? '—'}</dd>
        <dt>Subscribers</dt><dd>{(a.subscribers ?? []).length}</dd>
        <dt>Last Published</dt><dd>{lastPub}</dd>
        <dt>Status</dt><dd>{a.status ?? '—'}</dd>
      </dl>
      <div style={{ display: 'flex', gap: 8, marginTop: 12, flexWrap: 'wrap' }}>
        <a class="btn btn-sm btn-secondary" href={memHref}>View episodic memory →</a>
        <a class="btn btn-sm btn-secondary" href={runsHref}>View past runs →</a>
      </div>
    </>
  );
}

function VersionsTab({ versions }: { versions: AgentVersion[] }) {
  if (versions.length === 0) {
    return <div class="empty-state">No versions published yet.</div>;
  }
  return (
    <table class="version-table">
      <thead>
        <tr><th>Semver</th><th>Status</th><th>Published At</th><th>Changelog</th></tr>
      </thead>
      <tbody>
        {versions.map((v, i) => {
          const pubAt = v.published_at ? new Date(v.published_at).toLocaleString() : '—';
          const color = v.status === 'PUBLISHED' ? 'var(--pass)' : 'var(--text-secondary)';
          return (
            <tr key={i}>
              <td class="font-mono">{v.semver ?? v.version ?? ''}</td>
              <td style={{ color }}>{v.status ?? ''}</td>
              <td>{pubAt}</td>
              <td style={{ maxWidth: 250, wordBreak: 'break-word' }}>{v.changelog ?? '—'}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function SubscribersTab({ subscribers }: { subscribers: AgentSubscriber[] }) {
  if (subscribers.length === 0) {
    return <div class="empty-state">No subscribers yet.</div>;
  }
  return (
    <table class="version-table">
      <thead>
        <tr><th>System</th><th>Version</th><th>Pin Mode</th><th>Upgrade</th></tr>
      </thead>
      <tbody>
        {subscribers.map((s, i) => (
          <tr key={i}>
            <td>{s.system_id ?? s.system_name ?? ''}</td>
            <td class="font-mono">{s.pinned_version ?? s.version_id ?? '—'}</td>
            <td>
              {s.pinned
                ? <span style={{ color: 'var(--medium)' }}>Pinned</span>
                : <span style={{ color: 'var(--pass)' }}>Auto</span>}
            </td>
            <td>
              {s.upgrade_available_version_id ? (
                <div class="upgrade-banner" style={{ marginTop: 4 }}>
                  New version available
                  <span style={{ fontSize: 10, opacity: 0.7 }}>
                    {s.upgrade_available_version_id}
                  </span>
                </div>
              ) : '—'}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// Eval tab (S82f-2-extended item 10 / E1). Reads
// GET /api/agents/{id}/eval-summary. has_eval_suite=false renders an honest
// "no eval suite — demo-only agent" affordance rather than blanking.
function EvalTab() {
  const sum = evalSummary.value;
  if (evalLoading.value && !sum) {
    return <div class="loading">Loading eval summary…</div>;
  }
  if (evalError.value) {
    return <div class="error-banner">Failed to load eval summary: {evalError.value}</div>;
  }
  if (!sum) return null;
  if (!sum.has_eval_suite) {
    return (
      <div class="empty-state">
        <div style={{ fontWeight: 600, marginBottom: 4 }}>No eval suite</div>
        <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
          This agent has no <code>agents/{sum.agent_id}/eval/baseline.json</code> and
          no recorded suite runs. Typically a demo-only agent that has not
          completed Phase 4 of <code>docs/SOP-agent-onboarding.md</code>.
        </div>
      </div>
    );
  }
  const baseline = sum.baseline;
  const latest = sum.latest_run;
  return (
    <div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <RunCard title="Baseline (locked)" run={baseline} />
        <RunCard title="Latest run" run={latest} />
      </div>
      <div style={{ marginTop: 16, fontSize: 12, color: 'var(--text-secondary)' }}>
        <strong>Trend:</strong>{' '}
        {sum.trend.runs_passed}/{sum.trend.runs_total} runs PASS · mean pass
        rate {fmtPct(sum.trend.pass_rate_mean)}
      </div>
      {baseline?.cases && baseline.cases.length > 0 && (
        <section style={{ marginTop: 16 }}>
          <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 6 }}>
            Baseline cases ({baseline.cases.length})
          </div>
          <CasesTable cases={baseline.cases} />
        </section>
      )}
      {sum.history.length > 0 && (
        <>
          <div style={{ marginTop: 16, fontWeight: 600, fontSize: 13 }}>
            Recent runs ({sum.history.length})
          </div>
          <table class="version-table" style={{ marginTop: 8 }}>
            <thead>
              <tr>
                <th>When</th>
                <th>Mode</th>
                <th>Status</th>
                <th>Passed</th>
                <th>Pass rate</th>
              </tr>
            </thead>
            <tbody>
              {sum.history.map((r, i) => (
                <tr key={r.run_id ?? i}>
                  <td>{r.timestamp ? new Date(r.timestamp).toLocaleString() : '—'}</td>
                  <td>{r.mode ?? '—'}</td>
                  <td style={{ color: r.status === 'PASS' ? 'var(--pass)' : 'var(--medium)' }}>
                    {r.status ?? '—'}
                  </td>
                  <td>{r.cases_passed ?? '—'} / {r.cases_total ?? '—'}</td>
                  <td>{fmtPct(r.pass_rate ?? 0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}

function RunCard({ title, run }: { title: string; run: EvalRunSummary | null }) {
  if (!run) {
    return (
      <div style={{ border: '1px solid var(--border)', borderRadius: 6, padding: 12 }}>
        <div style={{ fontWeight: 600, marginBottom: 4 }}>{title}</div>
        <div style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>None recorded.</div>
      </div>
    );
  }
  const statusColor = run.status === 'PASS' ? 'var(--pass)' : 'var(--medium)';
  return (
    <div style={{ border: '1px solid var(--border)', borderRadius: 6, padding: 12 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
        <div style={{ fontWeight: 600 }}>{title}</div>
        <div style={{ color: statusColor, fontSize: 12, fontWeight: 600 }}>{run.status ?? '—'}</div>
      </div>
      <div style={{ fontSize: 11, color: 'var(--text-tertiary)', marginTop: 2 }}>
        {run.timestamp ? new Date(run.timestamp).toLocaleString() : '—'}
        {run.mode ? ` · ${run.mode}` : ''}
      </div>
      <div style={{ marginTop: 8, fontSize: 13 }}>
        <span style={{ fontWeight: 600 }}>{run.cases_passed ?? '—'}</span>
        <span style={{ color: 'var(--text-secondary)' }}> / {run.cases_total ?? '—'} cases</span>
        <span style={{ marginLeft: 8, color: 'var(--text-secondary)' }}>
          ({fmtPct(run.pass_rate ?? 0)})
        </span>
      </div>
      {Object.keys(run.per_system).length > 0 && (
        <table class="version-table" style={{ marginTop: 8, fontSize: 12 }}>
          <thead>
            <tr><th>System</th><th>Passed</th><th>Rate</th></tr>
          </thead>
          <tbody>
            {Object.entries(run.per_system).map(([sys, m]) => (
              <tr key={sys}>
                <td class="font-mono">{sys}</td>
                <td>{m.passed} / {m.total}</td>
                <td>{fmtPct(m.pass_rate)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function fmtPct(x: number): string {
  return `${(x * 100).toFixed(1)}%`;
}

const expandedCases = signal<Set<string>>(new Set());

function toggleCase(id: string): void {
  const next = new Set(expandedCases.value);
  if (next.has(id)) next.delete(id); else next.add(id);
  expandedCases.value = next;
}

function expandAll(cases: EvalCaseSummary[]): void {
  expandedCases.value = new Set(cases.map((c) => c.id ?? c.label ?? ''));
}

function collapseAll(): void {
  expandedCases.value = new Set();
}

export function CasesTable({ cases }: { cases: EvalCaseSummary[] }) {
  const expanded = expandedCases.value;
  return (
    <div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 6, fontSize: 11 }}>
        <button class="btn btn-xs btn-secondary" onClick={() => expandAll(cases)}>Expand all</button>
        <button class="btn btn-xs btn-secondary" onClick={collapseAll}>Collapse all</button>
        <span style={{ color: 'var(--text-tertiary)', alignSelf: 'center' }}>
          Click a case to drill into every metric.
        </span>
      </div>
      <table class="version-table">
        <thead>
          <tr>
            <th style={{ width: 20 }}></th>
            <th>Case</th>
            <th>System</th>
            <th>Category</th>
            <th>Passed</th>
            <th>Score</th>
            <th>Failures</th>
          </tr>
        </thead>
        <tbody>
          {cases.map((c) => {
            const key = c.id ?? c.label ?? '';
            const isOpen = expanded.has(key);
            return (
              <>
                <tr
                  key={key}
                  style={{ cursor: 'pointer' }}
                  onClick={() => toggleCase(key)}
                >
                  <td style={{ color: 'var(--text-tertiary)', textAlign: 'center' }}>
                    {isOpen ? '▾' : '▸'}
                  </td>
                  <td>
                    <div class="font-mono" style={{ fontSize: 11 }}>{c.id ?? '—'}</div>
                    <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>{c.label ?? ''}</div>
                  </td>
                  <td class="font-mono" style={{ fontSize: 11 }}>{c.system}</td>
                  <td>{c.category ?? '—'}</td>
                  <td style={{ color: c.passed ? 'var(--pass)' : 'var(--critical)', fontWeight: 600 }}>
                    {c.passed ? 'PASS' : 'FAIL'}
                  </td>
                  <td>{typeof c.overall_score === 'number' ? c.overall_score.toFixed(2) : '—'}</td>
                  <td>
                    {c.metric_failures.length === 0 ? (
                      <span style={{ color: 'var(--text-tertiary)' }}>—</span>
                    ) : (
                      <span style={{ color: 'var(--critical)' }}>
                        {c.metric_failures.length} metric{c.metric_failures.length === 1 ? '' : 's'} failed
                      </span>
                    )}
                  </td>
                </tr>
                {isOpen && (
                  <tr key={`${key}-detail`}>
                    <td></td>
                    <td colSpan={6} style={{ background: 'var(--bg-secondary, rgba(255,255,255,0.04))' }}>
                      <CaseDetail c={c} />
                    </td>
                  </tr>
                )}
              </>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function CaseDetail({ c }: { c: EvalCaseSummary }) {
  const metrics = c.metrics ?? c.metric_failures;
  return (
    <div style={{ padding: '8px 4px' }}>
      {c.failures.length > 0 && (
        <div style={{ marginBottom: 8 }}>
          <div style={{ fontWeight: 600, fontSize: 12, color: 'var(--critical)' }}>
            Top-level failures
          </div>
          <ul style={{ margin: '4px 0 0 0', paddingLeft: 16, fontSize: 11 }}>
            {c.failures.map((f, i) => <li key={i}>{f}</li>)}
          </ul>
        </div>
      )}
      <div style={{ fontWeight: 600, fontSize: 12, marginBottom: 4 }}>
        Metrics ({metrics.length})
      </div>
      <table class="version-table" style={{ fontSize: 11 }}>
        <thead>
          <tr>
            <th>Metric</th>
            <th style={{ width: 60 }}>Score</th>
            <th style={{ width: 60 }}>Pass</th>
            <th>Details</th>
          </tr>
        </thead>
        <tbody>
          {metrics.map((m, i) => (
            <tr key={i}>
              <td class="font-mono">{m.name ?? '?'}</td>
              <td>{typeof m.score === 'number' ? m.score.toFixed(2) : '—'}</td>
              <td style={{
                color: m.passed ? 'var(--pass)' : 'var(--critical)',
                fontWeight: 600,
              }}>
                {m.passed ? 'PASS' : 'FAIL'}
              </td>
              <td>{m.details ?? '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// Publish New Version form (#18). POST /agents/{id}/publish.
// Semver MAJOR.MINOR.PATCH per api/agents.py:130 regex.
const publishSemver = signal<string>('');
const publishChangelog = signal<string>('');
const publishSaving = signal<boolean>(false);
const publishError = signal<string | null>(null);
const publishSuccess = signal<string | null>(null);

function PublishTab({ agentId }: { agentId: string }) {
  async function submit(): Promise<void> {
    publishError.value = null;
    publishSuccess.value = null;
    if (!/^\d+\.\d+\.\d+/.test(publishSemver.value.trim())) {
      publishError.value = 'Semver must be MAJOR.MINOR.PATCH (e.g. 1.2.0).';
      return;
    }
    publishSaving.value = true;
    const r = await apiPost(`/agents/${encodeURIComponent(agentId)}/publish`, {
      semver: publishSemver.value.trim(),
      changelog: publishChangelog.value.trim(),
      config: {},
    });
    publishSaving.value = false;
    if (r.ok) {
      publishSuccess.value = `Published v${publishSemver.value.trim()}`;
      publishSemver.value = '';
      publishChangelog.value = '';
      // Refresh agent detail to surface the new version in the Versions tab.
      void loadAgent(agentId);
    } else {
      publishError.value = `Publish failed: ${r.detail}`;
    }
  }

  return (
    <div>
      {publishError.value && <div class="error-banner">{publishError.value}</div>}
      {publishSuccess.value && (
        <div class="badge badge-pass" style={{ display: 'inline-block', padding: '4px 8px', marginBottom: 8 }}>
          {publishSuccess.value}
        </div>
      )}
      <div class="form-row">
        <label class="form-label">Semver (MAJOR.MINOR.PATCH) <span style={{ color: 'var(--critical)' }}>*</span></label>
        <input
          class="form-input font-mono"
          placeholder="1.2.0"
          value={publishSemver.value}
          onInput={(e) => { publishSemver.value = (e.currentTarget as HTMLInputElement).value; }}
        />
      </div>
      <div class="form-row">
        <label class="form-label">Changelog</label>
        <textarea
          class="form-input"
          rows={4}
          placeholder="What changed in this version?"
          value={publishChangelog.value}
          onInput={(e) => { publishChangelog.value = (e.currentTarget as HTMLTextAreaElement).value; }}
        />
      </div>
      <button class="btn btn-sm btn-primary" disabled={publishSaving.value} onClick={() => void submit()}>
        {publishSaving.value ? 'Publishing…' : 'Publish Version'}
      </button>
    </div>
  );
}
