// Surface: Release Gates (CSM-2)
// V1 ancestor: static/release-gates.html
// Endpoints:
//   GET /api/grc/release-gates/v2/systems  — index with per-system rollups
//   GET /api/grc/release-gates/v2/system/{id}  — full gate detail
//   POST /api/grc/release-gates/v2/exception  — CISO override (exception/waiver)
// CISO-specific: Override button on FAILED blocking gates; requires reason modal.
// Note: no /override endpoint exists — the engine exposes /exception for waivers.
//   Button is labelled "Create Exception" to match the engine contract.

import { signal } from '@preact/signals';
import { useEffect } from 'preact/hooks';
import { apiGet, apiPost } from '../../shared/api/client';
import type {
  SystemGateSummary,
  SystemGateSummariesResponse,
  GateReport,
  GateEvaluation,
  ExceptionRequest,
  GateException,
} from './types';

// ============================================================
// Module-level signals
// ============================================================

const summaries = signal<SystemGateSummary[]>([]);
const loading = signal<boolean>(true);
const loadError = signal<string | null>(null);

const expandedId = signal<string | null>(null);
const detailCache = signal<Record<string, GateReport>>({});
const detailLoading = signal<boolean>(false);
const detailError = signal<string | null>(null);

// Override modal
const overrideTarget = signal<{ systemId: string; gate: GateEvaluation } | null>(null);
const overrideReason = signal<string>('');
const overrideSubmitting = signal<boolean>(false);
const overrideError = signal<string | null>(null);
const overrideSuccess = signal<GateException | null>(null);

// ============================================================
// Data load
// ============================================================

async function loadSummaries(): Promise<void> {
  loading.value = true;
  loadError.value = null;
  const r = await apiGet<SystemGateSummariesResponse>('/grc/release-gates/v2/systems');
  if (r.ok) {
    summaries.value = r.data.systems ?? [];
  } else {
    loadError.value = r.detail;
  }
  loading.value = false;
}

async function loadDetail(systemId: string): Promise<void> {
  if (detailCache.value[systemId]) return;
  detailLoading.value = true;
  detailError.value = null;
  const r = await apiGet<GateReport>(`/grc/release-gates/v2/system/${encodeURIComponent(systemId)}`);
  if (r.ok) {
    detailCache.value = { ...detailCache.value, [systemId]: r.data };
  } else {
    detailError.value = r.detail;
  }
  detailLoading.value = false;
}

async function toggleExpand(systemId: string): Promise<void> {
  if (expandedId.value === systemId) {
    expandedId.value = null;
    return;
  }
  expandedId.value = systemId;
  await loadDetail(systemId);
}

async function submitOverride(): Promise<void> {
  const target = overrideTarget.value;
  if (!target) return;
  if (!overrideReason.value.trim()) {
    overrideError.value = 'Reason is required.';
    return;
  }
  overrideSubmitting.value = true;
  overrideError.value = null;

  const today = new Date();
  const expires = new Date(today.getFullYear() + 1, today.getMonth(), today.getDate())
    .toISOString()
    .slice(0, 10);

  const body: ExceptionRequest = {
    ai_system_id: target.systemId,
    gate_id: target.gate.gate_id,
    reason: overrideReason.value.trim(),
    risk_acceptor: 'CISO',
    risk_acceptor_role: 'Chief Information Security Officer',
    expires_at: expires,
    compensating_controls: [],
  };

  const r = await apiPost<GateException>('/grc/release-gates/v2/exception', body);
  if (r.ok) {
    overrideSuccess.value = r.data;
    // Invalidate detail cache for this system so it reloads fresh
    const next = { ...detailCache.value };
    delete next[target.systemId];
    detailCache.value = next;
  } else {
    overrideError.value = r.detail;
  }
  overrideSubmitting.value = false;
}

function closeModal(): void {
  overrideTarget.value = null;
  overrideReason.value = '';
  overrideError.value = null;
  overrideSuccess.value = null;
}

// ============================================================
// Helpers
// ============================================================

function decisionClass(decision: string | null): string {
  const u = (decision ?? '').toUpperCase();
  if (u === 'PASS') return 'badge badge-pass';
  if (u === 'FAIL') return 'badge badge-critical';
  if (u === 'CONDITIONAL') return 'badge badge-medium';
  return 'badge badge-neutral';
}

function gateStatusClass(status: string): string {
  const u = status.toUpperCase();
  if (u === 'PASS') return 'badge badge-pass';
  if (u === 'FAIL') return 'badge badge-critical';
  if (u === 'WARNING') return 'badge badge-medium';
  return 'badge badge-neutral';
}

function fmtPct(n: number | null): string {
  if (n == null) return '—';
  return `${Math.round(n * 100)}%`;
}

// ============================================================
// Components
// ============================================================

export function ReleaseGatesPage() {
  useEffect(() => { void loadSummaries(); }, []);

  return (
    <div>
      <div class="page-header">
        <div>
          <div class="page-title">Release Gates</div>
          <div class="page-subtitle">
            Per-system gate rollup · expand for per-gate detail · CISO can create exceptions on failed blocking gates
          </div>
        </div>
        <div class="page-actions">
          <button class="btn btn-sm" onClick={() => void loadSummaries()}>Refresh</button>
        </div>
      </div>

      {loadError.value && (
        <div class="error-banner">Failed to load release gates: {loadError.value}</div>
      )}

      {loading.value && summaries.value.length === 0 && (
        <div class="loading" style={{ padding: '1.5rem' }}>Loading gate summaries…</div>
      )}

      {!loading.value && summaries.value.length === 0 && !loadError.value && (
        <div class="empty-state">No AI systems registered.</div>
      )}

      {summaries.value.map((s) => (
        <SystemGateRow key={s.ai_system_id} summary={s} />
      ))}

      <OverrideModal />
    </div>
  );
}

function SystemGateRow({ summary: s }: { summary: SystemGateSummary }) {
  const isExpanded = expandedId.value === s.ai_system_id;
  const detail = detailCache.value[s.ai_system_id] ?? null;

  if (s.error) {
    return (
      <div class="card" style={{ marginBottom: '0.75rem' }}>
        <div class="card-header">
          <div>
            <div class="card-title">{s.ai_system_name}</div>
            <div class="card-subtitle text-xs" style={{ color: 'var(--critical)' }}>
              Evaluation error: {s.error}
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div class="card" style={{ marginBottom: '0.75rem' }}>
      <div
        class="card-header"
        style={{ cursor: 'pointer' }}
        onClick={() => void toggleExpand(s.ai_system_id)}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flex: 1 }}>
          <span style={{ fontSize: '11px', color: 'var(--text-tertiary)', userSelect: 'none' }}>
            {isExpanded ? '▾' : '▸'}
          </span>
          <div>
            <div class="card-title">{s.ai_system_name}</div>
            <div class="card-subtitle text-xs">{s.domain ?? '—'} · {s.runtime_status ?? '—'}</div>
          </div>
        </div>
        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
          <span class={decisionClass(s.release_decision)}>{s.release_decision ?? '—'}</span>
          <span class="badge badge-neutral" title="Pass / Fail / Warning">
            {s.pass_count ?? 0}P · {s.fail_count ?? 0}F · {s.warning_count ?? 0}W
          </span>
          <span class="text-xs text-tertiary">Evidence: {fmtPct(s.evidence_completeness)}</span>
          {(s.blocking_failures ?? 0) > 0 && (
            <span class="badge badge-critical">{s.blocking_failures} blocking</span>
          )}
        </div>
      </div>

      {isExpanded && (
        <div style={{ borderTop: '1px solid var(--border)', padding: '1rem' }}>
          {detailLoading.value && <div class="loading">Loading gate detail…</div>}
          {detailError.value && (
            <div class="error-banner">Failed to load detail: {detailError.value}</div>
          )}
          {detail && <GateDetailPanel report={detail} />}
        </div>
      )}
    </div>
  );
}

function GateDetailPanel({ report }: { report: GateReport }) {
  return (
    <>
      <div class="text-xs text-tertiary" style={{ marginBottom: '0.75rem' }}>
        Target: {report.target_environment} · Generated: {report.generated_at.slice(0, 16).replace('T', ' ')}
        · Evidence: {fmtPct(report.evidence_completeness)}
      </div>
      <div class="text-xs" style={{ marginBottom: '0.75rem', color: 'var(--text-secondary)' }}>
        {report.release_rationale}
      </div>
      <table class="data-table">
        <thead>
          <tr>
            <th>Gate</th>
            <th>Status</th>
            <th>Blocking</th>
            <th>Reason</th>
            <th>Controls</th>
            <th>Exception</th>
            <th>Action</th>
          </tr>
        </thead>
        <tbody>
          {report.gates.map((g) => (
            <tr key={g.gate_id}>
              <td>
                <div class="cell-primary">{g.name}</div>
                <div class="cell-secondary mono" style={{ marginTop: 2, fontSize: '10px' }}>{g.gate_id}</div>
              </td>
              <td><span class={gateStatusClass(g.status)}>{g.status}</span></td>
              <td class="text-xs">{g.blocking ? 'Yes' : 'No'}</td>
              <td class="text-xs" style={{ maxWidth: '220px' }}>{g.failed_reason ?? '—'}</td>
              <td class="text-xs">{g.mapped_controls.join(', ') || '—'}</td>
              <td class="text-xs">{g.exception_id ? <span class="badge badge-pass">Waived</span> : '—'}</td>
              <td>
                {g.status === 'FAIL' && g.blocking && !g.exception_id ? (
                  <button
                    class="btn btn-sm"
                    style={{ borderColor: 'var(--critical)', color: 'var(--critical)' }}
                    onClick={() => {
                      overrideTarget.value = { systemId: report.ai_system_id, gate: g };
                      overrideReason.value = '';
                      overrideError.value = null;
                      overrideSuccess.value = null;
                    }}
                  >
                    Create Exception
                  </button>
                ) : (
                  <span class="text-xs text-tertiary">—</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

function OverrideModal() {
  const target = overrideTarget.value;
  if (!target) return null;

  return (
    <>
      <div
        class="drawer-overlay open"
        onClick={closeModal}
      />
      <div
        style={{
          position: 'fixed',
          top: '50%',
          left: '50%',
          transform: 'translate(-50%, -50%)',
          zIndex: 200,
          background: 'var(--bg-card)',
          border: '1px solid var(--border-strong)',
          borderRadius: '10px',
          padding: '1.5rem',
          minWidth: '480px',
          maxWidth: '560px',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
          <div class="card-title">Create Gate Exception</div>
          <button class="drawer-close" onClick={closeModal} style={{ border: 'none', background: 'none' }}>✕</button>
        </div>

        {overrideSuccess.value ? (
          <div>
            <div class="badge badge-pass" style={{ display: 'inline-block', marginBottom: '0.75rem' }}>Exception Created</div>
            <dl class="def-list">
              <dt>Exception ID</dt>
              <dd><span class="mono">{overrideSuccess.value.id}</span></dd>
              <dt>Status</dt>
              <dd>{overrideSuccess.value.status}</dd>
              <dt>Expires</dt>
              <dd>{overrideSuccess.value.expires_at}</dd>
            </dl>
            <button class="btn btn-sm" style={{ marginTop: '1rem' }} onClick={closeModal}>Close</button>
          </div>
        ) : (
          <div>
            <dl class="def-list" style={{ marginBottom: '1rem' }}>
              <dt>System</dt>
              <dd>{target.systemId}</dd>
              <dt>Gate</dt>
              <dd>{target.gate.name}</dd>
              <dt>Failed Reason</dt>
              <dd class="text-xs">{target.gate.failed_reason ?? '—'}</dd>
            </dl>

            <div style={{ marginBottom: '0.75rem' }}>
              <label style={{ display: 'block', fontSize: '11px', color: 'var(--text-secondary)', marginBottom: '0.375rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                Exception Reason <span style={{ color: 'var(--critical)' }}>*</span>
              </label>
              <textarea
                style={{
                  width: '100%',
                  minHeight: '80px',
                  background: 'var(--bg-input)',
                  color: 'var(--text-primary)',
                  border: '1px solid var(--border)',
                  borderRadius: '6px',
                  padding: '0.5rem 0.75rem',
                  fontFamily: 'inherit',
                  fontSize: '13px',
                  resize: 'vertical',
                }}
                value={overrideReason.value}
                onInput={(e) => { overrideReason.value = (e.target as HTMLTextAreaElement).value; }}
                placeholder="Describe the business justification and compensating controls…"
              />
            </div>

            <div class="text-xs text-tertiary" style={{ marginBottom: '0.75rem' }}>
              Accepted as: CISO — Chief Information Security Officer · Expires 1 year from today
            </div>

            {overrideError.value && (
              <div class="error-banner" style={{ marginBottom: '0.75rem' }}>{overrideError.value}</div>
            )}

            <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'flex-end' }}>
              <button class="btn btn-sm" onClick={closeModal}>Cancel</button>
              <button
                class="btn btn-sm btn-primary"
                disabled={overrideSubmitting.value}
                onClick={() => void submitOverride()}
              >
                {overrideSubmitting.value ? 'Submitting…' : 'Submit Exception'}
              </button>
            </div>
          </div>
        )}
      </div>
    </>
  );
}
