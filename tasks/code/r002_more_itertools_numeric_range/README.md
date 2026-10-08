# more-itertools (excerpt): numeric_range

This is part of the [more-itertools](https://github.com/more-itertools/more-itertools)
library (MIT licence, see LICENSE). `numeric_range` works like the built-in `range()`, but
its arguments can be any orderable numeric type (floats, `Decimal`, `Fraction`, even
`datetime` with a `timedelta` step):

```python
list(numeric_range(3.5))             # [0.0, 1.0, 2.0, 3.0]
list(reversed(numeric_range(3)))     # [2, 1, 0]
```

It should behave like `range()`: indexing, slicing, `len()`, `in`, `reversed()` and so on.

## Bug report

> **reversed() of an empty numeric_range crashes**
>
> `list(reversed(numeric_range(0)))` raises `IndexError: numeric range object index out of
> range`. With the built-in `range`, `list(reversed(range(0)))` is just `[]`, and I'd expect
> the same here, for any empty range.

## Running the tests

```
python -m pytest
```
