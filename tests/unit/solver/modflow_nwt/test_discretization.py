from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.physics.flow import FlowConfig
from hydromodpy.solver.modflow_grid import (
    build_temporal_discretization_from_time_grid,
    resolve_first_period_steady,
)


def test_build_temporal_discretization_from_time_grid_ignores_firstpersteady_in_steady() -> None:
    time_grid = SimpleNamespace(
        period_lengths_seconds=(1.0, 2.0, 3.0),
        nstp_per_period=4,
        window=None,
    )

    result = build_temporal_discretization_from_time_grid(
        time_grid=time_grid,
        flow_regime="steady",
        firstpersteady=False,
    )

    assert result.nper == 3
    assert np.allclose(result.perlen, np.array([1.0, 2.0, 3.0]))
    assert np.array_equal(result.nstp, np.array([4, 4, 4]))
    assert np.array_equal(result.steady, np.array([True, True, True]))


def test_build_temporal_discretization_from_time_grid_uses_first_period_steady() -> None:
    time_grid = SimpleNamespace(
        period_lengths_seconds=(1.0, 2.0, 3.0),
        nstp_per_period=1,
        window=None,
    )

    result = build_temporal_discretization_from_time_grid(
        time_grid=time_grid,
        flow_regime="transient",
        first_period_steady=False,
    )

    assert np.array_equal(result.steady, np.array([False, False, False]))


def test_build_temporal_discretization_from_time_grid_keeps_legacy_firstpersteady() -> None:
    time_grid = SimpleNamespace(
        period_lengths_seconds=(1.0, 2.0, 3.0),
        nstp_per_period=1,
        window=None,
    )

    result = build_temporal_discretization_from_time_grid(
        time_grid=time_grid,
        flow_regime="transient",
        firstpersteady=True,
    )

    assert np.array_equal(result.steady, np.array([True, False, False]))


def test_build_temporal_discretization_rejects_conflicting_first_period_flags() -> None:
    time_grid = SimpleNamespace(
        period_lengths_seconds=(1.0,),
        nstp_per_period=1,
        window=None,
    )

    with pytest.raises(ValueError, match="first_period_steady.*firstpersteady"):
        build_temporal_discretization_from_time_grid(
            time_grid=time_grid,
            flow_regime="transient",
            first_period_steady=False,
            firstpersteady=True,
        )


def test_resolve_first_period_steady_uses_explicit_flow_config() -> None:
    flow = SimpleNamespace(config=FlowConfig(first_period_steady=False))

    assert resolve_first_period_steady(flow=flow) is False


def test_resolve_first_period_steady_keeps_legacy_when_flow_default_is_implicit() -> None:
    flow = SimpleNamespace(config=FlowConfig())
    legacy_tgrid = SimpleNamespace(firstpersteady=False)

    assert resolve_first_period_steady(flow=flow, legacy_tgrid=legacy_tgrid) is False


def test_resolve_first_period_steady_rejects_conflicting_sources() -> None:
    flow = SimpleNamespace(config=FlowConfig(first_period_steady=True))
    legacy_tgrid = SimpleNamespace(firstpersteady=False)

    with pytest.raises(ValueError, match="flow.first_period_steady.*tgrid.firstpersteady"):
        resolve_first_period_steady(flow=flow, legacy_tgrid=legacy_tgrid)
