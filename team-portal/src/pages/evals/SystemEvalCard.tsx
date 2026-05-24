import { signal } from '@preact/signals';
import { apiGet, apiPost } from '../../shared/api/client';
import type {
  EvalsSystemOverview,
  EvalRecord,
  SystemDetailResponse,
  SimulatedRunResponse,
} from './types';
import { reloadEvalsOverview } from './EvalsPage';

// Module-level signal state — two levels of expansion.
const expandedSystems = signal<Set<string>>(new Set());
const openEvals = signal<Set<string>>(new Set());
const detailCache = signal<Map<string, EvalRecord[]>>(new Map());
const detailLoading = signal<Set<string>>(new Set());
const running = signal<Set<string>>(new Set());
const actionError = signal<string | null>(null);
const lastRun = signal<Map<string, SimulatedRunResponse>>(new Map());

function toggleSet(sig: typeof expandedSystems, key: string): void {
  const next = new Set(sig.value);
  if (next.has(key)) next.delete(key);
  else next.add(key);
  sig.value = next;
}

async function loadDetail(systemId: string): Promise<void> {
  if (detailCache.value.has(systemId) || detailLoading.value.has(systemId)) return;
  const loadingNext = new Set(detailLoading.value);
  loadingNext.add(systemId);
  detailLoading.value = loadingNext;
  const r = await apiGet<SystemDetailResponse>(`/grc/evals/v2/system/${encodeURIComponent(systemId)}`);
  if (r.ok) {
    const next = new Map(detailCache.value);
    next.set(systemId, r.data.evals ?? []);
    detailCache.value = next;
  }
  const doneNext = new Set(detailLoading.value);
  doneNext.delete(systemId);
  detailLoading.value = doneNext;
}

function toggleSystem(systemId: string): void {
  toggleSet(expandedSystems, systemId);
  if (expandedSystems.value.has(systemId)) void loadDetail(systemId);
}

async function runSimulatedSuite(systemId: string): Promise<void> {
  if (running.value.has(systemId)) return;
  actionError.value = null;
  const next = new Set(running.value);
  next.add(systemId);
  running.value = next;

  const r = await apiPost<SimulatedRunResponse>(
    `/grc/evals/v2/run/${encodeURIComponent(systemId)}`,
  );

  if (r.ok) {
    const lr = new Map(lastRun.value);
    lr.set(systemId, r.data);
    lastRun.value = lr;
    // Invalidate cached detail so the next expand re-fetches refreshed run_at.
    const dc = new Map(detailCache.value);
    dc.delete(systemId);
    detailCache.value = dc;
    if (expandedSystems.value.has(systemId)) void loadDetail(systemId);
    void reloadEvalsOverview();
  } else {
    actionError.value = `Run failed: ${r.detail}`;
  }

  const done = new Set(running.value);
  done.delete(systemId);
  running.value = done;
}

const pct = (x: number | null | undefined): number => Math.round((x ?? 0) * 100);

const STATUS_BADGE: Record<string, string> = {
  PASS: 'badge-pass',
  WARN: 'badge-medium',
  FAIL: 'badge-critical',
};

export function SystemEvalCard({ system: s }: { system: EvalsSystemOverview }) {
  const isOpen = expandedSystems.value.has(s.ai_system_id);
  const evals = detailCache.value.get(s.ai_system_id);
  const isLoadingDetail = detailLoading.value.has(s.ai_system_id);
  const isRunning = running.value.has(s.ai_system_id);
  const lr = lastRun.value.get(s.ai_system_id);

  return (
    <div class={`sys-eval-card ${isOpen ? 'expanded' : ''}`}>
      <div class="sys-eval-header" onClick={() => toggleSystem(s.ai_system_id)}>
        <div>
          <div class="text-sm font-bold">{s.ai_system_name}</div>
          <div class="text-xs text-secondary" style={{ marginTop: 2 }}>
            {s.ai_system_id} · {s.domain} · {s.runtime_status}
          </div>
        </div>
        <div>
          <div class="text-xs text-secondary">Evals</div>
          <div class="text-sm font-bold">{s.total}</div>
        </div>
        <div>
          <div class="text-xs text-secondary">Pass / Warn / Fail</div>
          <div class="text-sm">
            <span class="font-bold" style={{ color: 'var(--pass)' }}>{s.passes}</span>
            {' / '}
            <span class="font-bold" style={{ color: 'var(--medium)' }}>{s.warns}</span>
            {' / '}
            <span class="font-bold" style={{ color: 'var(--critical)' }}>{s.fails}</span>
          </div>
        </div>
        <div>
          <div class="text-xs text-secondary">Blocking</div>
          <div class={`text-sm font-bold ${s.blocking_fails > 0 ? 'text-critical' : ''}`}>
            {s.blocking_fails}
          </div>
        </div>
        <div style={{ textAlign: 'right' }}>
          <button
            class="btn btn-sm btn-primary"
            disabled={isRunning}
            onClick={(e) => {
              e.stopPropagation();
              void runSimulatedSuite(s.ai_system_id);
            }}
          >
            {isRunning ? 'Running…' : 'Run Simulated Eval Suite'}
          </button>
          {lr && !isRunning && (
            <div class="text-xs text-tertiary" style={{ marginTop: 4 }}>
              Last run {lr.ran_at.slice(0, 19).replace('T', ' ')} · {lr.eval_count} evals · gates {lr.release_gates.decision}
            </div>
          )}
        </div>
      </div>

      {actionError.value && (
        <div class="error-banner" style={{ margin: '6px 12px' }}>{actionError.value}</div>
      )}

      {isOpen && (
        <div>
          {isLoadingDetail && <div class="loading">Loading evals…</div>}
          {!isLoadingDetail && evals && evals.length === 0 && (
            <div class="empty-state">No evals recorded for this system.</div>
          )}
          {!isLoadingDetail && evals && evals.length > 0 && (
            <>
              <div class="eval-row head">
                <div />
                <div>Eval / Source</div>
                <div>Score</div>
                <div>Status</div>
                <div>Release Impact</div>
                <div>Run</div>
              </div>
              {evals.map((e) => <EvalDetailRow key={e.id} record={e} />)}
            </>
          )}
        </div>
      )}
    </div>
  );
}

function EvalDetailRow({ record: e }: { record: EvalRecord }) {
  const isOpen = openEvals.value.has(e.id);
  const pretty = e.eval_type
    .replace(/_/g, ' ')
    .toLowerCase()
    .replace(/\b\w/g, (c) => c.toUpperCase());
  const scoreColor =
    e.status === 'PASS' ? 'var(--pass)'
    : e.status === 'FAIL' ? 'var(--critical)'
    : 'var(--medium)';
  const passRate = e.pass_rate ?? (e.test_count ? (e.test_count - e.failed_count) / e.test_count : 0);

  return (
    <>
      <div class={`eval-row sev-${e.status}`} onClick={() => toggleSet(openEvals, e.id)}>
        <div class="toggle">{isOpen ? '▾' : '▸'}</div>
        <div>
          <div class="text-sm font-bold">{pretty}</div>
          <div class="text-xs text-tertiary">
            {e.tool_source} · n={e.test_count}
            {e.failed_count ? ` · ${e.failed_count} failures` : ''}
          </div>
        </div>
        <div class="score-line">
          <span class="score-num" style={{ color: scoreColor }}>{pct(e.score)}%</span>
          <span class="score-thresh">/ {pct(e.threshold)}%</span>
        </div>
        <div>
          <span class={`badge ${STATUS_BADGE[e.status] ?? 'badge-neutral'}`}>{e.status}</span>
        </div>
        <div>
          <span class={`impact-pill impact-${e.release_impact}`}>
            {e.release_impact.replace(/_/g, ' ')}
          </span>
        </div>
        <div class="text-xs text-tertiary" style={{ textAlign: 'right' }}>
          {(e.run_at ?? '').slice(0, 10)}
        </div>
      </div>
      {isOpen && (
        <div class="eval-detail">
          {e.notes && (
            <div class="row"><dt>Notes</dt><dd>{e.notes}</dd></div>
          )}
          <div class="row">
            <dt>Pass rate</dt>
            <dd>
              {pct(passRate)}% — {e.test_count - e.failed_count}/{e.test_count} cases pass
            </dd>
          </div>
          <div class="row">
            <dt>Controls</dt>
            <dd>
              {(e.control_mappings ?? []).length === 0 ? '—' : (
                <>
                  {(e.control_mappings ?? []).map((c) => (
                    <span key={c} class="badge badge-info" style={{ marginRight: 4 }}>{c}</span>
                  ))}
                </>
              )}
            </dd>
          </div>
          <div class="row">
            <dt>Frameworks</dt>
            <dd>
              {(e.framework_mappings ?? []).length === 0 ? '—' : (
                <>
                  {(e.framework_mappings ?? []).map((f, i) => (
                    <span key={i} class="badge badge-info" style={{ marginRight: 4 }}>
                      {f.framework.replace(/_/g, ' ')} {f.clause}
                    </span>
                  ))}
                </>
              )}
            </dd>
          </div>
          {e.evidence_id && (
            <div class="row">
              <dt>Evidence</dt>
              <dd>
                <a class="badge badge-info" href={`/evidence?id=${encodeURIComponent(e.evidence_id)}`}>
                  {e.evidence_id}
                </a>
              </dd>
            </div>
          )}
          {e.sample_failures && e.sample_failures.length > 0 && (
            <div class="row">
              <dt>Sample failures</dt>
              <dd>
                <ul>
                  {e.sample_failures.map((f, i) => (
                    <li key={i} class="sample">{f}</li>
                  ))}
                </ul>
              </dd>
            </div>
          )}
        </div>
      )}
    </>
  );
}
