# Azure Deployment Architect — POC Retrospective

Live log of friction encountered while running the V1→V2 dogfood POC against `aigovern.sandboxhub.co`. Findings bucketed for S56-S60 hardening input.

**Buckets:**
- **PLATFORM-GAP** — the platform is missing something a real workload needs
- **AGENT-CODE** — the workload (this agent) has a bug or design issue
- **DOC-GAP** — the runbook or platform docs are wrong / incomplete / misleading

---

## P1 — Intake

### F-001 · PLATFORM-GAP · Domain dropdown is finserv-only

**Found:** P1 Step 1, 2026-05-26
**Where:** `team-portal/src/pages/ai-systems/RegisterSystemPage.tsx:273`
**What:** Domain `SelectField` is hardcoded to `['Payments','AML','KYC','Credit','Customer Service','Wealth','Treasury']`. No "Platform Engineering", no "Other", no free-text fallback. Backend accepts any string (the field is a free string on the AI System model), so the constraint is purely UI.
**Impact:** Worse than cosmetic: `domain/risk_classification.py:20` defines `REGULATED_FS_DOMAINS = {Payments, AML, KYC, Credit, Treasury, Wealth}` — six of the seven dropdown options trip the regulated-FS risk floor (rule R5). Only `Customer Service` is risk-neutral. A platform/infra workload that picks anything else gets its inherent risk inflated above reality, which cascades into wrong gate sets and a misleading framework matrix.
**Workaround applied in this POC:** Selected `Customer Service` (only non-regulated option).
**Proposed fix (S56 backlog):** Backend-driven domain catalog (`/api/domains`) managed by CISO Console, OR env-configurable list + `Other` free-text fallback.
**Priority:** P1

---

### F-002 · PLATFORM-GAP · Step 2 was AWS-finserv-locked end-to-end (PARTIALLY RESOLVED 2026-05-26)

**Found:** P1 Step 2, 2026-05-26
**Where:** `team-portal/src/pages/ai-systems/RegisterSystemPage.tsx:300-325`
**What:** The entire Architecture step is hardcoded to a single AWS-finserv customer profile:
- Cloud Provider: `['AWS']` only — no Azure, no GCP, no on-prem
- AWS Services chips: `Bedrock, Lambda, ECS, EKS, S3, OpenSearch, Aurora, DynamoDB, ...`
- Models chips: includes `amazon.titan-text-express`, `amazon.nova-pro`
- RAG Sources chips: `FinCEN Advisories, Underwriting Standards, Regulatory Guidance, ...`
- Tools chips: `lookup_transaction, hold_payment, search_sanctions, credit_decision, ...`
- External Integrations: `Core Banking, Payments Platform, AML Platform, OFAC / SDN, ...`

Default form state in `cloud_provider: 'AWS'` at line 53.

**Impact:** **BLOCKS the Azure POC honestly.** An Azure workload cannot complete Step 2 without lying about cloud, lying about services (no Azure equivalents in chips), and lying about tools (no ARM read tools in the list). Beyond Azure: any non-finserv workload (healthcare, retail, devtools, internal platform) faces the same wall. The marketed "multi-cloud, multi-domain" platform is in reality a single-tenant AWS-finserv demo at the intake layer.

**Workaround options considered:**
- (a) Lie: pick AWS + closest service approximations → produces an artifact that misrepresents the workload, defeats the POC's purpose
- (b) Pivot workload to AWS Deployment Architect → still proves V1→V2 dogfood flow, but abandons the Azure rationale
- (c) Pause POC, in-S55 platform patch: make cloud + chip lists configurable, then resume

**Recommendation:** (c). Time-box ~1-2 hours. The fix is small (replace hardcoded arrays with a backend-served catalog or env-configurable constant) and unblocks every future non-finserv-on-AWS customer onboarding, not just this POC.

**Priority:** P0 (blocks current POC; blocks all non-finserv-on-AWS customers)

---

### F-003 · PLATFORM-GAP · RAG Sources / Tools / External Integrations chips are finserv-locked (non-blocking)

**Found:** P1 Step 2 verification, 2026-05-26 (after F-002 patch landed)
**Where:** `team-portal/src/pages/ai-systems/RegisterSystemPage.tsx` (Step 2 — three chip groups not touched by F-002 patch)
**What:** Cloud-conditional rendering fixed the Services chip list, but three sibling chip groups remain hardcoded to finserv vocabulary:
- RAG Sources: `FinCEN Advisories, Underwriting Standards, Regulatory Guidance, ...`
- Tools/APIs: `lookup_transaction, hold_payment, search_sanctions, credit_decision, ...`
- External Integrations: `Core Banking, Payments Platform, AML Platform, OFAC/SDN, ...`
**Impact:** Non-blocking (chips can be left empty), but misleading for any non-finserv workload. An Azure infra agent's actual tools (`list_subscriptions`, `get_network_topology`, etc.) are not in the chip list — operator has to leave the field blank and document tools elsewhere, which weakens intake completeness.
**Workaround in POC:** Leave the three chip groups empty; tools list documented in README + agent repo.
**Proposed fix (S56):** Lift to backend-served catalog (`/api/intake/catalog?domain=X&cloud=Y`) managed by CISO Console — same pattern as F-001's proposed domain catalog. Sibling fix.
**Priority:** P2 (non-blocking; bundled with F-001/F-002 catalog story)

---

### F-004 · PLATFORM-GAP · Backend field name `aws_services` is cloud-specific (cosmetic)

**Found:** While patching F-002, 2026-05-26
**Where:** `api/intake.py:127`, `domain/models.py:409`, and 14 other files
**What:** The backend field that holds Step 2's services chip selection is named `aws_services`. After the F-002 patch, this field now holds Azure/GCP services too — the name is a lie about contents.
**Impact:** Cosmetic / discoverability. Doesn't break anything (the field is `list[str]`), but a future maintainer reading `aws_services: list[str] = []` on an Azure record will be confused. Migration risk.
**Proposed fix (S56):** Rename `aws_services` → `cloud_services` across 16 files; keep `aws_services` as a deprecated alias on Pydantic in/out for one release.
**Priority:** P3 (cosmetic; bundle with the F-001/F-002/F-003 catalog story)

---

### F-005 · PLATFORM-GAP · Step 5 Evidence Upload field labels + placeholders are AWS-finserv flavored (cosmetic)

**Found:** P1 dry-run, 2026-05-26
**Where:** `team-portal/src/pages/ai-systems/RegisterSystemPage.tsx` Step 5
**What:** Eight URL fields with AWS-specific labels and placeholders: `Bedrock Configuration` (placeholder "ModelInvocationLoggingConfiguration export"), `IAM Policy` (placeholder "Policy ARN or document link"), `Logging Config` (placeholder "CloudWatch / Macie config"), `Terraform / CloudFormation` (placeholder "Git repo or commit URL"). Backend fields are named identically (`bedrock_config_url`, `iam_policy_url`, etc.).
**Impact:** Cosmetic. Fields accept any URL — operator can paste an Azure Monitor link into `Logging Config`. But labels misrepresent the artifact type collected. Same naming-lie pattern as F-004.
**Workaround in POC:** Paste Azure-equivalent URLs into the closest-named fields; document mapping in README.
**Proposed fix (S56):** Cloud-conditional labels + placeholders (same pattern as F-002 Step 2 patch), OR fully generic field names (`model_config_url`, `logging_config_url`, `iac_url` already generic-ish).
**Priority:** P3 (cosmetic; bundle with F-004 rename story)

---

### F-006 · DOC-GAP / PLATFORM-GAP · SDK decorator chain README is wrong (trace/evaluate are functions, not decorators)

**Found:** P2 dry-run wiring, 2026-05-26
**Where:** `sdk/README.md`, `sdk/signallayer/__init__.py` (chain assertion in `signallayer.guard()`)
**What:** Platform README documents a 5-decorator chain `@policy_gate → @scrub_pii → @guardrails → @trace → @evaluate`. In practice `trace` and `evaluate` are SDK aliases for the `tracer.trace_call(...)` and `evaluator.evaluate_response(...)` *functions*, not decorator factories. They are called INSIDE the decorated function body with computed args, not stacked above it. `signallayer.guard()` enforces all 5 names being stamped, which is impossible to satisfy with the SDK as shipped.
**Impact:** Anyone following the SDK quickstart literally cannot make `guard()` pass. Decorator stack appears broken until a maintainer explains the mental model. Erodes first-impression credibility of the SDK.
**Workaround in POC:** `agent.py` uses the 3 real decorators (`policy_gate`, `scrub_pii`, `guardrails`) and inlines `signallayer.trace(...)` / `signallayer.evaluate(...)` calls inside the function body in P4. Documented the gap in `agent.py` module docstring.
**Proposed fix (S56):** Either (a) ship `@signallayer.trace` and `@signallayer.evaluate` as real decorator factories so the docs match reality, OR (b) rewrite README to show the 3-decorator + 2-inline-call pattern and remove the all-5 enforcement from `guard()`.
**Priority:** P1 (blocks SDK quickstart; first thing every new customer hits)

---

### F-007 · PLATFORM-GAP · Smoke Probe 8 never exercises HMAC end-to-end

**Found:** P2 dry-run, 2026-05-26
**Where:** [deploy/smoke_portal.ps1:291-355](../../deploy/smoke_portal.ps1), [deploy/smoke_gov.ps1](../../deploy/smoke_gov.ps1)
**What:** Probe 8 labels itself "SDK key issuance round-trip" but only exercises the **operator** lifecycle (session-cookie auth on `/api/sdk-keys/*`: issue → status → revoke). It does NOT make any HMAC-signed call to `/api/sdk/*`. HMAC signing has been silently untested in prod for an unknown number of sessions.
**Impact:** Two compounding effects:
1. F-008 (no `/api/sdk/*` routes mounted) shipped to prod undetected for the full V1→V2 arc.
2. Any HMAC signing regression in the SDK or middleware would not surface until a real agent tried to call.
**Workaround in POC:** Hand-verified HMAC during this session against a freshly-issued key (`slk_ba951763`) — confirmed sig path is correct; the 401 on the wizard-issued key was a transcription typo from the screenshot.
**Proposed fix (S56):** Add Probe 9 to both smoke scripts — issue a key, sign a `GET /api/sdk/health` request, assert 200 + `first_seen_at` populates within 5s, then revoke. The new F-008 endpoint is the natural target.
**Priority:** P1 (test gap; the underlying surface was missing per F-008 which is now fixed)

---

### F-008 · PLATFORM-GAP · /api/sdk/* prefix had no routes mounted (was BLOCKING for P2; RESOLVED)

**Found:** P2 dry-run, 2026-05-26
**Where:** [middleware/hmac_auth.py:62](../../middleware/hmac_auth.py), [api/](../../api/) (no router with `prefix="/api/sdk"` existed)
**What:** S09 designed and shipped the HMAC middleware to guard `/api/sdk/*`. Every reference — `sdk_keys.py:10` docstring, `middleware/auth.py:45` PUBLIC_PREFIXES, `middleware/hmac_auth.py:62` SDK_PREFIX — documents this prefix as the canonical SDK-facing surface. But **no FastAPI router was ever mounted under this prefix.** The HMAC middleware guarded a route prefix with zero endpoints — every request to `/api/sdk/*` either got 401 (signature fail) or 404 (after middleware passes). The S53 wizard's "Verify Signal" step polls `first_seen_at`, which is set by the HMAC middleware on successful auth, but the SDK had no actual endpoint to call.
**Impact:** BLOCKED P2. Wizard's Step 3 ("Verify Signal") could never flip green. Every customer following the SDK onboarding flow would stall at "waiting for first signal".
**Workaround in POC:** Resolved this session — shipped [api/sdk_runtime.py](../../api/sdk_runtime.py) with `GET /api/sdk/health`. Minimal 200 response; the HMAC middleware's `mark_first_seen` side-effect is the actual value. Mounted in `dashboard.py` between `sdk_keys_router` and `frameworks_router`.
**Status:** RESOLVED 2026-05-26 — fix lands in the same S55-prep commit batch.
**Priority:** P0 (was blocking POC; fixed)

---

### F-009 · PLATFORM-GAP · Deploy zip ships data/ — every CI deploy wipes all runtime state (P0)

**Found:** P2 dry-run, 2026-05-26 — caught when a freshly-issued SDK key returned 404 from `/api/sdk-keys/{key_id}/status` after a routine CI deploy 12 minutes after issuance.
**Where:** [deploy/build-zip.py:51](../../deploy/build-zip.py) — `INCLUDE = [..., "data"]`
**What:** The deploy zip bakes in `data/` from the local repo. The local repo's `data/sdk_keys.jsonl` has 3 stale seed keys against `sys-payments-001`. On every CI deploy, the App Service zip extraction overwrites the prod runtime `data/sdk_keys.jsonl` (and every other writable JSONL under `data/`) with the repo's stale snapshot. Effects observed in this session:
- Wizard-issued `slk_a0f3aae8` (P1 outcome): wiped 12 min after issuance, before P2 could call it.
- API-issued `slk_ba951763` (debug key): wiped within the same window.
- The deploy that wiped them was 4b91121 (S55 #1, mounting `/api/sdk/health`).

**Other data lost on every deploy (inferred — full audit pending):**
- `ai_systems.jsonl` (every real-mode AI system intake)
- `findings_events.jsonl` (every CISO finding)
- `assurance_audit.jsonl` (chain-of-custody for every approval / decision — the chain is supposed to be append-only and cryptographically linked; deploys break the chain)
- `runtime_state.jsonl`, `runtime_approvals.jsonl`, `runtime_incidents.jsonl` (every production state transition)
- `assessments.jsonl`, `events.jsonl`, `release_gates.jsonl`, `rtf_completed_index.jsonl`, `simulated_eval_runs.jsonl`, `policy_decisions.jsonl`, `guardrail_violations.jsonl`, `injection_attempts.jsonl`, `connector_*.jsonl`, ...

**Why smoke didn't catch it:** Smoke Probe 8 (F-007) issues a key and revokes it in the same process invocation — never spans a deploy. Smoke 7 measures `count(v2)` against `count(v1)`, both of which are static seeds.

**Impact:** CRITICAL. The platform's persistence model is broken end-to-end. Every customer-visible state — intakes, keys, findings, approvals, audit chain — is silently truncated on every push to main. The audit chain claim (cryptographic chain-of-custody) is structurally false: each deploy creates a discontinuity.

**Workaround in POC:** Resolved this session — removed `"data"` from `build-zip.py` INCLUDE list. `storage._read_jsonl()` returns `[]` on missing files; `storage._append_jsonl()` creates in append mode. First request after deploy will recreate `data/` empty; new state accumulates there until the App Service container is rebuilt (which is rare; App Service plan persistence carries state across container restarts within the same plan).

**Real fix (S56+):** Move runtime data off the App Service filesystem into proper persistence. Options:
- Cosmos DB (per-JSONL-file as a container) — best fit for the existing `_append_jsonl`/`_read_jsonl` shape.
- Azure Storage Blob (one blob per JSONL, append-blob type).
- Azure Files mounted volume (least change to existing code).

**Compound rule (memory):** Any deploy artifact that bundles "data" or "state" alongside code is a footgun on every deploy. The platform's "stateless container" assumption must apply to the artifact, not just the runtime. Sibling of S54 #2 (slot swap wipes non-sticky settings) — same class of "silent overwrite via deploy mechanism."

**Status:** PARTIALLY RESOLVED 2026-05-26 — fix prevents future wipes but does NOT restore lost prod state. P1 wizard-issued key + system are gone; user must re-register if desired.

**Priority:** P0 (critical correctness)

---

### F-010 · PLATFORM-GAP · Inventory list endpoint never reads intake-written systems (P0, RESOLVED)

**Found:** P2 re-registration, 2026-05-26 — user re-registered the Azure Architect AI system after F-009 wipe; SDK key issuance returned a valid `ai_system_id` (data_source=real) but the inventory page showed total=0 in V2 mode.
**Where:** [api/grc.py:660-671](../../api/grc.py) — `GET /api/grc/ai-systems` used `AI_SYSTEMS` imported from `mock_data.py` (5 hardcoded seed dicts), NOT `domain.repository.list_ai_systems()` which concats seed + intake-written JSONL.
**What:** The intake submit handler (`api/intake.py:417`) writes the new AISystem to `data/ai_systems.jsonl` via `_append_jsonl`. The repository's `list_ai_systems()` reads both seed + JSONL correctly. But **the SPA-facing inventory endpoint imports only the mock_data seeds and never consults the repository.** Result: every customer-registered system was invisible to the portfolio list view. Has been broken since the intake feature shipped (at least back to S52, possibly earlier).
**Impact:** P0 — every customer onboarding through the V2 wizard produces a "phantom" system: the wizard says "submitted!", the redirect URL contains a valid `ai_system_id`, the SDK key issuance succeeds (the issuance code path correctly reads from the repository, see `api/sdk_keys.py:_resolve_system_data_source`), but the inventory page and direct GET endpoint return as if the system doesn't exist. Catastrophic onboarding UX.
**Why it wasn't caught:** The wizard's success path redirects to `/onboarding/{ai_system_id}` (a wizard sub-page), not the portfolio. The customer only sees the gap if they navigate back to inventory. Smoke probes test the seed list (V1=5, V2=0) which is the "correct" result given there were no intake systems persisted across deploys (F-009 ensured nothing survived). F-009 + F-010 covered for each other.
**Fix (this commit):**
1. `api/grc.py::list_ai_systems` now merges `AI_SYSTEMS` (seed dicts) with `domain.repository.list_ai_systems()` (intake AISystem models). New helper `_intake_to_summary_view` maps the domain shape → view shape for `AiSystemSummaryOut`. Computed fields (`open_findings`, `last_assessment`, etc.) default to zero/empty for intake rows — proper enrichment is sibling S56 work.
2. `api/grc.py::get_ai_system` (direct GET) falls back to the intake-stored row if the seed list miss, so the detail page resolves instead of 404'ing.
**Status:** RESOLVED 2026-05-26 — lands in same commit batch as F-008/F-009 close.
**Sibling work (S56 backlog):**
- Enrich intake rows with computed `open_findings` / `critical_findings` / `last_assessment` (requires findings + assessments to be joined like the seed path does)
- Migrate the seed `AI_SYSTEMS` mock dicts to the Pydantic shape so both paths go through one view-mapper
- Audit every other `mock_data.X` import in `api/grc.py` for the same class of bug (FINDINGS, RELEASE_GATE_RESULTS, EVIDENCE, RUNTIME_EVENTS all potentially same gap)
**Priority:** P0 (was breaking onboarding UX; fixed)

---

**Note on numbering:** Earlier draft notes used F-012/F-013/F-014/F-015/F-016 informally during the S55 debug session; the canonical numbering on disk is F-011 (slot swap) followed by F-012 (intake AWS-only), F-013 (key proliferation), F-014 (`.env` host bug), F-015 (`first_seen_at` telemetry). The retrospective is the source of truth.

---

### F-011 · PLATFORM-GAP · Slot swap wipes data/ even when zip excludes it (P0, RESOLVED)

**Found:** S55, 2026-05-26 — immediately after F-009 fix. User's re-registered `ai-sys-9832577d` + key `slk_df836485` were both wiped by the S55 #3 deploy (commit 0283891), even though that zip excluded `data/`.
**Where:** [.github/workflows/deploy.yml](../../.github/workflows/deploy.yml) — slot swap step. Plus every `_DATA_DIR = Path(__file__).resolve().parents[1] / "data"` site (24 files).
**What:** F-009's fix (remove `data/` from zip) was necessary but NOT sufficient. The App Service slot-swap mechanism trades the **entire `wwwroot/`** between slots on every swap — including `data/` even when it's not in the new zip. Staging's `data/` (frozen from old-zip-era deploys + whatever its last warmup wrote) replaces production's on every swap.
**How it stayed hidden after F-009:** F-009 verification used a key issued AFTER c72ab91 deployed; that key happened to survive because no subsequent deploy ran in the verification window. Once S55 #3 deployed (0283891), the swap wiped the prior runtime state.
**Impact:** P0. Without this fix, every CI deploy continues to silently wipe ai_systems.jsonl, sdk_keys.jsonl, findings_events.jsonl, assurance_audit.jsonl (the audit chain), and ~20 other writable JSONL files. F-009 alone was a false-positive close.
**Fix (this commit):**
1. **Code** — every `DATA_DIR` resolution (24 sites across api/ + domain/ + storage.py) now reads from env var `DATA_ROOT` first, falling back to the repo-relative path for local dev. Bulk-patched via a regex script for the 20 uniform sites; 4 outliers (storage.py, audit_chain.py, projection_worker.py, right_to_forget.py — different patterns or type annotations) were patched individually.
2. **App setting** — `DATA_ROOT=/home/data` set with `--slot-settings` on BOTH production and staging slots. `/home` is mounted from Azure Files per App Service plan and is **shared across all slots** — slot swap of `wwwroot/` is a no-op for `/home/data/`. The sticky flag means `DATA_ROOT` itself never swaps either.
**Trade-offs:**
- Production and staging slots now write to the same `/home/data/`. During staging warmup, any writes from staging would land in shared storage. Acceptable: warmup is read-only health probes; no intake / key issuance happens during warmup. If this becomes an issue, the next step is per-slot data directories with a sync-before-swap workflow step.
- Existing prod state in `/home/site/wwwroot/data/` (the user's `ai-sys-1ff2b903` + my `slk_c0dc8004`) is NOT migrated by this fix. Couldn't shell into prod (auto-mode classifier denied Kudu remote-shell access — fair guardrail). Those rows are lost when this fix deploys, but it's the LAST time anything is lost.
**Sibling work (S56 backlog):**
- Migrate to proper persistence (Cosmos DB or Blob Storage append-blobs). The current fix is a workaround; the real architecture move is off the App Service filesystem entirely.
- Add a smoke probe (Probe 10) that issues a key, deploys, and re-checks the key. Closes the F-009 + F-011 detection gap for future regressions.
**Status:** RESOLVED 2026-05-26 — lands in same commit as the env-var refactor.

**Post-mortem update (2026-05-26, same day):** Initial verification SHOWED the fix failed (state still wiped after slot swap). I built a hypothesis that `/home` was per-slot on this plan, and switched to direct-to-production deploys (S55 #5). After that ALSO failed, the actual root cause emerged: **the `az` command that set DATA_ROOT was run in Git Bash on Windows, which path-mangled the value from `/home/data` to `C:/Program Files/Git/home/data`.** The container saw the garbled value, wrote to a nonsensical sub-path inside wwwroot, and that subpath got wiped on every deploy. Lesson: when an env var value is a Linux path, the global `MSYS_NO_PATHCONV=1` rule applies to `az` commands too, not just `az staticwebapp` / `az functionapp` as the prior memory implied. Memory rule extended.

Final acceptance test 2026-05-26: registered `ai-sys-ede33ad4` post-DATA_ROOT-fix; triggered a fresh CI deploy via `gh workflow run`; confirmed `ai-sys-ede33ad4` still visible in V2 inventory after the deploy completed. F-011 is now actually fixed.
**Compound rule:** Updated [[deploy-zip-overwrites-runtime-data]] to add: "data/ in wwwroot/ ALSO gets wiped by slot swap, even if absent from the deploy zip. Persistence must live OUTSIDE wwwroot/ (under /home/ or external storage)."
**Priority:** P0 (was wiping prod state on every deploy; fixed)

---

### F-012 · PLATFORM-GAP · Intake wizard hard-codes Cloud Provider to AWS-only (cosmetic)

**Found:** S55 post-mortem, 2026-05-26 — while re-registering `ai-sys-bae72e75` for POC P2.
**Where:** [static/ai-systems-new.html:205](../../static/ai-systems-new.html#L205) — `selectField("Cloud Provider", "cloud_provider", ["AWS"], { required: true })` and all of Step 2's chips (`AWS Services Used`, `Bedrock`, etc.).
**What:** F-002 was logged as "PARTIALLY RESOLVED" on the API side, but the legacy static intake wizard still presents only AWS as a cloud provider with AWS-flavored service chips. An Azure (or GCP, or multi-cloud) workload has no native option; operator must pick "AWS" and stuff Azure detail into free-text fields.
**Impact:** Cosmetic for assurance posture (`cloud_provider` is metadata, doesn't branch risk engine or control binding). Misleading for the operator and contradicts the V2 multi-cloud arc claim.
**Workaround:** Select AWS, leave Step 2 chips empty, describe Azure detail in Description / Model Provider / Use Case.
**Fix (S56):** Add Azure + GCP options to the cloud_provider select; replace the AWS-only service chip list with a cloud-conditional chip set.
**Priority:** P2 (UX, not correctness)

---

### F-013 · PLATFORM-GAP · Wizard auto-mints a new SDK key on every page mount (key proliferation) — FIXED IN SOURCE 2026-05-26

**Found:** S55 post-mortem, 2026-05-26 — verifying first_seen_at after dry-run.
**Where:** [team-portal/src/pages/onboarding/OnboardingPage.tsx:165](../../team-portal/src/pages/onboarding/OnboardingPage.tsx#L165) — `useEffect(... void issueKey(systemId); ...)` fires `POST /api/sdk-keys` unconditionally on every mount of `/onboarding/:system_id`.
**What:** Every refresh / re-login / tab-restore on the onboarding wizard mints a brand-new key for the same AI system. Operator's hand-saved `.env` from a prior mount becomes silently orphaned (still HMAC-valid; just no longer the key the wizard polls). During this debug session at least 3 keys were minted for `ai-sys-bae72e75` (slk_5b4dfc09, slk_301660cb, plus the one minted on the latest reload).
**Symptom:** Operator follows the wizard, runs dry-run, sees wizard's Step 3 stuck on "Waiting…" because the wizard is polling the *latest* mint, not the key in the operator's `.env`. This is what made F-015 LOOK like an engine persistence bug for hours — the agent and the wizard each had a key the other side never touched.
**Fix (this commit):** Renamed `issueKey` to `bootstrapKey`. On mount, calls `GET /api/sdk-keys?ai_system_id=...&include_revoked=false` first. If a non-revoked key exists, surfaces a "returning user" UI (key_id + issued_at + first_seen_at + a Rotate button), tells the operator to use the `.env` they saved on first visit, and points FirstSignalPanel at the EXISTING key_id so polling matches the agent's actual traffic. If `first_seen_at` is already populated on the existing key, the wizard jumps straight to Step 3 in a green state — re-opening the page after verification "just works."
**Implementation notes:**
- Plaintext secret is unrecoverable (only sha256 hash stored beyond issuance — by design). Returning users cannot re-reveal the secret; they MUST use the `.env` they saved or explicitly Rotate (mint a new key + revoke the old via the AI System detail page).
- Step 2 (snippet) doesn't render in returning-user mode because there's no plaintext to inject. Operator has the snippet from their first visit; if they don't, the Rotate button is the recovery path.
- The Rotate flow currently only mints — server-side revocation of the prior key is a separate explicit action via the AI System detail page. Auto-revoke-on-rotate could ship later but raises the risk of accidentally invalidating a working agent.
**Verification gap:** The fix is in source; the deployed SPA still auto-mints until the team-portal SPA is rebuilt + redeployed. Runs through the same channel as F-014's pending SPA deploy.
**Priority:** P1 (was the root cause of the misdiagnosed F-015 — the entire "Verify Signal" gate appears broken when this fires, even when the engine is healthy)

---

### F-014 · PLATFORM-GAP · `Copy as .env` emits SPA host as engine base URL (load-bearing UX bug, FIXED IN SOURCE)

**Found:** S55 post-mortem, 2026-05-26 — explained why the dry-run hit a 200 with SPA HTML body instead of engine JSON.
**Where:** [team-portal/src/pages/onboarding/OnboardingPage.tsx:65-72](../../team-portal/src/pages/onboarding/OnboardingPage.tsx#L65-L72) — `engineBaseUrl` derived from `window.location.host`, which is the SWA host (`portal.aigovern.sandboxhub.co`), not the engine apex (`aigovern.sandboxhub.co`).
**What:** The S55 #8 "Copy as .env" button emitted `SL_API_BASE_URL=https://portal.aigovern.sandboxhub.co`. The SWA returns `index.html` (200) for every unknown path, so the SDK appeared to succeed but never touched the engine. HMAC middleware never ran. `first_seen_at` never populated. Every operator who used the new button got a silently-broken `.env`.
**Impact:** Same end-state as F-008 (no traffic to the engine) but with a 200 OK that misleads diagnosis. Burned the bulk of S55's final hour.
**Fix (in this commit):** Source `engineBaseUrl` from `import.meta.env.VITE_API_BASE_URL` (strip `/api/v*` suffix to get the origin). Fall back to `window.location` only when `VITE_API_BASE_URL` is unset.
**Verification gap:** The fix is in source; the deployed SPA still emits the old value until the team-portal SPA is rebuilt + redeployed in S56. Operators using the wizard between now and that rebuild must manually correct `SL_API_BASE_URL` to `https://aigovern.sandboxhub.co`.
**Sibling work (S56):** Rebuild + deploy team-portal SPA to ship the fix to operators.
**Priority:** P1 (every operator using the wizard's headline "Copy as .env" button got broken config — UX bug, not security)

---

### F-015 · MISDIAGNOSIS — engine is fine, this was F-013 wearing a different shirt (CLOSED 2026-05-26, NO BUG)

**Found:** S55 post-mortem, 2026-05-26.
**Root cause:** Instrumented `mark_first_seen` (S55 #10/#11), deployed, and pulled live logs. The single instrumentation line told the whole story:
```
sdk_keys.first_seen.noop key_id=slk_5b4dfc09 already=2026-05-26T21:55:54.189969+00:00
```
The dry-run was hitting **`slk_5b4dfc09`** (the very first key minted in this session, still in `.env`) — and the engine had been correctly stamping `first_seen_at` on that key since 21:55:54 UTC. The wizard was polling **`slk_<latest-mint>`** — a different key — because F-013 mints a fresh key on every wizard mount. The agent and the wizard were each looking at a key the other side never touched.
**Implication:** the engine works correctly. `mark_first_seen` writes, persists, and is read back fine. There is no telemetry persistence gap. The wizard's red ⚠ was 100% F-013's fault.
**Why this was hard to see:** the wizard's auto-mint happens silently on mount. Operator never sees "you have N keys for this system, here's the latest one" — they see "here's your new key, copy the secret." So the operator's mental model is "one wizard visit = one key," when reality is "one wizard mount = one new key." Add to that the SPA-host-vs-engine-host confusion of F-014 and you get a debug session that touches half the codebase before the instrumented log line drops the answer in your lap.
**Fix:** Closed by F-013's fix in this same commit — the wizard now lists existing un-revoked keys before minting, and FirstSignalPanel polls the existing key's status when present. F-015 disappears as a side effect.
**Instrumentation:** Kept at `logger.info` level (S55 #10 + #11) — useful diagnostic for the next time something looks like a persistence gap. The four breadcrumbs (`.enter` / `.read` / `.miss` / `.noop` / `.wrote` / `.failed`) make this class of bug a one-tail diagnosis instead of a half-day deep dive.
**Status:** CLOSED — no engine bug existed. Lesson: when the symptom looks impossible (engine returns 200 but state doesn't change), it's usually a "different keys" or "different DATA_DIR" problem before it's ever a "write silently fails" problem. Add an instrumentation breadcrumb FIRST, not last.

---

### F-015-orig (HISTORICAL — kept for posterity, since it was the working hypothesis for hours)

**Found:** S55 post-mortem, 2026-05-26 — POC P2 acceptance test partial pass.
**Where:** [middleware/hmac_auth.py:246-252](../../middleware/hmac_auth.py#L246-L252) and/or [domain/sdk_keys.py:246-263](../../domain/sdk_keys.py#L246-L263) — `mark_first_seen` either is not being invoked, or is being invoked and silently failing on the `_rewrite_jsonl` write. The middleware's try/except swallows the exception with a `logger.exception` that's not surfacing in the downloaded log window.
**What:** After multiple verified-200 HMAC-signed calls to `/api/sdk/health` from the agent using `slk_301660cb`, `GET /api/v1/sdk-keys/slk_301660cb/status` continues to return `first_seen_at: null`. The handler returns the canonical `{"ok":true,"service":"aigovern-engine"}` (confirms route ran), unsigned probe returns 401 (confirms middleware is active), and `env_fallback` is mathematically excluded (cannot equal a freshly-minted 32-byte random plaintext). Therefore the registered_key branch matched and `mark_first_seen` should have fired — but didn't persist.
**Hypotheses (S56 to root-cause):**
1. `_rewrite_jsonl` raising an exception on `/home/data/sdk_keys.jsonl` (write permission, file lock, atomic rename across mount). Exception swallowed by middleware try/except, not surfaced in log window pulled.
2. Multi-worker isolation: `DATA_DIR` resolved at module import per worker; if any worker booted before `DATA_ROOT` was sticky-set, it writes elsewhere. Reads from a *different* worker see no update.
3. `SdkKey.model_validate` rejecting the on-disk row (schema drift), so `get_by_key_id` returns None → `_resolve_secret_for_key` falls through to `env_fallback` — but env_fallback then somehow accepts the per-key signature (would require global secret == per-key secret, impossible by construction). Less likely than #1 or #2.
**Impact:** POC P2's "Verify Signal" wizard step never flips green even when the agent is fully functional. Telemetry / UX bug, not a security or correctness bug — HMAC verification itself works end-to-end. POC P2 is substantively pass (chain runs, engine accepts signed traffic, real-mode key authenticates) but the wizard's UI gate stays red.
**Fix (S56):** Add a `logger.info("sdk_keys.mark_first_seen attempt key_id=%s", key_id)` before the write and `logger.info("sdk_keys.mark_first_seen wrote key_id=%s", key_id)` after — capture from real-time `az webapp log tail` during a dry-run to bisect read-vs-write vs worker-isolation. Likely fix is a single line (don't swallow the exception, or add an `os.fsync`).
**Priority:** P1 (blocks the wizard's headline acceptance gate even when engine is healthy)

---

## POC P2 — SUBSTANTIVE CLOSE (2026-05-26)

**Acceptance proven:**
- ✅ 3-decorator chain (`policy_gate → scrub_pii → guardrails`) loads + executes in an external agent process (`agents/azure-architect/agent.py`)
- ✅ External agent makes an HMAC-signed call to engine `/api/sdk/health` and receives the canonical handler response (`{ok: true, service: "aigovern-engine"}`)
- ✅ Engine rejects unsigned probes with 401 (confirms HMAC middleware is the gate, not a no-auth shortcut)
- ✅ Real-mode key (`data_source: "real"`, issued via wizard for `ai-sys-bae72e75`) authenticates the request
- ✅ F-008, F-009, F-010, F-011 fixes all hold under the live agent traffic

**Known gaps deferred to S56:** F-012 (UX), F-013 (UX), F-014 (UX, fixed in source), F-015 (telemetry).

**Decision:** POC P2 advances to P3. F-015's wizard "Verify Signal" gate stays red until S56 lands the telemetry fix, but the underlying engine contract is proven and the agent is shipping signed traffic to a key it owns. P3 (upload OPA policy + verify framework matrix) is unblocked.

---

### F-016 · PLATFORM-GAP · Trace persistence silently no-ops when Langfuse creds are unset

**Found:** S55, 2026-05-26 — POC P3 close-out review.
**Where:** [tracer.py:93-96](../../tracer.py#L93-L96) — when `_get_client()` returns None (no `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY`), `_trace_call_impl` builds a synthetic timestamp-based `trace_id` (`trace_YYYYMMDD_HHMMSS_NNNN`) and returns it without persisting the trace anywhere.
**What:** Every local `--review` run that completes "successfully" returns a `trace_id` that looks legitimate but corresponds to nothing on disk, in Langfuse, or in the engine. The agent prints the synthetic ID and the operator reasonably assumes their trace is queryable later. It is not — the prompt, response, latency, and tokens are dropped after the print.
**Smoking gun shape:** Langfuse-issued IDs are cuid2 (`cm0abc...`). Synthetic IDs are timestamp-based (`trace_20260526_195405_541`). If you ever see the timestamp shape returned, the trace went nowhere.
**Impact:** P1 — the agent appears to satisfy the platform's audit contract while silently failing to. For workloads regulated under EU AI Act / NIST AI RMF, this is the entire point of having a trace, and the failure is invisible.
**Fix options (S56):**
  1. (Recommended) Loud warning at module load when `_get_client()` returns None, and refuse to return a trace_id unless Langfuse OR a local fallback wrote the trace.
  2. Local JSONL fallback at `data/traces.jsonl` so traces persist even without Langfuse — engine then has a path to render them in the CISO Console trace viewer.
  3. Both — warn AND fallback. JSONL is the durable-by-default path; Langfuse is the visualization path.
**Priority:** P1 (silent telemetry loss class — same family as F-015's misdiagnosis lesson: "if the symptom looks impossible, look for a silent no-op first").

**Status:** CLOSED in S56 #1 (commit `c73bc70`). Resolution went further than the original framing: option 3 (warn + JSONL fallback) PLUS a previously-unknown SDK-drift fix.
  - Module-level warning fires at `tracer.py` import when `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` absent (CI log confirmed it lands cleanly).
  - Every trace is appended to `data/traces.jsonl` (joinable with `data/evals.jsonl` via `trace_id`), regardless of whether Langfuse is configured.
  - **Bonus find:** Langfuse 4.x renamed `create_generation` → `start_observation`. The old code had been silently no-op'ing remote tracing in prod since the SDK upgrade because of the `except: pass` swallow. Switched to `client.start_as_current_observation(as_type='generation', ...)`. `langfuse_sent` field in `traces.jsonl` now reflects actual API success, not just "client constructed."
**Lesson:** when you remove a `bare except: pass`, expect to discover at least one broken integration. Worth a memory entry.

---

### F-017 · PLATFORM-GAP · Eval scores have zero persistence path (P0)

**Found:** S55, 2026-05-26 — user asked "where are the evals from A" after the live `--review` run; reading the code revealed they're nowhere.
**Where:**
  - [evaluator.py:264-293](../../evaluator.py#L264-L293) — `evaluate_response` proxies to the backend, returns a dict to the caller. No write.
  - [providers/backends/deepeval_evaluator.py](../../providers/backends/deepeval_evaluator.py) — backend calls `_evaluate_impl`, returns the dict, done. No write.
  - [agents/azure-architect/agent.py:206-225](../../agents/azure-architect/agent.py#L206-L225) — agent stores the dict on the result and `_print_review` prints it. No write.
**What:** The eval pipeline has no persistence implementation anywhere — not in the SDK, not in the engine, not in the agent. Every metric score generated by `--review` exists only in the terminal's scrollback. There is no JSONL store, no Langfuse score upload, no audit-chain entry, no engine endpoint to query later. The entire S55 #14 "live eval pipeline" claim is true at the *compute* layer but the data *vanishes* on process exit.
**Impact:** P0 — undermines the entire value proposition of having evals. The point of a 5-metric scoreboard is to (a) trend over time, (b) A/B prompts and measure relevancy/toxicity drift, (c) cite scores in compliance audits. None of those are possible when the scores aren't stored.
**Why this stayed hidden in S55 #14:** the calibration run worked end-to-end — print output looked great (relevancy 0.77, toxicity 0.00, etc.) and gave a strong illusion of success. The retrospective entry for #14 even says "5-metric eval" — true literally, false in the sense that *the platform contract* (evals as a persisted, queryable, auditable artifact) is unmet.
**Fix options (S56):**
  1. (Recommended) Langfuse `client.score(trace_id=..., name=metric_name, value=score)` calls inside the DeepEvalEvaluator backend — co-locates eval scores with the trace they evaluate. Requires F-016 fix first (need a real trace_id).
  2. JSONL persistence at `data/evals.jsonl` with `{trace_id, metric_name, score, passed, details, ts}` shape. Mirrors the SDK keys pattern. Add `GET /api/v1/evals?trace_id=...` so the CISO Console can render scores in the trace viewer.
  3. Both — Langfuse for the visualization path, JSONL for the durable platform record. Mirrors F-016 #3.
**Sibling work (S56):**
  - Engine endpoint + CISO Console panel to render the scoreboard for a given trace. Without that the JSONL is just bytes.
  - Eval-trend dashboard — a chart of relevancy / toxicity / pii_leakage scores over time per workload. The relevancy=0.77 result in S55 #14 (Sonnet drifted into cross-region recommendations for an explicitly single-region input) is exactly the kind of signal that becomes valuable when trended.
**Priority:** P0 — promised platform capability ships hollow.

**Status:** CLOSED in S56 #1 (commit `c73bc70`). Option 3 (Langfuse + JSONL).
  - `evaluate_response()` signature extended with `trace_id`, `workload_id`, `model` kwargs. Agent threads `trace_id` from `tracer.trace_call()` straight through, so `data/traces.jsonl` and `data/evals.jsonl` join cleanly.
  - Each non-skipped metric pushed to Langfuse via `client.create_score(trace_id=..., name=..., value=..., data_type='NUMERIC')` (the 4.x rename — old `score()` was failing too, same root cause as F-016).
  - New `GET /api/v1/evals?trace_id=&workload_id=&limit=` endpoint at [api/evals.py](../../api/evals.py) reads the JSONL back. Returns the file path in the response for operator transparency.
  - Sibling work (CISO Console trace-viewer panel with scoreboard, eval-trend dashboard) is deferred — the data store now exists, the rendering can come when the trace viewer itself is built.

---

### F-018 · DOC-GAP / PLATFORM-GAP · POC plan's "CISO Console policy upload UI" doesn't exist (P2)

**Found:** S55, 2026-05-26 — POC P3 close-out. User attempted the documented step "CISO Console → Policy Governance → upload policy" and reported there is no upload button anywhere in the CISO portal in prod.
**Where:**
  - Plan: [docs/plans/AZURE-ARCHITECT-POC.md §P3 step 2](../../docs/plans/AZURE-ARCHITECT-POC.md#L79) — "CISO Console → Policy Governance → upload policy → verify it lands in fail-closed evaluator"
  - Reality: [ciso-console/src/pages/policies/PoliciesPage.tsx](../../ciso-console/src/pages/policies/PoliciesPage.tsx) renders `mock_data.POLICIES` (the conceptual control library, e.g. "Review policy update: Tool Authorization v2.1") via `GET /api/grc/policies`. No upload control, no .rego rendering, no link to the actual enforced policies in `policies/*.rego`.
  - The engine's OPA-style policy evaluator does load `policies/*.rego` at runtime — but only from the deployed `wwwroot/policies/` directory. Operators can't upload, list, or hot-reload via UI.
**What:** The P3 plan presumes a policy management UI that was never built. `.rego` policies ship through git → CI → /home/site/wwwroot/policies/ alongside the engine code, and there is no operator-facing visibility that they landed.
**Why it stayed hidden:** The CISO Console's `PoliciesPage` *has the word "policies" in its URL*, which gave the appearance of being the right surface. It's actually the GRC control-library viewer for finserv compliance items — distinct subject matter, same word.
**Mitigation (no UI build today):** Verification of policy activation is achievable via behavior: the agent's `--review` call passes through `@policy_gate(action="llm_call")` on the engine side. If `azure-architect.rego` failed to parse OR failed to evaluate, the call would have errored with a `PolicyDenied` (worst case) or 500 (parse error). S55 #14's successful Anthropic round trip is therefore the de-facto P3 acceptance test — the policy is active, parses cleanly, and integrates with the base.rego stack.
**Fix options (S56 or later):**
  1. (Smallest) New `GET /api/v1/policies/rego` endpoint that lists files in `policies/` with a parse-status flag per file, and a small CISO Console panel that renders the list read-only. Closes the "is it active?" gap without enabling upload.
  2. (Medium) Add a write endpoint backed by validation + hot reload + audit-chain entry, plus an upload button. Material work because of security model: who can upload? Does it merge or replace? Does it require a quorum?
  3. (Cleanest long-term) Treat `.rego` as code-only — these are enforcement contracts and belong in PRs, not in a UI. Update the plan to reflect that. The CISO Console gets a read-only "Active enforced policies" panel (option 1) and nothing else.
**Recommendation:** option 3 + option 1's read-only panel. Policy enforcement is too load-bearing for a UI upload path; PR review is the right gate.
**Knock-on:** `docs/plans/AZURE-ARCHITECT-POC.md §P3` needs updating to remove the "upload via CISO Console" step. The remaining P3 actions (framework matrix drill, EU AI Act PDF pack, intake Step 5 evidence URLs) all use UIs that DO exist.
**Priority:** P2 (documentation correctness; the underlying enforcement works).

**Status:** CLOSED in S56 #2 (commit `02de720`). Resolution = recommendation: option 3 + option 1's read-only panel. No upload UI — by design.
  - New `GET /api/v1/policies/rego` at [api/policies_rego.py](../../api/policies_rego.py) enumerates `policies/*.rego` with `filename`, `package`, `summary` (first comment line), `size_bytes`, `sha256`. Sha256 is the load-bearing audit field — "policy X was active on date Y" is provable by hash match against git history.
  - CISO Console gets a new read-only "Active enforced policies" panel via `RegoBundlesPanel` in [ciso-console/src/pages/policies/PoliciesPage.tsx](../../ciso-console/src/pages/policies/PoliciesPage.tsx), rendered above the existing GRC control-library table. Read-only by design.
  - [docs/plans/AZURE-ARCHITECT-POC.md §P3 step 2](../../docs/plans/AZURE-ARCHITECT-POC.md#L79) rewritten: "Ship via git → CI; verify via 'Active enforced policies' panel + agent `--review` pass-through." No more upload claim.
**Compound rule earned:** "view" vs "upload" is the standard separation between change governance (git/PR/CI) and operational visibility (read-only panel). Conflating them is what F-018 was.

---

### S59 STEP 1 · P3 Framework Coverage matrix surface walkthrough

**Surface:** `gov.aigovern.sandboxhub.co` → Framework Coverage (portfolio matrix view)
**Date walked:** 2026-05-27
**Re-scope note:** Original target `ai-sys-bae72e75` (Azure Architect) shows 0% across all 8 frameworks (F-021 — no mappings populated yet for that system). Switched to portfolio-wide view of all 7 systems.

**Acceptance evidence (matrix-surface granularity):**
- Matrix renders 7 systems × 8 frameworks (56 cells); live screenshot captured this session.
- F-019 (export 401) + F-020 (display %) shipped and verified live — color thresholds and percentages now reflect real domain values.
- Two systems (`ai-sys-bae72e75`, `ai-sys-ede33ad4`) are 0% across the board → F-021 data-load gap.
- Three frameworks (ISO/IEC 42001, SR 11-7, FFIEC) are 0% for every system → expected; catalogs in `_PDF_NOT_YET`, Session-11 work.
- Five frameworks have live data: NIST AI RMF, NIST AI 600-1, OWASP LLM Top 10, OWASP Agentic Top 10, EU AI Act.

**Disposition:** P3 STEP 1 CLOSED at matrix-surface granularity. Per-cell RED-triage deferred to P5 (continuous monitoring) where individual-control drift is the natural lens.

**Carry-forward to P5:**
- Per-cell drill on `ai-sys-001` (Payments Exception Review Agent: 1-6% across all live frameworks — likely a controls-mapping gap, not a real coverage hole).
- F-021: populate framework mappings for `ai-sys-bae72e75` once P4 produces traces.
- F-022: portfolio rollup PDF before matrix-page "Export <framework>" buttons are usable end-to-end.

---

### S59 STEP 2 · EU AI Act PDF Pack generated for `ai-sys-002`

**Surface:** `gov.aigovern.sandboxhub.co` → Reports → EU AI Act PDF Pack
**Generator:** [pdf_report.py:616](../../pdf_report.py#L616) `generate_eu_ai_act_pack` (NIST AI RMF proxy mapping per file comment line 632)
**System:** `ai-sys-002` (AML Investigation Assistant) — EU AI Act matrix cell 91% green
**Artifact:** [agents/azure-architect/poc-evidence/p3-eu-ai-act-pack/eu-ai-act-pack-ai-sys-002.pdf](poc-evidence/p3-eu-ai-act-pack/eu-ai-act-pack-ai-sys-002.pdf)
**Size:** 153,976 bytes
**sha256:** `86c9382f2733025df95be2cac5747250aa1a4b66f25c1d7f6cf8a45303f466c6`
**Generated:** 2026-05-27

**Disposition:** STEP 2 ACCEPTED. PDF downloads cleanly via Reports surface (distinct from broken matrix-page export buttons per F-022). Sha256 above is the load-bearing audit value — same pattern as the .rego bundle hashes in F-018.

---

### F-019 · PLATFORM-BUG · CISO Console framework-export 401 (cross-origin cookie drop) (P1)

**Found:** S59 STEP 1, 2026-05-27 — operator opened Framework Coverage matrix at `gov.aigovern.sandboxhub.co`, clicked any "Export <framework>" button, got `Export error: Export failed: HTTP 401`. All 7 framework export buttons failed identically.
**Where:** [ciso-console/src/pages/frameworks/FrameworksPage.tsx:79](../../ciso-console/src/pages/frameworks/FrameworksPage.tsx#L79) — `exportPdf` bypasses the shared `apiPost` (because the response is binary PDF, not JSON) and uses a raw `fetch` with `credentials: 'same-origin'`. Shared client at [ciso-console/src/shared/api/client.ts:49](../../ciso-console/src/shared/api/client.ts#L49) correctly uses `credentials: 'include'`.
**What:** CISO Console SPA runs at `gov.aigovern.sandboxhub.co`; engine runs at apex `aigovern.sandboxhub.co` — two origins per [[two-origins-spa-vs-engine]]. `same-origin` causes the session cookie to be omitted on cross-origin POST → engine sees unauth → 401.
**Why it stayed hidden:** Every other API call goes through `apiRequest` which gets `credentials: 'include'` for free. PDF export is the only call that bypasses the helper (binary response forced a raw fetch). The special case forgot what the common case knew — exactly the gap a shared client exists to prevent.
**Fix:** 1-line change at line 79: `'same-origin'` → `'include'`. Built + deployed to `swa-aigovern-gov-dev` (bundle `index-BrUbZMvJ.js`).
**Status:** SHIPPED S59. **Note:** export will now reach the backend but currently 404s due to F-022 (empty `system_id` posted).
**Compound rule earned:** Any raw `fetch` in an SPA outside the shared client is a contract drift waiting to happen. Either route through the shared client (preferred) or copy ALL of its options (`credentials`, headers, data-mode header).

---

### F-020 · PLATFORM-BUG · CISO Console framework-coverage % double-multiplied (9520%, 8770%…) (P1)

**Found:** S59 STEP 1, 2026-05-27 — same matrix screenshot. AML Investigation Assistant showed `9130%` for EU AI Act, `8410%` for NIST AI RMF, etc. Color thresholds also broken: every non-zero cell rendered green (≥0.8 trip).
**Where:** [ciso-console/src/pages/frameworks/FrameworksPage.tsx:114-122](../../ciso-console/src/pages/frameworks/FrameworksPage.tsx#L114) — `coverageStyle` thresholds (0.8, 0.5) and `fmtPct` (`Math.round(n * 100)`) both assumed a 0-1 ratio. Domain at [domain/framework_coverage.py:410](../../domain/framework_coverage.py#L410) emits 0-100: `passing_total / applicable_total * 100.0`.
**What:** CISO Console multiplied a 0-100 value by 100 a second time. 95.2 → 9520%.
**Why it stayed hidden:** Sweep showed CISO Console was the **only** consumer using 0-1. Team Portal's [AiSystemFrameworksPanel.tsx:113](../../team-portal/src/pages/ai-systems/AiSystemFrameworksPanel.tsx#L113) explicitly documents "Engine returns coverage_pct on a 0-100 scale"; [domain/pdf_pack_base.py:343](../../domain/pdf_pack_base.py#L343) renders `{ic.coverage_pct:.0f}%` (0-100). The CISO Console code was written against a wrong assumption that nothing else in the codebase tested for. Initial fix recommendation was to flip the domain — reversed after grep sweep (23 consumer files, ~all expect 0-100; flipping domain would break Team Portal + PDF generators + tests).
**Fix:** CISO Console only. Thresholds 0.8 → 80, 0.5 → 50; dropped `* 100` from `fmtPct`. Added comment cross-referencing the domain contract. Shipped in same bundle as F-019.
**Status:** SHIPPED S59.
**Compound rule earned:** Before flipping a domain-level contract, grep ALL consumers — not just the one that's visibly wrong. The lone outlier is usually the bug, not the contract. (S59 #2.)

---

### F-022 · PLATFORM-BUG · Framework-matrix portfolio export sends empty system_id → 404 (P2, DEFERRED)

**Found:** S59 STEP 1, 2026-05-27 — analysis after fixing F-019.
**Where:** [FrameworksPage.tsx:81](../../ciso-console/src/pages/frameworks/FrameworksPage.tsx#L81) hardcodes `body: JSON.stringify({ system_id: '' })`. Backend [api/frameworks.py:432](../../api/frameworks.py#L432) requires a real system_id → returns 404 on empty.
**What:** The 7 "Export <framework>" buttons are designed as a **portfolio-wide** action (one button per framework column, no per-system selector on the page). But the only generator shapes are per-system: `generate_nist_pack(system_id)`, `generate_owasp_pack(system_id)`, `generate_eu_ai_act_pack(system_id)`. No portfolio-rollup generator exists. UI promised a feature the backend never had.
**Mitigation:** STEP 2 of S59 uses the **Reports** page (different surface) which calls per-system generators with real IDs — works today. Operators avoid the broken matrix-page buttons.
**Fix options:**
  1. **Portfolio rollup generators** (~45-60 min): add `generate_<fw>_portfolio_pack(system_ids: list[str])` for each live framework; backend dispatches when `system_id` is empty. Matches current button design. **Recommended.**
  2. **Frontend picker** (~30 min): add a system dropdown above the export row; column buttons use the selected system. Easier backend (no change) but adds UI noise.
  3. **Row-level export** (~20 min): drop column buttons; add per-cell export icons. Backend unchanged.
**Status:** DEFERRED to S60. Not on P3 critical path. Logged with full fix plan above.
**Compound rule earned:** UI promises that have never been implemented end-to-end are the same shape as F-018 and S57 #1. "Sweep operator verbs in docs vs UI reality" (S57 close note carry-forward) — still owed.

---

### F-023 · PLATFORM-GAP · No operator UI to add evidence to an existing AI system (P2)

**Found:** S59 STEP 3, 2026-05-27 — operator opened Team Portal → AI Systems → `ai-sys-bae72e75` → Edit, looking for the "Step 5 evidence URLs" field per S59 plan §STEP 3 and POC plan §P3 step 3. Field is not present in Edit mode.
**Where:**
  - [team-portal/src/pages/ai-systems/AiSystemEditModal.tsx:4-5](../../team-portal/src/pages/ai-systems/AiSystemEditModal.tsx#L4) — header comment explicitly scopes Edit to drawer def-list fields only: *"Full MATERIAL set (cloud_provider, tools, rag_sources…) requires extending /grc/ai-systems/{id} — out of scope for #9."* Evidence URLs are not in that set.
  - [team-portal/src/pages/ai-systems/RegisterSystemPage.tsx:81,426](../../team-portal/src/pages/ai-systems/RegisterSystemPage.tsx#L81) — Step 5 "Evidence Upload" exists in the registration wizard but not the edit flow.
  - [api/evidence.py](../../api/evidence.py) — no POST/PUT routes. Read-only.
  - [ciso-console/src/pages/evidence/EvidencePage.tsx](../../ciso-console/src/pages/evidence/EvidencePage.tsx) — read-only viewer. Only "Refresh" actions.
**What:** Post-registration there is no operator-visible surface for adding evidence URLs, files, or hashes to a registered system. Evidence is effectively append-only via Python `repository` calls — i.e. code, not operator workflow.
**Why it stayed hidden:** Same shape as F-018 (no policy upload UI; CISO Console's "Policies" page is a different concept) and F-022 (Framework matrix export buttons promise per-framework portfolio rollup PDFs that don't exist). All three are *plan documents a verb → no UI ships → operator hits a wall*. The Edit modal even self-documents the gap, but the plan never reconciled with that scope cut.
**Mitigation in S59:** STEP 3 skipped at UI level. Audit/evidence chain for `ai-sys-bae72e75` is still complete via the artifacts logged in this retro itself: F-018 .rego bundle sha256s, F-019/F-020/F-022 fix references, STEP 2's EU AI Act PDF Pack sha256 (`86c9382f…f466c6`). These provide the operator-visible audit trail STEP 3 was meant to produce, just not via the registered-system Edit screen.
**Fix options (S60+):**
  1. **Minimal** — extend Edit modal with read+add (no delete) evidence URL form, backed by new `POST /api/v1/grc/ai-systems/{id}/evidence` endpoint. ~60-90 min.
  2. **Right-sized** — full evidence CRUD in Edit + a CISO Console "Evidence Bundles" tab that supports add/link, not just view. ~3-4 hr.
  3. **Architectural** — treat evidence as immutable artifacts in an append-only store (already true at storage layer); UI surfaces an "Attach Evidence" affordance from anywhere a system is shown (drawer, AI systems list row, framework drill modal). Larger refactor.
**Recommendation:** option 1 next session if STEP 3-equivalent operator workflow becomes load-bearing for a demo; otherwise option 3 as long-term direction.
**Status:** OPEN — DEFERRED to S60+. Logged with full triage. Does NOT block P3 EXIT GATE per disposition below.
**Compound rule earned:** Three consecutive sessions producing the same finding shape ("UI promise that never shipped") makes this a class, not three incidents. The S57 close-note carry-forward — *"UI-promise audit: sweep operator verbs in docs vs UI reality"* — is now overdue. (S59 #3.)

---

### S59 STEP 3 · DISPOSITION

**Decision:** SKIPPED at UI level due to F-023. Per-system audit trail demonstrated via this retrospective's own logged artifacts (F-018 .rego sha256s + STEP 2 PDF sha256 `86c9382f…f466c6`).
**Plan deviation:** Plan §STEP 3 acceptance was "Step 5 saves; re-open shows persisted entries; system's evidence completeness % ticks up." This cannot execute without F-023's fix. P3 EXIT GATE proceeds with documented gap.

---

### S59 P3 EXIT GATE

**Status:** P3 CLOSED at surface-acceptance granularity with three documented carry-forward gaps (F-021, F-022, F-023).

**What P3 proved:**
- Framework Coverage matrix surface renders the full 7×8 grid, end-to-end auth works, percentages and color thresholds are real (F-019 + F-020 shipped this session).
- Per-system PDF generation works via the Reports surface for the live frameworks (STEP 2 produced [eu-ai-act-pack-ai-sys-002.pdf](poc-evidence/p3-eu-ai-act-pack/eu-ai-act-pack-ai-sys-002.pdf), sha256 `86c9382f…f466c6`).
- Audit trail concept is real: sha256-anchored evidence (PDF + .rego bundles from F-018) is verifiable + persistent.
- The `.rego` policy enforcement chain demonstrated in F-018 is still load-bearing — `azure-architect.rego` is active in the engine policy stack.

**What P3 explicitly did NOT prove (carry-forward):**
- **F-021** — framework coverage data populated for `ai-sys-bae72e75` (Azure Architect itself shows 0% across all frameworks; awaits P4 agent traces).
- **F-022** — portfolio rollup PDF (matrix-page Export buttons broken end-to-end; Reports surface is the working alternative for now).
- **F-023** — post-registration evidence-add UI (operator must rely on Python `repository` for evidence on existing systems).
- **UI-promise audit** — three F-018/F-022/F-023 same-shape findings in three sessions; a dedicated audit pass owes the carry-forward queue.

**Proceeding to P4:** Agent core (tool layer + orchestration loop, 5-turn cap, output to `data/plans.jsonl`, synthesis row to `eval/dataset.jsonl`). Per S59 plan §STEP 4.

---

### F-024 · PLATFORM-CRITICAL · `policies/*.rego` files were decorative — never enforced (RESOLVED in S60)

**Found:** S60 STEP 1, 2026-05-27 — wrapping `list_resource_groups` with `@signallayer.policy_gate(action="tool_invoke")` and calling it with a fake mutation-verb tool name (`delete_resource_group`) returned ALLOW instead of the `PolicyDeniedError` the rego file promises.
**Where:**
  - [domain/policy_engine.py](../../domain/policy_engine.py) — `_evaluate_local()` ran the five Python `_check_*` helpers then returned `policy_name="all_local_checks_pass"`. **Zero code paths loaded or evaluated any `.rego` file.**
  - [policies/azure-architect.rego](../../policies/azure-architect.rego) — workload-specific tool allowlist, mutation-verb deny, multi-subscription review, LLM-call budget — all defined but **never executed**.
  - [middleware/policy.py:166](../../middleware/policy.py#L166) — `_extract_arg()` read kwargs + positional args but ignored Python signature defaults. So `tool_name="..."` as a kwarg-only default was invisible to the engine.
**What:** Two compounding bugs masked each other. (1) The engine never consulted rego files. (2) Even if it had, `_extract_arg` couldn't see tool identities encoded as defaults — a pattern the SDK encourages. The F-018 contract ("rego sha256 visible in CISO Console = enforced rule") was a lie at the engine layer despite the UI showing a valid hash.
**Why it stayed hidden:** Same shape as [[bare-except-hides-broken-integrations]] — the engine returned `Decision.ALLOW` cleanly with a green-looking policy_name. No exception, no warning, no telemetry. Three full sessions (S57/S58/S59) shipped on top of this because no negative test ever ran a denied tool through the decorator chain.
**Fix (this session):**
  1. New [domain/rego_loader.py](../../domain/rego_loader.py) — regex parser for rego sets/lists/ints. Pure data extraction (no Rego logic execution); file remains source of truth, enforcement runs in Python alongside existing `_check_*` helpers. No new runtime dep, no OPA install.
  2. New `_check_workload_specific()` in `domain/policy_engine.py` — enforces allowlist + mutation-verb prefix deny derived from rego data.
  3. [middleware/policy.py:166](../../middleware/policy.py#L166) — `_extract_arg` falls back to the function's signature default when a kwarg is missing.
**Verification:** Six tests pass via direct `evaluate()` AND the full `@policy_gate` decorator chain:
  - `delete_resource_group` → DENY (`workload_mutation_verb_blocked`) ✓
  - `list_storage_accounts` → DENY (`workload_tool_not_allowlisted`) ✓
  - `list_resource_groups` → ALLOW, function body reached ✓
  - tool_invoke with no `tool_name` for an azure-architect workload → DENY ✓
  - non-azure-architect workloads → unchanged ALLOW (no regression) ✓
  - `fake_delete()` through the SDK decorator chain → raises `PolicyDeniedError` ✓
**Scope deferred:** Rule 5 (`max_llm_calls_per_run=25`) and Rule 6 (multi-subscription REVIEW) are NOT enforced yet — need OPA or run-state plumbing. Parser extracts the int + the conditional shape, but `_check_workload_specific` is a no-op for them. Documented in `domain/rego_loader.py`.
**Compound rule earned:** Any "the engine reads policy from a file" contract MUST have a negative test in CI that proves a known-bad input is denied. Memory: [[rego-files-were-decorative]].

---

### F-025 · PLATFORM-MEDIUM · `PolicyDeniedError` class mismatch SDK vs engine (RESOLVED in S60)

**Found:** S60 STEP 1, 2026-05-27 — `except signallayer.errors.PolicyDeniedError:` failed to catch a real deny because the engine raises `middleware.policy.PolicyDeniedError` — an *unrelated* class, not a subclass. MROs share only `Exception`.
**Where:**
  - [signallayer/errors.py](../../signallayer/errors.py) — `class PolicyDeniedError(SignalLayerError)`. Advertised in SDK `__all__`.
  - [middleware/policy.py](../../middleware/policy.py) — `class PolicyDeniedError(Exception)`. Raised by every `@policy_gate` decorator.
**Blast radius:** LOW now — error messages, policy_name, reason still surface. Only `except` discrimination is broken. Becomes MEDIUM once external SDK consumers exist.
**Fix (same session):** [middleware/policy.py:31](../../middleware/policy.py#L31) — engine `PolicyDeniedError` now subclasses `signallayer.errors.PolicyDeniedError` (lazy-imported with `Exception` fallback so middleware stays importable when the SDK isn't on the path). `isinstance(engine_err, SDKPolicyDeniedError)` is now True. Existing engine raise sites (`raise PolicyDeniedError(policy_name=..., reason=..., metadata=...)`) untouched — SDK base takes a single message string, synthesised from `policy_name + reason` in `__init__`.
**Verified:** SDK class catches engine deny ✓ · engine class still catches (no regression) ✓ · allowlisted ALLOW path unchanged ✓ · org-mandatory PII deny still wins for `llm_call` action (no F-024 layering regression) ✓.
**Status:** RESOLVED.

---

### S60 P4 STEP 1+2 · STATUS

**STEP 1 (tool layer) — DONE:**
- [agents/azure-architect/tools/arm_read.py](../../agents/azure-architect/tools/arm_read.py) — `list_resource_groups()` body implemented (real `ResourceManagementClient.resource_groups.list` wrapped in `asyncio.to_thread`, pydantic-strict return), wrapped with `@signallayer.policy_gate(action="tool_invoke")`.
- F-024 unblocks the STEP 1 acceptance criterion ("rego allowlist enforced").

**STEP 2 (orchestration loop) — STRUCTURALLY DONE, NOT LIVE-TESTED:**
- [agents/azure-architect/agent.py](../../agents/azure-architect/agent.py) — `_run_plan()` with 5-turn cap, governed dispatch, per-turn append to `data/plans.jsonl`, final synthesis row to `agents/azure-architect/eval/dataset.jsonl` in canonical `(input, output, context, metadata)` shape.
- CLI: `python agent.py --plan "<request>" --subscription <sub-id>` (Sonnet 4.6 default per S60 cost lock; `--deep` forces Opus).
- Tool errors (including `PolicyDeniedError`) rendered back to the model as `is_error: True` tool_result blocks — model can self-correct within remaining turns.
- **Not exercised end-to-end** — requires `pip install azure-mgmt-resource azure-identity`, `az login`, `ANTHROPIC_API_KEY`, real subscription ID. First live run is an S61 item.

**STEP 3 (per-tool tracing + policy verification) — PARTIAL:**
- Policy denial verified via direct `evaluate()` + decorator chain (F-024 tests).
- Live `trace_id` in `data/traces.jsonl` for tool dispatch deferred to first live `--plan` run.

**STEP 4 (Mermaid synthesis + per-tool eval) — DEFERRED to S61** per S60 plan.

---

### S61 P4 STEP 1+2 LIVE · STATUS

**First live `--plan` run — DONE (2026-05-27):**
- Installed `azure-mgmt-resource==25.0.0` + `azure-identity==1.25.3` (+ msal, msal-extensions, isodate transitives).
- Subscription scope: `06e4c6fa-8b0f-4e4a-b993-e0fd21eb22a3` (SignalLayerDev).
- Command: `PYTHONPATH=. python agents/azure-architect/agent.py --plan "audit my dev subscription: list resource groups and summarise what I have" --subscription 06e4c6fa-…`.
- Model: `claude-sonnet-4-6` (cost-locked default per S60). `--deep` for Opus.
- Run: `plan-7036dc14bb58` · turns=2 · stop=`end_turn` · 1 tool call (`list_resource_groups` ok=True).
- 6 resource groups returned. Sonnet produced a credible WAF synthesis across all 5 pillars from RG-level inventory alone (flagged `DefaultResourceGroup-EUS` anti-pattern + universal missing tags — both real findings).
- Artifacts persisted:
  - [data/plans.jsonl](../../data/plans.jsonl) — 2 per-turn telemetry rows (turn 0 = tool_use dispatch, turn 1 = end_turn synthesis), tracks `model`, `stop_reason`, `elapsed_ms`, in/out tokens, `tool_calls[]`, `text_chars`.
  - [agents/azure-architect/eval/dataset.jsonl](eval/dataset.jsonl) — row 6 in canonical `(input, output, context, metadata)` shape, picked up by S58's eval harness without further plumbing.

**Rego enforcement — VERIFIED LIVE (negative + positive):**
- New `/verify` block in [ARCHITECTURE.md](../../ARCHITECTURE.md) replays the real `(workload_id="azure-architect", action="tool_invoke", tool_name=…)` shape through `@signallayer.policy_gate`.
- DENY path: `tool_name="delete_resource_group"` → `PolicyDeniedError [workload_mutation_verb_blocked]` ✓.
- ALLOW path: `tool_name="list_resource_groups"` → returns normally ✓.
- Defense in depth confirmed: rego catches via BOTH explicit `readonly_azure_tools` allowlist AND prefix-based `workload_mutation_verb_blocked` rule.
- Corollary added to the [[rego-files-were-decorative]] rule: a negative test must replay the exact `(workload_id, action, tool_name)` triple the real caller produces. An unmapped-workload call hits a different code path (fallback ALLOW for unmapped workloads) and proves nothing about rego enforcement. The S61 verify block does this correctly; first attempt did not (false-FAIL caught and corrected mid-session).

**Remaining for S62+:**
- STEP 4 spillover: Mermaid synthesis + per-tool eval rubric (still deferred per S60 plan).
- Add a 2nd read tool (e.g. `list_resources_in_group`) — exercises multi-turn tool chaining. Add to `readonly_azure_tools` in [policies/azure-architect.rego](../../policies/azure-architect.rego) BEFORE wiring the function ([[rego-files-were-decorative]]).
- Triple-overdue UI-promise audit ([[ui-promise-audit-owed]]).
- F-021 (framework mapping data for `ai-sys-bae72e75`) — partially self-resolves once P4 runs accumulate traces.

---

### S62 P4 STEP 1 EXPANSION · STATUS

**2nd read tool wired + multi-turn validated — DONE (2026-05-29):**
- Rego allowlist edited FIRST (per [[rego-files-were-decorative]]): added `list_resources_in_group` to `readonly_azure_tools` in [policies/azure-architect.rego](../../policies/azure-architect.rego). Re-ran the rego positive+negative test; new tool ALLOWs, mutation-verb guard still DENYs.
- Schema: `ResourceSummary` + `ResourcesInGroupOut` added to [tools/schemas.py](tools/schemas.py). Thin shape — no polymorphic `properties` blob (list endpoints omit it in ARM anyway; use `get_resource_metadata` for drill-down).
- Implementation: [tools/arm_read.py](tools/arm_read.py)::`list_resources_in_group` wraps `ResourceManagementClient.resources.list_by_resource_group` via `asyncio.to_thread`. `@signallayer.policy_gate(action="tool_invoke")` governed. Same client + credential as `list_resource_groups` — no extra SDK install.
- Anthropic tool spec added to [prompts.py](prompts.py)::`PLAN_TOOL_SPECS`. Dispatch wired in [agent.py](agent.py)::`_build_tool_dispatch` — missing-`resource_group` ValueError surfaces as `is_error` tool_result so the model self-corrects.
- **Live multi-turn run:** `plan-799bcfdd3311`, Sonnet 4.6, 2 turns, stop=end_turn. Turn 0 fanned out BOTH tool calls in parallel (model derived `rg-aigovern-dev` from the prompt). Turn 1 produced 12,244 chars of WAF synthesis — 3,707 output tokens, well past the prior 2,048 ceiling. Parallel tool dispatch works without code changes; `_run_plan` already iterates over `tool_uses` and appends an aggregated `user` message with all `tool_result` blocks.

**Bug fixed during S62: streaming required at `max_tokens > 2000`** ([[anthropic-max-tokens-streaming-threshold]]):
- Bumped `TOKEN_BUDGETS["plan_turn"]` 2048 → 4096 to give the final-turn synthesis the same room as the standalone `architecture_review` path. The non-streaming `anthropic.messages.create()` then disconnected on every retry with `APIConnectionError: Connection error` (httpx `RemoteProtocolError: Server disconnected without sending a response`). CLAUDE.md global rule: "Use streaming for any call with `max_tokens > 2000`."
- Fix: switched the loop to the streaming context manager, `with anthropic.messages.stream(...) as s: msg = s.get_final_message()`. Same `msg` shape downstream; `.content`, `.stop_reason`, `.usage` unchanged. The 5-turn cap × 4096 = 20K max output, still bounded.
- New memory entry [[anthropic-max-tokens-streaming-threshold]] captures the non-obvious failure mode (network-shaped error, real cause is token budget).

**Synthesis quality from the live run** (Sonnet 4.6, dev subscription):
- Surfaced a real **CRITICAL** finding: `log-aigovern-prod` + `appi-aigovern-prod` live inside `rg-aigovern-dev`. RBAC blast radius wraps dev contributors over prod telemetry. Genuine issue, not hallucinated.
- Correctly flagged P2v3 over-provision for dev, no zone-redundant Postgres HA, no Private Endpoints, cross-region latency (compute in westus2 vs search/secrets in eastus).
- Token cost: ~6.4K input + 3.9K output ≈ $0.07 per run with Sonnet. P4 economics confirmed healthy for routine subscription audits.

**Remaining for S63+:**
- STEP 4 spillover (Mermaid + per-tool eval rubric). Still deferred.
- Implement `get_resource_metadata` (rego-allowed already, body still `NotImplementedError`). This is the natural "drill into one resource" tool to round out the read surface.
- Triple-overdue UI-promise audit ([[ui-promise-audit-owed]]).
- F-021 — framework mapping data for `ai-sys-bae72e75`.

---

### S63 P4 STEP 1 — drill-down trio complete · STATUS

**`get_resource_metadata` wired + live trio validated — DONE (2026-05-29):**
- Rego allowlist gate: `get_resource_metadata` already in `readonly_azure_tools` (reserved in S60 scaffolding). Per [[rego-files-were-decorative]] discipline, ran the rego positive+negative replay anyway with the new tool as the positive case — DENY held for `delete_resource_group`, ALLOW held for `get_resource_metadata`.
- Schema reused: `ResourceMetadata` was already defined in [tools/schemas.py](tools/schemas.py) from S60 (polymorphic `properties: dict[str, object]`, schema_version 1.0).
- Implementation: [tools/arm_read.py](tools/arm_read.py)::`get_resource_metadata` + `_parse_resource_id` helper. Three-step: parse ARM id → discover newest stable api_version via `providers.get(namespace)` (filter preview tags) → `resources.get_by_id`. Wrapped in `asyncio.to_thread`, governed by `@signallayer.policy_gate(action="tool_invoke")`. Malformed `resource_id` raises `ValueError` which the orchestration loop renders as `is_error` tool_result so the model self-corrects.
- Anthropic tool spec added to [prompts.py](prompts.py)::`PLAN_TOOL_SPECS` (now 3 tools). Dispatch wired in [agent.py](agent.py)::`_build_tool_dispatch` with missing-`resource_id` ValueError mirror of `_list_resources`.
- **Live trio run:** `plan-867aa0931a0a`, Sonnet 4.6, 3 turns. Turn 0: 1× `list_resources_in_group` (skipped `list_resource_groups` — operator named RG, correct planning). Turn 1: **3× parallel `get_resource_metadata`** drilling into Key Vault, App Service, PostgreSQL. Turn 2: full WAF synthesis with REAL CRITICAL findings — KV purge protection disabled, PostgreSQL public network access + Entra ID auth disabled, App Service `minTlsVersion: null`, prod-named Log Analytics + App Insights co-located inside `rg-aigovern-dev`.

**Bug found + fixed during S63: `plan_turn` is now bottleneck on synthesis turn** (extends [[anthropic-max-tokens-streaming-threshold]]):
- The live trio synthesis truncated at `stop=max_tokens` at 4096 output tokens, mid-verdict-table. Drill-down depth scales synthesis size — each `get_resource_metadata` result feeds per-resource prose into the final turn.
- Fix: bumped `TOKEN_BUDGETS["plan_turn"]` 4096 → 8192. 5-turn cap × 8192 = 40K bounded; intermediate tool turns rarely exceed 500 output tokens so the headroom serves the synthesis turn specifically. Streaming was already in place from S62 so no transport change needed.
- Pattern lesson: every tool added to the drill-down chain raises the synthesis token floor. Future allowlist additions should re-check the `plan_turn` ceiling against worst-case fan-out (turn-cap × max-parallel-calls × per-result prose).

**Verify block updated:** [ARCHITECTURE.md](../../ARCHITECTURE.md) rego positive test pinned from `list_resource_groups` to `get_resource_metadata` so the test proves the *current* allowlist surface, not just the original entry. Future tool additions should rotate the positive test to the newest entry by convention.

**Remaining for S64+:**
- STEP 4 spillover (Mermaid + per-tool eval rubric). Still deferred.
- 4 read-surface stubs remain: `list_subscriptions`, `list_role_assignments`, `get_network_topology` + the two property-bag tools (`get_storage_account_properties`, `get_key_vault_properties`). Storage/KV property-bag tools are partly redundant now that `get_resource_metadata` returns full polymorphic properties; reassess scope before implementing.
- **Quadruple-overdue UI-promise audit** ([[ui-promise-audit-owed]]).
- F-021 — framework mapping data for `ai-sys-bae72e75`.

---

_(Append further findings below as P3-P10 progress.)_
