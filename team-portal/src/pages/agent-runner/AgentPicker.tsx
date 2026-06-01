import type { RegistryAgent } from './types';

interface Props {
  agents: RegistryAgent[];
  selectedAgentId: string;
  onSelect: (agentId: string) => void;
  loading: boolean;
  loadError: string | null;
  disabled: boolean;
}

export function AgentPicker({ agents, selectedAgentId, onSelect, loading, loadError, disabled }: Props) {
  if (loading) return <div class="text-xs text-tertiary">Loading agents…</div>;
  if (loadError) return <div class="text-xs" style={{ color: 'var(--critical)' }}>Failed to load agents: {loadError}</div>;
  if (agents.length === 0) return <div class="text-xs text-tertiary">No agents registered.</div>;

  return (
    <div>
      <label class="text-xs text-tertiary" style={{ display: 'block', marginBottom: '0.3rem' }}>
        Agent
      </label>
      <select
        class="form-input"
        value={selectedAgentId}
        disabled={disabled}
        onChange={(e) => onSelect((e.target as HTMLSelectElement).value)}
        style={{ width: '100%', padding: '0.5rem', background: 'var(--bg-card-hover)', color: 'var(--text-primary)', border: '1px solid var(--border)', borderRadius: 4 }}
      >
        {agents.map((a) => (
          <option
            key={a.agent_id}
            value={a.agent_id}
            disabled={a.cli_only}
            title={a.cli_only ? 'CLI-only agent — not invocable from the runner UI yet.' : a.description}
          >
            {a.name}{a.cli_only ? ' (CLI only)' : ''} — {a.agent_id}
          </option>
        ))}
      </select>
      {selectedAgentId ? (
        <div class="text-xs text-tertiary" style={{ marginTop: '0.4rem' }}>
          {agents.find((a) => a.agent_id === selectedAgentId)?.description ?? ''}
        </div>
      ) : null}
    </div>
  );
}
