from intervals import busy_minutes, merge


def test_overlapping() -> None:
    assert merge([(60, 90), (75, 100)]) == [(60, 100)]


def test_nested_booking() -> None:
    assert merge([(60, 180), (90, 120)]) == [(60, 180)]


def test_touching_bookings_merge() -> None:
    assert merge([(60, 90), (90, 120)]) == [(60, 120)]


def test_input_in_any_order() -> None:
    assert merge([(300, 360), (60, 90)]) == [(60, 90), (300, 360)]


def test_busy_minutes() -> None:
    assert busy_minutes([(540, 600), (570, 630)]) == 90
