// Surface: RTF Operator Deep View / Forensics (CSM-3)
// NEW route: /rtf-forensics
// V1 ancestor: forensics portion of static/right-to-forget.html
// Distinct from RtfApprovalQueuePage (action-oriented approve/reject).
// This page is forensics-oriented: per-store SHA-256 digests, audit chain proof.
// Endpoints:
//   GET /api/right-to-forget           — list all cascades
//   GET /api/right-to-forget/{id}      — detail with per-store SHA-256
//   GET /api/audit/verify?window=200   — chain proof (verify-now button)

import { signal, computed } from '@preact/signals';
import { useEffect } from 'preact/hooks';
import { apiGet } from '../../shared/api/client';
import type {
  CascadeRow,
  CascadeListResponse,
  CascadeDetail,
  CascadeStatus,
  ChainVerifyResponse,
  PurgeStep,
} from './types';

// ============================================================
// Module-level signals
// ============================================================

const cascades = signal<CascadeRow[]>([]);
const listLoading = signal<boolean>(true);
const listError = signal<string | null>(null);

// Drill modal
const drillTarget = signal<CascadeRow | null>(null);
const drillDetail = signal<CascadeDetail | null>(null);
const drillLoading = signal<boolean>(false);
const drillError = signal<string | null>(null);

// Chain verify (shared — last result)
const chainResult = signal<ChainVerifyResponse | null>(null);
const chainVerifying = signal<boolean>(false);
const chainError = signal<string | null>(null);

// Filter
const filterStatus = signal<string>('ALL');

// ============================================================
// Derived
// ============================================================

const filteredCascades = computed<CascadeRow[]>(() => {
  if (filterStatus.value === 'ALL') return cascades.value;
  return cascades.value.filter((c) => c.status === filterStatus.value);
});

const kpis = computed(() => {
  const all = cascades.value;
  return {
    total: all.length,
    completed: all.filter((c) => c.status === 'COMPLETED').length,
    partial: all.filter((c) => c.status === 'PARTIAL_FAILURE').length,
    pending: all.filter((c) => c.status === 'PENDING_APPROVAL').length,
  };
});

// ============================================================
// Data loaders
// ============================================================

async function loadCascades(): Promise<void> {
  listLoading.value = true;
  listError.value = null;
  const r = await apiGet<CascadeListResponse>('/right-to-forget');
  if (r.ok) {
    // Newest first for forensics view
    cascades.value = [...(r.data.cascades ?? [])].reverse();
  } else {
    listError.value = r.detail;
  }
  listLoading.value = false;
}

async function openDrill(row: CascadeRow): Promise<void> {
  drillTarget.value = row;
  drillDetail.value = null;
  drillError.value = null;
  drillLoading.value = true;

  const id = encodeURIComponent(row.cascade_id);
  const r = await apiGet<CascadeDetail>(`/right-to-forget/${id}`);
  if (r.ok) {
    drillDetail.value = r.data;
  } else {
    drillError.value = r.detail;
  }
  drillLoading.value = false;
}

function closeDrill(): void {
  drillTarget.value = null;
  drillDetail.value = null;
}

async function verifyChain(): Promise<void> {
  chainVerifying.value = true;
  chainError.value = null;
  const r = await apiGet<ChainVerifyResponse>('/audit/verify', { window: 200 });
  if (r.ok) {
    chainResult.value = r.data;
  } else {
    chainError.value = r.detail;
  }
  chainVerifying.value = false;
}

// ============================================================
// Helpers
// ============================================================

function fmtTs(ts: string): string {
  return (ts ?? '').slice(0, 19).replace('T', ' ');
}

function statusBadgeClass(s: CascadeStatus): string {
  if (s === 'PENDING_APPROVAL') return 'badge badge-medium';
  if (s === 'APPROVED') return 'badge badge-info';
  if (s === 'COMPLETED') return 'badge badge-pass';
  if (s === 'REJECTED') return 'badge badge-critical';
  if (s === 'PARTIAL_FAILURE') return 'badge badge-high';
  return 'badge badge-neutral';
}

function stepDigestShort(step: PurgeStep): string {
  if (!step.sha256_digest_after) return '—';
  return step.sha256_digest_after.slice(0, 16) + '…';
}

// ============================================================
// Component
// ============================================================

export function RtfForensicsPage() {
  useEffect(() => { void loadCascades(); }, []);

  return (
    <div>
      <div class="page-header">
        <div>
          <div class="page-title">RTF Forensics</div>
          <div class="page-subtitle">
            Per-store SHA-256 digests · audit chain proof · tamper-evident deletion records
          </div>
        </div>
        <div class="page-actions">
          <ChainVerifyButton />
          <button class="btn btn-sm" onClick={() => void loadCascades()}>Refresh</button>
        </div>
      </div>

      {/* Chain verify result banner */}
      <ChainResultBanner />

      <KpiRow />
      <CascadeCard />
      <DrillModal />
    </div>
  );
}

function ChainVerifyButton() {
  return (
    <button
      class="btn btn-sm btn-primary"
      disabled={chainVerifying.value}
      onClick={() => void verifyChain()}
    >
      {chainVerifying.value ? 'Verifying…' : 'Verify Chain Now'}
    </button>
  );
}

function ChainResultBanner() {
  const result = chainResult.value;
  const err = chainError.value;

  if (!result && !err) return null;

  if (err) {
    return (
      <div class="error-banner" style={{ marginBottom: '1rem' }}>
        Chain verify failed: {err}
      </div>
    );
  }

  if (!result) return null;

  const isClean = result.status === 'CLEAN';
  return (
    <div
      style={{
        marginBottom: '1rem',
        padding: '0.75rem 1rem',
        borderRadius: 6,
        border: `1px solid ${isClean ? 'var(--pass)' : 'var(--critical)'}`,
        background: isClean ? 'rgba(34,197,94,0.06)' : 'rgba(239,68,68,0.06)',
        display: 'flex',
        alignItems: 'center',
        gap: '1rem',
        fontSize: 13,
      }}
    >
      <span
        class={isClean ? 'badge badge-pass' : 'badge badge-critical'}
        style={{ fontSize: 12 }}
      >
        {result.status}
      </span>
      <span>
        {result.events_checked} events checked
        {result.broken_at ? ` · broken at ${result.broken_at}` : ''}
        {result.window_start_event_id
          ? ` · window start ${result.window_start_event_id.slice(0, 12)}…`
          : ''}
      </span>
    </div>
  );
}

function KpiRow() {
  const k = kpis.value;
  return (
    <div class="kpi-row">
      <Kpi label="Total Cascades" value={k.total} />
      <Kpi label="Completed" value={k.completed} tone="pass" />
      <Kpi label="Partial Failures" value={k.partial} tone="critical" />
      <Kpi label="Pending Approval" value={k.pending} tone="medium" />
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

const STATUS_OPTIONS: { value: string; label: string }[] = [
  { value: 'ALL', label: 'All' },
  { value: 'COMPLETED', label: 'Completed' },
  { value: 'PENDING_APPROVAL', label: 'Pending' },
  { value: 'PARTIAL_FAILURE', label: 'Partial Failure' },
  { value: 'REJECTED', label: 'Rejected' },
];

function CascadeCard() {
  return (
    <div class="card">
      <div class="card-header">
        <div>
          <div class="card-title">Deletion Cascades</div>
          <div class="card-subtitle">
            {filteredCascades.value.length} cascade{filteredCascades.value.length !== 1 ? 's' : ''}
            {' '}· click row to inspect per-store digests
          </div>
        </div>
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          {STATUS_OPTIONS.map((o) => (
            <button
              key={o.value}
              class={`btn btn-sm ${filterStatus.value === o.value ? 'btn-primary' : ''}`}
              onClick={() => { filterStatus.value = o.value; }}
            >
              {o.label}
            </button>
          ))}
        </div>
      </div>

      {listLoading.value ? (
        <div class="loading" style={{ padding: '1.5rem' }}>Loading cascades…</div>
      ) : listError.value ? (
        <div class="error-banner" style={{ margin: '1rem' }}>Failed: {listError.value}</div>
      ) : filteredCascades.value.length === 0 ? (
        <div class="empty-state">No cascades match the current filter.</div>
      ) : (
        <table class="data-table">
          <thead>
            <tr>
              <th>Started</th>
              <th>Subject ID</th>
              <th>Status</th>
              <th>Stores Purged</th>
              <th>Requested By</th>
              <th>Cascade ID</th>
              <th>Inspect</th>
            </tr>
          </thead>
          <tbody>
            {filteredCascades.value.map((c) => (
              <tr key={c.cascade_id} style={{ cursor: 'pointer' }} onClick={() => void openDrill(c)}>
                <td class="text-xs text-tertiary">{fmtTs(c.started_at)}</td>
                <td><span class="mono">{c.subject_id}</span></td>
                <td>
                  <span class={statusBadgeClass(c.status)}>
                    {c.status.replace(/_/g, ' ')}
                  </span>
                </td>
                <td class="text-xs">
                  {c.steps ? `${Object.keys(c.steps).length} stores` : '—'}
                </td>
                <td class="text-xs">{c.requested_by}</td>
                <td>
                  <span class="mono" title={c.cascade_id} style={{ fontSize: 11 }}>
                    {c.cascade_id.slice(0, 12)}…
                  </span>
                </td>
                <td>
                  <button
                    class="btn btn-sm"
                    style={{ fontSize: 10 }}
                    onClick={(e) => { e.stopPropagation(); void openDrill(c); }}
                  >
                    Inspect
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function DrillModal() {
  const target = drillTarget.value;
  if (!target) return null;

  const detail = drillDetail.value;

  return (
    <div class="modal-overlay" onClick={closeDrill}>
      <div class="modal" style={{ maxWidth: 720, width: '95vw' }} onClick={(e) => e.stopPropagation()}>
        <div class="modal-header">
          <div class="modal-title">
            Forensic Detail — <span class="mono" style={{ fontSize: 13 }}>{target.subject_id}</span>
          </div>
          <button class="btn btn-sm" onClick={closeDrill}>✕</button>
        </div>

        <div class="modal-body">
          {/* Summary row */}
          <div style={{ display: 'flex', gap: '1rem', marginBottom: '1rem', fontSize: 12, flexWrap: 'wrap' }}>
            <div>
              <span class="text-secondary">Status: </span>
              <span class={statusBadgeClass(target.status)}>{target.status.replace(/_/g, ' ')}</span>
            </div>
            <div>
              <span class="text-secondary">Started: </span>
              <span>{fmtTs(target.started_at)}</span>
            </div>
            {target.completed_at && (
              <div>
                <span class="text-secondary">Completed: </span>
                <span>{fmtTs(target.completed_at)}</span>
              </div>
            )}
            <div>
              <span class="text-secondary">Cascade ID: </span>
              <span class="mono" style={{ fontSize: 11 }}>{target.cascade_id}</span>
            </div>
          </div>

          {drillLoading.value ? (
            <div class="loading" style={{ padding: '1.5rem' }}>Loading digest detail…</div>
          ) : drillError.value ? (
            <div class="error-banner">Failed to load detail: {drillError.value}</div>
          ) : detail ? (
            <DigestTable detail={detail} />
          ) : null}
        </div>

        <div class="modal-footer">
          <button class="btn btn-sm" onClick={closeDrill}>Close</button>
        </div>
      </div>
    </div>
  );
}

function DigestTable({ detail }: { detail: CascadeDetail }) {
  const steps = Object.entries(detail.steps ?? {});

  return (
    <>
      <div class="card-title" style={{ marginBottom: '0.5rem', fontSize: 12 }}>Per-Store Digests</div>
      {steps.length === 0 ? (
        <div class="empty-state">No store steps recorded.</div>
      ) : (
        <table class="data-table" style={{ marginBottom: '1rem' }}>
          <thead>
            <tr>
              <th>Store</th>
              <th>Items Removed</th>
              <th>SHA-256 Digest (after purge)</th>
              <th>Error</th>
            </tr>
          </thead>
          <tbody>
            {steps.map(([key, step]) => (
              <tr key={key}>
                <td>
                  <span class="badge badge-neutral" style={{ fontSize: 10 }}>
                    {step.store || key}
                  </span>
                </td>
                <td>{step.items_removed}</td>
                <td>
                  {step.sha256_digest_after ? (
                    <span class="mono" style={{ fontSize: 11 }} title={step.sha256_digest_after}>
                      {stepDigestShort(step)}
                    </span>
                  ) : (
                    <span class="text-tertiary">—</span>
                  )}
                </td>
                <td>
                  {step.error ? (
                    <span class="badge badge-critical" style={{ fontSize: 10 }}>{step.error}</span>
                  ) : (
                    <span class="badge badge-pass" style={{ fontSize: 10 }}>OK</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {detail.governance && (
        <div style={{ fontSize: 12 }}>
          <div class="text-secondary" style={{ marginBottom: 4 }}>Governance Metadata</div>
          {detail.governance.chain_hash && (
            <div>
              <span class="text-secondary">Chain Hash: </span>
              <span class="mono" style={{ fontSize: 11 }}>{detail.governance.chain_hash}</span>
            </div>
          )}
          {detail.governance.trace_id && (
            <div style={{ marginTop: 4 }}>
              <span class="text-secondary">Trace ID: </span>
              <span class="mono" style={{ fontSize: 11 }}>{detail.governance.trace_id}</span>
            </div>
          )}
        </div>
      )}
    </>
  );
}
