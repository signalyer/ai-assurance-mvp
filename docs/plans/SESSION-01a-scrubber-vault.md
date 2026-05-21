# SESSION-01a — Scrubber + De-ID Vault
# Date: 2026-05-21 (planned)
# Context cost: HIGH

## What this session builds
Two NEW files only:
1. `scrubber.py` — Presidio NER + regex layering, exposes `tokenise_payload(text, scope) -> (scrubbed, vault_id)` and `restore_payload(scrubbed, vault_id) -> raw`
2. `domain/deid_vault.py` — Fernet-encrypted token vault backed by Azure Key Vault (KV key + JSONL ciphertext via `storage.py`), with TTL enforcement

NO patches to existing files in this session. Patches happen in Session 01b.

## Pre-conditions
- [ ] `ARCHITECTURE.md` exists and lists scrubber.py + deid_vault.py under "In Progress"
- [ ] `DECISIONS.md` exists with the "Scrubber before Langfuse" decision
- [ ] `pip install presidio-analyzer presidio-anonymizer cryptography` in requirements.txt
- [ ] `SESSION_SECRET` env var set (used to derive Fernet key for vault if Key Vault is unavailable)
- [ ] `SCRUBBER_ENABLED=true`, `DEID_VAULT_TTL_SECONDS=3600` documented in `.env.example`
- [ ] `python -c "import presidio_analyzer; import cryptography"` passes locally

## Files to create
1. `scrubber.py` (root, beside tracer.py)
   - Public API: `tokenise_payload(text: str, scope: str) -> tuple[str, str]`
     - Returns `(scrubbed_text, vault_id)` where vault_id is the lookup key for restoration
   - Public API: `restore_payload(scrubbed: str, vault_id: str) -> str`
     - Reverses scrubbing using the vault entry; raises if vault entry missing/expired
   - Internal: Presidio analyzer with `en_core_web_sm` (small model), entity types:
     `PERSON, EMAIL_ADDRESS, PHONE_NUMBER, US_SSN, CREDIT_CARD, IBAN_CODE,
      IP_ADDRESS, US_BANK_NUMBER, NRP, LOCATION, DATE_TIME, URL`
   - Plus custom regex layer for `AWS_ARN`, `API_KEY` patterns
   - Tokens replace entities in-place: `[PERSON_001]`, `[EMAIL_002]`, etc. — stable per scope
   - Fail-closed: if Presidio throws, return `(text, "")` and log; caller must check vault_id != "" before trusting scrub

2. `domain/deid_vault.py`
   - Public API: `store(vault_id: str, mapping: dict[str, str], ttl_seconds: int | None = None) -> None`
   - Public API: `lookup(vault_id: str) -> dict[str, str] | None` — returns None on miss or expiry
   - Public API: `vault_stats() -> dict` — { total, active, expired, oldest, newest }
   - Backing: append to `data/deid_vault.jsonl` via `storage._append_jsonl()`
   - Encryption: Fernet from `cryptography`. Key derivation:
     - If `AZURE_KEYVAULT_URI` env var set → fetch DEID_VAULT_KEY via az-identity (read-only path)
     - Else → derive from `SESSION_SECRET` via HKDF (SHA-256) for dev/MVP
   - TTL: each entry carries `expires_at = now + ttl_seconds` (default from `DEID_VAULT_TTL_SECONDS` env)
   - Lookup is O(n) scan of JSONL for v1 (vault stays small; revisit if > 100K entries)

## Files to modify
NONE. Session 01a is new files only. Defer all integration patches to 01b.

## Architectural constraints (copied from ARCHITECTURE.md)
- `scrubber.tokenise_payload()` runs BEFORE `tracer.trace_call()` — verify at every call site (Session 01b)
- Langfuse receives `scrubbed_prompt`, never `raw_prompt`
- No PII in any log, JSONL, or trace
- Fail-closed: on scrubber error, do NOT send raw to Langfuse — drop the trace locally
- JSONL storage only via `storage._append_jsonl()` and `storage._read_jsonl()` patterns
- Type hints on every public function; docstring on every public function

## What NOT to build in this session
- Do NOT patch `tracer.py` (Session 01b)
- Do NOT patch `evaluator.py` (Session 01b)
- Do NOT add the `@scrub_pii` decorator (Session 01b)
- Do NOT touch `api/demo_run.py` or any call site (Session 01b)
- Do NOT build the policy engine (Session 02)
- Do NOT build agent_memory or rag_engine (Session 04)
- Do NOT touch any UI files

## Acceptance criteria
```bash
# Module imports succeed
python -c "import scrubber; print('scrubber OK')"
python -c "from domain.deid_vault import vault_stats; print('vault OK')"

# Round-trip scrub + restore
python -c "
from scrubber import tokenise_payload, restore_payload

text = 'Client John Smith SSN 123-45-6789 email john@example.com phone +1-555-867-5309'
scrubbed, vault_id = tokenise_payload(text, 'session-01a-smoke')

assert vault_id, 'FAIL: scrub returned empty vault_id'
assert 'john@example.com' not in scrubbed, 'FAIL: email leaked through scrubber'
assert '123-45-6789' not in scrubbed, 'FAIL: SSN leaked through scrubber'
assert '+1-555-867-5309' not in scrubbed, 'FAIL: phone leaked through scrubber'
assert 'John Smith' not in scrubbed, 'FAIL: name leaked through scrubber'

restored = restore_payload(scrubbed, vault_id)
assert 'john@example.com' in restored, 'FAIL: email not restored'
assert '123-45-6789' in restored, 'FAIL: SSN not restored'
print('PASS: scrubber round-trip end-to-end')
"

# Vault TTL enforcement
python -c "
from domain.deid_vault import store, lookup
import time
store('ttl-test', {'A': 'B'}, ttl_seconds=1)
assert lookup('ttl-test') == {'A': 'B'}, 'FAIL: immediate lookup missed'
time.sleep(2)
assert lookup('ttl-test') is None, 'FAIL: expired entry still returned'
print('PASS: vault TTL')
"

# Vault stats sanity
python -c "
from domain.deid_vault import vault_stats
s = vault_stats()
assert 'total' in s and 'active' in s and 'expired' in s, 'FAIL: vault_stats schema'
print('PASS: vault stats schema'); print(s)
"

# No raw PII appears in the vault JSONL on disk (only ciphertext)
python -c "
from pathlib import Path
p = Path('data/deid_vault.jsonl')
if p.exists():
    content = p.read_text(errors='ignore')
    assert 'john@example.com' not in content, 'FAIL: raw email in JSONL on disk'
    assert '123-45-6789' not in content, 'FAIL: raw SSN in JSONL on disk'
    print('PASS: vault JSONL contains only ciphertext')
else:
    print('SKIP: vault JSONL not yet created (no entries written this run)')
"
```

## End of session actions
1. Confirm all acceptance criteria PASS
2. Update `ARCHITECTURE.md`:
   - Move `scrubber.py` and `domain/deid_vault.py` from "In Progress" to "Built (2026-05-21)"
   - Update env var list to confirm `SCRUBBER_ENABLED`, `DEID_VAULT_TTL_SECONDS` are now in `.env`
3. Append to `DECISIONS.md`:
   - Any deviations from Presidio entity list
   - Decision on Fernet key derivation (Key Vault vs SESSION_SECRET HKDF)
4. Write `docs/plans/SESSION-01b-patches.md` for the next session
   - Files to patch: `tracer.py`, `evaluator.py`, `api/demo_run.py`, `domain/models.py`, `dashboard.py`
   - Goal: wire `@scrub_pii` decorator + close the raw-prompt leak to Langfuse
5. List any deviations or open issues at the end of session output
6. Run `/verify` one final time before declaring complete
