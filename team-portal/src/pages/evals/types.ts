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
