"""Atomic pyarrow Parquet writer with canonical V1 options forced.

Every Parquet file written by HydroModPy V1 goes through
:func:`write_table_atomic`. It centralises:

- ZSTD compression at level 5 (uniform across catalog and blob payloads),
- ``row_group_size=50_000`` so predicate pushdown on row-group stats kicks in,
- ``write_page_index=True`` and ``use_dictionary=True`` for selective reads,
- Parquet format ``version="2.6"`` (page index, column statistics v2),
- a KV-metadata mixin layered on top of the schema metadata,
- bloom filter columns (forwarded when the linked pyarrow build supports it).

The write goes to a sibling ``<target>.tmp-<uuid>`` then is promoted via
``os.replace``, so the on-disk view is always either the prior file or the
fully-written new one.
"""

from __future__ import annotations

import inspect
import os
import time
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

import pyarrow as pa
import pyarrow.parquet as pq

from hydromodpy.core.io.filesystem import native_io_path as _native_io_path
from hydromodpy.core.io.parquet import PARQUET_WRITE_DEFAULTS


def _supports_bloom_filter_columns() -> bool:
    """Return True if pyarrow.parquet.write_table accepts bloom_filter_columns."""
    try:
        sig = inspect.signature(pq.write_table)
    except (TypeError, ValueError):
        return False
    return "bloom_filter_columns" in sig.parameters


_BLOOM_FILTER_SUPPORTED: Final[bool] = _supports_bloom_filter_columns()


def _encode_metadata(
    base: Mapping[bytes, bytes] | Mapping[str, str] | None,
    extra: Mapping[str, str] | None,
) -> dict[bytes, bytes]:
    """Merge an existing schema metadata dict with an extra ``str`` mapping."""
    merged: dict[bytes, bytes] = {}
    if base:
        for key, value in base.items():
            k = key if isinstance(key, (bytes, bytearray)) else str(key).encode("utf-8")
            v = value if isinstance(value, (bytes, bytearray)) else str(value).encode("utf-8")
            merged[bytes(k)] = bytes(v)
    if extra:
        for key, value in extra.items():
            merged[str(key).encode("utf-8")] = str(value).encode("utf-8")
    return merged


def write_table_atomic(
    table: pa.Table,
    target: Path | str,
    *,
    kv_metadata: Mapping[str, str] | None = None,
    pk_cols: Sequence[str] | None = None,
    overrides: Mapping[str, object] | None = None,
) -> Path:
    """Write ``table`` to ``target`` atomically with the V1 Parquet options.

    Parameters
    ----------
    table
        PyArrow Table to persist. Its schema is reused as-is, the merged KV
        metadata is attached before the write.
    target
        Destination Parquet path. Parent directory is created if missing.
    kv_metadata
        Extra string key/value pairs to embed in the Parquet schema metadata.
        Merged on top of any metadata already present on the table schema.
    pk_cols
        Optional primary-key columns. Forwarded to pyarrow as the
        ``bloom_filter_columns`` argument when the linked pyarrow build exposes
        it (Arrow >= 23 in practice; ignored otherwise).
    overrides
        Extra write keyword arguments that take precedence over
        :data:`PARQUET_WRITE_DEFAULTS`. Used for callers that need to flip a
        single knob without rewriting the full option set.

    Returns
    -------
    Path
        The resolved ``target`` path after the atomic rename.
    """
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f"{target.name}.tmp-{uuid.uuid4().hex[:8]}")
    tmp_io = _native_io_path(tmp)
    target_io = _native_io_path(target)
    if os.path.exists(tmp_io):
        os.unlink(tmp_io)

    merged_metadata = _encode_metadata(table.schema.metadata, kv_metadata)
    out_table = table.replace_schema_metadata(merged_metadata)

    options: dict[str, object] = dict(PARQUET_WRITE_DEFAULTS)
    if overrides:
        options.update(overrides)
    if pk_cols and _BLOOM_FILTER_SUPPORTED:
        bloom_cols = [c for c in pk_cols if c in out_table.column_names]
        if bloom_cols:
            options.setdefault("bloom_filter_columns", bloom_cols)

    try:
        pq.write_table(out_table, tmp_io, **options)
    except Exception:
        try:
            os.unlink(tmp_io)
        except FileNotFoundError:
            pass
        raise
    _replace_with_retry(tmp_io, target_io)
    return target


def _replace_with_retry(tmp_io: str, target_io: str) -> None:
    """Promote ``tmp_io`` over ``target_io``, tolerating short Windows locks."""

    attempts = 6 if os.name == "nt" else 1
    delay_s = 0.05
    for attempt in range(attempts):
        try:
            os.replace(tmp_io, target_io)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay_s)
            delay_s *= 2


def read_kv_metadata(path: Path | str) -> dict[str, str]:
    """Return the Parquet file metadata decoded as a plain ``str`` mapping.

    Reads only the footer, never the row data. Missing metadata maps to an
    empty dict. Bytes keys/values are decoded as UTF-8 with replacement so a
    corrupt non-UTF-8 byte does not raise.
    """
    pf = pq.ParquetFile(Path(path))
    raw = pf.schema_arrow.metadata or {}
    decoded: dict[str, str] = {}
    for key, value in raw.items():
        k = (
            key.decode("utf-8", errors="replace")
            if isinstance(key, (bytes, bytearray))
            else str(key)
        )
        v = (
            value.decode("utf-8", errors="replace")
            if isinstance(value, (bytes, bytearray))
            else str(value)
        )
        decoded[k] = v
    return decoded


__all__ = [
    "read_kv_metadata",
    "write_table_atomic",
]
