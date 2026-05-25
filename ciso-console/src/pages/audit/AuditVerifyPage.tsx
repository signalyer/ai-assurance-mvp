// Surface 2: Audit Chain Verify (CSM-1)
// V1 ancestor: static/audit-events.html
// Data:
//   GET /api/audit/events?page=N          — paged event list
//   GET /api/audit/verify?window=N&full=true — chain integrity check → CLEAN/BROKEN banner
// Pattern: integrity banner at top, paged event table with expandable JSON row.

import { signal } from '@preact/signals';
import { useEffect } from 'preact/hooks';
import { apiGet } from '../../shared/api/client';
import type {
  AuditEvent, AuditEventsResponse, AuditVerifyResponse,
} from './types';

// ============================================================
// Module-level signals
// ============================================================

const events = signal<AuditEvent[]>([]);
const eventsLoading = signal<boolean>(true);
const eventsError = signal<string | null>(null);
const page = signal<number>(1);
const totalPages = signal<number>(1);

const verifyResult = signal<AuditVerifyResponse | null>(null);
const verifyLoading = signal<boolean>(true);
const verifyError = signal<string | null>(null);
const verifyWindow = signal<number>(100);

const expandedId = signal<string | null>(null);

// ============================================================
// Data loaders
// ============================================================

async function loadEvents(p: number): Promise<void> {
  eventsLoading.value = true;
  eventsError.value = null;
  const r = await apiGet<AuditEventsResponse>('/audit/events', { page: p, page_size: 50 });
  if (r.ok) {
    events.value = r.data.events ?? [];
    const total = r.data.total ?? 0;
    const size = r.data.page_size ?? 50;
    totalPages.value = Math.max(1, Math.ceil(total / size));
    page.value = r.data.page ?? p;
  } else {
    eventsError.value = r.detail;
  }
  eventsLoading.value = false;
}

async function runVerify(): Promise<void> {
  verifyLoading.value = true;
  verifyError.value = null;
  const r = await apiGet<AuditVerifyResponse>('/audit/verify', {
    window: verifyWindow.value,
    full: true,
  });
  if (r.ok) {
    verifyResult.value = r.data;
  } else {
    verifyError.value = r.detail;
  }
  verifyLoading.value = false;
}

async function loadAll(): Promise<void> {
  await Promise.all([loadEvents(page.value), runVerify()]);
}

// ============================================================
// Helpers
// ============================================================

function fmtTs(ts: string): string {
  return (ts || '').slice(0, 19).replace('T', ' ');
}

// ============================================================
// Component
// ============================================================

export function AuditVerifyPage() {
  useEffect(() => { void loadAll(); }, []);

  return (
    <div>
      <div class="page-header">
        <div>
          <div class="page-title">Audit Chain Verification</div>
          <div class="page-subtitle">
            Tamper-evident audit log · SHA-256 linked chain · each event hash covers prior state
          </div>
        </div>
        <div class="page-actions">
          <select
            class="filter-select"
            value={String(verifyWindow.value)}
            onChange={(e) => {
              verifyWindow.value = Number((e.currentTarget as HTMLSelectElement).value);
              void runVerify();
            }}
          >
            <option value="50">Last 50 events</option>
            <option value="100">Last 100 events</option>
            <option value="500">Last 500 events</option>
            <option value="1000">Last 1000 events</option>
          </select>
          <button class="btn btn-sm" onClick={() => void loadAll()}>Refresh</button>
        </div>
      </div>

      <ChainBanner />

      {verifyError.value && (
        <div class="error-banner">Verification failed: {verifyError.value}</div>
      )}

      <div class="card">
        <div class="card-header">
          <div>
            <div class="card-title">Audit Events</div>
            <div class="card-subtitle">
              Page {page.value} of {totalPages.value} · click a row to expand raw payload
            </div>
          </div>
          <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
            <button
              class="btn btn-sm"
              disabled={page.value <= 1 || eventsLoading.value}
              onClick={() => { page.value -= 1; void loadEvents(page.value); }}
            >
              ← Prev
            </button>
            <button
              class="btn btn-sm"
              disabled={page.value >= totalPages.value || eventsLoading.value}
              onClick={() => { page.value += 1; void loadEvents(page.value); }}
            >
              Next →
            </button>
          </div>
        </div>
        <EventsTable />
      </div>
    </div>
  );
}

function ChainBanner() {
  const v = verifyResult.value;

  if (verifyLoading.value && !v) {
    return (
      <div class="chain-banner" style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-secondary)' }}>
        Verifying chain integrity…
      </div>
    );
  }
  if (!v) return null;

  const isClean = v.status === 'CLEAN';
  return (
    <div class={`chain-banner ${isClean ? 'clean' : 'broken'}`}>
      <span style={{ fontSize: 16 }}>{isClean ? '✓' : '✗'}</span>
      <span>
        Chain {isClean ? 'CLEAN' : 'BROKEN'} — {v.events_checked} events verified across window={v.window}
        {!isClean && v.broken_count > 0 && ` · ${v.broken_count} tampered entries detected`}
        {' '}· verified {fmtTs(v.verified_at)}
      </span>
      {!isClean && v.broken_entries.length > 0 && (
        <span class="text-xs" style={{ marginLeft: 'auto' }}>
          First broken: #{v.broken_entries[0]?.position} — {v.broken_entries[0]?.reason}
        </span>
      )}
    </div>
  );
}

function EventsTable() {
  const rows = events.value;

  if (eventsLoading.value) return <div class="loading" style={{ padding: '1.5rem' }}>Loading events…</div>;
  if (eventsError.value) return <div class="error-banner" style={{ margin: '1rem' }}>Failed to load events: {eventsError.value}</div>;
  if (rows.length === 0) return <div class="empty-state">No audit events on record.</div>;

  return (
    <table class="data-table">
      <thead>
        <tr>
          <th>Timestamp</th>
          <th>Event Type</th>
          <th>Actor</th>
          <th>Resource</th>
          <th>Action</th>
          <th>Outcome</th>
          <th>Hash (prefix)</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((ev) => {
          const isExpanded = expandedId.value === ev.id;
          return (
            <>
              <tr
                key={ev.id}
                style={{ cursor: 'pointer' }}
                onClick={() => { expandedId.value = isExpanded ? null : ev.id; }}
              >
                <td class="text-xs text-tertiary">{fmtTs(ev.timestamp)}</td>
                <td class="cell-primary">{ev.event_type.replace(/_/g, ' ')}</td>
                <td class="text-xs">{ev.actor}</td>
                <td class="text-xs">
                  {ev.resource_type ? `${ev.resource_type}` : '—'}
                  {ev.resource_id ? (
                    <div class="text-tertiary mono">{ev.resource_id.slice(0, 16)}…</div>
                  ) : null}
                </td>
                <td class="text-xs">{ev.action}</td>
                <td>
                  <span class={`badge ${ev.outcome === 'SUCCESS' ? 'badge-pass' : ev.outcome === 'FAILURE' ? 'badge-critical' : 'badge-neutral'}`}>
                    {ev.outcome}
                  </span>
                </td>
                <td class="text-xs mono text-tertiary">
                  {ev.hash ? ev.hash.slice(0, 12) : '—'}
                </td>
              </tr>
              {isExpanded && (
                <tr key={`${ev.id}-expand`}>
                  <td colSpan={7} style={{ padding: '0.5rem 0.75rem', background: 'var(--bg-elevated)', borderBottom: '2px solid var(--border-strong)' }}>
                    <pre style={{
                      fontFamily: "'SF Mono', Menlo, Consolas, monospace",
                      fontSize: 10,
                      color: 'var(--text-secondary)',
                      background: 'var(--bg-base)',
                      border: '1px solid var(--border)',
                      borderRadius: 4,
                      padding: '0.5rem 0.75rem',
                      whiteSpace: 'pre-wrap',
                      wordBreak: 'break-all',
                      maxHeight: 300,
                      overflowY: 'auto',
                    }}>
                      {JSON.stringify(ev, null, 2)}
                    </pre>
                  </td>
                </tr>
              )}
            </>
          );
        })}
      </tbody>
    </table>
  );
}
