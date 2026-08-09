"""Repo-level guard: service images must install the LOCKED dependency set.

Why this suite exists (#225)
----------------------------
CI has two independent installs of the same service, and they used to resolve
dependencies by two different rules:

- the **test venv** (`.github/workflows/integration.yml`) runs
  ``uv sync --frozen``, which installs exactly what ``uv.lock`` pins;
- the **container image** (`services/*/Dockerfile`) ran a bare
  ``uv pip install --system [-e] .``, which ignores ``uv.lock`` entirely and
  re-resolves every ``>=`` constraint in ``pyproject.toml`` against PyPI at
  build time.

So the image shipped whatever was newest on the day it was built, while the
tests that were supposed to vouch for it ran against the lockfile. The two
sets had drifted to 58 differing packages and 9 major-version jumps before
anything broke; then ``mcp`` 2.0.0 shipped, its low-level ``Server`` dropped
the ``@server.list_tools()`` / ``@server.call_tool()`` decorators that
``src/mcp_server/http_transport.py`` builds on, and the public-api container
crashed on startup -- turning the integration workflow red with no code
change on our side.

The durable fix is that the image installs from the lockfile too, so
"tests passed" and "the image works" are statements about the same
dependency set. These tests pin that property in the build definition itself,
because no runtime test can catch it: the test venv is correct by
construction, and only the image is wrong.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]

# The Python services that build a container image from their own
# pyproject.toml + uv.lock pair. inh-contracts is excluded: it is a pure
# path-dependency library with no Dockerfile of its own.
SERVICES = ("inh-public-api-svc", "inh-ingestion-svc")


def _dockerfile(service: str) -> str:
    return (REPO_ROOT / "services" / service / "Dockerfile").read_text()


@pytest.mark.parametrize("service", SERVICES)
def test_dockerfile_copies_the_lockfile(service: str) -> None:
    """The image cannot install from a lock it never received.

    ``uv export --frozen`` reads ``uv.lock`` relative to the project dir, so
    the lockfile must be COPYed in alongside pyproject.toml.
    """
    assert f"services/{service}/uv.lock" in _dockerfile(service), (
        f"{service}/Dockerfile must COPY its uv.lock into the image; without it "
        "the build silently falls back to re-resolving pyproject.toml."
    )


@pytest.mark.parametrize("service", SERVICES)
def test_dockerfile_resolves_dependencies_from_the_lockfile(service: str) -> None:
    """Dependencies come from ``uv export --frozen``, not a fresh resolution.

    ``--frozen`` is the load-bearing flag: it forbids uv from updating the
    lock, so the exported requirements are byte-for-byte the versions
    ``uv sync --frozen`` gives the test venv. Without it, a pyproject/lock
    mismatch would be "helpfully" re-resolved and the drift would return.
    """
    dockerfile = _dockerfile(service)

    assert "uv export" in dockerfile, (
        f"{service}/Dockerfile must derive its requirements from uv.lock via "
        "`uv export`, not resolve pyproject.toml constraints at build time."
    )
    export_lines = [line for line in dockerfile.splitlines() if "uv export" in line]
    for line in export_lines:
        assert "--frozen" in line, (
            f"{service}/Dockerfile: `uv export` must pass --frozen so the lock is "
            f"used as-is and never re-resolved. Offending line: {line.strip()}"
        )


@pytest.mark.parametrize("service", SERVICES)
def test_dockerfile_installs_the_project_without_redistributing_deps(
    service: str,
) -> None:
    """The project install must not re-open dependency resolution.

    Installing the service package itself (``uv pip install .``) would make
    uv resolve its ``dependencies`` table all over again and quietly upgrade
    past the locked set -- undoing the export above. ``--no-deps`` installs
    only the package, leaving the already-installed locked versions intact.
    """
    dockerfile = _dockerfile(service)

    # Every `uv pip install` of a local path (`.`, `-e .`, `".[ocr]"`) must
    # either be the requirements install (-r) or carry --no-deps.
    for line in dockerfile.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            # Comment prose, not a build instruction. The install steps
            # deliberately quote the old lock-ignoring command to explain what
            # was wrong with it, so matching comments would flag the fix itself.
            continue
        if "uv pip install" not in stripped:
            continue
        if "-r " in stripped:  # the locked requirements install itself
            continue
        assert "--no-deps" in stripped, (
            f"{service}/Dockerfile: a project install that omits --no-deps re-resolves "
            f"dependencies and defeats the lockfile. Offending line: {stripped}"
        )


def test_public_api_caps_mcp_below_2() -> None:
    """``mcp`` is capped below 2.0 because our code uses its 1.x API.

    ``src/mcp_server/server.py`` and ``src/mcp_server/http_transport.py`` both
    build their tool surface with the low-level ``Server``'s
    ``@server.list_tools()`` / ``@server.call_tool()`` decorators. mcp 2.0.0
    removed those from ``mcp.server.lowlevel.Server`` (the registry moved to
    ``add_request_handler`` / the new ``MCPServer``), so importing our module
    against 2.x raises ``AttributeError: 'Server' object has no attribute
    'list_tools'`` at app-construction time.

    The Dockerfile fix above stops today's builds from picking 2.x, but the
    lock is regenerated whenever a dependency changes. This cap makes the
    incompatibility a declared constraint rather than an accident of
    lock timing, so ``uv lock`` can never reintroduce it -- in the image OR
    the test venv. Removing the cap requires porting both modules to the 2.x
    server API first.
    """
    pyproject = (
        REPO_ROOT / "services" / "inh-public-api-svc" / "pyproject.toml"
    ).read_text()

    mcp_requirement = re.search(r'"(mcp[^"]*)"', pyproject)
    assert mcp_requirement is not None, "public-api must declare an `mcp` dependency"
    assert "<2" in mcp_requirement.group(1), (
        "public-api must cap `mcp` below 2.0 -- our low-level Server decorator usage "
        f"does not exist in mcp 2.x. Found: {mcp_requirement.group(1)}"
    )
