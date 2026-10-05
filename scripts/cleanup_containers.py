"""Remove leftover repair-agent sandbox containers (only ones with our label).

Run from anywhere:  python scripts/cleanup_containers.py
Don't run it while a repair is in progress: it removes that run's container too.
"""

from __future__ import annotations

import sys

from repair_agent.sandbox import LABEL, SandboxError, cleanup_leftover_containers


def main() -> int:
    try:
        removed = cleanup_leftover_containers()
    except SandboxError as error:
        print(error, file=sys.stderr)
        return 1
    label = ", ".join(f"{key}={value}" for key, value in LABEL.items())
    if removed:
        print(f"Removed {len(removed)} container(s) labelled {label}: {', '.join(removed)}")
    else:
        print(f"No leftover containers labelled {label}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
