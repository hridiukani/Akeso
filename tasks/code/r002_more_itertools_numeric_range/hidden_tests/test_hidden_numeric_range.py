# NumericRangeTests from upstream more-itertools tests/test_more.py at commit edb3346f83 (MIT licence).

from collections.abc import Hashable, Iterable, Iterator, Sequence, Set
from datetime import datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from pickle import dumps, loads
from unittest import TestCase

import more_itertools as mi


class NumericRangeTests(TestCase):
    def test_basic(self):
        for args, expected in [
            ((4,), [0, 1, 2, 3]),
            ((4.0,), [0.0, 1.0, 2.0, 3.0]),
            ((1.0, 4), [1.0, 2.0, 3.0]),
            ((1, 4.0), [1.0, 2.0, 3.0]),
            ((1.0, 5), [1.0, 2.0, 3.0, 4.0]),
            ((0, 20, 5), [0, 5, 10, 15]),
            ((0, 20, 5.0), [0.0, 5.0, 10.0, 15.0]),
            ((0, 10, 3), [0, 3, 6, 9]),
            ((0, 10, 3.0), [0.0, 3.0, 6.0, 9.0]),
            ((0, -5, -1), [0, -1, -2, -3, -4]),
            ((0.0, -5, -1), [0.0, -1.0, -2.0, -3.0, -4.0]),
            ((1, 2, Fraction(1, 2)), [Fraction(1, 1), Fraction(3, 2)]),
            ((0,), []),
            ((0.0,), []),
            ((1, 0), []),
            ((1.0, 0.0), []),
            ((0.1, 0.30000000000000001, 0.2), [0.1]),  # IEE 754 !
            (
                (
                    Decimal("0.1"),
                    Decimal("0.30000000000000001"),
                    Decimal("0.2"),
                ),
                [Decimal("0.1"), Decimal("0.3")],
            ),  # okay with Decimal
            (
                (
                    Fraction(1, 10),
                    Fraction(30000000000000001, 100000000000000000),
                    Fraction(2, 10),
                ),
                [Fraction(1, 10), Fraction(3, 10)],
            ),  # okay with Fraction
            ((Fraction(2, 1),), [Fraction(0, 1), Fraction(1, 1)]),
            ((Decimal('2.0'),), [Decimal('0.0'), Decimal('1.0')]),
            (
                (
                    datetime(2019, 3, 29, 12, 34, 56),
                    datetime(2019, 3, 29, 12, 37, 55),
                    timedelta(minutes=1),
                ),
                [
                    datetime(2019, 3, 29, 12, 34, 56),
                    datetime(2019, 3, 29, 12, 35, 56),
                    datetime(2019, 3, 29, 12, 36, 56),
                ],
            ),
        ]:
            actual = list(mi.numeric_range(*args))
            self.assertEqual(expected, actual)
            self.assertTrue(
                all(type(a) is type(e) for a, e in zip(actual, expected))
            )

    def test_arg_count(self):
        for args, message in [
            ((), 'numeric_range expected at least 1 argument, got 0'),
            (
                (0, 1, 2, 3),
                'numeric_range expected at most 3 arguments, got 4',
            ),
        ]:
            with self.assertRaisesRegex(TypeError, message):
                mi.numeric_range(*args)

    def test_zero_step(self):
        for args in [
            (1, 2, 0),
            (
                datetime(2019, 3, 29, 12, 34, 56),
                datetime(2019, 3, 29, 12, 37, 55),
                timedelta(minutes=0),
            ),
            (1.0, 2.0, 0.0),
            (Decimal("1.0"), Decimal("2.0"), Decimal("0.0")),
            (Fraction(2, 2), Fraction(4, 2), Fraction(0, 2)),
        ]:
            with self.assertRaises(ValueError):
                list(mi.numeric_range(*args))

    def test_bool(self):
        for args, expected in [
            ((1.0, 3.0, 1.5), True),
            ((1.0, 2.0, 1.5), True),
            ((1.0, 1.0, 1.5), False),
            ((1.0, 0.0, 1.5), False),
            ((3.0, 1.0, -1.5), True),
            ((2.0, 1.0, -1.5), True),
            ((1.0, 1.0, -1.5), False),
            ((0.0, 1.0, -1.5), False),
            ((Decimal("1.0"), Decimal("2.0"), Decimal("1.5")), True),
            ((Decimal("1.0"), Decimal("0.0"), Decimal("1.5")), False),
            ((Fraction(2, 2), Fraction(4, 2), Fraction(3, 2)), True),
            ((Fraction(2, 2), Fraction(0, 2), Fraction(3, 2)), False),
            (
                (
                    datetime(2019, 3, 29),
                    datetime(2019, 3, 30),
                    timedelta(hours=1),
                ),
                True,
            ),
            (
                (
                    datetime(2019, 3, 29),
                    datetime(2019, 3, 28),
                    timedelta(hours=1),
                ),
                False,
            ),
        ]:
            self.assertEqual(expected, bool(mi.numeric_range(*args)))

    def test_contains(self):
        for args, expected_in, expected_not_in in [
            ((10,), range(10), (0.5,)),
            ((1.0, 9.9, 1.5), (1.0, 2.5, 4.0, 5.5, 7.0, 8.5), (0.9,)),
            ((9.0, 1.0, -1.5), (1.5, 3.0, 4.5, 6.0, 7.5, 9.0), (0.0, 0.9)),
            (
                (Decimal("1.0"), Decimal("9.9"), Decimal("1.5")),
                (
                    Decimal("1.0"),
                    Decimal("2.5"),
                    Decimal("4.0"),
                    Decimal("5.5"),
                    Decimal("7.0"),
                    Decimal("8.5"),
                ),
                (Decimal("0.9"),),
            ),
            (
                (Fraction(0, 1), Fraction(5, 1), Fraction(1, 2)),
                (Fraction(0, 1), Fraction(1, 2), Fraction(9, 2)),
                (Fraction(10, 2),),
            ),
            (
                (
                    datetime(2019, 3, 29),
                    datetime(2019, 3, 30),
                    timedelta(hours=1),
                ),
                (datetime(2019, 3, 29, 15),),
                (datetime(2019, 3, 29, 15, 30),),
            ),
        ]:
            r = mi.numeric_range(*args)
            for v in expected_in:
                self.assertTrue(v in r)
                self.assertFalse(v not in r)

            for v in expected_not_in:
                self.assertFalse(v in r)
                self.assertTrue(v not in r)

    def test_eq(self):
        for args1, args2 in [
            ((0, 5, 2), (0, 6, 2)),
            ((1.0, 9.9, 1.5), (1.0, 8.6, 1.5)),
            ((8.5, 0.0, -1.5), (8.5, 0.7, -1.5)),
            ((7.0, 0.0, 1.0), (17.0, 7.0, 0.5)),
            (
                (Decimal("1.0"), Decimal("9.9"), Decimal("1.5")),
                (Decimal("1.0"), Decimal("8.6"), Decimal("1.5")),
            ),
            (
                (Fraction(1, 1), Fraction(10, 1), Fraction(3, 2)),
                (Fraction(1, 1), Fraction(9, 1), Fraction(3, 2)),
            ),
            (
                (
                    datetime(2019, 3, 29),
                    datetime(2019, 3, 30),
                    timedelta(hours=10),
                ),
                (
                    datetime(2019, 3, 29),
                    datetime(2019, 3, 30, 1),
                    timedelta(hours=10),
                ),
            ),
        ]:
            self.assertEqual(
                mi.numeric_range(*args1), mi.numeric_range(*args2)
            )

        for args1, args2 in [
            ((0, 5, 2), (0, 7, 2)),
            ((1.0, 9.9, 1.5), (1.2, 9.9, 1.5)),
            ((1.0, 9.9, 1.5), (1.0, 10.3, 1.5)),
            ((1.0, 9.9, 1.5), (1.0, 9.9, 1.4)),
            ((8.5, 0.0, -1.5), (8.4, 0.0, -1.5)),
            ((8.5, 0.0, -1.5), (8.5, -0.7, -1.5)),
            ((8.5, 0.0, -1.5), (8.5, 0.0, -1.4)),
            ((0.0, 7.0, 1.0), (7.0, 0.0, 1.0)),
            (
                (Decimal("1.0"), Decimal("10.0"), Decimal("1.5")),
                (Decimal("1.0"), Decimal("10.5"), Decimal("1.5")),
            ),
            (
                (Fraction(1, 1), Fraction(10, 1), Fraction(3, 2)),
                (Fraction(1, 1), Fraction(21, 2), Fraction(3, 2)),
            ),
            (
                (
                    datetime(2019, 3, 29),
                    datetime(2019, 3, 30),
                    timedelta(hours=10),
                ),
                (
                    datetime(2019, 3, 29),
                    datetime(2019, 3, 30, 15),
                    timedelta(hours=10),
                ),
            ),
        ]:
            self.assertNotEqual(
                mi.numeric_range(*args1), mi.numeric_range(*args2)
            )

        self.assertNotEqual(mi.numeric_range(7.0), 1)
        self.assertNotEqual(mi.numeric_range(7.0), "abc")

    def test_get_item_by_index(self):
        for args, index, expected in [
            ((1, 6), 2, 3),
            ((1.0, 6.0, 1.5), 0, 1.0),
            ((1.0, 6.0, 1.5), 1, 2.5),
            ((1.0, 6.0, 1.5), 2, 4.0),
            ((1.0, 6.0, 1.5), 3, 5.5),
            ((1.0, 6.0, 1.5), -1, 5.5),
            ((1.0, 6.0, 1.5), -2, 4.0),
            (
                (Decimal("1.0"), Decimal("9.0"), Decimal("1.5")),
                -1,
                Decimal("8.5"),
            ),
            (
                (Fraction(1, 1), Fraction(10, 1), Fraction(3, 2)),
                2,
                Fraction(4, 1),
            ),
            (
                (
                    datetime(2019, 3, 29),
                    datetime(2019, 3, 30),
                    timedelta(hours=10),
                ),
                1,
                datetime(2019, 3, 29, 10),
            ),
        ]:
            self.assertEqual(expected, mi.numeric_range(*args)[index])

        for args, index in [
            ((1.0, 6.0, 1.5), 4),
            ((1.0, 6.0, 1.5), -5),
            ((6.0, 1.0, 1.5), 0),
            ((6.0, 1.0, 1.5), -1),
            ((Decimal("1.0"), Decimal("9.0"), Decimal("-1.5")), -1),
            ((Fraction(1, 1), Fraction(2, 1), Fraction(3, 2)), 2),
            (
                (
                    datetime(2019, 3, 29),
                    datetime(2019, 3, 30),
                    timedelta(hours=10),
                ),
                8,
            ),
        ]:
            with self.assertRaises(IndexError):
                mi.numeric_range(*args)[index]

    def test_get_item_by_slice(self):
        for args, sl, expected_args in [
            ((1.0, 9.0, 1.5), slice(None, None, None), (1.0, 9.0, 1.5)),
            ((1.0, 9.0, 1.5), slice(None, 1, None), (1.0, 2.5, 1.5)),
            ((1.0, 9.0, 1.5), slice(None, None, 2), (1.0, 9.0, 3.0)),
            ((1.0, 9.0, 1.5), slice(None, 2, None), (1.0, 4.0, 1.5)),
            ((1.0, 9.0, 1.5), slice(1, 2, None), (2.5, 4.0, 1.5)),
            ((1.0, 9.0, 1.5), slice(1, -1, None), (2.5, 8.5, 1.5)),
            ((1.0, 9.0, 1.5), slice(10, None, 3), (9.0, 9.0, 4.5)),
            ((1.0, 9.0, 1.5), slice(-10, None, 3), (1.0, 9.0, 4.5)),
            ((1.0, 9.0, 1.5), slice(None, -10, 3), (1.0, 1.0, 4.5)),
            ((1.0, 9.0, 1.5), slice(None, 10, 3), (1.0, 9.0, 4.5)),
            (
                (10.0, 0.0, -2.0),
                slice(None, None, -1),
                (2.0, 12.0, 2.0),
            ),
            (
                (Decimal("1.0"), Decimal("9.0"), Decimal("1.5")),
                slice(1, -1, None),
                (Decimal("2.5"), Decimal("8.5"), Decimal("1.5")),
            ),
            (
                (Fraction(1, 1), Fraction(5, 1), Fraction(3, 2)),
                slice(1, -1, None),
                (Fraction(5, 2), Fraction(4, 1), Fraction(3, 2)),
            ),
            (
                (
                    datetime(2019, 3, 29),
                    datetime(2019, 3, 30),
                    timedelta(hours=10),
                ),
                slice(1, -1, None),
                (
                    datetime(2019, 3, 29, 10),
                    datetime(2019, 3, 29, 20),
                    timedelta(hours=10),
                ),
            ),
        ]:
            self.assertEqual(
                mi.numeric_range(*expected_args), mi.numeric_range(*args)[sl]
            )

    def test_hash(self):
        for args, expected in [
            ((1.0, 6.0, 1.5), hash((1.0, 5.5, 1.5))),
            ((1.0, 7.0, 1.5), hash((1.0, 5.5, 1.5))),
            ((1.0, 7.5, 1.5), hash((1.0, 7.0, 1.5))),
            ((1.0, 1.5, 1.5), hash((1.0, 1.0, 1.5))),
            ((1.5, 1.0, 1.5), hash(range(0, 0))),
            ((1.5, 1.5, 1.5), hash(range(0, 0))),
            (
                (Decimal("1.0"), Decimal("9.0"), Decimal("1.5")),
                hash((Decimal("1.0"), Decimal("8.5"), Decimal("1.5"))),
            ),
            (
                (Fraction(1, 1), Fraction(5, 1), Fraction(3, 2)),
                hash((Fraction(1, 1), Fraction(4, 1), Fraction(3, 2))),
            ),
            (
                (
                    datetime(2019, 3, 29),
                    datetime(2019, 3, 30),
                    timedelta(hours=10),
                ),
                hash(
                    (
                        datetime(2019, 3, 29),
                        datetime(2019, 3, 29, 20),
                        timedelta(hours=10),
                    )
                ),
            ),
        ]:
            self.assertEqual(expected, hash(mi.numeric_range(*args)))

    def test_iter_twice(self):
        r1 = mi.numeric_range(1.0, 9.9, 1.5)
        r2 = mi.numeric_range(8.5, 0.0, -1.5)
        self.assertEqual([1.0, 2.5, 4.0, 5.5, 7.0, 8.5], list(r1))
        self.assertEqual([1.0, 2.5, 4.0, 5.5, 7.0, 8.5], list(r1))
        self.assertEqual([8.5, 7.0, 5.5, 4.0, 2.5, 1.0], list(r2))
        self.assertEqual([8.5, 7.0, 5.5, 4.0, 2.5, 1.0], list(r2))

    def test_len(self):
        for args, expected in [
            ((1.0, 7.0, 1.5), 4),
            ((1.0, 7.01, 1.5), 5),
            ((7.0, 1.0, -1.5), 4),
            ((7.01, 1.0, -1.5), 5),
            ((0.1, 0.30000000000000001, 0.2), 1),  # IEE 754 !
            (
                (
                    Decimal("0.1"),
                    Decimal("0.30000000000000001"),
                    Decimal("0.2"),
                ),
                2,
            ),  # works with Decimal
            ((Decimal("1.0"), Decimal("9.0"), Decimal("1.5")), 6),
            ((Fraction(1, 1), Fraction(5, 1), Fraction(3, 2)), 3),
            (
                (
                    datetime(2019, 3, 29),
                    datetime(2019, 3, 30),
                    timedelta(hours=10),
                ),
                3,
            ),
        ]:
            self.assertEqual(expected, len(mi.numeric_range(*args)))

    def test_repr(self):
        for args, *expected in [
            ((7.0,), "numeric_range(0.0, 7.0)"),
            ((1.0, 7.0), "numeric_range(1.0, 7.0)"),
            ((7.0, 1.0, -1.5), "numeric_range(7.0, 1.0, -1.5)"),
            (
                (Decimal("1.0"), Decimal("9.0"), Decimal("1.5")),
                (
                    "numeric_range(Decimal('1.0'), Decimal('9.0'), "
                    "Decimal('1.5'))"
                ),
            ),
            (
                (Fraction(7, 7), Fraction(10, 2), Fraction(3, 2)),
                (
                    "numeric_range(Fraction(1, 1), Fraction(5, 1), "
                    "Fraction(3, 2))"
                ),
            ),
            (
                (
                    datetime(2019, 3, 29),
                    datetime(2019, 3, 30),
                    timedelta(hours=10),
                ),
                "numeric_range(datetime.datetime(2019, 3, 29, 0, 0), "
                "datetime.datetime(2019, 3, 30, 0, 0), "
                "datetime.timedelta(seconds=36000))",
                "numeric_range(datetime.datetime(2019, 3, 29, 0, 0), "
                "datetime.datetime(2019, 3, 30, 0, 0), "
                "datetime.timedelta(0, 36000))",
            ),
        ]:
            with self.subTest(args=args):
                self.assertIn(repr(mi.numeric_range(*args)), expected)

    def test_reversed(self):
        for args, expected in [
            ((7.0,), [6.0, 5.0, 4.0, 3.0, 2.0, 1.0, 0.0]),
            ((1.0, 7.0), [6.0, 5.0, 4.0, 3.0, 2.0, 1.0]),
            ((7.0, 1.0, -1.5), [2.5, 4.0, 5.5, 7.0]),
            ((7.0, 0.9, -1.5), [1.0, 2.5, 4.0, 5.5, 7.0]),
            (
                (Decimal("1.0"), Decimal("5.0"), Decimal("1.5")),
                [Decimal('4.0'), Decimal('2.5'), Decimal('1.0')],
            ),
            (
                (Fraction(1, 1), Fraction(5, 1), Fraction(3, 2)),
                [Fraction(4, 1), Fraction(5, 2), Fraction(1, 1)],
            ),
            (
                (
                    datetime(2019, 3, 29),
                    datetime(2019, 3, 30),
                    timedelta(hours=10),
                ),
                [
                    datetime(2019, 3, 29, 20),
                    datetime(2019, 3, 29, 10),
                    datetime(2019, 3, 29),
                ],
            ),
        ]:
            self.assertEqual(expected, list(reversed(mi.numeric_range(*args))))

    def test_count(self):
        for args, v, c in [
            ((7.0,), 0.0, 1),
            ((7.0,), 0.5, 0),
            ((7.0,), 6.0, 1),
            ((7.0,), 7.0, 0),
            ((7.0,), 10.0, 0),
            (
                (Decimal("1.0"), Decimal("5.0"), Decimal("1.5")),
                Decimal('4.0'),
                1,
            ),
            (
                (Fraction(1, 1), Fraction(5, 1), Fraction(3, 2)),
                Fraction(5, 2),
                1,
            ),
            (
                (
                    datetime(2019, 3, 29),
                    datetime(2019, 3, 30),
                    timedelta(hours=10),
                ),
                datetime(2019, 3, 29, 20),
                1,
            ),
        ]:
            self.assertEqual(c, mi.numeric_range(*args).count(v))

    def test_index(self):
        for args, v, i in [
            ((7.0,), 0.0, 0),
            ((7.0,), 6.0, 6),
            ((7.0, 0.0, -1.0), 7.0, 0),
            ((7.0, 0.0, -1.0), 1.0, 6),
            (
                (Decimal("1.0"), Decimal("5.0"), Decimal("1.5")),
                Decimal('4.0'),
                2,
            ),
            (
                (Fraction(1, 1), Fraction(5, 1), Fraction(3, 2)),
                Fraction(5, 2),
                1,
            ),
            (
                (
                    datetime(2019, 3, 29),
                    datetime(2019, 3, 30),
                    timedelta(hours=10),
                ),
                datetime(2019, 3, 29, 20),
                2,
            ),
        ]:
            self.assertEqual(i, mi.numeric_range(*args).index(v))

        for args, v in [
            ((0.7,), 0.5),
            ((0.7,), 7.0),
            ((0.7,), 10.0),
            ((7.0, 0.0, -1.0), 0.5),
            ((7.0, 0.0, -1.0), 0.0),
            ((7.0, 0.0, -1.0), 10.0),
            ((7.0, 0.0), 5.0),
            ((Decimal("1.0"), Decimal("5.0"), Decimal("1.5")), Decimal('4.5')),
            ((Fraction(1, 1), Fraction(5, 1), Fraction(3, 2)), Fraction(5, 3)),
            (
                (
                    datetime(2019, 3, 29),
                    datetime(2019, 3, 30),
                    timedelta(hours=10),
                ),
                datetime(2019, 3, 30),
            ),
        ]:
            with self.assertRaises(ValueError):
                mi.numeric_range(*args).index(v)

    def test_parent_classes(self):
        r = mi.numeric_range(7.0)
        self.assertTrue(isinstance(r, Iterable))
        self.assertFalse(isinstance(r, Iterator))
        self.assertTrue(isinstance(r, Sequence))
        self.assertTrue(isinstance(r, Hashable))

    def test_bad_key(self):
        r = mi.numeric_range(7.0)
        for arg, message in [
            ('a', 'numeric range indices must be integers or slices, not str'),
            (
                (),
                'numeric range indices must be integers or slices, not tuple',
            ),
        ]:
            with self.assertRaisesRegex(TypeError, message):
                r[arg]

    def test_pickle(self):
        for args in [
            (7.0,),
            (5.0, 7.0),
            (5.0, 7.0, 3.0),
            (7.0, 5.0),
            (7.0, 5.0, 4.0),
            (7.0, 5.0, -1.0),
            (Decimal("1.0"), Decimal("5.0"), Decimal("1.5")),
            (Fraction(1, 1), Fraction(5, 1), Fraction(3, 2)),
            (datetime(2019, 3, 29), datetime(2019, 3, 30)),
        ]:
            r = mi.numeric_range(*args)
            self.assertTrue(dumps(r))  # assert not empty
            self.assertEqual(r, loads(dumps(r)))

    def test_empty_reversed(self):
        self.assertEqual(list(reversed(mi.numeric_range(0))), [])
