// RTF Approval Queue — type definitions.
// Mirrors engine response shapes from right_to_forget.py router:
//   GET  /api/right-to-forget?status=pending
//   POST /api/right-to-forget/{id}/approve
// Note: cascade submission lives in Team Workspace RtfRequestPage.

export type CascadeStatus =
  | 'PENDING_APPROVAL'
  | 'APPROVED'
  | 'REJECTED'
  | 'COMPLETED'
  | 'PARTIAL_FAILURE'
  | 'ALREADY_COMPLETED';

export interface CascadeStep {
  store: string;
  items_removed: number;
  sha256?: string | null;
  error?: string | null;
}

export interface Cascade {
  cascade_id: string;
  subject_id: string;
  reason: string;
  status: CascadeStatus;
  requested_by: string;
  approved_by?: string | null;
  approved_at?: string | null;
  rejection_reason?: string | null;
  started_at: string;
  completed_at?: string | null;
  steps?: Record<string, CascadeStep> | null;
}

export interface CascadeListResponse {
  cascades: Cascade[];
}

export interface ApproveResponse {
  cascade_id: string;
  status: CascadeStatus;
  approved_by: string;
  approved_at: string;
}
