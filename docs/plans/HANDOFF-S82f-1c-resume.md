# Resume — vendor_risk SOP S82f-1c (18 STAGED calibration runs)

## Where I am

S82f-1b closed cleanly with one unexpected piece of work: post-deploy
verification found that S82f-1's `_write_plaintext_secret()` shipped
SDK secrets to `/home/.s82f-secrets-*.txt` at mode **0777**, not 0600.
Root cause: App Service Linux mounts `/home` via Azure Files (CIFS)
with a fixed permissive umask; `os.chmod(path, 0o600)` silently no-ops.

Fix landed in commit `f171f6d` (deployed clean to `app-aigovern-dev`,
sha verified at `/api/health`):

- `_write_plaintext_secret()` → `_emit_plaintext_secret()`: single
  CRITICAL log line tagged `SECRET_BOOTSTRAP_DO_NOT_LEAK`, captured
  by App Insights via the GA `azure-monitor-opentelemetry` distro.
- CLAUDE.md rule (2026-06-01) added under compound-engineering section.
- Memory entry `appservice-home-permissions` written.

End-to-end proof: revoked both original keys via
`POST /api/sdk-keys/{key_id}/revoke` (CISO session), restarted app via
`az webapp restart`, lifespan re-bootstrap minted fresh keys and emitted
plaintext to App Insights traces. Retrieved via Kusto query against
`appi-aigovern-dev`. Stale `/home/.s82f-secrets-*.txt` files deleted.

## Decisions already made (don't re-litigate)

- Bootstrap secret handoff path is **App Insights tagged log**, not
  `/home`. Future agents follow this pattern.
- The two NEW SDK secrets leaked into the S82f-1b transcript (I ran the
  Kusto query from the agent context). **They must be rotated before
  this work is considered done.** This is queued as the first task of
  S82f-1c — revoke + remint + retrieve via App Insights from a portal
  session you control, NOT from a Claude tool call.
- Spec discrepancy resolved by record: handoff said 25 runs
  (12 EXT + 13 INT), the actual dataset
  (`agents/vendor_risk/eval/dataset-external.jsonl` +
  `dataset-internal.jsonl`) has **18 cases (10 EXT + 8 INT)**.
  Calibration log header must document this honestly. Building the
  missing 7 fixtures is out of scope for S82f-1c.

## Current state on disk + in cloud

- Engine sha: `f171f6d7739b31374b36afd134e591b31d5642e5`
- Vendor_risk systems: `sys-vendor-risk-ext-001`, `sys-vendor-risk-int-001`
  — both runtime_status STAGED via fold-on-read from
  `ai_system_lifecycle.jsonl`
- Active SDK keys (TO ROTATE FIRST in S82f-1c):
  - `slk_b3aebe21` → `sys-vendor-risk-ext-001`, issued 2026-06-01T17:07:52Z
  - `slk_7e903e17` → `sys-vendor-risk-int-001`, issued 2026-06-01T17:07:52Z
- Revoked SDK keys:
  - `slk_24d5e1f1` (revoked 17:05:56)
  - `slk_8d8d1bf9` (revoked 17:05:56)
- `/home/.s82f-secrets-*.txt`: deleted

## Key files to load

- `docs/plans/HANDOFF-S82f-1b-resume.md` — the prior handoff (calibration
  log shape spec, diagnostic table, 25-run breakdown — read for the
  intended structure, but apply to 18 actual cases)
- `agents/vendor_risk/eval/dataset-external.jsonl` (10 cases) +
  `dataset-internal.jsonl` (8 cases) — the calibration corpus
- `agents/vendor_risk/eval/run_eval.py` — eval-mode runner; calibration
  is LIVE SDK-path runs, not eval-mode, but the dataset shape is shared
- `agents/vendor_risk/agent.py` — the agent under calibration; INT path
  still calls Anthropic (S82f-2 will swap to local-deterministic)
- `agents/vendor_risk/onboarding/sdk_provisioning.py` — patched secret
  handoff (the new tagged-log mechanism)
- `domain/ai_system_lifecycle.jsonl` (on `/home/data/` in App Service)
  — runtime_status events the calibration runs will not modify
- `CLAUDE.md` — new rule 2026-06-01 "Never persist secrets to App Service
  `/home`"

## Outstanding questions (need user input)

1. **Where do calibration runs ORIGINATE from for the call chain?**
   Local laptop via signallayer SDK package, or scripted from the agent
   itself? S82f-1b assumed scripted HMAC-signed curl from Claude tooling
   — confirm or override.
2. **Per-run output viewer:** the agent's structured response (tier,
   concerns, mitigations, citations) has no portal UI surface. Calibration
   runs WILL land in the audit chain but the structured payload is
   visible only via raw JSONL. Acceptable for STAGED, or block on a
   minimal `/api/agent-runs/{id}` detail endpoint first?

## Next concrete actions (in order)

1. **Rotate the two leaked secrets first.** Revoke `slk_b3aebe21` and
   `slk_7e903e17` via `POST /api/sdk-keys/{key_id}/revoke` (CISO session
   cookie). Restart app. Retrieve new secrets via App Insights Kusto
   query **YOU run in your own portal session**:
   ```kusto
   traces
   | where timestamp > ago(15m)
   | where message contains "SECRET_BOOTSTRAP_DO_NOT_LEAK"
   | project timestamp, message
   | order by timestamp desc
   ```
2. **Resolve the call-origin question** (#1 above) before any live run.
3. **Build the calibration log skeleton.**
   `docs/sop-vendor-risk/07-staged-calibration-log.md` with header
   recording the three known caveats:
   - INT path still calls Anthropic (S82f-2 will fix)
   - Langfuse URLs are None on all events (S83 will fix)
   - Dataset is 18 not 25 (handoff drift; 7 fixtures missing)
4. **Drive 10 EXT runs sequentially**, append per-run row to the
   calibration log with: `run_id`, `system_id`, `fixture_id`,
   `risk_tier` (vs expected), `latency_ms`, App Insights `operation_id`,
   `notes`.
5. **Drive 8 INT runs sequentially**, same shape. Verify
   `assert_no_egress()` is NOT yet wired (S82f-2 task) — flag any
   surprise.
6. **Audit-chain verification per run:** confirm a row landed in
   `/home/data/audit_chain.jsonl` with the matching trace correlation.
7. **Roll-up section** in the calibration log: pass-rate vs eval
   thresholds, distribution of `risk_tier`, any threshold breaches,
   recommendation to lock or iterate.

## Working rules in effect

- Global `~/.claude/CLAUDE.md` SESSION MANAGEMENT (60% compact rule,
  workflow bands, etc.)
- Project `CLAUDE.md` — including new 2026-06-01 rule on `/home`
  permissions. Decorator chain:
  `@policy_gate → @scrub_pii → @guardrails → @trace_llm_call → @evaluate_response`
- Anthropic streaming required for `max_tokens > 2000`
  ([[anthropic-max-tokens-streaming-threshold]])
- JSONL writes only via `storage.py` (`_append_jsonl` / `_read_jsonl`)
- Per `[[run-commands-dont-defer]]`: execute via tools where you have
  perms; for secret-bearing operations (Kusto for plaintext retrieval),
  hand the operator the query rather than running it from the agent
  context — that was the lesson of S82f-1b's transcript leak

## Token budget for S82f-1c

Likely Refactoring/Testing-band shaped (mostly live calls + log appends,
not exploration). Target Normal band. The 18-run sequence + per-run
verification should fit cleanly inside one session.
