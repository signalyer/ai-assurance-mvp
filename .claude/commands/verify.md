Run the verification block from ARCHITECTURE.md.
For every command: show the exact output.
Report: PASS or FAIL for each check.
If any FAIL: stop, diagnose, fix before continuing.

Default checks (run all that apply for the current build state):

python -c "import scrubber; print('scrubber OK')"
python -c "from domain.deid_vault import vault_stats; print('vault OK')"
python -c "from domain.policy_engine import evaluate; print('policy_engine OK')"
python -c "from domain.agent_memory import build_context; print('agent_memory OK')"
python -c "from domain.rag_engine import rag_stats; print('rag_engine OK')"

# End-to-end scrubber smoke (after Session 01a)
python -c "
from scrubber import tokenise_payload, restore_payload
text = 'Client John Smith SSN 123-45-6789 email john@example.com'
scrubbed, vault_id = tokenise_payload(text, 'verify')
assert 'john@example.com' not in scrubbed, 'FAIL: email leaked'
assert '123-45-6789' not in scrubbed, 'FAIL: SSN leaked'
restored = restore_payload(scrubbed, vault_id)
assert 'john@example.com' in restored, 'FAIL: email not restored'
print('PASS: scrubber end-to-end')
"

# Skip checks for modules not yet built; mark as N/A, never as PASS.
