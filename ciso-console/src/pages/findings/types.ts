// Findings Inbox — type definitions.
// Mirrors the engine response shape from GET /api/findings/v2/
// (findings_v2.py router, already in the fully-clean OpenAPI sweep list).

export type FindingPriority = 'P0' | 'P1' | 'P2' | 'P3';
export type FindingStatus =
  | 'OPEN'
  | 'IN_PROGRESS'
  | 'RISK_ACCEPTED'
  | 'REMEDIATED'
  | 'VERIFIED'
  | 'CLOSED';
export type FindingImpact =
  | 'BLOCK_PRODUCTION'
  | 'BLOCK_PILOT'
  | 'WARNING'
  | 'NO_IMPACT';

export interface Finding {
  id: string;
  title: string;
  description: string;
  priority: FindingPriority;
  status: FindingStatus;
  impact: FindingImpact;
  ai_system_id: string;
  ai_system_name?: string | null;
  framework?: string | null;
  control_id?: string | null;
  assigned_to?: string | null;
  sla_days?: number | null;
  sla_breached?: boolean | null;
  created_at: string;
  updated_at: string;
  remediation_notes?: string | null;
  timeline?: FindingTimelineEntry[] | null;
}

export interface FindingTimelineEntry {
  timestamp: string;
  actor: string;
  action: string;
  note?: string | null;
}

export interface FindingsV2Response {
  findings: Finding[];
  total: number;
  page: number;
  page_size: number;
}
