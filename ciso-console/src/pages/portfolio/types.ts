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
  // S74b: portfolio-surface evidence summary for Draft Report grounding parity
  // with team-portal AiSystemDrawer. Optional for backwards compat with cached
  // responses; engine always populates them now.
  evidence_count?: number;
  evidence_types?: string[];
}

export interface AiSystemsListResponse {
  systems: AiSystemSummary[];
  total: number;
}
