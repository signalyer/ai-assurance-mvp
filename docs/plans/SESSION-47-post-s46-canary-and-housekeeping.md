# SESSION-47 — Slot-swap canary verification + V1 deprecation observation start

**Status entering S47:** V2 LIVE undisturbed. S46 committed but not yet pushed via the new slot+swap CI path. Production sha `fe0b0050` (S44 closeout); first S47 push to main becomes the canary deploy through the new `staging → swap → production` path defined in [.github/workflows/deploy.yml](.github/workflows/deploy.yml).

**Theme:** S47 is a *verification + housekeeping* session. The slot infra and V1 deprecation runway are in place; this session proves they work end-to-end against the live App Service and tidies the small inconsistencies S46 surfaced.

## Locked decisions (carry from S46)

- Slot-swap CI path is the canonical deploy path going forward. Rollback = `az webapp deployment slot swap --slot production --target-slot staging`.
- V1 deprecation window: **2026-07-02** (60 days post-S45 cutover). Removal criterion: 7 consecutive days `v1_surface_hits_24h < 5`.
- Sticky settings on production: `V2_APEX_REDIRECT`, `PORTAL_URL`, `GOV_URL`, `APPLICATIONINSIGHTS_CONNECTION_STRING`. Any new feature-flag-style setting added in S47+ must be marked sticky at creation time (or via the read+reapply pattern in [[slot-sticky-settings]]).
- Compound rules in effect: 24a-d, 25a-b, 26a-b, 27a + polymorphic, 28a-c, 38a, S43 #1, S44 #1, S45 #1, S45 #2, **S46 #1** (`--slot-settings` requires `KEY=VALUE` reapply).

## STEP 1 — Canary push verification (~20 min)

The S46 commit is the first traffic through the new CI path. The workflow will: deploy zip → staging slot, poll staging `/api/health` for sha match, `az webapp deployment slot swap`, verify production sha post-swap. Watch each gate.

- Push S46 commit to `origin/main`. Observe GitHub Actions `deploy` workflow.
- **Gate 1** — `Wait for staging-slot SHA to match commit`: staging slot was `Running 503` at S46 close; this step proves the zip deploy populated it. Expect 30-90s on P2v3 warm restart.
- **Gate 2** — `Swap staging → production`: atomic. `az webapp deployment slot swap` should return in <30s.
- **Gate 3** — `Verify production SHA after swap`: production `/api/health` reports the new sha. If this fails, manual swap-back required (the failure message in `deploy.yml` includes the exact CLI).
- Post-success live verification:
  - `curl -I https://aigovern.sandboxhub.co/findings` → expect `X-V1-Surface-Deprecated: removal-date=2026-07-02`
  - `curl -s https://aigovern.sandboxhub.co/api/health | jq .v1_surface_hits_24h` → expect integer (≥1 after the curl above)
  - Browser visit to `https://aigovern.sandboxhub.co/findings` → expect yellow banner top-of-page, links to `portal.*` and `gov.*` clickable
  - V2 surfaces unchanged: `curl -I https://portal.aigovern.sandboxhub.co/` + `https://gov.aigovern.sandboxhub.co/` → both 200

**Acceptance:** CI green end-to-end; live curl confirms deprecation header + counter; banner renders; V2 LIVE unchanged. A15 closes on this gate.

**Failure path:** if Gate 2 or Gate 3 fails, the staging slot holds the previous code. Manual swap-back via the CLI in the workflow's error message. Production sha returns to `fe0b0050`. S47 then becomes a diagnostic session — do not attempt redeploy until the failure mode is understood.

## STEP 2 — V1 deprecation observation cadence (~10 min)

S46 wired the signal; S47 starts watching it.

- Establish a daily cadence to record `v1_surface_hits_24h` from `/api/health` for the deletion criterion (7 consecutive days < 5 hits/day). Decide cadence mechanism: (a) manual operator check, (b) Azure Monitor query against the Prometheus counter (`v1_surface_hits_total{route="..."}`), (c) lightweight cron via `mcp__scheduled-tasks` against a recording script.
- First reading goes into a new tracking section in [ARCHITECTURE.md](ARCHITECTURE.md): "V1 deprecation watch — daily counts." Date column + per-day count. Target: zero entries above 5 for 7 consecutive days → `static/*.html` deletion authorized.
- Open question: do we route V1 hits to an Application Insights custom metric for trend visibility? The cumulative Prometheus counter is already there (`v1_surface_hits_total`); App Insights surfacing is a 1-line change in `observability/counters.py` if `applicationinsights` is already in the SDK chain.

**Acceptance:** decision recorded on cadence mechanism; first reading captured; tracking section live in `ARCHITECTURE.md`.

## STEP 3 — `parameters.dev.json` housekeeping (~15 min)

S46 surfaced that [deploy/bicep/parameters.dev.json](deploy/bicep/parameters.dev.json) is incomplete relative to current `main.bicep`. Several parameters declared in the template have no value in `parameters.dev.json` and rely on Bicep defaults.

- Missing parameter values (currently default-driven):
  - `cisoConsoleLocation`, `cisoConsoleSwaName`, `cisoConsoleSwaSku` (S44 — was added to the template but not parameters.json)
  - `deployCisoConsole` (defaults to false; explicit value would document intent)
  - `deployAlerts` (S46 — new toggle, defaults false; explicit value documents the one-shot contract)
  - `deployStagingSlot` (S46 — new toggle, defaults false; explicit value documents intent)
  - `webAppName`, `webAppLocation`, `stagingSlotName` (S46 — should be explicit because they pin to existing infra)
- Decision: should `parameters.dev.json` be exhaustive (every param has a value) or minimal (only overrides)? Current state is accidentally-minimal. **Recommended: exhaustive** — explicit is auditable; defaults drift silently.
- Add a comment block at the top of `parameters.dev.json` clarifying the policy.

**Acceptance:** `az deployment group create --template-file ... --parameters @parameters.dev.json` works with zero `--parameters KEY=VALUE` overrides for the routine no-op redeploy. Toggles (`deployTeamPortal`, `deployCisoConsole`, `deployAlerts`, `deployStagingSlot`) explicitly set to `false`; flipping any to `true` is the single edit needed.

## STEP 4 — Garak ADR-001 decision (~30 min)

A9 / A11 (Garak adversarial scan) has been "locked-deferred" since S42. The deferral is now a year-old open loop. Two paths:

- **Accept**: spend 2 sessions implementing per [ARCHITECTURE.md §Garak Deep Scan](ARCHITECTURE.md) (Dockerfile + sidecar, bicep, domain bridge, API endpoint, SPA tab, integration test). Aligns with adversarial scan obligations under the V2 acceptance contract.
- **Close as out-of-scope**: explicit ADR ruling that Garak Deep Scan is replaced by the existing scenario suite + the new V1 deprecation surface monitoring + the (planned) Foundry batch evals. Document the substitution in ADR-001.

S47 STEP 4 is the *decision*, not the implementation. Implementation (if accept) is its own S48 / S49.

**Acceptance:** ADR-001 amended with accept/close decision + rationale. If accept: S48 plan scaffolded.

## Outstanding questions (need user input)

1. **Cadence mechanism for V1 deprecation watch** — manual / Azure Monitor query / scheduled-tasks cron? (STEP 2)
2. **`parameters.dev.json` policy** — exhaustive (recommended) or minimal? (STEP 3)
3. **Garak Deep Scan** — accept the 2-session implementation track, or close as out-of-scope via ADR-001 amendment? (STEP 4)

## Target end-state (S47)

A15 closed via successful canary push through slot+swap CI. V1 deprecation observation cadence live with first reading recorded. `parameters.dev.json` exhaustive. Garak path decided (and either scaffolded or closed via ADR).

## Working rules in effect

- Global `~/.claude/CLAUDE.md` — SignalLayerDev, `$env:MSYS_NO_PATHCONV = "1"`, `/compact` at ~60%
- Project [CLAUDE.md](CLAUDE.md) — read [ARCHITECTURE.md](ARCHITECTURE.md) first, full files only, scrubber→tracer order, JSONL via storage.py only
- Compound rules: 24a-d, 25a-b, 26a-b, 27a + polymorphic, 28a-c, 38a, S43 #1, S44 #1, S45 #1, S45 #2, S46 #1
