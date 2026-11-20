"""No drain in a closed depression, on either backend.

A closed depression has no outlet, so the water reaching it ponds and a drain
there invents a discharge point. The surface is a plain tilt of 1 m per column
with one interior cell dug out by 10 m, so the depression is known by
construction. Drain conductances are in m2/s.
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.model.boundaries.boundary_condition_registry import BoundaryConditionBundle
from hydromodpy.solver.modflow6 import build as mf6_build
from hydromodpy.solver.modflow6.builders.boundary_conditions import (
    build_drain_stress_period_data,
)
from hydromodpy.solver.modflow_common.sink_mask import closed_depression_mask, resolve_sink_mask
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.solver.modflow_nwt.nwt import nwt_solver
from hydromodpy.solver.modflow_nwt.nwt.payloads.well_drainage import build_drainage_spd
from tests._helpers.model_factory import make_model
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays

NROW = 5
NCOL = 5
N_CELLS = NROW * NCOL
BASE_M = 100.0
PIT_CELL = 2 * NCOL + 2  # row 2, column 2
DRAIN_COND_M2_S = 0.05


def tilted_mesh(*, dug: bool, inactive: np.ndarray | None = None) -> SolverMesh:
    """A plane dropping 1 m per column, so every cell drains east to the mesh edge."""
    top = np.repeat(BASE_M - np.arange(NCOL, dtype=float)[None, :], NROW, axis=0)
    if dug:
        top[2, 2] = BASE_M - 10.0
    return solver_mesh_from_structured_arrays(
        nrow=NROW,
        ncol=NCOL,
        top=top,
        botm=np.zeros((1, NROW, NCOL)),
        dx=10.0,
        dy=10.0,
        inactive_mask=inactive,
    )


def pit_mask() -> np.ndarray:
    """The answer written out by hand, not measured by the code under test."""
    mask = np.zeros(N_CELLS, dtype=bool)
    mask[PIT_CELL] = True
    return mask


def mf6_conductance(*, sink_fill: bool, sink: np.ndarray | None) -> dict[int, float]:
    model = SimpleNamespace(
        dem_mask=np.zeros(N_CELLS, dtype=bool),
        nper=1,
        ncpl=N_CELLS,
        hk=np.full((1, N_CELLS), 1e-4),
        sink_fill=sink_fill,
        sink=sink,
        drain_band_depth_m=0.0,
        drain_bed_thickness_m=1.0,
        drain_conductance_floor_m2_s=1e-12,
    )
    spd = build_drain_stress_period_data(
        model,
        solver_mesh=tilted_mesh(dug=True),
        drainage_cond_series=np.array([DRAIN_COND_M2_S]),
        ocean_support_mask=np.zeros(N_CELLS, dtype=bool),
        stream_support_mask=np.zeros(N_CELLS, dtype=bool),
    )
    return {int(row[1]): float(row[3]) for row in spd[0]}


def nwt_conductance(*, sink_fill: bool, sink: np.ndarray | None) -> dict[int, float]:
    mesh = tilted_mesh(dug=True)
    drainage = SimpleNamespace(value=DRAIN_COND_M2_S, units="m2/s")
    adapter = SimpleNamespace(
        model=make_model(
            boundaries=BoundaryConditionBundle(
                conditions={"drainage": drainage}, active_ids=("drainage",)
            )
        ),
        solver_mesh=mesh,
        dem=mesh.reshape_to_grid(mesh.top),
        nrow=NROW,
        ncol=NCOL,
        cell_area=100.0,
        sink_fill=sink_fill,
        sink=None if sink is None else mesh.reshape_to_grid(np.asarray(sink, dtype=bool)),
        drain_band_depth_m=0.0,
        drain_bed_thickness_m=1.0,
        drain_conductance_floor_m2_s=1e-12,
    )
    spd = build_drainage_spd(
        adapter,
        drain_array=np.ones((NROW, NCOL), dtype=int),
        hk=np.full((1, NROW, NCOL), 1e-4),
    )
    return {int(row[1]) * NCOL + int(row[2]): float(row[4]) for row in spd[0]}


BACKENDS = [
    pytest.param(mf6_conductance, id="modflow6"),
    pytest.param(nwt_conductance, id="modflow nwt"),
]


@pytest.mark.parametrize("conductance_of", BACKENDS)
def test_drain_of_the_depression_is_zero(conductance_of) -> None:
    conductance = conductance_of(sink_fill=True, sink=pit_mask())

    assert len(conductance) == N_CELLS
    assert conductance[PIT_CELL] == 0.0
    outside = [value for cell, value in conductance.items() if cell != PIT_CELL]
    assert len(outside) == N_CELLS - 1
    assert all(value == pytest.approx(DRAIN_COND_M2_S) for value in outside)


def test_both_backends_give_the_same_conductance() -> None:
    mf6 = mf6_conductance(sink_fill=True, sink=pit_mask())
    nwt = nwt_conductance(sink_fill=True, sink=pit_mask())

    assert mf6.keys() == nwt.keys()
    assert all(mf6[cell] == pytest.approx(nwt[cell]) for cell in mf6)


def test_switch_off_keeps_the_depression_draining() -> None:
    conductance = mf6_conductance(sink_fill=False, sink=None)

    assert conductance[PIT_CELL] == pytest.approx(DRAIN_COND_M2_S)


@pytest.mark.parametrize("conductance_of", BACKENDS)
def test_drain_needs_the_mask(conductance_of) -> None:
    with pytest.raises(ValueError, match="solver.sink_fill"):
        conductance_of(sink_fill=True, sink=None)


def test_resolver_finds_the_dug_cell() -> None:
    # The function both solvers call, with the answer known by construction.
    mesh = tilted_mesh(dug=True)

    assert resolve_sink_mask(mesh, sink_fill=False, model_name="demo") is None
    mask = resolve_sink_mask(mesh, sink_fill=True, model_name="demo")
    assert mask is not None
    assert np.flatnonzero(mask).tolist() == np.flatnonzero(pit_mask()).tolist()


def test_both_solvers_call_the_resolver() -> None:
    # Every other test passes a mask in by hand, so removing these two calls
    # would leave them green while a real run with the switch on fails in the
    # drain builder.
    nwt_src = inspect.getsource(nwt_solver.ModflowNwt._build_spatial_discretization)
    assert "resolve_sink_mask(" in nwt_src
    assert "self.sink" in nwt_src

    mf6_src = inspect.getsource(mf6_build._mask_lakes)
    assert "resolve_sink_mask(" in mf6_src
    assert "model.sink" in mf6_src


def test_mask_not_measurable_names_the_model() -> None:
    no_active_cell = tilted_mesh(dug=True, inactive=np.ones((1, NROW, NCOL), dtype=bool))

    with pytest.raises(ValueError, match="model 'demo'.*sink_fill"):
        resolve_sink_mask(no_active_cell, sink_fill=True, model_name="demo")


def test_mesh_without_an_active_cell_is_refused() -> None:
    no_active_cell = tilted_mesh(dug=True, inactive=np.ones((1, NROW, NCOL), dtype=bool))

    with pytest.raises(ValueError, match="no active cell"):
        closed_depression_mask(no_active_cell)
