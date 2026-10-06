# dates

Small calendar helpers.

## `is_leap_year(year)`

Returns `True` if `year` is a leap year in the Gregorian calendar (the calendar in
everyday use), otherwise `False`.

## `days_in_month(year, month)`

Returns how many days `month` (1 to 12) has in `year`. February has 29 days in leap
years and 28 otherwise. A month outside 1 to 12 raises `ValueError`.

Examples:

- `days_in_month(2023, 4)` returns `30`
- `days_in_month(2024, 2)` returns `29`
- `days_in_month(1900, 2)` returns `28`
- `days_in_month(2000, 2)` returns `29`

## Running the tests

From this folder:

```
python -m pytest
```
