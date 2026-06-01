// RAG corpus management — Team Workspace surface #9.
// Engineers see corpus stats, run hybrid search, index documents (PII-scrubbed
// by default), and delete by doc_id. Wraps /api/rag/* endpoints introduced in
// commit A of Session 18 (api/rag.py). Engine code unchanged.
//
// Fail-soft contract honoured at the UI: when rag_enabled=false (no Azure
// creds in dev), every panel still renders with truthful empty states and
// a single "RAG backend disabled" banner — never a blank page.

import { signal, computed } from '@preact/signals';
import { useEffect } from 'preact/hooks';
import { apiGet, apiPost, apiDelete } from '../../shared/api/client';
import type {
  RagStats,
  SearchResponse,
  SearchResultItem,
  IndexDocumentResponse,
  DeleteDocumentResponse,
} from './types';

const DOC_ID_PATTERN = /^[A-Za-z0-9_=\-]+$/;
const MAX_CONTENT_CHARS = 100_000;
const MAX_DOC_ID = 256;
const MAX_QUERY = 2048;

// --- Stats ---
const stats = signal<RagStats | null>(null);
const statsLoading = signal<boolean>(true);
const statsError = signal<string | null>(null);

// --- Search ---
const query = signal<string>('');
const topK = signal<number>(5);
const hybrid = signal<boolean>(true);
const searching = signal<boolean>(false);
const searchError = signal<string | null>(null);
const searchResults = signal<SearchResultItem[]>([]);
const searchedFor = signal<string>('');

// --- Index ---
const indexDocId = signal<string>('');
const indexContent = signal<string>('');
const indexMetadata = signal<string>('{}');
const indexScrub = signal<boolean>(true);
const indexing = signal<boolean>(false);
const indexError = signal<string | null>(null);
const indexResult = signal<IndexDocumentResponse | null>(null);

// --- Delete ---
const deleteDocId = signal<string>('');
const deleting = signal<boolean>(false);
const deleteError = signal<string | null>(null);
const deleteResult = signal<DeleteDocumentResponse | null>(null);

// --- Derived state ---
const docIdValid = computed<string | null>(() => {
  const v = indexDocId.value.trim();
  if (!v) return null;
  if (v.length > MAX_DOC_ID) return `Doc ID must be ≤ ${MAX_DOC_ID} characters`;
  if (!DOC_ID_PATTERN.test(v)) return 'Doc ID may only contain letters, digits, - _ =';
  return null;
});

const metadataValid = computed<string | null>(() => {
  const v = indexMetadata.value.trim();
  if (!v) return null;
  try {
    const parsed = JSON.parse(v);
    if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
      return 'Metadata must be a JSON object (e.g. {"source":"docs"})';
    }
    return null;
  } catch {
    return 'Metadata must be valid JSON';
  }
});

const indexFormValid = computed<boolean>(() => {
  const id = indexDocId.value.trim();
  const c = indexContent.value;
  return id.length > 0
    && DOC_ID_PATTERN.test(id)
    && id.length <= MAX_DOC_ID
    && c.length > 0
    && c.length <= MAX_CONTENT_CHARS
    && metadataValid.value === null;
});

const queryValid = computed<boolean>(() => {
  const q = query.value.trim();
  return q.length > 0 && q.length <= MAX_QUERY;
});

// --- API calls ---
async function loadStats(): Promise<void> {
  statsLoading.value = true;
  statsError.value = null;
  const r = await apiGet<RagStats>('/rag/stats');
  if (r.ok) stats.value = r.data;
  else statsError.value = r.detail;
  statsLoading.value = false;
}

async function runSearch(): Promise<void> {
  if (!queryValid.value) return;
  searching.value = true;
  searchError.value = null;
  const q = query.value.trim();
  const r = await apiPost<SearchResponse>('/rag/search', {
    query: q,
    top_k: topK.value,
    hybrid: hybrid.value,
  });
  if (r.ok) {
    searchResults.value = r.data.results;
    searchedFor.value = q;
  } else {
    searchError.value = r.detail;
    searchResults.value = [];
  }
  searching.value = false;
}

async function indexDocument(): Promise<void> {
  if (!indexFormValid.value) return;
  indexing.value = true;
  indexError.value = null;
  indexResult.value = null;
  let parsedMeta: Record<string, unknown> = {};
  try {
    parsedMeta = JSON.parse(indexMetadata.value || '{}');
  } catch {
    indexError.value = 'Metadata must be valid JSON';
    indexing.value = false;
    return;
  }
  const r = await apiPost<IndexDocumentResponse>('/rag/documents', {
    doc_id: indexDocId.value.trim(),
    content: indexContent.value,
    metadata: parsedMeta,
    scrub: indexScrub.value,
  });
  if (r.ok) {
    indexResult.value = r.data;
    if (r.data.indexed) {
      indexDocId.value = '';
      indexContent.value = '';
      indexMetadata.value = '{}';
      await loadStats();
    }
  } else {
    indexError.value = r.detail;
  }
  indexing.value = false;
}

async function removeDocument(idOverride?: string): Promise<void> {
  const id = (idOverride ?? deleteDocId.value).trim();
  if (!id) return;
  if (!DOC_ID_PATTERN.test(id) || id.length > MAX_DOC_ID) {
    deleteError.value = 'Doc ID may only contain letters, digits, - _ =';
    return;
  }
  deleting.value = true;
  deleteError.value = null;
  deleteResult.value = null;
  const r = await apiDelete<DeleteDocumentResponse>(`/rag/documents/${encodeURIComponent(id)}`);
  if (r.ok) {
    deleteResult.value = r.data;
    if (!idOverride) deleteDocId.value = '';
    await loadStats();
  } else {
    deleteError.value = r.detail;
  }
  deleting.value = false;
}

// --- Helpers ---
function fmtTs(ts: string | null): string {
  if (!ts) return '—';
  return ts.slice(0, 19).replace('T', ' ');
}

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

function truncate(s: string, n: number): string {
  return s.length <= n ? s : s.slice(0, n) + '…';
}

export function RagCorpusPage() {
  useEffect(() => { void loadStats(); }, []);

  const s = stats.value;
  const dv = docIdValid.value;
  const mv = metadataValid.value;
  const enabled = s?.rag_enabled ?? false;

  return (
    <div>
      <div class="page-header">
        <div>
          <div class="page-title">RAG Corpus</div>
          <div class="page-subtitle">
            Manage the hybrid (BM25 + semantic vector) retrieval corpus. Documents are PII-scrubbed at index time by default; documents above the PII threshold are rejected and logged. Engineers self-serve; CISO Console retains the rejection audit trail.
          </div>
        </div>
        <div class="page-actions">
          <button class="btn btn-sm" onClick={() => void loadStats()}>Refresh stats</button>
        </div>
      </div>

      <div style={{
        marginBottom: '0.75rem',
        padding: '0.5rem 0.75rem',
        background: 'var(--bg-secondary, rgba(255,255,255,0.04))',
        border: '1px solid var(--border)',
        borderRadius: 4,
        fontSize: 12,
        color: 'var(--text-secondary)',
      }}>
        <strong>This page manages the global Azure AI Search corpus.</strong>{' '}
        Some agents ship with their own local corpus (e.g. <code>vendor_risk</code>{' '}
        — TPRM policy, GDPR Art.28, DORA, NYDFS-500, SCC 2021, prior assessments,
        carve-out playbook). Open <a href="/agent-library?open=vendor_risk">Agent
        Library → vendor_risk → Corpus</a> to browse those docs.
      </div>

      {!statsLoading.value && s && !enabled && (
        <div class="error-banner" style={{ marginBottom: '0.75rem' }}>
          <strong>RAG backend disabled.</strong> Index and search will return safe empties.
          Set <span class="mono">AZURE_SEARCH_ENDPOINT</span>, <span class="mono">AZURE_SEARCH_KEY</span>,
          and <span class="mono">OPENAI_API_KEY</span> on the engine to enable.
        </div>
      )}

      {statsError.value && <div class="error-banner">Failed to load stats: {statsError.value}</div>}

      <div class="kpi-row">
        <div class="kpi-card">
          <div class="kpi-label">Documents indexed</div>
          <div class="kpi-value">{s?.doc_count ?? '—'}</div>
          <div class="kpi-trend">{s ? (enabled ? 'live count from Azure Search' : 'engine disabled') : 'loading'}</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">Index size</div>
          <div class="kpi-value" style={{ fontSize: '20px' }}>{s ? fmtBytes(s.index_size) : '—'}</div>
          <div class="kpi-trend">Azure AI Search storage</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">PII rejections</div>
          <div class="kpi-value">{s?.rejections_total ?? '—'}</div>
          <div class="kpi-trend">cumulative · see data/rag_rejections.jsonl</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">Last updated</div>
          <div class="kpi-value" style={{ fontSize: '14px', lineHeight: 1.4 }}>{fmtTs(s?.last_updated ?? null)}</div>
          <div class="kpi-trend">embedding model: <span class="mono">{s?.embedding_model || '—'}</span></div>
        </div>
      </div>

      <div class="card">
        <div class="card-header">
          <div>
            <div class="card-title">Search corpus</div>
            <div class="card-subtitle">Hybrid scoring blends BM25 keyword and semantic vector similarity (configurable via RAG_HYBRID_SEMANTIC_WEIGHT).</div>
          </div>
        </div>
        <div style={{ padding: '0.875rem 1rem', display: 'grid', gap: '0.625rem' }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 100px 130px auto', gap: '0.5rem', alignItems: 'end' }}>
            <div>
              <label style={{ display: 'block', fontSize: '11px', color: 'var(--text-secondary)', textTransform: 'uppercase', marginBottom: '0.25rem' }}>
                Query ({query.value.length}/{MAX_QUERY})
              </label>
              <input
                type="text"
                class="filter-select"
                style={{ width: '100%' }}
                placeholder="e.g. data residency requirements for EU customers"
                value={query.value}
                maxLength={MAX_QUERY}
                onInput={(e) => { query.value = (e.target as HTMLInputElement).value; }}
                onKeyDown={(e) => { if (e.key === 'Enter' && queryValid.value) void runSearch(); }}
              />
            </div>
            <div>
              <label style={{ display: 'block', fontSize: '11px', color: 'var(--text-secondary)', textTransform: 'uppercase', marginBottom: '0.25rem' }}>
                Top K
              </label>
              <input
                type="number"
                class="filter-select"
                min={1}
                max={50}
                value={topK.value}
                onInput={(e) => { topK.value = Math.max(1, Math.min(50, parseInt((e.target as HTMLInputElement).value || '5', 10))); }}
              />
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.375rem', paddingBottom: '0.375rem' }}>
              <input
                type="checkbox"
                id="rag-hybrid-toggle"
                checked={hybrid.value}
                onChange={(e) => { hybrid.value = (e.target as HTMLInputElement).checked; }}
              />
              <label for="rag-hybrid-toggle" style={{ fontSize: '12px' }}>Hybrid (BM25 + vector)</label>
            </div>
            <button
              class="btn btn-sm btn-primary"
              onClick={() => void runSearch()}
              disabled={!queryValid.value || searching.value}
            >
              {searching.value ? 'Searching…' : 'Search'}
            </button>
          </div>
          {searchError.value && <div class="error-banner">Search failed: {searchError.value}</div>}
        </div>

        {searchedFor.value && !searching.value && (
          <>
            {searchResults.value.length === 0 && (
              <div class="empty-state">
                No results for <span class="mono">{truncate(searchedFor.value, 80)}</span>.{' '}
                {!enabled && <span style={{ opacity: 0.7 }}>(RAG backend is disabled — expected.)</span>}
              </div>
            )}
            {searchResults.value.length > 0 && (
              <table class="data-table">
                <thead>
                  <tr>
                    <th>Doc ID</th>
                    <th>Content preview</th>
                    <th>Score</th>
                    <th>BM25</th>
                    <th>Semantic</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {searchResults.value.map((r) => (
                    <tr key={r.id}>
                      <td><span class="mono">{truncate(r.id, 32)}</span></td>
                      <td>{truncate(r.content, 120)}</td>
                      <td><span class="mono">{r.score.toFixed(3)}</span></td>
                      <td><span class="mono">{r.bm25_score.toFixed(3)}</span></td>
                      <td><span class="mono">{r.semantic_score.toFixed(3)}</span></td>
                      <td>
                        <button
                          class="btn btn-sm"
                          onClick={() => void removeDocument(r.id)}
                          disabled={deleting.value}
                          title="Delete from index"
                        >
                          Delete
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </>
        )}
      </div>

      <div class="card">
        <div class="card-header">
          <div>
            <div class="card-title">Index document</div>
            <div class="card-subtitle">
              PII scrubbing runs before embedding when enabled (recommended). Documents with PII confidence &gt; 0.7 are rejected and logged.
            </div>
          </div>
        </div>
        <div style={{ padding: '0.875rem 1rem', display: 'grid', gap: '0.625rem' }}>
          <div>
            <label style={{ display: 'block', fontSize: '11px', color: 'var(--text-secondary)', textTransform: 'uppercase', marginBottom: '0.25rem' }}>
              Doc ID
            </label>
            <input
              type="text"
              class="filter-select"
              style={{ width: '100%' }}
              placeholder="e.g. policy-eu-residency-v3"
              value={indexDocId.value}
              maxLength={MAX_DOC_ID}
              onInput={(e) => { indexDocId.value = (e.target as HTMLInputElement).value; }}
            />
            {dv && <div style={{ fontSize: '11px', color: 'var(--critical)', marginTop: '0.25rem' }}>{dv}</div>}
          </div>
          <div>
            <label style={{ display: 'block', fontSize: '11px', color: 'var(--text-secondary)', textTransform: 'uppercase', marginBottom: '0.25rem' }}>
              Content ({indexContent.value.length}/{MAX_CONTENT_CHARS})
            </label>
            <textarea
              class="filter-select"
              style={{ width: '100%', minHeight: '120px', fontFamily: 'inherit', resize: 'vertical' }}
              placeholder="Document text. Will be scrubbed of PII before embedding when 'Scrub PII' is enabled."
              value={indexContent.value}
              maxLength={MAX_CONTENT_CHARS}
              onInput={(e) => { indexContent.value = (e.target as HTMLTextAreaElement).value; }}
            />
          </div>
          <div>
            <label style={{ display: 'block', fontSize: '11px', color: 'var(--text-secondary)', textTransform: 'uppercase', marginBottom: '0.25rem' }}>
              Metadata (JSON object)
            </label>
            <input
              type="text"
              class="filter-select mono"
              style={{ width: '100%' }}
              placeholder='{"source":"policy-docs","owner":"compliance-team"}'
              value={indexMetadata.value}
              onInput={(e) => { indexMetadata.value = (e.target as HTMLInputElement).value; }}
            />
            {mv && <div style={{ fontSize: '11px', color: 'var(--critical)', marginTop: '0.25rem' }}>{mv}</div>}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}>
            <input
              type="checkbox"
              id="rag-scrub-toggle"
              checked={indexScrub.value}
              onChange={(e) => { indexScrub.value = (e.target as HTMLInputElement).checked; }}
            />
            <label for="rag-scrub-toggle" style={{ fontSize: '12px' }}>
              Scrub PII before indexing (strongly recommended)
            </label>
          </div>
          {indexError.value && <div class="error-banner">Index failed: {indexError.value}</div>}
          {indexResult.value && indexResult.value.indexed && (
            <div style={{
              background: 'var(--pass-bg)', border: '1px solid var(--pass)',
              borderRadius: '6px', padding: '0.625rem 0.875rem', fontSize: '12px',
            }}>
              <strong>Indexed</strong> <span class="mono">{indexResult.value.doc_id}</span>.
            </div>
          )}
          {indexResult.value && !indexResult.value.indexed && (
            <div class="error-banner">
              <strong>Not indexed:</strong> {indexResult.value.reason || 'unknown reason — check engine logs.'}
            </div>
          )}
          <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
            <button
              class="btn btn-sm btn-primary"
              onClick={() => void indexDocument()}
              disabled={!indexFormValid.value || indexing.value}
            >
              {indexing.value ? 'Indexing…' : 'Index document'}
            </button>
          </div>
        </div>
      </div>

      <div class="card">
        <div class="card-header">
          <div>
            <div class="card-title">Delete document</div>
            <div class="card-subtitle">Idempotent — Azure Search returns success whether or not the doc existed.</div>
          </div>
        </div>
        <div style={{ padding: '0.875rem 1rem', display: 'grid', gap: '0.625rem' }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: '0.5rem', alignItems: 'end' }}>
            <div>
              <label style={{ display: 'block', fontSize: '11px', color: 'var(--text-secondary)', textTransform: 'uppercase', marginBottom: '0.25rem' }}>
                Doc ID to delete
              </label>
              <input
                type="text"
                class="filter-select mono"
                style={{ width: '100%' }}
                placeholder="policy-eu-residency-v3"
                value={deleteDocId.value}
                maxLength={MAX_DOC_ID}
                onInput={(e) => { deleteDocId.value = (e.target as HTMLInputElement).value; }}
              />
            </div>
            <button
              class="btn btn-sm"
              onClick={() => void removeDocument()}
              disabled={!deleteDocId.value.trim() || deleting.value}
            >
              {deleting.value ? 'Deleting…' : 'Delete'}
            </button>
          </div>
          {deleteError.value && <div class="error-banner">Delete failed: {deleteError.value}</div>}
          {deleteResult.value && (
            <div style={{
              background: deleteResult.value.deleted ? 'var(--pass-bg)' : 'var(--review-bg)',
              border: `1px solid ${deleteResult.value.deleted ? 'var(--pass)' : 'var(--review)'}`,
              borderRadius: '6px', padding: '0.625rem 0.875rem', fontSize: '12px',
            }}>
              <strong>{deleteResult.value.deleted ? 'Deleted' : 'Not deleted'}</strong>{' '}
              <span class="mono">{deleteResult.value.doc_id}</span>
              {!deleteResult.value.deleted && !enabled && ' — RAG backend disabled.'}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
