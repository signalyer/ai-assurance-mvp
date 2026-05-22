# SESSION 09 — CLI + Python SDK + Postgres Event Projection

**Sprint day:** 9 of 12
**Date drafted:** 2026-05-22
**Predecessors:** Sessions 01a/01b/02/03/04/05/06/07/08 — all complete (99/99 tests pass · 8 commits ahead of `origin/main`)
**Status:** PRE-EXECUTION REVIEW — awaiting 4 locked decisions + explicit "go" before sub-agent spawn

---

## 1. Decorator chain (UNCHANGED)

```
@policy_gate → @scrub_pii → @guardrails → @trace_llm_call → @evaluate_response
```

Session 09 does **NOT** touch decorator implementations. The SDK *re-exports* the existing decorators from `middleware.policy`, `middleware.scrubber`, `middleware.guardrails`, `tracer`, and `evaluator` as `signallayer.{policy_gate, scrub_pii, guardrails, trace, evaluate}`, plus a single `signallayer.init(api_key=..., base_url=...)` entry point. The SDK enforces decorator-order at import time via a `signallayer.guard` helper that inspects the stack of decorators on a target callable and raises `DecoratorOrderError` if the chain is wrong. No new chain stages. No reordering. No rewrites.

The Postgres projection worker reads from `data/events.jsonl` (the audit-chained event log written by Session 08) and writes to materialized tables — it is a *read-side* projection; it never writes to the JSONL ground truth.

---

## 2. Files to CREATE (one-line purpose each)

| File | Purpose |
|---|---|
| `sdk/signallayer/__init__.py` | Public surface: `init`, `policy_gate`, `scrub_pii`, `guardrails`, `trace`, `evaluate`, `guard`, version. |
| `sdk/signallayer/client.py` | HTTP client to the platform: HMAC-SHA-256 signing of `(ts, method, path, body_sha256)`; retries with backoff; typed `Result`. |
| `sdk/signallayer/decorators.py` | Re-exports of the 5 platform decorators with SDK-level config wiring (`base_url`, `api_key`, `tenant`). |
| `sdk/signallayer/order_guard.py` | `guard(fn)` — compile-time / import-time decorator-order assertion via `fn.__wrapped__` walk. |
| `sdk/signallayer/errors.py` | `SignalLayerError`, `AuthError`, `PolicyDeniedError`, `DecoratorOrderError`, `ChainBrokenError`. |
| `sdk/pyproject.toml` | Build config: name=`signallayer`, version=`0.1.0`, Python>=3.12, deps pinned. |
| `sdk/README.md` | 60-second quickstart with `examples/billing_agent.py` snippet. |
| `sdk/examples/billing_agent.py` | End-to-end demo: decorated function, `init()`, real call, prints trace+vault_id. |
| `cli/sl/__init__.py` | Package marker. |
| `cli/sl/__main__.py` | `python -m sl` entry. |
| `cli/sl/main.py` | Typer/Click app — root command + subcommand dispatch. |
| `cli/sl/cmd_login.py` | `sl login` — stores HMAC key (and/or device-code token per decision Q2) in `~/.signallayer/credentials.json` (0600). |
| `cli/sl/cmd_onboard.py` | `sl onboard <system-name>` — POST `/api/intake` + open portal URL. |
| `cli/sl/cmd_eval.py` | `sl eval run <system-id>` — POST `/api/evaluate/run`, stream results, exit 0/1 on pass/fail. |
| `cli/sl/cmd_gate.py` | `sl gate check <system-id>` — GET gate decision, exit 0/1 on PASS/FAIL. |
| `cli/sl/cmd_trace.py` | `sl trace tail [--system <id>]` — SSE tail from `/api/traces/stream` (read-only). |
| `cli/sl/cmd_evidence.py` | `sl evidence export <system-id> --framework <id> --out <path>` — downloads evidence ZIP from existing evidence API. |
| `cli/sl/auth.py` | HMAC signer (and/or Entra device-code per decision Q2); constant-time compare on responses. |
| `cli/sl/config.py` | Credentials file IO + env-var override (`SL_API_KEY`, `SL_BASE_URL`). |
| `cli/pyproject.toml` | Build config: name=`signallayer-cli`, console_script `sl = sl.main:app`. |
| `cli/README.md` | Command reference + onboarding flow diagram (ASCII). |
| `domain/projection.py` | Projection worker core: pure function `project_event(event, conn) -> None` dispatching by `event_type` → upsert to materialized tables. Idempotent on `(event_id)`. |
| `domain/projection_worker.py` | Worker loop: per-decision Q3 (LISTEN/NOTIFY · polling · CDC) — `run_forever()` + graceful shutdown + checkpoint to `data/projection_checkpoint.jsonl`. |
| `migrations/009_projection_views.sql` | Materialized tables: `ai_systems`, `eval_runs`, `findings`, `release_decisions`, `policy_evaluations` + schema per decision Q4 (column-per-event-type vs JSONB+GIN). |
| `api/projection.py` | FastAPI router — `GET /api/projection/status` (lag, last event_id, checkpoint), `POST /api/projection/replay?from=<event_id>` (privileged), `GET /api/projection/views/{view}` (paged). |
| `static/projection.html` | Read-side viewer: lag indicator, per-view counts, replay button (privileged). |
| `middleware/hmac_auth.py` | HMAC verification middleware for CLI/SDK boundary (rejects on bad signature, drift > 300s, replay via nonce cache). |
| `tests/test_sdk_client.py` | HMAC signing round-trip · retry behavior · error mapping. |
| `tests/test_sdk_order_guard.py` | Correct chain → pass · wrong order → `DecoratorOrderError` · missing decorator → error. |
| `tests/test_cli_commands.py` | Click/Typer runner: login (writes 0600 file) · onboard (mocked HTTP) · gate check (exit codes) · evidence export (file written). |
| `tests/test_projection_worker.py` | Replay 50 synthetic events → materialized views match JSONL ground truth · idempotency on duplicate apply · checkpoint resume. |
| `tests/test_hmac_auth.py` | Valid sig 200 · drifted ts 401 · replayed nonce 401 · tampered body 401. |
| `tests/test_session09_integration.py` | End-to-end: `pip install -e ./sdk` → run `examples/billing_agent.py` → CLI `sl gate check` against the resulting system → projection view contains the run. |

**Total new files:** 31 (SDK 8 · CLI 11 · projection 4 · middleware 1 · UI 1 · tests 5 · plan 1).

---

## 3. Files to MODIFY (exact change)

| File | Exact change |
|---|---|
| `dashboard.py` | Mount 2 new routers: `api.projection.router` and (conditionally) HMAC-auth middleware ahead of `SessionAuthMiddleware` for `/api/sdk/*` paths only. No change to existing route order. |
| `middleware/auth.py` | Add path-prefix exclusion for `/api/sdk/*` (delegated to HMAC middleware). Single-line allowlist append. |
| `requirements.txt` | Add `typer>=0.12`, `psycopg[binary]>=3.2` (already present — verify), `httpx>=0.27` (verify), `cryptography` (verify). No version bumps to existing pins. |
| `ARCHITECTURE.md` | Append Session 09 block: SDK + CLI + projection files, decision Q1–Q4 outcomes, new `/api/projection/*` + `/api/sdk/*` endpoints. |
| `DECISIONS.md` | Append 4 new entries (SDK distribution · CLI auth · projection strategy · view schema). |
| `docs/HANDOFF.md` | Rewrite for Day 10 entry; record 99 → 99+N test count; surface any new debt. |
| `.gitignore` | Add `~/.signallayer/`, `sdk/dist/`, `cli/dist/`, `data/projection_checkpoint.jsonl`. |
| `local.env` | Add `SL_HMAC_SECRET`, `SL_API_BASE_URL`, `PROJECTION_MODE` (per Q3), `PROJECTION_DSN` placeholders — values NOT committed. |

**No modifications to:** any `domain/*` Session 01–08 module, decorator chain order, scrubber, vault, policy engine, guardrails, RAG, agent memory, audit chain, right-to-forget cascade. Session 09 is strictly additive on the write side; projection is read-only against `events.jsonl`.

---

## 4. Two most critical architectural constraints

1. **`scrubber.tokenise_payload()` BEFORE `tracer.trace_call()` — INVARIANT.** The SDK re-exports decorators in the platform order and the `signallayer.guard` order-checker fails closed (`DecoratorOrderError`) on any deviation. The CLI never sees raw prompts: it talks only to platform endpoints which are already scrubber-gated. Projection worker reads scrubbed events from `events.jsonl` — it MUST NOT join against `data/vault.jsonl` or include `raw_prompt` in any materialized view. Acceptance test asserts no `vault_id → raw_prompt` join exists in `domain/projection.py`.

2. **Projection is a read-side replica — JSONL remains the source of truth.** `domain/projection_worker.py` is allowed to read `events.jsonl` and write to Postgres materialized tables ONLY. It MUST NOT write back to JSONL, MUST NOT mutate `events.jsonl`, MUST NOT call `repository._append_jsonl`. A replay must be safely re-runnable: every projection upsert is idempotent on `(event_id)`. If Postgres is unavailable, the platform continues to operate; only `/api/projection/*` endpoints degrade. Audit chain verification still runs against JSONL unchanged.

---

## 5. Will NOT build (explicit non-goals)

- Node/Go/Java SDKs (Python-only per Section 8 of sprint plan).
- Real-time webhooks (polling/SSE sufficient — Phase 2).
- Bedrock provider in SDK (Anthropic + OpenAI only).
- Multi-tenant projection (single-tenant v1).
- Streaming eval CLI (`sl eval run` is batch only).
- Custom DSL on CLI (no scripting language — flags only).
- Projection replay UI beyond a single button (no time-travel debugger).
- Hash-chain replication to Postgres (chain stays in JSONL — projection includes hash columns for read-only display only).
- BYO Azure subscription deploys for CLI `onboard` (single subscription v1).
- Postgres HA / read replicas for the projection (single primary).
- Mobile responsive `static/projection.html` (desktop-first).
- Any refactor of the 3 existing SQLAlchemy engines (deferred to Day 10 hardening).
- Auth on `GET /api/audit/events` (carried Session 08 HIGH debt — Day 10).
- Pagination fix for `domain/rag_engine.py` `purge_chunks` (carried Session 08 HIGH debt — Day 10).
- O(n) prev_hash re-read in `domain/audit_chain.py` (carried Session 08 HIGH debt — Day 10).

---

## 6. Acceptance criteria (runnable assertions)

Each criterion is paired with the exact assertion that will run in `tests/test_session09_integration.py` or via shell:

| # | Criterion | Runnable assertion |
|---|---|---|
| A1 | SDK installs editable and example runs end-to-end | `pip install -e ./sdk && python sdk/examples/billing_agent.py` exits 0 and stdout contains a `vault_id=` and a `trace_id=` line |
| A2 | SDK enforces decorator order at import time | `pytest tests/test_sdk_order_guard.py -k wrong_order` asserts `DecoratorOrderError` raised |
| A3 | SDK HMAC signing round-trips against `middleware/hmac_auth.py` | `pytest tests/test_hmac_auth.py` — 4 cases (valid/drift/replay/tamper) all pass |
| A4 | `sl onboard my-new-agent` creates a system | `sl onboard my-new-agent --no-browser` exits 0; subsequent `GET /api/intake/systems` includes `name == "my-new-agent"` |
| A5 | `sl gate check sys-001` exit codes correct | Seeded passing system → exit 0; seeded failing system → exit 1; assertion via `subprocess.run([...]).returncode` |
| A6 | `sl trace tail` streams SSE | CLI receives ≥1 event within 5s of a synthetic `trace_call` against test system |
| A7 | `sl evidence export` writes a valid ZIP | File exists, is a valid zipfile, contains `manifest.json` |
| A8 | Postgres projection matches JSONL ground truth | After replay of N events, `SELECT count(*) FROM eval_runs` == count of `EVAL_RUN_*` events in `events.jsonl`; per-view spot checks for `ai_systems`, `findings`, `release_decisions`, `policy_evaluations` |
| A9 | Projection is idempotent | Apply same event batch twice — row counts identical; no UNIQUE-violation errors |
| A10 | Projection never writes JSONL | `grep -r "_append_jsonl\|events.jsonl" domain/projection*.py` returns no write call (read-open only) |
| A11 | Projection worker survives crash + resume | Kill worker mid-batch, restart, checkpoint resumes from last event_id; final state matches single-shot replay |
| A12 | HMAC middleware rejects bad signatures | `curl` with tampered body → 401; with valid sig → 200 |
| A13 | Decorator chain unchanged | `pytest tests/` — all 99 pre-existing tests pass (regression) |
| A14 | No new decorator order in production code | `grep -r "@trace_llm_call\|@scrub_pii\|@policy_gate" --include="*.py"` chain order unchanged at every call site |
| A15 | `/verify` passes | All health probes green; Session 09 routes mounted |

**Pass bar:** 15/15 + 99 regression = 114+ tests must pass before commit.

---

## 7. Locked-decision dependencies (BLOCKING)

Sub-agent spawn does NOT proceed until the 4 questions below are answered "Y / go / approved":

- **Q1 — SDK distribution:** affects `sdk/pyproject.toml`, README install snippet, CI publish step.
- **Q2 — CLI auth model:** affects `cli/sl/auth.py`, `middleware/hmac_auth.py`, credentials-file layout.
- **Q3 — Postgres projection strategy:** affects `domain/projection_worker.py` core loop, `dashboard.py` startup wiring, dev tooling.
- **Q4 — Materialized view schema:** affects `migrations/009_projection_views.sql`, `domain/projection.py` upsert SQL.

---

## 8. Sub-agent plan (executes ONLY after approval)

Single `Agent` message with 3 parallel implementers (per `feedback_subagents_context_default.md`):

1. **SDK implementer** — owns `sdk/**` + `tests/test_sdk_*.py`.
2. **CLI + HMAC implementer** — owns `cli/**`, `middleware/hmac_auth.py`, `tests/test_cli_*.py`, `tests/test_hmac_auth.py`.
3. **Projection implementer** — owns `domain/projection*.py`, `migrations/009_projection_views.sql`, `api/projection.py`, `static/projection.html`, `tests/test_projection_worker.py`.

Then sequentially:
4. Integration test author wires `tests/test_session09_integration.py`.
5. Full test run: 99 regression + new tests.
6. Parallel `code-reviewer` + `security-reviewer` in one Agent message.
7. Update `ARCHITECTURE.md` + `DECISIONS.md` + `docs/HANDOFF.md`.
8. Commit: `Feat: Session 09 — CLI + SDK + Postgres event projection (Day 9)`.

---

## 9. Open risks for this session

- **HMAC clock drift on Windows dev boxes** — mitigation: 300s drift tolerance + explicit error.
- **`psycopg` LISTEN/NOTIFY behavior under `psycopg[binary]` 3.2** — verify before committing to Q3 LISTEN/NOTIFY.
- **Click vs Typer** — Typer is a Click superset; default to Typer for type-hint ergonomics unless decision overrides.
- **Editable install on Windows** — `pip install -e ./sdk` must succeed on PowerShell; CI parity check.
- **Projection replay against 1000s of historical events** — bound integration test to ≤500 events to keep <5s.
