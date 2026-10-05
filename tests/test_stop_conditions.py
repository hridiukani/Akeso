"""Tests for check-output normalisation and repeated-failure detection."""

import pytest

from akeso.agent import RepeatedFailureDetector
from akeso.checks import normalize_check_output

FAILURE_RUN_1 = """\
F..                                                                      [100%]
=================================== FAILURES ===================================
_______________________________ test_mean ______________________________________
E       AssertionError: assert <Stats object at 0x7f3a2b1c90d0> == 4
/tmp/pytest-of-agent/pytest-12/test_mean0/data.txt
=========================== short test summary info ============================
FAILED tests/test_stats.py::test_mean - assert 6.0 == 4
\x1b[31m1 failed, 2 passed in 0.05s\x1b[0m
"""

# The same failure on another run: different timing, address, temp dir, colours, trailing spaces.
FAILURE_RUN_2 = """\
F..                                                                      [100%]
=================================== FAILURES ===================================
_______________________________ test_mean ______________________________________
E       AssertionError: assert <Stats object at 0x7f99aa001234> == 4
/tmp/pytest-of-agent/pytest-13/test_mean0/data.txt
=========================== short test summary info ============================
FAILED tests/test_stats.py::test_mean - assert 6.0 == 4
1 failed, 2 passed in 1.32s (0:00:01)
"""

# A genuinely different failure: the model's edit changed the result.
DIFFERENT_FAILURE = FAILURE_RUN_1.replace("assert 6.0 == 4", "assert 3.0 == 4")


# --- normalisation ---


def test_same_failure_on_different_runs_normalises_identically() -> None:
    assert normalize_check_output(FAILURE_RUN_1) == normalize_check_output(FAILURE_RUN_2)


def test_different_failures_stay_different() -> None:
    assert normalize_check_output(FAILURE_RUN_1) != normalize_check_output(DIFFERENT_FAILURE)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1 failed in 0.05s", "1 failed in <time>"),
        ("1 failed in 12.3s (0:00:12)", "1 failed in <time>"),
        ("0.12s call     tests/test_x.py::test_slow", "<time> call     tests/test_x.py::test_slow"),
        ("<object at 0xDEADbeef42>", "<object at 0x<addr>>"),
        ("/tmp/pytest-of-agent/pytest-7/x", "/tmp/pytest-of-<user>/pytest-<n>/x"),
        ("C:\\Temp\\repair-agent-k3j_9x\\src", "C:\\Temp\\repair-agent-<tmp>\\src"),
        ("[... 1234 characters trimmed ...]\nE  boom", "[... characters trimmed ...]\nE  boom"),
        ("\x1b[1m\x1b[31mFAILED\x1b[0m", "FAILED"),
        ("  line with trailing spaces   \n\n", "line with trailing spaces"),
    ],
)
def test_normalisation_rules(raw: str, expected: str) -> None:
    assert normalize_check_output(raw) == expected


def test_assertion_values_are_not_mistaken_for_noise() -> None:
    # Numbers that matter (the actual vs expected values) must survive normalisation.
    assert "assert 6.0 == 4" in normalize_check_output("E   assert 6.0 == 4")


# --- repeated-failure detection ---


def test_stops_after_limit_identical_failures_in_a_row() -> None:
    detector = RepeatedFailureDetector(limit=3)

    assert detector.record(False, FAILURE_RUN_1) is False
    assert detector.record(False, FAILURE_RUN_2) is False  # same failure, different noise
    assert detector.record(False, FAILURE_RUN_1) is True


def test_a_different_failure_resets_the_count() -> None:
    detector = RepeatedFailureDetector(limit=3)
    detector.record(False, FAILURE_RUN_1)
    detector.record(False, FAILURE_RUN_1)

    assert detector.record(False, DIFFERENT_FAILURE) is False  # progress of a kind: count restarts
    assert detector.record(False, DIFFERENT_FAILURE) is False
    assert detector.record(False, DIFFERENT_FAILURE) is True


def test_a_pass_resets_the_count() -> None:
    detector = RepeatedFailureDetector(limit=2)
    detector.record(False, FAILURE_RUN_1)

    assert detector.record(True, "3 passed in 0.01s") is False
    assert detector.record(False, FAILURE_RUN_1) is False  # counting starts again from 1


def test_limit_of_two() -> None:
    detector = RepeatedFailureDetector(limit=2)

    assert detector.record(False, FAILURE_RUN_1) is False
    assert detector.record(False, FAILURE_RUN_2) is True
