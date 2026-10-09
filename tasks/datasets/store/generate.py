"""Fill the store schema with realistic, deterministic data from a seed.

Same seed, same data (byte for byte). Orders run from 2025-01-01 to 2026-09-30 and the
data deliberately includes what real store data has:
- NULL cities, NULL discounts, and refunds that haven't been processed (NULL amount)
- a product category nobody buys from (gift cards)
- order lines returned in two parts, on different days
- products with the same price, and small quantities, so unit counts often tie
- one month (between 2025-08 and 2026-05, chosen by the seed) with no orders at all:
  the store was closed for a refit
- order status histories (placed, paid, shipped, delivered, or cancelled) whose
  alphabetical order is not their time order
- timestamps at 00:00:00 and 23:59:59, and on the first and last day of months
"""

from __future__ import annotations

import random
import sqlite3
from datetime import date, datetime, timedelta

FIRST_DAY = date(2025, 1, 1)
LAST_DAY = date(2026, 9, 30)

# product_id, name, category, price
PRODUCTS = [
    (1, "Wireless earbuds", "Electronics", 59.0),
    (2, "USB-C charger", "Electronics", 25.0),
    (3, "Phone stand", "Electronics", 25.0),
    (4, "Bluetooth speaker", "Electronics", 89.0),
    (5, "Desk lamp", "Home", 39.0),
    (6, "Scented candle", "Home", 15.0),
    (7, "Throw blanket", "Home", 49.0),
    (8, "Plant pot", "Home", 15.0),
    (9, "Cookbook", "Books", 28.0),
    (10, "Travel guide", "Books", 22.0),
    (11, "Mystery novel", "Books", 14.0),
    (12, "Poetry collection", "Books", 14.0),
    (13, "Puzzle 1000 pieces", "Toys", 19.0),
    (14, "Building blocks", "Toys", 45.0),
    (15, "Plush bear", "Toys", 19.0),
    (16, "Notebook set", "Stationery", 12.0),
    (17, "Fountain pen", "Stationery", 35.0),
    (18, "Gel pens", "Stationery", 8.0),
    (19, "Gift card $25", "Gift cards", 25.0),  # nobody buys these: an empty category
    (20, "Gift card $50", "Gift cards", 50.0),
]
SELLABLE = [p for p in PRODUCTS if p[2] != "Gift cards"]
# Some products sell more often, but not so much that ties become rare.
WEIGHTS = [3, 4, 4, 2, 3, 4, 2, 4, 3, 2, 3, 3, 3, 2, 3, 4, 2, 4]
CITIES = ["London", "Manchester", "Leeds", "Bristol", "Glasgow", "Cardiff", "Belfast"]
FIRST_NAMES = ["Alex", "Bea", "Cai", "Dev", "Ema", "Finn", "Gus", "Ines", "Jae", "Kit", "Lou", "Mo", "Noor", "Ola"]
LAST_NAMES = ["Adams", "Bell", "Chen", "Doyle", "Ellis", "Ford", "Grant", "Hale", "Iqbal", "Jones", "Khan", "Lowe"]
CLOSED_MONTHS = [(2025, m) for m in range(8, 13)] + [(2026, m) for m in range(1, 6)]


def populate(conn: sqlite3.Connection, seed: int) -> None:
    """Insert all rows. The schema must already exist."""
    rng = random.Random(seed)
    closed = rng.choice(CLOSED_MONTHS)
    conn.executemany("INSERT INTO products VALUES (?, ?, ?, ?)", PRODUCTS)

    customers, orders, items, returns, events = [], [], [], [], []
    for customer_id in range(1, rng.randint(130, 160) + 1):
        joined = _moment(rng, FIRST_DAY, LAST_DAY - timedelta(days=60))
        city = None if rng.random() < 0.12 else rng.choice(CITIES)
        customers.append((customer_id, f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}", city, _stamp(joined)))
        for _ in range(rng.choice([0, 1, 2, 3, 4, 5, 6, 8, 10, 12])):
            placed = _moment(rng, joined.date(), LAST_DAY)
            if (placed.year, placed.month) == closed:
                continue  # the store was closed that month
            order_id = len(orders) + 1
            orders.append((order_id, customer_id, _stamp(placed)))
            for product in _pick(rng):
                quantity = rng.choice([1, 1, 1, 2, 2, 3])
                discount = None if rng.random() < 0.75 else rng.choice([0.1, 0.2, 0.25])
                items.append((order_id, product[0], quantity, product[3], discount))
                if rng.random() < 0.1:
                    returns.extend(_returns(rng, order_id, product[0], quantity, product[3], discount, placed))
            events.extend(_events(rng, order_id, placed))

    conn.executemany("INSERT INTO customers VALUES (?, ?, ?, ?)", customers)
    conn.executemany("INSERT INTO orders VALUES (?, ?, ?)", orders)
    conn.executemany("INSERT INTO order_items VALUES (?, ?, ?, ?, ?)", items)
    returns.sort(key=lambda r: (r[2], r[0], r[1]))
    conn.executemany("INSERT INTO returns VALUES (?, ?, ?, ?, ?, ?)", [(i, *r) for i, r in enumerate(returns, start=1)])
    events.sort(key=lambda e: (e[2], e[0]))
    conn.executemany("INSERT INTO order_events VALUES (?, ?, ?, ?)", [(i, *e) for i, e in enumerate(events, start=1)])
    conn.commit()


def _pick(rng: random.Random) -> list[tuple]:
    """1 to 4 different products for one order."""
    chosen: list[tuple] = []
    for _ in range(rng.choice([1, 1, 2, 2, 3, 4])):
        product = rng.choices(SELLABLE, weights=WEIGHTS)[0]
        if product not in chosen:
            chosen.append(product)
    return chosen


def _returns(rng: random.Random, order_id: int, product_id: int, quantity: int, price: float,
             discount: float | None, placed: datetime) -> list[tuple]:
    """One or two return rows for an order line; some refunds aren't processed yet."""
    paid_each = price * (1 - (discount or 0))
    returned = rng.randint(1, quantity)
    parts = [returned] if returned < 2 or rng.random() < 0.5 else [1, returned - 1]
    rows, when = [], placed
    for part in parts:
        when = when + timedelta(days=rng.randint(3, 20), seconds=rng.randint(0, 86399))
        if when.date() > LAST_DAY:
            break
        refund = None if rng.random() < 0.2 else round(part * paid_each, 2)
        rows.append((order_id, product_id, _stamp(when), part, refund))
    return rows


def _events(rng: random.Random, order_id: int, placed: datetime) -> list[tuple]:
    """The order's status history, cut off at LAST_DAY."""
    history = [("placed", placed)]
    when = placed + timedelta(minutes=rng.randint(1, 90))
    if rng.random() < 0.04:
        history.append(("cancelled", when))  # cancelled before paying
    else:
        history.append(("paid", when))
        if rng.random() < 0.05:
            history.append(("cancelled", when + timedelta(hours=rng.randint(1, 30))))
        else:
            when += timedelta(days=rng.randint(1, 3), seconds=rng.randint(0, 3600))
            history.append(("shipped", when))
            history.append(("delivered", when + timedelta(days=rng.randint(1, 6), seconds=rng.randint(0, 3600))))
    return [(order_id, status, _stamp(at)) for status, at in history if at.date() <= LAST_DAY]


def _moment(rng: random.Random, first: date, last: date) -> datetime:
    day = first + timedelta(days=rng.randint(0, max((last - first).days, 0)))
    roll = rng.random()
    if roll < 0.06:
        offset = timedelta(0)
    elif roll < 0.12:
        offset = timedelta(hours=23, minutes=59, seconds=59)
    else:
        offset = timedelta(seconds=rng.randint(0, 86399))
    return datetime.combine(day, datetime.min.time()) + offset


def _stamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%d %H:%M:%S")
