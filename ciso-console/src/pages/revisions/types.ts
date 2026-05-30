// Revisions Queue — type definitions.
// Mirrors engine response shapes from api/ai_system_edit.py:
//   GET  /api/ai-systems/revisions/pending           — org-wide pending list
//   GET  /api/ai-systems/revisions/{revision_id}     — single revision detail
//   POST /api/ai-systems/revisions/{revision_id}/decide — approve / reject / override
// G-1 (S65): the CISO-side decide surface that closes the UI-promise gap
// surfaced in S64's audit.

export type ApprovalStatus =
  | 'pending'
  | 'approved'
  | 'rejected'
  | 'auto_applied'
  | 'overridden';

export type RevisionTier = 'soft' | 'material' | 'critical';

export interface FieldChange {
  field: string;
  before?: unknown;
  after?: unknown;
  // Some revisions carry policy/rerun metadata directly on each change row;
  // keep this loose because the engine model is extra="allow".
  [key: string]: unknown;
}

export interface Revision {
  revision_id: string;
  ai_system_id: string;
  created_at: string;
  created_by: string;
  tier: RevisionTier | string;
  fields_changed: FieldChange[];
  approval_status?: ApprovalStatus | string;
  change_reason?: string;
  change_category?: string;
  rerun_steps?: string[];
  required_approver_roles?: string[];
  // The engine RevisionOut is extra="allow"; surface extras as opaque.
  [key: string]: unknown;
}

export interface RevisionsListResponse {
  revisions: Revision[];
  count: number;
}

export interface EditStatus {
  has_pending_material: boolean;
  release_blocked_by_revision: boolean;
  pending_revision_id: string | null;
  revision_count: number;
  last_revision_at: string | null;
  last_revision_tier: string | null;
}

export interface DecideResponse {
  revision: Revision;
  status: EditStatus;
}

export type Decision = 'APPROVE' | 'REJECT' | 'OVERRIDE';
