"""Shared datasets for SQL tasks: a schema plus a seeded generator, used by many tasks.

A dataset lives in tasks/datasets/<name>/:
    schema.sql    the tables (the agent sees this)
    generate.py   populate(conn, seed): fills the schema, deterministically for a seed
    README.md     notes for task authors

Databases are built on the host and copied into the sandbox, so the generator (and with
it any hidden seed) never enters a container.
"""

from __future__ import annotations

import importlib.util
import sqlite3
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DATASETS_FOLDER = "datasets"  # next to the task kinds: tasks/datasets/<name>
SCHEMA_FILE = "schema.sql"
GENERATOR_FILE = "generate.py"


class DatasetError(Exception):
    """A dataset is missing, incomplete, or its generator failed."""


@dataclass(frozen=True)
class Dataset:
    name: str
    root: Path

    @property
    def schema(self) -> str:
        return (self.root / SCHEMA_FILE).read_text(encoding="utf-8")

    def files(self) -> list[Path]:
        """Every file that defines this dataset (for hashing: a change here changes every task using it)."""
        return sorted(p for p in self.root.rglob("*") if p.is_file() and "__pycache__" not in p.parts)

    def table_names(self) -> list[str]:
        """The tables the schema creates, sorted."""
        conn = sqlite3.connect(":memory:")
        try:
            conn.executescript(self.schema)
            return [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
        finally:
            conn.close()

    def build(self, seed: int) -> bytes:
        """The database for this seed, as SQLite file bytes. Same seed, same bytes."""
        return _build(self.root.resolve(), seed)


def load_dataset(name: str, datasets_root: Path) -> Dataset:
    root = datasets_root / name
    missing = [f for f in (SCHEMA_FILE, GENERATOR_FILE) if not (root / f).is_file()]
    if missing:
        raise DatasetError(f"Dataset {name!r} at {root} is missing {', '.join(missing)}.")
    return Dataset(name=name, root=root)


@lru_cache(maxsize=16)  # tasks share datasets and seeds; building takes a moment
def _build(root: Path, seed: int) -> bytes:
    spec = importlib.util.spec_from_file_location(f"akeso_dataset_{root.name}", root / GENERATOR_FILE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript((root / SCHEMA_FILE).read_text(encoding="utf-8"))
        module.populate(conn, seed)
        conn.commit()
        return conn.serialize()
    except Exception as problem:
        raise DatasetError(f"Generating dataset {root.name!r} with seed {seed} failed: {problem}") from problem
    finally:
        conn.close()
