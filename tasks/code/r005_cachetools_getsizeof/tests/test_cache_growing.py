"""Minimal reproduction of the bug report, plus behaviour that already works."""

from cachetools import LRUCache


def test_growing_an_entry_that_still_fits_keeps_the_others() -> None:
    cache = LRUCache(maxsize=10, getsizeof=len)
    cache["b"] = "yyyy"
    cache["a"] = "xxxx"
    cache["a"] = "xxxxxx"
    assert dict(cache) == {"a": "xxxxxx", "b": "yyyy"}
    assert cache.currsize == 10


def test_new_entries_still_evict_when_full() -> None:
    cache = LRUCache(maxsize=10, getsizeof=len)
    cache["a"] = "xxxx"
    cache["b"] = "yyyy"
    cache["c"] = "zzzz"
    assert "a" not in cache and cache.currsize == 8
