"""Statistics over repeated attempts at the same tasks.

Each task runs n times. For each task, c of its n attempts pass.

- solve rate: c/n for one task, e.g. "2/3"
- pass rate per repeat: the share of tasks solved in repeat 1, in repeat 2, and so on,
  reported as their mean and standard deviation (the spread between whole runs)
- pass@1: the chance one attempt at a random task passes, the mean of c/n over tasks
- pass@k: the chance that at least one of k attempts passes, with the unbiased estimator
  1 - C(n-c, k) / C(n, k) (Chen et al., 2021), averaged over tasks
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable, Sequence
from math import comb


def pass_at_k(n: int, c: int, k: int) -> float:
    """Probability that at least one of k attempts (drawn from n with c passes) passes."""
    if not 0 <= c <= n or not 1 <= k <= n:
        raise ValueError(f"need 0 <= c <= n and 1 <= k <= n, got n={n}, c={c}, k={k}")
    if n - c < k:
        return 1.0  # every draw of k includes a pass
    return 1.0 - comb(n - c, k) / comb(n, k)


def mean_and_std(values: Sequence[float]) -> tuple[float, float]:
    """Mean and sample standard deviation (0 when there are fewer than two values)."""
    if not values:
        return 0.0, 0.0
    mean = statistics.fmean(values)
    return mean, statistics.stdev(values) if len(values) > 1 else 0.0


def solve_counts(outcomes: Iterable[tuple[str, bool]]) -> dict[str, tuple[int, int]]:
    """(passes, attempts) per task from (task_id, passed) pairs."""
    counts: dict[str, tuple[int, int]] = {}
    for task_id, passed in outcomes:
        c, n = counts.get(task_id, (0, 0))
        counts[task_id] = (c + int(passed), n + 1)
    return counts


def pass_at(counts: dict[str, tuple[int, int]], k: int) -> float:
    """Mean pass@k over tasks; a task with fewer than k attempts uses all it has."""
    if not counts:
        return 0.0
    return statistics.fmean(pass_at_k(n, c, min(k, n)) for c, n in counts.values())
