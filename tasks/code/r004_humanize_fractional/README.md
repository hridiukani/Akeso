# humanize (excerpt): number formatting

This is the number-formatting part of the [humanize](https://github.com/python-humanize/humanize)
library (MIT licence, see LICENCE): `intcomma`, `intword`, `apnumber`, `ordinal`,
`scientific`, `clamp`, `metric` and `fractional`.

`humanize.fractional(value)` writes a number as a whole number and a fraction:

```python
fractional(1.5)    # '1 1/2'
fractional(0.3)    # '3/10'
fractional(1)      # '1'
```

## Bug report

> **fractional() prints "2 1/1" for 2.9999999**
>
> `humanize.fractional(2.9999999)` returns `'2 1/1'`. That's not a sensible fraction: a value
> this close to 3 should just print `'3'`. I've seen similar odd output for other values
> very close to a whole number.

## Running the tests

```
python -m pytest
```
