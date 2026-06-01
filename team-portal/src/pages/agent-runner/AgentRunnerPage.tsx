import { signal, computed } from '@preact/signals';
import { useEffect } from 'preact/hooks';
import { listAgents, runAgent } from './api';
import type {
  ChainEvent,
  RegistryAgent,
  StepName,
  StepState,
} from './types';
import { AgentPicker } from './AgentPicker';
import { ChainTicker, buildInitialSteps, STEP_ORDER } from './ChainTicker';

const SEED_PROMPT = 'Review the portfolio for client cln-001. Identify the dominant risk and recommend 2-3 specific rebalancing actions.';

const agents = signal<RegistryAgent[]>([]);
const agentsLoading = signal<boolean>(true);
const agentsError = signal<string | null>(null);

const selectedAgentId = signal<string>('');
const prompt = signal<string>(SEED_PROMPT);
const systemIdOverride = signal<string>('');

const steps = signal<StepState[]>(buildInitialSteps());
const runId = signal<string | null>(null);
const totalElapsedMs = signal<number | null>(null);
const llmText = signal<string>('');
const running = signal<boolean>(false);
const connectionBanner = signal<string | null>(null);
const finalOutcome = signal<string | null>(null);
// True once we've received chain.done or chain.error from the engine.
// fetchEventSource fires `onerror` even on a clean server EOF after the
// terminal SSE event — without this guard the SPA shows "Connection lost"
// on a run that actually completed. See client.ts:159-164 + the S82f-2
// vendor_risk demo path where 50s runs were reaching Done but the banner
// still fired.
const terminalEventSeen = signal<boolean>(false);

const canRun = computed(() =>
  !running.value &&
  selectedAgentId.value !== '' &&
  prompt.value.trim().length > 0,
);

async function loadAgents(): Promise<void> {
  agentsLoading.value = true;
  agentsError.value = null;
  const res = await listAgents();
  agentsLoading.value = false;
  if (!res.ok) {
    agentsError.value = res.detail;
    return;
  }
  const list = res.data.agents ?? [];
  agents.value = list;
  if (!selectedAgentId.value) {
    const firstInvocable = list.find((a) => !a.cli_only);
    if (firstInvocable) selectedAgentId.value = firstInvocable.agent_id;
  }
}

function resetForRun(): void {
  steps.value = buildInitialSteps();
  runId.value = null;
  totalElapsedMs.value = null;
  llmText.value = '';
  connectionBanner.value = null;
  finalOutcome.value = null;
  terminalEventSeen.value = false;
}

function patchStep(name: StepName, patch: Partial<StepState>): void {
  steps.value = steps.value.map((s) => (s.name === name ? { ...s, ...patch } : s));
}

function markActiveNext(currentName: StepName): void {
  const idx = STEP_ORDER.indexOf(currentName);
  if (idx === -1 || idx === STEP_ORDER.length - 1) return;
  const nextName = STEP_ORDER[idx + 1];
  steps.value = steps.value.map((s) =>
    s.name === nextName && s.status === 'pending' ? { ...s, status: 'active' } : s,
  );
}

function applyEvent(evt: ChainEvent): void {
  switch (evt.event) {
    case 'chain.start':
      runId.value = evt.run_id;
      patchStep('policy_gate', { status: 'active' });
      return;
    case 'policy_gate': {
      const status = evt.decision === 'ALLOW' ? 'success' : evt.decision === 'REVIEW' ? 'review' : 'denied';
      patchStep('policy_gate', {
        status,
        elapsed_ms: evt.elapsed_ms,
        detail: `${evt.decision} · ${evt.rule}`,
        payload: evt,
      });
      if (status === 'success') markActiveNext('policy_gate');
      return;
    }
    case 'scrub_pii':
      patchStep('scrub_pii', {
        status: 'success',
        elapsed_ms: evt.elapsed_ms,
        detail: `${evt.redacted_count} redacted${evt.redacted_field_types.length ? ` · ${evt.redacted_field_types.join(', ')}` : ''}`,
        payload: evt,
      });
      markActiveNext('scrub_pii');
      return;
    case 'guardrails': {
      const status = evt.passed ? 'success' : 'blocked';
      patchStep('guardrails', {
        status,
        elapsed_ms: evt.elapsed_ms,
        detail: evt.passed
          ? `pass · injection=${evt.injection_score ?? 'n/a'}`
          : `BLOCK · ${evt.violations.join(', ') || 'violation'}`,
        payload: evt,
      });
      if (status === 'success') markActiveNext('guardrails');
      return;
    }
    case 'llm.delta':
      patchStep('llm', { status: 'active' });
      llmText.value = llmText.value + evt.text;
      return;
    case 'llm.done':
      patchStep('llm', {
        status: 'success',
        elapsed_ms: evt.elapsed_ms,
        detail: `${evt.model} · ${evt.turns} turns · in ${evt.input_tokens} / out ${evt.output_tokens}`,
        payload: evt,
      });
      markActiveNext('llm');
      return;
    case 'evaluate':
      patchStep('evaluate', {
        status: 'success',
        elapsed_ms: evt.elapsed_ms,
        detail: evt.deferred_to_s85
          ? 'deferred to S85'
          : `avg=${evt.avg_score ?? 'n/a'} · ${evt.scored_metric_count} metrics`,
        payload: evt,
      });
      markActiveNext('evaluate');
      return;
    case 'memory':
      patchStep('memory', {
        status: evt.outcome === 'success' ? 'success' : evt.outcome === 'review' ? 'review' : 'error',
        elapsed_ms: evt.elapsed_ms,
        detail: evt.episode_id ? `episode ${evt.episode_id.slice(0, 8)}…` : '(no episode)',
        payload: evt,
      });
      markActiveNext('memory');
      return;
    case 'audit':
      patchStep('audit', {
        status: evt.decision === 'BLOCKED' ? 'blocked' : 'success',
        elapsed_ms: evt.elapsed_ms,
        detail: `${evt.decision}${evt.audit_id ? ` · ${evt.audit_id}` : ''}`,
        payload: evt,
      });
      markActiveNext('audit');
      return;
    case 'chain.done':
      terminalEventSeen.value = true;
      totalElapsedMs.value = evt.total_elapsed_ms;
      finalOutcome.value = evt.outcome;
      patchStep('done', {
        status: evt.outcome === 'success' ? 'success'
          : evt.outcome === 'denied' ? 'denied'
          : evt.outcome === 'guardrail_block' ? 'blocked'
          : evt.outcome === 'review' ? 'review'
          : 'error',
        elapsed_ms: evt.total_elapsed_ms,
        detail: evt.terminal_reason ?? evt.outcome,
        payload: evt,
      });
      return;
    case 'chain.error':
      terminalEventSeen.value = true;
      steps.value = steps.value.map((s) =>
        s.status === 'active' ? { ...s, status: 'error', detail: `${evt.error_type}: ${evt.message}` } : s,
      );
      return;
  }
}

async function onRun(): Promise<void> {
  if (!canRun.value) return;
  running.value = true;
  resetForRun();
  const selected = agents.value.find((a) => a.agent_id === selectedAgentId.value);
  const systemId = systemIdOverride.value.trim() || selected?.default_system_id;
  const reqBody: import('./types').RunRequest = {
    agent_id: selectedAgentId.value,
    prompt: prompt.value,
  };
  if (systemId) reqBody.system_id = systemId;
  try {
    await runAgent(
      reqBody,
      {
        onEvent: (evt) => applyEvent(evt),
        onError: (err) => {
          // Suppress the banner when the chain already reached its terminal
          // event — fetchEventSource fires onerror on the engine's normal
          // stream close (treated as "unexpected EOF") even though the run
          // completed successfully. Real errors before chain.done/chain.error
          // still surface the banner.
          if (terminalEventSeen.value) return;
          const msg = err instanceof Error ? err.message : String(err);
          connectionBanner.value = `Connection lost — start a new run. (${msg})`;
        },
        onClose: () => {
          running.value = false;
        },
      },
    );
  } catch {
    running.value = false;
  }
}

export function AgentRunnerPage() {
  useEffect(() => {
    void loadAgents();
  }, []);

  return (
    <div style={{ padding: '1.5rem', maxWidth: 1280 }}>
      <div style={{ marginBottom: '1.25rem' }}>
        <h1 style={{ fontSize: 20, fontWeight: 700, margin: 0 }}>Agent Runner</h1>
        <div class="text-xs text-tertiary" style={{ marginTop: '0.3rem' }}>
          Run a governed agent end-to-end. The 8-step chain ticker shows each control as it fires.
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '380px 1fr', gap: '1.5rem' }}>
        {/* Left: controls */}
        <div class="card" style={{ padding: '1rem', alignSelf: 'start' }}>
          <AgentPicker
            agents={agents.value}
            selectedAgentId={selectedAgentId.value}
            onSelect={(id) => { selectedAgentId.value = id; }}
            loading={agentsLoading.value}
            loadError={agentsError.value}
            disabled={running.value}
          />

          <div style={{ marginTop: '1rem' }}>
            <label class="text-xs text-tertiary" style={{ display: 'block', marginBottom: '0.3rem' }}>
              Prompt
            </label>
            <textarea
              value={prompt.value}
              disabled={running.value}
              onInput={(e) => { prompt.value = (e.target as HTMLTextAreaElement).value; }}
              rows={6}
              style={{
                width: '100%', padding: '0.5rem', background: 'var(--bg-card-hover)',
                color: 'var(--text-primary)', border: '1px solid var(--border)',
                borderRadius: 4, fontSize: 12, fontFamily: 'inherit', resize: 'vertical',
              }}
            />
          </div>

          <div style={{ marginTop: '1rem' }}>
            <label class="text-xs text-tertiary" style={{ display: 'block', marginBottom: '0.3rem' }}>
              System ID override <span style={{ opacity: 0.6 }}>(optional)</span>
            </label>
            <input
              type="text"
              value={systemIdOverride.value}
              disabled={running.value}
              placeholder="defaults to agent's default_system_id"
              onInput={(e) => { systemIdOverride.value = (e.target as HTMLInputElement).value; }}
              style={{
                width: '100%', padding: '0.5rem', background: 'var(--bg-card-hover)',
                color: 'var(--text-primary)', border: '1px solid var(--border)',
                borderRadius: 4, fontSize: 12,
              }}
            />
          </div>

          <button
            class="btn btn-primary"
            disabled={!canRun.value}
            onClick={() => { void onRun(); }}
            style={{ marginTop: '1rem', width: '100%', padding: '0.6rem' }}
          >
            {running.value ? 'Running…' : 'Run agent'}
          </button>

          {connectionBanner.value ? (
            <div
              class="card"
              style={{
                marginTop: '0.8rem', padding: '0.6rem', borderLeft: '3px solid var(--critical)',
                fontSize: 11, color: 'var(--text-secondary)',
              }}
            >
              {connectionBanner.value}
            </div>
          ) : null}

          {finalOutcome.value && !connectionBanner.value ? (
            <div
              class="card"
              style={{
                marginTop: '0.8rem', padding: '0.6rem',
                borderLeft: `3px solid var(--${finalOutcome.value === 'success' ? 'pass' : finalOutcome.value === 'review' ? 'medium' : 'critical'})`,
                fontSize: 11, color: 'var(--text-secondary)',
              }}
            >
              Outcome: <strong>{finalOutcome.value}</strong>
            </div>
          ) : null}
        </div>

        {/* Right: chain ticker */}
        <div class="card" style={{ padding: '1rem' }}>
          <ChainTicker
            steps={steps.value}
            llmText={llmText.value}
            runId={runId.value}
            totalElapsedMs={totalElapsedMs.value}
          />
        </div>
      </div>
    </div>
  );
}
