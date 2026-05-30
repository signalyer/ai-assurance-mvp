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

// --- Edit flow (api/ai_system_edit.py) -------------------------------------

export interface EditStatus {
  has_pending_material: boolean;
  release_blocked_by_revision: boolean;
  pending_revision_id: string | null;
  revision_count: number;
  last_revision_at: string | null;
  last_revision_tier: string | null;
}

export interface EditInfo {
  ai_system_id: string;
  field_tiers: { soft: string[]; material: string[]; locked: string[] };
  rerun_matrix: Record<string, string[]>;
  approval_roles_by_level: Record<string, string[]>;
  valid_change_categories: string[];
  status: EditStatus;
}

export interface FieldChange {
  field: string;
  before?: unknown;
  after?: unknown;
}

export interface Approver {
  user: string;
  role: string;
  decision: string;
  signed_at: string;
  note?: string;
}

export interface Revision {
  revision_id: string;
  ai_system_id: string;
  created_at: string;
  created_by: string;
  tier: string;
  fields_changed: FieldChange[];
  soft_changes?: string[];
  material_changes?: string[];
  change_reason?: string;
  change_category?: string;
  approval_status?: string;
  required_approver_roles?: string[];
  approvers?: Approver[];
  triggered_reruns?: string[];
  decided_at?: string;
}

export interface RevisionsListResponse {
  revisions: Revision[];
  count: number;
}

export interface SubmitEditResponse {
  revision: Revision;
  status: EditStatus;
  next_step: 'pending_approval' | 'applied' | string;
}

// --- Evidence (api/grc.py::EvidenceRowOut) ---------------------------------
// Shared by AiSystemEditModal (read+add) and AiSystemDrawer (read-only).

export interface EvidenceRow {
  id: string;
  ai_system_id: string;
  evidence_type: string;
  source: string;
  uri: string | null;
  hash: string | null;
  collected_at: string;
  summary: string;
  immutable: boolean;
  linked_control_ids: string[];
  linked_finding_ids: string[];
  linked_frameworks: string[];
  data_source: string;
}

export interface EvidenceListResponse {
  ai_system_id: string;
  evidence: EvidenceRow[];
  count: number;
}
