from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.process.flow.boundary_conditions import FlowBoundaryConditionConfig
from hydromodpy.process.flow.sinks_sources import FlowWellConfig
from hydromodpy.solver.modflow6 import Modflow6
from hydromodpy.simulation.time import ResolvedSimulationTimeWindow


class _DummyGeographic:
    def __init__(self, dem: np.ndarray):
        self.dem_res = 1.0
        self.xmin = 0.0
        self.ymax = float(dem.shape[0])
        self.dem_box_buff_data = np.asarray(dem, dtype=float)
        self.dem_data = np.asarray(dem, dtype=float)
        self.watershed_box_buff_dem = "dummy_box.tif"
        self.watershed_buff_dem = "dummy_buff.tif"


def _build_model() -> Modflow6:
    dem = np.array([[10.0, 10.0, 10.0], [10.0, 10.0, 10.0]], dtype=float)
    geo = _DummyGeographic(dem)
    model = Modflow6(geographic=geo, model_folder=".")
    model.nlay = 1
    model.nrow = 2
    model.ncol = 3
    model.nper = 2
    model.dem_mask = np.zeros((2, 3), dtype=bool)
    model.time_grid = SimpleNamespace(
        window=ResolvedSimulationTimeWindow(
            start=pd.Timestamp("2003-01-01"),
            end=pd.Timestamp("2003-02-28"),
            step_value=1,
            step_unit="month",
            coverage_policy="error",
        )
    )
    return model


def test_modflow6_builds_chd_from_scalar_and_transient_side_boundaries() -> None:
    model = _build_model()
    model.flow = SimpleNamespace(
        boundary_conditions={
            "west_side": SimpleNamespace(value=10.0),
            "east_side": SimpleNamespace(value=[20.0, 21.0]),
        },
        active_bc=["west_side", "east_side"],
    )

    chd_spd = model._build_side_boundary_chd_spd()

    assert chd_spd[0][0] == [0, 0, 0, pytest.approx(10.0)]
    assert chd_spd[0][-1] == [0, 1, 2, pytest.approx(20.0)]
    assert chd_spd[1][-1] == [0, 1, 2, pytest.approx(21.0)]


def test_modflow6_applies_first_boundary_value_to_start_heads() -> None:
    model = _build_model()
    model.flow = SimpleNamespace(
        boundary_conditions={
            "north_side": SimpleNamespace(value=[7.0, 8.0]),
        },
        active_bc=["north_side"],
    )
    strt = np.zeros((1, 2, 3), dtype=float)

    updated = model._apply_side_boundary_start_heads(strt)

    assert np.all(updated[:, 0, :] == 7.0)
    assert np.all(updated[:, 1, :] == 0.0)


def test_modflow6_resolves_boundary_forcing_without_runtime_binding() -> None:
    model = _build_model()
    model.flow = SimpleNamespace(
        boundary_conditions={
            "east_side": FlowBoundaryConditionConfig(
                id="east_side",
                type="dirichlet",
                units="m",
                application_domain="east side",
                forcing={"mode": "constant", "value": 20.0},
            )
        },
        active_bc=["east_side"],
    )

    chd_spd = model._build_side_boundary_chd_spd()

    assert chd_spd[0][-1] == [0, 1, 2, pytest.approx(20.0)]
    assert chd_spd[1][-1] == [0, 1, 2, pytest.approx(20.0)]


def test_modflow6_resolves_well_forcing_without_runtime_binding() -> None:
    model = _build_model()
    model.grid_ctx = SimpleNamespace(grid=None)
    model.flow = SimpleNamespace(
        sinks_sources={
            "wells": {
                "W1": FlowWellConfig(
                    cell=(0, 0, 0),
                    units="m3/day",
                    forcing={"mode": "constant", "value": -86400.0},
                )
            }
        },
        active_sinks_sources=["wells"],
    )

    wel_spd = model._build_well_stress_period_data(2)

    assert wel_spd[0] == [[0, 0, 0, pytest.approx(-1.0)]]
    assert wel_spd[1] == [[0, 0, 0, pytest.approx(-1.0)]]
