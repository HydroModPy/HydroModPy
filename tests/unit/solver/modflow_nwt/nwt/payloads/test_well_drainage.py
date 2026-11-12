"""Drain and well payloads of the NWT adapter.

Drain conductance is in m2/s, well rates are in m3/s (negative pumps), heights are in m.
A drain row is (layer, row, column, elevation, conductance), a well row (layer, row, column, rate).
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.model.boundaries.boundary_condition_registry import BoundaryConditionBundle
from hydromodpy.solver.modflow_nwt.nwt.flow_to_modflow_adapter import FlowToModflowAdapter
from hydromodpy.solver.modflow_nwt.nwt.payloads.well_drainage import (
    build_drainage_spd,
    build_well_stress_period_data,
)
from tests._helpers.model_factory import make_model
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays


def flat_mesh(nrow=1, ncol=1):
    return solver_mesh_from_structured_arrays(
        nrow=nrow,
        ncol=ncol,
        top=np.zeros((nrow, ncol)),
        botm=np.full((1, nrow, ncol), -10.0),
        dx=10.0,
        dy=10.0,
    )


def adapter_of(model, mesh=None, nper=2) -> FlowToModflowAdapter:
    return FlowToModflowAdapter(
        model=model,
        solver_mesh=flat_mesh() if mesh is None else mesh,
        nper=nper,
        sink_fill=False,
    )


def well_adapter(wells, nper=2) -> FlowToModflowAdapter:
    model = make_model(wells=wells, active_sinks_sources=("wells",))
    return adapter_of(model, nper=nper)


def cell_well(flux) -> SimpleNamespace:
    return SimpleNamespace(location=SimpleNamespace(kind="cell", cell=(0, 0, 0)), flux=flux)


def test_drain_skips_inactive_cells():
    drainage = SimpleNamespace(value=2.0, units="m2/s")
    bundle = BoundaryConditionBundle(conditions={"drainage": drainage}, active_ids=("drainage",))
    adapter = adapter_of(make_model(boundaries=bundle), flat_mesh(nrow=1, ncol=2), nper=1)

    # The first cell is off in the activation mask, the second drains at 2 m2/s.
    spd = build_drainage_spd(adapter, drain_array=np.array([[0.0, 1.0]]), hk=np.ones((1, 1, 2)))

    np.testing.assert_allclose(spd[0], [[0, 0, 1, 0.0, 2.0]])


def test_drain_without_payload():
    bundle = BoundaryConditionBundle(conditions={}, active_ids=("drainage",))
    adapter = adapter_of(make_model(boundaries=bundle), nper=1)

    assert build_drainage_spd(adapter, drain_array=np.ones((1, 1)), hk=np.ones((1, 1, 1))) is None


WELL_ROWS = [
    pytest.param(
        {"W1": cell_well([-1e-4])},
        {0: [[0, 0, 0, pytest.approx(-1e-4)]], 1: [[0, 0, 0, pytest.approx(-1e-4)]]},
        id="one rate goes to every period",
    ),
    pytest.param({}, {}, id="no wells"),
]


@pytest.mark.parametrize(("wells", "expected"), WELL_ROWS)
def test_well_periods(wells, expected):
    assert build_well_stress_period_data(well_adapter(wells)) == expected


def test_well_without_period():
    assert build_well_stress_period_data(well_adapter({"W1": cell_well(-1e-4)}, nper=0)) == {}


def test_well_without_layer_takes_top_cell():
    location = SimpleNamespace(kind="xy")
    well = SimpleNamespace(location=location, flux=-1e-4, resolve_cell=lambda grid: (None, 0, 0))

    spd = build_well_stress_period_data(well_adapter({"W1": well}, nper=1))

    # The column holds one active layer, so the well sits in layer 0.
    assert spd == {0: [[0, 0, 0, pytest.approx(-1e-4)]]}


def test_non_finite_rate_refused():
    with pytest.raises(ValueError, match="W1.flux must be finite"):
        build_well_stress_period_data(well_adapter({"W1": cell_well(float("nan"))}))
