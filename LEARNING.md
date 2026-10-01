# repair-agent: Learning Log

## How to read this log

There is one entry per commit, in order, and each covers what changed, why, and the decisions behind it. The Project map always shows the current layout, and the Glossary at the bottom defines project-specific terms.

> "repair-agent" is a placeholder name.

## Project map

```
sandbox/
├── .gitignore    <- files git must never track (secrets, caches, run output)
├── CLAUDE.md     <- standing instructions for Claude Code   [local only]
├── LEARNING.md   <- this log                                [local only]
└── README.md     <- one-line project description
```

There is no code yet. `[local only]` files are gitignored, so they're not backed up on GitHub.

## Entries

### Commit 0.1: Project scaffolding
- **Date:** 2026-10-01
- **What:** Added a Python `.gitignore` and set the README to a one-line description. `CLAUDE.md` (assistant rules) and `LEARNING.md` (this log) were created but kept local by gitignoring them.
- **Why it exists:** It keeps secrets and generated files out of the repo before any code exists.
- **How it works:** `.gitignore` ignores `.venv/`, `__pycache__/`, `*.pyc`, `.pytest_cache/`, `.env`, `runs/`, `.DS_Store`, `CLAUDE.md` and `LEARNING.md`.
- **Key concepts:** `.env` will hold the Anthropic API key, so it's ignored *before* it exists. `.gitignore` only affects untracked files, so a file that's already committed needs `git rm --cached`.
- **Design decisions:**
  - I wrote a small `.gitignore` instead of GitHub's ~150-line template, so every line is explainable.
  - The personal files are gitignored rather than just left unstaged, so a careless `git add .` can't publish them. The cost is no backup.
- **How to verify:** `git check-ignore -v .env CLAUDE.md LEARNING.md` prints the matching rule for each file.
- **Interview questions:**
  1. *You leaked an API key in a pushed commit. What do you do?* Revoke or rotate it at the provider first. Then gitignore the file, run `git rm --cached` on it, and commit. The old commit still contains the key.
  2. *Why not commit `.venv/`?* It's large and machine-specific. It gets rebuilt from `pyproject.toml`.
- **Files changed:** `.gitignore` (new), `README.md` (replaced)

## Glossary

- **.env:** a local file of `NAME=value` secrets (e.g. API keys). It is never committed.
- **CLAUDE.md:** instructions Claude Code loads automatically at the start of each session.
