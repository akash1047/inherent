FROM python:3.11-slim

# Install uv for faster package management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# NOTE: this image expects the build context to be the REPO ROOT (set in
# docker-compose.yml via `context: .`), so the sibling shared package
# services/inh-contracts is visible and the `../inh-contracts` uv path
# dependency resolves.

# Copy the shared contracts package first (separate layer; changes rarely).
COPY services/inh-contracts /app/services/inh-contracts

# Copy this service's dependency files, readme, and source (readme + src are
# required by hatchling at install time). uv.lock is copied because this image
# installs the LOCKED dependency set -- see the install step below.
COPY services/inh-public-api-svc/pyproject.toml services/inh-public-api-svc/uv.lock services/inh-public-api-svc/Readme.md /app/services/inh-public-api-svc/
COPY services/inh-public-api-svc/src /app/services/inh-public-api-svc/src

WORKDIR /app/services/inh-public-api-svc

# Install the EXACT dependency set `uv.lock` pins -- the same one CI's test
# venv gets from `uv sync --frozen` (#225).
#
# This used to be a bare `uv pip install --system -e .`, which ignores uv.lock
# and re-resolves every `>=` constraint in pyproject.toml against PyPI at build
# time. That made the image's dependencies a function of its BUILD DATE, not of
# anything in the repo: the tests vouched for the locked set while the image
# shipped whatever was newest. The two had drifted to 58 differing packages
# (9 major-version jumps) when mcp 2.0.0 shipped a low-level `Server` without
# the `list_tools` decorator and crashed this service on startup, reddening
# integration with no code change on our side.
#
# Two steps, because they answer two different questions:
#   1. `uv export --frozen` renders uv.lock to pinned requirements (--frozen
#      forbids uv from updating the lock, so this is the lock verbatim); the
#      `../inh-contracts` path dependency is emitted as a relative path and
#      resolves against this WORKDIR, exactly as it did before.
#   2. `--no-deps` installs THIS package only. Without it, uv would re-resolve
#      the pyproject `dependencies` table and undo step 1.
RUN uv export --frozen --no-dev --no-hashes --no-emit-project -o /tmp/requirements.txt \
    && uv pip install --system -r /tmp/requirements.txt \
    && uv pip install --system --no-deps -e . \
    && rm /tmp/requirements.txt

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV SERVICE_MODE=api
ENV PORT=8080

EXPOSE 8080

# Run the application
CMD ["python", "-m", "src.main"]
