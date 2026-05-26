// Onboarding wizard (S53) — shared response types for /api/sdk-keys/*.
//
// Mirrors api/sdk_keys.py response models. Kept colocated with the
// onboarding page (not exported via shared/types) because no other surface
// in the SPA consumes these — the SDK Quickstart page is system-only, not
// key-aware.

export interface IssuedKey {
  id: string;
  key_id: string;
  hmac_secret: string;       // Plaintext — shown ONCE, then discarded from in-memory state.
  ai_system_id: string;
  data_source: 'seed' | 'real';
  issued_by: string;
  issued_at: string;
}

export interface KeyStatus {
  key_id: string;
  ai_system_id: string;
  issued_at: string;
  first_seen_at: string | null;
  revoked_at: string | null;
  total_calls_24h: number;
}
