// Portfolio Overview — type definitions.
// Mirrors engine response shape from GET /api/grc/ai-systems (grc.py AiSystemSummaryOut).

export interface AiSystemSummary {
  id: string;
  name: string;
  business_owner: string;
  technical_owner: string;
  domain: string;
  description: string;
  risk_level: string;
  autonomy_level: string;
  data_classes: string[];
  model: string;
  runtime_status: string;
  release_decision: string;
  open_findings: number;
  critical_findings: number;
  last_assessment: string;
  next_assessment: string;
  deployment_target: string;
  use_case: string;
  human_oversight: string;
  data_residency: string;
  trust_boundaries: string;
}

export interface AiSystemsListResponse {
  systems: AiSystemSummary[];
  total: number;
}
