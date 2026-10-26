"""Area-weighted forcing conserves the volume of the grid it reads.

On pixels finer than the cells, each pixel weighs on a cell by the area they
share, so the rate of a cell times its area is the integral of the grid over
the cell. The hand references below never call shapely on the pixels: the
integral over the domain is a sum of pixel values times interval overlaps.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
import pytest
import shapely
import xarray as xr
from pydantic import ValidationError
from scipy.spatial import Delaunay

from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.physics.flow.sinks_sources import FlowEtpConfig, FlowRechargeConfig
from hydromodpy.spatial.mesh.cartesian_grid.spatial_interpolation import interpolate_to_grid
from hydromodpy.spatial.mesh.forcing import discretize_fields_on_cells, discretize_points_on_cells
from hydromodpy.spatial.mesh.forcing._area import area_weights
from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.model.derived_geometry import derive_geometry
from hydromodpy.spatial.mesh.model.hydro_mesh import CellBlock, HydroMesh

from ._test_sgrid_field_discretization_builders import (
    MM_DAY_TO_M_S,
    _make_simulation_window,
)

pytestmark = pytest.mark.fast

_CONSERVATION_REL = 1.0e-9
_ORIGIN = np.array([352_000.0, 6_789_000.0])
_SIDE = 1000.0


def _triangle_mesh(seed: int = 3) -> HydroMesh:
    """A Delaunay triangulation of a 1 km square, about 50 m triangles."""
    rng = np.random.default_rng(seed)
    edge = np.linspace(0.0, _SIDE, 21)
    border = np.concatenate(
        [
            np.column_stack([edge, np.zeros_like(edge)]),
            np.column_stack([edge, np.full_like(edge, _SIDE)]),
            np.column_stack([np.zeros_like(edge[1:-1]), edge[1:-1]]),
            np.column_stack([np.full_like(edge[1:-1], _SIDE), edge[1:-1]]),
        ]
    )
    inner = rng.uniform(20.0, _SIDE - 20.0, size=(300, 2))
    points = np.vstack([border, inner]) + _ORIGIN
    triangles = Delaunay(points).simplices
    return HydroMesh(vertices=points, cell_blocks=(CellBlock(CellType.TRIANGLE, triangles),))


def _voronoi_mesh(seed: int = 5) -> HydroMesh:
    """Voronoi polygons of random seeds, clipped to the 1 km square."""
    rng = np.random.default_rng(seed)
    seeds = shapely.multipoints(rng.uniform(0.0, _SIDE, size=(250, 2)) + _ORIGIN)
    square = shapely.box(*_ORIGIN, *(_ORIGIN + _SIDE))
    cells = shapely.intersection(
        shapely.get_parts(shapely.voronoi_polygons(seeds, extend_to=square)), square
    )
    vertices: list[np.ndarray] = []
    rows: list[np.ndarray] = []
    start = 0
    for cell in cells:
        ring = np.asarray(shapely.get_coordinates(cell.exterior))[:-1]
        vertices.append(ring)
        rows.append(np.arange(start, start + ring.shape[0]))
        start += ring.shape[0]
    return HydroMesh(
        vertices=np.vstack(vertices), cell_blocks=(CellBlock(CellType.POLYGON, tuple(rows)),)
    )


def _centres(mesh: HydroMesh) -> np.ndarray:
    return np.column_stack(mesh.cell_centroids())


def _areas(mesh: HydroMesh) -> np.ndarray:
    return derive_geometry(mesh).areas


def _grid(pixel: float, margin: float, *, offset: float = 0.0) -> tuple[np.ndarray, np.ndarray]:
    """Pixel centres covering the square with ``margin``, y descending as in a raster."""
    n = int(round((_SIDE + 2.0 * margin) / pixel))
    x = _ORIGIN[0] - margin + offset + (np.arange(n) + 0.5) * pixel
    y = (_ORIGIN[1] - margin + offset + (np.arange(n) + 0.5) * pixel)[::-1]
    return x, y


def _rough_values(x: np.ndarray, y: np.ndarray, seed: int = 11) -> np.ndarray:
    """A gradient, pixel noise and 10 m stripes every 100 m, ``(ny, nx)``, in mm/day.

    The stripes are what a centre sample misses: a cell takes them whole or not at all.
    """
    rng = np.random.default_rng(seed)
    u = (x[None, :] - _ORIGIN[0]) / _SIDE
    v = (y[:, None] - _ORIGIN[1]) / _SIDE
    stripes = 20.0 * ((x[None, :] - _ORIGIN[0]) % 100.0 < 10.0)
    noise = rng.lognormal(0.0, 0.6, size=(y.size, x.size))
    return 1.0 + 2.0 * u + 0.5 * v + stripes + noise


def _integral_over_square(values: np.ndarray, x: np.ndarray, y: np.ndarray) -> float:
    """Integral of a pixel grid over the square, from interval overlaps only."""

    def overlap(centres: np.ndarray, low: float) -> np.ndarray:
        half = 0.5 * abs(centres[1] - centres[0])
        left = np.maximum(centres - half, low)
        right = np.minimum(centres + half, low + _SIDE)
        return np.clip(right - left, 0.0, None)

    weight = overlap(y, _ORIGIN[1])[:, None] * overlap(x, _ORIGIN[0])[None, :]
    return float((values * weight).sum())


def _field(values: np.ndarray, x: np.ndarray, y: np.ndarray) -> LoadResult:
    ds = xr.Dataset({"recharge": (("y", "x"), values)}, coords={"x": x, "y": y})
    record = FieldRecord(
        variable="recharge",
        source="test",
        unit="mm/day",
        data=ds,
        bbox=(float(x.min()), float(y.min()), float(x.max()), float(y.max())),
        crs="EPSG:2154",
    )
    return LoadResult(fields=[record])


def _on_cells(mesh: HydroMesh, load_result: LoadResult, method: str) -> np.ndarray:
    return discretize_fields_on_cells(
        load_result=load_result,
        centers=_centres(mesh),
        nper=1,
        method=method,
        mesh=mesh,
    )[0]


@pytest.mark.parametrize(
    ("mesh_builder", "offset"),
    [(_triangle_mesh, 0.0), (_voronoi_mesh, 3.7)],
    ids=["triangles-aligned-pixels", "voronoi-unaligned-pixels"],
)
def test_the_area_volume_equals_the_integral_of_the_grid_and_nearest_misses_it(
    mesh_builder, offset: float
) -> None:
    mesh = mesh_builder()
    x, y = _grid(10.0, 40.0, offset=offset)
    values = _rough_values(x, y)
    expected = _integral_over_square(values, x, y) * MM_DAY_TO_M_S
    areas = _areas(mesh)

    area_volume = float((_on_cells(mesh, _field(values, x, y), "area") * areas).sum())
    nearest_volume = float((_on_cells(mesh, _field(values, x, y), "nearest") * areas).sum())

    assert abs(area_volume - expected) / expected < _CONSERVATION_REL
    assert abs(nearest_volume - expected) / expected > 1.0e-3


def test_the_shared_areas_of_concave_cells_match_the_exact_overlay() -> None:
    l_shape = np.array([[0, 0], [90, 0], [90, 30], [30, 30], [30, 80], [0, 80]], float)
    u_shape = np.array(
        [[100, 0], [190, 0], [190, 80], [160, 80], [160, 25], [130, 25], [130, 80], [100, 80]],
        float,
    )
    vertices = np.vstack([l_shape, u_shape]) + _ORIGIN
    rows = (np.arange(6), np.arange(6, 14))
    mesh = HydroMesh(vertices=vertices, cell_blocks=(CellBlock(CellType.POLYGON, rows),))
    x = _ORIGIN[0] - 7.3 + (np.arange(23) + 0.5) * 9.7
    y = (_ORIGIN[1] - 4.1 + (np.arange(11) + 0.5) * 9.7)[::-1]

    weights = area_weights(mesh, x, y).toarray()

    half = 0.5 * 9.7
    xx, yy = np.meshgrid(x, y, indexing="xy")
    boxes = shapely.box(xx - half, yy - half, xx + half, yy + half).reshape(-1)
    for cell, ring in enumerate((l_shape, u_shape)):
        exact = shapely.area(shapely.intersection(shapely.Polygon(ring + _ORIGIN), boxes))
        np.testing.assert_allclose(weights[cell], exact, rtol=0.0, atol=1e-8)
        assert weights[cell].sum() == pytest.approx(shapely.Polygon(ring).area, rel=1e-12)


def test_every_period_of_a_transient_grid_conserves_its_volume() -> None:
    mesh = _voronoi_mesh()
    x, y = _grid(10.0, 40.0, offset=1.3)
    days = pd.date_range("2020-01-01", periods=60, freq="D")
    cube = np.stack([_rough_values(x, y, seed=day) for day in range(days.size)])
    ds = xr.Dataset({"recharge": (("time", "y", "x"), cube)}, coords={"time": days, "x": x, "y": y})
    record = FieldRecord(
        variable="recharge",
        source="test",
        unit="mm/day",
        data=ds,
        bbox=(float(x.min()), float(y.min()), float(x.max()), float(y.max())),
        crs="EPSG:2154",
        date_start=datetime(2020, 1, 1),
        date_end=datetime(2020, 2, 29),
        frequency="D",
    )
    window = _make_simulation_window("2020-01-01", "2020-02-29", step_unit="month")
    result = discretize_fields_on_cells(
        load_result=LoadResult(fields=[record]),
        centers=_centres(mesh),
        nper=2,
        simulation_window=window,
        method="area",
        mesh=mesh,
    )
    areas = _areas(mesh)
    for kper, days_in_period in enumerate((slice(0, 31), slice(31, 60))):
        mean_grid = cube[days_in_period].mean(axis=0)
        expected = _integral_over_square(mean_grid, x, y) * MM_DAY_TO_M_S
        assert abs(float((result[kper] * areas).sum()) - expected) / expected < _CONSERVATION_REL


def test_a_multi_band_geotiff_conserves_its_volume_in_every_band(tmp_path) -> None:
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import from_origin

    mesh = _triangle_mesh()
    x, y = _grid(12.5, 50.0, offset=2.1)
    bands = np.stack([_rough_values(x, y, seed=seed) for seed in (1, 2)])
    path = tmp_path / "recharge.tif"
    transform = from_origin(x[0] - 6.25, y[0] + 6.25, 12.5, 12.5)
    with rasterio.open(
        path, "w", driver="GTiff", height=y.size, width=x.size, count=2, dtype="float64",
        crs="EPSG:2154", transform=transform,
    ) as dst:  # fmt: skip
        dst.write(bands)
    record = FieldRecord(
        variable="recharge",
        source="test",
        unit="mm/day",
        data=str(path),
        bbox=(float(x.min()), float(y.min()), float(x.max()), float(y.max())),
        crs="EPSG:2154",
    )
    result = discretize_fields_on_cells(
        load_result=LoadResult(fields=[record]),
        centers=_centres(mesh),
        nper=2,
        method="area",
        mesh=mesh,
    )
    areas = _areas(mesh)
    for kper in range(2):
        expected = _integral_over_square(bands[kper], x, y) * MM_DAY_TO_M_S
        assert abs(float((result[kper] * areas).sum()) - expected) / expected < _CONSERVATION_REL


def test_a_uniform_grid_gives_its_value_to_a_cell_it_only_partly_covers() -> None:
    mesh = _triangle_mesh()
    x = _ORIGIN[0] + 250.0 + (np.arange(40) + 0.5) * 10.0
    y = _ORIGIN[1] + 250.0 + (np.arange(40) + 0.5) * 10.0
    result = _on_cells(mesh, _field(np.full((40, 40), 4.0), x, y), "area")
    np.testing.assert_allclose(result, 4.0 * MM_DAY_TO_M_S, rtol=1e-12)


def test_a_cell_no_pixel_reaches_takes_the_nearest_pixel() -> None:
    mesh = _triangle_mesh()
    x = _ORIGIN[0] + (np.arange(50) + 0.5) * 10.0
    y = _ORIGIN[1] + (np.arange(100) + 0.5) * 10.0
    values = np.where(x[None, :] < _ORIGIN[0] + 250.0, 1.0, 3.0) * np.ones((y.size, 1))
    result = _on_cells(mesh, _field(values, x, y), "area")
    nearest = _on_cells(mesh, _field(values, x, y), "nearest")
    outside = _centres(mesh)[:, 0] > _ORIGIN[0] + 600.0
    assert outside.any()
    np.testing.assert_array_equal(result[outside], nearest[outside])
    assert np.all(np.isfinite(result))


def test_area_refuses_to_run_without_the_cell_polygons() -> None:
    mesh = _triangle_mesh()
    x, y = _grid(10.0, 40.0)
    with pytest.raises(ValueError, match="cell polygons"):
        discretize_fields_on_cells(
            load_result=_field(_rough_values(x, y), x, y),
            centers=_centres(mesh),
            nper=1,
            method="area",
        )


def test_area_refuses_a_station_source() -> None:
    with pytest.raises(ValueError, match="station source has no pixel"):
        discretize_points_on_cells(
            load_result=LoadResult(),
            centers=np.zeros((3, 2)),
            nper=1,
            method="area",
        )


def test_the_centre_grid_interpolation_refuses_area() -> None:
    grid = np.zeros((2, 2))
    with pytest.raises(ValueError, match="cell polygons"):
        interpolate_to_grid(grid, np.arange(2.0), np.arange(2.0), grid, grid, 2, 2, "area")


@pytest.mark.parametrize("config", [FlowRechargeConfig, FlowEtpConfig])
def test_the_forcing_configs_accept_area_and_keep_nearest_as_default(config) -> None:
    assert config().interpolation_method == "nearest"
    assert config(interpolation_method="area").interpolation_method == "area"
    with pytest.raises(ValidationError):
        config(interpolation_method="bilinear")
