"""Comparing two runs of the same suite: did B do better than A, and by more than noise?

Both runs must be of the same frozen suite (else there is nothing to compare). Any other
difference in their fingerprints (model, settings, mode, prompt, limits...) is reported as
a warning: often it is exactly what is being tested, but it must never go unnoticed.

The uncertainty in the pass-rate difference comes from a paired bootstrap over tasks:
resample the shared tasks with replacement many times, and take the 2.5th and 97.5th
percentiles of B's mean solve rate minus A's. Pairing (the same task drawn for both runs)
removes the task-to-task variation that both runs share.
"""

from __future__ import annotations

import random
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from akeso import fingerprint as run_fingerprint
from akeso.batch import read_summary

BOOTSTRAP_SAMPLES = 10_000
BOOTSTRAP_SEED = 0  # fixed, so the same two runs always give the same interval


class CompareError(Exception):
    """The two runs can't be compared."""


@dataclass(frozen=True)
class GroupComparison:
    """One group (overall, or one split) in both runs."""

    name: str
    tasks: int  # tasks present in both runs
    a: dict[str, Any]  # the group's totals in run A
    b: dict[str, Any]
    difference: float  # B's mean solve rate minus A's, over the shared tasks
    ci_low: float  # 95% bootstrap interval for that difference
    ci_high: float


@dataclass(frozen=True)
class TaskChange:
    task_id: str
    split: str | None
    a: str  # solve rate in run A, e.g. "1/3"
    b: str


@dataclass(frozen=True)
class Comparison:
    run_a: str
    run_b: str
    warnings: list[str]
    groups: list[GroupComparison]
    changed: list[TaskChange] = field(default_factory=list)


def compare_runs(run_a: str, run_b: str, runs_dir: str | Path) -> Comparison:
    """Compare run B against run A (both folders under runs_dir)."""
    a, b = (_load(run_id, Path(runs_dir)) for run_id in (run_a, run_b))
    return compare_summaries(a, b)


def compare_summaries(a: dict[str, Any], b: dict[str, Any]) -> Comparison:
    fa, fb = a.get("fingerprint") or {}, b.get("fingerprint") or {}
    if fa.get("suite_freeze_fingerprint") != fb.get("suite_freeze_fingerprint"):
        raise CompareError(
            f"the runs are of different suites (freeze fingerprint {fa.get('suite_freeze_fingerprint')!r} "
            f"vs {fb.get('suite_freeze_fingerprint')!r}), so their results can't be compared")
    warnings = [f"{name} differs: {fa.get(name)!r} in {a['run_id']}, {fb.get(name)!r} in {b['run_id']}"
                for name in run_fingerprint.differences(fa, fb) if name != "suite_freeze_fingerprint"]
    for run in (a, b):
        if run.get("complete") is False:
            warnings.append(f"{run['run_id']} is incomplete ({len(run.get('not_run', []))} attempt(s) not run)")
        if run.get("run_type") != "official":
            warnings.append(f"{run['run_id']} is a dev run, not an official one")

    rates_a, rates_b = _solve_rates(a), _solve_rates(b)
    splits = {r["task_id"]: r.get("split") for run in (a, b) for r in run.get("results", [])}
    shared = sorted(set(rates_a) & set(rates_b))
    only = sorted(set(rates_a) ^ set(rates_b))
    if only:
        warnings.append(f"{len(only)} task(s) appear in only one run and are left out of the difference: "
                        + ", ".join(only))

    groups = [_group("overall", shared, rates_a, rates_b, a["totals"], b["totals"])]
    for split in sorted({s for s in splits.values() if s}):
        in_split = [t for t in shared if splits.get(t) == split]
        totals_a = a["totals"].get("by_split", {}).get(split)
        totals_b = b["totals"].get("by_split", {}).get(split)
        if in_split and totals_a and totals_b:
            groups.append(_group(split, in_split, rates_a, rates_b, totals_a, totals_b))

    sa, sb = a["totals"].get("solve_rates", {}), b["totals"].get("solve_rates", {})
    changed = [TaskChange(t, splits.get(t), sa[t], sb[t]) for t in shared if rates_a[t] != rates_b[t]]
    return Comparison(a["run_id"], b["run_id"], warnings, groups, changed)


def bootstrap_difference(
    pairs: list[tuple[float, float]], samples: int = BOOTSTRAP_SAMPLES, seed: int = BOOTSTRAP_SEED,
) -> tuple[float, float, float]:
    """(observed mean of b - a, 2.5th percentile, 97.5th percentile), resampling the pairs."""
    if not pairs:
        return 0.0, 0.0, 0.0
    diffs = [b - a for a, b in pairs]
    observed = statistics.fmean(diffs)
    rng = random.Random(seed)
    n = len(diffs)
    means = sorted(statistics.fmean(rng.choices(diffs, k=n)) for _ in range(samples))
    return observed, means[int(0.025 * (samples - 1))], means[int(0.975 * (samples - 1))]


def _group(name: str, tasks: list[str], rates_a: dict[str, float], rates_b: dict[str, float],
           totals_a: dict[str, Any], totals_b: dict[str, Any]) -> GroupComparison:
    difference, low, high = bootstrap_difference([(rates_a[t], rates_b[t]) for t in tasks])
    return GroupComparison(name, len(tasks), totals_a, totals_b, difference, low, high)


def _solve_rates(summary: dict[str, Any]) -> dict[str, float]:
    """Each task's share of passing attempts."""
    rates = {}
    for task_id, rate in summary["totals"].get("solve_rates", {}).items():
        passed, attempts = (int(part) for part in rate.split("/"))
        rates[task_id] = passed / attempts if attempts else 0.0
    return rates


def _load(run_id: str, runs_dir: Path) -> dict[str, Any]:
    try:
        return read_summary(runs_dir / run_id)
    except (OSError, ValueError) as problem:
        raise CompareError(f"no readable summary for run {run_id!r} in {runs_dir / run_id}") from problem
