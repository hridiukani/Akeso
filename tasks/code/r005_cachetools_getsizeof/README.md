# cachetools (excerpt)

This is the core of the [cachetools](https://github.com/tkem/cachetools) library (MIT
licence, see LICENSE): memoizing collections such as `LRUCache`, `LFUCache`, `FIFOCache`,
`RRCache`, `TTLCache` and `TLRUCache`. Each cache has a `maxsize`. By default every item
counts as size 1; with `getsizeof`, each value's size is `getsizeof(value)`, and the cache
evicts items until the total size fits within `maxsize`.

```python
cache = LRUCache(maxsize=10, getsizeof=len)
cache["b"] = "yyyy"     # currsize 4
cache["a"] = "xxxx"     # currsize 8
```

## Bug report (upstream issue #405)

> **Updating a key with a larger value evicts other keys that would still fit**
>
> With the cache above, `cache["a"] = "xxxxxx"` (6 characters) evicts `"b"`, even though
> the updated cache holds 6 + 4 = 10, which fits exactly in `maxsize`. It looks like the
> old size of `"a"` is still counted while making room for its new value. This happens with
> every cache type.

## Running the tests

```
python -m pytest
```
