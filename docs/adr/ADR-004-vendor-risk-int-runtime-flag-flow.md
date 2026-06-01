# ADR-004 — vendor_risk INT runtime-flag flow

- **Status:** Accepted (2026-06-01)
- **Deciders:** Praveen Kosuri
- **Supersedes:** none
- **Related:** `policies/vendor-risk-int.rego`, `domain/agent_runner.py:201-205`,
  `docs/sop-vendor-risk/07-staged-calibration-log.md`,
  `docs/SOP-agent-onboarding.md` Phases 3 and 8,
  CLAUDE.md 2026-06-01 rule — "operator_role must thread from session cookie to policy_engine"
- **Context anchors:**
  [`domain/agent_runner.py:201`](../../domain/agent_runner.py) (policy_evaluate call site),
  [`policies/vendor-risk-int.rego:82`](../../policies/vendor-risk-int.rego) (required_true_flags),
  [`middleware/auth.py:49`](../../middleware/auth.py) (ROLES tuple)

---

## 1. Context

The `vendor_risk` agent has two AI systems: EXT (`sys-vendor-risk-ext-001`, cloud LLM, 10/10 tier-match calibrated) and INT (`sys-vendor-risk-int-001`, no-egress internal path, 0/8 LLM behavior calibrated). INT calibration is blocked because `policies/vendor-risk-int.rego` requires two runtime boolean flags — `dlp_completed` and `network_egress_lock_engaged` — before the LLM step proceeds. These flags are read from `input_data` in `policy_engine.evaluate()`.

The dispatcher at `domain/agent_runner.py:201-205` builds `input_data = {"prompt": prompt, "operator_role": operator_role}`. Neither flag is ever present. All 8 INT calibration runs in S82f-1c DENIED at `policy_gate` with `workload_required_flag_not_set` at mean 4.0ms. There is no sanctioned path for an operator to set these flags. INT LLM calibration (Phase 6 completion and Phase 8 STAGED readiness) cannot proceed without one.

The flags are real safety controls. `dlp_completed` means the DLP pipeline confirmed no unmasked sensitive tokens will reach the LLM. `network_egress_lock_engaged` means the network isolation contract is provably enforced at the host level. Both must be true before it is safe to run vendor_risk against internal sensitive material. The solution must not make them defaultable, per-call user-togglable in a way that bypasses accountability, or silently inferred.

### Pre-analysis finding — tprm-analyst role does not exist in the auth layer

`policies/vendor-risk-int.rego:69-72` declares `required_operator_roles := {"tprm-analyst", "ciso"}`. But `middleware/auth.py:49` defines `ROLES = ("CRO", "CISO", "AUDIT", "MRM", "AIGOV", "OPERATOR", "ENGINEER")`. There is no `tprm-analyst` entry. The only role that can currently satisfy the INT role gate is `ciso`. This rego/auth mismatch is a pre-existing gap. It must be resolved as a prerequisite to any flag-flow implementation, regardless of which option is chosen. The implementation is assumed to bundle this fix.

---

## 2. Decision Drivers

| Driver | Weight |
|---|---|
| Flags are real safety controls — must not be bypassable or silently set | HARD CONSTRAINT |
| Attestation must produce an audit-chain record attributable to a named operator | High |
| Implementation must unblock INT LLM calibration (Phase 6 to Phase 8) | High |
| Role gate must use provisionable roles from `middleware/auth.py:ROLES` | High |
| SOP Phase 8 exit criterion: "all controls demonstrated active" over 100+ runs | High |
| Blast radius if the flow is abused or misconfigured | High |
| Implementation cost relative to current SOP phase (demo_only=True, Phase 6) | Medium |
| Policy engine errors default DENY — must not introduce ALLOW-on-error | HARD CONSTRAINT |

---

## 3. Options Considered

### Option A — Per-run attestation UI (operator attests per invocation)

Before every INT run, the Agent Runner SPA renders a pre-run banner. The operator ticks two checkboxes ("DLP scan completed" / "Egress lock engaged") and provides a free-text justification. The signed attestation is carried in the SSE request body and injected into `input_data` by the dispatcher. Flags are not persisted on the AI System row — they exist only for that invocation. Requires `ciso` role (pending tprm-analyst fix).

**Pros:** lowest implementation cost (~0.5 sessions). No `AISystem` schema change. Per-run audit trace is rich. Unblocks INT calibration quickly.

**Cons:** any client can inject `dlp_completed=true` in the request body — the rego trusts `input_data` verbatim and there is no server-side validation that a real DLP scan occurred. Does not satisfy SOP Phase 8 "failure-mode drill" exit criterion (flags cannot be tested for expiry or revocation because they do not persist). Per-calibration-run attestation friction is acceptable for 8 fixtures but is not a production pattern.

**Cost estimate:** ~0.5 sessions. No new Azure resources.

### Option B — Sticky PATCH on AISystem row with TTL (RECOMMENDED)

New endpoint: `PATCH /api/ai-systems/{id}/runtime-flags`. Body: `{dlp_completed, network_egress_lock_engaged, attested_by, attested_at, justification, expires_at}`. Flags are persisted on the AI System's JSONL record in `data/ai_systems.jsonl` via `storage.py`. TTL defaults to 24h; after expiry the dispatcher reads absent/expired flags and the next run DENIES until re-attested.

The dispatcher reads the system's persisted flags before calling `policy_evaluate()` and injects them into `input_data`. A separate `audit_chain.append_chained_event()` write records the attestation at PATCH time — independently of any run — so the audit row exists even if no run fires. Role gate on the PATCH: `ciso` initially (single-signer); designed to accept a second approver when `tprm-analyst` is provisioned.

**Pros:** server-side enforcement — a fabricated request body at run time is ignored; the dispatcher reads from the persisted row, not from the caller. TTL auto-expiry matches the real semantics of an egress lock that may be disengaged. Audit chain write is independent of runs. Directly satisfies SOP Phase 8 "failure-mode drill" exit criterion: attest via PATCH, verify ALLOW; let TTL expire, verify DENY; re-attest, verify ALLOW. Non-breaking `AISystem` schema extension — existing EXT runs unaffected.

**Cons:** one additional domain model (`RuntimeFlags`). Dispatcher must do a JSONL lookup on every INT policy_gate step (~1-2ms local disk read; acceptable). `api/ai_system_edit.py` grows a new route and RBAC dependency. Implementation cost ~1.5 sessions.

**Cost estimate:** ~1.5 sessions. No new Azure resources.

### Option C — Capability matrix in AISystem + per-run CISO override

`AISystem` schema gains a `capabilities` block encoding `dlp_program_maturity`, `egress_lock_default`, etc. Default flag values are derived from the matrix at startup. Per-run override available to `ciso` with justification.

**Pros:** more expressive governance model; could serve multiple systems.

**Cons:** substantially more surface area at SOP Phase 6 with `demo_only=True`. "Default values derived from the matrix" creates a path where `dlp_completed=True` by default if `dlp_program_maturity` is rated Tier 3 — a configuration parameter silently satisfying a runtime control. This violates the same principle as "policy engine errors default DENY." No current consumer of a capability matrix exists outside vendor_risk INT.

**Verdict:** rejected for current phase.

---

## 4. Decision

**Option B. High confidence.**

The two flags are runtime safety controls. A sticky server-side attestation with TTL and an independent audit chain write is the only design that enforces the flags via state a client cannot fabricate, auto-expires them (matching the real semantics of an egress lock), produces an audit record independent of whether a run fires, and satisfies the SOP Phase 8 failure-mode drill exit criterion.

Option A is appealing for speed but its blast radius — any client can inject `dlp_completed=true` without server validation — makes it unsuitable as the primary enforcement boundary for a no-egress safety contract. The SOP requires that controls be demonstrably active, not just logically present in the request body.

Option C defers to a future ADR. The current need is scoped and bounded; a generalized capability matrix solves a problem that does not yet exist elsewhere.

---

## 5. Consequences

**Positive:**
- INT calibration unblocked after ~1.5 sessions of implementation.
- Attestation is independently auditable via audit chain write at PATCH time.
- TTL expiry gives Phase 8 a clean deny-on-expiry drill path.
- tprm-analyst role alignment forces an overdue rego/auth reconciliation that would otherwise surface as a production incident.
- Non-breaking schema extension — existing EXT runs are unaffected.

**Negative / risks:**
- INT LLM calibration is delayed by ~1.5 sessions. The 8 INT fixtures remain in DENY until Option B is implemented and a valid attestation is PATCHed.
- If `expires_at` is set too aggressively for a long calibration session, the TTL may expire mid-run and produce an inconsistency in the calibration log. Set to 24h for calibration; expose `RUNTIME_FLAG_TTL_SECONDS` as an env override before Phase 8.
- The audit chain write at PATCH time introduces a new `event_type`. Existing consumers of `verify_chain` handle unknown event types gracefully (hash verification only), so no breakage, but the new type must be documented in the chain schema.
- `assert_no_egress()` in `agents/vendor_risk/agent.py` is still not wired on the INT execution path. The rego gate is the primary control and already blocks egress. This ADR does not close that gap.

**Technical debt incurred:** `storage.py` grows a JSONL lookup path for runtime flags. At demo scale this is negligible. If system count exceeds ~50, a future ADR should address indexed storage.

---

## 6. Files to Add or Modify

| File | Change | Rationale |
|---|---|---|
| `domain/models.py` | Add `RuntimeFlags` Pydantic model; add `runtime_flags: Optional[RuntimeFlags] = None` to `AISystem` | Schema grounding for the persisted attestation block |
| `storage.py` | Add `read_system_runtime_flags(system_id: str) -> RuntimeFlags \| None` and `patch_system_runtime_flags(system_id: str, flags: RuntimeFlags) -> None` | Canonical JSONL access per project CLAUDE.md storage rules; `_append_jsonl` / `_read_jsonl` pattern |
| `domain/agent_runner.py` | Before `policy_evaluate()` at line ~200: if `effective_system_id` starts with `"sys-vendor-risk-int-"`, call `storage.read_system_runtime_flags()` and inject returned flag values into `input_data` | Dispatcher is the only sanctioned injection point; rego must not be changed |
| `api/ai_system_edit.py` | New route `PATCH /api/ai-systems/{id}/runtime-flags`, role-gated to `ciso`; writes flags via `storage.patch_system_runtime_flags()`; emits audit chain event | Existing system-edit router is the right home per project file-placement rules |
| `middleware/auth.py` | Add `"TPRM_ANALYST"` to `ROLES` tuple **OR** update `policies/vendor-risk-int.rego` `required_operator_roles` to use `"audit"` — **user must decide which path before implementation** | Closes pre-existing rego/auth mismatch; no implementation should proceed without resolving this |
| `policies/vendor-risk-int.rego` | Change only if `tprm-analyst` is NOT added to `ROLES` | The flag gate logic is correct and must not be changed |
| `docs/SOP-agent-onboarding.md` Phase 8 | Add sub-step under "Failure-mode drills": "For systems with `required_true_flags` (e.g. `sys-vendor-risk-int-001`): (a) attest via PATCH → verify `policy_gate: ALLOW`; (b) let TTL expire → verify `policy_gate: DENY`; (c) re-attest → verify ALLOW. Record each drill outcome in the STAGED run log." | Phase 8 exit criterion already requires controls be demonstrated; this makes the INT flag flow an explicit drill item |
| `agents/vendor_risk/eval/run_calibration.py` | Before submitting INT fixtures: PATCH runtime flags (demo-ciso, justification="calibration run"); after all fixtures complete, let TTL expire or PATCH to clear | Calibration harness must drive the flag lifecycle, not assume flags are pre-set |

---

## 7. Rejected for Now (Revisit Triggers)

- **Option A (per-run attestation UI):** revisit only if the codebase needs multiple simultaneous operators running INT concurrently where sticky flags would cause cross-operator interference. Not a current concern at demo scale.
- **Option C (capability matrix):** revisit when a second system type requires the same `required_true_flags` rego pattern, making the abstraction cost worthwhile.
- **Dual-sign requirement:** Option B is single-signer (CISO). Revisit for Phase 10 (Pilot) when `tprm-analyst` is provisioned and the production sign-off process is established. Dual-sign is the correct production posture; it is deferred, not abandoned.

---

## 8. Open Questions Not Closed by This ADR

1. ~~**tprm-analyst role alignment (implementation blocker).**~~ **RESOLVED 2026-06-01: Path A.** Add `TPRM_ANALYST` to `middleware/auth.py:ROLES` tuple, provision `DEMO_USER_TPRM_ANALYST_HASH` app setting, and add a demo user. Rationale: the rego's distinction between `tprm-analyst` (second-line risk function) and `ciso` (executive accountability) is deliberate. Collapsing to `audit` (third-line assurance) would conflate accountabilities the two-line-of-defense model is meant to separate, and Phase 9 Pre-Release Assessment would force the role split anyway. Implementation cost ~30min; correctness preserved through to production.

2. **`assert_no_egress()` wiring.** INT LLM calibration can proceed once flags are set via Option B — the rego gate is the primary control. However, `assert_no_egress()` in `agents/vendor_risk/agent.py` should be wired in the same S82f-2 session for defense-in-depth. If deferred past S82f-2, it must be logged as an open finding in the INT system's finding inventory. This ADR recommends but does not enforce that sequencing.

3. **TTL tuning for production.** 24h is appropriate for calibration and STAGED. For Phase 9 Pre-Release Assessment, Compliance should specify the window in which a DLP scan result and an egress lock are considered operationally fresh (likely 4-8h in a real financial-services context). Expose as `RUNTIME_FLAG_TTL_SECONDS`; do not hardcode it.
