"""Shared pytest setup.

Tests marked @pytest.mark.docker need Docker running and the sandbox image built.
When either is missing they're skipped (with the reason), not failed, so the rest of
the suite still runs anywhere. Quick run without them: pytest -m "not docker"
"""

from __future__ import annotations

import pytest

from repair_agent.sandbox import IMAGE


def _docker_unavailable_reason() -> str | None:
    try:
        import docker

        client = docker.from_env()
        client.ping()
    except Exception:
        return "Docker isn't running (start Docker Desktop)"
    try:
        client.images.get(IMAGE)
    except Exception:
        return f"{IMAGE} isn't built (run: python scripts/build_images.py)"
    return None


# trylast: run after `-m` has deselected tests, so a quick run never contacts Docker.
@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    docker_items = [item for item in items if item.get_closest_marker("docker")]
    if not docker_items:
        return
    reason = _docker_unavailable_reason()
    if reason:
        for item in docker_items:
            item.add_marker(pytest.mark.skip(reason=reason))
