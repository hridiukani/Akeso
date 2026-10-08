# humanize (excerpt): naturalsize

This is part of the [humanize](https://github.com/python-humanize/humanize) library
(MIT licence, see LICENCE): `humanize.naturalsize()` formats a number of bytes as a
human-readable file size, such as `3.0 MB`.

```python
naturalsize(3000000)              # '3.0 MB'   (decimal units, the default)
naturalsize(3000, binary=True)    # '2.9 KiB'  (binary units)
naturalsize(3000, gnu=True)       # '2.9K'     (GNU style)
```

## Bug report

> **naturalsize() shows "1000.0 kB" instead of "1.0 MB"**
>
> `humanize.naturalsize(999999)` returns `'1000.0 kB'`. A size should never be shown as
> 1000 of one unit when the next unit up exists; I'd expect `'1.0 MB'`. The same thing
> seems to happen just below other unit boundaries.

## Running the tests

```
python -m pytest
```
