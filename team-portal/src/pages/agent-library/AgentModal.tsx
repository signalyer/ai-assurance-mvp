import { signal } from '@preact/signals';
import { useEffect } from 'preact/hooks';
import { apiGet, apiPost } from '../../shared/api/client';
import type { AgentDetail, AgentVersion, AgentSubscriber } from './types';

type Tab = 'overview' | 'versions' | 'subscribers' | 'publish';
type SseState = 'connecting' | 'open' | 'closed';

const openAgentId = signal<string | null>(null);
const currentAgent = signal<AgentDetail | null>(null);
const modalError = signal<string | null>(null);
const activeTab = signal<Tab>('overview');
const sseState = signal<SseState>('closed');

export function openAgent(id: string): void {
  openAgentId.value = id;
  activeTab.value = 'overview';
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
            {(['overview', 'versions', 'subscribers', 'publish'] as Tab[]).map((t) => (
              <div
                key={t}
                class={`modal-tab ${tab === t ? 'active' : ''}`}
                onClick={() => { activeTab.value = t; }}
              >
                {t === 'overview' ? 'Overview'
                  : t === 'versions' ? 'Version History'
                  : t === 'subscribers' ? 'Subscribers'
                  : 'Publish New Version'}
              </div>
            ))}
          </div>
          {modalError.value && <div class="error-banner">Failed to load agent: {modalError.value}</div>}
          {!a && !modalError.value && <div class="loading">Loading…</div>}
          {a && tab === 'overview' && <OverviewTab agent={a} />}
          {a && tab === 'versions' && <VersionsTab versions={a.versions ?? []} />}
          {a && tab === 'subscribers' && <SubscribersTab subscribers={a.subscribers ?? []} />}
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
  return (
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
