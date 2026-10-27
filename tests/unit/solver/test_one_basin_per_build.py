"""A build computes the basin of D once; every consumer reads that one.

``run_basin`` is the single call site of ``descent_basin``. The drainage
routing and the discharge observable read the basin the build kept, never a
second computation. A model without a basin falls back on the old support
``polygon_covers`` and says so. A domain that is the catchment floods D from
its outlet; a boxed domain keeps the rim flood, bit for bit.

The consumers that read the basin from a store or a sidecar rather than from the
model have their own "descent_basin raises" spies beside their other cases: the
budget zone in ``test_the_catchment_budget_zone_reads_the_basin_of_the_build``,
the ``_catchment`` series and their runoff area in ``test_catchment_aggregation``,
the calibration readers in ``test_the_criterion_reads_the_basin_of_d``.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.core import descent as core_descent
from hydromodpy.core.descent import DescentBasin
from hydromodpy.solver.modflow6 import build
from hydromodpy.solver.modflow_common import mesh_descent
from hydromodpy.solver.modflow_common.catchment_support import catchment_cell_mask
from hydromodpy.solver.modflow_common.mesh_descent import build_solver_mesh_descent, run_basin
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.model.hydro_mesh import CellBlock, HydroMesh
from tests._helpers.solver_meshes import solver_mesh_from, solver_mesh_from_structured_arrays
from tests._helpers.ugrid_meshes import quad_mesh

N = 10


def _top(nrow: int = N, ncol: int = N) -> np.ndarray:
    """Two valleys running south with a little noise, so the rim keeps cells of its own."""
    rows, cols = np.divmod(np.arange(nrow * ncol), ncol)
    centre = np.where(cols < ncol // 2, 2, 7)
    noise = np.random.default_rng(3).uniform(0.0, 0.4, nrow * ncol)
    return 100.0 + 0.5 * (nrow - 1 - rows) + np.abs(cols - centre) + noise


def _grid() -> SolverMesh:
    """10 m cells, mesh row 0 is the northern row, cell ``row * N + col``."""
    return solver_mesh_from_structured_arrays(
        nrow=N, ncol=N, top=_top().reshape(N, N), botm=np.full((1, N, N), -50.0), dx=10.0, dy=10.0
    )


def _triangles() -> SolverMesh:
    vertices, quads = quad_mesh(N, N, cell_size=10.0)
    triangles = [tri for a, b, c, d in quads.tolist() for tri in ([a, b, c], [a, c, d])]
    return solver_mesh_from(
        HydroMesh(
            vertices=vertices[:, :2],
            cell_blocks=(CellBlock(CellType.TRIANGLE, np.asarray(triangles)),),
        ),
        top=np.repeat(_top(), 2),
        botm=np.full((1, 2 * N * N), -50.0),
        inactive_mask=np.zeros((1, 2 * N * N), dtype=bool),
    )


def _outlet_xy(row: int = N - 1, col: int = 2) -> tuple[float, float]:
    return (10.0 * col + 5.0, 10.0 * (N - 1 - row) + 5.0)


def _geographic(**extra: object) -> SimpleNamespace:
    x, y = _outlet_xy()
    return SimpleNamespace(x_outlet=x, y_outlet=y, **extra)


def _model(tmp_path, geographic: object) -> SimpleNamespace:
    return SimpleNamespace(
        model_name="flow",
        flow=SimpleNamespace(active_bc=[], sinks_sources={}),
        full_path=str(tmp_path),
        model_output_name="flow",
        geographic=geographic,
    )


def _count_calls(monkeypatch) -> list[int]:
    calls: list[int] = []
    original = mesh_descent.descent_basin

    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(mesh_descent, "descent_basin", counted)
    return calls


def test_a_build_computes_the_basin_once_and_its_consumers_read_it(tmp_path, monkeypatch) -> None:
    calls = _count_calls(monkeypatch)
    mesh = _grid()
    model = _model(tmp_path, _geographic())

    descent, basin, _ = build._build_descent_and_dam_feet(
        model, mesh, {}, np.zeros(mesh.n_cells, dtype=bool), None
    )
    routed = build._drainage_basin_mask(basin)
    observed = [catchment_cell_mask(model) for _ in range(3)]

    assert descent is not None and basin is not None
    assert model.descent_basin is basin
    assert len(calls) == 1
    assert routed is basin.mask
    for mask in observed:
        np.testing.assert_array_equal(mask, basin.mask)


def _stored_basin(n_cells: int) -> DescentBasin:
    mask = np.zeros(n_cells, dtype=bool)
    mask[:5] = True
    return DescentBasin(
        mask=mask, outlet=0, rule="near_point", area_m2=500.0, seeded_at_outlet=False
    )


@pytest.mark.parametrize(
    "consumer",
    [
        pytest.param(
            lambda basin: catchment_cell_mask(SimpleNamespace(model_name="m", descent_basin=basin)),
            id="discharge_observable",
        ),
        pytest.param(build._drainage_basin_mask, id="drainage_routing"),
    ],
)
def test_no_consumer_computes_the_basin_again(consumer, monkeypatch) -> None:
    def refuse(*_args, **_kwargs):
        raise AssertionError("a consumer computed the basin of D again")

    monkeypatch.setattr(core_descent, "descent_basin", refuse)
    monkeypatch.setattr(mesh_descent, "descent_basin", refuse)
    basin = _stored_basin(N * N)

    np.testing.assert_array_equal(consumer(basin), basin.mask)


def test_a_model_without_a_basin_falls_back_on_the_covered_centres(tmp_path, caplog) -> None:
    import geopandas as gpd
    from shapely.geometry import box

    mesh = _grid()
    shp = tmp_path / "watershed.gpkg"
    gpd.GeoDataFrame(geometry=[box(0.0, 0.0, 50.0, 100.0)], crs="EPSG:2154").to_file(shp)
    model = SimpleNamespace(
        model_name="flow",
        descent_basin=None,
        geographic=SimpleNamespace(watershed_shp=str(shp)),
        solver_mesh=mesh,
    )

    with caplog.at_level(logging.INFO):
        mask = catchment_cell_mask(model)

    np.testing.assert_array_equal(mask, mesh.cell_centroids()[:, 0] < 50.0)
    assert "model flow carries no basin of D" in caplog.text
    assert "'polygon_covers'" in caplog.text


def test_a_constant_head_sink_is_counted_with_the_area_it_keeps(caplog) -> None:
    top = _top()
    sink = 4 * N + 7
    top[sink] = 50.0
    mesh = solver_mesh_from_structured_arrays(
        nrow=N, ncol=N, top=top.reshape(N, N), botm=np.full((1, N, N), 0.0), dx=10.0, dy=10.0
    )
    constant_head = np.zeros(N * N, dtype=bool)
    constant_head[sink] = True
    descent = build_solver_mesh_descent(mesh, lake_cells_by_lake={}, base_level_mask=constant_head)

    with caplog.at_level(logging.INFO):
        basin = run_basin(_geographic(), mesh, descent)

    assert not basin.mask[sink]
    sinks = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any("1 constant-head cell(s) have no lower neighbour" in m for m in sinks)


def test_the_constant_head_cell_the_basin_ends_at_is_no_loss(caplog) -> None:
    top = _top()
    sink = 8 * N + 2
    top[sink] = 50.0
    mesh = solver_mesh_from_structured_arrays(
        nrow=N, ncol=N, top=top.reshape(N, N), botm=np.full((1, N, N), 0.0), dx=10.0, dy=10.0
    )
    constant_head = np.zeros(N * N, dtype=bool)
    constant_head[sink] = True
    descent = build_solver_mesh_descent(mesh, lake_cells_by_lake={}, base_level_mask=constant_head)

    with caplog.at_level(logging.INFO):
        basin = run_basin(_geographic(), mesh, descent)

    assert basin.mask[sink]
    assert not [r for r in caplog.records if r.levelno == logging.WARNING]
    assert caplog.text.count("Basin of D:") == 1


@pytest.mark.parametrize("make_mesh", [_grid, _triangles], ids=["grid", "triangles"])
def test_a_watershed_domain_floods_d_from_its_outlet(make_mesh, caplog) -> None:
    mesh = make_mesh()
    geographic = _geographic(domain_extent="watershed")
    rim = build_solver_mesh_descent(mesh, lake_cells_by_lake={}, base_level_mask=None)
    assert not run_basin(_geographic(), mesh, rim).mask.all()
    caplog.clear()

    with caplog.at_level(logging.INFO):
        descent = build_solver_mesh_descent(
            mesh, lake_cells_by_lake={}, base_level_mask=None, geographic=geographic
        )
        basin = run_basin(geographic, mesh, descent)

    assert basin.seeded_at_outlet
    assert basin.mask.all()
    assert np.flatnonzero(descent.base_level).tolist() == [basin.outlet]
    assert basin.area_m2 == pytest.approx(float(mesh.cell_areas().sum()))
    assert caplog.text.count("Basin of D:") == 1


def test_a_watershed_domain_without_outlet_or_polygon_keeps_the_rim(caplog) -> None:
    mesh = _grid()
    rim = build_solver_mesh_descent(mesh, lake_cells_by_lake={}, base_level_mask=None)

    with caplog.at_level(logging.INFO):
        descent = build_solver_mesh_descent(
            mesh,
            lake_cells_by_lake={},
            base_level_mask=None,
            geographic=SimpleNamespace(domain_extent="watershed"),
        )

    np.testing.assert_array_equal(descent.base_level, rim.base_level)
    assert any(
        "neither an outlet point nor a watershed polygon" in r.getMessage()
        for r in caplog.records
        if r.levelno == logging.WARNING
    )


@pytest.mark.parametrize("extent", ["box", "watershed_buff"])
@pytest.mark.parametrize("make_mesh", [_grid, _triangles], ids=["grid", "triangles"])
def test_a_boxed_domain_keeps_the_rim_flood_bit_for_bit(make_mesh, extent) -> None:
    mesh = make_mesh()
    plain = build_solver_mesh_descent(mesh, lake_cells_by_lake={}, base_level_mask=None)

    boxed = build_solver_mesh_descent(
        mesh,
        lake_cells_by_lake={},
        base_level_mask=None,
        geographic=_geographic(domain_extent=extent),
    )

    np.testing.assert_array_equal(boxed.receiver, plain.receiver)
    np.testing.assert_array_equal(boxed.surface, plain.surface)
    np.testing.assert_array_equal(boxed.base_level, plain.base_level)
    assert not run_basin(_geographic(domain_extent=extent), mesh, boxed).seeded_at_outlet
