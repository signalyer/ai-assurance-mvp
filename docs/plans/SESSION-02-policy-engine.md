# SESSION 02 — Policy Engine (OPA)
# Date: 2026-05-21 (executed)
# Context cost: HIGH
# Status: COMPLETE

## What this session built
The OPA-style policy enforcement layer:
1. `domain/policy_engine.py` — OPA HTTP client + local Python fallback
2. `domain/trust_scorer.py` — workload trust scoring from policy history
3. `middleware/policy.py` — `@policy_gate` decorator
4. `policies/*.rego` — 4 Rego policy files (5 categories covered)

## Pre-conditions (ALL MET)
- [x] Session 01a complete (scrubber + vault built)
- [x] Session 01b complete (decorator pattern + tracer hardened)
- [x] Decorator chain order established: `@policy_gate -> @scrub_pii -> @trace_llm_call`
- [x] Pydantic v2 + Python 3.12 environment ready

## Files Created
1. **`domain/policy_engine.py`** — Core policy evaluator
   - `evaluate(workload_id, action, input_data, categories) -> PolicyResult`
   - `PolicyResult` dataclass: decision, category, policy_name, reason, metadata
   - `Decision` enum: ALLOW, DENY, REVIEW
   - `PolicyCategory` enum: ORG_MANDATORY, POSTURE, RISK_TIER, TEAM, SYSTEM_OVERRIDE
   - OPA HTTP client (uses `OPA_URL` env var)
   - Local Python fallback (when OPA not available)
   - Decision logging to `data/policy_decisions.jsonl` (audit trail)
   - `policy_stats()` for /api/policies/stats endpoint

2. **`domain/trust_scorer.py`** — Trust scoring
   - `trust_score(workload_id, lookback_days)` — single workload score
   - `all_workload_scores(lookback_days)` — all workloads
   - Score = 100 - DENY_PENALTY - REVIEW_PENALTY (with time decay)
   - Half-life: 7 days; Category multipliers applied
   - Returns: score (0-100), band (HIGH/MEDIUM/LOW), violation counts

3. **`middleware/policy.py`** — `@policy_gate` decorator
   - `@policy_gate(action, workload_id_arg, allow_review, strict)`
   - Extracts workload_id + prompt/response/domain from args
   - DENY raises `PolicyDeniedError` (fail-closed)
   - REVIEW proceeds with `policy_result` kwarg (when allow_review=True)
   - Backward compat: `POLICIES_ENABLED=false` disables enforcement

4. **`policies/base.rego`** — Org-mandatory rules
   - Rule 1: Raw PII never sent to external services
   - Rule 2: Memory writes must have scrubbed content

5. **`policies/pii.rego`** — Posture-aware PII rules
   - US-FinServ: disclaimer required for financial advice
   - US-FinServ: risk disclosure required for stock recommendations
   - EU-GDPR: cross-border PII transfer prohibited
   - HIPAA: PHI requires explicit authorization

6. **`policies/agent_tools.rego`** — Team-based tool authorization
   - Per-team tool allowlists (payments, support, engineering, marketing, data)
   - Payments team requires preauthorization
   - Code execution requires sandbox
   - Network calls require allowed domain

7. **`policies/financial_advisor.rego`** — Risk-tier policies for financial advisors
   - CRITICAL tier requires human-in-the-loop
   - Specific dollar amounts trigger REVIEW
   - Guaranteed-return claims trigger DENY (regulatory violation)
   - HIGH/CRITICAL require audit_session_id

## Files Modified
None directly — `@policy_gate` decorator is available for wiring in Session 03+.

## Architectural Constraints
- ✓ Fail-closed: errors and ambiguity default to DENY
- ✓ Decorator chain order: `@policy_gate` FIRST (before `@scrub_pii`)
- ✓ Policy decisions logged to `data/policy_decisions.jsonl` (audit trail)
- ✓ Backward compat: `POLICIES_ENABLED=false` for dev/test
- ✓ OPA-ready: HTTP client tries OPA first, falls back to local Python
- ✓ Trust scoring: time-decayed, category-weighted penalties

## Architecture: Decorator Chain (FULL ORDER)
```
@policy_gate                 ← Session 02 (NEW)
   |
   v (if ALLOW or REVIEW with allow_review=True)
@scrub_pii                   ← Session 01b
   |
   v (if vault_id set)
@trace_llm_call              ← Session 01a (tracer.py hardened)
   |
   v (always — for evaluation)
@evaluate_response           ← existing (evaluator.py)
```

## Acceptance Criteria
```bash
# 1. Module imports
python -c "from domain.policy_engine import evaluate; print('OK policy_engine')"
python -c "from domain.trust_scorer import trust_score; print('OK trust_scorer')"
python -c "from middleware.policy import policy_gate; print('OK middleware/policy')"

# 2. Policy decisions (5 categories)
# - Org-mandatory PII detection (raw email/SSN -> DENY)
# - Posture (US-FinServ disclaimer -> REVIEW)
# - Risk-tier (CRITICAL human-in-loop -> REVIEW)
# - Team (payments preauth -> DENY)
# - System-override (active -> ALLOW)

# 3. Trust scoring
# - Workload with violations -> score < 100
# - Workload with no violations -> score = 100
# - Bands: HIGH/MEDIUM/LOW

# 4. Decorator behavior
# - @policy_gate on async fn: enforces policies
# - DENY: raises PolicyDeniedError
# - REVIEW: passes through with policy_result kwarg
# - POLICIES_ENABLED=false: bypass enforcement (backward compat)
```

## What NOT to build in this session
- ❌ Deploy OPA sidecar to Azure App Service (Session 10 deployment)
- ❌ Wire @policy_gate into demo_run.py (Session 03 integration)
- ❌ Build /policies UI page (Session 06)
- ❌ Build api/policies.py router (Session 06)
- ❌ Build runtime policy management (Session 04 memory layer)

## Decision Log
- **Decision:** Chose Python fallback evaluator over Python-only (no OPA) approach
  - **Why:** Allows local dev/test without OPA install; production can use OPA sidecar
  - **Trade-off:** Two code paths to maintain; mitigated with shared logic patterns

- **Decision:** Decision logging is separate from main run logging
  - **Why:** Trust scoring needs structured policy decisions; mixing with run logs would force complex queries
  - **Trade-off:** Two JSONL files instead of one

- **Decision:** Time decay (half-life 7 days) for trust scoring
  - **Why:** Recent violations matter more than old ones; allows workloads to recover trust
  - **Trade-off:** Need to refresh trust scores periodically (cron job in Session 10)

## End-of-Session Actions
1. ✓ All smoke tests pass (policy_engine, trust_scorer, middleware/policy)
2. ✓ ARCHITECTURE.md updated to mark Session 02 files as Built
3. ✓ Decision log added to DECISIONS.md (Session 02 trade-offs)
4. ✓ Next session plan: `docs/plans/SESSION-03-guardrails.md` (NeMo + Llama Guard)

## Verification Commands
```bash
export SESSION_SECRET="test-secret"
export SCRUBBER_ENABLED="true"
export POLICIES_ENABLED="true"

# Smoke tests
python -m domain.policy_engine
python -m domain.trust_scorer
python -m middleware.policy

# Stats
python -c "from domain.policy_engine import policy_stats; print(policy_stats())"
python -c "from domain.trust_scorer import all_workload_scores; print(all_workload_scores())"
```
