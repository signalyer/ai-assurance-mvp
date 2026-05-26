# SESSION-51 — Garak deep-scan: sidecar + Bicep (Phase 1 of 2)

**Status entering S51:** S50 closed end-to-end. Both portals now render their own /login page with the "Sign in with Microsoft" CTA. ALLOW_DEMO_AUTH=true on both prod + staging slots — bcrypt path still live for the demo window. Engine prod sha unchanged (`2c69a13`). Garak deep-scan is the next substantive deliverable per ADR-001 §7; "adversarial breadth" was reconfirmed in S48 STEP 4 as load-bearing for the demo narrative.

**Theme:** Get a working Garak sidecar running in Azure (Container Apps), wired into Bicep, reachable from the engine — but NOT yet consumed by it. Phase 2 (S52) handles the engine bridge, API endpoint, UI tab split, and integration test. Split this way so a failed sidecar Bicep deploy doesn't block engine work, and so the sidecar can be smoke-tested in isolation before the engine starts depending on it.

## Locked decisions (from ADR-001)

- **Garak runs as a sidecar Container App** — not in-process with the engine. Garak's process model spawns probe subprocesses; embedding that in the App Service Python runtime is a stability hazard.
- **SSE for progress streaming** — same pattern as `api/adversarial.py` (S18) and `api/agent_notifications.py` (S07). FastAPI inside the sidecar, `text/event-stream` content type, sync-generator-drained-via-`asyncio.to_thread(next, gen, sentinel)` per the S18c compound rule.
- **`--probes` whitelist enforced in the sidecar** — never pass user-controlled probe IDs straight to the Garak CLI. Server-side allowlist is the bottleneck.
- **No `garak` in `requirements.txt` / `requirements-deploy.txt`** — explicit per ADR-001 appendix. Garak lives only in the sidecar's Dockerfile. The engine's build-zip whitelist already excludes it.
- **Sidecar talks to the engine via plain HTTPS** — no HMAC SDK auth path for the engine→sidecar callback. The sidecar is in the same private network and only accepts authed engine calls; the engine is the only client.

## STEP 1 — `deploy/garak/Dockerfile` + sidecar server (~90 min)

New folder `deploy/garak/`:

- `Dockerfile` — Python 3.12 base, `pip install garak fastapi uvicorn`, copy `server.py`, `EXPOSE 8080`, `CMD ["uvicorn","server:app","--host","0.0.0.0","--port","8080"]`. No engine code in this image — the sidecar is self-contained.
- `server.py` — FastAPI app with three routes:
  - `GET /health` — returns `{"ok":true,"garak_version":"<x.y.z>"}` for health-probe wiring.
  - `GET /probes` — returns the static whitelist (top-level probe names, e.g. `dan`, `goodside`, `promptinject`, `realtoxicityprompts`).
  - `POST /scan` — body `{"probes":["dan"], "target":"<engine endpoint URL>"}`. Validates each probe against the whitelist (400 on any unknown). Spawns Garak CLI subprocess; streams `text/event-stream` events (`probe-start`, `probe-progress`, `probe-result`, `done`).
- `requirements.txt` (sidecar-local) — `garak`, `fastapi`, `uvicorn[standard]`. Intentionally separate from the engine's requirements files.
- `.dockerignore` — excludes everything except `Dockerfile`, `server.py`, `requirements.txt`.

**Acceptance:** `docker build -t garak-sidecar deploy/garak/` succeeds locally; `docker run -p 8080:8080 garak-sidecar` boots; `curl localhost:8080/health` returns `{"ok":true,...}`; `curl -X POST localhost:8080/scan -d '{"probes":["fakeprobe"],...}'` returns 400.

## STEP 2 — `deploy/bicep/garak.bicep` + ACR push + Container App (~60 min)

New `deploy/bicep/garak.bicep`. Provisions:
- Azure Container Registry (ACR) `cragaigovern` (or reuses if exists) — Basic SKU.
- Container Apps Environment `cae-garak-aigovern-dev` if not already there.
- Container App `ca-garak-aigovern-dev` — single-replica, no public ingress (internal-only), env vars: `ALLOWED_PROBES` (comma-separated whitelist), `LOG_LEVEL`. Image pulled from `cragaigovern.azurecr.io/garak-sidecar:latest`.

`deploy/garak/push-image.ps1` — docker build → tag → `az acr login` → docker push. Idempotent. Outputs the image's `:sha256:` digest.

**Acceptance:** `az deployment group create --template-file deploy/bicep/garak.bicep --resource-group rg-aigovern-dev` succeeds; Container App reaches `Running` state; `az containerapp logs show` reveals uvicorn startup; `/health` reachable from the engine's outbound IP via the Container Apps internal DNS.

## STEP 3 — engine-side env vars + secret (no code change yet) (~20 min)

Add two App Service settings (both slots, per S46 #1):
- `GARAK_SIDECAR_URL=https://ca-garak-aigovern-dev.<env>.azurecontainerapps.io` — internal Container Apps URL.
- `GARAK_SIDECAR_API_KEY` — a long random token. Sidecar's `/scan` checks `Authorization: Bearer <token>`. Stored as Key Vault reference per S49 pattern (`kv-aigovern-sl-dev`).

No engine code consumes these yet — they're staged so S52 can land the bridge cleanly without a deploy gap.

**Acceptance:** `az webapp config appsettings list` shows both vars on both slots; sidecar `/scan` returns 401 when called without the bearer token.

## STEP 4 — smoke probe in `deploy/smoke_api.ps1` (~20 min)

Add Scenario 9: sidecar health probe.
- 9a: `GET ${GARAK_SIDECAR_URL}/health` returns 200 + `garak_version` field non-empty.
- 9b: `POST /scan` with `Authorization: Bearer ${GARAK_SIDECAR_API_KEY}` and a fast-running probe (e.g. `goodside` with 1 prompt) — assert SSE stream contains `probe-start` and `done` events.

Sidecar-side smoke; does NOT cross the engine boundary yet.

**Acceptance:** scenario 9 PASSES against prod; cold-start is acceptable (< 30s).

## STEP 5 — ARCHITECTURE.md + ADR-001 status (~10 min)

- ARCHITECTURE.md gets a "Session 51" section with the sidecar files + Bicep delta.
- ADR-001 §7 step list — strike steps 1+2 as ✓, leave 3-6 for S52.

## Outstanding questions

1. **ACR SKU**: Basic (existing) vs Standard? Basic is cheap (~$5/mo) but limits webhooks and replication. Default: Basic — we're single-region.
2. **Probe whitelist**: which probes to enable on day one? Default: `dan`, `goodside`, `promptinject`, `realtoxicityprompts`. Conservative — can expand in S52 once UI surfaces it.
3. **Image tagging**: `:latest` vs `:<git-sha>`? Default: `:latest` + immutable `:<sha>` push, deploy via `:latest` for now (one-image rolling deploy is fine for a sidecar).

## Target end-state (S51)

Garak sidecar is live in Container Apps, reachable from the engine, health-probed by smoke scripts, but not yet driven by the engine. S52 can land the engine bridge (`domain/garak_bridge.py`), the public API endpoint (`api/adversarial.py::deep_scan`), the UI tab split, and the integration test without any infrastructure dependencies blocking it.

## Working rules in effect

- Global `~/.claude/CLAUDE.md` — SignalLayerDev, absolute paths in deploys, `$env:MSYS_NO_PATHCONV=1` for any `az` invocation that path-mangles.
- Project [CLAUDE.md](../../CLAUDE.md) — read [ARCHITECTURE.md](../../ARCHITECTURE.md) first.
- [ADR-001](../adr/ADR-001-garak.md) is the contract for everything in this session, especially the appendix's "what we explicitly do NOT do".
- Compound rules through S50: all prior + nothing new this session. Re-emphasise: S18c (SSE sync-gen drain), S46 #1 (slot-sticky settings), S48 #1 (live-run smoke before done).
