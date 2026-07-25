"""Lazy loaders for the per-run Parquet and Zarr stores.

Returns
-------
:class:`polars.LazyFrame` for tabular Parquet views, :class:`pa.dataset.Dataset`
for per-field Zarr stores. Both are constructed without pulling row data, so a
cohort scan can be planned (filters, projections) before any byte is read.

These accessors fill the ML-friendly gap pointed out in
``reports_db/04_parquet_tabular.md §R08``. The previous catalog API only
exposed eager :class:`pandas.DataFrame` results, which is OOM-prone on large
workspaces.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from hydromodpy.core.state.paths import runs_dir_for
from hydromodpy.results.catalog.constants import PARQUET_VIEW_NAMES
from hydromodpy.results.storage.contract import (
    FIELDS_STORE_NAME,
    PARQUET_FILE_SUFFIX,
    TABLES_DIRNAME,
)

if TYPE_CHECKING:
    import polars as pl
    import pyarrow.dataset as pa_dataset


class _CatalogLike(Protocol):
    """Minimal contract for a catalog passed to the loaders."""

    @property
    def runs_dir(self) -> Path: ...

    @property
    def workspace_path(self) -> Path: ...


def list_parquet_paths(catalog: _CatalogLike, view: str) -> list[Path]:
    """Return existing ``<view>.parquet`` paths across every run.

    ``view`` must be one of :data:`PARQUET_VIEW_NAMES`. Missing files are
    silently skipped so the result is always a usable input for a scanner.
    """
    if view not in PARQUET_VIEW_NAMES:
        raise ValueError(f"Unknown Parquet view {view!r}. Allowed: {sorted(PARQUET_VIEW_NAMES)}")
    base = Path(catalog.runs_dir)
    if not base.is_dir():
        return []
    pattern = f"*/{TABLES_DIRNAME}/{view}{PARQUET_FILE_SUFFIX}"
    return sorted(p for p in base.glob(pattern) if p.is_file())


def list_field_paths(catalog: _CatalogLike) -> list[Path]:
    """Return the Zarr store path of every run."""
    base = Path(catalog.runs_dir)
    if not base.is_dir():
        return []
    return sorted(p for p in base.glob(f"*/{FIELDS_STORE_NAME}") if p.is_dir())


def scan_timeseries(
    catalog: _CatalogLike,
    *,
    filters: dict[str, object] | None = None,
    columns: Sequence[str] | None = None,
) -> pl.LazyFrame:
    """Return a polars :class:`LazyFrame` over every ``timeseries.parquet``.

    ``filters`` accepts a flat mapping; equality predicates are pushed through
    :meth:`polars.LazyFrame.filter`. ``columns`` is forwarded to the polars
    scanner so unread columns are never decoded.
    """
    import polars as pl

    paths = list_parquet_paths(catalog, "timeseries")
    if not paths:
        return pl.LazyFrame()
    lf = pl.scan_parquet([str(p) for p in paths])
    if columns is not None:
        lf = lf.select(list(columns))
    if filters:
        for key, value in filters.items():
            lf = lf.filter(pl.col(key) == value)
    return lf


def scan_view(
    catalog: _CatalogLike,
    view: str,
    *,
    filters: dict[str, object] | None = None,
    columns: Sequence[str] | None = None,
) -> pl.LazyFrame:
    """Return a polars :class:`LazyFrame` over any per-sim view."""
    import polars as pl

    paths = list_parquet_paths(catalog, view)
    if not paths:
        return pl.LazyFrame()
    lf = pl.scan_parquet([str(p) for p in paths])
    if columns is not None:
        lf = lf.select(list(columns))
    if filters:
        for key, value in filters.items():
            lf = lf.filter(pl.col(key) == value)
    return lf


def scan_field(catalog: _CatalogLike) -> pa_dataset.Dataset:
    """Return a :class:`pyarrow.dataset.Dataset` over every Zarr store.

    The dataset is built around the on-disk paths; ``format='parquet'`` is not
    used because the field stores are Zarr, not Parquet. The function exists so
    ML callers have a single uniform entry point for both timeseries (Parquet)
    and fields (Zarr) without polluting the catalog facade with another import.

    The returned dataset only carries the paths of the on-disk stores via an
    in-memory Arrow table; the actual numerical decoding stays the
    responsibility of :class:`xarray.open_zarr` callers.
    """
    import pyarrow as pa
    import pyarrow.dataset as pa_dataset_mod

    paths = list_field_paths(catalog)
    table = pa.table(
        {
            "path": pa.array([str(p) for p in paths], type=pa.string()),
            "name": pa.array([p.name for p in paths], type=pa.string()),
        }
    )
    return pa_dataset_mod.dataset(table)


def iter_parquet_paths(project_root: Path | str) -> Iterable[Path]:
    """Yield every Parquet payload under ``<project>/runs/``."""
    base = runs_dir_for(Path(project_root))
    if not base.is_dir():
        return
    for path in base.glob(f"*/{TABLES_DIRNAME}/*{PARQUET_FILE_SUFFIX}"):
        if path.is_file():
            yield path


__all__ = [
    "iter_parquet_paths",
    "list_field_paths",
    "list_parquet_paths",
    "scan_field",
    "scan_timeseries",
    "scan_view",
]
