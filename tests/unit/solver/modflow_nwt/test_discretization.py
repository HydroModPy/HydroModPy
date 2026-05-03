from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from hydromodpy.solver.modflow_grid import (
    build_temporal_discretization_from_time_grid,
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
