import { signal } from '@preact/signals';
import { useEffect } from 'preact/hooks';
import { Link } from 'wouter-preact';
import { apiGet } from '../../shared/api/client';
import { CasesTable } from '../agent-library/AgentModal';

// S82f-2-extended W4 — discoverability fix for the schema split documented in
// the post-S82f-2 handoff item 10. The generic /evals page reads
// /api/evals/recent which reads data/evals.jsonl (per-LLM-call shape).
// The vendor_risk suite lives in data/vendor_risk_eval_runs.jsonl (suite
// shape). This panel surfaces the suite directly on /evals so the obvious
// page reflects all eval activity, with click-to-Agent-Library deep link.
//
// Generalization plan: today hardcoded to vendor_risk because it's the only
// agent with an eval suite. The shape supports any agent_id — when finadvice
// or azure-architect complete Phase 4 of docs/SOP-agent-onboarding.md, add
// them to AGENTS_WITH_EVAL_SUITES below.

const AGENTS_WITH_EVAL_SUITES = [
  { agent_id: 'vendor_risk', display_name: 'Vendor Risk Analyzer' },
] as const;

interface PerSys { total: number; passed: number; pass_rate: number; }
interface CaseRow {
  id: string | null;
  label: string | null;
  system: string;
  category: string | null;
  passed: boolean;
  overall_score: number | null;
  failures: string[];
  metrics?: { name?: string; score?: number; passed?: boolean; details?: string }[];
  metric_failures: { name?: string; score?: number; passed?: boolean; details?: string }[];
}
interface RunSummary {
  run_id: string | null;
  timestamp: string | null;
  status: string | null;
  mode: string | null;
  cases_total: number | null;
  cases_passed: number | null;
  pass_rate: number | null;
  per_system: Record<string, PerSys>;
  cases?: CaseRow[];
}
interface EvalSummary {
  agent_id: string;
  has_eval_suite: boolean;
  baseline: RunSummary | null;
  latest_run: RunSummary | null;
  trend: { runs_total: number; runs_passed: number; pass_rate_mean: number };
}

const summaries = signal<Record<string, EvalSummary | null>>({});
const loading = signal<boolean>(false);
const error = signal<string | null>(null);

async function loadAll(): Promise<void> {
  loading.value = true;
  error.value = null;
  const out: Record<string, EvalSummary | null> = {};
  for (const a of AGENTS_WITH_EVAL_SUITES) {
    const r = await apiGet<EvalSummary>(
      `/agents/${encodeURIComponent(a.agent_id)}/eval-summary`,
      { include_cases: 'baseline' },
    );
    if (r.ok) out[a.agent_id] = r.data;
    else out[a.agent_id] = null;
  }
  summaries.value = out;
  loading.value = false;
}

function fmtPct(x: number | null | undefined): string {
  if (typeof x !== 'number') return '—';
  return `${(x * 100).toFixed(1)}%`;
}

export function AgentEvalsPanel() {
  useEffect(() => { void loadAll(); }, []);

  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'baseline',
        marginBottom: 8,
      }}>
        <div>
          <div style={{ fontSize: 14, fontWeight: 600 }}>Agent eval suites</div>
          <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
            Suite-level results from <code>data/&lt;agent&gt;_eval_runs.jsonl</code> and
            <code> agents/&lt;agent&gt;/eval/baseline.json</code> — different schema from
            the per-LLM-call evals below.
          </div>
        </div>
        <button class="btn btn-sm btn-secondary" onClick={() => void loadAll()}>Refresh</button>
      </div>
      {error.value && <div class="error-banner">{error.value}</div>}
      {loading.value && Object.keys(summaries.value).length === 0 && (
        <div class="loading">Loading agent eval suites…</div>
      )}
      {AGENTS_WITH_EVAL_SUITES.map((a) => {
        const s = summaries.value[a.agent_id];
        return <AgentEvalCard key={a.agent_id} agentId={a.agent_id} displayName={a.display_name} summary={s ?? null} />;
      })}
    </div>
  );
}

function AgentEvalCard({
  agentId,
  displayName,
  summary,
}: {
  agentId: string;
  displayName: string;
  summary: EvalSummary | null;
}) {
  if (!summary) return null;
  if (!summary.has_eval_suite) {
    return (
      <div style={{
        border: '1px solid var(--border)',
        borderRadius: 6,
        padding: 12,
        marginBottom: 8,
      }}>
        <div style={{ fontWeight: 600 }}>{displayName}</div>
        <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
          No eval suite — demo-only agent. See <code>docs/SOP-agent-onboarding.md</code>.
        </div>
      </div>
    );
  }
  const baseline = summary.baseline;
  const latest = summary.latest_run;
  const baselineColor = baseline?.status === 'PASS' ? 'var(--pass)' : 'var(--medium)';
  const latestColor = latest?.status === 'PASS' ? 'var(--pass)' : 'var(--medium)';

  return (
    <div style={{
      border: '1px solid var(--border)',
      borderRadius: 6,
      padding: 12,
      marginBottom: 12,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
        <div>
          <div style={{ fontWeight: 600, fontSize: 14 }}>{displayName}</div>
          <div style={{ fontSize: 11, color: 'var(--text-tertiary)' }} class="font-mono">{agentId}</div>
        </div>
        <Link
          href={`/agent-library?open=${encodeURIComponent(agentId)}`}
          style={{ fontSize: 12 }}
        >
          Open in Agent Library →
        </Link>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12, marginTop: 8 }}>
        <Stat label="Baseline" value={baseline ? `${baseline.cases_passed ?? '—'} / ${baseline.cases_total ?? '—'}` : '—'} sub={baseline ? `${fmtPct(baseline.pass_rate)} · ${baseline.status}` : ''} color={baselineColor} />
        <Stat label="Latest run" value={latest ? `${latest.cases_passed ?? '—'} / ${latest.cases_total ?? '—'}` : '—'} sub={latest ? `${fmtPct(latest.pass_rate)} · ${latest.status}` : ''} color={latestColor} />
        <Stat label="Trend" value={`${summary.trend.runs_passed}/${summary.trend.runs_total} PASS`} sub={`mean ${fmtPct(summary.trend.pass_rate_mean)}`} color="var(--text-secondary)" />
      </div>

      {baseline && Object.keys(baseline.per_system).length > 0 && (
        <div style={{ marginTop: 10 }}>
          <div style={{ fontWeight: 600, fontSize: 12, marginBottom: 4 }}>Baseline by system</div>
          <table class="version-table" style={{ fontSize: 11 }}>
            <thead><tr><th>System</th><th>Passed</th><th>Pass rate</th></tr></thead>
            <tbody>
              {Object.entries(baseline.per_system).map(([sys, m]) => (
                <tr key={sys}>
                  <td class="font-mono">{sys}</td>
                  <td>{m.passed} / {m.total}</td>
                  <td>{fmtPct(m.pass_rate)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {baseline?.cases && baseline.cases.length > 0 && (
        <details style={{ marginTop: 12 }}>
          <summary style={{ cursor: 'pointer', fontWeight: 600, fontSize: 13 }}>
            All {baseline.cases.length} baseline cases — click to drill into every metric
          </summary>
          <div style={{ marginTop: 8 }}>
            <CasesTable cases={baseline.cases} />
          </div>
        </details>
      )}
    </div>
  );
}

function Stat({ label, value, sub, color }: { label: string; value: string; sub: string; color: string }) {
  return (
    <div>
      <div style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>{label}</div>
      <div style={{ fontSize: 18, fontWeight: 600 }}>{value}</div>
      <div style={{ fontSize: 11, color, fontWeight: 600 }}>{sub}</div>
    </div>
  );
}
