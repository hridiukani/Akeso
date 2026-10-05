"""Remove leftover repair-agent sandbox containers (only ones with our label).

Run from anywhere:
    python scripts/cleanup_containers.py                       # older than 1 hour
    python scripts/cleanup_containers.py --max-age-minutes 15  # older than 15 minutes
    python scripts/cleanup_containers.py --all                 # every labelled container
--all (or a very small max age) also removes the container of a run still in progress.
"""

from __future__ import annotations

import argparse
import sys
from datetime import timedelta

from repair_agent.sandbox import LABEL, LEFTOVER_MAX_AGE, SandboxError, cleanup_leftover_containers


def _minutes(text: str) -> float:
    """argparse type: a non-negative number of minutes."""
    value = float(text)
    if value < 0:
        raise argparse.ArgumentTypeError("must be 0 or more")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Remove leftover repair-agent sandbox containers.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--all",
        action="store_true",
        help="remove every labelled container regardless of age (including runs in progress)",
    )
    mode.add_argument(
        "--max-age-minutes",
        type=_minutes,
        metavar="N",
        help=f"remove labelled containers older than N minutes (default: {LEFTOVER_MAX_AGE})",
    )
    args = parser.parse_args(argv)

    if args.all:
        max_age = None
    elif args.max_age_minutes is not None:
        max_age = timedelta(minutes=args.max_age_minutes)
    else:
        max_age = LEFTOVER_MAX_AGE

    try:
        removed = cleanup_leftover_containers(max_age=max_age)
    except SandboxError as error:
        print(error, file=sys.stderr)
        return 1

    label = ", ".join(f"{key}={value}" for key, value in LABEL.items())
    scope = "any age" if max_age is None else f"older than {max_age}"
    if removed:
        print(f"Removed {len(removed)} container(s) labelled {label} ({scope}): {', '.join(removed)}")
    else:
        print(f"No containers labelled {label} ({scope}) to remove.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
