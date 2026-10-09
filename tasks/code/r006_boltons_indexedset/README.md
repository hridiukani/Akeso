# boltons (excerpt): setutils

This is the `setutils` module of the [boltons](https://github.com/mahmoud/boltons) library
(BSD licence, see LICENSE). `IndexedSet` is a set that remembers insertion order and also
supports indexing like a list: `s[0]`, `s[-1]`, slicing, `index()` and `pop(index)`.
Removed items leave internal gaps that are compacted lazily.

```python
s = IndexedSet([10, 20, 30])
s[0]      # 10
s[-1]     # 30
s.pop(0)  # 10
```

Like a list, an index outside the set (from `-len(s)` to `len(s) - 1`) should raise
`IndexError`.

## Bug report

> **Out-of-range negative index returns an item instead of raising IndexError**
>
> `IndexedSet([10, 20, 30])[-4]` returns `30`. With a list, `[10, 20, 30][-4]` raises
> `IndexError: list index out of range`. I think `pop()` with a large negative index is
> affected too.

## Running the tests

```
python -m pytest
```
