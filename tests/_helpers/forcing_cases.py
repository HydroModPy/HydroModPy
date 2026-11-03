"""The forcing sources of the forcing tests: cell centers, gridded records, stations, windows.

A grid record is laid out like the cells of ``regular_mesh``, one pixel per cell, row 0 at the
north. The area tests read meshes of a 1 km square at Lambert-93 magnitudes. Not public API.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import shapely
import xarray as xr
from scipy.spatial import Delaunay

from hydromodpy.core.time import ResolvedSimulationTimeWindow
from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.location import StationLocation
from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.spatial.forcing.cells import discretize_fields_on_cells, discretize_points_on_cells
from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.model.geometry import derive_geometry
from hydromodpy.spatial.mesh.model.hydro_mesh import CellBlock, HydroMesh
from tests._helpers import geotiffs
from tests._helpers.mesh_cases import L93_ORIGIN, regular_mesh, square_domain

MM_DAY_TO_M_S = 1.0e-3 / 86400.0  # one millimeter a day in meters a second
PIXEL = 10.0  # side of a cell and of a pixel of the small grids, in meters
ORIGIN = np.array(L93_ORIGIN)  # south-west corner of the square of the area tests
SIDE = 1000.0  # side of that square, in meters
L93_PROJ4_WITHOUT_DATUM = (  # Lambert-93 as an old GeoTIFF writes it, which pyproj identifies as EPSG:2154
    "+proj=lcc +lat_0=46.5 +lon_0=3 +lat_1=49 +lat_2=44 +x_0=700000 +y_0=6600000 +ellps=GRS80 +units=m +no_defs"
)  # fmt: skip


def centres(nrow: int, ncol: int, pixel: float = PIXEL) -> np.ndarray:
    """Return the ``(nrow * ncol, 2)`` cell centers of the regular mesh, row 0 at the north."""
    return regular_mesh(nrow, ncol, dx=pixel).centers


def fields_on_cells(records, nrow: int = 2, ncol: int = 2, nper: int = 1, mesh_crs=None, **kwargs) -> dict:  # fmt: skip
    """Return the per-period rates of the grid *records* on the cells of ``centers``."""
    return discretize_fields_on_cells(
        load_result=LoadResult(fields=list(records)), centers=centres(nrow, ncol), nper=nper, mesh_crs=mesh_crs, **kwargs
    )  # fmt: skip


def points_on_cells(records, nrow: int = 2, ncol: int = 2, nper: int = 1, mesh_crs=None, **kwargs) -> dict:  # fmt: skip
    """Return the per-period rates of the station *records* on the cells of ``centers``."""
    return discretize_points_on_cells(
        load_result=LoadResult(points=list(records)), centers=centres(nrow, ncol), nper=nper, mesh_crs=mesh_crs, **kwargs
    )  # fmt: skip


def pixel_axes(nrow: int, ncol: int, pixel: float = PIXEL) -> tuple[np.ndarray, np.ndarray]:
    """Return the pixel centers of a raster on the cells of ``centers``, y descending."""
    x = (np.arange(ncol) + 0.5) * pixel
    y = (nrow - np.arange(nrow) - 0.5) * pixel
    return x, y


def field_record(
    data: xr.Dataset | Path | str, *, unit: str = "mm/day",
    bbox: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0), days: int | None = None,
) -> FieldRecord:  # fmt: skip
    """Return the field record of *data*, static or of *days* daily slices from 2020-01-01."""
    start, dates = datetime(2020, 1, 1), {}
    if days is not None:
        dates = {"date_start": start, "date_end": start + timedelta(days - 1), "frequency": "D"}
    return FieldRecord(
        variable="recharge", source="test", unit=unit, data=data, bbox=bbox, crs="EPSG:2154", **dates
    )  # fmt: skip


def grid_dataset(
    values: np.ndarray, x: np.ndarray, y: np.ndarray, times: pd.DatetimeIndex | None = None
) -> xr.Dataset:
    """Return the dataset of one ``recharge`` grid, ``(y, x)`` or ``(time, y, x)``."""
    if times is None:
        return xr.Dataset({"recharge": (("y", "x"), values)}, coords={"x": x, "y": y})
    coords = {"time": times, "x": x, "y": y}
    return xr.Dataset({"recharge": (("time", "y", "x"), values)}, coords=coords)


def grid_source(values: np.ndarray, x: np.ndarray, y: np.ndarray) -> LoadResult:
    """Return the source of one static grid of *values*, laid out ``(y, x)``, in mm/day."""
    bbox = (float(x.min()), float(y.min()), float(x.max()), float(y.max()))
    return LoadResult(fields=[field_record(grid_dataset(values, x, y), bbox=bbox)])


def static_field(
    nrow: int, ncol: int, value: float, unit: str = "mm/day", pixel: float = PIXEL
) -> FieldRecord:
    """Return a static grid of one *value* on the cells of ``centers``."""
    x, y = pixel_axes(nrow, ncol, pixel)
    data = grid_dataset(np.full((nrow, ncol), value, dtype=float), x, y)
    return field_record(data, unit=unit, bbox=(0.0, 0.0, ncol * pixel, nrow * pixel))


def daily_field(
    nrow: int, ncol: int, values_per_day: Sequence[float], unit: str = "mm/day", pixel: float = PIXEL,
) -> FieldRecord:  # fmt: skip
    """Return a daily grid from 2020-01-01, one uniform value a day, on the cells of ``centers``."""
    days = len(values_per_day)
    x, y = pixel_axes(nrow, ncol, pixel)
    cube = np.asarray(values_per_day, dtype=float)[:, None, None] * np.ones((days, nrow, ncol))
    times = pd.date_range("2020-01-01", periods=days, freq="D")
    data = grid_dataset(cube, x, y, times)
    return field_record(data, unit=unit, bbox=(0.0, 0.0, ncol * pixel, nrow * pixel), days=days)


def station(
    station_id: str, x: float, y: float, values: float | Sequence[float], *, days: int = 31,
    unit: str = "mm/day",
) -> PointRecord:  # fmt: skip
    """Return a daily station series from 2020-01-01, constant or one value a day."""
    if not np.isscalar(values):
        days = len(values)
    dates = pd.date_range("2020-01-01", periods=days, freq="D")
    return PointRecord(
        station_id=station_id, variable="recharge", source="test", unit=unit, frequency="D",
        data=pd.DataFrame({"datetime": dates, "value": values}),
        date_start=dates[0].to_pydatetime(), date_end=dates[-1].to_pydatetime(),
        location=StationLocation(id=station_id, x=x, y=y, crs="EPSG:2154"),
    )  # fmt: skip


def window(
    start: str, end: str, step_value: int = 1, step_unit: str = "month",
    coverage_policy: str = "ignore",
    period_bounds: tuple[tuple[pd.Timestamp, pd.Timestamp], ...] | None = None,
) -> ResolvedSimulationTimeWindow:  # fmt: skip
    """Return the simulation window from *start* to *end*, both inclusive."""
    return ResolvedSimulationTimeWindow(
        start=pd.Timestamp(start), end=pd.Timestamp(end), step_value=step_value,
        step_unit=step_unit, coverage_policy=coverage_policy, period_bounds=period_bounds,
    )  # fmt: skip


def write_geotiff(
    path: Path, bands: np.ndarray, x: np.ndarray, y: np.ndarray, dtype: str = "float64"
) -> Path:
    """Write the ``(bands, y, x)`` stack on pixels centered on *x* and *y* (y descending)."""
    cell = (float(x[1] - x[0]), float(y[0] - y[1]))
    corner = (float(x[0]) - cell[0] / 2.0, float(y[0]) + cell[1] / 2.0)
    return geotiffs.write_geotiff(path, bands, origin=corner, cell=cell, dtype=dtype)


def triangle_mesh(seed: int = 3) -> HydroMesh:
    """Return a Delaunay triangulation of the square, about 50 m triangles."""
    rng = np.random.default_rng(seed)
    edge, inside = np.linspace(0.0, SIDE, 21), np.linspace(0.0, SIDE, 21)[1:-1]
    border = np.concatenate([
        np.column_stack([edge, np.zeros_like(edge)]), np.column_stack([edge, np.full_like(edge, SIDE)]),
        np.column_stack([np.zeros_like(inside), inside]), np.column_stack([np.full_like(inside, SIDE), inside]),
    ])  # fmt: skip
    inner = rng.uniform(20.0, SIDE - 20.0, size=(300, 2))
    points = np.vstack([border, inner]) + ORIGIN
    triangles = Delaunay(points).simplices
    return HydroMesh(vertices=points, cell_blocks=(CellBlock(CellType.TRIANGLE, triangles),))


def voronoi_mesh(seed: int = 5) -> HydroMesh:
    """Return the Voronoi polygons of random seeds, clipped to the square."""
    rng = np.random.default_rng(seed)
    seeds = shapely.multipoints(rng.uniform(0.0, SIDE, size=(250, 2)) + ORIGIN)
    square = square_domain(SIDE, x0=float(ORIGIN[0]), y0=float(ORIGIN[1]))
    cells = shapely.get_parts(shapely.voronoi_polygons(seeds, extend_to=square))
    cells = shapely.intersection(cells, square)
    return polygon_mesh([np.asarray(shapely.get_coordinates(c.exterior))[:-1] for c in cells])


def polygon_mesh(rings: Sequence[np.ndarray]) -> HydroMesh:
    """Return the mesh whose cells are the open *rings*, one polygon each."""
    starts = np.cumsum([0, *(len(ring) for ring in rings)])
    rows = tuple(np.arange(starts[i], starts[i + 1]) for i in range(len(rings)))
    block = CellBlock(CellType.POLYGON, rows)
    return HydroMesh(vertices=np.vstack(rings).astype(float), cell_blocks=(block,))


def mesh_centres(mesh: HydroMesh) -> np.ndarray:
    """Return the ``(n_cells, 2)`` centroids of *mesh*."""
    return np.column_stack(mesh.cell_centroids())


def mesh_areas(mesh: HydroMesh) -> np.ndarray:
    """Return the cell areas of *mesh*."""
    return derive_geometry(mesh).areas


def square_pixels(pixel: float, margin: float, *, offset: float = 0.0) -> tuple[np.ndarray, np.ndarray]:  # fmt: skip
    """Return the pixel centers covering the square with *margin*, y descending as in a raster."""
    n = int(round((SIDE + 2.0 * margin) / pixel))
    x = ORIGIN[0] - margin + offset + (np.arange(n) + 0.5) * pixel
    y = (ORIGIN[1] - margin + offset + (np.arange(n) + 0.5) * pixel)[::-1]
    return x, y


def rough_values(x: np.ndarray, y: np.ndarray, seed: int = 11) -> np.ndarray:
    """Return a gradient, pixel noise and 10 m stripes every 100 m, ``(ny, nx)``, in mm/day.

    The stripes are what a center sample misses: a cell takes them whole or not at all.
    """
    rng = np.random.default_rng(seed)
    u = (x[None, :] - ORIGIN[0]) / SIDE
    v = (y[:, None] - ORIGIN[1]) / SIDE
    stripes = 20.0 * ((x[None, :] - ORIGIN[0]) % 100.0 < 10.0)
    noise = rng.lognormal(0.0, 0.6, size=(y.size, x.size))
    return 1.0 + 2.0 * u + 0.5 * v + stripes + noise


def integral_over_square(values: np.ndarray, x: np.ndarray, y: np.ndarray) -> float:
    """Return the integral of a pixel grid over the square, from interval overlaps only."""

    def overlap(axis: np.ndarray, low: float) -> np.ndarray:
        half = 0.5 * abs(axis[1] - axis[0])
        left = np.maximum(axis - half, low)
        right = np.minimum(axis + half, low + SIDE)
        return np.clip(right - left, 0.0, None)

    weight = overlap(y, ORIGIN[1])[:, None] * overlap(x, ORIGIN[0])[None, :]
    return float((values * weight).sum())
