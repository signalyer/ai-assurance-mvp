# Session 22 — Plan (draft)

**Status:** draft — pick one track at session start
**Branch:** main (direct commits, ≤3-file changes per session)

## Candidate tracks (pick one)

### Track A — deploy.yml path filter (15 min, low risk)
Carry-over flagged but not actioned in Session 21. Every push to main
(including docs / plan / README changes) triggers a ~3 min App Service
redeploy. Session 21 itself triggered two unnecessary deploys (commits
`1231cd4` and `7c86b8d` — both contained workflow + doc changes that
required deploy validation, but the pattern will continue with pure-doc
commits).

**Change:** add `paths-ignore` to `.github/workflows/deploy.yml`:
```yaml
on:
  push:
    branches: [main]
    paths-ignore:
      - 'docs/**'
      - '**.md'
      - '.github/workflows/contract-tests*.yml'  # don't redeploy on CI-only changes
  workflow_dispatch:  # always allow manual trigger
```

**Risk:** a code change bundled with a doc change in the same commit
still triggers deploy (path filters are OR across files in the commit),
so no risk of "code change skipped deploy."

**Done criteria:** push a doc-only commit, confirm no deploy run fires.

### Track B — Garak integration (multi-session, design needed first)
Plan still says "needs design work, not just CI hygiene." Session 22
could be the design session: pick an integration shape (subprocess vs
library import vs HTTP), decide where Garak probes live relative to the
existing `adversarial.py` probe registry, decide whether they share the
SSE stream or get their own endpoint.

**Pre-work:** read the Garak docs, look at `adversarial.py`'s current
probe registry shape, draft an ADR-style decision doc.

### Track C — rate-limit retry layer for adversarial probes
Session 20 noted this; not blocking until we raise `_PROBE_CONCURRENCY`
above 5. If the user has feedback from real adversarial runs showing
429s under load, this becomes worth doing. Otherwise defer.

## Working rules in effect (carried)

- Project CLAUDE.md: read every file before editing; full files only
- Session 19a-d: OIDC, az-CLI workaround, whitelist drift, SHA round-trip
- Session 20a-b: sync-generator-with-thread-pool; readiness gate polls
  for SHA match, not 200
- **Session 21a:** `os.environ.setdefault()` in build/export scripts is
  nondeterminism waiting to happen — force-set the contract
- **Session 21b:** Prefer workflow-scope env flag over action-version
  bumps for runtime deprecations (Node 20→24 model)

## Deadlines on the horizon

- **2026-06-02 (9 days)** — GitHub forces JS actions to Node 24.
  We're already opted in via `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24` so
  the flip is a no-op for us. Watch the deploy run on that date anyway.
