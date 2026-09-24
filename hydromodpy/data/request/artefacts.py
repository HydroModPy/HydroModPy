"""One file per variable and source, cut to the extent and the period asked for.

A cache may hold more than a request asks: a SIM2 grid fetched for a region, a
DEM merged over two departments, a network clipped to a larger basin. What a
request returns is cut to its own extent and period, whatever the cache held.

Chronicles land in Parquet, one row per observation; grids in NetCDF; rasters
in GeoTIFF; vectors in GeoPackage; tables (a lake abacus) in Parquet. Each
writer returns ``None`` when nothing is left after the cut, which the report
records as an empty answer rather than a failure, and otherwise a
:class:`Written` naming the file, its CRS, the box it covers and the period it
really holds.

A period end given without a time (``2020-01-31``) keeps its whole day: a
request for January keeps the hourly values of the 31st.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from hydromodpy.core.exceptions import DataProductError
from hydromodpy.core.io.atomic_replace import staged_path
from hydromodpy.core.io.filesystem import native_io_path
from hydromodpy.core.io.parquet import PARQUET_WRITE_DEFAULTS

if TYPE_CHECKING:  # pragma: no cover - typing only
    import geopandas as gpd

    from hydromodpy.data.contracts.spatial_field import FieldRecord
    from hydromodpy.data.contracts.table import TableRecord
    from hydromodpy.data.contracts.timeseries import PointRecord
    from hydromodpy.data.source.port import Extent

FEATURES_LAYER = "features"
"""The layer name inside every GeoPackage written here."""

POINT_COLUMNS = (
    "station_id",
    "variable",
    "source",
    "unit",
    "frequency",
    "station_x",
    "station_y",
    "station_crs",
    "datetime",
    "value",
)
"""The column order of a chronicle file, fixed so a reader can rely on it."""

RASTER_SUFFIXES = frozenset({".tif", ".tiff", ".asc"})
VECTOR_SUFFIXES = frozenset({".gpkg", ".shp", ".geojson", ".json", ".parquet"})

Period = tuple[datetime, datetime]
Bbox = tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class Written:
    """A file written for a request: where, in which CRS, over which box and period."""

    path: Path
    crs: str | None
    bbox: Bbox | None
    period: tuple[str, str] | None = None


def last_instant(period: Period) -> datetime:
    """The last instant the period keeps: its end, or the end of that day at midnight."""
    end = period[1]
    if (end.hour, end.minute, end.second, end.microsecond) == (0, 0, 0, 0):
        return end + timedelta(days=1) - timedelta(microseconds=1)
    return end


def write_points(
    records: Sequence[PointRecord], target: Path, *, period: Period | None
) -> Written | None:
    """Write station chronicles as one long Parquet table, cut to ``period``."""
    import pandas as pd

    frames = []
    for record in records:
        observations = record.data.loc[:, ["datetime", "value"]].copy()
        if period is not None:
            observations = observations[_within(observations["datetime"], period)]
        if observations.empty:
            continue
        location = record.location
        observations["station_id"] = record.station_id
        observations["variable"] = record.variable
        observations["source"] = record.source
        observations["unit"] = record.unit
        observations["frequency"] = record.frequency
        observations["station_x"] = None if location is None else float(location.x)
        observations["station_y"] = None if location is None else float(location.y)
        observations["station_crs"] = None if location is None else str(location.crs)
        frames.append(observations)
    if not frames:
        return None
    _refuse_frames_that_disagree_about_the_clock(frames)
    table = pd.concat(frames, ignore_index=True).loc[:, list(POINT_COLUMNS)]
    table = table.sort_values(["station_id", "variable", "datetime"], kind="stable")
    _write_table(table.reset_index(drop=True), target)
    held = (table["datetime"].min().isoformat(), table["datetime"].max().isoformat())

    located = table.dropna(subset=["station_x", "station_y"])
    crs_values = set(located["station_crs"])
    if located.empty or len(crs_values) != 1:
        return Written(target, None, None, held)
    return Written(
        target,
        str(crs_values.pop()),
        (
            float(located["station_x"].min()),
            float(located["station_y"].min()),
            float(located["station_x"].max()),
            float(located["station_y"].max()),
        ),
        held,
    )


def _within(column, period: Period):
    import pandas as pd

    start, end = pd.Timestamp(period[0]), pd.Timestamp(last_instant(period))
    zone = getattr(column.dt, "tz", None)
    if zone is not None:
        start = start.tz_localize(zone) if start.tzinfo is None else start
        end = end.tz_localize(zone) if end.tzinfo is None else end
    return (column >= start) & (column <= end)


def _refuse_frames_that_disagree_about_the_clock(frames: list) -> None:
    """One table has one datetime column: naive and aware stations cannot share it."""
    aware = {
        str(frame["station_id"].iloc[0]): frame["datetime"].dt.tz is not None for frame in frames
    }
    if len(set(aware.values())) > 1:
        raise DataProductError(
            "the chronicles mix naive and timezone-aware timestamps "
            f"({aware}); reading a naive timestamp as UTC would invent an offset"
        )


def write_fields(
    records: Sequence[FieldRecord],
    target: Path,
    *,
    extent: Extent | None,
    period: Period | None,
) -> Written | None:
    """Cut gridded records to the extent and period, merge them, write one NetCDF."""
    import xarray as xr

    datasets = []
    for record in records:
        dataset = _cut_grid(record.dataset, record.crs, extent=extent, period=period)
        if dataset is None:
            continue
        if record.variable in dataset.data_vars:
            dataset[record.variable].attrs["units"] = record.unit
        datasets.append(dataset)
    if not datasets:
        return None
    try:
        merged = xr.merge(datasets, join="exact", combine_attrs="drop_conflicts")
    except ValueError as exc:
        raise DataProductError(
            f"the grids of {[record.variable for record in records]} do not align, "
            f"so they cannot be one dataset: {exc}"
        ) from exc
    crs = str(records[0].crs)
    merged.attrs["crs"] = crs
    merged.attrs["source"] = str(records[0].source)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f"{target.name}.tmp-{uuid.uuid4().hex[:8]}")
    try:
        merged.to_netcdf(native_io_path(tmp))
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    os.replace(native_io_path(tmp), native_io_path(target))
    bbox = None
    if "x" in merged.coords and "y" in merged.coords:
        bbox = (
            float(merged["x"].min()),
            float(merged["y"].min()),
            float(merged["x"].max()),
            float(merged["y"].max()),
        )
    held = None
    if "time" in merged.coords and merged["time"].size:
        times = merged["time"].to_index()
        held = (times.min().isoformat(), times.max().isoformat())
    return Written(target, crs, bbox, held)


def _cut_grid(dataset, crs: str, *, extent: Extent | None, period: Period | None):
    """Return the part of ``dataset`` inside the extent and period, or None."""
    if extent is not None and "x" in dataset.dims and "y" in dataset.dims:
        xmin, ymin, xmax, ymax = extent.to_crs(crs).bbox
        dataset = dataset.sel(x=_axis_slice(dataset["x"], xmin, xmax))
        dataset = dataset.sel(y=_axis_slice(dataset["y"], ymin, ymax))
    if period is not None and "time" in dataset.dims:
        dataset = dataset.sel(time=slice(period[0], last_instant(period)))
    if any(size == 0 for size in dataset.sizes.values()):
        return None
    return dataset


def _axis_slice(axis, low: float, high: float) -> slice:
    """A label slice from low to high, whichever way the axis runs."""
    values = axis.values
    if len(values) > 1 and values[0] > values[-1]:
        return slice(high, low)
    return slice(low, high)


def write_raster(source: Path, target: Path, *, extent: Extent | None) -> Written | None:
    """Cut a raster to the extent, in the raster's own CRS, and write a GeoTIFF."""
    import rasterio
    from rasterio.windows import Window, bounds, from_bounds

    with rasterio.open(native_io_path(source)) as src:
        full = Window(0, 0, src.width, src.height)
        window = full
        if extent is not None:
            wanted = from_bounds(*extent.to_crs(str(src.crs)).bbox, transform=src.transform)
            try:
                window = wanted.intersection(full)
            except Exception:  # noqa: BLE001 - rasterio raises when the two do not overlap
                return None
            window = window.round_offsets().round_lengths()
        if window.width < 1 or window.height < 1:
            return None
        data = src.read(window=window)
        transform = src.window_transform(window)
        profile = src.profile.copy()
        profile.update(
            driver="GTiff",
            height=int(window.height),
            width=int(window.width),
            transform=transform,
        )
        crs = str(src.crs) if src.crs else None
        box = tuple(float(v) for v in bounds(window, src.transform))
    target.parent.mkdir(parents=True, exist_ok=True)
    with (
        staged_path(target) as staged,
        rasterio.open(native_io_path(staged), "w", **profile) as dst,
    ):
        dst.write(data)
    return Written(target, crs, box)


def write_features(
    frame: gpd.GeoDataFrame, target: Path, *, extent: Extent | None
) -> Written | None:
    """Cut a feature table to the extent and write it as one named GeoPackage layer."""
    from shapely.geometry import box

    if frame.crs is None:
        raise DataProductError("a feature table without a CRS names no place")
    if extent is not None:
        frame = frame.clip(box(*extent.to_crs(str(frame.crs)).bbox))
    if len(frame) == 0:
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    with staged_path(target) as staged:
        frame.to_file(native_io_path(staged), driver="GPKG", layer=FEATURES_LAYER)
    return Written(target, str(frame.crs), tuple(float(v) for v in frame.total_bounds))


def read_features(path: Path) -> gpd.GeoDataFrame:
    """Read a vector file of any format the cache holds."""
    import geopandas as gpd

    if path.suffix.lower() == ".parquet":
        return gpd.read_parquet(native_io_path(path))
    return gpd.read_file(native_io_path(path))


def write_tables(records: Sequence[TableRecord], target: Path) -> Written | None:
    """Write tables (one lake abacus per record) as one long Parquet table."""
    import pandas as pd

    frames = []
    for record in records:
        frame = record.frame.copy()
        frame.insert(0, "table_id", record.table_id)
        frames.append(frame)
    if not frames:
        return None
    _write_table(pd.concat(frames, ignore_index=True), target)
    return Written(target, None, None)


def _write_table(table: object, target: Path) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    target.parent.mkdir(parents=True, exist_ok=True)
    arrow = pa.Table.from_pandas(table, preserve_index=False)
    with staged_path(target) as staged:
        pq.write_table(arrow, native_io_path(staged), **PARQUET_WRITE_DEFAULTS)


__all__ = [
    "FEATURES_LAYER",
    "POINT_COLUMNS",
    "RASTER_SUFFIXES",
    "VECTOR_SUFFIXES",
    "Written",
    "last_instant",
    "read_features",
    "write_features",
    "write_fields",
    "write_points",
    "write_raster",
    "write_tables",
]
