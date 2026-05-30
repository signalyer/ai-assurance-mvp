import { signal, computed } from '@preact/signals';
import { useEffect } from 'preact/hooks';
import { apiGet } from '../../shared/api/client';
import type { EvalsSystemOverview, OverviewResponse } from './types';
import { SystemEvalCard } from './SystemEvalCard';
import { RecentLiveRunsPanel } from './RecentLiveRunsPanel';

const overview = signal<EvalsSystemOverview[]>([]);
const loading = signal<boolean>(true);
const loadError = signal<string | null>(null);

const kpis = computed(() => {
  const o = overview.value;
  return {
    total: o.reduce((s, x) => s + x.total, 0),
    passes: o.reduce((s, x) => s + x.passes, 0),
    warns: o.reduce((s, x) => s + x.warns, 0),
    fails: o.reduce((s, x) => s + x.fails, 0),
    blocking: o.reduce((s, x) => s + x.blocking_fails, 0),
    systemCount: o.length,
  };
});

// Sort failing systems first (V1 parity — static/evals.html renderSystems order())
const sortedSystems = computed(() => {
  const order = (s: EvalsSystemOverview): number =>
    s.fails > 0 ? 0 : s.warns > 0 ? 1 : 2;
  return [...overview.value].sort(
    (a, b) => order(a) - order(b) || a.ai_system_name.localeCompare(b.ai_system_name),
  );
});

export async function reloadEvalsOverview(): Promise<void> {
  return loadOverview();
}

async function loadOverview(): Promise<void> {
  loading.value = true;
  loadError.value = null;
  const r = await apiGet<OverviewResponse>('/grc/evals/v2/overview');
  if (r.ok) {
    overview.value = (r.data.systems ?? []).filter((s) => s.total > 0);
  } else {
    loadError.value = r.detail;
  }
  loading.value = false;
}

export function EvalsPage() {
  useEffect(() => { void loadOverview(); }, []);

  const k = kpis.value;
  const systems = sortedSystems.value;

  return (
    <div>
      <div class="page-header">
        <div>
          <div class="page-title">Evaluation Suite</div>
          <div class="page-subtitle">
            Evals feed release gates, findings, residual risk, and framework coverage — not vanity metrics
          </div>
        </div>
        <div class="page-actions">
          <button class="btn btn-sm" onClick={() => void loadOverview()}>Refresh</button>
        </div>
      </div>

      {loadError.value && <div class="error-banner">Failed to load evals: {loadError.value}</div>}

      <RecentLiveRunsPanel />

      <div class="kpi-row">
        <div class="kpi-card">
          <div class="kpi-label">Total Evals</div>
          <div class="kpi-value">{k.total}</div>
          <div class="kpi-trend">across {k.systemCount} systems</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">Passing</div>
          <div class="kpi-value" style={{ color: 'var(--pass)' }}>{k.passes}</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">Warnings</div>
          <div class="kpi-value">{k.warns}</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">Blocking Failures</div>
          <div class="kpi-value critical">{k.blocking}</div>
          <div class="kpi-trend">of {k.fails} total fails</div>
        </div>
      </div>

      {loading.value && <div class="loading">Loading evals overview…</div>}
      {!loading.value && systems.length === 0 && !loadError.value && (
        <div class="empty-state">No systems with recorded evals.</div>
      )}
      {!loading.value && systems.map((s) => (
        <SystemEvalCard key={s.ai_system_id} system={s} />
      ))}
    </div>
  );
}
