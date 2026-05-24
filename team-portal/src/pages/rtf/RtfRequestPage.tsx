// Right-to-Forget — engineer-side surface (V2 plan #10).
// Engineers submit a cascade (subject_id + reason) and see their own history.
// Per-store sha256 forensics + cross-team approval queue live on CISO Console.

import { signal, computed } from '@preact/signals';
import { useEffect } from 'preact/hooks';
import { apiGet, apiPost } from '../../shared/api/client';
import type { CascadeResult, CascadeListResponse } from './types';

const ACTOR = 'demo-engineer';
const SUBJECT_PATTERN = /^[A-Za-z0-9._@\-]+$/;

const cascades = signal<CascadeResult[]>([]);
const listLoading = signal<boolean>(true);
const listError = signal<string | null>(null);

const subjectId = signal<string>('');
const reason = signal<string>('');
const submitting = signal<boolean>(false);
const submitError = signal<string | null>(null);
const submitResult = signal<CascadeResult | null>(null);

const subjectValid = computed<string | null>(() => {
  const v = subjectId.value.trim();
  if (!v) return null;
  if (v.length > 256) return 'Subject ID must be <= 256 characters';
  if (!SUBJECT_PATTERN.test(v)) return 'Subject ID may only contain letters, digits, and . _ @ -';
  return null;
});

const formValid = computed<boolean>(() => {
  const v = subjectId.value.trim();
  const r = reason.value.trim();
  return v.length > 0 && SUBJECT_PATTERN.test(v) && v.length <= 256
    && r.length > 0 && r.length <= 1024;
});

async function loadCascades(): Promise<void> {
  listLoading.value = true;
  listError.value = null;
  const r = await apiGet<CascadeListResponse>('/right-to-forget');
  if (r.ok) {
    // Newest first for engineer UX (V1 returned oldest-first envelope)
    cascades.value = [...(r.data.cascades ?? [])].reverse();
  } else {
    listError.value = r.detail;
  }
  listLoading.value = false;
}

async function submit(): Promise<void> {
  if (!formValid.value) return;
  submitting.value = true;
  submitError.value = null;
  submitResult.value = null;
  const r = await apiPost<CascadeResult>('/right-to-forget', {
    subject_id: subjectId.value.trim(),
    reason: reason.value.trim(),
  });
  if (r.ok) {
    submitResult.value = r.data;
    subjectId.value = '';
    reason.value = '';
    await loadCascades();
  } else {
    submitError.value = r.detail;
  }
  submitting.value = false;
}

function statusBadgeClass(s: string): string {
  if (s === 'COMPLETED') return 'pill-success';
  if (s === 'PARTIAL_FAILURE') return 'pill-failure';
  if (s === 'ALREADY_COMPLETED') return 'pill-review';
  return '';
}

function fmtTs(ts: string): string {
  return (ts || '').slice(0, 19).replace('T', ' ');
}

function stepSummary(c: CascadeResult): string {
  const steps = Object.values(c.steps || {});
  const removed = steps.reduce((s, x) => s + (x.items_removed || 0), 0);
  const errored = steps.filter((x) => x.error).length;
  return `${steps.length} stores · ${removed} items removed${errored ? ` · ${errored} errored` : ''}`;
}

export function RtfRequestPage() {
  useEffect(() => { void loadCascades(); }, []);

  const rows = cascades.value;
  const sv = subjectValid.value;

  return (
    <div>
      <div class="page-header">
        <div>
          <div class="page-title">Right-to-Forget</div>
          <div class="page-subtitle">
            Submit a deletion cascade for a data subject. The cascade purges across vault · T2 episodic · T3 RAG · Langfuse, emits a tamper-evident audit event, and returns per-store SHA-256 digests. Approvals and cross-team queue live on the CISO Console.
          </div>
        </div>
        <div class="page-actions">
          <span style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>
            Submitting as <strong>{ACTOR}</strong>
          </span>
          <button class="btn btn-sm" onClick={() => void loadCascades()}>Refresh</button>
        </div>
      </div>

      <div class="card">
        <div class="card-header">
          <div>
            <div class="card-title">New cascade request</div>
            <div class="card-subtitle">
              Subject ID is the identifier the cascade hunts across stores. Reason is permanently recorded in the audit chain.
            </div>
          </div>
        </div>
        <div style={{ padding: '0.875rem 1rem', display: 'grid', gap: '0.75rem' }}>
          <div>
            <label style={{ display: 'block', fontSize: '11px', color: 'var(--text-secondary)', textTransform: 'uppercase', marginBottom: '0.25rem' }}>
              Subject ID
            </label>
            <input
              type="text"
              class="filter-select"
              style={{ width: '100%' }}
              placeholder="e.g. user-12345 or jane.doe@example.com"
              value={subjectId.value}
              maxLength={256}
              onInput={(e) => { subjectId.value = (e.target as HTMLInputElement).value; }}
            />
            {sv && <div style={{ fontSize: '11px', color: 'var(--critical)', marginTop: '0.25rem' }}>{sv}</div>}
          </div>
          <div>
            <label style={{ display: 'block', fontSize: '11px', color: 'var(--text-secondary)', textTransform: 'uppercase', marginBottom: '0.25rem' }}>
              Reason ({reason.value.length}/1024)
            </label>
            <textarea
              class="filter-select"
              style={{ width: '100%', minHeight: '80px', fontFamily: 'inherit', resize: 'vertical' }}
              placeholder="GDPR Art. 17 request from data subject, ticket SUP-1234"
              value={reason.value}
              maxLength={1024}
              onInput={(e) => { reason.value = (e.target as HTMLTextAreaElement).value; }}
            />
          </div>
          {submitError.value && <div class="error-banner">Cascade failed: {submitError.value}</div>}
          {submitResult.value && (
            <div style={{
              background: 'var(--pass-bg)', border: '1px solid var(--pass)',
              borderRadius: '6px', padding: '0.625rem 0.875rem', fontSize: '12px',
            }}>
              <strong>Cascade {submitResult.value.status.toLowerCase()}</strong> for subject{' '}
              <span class="mono">{submitResult.value.subject_id}</span> · cascade ID{' '}
              <span class="mono">{submitResult.value.cascade_id.slice(0, 12)}…</span> · {stepSummary(submitResult.value)}
            </div>
          )}
          <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
            <button
              class="btn btn-sm btn-primary"
              onClick={() => void submit()}
              disabled={!formValid.value || submitting.value}
            >
              {submitting.value ? 'Cascading…' : 'Submit cascade'}
            </button>
          </div>
        </div>
      </div>

      <div class="card">
        <div class="card-header">
          <div>
            <div class="card-title">Recent cascades</div>
            <div class="card-subtitle">All cascades in this engine. Tamper-evident — every entry is in the audit chain.</div>
          </div>
        </div>
        {listError.value && <div class="error-banner">Failed to load cascades: {listError.value}</div>}
        {listLoading.value && <div class="loading">Loading cascades…</div>}
        {!listLoading.value && rows.length === 0 && !listError.value && (
          <div class="empty-state">No cascades on record yet.</div>
        )}
        {rows.length > 0 && (
          <table class="data-table">
            <thead>
              <tr>
                <th>Started</th><th>Subject</th><th>Status</th><th>Stores</th><th>Cascade ID</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.cascade_id}>
                  <td><span class="mono">{fmtTs(c.started_at)}</span></td>
                  <td><span class="mono">{c.subject_id}</span></td>
                  <td><span class={`pill ${statusBadgeClass(c.status)}`}>{c.status}</span></td>
                  <td>{stepSummary(c)}</td>
                  <td><span class="mono" title={c.cascade_id}>{c.cascade_id.slice(0, 12)}…</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
