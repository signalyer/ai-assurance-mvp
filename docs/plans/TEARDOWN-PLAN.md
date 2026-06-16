# Prod Teardown Plan — aigovern.sandboxhub.co

**Scope:** All 26 resources in `rg-aigovern-dev` (subscription `SignalLayerDev`).
**Drivers:** Cost containment between demos · environment refresh · disaster recovery rehearsal.
**Status:** Plan only. No scripts written yet. Awaiting mode selection.

---

## 0. What's in prod right now

| Group | Resource | Type | Region | Monthly $ | Tear-down posture |
|---|---|---|---|---:|---|
| **Compute** | `asp-aigovern-dev` | App Service Plan P1V3 Linux | westus2 | $340 | Stop slot then delete plan |
| | `app-aigovern-dev` | App Service (engine) | westus2 | (in plan) | Stop → delete |
| | `app-aigovern-dev/staging` | Slot | westus2 | (in plan) | Stop → delete |
| | `psql-aigovern-dev` | Postgres Flexible B2ms | westus2 | $130 | **Stop** (free, 7-day) → snapshot → delete |
| | `search-aigovern-dev` | Azure AI Search Basic | eastus | $75 | No native stop · export index → delete |
| **Edge** | `aigovern.sandboxhub.co` | App Service managed cert | westus2 | ~$0 | Unbind → delete (auto on app delete) |
| | `api.aigovern.sandboxhub.co` | App Service managed cert | westus2 | ~$0 | Unbind → delete |
| **SPAs** | `swa-aigovern-portal-dev` | Static Web App (Free tier) | eastus2 | $0 | Delete (CNAME to leave dangling — fix DNS) |
| | `swa-aigovern-gov-dev` | Static Web App (Free tier) | eastus2 | $0 | Delete |
| **Secrets** | `kv-aigovern-sl-dev` | Key Vault Standard | eastus | $5 | Soft-delete by default (90-day recovery) · **never purge** |
| **Observability** | `log-aigovern-dev` | Log Analytics | eastus | $15 | Export queries → delete |
| | `log-aigovern-prod` | Log Analytics | eastus | $15 | Export queries → delete |
| | `appi-aigovern-dev` | App Insights | eastus | $20 | Continuous export → delete |
| | `appi-aigovern-prod` | App Insights | eastus | $10 | Export → delete |
| | `ag-aigovern-dev` | Action Group | global | ~$0 | Delete |
| | 7 metric alerts | Scheduled Query Rules | eastus | ~$1 | Delete (auto on workspace delete) |
| | 2 Smart Detection | Insights addon | global | $0 | Auto-deleted with App Insights |

**Total burn ≈ $611/mo** (compute $545 + observability $60 + Key Vault $5 + nominal).

---

## 1. Three modes — pick the right one

| Mode | What it does | Reversible? | Time | Savings | Use when |
|---|---|---|---|---:|---|
| **A · Pause** | App Service `stop` + Postgres `stop` + SWAs left running (free) | Instant via `start` | <2 min | ~$420/mo (compute idle but plan/storage still bills) | Mid-day break · weekend gap |
| **B · Hibernate** | Pause + delete metric alerts + drop App Service plan to F1 free | 30-min rebuild | ~10 min | ~$540/mo | Multi-week gap between demos |
| **C · Demolish** | Snapshot everything → delete the entire RG (Key Vault stays in soft-delete) | Full rebuild from Bicep (~30 min) | ~25 min teardown + ~30 min rebuild | $611/mo (full burn eliminated) | Cost contain · DR drill · long break · before fresh-customer demo |

**Default recommendation: Mode A (Pause)** for any gap <72h, **Mode C (Demolish)** for anything longer with snapshot + Bicep-driven rebuild.

---

## 2. Pre-flight checks (every mode)

Run before any teardown action:

```powershell
# 1. Confirm we're on the right subscription
az account show --query "{name:name, id:id}" -o table
# Expect: SignalLayerDev · 06e4c6fa-8b0f-4e4a-b993-e0fd21eb22a3

# 2. Confirm the RG exists and inventory matches
az resource list --resource-group rg-aigovern-dev --query "length(@)"
# Expect: 26 (or your current count — if it differs, abort and inspect)

# 3. Confirm no active sessions
curl -s https://api.aigovern.sandboxhub.co/api/health
# Then check usage_analytics for active sessions in last 30 min before pulling the rug

# 4. Confirm git is clean and pushed (in case rebuild draws from a different commit than expected)
git status --short
git log origin/main..HEAD --oneline   # should be empty

# 5. Confirm Bicep templates exist for rebuild path (Mode C only)
Test-Path deploy/bicep/main.bicep
Test-Path deploy/bicep/staticwebapps.bicep
Test-Path deploy/bicep/staticwebapps-gov.bicep
```

**Abort conditions:**
- Subscription mismatch → STOP
- Resource count delta > 2 → STOP (someone provisioned outside Bicep)
- Active sessions > 0 (someone is using the demo right now) → CONFIRM before teardown
- Git ahead of origin → push first (rebuild Bicep should match committed state)

---

## 3. Backup phase (Modes B and C only)

Backup BEFORE any delete operation. Output to `deploy/teardown-backup-YYYYMMDD-HHMMSS/`.

| Asset | How | Where |
|---|---|---|
| **App settings** | `az webapp config appsettings list` for app + staging slot | `app-settings.json` · `app-settings-staging.json` |
| **Hash list (sans values)** | Names only — values are derivable from `deploy/creds.txt` | `demo-user-hashes.txt` |
| **Postgres** | `pg_dump -F c` (custom format) via temporary firewall rule | `postgres-dump.pgcustom` |
| **Postgres firewall rules** | `az postgres flexible-server firewall-rule list` | `postgres-firewall.json` |
| **AI Search index schemas** | REST `GET /indexes` per index | `search-indexes/*.json` |
| **AI Search content** | REST `POST /indexes/{name}/docs/search` · paginated · `select=*` | `search-content/{index}.jsonl` |
| **Key Vault secret list (names only)** | `az keyvault secret list` | `keyvault-secrets-list.txt` |
| **App Service /home/data JSONL** | Kudu REST `POST /api/zip` over `/home/data/` | `home-data.zip` |
| **App Service /home/site/repository (if any)** | Same Kudu zip | `home-site.zip` |
| **Log Analytics queries** | `az monitor log-analytics workspace saved-search list` | `saved-searches.json` |
| **Alert rule definitions** | `az monitor scheduled-query list` | `scheduled-query-rules.json` |
| **Action Group config** | `az monitor action-group show` | `action-group.json` |
| **Static Web App config** | Already in Bicep · skip | n/a |

**Verify backup integrity** before proceeding:
```powershell
$backupDir = "deploy/teardown-backup-$(Get-Date -Format yyyyMMdd-HHmmss)"
# Confirm size sane
Get-ChildItem $backupDir -Recurse | Measure-Object -Property Length -Sum
# Confirm pg_dump readable
pg_restore --list "$backupDir/postgres-dump.pgcustom" | Select-Object -First 5
# Confirm AI Search JSONL lines parse
Get-Content "$backupDir/search-content/*.jsonl" | Select-Object -First 1 | ConvertFrom-Json
```

---

## 4. Teardown phases (ordered by dependency)

### Phase 1 — Stop traffic & break SSO
```powershell
# Stop App Service (immediate halt, dropping any in-flight requests)
az webapp stop --name app-aigovern-dev --resource-group rg-aigovern-dev
az webapp stop --name app-aigovern-dev --resource-group rg-aigovern-dev --slot staging
# DNS still points; users get a "stopped" page until alert TTL expires
```

### Phase 2 — Snapshot data stores (Mode C only)
```powershell
# Postgres Flexible — stop is free up to 7 days
az postgres flexible-server stop --name psql-aigovern-dev --resource-group rg-aigovern-dev
# Postgres snapshot (point-in-time restore is 7d by default; ensure we have a logical dump for >7d horizons)
# (Backup phase already ran pg_dump above)

# Azure AI Search — no native pause · export already captured in backup phase
```

### Phase 3 — Delete metric alerts (Modes B and C)
```powershell
$alerts = @(
  "alert-opa-unreachable", "alert-http-5xx-rate", "alert-rtf-partial-failure",
  "alert-pii-leak", "alert-audit-chain-broken", "alert-vault-error",
  "alert-scrub-rate-regression", "alert-p95-latency"
)
foreach ($a in $alerts) {
  az monitor scheduled-query delete --name $a --resource-group rg-aigovern-dev --yes
}
az monitor action-group delete --name ag-aigovern-dev --resource-group rg-aigovern-dev
```

### Phase 4 — Delete SPA endpoints (Mode C)
```powershell
az staticwebapp delete --name swa-aigovern-portal-dev --resource-group rg-aigovern-dev --yes
az staticwebapp delete --name swa-aigovern-gov-dev --resource-group rg-aigovern-dev --yes
# DNS CNAMEs at sandboxhub.co will dangle — record this in the rebuild runbook
```

### Phase 5 — Delete App Service (Mode C)
```powershell
# Unbind custom cert/domain bindings first to release them
az webapp config hostname delete --webapp-name app-aigovern-dev --resource-group rg-aigovern-dev --hostname aigovern.sandboxhub.co 2>$null
az webapp config hostname delete --webapp-name app-aigovern-dev --resource-group rg-aigovern-dev --hostname api.aigovern.sandboxhub.co 2>$null
# Delete the slot, then the app, then the plan (order matters)
az webapp deployment slot delete --name app-aigovern-dev --resource-group rg-aigovern-dev --slot staging
az webapp delete --name app-aigovern-dev --resource-group rg-aigovern-dev --keep-empty-plan false
az appservice plan delete --name asp-aigovern-dev --resource-group rg-aigovern-dev --yes
```

### Phase 6 — Delete Postgres (Mode C)
```powershell
# Stop already done in Phase 2 · final delete
az postgres flexible-server delete --name psql-aigovern-dev --resource-group rg-aigovern-dev --yes
# PITR backups retained per server config (default 7d) — irrecoverable after that window
```

### Phase 7 — Delete Azure AI Search (Mode C)
```powershell
az search service delete --name search-aigovern-dev --resource-group rg-aigovern-dev --yes
```

### Phase 8 — Delete observability (Mode C)
```powershell
az monitor app-insights component delete --app appi-aigovern-dev --resource-group rg-aigovern-dev
az monitor app-insights component delete --app appi-aigovern-prod --resource-group rg-aigovern-dev
az monitor log-analytics workspace delete --workspace-name log-aigovern-dev --resource-group rg-aigovern-dev --yes
az monitor log-analytics workspace delete --workspace-name log-aigovern-prod --resource-group rg-aigovern-dev --yes
```

### Phase 9 — Key Vault (DO NOT PURGE)
```powershell
# Soft-delete only. 90-day recovery window preserves secrets in case of a re-mind reversal.
az keyvault delete --name kv-aigovern-sl-dev --resource-group rg-aigovern-dev
# DO NOT run `az keyvault purge` — that's the only irreversible action and we want the safety net.
# To recover within 90 days: `az keyvault recover --name kv-aigovern-sl-dev`
```

### Phase 10 — RG sweep (only if empty)
```powershell
# After all child resources are gone, the RG itself can be deleted
# Confirm empty first
$remaining = az resource list --resource-group rg-aigovern-dev --query "length(@)"
if ($remaining -eq 0) {
  az group delete --name rg-aigovern-dev --yes --no-wait
} else {
  Write-Warning "RG still has $remaining resource(s) — investigate before deleting"
  az resource list --resource-group rg-aigovern-dev -o table
}
```

---

## 5. Safety mechanisms (baked into the script)

| Layer | Mechanism |
|---|---|
| **Mode default** | `-Mode Pause` is the default · Demolish requires `-Mode Demolish` explicitly |
| **WhatIf** | `-WhatIf` switch prints every `az` command that WOULD run, executes none |
| **Type-the-RG-name confirmation** | For Mode C: prompt for literal `rg-aigovern-dev` typing · case-sensitive · 3-strike abort |
| **Subscription guard** | Refuses to run unless `az account show` confirms `SignalLayerDev` |
| **Resource-count gate** | Compares live count vs expected baseline (26) · aborts if delta > 2 |
| **Backup precondition** | Mode B/C refuse to proceed unless `deploy/teardown-backup-*` directory exists and `manifest.json` lists all required assets |
| **Soft-delete preference** | Key Vault and Storage soft-delete are left intact · `--purge` is a separate `-IAmCertain` flag with its own type-the-name confirmation |
| **Logging** | Every action appended to `deploy/teardown-log-{timestamp}.jsonl` with timestamp, action, resource, exit code |
| **Audit trail** | Final log uploaded to a permanent location (e.g., gist or another RG) so post-mortem evidence outlives the teardown |
| **Idempotency** | Each phase function checks current state before acting · safe to re-run after partial failure |
| **No --no-wait on safety-critical deletes** | Postgres delete blocks until confirmed · so you don't think it succeeded when it's actually pending |
| **Cooldown clause** | After Phase 1 (stop), script pauses 30 seconds and asks "still proceed?" before any destructive call |

---

## 6. Rebuild path (after Mode C)

```powershell
# Per global CLAUDE.md Step 0 + Azure standards
az account set --subscription "SignalLayerDev"
$env:MSYS_NO_PATHCONV = "1"

# 1. Re-register providers (idempotent)
.\deploy\register-providers.ps1

# 2. Rebuild infra via Bicep
az deployment group create `
  --resource-group rg-aigovern-dev `
  --template-file deploy/bicep/main.bicep `
  --parameters @deploy/bicep/main.parameters.dev.json

# 3. Restore secrets to Key Vault (recover from soft-delete or re-provision)
# Option A — within 90 days: az keyvault recover --name kv-aigovern-sl-dev
# Option B — after 90 days: re-provision via deploy/generate-creds.py + push hashes

# 4. Restore Postgres
pg_restore -h psql-aigovern-dev.postgres.database.azure.com -U <admin> -d aigovern \
  -F c deploy/teardown-backup-<timestamp>/postgres-dump.pgcustom

# 5. Restore AI Search indexes
# Re-create index schemas then bulk-upload JSONL via REST POST /indexes/{name}/docs/index

# 6. Restore /home/data
# Upload backup zip via Kudu REST `PUT /api/zip/home/data`

# 7. Redeploy app code
.\deploy\build-zip.ps1
az webapp deploy --src-path deploy/app.zip --resource-group rg-aigovern-dev --name app-aigovern-dev --type zip

# 8. Smoke test
.\deploy\smoke.ps1
```

**Rebuild time:** ~30 minutes if Bicep is healthy and backups present. ~2 hours if rebuilding from scratch without backups (re-seed demo data manually).

---

## 7. Cost analysis (savings per mode)

| Mode | Compute | Observability | Other | Monthly total | Savings vs running |
|---|---:|---:|---:|---:|---:|
| Running (baseline) | $545 | $60 | $6 | **$611** | — |
| A · Pause | ~$190 (plan still bills, storage active) | $60 | $6 | **$256** | **$355/mo** |
| B · Hibernate | ~$13 (F1 free plan + storage) | $0 (alerts deleted) | $5 (KV stays) | **$18** | **$593/mo** |
| C · Demolish | $0 | $0 | $0 (KV soft-deleted) | **$0** | **$611/mo** |

**Caveat on Mode A:** App Service stopped still bills the plan in full — that's how P1V3 works. Real Pause savings come only from Postgres (`stop` is free) and the Postgres state preservation (no need to restore). If you want truly zero compute spend, you need Mode B or C.

---

## 8. Script architecture (proposed)

```
deploy/
├── teardown-prod.ps1               # Main entry point · parameter dispatcher
├── teardown/
│   ├── lib/
│   │   ├── preflight.ps1           # Subscription · RG · count checks
│   │   ├── backup.ps1              # All export operations
│   │   ├── confirm.ps1             # Type-the-name · subscription gate
│   │   ├── log.ps1                 # JSONL audit logger
│   │   └── verify.ps1              # Post-action validation
│   ├── modes/
│   │   ├── pause.ps1               # Mode A
│   │   ├── hibernate.ps1           # Mode B
│   │   └── demolish.ps1            # Mode C
│   └── phases/
│       ├── phase-01-stop-traffic.ps1
│       ├── phase-02-snapshot-data.ps1
│       ├── phase-03-delete-alerts.ps1
│       ├── phase-04-delete-spas.ps1
│       ├── phase-05-delete-app.ps1
│       ├── phase-06-delete-postgres.ps1
│       ├── phase-07-delete-search.ps1
│       ├── phase-08-delete-observability.ps1
│       ├── phase-09-delete-keyvault-softdelete.ps1
│       └── phase-10-delete-rg.ps1
├── rebuild-prod.ps1                # Mirror script · orchestrates Bicep + restore
└── teardown-prod.README.md         # Operator's runbook
```

### Main entry point signature
```powershell
.\deploy\teardown-prod.ps1 `
  -Mode <Pause|Hibernate|Demolish> `
  [-WhatIf] `
  [-SkipBackup] `
  [-Force] `
  [-BackupOnly]
```

| Param | Meaning |
|---|---|
| `-Mode` | Required · Pause, Hibernate, or Demolish |
| `-WhatIf` | Print every action without executing |
| `-SkipBackup` | Skip Mode B/C backup phase · **requires `-Force`** |
| `-Force` | Skip type-the-name confirmation · **never use interactively · CI only** |
| `-BackupOnly` | Run backup phase then exit (no teardown actions) |

---

## 9. What can go wrong

| Failure | Recovery |
|---|---|
| App Service stop times out (transient) | Re-run Phase 1 · idempotent |
| Postgres delete blocked by active connection | Script forces firewall rules to deny-all first |
| AI Search export hits throttling | Backup uses paginated REST · retries with exponential backoff |
| Key Vault accidentally hard-purged | **Unrecoverable.** Script blocks `--purge` unless `-IAmCertain` set explicitly |
| RG delete leaves managed identities | Manual cleanup via portal |
| Custom DNS records dangle | Documented in rebuild runbook · `sandboxhub.co` CNAMEs need re-pointing post-rebuild |
| Storage account has soft-delete locked artifacts | None in this RG, but if added later, must clear before RG delete |
| Bicep template drifts from running config | Always export ARM template before teardown · `az group export` |
| `creds.txt` lost during human shuffling | Bcrypt hashes can be regenerated · plaintexts cannot be recovered |
| Subscription cost forecast doesn't drop | Some Azure resources have 24-48h billing lag · check after 48h |

---

## 10. Decisions to lock before I write the script

| Decision | Options | Recommendation |
|---|---|---|
| **Default mode for the script** | Pause · Hibernate · Demolish · No-default (always specify) | **No-default** — force operator to choose intentionally |
| **Backup destination** | Local `deploy/teardown-backup-*` · Blob storage in a separate RG · GitHub repo (binary unfriendly) | **Local + Blob upload** to a survival RG (`rg-aigovern-backups` in a different region) |
| **Key Vault: ever purge?** | Yes (`-IAmCertain`) · Never | **Never** — let soft-delete age out · purge is a Day 30 cron not a Day 0 teardown action |
| **Postgres backup retention** | 7-day PITR (built-in) only · Custom pg_dump · Both | **Both** — pg_dump survives `flexible-server delete` |
| **Demolish requires git clean?** | Yes · No | **Yes** — sprint state must be committed so rebuild is reproducible |
| **Run as standalone scripts or as a single composed orchestrator?** | Standalone per-mode · Single dispatcher | **Single dispatcher** — easier audit trail; matches existing `deploy/build-zip.ps1` style |
| **Notify on completion?** | None · Email · Slack webhook · Action Group | **Action Group** if it still exists, otherwise local log only |
| **Test the script first?** | Yes · No | **Yes — `-WhatIf` dry run, then test pause/start cycle, before any Demolish run** |

---

## 11. Recommended sequence

1. **Today:** I write `teardown-prod.ps1` + the `preflight`, `backup`, `confirm`, and `log` library helpers.
2. **Test Mode A (Pause) with `-WhatIf`** — verify command set is correct.
3. **Test Mode A live** — pause, then start. Verify app comes back identical (Langfuse traces should resume cleanly).
4. **Add Mode B (Hibernate) and test with `-WhatIf`.**
5. **Mode C (Demolish) only after a full demo cycle has produced a current backup we can rebuild from end-to-end.**
6. **Document `deploy/teardown-prod.README.md`** with operator runbook.
7. **Commit + push** with explicit warning in commit message.

I will **not** execute any Mode B or C action against prod without your explicit go-ahead per individual run.

---

## 12. Anti-goals (deliberately NOT in this plan)

- Auto-teardown on schedule (cron) — too easy to surprise yourself; teardown stays human-triggered
- Cross-subscription teardown — single subscription only
- Purge of any soft-deleted resource — always preserve recovery window
- Multi-RG teardown — strictly `rg-aigovern-dev`; if other RGs added, list them explicitly
- Application data wipe (PII vault values etc.) on Pause — values stay encrypted at rest
- Customer notification — internal demo, no customers to notify
- Cost forecast integration — out of scope; check Azure cost dashboard manually 48h after

---

**End of plan.** Awaiting decision on the 8 items in Section 10 before I write the script.
