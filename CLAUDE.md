# Project instructions for Claude Code

## The project
Name: Akeso.

A CLI that gives an LLM a broken code repo (failing pytest tests) or a broken SQL query. The LLM can read files, edit files, run commands and run checks inside a disposable, locked-down Docker container. It loops until the checks pass or a limit is hit (max steps, max cost, repeated identical error). Every step is saved as a trace. A frozen suite of about 30 tasks is scored on pass rate, steps and cost. Tests or the gold query result are the judge, never the model.

## How work is organized
The project is built in topics (e.g. "Python project setup", "Docker sandbox"). Each topic has several small commits. When I say "topic done: <name>", the topic is finished.

## Rules for every task
1. Do only what the current prompt asks. No extra features. If you think something else is needed, suggest it at the end instead of building it.
2. Before writing code, give a short plan: which files, and why. Then build.
3. Show me how to run and verify it myself: exact commands and expected output.
4. Never read, print or commit secrets. API keys (GROQ_API_KEY and ANTHROPIC_API_KEY) live only in .env, which is gitignored. Never pass .env, host environment variables or host folders into a container.
5. Prefer simple, readable code over clever code. Use type hints and short docstrings. Comments explain why, not what.

## Committing
- You commit everything yourself. Make small, focused commits: each one a single meaningful change (for example "add config loader", "add tests for path safety"), typically 1 to 3 commits per prompt. There is no target count per topic: make as many commits as there are meaningful changes. Never make empty or padding commits.
- Every commit must leave the project working. Check pytest's own exit code, never one hidden behind a pipe:
  - Before every commit, run the quick tests: `python -m pytest -m "not docker and not slow"` (about 10 seconds). Don't commit if they fail.
  - Once at the end of each step, if that step touched sandbox, environment, grading or agent code (sandbox.py, workspace.py, environment.py, checks.py, grading.py, sql_judge.py, sql_runner.py, agent.py, tools.py, oneshot.py, docker/), run the Docker tests in parallel, then the slow tests: `python -m pytest -m docker -n 4` and `python -m pytest -m slow`. If they fail, fix it in a new commit before moving on.
  - Before I push (at "topic done"), run the full suite so everything is green: `python -m pytest -m "not slow" -n 4`, then `python -m pytest -m slow`.
- Tests that need Docker get the `docker` marker (`@pytest.mark.docker`). Tests that start real Python or pytest processes on this machine (LocalWorkspace, one-shot runs, subprocesses) get the `slow` marker. Slow tests run serially: they're timing-sensitive and slow each other down when run in parallel.
- Use Conventional Commits messages (feat:, fix:, test:, docs:, chore:, refactor:).
- Before every commit, check that no secrets are staged: never `.env` or any `.env.*` file. The only exception is `.env.example`, which holds placeholders and is meant to be committed.
- Never push. I push all commits myself at the end of each session.

## During a topic
- Keep explanations brief unless I ask you to explain something.
- Still suggest improvements at the end of a step without building them.
- When a suggestion is deferred, add it to BACKLOG.md (the technical to-do list, committed), grouped by when it will be handled.

## When I say "topic done: <name>"
1. In chat only: go through every commit in the topic in order: the commit message, what changed, and why. Explain clearly enough that I could describe each one in an interview. This commit-by-commit summary never goes into LEARNING.md.
2. Update LEARNING.md, following the style rules below:
   - Rewrite "Where we are" (replace it; don't append).
   - Update "Following one task through the system" so it describes the system as it works now.
   - Add one plain-language section for the topic.
   - Add new terms to "Words to know" and update "Known limitations".
   - Never rewrite or delete earlier topic sections unless I ask you to fix a mistake. Keep anything under "My notes" exactly as I wrote it.
3. LEARNING.md is local only (gitignored, never committed), so there is nothing to commit for it.

## LEARNING.md style
LEARNING.md is for me, preparing to explain Akeso to two audiences: a non-technical person and a technical interviewer.
- Explain everything in two layers. First the plain version: what it is and why it exists, in everyday language, with an analogy where it helps. Then "the technical version": the same idea in the real terms an engineer would use (for example sandbox, container isolation, tool calling, agent loop, reward hacking), each briefly defined.
- Both layers must be accurate. The plain version simplifies but must never be wrong.
- Avoid file names, function names, code and commit details unless truly essential.
- Use the file's one consistent analogy (the apprentice mechanic, the locked practice workshop, the foreman, the inspector's checklist and the logbook).
- File structure, in order:
  1. "Where we are": what stage the project is at, which topics are done, what it can and can't do yet, and what's next. A few short paragraphs, rewritten after every topic.
  2. "The project in plain words": what we're building, why, and how the pieces fit together.
  3. "Following one task through the system": the step-by-step story of fixing one bug with the current system.
  4. One section per topic, each with: what we built and why the project needed it; how it works (the plain version as a story or analogy, then the technical version in a few precise sentences); the tricky part or interesting decision and why we chose it; and interview questions with answers in plain, confident language.
  5. "Words to know": a short plain-English glossary.
  6. "Known limitations": what the project doesn't handle yet, explained simply.
- The technical backlog belongs in BACKLOG.md, not LEARNING.md.

## Tech choices
- Python 3.11+, pyproject.toml, a .venv virtual environment
- LLM access goes through one small provider interface in our code, with two implementations: an OpenAI-compatible provider using the OpenAI Python SDK (used for Groq, and could later point at OpenRouter or local Ollama), and an Anthropic provider using the Anthropic Python SDK (needed for prompt caching). The rest of the code never imports a provider SDK directly; it only uses our interface and our own internal message format.
- The active provider and model come from config (.env), e.g. PROVIDER=groq or PROVIDER=anthropic, with a model name per provider. Nothing about providers or models is hardcoded in logic. .env holds both GROQ_API_KEY and ANTHROPIC_API_KEY.
- Groq's free tier has rate limits, so model calls must handle HTTP 429 errors by waiting and retrying with backoff.
- Track input and output tokens on every call. Cost comes from a per-model price table in config (0 for Groq's free tier). Record the provider and exact model name in every run.
- Docker through the docker Python SDK
- pytest for task checks and for testing the harness itself
- typer and rich for the CLI (later)

## Measurement rule
Groq is for development and debugging only. All reported numbers (baseline, experiments, held-out results) must come from the Anthropic model, run with identical settings. Never compare results from different providers or models as if they were the same experiment.
