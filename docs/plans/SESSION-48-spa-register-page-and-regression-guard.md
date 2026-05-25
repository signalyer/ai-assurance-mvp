# SESSION-48 — Register-new-system port + subroute regression smoke + S47 housekeeping carryover

**Status entering S48:** V2 LIVE and fully functional. Three production fixes from S47 (`1d95422`, `d6f9a8d`, `02f9f95`) all on prod. `demo-engineer` / `demo-ciso` login verified end-to-end. The one user-visible feature gap is the **Register-new-AI-system flow** — V2 button links to a route that doesn't exist; the V1 5-step wizard is still reachable at `static/ai-systems-new.html` as a workaround.

**Theme:** Close the one user-facing functional gap left from S47, prevent the regression class that hid the day-0 SPA outage, and finally land the non-blocking S47 housekeeping items (`parameters.dev.json`, Garak ADR-001).

## Locked decisions (carry from S47)

- Slot-swap CI is canonical for engine deploys. SPA deploys remain manual `swa deploy` (Free SKU; no GitHub Actions for SPAs).
- SPA `VITE_API_BASE_URL=https://aigovern.sandboxhub.co/api/v1` baked at build time. `.env.production` files checked in (public values only).
- SPA `client.ts` uses `credentials: 'include'`. Engine CORS allows portal.* and gov.* with `allow_credentials=True`, OPTIONS preflight handled outermost-of-stack.
- Engine auth model is **demo-role username/password** (7 roles). Entra integration with engine remains deferred — see [[entra-engine-bridge]] (future ADR).
- V1 deprecation watch is **manual daily curl** (S47 STEP 2 cadence). Streak tracking lives in ARCHITECTURE.md table; removal date hard-stop 2026-07-02.
- Compound rules in effect: 24a-d, 25a-b, 26a-b, 27a + polymorphic, 28a-c, 38a, S43 #1, S44 #1, S45 #1, S45 #2, S46 #1, **S47 #1** (SPA smokes must probe a subroute), **S47 #2** ([[bash-cwd-persistence]] — multi-target deploys use absolute paths).

## STEP 1 — Register-new-AI-system: pick A/B/C and execute (~30 min to 4 hrs depending on choice)

V1 had a 5-step intake wizard at `static/ai-systems-new.html` (451 lines vanilla JS) calling `POST /api/grc/intake/preview` + `POST /api/grc/intake/submit`. Both APIs still live on engine (`api/intake.py`, returns 401 anonymous = working). V2 SPA has the "Register System" button (`team-portal/src/pages/ai-systems/AiSystemsPage.tsx:120`) pointing at `/ai-systems/new` but no wouter route registered. Three options:

- **Option A — Full port to V2** (`RegisterSystemPage.tsx` + wouter route + 5-step wizard in Preact). 2-4 hours; closes the gap properly. Likely needs its own session.
- **Option B — Minimal modal on `/ai-systems`** (3 fields: name + autonomy + data class; calls `/api/grc/intake/submit` with V1 defaults for omitted fields). 30-60 min; loses risk classification depth. *Probably a trap* — half-built register pages tend to become permanent.
- **Option C — Interim deep-link to V1** (change `<a href="/ai-systems/new">` to absolute V1 URL; carve `static/ai-systems-new.html` out of the 2026-07-02 deletion until A lands). 5 min + ARCHITECTURE.md note. Full UX preserved; contradicts V1 deprecation messaging slightly.

**Recommended path:** C as interim (this session), A scheduled for S49 once UX wireframes are confirmed.

**Acceptance:** "Register System" button leads to a working flow (V1 wizard via deep-link, OR V2 modal/page). User can submit a new AI system end-to-end and see it appear in the `/ai-systems` list.

## STEP 2 — Subroute regression smoke (~30 min)

S47 incident root cause was that `smoke_portal.ps1` / `smoke_gov.ps1` only probed `/`, hiding the missing `staticwebapp.config.json` since V2 first shipped. Compound rule S47 #1 codified: SPA smokes must probe a subroute. Extend both scripts:

- `smoke_portal.ps1`: probe `/` (existing) + `/findings` (or `/ai-systems`) returns 200 with HTML body containing the SPA shell marker. Plus an authenticated API probe: login as `demo-engineer` → `curl /api/v1/grc/ai-systems` with cookie → expect 200 with non-empty JSON array (or empty array, not 401).
- `smoke_gov.ps1`: same pattern with `/findings` (gov landing) + login as `demo-ciso` → `curl /api/v1/grc/policies` → expect 200.

Both scripts must accept credentials via env (`SMOKE_DEMO_PASSWORD_CISO`, `SMOKE_DEMO_PASSWORD_ENGINEER`) — never hardcoded. CLAUDE.md global rule.

**Acceptance:** running `pwsh deploy/smoke_portal.ps1` with the env vars set prints 5 probes (HTML root, HTML subroute, login, authed JSON, logout) all PASS. Same for gov.

## STEP 3 — `parameters.dev.json` housekeeping (~15 min) — carried from S47

S46 surfaced that [deploy/bicep/parameters.dev.json](../../deploy/bicep/parameters.dev.json) is incomplete relative to current `main.bicep`. Several parameters declared in the template have no value in `parameters.dev.json` and rely on Bicep defaults. **Recommended: exhaustive** — explicit is auditable; defaults drift silently.

Missing parameter values to set explicitly:
- `cisoConsoleLocation`, `cisoConsoleSwaName`, `cisoConsoleSwaSku`
- `deployCisoConsole`, `deployAlerts`, `deployStagingSlot` (toggles; document intent explicitly)
- `webAppName`, `webAppLocation`, `stagingSlotName`

**Acceptance:** `az deployment group create --template-file ... --parameters @parameters.dev.json` works with zero `--parameters KEY=VALUE` overrides for the routine no-op redeploy. Toggles explicitly `false`; flipping any to `true` is the single edit needed.

## STEP 4 — Garak ADR-001 decision (~30 min) — carried from S47

A9 / A11 (Garak adversarial scan) has been "locked-deferred" since S42. Two paths: **Accept** (2 sessions per [ARCHITECTURE.md §Garak Deep Scan](../../ARCHITECTURE.md): Dockerfile + sidecar, Bicep, domain bridge, API endpoint, SPA tab, integration test) or **Close as out-of-scope** (ADR-001 amended; substitution = existing scenario suite + V1 deprecation monitoring + planned Foundry batch evals).

S48 STEP 4 is the *decision*. Implementation (if accept) is S50 / S51.

**Acceptance:** ADR-001 amended with accept/close decision + rationale.

## Outstanding questions (need user input)

1. **Register page** — A, B, or C? Recommended C as interim, A next.
2. **Subroute smoke credentials** — store the new demo passwords in 1Password and reference via env, or rotate them per session and reset before each CI run?
3. **`parameters.dev.json` policy** — exhaustive (recommended) vs minimal?
4. **Garak ADR-001** — accept the implementation track, or close as out-of-scope?

## Target end-state (S48)

Register-new-system flow works (interim or permanent). SPA subroute regressions prevented by extended smoke. `parameters.dev.json` exhaustive. Garak path decided. V1 deprecation streak continues per S47 STEP 2 manual cadence.

## Working rules in effect

- Global `~/.claude/CLAUDE.md` — SignalLayerDev, `$env:MSYS_NO_PATHCONV = "1"`, `/compact` at ~60%, absolute paths in multi-target deploys
- Project [CLAUDE.md](../../CLAUDE.md) — read [ARCHITECTURE.md](../../ARCHITECTURE.md) first, full files only, scrubber→tracer order, JSONL via storage.py only
- Compound rules: 24a-d, 25a-b, 26a-b, 27a + polymorphic, 28a-c, 38a, S43 #1, S44 #1, S45 #1, S45 #2, S46 #1, S47 #1, S47 #2
