// Revision History panel — shows append-only revision records for one AI
// system. Read-only in this commit; approve/reject (decide) is the CISO
// Console's responsibility (Week 3) via POST /api/ai-systems/revisions/{id}/decide.

import { signal } from '@preact/signals';
import { useEffect } from 'preact/hooks';
import { apiGet } from '../../shared/api/client';
import type { Revision, RevisionsListResponse } from './types';

const openSystemId = signal<string | null>(null);
const revisions = signal<Revision[]>([]);
const loading = signal<boolean>(false);
const loadError = signal<string | null>(null);
const expandedRevId = signal<string | null>(null);

export function openRevisions(id: string): void {
  openSystemId.value = id;
  expandedRevId.value = null;
}

function closeRevisions(): void {
  openSystemId.value = null;
  revisions.value = [];
  loadError.value = null;
  expandedRevId.value = null;
}

async function loadRevisions(id: string): Promise<void> {
  loading.value = true;
  loadError.value = null;
  revisions.value = [];
  const r = await apiGet<RevisionsListResponse>(
    `/ai-systems/${encodeURIComponent(id)}/revisions`,
  );
  if (r.ok) {
    revisions.value = r.data.revisions ?? [];
  } else {
    loadError.value = r.detail;
  }
  loading.value = false;
}

function statusBadgeClass(status?: string): string {
  switch (status) {
    case 'approved':
    case 'auto_applied':
      return 'badge badge-success';
    case 'rejected':
      return 'badge badge-critical';
    case 'pending':
      return 'badge badge-warning';
    case 'overridden':
      return 'badge badge-info';
    default:
      return 'badge';
  }
}

function fmtDate(iso?: string): string {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function fmtValue(v: unknown): string {
  if (v === null || v === undefined) return '∅';
  if (Array.isArray(v)) return v.join(', ');
  if (typeof v === 'object') return JSON.stringify(v);
  return String(v);
}

export function AiSystemRevisionsPanel() {
  const id = openSystemId.value;

  useEffect(() => {
    if (id) void loadRevisions(id);
  }, [id]);

  if (!id) return null;

  const isOpen = id !== null;
  const revs = revisions.value;

  return (
    <>
      <div class={`drawer-overlay ${isOpen ? 'open' : ''}`} onClick={closeRevisions} />
      <aside class={`drawer ${isOpen ? 'open' : ''}`} aria-hidden={!isOpen} style={{ width: 640 }}>
        <div class="drawer-header">
          <div class="drawer-title">Revision History</div>
          <button class="drawer-close" onClick={closeRevisions} aria-label="Close">×</button>
        </div>
        <div class="drawer-body">
          <div class="text-xs text-tertiary" style={{ marginBottom: 12 }}>
            System <span class="font-mono">{id}</span> · {revs.length} revision{revs.length === 1 ? '' : 's'}
          </div>

          {loading.value && <div class="loading">Loading…</div>}
          {loadError.value && <div class="error-banner">Failed to load revisions: {loadError.value}</div>}

          {!loading.value && !loadError.value && revs.length === 0 && (
            <div class="empty-state">No revisions yet for this system.</div>
          )}

          {!loading.value && revs.map((r) => {
            const isExpanded = expandedRevId.value === r.revision_id;
            return (
              <div
                key={r.revision_id}
                style={{
                  border: '1px solid var(--border)',
                  borderRadius: 4,
                  marginBottom: 10,
                  padding: '0.75rem',
                }}
              >
                <div
                  style={{ display: 'flex', justifyContent: 'space-between', cursor: 'pointer' }}
                  onClick={() => {
                    expandedRevId.value = isExpanded ? null : r.revision_id;
                  }}
                >
                  <div>
                    <div class="font-mono text-xs">{r.revision_id}</div>
                    <div class="text-sm" style={{ marginTop: 2 }}>
                      <span class={`badge ${r.tier === 'material' ? 'badge-warning' : 'badge-info'}`}>{r.tier}</span>
                      {' '}
                      <span class={statusBadgeClass(r.approval_status)}>{r.approval_status ?? '—'}</span>
                      {' '}
                      <span class="text-tertiary">·</span>
                      {' '}
                      {r.fields_changed.length} field{r.fields_changed.length === 1 ? '' : 's'}
                    </div>
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <div class="text-xs text-tertiary">{fmtDate(r.created_at)}</div>
                    <div class="text-xs">{r.created_by}</div>
                  </div>
                </div>

                {isExpanded && (
                  <div style={{ marginTop: 10, paddingTop: 10, borderTop: '1px solid var(--border)' }}>
                    {r.change_reason && (
                      <div style={{ marginBottom: 8 }}>
                        <div class="drawer-section-title">Reason</div>
                        <div class="text-sm">{r.change_reason}</div>
                        {r.change_category && (
                          <div class="text-xs text-tertiary">Category: {r.change_category}</div>
                        )}
                      </div>
                    )}

                    <div style={{ marginBottom: 8 }}>
                      <div class="drawer-section-title">Field Changes</div>
                      <table class="data-table" style={{ fontSize: 12 }}>
                        <thead>
                          <tr><th>Field</th><th>Before</th><th>After</th></tr>
                        </thead>
                        <tbody>
                          {r.fields_changed.map((c, i) => (
                            <tr key={i}>
                              <td class="font-mono">{c.field}</td>
                              <td class="text-tertiary">{fmtValue(c.before)}</td>
                              <td>{fmtValue(c.after)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>

                    {r.approvers && r.approvers.length > 0 && (
                      <div style={{ marginBottom: 8 }}>
                        <div class="drawer-section-title">Approvers</div>
                        {r.approvers.map((a, i) => (
                          <div key={i} class="text-xs" style={{ marginBottom: 4 }}>
                            <span class="font-mono">{a.decision}</span>
                            {' '}by <strong>{a.user}</strong> ({a.role})
                            {' '}<span class="text-tertiary">@ {fmtDate(a.signed_at)}</span>
                            {a.note && <div style={{ marginLeft: 12, color: 'var(--text-secondary)' }}>{a.note}</div>}
                          </div>
                        ))}
                      </div>
                    )}

                    {r.required_approver_roles && r.required_approver_roles.length > 0 && (
                      <div class="text-xs text-tertiary">
                        Required roles: {r.required_approver_roles.join(', ')}
                      </div>
                    )}

                    {r.triggered_reruns && r.triggered_reruns.length > 0 && (
                      <div class="text-xs text-tertiary" style={{ marginTop: 4 }}>
                        Triggers re-runs: {r.triggered_reruns.join(', ')}
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </aside>
    </>
  );
}
