# Security log — Azure Deployment Architect

P7 (Adversarial probing) discipline: every failed probe + its mitigation is
documented here with the platform finding ID, the mitigation method, and
the commit SHA that closed it.

Mitigation methods (pick one or more per finding):
- **system-prompt** — tightened the Opus or Haiku prompt
- **guardrail** — added a Llama Guard topic rule, NeMo rail, or LLM Guard
  scanner clause
- **opa-policy** — added a rule to `policies/azure-architect.rego`
- **tool-schema** — narrowed a tool's return schema or input validation

Format per entry:

```
## <Finding ID> · <severity> · <category>
**Probe:** adversarial probe name
**Found:** YYYY-MM-DD
**Mitigation:** method(s) listed above
**Commit:** <sha>
**Verification:** how we re-probed and confirmed it now fails closed
```

---

_(First entry written during P7 calibration.)_
