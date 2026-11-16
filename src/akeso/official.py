"""Official runs: the only runs whose numbers get reported (CLAUDE.md, Measurement rule).

An official run must use the measurement setup (provider, tier, model and the default
pinned settings and limits), the frozen suite unmodified, and a clean working tree, so the
exact code is known. `akeso run --official` checks all of this before spending anything,
and shows an estimate of the tokens and cost for confirmation.
"""

from __future__ import annotations

import json
import statistics
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from akeso.config import PRICES, AgentLimits, ModelSettings, Settings
from akeso.freeze import FreezeCheck

# The measurement setup. Defaults for model settings and limits are part of it, so an
# official run can't be quietly shortened or re-tuned through .env.
MEASUREMENT_PROVIDER = "groq"
MEASUREMENT_TIER = "developer"
MEASUREMENT_MODEL = "openai/gpt-oss-120b"
MEASUREMENT_MODEL_SETTINGS = ModelSettings()
MEASUREMENT_LIMITS = AgentLimits()
# Attempts per task in an official run, unless --repeats says otherwise: enough to see the
# spread between runs, at three times the cost of one.
OFFICIAL_REPEATS = 3

# Without earlier runs of a task to go on, assume a typical attempt (the calibration
# averaged about 20,000 tokens per task, roughly 90% of them input).
FALLBACK_INPUT_TOKENS = 18_000
FALLBACK_OUTPUT_TOKENS = 2_000
# One-shot attempts are one call: about 1,600 tokens each in the free-tier rehearsal.
FALLBACK_ONESHOT_INPUT_TOKENS = 1_500
FALLBACK_ONESHOT_OUTPUT_TOKENS = 600


def official_problems(
    settings: Settings,
    limits: AgentLimits,
    freeze_check: FreezeCheck | None,
    fingerprint: dict[str, Any],
    *,
    allow_modified: bool = False,
    overrides: Sequence[str] = (),
) -> list[str]:
    """Every reason this run can't be official (empty when it can)."""
    problems = []
    if settings.provider != MEASUREMENT_PROVIDER:
        problems.append(f"the provider is {settings.provider!r}; official runs use {MEASUREMENT_PROVIDER!r} (PROVIDER)")
    if settings.tier != MEASUREMENT_TIER:
        problems.append(f"the Groq tier is {settings.tier!r}; official runs need the {MEASUREMENT_TIER!r} tier (GROQ_TIER)")
    if settings.model != MEASUREMENT_MODEL:
        problems.append(f"the model is {settings.model!r}; official runs use {MEASUREMENT_MODEL!r}")
    for option in overrides:
        problems.append(f"{option} can't be used with --official: official runs use the measurement settings")
    if settings.model_settings != MEASUREMENT_MODEL_SETTINGS:
        problems.append(f"model settings {_changed(asdict(settings.model_settings), asdict(MEASUREMENT_MODEL_SETTINGS))} "
                        "differ from the measurement settings (MODEL_* in .env)")
    if limits != MEASUREMENT_LIMITS:
        problems.append(f"limits {_changed(asdict(limits), asdict(MEASUREMENT_LIMITS))} differ from the "
                        "measurement limits (AGENT_* in .env)")
    if freeze_check is None:
        problems.append("the suite isn't frozen (no manifest); see FREEZE.md")
    elif not freeze_check.ok:
        problems.append(f"{len(freeze_check.modified)} task file(s) changed since the freeze")
    if allow_modified:
        problems.append("--allow-modified can't be used with --official")
    if fingerprint.get("harness_commit") is None:
        problems.append("the harness commit is unknown (is this a git checkout?)")
    if fingerprint.get("harness_dirty") is not False:
        problems.append("the working tree has uncommitted changes; commit or stash them first")
    if fingerprint.get("docker_image") is None:
        problems.append("the Docker sandbox image isn't available")
    return problems


def _changed(actual: dict[str, Any], expected: dict[str, Any]) -> str:
    return ", ".join(f"{name}={actual[name]!r} (expected {expected[name]!r})"
                     for name in expected if actual.get(name) != expected[name])


@dataclass(frozen=True)
class Estimate:
    input_tokens: int
    output_tokens: int
    cost_usd: float
    tasks_with_history: int  # tasks whose estimate comes from earlier runs
    tasks: int

    @property
    def tokens(self) -> int:
        return self.input_tokens + self.output_tokens


def estimate(
    task_ids: Sequence[str], model: str, runs_dir: str | Path, repeats: int = 1, mode: str = "loop",
) -> Estimate:
    """Expected tokens and cost: each task's median from earlier runs in the same mode in
    runs_dir (any model, since this only sizes the attempt), or a typical attempt without
    history. Cost assumes no cache hits, so it errs high."""
    history = _history(Path(runs_dir), mode)
    fallback_in, fallback_out = ((FALLBACK_ONESHOT_INPUT_TOKENS, FALLBACK_ONESHOT_OUTPUT_TOKENS) if mode == "oneshot"
                                 else (FALLBACK_INPUT_TOKENS, FALLBACK_OUTPUT_TOKENS))
    price = PRICES[model]
    total_in = total_out = known = 0
    for task_id in task_ids:
        runs = history.get(task_id)
        if runs:
            known += 1
            total_in += int(statistics.median(r[0] for r in runs))
            total_out += int(statistics.median(r[1] for r in runs))
        else:
            total_in += fallback_in
            total_out += fallback_out
    total_in, total_out = total_in * repeats, total_out * repeats
    cost = (total_in * price.input_per_mtok + total_out * price.output_per_mtok) / 1_000_000
    return Estimate(total_in, total_out, cost, known, len(task_ids))


def _history(runs_dir: Path, mode: str = "loop") -> dict[str, list[tuple[int, int]]]:
    """(input, output) tokens of every recorded attempt per task in runs of this mode (runs
    from before modes existed were loop runs), skipping attempts that never reached the
    model (crashes, quota errors)."""
    found: dict[str, list[tuple[int, int]]] = {}
    for path in sorted(runs_dir.glob("*/summary.json")):
        try:
            summary = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if (summary.get("mode") or "loop") != mode:
            continue
        for r in summary.get("results", []):
            if r.get("steps", 0) > 0 and r.get("input_tokens", 0) > 0:
                found.setdefault(r["task_id"], []).append((r["input_tokens"], r["output_tokens"]))
    return found
