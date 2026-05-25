# SESSION-31 — Track A OpenAPI sweep, router #7

## Default target
`api/findings_v2.py` (5 routes, medium SPA coupling).
Alternatives: `api/runtime_v2.py`, `api/release_gates.py`.
Defer `api/guide.py` (9, high SPA coupling).

## Why findings_v2.py
Sweep progress is 6/25 routers (29/66 routes). Session 30 closed
`api/domains_api.py` with 6 live consumers — the highest coupling
sweep so far, all wire-compatible. `findings_v2.py` is the next rung:
5 routes; consumer surface limited to `static/findings.html` (one
file). Should be tractable inside the 3-file budget; precedent for
strict mirror is high since findings are deterministic
(`domain/findings_workflow.py` Pydantic models).

### Consumer surface (preliminary — re-verify at S31 start)
- `static/findings.html` — single live consumer per S30 grep
- `team-portal/` — none detected (Findings locked to CISO Console
  per V2-PORTAL-SPLIT.md §3 Decision Log)

Re-run before any edit:
```
Grep -r "/api/findings|/api/grc/findings" static/ team-portal/
```

Likely decision per route (confirm at read time):
- **List + filter endpoints** — strict mirror likely fits if Finding
  models are stable upstream (precedent: evidence pattern S29).
- **Mutation endpoints** (accept/dismiss/triage) — strict envelope
  pattern (like S30 `DomainDeleteResponse`).
- Watch for any list endpoint where the consumer reads few fields
  AND upstream shape varies → fall back to `list[dict]` per compound 27a.

## Workflow (locked Sessions 25-30)
1. **Project CLAUDE.md ritual.** State decorator chain + 3 most-recent
   "in progress" files (expect None per S25 cleanup).
2. **Verify deploy SHA.** `curl -s https://aigovern.sandboxhub.co/api/health`
   should report S30's code SHA. Doc-only commits no longer deploy
   (compound 28a empirically held S30 prep).
3. **UI-consumer re-grep.** Re-verify the consumer surface above.
4. **Read `api/findings_v2.py` + `static/findings.html` end-to-end**
   before drafting models. Trace each consumer fetch → which fields
   it reads → strict-vs-`list[dict]` per route.
5. **Read `domain/findings_workflow.py`** — confirm upstream Finding
   shape is a stable Pydantic model (precondition for strict mirror).
6. **Draft Pydantic v2 response models.** Strict-by-default per
   compound rule 27a; `list[dict]` only for genuinely asymmetric
   shapes (compound 27a's asymmetric case).
7. **Wire `response_model=` + `operation_id="findings_<resource>_<verb>"`.**
   Verb convention: HTTP-ish (`_get`, `_update`) for REST verbs;
   semantic (`_accept`, `_dismiss`, `_list`) where POST semantics
   dominate. Note: `findings_*` collides with no existing prefix in
   the spec — safe.
8. **Modernize Pydantic v2 boundary calls** if any `config.dict()`
   slipped through (S30 found one in domains_api).
9. **Regenerate spec.** `SL_OPENAPI_EXPORT_PROFILE=ci python scripts/export_openapi.py`
10. **Inspect diff.** New schemas + new operationIds only. No removed
    routes, no shape changes to prior schemas.
11. **Smoke.** `python -c "import api.findings_v2"` + TestClient
    against `dashboard.app` for each route — confirm 200 + shape
    matches model.
12. **Close.** ARCHITECTURE.md Session 31 entry + bump sweep progress
    to 7/25 (34/66 routes) + this plan file replaced by SESSION-32.
    Two-commit pattern (code + docs).

## Three-file budget
- `api/findings_v2.py`
- `docs/openapi-v1.json`
- `ARCHITECTURE.md`

If consumer grep surfaces UI files that would break under strict
models, fall back to `list[dict]` for that route — do **not**
spillover into UI changes. This sweep stays non-breaking.

## Open items carried from Session 30
- **Track C manual login verification** still open: load
  https://aigovern.sandboxhub.co/login → DevTools → Cookies →
  confirm `session` has `Domain=.aigovern.sandboxhub.co` → logout
  → confirm removed. Rollback: `az webapp config appsettings delete
  --name app-aigovern-dev --resource-group rg-aigovern-dev
  --setting-names SESSION_COOKIE_DOMAIN`.
- **ADR-001 Garak sidecar** Accepted, unscheduled (ADR §7 steps 1-6).
- **Hidden contract trap** `storage.py:101` `calculate_analytics()`
  empty-vs-populated asymmetry (8 vs 10 keys). One-line comment
  worth adding — STRETCH ONLY, do not break the 3-file budget for it.

## Working rules in effect
- Project CLAUDE.md: read every file before editing; full files only;
  scrubber before tracer; policy fail-closed; ≤3-file change rule;
  end-of-session = /verify + ARCHITECTURE.md + next plan + commit.
- Global ~/.claude/CLAUDE.md: Azure SignalLayerDev,
  `MSYS_NO_PATHCONV=1`, /compact at ~65%.
- Compound rules 19a-d, 20a-b, 21a-b, 22a-b, 23a-b, 24a-b, 25a-b,
  26a-b, 27a, 28a — all in ARCHITECTURE.md.
- Direct-to-main; two-commit pattern (code + docs); compound 28a
  (paths-ignore now correct) keeps doc commits from redeploying.
- Local `import dashboard` logs `openapi.drift.production_warn` —
  EXPECTED, not a defect (compound 25b).
- Revert any `data/*.jsonl` pollution before commit (S28 lesson).

## Pattern reminders for the strict-vs-list[dict] decision
- **Evidence pattern (S29):** every shape upstream is deterministic
  (dataclass or stable Pydantic model) + the consumer reads many
  fields + single-record fetch → **strict mirror** wins.
- **Connectors pattern (S28):** domain-payload lists at the API
  boundary → **`list[dict]`** wins, because binding to full domain
  Pydantic models re-validates on response and couples this router's
  OpenAPI surface to every domain schema bump.
- **Analytics pattern (S27):** genuinely asymmetric shape (empty
  vs populated history) → `ConfigDict(extra="allow")` with Optional
  fields on the asymmetric keys.
- **Domains pattern (S30):** stored JSON files with bounded legacy
  drift → strict mirror with `ConfigDict(extra="allow")`. Single-
  record gets the strict mirror; list endpoint where consumers iterate
  and read few fields stays `list[dict]`.

Pick per route based on what each consumer actually reads.
