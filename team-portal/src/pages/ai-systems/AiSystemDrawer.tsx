import { useEffect, useRef } from 'preact/hooks';
import { signal } from '@preact/signals';
import { apiGet } from '../../shared/api/client';
import { SeverityBadge, DecisionBadge, RuntimeStatusDot } from '../../shared/components/Badges';
import { openEdit, registerEditSavedCallback } from './AiSystemEditModal';
import { openRevisions } from './AiSystemRevisionsPanel';
import { openFrameworks } from './AiSystemFrameworksPanel';
import { openBoundAgents } from './AiSystemBoundAgentsPanel';
import { openAiSummary } from '../../shared/components/AiSummaryDrawer';
import { AiActionsMenu } from '../../shared/components/AiActionsMenu';
import type { AiSystemDetail, EditStatus, EvidenceListResponse, EvidenceRow, ReleaseGate } from './types';

// Open-system signal: drives the side drawer.
// Setting to a non-null id triggers a fetch; null closes the drawer.
const openSystemId = signal<string | null>(null);
const currentSystem = signal<AiSystemDetail | null>(null);
const drawerError = signal<string | null>(null);
const editStatus = signal<EditStatus | null>(null);
// S67: drawer surfaces canonical layered evidence via the dedicated endpoint
// (same one the Edit modal reads). Loaded on drawer open alongside detail.
const evidenceRows = signal<EvidenceRow[]>([]);
const evidenceError = signal<string | null>(null);

// Edit modal calls back here on successful save so the drawer + status banner
// reflect the new state without a page reload. S67: also refreshes evidence
// list — operator may have added rows in the modal's Evidence section.
registerEditSavedCallback((id: string) => {
  if (openSystemId.value === id) {
    void loadDetail(id);
    void loadEvidence(id);
  }
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
  evidenceRows.value = [];
  evidenceError.value = null;
  const url = new URL(window.location.href);
  url.searchParams.delete('id');
  window.history.replaceState({}, '', url.toString());
}

async function loadEvidence(id: string): Promise<void> {
  evidenceError.value = null;
  const r = await apiGet<EvidenceListResponse>(
    `/grc/ai-systems/${encodeURIComponent(id)}/evidence`,
  );
  if (r.ok) {
    evidenceRows.value = r.data.evidence ?? [];
  } else {
    evidenceError.value = r.detail;
    evidenceRows.value = [];
  }
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
    if (id) {
      void loadDetail(id);
      void loadEvidence(id);
    }
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
      <AskAiPromptModal />
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
            <FailedGateRow key={g.id} gate={g} systemId={s.id} />
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
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
              <span class="font-mono text-xs">{f.id}</span>
              <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                <SeverityBadge value={f.severity} />
                <button
                  class="btn btn-xs btn-secondary"
                  onClick={() => openSummarizeFinding(s.id, f.id, f.severity, f.title)}
                >
                  Summarize
                </button>
              </div>
            </div>
            <div class="text-sm" style={{ marginTop: 4 }}>{f.title}</div>
          </div>
        ))}
      </div>

      <EvidenceSection systemId={s.id} />

      <div class="drawer-section">
        <div class="drawer-section-title">Last Assessment</div>
        <div class="text-sm">{s.last_assessment} · next {s.next_assessment}</div>
      </div>

      {/* Action buttons */}
      <div class="drawer-section" style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <a class="btn btn-sm btn-primary" href={`/assessment?system=${encodeURIComponent(s.id)}`}>
          Run Assessment
        </a>
        {/* #9-#12 wired. All drawer actions live. */}
        <button class="btn btn-sm btn-secondary" onClick={() => openEdit(s.id)}>Edit System</button>
        <button class="btn btn-sm btn-secondary" onClick={() => openRevisions(s.id)}>
          Revision History{editStatus.value && editStatus.value.revision_count > 0 ? ` (${editStatus.value.revision_count})` : ''}
        </button>
        <button class="btn btn-sm btn-secondary" onClick={() => openFrameworks(s.id)}>Frameworks</button>
        <button class="btn btn-sm btn-secondary" onClick={() => openBoundAgents(s.id)}>Bound Agents</button>
        {/* S73: AI actions consolidated into menu. SUMMARIZE_FINDING is per-row above. */}
        <AiActionsMenu
          items={[
            { key: 'ask',         label: 'Ask AI…',     onClick: () => openAskAboutSystem(s) },
            { key: 'draft-report', label: 'Draft Report', onClick: () => openDraftReport(s) },
          ]}
        />
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// S72: AI action surface — inline helpers
//
// All four route through the shared AiSummaryDrawer (already SSE-aware from
// S69). Anthropic pinned per [[FailedGateRow.onExplain pattern]]: all four
// use cases are in Anthropic's allowed list, and Bedrock has no streaming
// adapter yet. Drop the pin in S71b/S73 when Bedrock streaming lands.
// ---------------------------------------------------------------------------

// S72b: in-app modal replaces window.prompt for Ask AI. Module-level signal
// drives the open/close state — same pattern as openAiSummary above.
const askPromptSystem = signal<AiSystemDetail | null>(null);

function openAskAboutSystem(s: AiSystemDetail): void {
  askPromptSystem.value = s;
}

function closeAskPrompt(): void {
  askPromptSystem.value = null;
}

function submitAskPrompt(s: AiSystemDetail, question: string): void {
  const trimmed = question.trim();
  if (!trimmed) return;
  closeAskPrompt();
  openAiSummary({
    url: '/assurance-model/ask',
    title: `Ask: ${s.name}`,
    body: {
      ai_system_id: s.id,
      data_classes: [],
      payload: {
        question: trimmed,
        risk_tier: s.risk_level,
        open_findings_summary: summarizeOpenFindings(s),
      },
      user: 'team-portal',
    },
  });
}

export function AskAiPromptModal() {
  const s = askPromptSystem.value;
  const inputRef = useRef<HTMLTextAreaElement | null>(null);

  // Autofocus the textarea when the modal opens.
  useEffect(() => {
    if (s && inputRef.current) {
      inputRef.current.focus();
    }
  }, [s]);

  if (!s) return null;

  function onSubmit(e: Event) {
    e.preventDefault();
    const text = inputRef.current?.value ?? '';
    submitAskPrompt(s!, text);
  }

  function onKeyDown(e: KeyboardEvent) {
    // Cmd/Ctrl+Enter submits; Escape cancels (overlay click handles backdrop).
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
      e.preventDefault();
      const text = inputRef.current?.value ?? '';
      submitAskPrompt(s!, text);
    } else if (e.key === 'Escape') {
      e.preventDefault();
      closeAskPrompt();
    }
  }

  return (
    <>
      <div
        class="drawer-overlay open"
        style={{ zIndex: 200 }}
        onClick={closeAskPrompt}
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`Ask AI about ${s.name}`}
        style={{
          position: 'fixed',
          top: '50%',
          left: '50%',
          transform: 'translate(-50%, -50%)',
          zIndex: 201,
          width: 'min(560px, calc(100vw - 32px))',
          background: 'var(--bg-card)',
          color: 'var(--text-primary)',
          border: '1px solid var(--border)',
          borderRadius: 8,
          boxShadow: '0 10px 40px rgba(0,0,0,0.55)',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        <div
          style={{
            padding: '0.75rem 1rem',
            borderBottom: '1px solid var(--border)',
            fontWeight: 600,
            fontSize: '0.95rem',
          }}
        >
          Ask AI about {s.name}
        </div>
        <form onSubmit={onSubmit} style={{ padding: '1rem', display: 'flex', flexDirection: 'column', gap: 12 }}>
          <label
            for="ask-ai-question"
            class="text-xs text-secondary"
            style={{ fontWeight: 500 }}
          >
            Your question
          </label>
          <textarea
            id="ask-ai-question"
            ref={inputRef}
            rows={4}
            onKeyDown={onKeyDown}
            placeholder='e.g. "What is blocking this system from production release?"'
            style={{
              width: '100%',
              fontSize: '0.9rem',
              lineHeight: 1.5,
              padding: '0.6rem 0.75rem',
              background: 'var(--bg-input)',
              color: 'var(--text-primary)',
              border: '1px solid var(--border)',
              borderRadius: 4,
              resize: 'vertical',
              fontFamily: 'inherit',
              boxSizing: 'border-box',
            }}
          />
          <div class="text-xs text-tertiary">
            ⌘/Ctrl+Enter to send · Esc to cancel · Grounded in this system's risk tier + open findings.
          </div>
          <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
            <button
              type="button"
              class="btn btn-sm btn-secondary"
              onClick={closeAskPrompt}
            >
              Cancel
            </button>
            <button type="submit" class="btn btn-sm btn-primary">
              Ask
            </button>
          </div>
        </form>
      </div>
    </>
  );
}

function openSummarizeFinding(
  systemId: string,
  findingId: string,
  severity: string,
  title: string,
): void {
  openAiSummary({
    url: '/assurance-model/summarize-finding',
    title: `Finding: ${findingId}`,
    body: {
      ai_system_id: systemId,
      data_classes: [],
      payload: {
        finding_id: findingId,
        severity,
        title,
        finding_note: null,
      },
      user: 'team-portal',
    },
  });
}

function openSummarizeEvidence(systemId: string, rows: EvidenceRow[]): void {
  // Collapse the rows the drawer already loaded into a compact section list
  // so the prompt sees what the operator sees (no extra fetch needed).
  const sections = summarizeEvidenceSections(rows);
  openAiSummary({
    url: '/assurance-model/summarize-evidence',
    title: 'Evidence summary',
    body: {
      ai_system_id: systemId,
      data_classes: [],
      payload: {
        evidence_sections: sections || '(no evidence on file)',
        evidence_completeness: rows.length > 0 ? `${rows.length} records on file` : '0%',
      },
      user: 'team-portal',
    },
  });
}

function openDraftReport(s: AiSystemDetail): void {
  const openCrit = s.findings.filter(
    (f) => (f.status === 'OPEN' || f.status === 'IN_PROGRESS') && f.severity === 'CRITICAL',
  ).length;
  const openHigh = s.findings.filter(
    (f) => (f.status === 'OPEN' || f.status === 'IN_PROGRESS') && f.severity === 'HIGH',
  ).length;
  // S72b: feed the evidence rows the drawer already loaded into the prompt
  // so the new Evidence posture line in the report has real input.
  const rows = evidenceRows.value;
  const evidenceSummary = rows.length === 0
    ? '0 evidence records on file — assurance pack is empty'
    : `${rows.length} records on file: ${summarizeEvidenceSections(rows)}`;
  openAiSummary({
    url: '/assurance-model/draft-report',
    title: `Report: ${s.name}`,
    body: {
      ai_system_id: s.id,
      data_classes: [],
      payload: {
        portfolio_stats: (
          `1 system · risk=${s.risk_level} · decision=${s.release_decision} · ` +
          `runtime=${s.runtime_status}`
        ),
        top_risks: (
          `${openCrit} open CRITICAL, ${openHigh} open HIGH on ${s.name}; ` +
          `domain=${s.domain}`
        ),
        evidence_summary: evidenceSummary,
      },
      user: 'team-portal',
    },
  });
}

function summarizeOpenFindings(s: AiSystemDetail): string {
  const open = s.findings.filter((f) => f.status === 'OPEN' || f.status === 'IN_PROGRESS');
  if (open.length === 0) return '(no open findings)';
  const bySev: Record<string, number> = {};
  for (const f of open) bySev[f.severity] = (bySev[f.severity] ?? 0) + 1;
  const parts = Object.entries(bySev).map(([k, v]) => `${v} ${k}`);
  return `${open.length} open: ${parts.join(', ')}`;
}

function summarizeEvidenceSections(rows: EvidenceRow[]): string {
  if (rows.length === 0) return '';
  const byType: Record<string, number> = {};
  for (const r of rows) byType[r.evidence_type] = (byType[r.evidence_type] ?? 0) + 1;
  return Object.entries(byType)
    .map(([k, v]) => (v > 1 ? `${k} ×${v}` : k))
    .join(', ');
}

// S68a (G-6): Failed release gate row with Explain button. Routes to
// /api/v1/assurance-model/explain-release; drawer renders the simulated
// preview via the shared AiSummaryDrawer. Currently sim-only — S69 wires
// real Anthropic streaming.
function FailedGateRow({ gate: g, systemId }: { gate: ReleaseGate; systemId: string }) {
  function onExplain(): void {
    openAiSummary({
      url: '/assurance-model/explain-release',
      title: `Explain: ${g.id}`,
      body: {
        ai_system_id: systemId,
        data_classes: [],
        payload: {
          gate_id: g.id,
          gate_note: g.note ?? null,
          gate_actual: g.actual ?? null,
        },
        // S69 constraint: pin Anthropic. Routing engine ranks Bedrock above
        // Anthropic for RELEASE_DECISION_NARRATIVE (Bedrock carries all three
        // roles), but App Service has no AWS creds -- without this pin the
        // live LLM path would fall back to sim and the operator would see
        // the same Simulated preview as S68a. S69b: provider-agnostic
        // streaming will drop this pin.
        user: 'team-portal',
      },
    });
  }

  return (
    <div
      class="text-xs"
      style={{
        padding: '0.5rem',
        background: 'var(--critical-bg)',
        border: '1px solid rgba(239,68,68,0.3)',
        borderRadius: 4,
        marginBottom: 6,
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        gap: 8,
      }}
    >
      <div>
        <span class="font-mono text-critical">{g.id}</span> {g.note ?? g.actual}
      </div>
      <button
        class="btn btn-xs btn-secondary"
        style={{ flexShrink: 0 }}
        onClick={onExplain}
      >
        Explain
      </button>
    </div>
  );
}

// S67: Evidence section. Read-only here; add lives in the Edit modal.
// Shows the canonical layered store (seed + overlays + demo + intake-written)
// via /grc/ai-systems/{id}/evidence. The first 8 rows render inline; an
// overflow line summarizes the rest so the drawer doesn't grow unbounded
// for systems with 20+ rows (typical post-S67 consolidation).
const EVIDENCE_PREVIEW_LIMIT = 8;

function EvidenceSection({ systemId }: { systemId: string }) {
  const rows = evidenceRows.value;
  const err = evidenceError.value;
  const visible = rows.slice(0, EVIDENCE_PREVIEW_LIMIT);
  const overflow = rows.length - visible.length;

  return (
    <div class="drawer-section">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div class="drawer-section-title" style={{ margin: 0 }}>Evidence ({rows.length})</div>
        <button
          class="btn btn-xs btn-secondary"
          onClick={() => openSummarizeEvidence(systemId, rows)}
          title={
            rows.length === 0
              ? 'Summarize evidence with AI (will report that none is on file)'
              : 'Summarize evidence with AI'
          }
        >
          Summarize evidence
        </button>
      </div>
      {err && <div class="text-xs text-critical">Could not load evidence: {err}</div>}
      {!err && rows.length === 0 && (
        <div class="text-xs text-tertiary">No evidence on file yet. Add via Edit System → Evidence.</div>
      )}
      {visible.map((ev) => (
        <div
          key={ev.id}
          style={{
            padding: '0.5rem',
            border: '1px solid var(--border)',
            borderRadius: 4,
            marginBottom: 6,
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
            <span class="font-mono text-xs">{ev.evidence_type}</span>
            <span class="text-xs text-tertiary">{ev.collected_at?.slice(0, 10)}</span>
          </div>
          <div class="text-sm" style={{ marginTop: 4 }}>{ev.summary || ev.source}</div>
        </div>
      ))}
      {overflow > 0 && (
        <div class="text-xs text-tertiary" style={{ marginTop: 4 }}>
          + {overflow} more — open Edit System → Evidence to see all.
        </div>
      )}
    </div>
  );
}
