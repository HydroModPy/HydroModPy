"""Which cells belong to the catchment, and how much of each cell lies inside its polygon.

The planner smooths the pixel staircase of the delineated catchment before it meshes, and the
faces of the mesh follow that smooth outline. The cell mask of a discharge objective and the
catchment fraction (share of a cell inside the polygon, no unit) read the outline the mesh followed
when it carries one, and the delineated polygon otherwise. The basin of the descent stays a
hydraulic, all-or-nothing set of cells and carries the fraction to the sidecar and to the store.
"""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pytest
import shapely
from rasterio.features import shapes
from rasterio.transform import Affine
from shapely.geometry import Polygon, box, shape

from hydromodpy.catchment.drainage.descent import DescentBasin
from hydromodpy.mesh.planar.geometry import cell_polygons
from hydromodpy.mesh.planning.catchment_outline import smooth_polygon
from hydromodpy.model.domain.geometry import CatchmentGeometry
from hydromodpy.model.model import Geometry
from hydromodpy.results.zarr_store.simulation_zarr import SimulationZarr
from hydromodpy.solver.modflow_common.catchment_basin import (
    catchment_cell_mask,
    polygon_cell_fraction,
    run_basin,
)
from hydromodpy.solver.modflow_common.descent_store import (
    read_descent_sidecar,
    write_descent_sidecar,
    write_descent_sidecar_to_store,
)
from hydromodpy.solver.modflow_common.flow_directions import build_solver_mesh_descent
from tests._helpers.mesh_cases import LAMBERT93_WKT
from tests._helpers.model_factory import make_model
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays
from tests._helpers.ugrid_meshes import quad_mesh

PIXEL = 10.0
NPIX = 20
CELL = 2.0


def staircase() -> Polygon:
    """An elliptic catchment as a delineation draws it: the polygon of a pixel mask."""
    rows, cols = np.mgrid[0:NPIX, 0:NPIX]
    x = (cols + 0.5) * PIXEL - 0.5 * NPIX * PIXEL
    y = (NPIX - rows - 0.5) * PIXEL - 0.5 * NPIX * PIXEL
    mask = np.hypot(x, 0.8 * y) < 0.35 * NPIX * PIXEL
    transform = Affine(PIXEL, 0.0, 0.0, 0.0, -PIXEL, NPIX * PIXEL)
    parts = [
        shape(geometry)
        for geometry, value in shapes(
            mask.astype("uint8"), mask=mask, transform=transform, connectivity=4
        )
        if value == 1
    ]
    return max(parts, key=lambda part: part.area)


STAIR = staircase()
SMOOTH = smooth_polygon(STAIR, PIXEL)


def smooth_mesh(*, followed: bool):
    """The cells of 2 m over the 200 m square, carrying the smooth outline or not.

    The grid is shifted off the meter so that no cell center lies on a diagonal of the smooth outline.
    """
    n = int(NPIX * PIXEL / CELL)
    mesh = solver_mesh_from_structured_arrays(
        nrow=n,
        ncol=n,
        top=np.full((n, n), 10.0),
        botm=np.zeros((1, n, n)),
        dx=CELL,
        dy=CELL,
        xoff=0.37,
        yoff=0.21,
    )
    cell_mesh = replace(mesh.cell_mesh, crs_wkt=LAMBERT93_WKT)
    if followed:
        cell_mesh = cell_mesh.with_smoothed_catchment(SMOOTH)
    return replace(mesh, cell_mesh=cell_mesh)


def geographic(tmp_path):
    shp = tmp_path / "watershed.gpkg"
    gpd.GeoDataFrame(geometry=[STAIR], crs=LAMBERT93_WKT).to_file(shp)
    return SimpleNamespace(watershed_shp=str(shp), crs_project=LAMBERT93_WKT)


def outline_catchment(tmp_path) -> CatchmentGeometry:
    """Where the catchment closes, as the ``Model`` of the run carries it."""
    return CatchmentGeometry.from_geographic(geographic(tmp_path), crs=LAMBERT93_WKT)


def solver_on(tmp_path, mesh) -> SimpleNamespace:
    """The members of a solver object that ``catchment_cell_mask`` reads."""
    inputs = make_model(
        geometry=Geometry(cells=None, domain=None, catchment=outline_catchment(tmp_path))
    )
    return SimpleNamespace(model_name="m", descent_basin=None, inputs=inputs, solver_mesh=mesh)


def inside(polygon, mesh) -> np.ndarray:
    return shapely.covers(polygon, shapely.points(mesh.cell_centers()))


def share(polygon, mesh) -> np.ndarray:
    cells = cell_polygons(
        np.asarray(mesh.planar_mesh.vertices, dtype=float),
        mesh.cell_mesh.geometry.padded_connectivity,
    )
    return shapely.area(shapely.intersection(cells, polygon)) / shapely.area(cells)


OUTLINES = [
    pytest.param(True, SMOOTH, id="the mesh followed the smooth outline"),
    pytest.param(False, STAIR, id="the mesh did not follow it"),
]


@pytest.mark.parametrize(("followed", "outline"), OUTLINES)
def test_fallback_support(tmp_path, followed, outline) -> None:
    mesh = smooth_mesh(followed=followed)

    mask = catchment_cell_mask(solver_on(tmp_path, mesh))

    np.testing.assert_array_equal(mask, inside(outline, mesh))


@pytest.mark.parametrize(("followed", "outline"), OUTLINES)
def test_catchment_fraction_of_a_mesh(tmp_path, followed, outline) -> None:
    mesh = smooth_mesh(followed=followed)

    fraction = polygon_cell_fraction(outline_catchment(tmp_path), mesh)

    np.testing.assert_allclose(fraction, share(outline, mesh), atol=1.0e-9)


def test_smooth_outline_moves_the_cells_of_the_band(tmp_path) -> None:
    mesh = smooth_mesh(followed=True)

    mask = catchment_cell_mask(solver_on(tmp_path, mesh))
    fraction = polygon_cell_fraction(outline_catchment(tmp_path), mesh)

    assert (mask != inside(STAIR, mesh)).any()
    assert np.abs(fraction - share(STAIR, mesh)).max() > 0.2


N = 10
CRS = "EPSG:2154"
# Cuts the cells of the first and last columns and rows the basin reaches.
POLYGON = box(3.0, 3.0, 47.0, 96.0)


def grid_mesh():
    rows, cols = np.divmod(np.arange(N * N), N)
    centre = np.where(cols < N // 2, 2, 7)
    noise = np.random.default_rng(3).uniform(0.0, 0.4, N * N)
    top = 100.0 + 0.5 * (N - 1 - rows) + np.abs(cols - centre) + noise
    return solver_mesh_from_structured_arrays(
        nrow=N, ncol=N, top=top.reshape(N, N), botm=np.full((1, N, N), -50.0), dx=10.0, dy=10.0
    )


def grid_catchment(tmp_path, *, polygon=POLYGON) -> CatchmentGeometry:
    outlet = (2 * 10.0 + 5.0, 5.0)
    extra = {}
    if polygon is not None:
        shp = tmp_path / "watershed.gpkg"
        gpd.GeoDataFrame(geometry=[polygon], crs=CRS).to_file(shp)
        extra["watershed_shp"] = str(shp)
    geographic = SimpleNamespace(x_outlet=outlet[0], y_outlet=outlet[1], **extra)
    return CatchmentGeometry.from_geographic(geographic, crs=CRS)


def basin_of(tmp_path, *, polygon=POLYGON) -> DescentBasin:
    mesh = grid_mesh()
    descent = build_solver_mesh_descent(mesh, lake_cells_by_lake={}, base_level_mask=None)
    return run_basin(grid_catchment(tmp_path, polygon=polygon), mesh, descent)


def overlay(polygon) -> np.ndarray:
    mesh = grid_mesh()
    cells = cell_polygons(
        np.asarray(mesh.planar_mesh.vertices, dtype=float),
        mesh.cell_mesh.geometry.padded_connectivity,
    )
    return shapely.area(shapely.intersection(cells, polygon)) / shapely.area(cells)


def test_basin_carries_the_polygon_share(tmp_path) -> None:
    basin = basin_of(tmp_path)

    assert basin.catchment_fraction is not None
    np.testing.assert_allclose(basin.catchment_fraction, overlay(POLYGON), atol=1e-12)
    cut = (basin.catchment_fraction > 0.0) & (basin.catchment_fraction < 1.0)
    assert (cut & basin.mask).any()


def test_fraction_reaches_the_store(tmp_path) -> None:
    basin = basin_of(tmp_path)
    mesh = grid_mesh()
    descent = build_solver_mesh_descent(mesh, lake_cells_by_lake={}, base_level_mask=None)
    write_descent_sidecar(descent, tmp_path, "m", basin=basin)

    record = read_descent_sidecar(tmp_path / "m.descent.npz")
    store = SimulationZarr.create(tmp_path / "run.zarr", n_cells=N * N, n_layers=1)
    try:
        vertices, connectivity = quad_mesh(N, N, cell_size=10.0)
        store.write_mesh(vertices, connectivity, np.array([0.0, -50.0]))
        written = write_descent_sidecar_to_store(store, tmp_path, sim_id="sim", n_cells=N * N)
        stored = store.root["mesh"]["catchment_fraction"]
        values, attrs, dtype = stored[:], dict(stored.attrs), stored.dtype
    finally:
        store.close()

    assert record is not None
    np.testing.assert_array_equal(record.catchment_fraction, basin.catchment_fraction)
    assert written
    assert dtype == np.float64
    np.testing.assert_array_equal(values, basin.catchment_fraction)
    assert attrs["units"] == "1"


def rewrite_sidecar(tmp_path, **changes) -> None:
    path = tmp_path / "m.descent.npz"
    with np.load(path, allow_pickle=False) as payload:
        arrays = {name: payload[name] for name in payload.files}
    for name, value in changes.items():
        if value is None:
            arrays.pop(name)
        else:
            arrays[name] = value
    np.savez(path, **arrays)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"catchment_fraction": np.full(N * N, 1.5)}, r"catchment fraction outside \[0, 1\]"),
        (
            {
                "basin": None,
                "basin_outlet": None,
                "basin_rule": None,
                "basin_area_m2": None,
                "basin_seeded_at_outlet": None,
            },
            "catchment fraction without a basin",
        ),
    ],
    ids=["out_of_range", "without_basin"],
)
def test_sidecar_refusals(tmp_path, changes, message) -> None:
    basin = basin_of(tmp_path)
    mesh = grid_mesh()
    descent = build_solver_mesh_descent(mesh, lake_cells_by_lake={}, base_level_mask=None)
    write_descent_sidecar(descent, tmp_path, "m", basin=basin)
    rewrite_sidecar(tmp_path, **changes)

    with pytest.raises(ValueError, match=message):
        read_descent_sidecar(tmp_path / "m.descent.npz")


@pytest.mark.parametrize(
    ("with_basin", "fraction", "message"),
    [
        (False, np.ones(N * N), "stored with the basin it weighs"),
        (True, np.ones(N * N + 1), "one value per cell"),
        (True, np.full(N * N, -0.1), r"in \[0, 1\]"),
    ],
    ids=["without_basin", "wrong_size", "negative"],
)
def test_store_refusals(tmp_path, with_basin, fraction, message) -> None:
    basin = basin_of(tmp_path)
    mesh = grid_mesh()
    descent = build_solver_mesh_descent(mesh, lake_cells_by_lake={}, base_level_mask=None)
    store = SimulationZarr.create(tmp_path / "run.zarr", n_cells=N * N, n_layers=1)
    try:
        with pytest.raises(ValueError, match=message):
            store.write_descent(
                receiver=descent.receiver,
                surface=descent.surface,
                base_level=descent.base_level,
                constant_head=descent.constant_head,
                raised=descent.raised,
                channel=descent.channel,
                pinned=descent.pinned,
                attrs={"adjacency": "shared_nodes"},
                basin=basin.mask if with_basin else None,
                basin_attrs={"descent_outlet": basin.outlet} if with_basin else None,
                catchment_fraction=fraction,
            )
    finally:
        store.close()
