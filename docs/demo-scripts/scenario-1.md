# Scenario 1 — Team Risk · Live PII Pipeline

**Audience cue:** the auditor in the room wants to see a real PII string disappear before it ever reaches a third-party service.
**Real components exercised:** Presidio detector · 12 regex patterns · Fernet vault (`domain/deid_vault.py`) · `@scrub_pii` decorator · Langfuse trace sink (or local fallback).
**Duration:** ~15s.

## Talk track

"Here's an inbound request that contains a customer's SSN, phone number, and account number. Watch what happens when I trigger the live PII pipeline. The decorator chain fires `@scrub_pii` before anything else — Presidio plus our 12 regex patterns tokenize every sensitive value, the raw mapping goes into a Fernet-encrypted vault on disk, and only the tokens flow downstream."

"You'll see the scrubbed payload in the result panel — `[SSN_001]`, `[PHONE_001]`. The Langfuse trace ID below the result links to the trace; click it and you'll see the same tokens, never the raw values. That's the guarantee we make: Langfuse — or any other downstream — never sees raw PII. Not as a policy. As a structural constraint enforced by the decorator order at decoration time."

## What's NOT shown

- Real-time per-token TTL inspection — Phase 2 UI.
- Cross-region Key Vault failover — single-region in v1.

## If asked

- *"What if Presidio misses a pattern?"* — The DeepEval `pii_leak` scorer runs post-hoc on the trace itself; counter `pii_leak_total` is monitored with alert threshold > 0.
- *"How long does the vault keep tokens?"* — Configurable TTL per workload, default 30 days. RTF cascade deletes them on request regardless of TTL.
- *"Can the operator see raw PII?"* — Only via the audited `vault_decrypt` endpoint, which requires `ciso` role and is logged.
