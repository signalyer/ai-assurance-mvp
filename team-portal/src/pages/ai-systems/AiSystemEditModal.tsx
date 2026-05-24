// Edit System modal — driven by module-level signals, mirrors AiSystemDrawer
// pattern. Opens via openEdit(id); on save, calls back to the drawer to
// refresh in place. Scopes editable fields to those present on AiSystemDetail
// (drawer def-list). Full MATERIAL set (cloud_provider, tools, rag_sources…)
// requires extending /grc/ai-systems/{id} — out of scope for #9.

import { signal, computed } from '@preact/signals';
import { useEffect } from 'preact/hooks';
import { apiGet, apiRequest } from '../../shared/api/client';
import type {
  AiSystemDetail,
  EditInfo,
  SubmitEditResponse,
} from './types';

const editingSystemId = signal<string | null>(null);
const editInfo = signal<EditInfo | null>(null);
const baseDetail = signal<AiSystemDetail | null>(null);
const loadError = signal<string | null>(null);
const saveError = signal<string | null>(null);
const saving = signal<boolean>(false);
const successBanner = signal<string | null>(null);

// Edited values keyed by field name. Compared to baseDetail on submit;
// unchanged fields are dropped before POST.
const draft = signal<Record<string, string>>({});
const changeReason = signal<string>('');
const changeCategory = signal<string>('Other');

// Refresh callback set by the drawer so a successful edit can re-load the
// drawer's currentSystem without circular imports.
let onSavedCallback: ((systemId: string) => void) | null = null;

export function registerEditSavedCallback(cb: (systemId: string) => void): void {
  onSavedCallback = cb;
}

export function openEdit(id: string): void {
  editingSystemId.value = id;
  draft.value = {};
  changeReason.value = '';
  changeCategory.value = 'Other';
  saveError.value = null;
  successBanner.value = null;
}

function closeEdit(): void {
  editingSystemId.value = null;
  editInfo.value = null;
  baseDetail.value = null;
  loadError.value = null;
  saveError.value = null;
  draft.value = {};
}

// Fields displayed in the drawer's def-list; we cap edits to these so users
// always see the current value alongside the input. Order matches the drawer.
const EDITABLE_FIELDS: ReadonlyArray<{ key: keyof AiSystemDetail; label: string; type: 'text' | 'textarea' | 'csv' }> = [
  { key: 'name', label: 'Name', type: 'text' },
  { key: 'description', label: 'Description', type: 'textarea' },
  { key: 'business_owner', label: 'Business Owner', type: 'text' },
  { key: 'technical_owner', label: 'Technical Owner', type: 'text' },
  { key: 'domain', label: 'Domain', type: 'text' },
  { key: 'use_case', label: 'Use Case', type: 'textarea' },
  { key: 'human_oversight', label: 'HITL / Human Oversight', type: 'text' },
  { key: 'data_residency', label: 'Data Residency', type: 'text' },
  { key: 'autonomy_level', label: 'Autonomy Level', type: 'text' },
  { key: 'data_classes', label: 'Data Classes (comma-separated)', type: 'csv' },
];

async function loadForEdit(id: string): Promise<void> {
  loadError.value = null;
  editInfo.value = null;
  baseDetail.value = null;

  const [infoRes, detailRes] = await Promise.all([
    apiGet<EditInfo>(`/ai-systems/${encodeURIComponent(id)}/edit-info`),
    apiGet<AiSystemDetail>(`/grc/ai-systems/${encodeURIComponent(id)}`),
  ]);

  if (!infoRes.ok) {
    loadError.value = `edit-info: ${infoRes.detail}`;
    return;
  }
  if (!detailRes.ok) {
    loadError.value = `system: ${detailRes.detail}`;
    return;
  }

  editInfo.value = infoRes.data;
  baseDetail.value = detailRes.data;

  const seed: Record<string, string> = {};
  for (const f of EDITABLE_FIELDS) {
    const cur = detailRes.data[f.key];
    seed[f.key as string] = f.type === 'csv'
      ? Array.isArray(cur) ? cur.join(', ') : String(cur ?? '')
      : String(cur ?? '');
  }
  draft.value = seed;
}

function tierFor(fieldName: string, info: EditInfo): 'soft' | 'material' | 'locked' | 'unknown' {
  if (info.field_tiers.locked.includes(fieldName)) return 'locked';
  if (info.field_tiers.soft.includes(fieldName)) return 'soft';
  if (info.field_tiers.material.includes(fieldName)) return 'material';
  return 'unknown';
}

const computedChanges = computed<Record<string, unknown>>(() => {
  const base = baseDetail.value;
  const d = draft.value;
  if (!base) return {};
  const out: Record<string, unknown> = {};
  for (const f of EDITABLE_FIELDS) {
    const raw = d[f.key as string] ?? '';
    const cur = base[f.key];
    if (f.type === 'csv') {
      const after = raw.split(',').map((s) => s.trim()).filter(Boolean);
      const before = Array.isArray(cur) ? cur : [];
      if (after.length !== before.length || after.some((v, i) => v !== before[i])) {
        out[f.key as string] = after;
      }
    } else {
      const before = String(cur ?? '');
      if (raw !== before) out[f.key as string] = raw;
    }
  }
  return out;
});

const hasMaterial = computed<boolean>(() => {
  const info = editInfo.value;
  const ch = computedChanges.value;
  if (!info) return false;
  return Object.keys(ch).some((k) => tierFor(k, info) === 'material');
});

async function submitEdit(): Promise<void> {
  const id = editingSystemId.value;
  const info = editInfo.value;
  if (!id || !info) return;

  const changes = computedChanges.value;
  if (Object.keys(changes).length === 0) {
    saveError.value = 'No changes to submit.';
    return;
  }
  if (hasMaterial.value && !changeReason.value.trim()) {
    saveError.value = 'Change reason is required for material edits.';
    return;
  }

  saving.value = true;
  saveError.value = null;

  const res = await apiRequest<SubmitEditResponse>(
    `/ai-systems/${encodeURIComponent(id)}/edit`,
    {
      method: 'POST',
      body: {
        changes,
        change_reason: changeReason.value.trim(),
        change_category: changeCategory.value,
      },
    },
  );

  saving.value = false;

  if (!res.ok) {
    saveError.value = res.detail;
    return;
  }

  const next = res.data.next_step;
  successBanner.value = next === 'pending_approval'
    ? `Submitted — pending approval (revision ${res.data.revision.revision_id}).`
    : `Applied (revision ${res.data.revision.revision_id}).`;

  if (onSavedCallback) onSavedCallback(id);

  // Auto-close after a brief delay so the user sees the banner.
  setTimeout(() => closeEdit(), 1400);
}

export function AiSystemEditModal() {
  const id = editingSystemId.value;

  useEffect(() => {
    if (id) void loadForEdit(id);
  }, [id]);

  if (!id) return null;

  const info = editInfo.value;
  const base = baseDetail.value;

  return (
    <div
      class="modal-overlay open"
      onClick={(e) => {
        if (e.target === e.currentTarget) closeEdit();
      }}
    >
      <div class="modal" style={{ maxWidth: 720 }}>
        <div class="modal-header">
          <div>
            <div class="modal-title">Edit System {base ? `· ${base.name}` : ''}</div>
            <div class="text-xs text-tertiary" style={{ marginTop: 2 }}>
              Soft fields auto-apply. Material fields enter the approval queue.
            </div>
          </div>
          <button class="modal-close" onClick={closeEdit} aria-label="Close">×</button>
        </div>

        <div class="modal-body">
          {loadError.value && <div class="error-banner">Failed to load: {loadError.value}</div>}
          {!info && !loadError.value && <div class="loading">Loading…</div>}

          {info && info.status.has_pending_material && (
            <div
              class="error-banner"
              style={{ marginBottom: 12 }}
            >
              A material revision is already pending
              ({info.status.pending_revision_id}) — resolve it before submitting another edit.
            </div>
          )}

          {info && base && !info.status.has_pending_material && (
            <>
              <table class="data-table" style={{ marginBottom: 16 }}>
                <thead>
                  <tr>
                    <th style={{ width: '22%' }}>Field</th>
                    <th style={{ width: '12%' }}>Tier</th>
                    <th>Value</th>
                  </tr>
                </thead>
                <tbody>
                  {EDITABLE_FIELDS.map((f) => {
                    const tier = tierFor(f.key as string, info);
                    const v = draft.value[f.key as string] ?? '';
                    return (
                      <tr key={f.key as string}>
                        <td>
                          <div class="cell-primary text-sm">{f.label}</div>
                          <div class="cell-secondary font-mono">{f.key as string}</div>
                        </td>
                        <td>
                          <span class={`badge ${tier === 'material' ? 'badge-warning' : 'badge-info'}`}>
                            {tier}
                          </span>
                        </td>
                        <td>
                          {f.type === 'textarea' ? (
                            <textarea
                              class="filter-input"
                              style={{ width: '100%', minHeight: 60 }}
                              value={v}
                              onInput={(e) => {
                                draft.value = {
                                  ...draft.value,
                                  [f.key as string]: (e.currentTarget as HTMLTextAreaElement).value,
                                };
                              }}
                            />
                          ) : (
                            <input
                              class="filter-input"
                              style={{ width: '100%' }}
                              type="text"
                              value={v}
                              onInput={(e) => {
                                draft.value = {
                                  ...draft.value,
                                  [f.key as string]: (e.currentTarget as HTMLInputElement).value,
                                };
                              }}
                            />
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>

              <div class="drawer-section">
                <div class="drawer-section-title">Change Reason {hasMaterial.value && <span class="text-critical">*</span>}</div>
                <textarea
                  class="filter-input"
                  style={{ width: '100%', minHeight: 60 }}
                  placeholder={hasMaterial.value
                    ? 'Required for material edits — why is this change being made?'
                    : 'Optional for soft edits.'}
                  value={changeReason.value}
                  onInput={(e) => (changeReason.value = (e.currentTarget as HTMLTextAreaElement).value)}
                />
              </div>

              <div class="drawer-section">
                <div class="drawer-section-title">Change Category</div>
                <select
                  class="filter-select"
                  value={changeCategory.value}
                  onChange={(e) => (changeCategory.value = (e.currentTarget as HTMLSelectElement).value)}
                >
                  {info.valid_change_categories.map((c) => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </select>
              </div>

              <div class="text-xs text-tertiary" style={{ marginTop: 8 }}>
                {Object.keys(computedChanges.value).length === 0
                  ? 'No changes yet.'
                  : `${Object.keys(computedChanges.value).length} field(s) changed · ${hasMaterial.value ? 'will require approval' : 'will auto-apply'}.`}
              </div>
            </>
          )}

          {saveError.value && <div class="error-banner" style={{ marginTop: 12 }}>{saveError.value}</div>}
          {successBanner.value && (
            <div
              style={{
                marginTop: 12,
                padding: '0.75rem 1rem',
                background: 'var(--pass-bg, rgba(34,197,94,0.1))',
                border: '1px solid var(--pass, #22c55e)',
                borderRadius: 4,
                color: 'var(--pass, #22c55e)',
                fontSize: 13,
              }}
            >
              {successBanner.value}
            </div>
          )}
        </div>

        <div class="modal-footer">
          <div style={{ flex: 1 }} />
          <button class="btn btn-sm btn-secondary" onClick={closeEdit} disabled={saving.value}>Cancel</button>
          <button
            class="btn btn-sm btn-primary"
            onClick={() => void submitEdit()}
            disabled={
              saving.value ||
              !info ||
              info.status.has_pending_material ||
              Object.keys(computedChanges.value).length === 0
            }
          >
            {saving.value ? 'Submitting…' : hasMaterial.value ? 'Submit for Approval' : 'Apply Changes'}
          </button>
        </div>
      </div>
    </div>
  );
}
