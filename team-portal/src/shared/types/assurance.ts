// Assurance Model wire types — mirror of api/assurance_model.py Pydantic
// models for the LLM-triggering endpoints (/assurance-model/ask,
// /summarize-finding, /explain-release, /summarize-evidence, /draft-report).
//
// Engine source of truth: api/assurance_model.py::AskRequest, AskResponseOut.
// S68a: surface the response.status discriminator so the drawer can render
// the "Simulated preview" badge today and drop it transparently in S69
// once REAL_LLM_ENABLED is wired in the dispatcher.

export interface AskRequest {
  use_case?: string;
  ai_system_id?: string | null;
  data_classes?: string[];
  question?: string | null;
  payload?: Record<string, unknown>;
  preferred_provider?: string | null;
  user?: string;
}

// PolicyDecisionOut on the engine uses ConfigDict(extra='allow') — shape
// varies across blocked / re-check blocked / allowed branches. Keep loose.
export type PolicyDecisionOut = Record<string, unknown>;

export interface GovernanceMetadata {
  policy_decision?: 'ALLOW' | 'DENY' | string;
  trace_id?: string | null;
  chain_hash?: string | null;
}

// status: "blocked" | "simulated" | (future "live" once S69 ships).
// Drawer branches on this to show/hide the Simulated preview badge.
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
}
