# Exceptions log — Azure Deployment Architect

P8 (Release Gate evaluation) discipline: every release-gate exception/waiver
approved by the CISO is documented here. The platform's gate engine stores
the exception record in JSONL; this file is the human-readable index.

Format per entry:

```
## <Gate ID> · expires <YYYY-MM-DD>
**Reason:** one-paragraph rationale for the waiver
**Risk acceptor:** name, role
**Compensating controls:** list — what offsets the unmet gate
**Engine record:** link to data/gate_exceptions.jsonl entry
**Re-evaluation:** what triggers a fresh look (calendar date, prod incident,
  framework update, etc.)
```

---

_(First entry written when a P8 gate failure is waived rather than fixed.)_
