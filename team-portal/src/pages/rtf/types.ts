// Right-to-Forget wire types — mirror of api/right_to_forget.py.
// Engineer-side surface: submit a cascade, view history.
// Approval queue + per-store digest forensics live on CISO Console.

export interface PurgeStep {
  store: string;
  items_removed: number;
  sha256_digest_after: string;
  error: string | null;
}

export interface CascadeResult {
  cascade_id: string;
  subject_id: string;
  status: 'COMPLETED' | 'PARTIAL_FAILURE' | 'ALREADY_COMPLETED' | string;
  steps: Record<string, PurgeStep>;
  started_at: string;
  completed_at: string;
}

export interface CascadeListResponse {
  cascades: CascadeResult[];
}
