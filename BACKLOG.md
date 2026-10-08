# Backlog

Technical to-do list for building Akeso: deferred suggestions and known gaps, grouped by
when they'll be handled. Learning material lives in LEARNING.md (local only); this file is
the engineering list.

## Measurement topic

- **Anthropic provider, with prompt caching.** Every official number must come from the
  Anthropic model, so this is required before the baseline. Caching the repeated system
  prompt and tool definitions should cut cost on longer runs.
- **Run fingerprint in summary.json.** Record hashes of the task files, the Docker image
  digest, the prompt version and the limits, so two runs can be proven to use identical
  settings (the Measurement rule). Hash file contents with line endings normalised (or
  hash the git blobs), so the same tasks give the same fingerprint on every machine;
  .gitattributes now keeps LF in working copies, but a fingerprint shouldn't depend on it.
- **Record pacing waits per task and per run.** Token-aware pacing replaced the 429s (0 in
  the Topic 7 smoke run) with up-front waits, which nothing records. Count them and their
  seconds in each result and summary.json, so a slow run can be put down to the model or
  to the quota.
- **`akeso run --resume`.** Rerun only the missing or crashed tasks in an existing run
  folder, instead of starting a long suite again after a crash.

## Full-suite topic

- **Held-out tasks.** Every task is `split: dev` so far. Official results need held-out
  tasks the prompt was never tuned on, and runs should report the dev and held-out splits
  separately.
- **Harder SQL tasks.** s001 took 3 steps and s002 took 5 in the Topic 7 smoke run, so
  both are easy for the development model. Candidates: `= NULL` instead of `IS NULL`,
  `WHERE` instead of `HAVING`, an inner join that drops the plan nobody is on, a window
  function over the wrong partition, annual revenue spread over months.
- **Mind Groq's daily request cap.** Its headers report 1,000 requests a day (on top of
  8,000 tokens a minute). A 30-task suite at about 4 steps a task is ~120 requests, so
  about 8 development runs a day; plan full-suite debugging around it.

## Polish topic

- **Stronger code-tampering checks.** Check imports by parsing the code (Python's `ast`)
  rather than with a text pattern, so imports assembled at runtime are caught, and flag
  source that inspects running modules (`sys.modules`) or reads test files. These are the
  gaps listed in LEARNING.md's Known limitations.
- **`akeso run --task ID`, and fold the old scripts into the CLI.** `scripts/run_agent.py`,
  `scripts/cleanup_containers.py` and `scripts/build_images.py` overlap the CLI now.
- **Pin the sandbox base image by digest.** `python:3.11-slim` can change underneath us;
  pinning its digest keeps the sandbox identical between runs. (The parallel Docker tests
  from this item are done.)
- **Catch hardcoding in queries that read a table.** `SELECT 1234.5 FROM plans LIMIT 1`
  passes the tamper check because it references a table, and a literal JSON string fed to
  `json_each` does too. The hidden database makes both fail, but they aren't labelled
  tampering. Flag results made only of literals with no aggregate, and long string literals
  passed to table-valued functions.
- **Update README.md for SQL tasks.** It doesn't mention SQL tasks, that they need Docker
  (local mode refuses them), the query runner, or the sqlglot dependency.

## Experiment candidates (don't implement before the baseline is measured)

- **Verify-before-stop.** When the model stops calling tools and the checks aren't passing,
  run them and send the failure back so the agent continues instead of ending. Evidence:
  in run 20261007-215234-a20e17, c003 and c005 stopped without the model running checks.
- **Trim conversation history.** The whole history is resent every step (input grew from
  1.4k to 2k tokens per call on c003). Shortening old tool outputs, or prompt caching once
  the Anthropic provider exists, could cut cost, but may change pass rate. Measure first.
- **"No progress" detection beyond checks.** Stop runs that repeat identical reads or edits
  sooner (today only identical failing checks, max steps and tokens stop them). Stopping
  earlier can also stop a run that would have recovered. Measure first.

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
- **Flaky local agent test.** `test_cheating_changes_never_reach_grading[local]` failed
  once during a slow quick run (the agent's own check didn't pass after the cheat, so the
  loop ran a fourth step), then passed on every rerun. Its trace was already deleted. Now
  that pytest keeps failed tests' tmp folders (tmp_path_retention_policy = "failed"), look
  at the trace next time it fails. Likely load-sensitive timing in local mode.

## Done in Topic 7 (SQL tasks)

- **Token-aware pacing for Groq.** Done (step 7.1): the Groq provider reads its
  x-ratelimit-* headers and waits for the token quota to refill before a call that would
  exceed it; backoff on 429 is the fallback. Retry messages are logged at debug level; the
  count is in each result, summary.json and the end-of-run line.
- **More validator checks.** Done (step 7.7): `akeso validate` fails a task containing
  symlinks (in the task or its dataset) and a code task whose hidden test file names
  collide with visible ones.
- **Faster quick tests, parallel Docker tests.** Done: tests that start real processes on
  this machine are marked `slow`, so the quick run takes ~10 s instead of 2.5 min, and the
  Docker tests run with `pytest -n 4` (~45 s instead of 2 to 2.5 min). Slow tests stay
  serial. Running in parallel exposed (and fixed) a race in the leftover-container sweep.
- **LF line endings everywhere.** Done: .gitattributes keeps LF for every text file.
- **Unparseable SQL is a warning, not tampering.** Done: the hidden database decides the
  verdict; validate still fails a gold query the parser can't read.

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
  (GROQ_MIN_CALL_INTERVAL, default 2s). Groq's limit still bites; token-aware pacing is
  scheduled for the SQL topic.
- **Sweep leftover containers at the start of every CLI run.** Done (step 6.6): every batch
  run (and so `akeso run`) sweeps containers older than an hour before a Docker run.
- **A task-writing guideline for overfitting.** Done (Topic 6 follow-up): TASK_GUIDE.md,
  with c002 as the counter-example, noted in its task.yaml.
