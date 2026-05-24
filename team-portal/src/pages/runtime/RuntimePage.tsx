import { signal, computed } from '@preact/signals';
import { useEffect } from 'preact/hooks';
import { apiGet } from '../../shared/api/client';
import type { AiSystemsListResponse } from '../ai-systems/types';
import type {
  RuntimeEvent, RuntimeApproval, RuntimeIncident, RuntimeState, RuntimeConnector,
  EventsResponse, ApprovalsResponse, IncidentsResponse, StatesResponse, ConnectorsResponse,
} from './types';
import { EventStream } from './EventStream';
import { SystemStates } from './SystemStates';
import {
  RuntimeModals, runtimeActionError, registerRuntimeReload, openRequestApproval,
} from './RuntimeModals';

const SOURCES = [
  'Langfuse', 'AWS CloudTrail', 'AWS Security Hub', 'AWS GuardDuty', 'AWS Macie',
  'AWS Bedrock Guardrails', 'NeMo Guardrails', 'Lakera (placeholder)',
  'Custom Tool Gateway', 'Custom AI Gateway', 'Internal',
];

const scope = signal<string>('ALL');
const sourceFilter = signal<string>('');
const aiSystems = signal<{ id: string; name: string }[]>([]);
const events = signal<RuntimeEvent[]>([]);
const approvals = signal<RuntimeApproval[]>([]);
const incidents = signal<RuntimeIncident[]>([]);
const states = signal<RuntimeState[]>([]);
const connectors = signal<RuntimeConnector[]>([]);
const loadError = signal<string | null>(null);
const loading = signal<boolean>(true);

const kpis = computed(() => {
  const ev = events.value;
  const blocked = ev.filter((e) =>
    ['blocked', 'refused', 'halted', 'masked'].includes(e.action_taken),
  ).length;
  const killed = states.value.filter((s) => s.kill_switch_engaged).length;
  const pendingApprovals = approvals.value.filter((a) => a.status === 'PENDING').length;
  const openIncidents = incidents.value.filter(
    (i) => i.status === 'OPEN' || i.status === 'INVESTIGATING',
  ).length;
  return { total: ev.length, blocked, killed, pendingApprovals, openIncidents };
});

async function loadAll(): Promise<void> {
  loading.value = true;
  loadError.value = null;
  const qs: Record<string, string | number> = { limit: 60, scope: scope.value };
  if (sourceFilter.value) qs.source = sourceFilter.value;
  const [evR, apR, incR, stR, conR, sysR] = await Promise.all([
    apiGet<EventsResponse>('/grc/runtime/v2/events', qs),
    apiGet<ApprovalsResponse>('/grc/runtime/v2/approvals'),
    apiGet<IncidentsResponse>('/grc/runtime/v2/incidents'),
    apiGet<StatesResponse>('/grc/runtime/v2/state'),
    apiGet<ConnectorsResponse>('/grc/runtime/v2/connectors'),
    apiGet<AiSystemsListResponse>('/grc/ai-systems'),
  ]);
  if (evR.ok) events.value = evR.data.events ?? [];
  if (apR.ok) approvals.value = apR.data.approvals ?? [];
  if (incR.ok) incidents.value = incR.data.incidents ?? [];
  if (stR.ok) states.value = stR.data.states ?? [];
  if (conR.ok) connectors.value = conR.data.connectors ?? [];
  if (sysR.ok) {
    aiSystems.value = (sysR.data.systems ?? []).map((s) => ({ id: s.id, name: s.name }));
  }
  if (!evR.ok) loadError.value = evR.detail;
  loading.value = false;
}

export function RuntimePage() {
  useEffect(() => {
    registerRuntimeReload(loadAll);
    void loadAll();
  }, []);

  return (
    <div>
      <div class="page-header">
        <div>
          <div class="page-title">Runtime Governance &amp; Telemetry</div>
          <div class="page-subtitle">
            Live event stream from Langfuse, AWS, guardrails, and policy gateways · system kill switches, approvals, incidents
          </div>
        </div>
        <div class="page-actions">
          <select
            class="filter-select"
            value={scope.value}
            onChange={(e) => {
              scope.value = (e.currentTarget as HTMLSelectElement).value;
              void loadAll();
            }}
          >
            <option value="ALL">All AI Systems</option>
            {aiSystems.value.map((s) => (
              <option key={s.id} value={s.id}>{s.name}</option>
            ))}
          </select>
          <select
            class="filter-select"
            value={sourceFilter.value}
            onChange={(e) => {
              sourceFilter.value = (e.currentTarget as HTMLSelectElement).value;
              void loadAll();
            }}
          >
            <option value="">All Sources</option>
            {SOURCES.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <button class="btn btn-sm" onClick={() => void loadAll()}>Refresh</button>
        </div>
      </div>

      {loadError.value && <div class="error-banner">Failed to load runtime data: {loadError.value}</div>}
      {runtimeActionError.value && (
        <div class="error-banner">{runtimeActionError.value}</div>
      )}

      <KpiRow />

      <div class="grid-2">
        <div>
          <Card title="Connector Status" subtitle="Each connector is a stub today — wire a real SDK to enable">
            <Connectors items={connectors.value} />
          </Card>
          <Card title="System Runtime State" subtitle="Kill switch, monitoring level, enable/disable per AI system">
            <SystemStates items={states.value} />
          </Card>
        </div>
        <div>
          <Card
            title="Human Approval Queue"
            subtitle="Actions awaiting human approval. TTL-bounded, auto-expire."
            action={
              <button
                class="btn btn-sm btn-primary"
                onClick={() => openRequestApproval(aiSystems.value)}
              >
                + Request
              </button>
            }
          >
            <Approvals items={approvals.value} />
          </Card>
          <Card title="Active Incidents" subtitle="Create from any event row in the stream">
            <Incidents items={incidents.value} />
          </Card>
        </div>
      </div>

      <Card title="Runtime Event Stream" subtitle="Latest first — click an event to create an incident">
        <EventStream events={events.value} loading={loading.value} />
      </Card>

      <RuntimeModals />
    </div>
  );
}

function KpiRow() {
  const k = kpis.value;
  return (
    <div class="kpi-row">
      <Kpi label="Events (24h sample)" value={k.total} />
      <Kpi label="Blocked / Refused" value={k.blocked} tone="critical" sub="DLP, guardrails, authz" />
      <Kpi label="Pending Approvals" value={k.pendingApprovals} tone="medium" />
      <Kpi
        label="Active Incidents"
        value={k.openIncidents}
        tone="critical"
        sub={`${k.killed} kill switch engaged`}
      />
    </div>
  );
}

function Kpi({ label, value, tone, sub }: { label: string; value: number; tone?: string; sub?: string }) {
  return (
    <div class="kpi-card">
      <div class="kpi-label">{label}</div>
      <div class={`kpi-value ${tone ?? ''}`}>{value}</div>
      {sub && <div class="kpi-trend">{sub}</div>}
    </div>
  );
}

function Card({ title, subtitle, action, children }: {
  title: string;
  subtitle?: string;
  action?: preact.ComponentChildren;
  children: preact.ComponentChildren;
}) {
  return (
    <div class="card mb-4">
      <div class="card-header">
        <div>
          <div class="card-title">{title}</div>
          {subtitle && <div class="card-subtitle">{subtitle}</div>}
        </div>
        {action}
      </div>
      <div class="card-body">{children}</div>
    </div>
  );
}

function Connectors({ items }: { items: RuntimeConnector[] }) {
  if (items.length === 0) return <div class="empty-state">No connectors configured.</div>;
  return (
    <>
      {items.map((c) => (
        <div key={c.source} class="connector-row">
          <div>
            <div class="text-sm font-bold">{c.source}</div>
            <div class="text-xs text-tertiary">{c.implementation}</div>
          </div>
          <div class="text-xs text-tertiary" style={{ textAlign: 'right' }}>{c.event_count} events</div>
          <div style={{ textAlign: 'right' }}>
            <span class={`badge ${c.event_count > 0 ? 'badge-pass' : 'badge-neutral'}`}>
              {c.event_count > 0 ? 'connected' : 'idle'}
            </span>
          </div>
        </div>
      ))}
    </>
  );
}

function Approvals({ items }: { items: RuntimeApproval[] }) {
  if (items.length === 0) {
    return <div class="text-xs text-tertiary" style={{ padding: '0.5rem 1rem' }}>No approval requests.</div>;
  }
  return (
    <>
      {items.slice(0, 8).map((a) => {
        const statusBadge =
          a.status === 'PENDING' ? 'badge-medium'
          : a.status === 'APPROVED' ? 'badge-pass'
          : a.status === 'REJECTED' ? 'badge-critical'
          : 'badge-neutral';
        return (
          <div key={a.id} class="list-row">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span class="font-mono text-xs">{a.id}</span>
              <span class={`badge ${statusBadge}`}>{a.status}</span>
            </div>
            <div class="text-sm" style={{ marginTop: 4 }}>{a.action_description}</div>
            <div class="text-xs text-tertiary" style={{ marginTop: 4 }}>
              {a.ai_system_id} · req {a.requested_by} · expires {a.expires_at.slice(0, 19)}
            </div>
            {a.approver && a.status !== 'PENDING' && (
              <div class="text-xs text-tertiary" style={{ marginTop: 4 }}>
                {a.status === 'APPROVED' ? 'Approved' : 'Rejected'} by {a.approver}
                {a.note ? ` — ${a.note}` : ''}
              </div>
            )}
          </div>
        );
      })}
    </>
  );
}

function Incidents({ items }: { items: RuntimeIncident[] }) {
  if (items.length === 0) {
    return <div class="text-xs text-tertiary" style={{ padding: '0.875rem 1rem' }}>No incidents.</div>;
  }
  return (
    <>
      {items.slice(0, 8).map((i) => {
        const badge =
          i.status === 'OPEN' ? 'badge-critical'
          : i.status === 'INVESTIGATING' ? 'badge-high'
          : i.status === 'MITIGATED' ? 'badge-medium'
          : 'badge-pass';
        return (
          <div key={i.id} class="list-row">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span class="font-mono text-xs font-bold">{i.id}</span>
              <span class={`badge ${badge}`}>{i.status}</span>
            </div>
            <div class="text-sm" style={{ marginTop: 4 }}>{i.summary}</div>
            <div class="text-xs text-tertiary" style={{ marginTop: 4 }}>
              {i.ai_system_id} · owner {i.owner} · created {i.created_at.slice(0, 19)}
              {i.from_event_id ? ` · from ${i.from_event_id}` : ''}
            </div>
          </div>
        );
      })}
    </>
  );
}
