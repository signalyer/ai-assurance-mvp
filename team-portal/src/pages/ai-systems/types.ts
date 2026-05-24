// AI Systems wire types — mirror of api/grc.py response shapes for the
// /api/grc/ai-systems endpoints. Replace with codegen output from
// docs/openapi-v1.json once openapi-typescript is wired in.

export interface AiSystemSummary {
  id: string;
  name: string;
  business_owner: string;
  technical_owner?: string;
  domain: string;
  risk_level: string;
  autonomy_level: string;
  data_classes: string[];
  runtime_status: string;
  release_decision: string;
  open_findings: number;
  critical_findings: number;
  last_assessment: string;
}

export interface AiSystemFinding {
  id: string;
  title: string;
  severity: string;
  status: 'OPEN' | 'IN_PROGRESS' | 'RESOLVED' | string;
}

export interface ReleaseGate {
  id: string;
  passed: boolean;
  note?: string;
  actual?: string;
}

export interface ReleaseGateBlock {
  gates: ReleaseGate[];
  approver: string;
}

export interface AiSystemDetail extends AiSystemSummary {
  description: string;
  use_case: string;
  model: string;
  human_oversight: string;
  deployment_target: string;
  data_residency: string;
  trust_boundaries: string;
  next_assessment: string;
  findings: AiSystemFinding[];
  release_gates?: ReleaseGateBlock;
}

export interface AiSystemsListResponse {
  systems: AiSystemSummary[];
}
