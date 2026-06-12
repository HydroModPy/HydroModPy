"""Per-simulation write operations.

:class:`WritesMixin` is a thin facade that composes three concern mixins:

- :class:`hydromodpy.results.catalog.writes_duckdb.WritesMixinDuckDB`:
  parameters, metrics, stations, scientific objectives, run environment,
  geographic metadata, provenance, and tracked-input registration.
- :class:`hydromodpy.results.catalog.writes_parquet.WritesMixinParquet`:
  timeseries, observations, budgets, mass balance and GeoParquet writes,
  plus the shared ``_write_parquet_records`` plumbing.
- :class:`hydromodpy.results.catalog.writes_zarr.WritesMixinZarr`:
  field, time, CRS, mesh and geographic raster writes.

Shared helpers live in
:mod:`hydromodpy.results.catalog.writes_helpers`. ``register_simulation``
lives in :mod:`hydromodpy.results.catalog.registration`.

In v2 every Parquet payload is built as a :class:`pyarrow.Table` matching
one of the schemas in :mod:`hydromodpy.results.parquet_schemas`, then
dispatched to :func:`hydromodpy.results.parquet_io.write_table_atomic`.
The legacy DuckDB ``COPY ... (FORMAT PARQUET)`` path is gone.
"""

from __future__ import annotations

from hydromodpy.results.catalog.writes_duckdb import WritesMixinDuckDB
from hydromodpy.results.catalog.writes_parquet import WritesMixinParquet
from hydromodpy.results.catalog.writes_zarr import WritesMixinZarr


class WritesMixin(WritesMixinDuckDB, WritesMixinParquet, WritesMixinZarr):
    """Mutating operations for :class:`Catalog`.

    Composes the per-sink mixins:
    :class:`WritesMixinDuckDB`, :class:`WritesMixinParquet`,
    :class:`WritesMixinZarr`. The MRO keeps every write method resolvable
    on a single facade attribute; cross-mixin calls (e.g.
    ``write_metric`` mirroring to Parquet via ``_write_parquet_records``)
    work through normal Python method resolution.

    Each write method relies on facade attributes provided by
    :class:`Catalog`: ``self._backend`` (CatalogBackend port),
    ``self._db`` (DuckDB connection for perf paths only),
    ``self._workspace``, ``self._paths`` (StoragePathResolver),
    ``self._persistence`` (PersistenceConfig), and ``self.open_zarr``
    (LifecycleMixin).
    """


__all__ = ["WritesMixin"]
