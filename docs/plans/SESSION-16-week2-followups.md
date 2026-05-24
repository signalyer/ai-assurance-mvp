# SESSION 16 — Phase 2 Week 2 follow-ups (#14–#20)

Pickup point after Session 15 closed out the AI Systems surface.
Branch: `phase/14-team-workspace-scaffold`. No PR yet. No merge to main.

## What's already done (Session 15, 4 commits)

| Commit  | Tasks       | What shipped |
|---------|-------------|--------------|
| 719986d | #9 + #10    | AiSystemEditModal + AiSystemRevisionsPanel — POST /ai-systems/{id}/edit with tiered auto-apply vs approval routing; revision history with field-change drilldown. Drawer wires both buttons; pending-material banner inside drawer body. |
| 8cbbb57 | #11         | AiSystemFrameworksPanel — 2-stage load (matrix → per-framework drill). 8 framework cards with coverage bars; drill shows item-level coverage + control/finding/evidence counts. |
| 24f78e3 | #12         | AiSystemBoundAgentsPanel — bind/pin/unpin/accept-upgrade/unbind. Picker filters unbound agents. Also fixed domain/agents.py:get_agent() to consult _inmem_agents (matches the Session 12B list_agents fix). |
| 6ef1c6c | #13         | Client-side CSV export with RFC 4180 escaping + UTF-8 BOM. Honours filter set, count in button label. |

Drawer is fully wired. No disabled buttons remain on the AI Systems page or drawer.

## What's NOT done (7 tasks left)

All defined by disabled buttons / TODO markers in the existing pages. Engine
endpoints exist for each — these are wiring tasks, not net-new backend.

### Runtime page (3 tasks)
- **#14** SystemStates.tsx:45,48,49 — Pause / Monitoring / Resume buttons.
  Engine: see `api/runtime_v2.py` for state-transition endpoints.
- **#15** RuntimePage.tsx:125 — `+ Request Connector` modal.
  Confirm engine endpoint in `api/connectors.py`; otherwise scope as
  client-only request form posting to a TBD endpoint.
- **#16** RuntimePage.tsx:135 — runtime event → incident creation.
  Engine: `api/findings_v2.py` create finding.

### Evals page (1 task)
- **#17** SystemEvalCard.tsx:84 — disabled Run eval button.
  Engine: `api/evaluate.py` POST.

### Agent Library page (3 tasks)
- **#18** AgentModal.tsx:89 — `PublishTabStub` → real publish form.
  Engine: `POST /api/agents/{id}/publish` (already exists, Session 07).
- **#19** AgentModal.tsx:95 — SSE live-update indicator.
  Engine: `GET /api/agents/{id}/listen` (Session 07 SSE endpoint).
- **#20** AgentLibraryPage.tsx:61 — `+ Create Agent` button.
  Engine: `POST /api/agents`.

## Established patterns (mirror these for new panels)

- **Signal-driven open/close**: `openX(id)` exported, sibling component reads
  module-level signal to decide whether to render. See AiSystemRevisionsPanel
  or AiSystemBoundAgentsPanel for the canonical shape.
- **Avoid circular imports**: when component B's save needs to refresh
  component A, use `registerXSavedCallback` indirection (see AiSystemEditModal
  + AiSystemDrawer). Don't try to import the loader directly.
- **API client**: always `apiGet/apiPost/apiRequest` from `shared/api/client.ts`
  — never raw fetch. ApiResult<T> discriminated union, branch on `r.ok`.
- **Engine errors to UI**: dev surfaces raw engine errors via `actionError`
  banner; don't add a translation layer.
- **Mount panels on the page**: each panel component is rendered once as a
  sibling of the main content. See AiSystemsPage.tsx final JSX block.

## Infrastructure already in place

- Dashboard: `python -m uvicorn dashboard:app --host 127.0.0.1 --port 8000`.
  Launch.json runs with `SL_OPENAPI_STRICT=false` + noop backends so it boots
  without Postgres / Langfuse / DeepEval.
- Team-portal: `npm run dev --prefix team-portal` → :5174. Vite proxies
  `/api/v1/*` to `:8000`.
- Both servers should start cleanly via `mcp__Claude_Preview__preview_start`
  with names `dashboard` and `team-portal`.

## OpenAPI drift

`docs/openapi-v1.json` was regenerated this session
(`python scripts/export_openapi.py`) — drift was pre-existing, not caused
by Session 15 changes. No Python schema changes this session beyond the
`get_agent` body, which doesn't touch the OpenAPI surface.

## Suggested order for Session 16

1. **#17 (Evals Run)** — smallest scope, hits a single endpoint, no UI
   skeleton needed beyond replacing one button. Warm-up task.
2. **#14 + #15 + #16 (Runtime bundle)** — three tasks on one page. Bundle
   like #9+#10 so the file is touched once.
3. **#18 + #19 + #20 (Agent Library bundle)** — three tasks on one page.
   Same rationale.

That's 3 commits, mirroring the Session 15 cadence.

## After Session 16

The Week 2 backlog is fully closed. Then either:
- Path B: open Week 3 surfaces per V2-PORTAL-SPLIT.md §6 (8 more Team
  Workspace pages + CISO Console scaffold).
- Provision swa-aigovern-portal-dev (Bicep already opt-in from e0a3082)
  and ship the first deploy.
- Open the PR on phase/14-team-workspace-scaffold (user previously chose
  "accumulate more first").
