"""Fill the SaaS schema with realistic, deterministic data from a seed.

Same seed, same data (byte for byte). The data covers 2025-01-01 to 2026-09-30 and
deliberately includes what real billing data has:
- NULL emails and countries, and customers who never subscribe or never pay
- plan changes part-way through a billing period (a prorated charge on the change day)
- failed payments, retries a few days later, and refunds
- discounted amounts, so sums of money aren't round numbers
- timestamps right at day and month boundaries (00:00:00 and 23:59:59, the 1st and the
  last day of a month)
- a plan nobody is on
"""

from __future__ import annotations

import calendar
import random
import sqlite3
from datetime import date, datetime, timedelta

FIRST_DAY = date(2025, 1, 1)
LAST_DAY = date(2026, 9, 30)  # nothing happens after this day

# plan_id, name, billing_period, price, weight when a customer picks a plan
PLANS = [
    (1, "Starter", "monthly", 19.0, 40),
    (2, "Pro", "monthly", 49.0, 30),
    (3, "Business", "monthly", 129.0, 12),
    (4, "Pro Annual", "annual", 490.0, 13),
    (5, "Enterprise", "monthly", 1490.0, 5),
    (6, "Legacy Basic", "monthly", 9.0, 0),  # retired: nobody is on it
]
COUNTRIES = ["US", "US", "US", "GB", "DE", "IN", "BR", "CA", "FR", "AU"]
FIRST_NAMES = ["Ana", "Ben", "Chen", "Dara", "Eli", "Fatima", "Goran", "Hana", "Ivan", "Jo",
               "Kofi", "Lena", "Mateo", "Nia", "Omar", "Priya", "Quinn", "Rosa", "Sam", "Tariq"]
LAST_NAMES = ["Abara", "Berg", "Costa", "Dubois", "Evans", "Fischer", "Garcia", "Haddad",
              "Ito", "Jensen", "Khan", "Lopez", "Moreau", "Nowak", "Okafor", "Patel"]


def populate(conn: sqlite3.Connection, seed: int) -> None:
    """Insert all rows. The schema must already exist."""
    rng = random.Random(seed)
    conn.executemany("INSERT INTO plans VALUES (?, ?, ?, ?)", [p[:4] for p in PLANS])

    customers, subscriptions, payments = [], [], []
    for customer_id in range(1, rng.randint(140, 180) + 1):
        signed_up = _random_moment(rng, FIRST_DAY, LAST_DAY - timedelta(days=45))
        first, last = rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
        email = None if rng.random() < 0.06 else f"{first}.{last}{customer_id}@example.com".lower()
        country = None if rng.random() < 0.10 else rng.choice(COUNTRIES)
        customers.append((customer_id, f"{first} {last}", email, country, _stamp(signed_up)))

        if rng.random() < 0.15:
            continue  # signed up but never subscribed (so never paid)
        start = signed_up.date() + timedelta(days=rng.choice([0, 0, 0, 1, 3, 7, 14, 30]))
        if rng.random() < 0.2:  # many people start on the 1st or the last day of a month
            start = _snap_to_month_edge(rng, start)
        if start > LAST_DAY:
            continue
        plan = _pick_plan(rng)
        discounted = rng.random() < 0.1  # 20% off the first three charges

        # Plan changes and cancellations (some customers do both, in that order).
        periods = []  # (plan, start, end, end_reason)
        change_day = start + timedelta(days=rng.randint(10, 300)) if rng.random() < 0.25 else None
        if change_day and change_day <= LAST_DAY:
            periods.append((plan, start, change_day, "plan_change"))
            plan = _pick_plan(rng, other_than=plan)
            start = change_day
        cancel_day = start + timedelta(days=rng.randint(20, 400)) if rng.random() < 0.2 else None
        if cancel_day and cancel_day <= LAST_DAY:
            periods.append((plan, start, cancel_day, "cancelled"))
        else:
            periods.append((plan, start, None, None))

        charges_so_far = 0
        previous = None  # (plan, start) of the period being replaced, for proration
        for plan, begin, end, reason in periods:
            subscription_id = len(subscriptions) + 1
            subscriptions.append((subscription_id, customer_id, plan[0], begin.isoformat(),
                                  end.isoformat() if end else None, reason))
            for index, day in enumerate(_billing_days(begin, end, plan[2])):
                amount = plan[3]
                if index == 0 and previous is not None:
                    amount = _prorated(previous, plan, begin)
                    if amount <= 0:
                        continue  # a downgrade's credit covers the first charge
                if discounted and charges_so_far < 3:
                    amount *= 0.8
                charges_so_far += 1
                payments.extend(_charge(rng, subscription_id, customer_id, day, round(amount, 2)))
            previous = (plan, begin)

    conn.executemany("INSERT INTO customers VALUES (?, ?, ?, ?, ?)", customers)
    conn.executemany("INSERT INTO subscriptions VALUES (?, ?, ?, ?, ?, ?)", subscriptions)
    payments.sort(key=lambda p: (p[2], p[0], p[1]))  # in time order, like a real ledger
    conn.executemany("INSERT INTO payments VALUES (?, ?, ?, ?, ?, ?)",
                     [(i, *p) for i, p in enumerate(payments, start=1)])
    conn.commit()


def _pick_plan(rng: random.Random, other_than: tuple | None = None) -> tuple:
    choices = [p for p in PLANS if p[4] and p is not other_than]
    return rng.choices(choices, weights=[p[4] for p in choices])[0]


def _random_moment(rng: random.Random, first: date, last: date) -> datetime:
    day = first + timedelta(days=rng.randint(0, (last - first).days))
    return datetime.combine(day, datetime.min.time()) + _time_of_day(rng)


def _time_of_day(rng: random.Random) -> timedelta:
    """Mostly random, but often exactly at the start or the end of the day."""
    roll = rng.random()
    if roll < 0.08:
        return timedelta(0)  # 00:00:00
    if roll < 0.16:
        return timedelta(hours=23, minutes=59, seconds=59)
    return timedelta(seconds=rng.randint(0, 86399))


def _snap_to_month_edge(rng: random.Random, day: date) -> date:
    if rng.random() < 0.5:
        return day.replace(day=1)
    return day.replace(day=calendar.monthrange(day.year, day.month)[1])


def _add_months(day: date, months: int, anchor_day: int) -> date:
    """The same day of the month `months` later, clamped to that month's length (Jan 31 -> Feb 28)."""
    year, month = divmod(day.year * 12 + day.month - 1 + months, 12)
    return date(year, month + 1, min(anchor_day, calendar.monthrange(year, month + 1)[1]))


def _billing_days(start: date, end: date | None, period: str) -> list[date]:
    """Charge days from start up to (not including) end, and never after LAST_DAY."""
    step = 1 if period == "monthly" else 12
    days = []
    while True:
        day = _add_months(start, len(days) * step, start.day)
        if day > LAST_DAY or (end is not None and day >= end):
            return days
        days.append(day)


def _prorated(previous: tuple, plan: tuple, change_day: date) -> float:
    """The new plan's price minus credit for the unused part of the old plan's current period."""
    old_plan, old_start = previous
    step = 1 if old_plan[2] == "monthly" else 12
    n = 0
    while _add_months(old_start, (n + 1) * step, old_start.day) <= change_day:
        n += 1
    period_start = _add_months(old_start, n * step, old_start.day)
    period_end = _add_months(old_start, (n + 1) * step, old_start.day)
    unused = (period_end - change_day).days / (period_end - period_start).days
    return plan[3] - old_plan[3] * unused


def _charge(rng: random.Random, subscription_id: int, customer_id: int, day: date, amount: float) -> list[tuple]:
    """One billing attempt, plus one retry three days later if it fails. Some succeed and are later refunded."""
    attempts = []
    when = datetime.combine(day, datetime.min.time()) + _time_of_day(rng)
    for _ in range(2):
        if when.date() > LAST_DAY:
            break
        roll = rng.random()
        status = "failed" if roll < 0.06 else "refunded" if roll < 0.08 else "succeeded"
        attempts.append((subscription_id, customer_id, _stamp(when), amount, status))
        if status != "failed":
            break
        when += timedelta(days=3, seconds=rng.randint(0, 3600))
    return attempts


def _stamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%d %H:%M:%S")
