"""The first-period steady policy of a run is read off its model."""

from __future__ import annotations

import pytest

from hydromodpy.solver.modflow_grid.discretization_temporal import resolve_first_period_steady


@pytest.mark.parametrize("default", [True, False])
def test_without_a_model_the_default_stands(default: bool) -> None:
    assert resolve_first_period_steady(default=default) is default
    assert resolve_first_period_steady(model=None, default=default) is default
