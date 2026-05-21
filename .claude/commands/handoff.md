Session handoff sequence — run in order. Do not skip steps.

1. Run /verify — show all output. Continue only if every applicable check is PASS.

2. Update ARCHITECTURE.md:
   - Move completed files from "In Progress" to "Built (YYYY-MM-DD)"
   - Remove from "Planned" anything started this session
   - Update environment variable list if any added/changed

3. Append to DECISIONS.md any new decisions made this session.
   Use the template:
   ## YYYY-MM-DD — Decision title
   Decision: what was decided
   Alternatives: what was considered
   Why: reasoning
   Constrains: what this forecloses going forward

4. Write docs/plans/SESSION-NN+1-<next-component>.md for the next session.
   Use the template from docs/plans/SESSION-01a-scrubber-vault.md exactly.

5. Output a session summary:
   - What was built (exact file list)
   - What was skipped and why
   - Any deviations from the plan
   - Open issues for next session

6. Output the exact opening message for the next Claude Code session
   (per .claude/commands/plan.md format, with the new SESSION-NN+1 filename filled in).

7. Run git status. Surface any untracked files, .env*, or local.settings.json.
   Do NOT auto-commit. Wait for me to approve commit.
