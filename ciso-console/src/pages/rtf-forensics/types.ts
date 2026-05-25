// RTF Forensics Deep View — type definitions (CSM-3)
// Mirrors engine response shapes:
//   GET /api/right-to-forget           — list all cascades
//   GET /api/right-to-forget/{id}      — detail with per-store SHA-256
//   GET /api/audit/verify?window=200   — chain proof

export type CascadeStatus =
  | 'PENDING_APPROVAL'
  | 'APPROVED'
  | 'REJECTED'
  | 'COMPLETED'
  | 'PARTIAL_FAILURE'
  | 'ALREADY_COMPLETED';

export interface PurgeStep {
  store: string;
  items_removed: number;
  sha256_digest_after: string;
  error?: string | null;
}

export interface CascadeDetail {
  cascade_id: string;
  subject_id: string;
  status: CascadeStatus;
  steps: Record<string, PurgeStep>;
  started_at: string;
  completed_at: string;
  governance?: {
    chain_hash?: string | null;
    trace_id?: string | null;
  } | null;
}

// List endpoint returns a superset with approval fields
export interface CascadeRow {
  cascade_id: string;
  subject_id: string;
  reason: string;
  status: CascadeStatus;
  requested_by: string;
  approved_by?: string | null;
  started_at: string;
  completed_at?: string | null;
  steps?: Record<string, PurgeStep> | null;
}

export interface CascadeListResponse {
  cascades: CascadeRow[];
}

export interface ChainVerifyResponse {
  status: 'CLEAN' | 'BROKEN';
  events_checked: number;
  broken_at?: string | null;
  window_start_event_id?: string | null;
}
