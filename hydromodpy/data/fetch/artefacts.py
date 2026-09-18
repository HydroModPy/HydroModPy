"""How each of the four payload kinds lands as one sealable artefact.

This is the part of ``data-fetch`` the plan called conception rather than
execution, and the question it answers is narrow: a seal hashes **files**, so
every payload has to become one file with a name the declaration knew before the
run. The four answers are not symmetric, and each is chosen for a measured
reason rather than for tidiness.

``features`` -- one GeoPackage layer
    The payload is already a ``GeoDataFrame``. GeoPackage rather than
    GeoParquet: the three hydrography sources emit mixed linear geometries with
    provider columns of their own, and a GeoPackage is what every desktop GIS
    opens without a plugin. The layer is named, because a GeoPackage without a
    layer name is a file whose one table is called after the file.

``files`` -- one raster, moved and renamed
    A declared output path cannot depend on an input, and the one ``files``
    source of this tree returns a merged GeoTIFF whose name is built from the
    department codes it downloaded. It is **moved**, not copied: it is routinely
    the largest write of the job, and copying it would double that for nothing.
    A payload that is not exactly one raster is refused rather than sealed under
    a name that does not describe it -- the honest failure for a shape this
    declaration cannot publish.

``points`` -- one long Parquet table
    One row per observation, with the station identity, its coordinates and its
    unit repeated on every row. Wide-by-station would make the column set depend
    on which piezometers happened to answer, which is a schema that changes with
    the weather. The coordinates travel as three ordinary columns rather than as
    a geometry, so the table reads with pandas alone. One table carries one
    ``datetime`` column, so a batch whose stations disagree about
    timezone-awareness is refused rather than read as if they agreed.

``fields`` -- one NetCDF-4 file
    The payload is a list of ``xarray`` datasets that came out of one cube, one
    per requested variable, sharing their grid and their time axis. They are
    merged into one dataset and written once, with an **exact** join: records
    that do not share their grid are refused, because the outer join xarray
    defaults to pads the union with NaN and publishes a field nobody asked for.
    Zarr is what this repository uses for field arrays inside a run directory,
    and it is a **directory**: the seal inventories files and would have nothing
    to hash. One NetCDF file is the shape a job artefact can take.
"""

from __future__ import annotations

import os
import shutil
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hydromodpy.core.exceptions import DataProductError
from hydromodpy.core.io.filesystem import native_io_path
from hydromodpy.core.io.parquet import PARQUET_WRITE_DEFAULTS

if TYPE_CHECKING:  # pragma: no cover - typing only
    import geopandas as gpd

    from hydromodpy.data.contracts.spatial_field import FieldRecord
    from hydromodpy.data.contracts.timeseries import PointRecord
    from hydromodpy.data.source.port import FetchResult

FEATURES_LAYER = "features"
"""The layer name inside the GeoPackage. One without a name is unnamed."""

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
"""The column order of ``points.parquet``, fixed so a reader can rely on it."""

RASTER_SUFFIXES = frozenset({".tif", ".tiff"})
"""What the one declared ``files`` artefact may be. See the module docstring."""


def write_payload(result: FetchResult, target: Path) -> Path:
    """Write the payload of *result* to *target*, by the kind it declares.

    Dispatches on ``result.kind`` and never on ``isinstance``: the kind is the
    closed vocabulary the port publishes, and the whole reason it is declared
    rather than recovered is that a consumer should not branch on the third-party
    type a provider happened to return.
    """
    if result.kind == "features":
        return write_features(result.features, target)
    if result.kind == "files":
        return place_single_raster(result.files, target)
    if result.kind == "points":
        return write_points(result.points, target)
    if result.kind == "fields":
        return write_fields(result.fields, target)
    raise DataProductError(  # pragma: no cover - PayloadKind is closed and checked
        f"result of {result.source_id!r} declares the unknown payload kind {result.kind!r}"
    )


def write_features(frame: gpd.GeoDataFrame | None, target: Path) -> Path:
    """Write a feature table as one named GeoPackage layer."""
    if frame is None or len(frame) == 0:
        raise DataProductError("a features payload with no row is not written")
    if frame.crs is None:
        raise DataProductError(
            "the features payload carries no CRS, so the GeoPackage it would be "
            "written to could not declare one either"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    frame.to_file(str(target), driver="GPKG", layer=FEATURES_LAYER)
    return target


def place_single_raster(files: Sequence[Path], target: Path) -> Path:
    """Move the one raster a ``files`` payload holds under its declared name.

    Refuses anything else. A ``files`` source that returned three shapefile parts
    or two rasters would be a real payload this declaration has no name for, and
    inventing one -- ``raster.tif`` holding a ``.shp`` -- is the kind of false
    statement the campaign spent two phases removing.
    """
    if len(files) != 1:
        raise DataProductError(
            f"the files payload holds {len(files)} file(s); this capability declares one "
            "artefact for that kind, so it serves a source that returns exactly one"
        )
    produced = Path(files[0])
    if not produced.is_file():
        raise DataProductError(f"the files payload names {produced}, which is not a file")
    if produced.suffix.lower() not in RASTER_SUFFIXES:
        raise DataProductError(
            f"the files payload is {produced.name}, and the declared artefact is a GeoTIFF; "
            f"this capability serves {sorted(RASTER_SUFFIXES)} for that kind"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    # shutil and not Path.replace: the scratch lives under TMPDIR, which is
    # routinely a different filesystem from the job directory, and a rename
    # across two of them fails with EXDEV.
    shutil.move(native_io_path(produced), native_io_path(target))
    return target


def write_points(records: Sequence[PointRecord], target: Path) -> Path:
    """Write station time series as one long Parquet table."""
    import pandas as pd

    if not records:
        raise DataProductError("a points payload with no record is not written")
    _refuse_records_that_disagree_about_the_clock(records)
    frames = []
    for record in records:
        observations = record.data.loc[:, ["datetime", "value"]].copy()
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
    table = pd.concat(frames, ignore_index=True)
    table = table.loc[:, list(POINT_COLUMNS)]
    table = table.sort_values(["station_id", "variable", "datetime"], kind="stable")
    return _write_table_atomic(table.reset_index(drop=True), target)


def _refuse_records_that_disagree_about_the_clock(records: Sequence[PointRecord]) -> None:
    """Refuse a batch whose stations do not agree on timezone-awareness.

    One long table has **one** ``datetime`` column, so the whole batch is either
    naive or aware. A provider that answers naive for one station and aware for
    another leaves no honest column type: reading the naive one as UTC invents
    an offset, and pandas refuses to sort the two against each other anyway --
    ``sort_values`` below raised a bare ``TypeError`` out of its lexsort path,
    which the process mapped to the generic exit 1, the code whose whole meaning
    is "this is a bug in HydroModPy".

    Aware records of **different** offsets are fine and are not refused: they
    name the same instants, ``pandas`` concatenates them into one UTC column,
    and no information is invented.
    """
    aware = {
        record.station_id: record.data["datetime"].dt.tz is not None
        for record in records
        if len(record.data)
    }
    if len(set(aware.values())) > 1:
        naive = sorted(name for name, is_aware in aware.items() if not is_aware)
        with_zone = sorted(name for name, is_aware in aware.items() if is_aware)
        raise DataProductError(
            "the points payload mixes naive and timezone-aware timestamps -- "
            f"naive for {naive}, aware for {with_zone}. One table carries one "
            "datetime column, and reading a naive timestamp as UTC would invent "
            "an offset the provider never gave."
        )


def write_fields(records: Sequence[FieldRecord], target: Path) -> Path:
    """Merge the gridded records into one dataset and write it once."""
    import xarray as xr

    if not records:
        raise DataProductError("a fields payload with no record is not written")
    datasets = []
    for record in records:
        dataset = record.dataset
        if not isinstance(dataset, xr.Dataset):  # pragma: no cover - contract says otherwise
            raise DataProductError(
                f"field record {record.variable!r} carries a {type(dataset).__name__}, "
                "and only an xarray Dataset can be written"
            )
        datasets.append(dataset)
    # ``join="exact"`` and not the default ``"outer"``. The records of one fetch
    # come out of one cube and share their grid, and when they do the two joins
    # produce the same dataset. When they do not, the outer join silently pads
    # the union with NaN -- measured: two 2x2 grids a megametre apart merged into
    # one 4x4 grid, three quarters of it empty, with no error anywhere and a file
    # far larger than the extent implies. A refusal is the only answer that does
    # not publish a field nobody asked for. xarray is itself moving this default
    # to "exact", and warns about it.
    try:
        merged = xr.merge(datasets, join="exact", combine_attrs="drop_conflicts")
    except ValueError as exc:
        raise DataProductError(
            f"the fields payload holds {[record.variable for record in records]} on grids "
            f"that do not align, so they cannot be one dataset: {exc}"
        ) from exc
    merged.attrs["crs"] = str(records[0].crs)
    merged.attrs["source"] = str(records[0].source)
    for record in records:
        if record.variable in merged.data_vars:
            merged[record.variable].attrs["units"] = record.unit
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f"{target.name}.tmp-{uuid.uuid4().hex[:8]}")
    try:
        merged.to_netcdf(native_io_path(tmp))
    except Exception:
        _unlink_quietly(tmp)
        raise
    os.replace(native_io_path(tmp), native_io_path(target))
    return target


def payload_summary(result: FetchResult) -> dict[str, Any]:
    """Return how much of each payload came back, for the report.

    One key per kind and not a bare count, because "how big" means a different
    thing for each: a number of observations, a number of grid variables, a
    number of features, a number of files.
    """
    if result.kind == "points":
        return {
            "stations": len({record.station_id for record in result.points}),
            "observations": int(sum(len(record.data) for record in result.points)),
        }
    if result.kind == "fields":
        return {"fields": len(result.fields)}
    if result.kind == "features":
        return {"features": 0 if result.features is None else int(len(result.features))}
    return {"files": len(result.files)}


def _write_table_atomic(table: object, target: Path) -> Path:
    """Write a pandas frame as Parquet with the canonical options, atomically.

    The options come from ``core.io.parquet`` so the file this capability seals
    is written the way every other tabular Parquet of this repository is. The
    ``results`` writer next door adds key-value metadata, primary-key bloom
    filters and a replace retry; none of the three applies to a job artefact,
    which is written once into a directory nobody else holds open.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    os.makedirs(native_io_path(target.parent), exist_ok=True)
    tmp = target.with_name(f"{target.name}.tmp-{uuid.uuid4().hex[:8]}")
    arrow = pa.Table.from_pandas(table, preserve_index=False)
    try:
        pq.write_table(arrow, native_io_path(tmp), **PARQUET_WRITE_DEFAULTS)
    except Exception:
        _unlink_quietly(tmp)
        raise
    os.replace(native_io_path(tmp), native_io_path(target))
    return target


def _unlink_quietly(path: Path) -> None:
    try:
        os.unlink(native_io_path(path))
    except FileNotFoundError:
        pass


__all__ = [
    "FEATURES_LAYER",
    "POINT_COLUMNS",
    "RASTER_SUFFIXES",
    "payload_summary",
    "place_single_raster",
    "write_features",
    "write_fields",
    "write_payload",
    "write_points",
]
