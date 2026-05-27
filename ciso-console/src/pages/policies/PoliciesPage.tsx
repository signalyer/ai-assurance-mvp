// Surface: Policy Governance (CSM-4)
// V1 ancestor: static/policies.html
// Endpoints:
//   GET /api/grc/policies         — list (PoliciesOut)
//   GET /api/grc/policies/{id}    — detail (PolicyOut)
// CISO posture: read-only. Filter by severity/automation; click-to-drill modal
// with full policy text, last-eval summary, bound systems.

import { signal, computed } from '@preact/signals';
import { useEffect, useState } from 'preact/hooks';
import { apiGet } from '../../shared/api/client';
import type { PolicyItem, PoliciesResponse } from './types';

// ============================================================
// F-018: Active enforced .rego policies (read-only)
// .rego bundles ship via git → CI; this panel surfaces what's
// CURRENTLY enforced on the engine so operators can audit it.
// No upload UI — that's deliberate (see POC-RETROSPECTIVE.md F-018).
// ============================================================

type RegoPolicy = {
  name: string;
  filename: string;
  size_bytes: number;
  sha256: string;
  package: string;
  summary: string;
};

type RegoListResponse = {
  items: RegoPolicy[];
  count: number;
  source_dir: string;
};

const regoBundles = signal<RegoPolicy[]>([]);
const regoLoading = signal<boolean>(true);
const regoError = signal<string | null>(null);
const regoSourceDir = signal<string>('');

async function loadRegoBundles(): Promise<void> {
  regoLoading.value = true;
  regoError.value = null;
  const r = await apiGet<RegoListResponse>('/policies/rego');
  if (r.ok) {
    regoBundles.value = r.data.items;
    regoSourceDir.value = r.data.source_dir;
  } else {
    regoError.value = r.detail;
  }
  regoLoading.value = false;
}

function RegoBundlesPanel() {
  const items = regoBundles.value;
  const hasData = items.length > 0;
  return (
    <div class="card" style={{ marginBottom: '1.5rem' }}>
      <div class="card-header">
        <div>
          <div class="card-title">Active enforced policies (.rego)</div>
          <div class="card-subtitle">
            Bundles loaded by the policy engine. Ship via git → CI. Read-only.
          </div>
        </div>
        <button class="btn btn-sm" onClick={() => void loadRegoBundles()}>Refresh</button>
      </div>
      {regoLoading.value && !hasData ? (
        <div class="loading" style={{ padding: '1rem' }}>Loading enforced policies…</div>
      ) : regoError.value && !hasData ? (
        <div class="error-banner" style={{ margin: '0.75rem' }}>Failed: {regoError.value}</div>
      ) : !hasData ? (
        <div class="empty-state" style={{ padding: '1rem' }}>No .rego bundles found.</div>
      ) : (
        <table class="data-table">
          <thead>
            <tr>
              <th>Bundle</th>
              <th>Package</th>
              <th>Summary</th>
              <th style={{ textAlign: 'right' }}>Size</th>
              <th>SHA-256</th>
            </tr>
          </thead>
          <tbody>
            {items.map((b) => (
              <tr key={b.filename}>
                <td style={{ fontFamily: 'monospace', fontSize: 12 }}>{b.filename}</td>
                <td style={{ fontFamily: 'monospace', fontSize: 12 }}>{b.package || '—'}</td>
                <td style={{ fontSize: 12, color: 'var(--text-secondary)', maxWidth: 360 }}>
                  {b.summary || '—'}
                </td>
                <td style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums', fontSize: 12 }}>
                  {b.size_bytes.toLocaleString()}
                </td>
                <td style={{ fontFamily: 'monospace', fontSize: 11, color: 'var(--text-tertiary)' }}>
                  {b.sha256.slice(0, 16)}…
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {regoSourceDir.value && (
        <div style={{ padding: '0.5rem 0.75rem', fontSize: 11, color: 'var(--text-tertiary)', fontFamily: 'monospace' }}>
          source: {regoSourceDir.value}
        </div>
      )}
    </div>
  );
}

// ============================================================
// Module-level signals
// ============================================================

const policies = signal<PolicyItem[]>([]);
const loading = signal<boolean>(true);
const loadError = signal<string | null>(null);

const filterSeverity = signal<string>('ALL');
const filterAutomation = signal<string>('ALL');
const searchText = signal<string>('');

// ============================================================
// Derived
// ============================================================

const filtered = computed(() => {
  let items = policies.value;
  if (filterSeverity.value !== 'ALL') {
    items = items.filter((p) => p.severity === filterSeverity.value);
  }
  if (filterAutomation.value !== 'ALL') {
    items = items.filter((p) => p.automation_status === filterAutomation.value);
  }
  const q = searchText.value.trim().toLowerCase();
  if (q) {
    items = items.filter(
      (p) =>
        p.id.toLowerCase().includes(q) ||
        p.requirement.toLowerCase().includes(q) ||
        p.owner.toLowerCase().includes(q) ||
        p.framework_mappings.some((f) => f.toLowerCase().includes(q)),
    );
  }
  return items;
});

const severities = computed(() => {
  const set = new Set(policies.value.map((p) => p.severity));
  return Array.from(set).sort();
});

const automationStatuses = computed(() => {
  const set = new Set(policies.value.map((p) => p.automation_status));
  return Array.from(set).sort();
});

// ============================================================
// Loaders
// ============================================================

async function loadPolicies(): Promise<void> {
  loading.value = true;
  loadError.value = null;
  const r = await apiGet<PoliciesResponse>('/grc/policies');
  if (r.ok) {
    policies.value = r.data.policies;
  } else {
    loadError.value = r.detail;
  }
  loading.value = false;
}

// ============================================================
// Helpers
// ============================================================

function severityTone(s: string): string {
  switch (s.toLowerCase()) {
    case 'critical': return 'critical';
    case 'high':     return 'critical';
    case 'medium':   return 'medium';
    default:         return 'pass';
  }
}

function complianceRate(p: PolicyItem): number {
  const total = p.compliant_systems + p.non_compliant_systems;
  return total === 0 ? 1 : p.compliant_systems / total;
}

function pct(n: number): string {
  return `${(n * 100).toFixed(0)}%`;
}

// ============================================================
// Modal
// ============================================================

function PolicyModal({
  policy,
  onClose,
}: {
  policy: PolicyItem;
  onClose: () => void;
}) {
  const rate = complianceRate(policy);
  const tone = rate >= 0.9 ? 'pass' : rate >= 0.6 ? 'medium' : 'critical';
  return (
    <div
      style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.55)',
        zIndex: 200, display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div
        style={{
          background: 'var(--bg-card)', borderRadius: 8, padding: '1.5rem',
          width: 680, maxWidth: '95vw', maxHeight: '85vh', overflowY: 'auto',
          boxShadow: '0 8px 32px rgba(0,0,0,0.4)',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '1rem' }}>
          <div>
            <div style={{ fontSize: 11, color: 'var(--text-tertiary)', marginBottom: 4 }}>{policy.id}</div>
            <div style={{ fontWeight: 600, fontSize: 15 }}>{policy.requirement}</div>
          </div>
          <button class="btn btn-sm" onClick={onClose} style={{ flexShrink: 0, marginLeft: '1rem' }}>Close</button>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem', marginBottom: '1rem' }}>
          <div class="kpi-card" style={{ padding: '0.75rem' }}>
            <div class="kpi-label">Severity</div>
            <div class={`kpi-value ${severityTone(policy.severity)}`}>{policy.severity}</div>
          </div>
          <div class="kpi-card" style={{ padding: '0.75rem' }}>
            <div class="kpi-label">Automation</div>
            <div class="kpi-value">{policy.automation_status}</div>
          </div>
          <div class="kpi-card" style={{ padding: '0.75rem' }}>
            <div class="kpi-label">Compliance Rate</div>
            <div class={`kpi-value ${tone}`}>{pct(rate)}</div>
          </div>
          <div class="kpi-card" style={{ padding: '0.75rem' }}>
            <div class="kpi-label">Owner</div>
            <div class="kpi-value" style={{ fontSize: 13 }}>{policy.owner}</div>
          </div>
        </div>

        <div class="card" style={{ marginBottom: '1rem' }}>
          <div class="card-header"><div class="card-title">Pass Criteria</div></div>
          <pre style={{
            margin: 0, padding: '0.75rem', fontFamily: 'monospace', fontSize: 12,
            whiteSpace: 'pre-wrap', color: 'var(--text-primary)', overflowX: 'auto',
          }}>
            {policy.pass_criteria}
          </pre>
        </div>

        <div class="card" style={{ marginBottom: '1rem' }}>
          <div class="card-header"><div class="card-title">Framework Mappings</div></div>
          <div style={{ padding: '0.75rem', display: 'flex', flexWrap: 'wrap', gap: '0.4rem' }}>
            {policy.framework_mappings.length > 0
              ? policy.framework_mappings.map((f) => (
                  <span key={f} class="badge badge-info" style={{ fontSize: 11 }}>{f}</span>
                ))
              : <span class="text-tertiary">None</span>}
          </div>
        </div>

        <div class="card" style={{ marginBottom: '1rem' }}>
          <div class="card-header"><div class="card-title">Evidence Required</div></div>
          <div style={{ padding: '0.75rem', display: 'flex', flexWrap: 'wrap', gap: '0.4rem' }}>
            {policy.evidence_required.length > 0
              ? policy.evidence_required.map((e) => (
                  <span key={e} class="badge" style={{ fontSize: 11 }}>{e}</span>
                ))
              : <span class="text-tertiary">None specified</span>}
          </div>
        </div>

        <div class="card">
          <div class="card-header"><div class="card-title">System Compliance</div></div>
          <div style={{ padding: '0.75rem', display: 'flex', gap: '2rem' }}>
            <div>
              <div style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>Compliant</div>
              <div style={{ fontWeight: 700, color: 'var(--pass)', fontSize: 20 }}>{policy.compliant_systems}</div>
            </div>
            <div>
              <div style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>Non-compliant</div>
              <div style={{ fontWeight: 700, color: 'var(--critical)', fontSize: 20 }}>{policy.non_compliant_systems}</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ============================================================
// Component
// ============================================================

export function PoliciesPage() {
  const [selected, setSelected] = useState<PolicyItem | null>(null);

  useEffect(() => {
    void loadPolicies();
    void loadRegoBundles();
  }, []);

  const items = filtered.value;

  return (
    <div>
      <div class="page-header">
        <div>
          <div class="page-title">Policy Governance</div>
          <div class="page-subtitle">
            OPA control requirements · read-only CISO view
          </div>
        </div>
        <div class="page-actions">
          <button class="btn btn-sm" onClick={() => void loadPolicies()}>Refresh</button>
        </div>
      </div>

      <RegoBundlesPanel />

      {/* Filters */}
      <div style={{ display: 'flex', gap: '0.75rem', marginBottom: '1rem', flexWrap: 'wrap' }}>
        <input
          type="text"
          class="input"
          placeholder="Search ID, requirement, owner, framework…"
          style={{ flex: 1, minWidth: 220 }}
          value={searchText.value}
          onInput={(e) => { searchText.value = (e.target as HTMLInputElement).value; }}
        />
        <select
          class="input"
          style={{ width: 160 }}
          value={filterSeverity.value}
          onChange={(e) => { filterSeverity.value = (e.target as HTMLSelectElement).value; }}
        >
          <option value="ALL">All Severities</option>
          {severities.value.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <select
          class="input"
          style={{ width: 180 }}
          value={filterAutomation.value}
          onChange={(e) => { filterAutomation.value = (e.target as HTMLSelectElement).value; }}
        >
          <option value="ALL">All Automation</option>
          {automationStatuses.value.map((a) => <option key={a} value={a}>{a}</option>)}
        </select>
      </div>

      {loading.value && policies.value.length === 0 ? (
        <div class="loading" style={{ padding: '2rem' }}>Loading policies…</div>
      ) : loadError.value && policies.value.length === 0 ? (
        <div class="error-banner" style={{ margin: '1rem' }}>Failed: {loadError.value}</div>
      ) : items.length === 0 ? (
        <div class="empty-state">No policies match the current filters.</div>
      ) : (
        <div class="card">
          <div class="card-header">
            <div class="card-title">Policies</div>
            <div class="card-subtitle">{items.length} of {policies.value.length}</div>
          </div>
          <table class="data-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Requirement</th>
                <th>Severity</th>
                <th>Frameworks</th>
                <th>Automation</th>
                <th>Compliant</th>
                <th>Non-compliant</th>
                <th>Owner</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {items.map((p) => {
                const rate = complianceRate(p);
                const tone = rate >= 0.9 ? 'pass' : rate >= 0.6 ? 'medium' : 'critical';
                return (
                  <tr key={p.id}>
                    <td class="text-xs text-tertiary">{p.id}</td>
                    <td style={{ maxWidth: 260 }}>
                      <div style={{ fontSize: 12, lineHeight: 1.4 }}>{p.requirement}</div>
                    </td>
                    <td>
                      <span class={`badge badge-${severityTone(p.severity)}`}>{p.severity}</span>
                    </td>
                    <td>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 2 }}>
                        {p.framework_mappings.slice(0, 2).map((f) => (
                          <span key={f} class="badge badge-info" style={{ fontSize: 10 }}>{f}</span>
                        ))}
                        {p.framework_mappings.length > 2 && (
                          <span class="text-tertiary" style={{ fontSize: 10 }}>+{p.framework_mappings.length - 2}</span>
                        )}
                      </div>
                    </td>
                    <td class="text-xs">{p.automation_status}</td>
                    <td>
                      <span style={{ color: 'var(--pass)', fontWeight: 600 }}>{p.compliant_systems}</span>
                    </td>
                    <td>
                      <span class={`badge badge-${tone}`}>{p.non_compliant_systems}</span>
                    </td>
                    <td class="text-xs text-tertiary">{p.owner}</td>
                    <td>
                      <button
                        class="btn btn-sm"
                        onClick={() => setSelected(p)}
                      >
                        Detail
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {selected && (
        <PolicyModal policy={selected} onClose={() => setSelected(null)} />
      )}
    </div>
  );
}
