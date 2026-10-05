"""Shared pytest setup.

Tests marked @pytest.mark.docker need Docker running and the sandbox image built.
When either is missing they're skipped (with the reason), not failed, so the rest of
the suite still runs anywhere. Quick run without them: pytest -m "not docker"

When Docker tests do run, the session starts by sweeping up sandbox containers left
behind by crashed runs (older than LEFTOVER_MAX_AGE).
"""

from __future__ import annotations

import pytest

from repair_agent.sandbox import IMAGE, SandboxError, cleanup_leftover_containers

# Set during collection: True when docker-marked tests were selected and Docker works.
_DOCKER_TESTS_WILL_RUN = pytest.StashKey[bool]()


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
    config.stash[_DOCKER_TESTS_WILL_RUN] = False
    if not docker_items:
        return
    reason = _docker_unavailable_reason()
    if reason:
        for item in docker_items:
            item.add_marker(pytest.mark.skip(reason=reason))
    else:
        config.stash[_DOCKER_TESTS_WILL_RUN] = True


@pytest.fixture(scope="session", autouse=True)
def sweep_leftover_containers(request: pytest.FixtureRequest) -> None:
    """Once per session, remove our containers older than LEFTOVER_MAX_AGE.

    Skipped when no Docker tests run, so quick runs stay Docker-free. The age limit
    means containers of a run happening right now are never touched.
    """
    if not request.config.stash.get(_DOCKER_TESTS_WILL_RUN, False):
        return
    try:
        removed = cleanup_leftover_containers()
    except SandboxError:
        return  # Docker went away since collection; the docker tests will report it
    if removed:
        reporter = request.config.pluginmanager.get_plugin("terminalreporter")
        if reporter is not None:
            reporter.write_line(f"Swept {len(removed)} leftover sandbox container(s): {', '.join(removed)}")
