# Demo Q&A — AI Assurance Platform

**Audience:** internal stakeholders, sponsor exec, prospective auditors and engineers.
**Use:** read before any live demo. Answers are anchored to real files / endpoints / counters so they survive cross-examination.

Last updated: 2026-05-22 (Session 11 of the 12-day production sprint).

---

## A. Auditor / risk officer

### A1. How do you prove Langfuse never received raw PII?
Every traced agent goes through the `@scrub_pii` decorator before `@trace_llm_call` fires (enforced order — see `ARCHITECTURE.md` §Decorator chain). Langfuse only ever sees the scrubbed payload (token placeholders like `[SSN_001]`). The raw mapping lives in a Fernet-encrypted local vault (`data/deid_vault.jsonl`) — ciphertext only on disk, never logged. A 50-case test suite (`tests/test_session10_observability.py` + scrubber regression set) plus the `pii_no_raw_to_langfuse.rego` OPA policy gate this at runtime; an App Insights alert fires on any synthetic leak.

### A2. What is the right-to-forget SLA and how do you verify it?
The cascade purges across four stores (vault → Tier 2 episodic → Tier 3 RAG → Langfuse) in a single API call (`/api/right-to-forget`, see `domain/right_to_forget.py::cascade`). Demo target: under 60s. The returned `CascadeResult` carries a `PurgeResult` per store with `items_removed` and a SHA-256 digest of post-state. Session 11 added HMAC-SHA256 signing on the `data/rtf_completed_index.jsonl` sidecar (`_compute_sidecar_sig`, `_verify_sidecar_entry`) so the idempotency index is integrity-protected.

### A3. How is the audit log tamper-evident?
Every event in `events.jsonl` carries a `prev_event_hash`, forming a SHA-256 chain. `GET /api/audit/verify` (`api/audit_verify.py`) walks the chain and returns the last good index plus first break. Sessions 08-10 added a portalocker advisory lock around the writer and a checkpoint file (now written inside the lock — Session 11 fix in `domain/audit_chain.py`). Any post-hoc mutation of an event breaks the chain at that index.

### A4. What is the framework coverage scope today?
Six frameworks ship in v1, with inline mappings on every control, scorer, gate, and policy: NIST AI RMF 1.0 (top 20 subcategories), OWASP LLM Top 10 2025 (all 10), EU AI Act Annex IV (10 documentation items), ISO/IEC 42001 (top 15 controls), SR 11-7 (Sections IV, V, VII), FFIEC IT Handbook (AI-relevant subset). All six have evidence-pack generators (`pdf_report.py::generate_*_pack`). The US-FinServ overlay composes NIST + SR 11-7 + FFIEC + GLBA + NYDFS — overlay added in Session 06.

### A5. How is evidence-bundle integrity established?
Each generated PDF pack is deterministic at minute granularity and carries a SHA-256 footer over its own content (`_compute_evidence_hash` in `domain/pdf_pack_base.py`). The `test_existing_packs_call_stable_within_minute` test (`tests/test_pdf_pack_base.py`) gates regressions. The pack also embeds framework citations on every evidence row, so an auditor can trace any control back to its source statement.

### A6. What is your OPA policy review cadence and change-management?
OPA runs as a sidecar on the App Service with bundle hot-reload from `policies/main/` (typical reload < 5s). Every change goes through `opa fmt --check` + `opa test ./policies` + Rego unit tests in CI (`docs/plans/12-DAY-PRODUCTION-SPRINT.md` §2.5). Categories with explicit precedence: org-mandatory → posture-driven → risk-tier-driven → team → system-override (waiver required). Decisions are logged to the audit chain.

---

## B. Engineer / builder

### B7. How do I install the SDK and run my first traced agent?
```bash
pip install -e ./sdk    # local; PyPI feed is Phase 2
sl login --base-url https://aigovern.sandboxhub.co --key-id <id>
sl onboard my-agent
```
Then in code: `from signallayer import init, scrub_pii, trace_llm_call, evaluate_response, policy_gate`. Decorators must be applied in the order `@policy_gate → @scrub_pii → @guardrails → @trace_llm_call → @evaluate_response` (top-down). The SDK raises `MissingScrubberError` at decoration time if `@scrub_pii` is absent.

### B8. How is the decorator chain order enforced?
The SDK inspects the stack at decoration time (not at call time) and raises before the function ever runs. The check is in `sdk/signallayer/order_guard.py` and is exercised by `tests/test_sdk_order_guard.py`. There is no runtime escape.

### B9. What is the local-dev story?
Run with `AUTH_ENABLED=false` and `MEMORY_ENABLED=false`. Cosmos / AI Search / Langfuse all degrade gracefully (Tier 2 falls back to JSONL, Tier 3 returns empty retrieval, tracer drops to local sink). `pytest --basetemp=./_pytest_tmp` is the recommended pattern (Windows %TEMP% ACL quirk documented in `pytest.ini`). The full test suite (245 tests including Session 11 additions) runs offline.

### B10. What is the performance overhead of the decorator stack?
Scrubber p95 < 100ms is the gate. Session 10 perf-smoke recorded ~6.3ms p50 against a representative payload on B1 SKU (see `tests/test_session10_perf_smoke.py`). The full chain (scrub + trace + eval) adds < 200ms on a warm worker. Load test budget: 25 RPS sustained for 10 min, p95 < 2s, zero errors on B1.

### B11. How does multi-agent versioning and pin-vs-upgrade work?
`System` has 1..N `Agents`; `AgentBinding` pins a specific agent version to a system (`domain/agents.py`). Publishing v2 of a reusable agent emits a `agent_published` event; subscribers receive a notification within polling interval (no webhooks in v1). Each subscribing system either pins v1 (explicit decision) or accepts v2 with consent. The weakest-link rule means a system inherits the highest risk tier among its bound agents.

### B12. How do I author a custom Rego policy and get it deployed?
Drop a `.rego` file under `policies/teams/<your-team>/` (team category — see `12-DAY-PRODUCTION-SPRINT.md` §1.4). Run `opa fmt --check` + `opa test ./policies` locally. Push to a feature branch; CI runs the same gates + a coverage check. After merge, the bundle reloads on the live sidecar within 5s. There's no DSL — Rego is enough.

---

## C. Executive / sponsor

### C13. What is the monthly cost story at demo load?
Roughly $884–$1,184/mo (sprint plan §3): App Service P1V3 (~$340), Postgres Flexible B2ms (~$130), AI Search Basic (~$75), App Insights + Log Analytics (~$30), Langfuse Pro (~$99), LLM API pay-as-you-go ($200–500 depending on demo volume). Storage and Key Vault are rounding errors at ~$10. No HA / multi-region in v1.

### C14. What is time-to-value for a new team onboarding?
~30 minutes from `sl onboard` to a first traced + evaluated request: SDK install, decorator wrapping the agent entry point, scrubber wired, eval pack assigned. Day-1 governance posture comes from inherited org-mandatory + posture-driven policies — no per-team policy authoring needed to be useful.

### C15. What is our vendor risk exposure?
Three external dependencies: Langfuse Cloud (L5 traces — graceful degradation if down, traces drop to local sink), Microsoft Presidio (L3 PII detection — self-hosted, vendored model `en_core_web_sm`), OPA (L2 policy — self-hosted sidecar, no external network). Anthropic + OpenAI for LLM calls — those are core to the demo content, not the assurance plane. We have no other third-party assurance vendors in the data path.

### C16. What is the Phase 2 roadmap headline?
Three things: (a) split the single app into Team Portal + Gov Console with shared SSO; (b) add real-time webhooks + an external blockchain anchor for the audit chain; (c) Bedrock provider + multi-language SDKs (Node, Go). Full list in `12-DAY-PRODUCTION-SPRINT.md` §8.

---

## D. Skeptic

### D17. What's NOT real?
Honest list (`12-DAY-PRODUCTION-SPRINT.md` §8): no real-time webhooks (polling), no per-tenant AI Search index, no mobile / responsive UI, no streaming evals (batch only), no synthetic golden-dataset generation, no Bedrock, no HIPAA/GDPR/FedRAMP/DORA framework packs yet, no OPA HA cluster (single sidecar), no agent marketplace beyond the org, the SDK is Python-only. The Team Portal / Governance Console split is v2 (today is single-app with role-based views). External blockchain anchor for the audit chain is also v2 — internal hash chain is enough for now.

### D18. What happens if Langfuse goes down?
Trace writes drop to a local JSONL sink (`tracer.py` graceful-degrade path); the request itself never fails. App Insights fires `langfuse_unavailable` alert. Catch-up replay is a manual op; not automated in v1.

### D19. What happens if OPA crashes?
Policy decisions fail closed → DENY. Every gate (`@policy_gate`, release gates, tool-authz, agent-binding, RTF cascade) defaults to denial when the OPA HTTP client times out or returns an error. App Insights `opa_unreachable` alert fires immediately. There is no fail-open code path. This is the most important invariant — verified by `tests/test_session10_hardening.py::test_opa_unreachable_fails_closed`.

### D20. How do you know your scrubber catches everything?
We don't claim 100% — that's not honest. We claim: the scrubber catches the 12 patterns we explicitly enumerate (SSN, CC, IBAN, ARN, API_KEY, IP, phone, DOB, MRN, NPI, ABA, custom hook) plus Presidio's NER coverage; we test 50 representative cases on every commit; we use the `pii_leak` DeepEval scorer as a runtime tripwire that fires post-hoc on any trace; and we publish the leak rate as a Prometheus counter (`pii_leak_total`). Residual risk is real and disclosed; the controls layer (RTF cascade) is the safety net when something slips.

---

**Verification:** the file paths, counters, endpoints, and test names cited above were grep-confirmed in the repository at the timestamp at the top of this document. If anything reads stale, run `grep -r "<term>" .` before the demo.
