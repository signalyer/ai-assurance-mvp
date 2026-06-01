import { signal, computed } from '@preact/signals';
import { useEffect } from 'preact/hooks';
import { apiGet } from '../../shared/api/client';
import type {
  StatsResponse, EpisodesResponse, EpisodeItem,
  RecallResponse, RecallItem, ContextResponse,
  DomainsResponse, DomainSummary,
} from './types';

// Module-level signals (Phase 2 pattern — see EvalsPage / RuntimeModals).
const stats = signal<StatsResponse | null>(null);
const statsLoading = signal<boolean>(false);
const statsError = signal<string | null>(null);

const domains = signal<DomainSummary[]>([]);
const workloadId = signal<string>('');
const lookbackDays = signal<number>(7);
const episodeLimit = signal<number>(20);

const episodes = signal<EpisodeItem[]>([]);
const episodesLoading = signal<boolean>(false);
const episodesError = signal<string | null>(null);

const recallQuery = signal<string>('');
const recallTopK = signal<number>(5);
const recallResults = signal<RecallItem[]>([]);
const recallLoading = signal<boolean>(false);
const recallError = signal<string | null>(null);
const recallLastQuery = signal<string>('');

const ctxIncludeRag = signal<boolean>(true);
const ctxIncludeProcedural = signal<boolean>(true);
const ctxLoading = signal<boolean>(false);
const ctxError = signal<string | null>(null);
const ctxResult = signal<ContextResponse | null>(null);

const kpis = computed(() => {
  const s = stats.value;
  return {
    totalEpisodes: s?.memory?.total_episodes ?? null,
    expired: s?.memory?.expired_count ?? null,
    ragDocs: s?.rag?.doc_count ?? null,
    ragIndex: s?.rag?.index_name ?? '—',
    byWorkload:
      (s?.memory?.episodes_by_workload as Record<string, number> | undefined) ??
      (s?.memory?.by_workload as Record<string, number> | undefined) ??
      {},
  };
});

async function loadDomains(): Promise<void> {
  const r = await apiGet<DomainsResponse>('/domains/');
  if (r.ok) domains.value = r.data.domains ?? [];
}

async function loadStats(): Promise<void> {
  statsLoading.value = true;
  statsError.value = null;
  const r = await apiGet<StatsResponse>('/memory/stats');
  if (r.ok) stats.value = r.data;
  else statsError.value = r.detail;
  statsLoading.value = false;
}

async function loadEpisodes(): Promise<void> {
  const wid = workloadId.value;
  if (!wid) {
    episodes.value = [];
    return;
  }
  episodesLoading.value = true;
  episodesError.value = null;
  const r = await apiGet<EpisodesResponse>('/memory/episodes', {
    workload_id: wid,
    limit: episodeLimit.value,
    lookback_days: lookbackDays.value,
  });
  if (r.ok) episodes.value = r.data.episodes ?? [];
  else episodesError.value = r.detail;
  episodesLoading.value = false;
}

async function runRecall(): Promise<void> {
  const wid = workloadId.value;
  const q = recallQuery.value.trim();
  recallError.value = null;
  if (!wid) { recallError.value = 'Select a workload before searching.'; return; }
  if (!q) { recallError.value = 'Enter a search query.'; return; }
  recallLoading.value = true;
  recallResults.value = [];
  recallLastQuery.value = q;
  const r = await apiGet<RecallResponse>('/memory/recall', {
    workload_id: wid, query: q, top_k: recallTopK.value,
  });
  if (r.ok) recallResults.value = r.data.results ?? [];
  else recallError.value = r.detail;
  recallLoading.value = false;
}

async function buildContext(): Promise<void> {
  const wid = workloadId.value;
  ctxError.value = null;
  if (!wid) { ctxError.value = 'Select a workload before building context.'; return; }
  ctxLoading.value = true;
  ctxResult.value = null;
  const r = await apiGet<ContextResponse>('/memory/context', {
    workload_id: wid,
    lookback_days: lookbackDays.value,
    include_rag: ctxIncludeRag.value,
    include_procedural: ctxIncludeProcedural.value,
  });
  if (r.ok) ctxResult.value = r.data;
  else ctxError.value = r.detail;
  ctxLoading.value = false;
}

function refreshAll(): void {
  void loadStats();
  void loadEpisodes();
}

function outcomeClass(o: string): string {
  if (o === 'success') return 'pill-success';
  if (o === 'failure') return 'pill-failure';
  if (o === 'review') return 'pill-review';
  return '';
}

function fmtTs(ts: string, len = 19): string {
  return (ts || '').slice(0, len).replace('T', ' ');
}

function copyContext(): void {
  const c = ctxResult.value?.context ?? '';
  if (!c) return;
  void navigator.clipboard.writeText(c).catch(() => {});
}

export function MemoryPage() {
  useEffect(() => {
    void loadDomains();
    void loadStats();
    // S82f-2-extended: deep-link `?workload_id=<id>` auto-selects the
    // workload and loads episodes. Lets Agent Library / Agent Runner /
    // /agent-runs link straight at the relevant memory slice without the
    // operator hunting in the dropdown.
    try {
      const params = new URLSearchParams(window.location.search);
      const wid = params.get('workload_id');
      if (wid) {
        workloadId.value = wid;
        void loadEpisodes();
      }
    } catch {
      // window unavailable — silent.
    }
    const t = window.setInterval(() => { void loadStats(); }, 30_000);
    return () => window.clearInterval(t);
  }, []);

  const k = kpis.value;
  const eps = episodes.value;
  const rec = recallResults.value;
  const ctx = ctxResult.value;

  const onWorkloadChange = (e: Event) => {
    workloadId.value = (e.target as HTMLSelectElement).value;
    void loadEpisodes();
  };
  const onLookbackChange = (e: Event) => {
    lookbackDays.value = Number((e.target as HTMLSelectElement).value);
    void loadEpisodes();
  };
  const onLimitChange = (e: Event) => {
    episodeLimit.value = Number((e.target as HTMLSelectElement).value);
    void loadEpisodes();
  };

  return (
    <div>
      <div class="page-header">
        <div>
          <div class="page-title">Agent Memory</div>
          <div class="page-subtitle">
            Episodic T2 store, semantic recall, multi-tier context (T1 in-context · T2 episodic · T3 RAG · T4 procedural) — stats auto-refresh every 30s
          </div>
        </div>
        <div class="page-actions">
          <select class="filter-select" value={workloadId.value} onChange={onWorkloadChange}>
            <option value="">All / none selected</option>
            {domains.value.map((d) => (
              <option key={d.id} value={d.id}>{d.name ?? d.id}</option>
            ))}
          </select>
          <button class="btn btn-sm" onClick={refreshAll}>Refresh</button>
        </div>
      </div>

      {statsError.value && <div class="error-banner">Stats error: {statsError.value}</div>}

      <div class="kpi-row">
        <div class="kpi-card">
          <div class="kpi-label">Total Episodes</div>
          <div class="kpi-value">{k.totalEpisodes ?? '—'}</div>
          <div class="kpi-trend">across all workloads</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">Workloads Tracked</div>
          <div class="kpi-value">{Object.keys(k.byWorkload).length}</div>
          <div class="kpi-trend">with episodic memory</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">RAG Documents</div>
          <div class="kpi-value">{k.ragDocs ?? '—'}</div>
          <div class="kpi-trend">index: {k.ragIndex}</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">Expired Episodes</div>
          <div class="kpi-value">{k.expired ?? '—'}</div>
          <div class="kpi-trend">eligible for purge</div>
        </div>
      </div>

      {statsLoading.value && stats.value === null && (
        <div class="loading">Loading memory stats…</div>
      )}

      <div class="card">
        <div class="card-header">
          <div>
            <div class="card-title">Episode Browser</div>
            <div class="card-subtitle">Recent episodic memory entries for the selected workload</div>
          </div>
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            <select class="filter-select" value={String(lookbackDays.value)} onChange={onLookbackChange}>
              <option value="7">Last 7 days</option>
              <option value="14">Last 14 days</option>
              <option value="30">Last 30 days</option>
              <option value="90">Last 90 days</option>
            </select>
            <select class="filter-select" value={String(episodeLimit.value)} onChange={onLimitChange}>
              <option value="20">20 rows</option>
              <option value="50">50 rows</option>
              <option value="100">100 rows</option>
            </select>
          </div>
        </div>

        {episodesError.value && <div class="error-banner">Failed to load episodes: {episodesError.value}</div>}
        {episodesLoading.value && <div class="loading">Loading episodes…</div>}
        {!episodesLoading.value && !workloadId.value && (
          <div class="empty-state">Select a workload to load episodes.</div>
        )}
        {!episodesLoading.value && workloadId.value && eps.length === 0 && !episodesError.value && (
          <div class="empty-state">No episodes found for this workload and time range.</div>
        )}
        {eps.length > 0 && (
          <table class="data-table">
            <thead>
              <tr>
                <th>Timestamp</th><th>Outcome</th><th>Prompt</th><th>Response</th><th>Trace</th>
              </tr>
            </thead>
            <tbody>
              {eps.map((ep) => (
                <tr key={ep.episode_id}>
                  <td><span class="mono">{fmtTs(ep.timestamp)}</span></td>
                  <td><span class={`pill ${outcomeClass(ep.outcome)}`}>{ep.outcome}</span></td>
                  <td title={ep.prompt_preview}>{ep.prompt_preview}</td>
                  <td title={ep.response_preview}>{ep.response_preview}</td>
                  <td>{ep.trace_id ? <span class="mono" title={ep.trace_id}>{ep.trace_id.slice(0, 12)}…</span> : <span class="text-tertiary">—</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div class="card">
        <div class="card-header">
          <div>
            <div class="card-title">Semantic Search</div>
            <div class="card-subtitle">Rank prior episodes by semantic similarity to a query</div>
          </div>
        </div>
        <div style={{ padding: '0.875rem 1rem', display: 'flex', gap: '0.5rem' }}>
          <input
            type="text"
            class="filter-select"
            style={{ flex: 1 }}
            placeholder="e.g. 'compliance rejection cases' or 'hallucinated stock picks'"
            value={recallQuery.value}
            onInput={(e) => { recallQuery.value = (e.target as HTMLInputElement).value; }}
            onKeyDown={(e) => { if ((e as KeyboardEvent).key === 'Enter') void runRecall(); }}
          />
          <select
            class="filter-select"
            value={String(recallTopK.value)}
            onChange={(e) => { recallTopK.value = Number((e.target as HTMLSelectElement).value); }}
          >
            <option value="5">Top 5</option>
            <option value="10">Top 10</option>
            <option value="20">Top 20</option>
          </select>
          <button class="btn btn-sm btn-primary" onClick={() => void runRecall()} disabled={recallLoading.value}>
            {recallLoading.value ? 'Searching…' : 'Search'}
          </button>
        </div>
        {recallError.value && <div class="error-banner">{recallError.value}</div>}
        {!recallLoading.value && rec.length === 0 && recallLastQuery.value && !recallError.value && (
          <div class="empty-state">No results for "{recallLastQuery.value}".</div>
        )}
        {rec.length > 0 && (
          <table class="data-table">
            <thead>
              <tr>
                <th style={{ width: '120px' }}>Score</th>
                <th>Timestamp</th><th>Outcome</th><th>Prompt</th><th>Response</th>
              </tr>
            </thead>
            <tbody>
              {rec.map((r) => {
                const pct = Math.max(0, Math.min(100, Math.round((r.relevance_score || 0) * 100)));
                return (
                  <tr key={r.episode_id}>
                    <td><span class="mono">{pct}%</span></td>
                    <td><span class="mono">{fmtTs(r.timestamp, 16)}</span></td>
                    <td><span class={`pill ${outcomeClass(r.outcome)}`}>{r.outcome}</span></td>
                    <td title={r.prompt_preview}>{r.prompt_preview}</td>
                    <td title={r.response_preview}>{r.response_preview}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      <div class="card">
        <div class="card-header">
          <div>
            <div class="card-title">Context Viewer</div>
            <div class="card-subtitle">Assemble multi-tier context (T1 in-context · T2 episodic · T3 RAG · T4 procedural)</div>
          </div>
          <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
            <label style={{ fontSize: '12px' }}>
              <input
                type="checkbox"
                checked={ctxIncludeRag.value}
                onChange={(e) => { ctxIncludeRag.value = (e.target as HTMLInputElement).checked; }}
                style={{ marginRight: '4px' }}
              />
              RAG
            </label>
            <label style={{ fontSize: '12px' }}>
              <input
                type="checkbox"
                checked={ctxIncludeProcedural.value}
                onChange={(e) => { ctxIncludeProcedural.value = (e.target as HTMLInputElement).checked; }}
                style={{ marginRight: '4px' }}
              />
              Procedural
            </label>
            <button class="btn btn-sm btn-primary" onClick={() => void buildContext()} disabled={ctxLoading.value}>
              {ctxLoading.value ? 'Building…' : 'Build Context'}
            </button>
          </div>
        </div>
        {ctxError.value && <div class="error-banner">{ctxError.value}</div>}
        {!ctxLoading.value && !ctx && !ctxError.value && (
          <div class="empty-state">Select a workload then click "Build Context".</div>
        )}
        {ctx && (
          <div style={{ padding: '0.875rem 1rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.5rem', fontSize: '12px' }}>
              <span>
                Workload: <strong>{ctx.workload_id}</strong> · Lookback: <strong>{ctx.lookback_days}d</strong> · Length: <strong>{ctx.context.length} chars</strong>
              </span>
              <button class="btn btn-sm" onClick={copyContext}>Copy</button>
            </div>
            <pre style={{
              background: 'var(--bg-input)', border: '1px solid var(--border-strong)',
              borderRadius: '6px', padding: '1rem', fontSize: '11px',
              fontFamily: 'Monaco, Menlo, Consolas, monospace',
              whiteSpace: 'pre-wrap', wordBreak: 'break-word',
              maxHeight: '420px', overflowY: 'auto', lineHeight: 1.6,
            }}>{ctx.context || '(empty context)'}</pre>
          </div>
        )}
      </div>
    </div>
  );
}
