// Adversarial probe suite — wire types mirroring api/adversarial.py.
// SSE stream: start | probe | done | error.

export interface CategoriesResponse {
  categories: string[];
  total_probes: number;
}

export type Severity = 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW';

export interface StartEvent {
  event: 'start';
  model: string;
  provider: 'anthropic' | 'openai';
  total_probes: number;
  categories: string[];
}

export interface ProbeEvent {
  event: 'probe';
  index: number;
  total: number;
  category: string;
  probe_name: string;
  severity: Severity;
  resisted: boolean | null;
  confidence?: string | null;
  reason?: string | null;
  error?: string | null;
  latency_ms: number;
}

export interface DoneEvent {
  event: 'done';
  summary: {
    model: string;
    provider: string;
    total_probes: number;
    resisted_count: number;
    failed_count: number;
    security_score: number;
    risk_level: Severity;
    failed_by_severity: Record<Severity, number>;
    categories_tested: string[];
  };
}

export interface ErrorEvent {
  event: 'error';
  message: string;
  detail?: string;
}

export type StreamEvent = StartEvent | ProbeEvent | DoneEvent | ErrorEvent;
