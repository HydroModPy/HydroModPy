"""``solver.drain_band_depth_m``: a sub-cell discharge band, on either backend.

A single drain elevation states the land inside a cell is flat. The band is the
one remedy the USGS documents for that (UZF1 ``SURFDEP``, MODFLOW 6 ``DDRN``):
the drain drops to ``top - D/2`` and its conductance is multiplied by
``bed_thickness / D``. The DRAIN BED thickness, not the cell area and not the
layer: the conductance being scaled is already ``Kv*A/M``, so ``M/D`` turns it
into ``Kv*A/D``, which is ``CDRN``. The mesh below still gives every column a
different LAYER thickness, on purpose: the rows must not depend on it.

Every expected number here is written out by hand from a mesh whose top, cell
area and conductance are fixed by construction, never read back from the code
under test.
"""

from __future__ import annotations

import math
import tomllib
from types import SimpleNamespace

import numpy as np
import pytest
from pydantic import ValidationError

from hydromodpy.core.budget.flux import DRAIN_BAND_DEPTH_ATTR, drain_band_depth
from hydromodpy.model.boundaries.boundary_condition_registry import BoundaryConditionBundle
from hydromodpy.model.model import ModelOptions
from hydromodpy.results.zarr_store.simulation_zarr import SimulationZarr
from hydromodpy.solver.base.drain_conductance import drain_discharge_band
from hydromodpy.solver.base.solver_config import SolverConfig
from hydromodpy.solver.modflow6.build import apply_preprocess_options as mf6_apply_options
from hydromodpy.solver.modflow6.builders.boundary_conditions import (
    build_drain_stress_period_data,
)
from hydromodpy.solver.modflow_common.flow_run import build_preprocess_options
from hydromodpy.solver.modflow_common.options import ModflowPreprocessOptions
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.solver.modflow_nwt.nwt.nwt_solver import ModflowNwt
from hydromodpy.solver.modflow_nwt.nwt.payloads.well_drainage import build_drainage_spd
from tests._helpers.model_factory import make_model
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays

NROW = 2
NCOL = 3
N_CELLS = NROW * NCOL
CELL_SIDE_M = 10.0
CELL_AREA_M2 = 100.0
DRAIN_COND_M2_S = 0.04
BAND_M = 0.5

# The mesh top, by construction: a plane dropping one meter per column.
TOP_BY_CELL: dict[int, float] = {0: 100.0, 1: 99.0, 2: 98.0, 3: 100.0, 4: 99.0, 5: 98.0}

# The DRAIN BED thickness, a declared scalar. The mesh below still varies its
# LAYER thickness per column (4, 5, 6 m), which the drain rows must ignore.
BED_M = 2.0

# Hand-written answers for BAND_M = 0.5 m on that mesh.
#   elevation   = top - D/2   = top - 0.25
#   conductance = C * M / D   = 0.04 * 2.0 / 0.5 = 0.16 partout
BANDED_ELEVATION_BY_CELL: dict[int, float] = {
    0: 99.75,
    1: 98.75,
    2: 97.75,
    3: 99.75,
    4: 98.75,
    5: 97.75,
}
BANDED_COND_M2_S = 0.16


def _mesh() -> SolverMesh:
    top = np.repeat(100.0 - np.arange(NCOL, dtype=float)[None, :], NROW, axis=0)
    thickness = np.repeat(4.0 + np.arange(NCOL, dtype=float)[None, :], NROW, axis=0)
    return solver_mesh_from_structured_arrays(
        nrow=NROW,
        ncol=NCOL,
        top=top,
        botm=(top - thickness)[None, :, :],
        dx=CELL_SIDE_M,
        dy=CELL_SIDE_M,
    )


def _mf6_model(*, band_depth_m: float) -> SimpleNamespace:
    return SimpleNamespace(
        dem_mask=np.zeros(N_CELLS, dtype=bool),
        nper=1,
        ncpl=N_CELLS,
        hk=np.full((1, N_CELLS), 1e-4),
        sink_fill=False,
        sink=None,
        drain_band_depth_m=band_depth_m,
        drain_bed_thickness_m=BED_M,
        drain_conductance_floor_m2_s=1e-12,
    )


def _drainage_model(conductance: float):
    """A model whose only active boundary is a drainage of the given conductance."""
    drainage = SimpleNamespace(value=conductance, units="m2/s")
    return make_model(
        boundaries=BoundaryConditionBundle(
            conditions={"drainage": drainage}, active_ids=("drainage",)
        )
    )


def _nwt_adapter(mesh: SolverMesh, *, band_depth_m: float) -> SimpleNamespace:
    """A stand-in carrying exactly what ``build_drainage_spd`` reads."""
    return SimpleNamespace(
        model=_drainage_model(DRAIN_COND_M2_S),
        solver_mesh=mesh,
        dem=mesh.reshape_to_grid(mesh.top),
        nrow=NROW,
        ncol=NCOL,
        cell_area=CELL_AREA_M2,
        sink_fill=False,
        sink=None,
        drain_band_depth_m=band_depth_m,
        drain_bed_thickness_m=BED_M,
        drain_conductance_floor_m2_s=1e-12,
    )


def _mf6_rows(*, band_depth_m: float, conductance: float = DRAIN_COND_M2_S) -> dict[int, tuple]:
    spd = build_drain_stress_period_data(
        _mf6_model(band_depth_m=band_depth_m),
        solver_mesh=_mesh(),
        drainage_cond_series=np.array([conductance]),
        ocean_support_mask=np.zeros(N_CELLS, dtype=bool),
        stream_support_mask=np.zeros(N_CELLS, dtype=bool),
    )
    return {int(row[1]): (float(row[2]), float(row[3])) for row in spd[0]}


def _nwt_rows(*, band_depth_m: float, conductance: float = DRAIN_COND_M2_S) -> dict[int, tuple]:
    mesh = _mesh()
    adapter = _nwt_adapter(mesh, band_depth_m=band_depth_m)
    adapter.model = _drainage_model(conductance)
    spd = build_drainage_spd(
        adapter,
        drain_array=np.ones((NROW, NCOL), dtype=int),
        hk=np.full((1, NROW, NCOL), 1e-4),
    )
    return {int(row[1]) * NCOL + int(row[2]): (float(row[3]), float(row[4])) for row in spd[0]}


class TestZeroIsTodaysBehaviour:
    """D = 0 is the default and must leave every drain row exactly as it was."""

    def test_the_hk_fallback_is_untouched_at_zero(self) -> None:
        # hk 1e-4 m/s, area 100 m2, bed 2 m: 1e-4*100/2 = 5e-3 m2/s, and the
        # LAYER thickness (4, 5, 6 m per column) must not enter it.
        rows = _mf6_rows(band_depth_m=0.0, conductance=0.0)
        assert rows[0] == (100.0, pytest.approx(5e-3))
        assert rows[1] == (99.0, pytest.approx(5e-3))
        assert rows[2] == (98.0, pytest.approx(5e-3))


class TestTheHandWrittenBand:
    """top - D/2 and C * thickness / D, on both backends."""

    def test_the_helper_alone(self) -> None:
        # 100.0 - 0.5/2 = 99.75 ; 0.04 * 2.0 / 0.5 = 0.16
        elevation, conductance = drain_discharge_band(
            top=100.0, conductance=0.04, bed_thickness=BED_M, band_depth=0.5
        )
        assert elevation == pytest.approx(99.75)
        assert conductance == pytest.approx(0.16)

    def test_mf6_lowers_the_drain_by_half_the_band(self) -> None:
        rows = _mf6_rows(band_depth_m=BAND_M)
        for cell, (elevation, _) in rows.items():
            assert elevation == pytest.approx(BANDED_ELEVATION_BY_CELL[cell])

    def test_mf6_scales_the_conductance_by_bed_over_depth(self) -> None:
        rows = _mf6_rows(band_depth_m=BAND_M)
        for _cell, (_, conductance) in rows.items():
            assert conductance == pytest.approx(BANDED_COND_M2_S)

    def test_nwt_lowers_the_drain_by_half_the_band(self) -> None:
        rows = _nwt_rows(band_depth_m=BAND_M)
        for cell, (elevation, _) in rows.items():
            assert elevation == pytest.approx(BANDED_ELEVATION_BY_CELL[cell])

    def test_nwt_scales_the_conductance_by_bed_over_depth(self) -> None:
        rows = _nwt_rows(band_depth_m=BAND_M)
        for _cell, (_, conductance) in rows.items():
            assert conductance == pytest.approx(BANDED_COND_M2_S)

    def test_the_hk_fallback_conductance_is_banded_too(self) -> None:
        # Cell 0: fallback 1e-4*100/2 = 5e-3 m2/s, banded 5e-3*2/0.5 = 2e-2 m2/s.
        # The bed thickness cancels: the banded fallback is Kv*A/D exactly.
        mf6 = _mf6_rows(band_depth_m=BAND_M, conductance=0.0)
        nwt = _nwt_rows(band_depth_m=BAND_M, conductance=0.0)
        assert mf6[0] == (pytest.approx(99.75), pytest.approx(2e-2))
        assert nwt[0] == (pytest.approx(99.75), pytest.approx(2e-2))

    def test_a_deeper_band_discharges_lower_and_harder_per_metre(self) -> None:
        # D = 2 m = BED_M: elevation 99.0, conductance 0.04 * 2 / 2 = 0.04,
        # la valeur declaree inchangee.
        rows = _mf6_rows(band_depth_m=2.0)
        assert rows[0] == (pytest.approx(99.0), pytest.approx(0.04))


class TestBothBackendsAgree:
    """One meaning, one behavior: the same mesh and the same D give the same rows."""

    @pytest.mark.parametrize("band_depth_m", [0.0, 0.25, 0.5, 1.0, 2.0])
    def test_same_mesh_same_depth_same_rows(self, band_depth_m: float) -> None:
        mf6 = _mf6_rows(band_depth_m=band_depth_m)
        nwt = _nwt_rows(band_depth_m=band_depth_m)
        assert mf6.keys() == nwt.keys()
        for cell in mf6:
            assert mf6[cell][0] == pytest.approx(nwt[cell][0])
            assert mf6[cell][1] == pytest.approx(nwt[cell][1])

    @pytest.mark.parametrize("band_depth_m", [0.0, 0.5, 2.0])
    def test_they_agree_on_the_hk_fallback_too(self, band_depth_m: float) -> None:
        mf6 = _mf6_rows(band_depth_m=band_depth_m, conductance=0.0)
        nwt = _nwt_rows(band_depth_m=band_depth_m, conductance=0.0)
        assert mf6.keys() == nwt.keys()
        for cell in mf6:
            assert mf6[cell][0] == pytest.approx(nwt[cell][0])
            assert mf6[cell][1] == pytest.approx(nwt[cell][1])

    def test_both_builders_call_the_same_shared_helper(self) -> None:
        from hydromodpy.solver.modflow6.builders import boundary_conditions as mf6_bc
        from hydromodpy.solver.modflow_nwt.nwt.payloads import well_drainage

        assert mf6_bc.drain_discharge_band is drain_discharge_band
        assert well_drainage.drain_discharge_band is drain_discharge_band


class TestRefusedAtConfigurationLoad:
    """A depth that is not a depth is refused by name, before any solver runs."""

    def test_a_negative_depth_is_refused_by_name(self) -> None:
        with pytest.raises(ValidationError, match="solver.drain_band_depth_m"):
            SolverConfig.model_validate({"drain_band_depth_m": -0.5})

    def test_a_negative_depth_read_from_toml_is_refused(self) -> None:
        payload = tomllib.loads("[solver]\ndrain_band_depth_m = -1.0\n")["solver"]
        with pytest.raises(ValidationError, match="cannot be negative"):
            SolverConfig.model_validate(payload)

    def test_nan_is_refused_by_name(self) -> None:
        payload = tomllib.loads("[solver]\ndrain_band_depth_m = nan\n")["solver"]
        assert math.isnan(payload["drain_band_depth_m"])
        with pytest.raises(ValidationError, match="solver.drain_band_depth_m must be a finite"):
            SolverConfig.model_validate(payload)

    def test_infinity_is_refused_by_name(self) -> None:
        payload = tomllib.loads("[solver]\ndrain_band_depth_m = inf\n")["solver"]
        with pytest.raises(ValidationError, match="solver.drain_band_depth_m must be a finite"):
            SolverConfig.model_validate(payload)


class TestTheSinkFillInteraction:
    """The pair is refused: two opposite answers to the same question.

    ``sink_fill`` deletes the discharge of a depressed cell; the band gives every
    cell a deeper one. Set together, ``sink_fill`` zeroes the conductance of
    exactly the cells the band was set for, so the depth would silently do
    nothing where it matters most.
    """

    def test_the_pair_is_refused_and_both_keys_are_named(self) -> None:
        payload = tomllib.loads("[solver]\nsink_fill = true\ndrain_band_depth_m = 0.5\n")["solver"]
        with pytest.raises(ValidationError) as excinfo:
            SolverConfig.model_validate(payload)
        message = str(excinfo.value)
        assert "solver.sink_fill" in message
        assert "solver.drain_band_depth_m" in message

    def test_assigning_the_pair_afterwards_is_refused_too(self) -> None:
        cfg = SolverConfig.model_validate({"drain_band_depth_m": 0.5})
        with pytest.raises(ValidationError, match="cannot both be set"):
            cfg.sink_fill = True


class TestTheDepthReachesTheDrainRows:
    """The whole chain, TOML text to drain row, on both backends.

    The sibling feature shipped a switch nothing read. This walks the real
    functions: ``tomllib`` -> ``SolverConfig`` -> ``build_preprocess_options``
    -> each backend's ``apply_preprocess_options`` -> the DRN rows.
    """

    # The bed thickness is declared too: it scales the conductance just as
    # much as the band does, so a run that carried the depth but dropped the
    # bed would still be silently wrong.
    TOML = '[solver]\nbackend = "modflow6"\ndrain_band_depth_m = 0.5\ndrain_bed_thickness_m = 2.0\n'

    def _options(self) -> ModflowPreprocessOptions:
        cfg = SolverConfig.model_validate(tomllib.loads(self.TOML)["solver"])
        assert cfg.drain_band_depth_m == BAND_M
        assert cfg.drain_bed_thickness_m == BED_M
        return build_preprocess_options(make_model(options=ModelOptions.from_settings(cfg)))

    def test_it_reaches_the_mf6_drain_rows(self) -> None:
        model = _mf6_model(band_depth_m=0.0)
        mf6_apply_options(model, self._options())
        assert model.drain_band_depth_m == BAND_M

        spd = build_drain_stress_period_data(
            model,
            solver_mesh=_mesh(),
            drainage_cond_series=np.array([DRAIN_COND_M2_S]),
            ocean_support_mask=np.zeros(N_CELLS, dtype=bool),
            stream_support_mask=np.zeros(N_CELLS, dtype=bool),
        )
        rows = {int(row[1]): (float(row[2]), float(row[3])) for row in spd[0]}
        assert rows[0] == (pytest.approx(99.75), pytest.approx(BANDED_COND_M2_S))

    def test_it_reaches_the_nwt_drain_rows(self) -> None:
        solver = SimpleNamespace(
            preprocess_options=None,
            _select_active_dem=lambda box: None,
        )
        ModflowNwt._apply_preprocess_options(solver, self._options())
        assert solver.drain_band_depth_m == BAND_M

        mesh = _mesh()
        adapter = _nwt_adapter(mesh, band_depth_m=solver.drain_band_depth_m)
        spd = build_drainage_spd(
            adapter,
            drain_array=np.ones((NROW, NCOL), dtype=int),
            hk=np.full((1, NROW, NCOL), 1e-4),
        )
        assert float(spd[0][0][3]) == pytest.approx(99.75)
        assert float(spd[0][0][4]) == pytest.approx(BANDED_COND_M2_S)


class TestTheBandTravelsInTheStore:
    """The depth has to survive the run, or a figure re-derives a different mask."""

    def test_the_depth_written_is_the_depth_read_back(self, tmp_path) -> None:
        sz = SimulationZarr.create(tmp_path / "banded.zarr", n_cells=3, n_layers=1)
        try:
            sz.drain_band_depth_m = BAND_M
        finally:
            sz.close()

        reopened = SimulationZarr(tmp_path / "banded.zarr")
        try:
            assert reopened.drain_band_depth_m == pytest.approx(BAND_M)
            assert drain_band_depth(reopened.root) == pytest.approx(BAND_M)
        finally:
            reopened.close()

    def test_turning_the_band_off_leaves_no_attribute_behind(self, tmp_path) -> None:
        sz = SimulationZarr.create(tmp_path / "cleared.zarr", n_cells=3, n_layers=1)
        try:
            sz.drain_band_depth_m = BAND_M
            sz.drain_band_depth_m = 0.0

            assert DRAIN_BAND_DEPTH_ATTR not in sz.root.attrs
            assert sz.drain_band_depth_m == 0.0
        finally:
            sz.close()


class TestTheDrainedCells:
    """The rows follow the cell order and leave out the cells another package holds."""

    def test_a_closed_depression_keeps_its_row_with_no_conductance(self) -> None:
        model = _mf6_model(band_depth_m=BAND_M)
        model.sink_fill = True
        model.sink = np.array([False, False, True, False, False, False])

        spd = build_drain_stress_period_data(
            model,
            solver_mesh=_mesh(),
            drainage_cond_series=np.array([DRAIN_COND_M2_S]),
            ocean_support_mask=np.zeros(N_CELLS, dtype=bool),
            stream_support_mask=np.zeros(N_CELLS, dtype=bool),
        )

        conductance = {int(row[1]): float(row[3]) for row in spd[0]}
        assert conductance[2] == 0.0
        assert conductance[1] == pytest.approx(BANDED_COND_M2_S)
