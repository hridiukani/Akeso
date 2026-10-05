"""Remove leftover repair-agent sandbox containers (only ones with our label).

Run from anywhere:
    python scripts/cleanup_containers.py         # only containers older than 1 hour
    python scripts/cleanup_containers.py --all   # every labelled container, any age
--all also removes the container of a run that's still in progress.
"""

from __future__ import annotations

import argparse
import sys

from repair_agent.sandbox import LABEL, LEFTOVER_MAX_AGE, SandboxError, cleanup_leftover_containers


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Remove leftover repair-agent sandbox containers.")
    parser.add_argument(
        "--all",
        action="store_true",
        help="remove every labelled container regardless of age (including runs in progress)",
    )
    args = parser.parse_args(argv)

    try:
        removed = cleanup_leftover_containers(max_age=None if args.all else LEFTOVER_MAX_AGE)
    except SandboxError as error:
        print(error, file=sys.stderr)
        return 1

    label = ", ".join(f"{key}={value}" for key, value in LABEL.items())
    scope = "any age" if args.all else f"older than {LEFTOVER_MAX_AGE}"
    if removed:
        print(f"Removed {len(removed)} container(s) labelled {label} ({scope}): {', '.join(removed)}")
    else:
        print(f"No containers labelled {label} ({scope}) to remove.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
