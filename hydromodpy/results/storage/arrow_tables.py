"""Build the Arrow tables of the Parquet payloads of a run.

Every tabular payload of a run is a :class:`pyarrow.Table` that conforms to
one schema of :mod:`hydromodpy.results.storage.parquet_schemas`. The
builders here take records or columns, fill the missing columns with their
defaults, coerce the instants to UTC milliseconds and cast to the declared
types. :func:`merge_with_existing` is the last-write-wins merge a payload
goes through when a run writes it again.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa

from hydromodpy.results.storage.parquet_schemas import check_schema_version


def coerce_timestamp_utc(value: Any) -> pd.Timestamp | None:
    """Return a UTC-aware :class:`pandas.Timestamp`, or ``None`` for an unreadable value."""
    if value is None:
        return None
    if isinstance(value, pd.Timestamp):
        stamp = value
    else:
        try:
            stamp = pd.Timestamp(value)
        except (TypeError, ValueError):
            return None
    if stamp.tz is None:
        return stamp.tz_localize("UTC")
    return stamp.tz_convert("UTC")


def isoformat_instant(value: Any) -> str:
    """Return an ISO-8601 instant with the ``T`` separator a strict parser expects."""
    if hasattr(value, "isoformat"):
        return str(value.isoformat())
    text = str(value)
    return text.replace(" ", "T", 1) if " " in text[:19] else text


def table_from_records(
    records: Sequence[Mapping[str, Any]],
    schema: pa.Schema,
    *,
    defaults: Mapping[str, Any] | None = None,
) -> pa.Table:
    """Build a table from records, conforming to *schema*.

    A missing column falls back to ``None`` or to *defaults*. Instants are
    coerced to UTC milliseconds.
    """
    if not records:
        return pa.Table.from_pydict({field.name: [] for field in schema}, schema=schema)
    names = [field.name for field in schema]
    timestamp_fields = {field.name for field in schema if pa.types.is_timestamp(field.type)}
    columns: dict[str, list[Any]] = {name: [] for name in names}
    for record in records:
        for name in names:
            value = record.get(name)
            if value is None and defaults is not None and name in defaults:
                value = defaults[name]
            if name in timestamp_fields and value is not None:
                value = coerce_timestamp_utc(value)
            columns[name].append(value)
    arrays: list[pa.Array] = []
    for field in schema:
        values = columns[field.name]
        if pa.types.is_timestamp(field.type):
            ms_values = [None if v is None else int(v.value // 1_000_000) for v in values]
            arrays.append(pa.array(ms_values, type=field.type))
        else:
            arrays.append(pa.array(values, type=field.type, from_pandas=True))
    return pa.Table.from_arrays(arrays, names=names).replace_schema_metadata(schema.metadata)


def _is_column_array(value: Any) -> bool:
    """Return True for per-row array-likes; str, bytes and scalars broadcast."""
    return isinstance(value, np.ndarray | list | tuple | pd.Series | pd.Index)


def _timestamp_array_ms(value: Any, n_rows: int, dtype: pa.DataType) -> pa.Array:
    """Build a millisecond timestamp array; a naive input is UTC."""
    if value is None:
        return pa.nulls(n_rows, dtype)
    if not _is_column_array(value):
        stamp = coerce_timestamp_utc(value)
        ms = None if stamp is None else int(stamp.value // 1_000_000)
        return pa.array([ms] * n_rows, type=dtype)
    index = pd.DatetimeIndex(value)
    index = index.tz_localize("UTC") if index.tz is None else index.tz_convert("UTC")
    return pa.array(index.as_unit("ms").asi8, type=dtype, mask=index.isna())


def table_from_columns(
    columns: Mapping[str, Any],
    schema: pa.Schema,
    *,
    defaults: Mapping[str, Any] | None = None,
) -> pa.Table:
    """Build a table from equal-length columns, conforming to *schema*.

    Scalars broadcast and missing columns fall back to *defaults* or null.
    This skips the per-record Python loop, which matters for a series of
    millions of rows.
    """
    names = [field.name for field in schema]
    unknown = set(columns) - set(names)
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
    return pa.Table.from_arrays(arrays, names=names).replace_schema_metadata(schema.metadata)


def merge_with_existing(target: Path, new_table: pa.Table, pk_cols: Sequence[str]) -> pa.Table:
    """Merge *new_table* over the file at *target*, the new row winning on *pk_cols*."""
    import pyarrow.parquet as pq

    existing = pq.read_table(target)
    check_schema_version(existing.schema.metadata)
    combined = pa.concat_tables([existing, new_table], promote_options="default")
    frame = combined.to_pandas().drop_duplicates(subset=list(pk_cols), keep="last")
    return pa.Table.from_pandas(
        frame, schema=new_table.schema, preserve_index=False
    ).replace_schema_metadata(new_table.schema.metadata)


__all__ = [
    "coerce_timestamp_utc",
    "isoformat_instant",
    "merge_with_existing",
    "table_from_columns",
    "table_from_records",
]
