"""Basic statistics helpers."""


def mean(numbers: list[float]) -> float:
    """Return the arithmetic mean of a non-empty list of numbers."""
    total = sum(numbers)
    return total / len(numbers)
