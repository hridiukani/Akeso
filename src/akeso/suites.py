"""Suites: named lists of task ids, stored as suites/<name>.yaml.

A suite file is a plain YAML list:

    - c001_mean
    - c002_shipping
"""

from __future__ import annotations

from pathlib import Path

import yaml

DEFAULT_SUITES_DIR = Path("suites")


class SuiteError(Exception):
    """A suite is missing or malformed. The message says which file and what's wrong."""


def load_suite(name: str, suites_dir: str | Path = DEFAULT_SUITES_DIR) -> list[str]:
    """The task ids in suites/<name>.yaml, in order."""
    folder = Path(suites_dir)
    path = folder / f"{name}.yaml"
    if not path.is_file():
        available = ", ".join(sorted(p.stem for p in folder.glob("*.yaml"))) or "none"
        raise SuiteError(f"No suite named {name!r} (looked for {path}). Available suites: {available}.")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as problem:
        raise SuiteError(f"{path}: not valid YAML ({problem}).") from None
    if not isinstance(data, list) or not data or not all(isinstance(item, str) and item.strip() for item in data):
        raise SuiteError(f"{path}: must be a non-empty YAML list of task ids.")
    duplicates = sorted({item for item in data if data.count(item) > 1})
    if duplicates:
        raise SuiteError(f"{path}: task ids listed more than once: {', '.join(duplicates)}.")
    return [item.strip() for item in data]
