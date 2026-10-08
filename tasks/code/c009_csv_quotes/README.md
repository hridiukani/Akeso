# rows

Splits a line of a comma-separated (or other delimiter-separated) file into fields.

## `csvrow.split_row(line, delimiter=",")`

- Fields are separated by `delimiter`.
- A field may be wrapped in double quotes, so it can contain the delimiter: `a,"b,c"`
  is two fields, `a` and `b,c`. The wrapping quotes aren't part of the value.
- Inside a quoted field, two double quotes in a row (`""`) stand for one double quote
  character: `"He said ""hi"""` is the field `He said "hi"`.
- `""` on its own is an empty field.
- Empty fields are kept: `a,,b` is `["a", "", "b"]`, and a trailing delimiter gives a
  trailing empty field.

## Running the tests

```
python -m pytest
```
