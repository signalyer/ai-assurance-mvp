// Surface: Reports (CSM-4)
// V1 ancestor: static/reports.html
// Endpoints:
//   GET /api/reports/catalog           — report type catalog
//   GET /api/reports/systems           — AI system selector
//   GET /api/reports/{type}            — JSON data view
//   GET /api/reports/{type}/export.pdf — print-ready HTML (open in new tab)
//   GET /api/reports/{type}/export.json / export.csv — file downloads
// CISO posture: generate + download enabled per report type.
// PDF export opens a new tab (print-ready HTML — no native PDF lib in engine).
// JSON/CSV downloads use raw fetch + Blob trick (binary blob pattern, CSM-2 Frameworks).

import { signal } from '@preact/signals';
import { useEffect, useState } from 'preact/hooks';
import { apiGet } from '../../shared/api/client';
import type {
  ReportCatalogItem,
  ReportCatalogResponse,
  ReportSystemItem,
  ReportSystemsResponse,
  ReportStatus,
} from './types';

// ============================================================
// Module-level signals
// ============================================================

const catalog = signal<ReportCatalogItem[]>([]);
const systems = signal<ReportSystemItem[]>([]);
const catalogLoading = signal<boolean>(true);
const catalogError = signal<string | null>(null);

// Per-report status map keyed by report type
const statusMap = signal<Record<string, ReportStatus>>({});

// Selected system per report type (for requires_system reports)
const systemSelections = signal<Record<string, string>>({});

// ============================================================
// Loaders
// ============================================================

async function loadCatalog(): Promise<void> {
  catalogLoading.value = true;
  catalogError.value = null;
  const [catResult, sysResult] = await Promise.all([
    apiGet<ReportCatalogResponse>('/reports/catalog'),
    apiGet<ReportSystemsResponse>('/reports/systems'),
  ]);
  if (catResult.ok) {
    catalog.value = catResult.data.reports;
    // Initialise status map
    const map: Record<string, ReportStatus> = {};
    for (const r of catResult.data.reports) {
      map[r.type] = { type: r.type, state: 'idle', lastGeneratedAt: null, error: null };
    }
    statusMap.value = map;
  } else {
    catalogError.value = catResult.detail;
  }
  if (sysResult.ok) {
    systems.value = sysResult.data.systems;
  }
  catalogLoading.value = false;
}

// ============================================================
// Actions
// ============================================================

const BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? '/api/v1').replace(/\/+$/, '');

function reportUrl(reportType: string, systemId: string | null, suffix: string): string {
  const base = `${BASE_URL}/reports/${reportType}${suffix}`;
  return systemId ? `${base}${suffix.includes('?') ? '&' : '?'}system_id=${encodeURIComponent(systemId)}` : base;
}

async function triggerDownload(url: string, filename: string): Promise<void> {
  // credentials: 'include' — engine + SPA live on different subdomains; per
  // [[raw-fetch-drifts-from-shared-client]] same-origin silently drops the
  // session cookie cross-origin and 401s in prod. Shared apiClient uses
  // 'include' everywhere; this raw fetch must match.
  const resp = await fetch(url, { credentials: 'include' });
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  const blob = await resp.blob();
  const objectUrl = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = objectUrl;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(objectUrl);
}

function setStatus(type: string, patch: Partial<ReportStatus>): void {
  const current = statusMap.value[type] ?? { type, state: 'idle' as const, lastGeneratedAt: null, error: null };
  const next: ReportStatus = { ...current, ...patch };
  statusMap.value = { ...statusMap.value, [type]: next };
}

async function handleGenerate(item: ReportCatalogItem): Promise<void> {
  const systemId = item.requires_system ? (systemSelections.value[item.type] ?? null) : null;
  if (item.requires_system && !systemId) return; // button is disabled — guard anyway
  setStatus(item.type, { state: 'generating', error: null });
  try {
    // Verify the report endpoint is reachable (JSON data path)
    const r = await apiGet<unknown>('/reports/' + item.type, systemId ? { system_id: systemId } : undefined);
    if (!r.ok) throw new Error(r.detail);
    setStatus(item.type, {
      state: 'done',
      lastGeneratedAt: new Date().toISOString(),
      error: null,
    });
  } catch (err) {
    setStatus(item.type, {
      state: 'error',
      error: err instanceof Error ? err.message : 'Unknown error',
    });
  }
}

async function handleDownloadPdf(item: ReportCatalogItem): Promise<void> {
  const systemId = item.requires_system ? (systemSelections.value[item.type] ?? null) : null;
  // PDF endpoint returns print-ready HTML — open in new tab so user can Ctrl+P
  const url = reportUrl(item.type, systemId, '/export.pdf');
  window.open(url, '_blank', 'noopener,noreferrer');
}

async function handleDownloadJson(item: ReportCatalogItem): Promise<void> {
  const systemId = item.requires_system ? (systemSelections.value[item.type] ?? null) : null;
  const url = reportUrl(item.type, systemId, '/export.json');
  const stamp = new Date().toISOString().slice(0, 16).replace('T', '_').replace(':', '');
  const fname = `report_${item.type}${systemId ? '_' + systemId : ''}_${stamp}.json`;
  try {
    await triggerDownload(url, fname);
  } catch (err) {
    setStatus(item.type, {
      state: 'error',
      error: err instanceof Error ? err.message : 'Download failed',
    });
  }
}

async function handleDownloadCsv(item: ReportCatalogItem): Promise<void> {
  const systemId = item.requires_system ? (systemSelections.value[item.type] ?? null) : null;
  const url = reportUrl(item.type, systemId, '/export.csv');
  const stamp = new Date().toISOString().slice(0, 16).replace('T', '_').replace(':', '');
  const fname = `report_${item.type}${systemId ? '_' + systemId : ''}_${stamp}.csv`;
  try {
    await triggerDownload(url, fname);
  } catch (err) {
    setStatus(item.type, {
      state: 'error',
      error: err instanceof Error ? err.message : 'Download failed',
    });
  }
}

// ============================================================
// Helpers
// ============================================================

function stateBadge(state: ReportStatus['state']): string {
  switch (state) {
    case 'generating': return 'badge badge-info';
    case 'done':       return 'badge badge-pass';
    case 'error':      return 'badge badge-critical';
    default:           return 'badge';
  }
}

function stateLabel(state: ReportStatus['state']): string {
  switch (state) {
    case 'generating': return 'Generating…';
    case 'done':       return 'Ready';
    case 'error':      return 'Error';
    default:           return 'Not generated';
  }
}

function fmtTs(iso: string | null): string {
  if (!iso) return '—';
  return new Date(iso).toLocaleString();
}

// ============================================================
// Sub-components
// ============================================================

function SystemSelector({ reportType, required }: { reportType: string; required: boolean }) {
  if (!required) return null;
  const value = systemSelections.value[reportType] ?? '';
  return (
    <select
      class="input"
      style={{ fontSize: 12, padding: '0.25rem 0.5rem', marginBottom: '0.5rem', width: '100%' }}
      value={value}
      onChange={(e) => {
        systemSelections.value = {
          ...systemSelections.value,
          [reportType]: (e.target as HTMLSelectElement).value,
        };
      }}
    >
      <option value="">— select system —</option>
      {systems.value.map((s) => (
        <option key={s.id} value={s.id}>{s.name} ({s.domain})</option>
      ))}
    </select>
  );
}

function ReportCard({ item }: { item: ReportCatalogItem }) {
  const status = statusMap.value[item.type] ?? { state: 'idle' as const, lastGeneratedAt: null, error: null, type: item.type };
  const systemId = systemSelections.value[item.type] ?? '';
  const canAct = !item.requires_system || systemId !== '';
  const busy = status.state === 'generating';

  return (
    <div class="card" style={{ display: 'flex', flexDirection: 'column' }}>
      <div class="card-header" style={{ flexShrink: 0 }}>
        <div>
          <div class="card-title">{item.title}</div>
          <div class="card-subtitle">{item.scope} · {item.audience.join(', ')}</div>
        </div>
        <span class={stateBadge(status.state)}>{stateLabel(status.state)}</span>
      </div>

      <div style={{ padding: '0.75rem', flex: 1, display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
        <div style={{ fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.5 }}>
          {item.description}
        </div>

        {status.lastGeneratedAt && (
          <div style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>
            Last generated: {fmtTs(status.lastGeneratedAt)}
          </div>
        )}

        {status.error && (
          <div class="error-banner" style={{ fontSize: 11, padding: '0.4rem 0.6rem' }}>
            {status.error}
          </div>
        )}

        <SystemSelector reportType={item.type} required={item.requires_system} />

        <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', marginTop: 'auto' }}>
          <button
            class="btn btn-sm btn-primary"
            disabled={!canAct || busy}
            onClick={() => void handleGenerate(item)}
          >
            {busy ? 'Generating…' : 'Generate'}
          </button>
          <button
            class="btn btn-sm"
            disabled={!canAct || status.state !== 'done'}
            onClick={() => void handleDownloadPdf(item)}
            title="Opens print-ready HTML in new tab — use Ctrl+P to save as PDF"
          >
            PDF
          </button>
          <button
            class="btn btn-sm"
            disabled={!canAct || status.state !== 'done'}
            onClick={() => void handleDownloadJson(item)}
          >
            JSON
          </button>
          <button
            class="btn btn-sm"
            disabled={!canAct || status.state !== 'done'}
            onClick={() => void handleDownloadCsv(item)}
          >
            CSV
          </button>
        </div>
      </div>
    </div>
  );
}

// ============================================================
// Page
// ============================================================

export function ReportsPage() {
  useEffect(() => { void loadCatalog(); }, []);

  const items = catalog.value;

  return (
    <div>
      <div class="page-header">
        <div>
          <div class="page-title">Reports</div>
          <div class="page-subtitle">
            Generate and download AI governance reports · 6 report types
          </div>
        </div>
        <div class="page-actions">
          <button class="btn btn-sm" onClick={() => void loadCatalog()}>Refresh</button>
        </div>
      </div>

      {catalogLoading.value ? (
        <div class="loading" style={{ padding: '2rem' }}>Loading report catalog…</div>
      ) : catalogError.value ? (
        <div class="error-banner" style={{ margin: '1rem' }}>Failed: {catalogError.value}</div>
      ) : items.length === 0 ? (
        <div class="empty-state">No reports available.</div>
      ) : (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))',
            gap: '1rem',
          }}
        >
          {items.map((item) => (
            <ReportCard key={item.type} item={item} />
          ))}
        </div>
      )}
    </div>
  );
}
