// Surface 1: Findings Inbox (CSM-1)
// V1 ancestor: static/findings.html
// Data: GET /api/grc/findings/v2/list (router prefix /api/grc/findings/v2; S49 fix).
// Pattern: table of findings, click row to open detail drawer.
// Read-only this session. Acknowledge/resolve mutation is CSM-2 scope.

import { signal, computed } from '@preact/signals';
import { useEffect } from 'preact/hooks';
import { apiGet } from '../../shared/api/client';
import type {
  Finding, FindingsV2Response, FindingPriority, FindingStatus, FindingImpact,
} from './types';

// ============================================================
// Module-level signals
// ============================================================

const findings = signal<Finding[]>([]);
const loading = signal<boolean>(true);
const loadError = signal<string | null>(null);

const scopeFilter = signal<string>('ALL');
const statusFilter = signal<string>('');
const priorityFilter = signal<string>('');
const searchText = signal<string>('');

const drawerFinding = signal<Finding | null>(null);

// ============================================================
// Derived
// ============================================================

const filtered = computed<Finding[]>(() => {
  let rows = findings.value;
  if (scopeFilter.value !== 'ALL') {
    rows = rows.filter((f) => f.ai_system_id === scopeFilter.value);
  }
  if (statusFilter.value) {
    rows = rows.filter((f) => f.status === statusFilter.value);
  }
  if (priorityFilter.value) {
    rows = rows.filter((f) => f.priority === priorityFilter.value);
  }
  const q = searchText.value.trim().toLowerCase();
  if (q) {
    rows = rows.filter(
      (f) =>
        f.title.toLowerCase().includes(q) ||
        f.id.toLowerCase().includes(q) ||
        (f.ai_system_name ?? '').toLowerCase().includes(q) ||
        (f.control_id ?? '').toLowerCase().includes(q),
    );
  }
  return rows;
});

const kpis = computed(() => {
  const all = findings.value;
  const open = all.filter((f) => f.status === 'OPEN').length;
  const p0p1 = all.filter((f) => f.priority === 'P0' || f.priority === 'P1').length;
  const breached = all.filter((f) => f.sla_breached === true).length;
  const blocking = all.filter(
    (f) => f.impact === 'BLOCK_PRODUCTION' || f.impact === 'BLOCK_PILOT',
  ).length;
  return { total: all.length, open, p0p1, breached, blocking };
});

const systemIds = computed<string[]>(() => {
  const seen = new Set<string>();
  for (const f of findings.value) seen.add(f.ai_system_id);
  return [...seen].sort();
});

// ============================================================
// Data load
// ============================================================

async function loadFindings(): Promise<void> {
  loading.value = true;
  loadError.value = null;
  const r = await apiGet<FindingsV2Response>('/grc/findings/v2/list');
  if (r.ok) {
    findings.value = r.data.findings ?? [];
  } else {
    loadError.value = r.detail;
  }
  loading.value = false;
}

// ============================================================
// Helpers
// ============================================================

function fmtTs(ts: string): string {
  return (ts || '').slice(0, 10);
}

function priorityClass(p: FindingPriority): string {
  return `badge find-priority-${p}`;
}

function statusClass(s: FindingStatus): string {
  return `badge find-status-${s}`;
}

function impactLabel(i: FindingImpact): string {
  return i.replace(/_/g, ' ');
}

function slaClass(f: Finding): string {
  if (f.sla_breached) return 'badge badge-critical';
  if (f.sla_days != null && f.sla_days <= 3) return 'badge badge-medium';
  return 'badge badge-neutral';
}

function slaLabel(f: Finding): string {
  if (f.sla_breached) return 'BREACHED';
  if (f.sla_days == null) return '—';
  return `${f.sla_days}d`;
}

// ============================================================
// Components
// ============================================================

export function FindingsInboxPage() {
  useEffect(() => { void loadFindings(); }, []);

  return (
    <div>
      <div class="page-header">
        <div>
          <div class="page-title">Findings &amp; Remediation</div>
          <div class="page-subtitle">
            Cross-portfolio findings · each maps to ≥1 control, ≥1 framework, and ≥1 release gate where relevant
          </div>
        </div>
        <div class="page-actions">
          <input
            type="text"
            class="filter-select"
            style={{ width: 200 }}
            placeholder="Search ID, title, control…"
            value={searchText.value}
            onInput={(e) => { searchText.value = (e.target as HTMLInputElement).value; }}
          />
          <select
            class="filter-select"
            value={scopeFilter.value}
            onChange={(e) => { scopeFilter.value = (e.currentTarget as HTMLSelectElement).value; }}
          >
            <option value="ALL">All AI Systems</option>
            {systemIds.value.map((id) => <option key={id} value={id}>{id}</option>)}
          </select>
          <select
            class="filter-select"
            value={statusFilter.value}
            onChange={(e) => { statusFilter.value = (e.currentTarget as HTMLSelectElement).value; }}
          >
            <option value="">All Statuses</option>
            {(['OPEN','IN_PROGRESS','RISK_ACCEPTED','REMEDIATED','VERIFIED','CLOSED'] as const).map((s) => (
              <option key={s} value={s}>{s.replace(/_/g, ' ')}</option>
            ))}
          </select>
          <select
            class="filter-select"
            value={priorityFilter.value}
            onChange={(e) => { priorityFilter.value = (e.currentTarget as HTMLSelectElement).value; }}
          >
            <option value="">All Priorities</option>
            {(['P0','P1','P2','P3'] as const).map((p) => (
              <option key={p} value={p}>{p}</option>
            ))}
          </select>
          <button class="btn btn-sm" onClick={() => void loadFindings()}>Refresh</button>
        </div>
      </div>

      {loadError.value && (
        <div class="error-banner">Failed to load findings: {loadError.value}</div>
      )}

      <KpiRow />

      <div class="card">
        <div class="card-header">
          <div>
            <div class="card-title">Findings</div>
            <div class="card-subtitle">
              {filtered.value.length} of {findings.value.length} findings · click a row for detail
            </div>
          </div>
        </div>
        <FindingsTable />
      </div>

      <FindingDrawer />
    </div>
  );
}

function KpiRow() {
  const k = kpis.value;
  return (
    <div class="kpi-row">
      <Kpi label="Total Findings" value={k.total} />
      <Kpi label="Open" value={k.open} tone="critical" />
      <Kpi label="P0 / P1" value={k.p0p1} tone="critical" sub="critical + high priority" />
      <Kpi label="SLA Breached" value={k.breached} tone="medium" />
    </div>
  );
}

function Kpi({ label, value, tone, sub }: { label: string; value: number; tone?: string; sub?: string }) {
  return (
    <div class="kpi-card">
      <div class="kpi-label">{label}</div>
      <div class={`kpi-value ${tone ?? ''}`}>{value}</div>
      {sub && <div class="kpi-trend">{sub}</div>}
    </div>
  );
}

function FindingsTable() {
  const rows = filtered.value;
  const hasData = findings.value.length > 0;

  // Show the loading placeholder ONLY when we have nothing to show yet.
  // Once data has arrived, a subsequent refresh (Refresh button, periodic
  // re-fetch) must NOT hide the existing rows — that conflates "fetch in
  // flight" with "no data" and produces the "stuck loading…" UX we hit in
  // prod when `loading` flipped back to true after the initial load
  // resolved (e.g. user clicked Refresh, or a stray re-mount fired loadFindings).
  if (loading.value && !hasData) {
    return <div class="loading" style={{ padding: '1.5rem' }}>Loading findings…</div>;
  }
  if (rows.length === 0) return <div class="empty-state">No findings match the current filters.</div>;

  return (
    <table class="data-table">
      <thead>
        <tr>
          <th>ID</th>
          <th>Priority</th>
          <th>Title</th>
          <th>AI System</th>
          <th>Status</th>
          <th>Impact</th>
          <th>Framework</th>
          <th>Control</th>
          <th>SLA</th>
          <th>Updated</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((f) => (
          <tr
            key={f.id}
            style={{ cursor: 'pointer' }}
            onClick={() => { drawerFinding.value = f; }}
          >
            <td><span class="mono">{f.id.slice(0, 10)}</span></td>
            <td><span class={priorityClass(f.priority)}>{f.priority}</span></td>
            <td>
              <div class="cell-primary">{f.title}</div>
              {f.description && (
                <div class="cell-secondary" style={{ marginTop: 2 }}>
                  {f.description.slice(0, 80)}{f.description.length > 80 ? '…' : ''}
                </div>
              )}
            </td>
            <td class="text-xs">{f.ai_system_name ?? f.ai_system_id}</td>
            <td><span class={statusClass(f.status)}>{f.status.replace(/_/g, ' ')}</span></td>
            <td class="text-xs">{impactLabel(f.impact)}</td>
            <td class="text-xs">{f.framework ?? '—'}</td>
            <td class="text-xs">{f.control_id ?? '—'}</td>
            <td><span class={slaClass(f)}>{slaLabel(f)}</span></td>
            <td class="text-xs text-tertiary">{fmtTs(f.updated_at)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// Drawer: read-only detail. Mutation (acknowledge/resolve) is CSM-2 scope.
function FindingDrawer() {
  const f = drawerFinding.value;
  const isOpen = f !== null;

  function close() { drawerFinding.value = null; }

  return (
    <>
      <div
        class={`drawer-overlay ${isOpen ? 'open' : ''}`}
        onClick={close}
      />
      <div class={`drawer ${isOpen ? 'open' : ''}`}>
        {f && (
          <>
            <div class="drawer-header">
              <div class="drawer-title">{f.title}</div>
              <button class="drawer-close" onClick={close}>✕</button>
            </div>
            <div class="drawer-body">
              <div class="drawer-section">
                <div class="drawer-section-title">Classification</div>
                <dl class="def-list">
                  <dt>ID</dt>
                  <dd><span class="mono">{f.id}</span></dd>
                  <dt>Priority</dt>
                  <dd><span class={priorityClass(f.priority)}>{f.priority}</span></dd>
                  <dt>Status</dt>
                  <dd><span class={statusClass(f.status)}>{f.status.replace(/_/g, ' ')}</span></dd>
                  <dt>Impact</dt>
                  <dd>{impactLabel(f.impact)}</dd>
                  <dt>SLA</dt>
                  <dd><span class={slaClass(f)}>{slaLabel(f)}</span></dd>
                </dl>
              </div>

              <div class="drawer-section">
                <div class="drawer-section-title">Context</div>
                <dl class="def-list">
                  <dt>AI System</dt>
                  <dd>{f.ai_system_name ?? f.ai_system_id}</dd>
                  <dt>Framework</dt>
                  <dd>{f.framework ?? '—'}</dd>
                  <dt>Control</dt>
                  <dd>{f.control_id ?? '—'}</dd>
                  <dt>Assigned To</dt>
                  <dd>{f.assigned_to ?? '—'}</dd>
                  <dt>Created</dt>
                  <dd>{fmtTs(f.created_at)}</dd>
                  <dt>Updated</dt>
                  <dd>{fmtTs(f.updated_at)}</dd>
                </dl>
              </div>

              {f.description && (
                <div class="drawer-section">
                  <div class="drawer-section-title">Description</div>
                  <div class="text-sm" style={{ lineHeight: 1.6 }}>{f.description}</div>
                </div>
              )}

              {f.remediation_notes && (
                <div class="drawer-section">
                  <div class="drawer-section-title">Remediation Notes</div>
                  <div class="text-sm" style={{ lineHeight: 1.6 }}>{f.remediation_notes}</div>
                </div>
              )}

              {f.timeline && f.timeline.length > 0 && (
                <div class="drawer-section">
                  <div class="drawer-section-title">Timeline</div>
                  {f.timeline.map((entry, i) => (
                    <div key={i} class="list-row">
                      <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                        <span class="text-xs font-bold">{entry.action}</span>
                        <span class="text-xs text-tertiary">{entry.timestamp.slice(0, 16).replace('T', ' ')}</span>
                      </div>
                      <div class="text-xs text-tertiary" style={{ marginTop: 2 }}>
                        {entry.actor}{entry.note ? ` — ${entry.note}` : ''}
                      </div>
                    </div>
                  ))}
                </div>
              )}

              <div class="text-xs text-tertiary" style={{ marginTop: '1rem' }}>
                Mutation (acknowledge / resolve) available in CSM-2.
              </div>
            </div>
          </>
        )}
      </div>
    </>
  );
}
