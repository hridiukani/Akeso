# Dataset: store

A small online store (customers, products, orders, order items, returns and order status
events), shared by every SQL task that names `dataset: store`. Each task picks a `seed`
(the visible database) and a `hidden_seed` (the grading-only database).

- `schema.sql`: the tables. The agent sees this schema.
- `generate.py`: `populate(conn, seed)` fills the schema; the same seed always gives the
  same database. Its docstring lists the messy cases it deliberately includes, notably a
  month with no orders whose position depends on the seed.

Changing either file changes every task that uses this dataset, so re-run `akeso validate`.
