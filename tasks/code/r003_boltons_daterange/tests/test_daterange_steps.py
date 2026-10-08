"""Minimal reproduction of the bug report, plus steps that already work."""

from datetime import date

from boltons.timeutils import daterange


def test_one_year_steps_from_late_december() -> None:
    dates = list(daterange(date(2012, 12, 25), date(2016, 1, 1), step=(1, 0, 0)))
    assert dates == [date(2012, 12, 25), date(2013, 12, 25), date(2014, 12, 25), date(2015, 12, 25)]


def test_thirteen_month_steps() -> None:
    dates = list(daterange(date(2012, 12, 25), date(2016, 1, 1), step=(0, 13, 0)))
    assert dates == [date(2012, 12, 25), date(2014, 1, 25), date(2015, 2, 25)]


def test_day_steps() -> None:
    assert list(daterange(date(2020, 1, 1), date(2020, 1, 4))) == [date(2020, 1, 1), date(2020, 1, 2), date(2020, 1, 3)]
