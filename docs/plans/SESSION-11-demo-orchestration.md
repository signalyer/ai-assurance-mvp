# SESSION 11 — Demo Orchestration + ISO/SR-11-7/FFIEC PDF Packs + 20-Q&A Prep

**Date:** 2026-05-22 (Day 11 of 12)
**Status:** DRAFT — awaiting user approval before agents are spawned
**Prereqs:** Sessions 01-10 complete · 224 tests pass · 4 commits ahead of origin/main

---

## 1. Objectives (the "what ships")

1. **Demo Control panel** — one-click triggers for all 6 demo scenarios with synchronized talk-track display.
2. **3 new PDF Pack engines** — ISO/IEC 42001 · SR 11-7 · FFIEC IT Handbook (matching the existing NIST / OWASP / EU AI Act pattern, stdlib-only).
3. **6 scripted demo scenarios** — talk tracks + acceptance script for each (≤2 min each, 12 min total demo block).
4. **20-Q&A prep document** — likely auditor / stakeholder / engineer questions with crisp answers backed by evidence pointers.
5. **5 Day-11 security/code-debt fixes** (carried from Session 10 review):
   - HIGH: RTF sidecar HMAC integrity (`data/rtf_completed_index.jsonl`)
   - MED: `cli/sl/config.py` symlink-attack (`O_EXCL` on first write)
   - MED: `X-Request-Id` regex validation
   - MED: `audit_chain.py` checkpoint-inside-lock + dead `LockException` branch
   - MED: `api/metrics.py` `METRICS_TOKEN` module-cache

---

## 2. Six-item pre-execution review

### 2.1 Decorator chain & PII boundary — unchanged
`@policy_gate → @scrub_pii → @guardrails → @trace_llm_call → @evaluate_response`
Demo Control panel triggers must run through the live decorator chain. **No mock paths.** Scenarios 1, 2, 5 hit real Presidio + Fernet + Langfuse. Scenario 4 hits the real RTF cascade.

### 2.2 Storage — JSONL via `storage._append_jsonl()` / `_read_jsonl()`
Demo-control commands emit `demo_scenario_run` events to the SSOT events log (so the audit hash chain captures the demo itself — a meta-feature worth narrating). PDF Pack generators read events.jsonl, framework YAMLs, and coverage matrix — write nothing back.

### 2.3 Security rules
- New `/api/demo/*` endpoints behind `require_role("demo-operator")` (NOT public). Adding `demo-operator` to the role enum.
- PDF generation reads framework YAMLs only; no user-supplied template paths (path-traversal safe).
- RTF sidecar HMAC fix lands BEFORE the demo scenario that exercises right-to-forget (Scenario 4) — otherwise demo could be used to demonstrate the vulnerability.
- Demo narration storage MUST NOT exfiltrate real PII or customer names — narration is generic.

### 2.4 File placement
- New API router: `api/demo.py` (mount in `dashboard.py`)
- New UI: `static/demo-control.html` OR evolve `static/demo.html` (Decision Q1)
- New PDF engines: `domain/pdf_pack_iso42001.py`, `domain/pdf_pack_sr_11_7.py`, `domain/pdf_pack_ffiec.py` (OR shared `domain/pdf_pack_base.py` — Decision Q2)
- Demo narration: inline data-attributes OR `docs/demo-scripts/{scenario-N}.md` (Decision Q3)
- Q&A: `docs/DEMO-QA.md` OR append-section in `docs/RUNBOOK.md` (Decision Q4)
- Framework YAMLs already present at `frameworks/iso-42001.yaml`, `frameworks/sr-11-7.yaml`, `frameworks/ffiec.yaml` (verify in implementer phase)

### 2.5 Test surface
- Each new PDF engine: 1 unit test (renders without exception · contains expected framework citation strings · SHA-256 of bundle stable across runs given fixed input)
- `api/demo.py`: 3 tests (RBAC denial · scenario list · scenario trigger emits event)
- RTF HMAC sidecar: 4 tests (valid sig accepted · invalid sig rejected · missing sig rejected · disagreement with events.jsonl emits warning)
- `X-Request-Id` validator: 2 tests (valid passes · invalid → server-generated UUID)
- Target: +14 tests → 238 total.

### 2.6 Observability + acceptance gate
- Demo Control panel emits Prometheus counters: `demo_scenario_runs_total{scenario="..."}`, `demo_scenario_failures_total`.
- `/verify` must pass after all changes.
- Manual acceptance: run all 6 scenarios end-to-end from the Control panel → all green → bundle exports succeed → events.jsonl audit chain still verifies.

---

## 3. Decisions to lock (asked via AskUserQuestion)
1. Demo Control panel scaffold — new `static/demo-control.html` vs evolve `static/demo.html`
2. PDF Pack engines — copy NIST/OWASP/EU AI Act pattern (3 standalone) vs factor `pdf_pack_base.py` first
3. Demo narration storage — inline HTML data-attributes vs separate `docs/demo-scripts/` markdown
4. 20-Q&A document — standalone `docs/DEMO-QA.md` vs section in `docs/RUNBOOK.md`

---

## 4. Execution plan (after approval)

Parallel workstream (per `feedback_subagents_context_default.md`):

| Agent | Scope |
|---|---|
| Implementer A | RTF sidecar HMAC + `X-Request-Id` validator + audit_chain checkpoint fix + metrics token cache (Day 11 debt batch) |
| Implementer B | 3 PDF Pack engines (ISO 42001 · SR 11-7 · FFIEC) + unit tests |
| Implementer C | `api/demo.py` router + `static/demo-control.html` + 6 scenario triggers + tests |
| Implementer D | `docs/demo-scripts/` (or inline) + `docs/DEMO-QA.md` (or RUNBOOK section) + RUNBOOK updates |

After all 4 land:
- code-reviewer + security-reviewer in parallel
- Address findings
- `/verify`
- ARCHITECTURE.md + DECISIONS.md + HANDOFF.md updates
- Single commit: `Feat: Session 11 — Demo Control + ISO/SR-11-7/FFIEC Packs + 20-Q&A (Day 11)`

---

## 5. Out of scope (deferred to Day 12)
- Stakeholder dry-run
- Final deploy to `aigovern.sandboxhub.co`
- Any bug fixes surfaced by the dry-run
- Demo deck (slides)
- Phase-2 backlog items carried in HANDOFF.md "Open items (debt)"

---

## 6. Risk register (Session 11 specific)

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| PDF Pack pattern divergence across 3 new engines if not factored | MED | LOW | Decision Q2 — user picks shared base vs copy |
| Demo Control panel exposes raw event details with PII | LOW | HIGH | All scenarios run through scrubber; control panel renders only event IDs + scrubbed previews |
| RTF HMAC migration breaks existing sidecar entries | MED | MED | First-read: accept-unsigned with `logger.warning` + emit `rtf_sidecar_unsigned_total` counter; flip strict mode in Session 12 |
| Demo scenarios drift from real backend behavior | MED | HIGH | Each scenario script runs through the real decorator chain — no mocks; smoke test in `/verify` |

---

**Draft locked pending 4-decision approval. Will NOT spawn agents until user replies "Y" / "go" / "approved".**
