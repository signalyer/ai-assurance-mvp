import type { RuntimeState } from './types';

interface Props {
  items: RuntimeState[];
}

/**
 * Read-only system state cards. Action buttons (kill switch, monitoring,
 * enable/disable) are disabled with "deferred" titles — wired in a
 * follow-up task per the lean-cut pattern.
 */
export function SystemStates({ items }: Props) {
  if (items.length === 0) return <div class="empty-state">No systems registered.</div>;

  return (
    <>
      {items.map((s) => {
        const cls = s.kill_switch_engaged ? 'killed'
          : s.monitoring_level === 'HEIGHTENED' ? 'heightened'
          : '';
        const lightCls = s.kill_switch_engaged ? 'red'
          : s.enabled ? 'green'
          : 'amber';
        const statusLabel = s.kill_switch_engaged ? 'KILLED'
          : s.enabled ? 'Enabled'
          : 'Disabled';
        return (
          <div key={s.ai_system_id} class={`sys-state-card ${cls}`}>
            <div>
              <div class="text-sm font-bold">
                <span class={`light ${lightCls}`} />
                {s.ai_system_name}
              </div>
              <div class="text-xs text-tertiary">{s.ai_system_id}</div>
            </div>
            <div>
              <div class="text-xs text-secondary">Status</div>
              <div class="text-sm font-bold">{statusLabel}</div>
            </div>
            <div>
              <div class="text-xs text-secondary">Monitoring</div>
              <div class="text-sm">{s.monitoring_level}</div>
            </div>
            <div style={{ display: 'flex', gap: 4, justifyContent: 'flex-end', flexWrap: 'wrap' }}>
              <button class="btn btn-sm" disabled title="Pending Phase 2 follow-up">
                {s.kill_switch_engaged ? 'Reset Kill' : 'Kill Switch'}
              </button>
              <button class="btn btn-sm" disabled title="Pending Phase 2 follow-up">Monitoring</button>
              <button class="btn btn-sm" disabled title="Pending Phase 2 follow-up">
                {s.enabled ? 'Disable' : 'Enable'}
              </button>
            </div>
          </div>
        );
      })}
    </>
  );
}
