"""``solver.drain_band_depth_m``: a sub-cell discharge band, on either backend.

A single drain elevation states the land inside a cell is flat. The band is the
one remedy the USGS documents for that (UZF1 ``SURFDEP``, MODFLOW 6 ``DDRN``):
the drain drops to ``top - D/2`` and its conductance is multiplied by
``top_layer_thickness / D``. The thickness, not the cell area: the conductance
being scaled is already ``Kv*A/b``, so ``b/D`` turns it into ``Kv*A/D``, which
is ``CDRN``. The mesh below therefore gives every column a DIFFERENT thickness,
and none of them equal to the cell area, so a build reading the wrong operand
cannot pass. Nothing is classified and nothing is moved.

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

from hydromodpy.core.field_routing import (
    DRAIN_BAND_DEPTH_ATTR,
    drain_band_depth,
    seepage_mask,
)
from hydromodpy.results.zarr_store import SimulationZarr
from hydromodpy.solver.base.solver_config import SolverConfig
from hydromodpy.solver.modflow6.build import apply_preprocess_options as mf6_apply_options
from hydromodpy.solver.modflow6.builders.boundary_conditions import (
    build_drain_stress_period_data,
)
from hydromodpy.solver.modflow_common.drain_conductance import drain_discharge_band
from hydromodpy.solver.modflow_common.flow_adapter_helpers import build_preprocess_options
from hydromodpy.solver.modflow_common.options import ModflowPreprocessOptions
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.solver.modflow_nwt.nwt.nwt_solver import ModflowNwt
from hydromodpy.solver.modflow_nwt.nwt.payloads.well_drainage import build_drainage_spd

NROW = 2
NCOL = 3
N_CELLS = NROW * NCOL
CELL_SIDE_M = 10.0
CELL_AREA_M2 = 100.0
DRAIN_COND_M2_S = 0.04
BAND_M = 0.5

# The mesh top, by construction: a plane dropping one metre per column.
TOP_BY_CELL: dict[int, float] = {0: 100.0, 1: 99.0, 2: 98.0, 3: 100.0, 4: 99.0, 5: 98.0}

# The top layer thickness, by construction: 4, 5, 6 m per column. Deliberately
# not the cell area (100 m2) and deliberately not constant, so `C * A / D` and
# `C * b / D` cannot agree on any cell.
THICKNESS_BY_CELL: dict[int, float] = {0: 4.0, 1: 5.0, 2: 6.0, 3: 4.0, 4: 5.0, 5: 6.0}

# Hand-written answers for BAND_M = 0.5 m on that mesh.
#   elevation   = top - D/2          = top - 0.25
#   conductance = C * thickness / D  = 0.04 * b / 0.5
BANDED_ELEVATION_BY_CELL: dict[int, float] = {
    0: 99.75,
    1: 98.75,
    2: 97.75,
    3: 99.75,
    4: 98.75,
    5: 97.75,
}
BANDED_COND_BY_CELL: dict[int, float] = {
    0: 0.32,
    1: 0.40,
    2: 0.48,
    3: 0.32,
    4: 0.40,
    5: 0.48,
}


def _mesh() -> SolverMesh:
    top = np.repeat(100.0 - np.arange(NCOL, dtype=float)[None, :], NROW, axis=0)
    thickness = np.repeat(4.0 + np.arange(NCOL, dtype=float)[None, :], NROW, axis=0)
    return SolverMesh.from_structured_arrays(
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
    )


def _nwt_adapter(mesh: SolverMesh, *, band_depth_m: float) -> SimpleNamespace:
    """A stand-in carrying exactly what ``build_drainage_spd`` reads."""
    return SimpleNamespace(
        _is_bc_active=lambda bc_id: bc_id == "drainage",
        _boundary_conditions={"drainage": SimpleNamespace(value=DRAIN_COND_M2_S, units="m2/s")},
        solver_mesh=mesh,
        dem=mesh.reshape_to_grid(mesh.top),
        nrow=NROW,
        ncol=NCOL,
        cell_area=CELL_AREA_M2,
        sink_fill=False,
        sink=None,
        drain_band_depth_m=band_depth_m,
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
    adapter._boundary_conditions = {
        "drainage": SimpleNamespace(value=conductance, units="m2/s"),
    }
    spd = build_drainage_spd(
        adapter,
        drain_array=np.ones((NROW, NCOL), dtype=int),
        hk=np.full((1, NROW, NCOL), 1e-4),
    )
    return {int(row[1]) * NCOL + int(row[2]): (float(row[3]), float(row[4])) for row in spd[0]}


class TestZeroIsTodaysBehaviour:
    """D = 0 is the default and must leave every drain row exactly as it was."""

    def test_the_default_is_zero_everywhere_in_the_chain(self) -> None:
        assert SolverConfig().drain_band_depth_m == 0.0
        assert ModflowPreprocessOptions().drain_band_depth_m == 0.0
        state = SimpleNamespace(setup=SimpleNamespace(), cfg=SimpleNamespace(solver=SolverConfig()))
        assert build_preprocess_options(state).drain_band_depth_m == 0.0

    def test_mf6_rows_are_the_bare_top_and_the_declared_conductance(self) -> None:
        rows = _mf6_rows(band_depth_m=0.0)
        assert rows.keys() == TOP_BY_CELL.keys()
        for cell, (elevation, conductance) in rows.items():
            assert elevation == TOP_BY_CELL[cell]
            assert conductance == DRAIN_COND_M2_S

    def test_nwt_rows_are_the_bare_top_and_the_declared_conductance(self) -> None:
        rows = _nwt_rows(band_depth_m=0.0)
        assert rows.keys() == TOP_BY_CELL.keys()
        for cell, (elevation, conductance) in rows.items():
            assert elevation == TOP_BY_CELL[cell]
            assert conductance == DRAIN_COND_M2_S

    def test_the_hk_fallback_is_untouched_at_zero(self) -> None:
        # hk 1e-4 m/s, area 100 m2, thickness 4 m, cell 0: 1e-4*100/4 = 2.5e-3 m2/s.
        rows = _mf6_rows(band_depth_m=0.0, conductance=0.0)
        assert rows[0] == (100.0, pytest.approx(2.5e-3))

    def test_the_helper_returns_its_inputs_at_zero(self) -> None:
        assert drain_discharge_band(
            top=100.0, conductance=0.04, top_thickness=4.0, band_depth=0.0
        ) == (100.0, 0.04)


class TestTheHandWrittenBand:
    """top - D/2 and C * thickness / D, on both backends."""

    def test_the_helper_alone(self) -> None:
        # 100.0 - 0.5/2 = 99.75 ; 0.04 * 4.0 / 0.5 = 0.32
        elevation, conductance = drain_discharge_band(
            top=100.0, conductance=0.04, top_thickness=4.0, band_depth=0.5
        )
        assert elevation == pytest.approx(99.75)
        assert conductance == pytest.approx(0.32)

    def test_mf6_lowers_the_drain_by_half_the_band(self) -> None:
        rows = _mf6_rows(band_depth_m=BAND_M)
        for cell, (elevation, _) in rows.items():
            assert elevation == pytest.approx(BANDED_ELEVATION_BY_CELL[cell])

    def test_mf6_scales_the_conductance_by_thickness_over_depth(self) -> None:
        rows = _mf6_rows(band_depth_m=BAND_M)
        for cell, (_, conductance) in rows.items():
            assert conductance == pytest.approx(BANDED_COND_BY_CELL[cell])

    def test_nwt_lowers_the_drain_by_half_the_band(self) -> None:
        rows = _nwt_rows(band_depth_m=BAND_M)
        for cell, (elevation, _) in rows.items():
            assert elevation == pytest.approx(BANDED_ELEVATION_BY_CELL[cell])

    def test_nwt_scales_the_conductance_by_thickness_over_depth(self) -> None:
        rows = _nwt_rows(band_depth_m=BAND_M)
        for cell, (_, conductance) in rows.items():
            assert conductance == pytest.approx(BANDED_COND_BY_CELL[cell])

    def test_the_hk_fallback_conductance_is_banded_too(self) -> None:
        # Cell 0: fallback 1e-4*100/4 = 2.5e-3 m2/s, banded 2.5e-3*4/0.5 = 2e-2 m2/s.
        # The thickness cancels: the banded fallback is Kv*A/D exactly, which is
        # CDRN, and it is the same on every column despite b varying.
        mf6 = _mf6_rows(band_depth_m=BAND_M, conductance=0.0)
        nwt = _nwt_rows(band_depth_m=BAND_M, conductance=0.0)
        assert mf6[0] == (pytest.approx(99.75), pytest.approx(2e-2))
        assert nwt[0] == (pytest.approx(99.75), pytest.approx(2e-2))

    def test_a_deeper_band_discharges_lower_and_harder_per_metre(self) -> None:
        # D = 2 m: elevation 99.0, conductance 0.04 * 4 / 2 = 0.08 m2/s.
        rows = _mf6_rows(band_depth_m=2.0)
        assert rows[0] == (pytest.approx(99.0), pytest.approx(0.08))

    def test_it_does_not_move_the_topography(self) -> None:
        mesh = _mesh()
        before = np.array(mesh.top, dtype=float, copy=True)
        build_drain_stress_period_data(
            _mf6_model(band_depth_m=BAND_M),
            solver_mesh=mesh,
            drainage_cond_series=np.array([DRAIN_COND_M2_S]),
            ocean_support_mask=np.zeros(N_CELLS, dtype=bool),
            stream_support_mask=np.zeros(N_CELLS, dtype=bool),
        )
        assert np.array_equal(np.asarray(mesh.top, dtype=float), before)


class TestBothBackendsAgree:
    """One meaning, one behaviour: the same mesh and the same D give the same rows."""

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

    def test_zero_and_positive_depths_are_accepted(self) -> None:
        assert SolverConfig.model_validate({"drain_band_depth_m": 0.0}).drain_band_depth_m == 0.0
        assert SolverConfig.model_validate({"drain_band_depth_m": 0.61}).drain_band_depth_m == 0.61


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

    def test_each_one_alone_is_accepted(self) -> None:
        assert SolverConfig.model_validate({"sink_fill": True}).sink_fill is True
        assert SolverConfig.model_validate({"drain_band_depth_m": 0.5}).drain_band_depth_m == 0.5

    def test_sink_fill_with_a_zero_band_stays_valid(self) -> None:
        # Every configuration written before this option existed keeps loading.
        cfg = SolverConfig.model_validate({"sink_fill": True, "drain_band_depth_m": 0.0})
        assert cfg.sink_fill is True
        assert cfg.drain_band_depth_m == 0.0

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

    TOML = '[solver]\ndrain_band_depth_m = 0.5\n\n[solver.backend]\nbackend = "modflow6"\n'

    def _options(self) -> ModflowPreprocessOptions:
        cfg = SolverConfig.model_validate(tomllib.loads(self.TOML)["solver"])
        assert cfg.drain_band_depth_m == BAND_M
        state = SimpleNamespace(setup=SimpleNamespace(), cfg=SimpleNamespace(solver=cfg))
        return build_preprocess_options(state)

    def test_the_parsed_toml_reaches_the_preprocess_options(self) -> None:
        assert self._options().drain_band_depth_m == BAND_M

    def test_it_reaches_the_mf6_drain_rows(self) -> None:
        model = _mf6_model(band_depth_m=0.0)
        model.geographic = SimpleNamespace(
            watershed_box_buff_dem="box.tif", watershed_buff_dem="dem.tif"
        )
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
        assert rows[0] == (pytest.approx(99.75), pytest.approx(BANDED_COND_BY_CELL[0]))

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
        assert float(spd[0][0][4]) == pytest.approx(BANDED_COND_BY_CELL[0])

    def test_the_steady_initial_condition_model_inherits_the_depth(self) -> None:
        # The auxiliary steady model must build the same drains as the transient
        # one, or the initial heads come from a different boundary condition.
        import inspect

        from hydromodpy.solver.modflow6.support import steady_initial_conditions as mf6_ssic
        from hydromodpy.solver.modflow_nwt.nwt import steady_initial_conditions as nwt_ssic

        for module, name in (
            (mf6_ssic, "run_modflow6_steady_state_initialization"),
            (nwt_ssic, "run_nwt_steady_state_initialization"),
        ):
            source = inspect.getsource(getattr(module, name))
            assert "drain_band_depth_m" in source, f"{name} drops the discharge band"


class TestTheSeepageCriterionFollowsTheBand:
    """A banded drain moves where the water table stops, so the mask must move too.

    The criterion is ``watertable >= topography``. A banded drain sits at
    ``top - D/2`` and holds the head there, so on a banded run the untouched
    test returns an all-false mask while the drains are discharging. That is
    the one reader the band cannot leave alone, and the depth travels to it in
    the store rather than through a call chain, so a figure drawn months later
    reads the same criterion the run was built with.
    """

    TOP = np.array([100.0, 100.0, 100.0])
    # One cell above the top, one inside a 1 m band, one well below it.
    WATERTABLE = np.array([100.2, 99.7, 98.0])

    def test_without_a_band_only_the_cell_above_the_top_seeps(self) -> None:
        mask = seepage_mask(watertable=self.WATERTABLE, topography=self.TOP)

        assert mask.tolist() == [1.0, 0.0, 0.0]

    def test_a_band_lets_the_cell_inside_it_seep(self) -> None:
        # D = 1 m puts the drain at 99.5, and 99.7 >= 99.5.
        mask = seepage_mask(watertable=self.WATERTABLE, topography=self.TOP, band_depth=1.0)

        assert mask.tolist() == [1.0, 1.0, 0.0]

    def test_the_band_does_not_make_every_cell_seep(self) -> None:
        mask = seepage_mask(watertable=self.WATERTABLE, topography=self.TOP, band_depth=1.0)

        assert mask[2] == 0.0

    def test_a_solver_declared_flux_still_wins_over_the_geometry(self) -> None:
        mask = seepage_mask(
            watertable=self.WATERTABLE,
            topography=self.TOP,
            surface_excess=np.array([0.0, 0.0, 1e-6]),
            band_depth=1.0,
        )

        assert mask.tolist() == [0.0, 0.0, 1.0]

    def test_a_stack_is_banded_the_same_way_as_one_step(self) -> None:
        stack = np.vstack([self.WATERTABLE, self.WATERTABLE])
        mask = seepage_mask(watertable=stack, topography=self.TOP, band_depth=1.0)

        assert mask.shape == (2, 3)
        assert mask.tolist() == [[1.0, 1.0, 0.0], [1.0, 1.0, 0.0]]


class TestTheBandTravelsInTheStore:
    """The depth has to survive the run, or a figure re-derives a different mask."""

    def test_a_store_that_never_saw_the_option_reads_zero(self, tmp_path) -> None:
        sz = SimulationZarr.create(tmp_path / "plain.zarr", n_cells=3, n_layers=1)
        try:
            assert drain_band_depth(sz.root) == 0.0
            assert sz.drain_band_depth_m == 0.0
        finally:
            sz.close()

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

    def test_a_nonsense_depth_in_a_store_reads_as_no_band(self, tmp_path) -> None:
        # Never written by the code, but a store is a file a user can edit, and
        # the criterion must not silently lower every drain by half a nan.
        sz = SimulationZarr.create(tmp_path / "broken.zarr", n_cells=3, n_layers=1)
        try:
            sz.root.attrs[DRAIN_BAND_DEPTH_ATTR] = float("nan")
            assert drain_band_depth(sz.root) == 0.0
            sz.root.attrs[DRAIN_BAND_DEPTH_ATTR] = -2.0
            assert drain_band_depth(sz.root) == 0.0
        finally:
            sz.close()
