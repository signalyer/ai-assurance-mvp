// Shared badge primitives — ported from static/shared.js severity/decision/runtime helpers.
// Used by AI Systems, Runtime, Evals, Agent Library pages.

import type { ComponentChildren } from 'preact';

export type Severity = 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW' | 'INFO' | string;
export type Decision = 'APPROVED' | 'CONDITIONAL_PILOT' | 'HOLD' | 'REJECT' | string;
export type RuntimeStatus = 'PRODUCTION' | 'PILOT' | 'STAGED' | string;

const SEVERITY_CLASS: Record<string, string> = {
  CRITICAL: 'badge-critical',
  HIGH: 'badge-high',
  MEDIUM: 'badge-medium',
  LOW: 'badge-low',
  INFO: 'badge-info',
};

const DECISION_CLASS: Record<string, string> = {
  APPROVED: 'badge-pass',
  CONDITIONAL_PILOT: 'badge-medium',
  HOLD: 'badge-high',
  REJECT: 'badge-critical',
};

const DECISION_LABEL: Record<string, string> = {
  APPROVED: 'Approved',
  CONDITIONAL_PILOT: 'Conditional',
  HOLD: 'Hold',
  REJECT: 'Reject',
};

export function SeverityBadge({ value }: { value: Severity }) {
  const cls = SEVERITY_CLASS[value] ?? 'badge-neutral';
  return <span class={`badge ${cls}`}>{value}</span>;
}

export function DecisionBadge({ value }: { value: Decision }) {
  const cls = DECISION_CLASS[value] ?? 'badge-neutral';
  const label = DECISION_LABEL[value] ?? value;
  return <span class={`badge ${cls}`}>{label}</span>;
}

export function RuntimeStatusDot({ value }: { value: RuntimeStatus }) {
  const cls = value === 'PRODUCTION' ? 'dot-pass' : value === 'PILOT' ? 'dot-medium' : 'dot-low';
  return (
    <span class="runtime-status">
      <span class={`status-dot ${cls}`} />
      <span>{value}</span>
    </span>
  );
}

export function Badge({ tone = 'neutral', children }: { tone?: string; children: ComponentChildren }) {
  return <span class={`badge badge-${tone}`}>{children}</span>;
}
