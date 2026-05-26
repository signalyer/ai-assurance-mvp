# Azure Architecture — AI Assurance Platform

**Files:** [`azure-architecture.svg`](./azure-architecture.svg) (editable vector, 1920×1280) · [`azure-architecture.png`](./azure-architecture.png) (raster) · `assets/` (Azure V23 icons subset)

**Last regenerated:** Session 53 · 2026-05-26
**Source of truth:** [`../../deploy/bicep/parameters.dev.json`](../../deploy/bicep/parameters.dev.json), [`../../ARCHITECTURE.md`](../../ARCHITECTURE.md)

---

## 1 · What the diagram shows

| Tier | Service | Resource name | Region | SKU / notes |
|---|---|---|---|---|
| Identity | Microsoft Entra ID | `github-deploy-aigovern` app reg | tenant | OIDC federated, no secrets |
| Edge | Azure DNS | `sandboxhub.co` zone | global | CNAMEs to SWA + App Service custom domain |
| SPA — Team Portal | Static Web Apps | `swa-aigovern-portal-dev` | eastus2 | Free SKU |
| SPA — CISO Console | Static Web Apps | `swa-aigovern-gov-dev` | eastus2 | Free SKU |
| Engine | App Service Plan | `asp-aigovern-dev` | eastus | B1 Linux |
| Engine | App Service | `app-aigovern-dev` | eastus | Python 3.12, FastAPI |
| Storage (primary) | App Service local disk | `data/*.jsonl` | — | events, ai_systems, findings, sdk_keys |
| Tier-2 episodic memory (optional) | PostgreSQL Flexible Server | (deferred in dev) | eastus | tsvector FTS |
| Tier-3 RAG (optional) | Azure AI Search | (deferred in dev) | eastus | Hybrid BM25 + text-embedding-3-small |
| Observability | Log Analytics workspace | `log-aigovern-prod` | eastus | PerGB2018, 30-day |
| Observability | Application Insights | `appi-aigovern-dev` | eastus | Workspace-based, OTel |
| Alerting | 8 scheduled-query alerts | per `alerts.bicep` | eastus | action group `ag-aigovern-dev` |

**Resource group:** `rg-aigovern-dev` (eastus) — note: the conversation handoff referenced `rg-aigovern-prod`; the IaC parameters file is the source of truth and uses `-dev`. The diagram reflects the IaC.

## 2 · Traffic flows

1. **SPA operators → SWA → App Service.** Cookie session (HttpOnly + Secure + 10-min sliding). TLS terminates at the reverse proxy; the engine reads `X-Forwarded-Proto` (S49 #1) before issuing secure cookies or computing redirect URIs.
2. **SDK clients → `/api/sdk/*` (HMAC-gated).** External customer apps using the `signallayer` Python SDK sign each request with HMAC-SHA-256 over the canonical input `unix_ts \n METHOD \n path \n sha256(body)`. The middleware enforces ±300s drift, a 600s nonce TTL, and a 50k nonce cap. Per-system keys land in `data/sdk_keys.jsonl` (S53); the legacy single-tenant `SL_HMAC_SECRET` env var is still honoured as a fallback for demo apps.
3. **Engine → external egress.** Every external call (Anthropic, AWS Bedrock, Langfuse, Azure AI Search) is fed by a scrubbed payload. The hard invariant `scrub_pii MUST run before trace_call` is enforced by both the decorator chain (`signallayer.guard` raises `DecoratorOrderError` at import time) and the tracer (which refuses to send when `vault_id` is missing under `SCRUBBER_ENABLED`).
4. **App Service → observability.** Structured JSON logs + Prometheus counters → App Insights (workspace-based) → Log Analytics (`log-aigovern-prod`). 8 KQL scheduled-query alerts forward to the `ag-aigovern-dev` action group: `pii-leak`, `opa-unreachable`, `vault-error`, `audit-chain-broken`, `http-5xx-rate`, `p95-latency`, `rtf-partial-failure`, `scrub-rate-regression`.
5. **GitHub Actions → App Service.** Push to `main` → OIDC federated credential exchange against the `github-deploy-aigovern` app registration (subject `repo:signalyer/ai-assurance-mvp:ref:refs/heads/main`) → `azure/webapps-deploy@v3` against `app-aigovern-dev`. The workflow then GETs `/api/health` and verifies the returned `sha` matches the workflow's `GITHUB_SHA` (S19d) before exiting green.

## 3 · Identity model

| Principal | Credential | Resource | Role |
|---|---|---|---|
| GitHub Actions workflow | OIDC federated (no secret at rest) | `app-aigovern-dev` | Website Contributor |
| SPA operator (browser) | Session cookie (engine-issued) | `/api/*` except `/api/sdk/*` | 5-role auth: ciso · risk · engineer · reviewer · readonly |
| SDK client (customer app) | Per-system HMAC secret (S53) or legacy `SL_HMAC_SECRET` | `/api/sdk/*` | HMAC-only gate; no session role |
| Developer (CLI) | `~/.signallayer/credentials.json` (POSIX 0600 / Windows ACL) | `/api/sdk/*` and operator API via cookie login | Whatever the cookie role grants |

## 4 · Security & compliance highlights

- **Scrubber-before-tracer invariant.** Hard-wired in the decorator chain; Langfuse never receives raw prompts. The `tracer.py` module refuses to emit when `vault_id` is missing under `SCRUBBER_ENABLED`.
- **OPA policy engine** — fail-closed (any error → DENY, never ALLOW). In-process Python fallback for dev; HTTP client for prod OPA.
- **Presidio NER + Fernet-encrypted de-id vault** — entities scrubbed at the edge, raw values vaulted with a TTL, accessible only via `vault_id` for downstream re-id.
- **Tamper-evident audit hash chain** — SHA-256 over canonical JSON, GENESIS root, `portalocker` advisory lock for cross-process append safety. Verifiable via `GET /api/audit/verify`.
- **Right-to-Forget cascade (S08)** — `vault → T2 (Postgres) → T3 (Azure AI Search) → Langfuse` orchestrated sync. Any step error degrades the cascade to `PARTIAL_FAILURE` and writes per-store SHA-256 digests to the audit chain. Idempotent on `cascade_id`.
- **Per-system SDK keys (S53)** — each registered AI system gets its own `(key_id, hmac_secret)` pair. Plaintext secret stored server-side because HMAC verification requires it; same trust boundary as the legacy single-tenant env-var secret. Surfaced to the SPA exactly once at issuance; re-display ≡ revoke + reissue.

**Demo-build security posture (current default):** no Key Vault, no managed identity, no VNet integration, no private endpoints, CORS `*`. HTTPS enforced via App Service. These are intentional v1 simplifications, not gaps — they are explicitly called out in `~/.claude/CLAUDE.md`. Production posture (deferred) flips all five of those on.

## 5 · Well-Architected pillar alignment

| Pillar | Status (v1 demo build) | Notes |
|---|---|---|
| **Security** | Partial | Decorator chain + scrubber + audit chain are strong; KV + MI + private endpoints deferred to prod build. |
| **Reliability** | Partial | App Service B1 (no zone redundancy); JSONL on local disk has no cross-instance replication. Acceptable for single-tenant v1. |
| **Performance** | Strong for v1 | Latency budget met (p95 alert wired); scrubber p95 ≈ 6 ms; OPA p95 < 50 ms. |
| **Cost** | Strong | Free SWA SKU × 2, B1 App Service, optional PG/Search off by default. |
| **Operational excellence** | Strong | CI auto-deploy with SHA round-trip, 8 alerts, structured logs, request_id propagation via ContextVar. |

## 6 · Known asymmetries & annotations

- **Resource group name divergence.** The Session 53 handoff prompt referenced `rg-aigovern-prod`; the IaC parameter file uses `rg-aigovern-dev`. **Diagram reflects IaC reality.** No `-prod` RG exists in `SignalLayerDev` today.
- **Static Web Apps must live in `eastus2`.** Azure SWA is not available in `eastus`. This is the only cross-region asymmetry in the topology.
- **Application Insights deployment is deferred** during sessions that touched the engine — see S12 deploy notes. The Bicep module exists and parameters are set; an instrumentation attempt crashed prod in S12 and was reverted (`418440c`). To be re-attempted in a session with a Docker staging slot.
- **PG + AI Search are optional.** Defaults are `MEMORY_BACKEND=noop` / `RAG_BACKEND=noop`. The diagram shows them as Tier-2 / Tier-3 dependencies; in `app-aigovern-dev` they are unprovisioned today.
- **Custom domain.** `aigovern.sandboxhub.co` is bound to the App Service via Azure DNS CNAME + managed certificate. SWA custom domain wiring is per-SPA (handled in `staticwebapps*.bicep`).

## 7 · Re-rendering instructions

Edit the SVG by hand (it's vector + plain XML — friendly to git diffs). Then re-render the PNG:

```powershell
& "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" `
  --headless --disable-gpu --hide-scrollbars `
  --screenshot="C:\ai-assurance-mvp\docs\architecture\azure-architecture.png" `
  --window-size=1920,1280 `
  "file:///C:/ai-assurance-mvp/docs/architecture/azure-architecture.svg"
```

For an exec-deck 2× render, use `--window-size=3840,2560`.

## 8 · Maintenance rules

Re-render when any of the following changes:

- [`deploy/bicep/parameters.dev.json`](../../deploy/bicep/parameters.dev.json) — names, regions, SKUs
- [`deploy/bicep/main.bicep`](../../deploy/bicep/main.bicep) or the module Bicep files — topology shifts
- [`ARCHITECTURE.md`](../../ARCHITECTURE.md) decorator chain or scrubber/tracer ordering
- [`middleware/hmac_auth.py`](../../middleware/hmac_auth.py) — auth model
- New routers mounted in [`dashboard.py`](../../dashboard.py) — refresh the routers list inside the engine box
- Trust-boundary changes (new external egress target, new ingress path)

---

*Icons © Microsoft (Azure Architecture Icons V23) — used per published terms. Not modified.*
