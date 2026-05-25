// Release Gates — type definitions.
// Mirrors engine response shapes from:
//   GET /api/grc/release-gates/v2/systems  (release_gates.py SystemGateSummariesOut)
//   GET /api/grc/release-gates/v2/system/{id}  (GateReportOut)
//   POST /api/grc/release-gates/v2/exception  (GateExceptionOut)

export interface SystemGateSummary {
  ai_system_id: string;
  ai_system_name: string;
  domain: string | null;
  runtime_status: string | null;
  release_decision: string | null;
  release_rationale: string | null;
  pass_count: number | null;
  fail_count: number | null;
  warning_count: number | null;
  blocking_failures: number | null;
  evidence_completeness: number | null;
  error: string | null;
}

export interface SystemGateSummariesResponse {
  systems: SystemGateSummary[];
}

export interface GateEvaluation {
  gate_id: string;
  name: string;
  status: string;
  blocking: boolean;
  failed_reason: string | null;
  mapped_controls: string[];
  mapped_frameworks: string[];
  evidence_required: string[];
  remediation_required: string[];
  exception_id: string | null;
}

export interface GateReport {
  ai_system_id: string;
  ai_system_name: string;
  target_environment: string;
  generated_at: string;
  gates: GateEvaluation[];
  release_decision: string;
  release_rationale: string;
  pass_count: number;
  fail_count: number;
  warning_count: number;
  blocking_failures: number;
  evidence_completeness: number;
}

export interface ExceptionRequest {
  ai_system_id: string;
  gate_id: string;
  reason: string;
  risk_acceptor: string;
  risk_acceptor_role: string;
  expires_at: string;
  compensating_controls: string[];
}

export interface GateException {
  id: string;
  ai_system_id: string;
  gate_id: string;
  reason: string;
  risk_acceptor: string;
  risk_acceptor_role: string;
  expires_at: string;
  status: string;
  compensating_controls: string[];
  created_at: string;
}
