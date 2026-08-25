"""``solver.sink_fill``: no drain in a closed depression, on either backend.

A closed depression has no outlet, so the water reaching it ponds; a drain
there invents a discharge point. The surface below is a plain tilt with one
interior cell dug out, so the depression is known by construction and no test
re-derives it with the helper under test.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.solver.base.solver_config import SolverConfig
from hydromodpy.solver.modflow6.builders.boundary_conditions import (
    build_drain_stress_period_data,
)
from hydromodpy.solver.modflow_common.flow_adapter_helpers import build_preprocess_options
from hydromodpy.solver.modflow_common.options import ModflowPreprocessOptions
from hydromodpy.solver.modflow_common.sink_mask import closed_depression_mask, resolve_sink_mask
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.solver.modflow_nwt.nwt.payloads.well_drainage import build_drainage_spd

NROW = 5
NCOL = 5
N_CELLS = NROW * NCOL
BASE_M = 100.0
PIT_ROW = 2
PIT_COL = 2
PIT_CELL = PIT_ROW * NCOL + PIT_COL
DRAIN_COND_M2_S = 0.05


def _tilted_top(*, dug: bool) -> np.ndarray:
    """A plane dropping one metre per column, optionally dug at one cell.

    Every cell drains east to the mesh edge, so the plane alone has no closed
    depression. Digging one interior cell ten metres down leaves exactly one.
    """
    top = np.repeat(BASE_M - np.arange(NCOL, dtype=float)[None, :], NROW, axis=0)
    if dug:
        top[PIT_ROW, PIT_COL] = BASE_M - 10.0
    return top


def _mesh(*, dug: bool, inactive: np.ndarray | None = None) -> SolverMesh:
    return SolverMesh.from_structured_arrays(
        nrow=NROW,
        ncol=NCOL,
        top=_tilted_top(dug=dug),
        botm=np.zeros((1, NROW, NCOL)),
        dx=10.0,
        dy=10.0,
        inactive_mask=inactive,
    )


def _hand_written_mask() -> np.ndarray:
    """The answer written out by hand, not measured by the code under test."""
    mask = np.zeros(N_CELLS, dtype=bool)
    mask[PIT_CELL] = True
    return mask


def _mf6_model(*, sink_fill: bool, sink: np.ndarray | None) -> SimpleNamespace:
    return SimpleNamespace(
        dem_mask=np.zeros(N_CELLS, dtype=bool),
        nper=1,
        ncpl=N_CELLS,
        hk=np.full((1, N_CELLS), 1e-4),
        sink_fill=sink_fill,
        sink=sink,
        drain_band_depth_m=0.0,
    )


def _nwt_adapter(mesh: SolverMesh, *, sink_fill: bool, sink: np.ndarray | None) -> SimpleNamespace:
    """A stand-in carrying exactly what ``build_drainage_spd`` reads."""
    return SimpleNamespace(
        _is_bc_active=lambda bc_id: bc_id == "drainage",
        _boundary_conditions={"drainage": SimpleNamespace(value=DRAIN_COND_M2_S, units="m2/s")},
        solver_mesh=mesh,
        dem=mesh.reshape_to_grid(mesh.top),
        nrow=NROW,
        ncol=NCOL,
        cell_area=100.0,
        sink_fill=sink_fill,
        sink=None if sink is None else mesh.reshape_to_grid(np.asarray(sink, dtype=bool)),
        drain_band_depth_m=0.0,
    )


def _mf6_conductance_by_cell(spd: dict[int, list[list[float]]]) -> dict[int, float]:
    return {int(row[1]): float(row[3]) for row in spd[0]}


def _nwt_conductance_by_cell(spd: dict[int, np.ndarray]) -> dict[int, float]:
    return {int(row[1]) * NCOL + int(row[2]): float(row[4]) for row in spd[0]}


def test_default_is_off_so_no_existing_run_changes() -> None:
    assert ModflowPreprocessOptions().sink_fill is False
    assert SolverConfig().sink_fill is False
    state = SimpleNamespace(setup=SimpleNamespace(), cfg=SimpleNamespace(solver=SolverConfig()))
    assert build_preprocess_options(state).sink_fill is False


def test_toml_switch_reaches_the_preprocess_options() -> None:
    cfg = SolverConfig.model_validate({"sink_fill": True})
    state = SimpleNamespace(setup=SimpleNamespace(), cfg=SimpleNamespace(solver=cfg))
    assert build_preprocess_options(state).sink_fill is True


def test_mask_holds_the_dug_cell_and_nothing_else() -> None:
    mask = closed_depression_mask(_mesh(dug=True))
    assert np.flatnonzero(mask).tolist() == [PIT_CELL]


def test_a_plain_tilt_has_no_closed_depression() -> None:
    assert not closed_depression_mask(_mesh(dug=False)).any()


def test_mask_ignores_inactive_cells() -> None:
    """An inactive cell is never in a depression and never blocks the escape."""
    inactive = np.zeros((1, NROW, NCOL), dtype=bool)
    inactive[0, 0, :] = True
    mask = closed_depression_mask(_mesh(dug=True, inactive=inactive))
    assert np.flatnonzero(mask).tolist() == [PIT_CELL]


def test_resolve_sink_mask_returns_nothing_when_the_switch_is_off() -> None:
    assert resolve_sink_mask(_mesh(dug=True), sink_fill=False, model_name="demo") is None


def test_resolve_sink_mask_names_the_model_it_could_not_measure() -> None:
    inactive = np.ones((1, NROW, NCOL), dtype=bool)
    with pytest.raises(ValueError, match="model 'demo'.*sink_fill"):
        resolve_sink_mask(_mesh(dug=True, inactive=inactive), sink_fill=True, model_name="demo")


def test_mask_refuses_a_mesh_with_no_active_cell() -> None:
    inactive = np.ones((1, NROW, NCOL), dtype=bool)
    with pytest.raises(ValueError, match="no active cell"):
        closed_depression_mask(_mesh(dug=True, inactive=inactive))


def test_mf6_zeroes_the_drain_of_the_depression_and_keeps_the_others() -> None:
    spd = build_drain_stress_period_data(
        _mf6_model(sink_fill=True, sink=_hand_written_mask()),
        solver_mesh=_mesh(dug=True),
        drainage_cond_series=np.array([DRAIN_COND_M2_S]),
        ocean_support_mask=np.zeros(N_CELLS, dtype=bool),
        stream_support_mask=np.zeros(N_CELLS, dtype=bool),
    )
    conductance = _mf6_conductance_by_cell(spd)
    assert len(conductance) == N_CELLS
    assert conductance[PIT_CELL] == 0.0
    outside = [value for cell, value in conductance.items() if cell != PIT_CELL]
    assert len(outside) == N_CELLS - 1
    assert all(value == pytest.approx(DRAIN_COND_M2_S) for value in outside)


def test_nwt_zeroes_the_drain_of_the_depression_and_keeps_the_others() -> None:
    mesh = _mesh(dug=True)
    spd = build_drainage_spd(
        _nwt_adapter(mesh, sink_fill=True, sink=_hand_written_mask()),
        drain_array=np.ones((NROW, NCOL), dtype=int),
        hk=np.full((1, NROW, NCOL), 1e-4),
    )
    conductance = _nwt_conductance_by_cell(spd)
    assert len(conductance) == N_CELLS
    assert conductance[PIT_CELL] == 0.0
    outside = [value for cell, value in conductance.items() if cell != PIT_CELL]
    assert len(outside) == N_CELLS - 1
    assert all(value == pytest.approx(DRAIN_COND_M2_S) for value in outside)


def test_both_backends_produce_the_same_conductance_field() -> None:
    mesh = _mesh(dug=True)
    mask = _hand_written_mask()
    mf6 = _mf6_conductance_by_cell(
        build_drain_stress_period_data(
            _mf6_model(sink_fill=True, sink=mask),
            solver_mesh=mesh,
            drainage_cond_series=np.array([DRAIN_COND_M2_S]),
            ocean_support_mask=np.zeros(N_CELLS, dtype=bool),
            stream_support_mask=np.zeros(N_CELLS, dtype=bool),
        )
    )
    nwt = _nwt_conductance_by_cell(
        build_drainage_spd(
            _nwt_adapter(mesh, sink_fill=True, sink=mask),
            drain_array=np.ones((NROW, NCOL), dtype=int),
            hk=np.full((1, NROW, NCOL), 1e-4),
        )
    )
    assert mf6.keys() == nwt.keys()
    assert all(mf6[cell] == pytest.approx(nwt[cell]) for cell in mf6)


def test_switching_it_off_leaves_the_depression_draining() -> None:
    spd = build_drain_stress_period_data(
        _mf6_model(sink_fill=False, sink=None),
        solver_mesh=_mesh(dug=True),
        drainage_cond_series=np.array([DRAIN_COND_M2_S]),
        ocean_support_mask=np.zeros(N_CELLS, dtype=bool),
        stream_support_mask=np.zeros(N_CELLS, dtype=bool),
    )
    assert _mf6_conductance_by_cell(spd)[PIT_CELL] == pytest.approx(DRAIN_COND_M2_S)


def test_mf6_refuses_to_build_the_drain_without_the_mask() -> None:
    with pytest.raises(ValueError, match="solver.sink_fill"):
        build_drain_stress_period_data(
            _mf6_model(sink_fill=True, sink=None),
            solver_mesh=_mesh(dug=True),
            drainage_cond_series=np.array([DRAIN_COND_M2_S]),
            ocean_support_mask=np.zeros(N_CELLS, dtype=bool),
            stream_support_mask=np.zeros(N_CELLS, dtype=bool),
        )


def test_nwt_refuses_to_build_the_drain_without_the_mask() -> None:
    mesh = _mesh(dug=True)
    with pytest.raises(ValueError, match="solver.sink_fill"):
        build_drainage_spd(
            _nwt_adapter(mesh, sink_fill=True, sink=None),
            drain_array=np.ones((NROW, NCOL), dtype=int),
            hk=np.full((1, NROW, NCOL), 1e-4),
        )


class TestTheMaskReachesTheModel:
    """The two lines that hand the mask to a model, which nothing else covers.

    Every other test here builds its own model stand-in and passes a mask in by
    hand, so deleting the two ``resolve_sink_mask`` calls in the solvers leaves
    them all green while every real run with the switch on dies in the DRN
    builder. That is the dead wiring this feature existed to remove, so it gets
    its own test.
    """

    def test_both_solvers_resolve_the_mask_on_the_mesh_they_just_built(self) -> None:
        import inspect

        from hydromodpy.solver.modflow6 import build as mf6_build
        from hydromodpy.solver.modflow_nwt.nwt import nwt_solver

        nwt_src = inspect.getsource(nwt_solver.ModflowNwt._build_spatial_discretization)
        assert "resolve_sink_mask(" in nwt_src, "the NWT solver stopped resolving the mask"
        assert "self.sink" in nwt_src

        mf6_src = inspect.getsource(mf6_build.run_pre_processing)
        assert "resolve_sink_mask(" in mf6_src, "MODFLOW 6 stopped resolving the mask"
        assert "model.sink" in mf6_src

    def test_the_resolver_finds_the_dug_cell_on_a_real_solver_mesh(self) -> None:
        # The end-to-end shape, through the very function both solvers call,
        # with the answer known by construction.
        mesh = _mesh(dug=True)
        assert resolve_sink_mask(mesh, sink_fill=False, model_name="demo") is None
        mask = resolve_sink_mask(mesh, sink_fill=True, model_name="demo")
        assert mask is not None
        assert np.flatnonzero(mask).tolist() == np.flatnonzero(_hand_written_mask()).tolist()

    def test_flat_ground_is_not_a_closed_depression(self) -> None:
        """A cell that merely TIES its rim is not a basin.

        Flooding with the descent epsilon lifted every such cell by one
        increment and reported plateaus as depressions. Measured on the Nancon
        mesh before the fix: 270 of 3 023 flagged cells were ties with no basin
        at all, median fill 1.9 mm. Here the western half is dead flat and the
        eastern half drains off the mesh, so the answer is zero by construction.
        """
        top = np.repeat(BASE_M - np.arange(NCOL, dtype=float)[None, :], NROW, axis=0)
        top[:, :3] = BASE_M
        flat_mesh = SolverMesh.from_structured_arrays(
            nrow=NROW,
            ncol=NCOL,
            top=top,
            botm=np.zeros((1, NROW, NCOL)),
            dx=10.0,
            dy=10.0,
        )
        assert not closed_depression_mask(flat_mesh).any()

        # And the same plateau with one cell dug into it still holds exactly it.
        top[PIT_ROW, PIT_COL] = BASE_M - 10.0
        dug_mesh = SolverMesh.from_structured_arrays(
            nrow=NROW,
            ncol=NCOL,
            top=top,
            botm=np.zeros((1, NROW, NCOL)),
            dx=10.0,
            dy=10.0,
        )
        assert np.flatnonzero(closed_depression_mask(dug_mesh)).tolist() == [PIT_CELL]
