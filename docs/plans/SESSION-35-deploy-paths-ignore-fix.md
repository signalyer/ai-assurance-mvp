# SESSION-35 — Compound 28a observation phase (NOT fix yet)

## Status change at S34 closeout — read this first
Original plan: dedicated fix session for compound 28a after 5/5 confirmed
triggers. **The S34 closeout commit `d5b36de` broke the streak — it did
NOT trigger the deploy workflow**, only contract-tests. Identical diff
shape to the 5 prior triggering closeouts (modify ARCHITECTURE.md +
delete `SESSION-N-*.md` + add `SESSION-N+1-*.md`).

This means compound 28a is either **intermittent** (GitHub Actions
flake, race condition, or undocumented paths-ignore semantics) or my
pattern recognition on the 5 prior hits was missing a distinguishing
factor. Either way, **a premature fix is the wrong move** — changing
the workflow now risks adding complexity to something that may already
be working, and obscures the diagnosis for the actual root cause.

**S35 is now an observation session, not a fix session.**

## Why this session exists
Compound 28a hit 5/5 confirmed data points through S33, then broke the
streak at S34 closeout. Pattern is no longer fully characterized — need
more data before any fix.

## Data points (preserve for blame trail)
| Session | Commit | Deploy run? | Notes |
|---|---|---|---|
| S29 closeout | (git log) | YES — 26377047211 | 1m14s |
| S30 closeout | b796494 | YES — 26377787295 | 56s |
| S31 closeout | 9c6d4c8 | YES — 26378101370 | 58s |
| S32 closeout | ca20d85 | YES — 26378408453 | 59s |
| S33 closeout | 37458cd | YES — 26378651826 | 56s |
| **S34 closeout** | **d5b36de** | **NO** | **Streak broken — only contract-tests fired** |

All six closeout commits share the same diff shape:
- modify `ARCHITECTURE.md`
- delete `docs/plans/SESSION-N-*.md`
- add `docs/plans/SESSION-N+1-*.md`

Yet S34 didn't trigger deploy. Possible explanations to test:
1. **GitHub Actions flake** — paths-ignore evaluation race / inconsistency
2. **File-content sensitivity** — `paths-ignore` may interact with
   added-file *content* in some edge case (unlikely per docs, but
   undocumented behavior happens)
3. **Concurrency cancellation** — S34 closeout pushed ~3min after Track A
   commit; the deploy concurrency group `deploy-app-aigovern-dev` is
   `cancel-in-progress: false`. But maybe queued-and-dropped semantics
   differ from cancel semantics.
4. **My prior pattern recognition was wrong** — one of S29-S33 had a
   different shape than I cataloged. Worth re-checking the actual
   `git show --stat` for each.

## Step 0 — Observation only (no code change this session)

Before any fix, gather more data:

1. **Re-verify the 5 prior triggers** — for each of `b796494`, `9c6d4c8`,
   `ca20d85`, `37458cd`, run `git show --stat` and compare exact file
   sets. Confirm I cataloged the diff shape correctly. If any one was
   actually different (e.g. accidentally touched a code file), it
   wasn't a real 28a hit and the streak was 4, not 5.

2. **Re-verify the S34 closeout non-trigger** — run
   `gh run list --workflow=deploy.yml --commit=d5b36de`. Confirm it
   genuinely didn't fire (not just delayed or filtered from default
   list).

3. **Log the next 3 doc-only commits** through S35 / S36 / S37 closeouts.
   Track each in a continuation table below.

4. **Decision gate at S37 closeout:**
   - If 0/3 trigger → 28a self-resolved; close as "GitHub flake,
     not actionable." Update compound rule to "intermittent, do not fix."
   - If 1-2/3 trigger → still intermittent; one more session of
     observation (S38).
   - If 3/3 trigger → pattern re-confirmed; proceed to Step 1
     diagnosis below. Now have S29-S33 (5/5) + S34 (broken) +
     S35-S37 (3/3) = strong intermittent signal worth fixing.

5. **If S34 was a flake, do nothing in S35.** Move directly to Track A
   sweep for the planned target (`api/rag.py`, identical 4/4/0 shape
   to S34's memory.py). This file becomes a living observation log,
   not a fix plan, until the threshold above triggers.

| Session | Closeout commit | Triggered deploy? | Notes |
|---|---|---|---|
| S35 | (TBD) | (TBD) | |
| S36 | (TBD) | (TBD) | |
| S37 | (TBD) | (TBD) | |

---

## Steps 1-5 — DO NOT EXECUTE UNTIL STEP 0 GATE TRIPS

The original fix plan below is preserved for when (if) the threshold
in Step 0.4 is met. Skip it until then.

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
