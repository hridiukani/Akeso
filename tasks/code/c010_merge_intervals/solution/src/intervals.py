"""Merging time ranges for the room-booking calendar."""

Interval = tuple[int, int]  # (start, end) in minutes since midnight; start <= end


def merge(intervals: list[Interval]) -> list[Interval]:
    """Merge overlapping or touching intervals. Returns them sorted by start."""
    merged: list[Interval] = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def busy_minutes(intervals: list[Interval]) -> int:
    """Total minutes covered by at least one interval."""
    return sum(end - start for start, end in merge(intervals))
