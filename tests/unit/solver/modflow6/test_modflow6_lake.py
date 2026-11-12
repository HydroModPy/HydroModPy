"""The LAK package arguments built from a lake, on a DISV grid.

CONNECTIONDATA is built from the cell mesh because FloPy cannot do it for lakes
on DISV. Each lake column gets one VERTICAL connection to the first active cell
below it, and HORIZONTAL connections (conductance in 1/s, lengths in m) only
across shared edges to active, non-lake cells. The stage-volume-area table
(stage m, volume m3, area m2) must be sorted and strictly increasing.
"""

from __future__ import annotations

import dataclasses
import inspect
import logging
from itertools import pairwise
from types import SimpleNamespace

import flopy
import numpy as np
import pytest
from shapely.geometry import Polygon

from hydromodpy.model.boundaries.boundary_condition_registry import BoundaryConditionBundle
from hydromodpy.solver.modflow6.builders.lake import (
    _lake_connection_floor,
    _refuse_chd_connections,
    _warn_table_off_connection_floor,
    build_exposed_band_runoff_specs,
    build_lak_package_args,
    build_lake_connectiondata,
    build_lake_table,
    build_lakes,
)
from hydromodpy.solver.modflow6.builders.lake_cells import apply_lake_idomain_mask
from hydromodpy.solver.modflow6.builders.mvr import build_mvr_period_records
from hydromodpy.solver.modflow6.builders.sfr import (
    ResolvedSfrNetwork,
    build_drainage_mover_records,
    mover_rows_reach_lake,
)
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from tests._helpers.model_factory import make_model
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays
from validation_cases.numerical.steady.lak_merritt_konikow_p01.geometry import (
    CASE_DIR,
    load_geometry,
)
from validation_cases.numerical.steady.lak_merritt_konikow_p01.runtime_lak import (
    build_hmp_connectiondata,
    build_hmp_solver_mesh,
)
from validation_cases.shared import load_case_tolerances

# A 4x4 unit grid with the central 2x2 block as the lake. Row-major ids.
LAKE_CELLS = [5, 6, 9, 10]
SQUARE_1_TO_3 = Polygon([(1.0, 1.0), (3.0, 1.0), (3.0, 3.0), (1.0, 3.0)])
ABACUS = [(5.0, 0.0, 4.0), (10.0, 20.0, 4.0)]  # stage m, volume m3, area m2


def grid_4x4(top=10.0, step=5.0, nlay=2) -> SolverMesh:
    botm = np.stack([np.full((4, 4), top - (lay + 1) * step) for lay in range(nlay)])
    return solver_mesh_from_structured_arrays(
        nrow=4, ncol=4, top=np.full((4, 4), top), botm=botm, dx=1.0, dy=1.0
    )


def masked_grid() -> SolverMesh:
    return apply_lake_idomain_mask(grid_4x4(), lake_cell_ids_by_lake={"lac0": LAKE_CELLS})


def carved_grid(lake_top=7.0, nlay=3) -> SolverMesh:
    # Neighbour tops stay at 10 m, lake columns are carved down to lake_top.
    top = np.full((4, 4), 10.0)
    for cid in LAKE_CELLS:
        top[cid // 4, cid % 4] = lake_top
    botm = np.stack([np.full((4, 4), 6.0 - lay * 3.0) for lay in range(nlay)])
    return solver_mesh_from_structured_arrays(nrow=4, ncol=4, top=top, botm=botm, dx=1.0, dy=1.0)


def lake_model(**lake) -> SimpleNamespace:
    """One lake called lac0, with the fields given, in a model run in seconds."""
    return SimpleNamespace(
        model_output_name="lac_test",
        time_units="seconds",
        inputs=make_model(
            boundaries=BoundaryConditionBundle(conditions={}, active_ids=("lake",)),
            lakes={"lac0": lake},
        ),
    )


def connectiondata_rows() -> list[list]:
    return build_lake_connectiondata(
        None, lake_index=0, lake_cell_ids=LAKE_CELLS, bedleak=0.5, solver_mesh=masked_grid()
    )


TABLES = [
    pytest.param(
        [(12.0, 50.0, 20.0), (10.0, 0.0, 5.0), (11.0, 20.0, 12.0)],
        [(10.0, 0.0, 5.0), (11.0, 20.0, 12.0), (12.0, 50.0, 20.0)],
        id="rows sorted by stage",
    ),
    pytest.param(
        {"stage": [10.0, 11.0], "volume": [0.0, 20.0], "sarea": [5.0, 12.0]},
        [(10.0, 0.0, 5.0), (11.0, 20.0, 12.0)],
        id="column mapping",
    ),
]


@pytest.mark.parametrize(("abacus", "expected"), TABLES)
def test_lake_table(abacus, expected) -> None:
    table = build_lake_table(None, lake_id="lac0", abacus=abacus)

    assert table == expected
    assert all(b[0] > a[0] for a, b in pairwise(table))


TABLE_REFUSALS = [
    pytest.param(
        [(10.0, 30.0, 5.0), (11.0, 20.0, 12.0)], "volume must strictly increase", id="volume drops"
    ),
    # MF6 lak_read_table aborts when the volume does not rise (v <= v0).
    pytest.param(
        [(10.0, 20.0, 5.0), (11.0, 20.0, 12.0)], "volume must strictly increase", id="volume equal"
    ),
    pytest.param(
        [(10.0, 10.0, 12.0), (11.0, 20.0, 5.0)], "surface area must not decrease", id="area drops"
    ),
    pytest.param(
        [(10.0, 0.0, 5.0), (10.0, 20.0, 12.0)], "strictly increasing", id="stage repeated"
    ),
    pytest.param([(10.0, 0.0, 5.0), (11.0, 20.0, -1.0)], "must be", id="negative area"),
    pytest.param([(10.0, 0.0, 5.0)], "at least two rows", id="one row"),
]


@pytest.mark.parametrize(("abacus", "message"), TABLE_REFUSALS)
def test_lake_table_refusals(abacus, message) -> None:
    with pytest.raises(ValueError, match=message):
        build_lake_table(None, lake_id="lac0", abacus=abacus)


def whole_grid_lake() -> list[list]:
    return build_lake_connectiondata(
        None,
        lake_index=0,
        lake_cell_ids=range(16),
        bedleak=0.5,
        occupied_layers=2,  # the lake fills both layers, so no cell lies below it
        solver_mesh=apply_lake_idomain_mask(
            grid_4x4(), lake_cell_ids_by_lake={"lac0": list(range(16))}
        ),
    )


CONNECTION_REFUSALS = [
    pytest.param(
        lambda: build_lake_connectiondata(
            None, lake_index=0, lake_cell_ids=LAKE_CELLS, bedleak=-1.0, solver_mesh=masked_grid()
        ),
        "bedleak must be >= 0, got -1.0",
        id="negative bedleak",
    ),
    pytest.param(
        lambda: build_lake_connectiondata(
            None, lake_index=0, lake_cell_ids=[], bedleak=0.5, solver_mesh=masked_grid()
        ),
        "at least one lake cell",
        id="no lake cell",
    ),
    pytest.param(whole_grid_lake, "Lake has no aquifer connection", id="no active neighbour"),
    pytest.param(
        lambda: build_lak_package_args(
            lake_model(polygon=SQUARE_1_TO_3, bedleak=0.3, abacus=ABACUS),
            solver_mesh=masked_grid(),
            lake_cell_ids_by_lake={"lac0": []},
        ),
        r"lakes\.lac0 resolved to no grid cell",
        id="polygon off the grid",
    ),
]


@pytest.mark.parametrize(("build", "match"), CONNECTION_REFUSALS)
def test_lake_connection_refusals(build, match) -> None:
    with pytest.raises(ValueError, match=match):
        build()


def test_get_lak_connections_is_not_called() -> None:
    # FloPy's helper does not support lakes on DISV. The docstring may name it,
    # but the builder must never call or import it.
    from hydromodpy.solver.modflow6.builders import lake as lake_module

    source = inspect.getsource(lake_module)

    assert "get_lak_connections(" not in source
    assert "import get_lak_connections" not in source


def test_lak_package_args() -> None:
    args = build_lak_package_args(
        lake_model(polygon=SQUARE_1_TO_3, bedleak=0.3, abacus=ABACUS),
        solver_mesh=masked_grid(),
        lake_cell_ids_by_lake={"lac0": LAKE_CELLS},
    )

    assert args["nlakes"] == 1
    assert args["ntables"] == 1
    # 4 VERTICAL + 8 HORIZONTAL connections for the single lake.
    assert args["packagedata"][0][2] == len(args["connectiondata"]) == 12
    # No bedleak_unit declared, so the value reaches CONNECTIONDATA unchanged (1/s).
    assert {float(row[4]) for row in args["connectiondata"]} == {0.3}
    assert [row[0] for row in args["laktab_specs"][0]["table"]] == [5.0, 10.0]
    # The model runs in seconds, so the conversions stay 1.0 (not 86400).
    assert args["time_conversion"] == 1.0
    assert args["length_conversion"] == 1.0


def test_lak_package_args_without_lake() -> None:
    model = SimpleNamespace(
        inputs=make_model(boundaries=BoundaryConditionBundle(conditions={}, active_ids=()))
    )

    assert build_lak_package_args(model, solver_mesh=grid_4x4()) is None


def test_bedleak_in_per_day_reaches_connectiondata_per_second() -> None:
    model = lake_model(polygon=SQUARE_1_TO_3, bedleak=0.5, bedleak_unit="1/day", abacus=ABACUS)

    args = build_lak_package_args(
        model, solver_mesh=masked_grid(), lake_cell_ids_by_lake={"lac0": LAKE_CELLS}
    )

    # bedleak sits at index 4 of every row, VERTICAL and HORIZONTAL.
    assert {float(row[4]) for row in args["connectiondata"]} == {0.5 / 86400.0}


def test_no_bank_connection_when_the_neighbour_is_not_higher() -> None:
    rows = build_lake_connectiondata(
        None,
        lake_index=0,
        lake_cell_ids=LAKE_CELLS,
        bedleak=0.5,
        solver_mesh=carved_grid(lake_top=10.0),
        dynamic_area=True,
        bank_seepage=True,
    )

    assert not [r for r in rows if r[3] == "HORIZONTAL"]


def test_chd_connection_refusal() -> None:
    rows = connectiondata_rows()
    target = next(r[2] for r in rows if r[3] == "HORIZONTAL")
    dtype = [("cellid", object), ("head", float)]

    def chd_at(cellid):
        record = np.array([(cellid, 5.0)], dtype=dtype).view(np.recarray)
        data = SimpleNamespace(get_data=lambda: {0: record})
        return SimpleNamespace(chd=SimpleNamespace(stress_period_data=data))

    # MF6 fails on the LAK residual when a lake connects to a CHD cell.
    with pytest.raises(ValueError, match="CHD"):
        _refuse_chd_connections(chd_at(target), lake_id="lac0", rows=rows)
    # No CHD package, or a CHD elsewhere, is accepted.
    _refuse_chd_connections(SimpleNamespace(), lake_id="lac0", rows=rows)
    _refuse_chd_connections(chd_at((1, 0)), lake_id="lac0", rows=rows)


def test_table_bottom_against_the_connection_floor(caplog) -> None:
    # MF6 bounds the stage at min(belev), so a table that starts elsewhere warns.
    mesh = carved_grid(lake_top=7.0)
    rows = build_lake_connectiondata(
        None,
        lake_index=0,
        lake_cell_ids=LAKE_CELLS,
        bedleak=0.5,
        solver_mesh=mesh,
        dynamic_area=True,
    )
    floor = _lake_connection_floor(rows, mesh)
    assert floor == 7.0

    with caplog.at_level(logging.WARNING):
        _warn_table_off_connection_floor("lac0", [(7.0, 0.0, 0.0), (8.0, 4.0, 4.0)], floor)
    assert not [r for r in caplog.records if r.levelno == logging.WARNING]

    with caplog.at_level(logging.WARNING):
        _warn_table_off_connection_floor("lac0", [(5.0, 0.0, 0.0), (8.0, 4.0, 4.0)], floor)
    assert any("min(belev)" in r.getMessage() for r in caplog.records)


def test_connection_floor_of_a_flat_bank_row_is_the_cell_bottom() -> None:
    mesh = grid_4x4()  # layer 0 bottom 5 m, layer 1 bottom 0 m
    # belev equals telev (6 m) on a HORIZONTAL row of layer 1, so MF6 takes the cell bottom.
    flat_bank = [0, 0, (1, 4), "HORIZONTAL", 0.5, 6.0, 6.0, 1.0, 1.0]
    sloped_bank = [0, 0, (1, 4), "HORIZONTAL", 0.5, 2.0, 6.0, 1.0, 1.0]

    assert _lake_connection_floor([flat_bank], mesh) == 0.0
    assert _lake_connection_floor([sloped_bank], mesh) == 2.0


def test_a_chd_package_without_records_for_a_period_is_accepted() -> None:
    rows = connectiondata_rows()
    data = SimpleNamespace(get_data=lambda: {0: None, 1: None})

    _refuse_chd_connections(
        SimpleNamespace(chd=SimpleNamespace(stress_period_data=data)), lake_id="lac0", rows=rows
    )


class SlottedModel:
    __slots__ = ()


def test_a_model_that_cannot_hold_the_seal_count_still_builds() -> None:
    rows = build_lake_connectiondata(
        SlottedModel(),
        lake_index=0,
        lake_cell_ids=LAKE_CELLS,
        bedleak=0.5,
        solver_mesh=masked_grid(),
    )

    assert len(rows) == 12  # 4 VERTICAL + 8 HORIZONTAL


def test_lake_cells_come_from_the_polygon_when_not_given() -> None:
    model = lake_model(polygon=SQUARE_1_TO_3, bedleak=0.3, abacus=ABACUS)

    args = build_lak_package_args(model, solver_mesh=grid_4x4())

    assert args["nlakes"] == 1
    assert args["packagedata"][0][2] == 12


def test_a_lake_without_bedleak_gets_the_default(caplog) -> None:
    model = lake_model(polygon=SQUARE_1_TO_3, abacus=ABACUS)

    with caplog.at_level(logging.WARNING):
        args = build_lak_package_args(
            model, solver_mesh=masked_grid(), lake_cell_ids_by_lake={"lac0": LAKE_CELLS}
        )

    assert "has no bedleak; using the default 1.0 1/s" in caplog.text
    assert {float(row[4]) for row in args["connectiondata"]} == {1.0}


def gwf_on_the_4x4_grid(tmp_path):
    """A flopy GWF model on the unit 4 x 4 DISV grid of ``grid_4x4`` (vertex v = 5 * j + i)."""
    sim = flopy.mf6.MFSimulation(sim_name="lak", sim_ws=str(tmp_path))
    flopy.mf6.ModflowTdis(sim)
    gwf = flopy.mf6.ModflowGwf(sim, modelname="lak")
    vertices = [[5 * j + i, float(i), float(j)] for j in range(5) for i in range(5)]
    cell2d = [
        [4 * j + i, i + 0.5, j + 0.5, 4, 5 * j + i, 5 * j + i + 1, 5 * j + i + 6, 5 * j + i + 5]
        for j in range(4)
        for i in range(4)
    ]
    flopy.mf6.ModflowGwfdisv(
        gwf,
        nlay=2,
        ncpl=16,
        nvert=25,
        top=10.0,
        botm=[5.0, 0.0],
        vertices=vertices,
        cell2d=cell2d,
    )
    return gwf


def test_lak_package_and_its_table_are_built(tmp_path) -> None:
    model = lake_model(polygon=SQUARE_1_TO_3, bedleak=0.3, abacus=ABACUS)
    model.gwf = gwf_on_the_4x4_grid(tmp_path)
    model.full_path = tmp_path

    mover_rows, n_lakes, connections = build_lakes(
        model, masked_grid(), {"lac0": LAKE_CELLS}, [], [], None
    )

    assert mover_rows == []
    assert n_lakes == 1
    assert len(connections) == 12  # 4 VERTICAL + 8 HORIZONTAL
    assert model.lak.nlakes.get_data() == 1
    table = model.gwf.get_package("laktab_0").table.get_data()
    assert [row[0] for row in table] == [5.0, 10.0]  # stage (m) at the foot and top of the abacus
    assert model.gwf.get_package("obs_0") is not None
    # The sidecar re-keys the lake observations by lake id at extraction.
    assert (tmp_path / "lac_test.lak.meta.json").is_file()


def test_no_lake_package_without_lake_cells() -> None:
    model = lake_model(polygon=SQUARE_1_TO_3, bedleak=0.3, abacus=ABACUS)

    assert build_lakes(model, masked_grid(), {}, [], [], None) == ([], 0, [])


EXPOSED_BAND_MODELS = [
    pytest.param({}, set(), id="no bed reconstruction"),
    pytest.param({"other": {}}, {"lac0"}, id="lake absent from the reconstruction"),
]


@pytest.mark.parametrize(("reconstruction", "marnage"), EXPOSED_BAND_MODELS)
def test_no_exposed_band_spec_without_a_reconstructed_lake(reconstruction, marnage) -> None:
    model = lake_model(bed_reconstruction=SimpleNamespace(exposed_band_runoff=True))
    model._lake_bed_reconstruction = reconstruction
    model._marnage_lake_ids = marnage

    assert build_exposed_band_runoff_specs(model) == []


# Merritt and Konikow (2000) test 1, ex-gwf-lak-p01: one surface lake, 5x5 cells on
# layer 0. FloPy's get_lak_connections gives 45 connections, 25 VERTICAL and 20
# HORIZONTAL. The counts come from the structural tolerances of the case.


def test_connectiondata_matches_the_published_split() -> None:
    tolerance = dict(load_case_tolerances(CASE_DIR)["structural"])

    rows = build_hmp_connectiondata()

    vertical = [r for r in rows if r[3] == "VERTICAL"]
    horizontal = [r for r in rows if r[3] == "HORIZONTAL"]
    assert len(rows) == int(tolerance["n_connections"]) == 45
    assert len(vertical) == int(tolerance["n_vertical"]) == 25
    assert len(horizontal) == int(tolerance["n_horizontal"]) == 20


def test_one_vertical_connection_per_lake_cell() -> None:
    geometry = load_geometry()

    rows = build_hmp_connectiondata(geometry)

    vertical = [r for r in rows if r[3] == "VERTICAL"]
    assert sorted(int(r[2][1]) for r in vertical) == sorted(geometry.lake_cell_ids)
    # Each one points at layer 1, the first active layer below the surface lake.
    assert all(r[2][0] == 1 for r in vertical)


def test_horizontal_connections_are_valid() -> None:
    geometry = load_geometry()
    lake_set = set(geometry.lake_cell_ids)

    rows = build_hmp_connectiondata(geometry)

    horizontal = [r for r in rows if r[3] == "HORIZONTAL"]
    assert horizontal
    for row in horizontal:
        assert int(row[2][0]) == 0  # the surface lake occupies layer 0
        assert int(row[2][1]) not in lake_set  # bank seepage never joins two lake cells
        assert float(row[7]) > 0.0  # connlen
        assert float(row[8]) > 0.0  # connwidth


def test_lake_cells_are_inactive_on_the_surface_layer() -> None:
    geometry = load_geometry()
    mesh = build_hmp_solver_mesh(geometry)

    masked = apply_lake_idomain_mask(mesh, lake_cell_ids_by_lake={"lac0": geometry.lake_cell_ids})

    lake_cells = geometry.lake_cell_ids
    non_lake = [c for c in range(geometry.n_cells) if c not in set(lake_cells)]
    assert np.all(masked.idomain[0, lake_cells] == 0)
    assert np.all(masked.idomain[1:, lake_cells] == 1)
    assert np.all(masked.idomain[:, non_lake] == 1)


# A lake fed only by the hillslope drainage still announces MOVER. route_drainage hands
# each drain cell to the first reach or lake it meets, and MODFLOW 6 stops at the first
# DRN-to-LAK record if LAK does not advertise MOVER.


def lake_args(*, external_mover_to_lake: bool) -> dict:
    top = np.full((4, 4), 100.0)
    botm = np.stack([np.full((4, 4), 50.0), np.full((4, 4), 0.0)])
    mesh = solver_mesh_from_structured_arrays(nrow=4, ncol=4, top=top, botm=botm, dx=1.0, dy=1.0)
    cells = {"lac0": [0, 1]}
    model = lake_model(
        polygon=Polygon([(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)]),
        bedleak=0.2,
        abacus=[(50.0, 0.0, 4.0), (90.0, 160.0, 4.0)],
        initial_stage=60.0,
        outlets=[],
    )
    return build_lak_package_args(
        model,
        solver_mesh=apply_lake_idomain_mask(mesh, lake_cell_ids_by_lake=cells),
        lake_cell_ids_by_lake=cells,
        external_mover_to_lake=external_mover_to_lake,
    )


def drain_chain_ending_in_a_lake() -> list[list[object]]:
    """MVR rows of a hillslope chain 0 -> 1 -> 2 whose cell 2 is lake number 0."""
    records = build_drainage_mover_records(
        {"net0": ResolvedSfrNetwork("net0", (), {"route_drainage": True})},
        drn_spd={0: [[0, 0, 100.0, 0.05], [0, 1, 100.0, 0.05]]},
        receiver=np.array([1, 2, -1]),
        basin_cell_mask=np.ones(3, dtype=bool),
        face_adjacency=[{1}, {0, 2}, {1}],
        mesh_top=np.zeros(3),
        lake_cells_by_number={0: [2]},
    )
    return build_mvr_period_records(records)


def test_a_drn_row_with_a_lake_receiver_is_counted() -> None:
    rows = drain_chain_ending_in_a_lake()

    assert [row[2] for row in rows] == ["LAK", "LAK"]
    assert mover_rows_reach_lake(rows) is True


def test_a_drn_row_with_a_reach_receiver_is_not() -> None:
    assert mover_rows_reach_lake([["DRN", 0, "SFR", 3, "FACTOR", 1.0]]) is False
    assert mover_rows_reach_lake([]) is False


def test_lak_announces_mover_when_only_the_drainage_feeds_it() -> None:
    fed = mover_rows_reach_lake(drain_chain_ending_in_a_lake())

    assert lake_args(external_mover_to_lake=fed)["mover"] is True
    assert "mover" not in lake_args(external_mover_to_lake=False)


def test_a_marnage_column_with_no_active_layer_is_refused_by_name() -> None:
    # A marnage lake keeps its columns active. One column closed at every layer
    # (outside the catchment mask) has no top active layer, and the bed
    # connection would be written to layer -1.
    mesh = carved_grid(lake_top=7.0)
    idomain = np.array(mesh.idomain, copy=True)
    idomain[:, LAKE_CELLS[0]] = 0
    mesh = dataclasses.replace(mesh, idomain=idomain)
    with pytest.raises(ValueError, match=r"column 5 .* no active layer"):
        build_lake_connectiondata(
            None,
            lake_index=0,
            lake_cell_ids=LAKE_CELLS,
            bedleak=0.5,
            solver_mesh=mesh,
            dynamic_area=True,
        )
