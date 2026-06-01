# 07 — Staged Calibration Log (S82f-1c)

## Header

- **Session:** S82f-1c
- **Date range:** _TBD on first run start_..._TBD on last run end_
- **Deploy SHA at start:** `f171f6d` (post-S82f-1b plaintext-secret-handoff fix)
- **Dataset:** `agents/vendor_risk/eval/dataset-external.jsonl` (10 cases) +
  `dataset-internal.jsonl` (8 cases) = **18 total**
- **Call origin:** Local SDK package harness
  (`agents/vendor_risk/eval/run_calibration.py`) → `POST /api/agent-runner/run`
  (SSE, cookie auth)
- **Operator:** _TBD_

## Caveats (recorded honestly per [[run-commands-dont-defer]] discipline)

1. **INT path still calls Anthropic.** The `assert_no_egress()` primitive
   exists but is not wired into the INT execution path; S82f-2 will swap
   to local-deterministic + close the egress assertion. The 8 INT runs in
   this calibration consumed external Anthropic API quota.
2. **Langfuse URLs are `None` on all events.** The audit-event builder is
   in place but `langfuse_trace_id` is empty until S83 wires the real
   trace_id through the chain.
3. **Dataset is 18, not 25.** The S82f-1 plan and S82f-1b handoff both
   referenced 25 cases (12 EXT + 13 INT). The actual dataset on disk is
   18 (10 EXT + 8 INT). Building the 7 missing fixtures is out of scope
   for S82f-1c — recorded as carry-over for S82f-2 fixture-gap fix.
4. **`/api/agent-runs/{id}` viewer is read-side new.** Persistence into
   `data/agent_runs.jsonl` was added in S82f-1c alongside the endpoint.
   Runs that pre-date this session are not visible there.

## Per-run table

| # | run_id | system_id | fixture | expected_tier | actual_tier | tier_match | latency_ms | operation_id | audit_id | notes |
|---|--------|-----------|---------|---------------|-------------|------------|------------|--------------|----------|-------|
| 1 | _pending_ | sys-vendor-risk-ext-001 | ext-01-clean-saas | MEDIUM | | | | | | |
| 2 | _pending_ | sys-vendor-risk-ext-001 | ext-02-clean-paas | MEDIUM | | | | | | |
| 3 | _pending_ | sys-vendor-risk-ext-001 | ext-03-clean-data-processor | MEDIUM | | | | | | |
| 4 | _pending_ | sys-vendor-risk-ext-001 | ext-04-clean-cdn | LOW | | | | | | |
| 5 | _pending_ | sys-vendor-risk-ext-001 | ext-05-edge-carveout-eu | HIGH | | | | | | |
| 6 | _pending_ | sys-vendor-risk-ext-001 | ext-06-edge-iso-expired | MEDIUM | | | | | | |
| 7 | _pending_ | sys-vendor-risk-ext-001 | ext-07-edge-conflicting-dpa | HIGH | | | | | | |
| 8 | _pending_ | sys-vendor-risk-ext-001 | ext-08-adv-pdf-injection | HIGH | | | | | | |
| 9 | _pending_ | sys-vendor-risk-ext-001 | ext-09-adv-soc2-type-confusion | HIGH | | | | | | |
| 10 | _pending_ | sys-vendor-risk-ext-001 | ext-10-adv-encryption-ambiguity | HIGH | | | | | | |
| 11 | _pending_ | sys-vendor-risk-int-001 | int-01-mnpi-deal-context | MEDIUM | | | | | | |
| 12 | _pending_ | sys-vendor-risk-int-001 | int-02-mnpi-active-deal | HIGH | | | | | | |
| 13 | _pending_ | sys-vendor-risk-int-001 | int-03-mnpi-board-package | HIGH | | | | | | |
| 14 | _pending_ | sys-vendor-risk-int-001 | int-04-intref-core-banking | HIGH | | | | | | |
| 15 | _pending_ | sys-vendor-risk-int-001 | int-05-intref-trading-platform | HIGH | | | | | | |
| 16 | _pending_ | sys-vendor-risk-int-001 | int-06-intref-customer-pii-export | HIGH | | | | | | |
| 17 | _pending_ | sys-vendor-risk-int-001 | int-07-hitl-critical-resid | CRITICAL | | | | | | |
| 18 | _pending_ | sys-vendor-risk-int-001 | int-08-hitl-high-resid-mnpi | HIGH | | | | | | |

The harness (`agents/vendor_risk/eval/run_calibration.py`) populates each row
on chain.done; each `run_id` is also retrievable via
`GET /api/agent-runs/{run_id}` (S82f-1c read endpoint).

## Audit-chain verification

Per run, the harness asserts a corresponding row in
`/home/data/audit_chain.jsonl` (via `/api/audit/chain/verify` or direct read
through the new viewer). Any miss is recorded in the run's `notes` column
and counted in the roll-up.

## Roll-up (filled after all 18 runs)

- **EXT pass-rate vs thresholds:** _TBD_ — see `agents/vendor_risk/eval/thresholds.json`
- **INT pass-rate vs thresholds:** _TBD_
- **Tier distribution:**
  - EXT actual: LOW=__ MEDIUM=__ HIGH=__ CRITICAL=__ (expected LOW=1 MEDIUM=3 HIGH=6)
  - INT actual: LOW=__ MEDIUM=__ HIGH=__ CRITICAL=__ (expected MEDIUM=1 HIGH=6 CRITICAL=1)
- **Mean latency EXT vs INT:** _TBD_
- **Failures / retries / escalation_triggered:** _TBD_
- **Audit-chain coverage:** _TBD_ / 18

## Threshold recommendation for S82f-2 lock

_Filled after roll-up. Compare actual pass-rate against
`agents/vendor_risk/eval/thresholds.json`; either propose new thresholds or
recommend a calibration iteration._

## Open carry-overs at session close

- 7 missing fixtures (handoff drift) → S82f-2 fixture-gap fix
- `assert_no_egress()` wiring on INT path → S82f-2
- Langfuse `trace_id` flow → S83
