# SESSION 12B — Production Recovery Plan

> **Status:** Draft, awaiting user approval to execute.
> **Date:** 2026-05-23
> **Triggered by:** `aigovern.sandboxhub.co` HTTP 503 since ~19:25 UTC during Day-12 deploy churn.
> **Risk level:** Low (root cause confirmed, fix is targeted, all changes reversible).
> **Estimated wall time to green:** 15-20 minutes.

---

## 1. Context — how we got here

Day-12 deploy work added an App Service env var (`APPLICATIONINSIGHTS_CONNECTION_STRING`), which auto-restarted the container. The restart triggered Oryx to rebuild `antenv/` from `requirements-deploy.txt`. The container then failed to start with the same error on every subsequent restart attempt.

**My first diagnoses were wrong** (App Insights, OTel distro, slim requirements pruning). The real cause was only confirmed after enabling SCM basic auth and pulling the actual container log.

## 2. Root cause (confirmed)

**Container log shows:**
```
File "api/security.py", line 26, in <module>
    from guardrails.llama_guard_adapter import evaluate_content
ModuleNotFoundError: No module named 'guardrails'
```

**The chain:**

1. Session 03 (2026-05-21) replaced the legacy `guardrails.py` *file* with a `guardrails/` *package* (4 modules + 1 YAML config)
2. `deploy/build-zip.py` INCLUDE list was never updated — still references `"guardrails.py"` which prints a `WARN: missing (skipped)` and continues
3. `api/security.py` line 26 imports `from guardrails.llama_guard_adapter import evaluate_content` at module load
4. `api/security.py` is imported by `dashboard.py` at module load
5. So **every cold start since Session 03 should have failed**
6. It didn't, because the App Service container had been running continuously and `antenv/` already had a `guardrails` directory from somewhere (likely a prior manual `pip install` or a one-time deploy with an old layout)
7. Today's restarts triggered antenv rebuild → cached state lost → import fails → container exits → 503

**Secondary issues uncovered while diagnosing:**

| Missing from INCLUDE | Consumed by | Latent risk |
|---|---|---|
| `guardrails/` | api/security.py | **active 503** |
| `frameworks/` | domain/framework_coverage.py | next restart |
| `observability/` | dashboard.py (try/ImportError swallow hides this) | telemetry stays dead |
| `policies/` | domain/policy_engine.py | next restart |

**Also slim requirements drift:** `requirements-deploy.txt` was missing ~10 packages the app imports at module load (langfuse, presidio, cryptography, psycopg, PyYAML, portalocker, cachetools, azure-search-documents, pyjwt, requests/httpx). Already fixed in commit `dad83ae`, pushed but not yet deployed.

## 3. Current state (uncommitted local changes)

| File | Status |
|---|---|
| `deploy/build-zip.py` | edited — adds `guardrails`, `frameworks`, `observability`, `policies` to INCLUDE |
| `deploy/app.zip` | rebuilt — 209 files / 2.87 MB / contains all 4 missing packages (verified) |
| `requirements-deploy.txt` | already pushed in `dad83ae` |

| Azure state | Value |
|---|---|
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | **REMOVED** (diagnostic, must restore) |
| `SL_HMAC_SECRET` | present |
| SCM basic auth | **enabled** (must re-disable post-recovery) |
| Filesystem logging | enabled |
| Active deploy on App Service | `dad83ae` zip — Oryx rebuilt antenv with slim file but no `guardrails/` source |

---

## 4. Recovery plan — 5 phases with explicit checkpoints

Each phase has a clear stop-and-verify point. Nothing in Phase N executes until Phase N-1 has confirmed success. **I will not advance phases without your explicit "go".**

### Phase A — Commit the source fix (no Azure impact) · ~2 min

**Actions:**

1. `git add deploy/build-zip.py`
2. Commit with message documenting the 4-package addition and root-cause analysis
3. `git push origin main`

**Verification:**

- Commit appears on `origin/main`
- Working tree clean

**Rollback:** `git revert <sha>` — trivial.

**Risk:** None. Source-only change, no Azure touched.

**Stop here for user approval before Phase B.**

---

### Phase B — Deploy zipfile to App Service · ~6-10 min

**Actions:**

1. `az webapp deploy --resource-group rg-aigovern-dev --name app-aigovern-dev --src-path deploy/app.zip --type zip --async true`
2. Poll `/api/health` every 30s for up to 12 min

**Verification:**

- `/api/health` returns HTTP 200 with `{"status":"ready",...}`
- Subsequent `/login` returns HTTP 200 and renders the form
- `/api/agents` returns HTTP 401 (clean unauth JSON, not 500)

**Rollback:** Earlier deploy `dad83ae` is still in Kudu deployment history. Can mark it active via `az webapp deployment list-publishing-credentials` + Kudu REST. But the dad83ae deploy was ALSO broken (same guardrails ModuleNotFoundError). So real rollback would mean re-fetching commit `b33d59a` zip, but no such zip exists. **In practice: if Phase B fails, we're not worse off than now — we go to Phase B'.**

**Phase B' — fallback if Phase B fails:**
- Pull a fresh container log via SCM basic auth (still enabled)
- Identify the NEXT module missing
- Add it to INCLUDE, rebuild, redeploy
- Repeat until clean

**Risk:** Medium. Oryx may take 8-12 min on B1 because the new requirements-deploy.txt installs presidio + langfuse + cryptography + psycopg. Build timeout is 20 min — should fit.

**Stop here for user approval before Phase C.**

---

### Phase C — Restore App Insights connection string · ~1 min + 60s restart

**Actions:**

1. `az webapp config appsettings set -g rg-aigovern-dev -n app-aigovern-dev --settings APPLICATIONINSIGHTS_CONNECTION_STRING="<value from appi-aigovern-dev>"` — fetch the value from the App Insights resource, never displayed
2. Wait 60s for restart
3. Re-probe `/api/health` — must still be 200

**Verification:**

- `/api/health` still 200 after restart
- `az webapp config appsettings list` shows the setting present

**Rollback:** Re-delete the setting. Easy.

**Note:** This restores the env var only — it does NOT re-attempt the OTel instrumentation fix. The 8 alert rules will still not fire on real traffic (no instrumentation), and the workspace will stay empty. **That problem is deferred to a future session with proper Docker staging.** See §6.

**Risk:** Low. The current code path (try/ImportError swallow) is already gated on the OTel package being absent, so setting the env var changes nothing observable.

**Stop here for user approval before Phase D.**

---

### Phase D — Disable SCM basic auth · ~1 min

**Actions:**

1. PUT the policy back to `allow: false` via `az rest`

**Verification:**

- `az rest GET ...basicPublishingCredentialsPolicies/scm` returns `allow: false`

**Rollback:** None needed — this restores Session 10's hardening.

**Risk:** None.

---

### Phase E — Run the smoke test · ~2 min

**Actions:** You run locally with credentials (I cannot — would leak password into transcript):

```powershell
$env:SMOKE_TARGET_URL = "https://aigovern.sandboxhub.co"
$env:SMOKE_USER       = "demo-aigov"
$env:SMOKE_PASSWORD   = "<shared demo password>"
pwsh deploy/smoke_e2e.ps1
Remove-Item Env:SMOKE_PASSWORD
```

**Verification:**

- All 6 scenarios PASS
- Exit code 0
- Output: `=== SMOKE E2E PASSED — all 6 scenarios passed ===`

**Rollback:** Not applicable. Smoke is read-only diagnostic.

**Risk:** Some scenarios might still fail for reasons unrelated to tonight's outage (e.g., seeded systems missing). If they do, log the failure to `docs/dry-run-notes-DAY12.md` and either fix or defer per impact.

---

## 5. Acceptance criteria for "recovery complete"

Recovery is complete when **all** of the following hold:

| # | Criterion | Verification |
|---|---|---|
| R1 | `/api/health` returns HTTP 200 | `curl -sf https://aigovern.sandboxhub.co/api/health` exits 0 |
| R2 | Login page renders | `curl -s https://aigovern.sandboxhub.co/login | grep -q 'name="username"'` |
| R3 | Authed routes return clean 401 (not 500) | `curl -s -o /dev/null -w "%{http_code}" https://aigovern.sandboxhub.co/api/agents` returns 401 |
| R4 | Smoke test passes all 6 scenarios | `pwsh deploy/smoke_e2e.ps1` exit 0 |
| R5 | `APPLICATIONINSIGHTS_CONNECTION_STRING` restored | `az webapp config appsettings list` shows the key |
| R6 | SCM basic auth disabled | `az rest GET ...` returns `allow: false` |
| R7 | All 5 source packages in the deploy zip | `python -c "import zipfile; z=zipfile.ZipFile('deploy/app.zip'); print(sorted({n.split('/')[0] for n in z.namelist()}))"` includes guardrails, frameworks, observability, policies |
| R8 | Working tree clean and main pushed | `git status` clean, `git log origin/main..HEAD` empty |

---

## 6. What this plan does NOT fix (deferred carry-over)

These are real problems, surfaced or worsened during today's deploys, that are **out of scope for tonight**:

| Carry-over | Why deferred | Where to fix it |
|---|---|---|
| App Insights instrumentation gap (workspace empty, 8 alerts can't fire) | Needs Docker staging to validate OTel dep tree on App Service Linux Python 3.12 BEFORE deploying. B1 is too risky. | Session 13 or dedicated session post-demo |
| `build-zip.py` INCLUDE list drifts silently | This is the SECOND time a missing-package error has appeared this session. Need a defensive test. | Add `tests/test_deploy_completeness.py` that imports every module the dashboard imports and asserts no ImportError — runs in CI |
| `requirements-deploy.txt` vs `requirements.txt` drift | Same class of problem | CI check that diffs the two and warns on packages used at module load that are only in the dev file |
| App Service on B1 with no staging slot | Tonight's 503 was unrecoverable in-place because we deployed to prod with no safety net | V2 plan §6 already specifies moving to P1v3 with staging slot |
| Cold-start cooldown lockout | B1 has this; P-series + Always On do not | Same as above |
| SCM basic auth toggling for diagnostics | Inconvenient and security-sensitive; needs a better approach | Add `az webapp log tail` as the default diagnostic path, or wire Application Insights logs (which obviates Kudu) |
| Backend env pins absent from IaC — a fresh App Service rebuild would re-detonate the deepeval cold-start crash (Session 12B) and pull in heavy transitives that aren't shipped in `requirements-deploy.txt` | The Day-12 fix set `EVAL_BACKEND=noop` on App Service via the portal/CLI, not in git. Session 21's CI OpenAPI export profile (`SL_OPENAPI_EXPORT_PROFILE=ci`) captured the full set of safe defaults but only for the export script — not for the runtime. Any rebuild from `deploy/bicep/` would ship without them. | **Fresh-deploy requirement (must be set on `app-aigovern-dev` and any future App Service before first request):** `EVAL_BACKEND=noop`, `SCRUBBER_BACKEND=regex`, `TRACER_BACKEND=noop`, `MEMORY_BACKEND=noop`, `RAG_BACKEND=noop`, `POLICY_BACKEND=noop`. Recorded here as Session 24's closure of the open Session 13 item. Bicep parameterisation deferred to the App Insights / P1v3 staging-slot session — encoding these into `appsettings.bicep` without a staging slot to verify against repeats the Session 12 risk pattern. |
| Parent-domain cookie wired via `SESSION_COOKIE_DOMAIN` env var (Session 24) is unset on V1 today | V1 stays host-only until V2 cutover so existing logins aren't disturbed mid-V2-build. Code path is dormant when env var is unset (host-only cookie, identical to pre-Session-24 behaviour). | When V2 SPAs flip onto subdomains, set `SESSION_COOKIE_DOMAIN=.aigovern.sandboxhub.co` on App Service and verify in browser DevTools that cookie `Domain` attribute is `.aigovern.sandboxhub.co`. Logout must also clear the parent-domain cookie (covered by `_cookie_domain()` mirror in `middleware/auth.py` logout handler — Session 24). |

Add each of these to `HANDOFF.md` "Day-12 carry-over debt" section so they don't fall through.

---

## 7. What I learned tonight (lessons to encode in CLAUDE.md)

To be added to `~/.claude/CLAUDE.md` after this session, per "compound engineering rule":

> **Date: 2026-05-23.** When a deployed app returns HTTP 5xx, the first action is to read the actual container/application log, not to theorize about the cause. Each theory-driven deploy attempt without log access risks compounding the failure (e.g., triggering cold-start cooldown, exhausting deploy quotas, masking the original error). If logs are inaccessible (auth gate, disabled file logging), enable diagnostic access FIRST and only then iterate.

> **Date: 2026-05-23.** App Service Linux antenv pruning: when SCM_DO_BUILD_DURING_DEPLOYMENT=true, every deploy that changes the in-zip `requirements.txt` triggers Oryx to rebuild antenv from scratch. Packages previously installed via other paths (manual pip, prior full-requirements deploy, base image) WILL BE REMOVED. The slim-requirements pattern is unsafe unless the slim file is the genuine source of truth for what the app imports at module load.

> **Date: 2026-05-23.** When build-zip.py prints `WARN: missing (skipped): <path>`, that warning is not informational — it is the strongest possible signal that the deploy is wrong. A missing source path means a runtime ImportError. Treat that warning as a fail-the-build error in a future hardening pass.

---

## 8. Sign-off

| Reviewer | Status |
|---|---|
| Praveen (architect) | _awaiting approval to execute Phase A_ |
| Claude (executor) | drafted 2026-05-23 ~20:25 UTC |

Once approved, I'll execute one phase at a time and stop after each for verification. If anything in a phase deviates from this plan, I will stop and surface it instead of improvising.
