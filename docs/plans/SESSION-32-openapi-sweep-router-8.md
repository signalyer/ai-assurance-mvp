# SESSION-32 — Track A OpenAPI sweep, router #8

## Default target
`api/agent_bindings.py` (4 routes, 3 already typed — finish the one
remaining untyped route; precedent: S31 adversarial pattern).

Alternatives (small): `api/frameworks.py` (4/3), `api/projection.py` (3/1).
Defer `api/guide.py` (9 routes, high SPA coupling).

## State of the sweep (post-S31)
- **Total routers with routes:** 36
- **Fully typed:** 19 (some by pre-S25 typing audit, e.g. `findings_v2.py`
  per SESSION-13 §3.1, `runtime_v2.py`, `grc.py`, etc.)
- **Partially typed:** 5 (`agent_bindings.py`, `frameworks.py`,
  `projection.py`, `analytics.py`, `reports.py`) — 11 untyped routes
- **Fully untyped:** 12 — 32 untyped routes
- **Remaining work:** 17 routers, ~43 routes

The "6/25 routers" counter from S30 and earlier was tracking this
initiative's sweep count, not total coverage. ARCHITECTURE.md S31
entry has the corrected matrix.

## Why agent_bindings.py
- Smallest delta: 1 untyped route to finish
- Pattern locked: 3 sibling routes in same file are the template
- Continues the "finish partials first" strategy — converts another
  half-done entry to fully-typed
- Low blast radius: bindings are internal API, not SPA-critical

## Workflow (locked Sessions 25-31)
1. **Project CLAUDE.md ritual.** State decorator chain + most-recent
   "in progress" files.
2. **Verify deploy SHA.** `curl -s https://aigovern.sandboxhub.co/api/health`
   should report S31's code SHA (`api/adversarial.py` commit). Watch
   for the 28a regression: doc-only commit with file deletes may
   have re-deployed S30 SHA — confirm.
3. **UI-consumer grep.** `Grep -r "/api/agent-?bindings" static/ team-portal/`
   (note: route prefix is `/api/agent_bindings` — confirm in file).
4. **Read `api/agent_bindings.py` end-to-end** + identify which route
   is missing `response_model=`. The 3 typed siblings are the
   pattern.
5. **Draft Pydantic v2 model** for the untyped route. Strict-by-default
   per compound 27a; `list[dict]` only for genuinely asymmetric shapes.
6. **Wire `response_model=` + `operation_id="agent_bindings_<verb>"`.**
   Match the verb convention used by the 3 sibling typed routes —
   don't introduce a new naming pattern in the same file.
7. **Regenerate spec.** `python scripts/export_openapi.py`
8. **Inspect diff.** Should be small (≤10 lines): one new schema +
   one operationId rename if the existing 3 routes already have
   stable operation_ids; otherwise stamp those too.
9. **Smoke.** `python -c "import api.agent_bindings"` + `import dashboard`.
10. **Close.** ARCHITECTURE.md Session 32 entry + bump matrix (20/36
    typed, 16 remaining) + replace this plan with SESSION-33.
    Two-commit pattern (code + docs).

## Three-file budget
- `api/agent_bindings.py`
- `docs/openapi-v1.json`
- `ARCHITECTURE.md`

Plus this plan file (docs-only commit). If consumer grep surfaces UI
files that would break under a strict model, fall back to `list[dict]`
for that route — do **not** spillover into UI changes.

## Open items carried from prior sessions
- **Compound rule 28a regression (S31 finding).** Doc-only commit
  `b796494` deployed despite all-`.md` files. Suspected GHA quirk
  around file delete+add in same push. Needs reproduction in a
  dedicated session before rule is patched. Until then: doc-only
  commits that **only modify** are safe; doc-only commits with
  file moves should expect deploy to fire.
- **Track C cookie-domain manual verify** (carried since S22):
  load https://aigovern.sandboxhub.co/login → DevTools → Cookies →
  confirm `session` has `Domain=.aigovern.sandboxhub.co` → logout
  → confirm removed.
- **ADR-001 Garak sidecar** Accepted, unscheduled (ADR §7 steps 1-6).
- **Hidden contract trap** `storage.py:101` `calculate_analytics()`
  empty-vs-populated asymmetry (8 vs 10 keys). One-line comment
  worth adding — STRETCH ONLY, do not break the 3-file budget.

## Working rules in effect
- Project CLAUDE.md: read every file before editing; full files only;
  scrubber before tracer; policy fail-closed; ≤3-file change rule;
  end-of-session = /verify + ARCHITECTURE.md + next plan + commit.
- Global ~/.claude/CLAUDE.md: Azure SignalLayerDev,
  `MSYS_NO_PATHCONV=1`, /compact at ~65%.
- Compound rules 19a-d, 20a-b, 21a-b, 22a-b, 23a-b, 24a-b, 25a-b,
  26a-b, 27a, 28a — all in ARCHITECTURE.md. (28a has known regression
  on delete+add commits — see open items.)
- Direct-to-main; two-commit pattern (code + docs).
- Local `import dashboard` logs `openapi.drift.production_warn` —
  EXPECTED, not a defect (compound 25b).
- **SSE/streaming routes (S31 lesson):** `operation_id=` only;
  `response_model=` cannot apply; document the intentional gap
  in the file docstring.
- Revert any `data/*.jsonl` pollution before commit (S28 lesson).

## Pattern reminders for the strict-vs-list[dict] decision
- **Evidence pattern (S29):** deterministic upstream (dataclass or
  stable Pydantic) + consumer reads many fields + single-record
  fetch → **strict mirror** wins.
- **Connectors pattern (S28):** domain-payload lists at the API
  boundary → **`list[dict]`** wins.
- **Analytics pattern (S27):** genuinely asymmetric shape (empty vs
  populated history) → `ConfigDict(extra="allow")` with Optional
  fields on asymmetric keys.
- **Domains pattern (S30):** stored JSON files with bounded legacy
  drift → strict mirror with `ConfigDict(extra="allow")`. Single-
  record gets strict; list endpoint where consumers iterate and
  read few fields stays `list[dict]`.
- **Adversarial pattern (S31):** SSE/streaming routes — `operation_id`
  only, no `response_model`. Document in file docstring.

Pick per route based on what each consumer actually reads.
