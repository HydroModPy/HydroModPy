"""The declared skips of the port tests.

A case a port test cannot play here is a skip that names why, never a case
left out. A solver binary that is not installed skips and names
``hmp install-binaries``. An optional module a mesh engine imports, gmsh for
one, skips and names the module. Each skip turns into a failure when the
environment promised what is missing: ``HMP_REQUIRE_BINARIES`` for the
binaries, ``HMP_REQUIRE_GMSH`` for the mesh extra. A green run that skipped
half its cases proves nothing on a machine that set them.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager

import pytest

from hydromodpy.core.workspace.workspace import resolve_bin_path
from hydromodpy.solver.modflow_common.binaries import exe_filename, locate_solver_binary


def cannot_run(reason: str, promise: str) -> None:
    """Skip with ``reason``, or fail when the variable ``promise`` is set."""
    if os.environ.get(promise):
        pytest.fail(f"{promise} is set and {reason}")
    pytest.skip(reason)


def missing_module(exc: BaseException) -> str | None:
    """Return the name of the module whose absence raised ``exc``, or None.

    A pipeline step wraps what it raises, so the chain of causes is walked. A
    module of hydromodpy itself is never optional: its absence is a broken
    install, which fails.
    """
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, ModuleNotFoundError) and current.name:
            if current.name.partition(".")[0] == "hydromodpy":
                return None
            return current.name
        current = current.__cause__ or current.__context__
    return None


@pytest.fixture(scope="session", autouse=True)
def _fill_the_trial_pipeline() -> None:
    """Fill the trial pipeline, which the solver port builds its models through.

    It is the one global the library keeps, and filling it is idempotent.
    """
    from hydromodpy.project.trial_pipeline import fill_trial_pipeline

    fill_trial_pipeline()


@pytest.fixture
def require_binaries() -> Callable[[Iterable[str], str], None]:
    """Return a check that skips a case when one of its solver binaries is absent.

    The check takes the canonical solver names (``mf6``, ``libmf6``, ``mfnwt``)
    and who needs them, and looks in the folder the build reads binaries from.
    """

    def check(names: Iterable[str], who: str) -> None:
        folder = resolve_bin_path()
        absent = [name for name in names if locate_solver_binary(folder, name) is None]
        if absent:
            files = ", ".join(exe_filename(name) for name in absent)
            cannot_run(
                f"{who} needs {files}, absent from {folder}: run `hmp install-binaries`",
                "HMP_REQUIRE_BINARIES",
            )

    return check


@pytest.fixture
def optional_modules() -> Callable[[str], object]:
    """Return a context that skips a case whose mesh engine misses an optional module."""

    @contextmanager
    def guard(who: str) -> Iterator[None]:
        try:
            yield
        except Exception as exc:
            name = missing_module(exc)
            if name is None:
                raise
            cannot_run(f"{who} imports {name}, which this environment lacks", "HMP_REQUIRE_GMSH")

    return guard
