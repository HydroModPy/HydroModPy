"""Conductance (m2/s) and elevation (m) of the drains both MODFLOW backends write.

Without a configured conductance C = hk * cell_area / bed_thickness (m/s * m2 / m).
A discharge band D (m) lowers the drain to top - D/2 and scales C by bed_thickness / D.
MODFLOW 6 and MODFLOW-NWT share the helpers and must write the same rows.
"""

from __future__ import annotations

import logging
import tomllib
from types import SimpleNamespace

import numpy as np
import pytest
from pydantic import ValidationError

from hydromodpy.core.budget.flux import DRAIN_BAND_DEPTH_ATTR, drain_band_depth
from hydromodpy.model.boundaries.boundary_condition_registry import BoundaryConditionBundle
from hydromodpy.model.model import ModelOptions
from hydromodpy.results.zarr_store.simulation_zarr import SimulationZarr
from hydromodpy.solver.base.drain_conductance import (
    drain_discharge_band,
    hk_fallback_drain_conductance,
)
from hydromodpy.solver.base.solver_config import SolverConfig
from hydromodpy.solver.modflow6.build import apply_preprocess_options as mf6_apply_options
from hydromodpy.solver.modflow6.builders import boundary_conditions as mf6_boundaries
from hydromodpy.solver.modflow_common.flow_run import build_preprocess_options
from hydromodpy.solver.modflow_nwt.nwt.nwt_solver import ModflowNwt
from hydromodpy.solver.modflow_nwt.nwt.payloads import well_drainage
from hydromodpy.solver.modflow_nwt.nwt.payloads.well_drainage import build_drainage_spd
from tests._helpers.model_factory import make_model
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays

N_CELLS = 6
CELL_AREA_M2 = 100.0  # 10 m x 10 m
HK_M_S = 1e-4
DRAIN_COND_M2_S = 0.04
BAND_M = 0.5
BED_M = 2.0

# A plane dropping 1 m per column on a 2 x 3 grid, with layers of 4, 5 and 6 m.
# The drain rows must not depend on the layer thickness.
TOP_BY_CELL = {0: 100.0, 1: 99.0, 2: 98.0, 3: 100.0, 4: 99.0, 5: 98.0}
# top - D/2, for D = 0.5 m
BANDED_ELEVATION_BY_CELL = {0: 99.75, 1: 98.75, 2: 97.75, 3: 99.75, 4: 98.75, 5: 97.75}
BANDED_COND_M2_S = 0.16  # 0.04 * 2.0 / 0.5


def drn_model(bed_thickness_m=1.0, band_depth_m=0.0, nper=1):
    return SimpleNamespace(
        dem_mask=np.zeros(N_CELLS, dtype=bool),
        nper=nper,
        ncpl=N_CELLS,
        hk=np.full((1, N_CELLS), HK_M_S),
        sink_fill=False,
        sink=None,
        drain_band_depth_m=band_depth_m,
        drain_bed_thickness_m=bed_thickness_m,
        drain_conductance_floor_m2_s=1e-12,
    )


def flat_strip(layer_thickness_m):
    """One row of six 10 m cells, top at the layer thickness above a flat bottom."""
    return solver_mesh_from_structured_arrays(
        nrow=1,
        ncol=N_CELLS,
        top=np.full((1, N_CELLS), layer_thickness_m),
        botm=np.zeros((1, 1, N_CELLS)),
        dx=10.0,
        dy=10.0,
    )


def sloped_plane():
    top = np.repeat(100.0 - np.arange(3, dtype=float)[None, :], 2, axis=0)
    thickness = np.repeat(4.0 + np.arange(3, dtype=float)[None, :], 2, axis=0)
    return solver_mesh_from_structured_arrays(
        nrow=2, ncol=3, top=top, botm=(top - thickness)[None, :, :], dx=10.0, dy=10.0
    )


def unequal_cells():
    """Six drained cells of 0.5 to 12 m2, like the triangles of a refined gmsh mesh."""
    areas = np.array([0.5, 1.0, 2.0, 4.0, 8.0, 12.0])
    return SimpleNamespace(
        top=np.full(6, 5.0),
        cell_areas=lambda: areas,
        top_active_layer=lambda: np.zeros(6, dtype=int),
        top_active_cell_top=lambda: np.full(6, 5.0),
    )


def mf6_spd(model, mesh, series):
    return mf6_boundaries.build_drain_stress_period_data(
        model,
        solver_mesh=mesh,
        drainage_cond_series=np.asarray(series, dtype=float),
        ocean_support_mask=np.zeros(N_CELLS, dtype=bool),
        stream_support_mask=np.zeros(N_CELLS, dtype=bool),
    )


def mf6_rows(band_depth_m, conductance=DRAIN_COND_M2_S):
    """MODFLOW 6 rows on the sloped plane as {cell: (elevation, conductance)}."""
    spd = mf6_spd(
        drn_model(bed_thickness_m=BED_M, band_depth_m=band_depth_m), sloped_plane(), [conductance]
    )
    return {int(row[1]): (float(row[2]), float(row[3])) for row in spd[0]}


def nwt_rows(band_depth_m, conductance=DRAIN_COND_M2_S):
    """MODFLOW-NWT rows on the sloped plane, in the same form."""
    mesh = sloped_plane()
    drainage = SimpleNamespace(value=conductance, units="m2/s")
    adapter = SimpleNamespace(
        model=make_model(
            boundaries=BoundaryConditionBundle(
                conditions={"drainage": drainage}, active_ids=("drainage",)
            )
        ),
        solver_mesh=mesh,
        dem=mesh.reshape_to_grid(mesh.top),
        nrow=2,
        ncol=3,
        cell_area=CELL_AREA_M2,
        sink_fill=False,
        sink=None,
        drain_band_depth_m=band_depth_m,
        drain_bed_thickness_m=BED_M,
        drain_conductance_floor_m2_s=1e-12,
    )
    spd = build_drainage_spd(
        adapter, drain_array=np.ones((2, 3), dtype=int), hk=np.full((1, 2, 3), HK_M_S)
    )
    return {int(row[1]) * 3 + int(row[2]): (float(row[3]), float(row[4])) for row in spd[0]}


HK_FALLBACK = [
    # hk 1e-4 m/s * area 100 m2 / bed 5 m
    pytest.param(1e-4, 5.0, 2.0e-3, id="bed 5 m"),
    pytest.param(1e-4, 10.0, 1.0e-3, id="doubled bed halves it"),
    # a zero-K cell would be read by MODFLOW as no drain at all
    pytest.param(0.0, 5.0, 1e-12, id="zero K takes the floor"),
]


@pytest.mark.parametrize(("hk", "bed_m", "expected"), HK_FALLBACK)
def test_hk_fallback_conductance(hk, bed_m, expected):
    value = hk_fallback_drain_conductance(
        hk=hk, cell_area=CELL_AREA_M2, bed_thickness=bed_m, floor_m2_s=1e-12
    )
    assert value == pytest.approx(expected)


FALLBACK_ON_STRIP = [
    # 1e-4 * 100 / bed, whatever the layer thickness
    pytest.param(1.0, 5.0, 1.0e-2, id="bed 1 m"),
    pytest.param(2.0, 5.0, 5.0e-3, id="bed 2 m"),
    pytest.param(1.0, 10.0, 1.0e-2, id="layer 10 m"),
    pytest.param(1.0, 40.0, 1.0e-2, id="layer 40 m"),
]


@pytest.mark.parametrize(("bed_m", "layer_m", "expected"), FALLBACK_ON_STRIP)
def test_mf6_fallback_conductance(bed_m, layer_m, expected):
    # A thicker aquifer must not make the drain less conductive.
    spd = mf6_spd(drn_model(bed_thickness_m=bed_m), flat_strip(layer_m), [0.0])
    assert len(spd[0]) == N_CELLS
    assert spd[0][0][3] == pytest.approx(expected)


def test_mf6_configured_conductance_bypasses_fallback():
    model = drn_model()
    model.hk = np.full((1, N_CELLS), 99.0)  # large hk must be ignored
    assert mf6_spd(model, flat_strip(5.0), [0.05])[0][0][3] == pytest.approx(0.05)


def test_mf6_static_conductance_collapses_to_one_period():
    # MODFLOW 6 reuses period 0, so a long daily run does not rewrite every drain row.
    spd = mf6_spd(drn_model(nper=6940), flat_strip(5.0), np.zeros(6940))
    assert sorted(spd) == [0]
    assert len(spd[0]) == N_CELLS


def test_mf6_emits_a_period_only_when_conductance_changes():
    series = np.zeros(100)
    series[10:] = 0.05
    series[60:] = 0.08
    spd = mf6_spd(drn_model(nper=100), flat_strip(5.0), series)
    assert sorted(spd) == [0, 10, 60]
    assert spd[10][0][3] == pytest.approx(0.05)
    assert spd[60][0][3] == pytest.approx(0.08)


def test_nwt_and_mf6_share_the_fallback_helper():
    assert well_drainage.hk_fallback_drain_conductance is hk_fallback_drain_conductance
    mf6_value = mf6_spd(drn_model(), flat_strip(5.0), [0.0])[0][0][3]
    nwt_value = hk_fallback_drain_conductance(
        hk=1e-4, cell_area=CELL_AREA_M2, bed_thickness=1.0, floor_m2_s=1e-12
    )
    assert mf6_value == pytest.approx(nwt_value) == pytest.approx(1.0e-2)


def test_conductance_per_cell_on_unequal_cells_is_reported_once(caplog):
    # One conductance per cell drains C / A per unit area, 24-fold here. A second
    # build of the same model (a calibration trial) adds nothing.
    model, mesh = drn_model(), unequal_cells()
    with caplog.at_level(logging.WARNING):
        spd = mf6_spd(model, mesh, [1e-7])
        mf6_spd(model, mesh, [1e-7])
    assert [row[3] for row in spd[0]] == pytest.approx([1e-7] * 6)
    reports = [r.getMessage() for r in caplog.records if "conductance per cell" in r.getMessage()]
    assert len(reports) == 1
    assert "0.5 to 12 m2" in reports[0] and "24.0-fold" in reports[0]
    assert "solver.drain_bed_thickness_m" in reports[0]


def test_derived_conductance_on_unequal_cells_is_not_reported(caplog):
    # C = K * A / b follows the area, so the leakance K / b is the same everywhere.
    with caplog.at_level(logging.WARNING):
        spd = mf6_spd(drn_model(), unequal_cells(), [0.0])
    assert "conductance per cell" not in caplog.text
    leakance = [row[3] / area for row, area in zip(spd[0], unequal_cells().cell_areas())]
    assert leakance == pytest.approx([1e-4] * 6)


def test_auxiliary_model_does_not_repeat_the_report(caplog):
    model = drn_model()
    model.auxiliary = True
    with caplog.at_level(logging.WARNING):
        mf6_spd(model, unequal_cells(), [1e-7])
    assert "conductance per cell" not in caplog.text


def test_band_helper():
    # 100 - 0.5 / 2 = 99.75 m and 0.04 * 2.0 / 0.5 = 0.16 m2/s
    elevation, conductance = drain_discharge_band(
        top=100.0, conductance=0.04, bed_thickness=BED_M, band_depth=BAND_M
    )
    assert elevation == pytest.approx(99.75)
    assert conductance == pytest.approx(0.16)


def test_zero_band_leaves_the_fallback_untouched():
    # 1e-4 * 100 / 2 m = 5e-3 m2/s, the layer thickness does not enter.
    rows = mf6_rows(band_depth_m=0.0, conductance=0.0)
    for cell in (0, 1, 2):
        assert rows[cell] == (TOP_BY_CELL[cell], pytest.approx(5e-3))


BACKENDS = [pytest.param(mf6_rows, id="mf6"), pytest.param(nwt_rows, id="nwt")]


@pytest.mark.parametrize("rows_of", BACKENDS)
def test_band_lowers_the_drain_and_scales_conductance(rows_of):
    rows = rows_of(band_depth_m=BAND_M)
    assert rows.keys() == BANDED_ELEVATION_BY_CELL.keys()
    for cell, (elevation, conductance) in rows.items():
        assert elevation == pytest.approx(BANDED_ELEVATION_BY_CELL[cell])
        assert conductance == pytest.approx(BANDED_COND_M2_S)


@pytest.mark.parametrize("rows_of", BACKENDS)
def test_band_applies_to_the_fallback_conductance(rows_of):
    # 5e-3 * 2 / 0.5 = 2e-2 m2/s. The bed cancels, the result is Kv * A / D.
    rows = rows_of(band_depth_m=BAND_M, conductance=0.0)
    assert rows[0] == (pytest.approx(99.75), pytest.approx(2e-2))


def test_band_as_deep_as_the_bed_keeps_the_declared_conductance():
    # D = 2 m = bed: elevation 99.0 m, conductance 0.04 * 2 / 2 = 0.04 m2/s.
    assert mf6_rows(band_depth_m=2.0)[0] == (pytest.approx(99.0), pytest.approx(0.04))


@pytest.mark.parametrize("conductance", [DRAIN_COND_M2_S, 0.0], ids=["declared", "fallback"])
@pytest.mark.parametrize("band_depth_m", [0.0, 0.25, 0.5, 1.0, 2.0])
def test_backends_write_the_same_rows(band_depth_m, conductance):
    mf6 = mf6_rows(band_depth_m, conductance)
    nwt = nwt_rows(band_depth_m, conductance)
    assert mf6.keys() == nwt.keys()
    for cell in mf6:
        assert mf6[cell] == pytest.approx(nwt[cell])


def test_backends_call_the_same_band_helper():
    assert mf6_boundaries.drain_discharge_band is drain_discharge_band
    assert well_drainage.drain_discharge_band is drain_discharge_band


def test_closed_depression_keeps_its_row_with_no_conductance():
    model = drn_model(bed_thickness_m=BED_M, band_depth_m=BAND_M)
    model.sink_fill = True
    model.sink = np.array([False, False, True, False, False, False])
    spd = mf6_spd(model, sloped_plane(), [DRAIN_COND_M2_S])
    conductance = {int(row[1]): float(row[3]) for row in spd[0]}
    assert conductance[2] == 0.0
    assert conductance[1] == pytest.approx(BANDED_COND_M2_S)


TOML = '[solver]\nbackend = "modflow6"\ndrain_band_depth_m = 0.5\ndrain_bed_thickness_m = 2.0\n'


def preprocess_options_from_toml():
    cfg = SolverConfig.model_validate(tomllib.loads(TOML)["solver"])
    assert cfg.drain_band_depth_m == BAND_M
    assert cfg.drain_bed_thickness_m == BED_M
    return build_preprocess_options(make_model(options=ModelOptions.from_settings(cfg)))


def test_depth_from_toml_reaches_the_mf6_rows():
    model = drn_model(bed_thickness_m=BED_M)
    mf6_apply_options(model, preprocess_options_from_toml())
    assert model.drain_band_depth_m == BAND_M
    spd = mf6_spd(model, sloped_plane(), [DRAIN_COND_M2_S])
    row = next(row for row in spd[0] if int(row[1]) == 0)
    assert (float(row[2]), float(row[3])) == (pytest.approx(99.75), pytest.approx(BANDED_COND_M2_S))


def test_depth_from_toml_reaches_the_nwt_rows():
    solver = SimpleNamespace(preprocess_options=None, _select_active_dem=lambda box: None)
    ModflowNwt._apply_preprocess_options(solver, preprocess_options_from_toml())
    assert solver.drain_band_depth_m == BAND_M
    # Same chain as the rows above, the band comes from the options.
    assert nwt_rows(solver.drain_band_depth_m)[0] == (
        pytest.approx(99.75),
        pytest.approx(BANDED_COND_M2_S),
    )


def test_band_survives_the_store(tmp_path):
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


def test_band_off_leaves_no_attribute_in_the_store(tmp_path):
    sz = SimulationZarr.create(tmp_path / "cleared.zarr", n_cells=3, n_layers=1)
    try:
        sz.drain_band_depth_m = BAND_M
        sz.drain_band_depth_m = 0.0
        assert DRAIN_BAND_DEPTH_ATTR not in sz.root.attrs
        assert sz.drain_band_depth_m == 0.0
    finally:
        sz.close()


def test_sink_fill_and_band_cannot_be_set_together():
    # sink_fill zeroes the drain of exactly the cells the band is set for.
    payload = tomllib.loads("[solver]\nsink_fill = true\ndrain_band_depth_m = 0.5\n")["solver"]
    with pytest.raises(ValidationError) as excinfo:
        SolverConfig.model_validate(payload)
    assert "solver.sink_fill" in str(excinfo.value)
    assert "solver.drain_band_depth_m" in str(excinfo.value)
    cfg = SolverConfig.model_validate({"drain_band_depth_m": 0.5})
    with pytest.raises(ValidationError, match="cannot both be set"):
        cfg.sink_fill = True


REFUSED_BANDS = [
    pytest.param("-0.5", "solver.drain_band_depth_m", id="negative"),
    pytest.param("-1.0", "cannot be negative", id="negative message"),
    pytest.param("nan", "solver.drain_band_depth_m must be a finite", id="nan"),
    pytest.param("inf", "solver.drain_band_depth_m must be a finite", id="infinity"),
]


@pytest.mark.parametrize(("depth", "message"), REFUSED_BANDS)
def test_refusals(depth, message):
    payload = tomllib.loads(f"[solver]\ndrain_band_depth_m = {depth}\n")["solver"]
    with pytest.raises(ValidationError, match=message):
        SolverConfig.model_validate(payload)
