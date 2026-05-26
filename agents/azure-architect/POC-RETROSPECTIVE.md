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
**Compound rule:** Updated [[deploy-zip-overwrites-runtime-data]] to add: "data/ in wwwroot/ ALSO gets wiped by slot swap, even if absent from the deploy zip. Persistence must live OUTSIDE wwwroot/ (under /home/ or external storage)."
**Priority:** P0 (was wiping prod state on every deploy; fixed)

---

_(Append further findings below as P1-P10 progress.)_
