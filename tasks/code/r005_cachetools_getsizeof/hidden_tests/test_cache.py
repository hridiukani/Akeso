# From upstream cachetools tests/test_cache.py at commit 39b31bc9b6 (MIT licence).
import unittest

import cachetools

from . import CacheTestMixin


class CacheTest(unittest.TestCase, CacheTestMixin):
    Cache = cachetools.Cache
