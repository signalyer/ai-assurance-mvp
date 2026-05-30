// Surface: AI System Revisions Queue (G-1, S65)
//
// Closes the UI-promise gap surfaced in S64's audit (G-1): the engine has
// had POST /api/ai-systems/revisions/{id}/decide since S13, but CISO had
// no surface to actually use it. Engineers in Team Portal could submit
// edits indefinitely with no inbox/notification on the governance side.
//
// Data:
//   GET  /api/ai-systems/revisions/pending         — org-wide pending list
//   GET  /api/ai-systems/revisions/{rev_id}        — single revision detail (lazy on row open)
//   POST /api/ai-systems/revisions/{rev_id}/decide — approve | reject | override
//
// Pattern: mirrors RtfApprovalQueuePage.tsx — pending table + modal +
// audit-friendly status badges. Per V2-PORTAL-SPLIT.md §3, Team Portal
// submits the edit, CISO Console decides.

import { signal, computed } from '@preact/signals';
import { useEffect } from 'preact/hooks';
import { apiGet, apiPost } from '../../shared/api/client';
import type {
  Revision,
  RevisionsListResponse,
  DecideResponse,
  Decision,
} from './types';

// ============================================================
// Module-level signals
// ============================================================

const pending = signal<Revision[]>([]);
const pendingLoading = signal<boolean>(true);
const pendingError = signal<string | null>(null);

// Decide modal (approve OR reject OR override — verb determines title/copy).
const decideTarget = signal<Revision | null>(null);
const decideMode = signal<Decision>('APPROVE');
const decideNote = signal<string>('');
const decideRoleOverride = signal<string>(''); // optional; server defaults
const decideSaving = signal<boolean>(false);
const decideError = signal<string | null>(null);

const ACTOR = 'demo-ciso';

const kpis = computed(() => {
  const rows = pending.value;
  const byTier: Record<string, number> = {};
  for (const r of rows) {
    const t = String(r.tier ?? 'unknown');
    byTier[t] = (byTier[t] ?? 0) + 1;
  }
  return {
    pending: rows.length,
    critical: byTier.critical ?? 0,
    material: byTier.material ?? 0,
    soft: byTier.soft ?? 0,
  };
});

// ============================================================
// Data loaders
// ============================================================

async function loadPending(): Promise<void> {
  pendingLoading.value = true;
  pendingError.value = null;
  const r = await apiGet<RevisionsListResponse>('/ai-systems/revisions/pending');
  if (r.ok) {
    pending.value = r.data.revisions ?? [];
  } else {
    pendingError.value = r.detail;
  }
  pendingLoading.value = false;
}

// ============================================================
// Decide flow
// ============================================================

function openDecide(rev: Revision, mode: Decision): void {
  decideTarget.value = rev;
  decideMode.value = mode;
  decideNote.value = '';
  decideRoleOverride.value = '';
  decideError.value = null;
}

function closeDecide(): void {
  decideTarget.value = null;
  decideSaving.value = false;
}

async function confirmDecide(): Promise<void> {
  const target = decideTarget.value;
  if (!target) return;

  // Reject + override require a note for audit traceability; approve is optional.
  // Mirrors RtfApprovalQueuePage convention so CISO muscle-memory transfers.
  if (decideMode.value !== 'APPROVE' && !decideNote.value.trim()) {
    decideError.value =
      decideMode.value === 'REJECT'
        ? 'Rejection reason is required.'
        : 'Override justification is required.';
    return;
  }

  decideSaving.value = true;
  decideError.value = null;

  const id = encodeURIComponent(target.revision_id);
  const body: Record<string, unknown> = {
    decision: decideMode.value,
    note: decideNote.value.trim(),
  };
  if (decideRoleOverride.value.trim()) {
    body.role = decideRoleOverride.value.trim();
  }

  const r = await apiPost<DecideResponse>(
    `/ai-systems/revisions/${id}/decide`,
    body,
  );
  decideSaving.value = false;

  if (r.ok) {
    closeDecide();
    await loadPending();
  } else {
    // 409 surfaces as the engine's ConflictDetail — apiPost flattens to .detail.
    decideError.value = `Action failed: ${r.detail}`;
  }
}

// ============================================================
// Helpers
// ============================================================

function fmtTs(ts: string | null | undefined): string {
  return (ts ?? '').slice(0, 19).replace('T', ' ');
}

function tierBadgeClass(tier: string): string {
  if (tier === 'critical') return 'badge badge-critical';
  if (tier === 'material') return 'badge badge-high';
  if (tier === 'soft') return 'badge badge-info';
  return 'badge badge-neutral';
}

function fmtVal(v: unknown): string {
  if (v === null || v === undefined) return '—';
  if (typeof v === 'string') return v;
  if (typeof v === 'number' || typeof v === 'boolean') return String(v);
  try {
    return JSON.stringify(v);
  } catch {
    return String(v);
  }
}

function changeSummary(rev: Revision): string {
  // noUncheckedIndexedAccess: changed[i] is FieldChange|undefined, so map and
  // filter rather than positional access. .map().filter(Boolean) gives a
  // narrowed string[].
  const fields = (rev.fields_changed ?? [])
    .map((c) => c?.field)
    .filter((f): f is string => typeof f === 'string');
  const n = fields.length;
  if (n === 0) return 'no fields';
  if (n === 1) return `1 field: ${fields[0]}`;
  return `${n} fields: ${fields.slice(0, 3).join(', ')}${n > 3 ? '…' : ''}`;
}

// ============================================================
// Component
// ============================================================

export function RevisionsQueuePage() {
  useEffect(() => {
    void loadPending();
  }, []);

  return (
    <div>
      <div class="page-header">
        <div>
          <div class="page-title">AI System Revisions</div>
          <div class="page-subtitle">
            Engineer-submitted edits awaiting governance decision · approve / reject / override ·
            each decision is recorded against the tamper-evident audit chain
          </div>
        </div>
        <div class="page-actions">
          <span style={{ fontSize: 11, color: 'var(--text-secondary)' }}>
            Acting as <strong>{ACTOR}</strong>
          </span>
          <button class="btn btn-sm" onClick={() => void loadPending()}>
            Refresh
          </button>
        </div>
      </div>

      <KpiRow />

      <div class="card mb-4">
        <div class="card-header">
          <div>
            <div class="card-title">Pending Decisions</div>
            <div class="card-subtitle">
              {pending.value.length} revision{pending.value.length !== 1 ? 's' : ''} awaiting CISO
              decision — release is blocked on every system with a pending material edit
            </div>
          </div>
        </div>
        <PendingTable />
      </div>

      <DecideModal />
    </div>
  );
}

function KpiRow() {
  const k = kpis.value;
  return (
    <div class="kpi-row">
      <Kpi label="Pending Total" value={k.pending} tone="medium" />
      <Kpi label="Critical Tier" value={k.critical} tone="critical" />
      <Kpi label="Material Tier" value={k.material} tone="high" />
      <Kpi label="Soft Tier" value={k.soft} />
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

  if (pendingLoading.value && rows.length === 0) {
    return <div class="loading" style={{ padding: '1.5rem' }}>Loading pending revisions…</div>;
  }
  if (pendingError.value) {
    return <div class="error-banner" style={{ margin: '1rem' }}>Failed to load: {pendingError.value}</div>;
  }
  if (rows.length === 0) {
    return <div class="empty-state">No revisions awaiting decision.</div>;
  }

  return (
    <table class="data-table">
      <thead>
        <tr>
          <th>Submitted</th>
          <th>AI System</th>
          <th>Tier</th>
          <th>Author</th>
          <th>Change</th>
          <th>Reason</th>
          <th>Revision ID</th>
          <th>Actions</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.revision_id}>
            <td class="text-xs text-tertiary">{fmtTs(r.created_at)}</td>
            <td>
              <span class="mono">{r.ai_system_id}</span>
            </td>
            <td>
              <span class={tierBadgeClass(String(r.tier))}>{String(r.tier)}</span>
            </td>
            <td class="text-xs">{r.created_by}</td>
            <td class="text-xs" style={{ maxWidth: 260 }}>
              {changeSummary(r)}
            </td>
            <td class="text-xs" style={{ maxWidth: 240 }}>
              {r.change_reason ?? '—'}
            </td>
            <td>
              <span class="mono" title={r.revision_id}>
                {r.revision_id.slice(0, 12)}…
              </span>
            </td>
            <td>
              <div style={{ display: 'flex', gap: '0.375rem' }}>
                <button
                  class="btn btn-sm btn-primary"
                  onClick={() => openDecide(r, 'APPROVE')}
                >
                  Approve
                </button>
                <button
                  class="btn btn-sm"
                  style={{ borderColor: 'var(--critical)', color: 'var(--critical)' }}
                  onClick={() => openDecide(r, 'REJECT')}
                >
                  Reject
                </button>
                {r.tier === 'critical' && (
                  <button
                    class="btn btn-sm"
                    title="Override the standard approval requirement (e.g. emergency rollback). Justification mandatory."
                    onClick={() => openDecide(r, 'OVERRIDE')}
                  >
                    Override
                  </button>
                )}
              </div>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function DecideModal() {
  const target = decideTarget.value;
  if (!target) return null;

  const mode = decideMode.value;
  const title =
    mode === 'APPROVE'
      ? `Approve Revision — ${target.ai_system_id}`
      : mode === 'REJECT'
        ? `Reject Revision — ${target.ai_system_id}`
        : `Override Revision — ${target.ai_system_id}`;

  const confirmLabel =
    mode === 'APPROVE'
      ? 'Confirm Approval'
      : mode === 'REJECT'
        ? 'Confirm Rejection'
        : 'Confirm Override';

  const noteLabel =
    mode === 'APPROVE'
      ? 'Approval Note (optional)'
      : mode === 'REJECT'
        ? 'Rejection Reason *'
        : 'Override Justification *';

  return (
    <div class="modal-overlay" onClick={closeDecide}>
      <div class="modal" onClick={(e) => e.stopPropagation()}>
        <div class="modal-header">
          <div class="modal-title">{title}</div>
          <button class="btn btn-sm" onClick={closeDecide}>✕</button>
        </div>
        <div class="modal-body">
          <div class="text-xs text-tertiary" style={{ marginBottom: 4 }}>
            Revision: <span class="mono">{target.revision_id}</span>
          </div>
          <div class="text-xs text-secondary" style={{ marginBottom: 8 }}>
            Tier: <span class={tierBadgeClass(String(target.tier))}>{String(target.tier)}</span> ·
            Author: {target.created_by} · Category: {target.change_category ?? '—'}
          </div>

          {target.change_reason && (
            <div class="text-xs text-secondary" style={{ marginBottom: 8 }}>
              <strong>Author reason:</strong> {target.change_reason}
            </div>
          )}

          {target.fields_changed && target.fields_changed.length > 0 && (
            <div style={{ marginBottom: 12 }}>
              <div class="text-xs text-tertiary" style={{ marginBottom: 4 }}>
                Proposed changes ({target.fields_changed.length}):
              </div>
              <table class="data-table" style={{ fontSize: 11 }}>
                <thead>
                  <tr>
                    <th>Field</th>
                    <th>Before</th>
                    <th>After</th>
                  </tr>
                </thead>
                <tbody>
                  {target.fields_changed.map((ch, i) => (
                    <tr key={`${ch.field}-${i}`}>
                      <td class="mono">{ch.field}</td>
                      <td class="text-tertiary" style={{ maxWidth: 200, wordBreak: 'break-word' }}>
                        {fmtVal((ch as Record<string, unknown>).before)}
                      </td>
                      <td style={{ maxWidth: 200, wordBreak: 'break-word' }}>
                        {fmtVal((ch as Record<string, unknown>).after)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {target.required_approver_roles && target.required_approver_roles.length > 0 && (
            <div class="text-xs text-secondary" style={{ marginBottom: 8 }}>
              <strong>Required roles:</strong> {target.required_approver_roles.join(', ')}
            </div>
          )}

          <div class="form-row">
            <label class="form-label">{noteLabel}</label>
            <textarea
              class="form-input"
              rows={3}
              value={decideNote.value}
              onInput={(e) => {
                decideNote.value = (e.currentTarget as HTMLTextAreaElement).value;
              }}
              placeholder={
                mode === 'APPROVE'
                  ? 'e.g. Material change reviewed; aligns with Q2 risk policy'
                  : mode === 'REJECT'
                    ? 'State the policy basis or specific concern blocking approval'
                    : 'State why standard approval is being bypassed (emergency / rollback / etc.)'
              }
            />
          </div>

          <div class="form-row">
            <label class="form-label text-xs">
              Role override <span class="text-tertiary">(optional — defaults from session)</span>
            </label>
            <input
              class="form-input"
              type="text"
              value={decideRoleOverride.value}
              onInput={(e) => {
                decideRoleOverride.value = (e.currentTarget as HTMLInputElement).value;
              }}
              placeholder="e.g. Model Risk Management"
            />
          </div>

          {decideError.value && <div class="error-banner">{decideError.value}</div>}

          <div class="text-xs text-tertiary">Actor: {ACTOR}</div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-sm" onClick={closeDecide}>Cancel</button>
          <button
            class={`btn btn-sm ${mode === 'APPROVE' ? 'btn-primary' : ''}`}
            style={mode !== 'APPROVE' ? { borderColor: 'var(--critical)', color: 'var(--critical)' } : {}}
            disabled={decideSaving.value}
            onClick={() => void confirmDecide()}
          >
            {decideSaving.value ? 'Saving…' : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
