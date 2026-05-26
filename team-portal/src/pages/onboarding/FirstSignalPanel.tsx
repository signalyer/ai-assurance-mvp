// FirstSignalPanel — Step 3 of the onboarding wizard (S53).
//
// Polls GET /api/sdk-keys/{key_id}/status every 2500ms until the engine
// flips first_seen_at from null to a timestamp (set by the HMAC middleware
// on the first authed SDK call). Three visual states: waiting, arrived,
// stalled (no signal after 60s).
//
// Stops polling cleanly once first_seen_at arrives. Cleanup in useEffect
// return clears the interval on unmount.

import { signal, computed } from '@preact/signals';
import { useEffect } from 'preact/hooks';
import { apiGet } from '../../shared/api/client';
import type { KeyStatus } from './types';

interface Props {
  keyId: string;
  aiSystemId: string;
  /** Called once when first_seen_at first transitions from null → timestamp. */
  onArrived?: () => void;
}

const POLL_INTERVAL_MS = 2500;
const STALL_THRESHOLD_MS = 60_000;

// Module-level signals — per-key state. The panel is mounted at most once
// at a time within the wizard, so a single set of module signals is fine.
const lastStatus = signal<KeyStatus | null>(null);
const pollError = signal<string | null>(null);
const startedAt = signal<number>(0);
const tick = signal<number>(0);   // forces re-render for the elapsed timer

async function pollOnce(keyId: string): Promise<KeyStatus | null> {
  const r = await apiGet<KeyStatus>(`/sdk-keys/${encodeURIComponent(keyId)}/status`);
  if (!r.ok) {
    pollError.value = r.detail;
    return null;
  }
  pollError.value = null;
  lastStatus.value = r.data;
  return r.data;
}

export function FirstSignalPanel({ keyId, aiSystemId, onArrived }: Props) {
  useEffect(() => {
    // Reset module state when a new key_id is mounted (e.g. user re-runs setup).
    lastStatus.value = null;
    pollError.value = null;
    startedAt.value = Date.now();
    tick.value = 0;
    let stopped = false;
    let arrivedFired = false;

    async function loop(): Promise<void> {
      const status = await pollOnce(keyId);
      tick.value += 1;
      if (status?.first_seen_at && !arrivedFired) {
        arrivedFired = true;
        onArrived?.();
        return;  // stop polling — single edge transition is all we need
      }
      if (!stopped) {
        timer = window.setTimeout(loop, POLL_INTERVAL_MS);
      }
    }

    let timer = window.setTimeout(loop, 0);
    // Re-render every second so the elapsed timer + stall threshold update
    // even between polls.
    const heartbeat = window.setInterval(() => { tick.value += 1; }, 1000);

    return () => {
      stopped = true;
      window.clearTimeout(timer);
      window.clearInterval(heartbeat);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [keyId]);

  const status = lastStatus.value;
  const elapsedMs = computed(() => Math.max(0, Date.now() - startedAt.value)).value;
  void tick.value;  // signal subscription for re-render

  const arrived = !!status?.first_seen_at;
  const stalled = !arrived && elapsedMs > STALL_THRESHOLD_MS;

  return (
    <div class="card" style={{ marginTop: '0.75rem' }}>
      <div class="card-header">
        <div>
          <div class="card-title">3 · Verify — first SDK signal</div>
          <div class="card-subtitle">
            The wizard finishes once the engine has received its first HMAC-authed call from this key.
          </div>
        </div>
      </div>
      <div style={{ padding: '1rem 1.25rem' }}>
        {arrived && status ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <span style={{
              display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
              width: '28px', height: '28px', borderRadius: '50%',
              background: 'var(--success-bg, #14532d)', color: 'var(--success-fg, #4ade80)',
              fontSize: '16px', fontWeight: 700,
            }}>✓</span>
            <div>
              <div style={{ fontWeight: 600 }}>
                First signal received at {new Date(status.first_seen_at!).toLocaleTimeString()}
              </div>
              <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '2px' }}>
                Calls in last 24h: <strong>{status.total_calls_24h}</strong>.{' '}
                <a href={`/runtime?system=${encodeURIComponent(aiSystemId)}`}>View runtime →</a>
              </div>
            </div>
          </div>
        ) : stalled ? (
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <span style={{ color: 'var(--warning-fg, #f59e0b)', fontSize: '18px' }}>⚠</span>
              <strong>Still no signal after {Math.round(elapsedMs / 1000)}s.</strong>
            </div>
            <ul style={{ margin: '0.5rem 0 0 1.25rem', fontSize: '13px', lineHeight: 1.7 }}>
              <li>Confirm <code>SL_API_KEY</code> matches the <code>hmac_secret</code> shown in Step 1.</li>
              <li>Confirm <code>SL_API_BASE_URL</code> points at this engine (not localhost).</li>
              <li>Confirm <code>signallayer.guard()</code> didn't raise <em>DecoratorOrderError</em> at import time.</li>
              <li>Make at least one real LLM call — initialisation alone doesn't produce a trace.</li>
            </ul>
            {pollError.value && (
              <div class="error-banner" style={{ marginTop: '0.5rem' }}>
                Poll error: {pollError.value}
              </div>
            )}
          </div>
        ) : (
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <span class="spinner" aria-hidden="true" style={{
              display: 'inline-block', width: '18px', height: '18px',
              border: '2px solid var(--border-strong)', borderTopColor: 'var(--accent)',
              borderRadius: '50%', animation: 'spin 0.8s linear infinite',
            }} />
            <div>
              <div style={{ fontWeight: 600 }}>Waiting for first SDK call…</div>
              <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '2px' }}>
                Usually arrives within 30s of <code>signallayer.init()</code>. Elapsed: {Math.round(elapsedMs / 1000)}s.
              </div>
              {pollError.value && (
                <div style={{ color: 'var(--danger-fg, #f87171)', fontSize: '12px', marginTop: '4px' }}>
                  {pollError.value}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
