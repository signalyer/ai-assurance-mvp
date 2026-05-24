import { useEffect } from 'preact/hooks';
import { signal } from '@preact/signals';
import { apiGet } from '../../shared/api/client';
import { SeverityBadge, DecisionBadge, RuntimeStatusDot } from '../../shared/components/Badges';
import { openEdit, registerEditSavedCallback } from './AiSystemEditModal';
import { openRevisions } from './AiSystemRevisionsPanel';
import type { AiSystemDetail, EditStatus } from './types';

// Open-system signal: drives the side drawer.
// Setting to a non-null id triggers a fetch; null closes the drawer.
const openSystemId = signal<string | null>(null);
const currentSystem = signal<AiSystemDetail | null>(null);
const drawerError = signal<string | null>(null);
const editStatus = signal<EditStatus | null>(null);

// Edit modal calls back here on successful save so the drawer + status banner
// reflect the new state without a page reload.
registerEditSavedCallback((id: string) => {
  if (openSystemId.value === id) void loadDetail(id);
});

export function openSystem(id: string): void {
  openSystemId.value = id;
  const url = new URL(window.location.href);
  url.searchParams.set('id', id);
  window.history.replaceState({}, '', url.toString());
}

export function closeSystem(): void {
  openSystemId.value = null;
  currentSystem.value = null;
  drawerError.value = null;
  const url = new URL(window.location.href);
  url.searchParams.delete('id');
  window.history.replaceState({}, '', url.toString());
}

async function loadDetail(id: string): Promise<void> {
  drawerError.value = null;
  currentSystem.value = null;
  editStatus.value = null;
  const [detail, info] = await Promise.all([
    apiGet<AiSystemDetail>(`/grc/ai-systems/${encodeURIComponent(id)}`),
    apiGet<{ status: EditStatus }>(`/ai-systems/${encodeURIComponent(id)}/edit-info`),
  ]);
  if (detail.ok) {
    currentSystem.value = detail.data;
  } else {
    drawerError.value = detail.detail;
  }
  if (info.ok) editStatus.value = info.data.status;
  // edit-info is best-effort enrichment; silent on failure (banner is optional).
}

export function AiSystemDrawer() {
  const id = openSystemId.value;

  useEffect(() => {
    if (id) void loadDetail(id);
  }, [id]);

  const isOpen = id !== null;
  const s = currentSystem.value;

  return (
    <>
      <div class={`drawer-overlay ${isOpen ? 'open' : ''}`} onClick={closeSystem} />
      <aside class={`drawer ${isOpen ? 'open' : ''}`} aria-hidden={!isOpen}>
        <div class="drawer-header">
          <div class="drawer-title">{s?.name ?? 'System Details'}</div>
          <button class="drawer-close" onClick={closeSystem} aria-label="Close">×</button>
        </div>
        <div class="drawer-body">
          {drawerError.value && <div class="error-banner">{drawerError.value}</div>}
          {!s && !drawerError.value && <div class="loading">Loading…</div>}
          {s && editStatus.value?.has_pending_material && (
            <div class="error-banner" style={{ marginBottom: 12 }}>
              Material revision pending ({editStatus.value.pending_revision_id}) — release is blocked.
            </div>
          )}
          {s && <DrawerContent system={s} />}
        </div>
      </aside>
    </>
  );
}

function DrawerContent({ system: s }: { system: AiSystemDetail }) {
  const openFindings = s.findings.filter(
    (f) => f.status === 'OPEN' || f.status === 'IN_PROGRESS',
  );

  return (
    <>
      <div class="drawer-section">
        <div style={{ display: 'flex', gap: 6, marginBottom: 12, flexWrap: 'wrap' }}>
          <SeverityBadge value={s.risk_level} />
          <DecisionBadge value={s.release_decision} />
          <RuntimeStatusDot value={s.runtime_status} />
        </div>
        <div class="text-sm text-secondary">{s.description}</div>
      </div>

      <div class="drawer-section">
        <div class="drawer-section-title">System Details</div>
        <dl class="def-list">
          <dt>ID</dt><dd class="font-mono">{s.id}</dd>
          <dt>Business Owner</dt><dd>{s.business_owner}</dd>
          {s.technical_owner && <><dt>Technical Owner</dt><dd>{s.technical_owner}</dd></>}
          <dt>Domain</dt><dd>{s.domain}</dd>
          <dt>Use Case</dt><dd>{s.use_case}</dd>
          <dt>Model</dt><dd class="font-mono">{s.model}</dd>
          <dt>Autonomy</dt><dd>{s.autonomy_level}</dd>
          <dt>HITL</dt><dd>{s.human_oversight}</dd>
          <dt>Deployment</dt><dd>{s.deployment_target}</dd>
          <dt>Data Residency</dt><dd>{s.data_residency}</dd>
          <dt>Trust Boundary</dt><dd>{s.trust_boundaries}</dd>
        </dl>
      </div>

      <div class="drawer-section">
        <div class="drawer-section-title">Data Classes Handled</div>
        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
          {s.data_classes.map((d) => (
            <span key={d} class="badge badge-info">{d}</span>
          ))}
        </div>
      </div>

      {s.release_gates && (
        <div class="drawer-section">
          <div class="drawer-section-title">Release Gate Status</div>
          <div class="text-sm" style={{ marginBottom: 8 }}>
            <strong>
              {s.release_gates.gates.filter((g) => g.passed).length}/{s.release_gates.gates.length} gates passing
            </strong>
            {' · approved by '}{s.release_gates.approver}
          </div>
          {s.release_gates.gates.filter((g) => !g.passed).map((g) => (
            <div
              key={g.id}
              class="text-xs"
              style={{
                padding: '0.5rem',
                background: 'var(--critical-bg)',
                border: '1px solid rgba(239,68,68,0.3)',
                borderRadius: 4,
                marginBottom: 6,
              }}
            >
              <span class="font-mono text-critical">{g.id}</span> {g.note ?? g.actual}
            </div>
          ))}
        </div>
      )}

      <div class="drawer-section">
        <div class="drawer-section-title">Open Findings ({openFindings.length})</div>
        {openFindings.length === 0 && (
          <div class="text-xs text-tertiary">No open findings.</div>
        )}
        {openFindings.slice(0, 5).map((f) => (
          <div
            key={f.id}
            style={{
              padding: '0.5rem',
              border: '1px solid var(--border)',
              borderRadius: 4,
              marginBottom: 6,
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span class="font-mono text-xs">{f.id}</span>
              <SeverityBadge value={f.severity} />
            </div>
            <div class="text-sm" style={{ marginTop: 4 }}>{f.title}</div>
          </div>
        ))}
      </div>

      <div class="drawer-section">
        <div class="drawer-section-title">Last Assessment</div>
        <div class="text-sm">{s.last_assessment} · next {s.next_assessment}</div>
      </div>

      <div class="drawer-section" style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <a class="btn btn-sm btn-primary" href={`/assessment?system=${encodeURIComponent(s.id)}`}>
          Run Assessment
        </a>
        {/* #9/#10 wired. #11 Frameworks + #12 Bound Agents pending follow-ups. */}
        <button class="btn btn-sm btn-secondary" onClick={() => openEdit(s.id)}>Edit System</button>
        <button class="btn btn-sm btn-secondary" onClick={() => openRevisions(s.id)}>
          Revision History{editStatus.value && editStatus.value.revision_count > 0 ? ` (${editStatus.value.revision_count})` : ''}
        </button>
        <button class="btn btn-sm btn-secondary" disabled title="Pending Phase 2 follow-up">Frameworks</button>
        <button class="btn btn-sm btn-secondary" disabled title="Pending Phase 2 follow-up">Bound Agents</button>
      </div>
    </>
  );
}
