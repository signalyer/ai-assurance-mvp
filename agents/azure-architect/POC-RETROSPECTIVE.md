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

_(Append further findings below as P3-P10 progress.)_
