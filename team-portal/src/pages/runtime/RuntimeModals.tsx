// Three runtime mutation modals colocated by page (state change, request
// approval, create incident). Each is signal-driven open/close per the
// Session 15 pattern. Errors surface raw via a shared actionError signal
// that RuntimePage renders above the KPI row.

import { signal } from '@preact/signals';
import { apiPost } from '../../shared/api/client';
import type {
  RuntimeState, RuntimeEvent, RuntimeApproval, RuntimeIncident,
} from './types';

// Hardcoded actor — five-role auth allowlist in middleware/auth.py. The
// engine writes audit entries with this string; not user-visible.
const ACTOR = 'demo-engineer';

// ===========================================================================
// Shared state
// ===========================================================================

export const runtimeActionError = signal<string | null>(null);

// Reload callback — RuntimePage registers loadAll on mount so child
// components can refresh after a successful POST without circular imports.
type Reloader = () => Promise<void>;
let _reload: Reloader | null = null;
export function registerRuntimeReload(fn: Reloader): void {
  _reload = fn;
}
async function triggerReload(): Promise<void> {
  if (_reload) await _reload();
}

// ===========================================================================
// State change modal (#14) — kill switch / monitoring level / enabled
// ===========================================================================

type StateAction = 'kill-switch' | 'reset-kill-switch' | 'monitoring' | 'enabled';

interface StateChangeArgs {
  system: RuntimeState;
  action: StateAction;
}

const stateChangeOpen = signal<StateChangeArgs | null>(null);
const stateChangeReason = signal<string>('');
const stateChangeLevel = signal<string>('STANDARD');
const stateChangeSaving = signal<boolean>(false);

export function openStateChange(args: StateChangeArgs): void {
  stateChangeOpen.value = args;
  stateChangeReason.value = '';
  stateChangeLevel.value = args.system.monitoring_level || 'STANDARD';
  runtimeActionError.value = null;
}

function closeStateChange(): void {
  stateChangeOpen.value = null;
}

async function saveStateChange(): Promise<void> {
  const args = stateChangeOpen.value;
  if (!args) return;
  stateChangeSaving.value = true;

  const id = encodeURIComponent(args.system.ai_system_id);
  const reason = stateChangeReason.value.trim();
  let path: string;
  let body: Record<string, unknown>;

  switch (args.action) {
    case 'kill-switch':
      if (!reason) { runtimeActionError.value = 'Reason required for kill switch.'; stateChangeSaving.value = false; return; }
      path = `/grc/runtime/v2/state/${id}/kill-switch`;
      body = { actor: ACTOR, reason };
      break;
    case 'reset-kill-switch':
      path = `/grc/runtime/v2/state/${id}/reset-kill-switch`;
      body = { actor: ACTOR, reason: reason || null };
      break;
    case 'monitoring':
      path = `/grc/runtime/v2/state/${id}/monitoring`;
      body = { level: stateChangeLevel.value, actor: ACTOR };
      break;
    case 'enabled':
      path = `/grc/runtime/v2/state/${id}/enabled`;
      body = { enabled: !args.system.enabled, actor: ACTOR, reason: reason || null };
      break;
  }

  const r = await apiPost(path, body);
  stateChangeSaving.value = false;
  if (r.ok) {
    closeStateChange();
    await triggerReload();
  } else {
    runtimeActionError.value = `State change failed: ${r.detail}`;
  }
}

function StateChangeModal() {
  const args = stateChangeOpen.value;
  if (!args) return null;

  const titles: Record<StateAction, string> = {
    'kill-switch': `Engage Kill Switch — ${args.system.ai_system_name}`,
    'reset-kill-switch': `Reset Kill Switch — ${args.system.ai_system_name}`,
    monitoring: `Set Monitoring Level — ${args.system.ai_system_name}`,
    enabled: `${args.system.enabled ? 'Disable' : 'Enable'} — ${args.system.ai_system_name}`,
  };

  const reasonRequired = args.action === 'kill-switch';

  return (
    <div class="modal-overlay" onClick={closeStateChange}>
      <div class="modal" onClick={(e) => e.stopPropagation()}>
        <div class="modal-header">
          <div class="modal-title">{titles[args.action]}</div>
          <button class="btn btn-sm" onClick={closeStateChange}>✕</button>
        </div>
        <div class="modal-body">
          {args.action === 'monitoring' && (
            <div class="form-row">
              <label class="form-label">Level</label>
              <select
                class="form-input"
                value={stateChangeLevel.value}
                onChange={(e) => { stateChangeLevel.value = (e.currentTarget as HTMLSelectElement).value; }}
              >
                <option value="STANDARD">STANDARD</option>
                <option value="HEIGHTENED">HEIGHTENED</option>
                <option value="INCIDENT">INCIDENT</option>
              </select>
            </div>
          )}
          <div class="form-row">
            <label class="form-label">
              Reason {reasonRequired ? <span style={{ color: 'var(--critical)' }}>*</span> : <span class="text-tertiary">(optional)</span>}
            </label>
            <textarea
              class="form-input"
              rows={3}
              value={stateChangeReason.value}
              onInput={(e) => { stateChangeReason.value = (e.currentTarget as HTMLTextAreaElement).value; }}
            />
          </div>
          <div class="text-xs text-tertiary">Actor: {ACTOR}</div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-sm" onClick={closeStateChange}>Cancel</button>
          <button
            class="btn btn-sm btn-primary"
            disabled={stateChangeSaving.value}
            onClick={() => void saveStateChange()}
          >
            {stateChangeSaving.value ? 'Saving…' : 'Confirm'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ===========================================================================
// Request approval modal (#15) — Human Approval Queue + Request button
// ===========================================================================

const requestOpen = signal<boolean>(false);
const requestSystemId = signal<string>('');
const requestDescription = signal<string>('');
const requestRequestedBy = signal<string>(ACTOR);
const requestTtlMinutes = signal<number>(60);
const requestSaving = signal<boolean>(false);

let _systemChoices: { id: string; name: string }[] = [];
export function openRequestApproval(systemChoices: { id: string; name: string }[]): void {
  _systemChoices = systemChoices;
  requestOpen.value = true;
  requestSystemId.value = systemChoices[0]?.id ?? '';
  requestDescription.value = '';
  requestRequestedBy.value = ACTOR;
  requestTtlMinutes.value = 60;
  runtimeActionError.value = null;
}

function closeRequest(): void { requestOpen.value = false; }

async function saveRequest(): Promise<void> {
  if (!requestSystemId.value || !requestDescription.value.trim()) {
    runtimeActionError.value = 'System and description are required.';
    return;
  }
  requestSaving.value = true;
  const r = await apiPost<RuntimeApproval>('/grc/runtime/v2/approvals', {
    ai_system_id: requestSystemId.value,
    action_description: requestDescription.value.trim(),
    requested_by: requestRequestedBy.value.trim() || ACTOR,
    ttl_minutes: requestTtlMinutes.value,
  });
  requestSaving.value = false;
  if (r.ok) {
    closeRequest();
    await triggerReload();
  } else {
    runtimeActionError.value = `Approval request failed: ${r.detail}`;
  }
}

function RequestApprovalModal() {
  if (!requestOpen.value) return null;
  return (
    <div class="modal-overlay" onClick={closeRequest}>
      <div class="modal" onClick={(e) => e.stopPropagation()}>
        <div class="modal-header">
          <div class="modal-title">Request Human Approval</div>
          <button class="btn btn-sm" onClick={closeRequest}>✕</button>
        </div>
        <div class="modal-body">
          <div class="form-row">
            <label class="form-label">AI System</label>
            <select
              class="form-input"
              value={requestSystemId.value}
              onChange={(e) => { requestSystemId.value = (e.currentTarget as HTMLSelectElement).value; }}
            >
              {_systemChoices.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </div>
          <div class="form-row">
            <label class="form-label">Action Description</label>
            <textarea
              class="form-input"
              rows={3}
              value={requestDescription.value}
              onInput={(e) => { requestDescription.value = (e.currentTarget as HTMLTextAreaElement).value; }}
              placeholder="e.g. Authorise tool call to transfer funds &gt; $10k"
            />
          </div>
          <div class="form-row">
            <label class="form-label">Requested By</label>
            <input
              class="form-input"
              value={requestRequestedBy.value}
              onInput={(e) => { requestRequestedBy.value = (e.currentTarget as HTMLInputElement).value; }}
            />
          </div>
          <div class="form-row">
            <label class="form-label">TTL (minutes)</label>
            <input
              class="form-input"
              type="number"
              min={1}
              max={1440}
              value={requestTtlMinutes.value}
              onInput={(e) => { requestTtlMinutes.value = Number((e.currentTarget as HTMLInputElement).value) || 60; }}
            />
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-sm" onClick={closeRequest}>Cancel</button>
          <button
            class="btn btn-sm btn-primary"
            disabled={requestSaving.value}
            onClick={() => void saveRequest()}
          >
            {requestSaving.value ? 'Saving…' : 'Submit'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ===========================================================================
// Create incident modal (#16) — pre-filled from an event row
// ===========================================================================

const incidentEvent = signal<RuntimeEvent | null>(null);
const incidentSeverity = signal<string>('HIGH');
const incidentSummary = signal<string>('');
const incidentOwner = signal<string>(ACTOR);
const incidentSaving = signal<boolean>(false);

export function openCreateIncident(ev: RuntimeEvent): void {
  incidentEvent.value = ev;
  incidentSeverity.value = ev.severity === 'INFO' || ev.severity === 'LOW' ? 'MEDIUM' : ev.severity;
  incidentSummary.value = `${ev.event_type.replace(/_/g, ' ')} — ${ev.details}`.slice(0, 200);
  incidentOwner.value = ACTOR;
  runtimeActionError.value = null;
}

function closeIncident(): void { incidentEvent.value = null; }

async function saveIncident(): Promise<void> {
  const ev = incidentEvent.value;
  if (!ev) return;
  if (!incidentSummary.value.trim()) {
    runtimeActionError.value = 'Incident summary is required.';
    return;
  }
  incidentSaving.value = true;
  const r = await apiPost<RuntimeIncident>('/grc/runtime/v2/incidents', {
    ai_system_id: ev.ai_system_id,
    severity: incidentSeverity.value,
    summary: incidentSummary.value.trim(),
    owner: incidentOwner.value.trim() || ACTOR,
    actor: ACTOR,
    from_event_id: ev.id,
  });
  incidentSaving.value = false;
  if (r.ok) {
    closeIncident();
    await triggerReload();
  } else {
    runtimeActionError.value = `Incident creation failed: ${r.detail}`;
  }
}

function CreateIncidentModal() {
  const ev = incidentEvent.value;
  if (!ev) return null;
  return (
    <div class="modal-overlay" onClick={closeIncident}>
      <div class="modal" onClick={(e) => e.stopPropagation()}>
        <div class="modal-header">
          <div class="modal-title">Create Incident from Event</div>
          <button class="btn btn-sm" onClick={closeIncident}>✕</button>
        </div>
        <div class="modal-body">
          <div class="text-xs text-tertiary" style={{ marginBottom: 8 }}>
            From event <span class="font-mono">{ev.id}</span> · {ev.ai_system_id} · {ev.source}
          </div>
          <div class="form-row">
            <label class="form-label">Severity</label>
            <select
              class="form-input"
              value={incidentSeverity.value}
              onChange={(e) => { incidentSeverity.value = (e.currentTarget as HTMLSelectElement).value; }}
            >
              <option value="CRITICAL">CRITICAL</option>
              <option value="HIGH">HIGH</option>
              <option value="MEDIUM">MEDIUM</option>
              <option value="LOW">LOW</option>
            </select>
          </div>
          <div class="form-row">
            <label class="form-label">Summary</label>
            <textarea
              class="form-input"
              rows={3}
              value={incidentSummary.value}
              onInput={(e) => { incidentSummary.value = (e.currentTarget as HTMLTextAreaElement).value; }}
            />
          </div>
          <div class="form-row">
            <label class="form-label">Owner</label>
            <input
              class="form-input"
              value={incidentOwner.value}
              onInput={(e) => { incidentOwner.value = (e.currentTarget as HTMLInputElement).value; }}
            />
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-sm" onClick={closeIncident}>Cancel</button>
          <button
            class="btn btn-sm btn-primary"
            disabled={incidentSaving.value}
            onClick={() => void saveIncident()}
          >
            {incidentSaving.value ? 'Creating…' : 'Create Incident'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ===========================================================================
// Mount point
// ===========================================================================

export function RuntimeModals() {
  return (
    <>
      <StateChangeModal />
      <RequestApprovalModal />
      <CreateIncidentModal />
    </>
  );
}
