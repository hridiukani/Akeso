"""Build the sandbox Docker images.

Run from anywhere:  python scripts/build_images.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

DOCKER_DIR = Path(__file__).resolve().parent.parent / "docker"

# image tag -> Dockerfile inside docker/
IMAGES = {
    "repair-agent-code:latest": "code.Dockerfile",
}


def main() -> int:
    for tag, dockerfile in IMAGES.items():
        # flush so this line appears before docker's own output when piped to a log
        print(f"Building {tag} from docker/{dockerfile} ...", flush=True)
        # The build context is docker/ only, so nothing else in the repo (.env, tasks,
        # source) is ever sent to the Docker daemon or baked into the image.
        result = subprocess.run(
            ["docker", "build", "-f", str(DOCKER_DIR / dockerfile), "-t", tag, str(DOCKER_DIR)]
        )
        if result.returncode != 0:
            print(f"Failed to build {tag}.", file=sys.stderr)
            return result.returncode
    print("All images built.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
