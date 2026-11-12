"""The home-grown LAK CONNECTIONDATA builder on a DISV grid.

``flopy.mf6.utils.get_lak_connections`` does not support embedded / horizontal
lakes on DISV, so ``builders/lake.py`` builds CONNECTIONDATA itself from the cell
mesh. The invariants under test:

* exactly one VERTICAL connection per lake column, pointing at the first active
  cell below the occupied layers (``cellid = (lay, cell2d)``);
* HORIZONTAL connections only across shared edges to active, non-lake neighbors,
  never to another lake cell;
* ``connwidth`` equals the shared-edge length and ``connlen`` is strictly
  positive for every HORIZONTAL row.
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace

import numpy as np
from shapely.geometry import Point, Polygon

from hydromodpy.model.boundaries.boundary_condition_registry import BoundaryConditionBundle
from hydromodpy.solver.modflow6.builders._lake_geometry import _drop_interior_rings
from hydromodpy.solver.modflow6.builders.lake import (
    build_lak_package_args,
    build_lake_connectiondata,
)
from hydromodpy.solver.modflow6.builders.lake_cells import apply_lake_idomain_mask
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from tests._helpers.model_factory import make_model
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays

# A 4x4, 2-layer unit grid with the central 2x2 block as the lake footprint.
# Row-major flat ids: the center cells are 5, 6, 9, 10.
_LAKE_CELLS = [5, 6, 9, 10]


def _grid_4x4(nlay: int = 2) -> SolverMesh:
    top = np.full((4, 4), 10.0)
    botm = np.stack([np.full((4, 4), 10.0 - (lay + 1) * 5.0) for lay in range(nlay)])
    return solver_mesh_from_structured_arrays(nrow=4, ncol=4, top=top, botm=botm, dx=1.0, dy=1.0)


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


def test_builder_does_not_use_get_lak_connections() -> None:
    # get_lak_connections does not support embedded/horizontal lakes on DISV, so
    # the home-grown builder must never call it for the multi-cell case.
    from hydromodpy.solver.modflow6.builders import lake as lake_mod

    source = inspect.getsource(lake_mod)
    # The docstring may name it as the reason it is avoided; what must not happen
    # is an actual call or import of it.
    assert "get_lak_connections(" not in source
    assert "import get_lak_connections" not in source


def test_drop_interior_rings_removes_holes() -> None:
    solid = Polygon([(0.0, 0.0), (3.0, 0.0), (3.0, 3.0), (0.0, 3.0)])
    holed = Polygon(
        [(0.0, 0.0), (3.0, 0.0), (3.0, 3.0), (0.0, 3.0)],
        holes=[[(1.0, 1.0), (2.0, 1.0), (2.0, 2.0), (1.0, 2.0)]],
    )
    assert len(holed.interiors) == 1
    filled = _drop_interior_rings(holed)
    assert len(filled.interiors) == 0
    assert filled.covers(Point(1.5, 1.5))  # the former hole is now inside
    # A geometry without interior rings is returned unchanged.
    assert _drop_interior_rings(solid) is solid


def _model_with_lake() -> SimpleNamespace:
    polygon = Polygon([(1.0, 1.0), (3.0, 1.0), (3.0, 3.0), (1.0, 3.0)])
    abacus = [(5.0, 0.0, 4.0), (10.0, 20.0, 4.0)]
    return SimpleNamespace(
        model_output_name="lac_test",
        time_units="seconds",
        inputs=make_model(
            boundaries=BoundaryConditionBundle(conditions={}, active_ids=("lake",)),
            lakes={"lac0": {"polygon": polygon, "bedleak": 0.3, "abacus": abacus}},
        ),
    )


def test_resolve_lake_occupied_layers_reads_config_default_and_override() -> None:
    from hydromodpy.solver.modflow6.builders.lake_cells import resolve_lake_occupied_layers

    model = SimpleNamespace(
        inputs=make_model(
            boundaries=BoundaryConditionBundle(conditions={}, active_ids=("lake",)),
            lakes={
                "surface": {"polygon": None, "bedleak": 0.1},
                "deep": {"polygon": None, "bedleak": 0.1, "occupied_layers": 3},
            },
        ),
    )
    # A lake without the field defaults to a surface lake (1); a deep reservoir
    # carries its declared occupied-layer count.
    assert resolve_lake_occupied_layers(model) == {"surface": 1, "deep": 3}


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
    model = SimpleNamespace(
        inputs=make_model(boundaries=BoundaryConditionBundle(conditions={}, active_ids=()))
    )
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
        inputs=make_model(
            boundaries=BoundaryConditionBundle(conditions={}, active_ids=("lake",)),
            lakes={
                "lac0": {
                    "polygon": polygon,
                    "bedleak": 0.5,
                    "bedleak_unit": "1/day",
                    "abacus": abacus,
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


def _south_wall(mesh: SolverMesh) -> tuple[set[tuple[int, int]], float]:
    """The faces a wall on the south shore of the lake bars, and the shore ordinate."""
    from shapely.geometry import LineString

    from hydromodpy.solver.modflow6.builders.lake import cutoff_wall_pairs

    cen = mesh.cell_centers()
    body = cen[_LAKE_CELLS].mean(axis=0)
    y_wall = float(min(cen[c][1] for c in _LAKE_CELLS)) - 0.5
    # West to east, so the lake lies on the left of the wall.
    wall = LineString([(float(body[0]) - 5.0, y_wall), (float(body[0]) + 5.0, y_wall)])
    return cutoff_wall_pairs({"cutoff_wall_line": wall}, _LAKE_CELLS, mesh), y_wall


def _carved_grid(lake_top: float = 7.0, nlay: int = 3) -> SolverMesh:
    # Neighbor tops at 10 m, lake columns carved down to ``lake_top``.
    top = np.full((4, 4), 10.0)
    for cid in _LAKE_CELLS:
        top[cid // 4, cid % 4] = lake_top
    botm = np.stack([np.full((4, 4), 6.0 - lay * 3.0) for lay in range(nlay)])
    return solver_mesh_from_structured_arrays(nrow=4, ncol=4, top=top, botm=botm, dx=1.0, dy=1.0)


def test_marnage_bank_absent_when_neighbour_is_not_higher() -> None:
    # A neighbor whose top is at the bed level offers no bank face.
    mesh = _carved_grid(lake_top=10.0)
    rows = build_lake_connectiondata(
        None,
        lake_index=0,
        lake_cell_ids=_LAKE_CELLS,
        bedleak=0.5,
        solver_mesh=mesh,
        dynamic_area=True,
        bank_seepage=True,
    )
    assert not [r for r in rows if r[3] == "HORIZONTAL"]


def test_lake_connected_to_a_chd_cell_is_refused() -> None:
    # CHD: MF6 fails on the LAK residual when a lake connects to a CHD cell.
    import pytest

    from hydromodpy.solver.modflow6.builders.lake import _refuse_chd_connections

    rows = _rows()
    target = next(r[2] for r in rows if r[3] == "HORIZONTAL")
    dtype = [("cellid", object), ("head", float)]
    chd_rec = np.array([(target, 5.0)], dtype=dtype).view(np.recarray)
    chd = SimpleNamespace(stress_period_data=SimpleNamespace(get_data=lambda: {0: chd_rec}))
    with pytest.raises(ValueError, match="CHD"):
        _refuse_chd_connections(SimpleNamespace(chd=chd), lake_id="lac0", rows=rows)
    # No CHD package, or a CHD elsewhere: accepted.
    _refuse_chd_connections(SimpleNamespace(), lake_id="lac0", rows=rows)
    far = np.array([((1, 0), 5.0)], dtype=dtype).view(np.recarray)
    other = SimpleNamespace(stress_period_data=SimpleNamespace(get_data=lambda: {0: far}))
    _refuse_chd_connections(SimpleNamespace(chd=other), lake_id="lac0", rows=rows)


def test_table_bottom_is_compared_to_the_connection_floor(caplog) -> None:
    # LAK-7: MF6 bounds the stage at min(belev); a table away from it warns.
    import logging

    from hydromodpy.solver.modflow6.builders.lake import (
        _lake_connection_floor,
        _warn_table_off_connection_floor,
    )

    mesh = _carved_grid(lake_top=7.0)
    rows = build_lake_connectiondata(
        None,
        lake_index=0,
        lake_cell_ids=_LAKE_CELLS,
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
