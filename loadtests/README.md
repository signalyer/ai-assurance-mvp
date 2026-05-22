# Load-Test Harness — AI Assurance Platform

## Overview

Four test artefacts covering different layers of performance validation.

---

## Locust Scenario (End-to-End HTTP)

**File:** `loadtests/locustfile.py`

**Acceptance target (Phase 1 / B1 SKU):** 25 RPS sustained for 10 minutes, p95 < 2 000 ms, zero errors.

> SKU note: The 100 RPS target is documented as Phase 2 / S1 SKU. B1 (~$13/mo, single small core) is the
> demo deployment tier. Running 100 concurrent Locust users against a B1 instance will exceed its CPU
> budget and is not a supported acceptance gate in Phase 1.

**Run:**
```bash
locust -f loadtests/locustfile.py \
    --headless \
    -u 25 -r 5 \
    --run-time 10m \
    --host $LOCUST_TARGET
```

**Environment variables:**

| Variable         | Required | Description                                       |
|------------------|----------|---------------------------------------------------|
| `LOCUST_TARGET`  | Yes      | Base URL of the running application               |
| `LOCUST_SDK_KEY` | No       | When set, requests carry HMAC auth headers        |

**Task weights:**

| Task               | Weight | Endpoint                              |
|--------------------|--------|---------------------------------------|
| `scrub_endpoint`   | 60     | POST `/api/demo/run`                  |
| `policy_check`     | 20     | GET `/api/release-gates/{system_id}`  |
| `framework_matrix` | 10     | GET `/api/frameworks/matrix`          |
| `health`           | 10     | GET `/api/health`                     |

---

## Scrubber Microbench (In-Process)

**File:** `loadtests/scrubber_perf.py`

**Threshold:** p95 < 100 ms (constant `P95_MAX_MS = 100`)

**Run:**
```bash
python -m loadtests.scrubber_perf
```

Generates 10 000 synthetic PII payloads (email + SSN + name + phone) and
runs each through `scrubber.tokenise_payload()`. No network calls.

Exit code 0 = pass, 1 = fail, 2 = skipped (dependency unavailable).

---

## OPA / Policy-Engine Microbench (In-Process)

**File:** `loadtests/opa_p95.py`

**Threshold:** p95 < 50 ms (constant `P95_MAX_MS = 50`)

**Run:**
```bash
python -m loadtests.opa_p95
```

Runs 1 000 calls to `domain.policy_engine.evaluate()` using the local Python
fallback (OPA sidecar not required). `OPA_URL` is cleared for the duration of
the bench to guarantee local execution.

Exit code 0 = pass, 1 = fail, 2 = skipped.

---

## Framework Coverage Microbench (In-Process)

**File:** `loadtests/framework_coverage_perf.py`

**Threshold:** median wall time < 2 000 ms (constant `MEDIAN_MAX_MS = 2000`)

**Run:**
```bash
python -m loadtests.framework_coverage_perf
```

Calls `domain.framework_coverage.framework_matrix()` 50 times against the 6
seeded demo AI systems. If no seeded systems are present (fresh-start / empty
data directory), exits with code 2 (skipped) rather than failing — seed the
demo data first:

```bash
python mock_data.py
```

Exit code 0 = pass, 1 = fail, 2 = skipped (no seeded systems or dependency unavailable).

---

## Threshold Summary

| Bench                  | Metric    | Threshold  | Constant        |
|------------------------|-----------|------------|-----------------|
| Scrubber               | p95       | < 100 ms   | `P95_MAX_MS`    |
| OPA / Policy engine    | p95       | < 50 ms    | `P95_MAX_MS`    |
| Framework coverage     | median    | < 2 000 ms | `MEDIAN_MAX_MS` |
| Locust HTTP (Phase 1)  | p95       | < 2 000 ms | —               |

All in-process microbenches (scrubber, OPA, framework coverage) require no
Azure, Postgres, or Langfuse connectivity and are safe to run on the local
development machine.
