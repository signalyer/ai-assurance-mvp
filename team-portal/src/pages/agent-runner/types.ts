// Mirror of docs/agent-runner-sse-protocol.md (locked S80).
// Any field change here must update that doc + tests/test_agent_runner_chain_events.py
// per [[grep-all-consumers-before-contract-flip]].

export type ChainOutcome =
  | 'success'
  | 'failure'
  | 'review'
  | 'denied'
  | 'guardrail_block'
  | 'error';

export type PolicyDecision = 'ALLOW' | 'DENY' | 'REVIEW';

export type AuditDecision = 'LIVE' | 'SIMULATED' | 'BLOCKED';

export type ChainErrorStep =
  | 'resolve'
  | 'policy_gate'
  | 'scrub_pii'
  | 'guardrails'
  | 'llm'
  | 'evaluate'
  | 'sse';

interface BaseEvent {
  event: string;
  run_id: string;
  elapsed_ms: number;
}

export interface ChainStartEvent extends BaseEvent {
  event: 'chain.start';
  agent_id: string;
  agent_name: string;
  provider_id: string;
  system_id: string;
  user: string;
  started_at: string;
}

export interface PolicyGateEvent extends BaseEvent {
  event: 'policy_gate';
  decision: PolicyDecision;
  rule: string;
  reason: string;
}

export interface ScrubPiiEvent extends BaseEvent {
  event: 'scrub_pii';
  scrubber_enabled: boolean;
  redacted_count: number;
  redacted_field_types: string[];
  vault_id: string;
  scrubbed_preview: string;
  raw_preview?: string; // DEMO_MODE only
}

export interface GuardrailsEvent extends BaseEvent {
  event: 'guardrails';
  passed: boolean;
  violations: string[];
  injection_score: number | null;
  topic_in_scope: boolean | null;
  safety_pass: boolean | null;
}

export interface LlmDeltaEvent extends BaseEvent {
  event: 'llm.delta';
  text: string;
  turn: number;
}

export interface LlmDoneEvent extends BaseEvent {
  event: 'llm.done';
  model: string;
  input_tokens: number;
  output_tokens: number;
  delta_count: number;
  stop_reason: string;
  turns: number;
}

export interface EvaluateEvent extends BaseEvent {
  event: 'evaluate';
  scores: Record<string, unknown>;
  avg_score: number | null;
  scored_metric_count: number;
  deferred_to_s85?: boolean;
}

export interface MemoryEvent extends BaseEvent {
  event: 'memory';
  episode_id: string;
  outcome: 'success' | 'failure' | 'review';
  workload_id: string;
}

export interface AuditEvent extends BaseEvent {
  event: 'audit';
  audit_id: string;
  decision: AuditDecision;
  trace_id: string;
  langfuse_url: string | null;
  appinsights_url: string | null;
}

export interface ChainDoneEvent extends BaseEvent {
  event: 'chain.done';
  outcome: ChainOutcome;
  episode_id: string;
  audit_id: string;
  total_elapsed_ms: number;
  terminal_reason: string | null;
}

export interface ChainErrorEvent extends BaseEvent {
  event: 'chain.error';
  step: ChainErrorStep;
  error_type: string;
  message: string;
}

export type ChainEvent =
  | ChainStartEvent
  | PolicyGateEvent
  | ScrubPiiEvent
  | GuardrailsEvent
  | LlmDeltaEvent
  | LlmDoneEvent
  | EvaluateEvent
  | MemoryEvent
  | AuditEvent
  | ChainDoneEvent
  | ChainErrorEvent;

// The 8 named steps the ChainTicker renders, in temporal order.
// llm.delta is folded INTO the llm step; chain.start/chain.done bracket the
// pipeline rather than appearing as steps; chain.error is a per-step overlay.
export type StepName =
  | 'policy_gate'
  | 'scrub_pii'
  | 'guardrails'
  | 'llm'
  | 'evaluate'
  | 'memory'
  | 'audit'
  | 'done';

export type StepStatus =
  | 'pending'  // not started yet (pre-run skeleton or upstream of cursor)
  | 'active'  // currently running (most recent non-terminal event)
  | 'success'
  | 'denied'
  | 'review'
  | 'blocked'
  | 'error';

export interface StepState {
  name: StepName;
  label: string;
  status: StepStatus;
  elapsed_ms: number | null;
  detail: string | null;        // short pill text (e.g. "ALLOW", "0 redacted", "claude-sonnet-4-6")
  payload: ChainEvent | null;   // last event that updated this step
}

export interface RegistryAgent {
  agent_id: string;
  name: string;
  description: string;
  default_system_id: string;
  cli_only: boolean;
}

export interface RegistryListResponse {
  agents: RegistryAgent[];
}

export interface RunRequest {
  agent_id: string;
  prompt: string;
  system_id?: string;
  model?: string;
  demo_mode?: boolean;
}
