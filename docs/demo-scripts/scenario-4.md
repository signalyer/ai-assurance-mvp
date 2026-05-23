# Scenario 4 — Cross-team · Right-to-Forget Cascade

**Audience cue:** GDPR Article 17 / CCPA — prove every store actually purged, with cryptographic verification.
**Real components exercised:** `domain/right_to_forget.py::cascade` · Fernet vault purge · Tier 2 episodic purge · Tier 3 RAG delete-by-source-id · Langfuse trace delete · HMAC-signed sidecar (`data/rtf_completed_index.jsonl`) — new in Session 11.
**Duration:** ~45s.

## Talk track

"A customer — `demo-customer-9999` — has exercised their right to erasure. I trigger the cascade with one call."

"Four stores purge in order: vault first, because every other store references its tokens; Tier 2 episodic memory in Postgres; Tier 3 RAG in Azure AI Search by `source_id` filter; finally Langfuse via API delete. The result panel shows each `PurgeResult` with `items_removed` and a SHA-256 digest of the post-state — that's the verification an auditor needs. The whole cascade is captured as a single tamper-evident event on the audit chain."

"Two Session-11 hardening callouts: the sidecar that tracks completed cascades is now HMAC-signed, so an attacker who writes to the data directory can't mark a fresh subject as 'already purged' to suppress a real RTF request. Unsigned legacy entries get rejected with a warning and the reader falls back to scanning `events.jsonl`."

## What's NOT shown

- The actual Langfuse-side delete confirmation UI — out of scope.
- Replay-from-backups purge — operational runbook, not in the demo path.

## If asked

- *"What if Langfuse is unreachable?"* — Cascade marks Langfuse step `PARTIAL_FAILURE`, retries via outbox, full cascade stays in `RTF_CASCADE_FAILED` state until Langfuse confirms.
- *"What proves the SHA-256 wasn't faked?"* — The digest is computed over post-state by the store itself, then committed to the chained audit log. Replaying the chain reproduces it; mutation breaks the chain.
