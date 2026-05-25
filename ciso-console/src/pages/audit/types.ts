// Audit Verification — type definitions.
// Mirrors engine response shapes from:
//   GET /api/audit/events?page=N     (paged event list)
//   GET /api/audit/verify?window=N&full=true  (chain integrity check)
// Source: audit_verify.py router.

export interface AuditEvent {
  id: string;
  timestamp: string;
  event_type: string;
  actor: string;
  resource_type?: string | null;
  resource_id?: string | null;
  action: string;
  outcome: string;
  details?: Record<string, unknown> | null;
  hash?: string | null;
  prev_hash?: string | null;
}

export interface AuditEventsResponse {
  events: AuditEvent[];
  page: number;
  page_size: number;
  total: number;
  has_next: boolean;
}

export interface AuditVerifyBrokenEntry {
  id: string;
  position: number;
  reason: string;
}

export interface AuditVerifyResponse {
  status: 'CLEAN' | 'BROKEN';
  window: number;
  events_checked: number;
  broken_count: number;
  broken_entries: AuditVerifyBrokenEntry[];
  verified_at: string;
}
