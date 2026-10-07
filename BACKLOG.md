# Backlog

Technical to-do list for building Akeso: deferred suggestions and known gaps, grouped by
when they'll be handled. Learning material lives in LEARNING.md (local only); this file is
the engineering list.

## Done in Topic 6 (tasks, cheat-proof grading and the run command)

- **Symlinked test config escaped the judge restore.** Done (step 6.3): any symlink in the
  agent's environment is recorded as tampering and never carried into grading.
- **Code-level tampering wasn't caught.** Done (step 6.3): conftest.py, sitecustomize.py,
  usercustomize.py, *.pth, pytest config, and edited source importing pytest/_pytest/pluggy
  are flagged. Remaining gaps are in LEARNING.md's Known limitations.
- **Fresh container for the final check.** Done (step 6.2): grading applies only editable
  regular-file changes to a brand-new environment built from the pristine task.
- **A `TAMPERED` stop reason.** Done (step 6.3): `tampered` is a verdict with the findings
  recorded, separate from the stop reason.
- **`task_id` in `AgentResult`, plus a batch runner with `--run-id`.** Done (steps 6.2,
  6.6, 6.7): results carry task_id; `akeso run --suite NAME --run-id ID` writes one folder
  per run with a trace per task and summary.json.
- **Automatic task validation.** Done (step 6.5): `akeso validate` grades each task's broken
  version (must fail) and reference solution (must pass visible and hidden tests) in Docker.
- **Pace calls for Groq.** Done (step 6.6): a per-provider minimum gap between calls
  (GROQ_MIN_CALL_INTERVAL, default 2s). Note: the smoke run still hit 429s, so Groq's limit
  looks token-based (see the Topic 6 suggestions).
- **Sweep leftover containers at the start of every CLI run.** Done (step 6.6): every batch
  run (and so `akeso run`) sweeps containers older than an hour before a Docker run.

## Experiment candidates (don't implement before the baseline is measured)

- **Trim conversation history.** The whole history is resent every step (input grew from
  1.4k to 2k tokens per call on c003). Shortening old tool outputs, or prompt caching once
  the Anthropic provider exists, could cut cost, but may change pass rate. Measure first.
- **"No progress" detection beyond checks.** Stop runs that repeat identical reads or edits
  sooner (today only identical failing checks, max steps and tokens stop them). Stopping
  earlier can also stop a run that would have recovered. Measure first.

## Polish topic

- **Speed up the Docker tests.** About 2.5 to 3.5 minutes now; running them in parallel with
  `pytest-xdist` (one sandbox each) would shorten commit cycles.

## Unscheduled

- **Ignore `.env.*` in `.gitignore`.** `.gitignore` only ignores `.env`, so a `.env.local`
  would show up in `git status` and could be added by `git add .`. The commit-time secret
  check catches it for Claude's commits only. Fix: add `.env.*` followed by `!.env.example`.
- **Local-mode timeouts don't kill child processes.** In `LocalWorkspace.exec`,
  `subprocess.run(..., timeout=...)` kills only the direct child; processes it started can
  keep running. Docker is unaffected (coreutils `timeout` signals the process group, and
  removing the container kills everything). Accepted while local mode is opt-in. Fix: start
  the command in its own process group (`start_new_session=True` on Unix,
  `CREATE_NEW_PROCESS_GROUP` plus a tree kill on Windows) and kill the group on timeout.
