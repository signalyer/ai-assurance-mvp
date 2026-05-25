# SESSION-35 — Dedicated compound 28a fix (deploy.yml paths-ignore)

## Why this session exists
Compound 28a hit 4/4 (effectively 5/5 with S29 baseline) confirmed
data points through S34. Every doc-only closeout commit since
Session 29 has triggered the deploy workflow despite paths-ignore
globs intended to suppress them. Pattern is fully characterized;
S35 is the dedicated fix per the rule "schedule a fix session when
the regression has 4 distinct data points."

## Data points (preserve for blame trail)
| Session | Commit | Run ID | Duration |
|---|---|---|---|
| S29 closeout | (see git log) | 26377047211 | 1m14s |
| S30 closeout | b796494 | 26377787295 | 56s |
| S31 closeout | 9c6d4c8 | 26378101370 | 58s |
| S32 closeout | ca20d85 | 26378408453 | 59s |
| S33 closeout | 37458cd | 26378651826 | 56s |
| S34 closeout | (this session's commit) | TBD | TBD — 6th data point against broken globs |

All six closeout commits share the same diff shape:
- modify `ARCHITECTURE.md`
- delete `docs/plans/SESSION-N-*.md`
- add `docs/plans/SESSION-N+1-*.md`

## Step 1 — Reproduce + diagnose (≤10 min)
Pick one triggering run and inspect the actual changed-files set:
```bash
gh run view 26378651826 --json headSha,event,displayTitle
git show --stat 37458cd
```
Then read [.github/workflows/deploy.yml](.github/workflows/deploy.yml)
current `paths-ignore` block. Hypothesis: the *added* file
(`docs/plans/SESSION-N+1-*.md`) matches a path *outside* the existing
ignore globs even though the deleted + modified files are within them.
GitHub evaluates paths-ignore against the *union* of all changed files;
any one path falling outside the ignore set defeats the suppression.

Confirm or refute by reading the current globs against each of the
three filesets in S33→S34 (the most recent triggering commit).

## Step 2 — Decide fix shape

**Option A — Broaden paths-ignore.** Add explicit globs for the file
shapes that escape today:
```yaml
paths-ignore:
  - '**/*.md'
  - 'docs/**'
  - 'docs/plans/**'
  - 'ARCHITECTURE.md'
```
Lower-risk; preserves the "deploy on push" default for unspecified
files. But fragile — any new doc shape can re-trigger.

**Option B — Flip to `paths` allowlist.** Explicit list of dirs/files
that SHOULD trigger deploy:
```yaml
paths:
  - 'api/**'
  - 'domain/**'
  - 'middleware/**'
  - 'guardrails/**'
  - 'frameworks/**'
  - 'observability/**'
  - 'providers/**'
  - 'scripts/**'
  - 'static/**'
  - 'team-portal/**'
  - 'deploy/**'
  - 'dashboard.py'
  - 'requirements*.txt'
  - '.github/workflows/deploy.yml'
```
Higher-confidence; new files default to "no deploy" until added.
Risk: forgetting to add a new code dir means real changes silently
skip deploy. Mitigated by Session 19's SHA round-trip catching a stale
container on the next code push.

**Recommendation: Option B.** The Session 19 SHA verifier already catches
"is prod fresh?" — pairing it with an explicit allowlist makes the deploy
trigger boundary auditable in a single file. Option A keeps the loophole
class open.

## Step 3 — Implement + verify

1. Edit [.github/workflows/deploy.yml](.github/workflows/deploy.yml) per
   chosen option.
2. **Track A commit** — the workflow change itself (code change; SHOULD
   trigger deploy; that's the test).
3. **Track B commit** — S35 closeout (ARCHITECTURE.md + SESSION-36 plan;
   same modify+delete+add shape as every prior closeout). This commit is
   the live verification: if 28a fix works, this commit does NOT trigger
   the deploy workflow.
4. After push, check `gh run list --workflow=deploy.yml --limit 3`:
   - Track A run: should appear, succeed
   - Track B run: should NOT appear

If Track B still triggers, the fix is wrong — revert and re-diagnose
before closing the session. Do not pile a second fix on top.

## Step 4 — Compound rule capture

On success, add **compound 28b** to CLAUDE.md or the running compound
log: "GitHub Actions `paths-ignore` evaluates against the union of
all changed files; a single path outside the ignore set defeats it.
Prefer `paths:` allowlist for code-deploy triggers — pairs naturally
with the Session 19 SHA round-trip verifier and makes the trigger
boundary auditable in one file."

## Step 5 — Track B (S35 closeout, returns to sweep agenda)

ARCHITECTURE.md S35 entry + SESSION-36 plan. **SESSION-36 returns to
the OpenAPI sweep at `api/rag.py`** — identical 4/4/0 shape to S34's
memory.py (response models present from S18, op_ids missing). Pure
op_id stamping; smallest possible delta; ideal warm-up after the
deploy detour.

## Out of scope for S35
- Any OpenAPI sweep work (resumes S36)
- Any other workflow changes (focus the diff to one file so the
  bisect for the fix is unambiguous)
- Touching the Session 19 SHA round-trip logic (it's working)
