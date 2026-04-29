"""Every registered solver adapter must structurally conform to ``SolverAdapter``.

The test is parametrised on :func:`registry.list_pairs` so it covers
both eagerly-registered adapters and lazily-loaded built-ins. A new
adapter that lands in ``_BUILTIN_PATHS`` without honouring the
``validate / execute / cleanup`` triplet would surface here immediately.
"""

from __future__ import annotations

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
