# durations

Formats lengths of time for display.

## `format_duration(seconds)`

Takes a whole number of seconds and returns it as `H:MM:SS`:

- hours are not zero-padded and are not limited to 24
- minutes and seconds always have two digits
- a negative number of seconds raises `ValueError`

Examples:

- `format_duration(59)` returns `"0:00:59"`
- `format_duration(600)` returns `"0:10:00"`
- `format_duration(3725)` returns `"1:02:05"`
- `format_duration(93784)` returns `"26:03:04"`

## Running the tests

From this folder:

```
python -m pytest
```
