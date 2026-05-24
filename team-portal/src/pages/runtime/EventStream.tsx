import type { RuntimeEvent } from './types';
import { openCreateIncident } from './RuntimeModals';

interface Props {
  events: RuntimeEvent[];
  loading: boolean;
}

const SEVERITY_BADGE: Record<string, string> = {
  CRITICAL: 'badge-critical',
  HIGH: 'badge-high',
  MEDIUM: 'badge-medium',
  LOW: 'badge-neutral',
  INFO: 'badge-neutral',
};

export function EventStream({ events, loading }: Props) {
  return (
    <div class="ev-table">
      <div class="ev-row head">
        <div>Timestamp</div>
        <div>Source</div>
        <div>Event / Details</div>
        <div>System</div>
        <div>Severity</div>
        <div>Action</div>
        <div>Policy / Control</div>
        <div>Evidence</div>
      </div>
      {loading && <div class="loading" style={{ padding: '1rem' }}>Loading…</div>}
      {!loading && events.length === 0 && (
        <div class="empty-state" style={{ padding: '1.5rem' }}>No events match.</div>
      )}
      {!loading && events.map((e) => {
        const ts = e.timestamp ?? '';
        const sevCls = SEVERITY_BADGE[e.severity] ?? 'badge-neutral';
        return (
          <div
            key={e.id}
            class={`ev-row sev-${e.severity}`}
            style={{ cursor: 'pointer' }}
            title="Click to create an incident from this event"
            onClick={() => openCreateIncident(e)}
          >
            <div class="text-xs text-tertiary">
              {ts.slice(11, 19)}
              <br />
              <span class="text-tertiary">{ts.slice(0, 10)}</span>
            </div>
            <div><span class="src-pill">{e.source}</span></div>
            <div>
              <div class="text-sm font-bold">{e.event_type.replace(/_/g, ' ')}</div>
              <div class="text-xs text-tertiary">{e.details}</div>
            </div>
            <div class="text-xs">{e.ai_system_id}</div>
            <div><span class={`badge ${sevCls}`}>{e.severity}</span></div>
            <div><span class={`action-pill action-${e.action_taken}`}>{e.action_taken}</span></div>
            <div class="text-xs">
              {e.policy_triggered ? <span class="badge badge-info">{e.policy_triggered}</span> : '—'}
              {e.linked_framework && (
                <div class="text-tertiary" style={{ fontSize: 10, marginTop: 4 }}>{e.linked_framework}</div>
              )}
            </div>
            <div class="text-xs text-tertiary" style={{ textAlign: 'right' }}>
              {e.evidence_id ? <a href="/evidence">{e.evidence_id}</a> : '—'}
            </div>
          </div>
        );
      })}
    </div>
  );
}
