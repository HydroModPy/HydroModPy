"""The Whitebox-backed tests must stay outside xdist in CI.

The native Whitebox binding dies outright, taking its process with it, when
several DEM workflows run in one long-lived pytest worker. ``tests/conftest.py``
already puts every Whitebox test in one ``xdist_group``, which stops two workers
touching the backend at once but also guarantees they all land on the same node,
which is the condition that kills it. Pinning the fd-level stdio redirect off,
the previous attempt, was not enough: a worker still died on ``main``.

So every CI step that walks a tier in parallel excludes the Whitebox tests and a
serial step runs them. Nothing links the list in the conftest to the paths in
the workflows but this module.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from tests.conftest import _WHITEBOX_XDIST_GROUP_TEST_FILES

_REPO_ROOT = Path(__file__).resolve().parents[3]
_WORKFLOW_DIR = _REPO_ROOT / ".github" / "workflows"
_PARALLEL_RE = re.compile(r"-n\s+(auto|\d+)")


def _whitebox_test_paths() -> list[Path]:
    """Locate every file the conftest puts in the Whitebox xdist group."""
    found: list[Path] = []
    for name in sorted(_WHITEBOX_XDIST_GROUP_TEST_FILES):
        matches = sorted((_REPO_ROOT / "tests").rglob(name))
        assert matches, (
            f"{name} is listed in the Whitebox xdist group but no such test file "
            "exists; the entry protects nothing and the test that replaced it is "
            "running unguarded"
        )
        found.extend(matches)
    return found


def _pytest_commands(workflow: Path) -> list[str]:
    """Every pytest invocation in a workflow, line continuations folded in."""
    document = yaml.safe_load(workflow.read_text(encoding="utf-8"))
    commands: list[str] = []
    for job in (document.get("jobs") or {}).values():
        for step in job.get("steps") or []:
            script = step.get("run")
            if not script:
                continue
            folded = script.replace("\\\n", " ")
            commands.extend(
                " ".join(line.split()) for line in folded.splitlines() if "pytest" in line
            )
    return commands


def _collects(command: str, path: Path) -> bool:
    """Whether a pytest command walks a tree that contains ``path``."""
    relative = path.relative_to(_REPO_ROOT).as_posix()
    for token in command.split():
        if not token.startswith("tests/"):
            continue
        if relative == token or relative.startswith(token.rstrip("/") + "/"):
            return True
    return False


def _ignored(command: str, path: Path) -> bool:
    relative = path.relative_to(_REPO_ROOT).as_posix()
    for token in command.split():
        if not token.startswith("--ignore="):
            continue
        ignored = token.split("=", 1)[1]
        if relative == ignored or relative.startswith(ignored.rstrip("/") + "/"):
            return True
    return False


def test_every_whitebox_group_file_still_exists() -> None:
    """A deleted or renamed file drops out of the group and back into a parallel run."""
    assert len(_whitebox_test_paths()) == len(_WHITEBOX_XDIST_GROUP_TEST_FILES)


@pytest.mark.parametrize(
    "workflow",
    [pytest.param(path, id=path.name) for path in sorted(_WORKFLOW_DIR.glob("*.yml"))],
)
def test_no_parallel_step_collects_a_whitebox_test(workflow: Path) -> None:
    offenders: list[str] = []
    for command in _pytest_commands(workflow):
        if not _PARALLEL_RE.search(command):
            continue
        for path in _whitebox_test_paths():
            if _collects(command, path) and not _ignored(command, path):
                offenders.append(f"{path.relative_to(_REPO_ROOT).as_posix()} in: {command}")

    assert not offenders, (
        f"{workflow.name} runs Whitebox tests inside an xdist worker, which kills it:\n  "
        + "\n  ".join(offenders)
        + "\nAdd an --ignore for them and a serial step that runs them."
    )


@pytest.mark.parametrize(
    "workflow",
    [pytest.param(path, id=path.name) for path in sorted(_WORKFLOW_DIR.glob("*.yml"))],
)
def test_what_a_parallel_step_ignores_is_run_somewhere_serially(workflow: Path) -> None:
    """Excluding a Whitebox test everywhere without running it would lose coverage."""
    commands = _pytest_commands(workflow)
    serial = [command for command in commands if not _PARALLEL_RE.search(command)]

    missing: list[str] = []
    for path in _whitebox_test_paths():
        excluded = any(
            _PARALLEL_RE.search(command) and _collects(command, path) and _ignored(command, path)
            for command in commands
        )
        if excluded and not any(_collects(command, path) for command in serial):
            missing.append(path.relative_to(_REPO_ROOT).as_posix())

    assert not missing, f"{workflow.name} excludes these but never runs them serially: {missing}"
