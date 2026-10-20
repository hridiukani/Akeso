# Backlog

Technical to-do list for building Akeso: deferred suggestions and known gaps, grouped by
when they'll be handled. Learning material lives in LEARNING.md (local only); this file is
the engineering list.

## Measurement topic

- **`akeso run --resume`.** Rerun only the missing, crashed or quota-stopped tasks in an
  existing run folder, instead of starting a long suite again. On the free tier it's what
  lets a full run (about 600,000 tokens) be spread over the 200,000-tokens-a-day limit
  (the calibration ran as three chunks under three run ids by hand); on the Developer tier
  it's still what saves a long official run after a crash or an outage.
- **Stop cleanly when the quota runs out.** A daily-cap 429 says "try again in 13
  minutes", but each remaining task retries for about 2 minutes and then errors (17 tasks
  in the first calibration run). Stop the run instead, record the remaining tasks as not
  run (not as failures), and let `--resume` pick them up.
- **Run fingerprint in summary.json.** Record everything that makes two runs comparable
  under the Measurement rule: the provider, the Groq tier (free or Developer), the exact
  model, the reasoning effort (not set today, so Groq's default for gpt-oss-120b), the
  prompt version, the limits and the Docker image digest, alongside the task freeze
  fingerprint (recorded since Topic 8, with line endings normalised).
- **Record pacing waits per task and per run.** Token-aware pacing replaced the 429s (0 in
  the Topic 7 smoke run) with up-front waits, which nothing records. Count them and their
  seconds in each result and summary.json, so a slow run can be put down to the model or
  to the quota.

## Polish topic

- **`akeso doctor`.** One command that checks what a long run needs before it starts:
  Docker running (Docker Desktop stopped between sessions three times in Topic 8), the
  sandbox image built, the freeze manifest present and matching, the active provider's key
  and model set, and which Groq tier the key is on.
- **Update README.md.** It doesn't mention SQL tasks, that they need Docker (local mode
  refuses them), the query runner, the sqlglot dependency, the two datasets, the dev and
  held-out split, `akeso freeze` and `--allow-modified`, or the free versus Developer tier.
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

## Experiments (chosen after the baseline is measured)

Which experiments to run is decided once the official baseline exists, from what it
shows. The candidates so far:

- **Trim conversation history.** The whole history is resent every step (input grew from
  1.4k to 2k tokens per call on c003). Shortening old tool outputs could cut cost, but may
  change pass rate. Evidence from the free tier: its 8,000-token request limit ended s010
  (after 18 steps), r002 and r006 in the calibration. The Developer tier removes that
  limit, so on official runs the case rests on cost and context length; check the
  baseline's token use per task first.
- **Verify-before-stop.** When the model stops calling tools and the checks aren't passing,
  run them and send the failure back so the agent continues instead of ending. Evidence:
  in run 20261007-215234-a20e17, c003 and c005 stopped without the model running checks;
  in the calibration, s008 gave up after a single failing check.

A further idea, if the baseline points to it: **"no progress" detection beyond checks**
(stop runs that repeat identical reads or edits sooner; today only identical failing
checks, max steps and tokens stop them). Stopping earlier can also stop a run that would
have recovered.

## When the Anthropic provider is first used

- **A live check before anything else.** It's built and tested offline only and has never
  made a real API call. Its first use starts with one small request that confirms the
  call works, that the cache breakpoint creates and then reads a cache entry, and that
  thinking blocks are replayed in a two-step tool loop, before any run that matters.

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

## Done in Topic 8 (the full suite)

- **Held-out tasks.** Done (step 8.8): 18 dev and 12 held-out tasks, balanced by kind,
  source and difficulty; runs report totals per split as well as overall. The suite is
  frozen (FREEZE.md, suites/manifest.json) and `akeso run` refuses modified tasks.
- **Anthropic provider, with prompt caching.** Done (pulled forward for calibration):
  the native SDK behind the same Provider interface, a cache breakpoint on the system
  prompt (which caches the tool definitions too), cache writes and reads priced
  separately, its own 429/overload backoff with retry counts, and thinking blocks replayed
  exactly. Note: Haiku 4.5's 4096-token cache minimum is above our prompt's size. Built
  and tested offline only: the MVP measures on Groq's gpt-oss-120b, so nothing has run on it.
- **Mind Groq's daily limits.** Done (step 8.7): the binding limit turned out to be 200,000
  tokens per day, not the 1,000 requests; the calibration ran in three chunks across days.
  Running official measurements within it is now part of `akeso run --resume` above.
- **Harder SQL tasks.** Done (steps 8.5 and 8.6): s003 to s014 add `= NULL`, WHERE vs
  HAVING, a LEFT JOIN undone by WHERE, annual plans spread over months, latest row per
  group, customer-level churn, join fan-out, NULL arithmetic with duplicated lines, integer
  division, ranking with ties, a missing month in a time series and latest status by event
  time, across the saas dataset and a new store dataset.

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
