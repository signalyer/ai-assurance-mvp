// Cross-cutting response types — manual mirror of api/_models.py.
// Replaced by openapi-typescript codegen (npm run codegen) in a follow-up task.
// Keep field names snake_case to match the engine wire format.

export interface GovernanceMetadata {
  trace_id?: string | null;
  policy_decision?: 'allow' | 'deny' | null;
  scrubbed?: boolean | null;
  guardrails_passed?: boolean | null;
  eval_score?: number | null;
}

export interface CursorPage<T> {
  items: T[];
  total: number | null;
  next_cursor: string | null;
  limit: number;
}

export interface JobResponse {
  job_id: string;
  status: 'queued' | 'running' | 'complete' | 'failed';
  created_at: string;
}

export interface OkResponse {
  ok: true;
}

export interface ConflictDetail {
  reason: string;
  policy_id?: string | null;
}

export interface ServerErrorDetail {
  detail: string;
  trace_id: string;
}

export interface WhoAmI {
  user: string;
  is_ciso?: boolean;
}
