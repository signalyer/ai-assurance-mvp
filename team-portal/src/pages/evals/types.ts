// Evals wire types — mirror /api/v1/grc/evals/v2/* response shapes.

export type EvalStatus = 'PASS' | 'WARN' | 'FAIL' | string;
export type ReleaseImpact = 'BLOCKS_RELEASE' | 'CONDITIONAL' | 'NONE' | string;

export interface EvalsSystemOverview {
  ai_system_id: string;
  ai_system_name: string;
  domain: string;
  runtime_status: string;
  total: number;
  passes: number;
  warns: number;
  fails: number;
  blocking_fails: number;
}

export interface FrameworkMapping {
  framework: string;
  clause: string;
}

export interface EvalRecord {
  id: string;
  eval_type: string;
  tool_source: string;
  status: EvalStatus;
  score: number;
  threshold: number;
  test_count: number;
  failed_count: number;
  pass_rate?: number | null;
  release_impact: ReleaseImpact;
  run_at: string;
  notes?: string | null;
  control_mappings?: string[];
  framework_mappings?: FrameworkMapping[];
  evidence_id?: string | null;
  sample_failures?: string[];
}

export interface OverviewResponse { systems: EvalsSystemOverview[] }
export interface SystemDetailResponse { evals: EvalRecord[] }

// POST /grc/evals/v2/run/{ai_system_id} — synchronous SimulatedRunOut envelope.
export interface RefreshedEval {
  eval_id: string;
  eval_type: string;
  new_score: number;
  status: EvalStatus;
}

export interface AssessmentSummary {
  overall_score: number;
  inherent_risk: string;
  residual_risk: string;
  residual_score: number;
  release_recommendation: string;
  rule_fired?: string | null;
  rationale?: string | null;
  failed_controls: string[];
  findings_generated: number;
  evidence_completeness: number;
}

export interface GateRollup {
  decision: string;
  rationale: string;
  pass_count: number;
  fail_count: number;
  warning_count: number;
  blocking_failures: number;
}

export interface SimulatedRunResponse {
  ai_system_id: string;
  ran_at: string;
  eval_count: number;
  evals: RefreshedEval[];
  assessment: AssessmentSummary;
  release_gates: GateRollup;
}

// ADR-003: multi-vendor eval suite catalog.
export type SuiteStatus = 'enabled' | 'roadmap';

export interface EvalSuiteEntry {
  vendor: string;
  label: string;
  description: string;
  integration: string;
  adr_ref: string;
  status: SuiteStatus;
  vendor_version: string;
}

export interface EvalSuiteCatalog {
  items: EvalSuiteEntry[];
  active_vendor: string;
  adr: string;
}

// ===========================================================================
// S70b — recent live evals (real data from data/evals.jsonl)
// Mirrors api/evaluate.py::RecentEvalsResponse. The "Recent live runs" panel
// on the Evals page reads these in addition to the seed-overlay system cards
// below. Provenance is intentionally narrow: real agent/SDK runs only.
// ===========================================================================

export interface RecentEvalMetric {
  score: number | null;
  passed: boolean | null;
  skipped: boolean;
  details: string;
}

export interface RecentEvalRow {
  trace_id: string;
  timestamp: string;
  workload_id: string | null;
  model: string | null;
  results: Record<string, RecentEvalMetric>;
}

export interface RecentEvalsResponse {
  rows: RecentEvalRow[];
  total: number;
  source: string;
}
