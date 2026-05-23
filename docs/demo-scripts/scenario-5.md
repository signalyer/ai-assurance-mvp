# Scenario 5 — Team Payments · Evals Degradation Detection

**Audience cue:** show that real metric drift is detected without anyone manually inspecting dashboards.
**Real components exercised:** DeepEval 6-metric scorer · event log trend aggregator · `/evals` dashboard sparklines · App Insights alert.
**Duration:** ~20s.

## Talk track

"This is a 14-day window of eval runs for the Payments billing-classifier. Look at hallucination — flat for 11 days, then a clear upward trend over the last three. That trend isn't manually drawn — it's computed from the raw eval events on the audit log every time the dashboard renders."

"App Insights fires an `eval_degradation` alert when the 3-day moving average crosses the Tier-B threshold for the system's risk tier. The team got the alert this morning. They're now in scenario 2 — a release gate just blocked their next deployment until they investigate. End-to-end: eval scoring → trend → alert → gate, all real, no human in the middle of the loop."

## What's NOT shown

- Auto-root-cause analysis — Phase 2.
- Streaming eval (eval-as-traffic-flows) — v1 is batch.

## If asked

- *"What window for the moving average?"* — Configurable per scorer; default 3-day for hallucination, 7-day for relevancy. Defined in `controls/library/eval-thresholds.yaml`.
- *"What if the trend is real and intentional?"* — The team marks the trend `acknowledged_drift`; the gate uses the acknowledged baseline going forward and re-alerts only on further degradation.
