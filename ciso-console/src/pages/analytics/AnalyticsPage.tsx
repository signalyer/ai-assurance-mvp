// Surface: Cross-portfolio Analytics (CSM-3)
// V1 ancestor: static/analytics.html (NOT static/analytics-usage.html)
// Endpoints:
//   GET /api/analytics          — full rollup (KPIs + breakdowns)
//   GET /api/analytics/trends   — daily trend table
// Pure read — no mutations.
// Pattern: string-breakdown display (no chart lib), mirrors team-portal Portfolio.

import { signal, computed } from '@preact/signals';
import { useEffect } from 'preact/hooks';
import { apiGet } from '../../shared/api/client';
import type { AnalyticsRollup, AnalyticsTrendsResponse, TrendPoint } from './types';

// ============================================================
// Module-level signals
// ============================================================

const rollup = signal<AnalyticsRollup | null>(null);
const rollupLoading = signal<boolean>(true);
const rollupError = signal<string | null>(null);

const trends = signal<TrendPoint[]>([]);
const trendsLoading = signal<boolean>(true);
const trendPassRate = signal<number>(0);

const periodDays = signal<number>(30);

// ============================================================
// Derived
// ============================================================

const kpis = computed(() => {
  const r = rollup.value;
  if (!r) return null;
  return {
    totalRuns: r.total_runs,
    passRate: r.pass_rate ?? 0,
    avgLatencyMs: r.average_latency_ms,
    totalTokens: r.total_tokens,
  };
});

// ============================================================
// Data loaders
// ============================================================

async function loadRollup(days: number): Promise<void> {
  rollupLoading.value = true;
  rollupError.value = null;
  const r = await apiGet<AnalyticsRollup>('/analytics', { days });
  if (r.ok) {
    rollup.value = r.data;
  } else {
    rollupError.value = r.detail;
  }
  rollupLoading.value = false;
}

async function loadTrends(days: number): Promise<void> {
  trendsLoading.value = true;
  const r = await apiGet<AnalyticsTrendsResponse>('/analytics/trends', { days });
  if (r.ok) {
    trends.value = r.data.trends ?? [];
    trendPassRate.value = r.data.pass_rate ?? 0;
  }
  trendsLoading.value = false;
}

async function loadAll(days: number): Promise<void> {
  await Promise.all([loadRollup(days), loadTrends(days)]);
}

async function onPeriodChange(days: number): Promise<void> {
  periodDays.value = days;
  await loadAll(days);
}

// ============================================================
// Helpers
// ============================================================

function pct(n: number): string {
  return `${(n * 100).toFixed(1)}%`;
}

function fmtNum(n: number): string {
  return n.toLocaleString();
}

function pctTone(rate: number): string {
  if (rate >= 0.9) return 'pass';
  if (rate >= 0.7) return 'medium';
  return 'critical';
}

// Render a dict of label→count as sorted breakdown bars (no chart lib)
function BreakdownList({ data, total }: { data: Record<string, number>; total: number }) {
  const entries = Object.entries(data).sort(([, a], [, b]) => b - a);
  if (entries.length === 0) return <span class="text-tertiary">—</span>;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
      {entries.map(([label, count]) => {
        const share = total > 0 ? count / total : 0;
        return (
          <div key={label} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <div style={{ width: 120, fontSize: 11, color: 'var(--text-secondary)', flexShrink: 0 }}>{label}</div>
            <div
              style={{
                height: 8,
                background: 'var(--accent)',
                borderRadius: 2,
                opacity: 0.7,
                width: `${Math.max(share * 180, 4)}px`,
                flexShrink: 0,
              }}
            />
            <div style={{ fontSize: 11, color: 'var(--text-secondary)' }}>
              {count} ({pct(share)})
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ============================================================
// Component
// ============================================================

const PERIODS = [7, 14, 30, 90];

export function AnalyticsPage() {
  useEffect(() => { void loadAll(periodDays.value); }, []);

  const k = kpis.value;

  return (
    <div>
      <div class="page-header">
        <div>
          <div class="page-title">Cross-portfolio Analytics</div>
          <div class="page-subtitle">
            Aggregate risk signal across all AI systems · {periodDays.value}-day window
          </div>
        </div>
        <div class="page-actions">
          {PERIODS.map((d) => (
            <button
              key={d}
              class={`btn btn-sm ${periodDays.value === d ? 'btn-primary' : ''}`}
              onClick={() => void onPeriodChange(d)}
            >
              {d}d
            </button>
          ))}
          <button class="btn btn-sm" onClick={() => void loadAll(periodDays.value)}>Refresh</button>
        </div>
      </div>

      {/* KPI row */}
      {rollupLoading.value ? (
        <div class="loading" style={{ padding: '1.5rem' }}>Loading analytics…</div>
      ) : rollupError.value ? (
        <div class="error-banner" style={{ margin: '1rem' }}>Failed: {rollupError.value}</div>
      ) : k ? (
        <>
          <div class="kpi-row">
            <div class="kpi-card">
              <div class="kpi-label">Total Runs</div>
              <div class="kpi-value">{fmtNum(k.totalRuns)}</div>
            </div>
            <div class="kpi-card">
              <div class="kpi-label">Pass Rate</div>
              <div class={`kpi-value ${pctTone(k.passRate)}`}>{pct(k.passRate)}</div>
            </div>
            <div class="kpi-card">
              <div class="kpi-label">Avg Latency</div>
              <div class="kpi-value">{fmtNum(k.avgLatencyMs)} ms</div>
            </div>
            <div class="kpi-card">
              <div class="kpi-label">Total Tokens</div>
              <div class="kpi-value">{fmtNum(k.totalTokens)}</div>
            </div>
          </div>

          <BreakdownCards rollup={rollup.value!} />
        </>
      ) : null}

      <TrendsCard />
    </div>
  );
}

function BreakdownCards({ rollup: r }: { rollup: AnalyticsRollup }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '1rem', marginBottom: '1rem' }}>
      <div class="card">
        <div class="card-header">
          <div class="card-title">By Domain</div>
        </div>
        <div style={{ padding: '1rem' }}>
          <BreakdownList data={r.by_domain} total={r.total_runs} />
        </div>
      </div>
      <div class="card">
        <div class="card-header">
          <div class="card-title">By Model</div>
        </div>
        <div style={{ padding: '1rem' }}>
          <BreakdownList data={r.by_model} total={r.total_runs} />
        </div>
      </div>
      <div class="card">
        <div class="card-header">
          <div class="card-title">Failure Types</div>
        </div>
        <div style={{ padding: '1rem' }}>
          <BreakdownList data={r.failure_types} total={r.total_runs} />
        </div>
      </div>
    </div>
  );
}

function TrendsCard() {
  const rows = trends.value;

  return (
    <div class="card">
      <div class="card-header">
        <div>
          <div class="card-title">Daily Trends</div>
          <div class="card-subtitle">
            Pass rate over period · overall {pct(trendPassRate.value)}
          </div>
        </div>
      </div>
      {trendsLoading.value ? (
        <div class="loading" style={{ padding: '1.5rem' }}>Loading trends…</div>
      ) : rows.length === 0 ? (
        <div class="empty-state">No trend data for this period.</div>
      ) : (
        <table class="data-table">
          <thead>
            <tr>
              <th>Date</th>
              <th>Total Runs</th>
              <th>Pass</th>
              <th>Fail</th>
              <th>Pass Rate</th>
              <th>Trend</th>
            </tr>
          </thead>
          <tbody>
            {[...rows].reverse().map((row) => (
              <tr key={row.date}>
                <td class="text-xs text-tertiary">{row.date}</td>
                <td>{row.runs}</td>
                <td style={{ color: 'var(--pass)' }}>{row.pass}</td>
                <td style={{ color: 'var(--critical)' }}>{row.fail}</td>
                <td>
                  <span
                    class={
                      row.pass_rate >= 0.9
                        ? 'badge badge-pass'
                        : row.pass_rate >= 0.7
                        ? 'badge badge-medium'
                        : 'badge badge-critical'
                    }
                  >
                    {pct(row.pass_rate)}
                  </span>
                </td>
                <td>
                  <div
                    style={{
                      height: 6,
                      background: row.pass_rate >= 0.9 ? 'var(--pass)' : row.pass_rate >= 0.7 ? 'var(--warning)' : 'var(--critical)',
                      borderRadius: 2,
                      width: `${Math.max(row.pass_rate * 100, 4)}px`,
                      opacity: 0.7,
                    }}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
