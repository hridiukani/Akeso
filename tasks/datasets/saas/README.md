# Dataset: saas

A small SaaS billing database (plans, customers, subscriptions, payments), shared by every
SQL task that names `dataset: saas`. Each task picks a `seed` (the visible database the
agent works with) and a `hidden_seed` (a second database used only for grading).

- `schema.sql`: the tables. The agent sees this schema.
- `generate.py`: `populate(conn, seed)` fills the schema; the same seed always gives the
  same database. Its docstring lists the messy cases it deliberately includes.

Changing either file changes every task that uses this dataset, so re-run `akeso validate`.
