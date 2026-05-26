# SESSION-52 — V1/V2 data-mode toggle + real-mode intake

**Status entering S52:** S50 closed end-to-end. S51 (Garak sidecar Phase 1) is the *technical* next session, but the V1→V2 real-data arc is the load-bearing product step — without it, S53-S55 (SDK onboarding wizard, real baselines, first live system) can't ship without breaking the demo. S52 should land **before** S53; can run before or after S51 since they touch different layers.

**Theme:** Make every page consciously V1 (seed-data demo portfolio) OR V2 (real customer systems). A `localStorage`-backed toggle in both portals' Topbars flips the mode. Every persisted row gets a `source: "seed" | "real"` field. The engine filters list endpoints by `X-Data-Mode` header. V2 mode with no data shows contextual "Register your first system" CTAs.

This is the unblock for the rest of the 4-session arc: S53 needs a place to put real systems without polluting V1 demos; S54 needs real-mode evals to file under `source=real`; S55 needs at least one real system live to instrument.

## Locked decisions (from S50 close — see [[project-v1-to-v2-real-data-arc]])

- **SDK-first telemetry**, not URL-probe. Onboarding flows around `pip install signallayer` + API-key + decorator chain. URL-probe connectors deferred.
- **localStorage toggle, not URL param, not user-profile setting.** Per-browser, per-device. Default `v1`. Toggle is a kill switch — flip to V1 mid-demo if V2 breaks.
- **`source` field, not separate tables.** A `findings_real` table is the wrong shape — every filter, projection, and audit-chain probe would need a v1/v2 fork. One field, one filter.
- **Engine filters; SPA does not.** SPA sends `X-Data-Mode: v1|v2`; engine list endpoints honor it. SPA never sees seed rows in V2 mode. Means engine is the single source of truth for what's visible.
- **Minimal 6-field intake.** Name, owner, domain, model provider, risk tier, intended use. `RegisterSystemPage` collects these already — don't expand here, expand in S56+.

## STEP 1 — engine `source` field + filter dependency (~90 min)

**Domain models** ([domain/models.py](../../domain/models.py)): add `source: Literal["seed", "real"] = "seed"` to: `AiSystem`, `Finding`, `EvalRun`, `EvidenceItem`, `Agent`, `AgentVersion`, `Policy`, `ReleaseDecision`. Default `"seed"` — every existing row backfills to that on load. Pydantic v2, default in `ConfigDict`-free field.

**Storage layer** ([storage.py](../../storage.py) + [domain/repository.py](../../domain/repository.py)): the JSONL writers (and the Postgres projection in [domain/projection.py](../../domain/projection.py)) already pass through arbitrary fields — verify `_append_jsonl` doesn't strip unknown keys. Migration script `migrations/052_source_field.sql`: `ALTER TABLE ai_systems ADD COLUMN source TEXT DEFAULT 'seed' NOT NULL;` for the 5 projection tables.

**Shared dependency** new `middleware/data_mode.py`: `def get_data_mode(request: Request) -> Literal["v1","v2"]` reads `X-Data-Mode` header, defaults to `"v1"` for backward compat. Tolerant of missing/malformed values — never raise.

**List-endpoint filtering**: every endpoint that returns rows for a list view honors mode. V1 = no filter (all rows visible). V2 = `[r for r in rows if r.source == "real"]`. Touch sites:
- [api/grc.py](../../api/grc.py) `/ai-systems`, `/findings`, `/policies` lists
- [api/findings_v2.py](../../api/findings_v2.py) `/list`
- [api/release_gates.py](../../api/release_gates.py) `/v2/systems`
- [api/evidence.py](../../api/evidence.py) `/v2/sectioned`, `/v2/completeness`
- [api/frameworks.py](../../api/frameworks.py) `/matrix` (filter the row set used by `framework_matrix`)
- [api/analytics.py](../../api/analytics.py), [api/reports.py](../../api/reports.py)
- [api/agents.py](../../api/agents.py), [api/agent_bindings.py](../../api/agent_bindings.py)

**Acceptance:** `curl -H "X-Data-Mode: v2" .../grc/ai-systems` returns `{"systems":[]}` against current prod (no real rows yet). `curl .../grc/ai-systems` (no header) returns seeded systems as before.

## STEP 2 — RegisterSystemPage writes `source: "real"` (~30 min)

[api/intake.py](../../api/intake.py) — the endpoint backing `RegisterSystemPage.tsx`. Tag intake-created systems with `source="real"` on persist. Existing seed flow ([domain/seed_systems.py](../../domain/seed_systems.py), called from `dashboard.py` startup) keeps writing `source="seed"`.

Add a unit test: `tests/test_intake_real_mode.py` asserts a POST to the intake endpoint persists a row with `source="real"`, and that the row is invisible to V1-mode `/grc/ai-systems` (it IS visible) AND visible to V2-mode (only this row). Sanity guard against the obvious off-by-one.

**Acceptance:** local register-flow E2E via `RegisterSystemPage` → V2 mode toggle on → page shows just the newly registered system. V1 mode → seeds + the new one.

## STEP 3 — `DataModeToggle` component in both Topbars (~45 min)

New shared component in both SPAs: `team-portal/src/shared/components/DataModeToggle.tsx` and `ciso-console/src/shared/components/DataModeToggle.tsx` (identical files — same pattern as `MicrosoftLogo.tsx` from S50).

Pattern:
- Module-level `dataMode = signal<"v1"|"v2">(...)`, initialized from `localStorage.getItem('aigovern_data_mode') ?? 'v1'`.
- Toggle = a small two-state switch in Topbar, label "Demo data" (V1) ↔ "Live data" (V2).
- On change: write `localStorage`, update signal, reload current page so list re-fetches (`window.location.reload()`).
- Visual: small pill, colored differently when V2 active so operators can SEE they're in live mode (red dot pre-V2; green dot pre-V1 to feel intentional).

Mount in both Topbars next to the user identity chip.

**Acceptance:** toggle visible in both portals, click flips localStorage + reloads, post-reload all list pages reflect the new mode.

## STEP 4 — `apiRequest` injects `X-Data-Mode` + V2 empty-states (~60 min)

[ciso-console/src/shared/api/client.ts](../../ciso-console/src/shared/api/client.ts) + [team-portal/src/shared/api/client.ts](../../team-portal/src/shared/api/client.ts): inside `apiRequest`, after `Accept: application/json`, append `X-Data-Mode: <localStorage value>`. Default to `v1` if unset.

**V2 empty-state copy** — touch every list page that already has an empty-state. When the empty state fires AND `dataMode === 'v2'`, replace the generic copy with a CTA:
- AI Systems empty (Team Portal) → "No AI systems registered yet. [Register your first system →]"
- Findings empty (CISO Console) → "No live findings yet. Findings appear automatically when an SDK-instrumented system produces a policy denial, guardrail violation, or eval regression. [Learn how to instrument →]"
- Release Gates empty → "Gates compute once an AI system has been registered and baselined. [Register →]"
- ... etc.

Each CTA links to the relevant page (RegisterSystemPage for portal, SDK quickstart for the "instrument" link). The SDK Quickstart page already exists (S17, surface #2) — point at it.

**Acceptance:** flip toggle to V2 on a fresh prod tenant → every list page shows the contextual empty-state CTA, no Loading-spinner leftover, no "HTTP 500" banner.

## STEP 5 — smoke probe + ARCHITECTURE.md (~30 min)

[deploy/smoke_gov.ps1](../../deploy/smoke_gov.ps1) + [deploy/smoke_portal.ps1](../../deploy/smoke_portal.ps1): Probe 7.
- 7a: `curl -H "X-Data-Mode: v1" $API/grc/ai-systems` → returns ≥6 systems (seeded).
- 7b: `curl -H "X-Data-Mode: v2" $API/grc/ai-systems` → returns 0 systems initially, OR ≥1 if any real intake has happened (assertion: `count(v2) <= count(v1)` — always true, drifts safely as real systems register).
- 7c: assert response shape unchanged across header presence — schema doesn't fork on mode.

ARCHITECTURE.md: new "Session 52" section under the existing arc; ADR-style note that the toggle is a **load-bearing product decision** and the `source` field is now an architectural invariant — any new domain entity MUST include it.

**Acceptance:** both smoke scripts 7/7 PASS against prod after deploy.

## Outstanding questions

1. **Toggle label copy**: "Demo data" / "Live data" vs "V1" / "V2" vs "Seed" / "Real"? Recommendation: "Demo data" / "Live data" — most explanatory to a customer demo audience peeking over the shoulder.
2. **Default mode at first paint**: V1 (safer) or V2 (forward-leaning)? Recommendation: V1 — until at least one real system is registered (S55), V2 default produces empty pages. Once we have real data, revisit.
3. **Toggle scope**: per-portal independent (toggle in gov is separate from toggle in portal) or unified via shared localStorage key? Recommendation: same key (`aigovern_data_mode`) — both portals share the same `.aigovern.sandboxhub.co` parent but localStorage IS per-origin, so they're naturally independent. Accept that — operator flips toggle once per portal they use.

## Target end-state (S52)

Every page in both portals can be flipped between demo-portfolio (V1) and live-customer (V2) view via a Topbar toggle. The engine filters server-side on `X-Data-Mode`. Registering a new system tags it `source: "real"` so it only appears in V2. V2 empty states surface contextual CTAs that route the user toward S53's SDK onboarding wizard. Demo data stays intact and untouched.

## Working rules in effect

- Global `~/.claude/CLAUDE.md` — full files only, type hints, validate environment startup, no hardcoding.
- Project [CLAUDE.md](../../CLAUDE.md) — read [ARCHITECTURE.md](../../ARCHITECTURE.md) first; scrubber→tracer ordering invariant (this session doesn't touch that path but the rule applies if any new logging is added).
- Compound rules through S50: all prior + nothing new this session. Re-emphasise: S46 #1 (slot-sticky settings if any new env var lands), S48 #1 (run smoke live before declaring done), S49 #5 (V2 empty states must still not blank the page on a refresh — `loading && !hasData` pattern holds).
- [[project-v1-to-v2-real-data-arc]] — the locked direction this session implements step 1 of.
