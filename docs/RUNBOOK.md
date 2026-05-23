# Operational Runbook — AI Assurance Platform

**Version:** Session 10
**Last updated:** 2026-05-22
**On-call contact:** praveen@signallayer.ai

---

## 1. Alert definitions and escalation

### alert-pii-leak

**What it means:** The injection guard detected and counted a PII leak attempt.
Even a single event in 5 minutes fires this alert because the presence of
any attempt is significant — it may indicate a prompt-injection attack or a
mis-configured integration sending raw PII.

**Who to page:** CISO immediately. Also notify the affected tenant's data
steward if the `vault_id` is known from logs.

**First response:**
1. Pull recent injection guard logs:
   ```kql
   traces | where message contains "pii_leak" | order by timestamp desc | take 50
   ```
2. Check whether the PII was scrubbed before reaching Langfuse (verify
   `scrub_pii_detected_total` counter incremented in the same window).
3. If raw PII reached Langfuse: escalate to incident, open DSAR review.

---

### alert-opa-unreachable

**What it means:** The OPA policy sidecar failed to respond and the fallback
path was taken. Default-DENY is still active, but policy audit trails are
degraded — OPA decisions are not being logged.

**Who to page:** Platform on-call engineer.

**First response:**
1. Check OPA sidecar health: `curl http://localhost:8181/health`
2. Restart sidecar if unresponsive: `systemctl restart opa` (Linux) or
   restart the container.
3. Verify OPA bundle load: `curl http://localhost:8181/v1/policies`

---

### alert-vault-error

**What it means:** More than 5 Fernet decryption failures occurred in 15
minutes in the de-identification vault. Likely cause: key rotation without
re-encrypting existing tokens, or file corruption.

**Who to page:** Platform on-call engineer + CISO if it persists > 30 min.

**First response:**
1. Check the `DEID_VAULT_KEY` environment variable matches the active key in
   `data/deid_vault.jsonl`.
2. If recently rotated: run the key-rotation reconciliation script (not yet
   implemented — manual check of vault entries required, see Session 11).
3. Do NOT delete vault entries — they contain reversible de-id mappings.

---

### alert-audit-chain-broken

**What it means:** `verify_chain` returned a status other than `CLEAN`. The
tamper-evident hash chain in `data/events.jsonl` has a break. This is a
high-severity integrity event.

**Who to page:** CISO immediately. Legal/Compliance if the platform is
under active regulatory review.

**First response:**
1. Do NOT write new events until the break is understood.
2. Run chain verification: `python -c "from domain.audit_chain import verify_chain; print(verify_chain(full=True))"`
3. Identify the broken link index from the output.
4. Preserve the raw file: `cp data/events.jsonl data/events_$(date +%s).jsonl`
5. Escalate — do not attempt self-repair without CISO sign-off.

---

### alert-http-5xx-rate

**What it means:** More than 1% of HTTP requests returned 5xx in 5 minutes.
Normal baseline is 0%; any sustained 5xx rate indicates a broken route,
unhandled exception, or dependency failure (Postgres, OPA, vault).

**Who to page:** Platform on-call engineer.

**First response:**
1. Check App Insights failures blade for the most frequent exception.
2. Check dependency calls: `dependencies | where success == false | order by timestamp desc | take 20`
3. Restart the App Service if exceptions are systemic and cause is unclear.

---

### alert-p95-latency

**What it means:** 95th percentile response latency exceeded 2 seconds in
5 minutes. LLM calls (Claude) are excluded from p95 expectations — this
alert fires for the non-LLM route latency.

**Who to page:** Platform on-call engineer.

**First response:**
1. Check for slow database queries: `dependencies | where type == "SQL" | order by duration desc | take 20`
2. Check for audit chain O(n) re-reads (Session 08 debt — should be fixed
   with prev_hash cache, but verify).
3. Check App Service CPU/memory utilisation — B1 has 1 vCPU; sustained LLM
   traffic can saturate it.

---

### alert-rtf-partial-failure

**What it means:** A Right-to-Forget cascade completed with
`PARTIAL_FAILURE` — at least one data store was not purged. Subject data
may remain in the system contrary to the erasure request.

**Who to page:** CISO + data steward for the affected subject.

**First response:**
1. Identify the cascade: `customMetrics | where name == "rtf_cascade_total" | where customDimensions["status"] == "PARTIAL_FAILURE" | order by timestamp desc | take 5`
2. Check the RTF sidecar index: `data/rtf_completed_index.jsonl` for the
   cascade record with `status=PARTIAL_FAILURE`.
3. Manually re-trigger the failed store purge. See `domain/right_to_forget.py`
   for individual store purge functions.
4. Log a DSAR exception with timestamp and remediation steps.

---

### alert-scrub-rate-regression

**What it means:** The ratio of PII scrub events to total requests dropped
below 0.5 over 30 minutes. Either the scrubber is being bypassed, a new
route is not decorated with `@scrub_pii`, or the scrubber is silently failing.

**Who to page:** Platform on-call engineer.

**First response:**
1. Check for new routes added without the decorator chain.
2. Verify the scrubber middleware is active: tail the structured log for
   `record_scrub` entries.
3. Check for silent exceptions in `middleware/scrubber.py` — scrubber errors
   are caught and logged but do not block requests.

---

## 2. Rollback steps

### Standard rollback (git revert + redeploy)

```bash
# 1. Identify the last known-good commit
git log --oneline -10

# 2. Revert the bad commit (creates a new revert commit — safe)
git revert <bad-commit-sha> --no-edit

# 3. Push to main
git push origin main

# 4. Redeploy (assumes deploy/deploy-all.ps1 is current)
pwsh deploy/deploy-all.ps1
```

### Emergency: roll back App Service deployment slot

If blue/green slots are configured (Session 12 target):
```bash
az webapp deployment slot swap \
  --name app-aigovern-dev \
  --resource-group rg-aigovern-dev \
  --slot staging \
  --target-slot production
```

Session 10 does not have slots configured. Use the git revert path above.

### Roll back Bicep IaC changes

Bicep is idempotent. Re-deploying the previous `main.bicep` will converge
the infrastructure back. Do NOT delete alert rules manually — re-deploy
the prior alerts.bicep instead.

---

## 3. Common operational KQL queries

### Trace lookup by request_id

```kql
traces
| where customDimensions["request_id"] == "<your-request-id>"
| order by timestamp asc
| project timestamp, severityLevel, message, customDimensions
```

### Recent PII detections (last 1 hour)

```kql
customMetrics
| where name == "pii_leak_attempt_total"
| where timestamp > ago(1h)
| summarize TotalAttempts = sum(value) by bin(timestamp, 5m)
| order by timestamp desc
```

### RTF cascade audit trail for a subject

```kql
traces
| where message contains "rtf_cascade" or message contains "right_to_forget"
| where customDimensions["vault_id"] == "<subject-vault-id>"
| order by timestamp asc
| project timestamp, message, customDimensions
```

### Audit chain break events

```kql
customMetrics
| where name == "audit_chain_break_total"
| where value > 0
| order by timestamp desc
| project timestamp, value, customDimensions
```

### OPA unreachable events with surrounding context

```kql
customMetrics
| where name == "opa_unreachable_total"
| where timestamp > ago(24h)
| join kind=leftouter (
    requests
    | where timestamp > ago(24h)
  ) on $left.timestamp == $right.timestamp
| project timestamp, opa_value = value, request_url = url, request_duration = duration
```

---

## 4. Azure Artifacts feed provisioning checklist (deferred from Session 09)

This checklist captures the steps required when the internal Python SDK feed
is activated. Currently deferred — the SDK ships as a local directory install.
Activate for Session 12 or Phase 2 production hardening.

1. **Create the Artifacts feed**
   ```bash
   az artifacts feed create \
     --name signallayer-python \
     --organization https://dev.azure.com/signallayer \
     --project ai-assurance
   ```

2. **Configure `~/.pypirc`** on the build agent with the feed URL and PAT:
   ```ini
   [distutils]
   index-servers = signallayer

   [signallayer]
   repository = https://pkgs.dev.azure.com/signallayer/ai-assurance/_packaging/signallayer-python/pypi/upload/
   username = __token__
   password = <PAT with Packaging Read+Write>
   ```

3. **Publish the SDK**
   ```bash
   cd sdk
   python -m build
   twine upload -r signallayer dist/*
   ```

4. **Update `requirements.txt`** to reference the feed instead of the local path:
   ```
   --extra-index-url https://pkgs.dev.azure.com/signallayer/ai-assurance/_packaging/signallayer-python/pypi/simple/
   signallayer-client>=1.0.0
   ```

5. **Add the feed URL as an App Service app setting**:
   ```bash
   az webapp config appsettings set \
     --name app-aigovern-dev \
     --resource-group rg-aigovern-dev \
     --settings PIP_EXTRA_INDEX_URL="https://pkgs.dev.azure.com/..."
   ```

6. **Rotate the PAT** every 90 days. Add a calendar reminder in the Azure
   DevOps PAT management panel. Expired PAT = failed deployment = outage.

---

## 5. STRICT_HMAC_BOOT toggle

**What it does:** When `STRICT_HMAC_BOOT=true`, `middleware/hmac_auth.py`
reads the HMAC signing secret (`HMAC_SECRET`) at module import time and
raises `RuntimeError` immediately if the variable is absent or empty.

**Default (dev):** `STRICT_HMAC_BOOT=false` — the middleware starts without
a secret and all HMAC-gated routes return 401, but the application does not
crash. Useful for local development where SDK routes are not exercised.

**Production:** Set `STRICT_HMAC_BOOT=true`. A missing secret on a production
node is a misconfiguration that should fail loudly at startup rather than
silently serving 401s.

**Toggling:**
```bash
# Enable strict boot (production)
az webapp config appsettings set \
  --name app-aigovern-dev \
  --resource-group rg-aigovern-dev \
  --settings STRICT_HMAC_BOOT=true

# Disable for local dev
export STRICT_HMAC_BOOT=false
```

**Rollback if strict boot is preventing startup:** Set `STRICT_HMAC_BOOT=false`
and verify `HMAC_SECRET` is populated in app settings before re-enabling.


---

## Demo operations (Session 11)

Live demo orchestration for the 6 scenarios in `12-DAY-PRODUCTION-SPRINT.md` §7.

### Access

- URL: `/demo-control` (served from `static/demo-control.html`)
- API prefix: `/api/demo-control`
- Required role: `demo-operator` or `ciso`. In dev mode (`AUTH_ENABLED=false`) set the `X-Role: demo-operator` header.

### Pre-demo checklist (run T-60 minutes)

1. Bicep deployment current: `az deployment group list -g rg-aigovern-dev --query "[?contains(name,'main')] | [0].properties.timestamp" -o tsv` shows a date within the last 24h.
2. App Insights connection string is set on the app: `az functionapp config appsettings list -n app-aigovern-dev -g rg-aigovern-dev --query "[?name=='APPLICATIONINSIGHTS_CONNECTION_STRING'].value" -o tsv` returns a value.
3. At least 8 alerts are present: `az monitor scheduled-query list -g rg-aigovern-dev --query "length(@)"` >= 8.
4. Smoke pass within the last hour: `$env:SMOKE_TARGET_URL=...; pwsh deploy/smoke_e2e.ps1` exits 0.
5. Load-test report is < 24h old (`reports/load_test_*.json` timestamp).
6. OPA bundle is current: `curl -s https://aigovern.azurewebsites.net/api/policy/bundle/version` matches `policies/main/.version`.
7. Langfuse healthy: `curl -s -o /dev/null -w "%{http_code}" https://cloud.langfuse.com/api/public/health` == 200.
8. Vault TTL configured: `az functionapp config appsettings list ... --query "[?name=='VAULT_TTL_DAYS'].value"` returns a positive integer.
9. RTF sidecar HMAC counter clean: query Prometheus `rtf_sidecar_unsigned_total` is 0 (no unsigned legacy entries remain).
10. All 6 demo scenarios green within the last hour: trigger `POST /api/demo-control/run/{id}` for each, status terminates as `completed`.

### Mid-demo failure recovery

If a scenario fails live:

1. `pii-pipeline-live` — say "the scrubber is the runtime tripwire; if it ever fails we drop the trace and alert. Watch the alert fire." Open App Insights and show `pii_scrub_failure_total > 0`.
2. `gate-failure-recovery` — say "the gate just fail-closed, which is exactly what should happen. Let me show the OPA decision log." Click the audit-events page.
3. `reusable-agent-upgrade` — say "the publish event is on the chain; the subscriber notification is polled. Let me show the event." Show `events.jsonl` tail.
4. `rtf-cascade` — say "the cascade is idempotent; the partial-failure state is the safe state. Re-trigger and show recovery." Re-run the same `cascade_id`.
5. `evals-degradation` — say "the trend uses the last full day; if the demo eval set is sparse the chart will be flat. The mechanism is real; data volume in the demo system is limited." Open the `/evals` dashboard.
6. `framework-coverage-export` — say "the pack generator is deterministic; if it failed it's a missing dependency, not the framework logic. Let me show the YAML coverage source." Open `frameworks/nist-ai-rmf.yaml`.

### Related docs

- Q&A prep: [`docs/DEMO-QA.md`](DEMO-QA.md)
- Scenario talk tracks: [`docs/demo-scripts/`](demo-scripts/)
- Architecture: [`ARCHITECTURE.md`](../ARCHITECTURE.md)
- Locked decisions: [`DECISIONS.md`](../DECISIONS.md)
