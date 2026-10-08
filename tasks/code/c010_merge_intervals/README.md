# booking

Helpers for a room-booking calendar. Times are minutes since midnight.

## `intervals.merge(intervals)`

Takes a list of `(start, end)` bookings, in **any order**, and merges every set of
bookings that overlap or touch into one. `(60, 90)` and `(90, 120)` touch, so they
become `(60, 120)`. The result is sorted by start time.

Examples:

- `merge([(60, 90), (75, 100)])` returns `[(60, 100)]`
- `merge([(60, 90), (90, 120)])` returns `[(60, 120)]`
- `merge([(300, 360), (60, 90)])` returns `[(60, 90), (300, 360)]`

## `intervals.busy_minutes(intervals)`

How many minutes are covered by at least one booking.

## Running the tests

```
python -m pytest
```
