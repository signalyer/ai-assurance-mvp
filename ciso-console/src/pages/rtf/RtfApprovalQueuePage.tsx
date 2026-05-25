// Surface 3: Right-to-Forget Approval Queue (CSM-1)
// V1 ancestor: static/right-to-forget.html (governance/approval side only)
// Engineer submission side lives in Team Workspace RtfRequestPage.
// Data:
//   GET  /api/right-to-forget?status=pending — pending approval queue
//   POST /api/right-to-forget/{id}/approve   — approve a cascade
// Pattern: mirrors team-portal/src/pages/rtf/RtfRequestPage.tsx structure.

import { signal, computed } from '@preact/signals';
import { useEffect } from 'preact/hooks';
import { apiGet, apiPost } from '../../shared/api/client';
import type { Cascade, CascadeListResponse, ApproveResponse, CascadeStatus } from './types';

// ============================================================
// Module-level signals
// ============================================================

// Approval queue (pending only — the CISO's primary view)
const pending = signal<Cascade[]>([]);
const pendingLoading = signal<boolean>(true);
const pendingError = signal<string | null>(null);

// Full history (all statuses)
const all = signal<Cascade[]>([]);
const allLoading = signal<boolean>(true);

// Approve modal
const approveTarget = signal<Cascade | null>(null);
const approveNote = signal<string>('');
const approveSaving = signal<boolean>(false);
const approveError = signal<string | null>(null);

// Reject flow (inline note in modal, separate call)
const rejectMode = signal<boolean>(false);
const rejectReason = signal<string>('');

const kpis = computed(() => ({
  pending: pending.value.length,
  completed: all.value.filter((c) => c.status === 'COMPLETED').length,
  rejected: all.value.filter((c) => c.status === 'REJECTED').length,
  partial: all.value.filter((c) => c.status === 'PARTIAL_FAILURE').length,
}));

// ============================================================
// Data loaders
// ============================================================

async function loadPending(): Promise<void> {
  pendingLoading.value = true;
  pendingError.value = null;
  const r = await apiGet<CascadeListResponse>('/right-to-forget', { status: 'pending' });
  if (r.ok) {
    pending.value = r.data.cascades ?? [];
  } else {
    pendingError.value = r.detail;
  }
  pendingLoading.value = false;
}

async function loadAll(): Promise<void> {
  allLoading.value = true;
  const r = await apiGet<CascadeListResponse>('/right-to-forget');
  if (r.ok) {
    // Newest first for governance UX
    all.value = [...(r.data.cascades ?? [])].reverse();
  }
  allLoading.value = false;
}

async function loadBoth(): Promise<void> {
  await Promise.all([loadPending(), loadAll()]);
}

// ============================================================
// Approve / reject actions
// ============================================================

function openApprove(cascade: Cascade, reject: boolean): void {
  approveTarget.value = cascade;
  approveNote.value = '';
  rejectMode.value = reject;
  rejectReason.value = '';
  approveError.value = null;
}

function closeApprove(): void {
  approveTarget.value = null;
  approveSaving.value = false;
}

async function confirmApprove(): Promise<void> {
  const target = approveTarget.value;
  if (!target) return;

  if (rejectMode.value && !rejectReason.value.trim()) {
    approveError.value = 'Rejection reason is required.';
    return;
  }

  approveSaving.value = true;
  approveError.value = null;

  const id = encodeURIComponent(target.cascade_id);
  const path = rejectMode.value
    ? `/right-to-forget/${id}/reject`
    : `/right-to-forget/${id}/approve`;

  const body = rejectMode.value
    ? { reason: rejectReason.value.trim(), actor: ACTOR }
    : { note: approveNote.value.trim() || null, actor: ACTOR };

  const r = await apiPost<ApproveResponse>(path, body);
  approveSaving.value = false;

  if (r.ok) {
    closeApprove();
    await loadBoth();
  } else {
    approveError.value = `Action failed: ${r.detail}`;
  }
}

// ============================================================
// Helpers
// ============================================================

const ACTOR = 'demo-ciso';

function fmtTs(ts: string): string {
  return (ts || '').slice(0, 19).replace('T', ' ');
}

function statusBadgeClass(s: CascadeStatus): string {
  if (s === 'PENDING_APPROVAL') return 'badge badge-medium';
  if (s === 'APPROVED') return 'badge badge-info';
  if (s === 'COMPLETED') return 'badge badge-pass';
  if (s === 'REJECTED') return 'badge badge-critical';
  if (s === 'PARTIAL_FAILURE') return 'badge badge-high';
  return 'badge badge-neutral';
}

function stepSummary(c: Cascade): string {
  if (!c.steps) return '—';
  const steps = Object.values(c.steps);
  const removed = steps.reduce((s, x) => s + (x.items_removed || 0), 0);
  const errored = steps.filter((x) => x.error).length;
  return `${steps.length} stores · ${removed} items removed${errored ? ` · ${errored} errored` : ''}`;
}

// ============================================================
// Component
// ============================================================

export function RtfApprovalQueuePage() {
  useEffect(() => { void loadBoth(); }, []);

  return (
    <div>
      <div class="page-header">
        <div>
          <div class="page-title">Right-to-Forget Approvals</div>
          <div class="page-subtitle">
            GDPR Art. 17 deletion cascade approvals · approve to execute cross-store purge · each decision is tamper-evident in the audit chain
          </div>
        </div>
        <div class="page-actions">
          <span style={{ fontSize: 11, color: 'var(--text-secondary)' }}>
            Acting as <strong>{ACTOR}</strong>
          </span>
          <button class="btn btn-sm" onClick={() => void loadBoth()}>Refresh</button>
        </div>
      </div>

      <KpiRow />

      <div class="card mb-4">
        <div class="card-header">
          <div>
            <div class="card-title">Pending Approval</div>
            <div class="card-subtitle">
              {pending.value.length} cascade{pending.value.length !== 1 ? 's' : ''} awaiting CISO decision
            </div>
          </div>
        </div>
        <PendingTable />
      </div>

      <div class="card">
        <div class="card-header">
          <div>
            <div class="card-title">Full History</div>
            <div class="card-subtitle">All cascades — approved, completed, rejected, partial failures</div>
          </div>
        </div>
        <HistoryTable />
      </div>

      <ApproveModal />
    </div>
  );
}

function KpiRow() {
  const k = kpis.value;
  return (
    <div class="kpi-row">
      <Kpi label="Pending Approval" value={k.pending} tone="medium" />
      <Kpi label="Completed" value={k.completed} tone="pass" />
      <Kpi label="Rejected" value={k.rejected} />
      <Kpi label="Partial Failures" value={k.partial} tone="critical" />
    </div>
  );
}

function Kpi({ label, value, tone }: { label: string; value: number; tone?: string }) {
  return (
    <div class="kpi-card">
      <div class="kpi-label">{label}</div>
      <div class={`kpi-value ${tone ?? ''}`}>{value}</div>
    </div>
  );
}

function PendingTable() {
  const rows = pending.value;

  if (pendingLoading.value) return <div class="loading" style={{ padding: '1.5rem' }}>Loading pending requests…</div>;
  if (pendingError.value) return <div class="error-banner" style={{ margin: '1rem' }}>Failed to load: {pendingError.value}</div>;
  if (rows.length === 0) return <div class="empty-state">No cascades awaiting approval.</div>;

  return (
    <table class="data-table">
      <thead>
        <tr>
          <th>Requested</th>
          <th>Subject ID</th>
          <th>Reason</th>
          <th>Requested By</th>
          <th>Cascade ID</th>
          <th>Actions</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((c) => (
          <tr key={c.cascade_id}>
            <td class="text-xs text-tertiary">{fmtTs(c.started_at)}</td>
            <td><span class="mono">{c.subject_id}</span></td>
            <td class="text-xs" style={{ maxWidth: 280 }}>{c.reason}</td>
            <td class="text-xs">{c.requested_by}</td>
            <td><span class="mono" title={c.cascade_id}>{c.cascade_id.slice(0, 12)}…</span></td>
            <td>
              <div style={{ display: 'flex', gap: '0.375rem' }}>
                <button
                  class="btn btn-sm btn-primary"
                  onClick={() => openApprove(c, false)}
                >
                  Approve
                </button>
                <button
                  class="btn btn-sm"
                  style={{ borderColor: 'var(--critical)', color: 'var(--critical)' }}
                  onClick={() => openApprove(c, true)}
                >
                  Reject
                </button>
              </div>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function HistoryTable() {
  const rows = all.value;

  if (allLoading.value) return <div class="loading" style={{ padding: '1.5rem' }}>Loading history…</div>;
  if (rows.length === 0) return <div class="empty-state">No cascade history on record.</div>;

  return (
    <table class="data-table">
      <thead>
        <tr>
          <th>Started</th>
          <th>Subject</th>
          <th>Status</th>
          <th>Stores</th>
          <th>Requested By</th>
          <th>Approved By</th>
          <th>Cascade ID</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((c) => (
          <tr key={c.cascade_id}>
            <td class="text-xs text-tertiary">{fmtTs(c.started_at)}</td>
            <td><span class="mono">{c.subject_id}</span></td>
            <td><span class={statusBadgeClass(c.status)}>{c.status.replace(/_/g, ' ')}</span></td>
            <td class="text-xs">{stepSummary(c)}</td>
            <td class="text-xs">{c.requested_by}</td>
            <td class="text-xs">{c.approved_by ?? '—'}</td>
            <td><span class="mono" title={c.cascade_id}>{c.cascade_id.slice(0, 12)}…</span></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function ApproveModal() {
  const target = approveTarget.value;
  if (!target) return null;

  const isReject = rejectMode.value;
  const title = isReject
    ? `Reject Cascade — ${target.subject_id}`
    : `Approve Cascade — ${target.subject_id}`;

  return (
    <div class="modal-overlay" onClick={closeApprove}>
      <div class="modal" onClick={(e) => e.stopPropagation()}>
        <div class="modal-header">
          <div class="modal-title">{title}</div>
          <button class="btn btn-sm" onClick={closeApprove}>✕</button>
        </div>
        <div class="modal-body">
          <div class="text-xs text-tertiary" style={{ marginBottom: 4 }}>
            Subject: <span class="mono">{target.subject_id}</span>
          </div>
          <div class="text-xs text-secondary" style={{ marginBottom: 8 }}>
            Reason on file: {target.reason}
          </div>

          {isReject ? (
            <div class="form-row">
              <label class="form-label">
                Rejection Reason <span style={{ color: 'var(--critical)' }}>*</span>
              </label>
              <textarea
                class="form-input"
                rows={3}
                value={rejectReason.value}
                onInput={(e) => { rejectReason.value = (e.currentTarget as HTMLTextAreaElement).value; }}
                placeholder="State the legal or policy basis for rejection"
              />
            </div>
          ) : (
            <div class="form-row">
              <label class="form-label">Approval Note <span class="text-tertiary">(optional)</span></label>
              <textarea
                class="form-input"
                rows={3}
                value={approveNote.value}
                onInput={(e) => { approveNote.value = (e.currentTarget as HTMLTextAreaElement).value; }}
                placeholder="e.g. GDPR Art. 17 verified — data subject identity confirmed"
              />
            </div>
          )}

          {approveError.value && (
            <div class="error-banner">{approveError.value}</div>
          )}

          <div class="text-xs text-tertiary">Actor: {ACTOR}</div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-sm" onClick={closeApprove}>Cancel</button>
          <button
            class={`btn btn-sm ${isReject ? '' : 'btn-primary'}`}
            style={isReject ? { borderColor: 'var(--critical)', color: 'var(--critical)' } : {}}
            disabled={approveSaving.value}
            onClick={() => void confirmApprove()}
          >
            {approveSaving.value
              ? 'Saving…'
              : isReject
              ? 'Confirm Rejection'
              : 'Confirm Approval'}
          </button>
        </div>
      </div>
    </div>
  );
}
