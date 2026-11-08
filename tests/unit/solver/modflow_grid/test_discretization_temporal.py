"""The first-period steady policy of a run is read off its model."""

from __future__ import annotations

import pytest

from hydromodpy.model.model import ModelTime
from hydromodpy.solver.modflow_grid.discretization_temporal import resolve_first_period_steady
from tests._helpers.model_factory import make_model


@pytest.mark.parametrize("first_period_steady", [True, False])
def test_the_policy_is_the_one_the_model_carries(first_period_steady: bool) -> None:
    model = make_model(
        time=ModelTime(grid=None, regime="transient", first_period_steady=first_period_steady)
    )

    assert resolve_first_period_steady(model=model, default=not first_period_steady) is (
        first_period_steady
    )


@pytest.mark.parametrize("default", [True, False])
def test_without_a_model_the_default_stands(default: bool) -> None:
    assert resolve_first_period_steady(default=default) is default
    assert resolve_first_period_steady(model=None, default=default) is default
