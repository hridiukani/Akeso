# Freeze

**Frozen on:** 2026-10-15
**Manifest:** `suites/manifest.json`
**Fingerprint:** `bff127af0ebdebfb9420f3f2ffc53873e11796aec16f783d08ed452af1b15de8`

## What's frozen

- **All 30 tasks.** Every file in each task folder under `tasks/code/` and `tasks/sql/`:
  task.yaml, README, broken code or query, visible tests, hidden tests and reference
  solution. That's 10 written code tasks, 6 real-bug tasks and 14 SQL tasks.
- **Both shared datasets.** `tasks/datasets/saas/` and `tasks/datasets/store/` (schema,
  generator, README). A dataset change counts as a change to every task that uses it.
- **The split.** 18 dev tasks (`suites/dev.yaml`) and 12 held-out tasks
  (`suites/heldout.yaml`); `suites/full.yaml` lists all 30. Held-out tasks are run only
  for official results, never while building or tuning.

In total, 210 files are hashed with SHA-256 after normalising line endings to LF, so the
same tasks give the same fingerprint on any machine. `akeso run` checks the tasks it is
about to run against the manifest and refuses to start if anything changed. Passing
`--allow-modified` runs anyway, and the run's `summary.json` records the flag and the
modified files. Such a run is never an official result.

The harness (agent, prompts, tools, grading) isn't part of the task freeze. Settings that
make two runs comparable are covered by the Measurement rule in CLAUDE.md, and by the
run fingerprint planned in BACKLOG.md.

## The rule

**Tasks never change after the freeze, except to fix a genuinely broken task.**

A task is broken only if it can't be judged fairly as written. For example:
- the README is ambiguous or contradicts the tests or the gold query
- the reference solution or the gold query is wrong
- a test is flaky
- the task can't run in the sandbox

A task being too easy or too hard is never a reason: difficulty was settled once, in
calibration (CALIBRATION.md).

To fix a broken task:

1. Make the smallest change that makes it fair, and check it with `akeso validate`.
2. Re-freeze with `akeso freeze` and commit the new manifest with the fix.
3. Record it below: the date, the task, what was wrong, what changed, and the new
   fingerprint.
4. Rerun every affected official measurement, meaning every baseline, experiment or
   held-out result that included the task, and record which runs replaced which.

## Changes since the freeze

None.
