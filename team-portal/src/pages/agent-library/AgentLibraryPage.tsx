import { signal, computed } from '@preact/signals';
import { useEffect } from 'preact/hooks';
import { apiGet } from '../../shared/api/client';
import type { AgentSummary } from './types';
import { AgentModal, openAgent } from './AgentModal';
import { AgentCreateModal, openCreateAgent, registerAgentsReload } from './AgentCreateModal';

type OwnerFilter = '' | 'REUSABLE' | 'CUSTOM';

const allAgents = signal<AgentSummary[]>([]);
const loading = signal<boolean>(true);
const loadError = signal<string | null>(null);
const searchTerm = signal<string>('');
const teamFilter = signal<string>('');
const ownerFilter = signal<OwnerFilter>('');

const teams = computed<string[]>(() => {
  const set = new Set<string>();
  for (const a of allAgents.value) if (a.team) set.add(a.team);
  return Array.from(set).sort();
});

const filtered = computed<AgentSummary[]>(() => {
  const term = searchTerm.value.toLowerCase();
  const team = teamFilter.value;
  const owner = ownerFilter.value;
  return allAgents.value.filter((a) => {
    if (term) {
      const hay = `${a.name ?? ''} ${a.team ?? ''} ${a.description ?? ''}`.toLowerCase();
      if (!hay.includes(term)) return false;
    }
    if (team && a.team !== team) return false;
    if (owner && a.owner_type !== owner) return false;
    return true;
  });
});

async function loadAgents(): Promise<void> {
  loading.value = true;
  loadError.value = null;
  const r = await apiGet<AgentSummary[]>('/agents');
  if (r.ok) {
    allAgents.value = Array.isArray(r.data) ? r.data : [];
  } else {
    loadError.value = r.detail;
  }
  loading.value = false;
}

export function AgentLibraryPage() {
  useEffect(() => {
    registerAgentsReload(loadAgents);
    void loadAgents();
  }, []);
  const rows = filtered.value;

  return (
    <div>
      <div class="page-header">
        <div>
          <div class="page-title">Agent Library</div>
          <div class="page-subtitle">Publish, subscribe, and govern reusable AI agents across systems</div>
        </div>
        <div class="page-actions">
          <button class="btn btn-sm btn-primary" onClick={openCreateAgent}>
            + Register Agent
          </button>
        </div>
      </div>

      <div class="chip-row">
        <Chip value="" current={ownerFilter.value} label="All" />
        <Chip value="REUSABLE" current={ownerFilter.value} label="Reusable" />
        <Chip value="CUSTOM" current={ownerFilter.value} label="Custom" />
      </div>

      <div class="filter-bar" style={{ marginBottom: '1rem' }}>
        <input
          class="filter-input"
          type="text"
          placeholder="Search agents…"
          value={searchTerm.value}
          onInput={(e) => (searchTerm.value = (e.currentTarget as HTMLInputElement).value)}
        />
        <select
          class="filter-select"
          value={teamFilter.value}
          onChange={(e) => (teamFilter.value = (e.currentTarget as HTMLSelectElement).value)}
        >
          <option value="">All teams</option>
          {teams.value.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
      </div>

      {loadError.value && <div class="error-banner">Failed to load agents: {loadError.value}</div>}

      {loading.value && <div class="loading">Loading agents…</div>}
      {!loading.value && rows.length === 0 && !loadError.value && (
        <div class="empty-state">No agents match filters.</div>
      )}

      {!loading.value && rows.length > 0 && (
        <div class="agent-grid">
          {rows.map((a) => <AgentCard key={a.id} agent={a} />)}
        </div>
      )}

      <AgentModal />
      <AgentCreateModal />
    </div>
  );
}

function Chip({ value, current, label }: { value: OwnerFilter; current: OwnerFilter; label: string }) {
  const isActive = current === value;
  return (
    <span
      class={`chip ${isActive ? 'active' : ''}`}
      onClick={() => { ownerFilter.value = value; }}
    >
      {label}
    </span>
  );
}

function AgentCard({ agent: a }: { agent: AgentSummary }) {
  const ownerCls = a.owner_type === 'REUSABLE' ? 'badge-reusable' : 'badge-custom';
  const riskCls = `badge-risk-${a.inherent_risk ?? 'MEDIUM'}`;
  const semver = a.latest_semver ?? a.latest_version ?? '—';
  const subCount = typeof a.subscriber_count === 'number' ? a.subscriber_count : 0;
  const lastPub = a.last_published_at
    ? new Date(a.last_published_at).toLocaleDateString()
    : '—';
  const desc = a.description ?? '';
  const truncated = desc.length > 80 ? `${desc.slice(0, 80)}…` : desc;

  return (
    <div class="agent-card" onClick={() => openAgent(a.id)}>
      <div class="agent-card-header">
        <div class="agent-name">{a.name ?? ''}</div>
      </div>
      <div class="agent-badges">
        <span class={ownerCls}>{a.owner_type ?? ''}</span>
        <span class="badge-team">{a.team ?? ''}</span>
        <span class={riskCls}>{a.inherent_risk ?? ''}</span>
      </div>
      <div style={{ fontSize: 11, color: 'var(--text-secondary)', marginTop: 6, lineHeight: 1.4 }}>
        {truncated}
      </div>
      <div class="agent-meta">
        <span>v {semver}</span>
        <span>{subCount} subscriber{subCount !== 1 ? 's' : ''}</span>
        <span>Published {lastPub}</span>
      </div>
    </div>
  );
}
