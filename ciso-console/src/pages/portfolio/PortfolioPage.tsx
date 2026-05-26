// Surface: Portfolio Overview (CSM-2)
// V1 ancestor: static/governance.html dashboard section
// team-portal mirror: team-portal/src/pages/portfolio/PortfolioPage.tsx (ported, scope removed)
// Endpoints: GET /api/grc/ai-systems
// CISO-specific: no team filter (CISO sees all); per-row drill link to /findings?system_id=<id>

import { signal, computed } from '@preact/signals';
import { useEffect } from 'preact/hooks';
import { apiGet } from '../../shared/api/client';
import type { AiSystemSummary, AiSystemsListResponse } from './types';

// ============================================================
// Module-level signals
// ============================================================

const systems = signal<AiSystemSummary[]>([]);
const loading = signal<boolean>(true);
const loadError = signal<string | null>(null);

// ============================================================
// Derived
// ============================================================

const kpis = computed(() => {
  const list = systems.value;
  const byRisk: Record<string, number> = { CRITICAL: 0, HIGH: 0, MEDIUM: 0, LOW: 0 };
  const byStage: Record<string, number> = {};
  const byTier: Record<string, number> = {};
  let totalOpen = 0;
  let totalCritical = 0;
  for (const s of list) {
    const r = (s.risk_level ?? 'LOW').toUpperCase();
    byRisk[r] = (byRisk[r] ?? 0) + 1;
    const stage = s.runtime_status ?? 'UNKNOWN';
    byStage[stage] = (byStage[stage] ?? 0) + 1;
    const tier = s.deployment_target ?? 'UNKNOWN';
    byTier[tier] = (byTier[tier] ?? 0) + 1;
    totalOpen += s.open_findings ?? 0;
    totalCritical += s.critical_findings ?? 0;
  }
  return { count: list.length, byRisk, byStage, byTier, totalOpen, totalCritical };
});

const topByFindings = computed<AiSystemSummary[]>(() =>
  [...systems.value]
    .sort(
      (a, b) =>
        (b.critical_findings ?? 0) - (a.critical_findings ?? 0) ||
        (b.open_findings ?? 0) - (a.open_findings ?? 0),
    )
    .slice(0, 10),
);

// ============================================================
// Data load
// ============================================================

async function loadSystems(): Promise<void> {
  loading.value = true;
  loadError.value = null;
  const r = await apiGet<AiSystemsListResponse>('/grc/ai-systems');
  if (r.ok) {
    systems.value = r.data.systems ?? [];
  } else {
    loadError.value = r.detail;
  }
  loading.value = false;
}

// ============================================================
// Helpers
// ============================================================

function riskBadgeStyle(risk: string): string {
  const u = (risk ?? '').toUpperCase();
  if (u === 'CRITICAL') return 'badge badge-critical';
  if (u === 'HIGH') return 'badge badge-high';
  if (u === 'MEDIUM') return 'badge badge-medium';
  return 'badge badge-neutral';
}

function decisionBadgeStyle(decision: string): string {
  const u = (decision ?? '').toUpperCase();
  if (u === 'PASS' || u === 'APPROVED') return 'badge badge-pass';
  if (u === 'FAIL' || u === 'BLOCKED') return 'badge badge-critical';
  return 'badge badge-neutral';
}

function fmtDate(s: string): string {
  return (s ?? '').slice(0, 10);
}

// ============================================================
// Components
// ============================================================

export function PortfolioPage() {
  useEffect(() => { void loadSystems(); }, []);

  const k = kpis.value;

  return (
    <div>
      <div class="page-header">
        <div>
          <div class="page-title">Portfolio Overview</div>
          <div class="page-subtitle">
            Enterprise-wide view of all registered AI systems · risk distribution · findings hotspots
          </div>
        </div>
        <div class="page-actions">
          <button class="btn btn-sm" onClick={() => void loadSystems()}>Refresh</button>
        </div>
      </div>

      {loadError.value && (
        <div class="error-banner">Failed to load portfolio: {loadError.value}</div>
      )}

      {loading.value && systems.value.length === 0 && (
        <div class="loading" style={{ padding: '1.5rem' }}>Loading portfolio…</div>
      )}

      {(systems.value.length > 0 || (!loading.value && !loadError.value)) && (
        <>
          {/* KPI strip */}
          <div class="kpi-row">
            <div class="kpi-card">
              <div class="kpi-label">Total AI Systems</div>
              <div class="kpi-value">{k.count}</div>
              <div class="kpi-trend">enterprise portfolio</div>
            </div>
            <div class="kpi-card">
              <div class="kpi-label">Critical / High Risk</div>
              <div class="kpi-value critical">{(k.byRisk['CRITICAL'] ?? 0) + (k.byRisk['HIGH'] ?? 0)}</div>
              <div class="kpi-trend">{k.byRisk['CRITICAL'] ?? 0} critical · {k.byRisk['HIGH'] ?? 0} high</div>
            </div>
            <div class="kpi-card">
              <div class="kpi-label">Open Findings</div>
              <div class="kpi-value">{k.totalOpen}</div>
              <div class="kpi-trend">{k.totalCritical} critical severity</div>
            </div>
            <div class="kpi-card">
              <div class="kpi-label">Runtime Mix</div>
              <div class="kpi-value" style={{ fontSize: '13px', lineHeight: 1.6 }}>
                {Object.entries(k.byStage).length === 0
                  ? '—'
                  : Object.entries(k.byStage)
                      .slice(0, 3)
                      .map(([s, n]) => `${s}: ${n}`)
                      .join(' · ')}
              </div>
            </div>
          </div>

          {/* Risk distribution */}
          <div class="card">
            <div class="card-header">
              <div>
                <div class="card-title">Risk Distribution</div>
                <div class="card-subtitle">System count by inherent risk tier</div>
              </div>
            </div>
            <div style={{ padding: '0.875rem 1rem', display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '0.75rem' }}>
              {(['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'] as const).map((r) => (
                <div
                  key={r}
                  style={{
                    padding: '0.75rem',
                    border: '1px solid var(--border)',
                    borderRadius: '6px',
                    textAlign: 'center',
                  }}
                >
                  <div style={{ fontSize: '10px', textTransform: 'uppercase', color: 'var(--text-secondary)', fontWeight: 600 }}>{r}</div>
                  <div style={{ fontSize: '22px', fontWeight: 700, marginTop: '0.25rem' }}>
                    {k.byRisk[r] ?? 0}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Top-N by findings */}
          <div class="card">
            <div class="card-header">
              <div>
                <div class="card-title">Top 10 Systems by Findings</div>
                <div class="card-subtitle">Ordered by critical, then total open · click Findings to filter</div>
              </div>
            </div>
            {topByFindings.value.length === 0 && (
              <div class="empty-state">No systems registered yet.</div>
            )}
            {topByFindings.value.length > 0 && (
              <table class="data-table">
                <thead>
                  <tr>
                    <th>System</th>
                    <th>Domain</th>
                    <th>Risk</th>
                    <th>Stage</th>
                    <th>Decision</th>
                    <th>Critical</th>
                    <th>Open</th>
                    <th>Last Assessed</th>
                    <th>Findings</th>
                  </tr>
                </thead>
                <tbody>
                  {topByFindings.value.map((s) => (
                    <tr key={s.id}>
                      <td>
                        <div class="cell-primary">{s.name}</div>
                        <div class="cell-secondary" style={{ marginTop: 2 }}>{s.use_case.slice(0, 60)}{s.use_case.length > 60 ? '…' : ''}</div>
                      </td>
                      <td class="text-xs">{s.domain}</td>
                      <td><span class={riskBadgeStyle(s.risk_level)}>{s.risk_level}</span></td>
                      <td class="text-xs">{s.runtime_status}</td>
                      <td><span class={decisionBadgeStyle(s.release_decision)}>{s.release_decision}</span></td>
                      <td><span class="critical">{s.critical_findings ?? 0}</span></td>
                      <td>{s.open_findings ?? 0}</td>
                      <td class="text-xs text-tertiary">{fmtDate(s.last_assessment)}</td>
                      <td>
                        <a href={`/findings?system_id=${encodeURIComponent(s.id)}`} class="btn btn-sm">
                          Findings
                        </a>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </>
      )}
    </div>
  );
}
