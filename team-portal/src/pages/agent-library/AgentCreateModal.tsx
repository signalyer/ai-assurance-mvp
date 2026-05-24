// + Register Agent modal (#20). POST /api/agents.

import { signal } from '@preact/signals';
import { apiPost } from '../../shared/api/client';
import type { AgentSummary } from './types';

const open = signal<boolean>(false);
const name = signal<string>('');
const team = signal<string>('');
const description = signal<string>('');
const ownerType = signal<'CUSTOM' | 'REUSABLE'>('CUSTOM');
const inherentRisk = signal<'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'>('MEDIUM');
const saving = signal<boolean>(false);
const error = signal<string | null>(null);

type Reloader = () => Promise<void>;
let _reload: Reloader | null = null;
export function registerAgentsReload(fn: Reloader): void { _reload = fn; }

export function openCreateAgent(): void {
  open.value = true;
  name.value = '';
  team.value = '';
  description.value = '';
  ownerType.value = 'CUSTOM';
  inherentRisk.value = 'MEDIUM';
  error.value = null;
}

function close(): void { open.value = false; }

async function save(): Promise<void> {
  if (!name.value.trim() || !team.value.trim()) {
    error.value = 'Name and team are required.';
    return;
  }
  saving.value = true;
  const r = await apiPost<AgentSummary>('/agents', {
    name: name.value.trim(),
    description: description.value.trim(),
    team: team.value.trim(),
    owner_type: ownerType.value,
    inherent_risk: inherentRisk.value,
  });
  saving.value = false;
  if (r.ok) {
    close();
    if (_reload) await _reload();
  } else {
    error.value = `Create failed: ${r.detail}`;
  }
}

export function AgentCreateModal() {
  if (!open.value) return null;
  return (
    <div class="modal-overlay open" onClick={(e) => { if (e.target === e.currentTarget) close(); }}>
      <div class="modal">
        <div class="modal-header">
          <div class="modal-title">Register New Agent</div>
          <button class="modal-close" onClick={close}>×</button>
        </div>
        <div class="modal-body">
          {error.value && <div class="error-banner">{error.value}</div>}
          <div class="form-row">
            <label class="form-label">Name <span style={{ color: 'var(--critical)' }}>*</span></label>
            <input
              class="form-input"
              value={name.value}
              onInput={(e) => { name.value = (e.currentTarget as HTMLInputElement).value; }}
            />
          </div>
          <div class="form-row">
            <label class="form-label">Team <span style={{ color: 'var(--critical)' }}>*</span></label>
            <input
              class="form-input"
              value={team.value}
              onInput={(e) => { team.value = (e.currentTarget as HTMLInputElement).value; }}
            />
          </div>
          <div class="form-row">
            <label class="form-label">Description</label>
            <textarea
              class="form-input"
              rows={3}
              value={description.value}
              onInput={(e) => { description.value = (e.currentTarget as HTMLTextAreaElement).value; }}
            />
          </div>
          <div class="form-row">
            <label class="form-label">Owner Type</label>
            <select
              class="form-input"
              value={ownerType.value}
              onChange={(e) => { ownerType.value = (e.currentTarget as HTMLSelectElement).value as 'CUSTOM' | 'REUSABLE'; }}
            >
              <option value="CUSTOM">CUSTOM</option>
              <option value="REUSABLE">REUSABLE</option>
            </select>
          </div>
          <div class="form-row">
            <label class="form-label">Inherent Risk</label>
            <select
              class="form-input"
              value={inherentRisk.value}
              onChange={(e) => { inherentRisk.value = (e.currentTarget as HTMLSelectElement).value as 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'; }}
            >
              <option value="LOW">LOW</option>
              <option value="MEDIUM">MEDIUM</option>
              <option value="HIGH">HIGH</option>
              <option value="CRITICAL">CRITICAL</option>
            </select>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-sm" onClick={close}>Cancel</button>
          <button class="btn btn-sm btn-primary" disabled={saving.value} onClick={() => void save()}>
            {saving.value ? 'Saving…' : 'Register'}
          </button>
        </div>
      </div>
    </div>
  );
}
