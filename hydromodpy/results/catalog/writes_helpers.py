"""Shared helpers for the WritesMixin concern split.

These are pure module-level functions used by ``writes_duckdb``,
``writes_parquet`` and ``writes_zarr``. Keeping them in one place avoids
import cycles between the per-sink mixin modules.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa


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

    from hydromodpy.results.parquet_schemas import check_schema_version

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
]
