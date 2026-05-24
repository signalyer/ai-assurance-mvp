// My Systems Portfolio — Team Workspace surface #11.
// Dashboard view (KPIs + risk distribution + top-N by findings), complementary
// to the AI Systems CRUD-style list. No new engine endpoints — derived from
// the same /api/grc/ai-systems data already typed for AiSystemsPage.
//
// Filter: client-side All / My team toggle. "My team" is a stub until session
// auth wires the real actor (Phase 3). Defaults to All so the page renders
// non-empty in dev with seeded data.

import { signal, computed } from '@preact/signals';
import { useEffect } from 'preact/hooks';
import { Link } from 'wouter-preact';
import { apiGet } from '../../shared/api/client';
import type { AiSystemSummary } from '../ai-systems/types';

interface AiSystemsListResponse { systems: AiSystemSummary[] }

type ScopeFilter = 'all' | 'mine';

const ACTOR = 'demo-engineer';

const systems = signal<AiSystemSummary[]>([]);
const loading = signal<boolean>(true);
const loadError = signal<string | null>(null);
const scope = signal<ScopeFilter>('all');

// Stub own-team filter — until auth lands, matches systems whose owner string
// contains the actor token. Defaults render nothing in dev (no seeded match),
// which is the intended honest state, not a bug.
function isOwnedBy(s: AiSystemSummary, actor: string): boolean {
  const a = actor.toLowerCase();
  return (
    (s.business_owner || '').toLowerCase().includes(a) ||
    (s.technical_owner || '').toLowerCase().includes(a)
  );
}

const filtered = computed<AiSystemSummary[]>(() => {
  if (scope.value === 'all') return systems.value;
  return systems.value.filter((s) => isOwnedBy(s, ACTOR));
});

const kpis = computed(() => {
  const list = filtered.value;
  const byRisk = { CRITICAL: 0, HIGH: 0, MEDIUM: 0, LOW: 0 } as Record<string, number>;
  const byStatus: Record<string, number> = {};
  let totalOpen = 0;
  let totalCritical = 0;
  for (const s of list) {
    const r = (s.risk_level || 'LOW').toUpperCase();
    byRisk[r] = (byRisk[r] ?? 0) + 1;
    const st = s.runtime_status || 'UNKNOWN';
    byStatus[st] = (byStatus[st] ?? 0) + 1;
    totalOpen += s.open_findings || 0;
    totalCritical += s.critical_findings || 0;
  }
  return { count: list.length, byRisk, byStatus, totalOpen, totalCritical };
});

const topByFindings = computed<AiSystemSummary[]>(() => {
  return [...filtered.value]
    .filter((s) => (s.open_findings ?? 0) > 0)
    .sort((a, b) =>
      (b.critical_findings ?? 0) - (a.critical_findings ?? 0)
      || (b.open_findings ?? 0) - (a.open_findings ?? 0),
    )
    .slice(0, 5);
});

async function loadSystems(): Promise<void> {
  loading.value = true;
  loadError.value = null;
  const r = await apiGet<AiSystemsListResponse>('/grc/ai-systems');
  if (r.ok) systems.value = r.data.systems ?? [];
  else loadError.value = r.detail;
  loading.value = false;
}

function riskClass(r: string): string {
  const u = r.toUpperCase();
  if (u === 'CRITICAL') return 'critical';
  if (u === 'HIGH') return 'pill-failure';
  if (u === 'MEDIUM') return 'pill-review';
  return 'pill-success';
}

export function PortfolioPage() {
  useEffect(() => { void loadSystems(); }, []);

  const k = kpis.value;
  const top = topByFindings.value;
  const total = systems.value.length;
  const myCount = systems.value.filter((s) => isOwnedBy(s, ACTOR)).length;

  return (
    <div>
      <div class="page-header">
        <div>
          <div class="page-title">My Portfolio</div>
          <div class="page-subtitle">
            Dashboard view of registered AI systems with risk distribution and findings hotspots. Use the AI Systems page for CRUD-style detail.
          </div>
        </div>
        <div class="page-actions">
          <div style={{ display: 'inline-flex', border: '1px solid var(--border)', borderRadius: '6px', overflow: 'hidden' }}>
            <button
              class={`btn btn-sm ${scope.value === 'all' ? 'btn-primary' : ''}`}
              style={{ borderRadius: 0, borderRight: '1px solid var(--border)' }}
              onClick={() => { scope.value = 'all'; }}
            >
              All ({total})
            </button>
            <button
              class={`btn btn-sm ${scope.value === 'mine' ? 'btn-primary' : ''}`}
              style={{ borderRadius: 0 }}
              onClick={() => { scope.value = 'mine'; }}
              title={`Filter to systems owned by ${ACTOR} (stub until session auth in Phase 3)`}
            >
              My team ({myCount})
            </button>
          </div>
          <button class="btn btn-sm" onClick={() => void loadSystems()}>Refresh</button>
        </div>
      </div>

      {loadError.value && <div class="error-banner">Failed to load systems: {loadError.value}</div>}
      {loading.value && <div class="loading">Loading portfolio…</div>}

      {!loading.value && !loadError.value && (
        <>
          <div class="kpi-row">
            <div class="kpi-card">
              <div class="kpi-label">Systems in scope</div>
              <div class="kpi-value">{k.count}</div>
              <div class="kpi-trend">{scope.value === 'mine' ? `owned by ${ACTOR}` : 'all registered systems'}</div>
            </div>
            <div class="kpi-card">
              <div class="kpi-label">Critical findings</div>
              <div class="kpi-value critical">{k.totalCritical}</div>
              <div class="kpi-trend">across portfolio</div>
            </div>
            <div class="kpi-card">
              <div class="kpi-label">Open findings</div>
              <div class="kpi-value">{k.totalOpen}</div>
              <div class="kpi-trend">{k.totalCritical} critical · {k.totalOpen - k.totalCritical} non-critical</div>
            </div>
            <div class="kpi-card">
              <div class="kpi-label">Runtime mix</div>
              <div class="kpi-value" style={{ fontSize: '14px', lineHeight: 1.4 }}>
                {Object.entries(k.byStatus).length === 0
                  ? '—'
                  : Object.entries(k.byStatus).slice(0, 3).map(([s, n]) => `${s}: ${n}`).join(' · ')}
              </div>
            </div>
          </div>

          {scope.value === 'mine' && k.count === 0 && (
            <div class="card">
              <div style={{ padding: '1.25rem', textAlign: 'center', color: 'var(--text-secondary)', fontSize: '13px' }}>
                No systems matched <strong>{ACTOR}</strong> as owner.{' '}
                <span style={{ opacity: 0.7 }}>(Until session auth wires the real actor in Phase 3, "My team" is a stub heuristic.)</span>
              </div>
            </div>
          )}

          <div class="card">
            <div class="card-header">
              <div>
                <div class="card-title">Risk distribution</div>
                <div class="card-subtitle">System count by inherent risk tier</div>
              </div>
            </div>
            <div style={{ padding: '0.875rem 1rem', display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '0.75rem' }}>
              {(['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'] as const).map((r) => (
                <div key={r} style={{
                  padding: '0.75rem', border: '1px solid var(--border)',
                  borderRadius: '6px', textAlign: 'center',
                }}>
                  <div style={{ fontSize: '10px', textTransform: 'uppercase', color: 'var(--text-secondary)', fontWeight: 600 }}>{r}</div>
                  <div style={{ fontSize: '22px', fontWeight: 700, marginTop: '0.25rem' }}>{k.byRisk[r] ?? 0}</div>
                </div>
              ))}
            </div>
          </div>

          <div class="card">
            <div class="card-header">
              <div>
                <div class="card-title">Top systems by findings</div>
                <div class="card-subtitle">Ordered by critical, then total open findings</div>
              </div>
            </div>
            {top.length === 0 && <div class="empty-state">No open findings in scope. ✓</div>}
            {top.length > 0 && (
              <table class="data-table">
                <thead>
                  <tr>
                    <th>System</th><th>Risk</th><th>Runtime</th><th>Critical</th><th>Open</th><th>Owner</th>
                  </tr>
                </thead>
                <tbody>
                  {top.map((s) => (
                    <tr key={s.id}>
                      <td>
                        <Link href={`/ai-systems?id=${encodeURIComponent(s.id)}`}>{s.name}</Link>
                      </td>
                      <td><span class={`pill ${riskClass(s.risk_level)}`}>{s.risk_level}</span></td>
                      <td><span class="mono">{s.runtime_status}</span></td>
                      <td><span class="critical">{s.critical_findings ?? 0}</span></td>
                      <td>{s.open_findings ?? 0}</td>
                      <td>{s.business_owner}</td>
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
