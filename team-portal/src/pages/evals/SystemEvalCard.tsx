import { signal } from '@preact/signals';
import { useEffect } from 'preact/hooks';
import { apiGet, apiPost } from '../../shared/api/client';
import type {
  EvalsSystemOverview,
  EvalRecord,
  SystemDetailResponse,
  SimulatedRunResponse,
  EvalSuiteCatalog,
  EvalSuiteEntry,
} from './types';
import { reloadEvalsOverview } from './EvalsPage';

// Module-level signal state — two levels of expansion.
const expandedSystems = signal<Set<string>>(new Set());
const openEvals = signal<Set<string>>(new Set());
const detailCache = signal<Map<string, EvalRecord[]>>(new Map());
const detailLoading = signal<Set<string>>(new Set());
const running = signal<Set<string>>(new Set());
const actionError = signal<string | null>(null);
const lastRun = signal<Map<string, SimulatedRunResponse>>(new Map());

// ADR-003 multi-vendor catalog — loaded once per page session, shared across
// all cards. selectedSuite is purely cosmetic for this slice: only the
// `enabled` vendor actually runs; roadmap vendors are non-clickable.
const suiteCatalog = signal<EvalSuiteCatalog | null>(null);
const suiteCatalogLoading = signal<boolean>(false);
const selectedSuite = signal<string>('');

async function loadSuiteCatalog(): Promise<void> {
  if (suiteCatalog.value || suiteCatalogLoading.value) return;
  suiteCatalogLoading.value = true;
  const r = await apiGet<EvalSuiteCatalog>('/evals/suites');
  if (r.ok) {
    suiteCatalog.value = r.data;
    if (!selectedSuite.value) selectedSuite.value = r.data.active_vendor;
  }
  suiteCatalogLoading.value = false;
}

function toggleSet(sig: typeof expandedSystems, key: string): void {
  const next = new Set(sig.value);
  if (next.has(key)) next.delete(key);
  else next.add(key);
  sig.value = next;
}

async function loadDetail(systemId: string): Promise<void> {
  if (detailCache.value.has(systemId) || detailLoading.value.has(systemId)) return;
  const loadingNext = new Set(detailLoading.value);
  loadingNext.add(systemId);
  detailLoading.value = loadingNext;
  const r = await apiGet<SystemDetailResponse>(`/grc/evals/v2/system/${encodeURIComponent(systemId)}`);
  if (r.ok) {
    const next = new Map(detailCache.value);
    next.set(systemId, r.data.evals ?? []);
    detailCache.value = next;
  }
  const doneNext = new Set(detailLoading.value);
  doneNext.delete(systemId);
  detailLoading.value = doneNext;
}

function toggleSystem(systemId: string): void {
  toggleSet(expandedSystems, systemId);
  if (expandedSystems.value.has(systemId)) void loadDetail(systemId);
}

async function runSimulatedSuite(systemId: string): Promise<void> {
  if (running.value.has(systemId)) return;
  actionError.value = null;
  const next = new Set(running.value);
  next.add(systemId);
  running.value = next;

  const r = await apiPost<SimulatedRunResponse>(
    `/grc/evals/v2/run/${encodeURIComponent(systemId)}`,
  );

  if (r.ok) {
    const lr = new Map(lastRun.value);
    lr.set(systemId, r.data);
    lastRun.value = lr;
    // Invalidate cached detail so the next expand re-fetches refreshed run_at.
    const dc = new Map(detailCache.value);
    dc.delete(systemId);
    detailCache.value = dc;
    if (expandedSystems.value.has(systemId)) void loadDetail(systemId);
    void reloadEvalsOverview();
  } else {
    actionError.value = `Run failed: ${r.detail}`;
  }

  const done = new Set(running.value);
  done.delete(systemId);
  running.value = done;
}

const pct = (x: number | null | undefined): number => Math.round((x ?? 0) * 100);

const STATUS_BADGE: Record<string, string> = {
  PASS: 'badge-pass',
  WARN: 'badge-medium',
  FAIL: 'badge-critical',
};

interface EvalGroupDefinition {
  id: string;
  title: string;
  description: string;
  evalTypes: string[];
}

interface EvalGroup {
  definition: EvalGroupDefinition;
  evals: EvalRecord[];
  passes: number;
  warns: number;
  fails: number;
  blocking: number;
}

const EVAL_GROUPS: EvalGroupDefinition[] = [
  {
    id: 'safety',
    title: 'Safety & Abuse',
    description: 'Injection, jailbreak, refusal, toxicity, and unsafe-output checks.',
    evalTypes: ['PROMPT_INJECTION', 'JAILBREAK', 'REFUSAL', 'TOXICITY'],
  },
  {
    id: 'data-protection',
    title: 'Data Protection',
    description: 'PII and sensitive-data leakage tests.',
    evalTypes: ['PII_LEAKAGE'],
  },
  {
    id: 'grounding-quality',
    title: 'Grounding & Quality',
    description: 'Answer relevance, hallucination, factuality, and retrieval grounding.',
    evalTypes: ['ANSWER_RELEVANCE', 'HALLUCINATION', 'FACTUALITY', 'GROUNDEDNESS', 'RAG_GROUNDING'],
  },
  {
    id: 'tool-runtime',
    title: 'Tool & Runtime Assurance',
    description: 'Tool authorization, audit completeness, human approval, runtime policy, latency, and cost.',
    evalTypes: ['TOOL_AUTHORIZATION', 'AUDIT_COMPLETENESS', 'HUMAN_APPROVAL', 'RUNTIME_POLICY', 'LATENCY', 'COST'],
  },
  {
    id: 'domain-regulatory',
    title: 'Domain & Regulatory',
    description: 'Business-domain obligations and specialized regulatory checks.',
    evalTypes: ['REGULATORY_KNOWLEDGE', 'SANCTIONS_SCREENING', 'BIAS', 'RAG_POISONING'],
  },
];

const FALLBACK_GROUP: EvalGroupDefinition = {
  id: 'other',
  title: 'Other Evals',
  description: 'Additional tests not yet mapped into a suite group.',
  evalTypes: [],
};

const evalGroupByType = new Map<string, EvalGroupDefinition>();
for (const group of EVAL_GROUPS) {
  for (const evalType of group.evalTypes) {
    evalGroupByType.set(evalType, group);
  }
}

function groupEvals(evals: EvalRecord[]): EvalGroup[] {
  const grouped = new Map<string, EvalRecord[]>();
  for (const e of evals) {
    const group = evalGroupByType.get(e.eval_type) ?? FALLBACK_GROUP;
    grouped.set(group.id, [...(grouped.get(group.id) ?? []), e]);
  }

  return [...EVAL_GROUPS, FALLBACK_GROUP]
    .map((definition) => {
      const records = grouped.get(definition.id) ?? [];
      return {
        definition,
        evals: records,
        passes: records.filter((e) => e.status === 'PASS').length,
        warns: records.filter((e) => e.status === 'WARN').length,
        fails: records.filter((e) => e.status === 'FAIL').length,
        blocking: records.filter((e) => e.release_impact === 'BLOCKS_RELEASE' && e.status === 'FAIL').length,
      };
    })
    .filter((group) => group.evals.length > 0);
}

export function SystemEvalCard({ system: s }: { system: EvalsSystemOverview }) {
  const isOpen = expandedSystems.value.has(s.ai_system_id);
  const evals = detailCache.value.get(s.ai_system_id);
  const isLoadingDetail = detailLoading.value.has(s.ai_system_id);
  const isRunning = running.value.has(s.ai_system_id);
  const lr = lastRun.value.get(s.ai_system_id);
  // ADR-003: load multi-vendor catalog once.
  useEffect(() => { void loadSuiteCatalog(); }, []);
  const catalog = suiteCatalog.value;

  return (
    <div class={`sys-eval-card ${isOpen ? 'expanded' : ''}`}>
      <div class="sys-eval-header" onClick={() => toggleSystem(s.ai_system_id)}>
        <div>
          <div class="text-sm font-bold">{s.ai_system_name}</div>
          <div class="text-xs text-secondary" style={{ marginTop: 2 }}>
            {s.ai_system_id} · {s.domain} · {s.runtime_status}
          </div>
        </div>
        <div>
          <div class="text-xs text-secondary">Evals</div>
          <div class="text-sm font-bold">{s.total}</div>
        </div>
        <div>
          <div class="text-xs text-secondary">Pass / Warn / Fail</div>
          <div class="text-sm">
            <span class="font-bold" style={{ color: 'var(--pass)' }}>{s.passes}</span>
            {' / '}
            <span class="font-bold" style={{ color: 'var(--medium)' }}>{s.warns}</span>
            {' / '}
            <span class="font-bold" style={{ color: 'var(--critical)' }}>{s.fails}</span>
          </div>
        </div>
        <div>
          <div class="text-xs text-secondary">Blocking</div>
          <div class={`text-sm font-bold ${s.blocking_fails > 0 ? 'text-critical' : ''}`}>
            {s.blocking_fails}
          </div>
        </div>
        <div style={{ textAlign: 'right' }}>
          <button
            class="btn btn-sm btn-primary"
            disabled={isRunning}
            onClick={(e) => {
              e.stopPropagation();
              void runSimulatedSuite(s.ai_system_id);
            }}
          >
            {isRunning ? 'Running…' : 'Run Simulated Eval Suite'}
          </button>
          {lr && !isRunning && (
            <div class="text-xs text-tertiary" style={{ marginTop: 4 }}>
              Last run {lr.ran_at.slice(0, 19).replace('T', ' ')} · {lr.eval_count} evals · gates {lr.release_gates.decision}
            </div>
          )}
        </div>
      </div>

      {catalog && <EvalSuitePicker catalog={catalog} />}

      {actionError.value && (
        <div class="error-banner" style={{ margin: '6px 12px' }}>{actionError.value}</div>
      )}

      {isOpen && (
        <div>
          {isLoadingDetail && <div class="loading">Loading evals…</div>}
          {!isLoadingDetail && evals && evals.length === 0 && (
            <div class="empty-state">No evals recorded for this system.</div>
          )}
          {!isLoadingDetail && evals && evals.length > 0 && (
            <div class="eval-group-list">
              {groupEvals(evals).map((group) => (
                <EvalGroupSection key={group.definition.id} group={group} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function EvalGroupSection({ group }: { group: EvalGroup }) {
  return (
    <section class="eval-suite-group">
      <div class="eval-suite-group-header">
        <div>
          <div class="eval-suite-group-title">{group.definition.title}</div>
          <div class="eval-suite-group-subtitle">{group.definition.description}</div>
        </div>
        <div class="eval-suite-group-stats">
          <div>
            <span class="text-tertiary">Tests</span>
            <strong>{group.evals.length}</strong>
          </div>
          <div>
            <span class="text-tertiary">Pass / Warn / Fail</span>
            <strong>
              <span style={{ color: 'var(--pass)' }}>{group.passes}</span>
              {' / '}
              <span style={{ color: 'var(--medium)' }}>{group.warns}</span>
              {' / '}
              <span style={{ color: 'var(--critical)' }}>{group.fails}</span>
            </strong>
          </div>
          <div>
            <span class="text-tertiary">Blocking</span>
            <strong class={group.blocking > 0 ? 'text-critical' : ''}>{group.blocking}</strong>
          </div>
        </div>
      </div>
      <div class="eval-row head">
        <div />
        <div>Test / Source</div>
        <div>Score</div>
        <div>Status</div>
        <div>Release Impact</div>
        <div>Run</div>
      </div>
      {group.evals.map((e) => <EvalDetailRow key={e.id} record={e} />)}
    </section>
  );
}

function EvalDetailRow({ record: e }: { record: EvalRecord }) {
  const isOpen = openEvals.value.has(e.id);
  const pretty = e.eval_type
    .replace(/_/g, ' ')
    .toLowerCase()
    .replace(/\b\w/g, (c) => c.toUpperCase());
  const scoreColor =
    e.status === 'PASS' ? 'var(--pass)'
    : e.status === 'FAIL' ? 'var(--critical)'
    : 'var(--medium)';
  const passRate = e.pass_rate ?? (e.test_count ? (e.test_count - e.failed_count) / e.test_count : 0);

  return (
    <>
      <div class={`eval-row sev-${e.status}`} onClick={() => toggleSet(openEvals, e.id)}>
        <div class="toggle">{isOpen ? '▾' : '▸'}</div>
        <div>
          <div class="text-sm font-bold">{pretty}</div>
          <div class="text-xs text-tertiary">
            {e.tool_source} · n={e.test_count}
            {e.failed_count ? ` · ${e.failed_count} failures` : ''}
          </div>
        </div>
        <div class="score-line">
          <span class="score-num" style={{ color: scoreColor }}>{pct(e.score)}%</span>
          <span class="score-thresh">/ {pct(e.threshold)}%</span>
        </div>
        <div>
          <span class={`badge ${STATUS_BADGE[e.status] ?? 'badge-neutral'}`}>{e.status}</span>
        </div>
        <div>
          <span class={`impact-pill impact-${e.release_impact}`}>
            {e.release_impact.replace(/_/g, ' ')}
          </span>
        </div>
        <div class="text-xs text-tertiary" style={{ textAlign: 'right' }}>
          {(e.run_at ?? '').slice(0, 10)}
        </div>
      </div>
      {isOpen && (
        <div class="eval-detail">
          {e.notes && (
            <div class="row"><dt>Notes</dt><dd>{e.notes}</dd></div>
          )}
          <div class="row">
            <dt>Pass rate</dt>
            <dd>
              {pct(passRate)}% — {e.test_count - e.failed_count}/{e.test_count} cases pass
            </dd>
          </div>
          <div class="row">
            <dt>Controls</dt>
            <dd>
              {(e.control_mappings ?? []).length === 0 ? '—' : (
                <>
                  {(e.control_mappings ?? []).map((c) => (
                    <span key={c} class="badge badge-info" style={{ marginRight: 4 }}>{c}</span>
                  ))}
                </>
              )}
            </dd>
          </div>
          <div class="row">
            <dt>Frameworks</dt>
            <dd>
              {(e.framework_mappings ?? []).length === 0 ? '—' : (
                <>
                  {(e.framework_mappings ?? []).map((f, i) => (
                    <span key={i} class="badge badge-info" style={{ marginRight: 4 }}>
                      {f.framework.replace(/_/g, ' ')} {f.clause}
                    </span>
                  ))}
                </>
              )}
            </dd>
          </div>
          {e.evidence_id && (
            <div class="row">
              <dt>Evidence</dt>
              <dd>
                <a class="badge badge-info" href={`/evidence?id=${encodeURIComponent(e.evidence_id)}`}>
                  {e.evidence_id}
                </a>
              </dd>
            </div>
          )}
          {e.sample_failures && e.sample_failures.length > 0 && (
            <div class="row">
              <dt>Sample failures</dt>
              <dd>
                <ul>
                  {e.sample_failures.map((f, i) => (
                    <li key={i} class="sample">{f}</li>
                  ))}
                </ul>
              </dd>
            </div>
          )}
        </div>
      )}
    </>
  );
}

// ADR-003: multi-vendor suite picker. Only the `enabled` vendor is wired;
// roadmap vendors are non-clickable chips with a tooltip pointing at the
// ADR. No fake metric output; the picker shows what the platform supports
// today vs. what's coming. Suite selection does NOT yet alter the engine
// call — selection wiring lands when 2+ vendors are enabled (ADR-003 §7
// Step 3).
function EvalSuitePicker({ catalog }: { catalog: EvalSuiteCatalog }) {
  const selected = selectedSuite.value || catalog.active_vendor;
  return (
    <div
      class="eval-suite-picker"
      style={{
        padding: '10px 14px',
        borderTop: '1px solid var(--border)',
        borderBottom: '1px solid var(--border)',
        background: 'var(--bg-elev-1, rgba(255,255,255,0.02))',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <div>
          <div class="text-xs text-tertiary" style={{ marginBottom: 4 }}>
            Eval suite (per ADR-003)
          </div>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {catalog.items.map((entry) => (
              <SuiteChip key={entry.vendor} entry={entry} selected={selected === entry.vendor} />
            ))}
          </div>
        </div>
        <div style={{ marginLeft: 'auto', textAlign: 'right' }}>
          <div class="text-xs text-tertiary">Active backend</div>
          <div class="text-sm" style={{ fontFamily: 'monospace' }}>
            {catalog.active_vendor}
            {(() => {
              const active = catalog.items.find((i) => i.vendor === catalog.active_vendor);
              return active && active.vendor_version
                ? <span class="text-tertiary"> · v{active.vendor_version}</span>
                : null;
            })()}
          </div>
        </div>
      </div>
    </div>
  );
}

function SuiteChip({ entry, selected }: { entry: EvalSuiteEntry; selected: boolean }) {
  const isEnabled = entry.status === 'enabled';
  const baseStyle: Record<string, string | number> = {
    padding: '4px 10px',
    borderRadius: 14,
    fontSize: 12,
    border: '1px solid var(--border)',
    cursor: isEnabled ? 'pointer' : 'not-allowed',
    opacity: isEnabled ? 1 : 0.55,
    background: selected && isEnabled ? 'var(--accent, #3b82f6)' : 'transparent',
    color: selected && isEnabled ? '#fff' : 'var(--text-primary)',
    display: 'inline-flex',
    alignItems: 'center',
    gap: 6,
  };
  const tooltip = isEnabled
    ? `${entry.label} · ${entry.integration} · v${entry.vendor_version}`
    : `Roadmap — ${entry.adr_ref}. Click to view ADR.`;
  const onClick = () => {
    if (isEnabled) {
      selectedSuite.value = entry.vendor;
    } else {
      // Roadmap chip → take operator to ADR-003 (same repo path the engine cites)
      window.open(
        'https://github.com/signalyer/ai-assurance-mvp/blob/main/docs/adr/ADR-003-multi-vendor-evals.md',
        '_blank',
        'noopener,noreferrer',
      );
    }
  };
  return (
    <span
      class="suite-chip"
      style={baseStyle}
      title={tooltip}
      onClick={onClick}
      role="button"
      aria-disabled={!isEnabled}
    >
      <span style={{ fontWeight: 600 }}>{entry.label}</span>
      {isEnabled
        ? <span style={{ fontSize: 10 }}>·active</span>
        : <span style={{ fontSize: 10 }}>·roadmap</span>
      }
    </span>
  );
}
