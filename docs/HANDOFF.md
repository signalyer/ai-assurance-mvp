# Handoff — Resume Prompt

**Last session ended:** 2026-05-20
**Repo state:** clean, in sync with `origin/main` at commit `4c2e152`
**GitHub:** https://github.com/signalyer/ai-assurance-mvp (private)
**Live:** https://aigovern.sandboxhub.co

---

## Paste this into the new session

```
# Resume — AI Assurance Platform + Eval Harness

## Where I am
Platform live at aigovern.sandboxhub.co (single tenant, P1V3 + Postgres B2ms).
Repo just pushed to signalyer/ai-assurance-mvp. Currently in planning phase
for the target architecture — no new code written yet this cycle.

## Decision made last session: PIVOT
Stop building a custom eval harness. Compose Langfuse Cloud + DeepEval +
Presidio + Azure Key Vault. The defensibility is in the layers AROUND these
tools (Org layer, PII pipeline governance, Four-tier memory, workflow
overlay) — not in rebuilding tracing/eval infrastructure.

Authoritative target architecture (more complete than the earlier inline
diagram):
  C:\Users\pravk\Downloads\aigovern_complete_target_architecture.svg
Six layers: Org · Control Plane · PII Scrubbing · Four-tier memory ·
Runtime (Langfuse + DeepEval) · LLM abstraction.

## CRITICAL — fix before next demo
tracer.py currently sends RAW prompts to Langfuse Cloud. PII is leaking.
~1 day fix: regex-only scrubber + patch tracer.py to scrub before Langfuse
call. Do this before any enterprise demo.

## Planning docs already in repo (read in this order)
- docs/ai-eval-harness-plan.md — north-star (now superseded)
- docs/ai-eval-harness-tier1-tier2-plan.md — 14-feature spec
- docs/ai-eval-harness-impl-plan.md — 12-week build (now superseded by pivot)
- docs/HANDOFF.md — this file

Need to write next: docs/platform-realignment-plan.md per the new SVG.

## Outstanding decisions / questions
1. Pick a build sequence:
   (a) PII pipeline → Memory → Org layer  [recommended; regulated-buyer-safe]
   (b) PII pipeline → Org layer → Memory  [faster governance story]
   (c) Memory → PII pipeline → Org layer  [risky; only if memory is the demo hook]

2. Memory layer sizing — ~21 days for Tier 2 (episodic JSONL) + Tier 3
   (Azure AI Search) + agent_memory.py + rag_engine.py + governance overlay.
   Tier 4 (procedural / domains.py) already built.

3. DeepEval suite correction: drop ContextualRecall/Precision from the
   must-have list, add Toxicity + Scrub score. Final 6: Hallucination,
   Relevancy, Faithfulness, Toxicity, PII leakage, Scrub score.

4. Whether to keep a separate evals.sandboxhub.co deployment or fold
   everything into aigovern.sandboxhub.co (leaning fold — one codebase,
   one auth, one deploy).

## Next concrete action (pick one)
(a) Patch tracer.py emergency scrubber — stops the live leak (1 day)
(b) Write docs/platform-realignment-plan.md mapped to the new SVG
(c) Sketch agent_memory.py + rag_engine.py module signatures in detail

## Working rules in effect
- Global: ~/.claude/CLAUDE.md (SignalLayer standards, Azure-first,
  /compact at 65%)
- Project memory: C:\Users\pravk\.claude\projects\C--ai-assurance-mvp\
  memory\MEMORY.md (batch LLM calls, App Service deploy gotchas)
- Compose-don't-build for eval: Langfuse + DeepEval + Presidio commodity
  layers; governance overlay is the wedge
- One repo, one deploy until ≥3 customers pressure multi-tenant
```

---

## Bonus context for the resumer (not needed in the resume prompt itself)

**What's built today:**
- 12 pages live (Command Center, AI Systems, Findings, Release Gates, Evidence, Runtime, Policies, Reports, Connectors, Assurance Providers, Framework SOP, Analytics, AWS Analyzer demo)
- Domain layer with portfolio, framework coverage, notifications, governance guide, assurance providers, usage analytics, AWS demo flow, AI System edit + revision history
- Demo data in JSONL stores (append-only)
- Deploy tooling: build-zip, smoke, bind-ssl, godaddy-dns, generate-creds
- Auth: 5 role-based demo accounts, 10-min sliding sessions

**What's in progress per the target SVG:**
- scrubber.py · deid_vault.py · @scrub_pii decorator
- api/rag.py · rag-governance.html
- Fix tracer.py raw prompt leak ← CRITICAL

**What's planned:**
- Memory: agent_memory.py · compress_episode · selective_recall · Tier 2 JSONL schema · rag_engine.py Azure AI Search
- Org layer: risk inventory · governance body · RACI · regulatory posture (ISO 42001 / EU AI Act)

**Always-on:**
- domains.py (Tier 4 procedural memory) · storage.py · middleware/auth.py · domain/models.py

**5 role-based demo accounts:** see `deploy/creds.txt` (gitignored, on disk only).

**Subscription:** SignalLayerDev
**Resource group:** rg-aigovern-dev
**App Service:** app-aigovern-dev (Linux Python 3.12)
