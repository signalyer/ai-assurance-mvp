# Resume — vendor_risk SOP S82f-1b (verification + 25 STAGED calibration runs)

## Where I am
S82f-1 shipped: commit `37bd6e7` on origin/main, deployed cleanly to
`app-aigovern-dev` at 2026-06-01 16:37 UTC (CI run `26768240573`, 1m17s).
`/api/health` confirms `sha=37bd6e7e2c65c81550ca81739b1fad154ca0a1d0`.

S82f-1b's job is operator verification of the bootstrap effects + the
25 STAGED calibration runs (12 EXT + 13 INT) → write
`docs/sop-vendor-risk/07-staged-calibration-log.md`.

## What landed in S82f-1 (read these as background)
- `domain/ai_system_edit.py` — `transition_runtime_status()`,
  `promote_to_staged()`, `current_runtime_status()`, `ALLOWED_RUNTIME_TRANSITIONS`,
  append-only `data/ai_system_lifecycle.jsonl`
- `domain/repository.py` — `_fold_runtime_status()` overlays lifecycle
  events on `AISystem.runtime_status` (mirrors findings-event fold)
- `agents/vendor_risk/onboarding/sdk_provisioning.py` — NEW. Catalog +
  SDK keys + DESIGN→STAGED, all idempotent. Synthetic actor
  `system:bootstrap` writes `_BOOTSTRAP_REASON` into every lifecycle event
- `dashboard.py` lifespan — calls `ensure_vendor_risk_provisioning()`
  AFTER `ensure_vendor_risk_systems()` (ordering matters)
- `domain/telemetry_links.py` + `domain/agent_runner.py` — App Insights
  operation_id deep-link in chain `audit` event (Langfuse URL still
  None until S83 wires real trace_id)
- `agents/vendor_risk/agent.py::assert_no_egress` — defense-in-depth
  context manager. PRIMITIVE ONLY; INT path doesn't call it yet
  (S82f-2 work alongside local-provider swap)

## First-thing operator verification (5 min)

### A. ssh into the running container
```
az webapp ssh --name app-aigovern-dev --resource-group rg-aigovern-dev
```

### B. Confirm bootstrap effects landed
```bash
# Lifecycle log: expect exactly 2 RUNTIME_STATUS_CHANGED events
cat /home/data/ai_system_lifecycle.jsonl

# Expect ai_system_id ∈ {sys-vendor-risk-ext-001, sys-vendor-risk-int-001}
# from_status=DESIGN to_status=STAGED actor=system:bootstrap

# SDK key store: expect at least 2 new rows for the vendor_risk systems
grep -c "sys-vendor-risk-" /home/data/sdk_keys.jsonl

# Plaintext secret handoff (0600, only readable by the App Service identity)
ls -la /home/.s82f-secrets-sys-vendor-risk-*.txt
```

### C. Pull + record the SDK keys, then DELETE the plaintext files
```bash
cat /home/.s82f-secrets-sys-vendor-risk-ext-001.txt   # copy to secure store
cat /home/.s82f-secrets-sys-vendor-risk-int-001.txt   # copy to secure store
rm /home/.s82f-secrets-sys-vendor-risk-ext-001.txt
rm /home/.s82f-secrets-sys-vendor-risk-int-001.txt
```

Per the project rule, plaintext secrets must not loiter. Once they're in
your local secure store / Key Vault, delete the on-disk copies.

### D. Confirm via authenticated APIs (browser session in CISO Console)
- `GET /api/agents` → vendor_risk row exists (team=risk, owner_type=REUSABLE, inherent_risk=HIGH)
- `GET /api/systems/sys-vendor-risk-ext-001` → `runtime_status: "STAGED"`
- `GET /api/systems/sys-vendor-risk-int-001` → `runtime_status: "STAGED"`
- AI Systems page in CISO Console lists both as STAGED

If any of these are wrong, fall back to the diagnostic table below.

## Calibration sequence (25 runs)

Locked decisions from S82f handoff:
- **Live runs** (not synthetic) — calibration is the worked example
- **Shared EXT operation_id schema** with `system_id` as a custom dim
- WebJob host for 6h eval cron deferred to S82f-2

### 12 EXT runs (sys-vendor-risk-ext-001)
Vendor fixtures: 4 SaaS analytics, 4 model providers, 4 infra. Each run
captures: prompt, response, risk_tier, latency_ms, langfuse trace URL
(once S83 wires it), App Insights operation_id (already on the event).

### 13 INT runs (sys-vendor-risk-int-001)
Internal-vendor fixtures: 5 acquisition-target, 4 subsidiary, 4
in-flight integrations. Same capture schema as EXT.

**IMPORTANT** — the INT path TODAY still calls Anthropic. The
`assert_no_egress()` primitive exists but isn't wired into the INT
execution path because the local-provider swap is S82f-2 work. For S82f-1b
calibration, the INT runs WILL make outbound network calls — this is a
known temporary contradiction with the INT system contract. Record this
caveat in the calibration log header (`07-staged-calibration-log.md`).

### Calibration log shape (`docs/sop-vendor-risk/07-staged-calibration-log.md`)
```
# 07 — Staged Calibration Log (S82f-1b)

## Header
- Date range: <start>..<end>
- Deploy SHA at start: 37bd6e7
- Caveats:
  - INT path still calls Anthropic (S82f-2 will fix); 13 INT runs
    consumed external API quota in this window
  - Langfuse URL = None on all events; S83 wires real trace_id

## Per-run table
| run_id | system_id | fixture | risk_tier | latency_ms | operation_id | notes |
| ...    | ...       | ...     | ...       | ...        | ...          | ...   |

## Aggregate
- EXT runs: 12 ; risk_tier distribution: ...
- INT runs: 13 ; risk_tier distribution: ...
- Mean latency EXT vs INT: ...
- Failures / retries / escalation_triggered: ...

## Threshold proposals for S82f-2 lock
- ...
```

## Diagnostic table — if bootstrap effects are missing

| Symptom                                | Likely cause                                  | Fix                                                                |
|----------------------------------------|-----------------------------------------------|--------------------------------------------------------------------|
| `ai_system_lifecycle.jsonl` missing    | `ensure_vendor_risk_provisioning` failed early | Check App Insights for `[startup] vendor_risk provisioning failed (non-fatal)` |
| Catalog row missing in `/api/agents`   | Postgres DATABASE_URL unset → in-memory only   | Verify env; cold-start re-runs but in-memory storage is per-worker |
| SDK key already revoked, no new mint   | `list_keys(include_revoked=False)` saw 0       | Manually revoke remaining + restart container to re-mint           |
| Secret file at `/home/.s82f-secrets-*` not present | Container restarted before bootstrap, OR write failed | `az webapp restart` then re-ssh; if still missing, run sdk_provisioning via Kudu REPL |
| `runtime_status` shows DESIGN in API   | Fold-on-read regression; lifecycle log might exist but `_fold_runtime_status` not wired | Re-read `domain/repository.py:55-72` |
| RUNTIME_STATUS_CHANGED has wrong from_status | `base_status` wiring picked up folded value not raw record | Re-read `sdk_provisioning._promote_system` |

## Files to load
- `agents/vendor_risk/onboarding/sdk_provisioning.py` (this session's main deliverable)
- `domain/ai_system_edit.py` lines 489+ (governed transitions section)
- `domain/repository.py` lines 38-72 (fold-on-read)
- `docs/sop-vendor-risk/00-intent.md`
- `docs/SOP-agent-onboarding.md` Phases 7 + 8

## Outstanding architectural items (for S82f-2)
1. INT execution path doesn't yet call `assert_no_egress()` — needs
   local-model provider swap so the assertion can fire honestly
2. Langfuse URL builder returns None until real trace_id flows through
   chain (S83 marker in agent_runner.py line ~437)
3. Kudu auth (401 on basic-auth-from-publishing-creds) — still a thorn;
   bootstrap pattern sidesteps it but verification still needs `az webapp ssh`
4. The 6h eval cron WebJob host (S82f-2)

## Working rules in effect
Project CLAUDE.md + global CLAUDE.md unchanged. Decorator chain order:
`@policy_gate → @scrub_pii → @guardrails → @trace_llm_call → @evaluate_response`.
Anthropic streaming for any `TOKEN_BUDGETS > 2000`. Project 2026-06-01
rules apply (eager-import → INCLUDE; new agent → catalog seed).
Auto Mode.

## Token budget
S82f-1b: ~300-400K (Review Required band — calibration runs + log doc).

## Next concrete action
ssh in, run steps B + C above, then begin EXT calibration runs.
