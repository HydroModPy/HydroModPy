"""Shared helpers for the WritesMixin concern split.

These are pure module-level functions used by ``writes_duckdb``,
``writes_parquet`` and ``writes_zarr``. Keeping them in one place avoids
import cycles between the per-sink mixin modules.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa

from hydromodpy.core.version import __version__ as _HMP_VERSION
from hydromodpy.results.storage.contract import UNDETERMINED_LICENSE
from hydromodpy.results.storage.parquet_schemas import PARQUET_SCHEMA_VERSION


def _sha256_streaming(path: Path, chunk_size: int = 65536) -> str:
    """Compute SHA-256 of a file by reading it in fixed-size chunks."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_directory(root: Path) -> str:
    """Compute a deterministic SHA-256 over a directory tree."""
    h = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        h.update(path.relative_to(root).as_posix().encode("utf-8"))
        h.update(b"\0")
        h.update(_sha256_streaming(path).encode("ascii"))
        h.update(b"\0")
    return h.hexdigest()


def _path_size_bytes(path: Path) -> int:
    """Return file size or cumulative directory file size."""
    if path.is_file():
        return path.stat().st_size
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _coerce_timestamp_utc(value: Any) -> pd.Timestamp | None:
    """Return a UTC-aware :class:`pandas.Timestamp` or ``None``."""
    if value is None:
        return None
    if isinstance(value, pd.Timestamp):
        ts = value
    else:
        try:
            ts = pd.Timestamp(value)
        except (TypeError, ValueError):
            return None
    if ts.tz is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts


def _coerce_timestamp(value: Any) -> Any:
    """Return a value suitable for a ``TIMESTAMPTZ`` DuckDB column."""
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value
    return str(value)


def _python_value_type(value: object) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "double"
    return "string"


def _normalize_geometry_kind(geom_type: str | None) -> str | None:
    if not geom_type:
        return None
    mapping = {
        "Point": "point",
        "MultiPoint": "point",
        "LineString": "linestring",
        "MultiLineString": "linestring",
        "Polygon": "polygon",
        "MultiPolygon": "multipolygon",
    }
    return mapping.get(geom_type, "polygon")


def geographic_feature_description(gdf: Any) -> tuple[str | None, str, dict[str, Any]]:
    """Return ``(geometry_kind, crs, properties)`` describing a feature layer.

    Shared by the writer and by the index rebuild, so one GeoParquet file
    always yields the same catalog row whether it was described when written
    or read back from disk afterwards. The CRS is rendered through
    ``to_string()``: a layer read back from GeoParquet carries its CRS as
    PROJJSON, and only the canonical form matches the authority code the
    writer saw in memory.
    """
    from shapely.ops import unary_union

    union_geom = unary_union([g for g in gdf.geometry if g is not None and not g.is_empty])
    geometry_kind = _normalize_geometry_kind(union_geom.geom_type)
    if gdf.crs is None:
        raise ValueError("Geographic feature CRS is required.")
    crs = gdf.crs.to_string()
    schema_payload = {
        "columns": [str(col) for col in gdf.columns if col != gdf.geometry.name],
        "geometry_kind": geometry_kind,
        "crs": crs,
    }
    properties = {
        "n_features": int(len(gdf)),
        "bbox": [float(value) for value in gdf.total_bounds],
        "geometry_encoding": "WKB",
        "schema_sha256": hashlib.sha256(
            json.dumps(schema_payload, sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "geoparquet_version": "1.1.0",
    }
    return geometry_kind, crs, properties


def _epsg_from_crs(crs: str | None) -> int | None:
    if not crs:
        return None
    upper = str(crs).upper().strip()
    if upper.startswith("EPSG:"):
        try:
            return int(upper.split(":", 1)[1])
        except ValueError:
            return None
    try:
        from pyproj import CRS

        return CRS.from_user_input(crs).to_epsg()
    except Exception:
        return None


def kv_metadata_for_sim(backend: Any, sim_id: str) -> dict[str, str]:
    """Return Parquet KV metadata keys for ``sim_id``.

    Reads the simulation row plus a few catalog joins to enrich the file
    footer with ACDD-style geospatial/temporal coverage attributes. The
    returned ``written_at`` is *deterministic*: it is the simulation's
    ``ended_at`` (or ``created_at`` fallback), never ``datetime.now``, so a
    reproducible re-run lands on a byte-identical file.
    """
    row = backend.fetch_one(
        """SELECT s.project, s.name, sv.code, s.config_hash,
                  s.scientific_objective, s.bbox_xmin, s.bbox_ymin,
                  s.bbox_xmax, s.bbox_ymax, s.period_start, s.period_end,
                  s.crs_epsg, s.created_at, s.ended_at, s.doi
             FROM simulations s
             JOIN solvers sv ON s.solver_id = sv.id
            WHERE s.sim_id = ?""",
        [sim_id],
    )
    if row is None:
        return {
            "sim_id": sim_id,
            "hydromodpy_version": _HMP_VERSION,
            "hmp.schema_version": PARQUET_SCHEMA_VERSION,
            "Conventions": "CF-1.11",
            "license": UNDETERMINED_LICENSE,
            "written_at": "",
        }
    (
        project,
        name,
        solver,
        config_hash,
        objective,
        bb_xmin,
        bb_ymin,
        bb_xmax,
        bb_ymax,
        period_start,
        period_end,
        crs_epsg,
        created_at,
        ended_at,
        doi,
    ) = row
    written_at_source = ended_at if ended_at is not None else created_at
    crs_token = f"EPSG:{int(crs_epsg)}" if crs_epsg is not None else None
    kv: dict[str, str] = {
        "sim_id": sim_id,
        "project": "" if project is None else str(project),
        "name": "" if name is None else str(name),
        "solver": "" if solver is None else str(solver),
        "config_hash": "" if config_hash is None else str(config_hash),
        "hydromodpy_version": _HMP_VERSION,
        "hmp.schema_version": PARQUET_SCHEMA_VERSION,
        "Conventions": "CF-1.11",
        "license": UNDETERMINED_LICENSE,
        "scientific_objective": "" if objective is None else str(objective),
        "doi": "" if doi is None else str(doi),
        "written_at": "" if written_at_source is None else _isoformat_instant(written_at_source),
    }
    # The native extent keeps its own keys, in its own projection. The ACDD
    # ones are WGS84 degrees by definition and used to hold Lambert-93
    # metres, which a reader could only read as a longitude of 319987.5.
    if None not in (bb_xmin, bb_ymin, bb_xmax, bb_ymax):
        kv["hmp.bbox_xmin"] = str(bb_xmin)
        kv["hmp.bbox_ymin"] = str(bb_ymin)
        kv["hmp.bbox_xmax"] = str(bb_xmax)
        kv["hmp.bbox_ymax"] = str(bb_ymax)
        if crs_token:
            kv["hmp.bbox_crs"] = crs_token
        degrees = wgs84_bounds((bb_xmin, bb_ymin, bb_xmax, bb_ymax), crs_token)
        if degrees is not None:
            kv["geospatial_lon_min"] = str(degrees["lon_min"])
            kv["geospatial_lon_max"] = str(degrees["lon_max"])
            kv["geospatial_lat_min"] = str(degrees["lat_min"])
            kv["geospatial_lat_max"] = str(degrees["lat_max"])
            kv["geospatial_bounds_crs"] = "EPSG:4326"
    if crs_token:
        kv["geospatial_crs"] = crs_token
    # ISO-8601, so a strict parser accepts it. ``str(pandas.Timestamp)``
    # separates date and time with a space, and the Zarr store beside this
    # file writes the same instant with a ``T``.
    for key, value in (
        ("time_coverage_start", period_start),
        ("time_coverage_end", period_end),
    ):
        if value is not None:
            kv[key] = _isoformat_instant(value)
    return kv


def _isoformat_instant(value: Any) -> str:
    """Return an ISO-8601 instant, with the ``T`` a strict parser expects.

    ``str(pandas.Timestamp)`` separates date and time with a space, which the
    Zarr store beside the same run does not, so one run stated one instant in
    two encodings.
    """
    if hasattr(value, "isoformat"):
        return str(value.isoformat())
    text = str(value)
    return text.replace(" ", "T", 1) if " " in text[:19] else text


def wgs84_bounds(
    bbox: tuple[float, float, float, float] | None,
    crs: str | None,
) -> dict[str, float] | None:
    """Return ``{lat_min, lat_max, lon_min, lon_max}`` in WGS84 degrees.

    ACDD defines ``geospatial_lat_*`` / ``geospatial_lon_*`` as degrees, and
    both writers of a run used to put the native projected extent there: a
    reader who trusted the key name took a Lambert-93 easting of 319987.5 for a
    longitude.

    Returns ``None`` rather than a doubtful extent in every case where the
    answer cannot be trusted, because an absent key means unknown and a present
    one means declared:

    * no extent, no projection, or a coordinate that is not a number;
    * a projection that declares no area of use, which is the only thing the
      coordinates can be checked against. A synthetic model numbers its cells
      from the origin in plain metres while the project still names a CRS
      somewhere, and reprojecting those lands a 400 m aquifer in the South
      Atlantic: well-formed, and meaningless;
    * an extent that falls nowhere near that area of use, same reason;
    * an extent that crosses the antimeridian, which two scalars per axis
      cannot express.
    """
    if bbox is None or not crs:
        return None
    try:
        values = [float(value) for value in bbox]
    except (TypeError, ValueError):
        return None
    if len(values) != 4 or any(value != value for value in values):  # NaN check
        return None
    xmin, xmax = min(values[0], values[2]), max(values[0], values[2])
    ymin, ymax = min(values[1], values[3]), max(values[1], values[3])
    try:
        from pyproj import CRS, Transformer

        source = CRS.from_user_input(str(crs))
        area = source.area_of_use
        if area is None:
            return None
        transformer = Transformer.from_crs(source, CRS.from_epsg(4326), always_xy=True)
        # transform_bounds densifies the edges, so a projected rectangle whose
        # sides bow in degrees keeps its true extent, and it reports an
        # antimeridian crossing by returning a west greater than its east.
        lon_min, lat_min, lon_max, lat_max = transformer.transform_bounds(
            xmin, ymin, xmax, ymax, densify_pts=21
        )
    except Exception:
        return None
    degrees = (lon_min, lat_min, lon_max, lat_max)
    if any(value != value for value in degrees):
        return None
    if lon_min > lon_max or lat_min > lat_max:
        return None
    if abs(lon_min) > 180.0 or abs(lon_max) > 180.0:
        return None
    if abs(lat_min) > 90.0 or abs(lat_max) > 90.0:
        return None
    west, south, east, north = area.bounds
    if lon_max < west or lon_min > east or lat_max < south or lat_min > north:
        return None
    return {
        "lat_min": lat_min,
        "lat_max": lat_max,
        "lon_min": lon_min,
        "lon_max": lon_max,
    }


def _datetime_to_ms(values: Iterable[Any]) -> list[pd.Timestamp | None]:
    """Coerce arbitrary datetime inputs to UTC milliseconds-resolution."""
    out: list[pd.Timestamp | None] = []
    for v in values:
        out.append(_coerce_timestamp_utc(v))
    return out


def _table_from_records(
    records: Sequence[Mapping[str, Any]],
    schema: pa.Schema,
    *,
    defaults: Mapping[str, Any] | None = None,
) -> pa.Table:
    """Build a pyarrow Table from a record list, conforming to ``schema``.

    Missing columns fall back to ``None`` or to the provided ``defaults``. The
    table is cast (``safe=False``) at the end so the produced Arrow types match
    the declared schema exactly.
    """
    if not records:
        return pa.Table.from_pydict({field.name: [] for field in schema}, schema=schema)
    field_names = [field.name for field in schema]
    timestamp_fields = {field.name for field in schema if pa.types.is_timestamp(field.type)}
    columns: dict[str, list[Any]] = {name: [] for name in field_names}
    for record in records:
        for name in field_names:
            value = record.get(name)
            if value is None and defaults is not None and name in defaults:
                value = defaults[name]
            if name in timestamp_fields and value is not None:
                value = _coerce_timestamp_utc(value)
            columns[name].append(value)
    arrays: dict[str, pa.Array] = {}
    for field in schema:
        col = columns[field.name]
        if pa.types.is_timestamp(field.type):
            # Convert tz-aware Timestamps to ms ints, leave None as null.
            ms_values = [None if v is None else int(v.value // 1_000_000) for v in col]
            arrays[field.name] = pa.array(ms_values, type=field.type)
        else:
            arrays[field.name] = pa.array(col, type=field.type, from_pandas=True)
    return pa.Table.from_arrays(
        list(arrays.values()), names=field_names, metadata=schema.metadata
    ).replace_schema_metadata(schema.metadata)


def _is_column_array(value: Any) -> bool:
    """Return True for per-row array-likes; str/bytes and scalars broadcast."""
    return isinstance(value, np.ndarray | list | tuple | pd.Series | pd.Index)


def _timestamp_array_ms(value: Any, n_rows: int, dtype: pa.DataType) -> pa.Array:
    """Build a millisecond-resolution timestamp array; naive input is UTC."""
    if value is None:
        return pa.nulls(n_rows, dtype)
    if not _is_column_array(value):
        ts = _coerce_timestamp_utc(value)
        ms = None if ts is None else int(ts.value // 1_000_000)
        return pa.array([ms] * n_rows, type=dtype)
    index = pd.DatetimeIndex(value)
    index = index.tz_localize("UTC") if index.tz is None else index.tz_convert("UTC")
    return pa.array(index.as_unit("ms").asi8, type=dtype, mask=index.isna())


def _table_from_columns(
    columns: Mapping[str, Any],
    schema: pa.Schema,
    *,
    defaults: Mapping[str, Any] | None = None,
) -> pa.Table:
    """Columnar sibling of :func:`_table_from_records`.

    ``columns`` maps schema column names to equal-length per-row arrays;
    scalar values broadcast and missing columns fall back to ``defaults`` or
    null. This skips the per-record Python loop entirely, which matters for
    multi-million-row solver series.
    """
    field_names = [field.name for field in schema]
    unknown = set(columns) - set(field_names)
    if unknown:
        raise ValueError(f"columns not in schema: {sorted(unknown)}")
    n_rows = None
    for value in columns.values():
        if _is_column_array(value):
            n_rows = len(value)
            break
    if n_rows is None:
        raise ValueError("at least one column must be a per-row array")
    arrays: list[pa.Array] = []
    for field in schema:
        value = columns.get(field.name)
        if value is None and defaults is not None and field.name in defaults:
            value = defaults[field.name]
        if pa.types.is_timestamp(field.type):
            arrays.append(_timestamp_array_ms(value, n_rows, field.type))
        elif value is None:
            arrays.append(pa.nulls(n_rows, field.type))
        elif _is_column_array(value):
            if len(value) != n_rows:
                raise ValueError(f"column '{field.name}' has {len(value)} rows, expected {n_rows}")
            arrays.append(pa.array(value, type=field.type, from_pandas=True))
        else:
            arrays.append(pa.array([value] * n_rows, type=field.type))
    return pa.Table.from_arrays(arrays, names=field_names).replace_schema_metadata(schema.metadata)


def _merge_with_existing(target: Path, new_table: pa.Table, pk_cols: Sequence[str]) -> pa.Table:
    """Last-write-wins merge of an existing Parquet file with ``new_table``.

    Reads the existing file with pyarrow, concatenates, drops the duplicate
    rows on ``pk_cols`` keeping the *new* row (``keep="last"``). The merge
    happens in memory, so the caller is responsible for keeping the per-sim
    files small (typically <100 MB).
    """
    import pyarrow.parquet as pq

    from hydromodpy.results.storage.parquet_schemas import check_schema_version

    existing = pq.read_table(target)
    # Reject a stale/version-less Parquet before appending to it: union_by_name
    # would otherwise silently NULL-fill or coerce a schema-drifted older file.
    check_schema_version(existing.schema.metadata)
    # Ensure columns line up: project new_table onto existing's column order
    # when both share the same names, otherwise rely on concat_tables' promote.
    combined = pa.concat_tables([existing, new_table], promote_options="default")
    # Use pandas to drop duplicates with deterministic last-wins semantics.
    df = combined.to_pandas()
    df = df.drop_duplicates(subset=list(pk_cols), keep="last")
    return pa.Table.from_pandas(
        df, schema=new_table.schema, preserve_index=False
    ).replace_schema_metadata(new_table.schema.metadata)


__all__ = [
    "kv_metadata_for_sim",
    "wgs84_bounds",
    "_isoformat_instant",
    "_coerce_timestamp",
    "_coerce_timestamp_utc",
    "_datetime_to_ms",
    "_epsg_from_crs",
    "_merge_with_existing",
    "_normalize_geometry_kind",
    "_path_size_bytes",
    "_python_value_type",
    "_sha256_directory",
    "_sha256_streaming",
    "_table_from_columns",
    "_table_from_records",
    "geographic_feature_description",
]
