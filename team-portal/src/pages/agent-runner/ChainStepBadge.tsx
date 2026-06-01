import type { StepState, StepStatus } from './types';

interface Props {
  step: StepState;
}

const STATUS_BADGE: Record<StepStatus, string> = {
  pending: 'badge-neutral',
  active: 'badge-info',
  success: 'badge-pass',
  denied: 'badge-critical',
  review: 'badge-medium',
  blocked: 'badge-high',
  error: 'badge-critical',
};

const STATUS_GLYPH: Record<StepStatus, string> = {
  pending: '○',
  active: '◐',
  success: '●',
  denied: '✕',
  review: '?',
  blocked: '!',
  error: '✕',
};

function formatElapsed(ms: number | null): string {
  if (ms === null) return '—';
  if (ms < 1) return '<1ms';
  if (ms < 1000) return `${ms.toFixed(1)}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

export function ChainStepBadge({ step }: Props) {
  const sevCls = STATUS_BADGE[step.status];
  const glyph = STATUS_GLYPH[step.status];
  const isPending = step.status === 'pending';
  return (
    <div
      class="card"
      style={{
        padding: '0.6rem 0.85rem',
        marginBottom: '0.5rem',
        opacity: isPending ? 0.55 : 1,
        borderLeft: `3px solid var(--${
          step.status === 'pending' ? 'border' :
          step.status === 'active' ? 'info' :
          step.status === 'success' ? 'pass' :
          step.status === 'review' ? 'medium' :
          step.status === 'denied' || step.status === 'error' ? 'critical' :
          'high'
        })`,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
        <span style={{ fontSize: 14, width: 16, textAlign: 'center', color: 'var(--text-secondary)' }}>
          {glyph}
        </span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div class="card-title" style={{ fontSize: 12 }}>{step.label}</div>
          {step.detail ? (
            <div class="text-xs text-tertiary" style={{ marginTop: 2 }}>{step.detail}</div>
          ) : null}
        </div>
        <span class={`badge ${sevCls}`} style={{ fontSize: 10 }}>
          {step.status.toUpperCase()}
        </span>
        <span class="text-xs text-tertiary" style={{ minWidth: 48, textAlign: 'right' }}>
          {formatElapsed(step.elapsed_ms)}
        </span>
      </div>
    </div>
  );
}
