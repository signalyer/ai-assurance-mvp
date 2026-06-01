// Surface: Evidence Bundles (CSM-3)
// V1 ancestor: static/evidence.html
// Endpoints:
//   GET /api/grc/evidence/v2/sectioned?scope=ALL
//   GET /api/grc/evidence/v2/completeness?axis=ai_system
//   GET /api/grc/evidence/v2/sections
// CISO-specific: read-only audit view with expandable per-row detail +
//   verify-integrity button (disabled — no CISO verify endpoint in engine).

import { signal, computed } from '@preact/signals';
import { useEffect, useState } from 'preact/hooks';
import { apiGet } from '../../shared/api/client';
import { openAiSummary } from '../../shared/components/AiSummaryDrawer';
import type {
  SectionedResponse,
  SectionedSection,
  EvidenceRow,
  CompletenessResponse,
  CompletenessRow,
  CompletenessAxis,
} from './types';

// ============================================================
// Module-level signals
// ============================================================

const sections = signal<SectionedSection[]>([]);
const sectionsLoading = signal<boolean>(true);
const sectionsError = signal<string | null>(null);

const completeness = signal<CompletenessRow[]>([]);
const completenessLoading = signal<boolean>(true);
const completenessAxis = signal<CompletenessAxis>('ai_system');

const filterStatus = signal<string>('ALL');
const filterSystem = signal<string>('ALL');
const expandedId = signal<string | null>(null);

// ============================================================
// Derived
// ============================================================

const allRows = computed<EvidenceRow[]>(() =>
  sections.value.flatMap((s) => s.items),
);

const systemOptions = computed<string[]>(() => {
  const names = new Set(allRows.value.map((r) => r.ai_system_name));
  return ['ALL', ...Array.from(names).sort()];
});

const filteredRows = computed<EvidenceRow[]>(() => {
  let rows = allRows.value;
  if (filterSystem.value !== 'ALL') {
    rows = rows.filter((r) => r.ai_system_name === filterSystem.value);
  }
  if (filterStatus.value === 'IMMUTABLE') {
    rows = rows.filter((r) => r.immutable);
  } else if (filterStatus.value === 'MUTABLE') {
    rows = rows.filter((r) => !r.immutable);
  }
  return rows;
});

const kpis = computed(() => {
  const rows = allRows.value;
  return {
    total: rows.length,
    immutable: rows.filter((r) => r.immutable).length,
    withHash: rows.filter((r) => !!r.hash).length,
    systems: new Set(rows.map((r) => r.ai_system_id)).size,
  };
});

// ============================================================
// Data loaders
// ============================================================

async function loadSectioned(): Promise<void> {
  sectionsLoading.value = true;
  sectionsError.value = null;
  const r = await apiGet<SectionedResponse>('/grc/evidence/v2/sectioned', { scope: 'ALL' });
  if (r.ok) {
    sections.value = r.data.sections ?? [];
  } else {
    sectionsError.value = r.detail;
  }
  sectionsLoading.value = false;
}

async function loadCompleteness(axis: CompletenessAxis): Promise<void> {
  completenessLoading.value = true;
  const r = await apiGet<CompletenessResponse>('/grc/evidence/v2/completeness', { axis });
  if (r.ok) {
    completeness.value = r.data.rows ?? [];
  }
  completenessLoading.value = false;
}

async function loadAll(): Promise<void> {
  await Promise.all([loadSectioned(), loadCompleteness(completenessAxis.value)]);
}

async function onAxisChange(axis: CompletenessAxis): Promise<void> {
  completenessAxis.value = axis;
  await loadCompleteness(axis);
}

// ============================================================
// Helpers
// ============================================================

function fmtDate(s: string): string {
  return (s ?? '').slice(0, 10);
}

function pctBar(pct: number): string {
  if (pct >= 90) return 'badge badge-pass';
  if (pct >= 60) return 'badge badge-medium';
  return 'badge badge-critical';
}

// S73: roll the currently-filtered evidence rows into a compact "evidence
// type ×N" string the prompt can see. Same shape as
// team-portal/AiSystemDrawer.tsx::summarizeEvidenceSections.
function summarizeEvidenceSections(rows: EvidenceRow[]): string {
  if (rows.length === 0) return '';
  const byType: Record<string, number> = {};
  for (const r of rows) byType[r.evidence_type] = (byType[r.evidence_type] ?? 0) + 1;
  return Object.entries(byType)
    .map(([k, v]) => (v > 1 ? `${k} ×${v}` : k))
    .join(', ');
}

// S73: Summarize-evidence button binds to the currently-filtered view. When
// filterSystem is "ALL" the prompt sees portfolio-wide evidence; when scoped
// to a system, it sees per-system. ai_system_id is nullable in AskRequest —
// portfolio-wide passes null; per-system finds one row's id.
function openSummarizeFilteredEvidence(): void {
  const rows = filteredRows.value;
  if (rows.length === 0) return;
  const scope = filterSystem.value;
  const sysId = scope === 'ALL' ? null : (rows[0]?.ai_system_id ?? null);
  const scopeLabel = scope === 'ALL' ? 'portfolio-wide' : scope;
  openAiSummary({
    url: '/assurance-model/summarize-evidence',
    title: `Evidence summary · ${scopeLabel}`,
    body: {
      ai_system_id: sysId,
      data_classes: [],
      payload: {
        evidence_sections: summarizeEvidenceSections(rows) || '(no evidence on file)',
        evidence_completeness: `${rows.length} records on file · scope=${scopeLabel}`,
      },
      preferred_provider: 'anthropic-prod',
      user: 'ciso-console',
    },
  });
}

// ============================================================
// Component
// ============================================================

export function EvidencePage() {
  useEffect(() => { void loadAll(); }, []);

  return (
    <div>
      <div class="page-header">
        <div>
          <div class="page-title">Evidence Bundles</div>
          <div class="page-subtitle">
            Audit-ready evidence repository · tamper-evident digests · cross-framework coverage
          </div>
        </div>
        <div class="page-actions">
          <button class="btn btn-sm" onClick={() => void loadAll()}>Refresh</button>
        </div>
      </div>

      <KpiRow />
      <CompletenessCard />
      <EvidenceCard />
    </div>
  );
}

function KpiRow() {
  const k = kpis.value;
  return (
    <div class="kpi-row">
      <Kpi label="Total Evidence" value={k.total} />
      <Kpi label="Immutable Records" value={k.immutable} tone="pass" />
      <Kpi label="With SHA Digest" value={k.withHash} tone="info" />
      <Kpi label="AI Systems" value={k.systems} />
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

const AXES: { value: CompletenessAxis; label: string }[] = [
  { value: 'ai_system',      label: 'By AI System' },
  { value: 'framework',      label: 'By Framework' },
  { value: 'control_domain', label: 'By Control Domain' },
  { value: 'release_gate',   label: 'By Release Gate' },
];

function CompletenessCard() {
  const rows = completeness.value;
  const axis = completenessAxis.value;

  return (
    <div class="card mb-4">
      <div class="card-header">
        <div>
          <div class="card-title">Coverage Completeness</div>
          <div class="card-subtitle">Evidence coverage by axis — % of required types present</div>
        </div>
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          {AXES.map((a) => (
            <button
              key={a.value}
              class={`btn btn-sm ${axis === a.value ? 'btn-primary' : ''}`}
              onClick={() => void onAxisChange(a.value)}
            >
              {a.label}
            </button>
          ))}
        </div>
      </div>
      {completenessLoading.value ? (
        <div class="loading" style={{ padding: '1.5rem' }}>Loading completeness…</div>
      ) : rows.length === 0 ? (
        <div class="empty-state">No completeness data.</div>
      ) : (
        <table class="data-table">
          <thead>
            <tr>
              <th>Label</th>
              <th>Present</th>
              <th>Required</th>
              <th>Coverage %</th>
              <th>Missing Types</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.label}>
                <td>{row.label}</td>
                <td>{row.present}</td>
                <td>{row.required}</td>
                <td><span class={pctBar(row.pct)}>{row.pct.toFixed(1)}%</span></td>
                <td class="text-xs text-secondary">
                  {row.missing.length === 0
                    ? <span class="badge badge-pass">Complete</span>
                    : row.missing.join(', ')}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function EvidenceCard() {
  return (
    <div class="card">
      <div class="card-header">
        <div>
          <div class="card-title">Evidence Records</div>
          <div class="card-subtitle">
            {filteredRows.value.length} record{filteredRows.value.length !== 1 ? 's' : ''}
            {filterSystem.value !== 'ALL' ? ` · ${filterSystem.value}` : ' · all systems'}
          </div>
        </div>
        <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
          <select
            class="form-input"
            style={{ fontSize: 12, padding: '0.25rem 0.5rem', height: 'auto' }}
            value={filterSystem.value}
            onChange={(e) => { filterSystem.value = (e.currentTarget as HTMLSelectElement).value; }}
          >
            {systemOptions.value.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <select
            class="form-input"
            style={{ fontSize: 12, padding: '0.25rem 0.5rem', height: 'auto' }}
            value={filterStatus.value}
            onChange={(e) => { filterStatus.value = (e.currentTarget as HTMLSelectElement).value; }}
          >
            <option value="ALL">All</option>
            <option value="IMMUTABLE">Immutable only</option>
            <option value="MUTABLE">Mutable only</option>
          </select>
          <button
            class="btn btn-sm btn-secondary"
            onClick={() => openSummarizeFilteredEvidence()}
            disabled={filteredRows.value.length === 0}
            title="AI summary of the currently filtered evidence view"
          >
            Summarize this view
          </button>
        </div>
      </div>

      {sectionsLoading.value ? (
        <div class="loading" style={{ padding: '1.5rem' }}>Loading evidence…</div>
      ) : sectionsError.value ? (
        <div class="error-banner" style={{ margin: '1rem' }}>Failed: {sectionsError.value}</div>
      ) : filteredRows.value.length === 0 ? (
        <div class="empty-state">No evidence records match the current filter.</div>
      ) : (
        <EvidenceTable rows={filteredRows.value} />
      )}
    </div>
  );
}

function EvidenceTable({ rows }: { rows: EvidenceRow[] }) {
  return (
    <table class="data-table">
      <thead>
        <tr>
          <th />
          <th>Type</th>
          <th>AI System</th>
          <th>Section</th>
          <th>Source</th>
          <th>Collected</th>
          <th>Immutable</th>
          <th>SHA Digest</th>
          <th>Action</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <EvidenceRow key={row.id} row={row} />
        ))}
      </tbody>
    </table>
  );
}

function EvidenceRow({ row }: { row: EvidenceRow }) {
  const isExpanded = expandedId.value === row.id;

  function toggle() {
    expandedId.value = isExpanded ? null : row.id;
  }

  return (
    <>
      <tr class={isExpanded ? 'row-expanded' : ''} style={{ cursor: 'pointer' }} onClick={toggle}>
        <td style={{ width: 20, textAlign: 'center', color: 'var(--text-secondary)', userSelect: 'none' }}>
          {isExpanded ? '▼' : '▶'}
        </td>
        <td>
          <span class="badge badge-neutral" style={{ fontSize: 10 }}>{row.evidence_type_pretty}</span>
        </td>
        <td class="text-xs">{row.ai_system_name}</td>
        <td class="text-xs text-secondary">{row.section_name}</td>
        <td class="text-xs">{row.source}</td>
        <td class="text-xs text-tertiary">{fmtDate(row.collected_at)}</td>
        <td>
          {row.immutable
            ? <span class="badge badge-pass">Yes</span>
            : <span class="badge badge-neutral">No</span>}
        </td>
        <td>
          {row.hash
            ? <span class="mono" style={{ fontSize: 10 }} title={row.hash}>{row.hash.slice(0, 12)}…</span>
            : <span class="text-tertiary">—</span>}
        </td>
        <td>
          <button
            class="btn btn-sm"
            style={{ fontSize: 10 }}
            title="No CISO verify endpoint — engine only"
            disabled
          >
            Verify
          </button>
        </td>
      </tr>
      {isExpanded && (
        <tr>
          <td colSpan={9} style={{ background: 'var(--bg-card-hover)', padding: '1rem 1.5rem' }}>
            <EvidenceDetail row={row} />
          </td>
        </tr>
      )}
    </>
  );
}

function EvidenceDetail({ row }: { row: EvidenceRow }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem', fontSize: 12 }}>
      <div>
        <div class="text-xs text-secondary" style={{ marginBottom: 4 }}>Summary</div>
        <div>{row.summary}</div>
        {row.uri && (
          <div style={{ marginTop: 8 }}>
            <span class="text-secondary">URI: </span>
            <span class="mono" style={{ fontSize: 11 }}>{row.uri}</span>
          </div>
        )}
        {row.hash && (
          <div style={{ marginTop: 8 }}>
            <span class="text-secondary">Full SHA-256: </span>
            <span class="mono" style={{ fontSize: 11 }}>{row.hash}</span>
          </div>
        )}
      </div>
      <div>
        <div class="text-xs text-secondary" style={{ marginBottom: 4 }}>Linked Controls</div>
        <div>
          {row.linked_control_ids.length === 0
            ? <span class="text-tertiary">—</span>
            : row.linked_control_ids.map((c) => (
                <span key={c} class="badge badge-neutral" style={{ marginRight: 4, fontSize: 10 }}>{c}</span>
              ))}
        </div>
        <div class="text-xs text-secondary" style={{ marginTop: 8, marginBottom: 4 }}>Linked Frameworks</div>
        <div>
          {row.linked_frameworks.length === 0
            ? <span class="text-tertiary">—</span>
            : row.linked_frameworks.map((f) => (
                <span key={f} class="badge badge-info" style={{ marginRight: 4, fontSize: 10 }}>{f}</span>
              ))}
        </div>
        <div class="text-xs text-secondary" style={{ marginTop: 8, marginBottom: 4 }}>Evidence ID</div>
        <span class="mono" style={{ fontSize: 11 }}>{row.id}</span>
      </div>
    </div>
  );
}
