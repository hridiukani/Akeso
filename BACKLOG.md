# Backlog

Technical to-do list for building Akeso: deferred suggestions and known gaps, grouped by
when they'll be handled. Learning material lives in LEARNING.md (local only); this file is
the engineering list.

## Next topic: tamper detection, hidden tests, eval suite

- **Symlinked test config escapes the judge restore.** `list_files` skips symlinks, so a
  `conftest.py` the agent creates as a link isn't deleted, and pytest would still load it.
- **Code-level tampering isn't caught.** `sitecustomize.py`, `.pth` files, or src code that
  monkeypatches pytest survive restoring `tests/` and the pytest config.
- **Fresh container for the final check.** Copy only the agent's source changes plus the
  original tests into a new container, so nothing left in the old container (processes,
  edited caches) can influence the verdict.
- **A `TAMPERED` stop reason.** "Model's checks passed but the final check failed" is
  reported as `gave_up` today; a dedicated reason makes these cases countable.
- **`task_id` in `AgentResult`, plus a batch runner with `--run-id`.** One folder and one
  summary per suite run; today `scripts/run_agent.py` handles one task per run id.
- **Automatic task validation.** Store each known fix outside the task and check in CI that
  every task fails as-is and passes with its fix (done by hand for c001 to c003).
- **Pace calls for Groq.** Seven HTTP 429s on three small tasks; a 30-task suite needs a
  minimum gap between calls or fewer tasks at once.

## Experiment candidates (don't implement before the baseline is measured)

- **Trim conversation history.** The whole history is resent every step (input grew from
  1.4k to 2k tokens per call on c003). Shortening old tool outputs, or prompt caching once
  the Anthropic provider exists, could cut cost, but may change pass rate. Measure first.
- **"No progress" detection beyond checks.** Stop runs that repeat identical reads or edits
  sooner (today only identical failing checks, max steps and tokens stop them). Stopping
  earlier can also stop a run that would have recovered. Measure first.

## CLI topic

- **Sweep leftover containers at the start of every CLI run.** The age-based
  `cleanup_leftover_containers()` (labelled containers older than `LEFTOVER_MAX_AGE`, 1 hour)
  runs automatically only at the start of a test session (`tests/conftest.py`). Until the
  CLI calls it too, containers left by hard crashes during real runs pile up until
  `python scripts/cleanup_containers.py` is run.

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
