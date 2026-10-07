# Writing good Akeso tasks

A task is a small broken project plus the tests that judge it. A good task measures one
thing: can the agent find and properly fix a realistic bug? This guide covers what makes
a task fair and useful. Every task must pass `akeso validate` before it joins a suite.

## Layout

```
tasks/<kind>/<id>/
    task.yaml        id, kind, description, check_command, editable_paths, split, tags
    README.md        the intended behaviour (the agent sees this)
    pytest.ini       pythonpath = src, testpaths = tests
    src/             the broken code (the editable path)
    tests/           visible tests: the agent can read and run these
    hidden_tests/    used only for grading; never copied into the agent's sandbox
    solution/        the reference fix, laid out like the task (also never copied in)
```

The folder name must equal the `id`. `task.yaml`, `hidden_tests/` and `solution/` are
never shown to the agent, so notes for task authors belong in `task.yaml` (as YAML
comments), not in the README.

## 1. The bug must be realistic

Use mistakes real programmers make: off-by-one errors, a wrong comparison at a boundary,
units mixed up between two files, a missing case in a rule, wrong arithmetic in
formatting. Avoid contrived puzzles, deliberately obfuscated code, or bugs that only a
specific trick reveals. The surrounding code should look normal and reasonable, so the
bug is only visible by reasoning about behaviour.

## 2. The README describes intended behaviour, never the bug

Write the README as the project's real documentation: what each function should do, with
examples. It must be complete enough to define correct behaviour for every input the
tests use. It must not hint at the bug: no "note: be careful with leap years", no
examples chosen to point at the broken line, no comments in the code saying what's wrong.

## 3. Visible tests catch the bug, and guard against careless fixes

- At least one visible test fails because of the bug.
- Include at least one test that passes now and must keep passing (a regression guard).
  The best tasks have a guard that the *obvious* fix breaks, so only a careful fix passes
  (see c005: changing the leap-year rule to `year % 4 == 0` fixes 2000 but breaks 1900).
- Visible test file names must differ from hidden test file names (pytest refuses two
  test files with the same name).

## 4. Hidden tests must be able to catch an overfitted fix

An overfitted fix makes the visible tests pass without fixing the bug, typically by
special-casing their exact inputs (`if numbers == [2, 4, 6]: return 4.0`). Hidden tests
use other inputs to catch that. **This only works if special-casing the visible inputs
behaves differently from the real fix on other inputs.** Pick bugs where that's true.

- **Good: c001 (mean).** The bug (`/ (len - 1)`) is wrong for almost every list. A fix that
  special-cases `[2, 4, 6]` still gives wrong answers for `[1, 2, 3, 4]`, so the hidden
  tests catch it.
- **Counter-example: c002 (shipping).** The bug (`>` instead of `>=` at $50) is wrong for
  exactly one input: an order of exactly $50. A fix that special-cases `50.0` returns the
  right answer for that input, and every other input already worked. So the overfitted
  fix behaves exactly like the real fix for every possible input. No test can tell them
  apart, and none should: behaviourally, that "overfit" is correct. c002's hidden tests
  therefore guard against a different failure (fixes that break another tier boundary)
  instead of against overfitting.

Before writing hidden tests, ask: "If the agent hard-coded the visible tests' answers,
which other input would expose it?" If the honest answer is "none", either accept that
(and say so in `task.yaml`, as c002 does) or choose a different bug.

## 5. The reference solution is a minimal, clean fix

- Put the fixed files under `solution/`, at the same paths as in the task (`solution/src/x.py`).
- Change only files inside `editable_paths`, and never add or change `conftest.py`,
  `sitecustomize.py`, `*.pth` or pytest config: the solution is graded by the same
  tamper rules as an agent, and `akeso validate` fails if it would count as tampering.
- Keep it to what a careful engineer would change; don't refactor around the bug.

## 6. SQL tasks (kind: sql, planned)

The same principles apply, with a query instead of code:

- The bug is a realistic query mistake: a wrong join, a missing `GROUP BY` column, `<`
  instead of `<=` in a date range, a `NULL` handled with `=` instead of `IS NULL`.
- The README describes the question the query answers and the tables, not the mistake.
- The judge is the result of a gold (reference) query on the same data, never the
  model's opinion.
- Hidden checks run the query against different data. Choose data and bugs so that a
  query hard-coded to the visible data's results (or filtered on its specific ids or
  dates) gives different results on the hidden data.

## 7. Checklist before adding a task to a suite

- [ ] The bug is realistic and the code around it looks normal.
- [ ] The README defines the intended behaviour and gives no hint about the bug.
- [ ] A visible test fails; at least one guard test passes and must keep passing.
- [ ] Hidden tests catch special-casing of the visible inputs, or `task.yaml` explains
      why that isn't behaviourally detectable for this bug.
- [ ] The solution changes only editable files and contains nothing that counts as tampering.
- [ ] No module names that shadow Python's standard library (c005 uses `dates.py`, not `calendar.py`).
- [ ] No symlinks; visible and hidden test file names don't collide.
- [ ] `akeso validate` passes: the broken version fails, the solution passes visible and hidden tests.
