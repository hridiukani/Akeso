# Project instructions for Claude Code

## The project
Working name: repair-agent (placeholder; final name not chosen yet).

A CLI that gives an LLM a broken code repo (failing pytest tests) or a broken SQL query. The LLM can read files, edit files, run commands and run checks inside a disposable, locked-down Docker container. It loops until the checks pass or a limit is hit (max steps, max cost, repeated identical error). Every step is saved as a trace. A frozen suite of about 30 tasks is scored on pass rate, steps and cost. Tests or the gold query result are the judge, never the model.

## How work is organized
The project is built in topics (e.g. "Python project setup", "Docker sandbox"). Each topic has several small commits. When I say "topic done: <name>", the topic is finished.

## Rules for every task
1. Do only what the current prompt asks. No extra features. If you think something else is needed, suggest it at the end instead of building it.
2. Keep each change small enough for one commit.
3. Before writing code, give a short plan: which files, and why. Then build.
4. During a topic, explain each change briefly: what you built, why, and anything non-obvious. Go into detail only when I ask.
5. Show me how to run and verify it myself: exact commands and expected output.
6. Do NOT run git commit or git push. After every change, show me the exact git commands and a commit message in Conventional Commits style (feat:, fix:, test:, docs:, chore:). I run them myself.
7. Never read, print or commit secrets. API keys (GROQ_API_KEY and ANTHROPIC_API_KEY) live only in .env, which is gitignored. Never pass .env, host environment variables or host folders into a container.
8. Prefer simple, readable code over clever code. Use type hints and short docstrings. Comments explain why, not what.

## When I say "topic done: <name>"
1. Append ONE detailed LEARNING.md entry for the whole topic, in the format below. It must be detailed enough that I could learn the topic from it without this chat.
2. Update the Project map in LEARNING.md and add new terms to the Glossary.
3. Never rewrite or delete earlier entries unless I ask you to fix a mistake.
4. Suggest a docs: commit for the LEARNING.md update.
5. Give me 3 interview-style quiz questions about the topic. Wait for my answers, then tell me what I got right and wrong.

## LEARNING.md entry format
### Topic N: <name>
- Date
- What was built: summary of the topic
- Why it exists: the problem it solves in the project
- How it works: walkthrough of the files and functions
- Key concepts: each new concept explained simply, with an analogy where helpful
- Design decisions: choice, alternatives, reasoning
- How to verify: commands and expected output
- Interview questions: 3 to 5 likely questions with model answers
- Commits / files changed

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
