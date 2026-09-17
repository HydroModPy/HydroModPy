"""Canonical plain-Parquet write options shared across layers.

The ``results`` writer and the ``data`` adapters both emit tabular Parquet with
the same format contract (ZSTD-5, 50k row groups, dictionary, page index,
Parquet 2.6). ``data`` cannot import ``results`` under the layer matrix, so the
single source of truth lives here in ``core`` where both may import it.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Final

from hydromodpy.core.io.filesystem import native_io_path

PARQUET_WRITE_DEFAULTS: Final[dict[str, object]] = {
    "compression": "zstd",
    "compression_level": 5,
    "row_group_size": 50_000,
    "use_dictionary": True,
    "write_statistics": True,
    "write_page_index": True,
    "version": "2.6",
}
"""Write options applied to every tabular Parquet file HydroModPy produces."""

__all__ = ["PARQUET_WRITE_DEFAULTS", "merge_file_metadata"]


def merge_file_metadata(
    path: Path,
    metadata: Mapping[str, str],
    *,
    compression: str = "zstd",
    compression_level: int = 5,
) -> None:
    """Add ``metadata`` to the key-value footer of an existing Parquet file.

    Some writers own the encoding and expose no way to add a key while writing:
    geopandas for GeoParquet, DuckDB for ``COPY ... TO``. The file is rewritten
    once, atomically, with the merged footer, so no artefact of a run has to
    stay anonymous because of the tool that produced it.

    The whole file is read into memory to be rewritten, so this is for the small
    artefacts those two writers produce: a vector layer of a few thousand
    features, a one-row identity table. It is not a streaming rewrite and must
    not be pointed at a field array.
    """
    import pyarrow.parquet as pq

    io_path = native_io_path(path)
    table = pq.read_table(io_path)
    merged = dict(table.schema.metadata or {})
    merged.update(
        {key.encode("utf-8"): str(value).encode("utf-8") for key, value in metadata.items()}
    )
    rewritten = path.with_name(f"{path.name}.kv-{uuid.uuid4().hex[:8]}")
    rewritten_io = native_io_path(rewritten)
    try:
        pq.write_table(
            table.replace_schema_metadata(merged),
            rewritten_io,
            compression=compression,
            compression_level=compression_level,
        )
        os.replace(rewritten_io, io_path)
    except BaseException:
        # A half-written sibling is not a Parquet file and nobody would ever
        # collect it: the caller only knows the name it asked for.
        try:
            os.unlink(rewritten_io)
        except FileNotFoundError:
            pass
        raise
