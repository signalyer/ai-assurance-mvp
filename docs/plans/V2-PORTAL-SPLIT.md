# V2 — Portal Split Plan

> **Status:** Planned. Not yet scheduled to sessions.
> **Date:** 2026-05-23
> **Scope owner:** Praveen (architect)
> **Estimated effort:** 21 working days · ~4 calendar weeks · one engineer
> **V1 impact during execution:** Zero. V1 stays running at `aigovern.sandboxhub.co` the entire time. DNS cutover is the only irreversible step and is reversible in seconds.

This plan supersedes the §1.9 "Team Portal + Gov Console" framing in `docs/plans/12-DAY-PRODUCTION-SPRINT.md` with a concrete, scoped, two-SPA + one-engine architecture grounded in the §02b diagram from `docs/architecture/target-architecture.html`.

---

## 1. The agreed architecture

Three deployable units (excluding the existing engine):

```
   ┌──────────────────────────────┐    ┌──────────────────────────────┐
   │     TEAM WORKSPACE           │    │     CISO CONSOLE             │
   │  portal.aigovern.sandbox...  │    │  gov.aigovern.sandbox...     │
   │                              │    │                              │
   │  Engineers self-serve the    │    │  Governance read-overlay     │
   │  full lifecycle:             │    │  across all teams + approval │
   │  register → develop → eval   │    │  actions.                    │
   │  → deploy → run → audit own  │    │                              │
   └──────────────┬───────────────┘    └──────────────┬───────────────┘
                  │                                   │
                  └─────────── HTTPS ─────────────────┘
                              │
                  ┌───────────▼────────────┐
                  │  ENGINE (FastAPI)      │
                  │  api.aigovern.sandbox  │
                  │                        │   ◄── SDK + CLI also hit
                  │  6-layer enforcement   │       the same engine.
                  │  · OpenAPI contract    │
                  │  · Event-sourced       │
                  └───────────┬────────────┘
                              │
              ┌───────────────┼────────────────┐
              ▼               ▼                ▼
       events.jsonl       Postgres        Key Vault + Blob
        (SSOT)         (projections)      Azure Search · Langfuse
```

### Hard constraints (explicit)

| Constraint | Source |
|---|---|
| No mobile, no responsive design work | User decision, 2026-05-23 |
| No standalone "agent onboarding" product | User decision, 2026-05-23 — registration is the first step inside Team Workspace, not a separate app |
| Developers consume the 6-layer architecture **via the SDK** (decorator stack), not via portal config screens | User decision, 2026-05-23 — Session 09 already shipped this; V2 surfaces it in the workspace |
| CISO Console is read-overlay + governance approval actions; **not** a control panel | User decision, 2026-05-23 |
| V1 must remain functional throughout V2 build | This plan §6 |

---

## 2. What V2 is NOT

Things explicitly out of scope so future sessions don't drift:

- ❌ **Split products with "pump" data flow** (the `docs/PLAN-EVAL-HARNESS.md` model). Superseded by `docs/architecture/target-architecture.md` §9. One engine, multiple thin clients.
- ❌ **Three separate web apps.** Two web apps (Team Workspace + CISO Console). The CLI/SDK is a Python package, not a web app.
- ❌ **A standalone "agent onboarding" app.** Onboarding is Team Workspace's first page.
- ❌ **Engine rewrite.** ~80% of V1 code stays untouched.
- ❌ **Multi-tenant SaaS.** Single-tenant through V2. Multi-tenant is V3.
- ❌ **Multi-language SDKs.** Python only through V2.
- ❌ **Real-time webhooks.** Polling sufficient (deferred per `12-DAY-PRODUCTION-SPRINT.md` §8).
- ❌ **Mobile / responsive UI.** Desktop-first.
- ❌ **Streaming evals.** Batch only.

---

## 3. Audience and surfaces

### Team Workspace · `portal.aigovern.sandboxhub.co`

**Audience:** Engineers, ML team leads, system owners. Self-service, write-heavy, fast cadence. Default scope: filtered to the logged-in user's team.

**12 surfaces:**

| # | Surface | V1 status | V2 work |
|---|---|---|---|
| 1 | **Register AI System** | ✅ `static/ai-systems.html` + `ai-systems-new.html` | SPA decompose |
| 2 | **SDK Quickstart** (per-system) | ❌ Not in V1 (README only) | **NEW** — ~0.5 day |
| 3 | **Per-system 6-layer config** | ⚠ Backend partial via Session 05 provider abstraction | **NEW** — ~2 days |
| 4 | **Eval cockpit** (run, history, suite editor) | ✅ `static/evals.html` (basic) | SPA decompose + UX upgrade |
| 5 | **Adversarial test runner** (Garak) | ⚠ `adversarial.py` exists; CLI/script only | **NEW UI** — ~1 day |
| 6 | **Runtime traces** | ✅ `static/runtime.html` | SPA decompose |
| 7 | **Agent Library** (publish/subscribe) | ✅ `static/agent-library.html` (Session 07) | SPA decompose |
| 8 | **Memory inspector** (Tier 2 / Tier 3) | ✅ `static/memory.html` (Session 04) | SPA decompose |
| 9 | **RAG corpus management** | ⚠ `domain/rag_engine.py` exists; no UI | **NEW** — ~2 days |
| 10 | **Right-to-Forget request** (engineer side) | ✅ `static/right-to-forget.html` (Session 08) | Split: engineer = request only |
| 11 | **My systems portfolio** (own team only) | ⚠ `static/governance.html` exists but cross-team | Filter to own-team view |
| 12 | **Per-system framework alignment** (read-only) | ✅ `static/frameworks.html` (Session 06) | Filter to own systems |

### CISO Console · `gov.aigovern.sandboxhub.co`

**Audience:** CISO, Risk, Audit, AIGOV. Read-overlay + approval actions. Default scope: cross-portfolio.

**10 surfaces:**

| # | Surface | V1 status | V2 work |
|---|---|---|---|
| 1 | **Portfolio overview** (all teams) | ✅ `static/governance.html` | SPA decompose |
| 2 | **Findings** (cross-team) | ✅ `static/findings.html` | SPA decompose |
| 3 | **Release Gate approvals** | ✅ `static/release-gates.html` | SPA decompose |
| 4 | **Framework Coverage Matrix** (all systems × all frameworks) | ✅ `static/frameworks.html` (Session 06) | SPA decompose |
| 5 | **Audit Chain verify** | ✅ `static/audit-events.html` (Session 08) | SPA decompose |
| 6 | **Evidence bundles** (export + signed download) | ✅ `static/evidence.html` | SPA decompose |
| 7 | **Right-to-Forget approvals** (governance side) | ✅ `static/right-to-forget.html` (Session 08) | Split: governance = approve only |
| 8 | **Cross-portfolio analytics** | ✅ `static/analytics.html` | SPA decompose |
| 9 | **Policy governance** | ✅ `static/policies.html` | SPA decompose |
| 10 | **Reports** (executive PDF export) | ✅ `static/reports.html` | SPA decompose |

**Total:** 22 surfaces, of which **18 already exist in V1** and **4 are net-new pages**.

---

## 4. What stays the same (the 80%)

| Component | Why unchanged |
|---|---|
| All 18 `domain/*.py` modules | Business logic; clients don't touch it |
| All 16 `api/*.py` routers | Already an API; SPAs just consume it |
| `middleware/` (scrubber, policy, guardrails, tracer, HMAC, auth core) | Engine-side |
| `tracer.py`, `evaluator.py`, `scrubber.py`, `audit_chain.py`, `right_to_forget.py` | Core engine |
| The decorator chain order `@policy_gate → @scrub_pii → @guardrails → @trace_llm_call → @evaluate_response` | Engine invariant |
| All 8 App Insights alert rules + Bicep infra | Engine observability |
| Postgres event projection (Session 09) | Already SSOT — exactly what V2 assumed |
| `sl` CLI + `signallayer` SDK (Session 09) | Already V2-shaped — hits the same API the SPAs will |
| All policy `.rego` files, framework YAMLs, control libraries | Engine config |
| `events.jsonl` storage layer | SSOT |
| Provider abstraction (Session 05) | Pluggable backends |

**~80% of the codebase. V2 is a client-layer project, not an engine rewrite.**

---

## 5. What changes (the 20%)

### Engine-side changes

| Change | Effort | Detail |
|---|---|---|
| **Auth scope: single-host cookie → parent-domain cookie** | 2 days | `middleware/auth.py` `_set_session_cookie()` updates `domain=".aigovern.sandboxhub.co"`. Both subdomains share the session. Logout invalidates server-side session in all subdomains. |
| **CORS allowlist** | 0.5 day | Add `portal.aigovern.sandboxhub.co` and `gov.aigovern.sandboxhub.co` to allowed origins. FastAPI `CORSMiddleware`. |
| **OpenAPI spec hardening** | 3 days | Pin response models on every endpoint (no bare `dict` returns). Add `operationId` to every route for codegen. Version with `info.version` from package metadata. |
| **Contract tests in CI** | 1 day | Schemathesis or similar — fail CI if response shape changes without a version bump. |
| **Engine hostname:** add `api.aigovern.sandboxhub.co` CNAME → `app-aigovern-dev.azurewebsites.net` | 0.5 day | New DNS record + TLS cert binding on App Service |

### New web apps

| Change | Effort | Detail |
|---|---|---|
| **Team Workspace SPA scaffold** | 1 day | Vanilla HTML modules (no framework) per current `static/*.html` pattern, OR adopt Vite + lightweight framework if scope demands. Decide at start of Phase 3. |
| **Team Workspace: decompose 8 existing V1 pages** | 4 days | Move HTML + JS + CSS from `static/` → `team-portal/src/pages/`. Re-point API calls to `api.aigovern.sandboxhub.co`. |
| **Team Workspace: 4 new pages** (SDK Quickstart, per-system 6-layer config, RAG corpus, adversarial UI) | 4 days | New work per §3 above. |
| **CISO Console SPA scaffold + decompose 10 existing V1 pages** | 6 days | Mirror Team Workspace structure. All 10 pages are pure-read except RTF approvals and Release Gate approvals (which post). |
| **Shared component library** | 1 day | `shared.js`, `shared.css`, NavBar, KPI cards, table — extracted from current `static/shared.*` |

### Infrastructure

| Change | Effort | Detail |
|---|---|---|
| **2 new Azure Static Web Apps** (`swa-aigovern-portal-dev`, `swa-aigovern-gov-dev`) | 0.5 day | Bicep additions in `deploy/bicep/`. Both in `eastus2` per Static Web App regional rule. |
| **2 new DNS CNAMEs** (`portal.aigovern.sandboxhub.co`, `gov.aigovern.sandboxhub.co`) | 0.25 day | sandboxhub.co zone updates. |
| **2 new TLS certs** | 0.25 day | Auto-provisioned via SWA managed cert. |
| **App Service hostname `api.aigovern.sandboxhub.co`** | 0.5 day | Custom domain + cert on existing App Service. |

### Operations

| Change | Effort | Detail |
|---|---|---|
| **Smoke test rewrite** for two surfaces | 0.5 day | `deploy/smoke_e2e.ps1` splits into `smoke_portal.ps1` + `smoke_gov.ps1`. Engine smoke runs against `api.aigovern.sandboxhub.co`. |
| **Demo talk track URL updates** | 0.5 day | `docs/demo-scripts/scenario-*.md` and `docs/DEMO-QA.md`. |
| **RUNBOOK additions** | 0.5 day | Two-portal rollback steps, DNS cutover playbook. |

### Total effort

| Phase | Days |
|---|---|
| 1. OpenAPI hardening + contract tests | 4 |
| 2. Cross-subdomain auth + CORS + engine DNS | 3 |
| 3. Team Workspace SPA (decompose + 4 new pages) | 9 |
| 4. CISO Console SPA (decompose) | 6 |
| 5. 2 SWAs + DNS + TLS + Bicep additions | 1 |
| 6. Smoke + talk-track + RUNBOOK rewrites | 1.5 |
| **Total** | **24.5 days ≈ 5 calendar weeks** |

(Up from the 21-day estimate in chat due to explicitly accounting for the shared component library and engine custom-domain work.)

---

## 6. Migration path — V1 stays live throughout

**Critical: V1 (`aigovern.sandboxhub.co`) keeps serving traffic until week-5 DNS cutover.**

```
Week 1   Engine: harden OpenAPI spec + contract tests in CI
         Engine: parent-domain cookie auth (deployed to V1 first, tested against current users)
         Infra: Bicep additions for two new SWAs in dev RG (NOT pointed at DNS yet)
         Result: V1 unchanged from user POV. Engine ready for V2 clients.

Week 2   Team Workspace SPA: scaffold + shared component library + 4 V1-decomposed pages
         (AI Systems · Runtime · Evals · Agent Library)
         Deployed to swa-aigovern-portal-dev.azurestaticapps.net (NOT custom DNS)
         Result: Internal V2 staging URL live. V1 still primary.

Week 3   Team Workspace SPA: 4 remaining V1-decomposed pages + 2 new pages
         (Memory · RTF · Portfolio · Frameworks read-only · SDK Quickstart · 6-layer config)
         CISO Console SPA: scaffold + 5 V1-decomposed pages
         Result: Both SPAs reachable on .azurestaticapps.net URLs. V1 still primary.

Week 4   Team Workspace SPA: 2 final new pages (RAG corpus · Adversarial runner)
         CISO Console SPA: 5 remaining V1-decomposed pages
         Internal review + bug-fix parity against V1
         Smoke tests rewritten and passing against staging URLs
         Result: V2 feature-complete on staging. V1 still primary.

Week 5   DNS cutover: portal.aigovern.sandboxhub.co + gov.aigovern.sandboxhub.co go live
         aigovern.sandboxhub.co becomes 302 redirect to portal.aigovern... (or gov, role-aware)
         Talk tracks, RUNBOOK, DEMO-QA updated
         Stakeholder dry-run on V2
         Result: V2 is primary. V1 redirect in place. Rollback = DNS revert (≤60s).
```

**At no point during weeks 1-4 is V1 broken.** V1 is the safety net. The DNS change in week 5 is the only irreversible step, and it's reversible in seconds.

---

## 7. Acceptance criteria

V2 is complete when **all** of the following pass:

| # | Criterion | Verification |
|---|---|---|
| A1 | Engine emits stable OpenAPI spec at `api.aigovern.sandboxhub.co/openapi.json` | `curl` returns 200; `info.version` present |
| A2 | Contract tests in CI fail the build on response shape change | Introduce intentional breaking change in a branch; CI red |
| A3 | Same Entra session works across portal.* and gov.* | Log into one, navigate to the other, no re-prompt |
| A4 | Team Workspace renders all 12 surfaces | `pwsh deploy/smoke_portal.ps1` exits 0 |
| A5 | CISO Console renders all 10 surfaces | `pwsh deploy/smoke_gov.ps1` exits 0 |
| A6 | Engineer login lands on Team Workspace by default | Login as `demo-engineer` → URL ends with `portal.*` |
| A7 | CISO login lands on CISO Console by default | Login as `demo-ciso` → URL ends with `gov.*` |
| A8 | SDK Quickstart copy-paste produces a running decorator stack | Copy snippet, paste into a fresh Python file, `python file.py` runs without import error |
| A9 | Per-system 6-layer config UI shows current backend choices | Configured scrubber / memory / RAG / policy backends rendered correctly per system |
| A10 | RAG corpus UI lists documents with classification + scrub rate | Visible counts match `domain/rag_engine.rag_stats()` output |
| A11 | Adversarial runner UI fires a Garak probe and shows results | One probe to completion in the UI |
| A12 | V1 redirect 302s correctly | `curl -I https://aigovern.sandboxhub.co/` returns 302 to portal.* or gov.* |
| A13 | DNS rollback verified | Revert sandboxhub.co zone; V1 serves traffic in ≤60s |
| A14 | Existing 252-test suite still passes | `python -m pytest tests/` green |
| A15 | All 8 App Insights alerts still fire correctly post-cutover | Synthetic incident → alert email arrives |
| A16 | Decorator chain order still enforced (no regression) | `signallayer.guard(fn)` rejects wrong-order chains |

---

## 8. Open questions to resolve at start of Phase 3 (week 2)

1. **SPA framework choice.** Vanilla HTML modules (current pattern, low ceremony) vs. Vite + a lightweight framework (Svelte / Preact / vanilla-TS with reactive helpers). Decision criteria: if total SPA scope exceeds ~5K lines per portal, framework probably wins; below that, vanilla wins. Estimate scope at end of week 1.
2. **Branding for the two portals.** "Team Workspace" and "CISO Console" are working names. Final labels need stakeholder sign-off before week-4 talk tracks are rewritten.
3. **Role mapping at login.** A user with multiple roles (e.g., `demo-aigov` = both) — does login land them at one default with a "switch portal" link in the chrome, or at a chooser? Recommendation: default to most-recently-used; fall back to CISO Console for ambiguity.
4. **Custom domain ownership and DNS access.** Confirm sandboxhub.co zone is in an Azure DNS zone we control or whoever controls it can add records on a same-day SLA during week 5.

---

## 9. Risks and mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Parent-domain cookie auth has edge cases (e.g., logout race across subdomains) | Medium | Server-side session invalidation via `session_end()` covers this; document the gotchas in RUNBOOK. |
| OpenAPI drift slips through CI | Low | Schemathesis catches structural changes. Manual review on every `api/*.py` PR. |
| SPA bundle size grows large (slow first paint) | Low-Medium | Code-split per route; lazy-load. Each SPA target: < 500KB initial load, gzipped. |
| Static Web App regional rule (`eastus2` only) conflicts with other infra (`eastus`) | Low | Cross-region within Azure backbone is sub-10ms; no functional issue. Document in README. |
| Stakeholder demo lands during cutover window | Medium | DNS cutover scheduled outside demo windows; rollback playbook tested in week 4. |
| Team Workspace "Settings → 6-layer config" UI invites users to break things they shouldn't touch | High | Read-mostly with explicit "request change" workflow that routes to CISO Console for approval; no direct writes to policy backends from Team Workspace. |
| Adversarial runner UI causes load on Langfuse or eval providers | Low | Rate-limit per user; queue probes; show queue position. |

---

## 10. What this plan does NOT specify

Intentionally left for the team executing it to decide:

- Exact wireframes / visual design (a design pass happens at start of week 2)
- SPA framework (decided at start of week 2 per §8.1)
- Whether to consolidate `static/governance.html` and `static/runtime.html` (V1 pages) into smaller components — implementation detail
- Whether the CLI/SDK README links to the SDK Quickstart page in Team Workspace or stays standalone — both fine, recommend both
- Exact CSS approach (utility-first vs. classic) — team preference

---

## 11. Dependencies on V1 close-out

This plan assumes the following V1 items are complete before V2 Phase 1 begins:

- ✅ All Sessions 01-10 (already complete)
- ✅ Session 11 (Demo Control + PDF Packs) — already complete
- ⏳ Session 12 (Day 12 stakeholder dry-run + final deploy) — in progress today (2026-05-23)

V2 work starts in Session 13 at the earliest.

---

## 12. Estimated calendar

Assuming one engineer, 5 working days per week, no major interruptions:

| Calendar week | Phase | Deliverable |
|---|---|---|
| Week 1 | Engine hardening | OpenAPI spec stable; contract tests in CI; parent-domain cookie tested |
| Week 2 | Team Workspace foundation | Scaffold + 4 decomposed pages + shared component library |
| Week 3 | Team Workspace completion + CISO foundation | 4 more decomposed + 2 new pages on Team side; 5 decomposed on CISO side |
| Week 4 | CISO completion + integration | 5 more decomposed + 2 new pages on Team side (RAG corpus, Adversarial); 5 more decomposed CISO; bug-fix parity |
| Week 5 | Cutover | DNS + smoke + talk tracks + RUNBOOK + stakeholder dry-run on V2 |

**Earliest start:** day after Day-12 close-out (i.e., 2026-05-24 if Day 12 ends today)
**Earliest finish:** 2026-06-27 (~5 calendar weeks later, assuming continuous focused work)

---

## 13. Sign-off

| Reviewer | Date | Status |
|---|---|---|
| Praveen (architect) | _pending_ | _pending_ |
| (engineer executing) | _pending_ | _pending_ |

Once signed, this document moves from `docs/plans/` to the active session sequence (e.g., `SESSION-13-v2-engine-hardening.md`, `SESSION-14-team-workspace-scaffold.md`, etc.) with one session document per phase.
