"""An adapter that cannot serve an observable refuses with one named exception.

``SolverAdapter.extract_observables`` promises that a caller never reads a
signature to learn what a backend supports: it asks, and an unavailable
observable comes back as :class:`ObservableNotAvailableError`. That promise only
holds if every refusal path raises that one type. The config-dependent paths did
not: whether a run built a DRAIN package, a LAK sidecar or a solver mesh decided
between ``RuntimeError``, ``KeyError`` and ``FileNotFoundError``, so a caller had
to catch three unrelated types and could not tell a refusal from a bug.
"""

from __future__ import annotations

import ast
from pathlib import Path

import hydromodpy.solver.modflow6.extractors.lake as lake_extractor
import hydromodpy.solver.modflow_common.calibration_extractors as calibration_extractors
import hydromodpy.solver.modflow_common.observable_extraction as observable_extraction
from hydromodpy.core.exceptions import ObservableNotAvailableError, SolverError

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
