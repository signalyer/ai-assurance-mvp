// Assurance Model wire types — mirror of api/assurance_model.py Pydantic
// models for the LLM-triggering endpoints. Ported verbatim from
// team-portal/src/shared/types/assurance.ts in S72 — keep in sync.
//
// Engine source of truth: api/assurance_model.py::AskRequest, AskResponseOut.

export interface AskRequest {
  use_case?: string;
  ai_system_id?: string | null;
  data_classes?: string[];
  question?: string | null;
  payload?: Record<string, unknown>;
  preferred_provider?: string | null;
  user?: string;
}

export type PolicyDecisionOut = Record<string, unknown>;

export interface GovernanceMetadata {
  policy_decision?: 'ALLOW' | 'DENY' | string;
  trace_id?: string | null;
  chain_hash?: string | null;
}

export interface AskResponseOut {
  status: 'blocked' | 'simulated' | 'live' | string;
  provider: string | null;
  provider_id: string | null;
  model: string | null;
  use_case: string;
  response: string | null;
  policy_decision: PolicyDecisionOut | null;
  audit_event_id: string;
  sanitized_redactions: string[];
  governance: GovernanceMetadata | null;
  token_estimate?: number | null;
  cost_estimate_usd?: number | null;
  streaming_complete?: boolean | null;
}
