import { signal } from '@preact/signals';
import { useEffect } from 'preact/hooks';
import { apiGet } from '../../shared/api/client';
import type { AgentDetail, AgentVersion, AgentSubscriber } from './types';

type Tab = 'overview' | 'versions' | 'subscribers' | 'publish';

const openAgentId = signal<string | null>(null);
const currentAgent = signal<AgentDetail | null>(null);
const modalError = signal<string | null>(null);
const activeTab = signal<Tab>('overview');

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

export function AgentModal() {
  const id = openAgentId.value;

  useEffect(() => {
    if (id) void loadAgent(id);
  }, [id]);

  if (!id) return null;

  const a = currentAgent.value;
  const tab = activeTab.value;

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
          {a && tab === 'publish' && <PublishTabStub />}
        </div>
        <div class="modal-footer">
          <span style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>
            {/* V1 SSE live-update indicator deferred (Task #18). */}
            <span class="sse-dot" />
            <span>Live updates disabled</span>
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

function PublishTabStub() {
  return (
    <div class="empty-state">
      Publish New Version form — pending Phase 2 follow-up (Task #17).
    </div>
  );
}
