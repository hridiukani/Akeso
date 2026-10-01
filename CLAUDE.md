# Project instructions for Claude Code

## About me
I'm a student building this project to learn. I have never built anything like it. I must be able to explain every line in an interview without help. Teaching me matters more than speed.

## The project
Working name: repair-agent (placeholder; final name not chosen yet).

A CLI that gives an LLM a broken code repo (failing pytest tests) or a broken SQL query. The LLM can read files, edit files, run commands and run checks inside a disposable, locked-down Docker container. It loops until the checks pass or a limit is hit (max steps, max cost, repeated identical error). Every step is saved as a trace. A frozen suite of about 30 tasks is scored on pass rate, steps and cost. Tests or the gold query result are the judge, never the model.

## Rules for every task
1. Do only what the current prompt asks. No extra features. If you think something else is needed, suggest it at the end instead of building it.
2. Keep each change small enough for one commit.
3. Before writing code, give a short plan: which files, and why. Then build.
4. After building, explain in chat, briefly (I'll ask if I want more detail):
   - what you built and why the project needs it
   - how it works, walking through the code section by section
   - every new concept, library or command, explained from scratch, with a plain-English analogy where it helps
   - design choices you made, the alternatives, and why you picked this one
   - what could go wrong and how we would notice
5. Show me how to run and verify it myself: exact commands and expected output.
6. LEARNING.md is my learning log and you maintain it. After every task, append a new entry in the format below, update the Project map if files or folders changed, and add new terms to the Glossary. Keep entries brief: short bullets, project-specific concepts only, and skip basics I already know (like git). I'll ask if I want more detail. Never rewrite or delete earlier entries unless I ask you to fix a mistake.
7. Do NOT run git commit or git push. When done, show me the exact git commands and a commit message in Conventional Commits style (feat:, fix:, test:, docs:, chore:). I run them myself. LEARNING.md changes go in the same commit as the code they explain.
8. End with 3 interview-style quiz questions about this step. Wait for my answers, then tell me what I got right and wrong.
9. Never read, print or commit secrets. API keys live only in .env, which is gitignored. Never pass .env, host environment variables or host folders into a container.
10. Prefer simple, readable code over clever code. Use type hints and short docstrings. Comments explain why, not what.

## LEARNING.md entry format
### Commit X.Y: <title>
- Date
- What: one-paragraph summary
- Why it exists: the problem it solves in the project
- How it works: step-by-step walkthrough referencing files and functions
- Key concepts: each new concept explained simply, with an analogy where helpful
- Design decisions: choice, alternatives, reasoning
- How to verify: commands and expected output
- Interview questions: 3 to 5 likely questions with model answers
- Files changed

## Tech choices
- Python 3.11+, pyproject.toml, a .venv virtual environment
- Anthropic Python SDK for the LLM. The model name comes from config, never hardcoded in logic.
- Docker through the docker Python SDK
- pytest for task checks and for testing the harness itself
- typer and rich for the CLI (later)
