"""Canonical plain-Parquet write options shared across layers.

The ``results`` writer and the ``data`` adapters both emit tabular Parquet with
the same format contract (ZSTD-5, 50k row groups, dictionary, page index,
Parquet 2.6). ``data`` cannot import ``results`` under the layer matrix, so the
single source of truth lives here in ``core`` where both may import it.
"""

from __future__ import annotations

from typing import Final

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

__all__ = ["PARQUET_WRITE_DEFAULTS"]
