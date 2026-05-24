// Bound Agents panel for one AI system. Opens via openBoundAgents(id).
// Engine: /api/v1/systems/{id}/bindings (GET/POST/PATCH/DELETE).
// Read paths shipped; write paths (bind / pin / unbind / accept-upgrade)
// inline. Add-agent picker pulls /agents and offers unbound agents only.

import { signal, computed } from '@preact/signals';
import { useEffect } from 'preact/hooks';
import { apiRequest, apiGet, apiDelete, apiPost } from '../../shared/api/client';

interface Binding {
  id: string;
  system_id: string;
  agent_id: string;
  version_id?: string | null;
  pinned?: boolean;
  agent_name?: string;
  agent_team?: string;
  agent_owner_type?: string;
  version_semver?: string;
  upgrade_available_version_id?: string | null;
}

interface AgentSummary {
  id: string;
  name: string;
  team?: string;
  owner_type?: string;
  inherent_risk?: string;
  latest_version_id?: string | null;
}

const openSystemId = signal<string | null>(null);
const bindings = signal<Binding[]>([]);
const agents = signal<AgentSummary[]>([]);
const loadError = signal<string | null>(null);
const loading = signal<boolean>(false);
const actionError = signal<string | null>(null);
const actionBusy = signal<string | null>(null); // binding_id or '__add__' during mutation
const showAddPicker = signal<boolean>(false);
const selectedNewAgent = signal<string>('');

const unboundAgents = computed<AgentSummary[]>(() => {
  const bound = new Set(bindings.value.map((b) => b.agent_id));
  return agents.value.filter((a) => !bound.has(a.id));
});

export function openBoundAgents(id: string): void {
  openSystemId.value = id;
  showAddPicker.value = false;
  selectedNewAgent.value = '';
  actionError.value = null;
}

function closeBoundAgents(): void {
  openSystemId.value = null;
  bindings.value = [];
  agents.value = [];
  loadError.value = null;
  actionError.value = null;
  showAddPicker.value = false;
}

async function loadAll(systemId: string): Promise<void> {
  loading.value = true;
  loadError.value = null;
  bindings.value = [];
  const [bRes, aRes] = await Promise.all([
    apiGet<Binding[]>(`/systems/${encodeURIComponent(systemId)}/bindings`),
    apiGet<AgentSummary[]>(`/agents`),
  ]);
  if (bRes.ok) bindings.value = bRes.data ?? [];
  else loadError.value = `bindings: ${bRes.detail}`;
  if (aRes.ok) agents.value = aRes.data ?? [];
  else loadError.value = (loadError.value ?? '') + ` agents: ${aRes.detail}`;
  loading.value = false;
}

async function addBinding(): Promise<void> {
  const sid = openSystemId.value;
  const aid = selectedNewAgent.value;
  if (!sid || !aid) return;
  actionBusy.value = '__add__';
  actionError.value = null;
  const r = await apiPost<Binding>(`/systems/${encodeURIComponent(sid)}/bindings`, {
    agent_id: aid,
    pinned: false,
  });
  actionBusy.value = null;
  if (!r.ok) {
    actionError.value = r.detail;
    return;
  }
  showAddPicker.value = false;
  selectedNewAgent.value = '';
  await loadAll(sid);
}

async function togglePin(b: Binding): Promise<void> {
  const sid = openSystemId.value;
  if (!sid) return;
  actionBusy.value = b.id;
  actionError.value = null;
  const r = await apiRequest<Binding>(
    `/systems/${encodeURIComponent(sid)}/bindings/${encodeURIComponent(b.id)}`,
    { method: 'PATCH', body: { pinned: !b.pinned } },
  );
  actionBusy.value = null;
  if (!r.ok) {
    actionError.value = r.detail;
    return;
  }
  await loadAll(sid);
}

async function acceptUpgrade(b: Binding): Promise<void> {
  const sid = openSystemId.value;
  if (!sid) return;
  actionBusy.value = b.id;
  actionError.value = null;
  const r = await apiRequest<Binding>(
    `/systems/${encodeURIComponent(sid)}/bindings/${encodeURIComponent(b.id)}`,
    { method: 'PATCH', body: { accept_upgrade: true } },
  );
  actionBusy.value = null;
  if (!r.ok) {
    actionError.value = r.detail;
    return;
  }
  await loadAll(sid);
}

async function unbind(b: Binding): Promise<void> {
  const sid = openSystemId.value;
  if (!sid) return;
  if (!confirm(`Unbind ${b.agent_name ?? b.agent_id}?`)) return;
  actionBusy.value = b.id;
  actionError.value = null;
  const r = await apiDelete<void>(
    `/systems/${encodeURIComponent(sid)}/bindings/${encodeURIComponent(b.id)}`,
  );
  actionBusy.value = null;
  if (!r.ok) {
    actionError.value = r.detail;
    return;
  }
  await loadAll(sid);
}

export function AiSystemBoundAgentsPanel() {
  const id = openSystemId.value;

  useEffect(() => {
    if (id) void loadAll(id);
  }, [id]);

  if (!id) return null;

  const rows = bindings.value;
  const candidates = unboundAgents.value;

  return (
    <>
      <div class="drawer-overlay open" onClick={closeBoundAgents} />
      <aside class="drawer open" aria-hidden={false} style={{ width: 680 }}>
        <div class="drawer-header">
          <div class="drawer-title">Bound Agents</div>
          <button class="drawer-close" onClick={closeBoundAgents} aria-label="Close">×</button>
        </div>
        <div class="drawer-body">
          <div class="text-xs text-tertiary" style={{ marginBottom: 12 }}>
            System <span class="font-mono">{id}</span> · {rows.length} binding{rows.length === 1 ? '' : 's'}
          </div>

          {loading.value && <div class="loading">Loading…</div>}
          {loadError.value && <div class="error-banner">Failed to load: {loadError.value}</div>}
          {actionError.value && <div class="error-banner" style={{ marginBottom: 12 }}>{actionError.value}</div>}

          {!loading.value && !loadError.value && rows.length === 0 && (
            <div class="empty-state">No agents bound to this system.</div>
          )}

          {!loading.value && rows.map((b) => {
            const busy = actionBusy.value === b.id;
            const hasUpgrade = Boolean(b.upgrade_available_version_id);
            return (
              <div
                key={b.id}
                style={{
                  border: '1px solid var(--border)',
                  borderRadius: 4,
                  padding: '0.75rem',
                  marginBottom: 10,
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8 }}>
                  <div>
                    <div class="text-sm" style={{ fontWeight: 600 }}>{b.agent_name ?? b.agent_id}</div>
                    <div class="font-mono text-xs text-tertiary">{b.agent_id}</div>
                    <div class="text-xs" style={{ marginTop: 4 }}>
                      {b.agent_team && <span class="badge badge-info">{b.agent_team}</span>}
                      {' '}
                      {b.agent_owner_type && <span class="badge">{b.agent_owner_type}</span>}
                      {' '}
                      <span class="font-mono">{b.version_semver ?? (b.version_id ?? '—')}</span>
                      {' · '}
                      {b.pinned
                        ? <span style={{ color: 'var(--medium, #f59e0b)' }}>Pinned</span>
                        : <span style={{ color: 'var(--pass, #22c55e)' }}>Auto</span>}
                    </div>
                    {hasUpgrade && (
                      <div class="text-xs" style={{
                        marginTop: 6,
                        padding: '0.35rem 0.5rem',
                        background: 'rgba(245,158,11,0.1)',
                        border: '1px solid var(--medium, #f59e0b)',
                        borderRadius: 3,
                      }}>
                        New version available: <span class="font-mono">{b.upgrade_available_version_id}</span>
                      </div>
                    )}
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 4, minWidth: 130 }}>
                    {hasUpgrade && (
                      <button
                        class="btn btn-sm btn-primary"
                        disabled={busy}
                        onClick={() => void acceptUpgrade(b)}
                      >
                        {busy ? '…' : 'Accept Upgrade'}
                      </button>
                    )}
                    <button
                      class="btn btn-sm"
                      disabled={busy}
                      onClick={() => void togglePin(b)}
                    >
                      {busy ? '…' : b.pinned ? 'Unpin' : 'Pin'}
                    </button>
                    <button
                      class="btn btn-sm"
                      style={{ color: 'var(--critical, #ef4444)' }}
                      disabled={busy}
                      onClick={() => void unbind(b)}
                    >
                      {busy ? '…' : 'Unbind'}
                    </button>
                  </div>
                </div>
              </div>
            );
          })}

          {/* Add agent picker */}
          <div style={{ marginTop: 16, paddingTop: 12, borderTop: '1px solid var(--border)' }}>
            {!showAddPicker.value && (
              <button
                class="btn btn-sm btn-secondary"
                disabled={candidates.length === 0}
                title={candidates.length === 0 ? 'All available agents are already bound' : ''}
                onClick={() => { showAddPicker.value = true; }}
              >
                + Bind Agent
              </button>
            )}
            {showAddPicker.value && (
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                <select
                  class="filter-select"
                  value={selectedNewAgent.value}
                  onChange={(e) => (selectedNewAgent.value = (e.currentTarget as HTMLSelectElement).value)}
                >
                  <option value="">Select an agent…</option>
                  {candidates.map((a) => (
                    <option key={a.id} value={a.id}>{a.name} ({a.team ?? 'unknown'})</option>
                  ))}
                </select>
                <button
                  class="btn btn-sm btn-primary"
                  disabled={!selectedNewAgent.value || actionBusy.value === '__add__'}
                  onClick={() => void addBinding()}
                >
                  {actionBusy.value === '__add__' ? 'Binding…' : 'Bind'}
                </button>
                <button
                  class="btn btn-sm btn-secondary"
                  onClick={() => { showAddPicker.value = false; selectedNewAgent.value = ''; actionError.value = null; }}
                >
                  Cancel
                </button>
              </div>
            )}
          </div>
        </div>
      </aside>
    </>
  );
}
