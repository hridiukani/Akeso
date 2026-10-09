# Customers with no country, by signup year

Data quality check: how many customers have **no country on record**, grouped by the year
they signed up?

Definitions:
- A customer has no country on record when `customers.country` is NULL.
- The signup year is the year of `customers.signed_up_at`, as text, e.g. `2025`.

Expected result: one row per signup year that has at least one such customer, with two columns:
1. the signup year (`YYYY`)
2. the number of customers in that year with no country on record

Row order doesn't matter.
