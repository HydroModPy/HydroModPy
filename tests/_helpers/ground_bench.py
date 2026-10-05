"""A valley with a road across it: the bench of the crossing notch.

A 21 x 21 grid of 10 m cells. The channel runs south down column 10, the bed
drops one metre per row, and the sides rise half a metre per column away from
the axis. A road embankment is a band of rows raised across the whole width.
Everything is deterministic numpy, with no DEM file and no Whitebox: the
channel mask, the D8 pointer and the accumulation are written in closed form.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import LineString, Point
from shapely.geometry.base import BaseGeometry

from hydromodpy.spatial.geographic.core.ground_corrections import NotchReport, notch_dem

N = 21
RES = 10.0
AXIS = 10
CRS = "EPSG:2154"
TRANSFORM = from_origin(0.0, N * RES, RES, RES)
SOUTH = 8
WEST = 32


def x_of(col: int) -> float:
    """Easting of the centre of a column."""
    return (col + 0.5) * RES


def y_of(row: int) -> float:
    """Northing of the centre of a row."""
    return N * RES - (row + 0.5) * RES


def valley() -> np.ndarray:
    """The bare valley: the bed is ``100 - row`` on the axis."""
    rows = np.arange(N)[:, None]
    cols = np.arange(N)[None, :]
    return (100.0 - rows + 0.5 * np.abs(cols - AXIS)).astype("float32")


def bed(row: int) -> float:
    """The bed level of the bare valley at a row of the axis."""
    return 100.0 - row


@dataclass
class Bench:
    """The first-delineation rasters of the valley, and the channel vector."""

    dem: np.ndarray
    streams: np.ndarray
    d8: np.ndarray
    acc: np.ndarray
    network: gpd.GeoDataFrame


def build(*, embankment_rows: tuple[int, ...] = (), height: float = 0.0) -> Bench:
    """The valley with the rows of *embankment_rows* raised by *height* metres."""
    dem = valley()
    for row in embankment_rows:
        dem[row, :] += height
    streams = np.zeros((N, N), dtype=bool)
    streams[:, AXIS] = True
    d8 = np.full((N, N), SOUTH, dtype=int)
    d8[N - 1, :] = 0
    acc = np.ones((N, N))
    acc[:, AXIS] = np.arange(1, N + 1)
    line = LineString([(x_of(AXIS), N * RES - 1.0), (x_of(AXIS), 1.0)])
    return Bench(dem, streams, d8, acc, gpd.GeoDataFrame(geometry=[line], crs=CRS))


def structures(*rows: tuple[str, object]) -> gpd.GeoDataFrame:
    """A crossings frame from ``(kind, geometry)`` pairs, with the variable's columns."""
    return gpd.GeoDataFrame(
        {
            "kind": [kind for kind, _ in rows],
            "source": ["custom"] * len(rows),
            "name": [""] * len(rows),
            "drop_m": [float("nan")] * len(rows),
        },
        geometry=[geometry for _, geometry in rows],
        crs=CRS,
    )


def road_along(row: int) -> LineString:
    """A road across the whole width, on the centre line of *row*."""
    return LineString([(0.0, y_of(row)), (N * RES, y_of(row))])


def bridge_at(col: int, row: int) -> Point:
    """A point bridge at the centre of a pixel."""
    return Point(x_of(col), y_of(row))


def notch(
    bench: Bench,
    crossings: gpd.GeoDataFrame,
    *,
    kinds: tuple[str, ...] = ("road", "railway", "bridge"),
    notch_width_m: float = 10.0,
    bed_reach_m: float = 30.0,
    max_depth_m: float = 3.0,
    snap_radius_m: float = 30.0,
    dam_lines: Sequence[BaseGeometry] = (),
    lakes: Sequence[BaseGeometry] = (),
) -> tuple[np.ndarray, NotchReport]:
    """Run the raster notch on the bench and return the ground and the report."""
    report = NotchReport(parameters={})
    out = notch_dem(
        bench.dem,
        nodata=-9999.0,
        transform=TRANSFORM,
        streams=bench.streams,
        d8=bench.d8,
        acc=bench.acc,
        crossings=crossings,
        network=bench.network,
        kinds=list(kinds),
        notch_width_m=notch_width_m,
        bed_reach_m=bed_reach_m,
        max_depth_m=max_depth_m,
        snap_radius_m=snap_radius_m,
        report=report,
        dam_lines=dam_lines,
        lakes=lakes,
    )
    return out, report


def write_raster(path: Path, array: np.ndarray, *, dtype: str = "float32") -> Path:
    """Write *array* on the bench grid and return the path."""
    profile = {
        "driver": "GTiff",
        "height": array.shape[0],
        "width": array.shape[1],
        "count": 1,
        "dtype": dtype,
        "crs": CRS,
        "transform": TRANSFORM,
        "nodata": -9999.0,
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(array.astype(dtype), 1)
    return path
