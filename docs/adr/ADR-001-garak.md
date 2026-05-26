# ADR-001 — Garak integration shape

- **Status:** Accepted (Session 24, 2026-05-24). Originally Proposed in Session 23. Reconfirmed and scheduled in Session 48 (2026-05-26) — implementation lands in S50 (sidecar + Bicep) and S51 (UI + bridge + integration test). Closing-as-out-of-scope was the explicit alternative considered in S48 STEP 4 and rejected: adversarial breadth is a load-bearing assurance pillar for the demo narrative and post-demo customer conversations.
- **Deciders:** Praveen Kosuri
- **Supersedes:** none
- **Related:** Session 18 (`api/adversarial.py` SSE), Session 20 (`adversarial.py` parallelization), Session 12 (deploy-zip slim-down rule)
- **Context anchors:** [adversarial.py](../../adversarial.py), [api/adversarial.py](../../api/adversarial.py), [deploy/build-zip.py:53](../../deploy/build-zip.py)

---

## 1. Context

The platform ships a lightweight self-contained adversarial probe suite
(`adversarial.py`, 13 probes across 5 categories, ~10–15s wall clock under
`ThreadPoolExecutor(max_workers=5)`). It is the demonstrable security layer
for stakeholder demos and the live `/adversarial` Team Workspace surface.

[Garak](https://github.com/leondz/garak) (now NVIDIA / `garak-ai`) is the
de-facto open-source LLM red-teaming framework: ~150+ probes, real
detectors (not heuristics), generators for every major provider, structured
report output. Three things we *want* from Garak that our in-house suite
cannot credibly deliver:

1. **Breadth.** 150+ probes vs. 13. Stakeholders ask "what about probe X?"
   for X ∈ {`encoding`, `goodside`, `lmrc`, `malwaregen`, `xss`, ...}.
2. **Detector quality.** Garak's detectors are model-based or
   signature-based, not regex heuristics. Our `_check_response_safety()`
   has known false-positive shape (Session 12B fixed `llama_guard_adapter`
   substring bugs; the same class of weakness lives in `adversarial.py`).
3. **Reproducibility.** Garak emits structured `.report.jsonl` traceable to
   probe IDs with stable hashes. Auditors can independently reproduce a run.

Three things we want to **keep**:

1. **Slim deploy.** `requirements-deploy.txt` is ~30 MB total. Garak's
   transitive deps (`torch`, `transformers`, optional `nemoguardrails`) are
   ~1.5 GB. `deploy/build-zip.py:53` already documents this exclusion as
   intentional. Session 12 spent a full day debugging the consequences of
   shipping heavy ML libs through App Service / Oryx.
2. **SSE responsiveness.** The Session 18c contract — sync generator drained
   via `asyncio.to_thread(next, gen, sentinel)` — is now the canonical
   long-running-probe pattern. Switching it forces a rewrite of the SPA
   consumer at `team-portal/src/pages/adversarial/AdversarialPage.tsx`.
3. **Fault isolation.** A Garak probe crash must not crash the dashboard
   process. Today this is implicit (in-process probes are simple); with a
   150-probe framework it becomes load-bearing.

## 2. Decision drivers

| Driver                                         | Weight |
|------------------------------------------------|--------|
| Slim deploy invariant (Session 12 / 19c rule)  | HARD CONSTRAINT |
| Preserve SSE pattern (Session 18c)             | High   |
| Fault isolation                                | High   |
| Operational simplicity (one process to mind)   | Medium |
| Probe-definition reuse with `adversarial.py`   | Medium |
| Avoid spawning subprocesses on App Service B1  | Medium |
| Reproducibility / report provenance            | High   |

## 3. Options considered

### Option A — Library import (`import garak`)

In-process: `pip install garak` into the deploy zip, call `garak.cli.main()`
or its programmatic API directly from `adversarial.py`.

| | |
|---|---|
| **Pros** | Single process, no IPC. Direct access to Garak's report objects. Easiest for ad-hoc probe composition. |
| **Cons** | **Violates the HARD CONSTRAINT.** Adds ~1.5 GB of transitive deps to the App Service container. First-touch Oryx rebuild would re-litigate Session 12's outage. Garak's programmatic API is less stable than its CLI (the maintainers explicitly recommend CLI for reproducibility). No fault isolation — a probe segfault in torch crashes the dashboard worker. |
| **Verdict** | **Rejected.** The slim-deploy rule was paid for in production downtime and cannot be unwound for this. If we ever lift it, we lift it deliberately, not as a side effect of an integration choice. |

### Option B — Subprocess (`garak --report-prefix ...`)

Out-of-process: Garak installed on a *different* machine/container.
Dashboard process spawns Garak via subprocess and streams its stdout line
by line. Garak writes its `.report.jsonl`; we tail it and translate.

| | |
|---|---|
| **Pros** | Heavy deps stay out of the dashboard zip. CLI is Garak's supported, versioned interface. Stdout streaming maps directly onto the Session 18c sync-generator → SSE drain pattern (one line in, one event out). Fault isolation: Garak crash returns non-zero exit, dashboard continues. Garak's `--report-prefix` gives us a stable artifact to attach to evidence. |
| **Cons** | Need a place to install Garak. On App Service B1 Linux, `subprocess.Popen("garak ...")` is technically possible (the container has Python + apt) but pulling 1.5 GB of deps into the app container defeats the point. Realistically requires either: (a) a sidecar container, (b) a separate Container App, or (c) a dedicated worker VM. Each adds operational surface. Process spawn overhead per run (~1–2 s, negligible vs. 10–60s probe wall clock). |
| **Verdict** | **Strong candidate.** Preserves every hard constraint. The "where does Garak live?" sub-decision is real but tractable. |

### Option C — HTTP (Garak as a remote service)

Out-of-process and out-of-host: Garak runs as a long-lived HTTP service
(self-built FastAPI wrapper around Garak's library API, or a community
wrapper). Dashboard POSTs a run request, receives an SSE stream back, or
polls a job ID.

| | |
|---|---|
| **Pros** | Cleanest separation. Garak service can be scaled / GPU-scheduled independently. Same shape as `Anthropic` / `OpenAI` providers already wired through `providers/`. Multi-tenant story (Session 11 V2) becomes trivial: shared Garak service, per-tenant auth. |
| **Cons** | We have to build and operate that service ourselves — Garak does not ship a stable HTTP server. That is an entire second deliverable (auth, rate limit, lifecycle). HTTP→SSE→SSE proxying is two streaming layers to debug instead of one. Until V2 multi-tenancy actually arrives, the extra capability is unused. |
| **Verdict** | **Right answer for V2; wrong answer for V1.5.** Defer. |

## 4. Decision

**Adopt Option B (subprocess).** Specifically:

1. **Where Garak lives:** a dedicated **Azure Container App** sidecar named
   `ca-aigovern-garak-dev` in the existing `cae-aigovern-dev` environment.
   *Not* a process inside `app-aigovern-dev` (preserves slim-deploy);
   *not* a separate VM (no idle cost when Container Apps scales to zero).
   The container ships from a new `deploy/garak/Dockerfile` based on
   `python:3.12-slim` + `pip install garak`. Image size ~2 GB but it never
   touches the dashboard's deploy path.

2. **Invocation shape:** the dashboard process invokes the Container App
   over HTTPS to a thin exec endpoint that itself does
   `subprocess.Popen(["garak", "--model_type", ..., "--probes", ...,
   "--report-prefix", "/tmp/run-{uuid}", "--narrow_output"])` and streams
   the resulting `report.jsonl` lines back as SSE.

   This is *Option B at the Garak host* and *Option C between dashboard and
   Garak host*. The dashboard-side code looks like an HTTP SSE client; the
   subprocess invariant is preserved where it matters (fault isolation,
   slim deploy).

3. **Where it sits relative to `adversarial.py`:** **additive, not
   replacement.** The existing 13-probe in-house suite stays exactly as is.
   Rationale:
   - Demo predictability — the in-house suite runs in ~10s with known
     outcomes; Garak runs can take minutes and outcomes drift with
     model/provider updates.
   - Cost — Garak probes burn 10× the API tokens of our heuristic suite.
   - Offline mode — `adversarial.py` runs without any external service;
     Garak requires the sidecar to be reachable.

   The two surfaces are presented as **tiers**:
   - `adversarial.py` → "Quick Smoke" (always available, ~10s)
   - Garak sidecar → "Deep Scan" (opt-in, 1–10 min, structured report)

4. **SSE stream sharing:** **new endpoint, same pattern.** Add
   `POST /api/adversarial/deep-scan` returning `text/event-stream`, mirroring
   the existing `/api/adversarial/run` contract. Event names align:
   `start` / `probe` / `done` / `error`. The SPA gets a new tab in
   `AdversarialPage.tsx` ("Deep Scan") that reuses the existing manual
   SSE-frame parser.

   Reusing `/api/adversarial/run` was tempting (one endpoint, mode flag) but
   rejected: the request shapes diverge (Garak takes probe-IDs, not
   categories), the auth surface differs (Garak run cost-gated; quick smoke
   is not), and OpenAPI documents are clearer when each endpoint has one
   purpose.

5. **Probe-ID schema bridge:** introduce `domain/garak_bridge.py` that
   translates Garak `module.probename` IDs to our internal
   `{category, probe_name, severity}` shape so the UI table renders both
   suites uniformly. Severity comes from a YAML override map at
   `frameworks/garak_severity.yaml` — Garak does not natively encode
   severity, only detection.

## 5. Consequences

### Positive
- Slim deploy invariant intact. Dashboard zip size unchanged.
- Session 18c SSE pattern unchanged at the dashboard layer.
- Garak version bumps are isolated to the sidecar image — no dashboard
  redeploy required for probe-set updates.
- Provides a credible answer to "how do you red-team this?" for buyers who
  ask the second-order question.
- Pre-positions for V2 multi-tenancy: same sidecar serves multiple
  dashboard tenants.

### Negative
- New Azure resource to provision (`ca-aigovern-garak-dev`) and a new
  Container Apps environment cost line — though scale-to-zero keeps the
  idle cost ~$0.
- New `deploy/garak/Dockerfile` to maintain. Garak releases are frequent
  (~monthly); a CI job pinning + bumping the image is a follow-up.
- A second SSE consumer in the SPA — minor code dup with the existing
  parser. Tolerable; abstract only if a third arrives.
- Subprocess-spawn-from-HTTP-handler inside the Container App is a small
  trust boundary. We control the request shape, but we audit `--probes`
  against a whitelist server-side — never pass through raw user input.

### Neutral / open
- Authentication between dashboard and sidecar: defer to HMAC reusing the
  Session 09 `middleware/hmac_auth.py` pattern. Documented as a follow-up.
- Cost: each Garak deep-scan run hits the LLM provider directly from the
  sidecar (its own `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`). Means a separate
  budget meter and a separate Langfuse project — TBD.

## 6. Rejected for now (revisit triggers)

- **Option A (library import):** revisit only if the slim-deploy
  constraint is lifted for a different reason (e.g., we move dashboard to
  Container Apps with a 4 GB image budget).
- **Option C (direct HTTP, no subprocess underneath):** revisit when V2
  multi-tenancy ships. At that point, building a real Garak HTTP service
  becomes worth the operating cost.

## 7. Implementation plan (NOT in this session)

A future session, gated on this ADR being accepted:

1. `deploy/garak/Dockerfile` + `deploy/garak/server.py` (FastAPI, SSE,
   subprocess wrapper, `--probes` whitelist).
2. Container App provision in `deploy/bicep/garak.bicep`.
3. `domain/garak_bridge.py` + `frameworks/garak_severity.yaml`.
4. `api/adversarial.py::deep_scan` endpoint, reusing
   `_stream_suite` / `_format_sse` helpers.
5. `team-portal/src/pages/adversarial/AdversarialPage.tsx` tab split.
6. Integration test: end-to-end SSE from dashboard → sidecar → mocked
   Garak CLI returning a canned report.

Estimated: 2 sessions (one for sidecar + bicep, one for UI + bridge).

---

## Appendix — what we explicitly do NOT do

- We do **not** vendor Garak's probe definitions into our repo. The whole
  point of using Garak is its maintained catalog; copying it forks our
  fate from upstream.
- We do **not** translate Garak's detector output into our heuristic
  `resisted` boolean by reimplementing detection logic. We surface
  Garak's `passed` / `failed` field directly and label the source as
  "Garak detector" in the UI.
- We do **not** add a `garak` requirement to `requirements.txt` or
  `requirements-deploy.txt`. Confirmed by `deploy/build-zip.py:53`
  comment; reinforced here so a future session doesn't quietly re-add it.
