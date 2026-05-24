# Session 20 — `adversarial.py` tech debt cleanup

**Status:** ready
**Branch:** main (direct commits, per Session 18+ convention for ≤3-file changes)
**Estimated scope:** 1 file, ~50-80 LoC delta, no UI changes

## Why this session

Both items violate active memory rules and are pre-existing carry-over flagged
in Session 18's risk register. Now that auto-deploy works (Session 19), any
regression is caught in ~90s via SHA round-trip — safe time to refactor.

## Confirmed issues (verified 2026-05-24)

1. **Top-level heavy imports** (`adversarial.py` lines 11-12):
   ```python
   from anthropic import Anthropic
   from openai import OpenAI
   ```
   Violates memory rule [#4 "Top-level imports of optional heavy libs break the app"](feedback-appservice-deploy-python.md). Both SDKs are already in `requirements-deploy.txt` so this doesn't currently crash startup — but it (a) inflates cold-start time, (b) couples adversarial test code to LLM SDK presence even when `/api/adversarial/categories` (zero LLM use) is hit, (c) breaks the "lazy import optional deps" pattern used everywhere else in the codebase (cf. `tracer.py`, `scrubber.py`, `providers/backends/*`).

2. **Sequential probe loop** (`adversarial.py` line 370):
   ```python
   for i, (category, probe) in enumerate(flat_probes):
   ```
   Violates memory rule [batch LLM calls always](feedback-batch-llm-calls.md). Each probe is an independent LLM API call; running them serially makes the SSE stream artificially slow (10+ probes × ~3-5s each = 30-50s vs ~5-8s parallel).

## Tasks

1. **Lazy-import `Anthropic` and `OpenAI`** inside the function(s) that actually instantiate clients. Wrap in `try/except ImportError` returning a clear error to the SSE stream. Verify `/api/adversarial/categories` no longer transitively imports either SDK.

2. **Parallelize the probe loop** using `asyncio.gather` with a semaphore (concurrency cap of ~5 to avoid rate-limit storms on Anthropic/OpenAI). The SSE generator wrapper (`asyncio.to_thread(next, gen, sentinel)` per Session 18c) still works — just yield results as `asyncio.as_completed` resolves them.
   - Preserve the existing `progress` SSE event shape so `team-portal/src/pages/adversarial/AdversarialPage.tsx` doesn't break.
   - Tests: `tests/test_adversarial*.py` if present; otherwise smoke-test via the SPA after deploy.

3. **Add `tests/test_adversarial_lazy_imports.py`** — AST-walk `adversarial.py` and assert no top-level `import anthropic` or `import openai`. Belt-and-suspenders so future contributors don't reintroduce the regression.

4. **Verify locally then push.** The Session 19 auto-deploy workflow runs SHA round-trip; if anything regresses, it fails closed within 90s.

## Out of scope

- The SSE protocol itself — Session 18c locked that pattern in, don't touch it.
- The probe categories / probe definitions — those are data, not code debt.
- Garak integration — separate concern, separate session.
- The OpenAPI drift validator firing under non-noop env (Session 19 finding) — track as Session 21+.

## Done criteria

- [ ] `grep -E "^(import|from) (anthropic|openai)" adversarial.py` returns nothing
- [ ] Adversarial run of 10 probes finishes in <15s wall clock (vs current ~30-50s)
- [ ] SHA round-trip passes after deploy
- [ ] `tests/test_adversarial_lazy_imports.py` passes
- [ ] ARCHITECTURE.md gets a Session 20 entry
