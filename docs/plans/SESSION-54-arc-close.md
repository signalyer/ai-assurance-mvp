# SESSION-54 — V1→V2 arc close

**Status entering S54:** S53 closed live (engine `0af6162`, both SPAs serving the onboarding wizard + V2 empty-state CTAs, smoke 8/8 PASS). The V1→V2 arc was locked at S50 as 4 sessions; S52 + S53 are in. This session closes the remaining carryovers so the arc is formally done and the platform contract is stable enough to take an enterprise POC.

**Theme:** Defensive cleanup, not new surface. Five small carryovers that would each trip a customer on their first real-mode demo. Time-box to one session; if any item needs >2 hours, defer to S55 and document why.

## Locked carryovers (from [[project-v1-to-v2-real-data-arc]] + S53 known-open)

### STEP 1 — release-gates engine honors X-Data-Mode (~45 min)

**Symptom:** CISO Console `/release-gates` in V2 mode shows all 5 seed systems because [api/release_gates.py](../../api/release_gates.py) doesn't apply the `filter_by_mode` helper. The SPA's S53 V2 empty-state copy is wired but never triggers.

**Fix:** Apply `filter_by_mode(rows, get_data_mode(request))` in the release-gates list endpoint, matching the [api/sdk_keys.py](../../api/sdk_keys.py) pattern. The underlying engine in [domain/release_gate_engine.py](../../domain/release_gate_engine.py) already propagates `data_source` through `evaluate_system_gates`; only the HTTP layer needs the filter.

**Acceptance:** With `localStorage.aigovern_data_mode = 'v2'` set, `GET /api/v1/release-gates/v2/systems` returns `{systems: []}` until a real-mode system is registered. CISO Console SPA's V2 empty state ("Gates compute once an AI system has been registered…") renders.

**Touched:** `api/release_gates.py` (1 endpoint), `tests/test_release_gates_v2.py` (1 new test asserting V2 filtering).

### STEP 2 — SDK accepts `key_id=` kwarg (~30 min)

**Symptom:** The S53 onboarding wizard's generated snippet passes `key_id=os.environ["SL_KEY_ID"]` to `signallayer.init()`, but [sdk/signallayer/__init__.py](../../sdk/signallayer/__init__.py) doesn't accept it. Works on the env-var fallback path; would fail in any future stricter-init scenario.

**Fix:** Add `key_id: str | None = None` to `init()` signature. Plumb through to the client constructor so `X-SL-Key-Id` header uses the explicit value over `os.environ["SL_KEY_ID"]`. Backward-compatible — None default = env-var lookup (existing behavior).

**Acceptance:** `python -c "import signallayer; signallayer.init(key_id='slk_test', api_key='x', base_url='y'); print('OK')"` works without env vars set.

**Touched:** `sdk/signallayer/__init__.py`, `sdk/signallayer/client.py`, 2 new tests in `tests/test_sdk_client.py`.

### STEP 3 — Smoke verification with 1Password creds (~30 min)

**Symptom:** Probes 5 / 7 / 8 SKIP without `$env:SMOKE_DEMO_PASSWORD_{CISO,ENGINEER}`. S52 + S53 both shipped without non-spurious assertion of these probes.

**Fix:** Run `op signin` locally; populate both env vars; re-run smoke against prod. Probe 7 should show `(v1=N, v2=0)` — confirming the live engine filters V2 to empty (since no real systems registered yet). Probe 8 should issue + status + revoke a real key against prod.

**Acceptance:** Both smoke scripts pass 8/8 with **no SKIP** lines. Record the actual key created in Probe 8 in `data/sdk_keys.jsonl` on prod and note the `key_id` in this plan file for cleanup audit.

**Touched:** No code. Just verification.

**Executed 2026-05-26 (S54):** Both `smoke_gov.ps1` and `smoke_portal.ps1` ran 8/8 PASS, zero SKIPs, against `https://gov.aigovern.sandboxhub.co` + `https://portal.aigovern.sandboxhub.co` + `https://aigovern.sandboxhub.co` (engine). Probe 8 audit:
- gov-side key:    `slk_52ddb2ab` — issued → status polled → revoked
- portal-side key: `slk_b25264b4` — issued → status polled → revoked

Demo passwords rotated to fresh 24-char urlsafe values (bcrypt rounds=12); new hashes deployed to `app-aigovern-dev` via `az webapp config appsettings set` and verified live with form-encoded POST to `/api/auth/login` (200 for both demo-ciso and demo-engineer). Plaintexts saved to user's 1Password vault.

### STEP 4 — CI deploy reliability decision (~30 min)

**Symptom:** `azure/login@v2` archive download has been flaky across S52 + S53. Last CI run (S53 push, `86f7978`) was in_progress at session close; need to confirm whether it succeeded or hit the same failure mode.

**Fix path 1 (preferred):** If S53 push's CI run completed green, declare the issue transient and document; no code change.

**Fix path 2 (if still broken):** Pin `azure/login` to a specific SHA in [.github/workflows/deploy.yml](../../.github/workflows/deploy.yml) rather than `@v2`. Test by running `gh workflow run deploy.yml --ref main`.

**Acceptance:** Last 3 CI runs all green, or workflow file commits SHA-pinned with a green run on the new pin.

**Touched:** Possibly `.github/workflows/deploy.yml` (1 SHA pin).

**Executed 2026-05-26 (S54):** Declared **transient**. Last run on `main` (S53 / `86f7978`) is green. The two prior failures (`5e52998`, `0af6162`) share an identical root cause at the **GitHub Actions runner layer**, BEFORE any workflow code executes:

> `##[error]An action could not be found at the URI 'https://codeload.github.com/Azure/login/tar.gz/a457da9ea143d694b1b9c7c869ebb04ebe844ef5' (F028:5135E:...)`
> `##[error]Failed to download archive ... after 1 attempts.`

The runner already SHA-resolves `azure/login@v2` internally (the SHA `a457da9…` is visible in the failure URL). Adding a SHA pin in `deploy.yml` would change the resolved SHA but not the CDN serving the archive — `codeload.github.com` is the same regardless of how the version is expressed. **Pinning is not a real mitigation for this failure mode.**

Real mitigation options if it recurs: (a) auto-retry the failed run, (b) wrap setup with `nick-fields/retry`, (c) self-host a runner. (a) is the right call for a pre-POC platform. The S54 STEP 6 push will be the 4th data point — if it's also green, we have 2 consecutive greens after the flaky window and can close this out.

### STEP 5 — Intake-mode decision: 5-step vs 6-field (~20 min, deciding only)

**Symptom:** The locked V1→V2 plan from S50 specified "minimal 6-field intake" but S52 + S53 kept the existing 5-step / 30+ field wizard from [team-portal/src/pages/ai-systems/RegisterSystemPage.tsx](../../team-portal/src/pages/ai-systems/RegisterSystemPage.tsx). Need to decide whether to ship the simplified intake now (in S54 STEP 5 work) or accept the 5-step wizard as the V2 intake permanently and update the locked plan.

**Recommendation (open this in session):** Keep the 5-step wizard as V2 intake. The "minimal 6-field" goal was a Phase-2 simplification target; in practice the risk-classification rules need most of the 30+ fields to fire correctly, and the live risk panel is one of the strongest demo affordances. Update `memory/project_v1_to_v2_real_data_arc.md` to drop the 6-field claim. **Defer implementation; document the decision.**

**Acceptance:** A `DECISIONS.md` entry recording the choice; the memory file updated.

**Touched:** `DECISIONS.md`, `memory/project_v1_to_v2_real_data_arc.md`.

## STEP 6 — Arc close (~30 min)

- ARCHITECTURE.md: add a short "V1→V2 arc closed" section declaring S52-S54 the full set and S53's "4-session arc" plan delivered.
- Update [memory/project_v1_to_v2_real_data_arc.md](../../memory/project_v1_to_v2_real_data_arc.md) — mark arc complete; remove "session arc" planning notes; keep only the architectural invariants (data_source field, V1/V2 filter rule, scrubber-before-trace, etc.).
- Smoke 8/8 GREEN with no SKIPs documented.
- Deploy (engine zip via manual fallback if CI still failing; SPAs only if STEP 1 changes the response shape — which it shouldn't).

## Out of scope (defer to S55+)

- POC retrospective — runs after the Architect POC ships P10
- Any new SPA pages
- Any new release gates beyond what's in the engine today
- Any P0 hardening work (S56-S60 territory)

## Total time-box

5 hours active engineering work. If any single STEP exceeds 2 hours, stop and escalate the decision to a separate planning conversation; don't sink the session.

## Acceptance at S54 close

- Smoke 8/8 GREEN with non-spurious probe 5/7/8 assertions
- CI deploys reliably (3 consecutive greens) OR action SHA pinned with documented rationale
- Release Gates V2 empty-state visible in CISO Console
- SDK `key_id=` kwarg accepted
- Decision logged on intake-mode question
- ARCHITECTURE.md declares V1→V2 arc closed
- One commit, one push, one CI green
