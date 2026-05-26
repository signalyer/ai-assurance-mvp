// Session 52 — V1/V2 data-mode toggle.
//
// localStorage-backed kill switch that flips every list endpoint between
// V1 (seeded demo portfolio — default) and V2 (real customer systems
// registered via the intake flow). The toggle stamps every API request
// with `X-Data-Mode: v1|v2` via the shared apiRequest helper.
//
// Architectural notes:
//   - Per-origin localStorage (not user-profile) so a backend outage
//     never strands the operator in V2.
//   - Module-level signal so any page can subscribe (rare, but free).
//   - Reload on flip so every list re-fetches under the new mode — no
//     attempt at hot-swapping in-flight state.
//   - Default v1. V2 default produces empty pages until at least one
//     real system is registered (S53+).

import { signal } from '@preact/signals';

export type DataMode = 'v1' | 'v2';

const STORAGE_KEY = 'aigovern_data_mode';

function readInitial(): DataMode {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    return raw === 'v2' ? 'v2' : 'v1';
  } catch {
    return 'v1';
  }
}

export const dataMode = signal<DataMode>(readInitial());

export function getDataMode(): DataMode {
  return dataMode.value;
}

function setMode(next: DataMode): void {
  if (next === dataMode.value) return;
  try {
    window.localStorage.setItem(STORAGE_KEY, next);
  } catch {
    // Storage may be disabled (private mode). The signal still flips;
    // the reload below will read the in-memory value via the signal
    // on the next page, but it WON'T persist across full reloads.
  }
  dataMode.value = next;
  // Reload so every list re-fetches under the new mode. Cheap, honest,
  // and matches the kill-switch framing — no half-stale UI in flight.
  window.location.reload();
}

export function DataModeToggle() {
  const mode = dataMode.value;
  const isV2 = mode === 'v2';
  const label = isV2 ? 'Live data' : 'Demo data';
  const dotColor = isV2 ? '#10b981' : '#94a3b8'; // green / slate
  const title = isV2
    ? 'Live mode — only systems registered via the intake flow are visible. Click to switch to demo data.'
    : 'Demo mode — seeded portfolio of governance fixtures is visible. Click to switch to live data.';

  return (
    <button
      type="button"
      class="data-mode-toggle"
      onClick={() => setMode(isV2 ? 'v1' : 'v2')}
      title={title}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '0.4rem',
        padding: '0.25rem 0.65rem',
        marginRight: '0.5rem',
        border: '1px solid #cbd5e1',
        borderRadius: '999px',
        background: isV2 ? '#ecfdf5' : '#f8fafc',
        color: isV2 ? '#065f46' : '#334155',
        fontSize: '0.78rem',
        fontWeight: 600,
        cursor: 'pointer',
        lineHeight: 1,
      }}
    >
      <span
        aria-hidden="true"
        style={{
          width: '8px',
          height: '8px',
          borderRadius: '50%',
          background: dotColor,
          display: 'inline-block',
        }}
      />
      <span>{label}</span>
    </button>
  );
}
