import type { StepName, StepState } from './types';
import { ChainStepBadge } from './ChainStepBadge';

interface Props {
  steps: StepState[];
  llmText: string;
  runId: string | null;
  totalElapsedMs: number | null;
}

export const STEP_ORDER: StepName[] = [
  'policy_gate',
  'scrub_pii',
  'guardrails',
  'llm',
  'evaluate',
  'memory',
  'audit',
  'done',
];

const STEP_LABELS: Record<StepName, string> = {
  policy_gate: 'Policy Gate',
  scrub_pii: 'PII Scrub',
  guardrails: 'Guardrails',
  llm: 'LLM (tool-use)',
  evaluate: 'Evaluation',
  memory: 'Memory (write_episode)',
  audit: 'Audit',
  done: 'Done',
};

export function buildInitialSteps(): StepState[] {
  return STEP_ORDER.map((name) => ({
    name,
    label: STEP_LABELS[name],
    status: 'pending',
    elapsed_ms: null,
    detail: null,
    payload: null,
  }));
}

export function ChainTicker({ steps, llmText, runId, totalElapsedMs }: Props) {
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: '0.6rem' }}>
        <div class="card-title">Chain</div>
        <div class="text-xs text-tertiary">
          {runId ? <span>run_id: <code>{runId}</code></span> : <span>—</span>}
          {totalElapsedMs !== null ? <span style={{ marginLeft: 12 }}>total: {(totalElapsedMs / 1000).toFixed(2)}s</span> : null}
        </div>
      </div>
      {steps.map((step) => {
        const isLlmActive = step.name === 'llm' && (step.status === 'active' || step.status === 'success') && llmText;
        return (
          <div key={step.name}>
            <ChainStepBadge step={step} />
            {isLlmActive ? (
              <div
                class="card"
                style={{
                  marginTop: '-0.3rem',
                  marginBottom: '0.5rem',
                  marginLeft: '1.5rem',
                  padding: '0.6rem 0.85rem',
                  background: 'var(--bg-card-hover)',
                  maxHeight: 220,
                  overflowY: 'auto',
                  fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
                  fontSize: 11,
                  whiteSpace: 'pre-wrap',
                  color: 'var(--text-secondary)',
                }}
              >
                {llmText}
              </div>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
