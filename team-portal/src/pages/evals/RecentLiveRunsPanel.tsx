// S70b — "Recent live runs" panel for the Evals page.
//
// Source of truth: GET /api/v1/evals/recent (api/evaluate.py::evals_recent),
// which reads data/evals.jsonl directly. No seed/overlay fallback — empty
// state is honest. Per [[v1_to_v2_real_data_arc]] the panel renders real
// agent/SDK runs only; the seed-overlay system cards live below.
//
// Loading guard: `loading && !hasData` per [[never-blank-on-refresh]] —
// initial load shows the placeholder, refresh-while-data-present does not.
//
// No raw fetch — uses the shared apiGet client per
// [[raw-fetch-drifts-from-shared-client]].

import { signal, computed } from '@preact/signals';
import { useEffect } from 'preact/hooks';
import { apiGet } from '../../shared/api/client';
import type { RecentEvalsResponse, RecentEvalRow } from './types';

const rows = signal<RecentEvalRow[]>([]);
const loading = signal<boolean>(true);
const loadError = signal<string | null>(null);

const hasData = computed(() => rows.value.length > 0);

async function loadRecent(): Promise<void> {
  loading.value = true;
  loadError.value = null;
  const r = await apiGet<RecentEvalsResponse>('/evals/recent', { limit: 20 });
  if (r.ok) {
    rows.value = r.data.rows ?? [];
  } else {
    loadError.value = r.detail;
  }
  loading.value = false;
}

function MetricChip({ name, score, skipped, passed }: {
  name: string;
  score: number | null;
  skipped: boolean;
  passed: boolean | null;
}) {
  if (skipped) {
    return (
      <span class="chip chip-muted" title="Skipped — no context / no ground truth">
        {name}: n/a
      </span>
    );
  }
  const cls = passed === true ? 'chip chip-pass' : passed === false ? 'chip chip-fail' : 'chip';
  const value = score === null ? '—' : score.toFixed(2);
  return <span class={cls}>{name}: {value}</span>;
}

function Row({ row }: { row: RecentEvalRow }) {
  const metricNames = Object.keys(row.results);
  const ts = row.timestamp.replace('T', ' ').replace('Z', '').slice(0, 19);
  return (
    <div class="recent-eval-row">
      <div class="recent-eval-row__head">
        <code class="recent-eval-row__trace">{row.trace_id}</code>
        <span class="recent-eval-row__model">{row.model ?? '—'}</span>
        <span class="recent-eval-row__workload">{row.workload_id ?? '—'}</span>
        <span class="recent-eval-row__ts">{ts}</span>
      </div>
      <div class="recent-eval-row__metrics">
        {metricNames.map((m) => {
          const metric = row.results[m];
          if (!metric) return null;
          return (
            <MetricChip
              key={m}
              name={m}
              score={metric.score}
              skipped={metric.skipped}
              passed={metric.passed}
            />
          );
        })}
      </div>
    </div>
  );
}

export function RecentLiveRunsPanel() {
  useEffect(() => { void loadRecent(); }, []);

  const showInitialLoading = loading.value && !hasData.value;

  return (
    <div class="recent-live-runs">
      <div class="recent-live-runs__header">
        <div>
          <div class="recent-live-runs__title">Recent live runs</div>
          <div class="recent-live-runs__sub">
            Real evaluations from agents / SDK calls — distinct from the seed-overlay system cards below.
          </div>
        </div>
        <button class="btn btn-sm" onClick={() => void loadRecent()}>Refresh</button>
      </div>

      {loadError.value && (
        <div class="error-banner">Failed to load recent evals: {loadError.value}</div>
      )}

      {showInitialLoading && <div class="loading">Loading recent live runs…</div>}

      {!showInitialLoading && rows.value.length === 0 && !loadError.value && (
        <div class="empty-state">
          No live runs yet — run an agent via SDK to populate this.
        </div>
      )}

      {!showInitialLoading && rows.value.length > 0 && (
        <div class="recent-live-runs__list">
          {rows.value.map((row) => <Row key={row.trace_id} row={row} />)}
        </div>
      )}
    </div>
  );
}
