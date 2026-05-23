# Scenario 3 — Team CX · Reusable Agent Governance

**Audience cue:** show how a shared agent gets governed across teams without a single team owning everyone else's risk.
**Real components exercised:** Agent Library (`domain/agents.py`) · `AgentBinding` versioning · publish/subscribe event flow · weakest-link risk inheritance.
**Duration:** ~30s.

## Talk track

"The CX team published v2 of their `customer-intent-classifier` reusable agent. It's used by three other teams. Watch what happens when I trigger the publish."

"Each subscribing system receives a notification within the polling interval. The Payments team's binding stays pinned at v1 — they need to run their own evals before accepting v2. The Marketing team auto-upgrades because their consent policy permits minor version bumps. All three transitions are events on the audit chain. The risk tier of each subscribing system gets recomputed using the weakest-link rule — if the CX agent is HIGH and the subscribing system has a MED-tier agent, the system inherits HIGH."

## What's NOT shown

- Real-time webhooks — v1 polls.
- A public agent marketplace beyond this org — out of scope.

## If asked

- *"What if a subscriber's pinned version becomes unsupported?"* — Publisher emits `agent_deprecated`; subscriber gets a deadline event. Hard-cutoff date enforced by gate, not by deletion.
- *"Can a subscriber fork?"* — Yes. Forking creates a `custom` agent under the subscribing team's namespace; the link to the upstream is preserved for audit but the version stream is now independent.
