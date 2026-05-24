import { signal, computed } from '@preact/signals';
import { useEffect } from 'preact/hooks';
import { apiGet } from '../../shared/api/client';
import { SeverityBadge, DecisionBadge, RuntimeStatusDot } from '../../shared/components/Badges';
import { AiSystemDrawer, openSystem } from './AiSystemDrawer';
import type { AiSystemSummary, AiSystemsListResponse } from './types';

// Page state — module-level signals so URL?id= deep-link survives navigation.
const allSystems = signal<AiSystemSummary[]>([]);
const loading = signal<boolean>(true);
const loadError = signal<string | null>(null);
const searchTerm = signal<string>('');
const riskFilter = signal<string>('');
const decisionFilter = signal<string>('');
const statusFilter = signal<string>('');

const filtered = computed<AiSystemSummary[]>(() => {
  const term = searchTerm.value.toLowerCase();
  const risk = riskFilter.value;
  const decision = decisionFilter.value;
  const status = statusFilter.value;
  return allSystems.value.filter((s) => {
    if (term && !s.name.toLowerCase().includes(term) && !s.domain.toLowerCase().includes(term)) {
      return false;
    }
    if (risk && s.risk_level !== risk) return false;
    if (decision && s.release_decision !== decision) return false;
    if (status && s.runtime_status !== status) return false;
    return true;
  });
});

async function loadSystems(): Promise<void> {
  loading.value = true;
  loadError.value = null;
  const r = await apiGet<AiSystemsListResponse>('/grc/ai-systems');
  if (r.ok) {
    allSystems.value = r.data.systems ?? [];
  } else {
    loadError.value = r.detail;
  }
  loading.value = false;
}

export function AiSystemsPage() {
  useEffect(() => {
    void loadSystems();
    // Honour ?id= deep link (V1 parity — static/ai-systems.html load())
    const params = new URLSearchParams(window.location.search);
    const id = params.get('id');
    if (id) openSystem(id);
  }, []);

  const rows = filtered.value;

  return (
    <div>
      <div class="page-header">
        <div>
          <div class="page-title">AI System Inventory</div>
          <div class="page-subtitle">Production and pre-production AI systems under governance</div>
        </div>
        <div class="page-actions">
          <button class="btn btn-sm" disabled title="Pending Phase 2 follow-up">Export Inventory</button>
          <a class="btn btn-sm btn-primary" href="/ai-systems/new">+ Register System</a>
        </div>
      </div>

      <div class="filter-bar">
        <input
          class="filter-input"
          type="text"
          placeholder="Search systems…"
          value={searchTerm.value}
          onInput={(e) => (searchTerm.value = (e.currentTarget as HTMLInputElement).value)}
        />
        <select
          class="filter-select"
          value={riskFilter.value}
          onChange={(e) => (riskFilter.value = (e.currentTarget as HTMLSelectElement).value)}
        >
          <option value="">All risk levels</option>
          <option value="CRITICAL">Critical</option>
          <option value="HIGH">High</option>
          <option value="MEDIUM">Medium</option>
          <option value="LOW">Low</option>
        </select>
        <select
          class="filter-select"
          value={decisionFilter.value}
          onChange={(e) => (decisionFilter.value = (e.currentTarget as HTMLSelectElement).value)}
        >
          <option value="">All decisions</option>
          <option value="APPROVED">Approved</option>
          <option value="CONDITIONAL_PILOT">Conditional Pilot</option>
          <option value="HOLD">Hold</option>
          <option value="REJECT">Reject</option>
        </select>
        <select
          class="filter-select"
          value={statusFilter.value}
          onChange={(e) => (statusFilter.value = (e.currentTarget as HTMLSelectElement).value)}
        >
          <option value="">All statuses</option>
          <option value="PRODUCTION">Production</option>
          <option value="PILOT">Pilot</option>
          <option value="STAGED">Staged</option>
        </select>
      </div>

      {loadError.value && <div class="error-banner">Failed to load systems: {loadError.value}</div>}

      <div class="card" style={{ padding: 0, overflow: 'hidden' }}>
        <table class="data-table">
          <thead>
            <tr>
              <th>System Name</th>
              <th>Business Owner</th>
              <th>Domain</th>
              <th>Risk Level</th>
              <th>Autonomy</th>
              <th>Data Classes</th>
              <th>Runtime</th>
              <th>Decision</th>
              <th style={{ textAlign: 'right' }}>Open Findings</th>
              <th>Last Assessment</th>
            </tr>
          </thead>
          <tbody>
            {loading.value && (
              <tr><td colSpan={10} class="loading">Loading…</td></tr>
            )}
            {!loading.value && rows.length === 0 && (
              <tr><td colSpan={10} class="empty-state">No systems match filters.</td></tr>
            )}
            {!loading.value && rows.map((s) => (
              <tr key={s.id} style={{ cursor: 'pointer' }} onClick={() => openSystem(s.id)}>
                <td>
                  <div class="cell-primary">{s.name}</div>
                  <div class="cell-secondary">{s.id}</div>
                </td>
                <td class="text-sm">{(s.business_owner ?? '').split(',')[0]}</td>
                <td class="text-sm text-secondary">{s.domain}</td>
                <td><SeverityBadge value={s.risk_level} /></td>
                <td class="text-sm text-secondary">
                  {(s.autonomy_level ?? '').split(' ').slice(0, 3).join(' ')}
                  {(s.autonomy_level ?? '').split(' ').length > 3 ? '…' : ''}
                </td>
                <td class="text-xs text-tertiary">
                  {s.data_classes.slice(0, 3).join(', ')}{s.data_classes.length > 3 ? '…' : ''}
                </td>
                <td class="text-sm"><RuntimeStatusDot value={s.runtime_status} /></td>
                <td><DecisionBadge value={s.release_decision} /></td>
                <td style={{ textAlign: 'right' }}>
                  <span class="font-bold">{s.open_findings}</span>
                  {s.critical_findings > 0 && (
                    <span class="text-critical text-xs"> ({s.critical_findings} P0)</span>
                  )}
                </td>
                <td class="text-sm text-secondary">{s.last_assessment}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <AiSystemDrawer />
    </div>
  );
}
