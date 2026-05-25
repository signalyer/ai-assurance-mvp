# SESSION-46 — Post-cutover cleanup + V1 deprecation runway

**Status entering S46:** V2 LIVE (S45 closed A12 + A13). All 16 V2 acceptance criteria green. No blockers.

**Theme:** S46 is the *consolidation* session. V2 is live, V1 still serves on toggle-off. The goal is to (a) close the small debts S45 deferred, (b) start the V1 deprecation clock with explicit observation criteria, and (c) optionally pick up A15 (P1v3 + staging slot) if there's session budget.

## Locked decisions (carry from S45)

- Env-var-flip pattern remains the canonical rollback mechanism (S25/S43/S44/S45). Do not redeploy to undo config-level changes.
- `V2_APEX_REDIRECT=true` stays live throughout S46. Rollback is a single `az webapp config appsettings set V2_APEX_REDIRECT=false` away.
- V1 `static/*.html` deletion is **out of scope for S46** — observation window first.
- Compound rules in effect: 24a-d, 25a-b, 26a-b, 27a + polymorphic, 28a-c, 38a, S43 #1, S44 #1, **S45 #1** (probe assertions from built artefacts), **S45 #2** (scope-immutable resources need deploy-or-skip toggles).

## STEP 1 — Delete smoke_e2e.ps1 wrapper (~5 min)

S44 introduced `smoke_e2e.ps1` as a thin wrapper around the three child smokes (`smoke_api.ps1` / `smoke_portal.ps1` / `smoke_gov.ps1`) for operator muscle-memory continuity through cutover. That window is now closed.

- Delete [deploy/smoke_e2e.ps1](deploy/smoke_e2e.ps1).
- Grep CI configs ([.github/workflows/*.yml](.github/workflows/)) for `smoke_e2e` references — replace with explicit invocations of the three children.
- Update [ARCHITECTURE.md](ARCHITECTURE.md) verify block (line ~1448) — replace `pwsh deploy/smoke_e2e.ps1` with the three explicit invocations.

**Acceptance:** `git grep smoke_e2e` returns zero matches.

## STEP 2 — main.bicep `deployAlerts` toggle (~15 min)

S45 #2 compound observation: `main.bicep` alerts module fails on redeploy with `Scope can not be updated` (Azure Monitor metric-alert scope is immutable after creation). Partial state is benign — sibling SWA modules deploy fine — but the failed-overall status creates operator confusion ("did the deploy work?").

- Add `param deployAlerts bool = false` to [deploy/bicep/main.bicep](deploy/bicep/main.bicep). Mirror the `deployTeamPortal` / `deployCisoConsole` toggle pattern exactly.
- Wrap `alertsModule` declaration in `if (deployAlerts)`.
- Document in [deploy/bicep/README.md](deploy/bicep/README.md): "alerts module is one-shot — set `deployAlerts=true` only on first provision or when explicitly modifying alert configs."

**Acceptance:** `az deployment group create` with default params on `rg-aigovern-dev` succeeds (no alerts step → no scope-update failure). Existing alerts continue to fire unchanged (they were never deleted).

## STEP 3 — V1 deprecation runway (~30 min)

Start the V1 deprecation clock. **Do not delete `static/*.html` yet.** S46 establishes the deprecation contract; deletion lands in a later session after the observation window.

- Add `X-V1-Surface-Deprecated` response header to every V1 navigation route in [dashboard.py](dashboard.py) (the `@app.get("/ai-systems")`, `/findings`, `/runtime`, etc. cluster around line 394). Header value: `removal-date=2026-08-01` (90 days post-S45). This is the deprecation contract — readable from browser devtools, greppable from server access logs.
- Add a deprecation banner to V1 pages — `static/shared.js` injects a top-of-page yellow bar: "This is the legacy V1 surface. The V2 surfaces are at portal.aigovern.sandboxhub.co and gov.aigovern.sandboxhub.co. V1 will be removed after 2026-08-01."
- Add `dashboard.py` access-log hook: each hit to a V1 route increments a counter in [observability/counters.py](observability/counters.py). Surface in `/api/health` as `v1_surface_hits_24h`. Observation criterion for V1 deletion: 7 consecutive days of `< 5 hits/day` (catches bookmarks/external links).

**Acceptance:** `curl -I https://aigovern.sandboxhub.co/findings` returns `X-V1-Surface-Deprecated: removal-date=2026-08-01`. `/api/health` exposes `v1_surface_hits_24h`. Manual browser load shows banner.

## STEP 4 — OPTIONAL: A15 P1v3 + staging slot (~60 min, only if STEPS 1-3 finish under 50%)

A15 is the last yellow item in V2 acceptance. Independent infra track — does not affect V2 LIVE.

- Upgrade [deploy/bicep/main.bicep](deploy/bicep/main.bicep) App Service Plan from current SKU to P1v3.
- Add a staging slot (`app-aigovern-dev/slots/staging`) for zero-downtime deploys (swap pattern).
- Wire `deploy.yml` to deploy to staging slot, smoke against staging URL, then `az webapp deployment slot swap` on green.

**Acceptance:** `az webapp deployment slot list` shows staging slot. `deploy.yml` deploys to staging by default; production swap is a deliberate operator action.

## Outstanding questions (need user input)

1. **V1 deprecation removal-date** — is 2026-08-01 (90 days) the right window, or do you want a different timeline? S46 STEP 3 hard-codes it; flag if 60 or 120 days fits stakeholder communication better.
2. **A15 priority** — pick up in S46 STEP 4, or defer to a dedicated S47 infra session?

## Target end-state (S46)

V1 deprecation runway started (banner + header + counter); `smoke_e2e.ps1` deleted; `main.bicep` clean redeploy path restored. V2 LIVE undisturbed throughout — all S46 work is additive or removal of dead scaffolding.

## Working rules in effect

- Global `~/.claude/CLAUDE.md` — SignalLayerDev, `$env:MSYS_NO_PATHCONV = "1"`, `/compact` at ~60%
- Project [CLAUDE.md](CLAUDE.md) — read [ARCHITECTURE.md](ARCHITECTURE.md) first, full files only, scrubber→tracer order, JSONL via storage.py only
- Compound rules: 24a-d, 25a-b, 26a-b, 27a + polymorphic, 28a-c, 38a, S43 #1, S44 #1, S45 #1, S45 #2
