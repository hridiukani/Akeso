# Project instructions for Claude Code

## The project
Working name: repair-agent (placeholder; final name not chosen yet).

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
- Every commit must leave the project working: run the offline test suite before committing, and don't commit if it fails.
- Use Conventional Commits messages (feat:, fix:, test:, docs:, chore:, refactor:).
- Before every commit, check that .env and any secrets are not staged. Never commit them.
- Never push. I push all commits myself at the end of each session.

## During a topic
- Keep explanations brief unless I ask you to explain something.
- Still suggest improvements at the end of a step without building them.

## When I say "topic done: <name>"
1. In chat, go through every commit in the topic in order: the commit message, what changed, and why. Explain clearly enough that I could describe each one in an interview.
2. Add a LEARNING.md entry for the topic with only the important things: key concepts, important design decisions and why, anything surprising or tricky, and 3 to 5 interview questions with model answers. No commit-by-commit detail there; that lives in git history. Update the Project map and Glossary if needed. Never rewrite or delete earlier entries unless I ask you to fix a mistake.
3. LEARNING.md is local only (gitignored, never committed), so there is nothing to commit for it.

## LEARNING.md entry format
### Topic N: <name>
- Date
- Key concepts: each important concept explained simply, with an analogy where helpful
- Design decisions: choice, alternatives, and why
- Surprising or tricky: gotchas, bugs found, things that weren't obvious
- Interview questions: 3 to 5 likely questions with model answers

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
