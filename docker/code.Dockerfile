# Sandbox image for code tasks: Python 3.11 and pytest, nothing else.
# The agent's model-edited code runs in here, so the image is kept minimal on purpose:
# no git, curl or other tools that untrusted code could use.
FROM python:3.11-slim

# Pinned (same version as the harness) so task results can't change when pytest releases.
RUN pip install --no-cache-dir pytest==9.1.1

# Run as an unprivileged user, not root, so code inside can't modify the system.
RUN useradd --create-home --uid 1000 agent \
    && mkdir /workspace \
    && chown agent:agent /workspace

# Same settings run_checks uses on the host: no __pycache__ in the workspace, UTF-8 output.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONIOENCODING=utf-8

WORKDIR /workspace
USER agent
