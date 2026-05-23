# SESSION 13 — V2 Phase 1: Engine Hardening + Carry-Over Debt

> **Status:** Planned. Ready to start.
> **Created:** 2026-05-23 (end of Day 12 close-out)
> **Prereqs:** All complete. `day-12-complete` tag pushed at `53ebd4a`. Smoke 6/6 PASS against prod.
> **Calendar slot:** V2 Phase 1 of 5 per `docs/plans/V2-PORTAL-SPLIT.md` §6. Estimated **5 working days**.
> **Branch strategy:** `phase/13-engine-hardening` (per `~/.claude/templates/CLAUDE-phase-driven.md`).

---

## 1. Purpose

V2 Phase 1 has two parallel tracks:

**Track A (V2 prep — primary):** Harden the engine API so two SPAs (Team Workspace + CISO Console) can
consume it via a stable contract. This is the foundation week — nothing visual ships, but every
subsequent phase depends on it.

**Track B (V1 debt close-out — secondary):** Burn down 5 carry-over items from Day-12 that would
otherwise haunt V2. These are small but compound — each one twice-burned in the Day 12 retrospective.

V1 stays running at `aigovern.sandboxhub.co` throughout. Zero user-visible change this session.

---

## 2. State entering this session

### What's built (V1 — green)
- **Engine:** All Sessions 01-10 complete + Day-11 demo orchestration + Day-12 fixes (8 root causes)
- **Smoke:** `deploy/smoke_e2e.ps1` 6/6 PASS against prod (`aigovern.sandboxhub.co`)
- **Tag:** `day-12-complete` at commit `53ebd4a`, pushed to `origin/main`
- **Surfaces:** All 22 V2-target surfaces have V1 ancestors (18 mature, 4 stubs per `V2-PORTAL-SPLIT.md` §3)
- **SDK + CLI:** Shipped Session 09 (`sdk/signallayer`, `cli/sl`). HMAC working. **Already V2-shaped.**
- **Production deploy:** Manual `az webapp deploy` from local. No CI-on-merge yet — see Track B item 2.
- **Production runtime config:** `EVAL_BACKEND=noop` set on App Service (config-only, not in git).
- **Tests:** 252 passing in V1 suite as of Session 10 (Sessions 11/12 didn't add tests — carry-over).

### What's NOT built (gaps to start V2)
- ❌ OpenAPI spec with pinned response models — most endpoints still return bare `dict`
- ❌ Contract tests in CI — there is no CI yet (manual deploy)
- ❌ Cross-subdomain cookie auth — `middleware/auth.py` is single-host
- ❌ `api.aigovern.sandboxhub.co` engine CNAME — App Service has only the apex host
- ❌ Test for deploy completeness (twice-burned in Day 12 — `pydantic-settings` drift was hit #2)
- ❌ ARCHITECTURE.md entries for Sessions 11, 12, 12B (last update was Session 10)
- ❌ SESSION-12B §6 — `EVAL_BACKEND=noop` not captured as fresh-deploy requirement
- ❌ App Insights instrumentation in Docker staging (deferred from Day 12 — caused 503 on B1)
- ❌ P1v3 + staging slot (deferred from Day 12 — would have prevented the outage entirely)

---

## 3. Goals (this session, in priority order)

### Track A — V2 Phase 1 deliverables (per `V2-PORTAL-SPLIT.md` §5)

1. **A1. Pin response models on every `api/*.py` endpoint.**
   - Replace every `-> dict` return signature with a Pydantic v2 `BaseModel` declared in the same file
     or in `api/contracts/`.
   - Add `operationId` to every route for codegen-friendly OpenAPI.
   - Add `info.version` from package metadata.
   - **Acceptance:** `curl https://aigovern.sandboxhub.co/openapi.json | jq '.info.version'` returns a
     real version (not `"0.1.0"` default).

2. **A2. Contract tests in CI.**
   - Install Schemathesis (or alternative).
   - Add a workflow that runs `schemathesis run openapi.json --checks all`.
   - **Acceptance:** intentionally break a response shape in a branch → CI fails before merge.

3. **A3. Parent-domain cookie auth (preparation only — deployed to V1, not yet exercised by V2 client).**
   - Update `middleware/auth.py` `_set_session_cookie()` to use `domain=".aigovern.sandboxhub.co"`.
   - Server-side session invalidation on logout (already in place; verify covers all subdomains).
   - Deploy to V1; verify existing single-host clients still work (regression).
   - **Acceptance:** existing V1 login flow unchanged from user perspective; cookie `Domain` attribute
     visible as `.aigovern.sandboxhub.co` in browser DevTools.

4. **A4. Engine custom domain.**
   - Add CNAME `api.aigovern.sandboxhub.co` → `app-aigovern-dev.azurewebsites.net`.
   - Bind custom domain + TLS cert in App Service.
   - **Acceptance:** `curl https://api.aigovern.sandboxhub.co/api/health` returns 200.

### Track B — V1 debt (parallel, fill any free time)

5. **B1. `tests/test_deploy_completeness.py`** (twice-burned in Day 12).
   - Walk every `.py` in the deploy zip's `INCLUDE` list (`deploy/build-zip.py`).
   - Parse top-level imports.
   - Assert each is satisfiable from `requirements-deploy.txt` (or stdlib, or an explicit allowlist).
   - **Acceptance:** test fails if a future deploy drops a required package.

6. **B2. ARCHITECTURE.md backfill** for Sessions 11, 12, 12B.
   - Append three "Files — Built" blocks following the existing pattern.
   - Move "Files — Planned" entries to done.
   - Update decorator chain note if anything changed (it didn't).

7. **B3. `docs/plans/SESSION-12B-PROD-RECOVERY.md` §6 update.**
   - Add the new carry-over items surfaced today (substring matcher debt resolved, `EVAL_BACKEND=noop`
     required, manual-deploy gap, etc).
   - Mark Day 12 as closed with the smoke 6/6 evidence.

### Track B (deferred to a dedicated session if Track A overruns)

8. **B4. App Insights instrumentation in Docker staging slot.** First attempt (Day 12 commits
   019e1c8 / 99d09dc) crashed B1. Needs P1v3 + staging slot first — see B5. **Do not retry on
   bare B1 without staging.**

9. **B5. P1v3 + staging slot.** Bigger infra change; one session.

10. **B6. CI-on-merge deploy.** GitHub Actions workflow that builds the zip on push to `main` and
    deploys to App Service via OIDC. Eliminates manual-deploy drift.

---

## 4. Out of scope (explicitly)

- ❌ Any SPA work (Team Workspace, CISO Console) — that's Phase 2+
- ❌ Multi-tenant changes — V3
- ❌ Streaming, real-time webhooks — deferred per `12-DAY-PRODUCTION-SPRINT.md` §8
- ❌ New product features — debt + foundation only
- ❌ DNS cutover — that's Week 5, this is Week 1

---

## 5. Execution sequence (5 working days)

| Day | Track A | Track B (parallel / fill) |
|---|---|---|
| 1 | A1 — Audit every `api/*.py` for `-> dict` returns; draft contract Pydantic models | B6 spike: GitHub Actions workflow draft (no deploy yet) |
| 2 | A1 — Apply response models to first half of routers; verify `/openapi.json` shape | B2 — ARCHITECTURE.md Sessions 11, 12, 12B entries |
| 3 | A1 — Finish remaining routers; A2 — wire Schemathesis | B1 — write `test_deploy_completeness.py` |
| 4 | A3 — parent-domain cookie change; regression test against V1 | B3 — SESSION-12B §6 update |
| 5 | A4 — engine CNAME + TLS cert; final smoke run; tag `v2-phase-1-complete` | Push docs; open PR if working on branch |

---

## 6. Risks specific to this session

| Risk | Likelihood | Mitigation |
|---|---|---|
| Pinning response models breaks the existing static HTML pages that depend on undocumented shapes | High | Run `smoke_e2e.ps1` after every router change; do one router at a time |
| Parent-domain cookie breaks existing session flow | Medium | Deploy to V1, verify existing demo creds still log in before tagging |
| `api.aigovern.sandboxhub.co` CNAME conflicts with apex routing | Low | Apex stays on the SPA in Phase 5; engine on the API subdomain doesn't conflict |
| Contract tests find lots of latent shape inconsistencies | High | Expected. Triage: fix the response model to match reality, don't change the response shape (would break V1 UI) |
| Track A blocks on a decision (e.g., where to declare `BaseModel`s) | Medium | Default: one `models.py` per `api/*.py` file. Refactor to `api/contracts/` only if duplication emerges |

---

## 7. Verification (run at end of session)

```bash
# Engine spec stable + versioned
curl -s https://aigovern.sandboxhub.co/openapi.json | jq '.info.version'

# Engine reachable on new custom domain
curl -s https://api.aigovern.sandboxhub.co/api/health  # expects {"status":"ready"}

# Smoke still green (no V1 regression)
$env:SMOKE_TARGET_URL = "https://aigovern.sandboxhub.co"
$env:SMOKE_USER       = "demo-aigov"
$env:SMOKE_PASSWORD   = "<from deploy/creds.txt>"
$env:SMOKE_ALLOW_PROD = "true"
pwsh deploy/smoke_e2e.ps1

# Deploy completeness gate
python -m pytest tests/test_deploy_completeness.py -v

# Contract tests
schemathesis run https://aigovern.sandboxhub.co/openapi.json --checks all
```

All five must pass before tagging `v2-phase-1-complete`.

---

## 8. Handoff to SESSION 14 (V2 Phase 2)

After this session closes:
- Engine has stable OpenAPI + contract tests
- Both subdomains share session via parent-domain cookie
- `api.aigovern.sandboxhub.co` is live
- V1 still primary at `aigovern.sandboxhub.co` (zero user-visible change)
- Carry-over debt reduced

**SESSION 14 starts:** Team Workspace SPA scaffold + shared component library + first 4 decomposed
pages (AI Systems, Runtime, Evals, Agent Library). See `V2-PORTAL-SPLIT.md` §6 Week 2.

---

## 9. Sign-off

| Reviewer | Date | Status |
|---|---|---|
| Praveen (architect) | _pending_ | _pending_ |
