"""The run fingerprint: everything that has to match for two runs to be the same experiment.

Recorded in every run's summary.json. Two runs are comparable under the Measurement
rule (CLAUDE.md) only if their fingerprints agree on the provider, tier, model, model
settings, prompt version, limits, mode, sandbox image and frozen suite. The harness commit
and whether the working tree had uncommitted changes record exactly which code ran.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import asdict
from pathlib import Path
from typing import Any

from akeso.config import AgentLimits, Settings
from akeso.freeze import DEFAULT_MANIFEST, FreezeError, read_manifest
from akeso.prompts import prompt_version

# Fields that define the experiment. The harness commit and dirty flag are recorded but
# not part of it: a fix to, say, the report generator doesn't change what was measured.
EXPERIMENT_FIELDS = (
    "provider", "tier", "model", "model_settings", "prompt_version", "limits", "mode",
    "docker_image", "suite_freeze_fingerprint",
)


def collect(
    settings: Settings,
    limits: AgentLimits,
    *,
    mode: str = "loop",
    docker_image: str | None = None,
    manifest: str | Path = DEFAULT_MANIFEST,
    repo: str | Path = ".",
) -> dict[str, Any]:
    """The fingerprint of a run about to start with these settings."""
    commit, dirty = git_state(repo)
    return {
        "provider": settings.provider,
        "tier": settings.tier,
        "model": settings.model,
        "model_settings": asdict(settings.model_settings),
        "prompt_version": prompt_version(mode),
        "limits": asdict(limits),
        "mode": mode,
        "docker_image": docker_image,
        "suite_freeze_fingerprint": freeze_fingerprint(manifest),
        "harness_commit": commit,
        "harness_dirty": dirty,
    }


def experiment_key(fingerprint: dict[str, Any]) -> dict[str, Any]:
    """Just the fields that define the experiment."""
    return {name: fingerprint.get(name) for name in EXPERIMENT_FIELDS}


def differences(a: dict[str, Any], b: dict[str, Any], fields: tuple[str, ...] = EXPERIMENT_FIELDS) -> list[str]:
    """The named fields whose values differ between two fingerprints, e.g. ["model"]."""
    return [name for name in fields if a.get(name) != b.get(name)]


def digest(fingerprint: dict[str, Any]) -> str:
    """A short hash of the experiment fields, handy for labelling runs."""
    canonical = json.dumps(experiment_key(fingerprint), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def freeze_fingerprint(manifest: str | Path = DEFAULT_MANIFEST) -> str | None:
    try:
        return read_manifest(manifest)["fingerprint"]
    except FreezeError:
        return None


def git_state(repo: str | Path = ".") -> tuple[str | None, bool | None]:
    """(HEAD commit, whether the working tree has uncommitted changes), or Nones without git."""
    def git(*args: str) -> str | None:
        try:
            done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            return None
        return done.stdout if done.returncode == 0 else None

    commit = git("rev-parse", "HEAD")
    status = git("status", "--porcelain")
    return (commit.strip() if commit else None), (None if status is None else bool(status.strip()))
