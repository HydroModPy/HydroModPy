"""Unit tests for the ``SolverAdapter`` Protocol, the engine a run records, and the refusals.

The ``RunResult`` dataclass left with the contract of build, run and rerun: its
three tests left with it, since ``SolverRun`` is what a backend returns and
``tests/unit/solver/base/test_plan.py`` holds its cases.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

import hydromodpy.solver.modflow6.extractors.lake as lake_extractor
import hydromodpy.solver.modflow_common.calibration_extractors as calibration_extractors
import hydromodpy.solver.modflow_common.observable_extraction as observable_extraction
from hydromodpy.core.exceptions import ObservableNotAvailableError, SolverError
from hydromodpy.solver.base.adapter_protocol import SolverAdapter
from hydromodpy.solver.base.plan import RunSlot
from hydromodpy.solver.base.registry import solvers
from tests._helpers.fake_solvers import fake_adapter

DummyAdapter = fake_adapter("dummy")
"""A structural conformer with the twelve attributes and the five methods."""

PartialAdapter = fake_adapter("partial", run=None)
"""Missing ``run`` on purpose to check structural conformance."""


def test_dummy_adapter_is_recognised_as_solver_adapter() -> None:
    assert isinstance(DummyAdapter(), SolverAdapter)


def test_partial_adapter_fails_structural_check() -> None:
    assert not isinstance(PartialAdapter(), SolverAdapter)


def test_lifecycle_order_on_dummy_adapter(tmp_path: Path) -> None:
    adapter = DummyAdapter()
    slot = RunSlot(tmp_path, "dummy")
    adapter.validate(None, None, slot)
    built = adapter.build(None, None, slot, None)
    solved = adapter.run(built)
    adapter.cleanup(solved)

    assert adapter.calls == ["validate", "build", "run", "cleanup"]
    assert (built.solved, solved.solved) == (False, True)


# Every registered solver adapter must structurally conform to ``SolverAdapter``.
#
# The test is parametrized on ``solvers.names()`` so it covers both eagerly
# registered adapters and lazily loaded built-ins. A new adapter that lands in
# ``_BUILTIN_PATHS`` without the twelve attributes and the
# ``validate / build / run / cleanup / extract`` members would surface here
# immediately.


@pytest.mark.parametrize("key", solvers.names())
def test_registered_adapter_conforms_to_protocol(key: str) -> None:
    adapter = solvers.create(key)
    assert isinstance(adapter, SolverAdapter)


@pytest.mark.parametrize("key", solvers.names())
def test_registered_adapter_advertises_its_key(key: str) -> None:
    cls = solvers.get(key)
    assert f"{cls.process_type}_{cls.name}" == key
    assert isinstance(cls.requires, tuple)


@pytest.mark.parametrize(
    "pair",
    [("flow", "modflow_nwt"), ("flow", "modflow6"), ("flow", "boussinesq")],
    ids=lambda p: f"{p[0]}/{p[1]}",
)
def test_flow_adapter_exposes_observables(pair: tuple[str, str]) -> None:
    """The 3 flow backends must each expose ``observables`` on a solved run."""
    adapter = solvers.create(*pair)
    method = getattr(adapter, "observables", None)
    assert callable(method), f"{pair} must define observables"
    sig = inspect.signature(method)
    assert "solver_run" in sig.parameters
    assert "store" not in sig.parameters
    assert "requests" in sig.parameters
    assert "time_index" in sig.parameters
    # The old names must be gone, not shadowed by an alias.
    assert not hasattr(adapter, "extract_observables")
    assert not hasattr(adapter, "extract_calibration_series")


# An adapter that cannot serve an observable refuses with one named exception.
#
# ``observables`` of a flow backend promises that a caller never reads a
# signature to learn what a backend supports: it asks, and an unavailable
# observable comes back as :class:`ObservableNotAvailableError`. That promise only
# holds if every refusal path raises that one type. The config-dependent paths did
# not: whether a run built a DRAIN package, a LAK sidecar or a solver mesh decided
# between ``RuntimeError``, ``KeyError`` and ``FileNotFoundError``, so a caller had
# to catch three unrelated types and could not tell a refusal from a bug.

# Refusing to serve an observable is not a programming error, so these types
# must not appear on that path. ValueError stays legal: it guards arguments the
# caller built wrong, which is a bug and not a missing capability.
_WRONG_ON_A_REFUSAL_PATH = {"RuntimeError", "KeyError", "FileNotFoundError"}


_MODULES = (observable_extraction, calibration_extractors, lake_extractor)


def _raised_type_names(module: object) -> list[str]:
    source_file = getattr(module, "__file__", None)
    assert source_file is not None, f"{module!r} has no source file to read"
    tree = ast.parse(Path(source_file).read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Raise) or node.exc is None:
            continue
        exc = node.exc
        target = exc.func if isinstance(exc, ast.Call) else exc
        if isinstance(target, ast.Name):
            names.append(target.id)
    return names


def test_the_refusal_is_a_solver_error() -> None:
    """The type a caller catches sits under the solver error family."""
    assert issubclass(ObservableNotAvailableError, SolverError)


def test_extraction_refuses_with_one_named_type() -> None:
    """No extraction module refuses through a bare built-in exception."""
    offenders = {
        getattr(module, "__name__", str(module)): sorted(
            set(_raised_type_names(module)) & _WRONG_ON_A_REFUSAL_PATH
        )
        for module in _MODULES
    }
    assert not {name: raised for name, raised in offenders.items() if raised}
