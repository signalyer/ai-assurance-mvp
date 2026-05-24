// Frameworks coverage panel for one AI system. Opens via openFrameworks(id),
// mirrors AiSystemRevisionsPanel pattern. Two-stage load:
//   1. GET /frameworks/matrix       — list of frameworks + per-system coverage %
//   2. GET /frameworks/{slug}/system/{id}  on framework card click — per-item drill
// Both calls go through /api/v1/* alias.

import { signal } from '@preact/signals';
import { useEffect } from 'preact/hooks';
import { apiGet } from '../../shared/api/client';

interface FrameworkDef { slug: string; display_name: string; }
interface MatrixRow { system_id: string; system_name: string; cells: Record<string, number>; }
interface MatrixResponse { frameworks: FrameworkDef[]; rows: MatrixRow[]; }

interface ControlRollup {
  control_id: string;
  title: string;
  priority: string;
  domain: string;
  status: string;
  open_findings: number;
}
interface FindingSummary {
  id: string;
  system_id: string;
  title: string;
  severity: string;
  status: string;
  control_id: string | null;
}
interface EvidenceItem {
  id: string;
  summary: string;
  evidence_hash: string;
  collected_at: string;
  source: string;
  evidence_type: string;
}
interface DrillItem {
  id: string;
  display_name: string;
  coverage_pct: number;
  controls: ControlRollup[];
  findings: FindingSummary[];
  evidence: EvidenceItem[];
}
interface DrillResponse {
  framework: string;
  display_name: string;
  system_id: string;
  items: DrillItem[];
}

const openSystemId = signal<string | null>(null);
const frameworks = signal<FrameworkDef[]>([]);
const systemCells = signal<Record<string, number>>({});
const matrixError = signal<string | null>(null);
const matrixLoading = signal<boolean>(false);

const drillSlug = signal<string | null>(null);
const drillData = signal<DrillResponse | null>(null);
const drillError = signal<string | null>(null);
const drillLoading = signal<boolean>(false);

export function openFrameworks(id: string): void {
  openSystemId.value = id;
  drillSlug.value = null;
  drillData.value = null;
  drillError.value = null;
}

function closeFrameworks(): void {
  openSystemId.value = null;
  frameworks.value = [];
  systemCells.value = {};
  matrixError.value = null;
  drillSlug.value = null;
  drillData.value = null;
}

async function loadMatrix(systemId: string): Promise<void> {
  matrixLoading.value = true;
  matrixError.value = null;
  frameworks.value = [];
  systemCells.value = {};
  const r = await apiGet<MatrixResponse>('/frameworks/matrix');
  if (r.ok) {
    frameworks.value = r.data.frameworks;
    const row = r.data.rows.find((x) => x.system_id === systemId);
    systemCells.value = row?.cells ?? {};
  } else {
    matrixError.value = r.detail;
  }
  matrixLoading.value = false;
}

async function loadDrill(systemId: string, slug: string): Promise<void> {
  drillSlug.value = slug;
  drillLoading.value = true;
  drillError.value = null;
  drillData.value = null;
  const r = await apiGet<DrillResponse>(
    `/frameworks/${encodeURIComponent(slug)}/system/${encodeURIComponent(systemId)}`,
  );
  if (r.ok) {
    drillData.value = r.data;
  } else {
    drillError.value = r.detail;
  }
  drillLoading.value = false;
}

// Engine returns coverage_pct on a 0-100 scale (domain/framework_coverage.py).
function coverageColor(pct: number): string {
  if (pct >= 85) return 'var(--pass, #22c55e)';
  if (pct >= 60) return 'var(--medium, #f59e0b)';
  return 'var(--critical, #ef4444)';
}

function pctLabel(pct: number): string {
  return `${pct.toFixed(1)}%`;
}

function pctWidth(pct: number): string {
  return `${Math.max(0, Math.min(100, pct))}%`;
}

export function AiSystemFrameworksPanel() {
  const id = openSystemId.value;

  useEffect(() => {
    if (id) void loadMatrix(id);
  }, [id]);

  if (!id) return null;

  const fws = frameworks.value;
  const cells = systemCells.value;
  const slug = drillSlug.value;
  const drill = drillData.value;

  return (
    <>
      <div class="drawer-overlay open" onClick={closeFrameworks} />
      <aside class="drawer open" aria-hidden={false} style={{ width: 720 }}>
        <div class="drawer-header">
          <div class="drawer-title">Framework Coverage</div>
          <button class="drawer-close" onClick={closeFrameworks} aria-label="Close">×</button>
        </div>
        <div class="drawer-body">
          <div class="text-xs text-tertiary" style={{ marginBottom: 12 }}>
            System <span class="font-mono">{id}</span>
            {slug && (
              <>
                {' › '}
                <a
                  href="#"
                  onClick={(e) => {
                    e.preventDefault();
                    drillSlug.value = null;
                    drillData.value = null;
                  }}
                >
                  back to all frameworks
                </a>
              </>
            )}
          </div>

          {matrixLoading.value && <div class="loading">Loading frameworks…</div>}
          {matrixError.value && <div class="error-banner">Failed to load matrix: {matrixError.value}</div>}

          {/* Stage 1: framework cards */}
          {!slug && !matrixLoading.value && !matrixError.value && (
            <>
              {fws.length === 0 && <div class="empty-state">No frameworks configured.</div>}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                {fws.map((f) => {
                  const pct = cells[f.slug] ?? 0;
                  return (
                    <div
                      key={f.slug}
                      style={{
                        border: '1px solid var(--border)',
                        borderRadius: 4,
                        padding: '0.75rem',
                        cursor: 'pointer',
                      }}
                      onClick={() => void loadDrill(id, f.slug)}
                    >
                      <div class="text-sm" style={{ fontWeight: 600, marginBottom: 4 }}>
                        {f.display_name}
                      </div>
                      <div class="font-mono text-xs text-tertiary" style={{ marginBottom: 8 }}>
                        {f.slug}
                      </div>
                      <div
                        style={{
                          height: 6,
                          background: 'var(--border)',
                          borderRadius: 3,
                          overflow: 'hidden',
                          marginBottom: 4,
                        }}
                      >
                        <div
                          style={{
                            width: pctWidth(pct),
                            height: '100%',
                            background: coverageColor(pct),
                          }}
                        />
                      </div>
                      <div class="text-xs" style={{ color: coverageColor(pct) }}>
                        {pctLabel(pct)} coverage
                      </div>
                    </div>
                  );
                })}
              </div>
            </>
          )}

          {/* Stage 2: drill into one framework */}
          {slug && (
            <>
              {drillLoading.value && <div class="loading">Loading {slug}…</div>}
              {drillError.value && <div class="error-banner">Failed to load drill: {drillError.value}</div>}
              {drill && (
                <>
                  <div class="drawer-section-title">{drill.display_name}</div>
                  {drill.items.length === 0 && (
                    <div class="empty-state">No items in this framework.</div>
                  )}
                  {drill.items.map((it) => (
                    <div
                      key={it.id}
                      style={{
                        border: '1px solid var(--border)',
                        borderRadius: 4,
                        padding: '0.6rem 0.75rem',
                        marginBottom: 8,
                      }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
                        <div>
                          <div class="text-sm" style={{ fontWeight: 600 }}>{it.display_name}</div>
                          <div class="font-mono text-xs text-tertiary">{it.id}</div>
                        </div>
                        <div class="text-sm" style={{ color: coverageColor(it.coverage_pct) }}>
                          {pctLabel(it.coverage_pct)}
                        </div>
                      </div>
                      <div class="text-xs text-tertiary" style={{ marginTop: 6 }}>
                        {it.controls.length} control{it.controls.length === 1 ? '' : 's'}
                        {' · '}
                        {it.findings.length} finding{it.findings.length === 1 ? '' : 's'}
                        {' · '}
                        {it.evidence.length} evidence
                      </div>
                    </div>
                  ))}
                </>
              )}
            </>
          )}
        </div>
      </aside>
    </>
  );
}
