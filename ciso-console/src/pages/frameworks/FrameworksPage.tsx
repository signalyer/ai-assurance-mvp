// Surface: Framework Coverage Matrix (CSM-2)
// V1 ancestor: static/frameworks.html
// Endpoints:
//   GET /api/frameworks/matrix  — portfolio-wide coverage grid
//   GET /api/frameworks/{slug}/system/{id}  — drill-down detail
//   POST /api/frameworks/{slug}/export  — PDF download (triggers browser download)
// CISO-specific: PDF export button per framework column; click cell opens drill modal.

import { signal } from '@preact/signals';
import { useEffect } from 'preact/hooks';
import { apiGet, apiPost } from '../../shared/api/client';
import type {
  MatrixResponse,
  MatrixRow,
  FrameworkMeta,
  DrillDownResponse,
} from './types';

// ============================================================
// Module-level signals
// ============================================================

const matrix = signal<MatrixResponse | null>(null);
const loading = signal<boolean>(true);
const loadError = signal<string | null>(null);

// Drill modal
const drillTarget = signal<{ slug: string; systemId: string; systemName: string; frameworkName: string } | null>(null);
const drillData = signal<DrillDownResponse | null>(null);
const drillLoading = signal<boolean>(false);
const drillError = signal<string | null>(null);

// Export state
const exportingSlug = signal<string | null>(null);
const exportError = signal<string | null>(null);

// ============================================================
// Data load
// ============================================================

async function loadMatrix(): Promise<void> {
  loading.value = true;
  loadError.value = null;
  const r = await apiGet<MatrixResponse>('/frameworks/matrix');
  if (r.ok) {
    matrix.value = r.data;
  } else {
    loadError.value = r.detail;
  }
  loading.value = false;
}

async function openDrill(slug: string, systemId: string, systemName: string, frameworkName: string): Promise<void> {
  drillTarget.value = { slug, systemId, systemName, frameworkName };
  drillData.value = null;
  drillError.value = null;
  drillLoading.value = true;
  const r = await apiGet<DrillDownResponse>(
    `/frameworks/${encodeURIComponent(slug)}/system/${encodeURIComponent(systemId)}`,
  );
  if (r.ok) {
    drillData.value = r.data;
  } else {
    drillError.value = r.detail;
  }
  drillLoading.value = false;
}

async function exportPdf(slug: string, displayName: string): Promise<void> {
  exportingSlug.value = slug;
  exportError.value = null;
  // POST returns a PDF blob — fetch directly (not via apiPost which parses JSON)
  try {
    const base = (import.meta.env.VITE_API_BASE_URL ?? '/api/v1').replace(/\/+$/, '');
    const resp = await fetch(
      `${base}/frameworks/${encodeURIComponent(slug)}/export`,
      {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', Accept: 'application/pdf,application/json' },
        body: JSON.stringify({ system_id: '' }),
      },
    );
    if (!resp.ok) {
      exportError.value = `Export failed: HTTP ${resp.status}`;
    } else {
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${displayName.replace(/\s+/g, '_')}_coverage.pdf`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    }
  } catch (err) {
    exportError.value = err instanceof Error ? err.message : 'Network error';
  }
  exportingSlug.value = null;
}

function closeDrill(): void {
  drillTarget.value = null;
  drillData.value = null;
  drillError.value = null;
}

// ============================================================
// Helpers
// ============================================================

// Engine returns coverage_pct on a 0-100 scale (domain/framework_coverage.py:410).
// Matches Team Portal's AiSystemFrameworksPanel contract.
function coverageStyle(pct: number): { background: string; color: string } {
  if (pct >= 80) return { background: 'rgba(16,185,129,0.2)', color: '#10b981' };
  if (pct >= 50) return { background: 'rgba(245,158,11,0.2)', color: '#f59e0b' };
  if (pct > 0) return { background: 'rgba(239,68,68,0.15)', color: '#ef4444' };
  return { background: 'rgba(30,40,60,0.5)', color: 'var(--text-tertiary)' };
}

function fmtPct(n: number | undefined): string {
  if (n == null) return '—';
  return `${Math.round(n)}%`;
}

// ============================================================
// Components
// ============================================================

export function FrameworksPage() {
  useEffect(() => { void loadMatrix(); }, []);

  const m = matrix.value;

  return (
    <div>
      <div class="page-header">
        <div>
          <div class="page-title">Framework Coverage Matrix</div>
          <div class="page-subtitle">
            Portfolio × framework coverage grid · click any cell to drill into per-item detail · export PDF per framework
          </div>
        </div>
        <div class="page-actions">
          <button class="btn btn-sm" onClick={() => void loadMatrix()}>Refresh</button>
        </div>
      </div>

      {loadError.value && (
        <div class="error-banner">Failed to load matrix: {loadError.value}</div>
      )}

      {exportError.value && (
        <div class="error-banner">Export error: {exportError.value}</div>
      )}

      {loading.value && !m && (
        <div class="loading" style={{ padding: '1.5rem' }}>Loading coverage matrix…</div>
      )}

      {m && (
        <>
          {/* Export buttons row */}
          <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem', flexWrap: 'wrap' }}>
            {m.frameworks.map((fw) => (
              <button
                key={fw.slug}
                class="btn btn-sm"
                disabled={exportingSlug.value === fw.slug}
                onClick={() => void exportPdf(fw.slug, fw.display_name)}
                title={`Export ${fw.display_name} coverage as PDF`}
              >
                {exportingSlug.value === fw.slug ? 'Exporting…' : `Export ${fw.display_name}`}
              </button>
            ))}
          </div>

          <MatrixGrid rows={m.rows} frameworks={m.frameworks} />
        </>
      )}

      {m && m.rows.length === 0 && (
        <div class="empty-state">No AI systems registered.</div>
      )}

      <DrillModal />
    </div>
  );
}

function MatrixGrid({ rows, frameworks }: { rows: MatrixRow[]; frameworks: FrameworkMeta[] }) {
  return (
    <div class="card" style={{ overflowX: 'auto' }}>
      <table class="data-table" style={{ tableLayout: 'auto', minWidth: `${200 + frameworks.length * 120}px` }}>
        <thead>
          <tr>
            <th style={{ minWidth: '180px' }}>AI System</th>
            {frameworks.map((fw) => (
              <th key={fw.slug} style={{ minWidth: '110px', textAlign: 'center' }}>
                {fw.display_name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.system_id}>
              <td>
                <div class="cell-primary">{row.system_name}</div>
                <div class="cell-secondary mono" style={{ marginTop: 2, fontSize: '10px' }}>{row.system_id}</div>
              </td>
              {frameworks.map((fw) => {
                const pct = row.cells[fw.slug];
                const style = coverageStyle(pct ?? 0);
                return (
                  <td
                    key={fw.slug}
                    style={{ textAlign: 'center', cursor: 'pointer', padding: '0.5rem' }}
                    title={`${row.system_name} × ${fw.display_name}: ${fmtPct(pct)} — click to drill`}
                    onClick={() => void openDrill(fw.slug, row.system_id, row.system_name, fw.display_name)}
                  >
                    <span
                      style={{
                        display: 'inline-block',
                        padding: '0.25rem 0.5rem',
                        borderRadius: '4px',
                        fontSize: '12px',
                        fontWeight: 600,
                        ...style,
                      }}
                    >
                      {fmtPct(pct)}
                    </span>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DrillModal() {
  const target = drillTarget.value;
  if (!target) return null;

  return (
    <>
      <div class="drawer-overlay open" onClick={closeDrill} />
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
          minWidth: '540px',
          maxWidth: '680px',
          maxHeight: '80vh',
          overflowY: 'auto',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
          <div>
            <div class="card-title">{target.frameworkName}</div>
            <div class="card-subtitle text-xs">{target.systemName}</div>
          </div>
          <button
            onClick={closeDrill}
            style={{ border: 'none', background: 'none', cursor: 'pointer', color: 'var(--text-secondary)', fontSize: '16px' }}
          >
            ✕
          </button>
        </div>

        {drillLoading.value && <div class="loading">Loading detail…</div>}

        {drillError.value && (
          <div class="error-banner">Failed to load detail: {drillError.value}</div>
        )}

        {drillData.value && <DrillContent data={drillData.value} />}
      </div>
    </>
  );
}

function DrillContent({ data }: { data: DrillDownResponse }) {
  return (
    <div>
      {data.items.map((item) => (
        <div
          key={item.id}
          style={{ marginBottom: '1rem', padding: '0.75rem', border: '1px solid var(--border)', borderRadius: '6px' }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
            <div class="cell-primary">{item.display_name}</div>
            <span
              style={{
                ...coverageStyle(item.coverage_pct),
                display: 'inline-block',
                padding: '0.2rem 0.5rem',
                borderRadius: '4px',
                fontSize: '11px',
                fontWeight: 600,
              }}
            >
              {fmtPct(item.coverage_pct)}
            </span>
          </div>

          {item.controls.length > 0 && (
            <div style={{ marginBottom: '0.5rem' }}>
              <div class="text-xs text-tertiary" style={{ marginBottom: '0.25rem' }}>Controls</div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.25rem' }}>
                {item.controls.map((c) => (
                  <span key={c.control_id} class="badge badge-neutral" title={c.title}>{c.control_id}</span>
                ))}
              </div>
            </div>
          )}

          {item.findings.length > 0 && (
            <div style={{ marginBottom: '0.5rem' }}>
              <div class="text-xs text-tertiary" style={{ marginBottom: '0.25rem' }}>
                Findings ({item.findings.length})
              </div>
              {item.findings.slice(0, 3).map((f) => (
                <div key={f.id} class="text-xs" style={{ marginBottom: '0.2rem' }}>
                  <span
                    style={{
                      marginRight: '0.375rem',
                      color: (f.severity ?? '').toUpperCase() === 'CRITICAL' ? 'var(--critical)' : 'var(--text-secondary)',
                    }}
                  >
                    {f.severity}
                  </span>
                  {f.title}
                </div>
              ))}
              {item.findings.length > 3 && (
                <div class="text-xs text-tertiary">+{item.findings.length - 3} more findings</div>
              )}
            </div>
          )}

          {item.evidence.length > 0 && (
            <div class="text-xs text-tertiary">
              {item.evidence.length} evidence item{item.evidence.length !== 1 ? 's' : ''} collected
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
