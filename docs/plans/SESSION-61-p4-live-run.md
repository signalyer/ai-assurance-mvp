# SESSION 61 — P4 First Live Run + Rego Enforcement Verified

**Date:** 2026-05-27
**Branch:** main
**Predecessor:** S60 (P4 STEP 1+2 structural, F-024 + F-025 resolved)

---

## What shipped

1. **First live `--plan` run end-to-end.** Installed Azure SDK deps (`azure-mgmt-resource`, `azure-identity`) and ran the agent against SignalLayerDev. Sonnet 4.6, 2 turns, 1 tool call (`list_resource_groups`), full WAF synthesis. Run id `plan-7036dc14bb58`.

2. **Rego enforcement verified under the live decorator chain.** Both halves of the negative + positive test pass through `@signallayer.policy_gate(action="tool_invoke")` with the real `workload_id="azure-architect"` context. F-024's fix holds.

3. **Verify block hardened.** Added the rego negative+positive test to `ARCHITECTURE.md`'s `/verify` block so future sessions can't ship a regression silently. Directly applies the rule from `[[rego-files-were-decorative]]`.

4. **POC retrospective updated** with S61 live-run status + artifact pointers.

## Files touched

- `ARCHITECTURE.md` — added S61 rego enforcement block to `/verify`.
- `agents/azure-architect/POC-RETROSPECTIVE.md` — appended "S61 P4 STEP 1+2 LIVE · STATUS" section.
- `data/plans.jsonl` — 2 new rows (run `plan-7036dc14bb58`, turns 0 + 1). Runtime data, **not committed** per [[deploy-zip-overwrites-runtime-data]].
- `agents/azure-architect/eval/dataset.jsonl` — 1 new canonical row (synthesis). Runtime/eval data; commit decision below.

## Decisions locked

- **Cost-locked default stays Sonnet 4.6** for `--plan`. First live run confirmed Sonnet produced a credible WAF synthesis from RG-level inventory alone — Opus is not needed for this surface yet. `--deep` remains available.
- **Negative-test discipline:** any future policy-as-data system must replay the *exact* `(workload_id, action, tool_name)` triple the real caller produces. Calling `policy_gate` without workload context hits the unmapped-workload fallback (ALLOW) and proves nothing. Corollary added to `[[rego-files-were-decorative]]`.
- **Eval/dataset.jsonl IS committed.** Six rows now, including the first live run. Future sessions: re-evaluate if this grows large or accumulates PII (unlikely — output is WAF synthesis text only).
- **plans.jsonl is NOT committed.** Per-turn telemetry is runtime data, like traces.jsonl.

## Deviations

- None. S61 went STEP 1 of the S60 spillover queue (live run) and verified the new [[rego-files-were-decorative]] rule in CI form. STEP 4 (Mermaid synthesis + per-tool eval) remains deferred per the original S60 plan.
- Mid-session false alarm: first negative test reported FAIL because it had no `workload_id` (hit fallback ALLOW path). Diagnosed and corrected in <5 minutes. Not a real regression. Lesson captured in the locked decision above and in `POC-RETROSPECTIVE.md`.

## Open issues / carry-forward queue

1. **Add a 2nd read tool** — e.g. `list_resources_in_group`. Exercises multi-turn tool chaining (current loop only proved 1-turn dispatch). Add to `readonly_azure_tools` in `policies/azure-architect.rego` BEFORE writing the function ([[rego-files-were-decorative]]).
2. **STEP 4 spillover from S60:** Mermaid synthesis + per-tool eval rubric.
3. **UI-promise audit** — triple-overdue per `[[ui-promise-audit-owed]]`. Sweep every operator verb in plan docs against SPA source. Highest-leverage prevention work.
4. **F-021** — framework mapping data for `ai-sys-bae72e75`. Partially self-resolves once P4 accumulates more traces; defer until after S62.
5. **F-022 / F-023** — portfolio rollup PDF dispatch + post-registration evidence-add UI. Still on the S59 carry-forward queue.

## Next concrete action (S62)

Pick from the carry-forward queue above. **Recommended:** option 1 (2nd read tool) — proves multi-turn chaining and deepens the synthesis surface. Option 3 (UI-promise audit) is the highest-leverage prevention play if the user wants to clear platform debt instead of stacking more P4.

## Verification

`/verify` block (all PASS):

- scrubber import · PASS
- deid_vault import · PASS
- policy_engine import · PASS
- agent_memory import · PASS (dev warn: DATABASE_URL unset, expected)
- rag_engine import · PASS (dev warn: AZURE_SEARCH_* unset, expected)
- scrubber end-to-end PII round-trip · PASS
- **S61 rego DENY (mutation-verb tool) · PASS** (new)
- **S61 rego ALLOW (allowlisted tool) · PASS** (new)
