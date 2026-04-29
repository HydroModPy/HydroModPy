"""Every registered solver adapter must structurally conform to ``SolverAdapter``.

The test is parametrised on :func:`registry.list_pairs` so it covers
both eagerly-registered adapters and lazily-loaded built-ins. A new
adapter that lands in ``_BUILTIN_PATHS`` without honouring the
``validate / execute / cleanup / extract_calibration_series`` quartet
would surface here immediately.
"""

from __future__ import annotations

import inspect

import pytest

from hydromodpy.solver.base import registry
from hydromodpy.solver.base.protocol import SolverAdapter


@pytest.mark.parametrize("pair", registry.list_pairs(), ids=lambda p: f"{p[0]}/{p[1]}")
def test_registered_adapter_conforms_to_protocol(pair: tuple[str, str]) -> None:
    adapter = registry.get_solver_adapter(*pair)
    assert isinstance(adapter, SolverAdapter)


@pytest.mark.parametrize("pair", registry.list_pairs(), ids=lambda p: f"{p[0]}/{p[1]}")
def test_registered_adapter_advertises_pair(pair: tuple[str, str]) -> None:
    cls = registry.get(*pair)
    process_type, solver_name = pair
    assert cls.process_type == process_type
    assert cls.solver_name == solver_name
    assert isinstance(cls.requires, tuple)


@pytest.mark.parametrize(
    "pair",
    [("flow", "modflownwt"), ("flow", "modflow6"), ("flow", "boussinesq"), ("flow", "gr4j")],
    ids=lambda p: f"{p[0]}/{p[1]}",
)
def test_flow_adapter_exposes_extract_calibration_series(pair: tuple[str, str]) -> None:
    """The 4 flow backends must each expose ``extract_calibration_series``."""
    adapter = registry.get_solver_adapter(*pair)
    method = getattr(adapter, "extract_calibration_series", None)
    assert callable(method), f"{pair} must define extract_calibration_series"
    sig = inspect.signature(method)
    assert "ctx" in sig.parameters
    assert "store" in sig.parameters
    assert "variable" in sig.parameters
