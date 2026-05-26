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

_(Append further findings below as P1-P10 progress.)_
