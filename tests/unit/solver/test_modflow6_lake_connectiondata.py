"""The home-grown LAK CONNECTIONDATA builder on a DISV grid.

``flopy.mf6.utils.get_lak_connections`` does not support embedded / horizontal
lakes on DISV, so ``builders/lake.py`` builds CONNECTIONDATA itself with
``flopy.utils.GridIntersect`` and the mesh geometry. The invariants under test:

* exactly one VERTICAL connection per lake column, pointing at the first active
  cell below the occupied layers (``cellid = (lay, cell2d)``);
* HORIZONTAL connections only across shared edges to active, non-lake neighbours,
  never to another lake cell;
* ``connwidth`` equals the shared-edge length and ``connlen`` is strictly
  positive for every HORIZONTAL row.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace

import flopy
import numpy as np
from shapely.geometry import Polygon

from hydromodpy.solver.modflow6.builders import (
    apply_lake_idomain_mask,
    build_lak_package_args,
    build_lake_connectiondata,
    build_vertex_grid_for_intersection,
    resolve_lake_cells,
)
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh

# A 4x4, 2-layer unit grid with the central 2x2 block as the lake footprint.
# Row-major flat ids: the centre cells are 5, 6, 9, 10.
_LAKE_CELLS = [5, 6, 9, 10]


def _grid_4x4(nlay: int = 2) -> SolverMesh:
    top = np.full((4, 4), 10.0)
    botm = np.stack([np.full((4, 4), 10.0 - (lay + 1) * 5.0) for lay in range(nlay)])
    return SolverMesh.from_structured_arrays(nrow=4, ncol=4, top=top, botm=botm, dx=1.0, dy=1.0)


def _masked_grid() -> SolverMesh:
    mesh = _grid_4x4(nlay=2)
    return apply_lake_idomain_mask(mesh, lake_cell_ids_by_lake={"lac0": _LAKE_CELLS})


def _rows() -> list[list]:
    mesh = _masked_grid()
    return build_lake_connectiondata(
        None,
        lake_index=0,
        lake_cell_ids=_LAKE_CELLS,
        bedleak=0.5,
        solver_mesh=mesh,
    )


def test_one_vertical_connection_per_lake_column() -> None:
    rows = _rows()
    vertical = [r for r in rows if r[3] == "VERTICAL"]
    # One VERTICAL per lake cell, each to the active cell below (layer 1).
    assert len(vertical) == len(_LAKE_CELLS)
    vert_cells = sorted(int(r[2][1]) for r in vertical)
    assert vert_cells == sorted(_LAKE_CELLS)
    for r in vertical:
        assert r[2][0] == 1  # layer 1 (first active below the occupied layer 0)


def test_horizontal_connects_only_to_active_non_lake_neighbours() -> None:
    rows = _rows()
    horizontal = [r for r in rows if r[3] == "HORIZONTAL"]
    assert horizontal, "the lake must have bank-seepage HORIZONTAL connections"

    lake_set = set(_LAKE_CELLS)
    for r in horizontal:
        lay, neighbour = int(r[2][0]), int(r[2][1])
        assert lay == 0  # surface lake occupies layer 0 only
        # Negative invariant: never connect a lake cell to another lake cell.
        assert neighbour not in lake_set
        connwidth = float(r[8])
        connlen = float(r[7])
        # connwidth = shared-edge length (unit grid -> exactly 1.0).
        assert connwidth == 1.0
        # connlen = neighbour-centroid to edge half distance (0.5 on a unit grid).
        assert connlen > 0.0
        assert connlen == 0.5


def test_connectiondata_cellid_is_layer_cell2d_tuple() -> None:
    rows = _rows()
    for r in rows:
        cellid = r[2]
        assert isinstance(cellid, tuple)
        assert len(cellid) == 2  # (lay, cell2d) for DISV


def test_horizontal_count_matches_perimeter_edges() -> None:
    # The 2x2 lake block exposes 8 outer edges to the surrounding active ring.
    rows = _rows()
    horizontal = [r for r in rows if r[3] == "HORIZONTAL"]
    assert len(horizontal) == 8


def test_belev_telev_clip_to_neighbour_cell() -> None:
    rows = _rows()
    horizontal = [r for r in rows if r[3] == "HORIZONTAL"]
    for r in horizontal:
        belev, telev = float(r[5]), float(r[6])
        # Layer-0 neighbour spans 5..10 m; the lake top is 10 m, bottom 5 m.
        assert belev == 5.0
        assert telev == 10.0
        assert telev > belev


def test_builder_does_not_use_get_lak_connections() -> None:
    # get_lak_connections does not support embedded/horizontal lakes on DISV, so
    # the home-grown builder must never call it for the multi-cell case.
    from hydromodpy.solver.modflow6.builders import lake as lake_mod

    source = inspect.getsource(lake_mod)
    # The docstring may name it as the reason it is avoided; what must not happen
    # is an actual call or import of it.
    assert "get_lak_connections(" not in source
    assert "import get_lak_connections" not in source


def test_resolve_lake_cells_intersects_polygon() -> None:
    mesh = _grid_4x4(nlay=2)
    vertex_grid = build_vertex_grid_for_intersection(mesh)
    # The central 2x2 polygon (1,1)-(3,3) covers exactly cells 5,6,9,10.
    polygon = Polygon([(1.0, 1.0), (3.0, 1.0), (3.0, 3.0), (1.0, 3.0)])
    cells = resolve_lake_cells(None, lake_id="lac0", polygon=polygon, vertex_grid=vertex_grid)
    assert cells == sorted(_LAKE_CELLS)


def _model_with_lake() -> SimpleNamespace:
    polygon = Polygon([(1.0, 1.0), (3.0, 1.0), (3.0, 3.0), (1.0, 3.0)])
    abacus = [(5.0, 0.0, 4.0), (10.0, 20.0, 4.0)]
    return SimpleNamespace(
        model_output_name="lac_test",
        time_units="seconds",
        flow=SimpleNamespace(
            active_bc=["lake"],
            sinks_sources={
                "lakes": {"lac0": {"polygon": polygon, "bedleak": 0.3, "abacus": abacus}}
            },
        ),
    )


def test_build_lak_package_args_produces_packagedata_and_table() -> None:
    masked = _masked_grid()
    model = _model_with_lake()
    args = build_lak_package_args(
        model,
        solver_mesh=masked,
        lake_cell_ids_by_lake={"lac0": _LAKE_CELLS},
    )
    assert args is not None
    assert args["nlakes"] == 1
    assert args["ntables"] == 1
    # nlakeconn = len(connectiondata) for the single lake (4 VERTICAL + 8 HORIZONTAL).
    nlakeconn = args["packagedata"][0][2]
    assert nlakeconn == len(args["connectiondata"]) == 12
    # No bedleak_unit declared -> the value reaches CONNECTIONDATA unchanged (1/s).
    assert {float(row[4]) for row in args["connectiondata"]} == {0.3}
    # The abacus laktab is attached and well-formed (3 columns, sorted stage).
    spec = args["laktab_specs"][0]
    assert [row[0] for row in spec["table"]] == [5.0, 10.0]
    # HMP TDIS is seconds: outlet conversions stay 1.0 (NOT 86400).
    assert args["time_conversion"] == 1.0
    assert args["length_conversion"] == 1.0


def test_build_lak_package_args_is_none_without_lake() -> None:
    model = SimpleNamespace(flow=SimpleNamespace(active_bc=[], sinks_sources={}))
    assert build_lak_package_args(model, solver_mesh=_grid_4x4()) is None


def test_build_lak_package_args_converts_bedleak_unit_into_connectiondata() -> None:
    # A bedleak declared in 1/day must reach the CONNECTIONDATA in 1/s: HMP runs
    # TDIS in seconds, so a non-SI leakance would otherwise be off by 86400. The
    # default seconds case (no bedleak_unit) must stay untouched.
    polygon = Polygon([(1.0, 1.0), (3.0, 1.0), (3.0, 3.0), (1.0, 3.0)])
    abacus = [(5.0, 0.0, 4.0), (10.0, 20.0, 4.0)]
    model = SimpleNamespace(
        model_output_name="lac_test",
        time_units="seconds",
        flow=SimpleNamespace(
            active_bc=["lake"],
            sinks_sources={
                "lakes": {
                    "lac0": {
                        "polygon": polygon,
                        "bedleak": 0.5,
                        "bedleak_unit": "1/day",
                        "abacus": abacus,
                    }
                }
            },
        ),
    )
    args = build_lak_package_args(
        model,
        solver_mesh=_masked_grid(),
        lake_cell_ids_by_lake={"lac0": _LAKE_CELLS},
    )
    assert args is not None
    # bedleak lives at index 4 of every CONNECTIONDATA row (VERTICAL + HORIZONTAL).
    bedleaks = {float(row[4]) for row in args["connectiondata"]}
    assert bedleaks == {0.5 / 86400.0}


def test_modflowgwflak_builds_with_expected_nlakeconn_and_laktab(tmp_path: Path) -> None:
    masked = _masked_grid()
    model = _model_with_lake()
    args = build_lak_package_args(
        model,
        solver_mesh=masked,
        lake_cell_ids_by_lake={"lac0": _LAKE_CELLS},
    )
    assert args is not None
    laktab_specs = args.pop("laktab_specs")
    obs_continuous = args.pop("obs_continuous")
    args.pop("lake_obs_meta")

    sim = flopy.mf6.MFSimulation(sim_name="sim", sim_ws=str(tmp_path), exe_name="mf6")
    flopy.mf6.ModflowTdis(sim, nper=1, perioddata=[(1.0, 1, 1.0)], time_units="SECONDS")
    gwf = flopy.mf6.ModflowGwf(sim, modelname="flow", newtonoptions=["NEWTON", "UNDER_RELAXATION"])
    ims = flopy.mf6.ModflowIms(sim, filename="flow.ims")
    sim.register_ims_package(ims, [gwf.name])
    flopy.mf6.ModflowGwfdisv(
        gwf,
        nlay=masked.nlay,
        **masked.to_disv_kwargs(),
        idomain=masked.idomain(),
        xorigin=0.0,
        yorigin=0.0,
        length_units="METERS",
    )
    flopy.mf6.ModflowGwfic(gwf, strt=10.0)
    flopy.mf6.ModflowGwfnpf(gwf, icelltype=1, k=1.0)

    lak = flopy.mf6.ModflowGwflak(gwf, pname="LAK", **args)
    for spec in laktab_specs:
        flopy.mf6.ModflowUtllaktab(
            gwf,
            nrow=len(spec["table"]),
            ncol=3,
            table=spec["table"],
            filename=spec["filename"],
            parent_file=lak,
        )
    lak.obs.initialize(
        filename="flow.lak.obs", digits=10, print_input=False, continuous=obs_continuous
    )

    # The single lake carries all 12 connections (4 VERTICAL + 8 HORIZONTAL).
    assert int(lak.nlakes.get_data()) == 1
    packagedata = lak.packagedata.get_data()
    assert int(packagedata["nlakeconn"][0]) == 12
    # An abacus table is attached as a child package.
    assert int(lak.ntables.get_data()) == 1
    laktab_children = [p for p in gwf.packagelist if p.package_type == "laktab"]
    assert len(laktab_children) == 1
    # OBS6 requests one continuous CSV with a stage observation per lake.
    obs_csv = next(iter(obs_continuous))
    assert any(obs[1] == "stage" for obs in obs_continuous[obs_csv])
