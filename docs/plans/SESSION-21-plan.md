# Session 21 — CI hygiene: Node 24 migration + OpenAPI drift gate

**Status:** ready
**Branch:** main (direct commits, ≤3-file changes per session)
**Estimated scope:** 3 files (`deploy.yml`, `contract-tests.yml`, `contract-tests-nightly.yml`), no app-code changes
**Urgency:** Item #1 has a hard deadline of **2026-06-02** (9 days from today, 2026-05-24)

## Why this session

Two carried items, both CI-only, both have a clear blast radius (workflow
files only — no Python, no SPA). Bundle them in one session.

## Confirmed issues (verified 2026-05-24)

1. **Node.js 20 actions deprecation** (surfaced today, run 26374145961):
   ```
   Node.js 20 actions are deprecated. The following actions are running on
   Node.js 20 and may not work as expected: actions/checkout@v4,
   actions/setup-python@v5, azure/login@v2. Actions will be forced to run
   with Node.js 24 by default starting June 2nd, 2026.
   ```
   Three workflows pin Node-20-runtime actions. After 2026-06-02 GitHub
   force-flips them to Node 24; we want to validate the flip on our schedule,
   not theirs. Two paths: bump action versions OR set
   `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24=true` at the workflow level. The
   env-var path is cheaper and reversible — pick that.

2. **OpenAPI drift validator under non-noop env** (Session 20 plan §"Out of scope"):
   `.github/workflows/contract-tests.yml:40` pins `SL_OPENAPI_STRICT: 'false'`
   so the local engine boot tolerates drift. Then line ~55 runs
   `scripts/export_openapi.py --check` to detect drift in the artifact.
   These two are inconsistent: we tolerate drift at boot but block at
   artifact-check. The non-noop env case (real backends wired) fires false
   positives because tracer/scrubber init-time side effects shift the
   exported schema in ways unrelated to the API contract. Need to either:
   (a) make the artifact check tolerate the same drift, or (b) freeze
   the env at export time so output is deterministic across env shapes.

   **Recommendation:** option (b). Export with a fixed env profile
   (`SL_OPENAPI_EXPORT_PROFILE=ci`) that pins the env vars
   contributing to schema mutation. Documented and reproducible.

## Tasks

1. **Bump all three workflows to Node 24 via env var** (5 min, reversible):
   ```yaml
   env:
     FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: 'true'
   ```
   at the workflow `jobs.<job>` level (NOT step level — env-var path needs
   workflow/job scope to affect the Node runtime). Apply to:
   - `.github/workflows/deploy.yml`
   - `.github/workflows/contract-tests.yml`
   - `.github/workflows/contract-tests-nightly.yml`

   Push a no-op commit (or piggyback on task #2) to validate the deploy
   workflow under Node 24 before the forced flip.

2. **Pin OpenAPI export env profile** (~30 min):
   - Add `SL_OPENAPI_EXPORT_PROFILE` env var support to
     `scripts/export_openapi.py` (default: `"ci"`).
   - When profile is `ci`, force a known env shape before importing the
     FastAPI app: scrubber disabled, tracer disabled, RAG backend = noop,
     adversarial categories untouched (they're pure data).
   - Run `python scripts/export_openapi.py` locally — capture the new
     canonical artifact. Diff against `docs/openapi-v1.json`. If diff is
     non-empty, that IS the drift to commit; if it's empty, the existing
     artifact is already canonical and we just locked in reproducibility.
   - Verify CI passes both with `SL_OPENAPI_STRICT=false` (boot tolerance)
     AND with the artifact `--check` step (now deterministic).

3. **Document the new env contract** in `ARCHITECTURE.md` Session 21 entry —
   what `SL_OPENAPI_EXPORT_PROFILE=ci` pins, and why local dev exports
   under a different profile (if at all) will drift from the artifact.

## Out of scope

- Garak integration (separate session — needs design work, not just CI hygiene)
- Bumping action versions individually (env-var flip covers it; leave
  pinned versions alone until something else forces an upgrade)
- Rate-limit retry layer for adversarial probes (Session 20 noted this;
  not blocking until we raise `_PROBE_CONCURRENCY` above 5)
- App Service B1 → P0v3 upgrade discussion (cold-start cooldown rule
  exists because we're on B1 — separate cost decision)

## Done criteria

- [ ] All three workflows declare `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: 'true'`
- [ ] Deploy workflow runs green at least once with Node 24 (SHA round-trip passes)
- [ ] `contract-tests.yml` passes BOTH the boot phase AND the
      `export_openapi.py --check` phase on PR + main
- [ ] `docs/openapi-v1.json` is reproducible: running
      `SL_OPENAPI_EXPORT_PROFILE=ci python scripts/export_openapi.py`
      twice produces byte-identical output
- [ ] ARCHITECTURE.md gets a Session 21 entry + any compound rules earned

## Pre-flight check

```bash
# 1. Confirm hard deadline still 2026-06-02
gh api /repos/signalyer/ai-assurance-mvp/actions/runs/26374145961 \
  --jq '.head_commit.timestamp'

# 2. Survey current action versions (sanity — confirm none have already
#    been bumped past Node-20 stage)
grep -n "uses:" .github/workflows/*.yml

# 3. Confirm export script exists at the expected path
ls scripts/export_openapi.py
```

## Working rules in effect (carried)

- Project CLAUDE.md: read every file before editing; full files only
- Session 19a-d: OIDC, az-CLI workaround, whitelist drift, SHA round-trip
- Session 20a-b: sync-generator-with-thread-pool; readiness gate polls
  for SHA match, not 200
