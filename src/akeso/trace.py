"""Traces: a JSON Lines record of everything that happened in one agent run.

Each line is one event, e.g. {"ts": "...", "event": "tool_call", "name": "read_file", ...}.
JSON Lines (one JSON object per line) can be appended to as the run goes, so a crash
still leaves everything up to that point on disk, and it's easy to read line by line.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from types import TracebackType
from typing import Any

DEFAULT_TRACE_DIR = Path("runs")


def new_run_id() -> str:
    """Sortable and unique: UTC timestamp plus a short random suffix, e.g. 20261005-142301-a1b2c3."""
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)


def trace_path(trace_dir: Path, run_id: str, task_id: str) -> Path:
    return trace_dir / run_id / f"{task_id}.jsonl"


class TraceWriter:
    """Appends one JSON object per event to a .jsonl file, flushing after every line."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._file = path.open("a", encoding="utf-8")

    def event(self, kind: str, **data: Any) -> None:
        record = {"ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"), "event": kind, **data}
        self._file.write(json.dumps(record, default=_to_json, ensure_ascii=False) + "\n")
        self._file.flush()  # so a crash still leaves every event written so far

    def close(self) -> None:
        self._file.close()

    def __enter__(self) -> TraceWriter:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


def read_trace(path: Path) -> list[dict[str, Any]]:
    """All events in a trace file, in order."""
    with path.open(encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


def _to_json(value: Any) -> Any:
    """json.dumps fallback for our own types."""
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, Path):
        return value.as_posix()
    raise TypeError(f"Can't write {type(value).__name__} to a trace")
