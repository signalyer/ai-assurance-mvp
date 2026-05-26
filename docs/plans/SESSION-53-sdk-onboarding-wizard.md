# SESSION-53 — SDK onboarding wizard + first-signal page

**Status entering S53:** S52 closed live (engine `bc4db1c`, both SPAs serving the DataModeToggle bundle, both smoke scripts 7/7 PASS). The V1/V2 toggle is the unblock for this session: real customer systems registered via S53's wizard land with `data_source="real"` and only appear when an operator flips to V2 mode. Demo data stays untouched in V1.

**Theme:** Close the loop between "I just registered an AI system in V2 mode" and "I see telemetry from it." Today, [RegisterSystemPage.tsx](../../team-portal/src/pages/register/RegisterSystemPage.tsx) (S52 verified) creates an AI system with `data_source="real"` but the user is dropped onto `/ai-systems` with no obvious next step. S53 makes the next step explicit: issue an SDK API key tied to the new system, show the copy-pasteable decorator-chain snippet, and stand up a "waiting for first signal" page that polls the engine until traces start arriving.

The SignalLayer SDK (`sdk/signallayer/`, built S09) is the load-bearing primitive. The HMAC middleware ([middleware/hmac_auth.py](../../middleware/hmac_auth.py), S09) already authenticates SDK calls against `/api/sdk/*` — what's missing is the per-system key issuance UI and the "first signal" landing page after registration.

## Locked decisions (carry from [[project-v1-to-v2-real-data-arc]])

- **No new SDK transport.** HMAC-SHA-256 over `/api/sdk/*` per S09 stays as-is.
- **Per-system API keys, not per-tenant.** Each registered AI system gets its own `SL_KEY_ID` + `SL_HMAC_SECRET` pair so revocation is granular.
- **Secret shown once.** Display the HMAC secret only at issuance time; store only a SHA-256 hash server-side. Re-display = "issue a new key" workflow (revokes the old one).
- **First-signal probe is engine-side, not SPA-side.** A new `GET /api/sdk/keys/{key_id}/status` returns `{first_seen_at: null}` until the SDK has produced a trace, then returns the trace timestamp. SPA polls every 2-3s.

## STEP 1 — engine: SDK key model + issuance + status (~75 min)

- New [domain/sdk_keys.py](../../domain/sdk_keys.py): Pydantic v2 `SdkKey { id, key_id, hmac_secret_sha256, ai_system_id, data_source, issued_by, issued_at, revoked_at, first_seen_at }`. Persist to JSONL via the storage.py pattern; never log the plaintext secret.
- New [api/sdk_keys.py](../../api/sdk_keys.py) — 4 endpoints under `/api/sdk-keys` (NOT `/api/sdk/*` which is HMAC-gated):
  - `POST /api/sdk-keys` — body `{ai_system_id}`. Generates `key_id` (slug) + `hmac_secret` (32-byte url-safe random). Returns secret ONCE in response body; stores sha256 only.
  - `GET /api/sdk-keys?ai_system_id=...` — list keys for a system (no secrets in response — only id, key_id, issued_at, first_seen_at, revoked_at).
  - `POST /api/sdk-keys/{key_id}/revoke` — marks revoked_at; subsequent SDK calls fail HMAC.
  - `GET /api/sdk-keys/{key_id}/status` — returns `{first_seen_at, total_calls_24h}`. Polled by the first-signal page.
- Wire HMAC middleware to look up `key_id` → `hmac_secret_sha256` instead of the single `SL_HMAC_SECRET` env var. Backward-compatible: env var stays as the fallback for the demo apps.
- On first successful HMAC-authed call from a key, the middleware sets `first_seen_at` on the key record (idempotent on subsequent calls).
- All routes data-mode-aware: the issuance endpoint stamps the key with the parent system's `data_source` (intake-created systems are `"real"`, demo system keys are `"seed"`).
- Engine tests: `tests/test_sdk_keys.py` — issue, list, revoke, status, HMAC roundtrip with a real key, first-seen idempotency.

**Acceptance:** Local `curl -X POST .../api/sdk-keys -d '{"ai_system_id":"sys-xyz"}'` returns key + secret. A subsequent `sl trace tail` invocation using those creds returns 200 (was 401 before issuance). `GET .../api/sdk-keys/{key_id}/status` flips `first_seen_at` from null to a timestamp.

## STEP 2 — Team Portal SPA: onboarding wizard (~60 min)

- New [team-portal/src/pages/onboarding/OnboardingPage.tsx](../../team-portal/src/pages/onboarding/OnboardingPage.tsx): 3-step wizard, route `/onboarding/:system_id`:
  1. **Issue key.** Auto-fires `POST /api/sdk-keys` on mount; show the secret in a copy-once-then-hidden field with a "Show secret" toggle that requires explicit click + audit log entry.
  2. **Install snippet.** Mirror `sdk/README.md` quickstart. Inject the system's `id`, the just-issued `key_id`, and the engine base URL. "Copy" button per code block. Same template as the existing [SdkQuickstartPage.tsx](../../team-portal/src/pages/sdk-quickstart/SdkQuickstartPage.tsx) (S17 #2) but pre-configured for one specific system.
  3. **Verify.** Mounts `<FirstSignalPanel />` (see STEP 3) and disables the "Done" button until `first_seen_at` is set.
- Modify [RegisterSystemPage.tsx](../../team-portal/src/pages/register/RegisterSystemPage.tsx): on submit success, redirect to `/onboarding/{ai_system_id}` instead of `/ai-systems`.
- Wire the route + sidebar item (only visible when there's an active onboarding session — gate on a URL-param presence; don't surface in the main nav as a top-level link).

## STEP 3 — first-signal page (~30 min)

- New [team-portal/src/pages/onboarding/FirstSignalPanel.tsx](../../team-portal/src/pages/onboarding/FirstSignalPanel.tsx): polls `GET /api/sdk-keys/{key_id}/status` every 2500ms via `setInterval` with cleanup on unmount. Three visual states:
  - **Waiting** (default): spinner + "Waiting for first SDK call... usually arrives within 30 seconds of `import signallayer; sl.init()`." Auto-shows after 30s a troubleshooting checklist (verify ANTHROPIC_API_KEY, SL_API_BASE_URL, decorator order).
  - **First signal arrived**: green check + timestamp + "Trace appeared at HH:MM:SS." Inline link to the matching `/traces` page filtered by system.
  - **Stalled** (60s no signal): amber warning + "Still no signal. Common issues: ..." with a "Re-run setup" button that goes back to STEP 2.
- Acceptance: with the local demo `examples/billing_agent.py` running against the new key, the panel flips from waiting → first-signal in under 5s.

## STEP 4 — V2 empty-state CTA wiring (~30 min, folded from S52 leftover)

Catch up on the S52 STEP 2 sub-task that was deferred. The toggle + filter are live; what's missing is the contextual copy when an operator flips to V2 and sees an empty list.

- Pages to touch (all use the same empty-state pattern):
  - Team Portal [AiSystemsPage.tsx](../../team-portal/src/pages/ai-systems/AiSystemsPage.tsx) → "No live AI systems registered. [Register your first system →]" → `/register`
  - CISO Console [FindingsPage.tsx](../../ciso-console/src/pages/findings/FindingsPage.tsx) → "No live findings yet. Findings appear automatically when an SDK-instrumented system produces a policy denial, guardrail violation, or eval regression. [Learn how to instrument →]" → `/sdk-quickstart`
  - CISO Console [ReleaseGatesPage.tsx](../../ciso-console/src/pages/release-gates/ReleaseGatesPage.tsx) → "Gates compute once an AI system has been registered and baselined. [Register →]"
  - Team Portal [PortfolioPage.tsx](../../team-portal/src/pages/portfolio/PortfolioPage.tsx) → same as AI Systems.
- Gate the V2-specific copy via the existing module-level `dataMode` signal — fall back to the existing generic empty state in V1 mode.

## STEP 5 — smoke + ARCHITECTURE.md + deploy (~30 min)

- New smoke probe 8 in both `smoke_gov.ps1` / `smoke_portal.ps1`: `POST /api/sdk-keys` (with auth), assert key returned + secret has length > 32; then `GET /api/sdk-keys/{key_id}/status` returns 200 with `first_seen_at: null`. Then `POST /api/sdk-keys/{key_id}/revoke` and verify status code 200.
- ARCHITECTURE.md: new Session 53 section.
- Deploy: engine zip + both SPA bundles. Try CI first (GH Actions may have recovered); fall back to manual `build-zip.py` + `deploy-and-poll.ps1` + `swa deploy` if not.
- Live smoke 8/8 against prod.

## Working rules

- Global `~/.claude/CLAUDE.md` — full files only, type hints, no hardcoding.
- Project [CLAUDE.md](../../CLAUDE.md) — read [ARCHITECTURE.md](../../ARCHITECTURE.md) first; scrubber→tracer ordering (any new logging in STEP 1 must respect it).
- Compound rules through S52: all prior, plus **S52 #1** (grep for field name collisions before any cross-cutting field add), **S52 #2** (smoke defaults pinned to canonical hosts now), **S52 #3** (swa deploy CWD sensitivity — invoke from each SPA dir), **S52 #4** (don't poll GH Actions if it's 500 — fall back to manual deploy).
- Memory: [[project-v1-to-v2-real-data-arc]] is the locked direction; this session is item 2 of 4.

## Outstanding questions (decide at session open)

1. **API key storage** — JSONL alongside existing entities, or move keys-only to Postgres for atomic revocation? Recommendation: JSONL for now (matches everything else); revisit when revocation latency matters.
2. **First-signal probe shape** — long-poll vs short-poll? Recommendation: short-poll 2.5s (simpler, matches Memory/Agent SSE patterns in S07; long-poll adds plumbing for ~5s win that doesn't matter for the manual onboarding flow).
3. **Should the "Show secret" toggle audit each unhide?** Recommendation: yes — emit a `SDK_KEY_SECRET_REVEALED` event to the audit chain. The secret is only displayed once at issuance, but if the user navigates away mid-flow and comes back, they shouldn't be able to silently re-view it; a fresh key issuance is required.

## Target end-state (S53)

Registering a new AI system in V2 mode now drops the user into a 3-step wizard that ends with a verified first SDK call. CISO Console and Team Portal both surface contextual CTAs in V2 mode that route operators toward the onboarding flow. The SDK quickstart page from S17 #2 becomes the secondary entry point (for adding the SDK to a system that was created before S53 shipped).
