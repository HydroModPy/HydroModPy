results
=======

``hydromodpy.results`` owns the project-level catalog and the
per-run ``Run`` facade. It is the read-write layer between solver
outputs and downstream consumers (display, analysis, exports).

Sub-modules
-----------

- ``results/catalog/`` -- ``SimulationCatalog`` facade plus
  read / write mixins. One DuckDB file per project
  (``catalog.duckdb``); see :doc:`/architecture/storage-layout`.
- ``results/catalog/ports.py`` -- :class:`CatalogBackend` Protocol
  (Ports and Adapters port) consumed by every catalog operation.
- ``results/catalog/adapters/`` -- ``DuckDBBackend`` in-tree adapter.
  Additional adapters can plug in by implementing the protocol.
- ``results/catalog/migrations/`` -- Alembic-like SQL migrations
  applied by the runner in ``hydromodpy/core/migrations/runner.py``.
- ``results/run.py`` -- ``Run`` facade exposing read-only access to
  one persisted simulation. Stays below the 50-method limit.
- ``results/run_array.py``, ``run_timeseries.py``,
  ``run_geographic.py``, ``run_hydrographic.py``,
  ``run_environment.py`` -- focused mixins behind the ``Run`` facade.
- ``results/field_registry.py`` -- maps a logical field name to a
  Zarr or Parquet reader. Used by the ``hmp.read`` facade.
- ``results/zarr_store/`` -- Zarr v2 store with atomic writes,
  filelock, ACDD and CF metadata, ``ZARR_SCHEMA_VERSION``.
- ``results/parquet_io.py`` and ``parquet_schemas.py`` -- Parquet
  v2.6 writers, KV-metadata mixin, ``PARQUET_SCHEMA_VERSION``.
- ``results/geoparquet_io.py`` -- GeoParquet 1.1 writers
  (``GEOPARQUET_SCHEMA_VERSION``).
- ``results/simulation_group.py`` -- ``SimulationGroup`` view across
  multiple runs (used by comparison and calibration analysis).
- ``results/exporters/`` -- format writers: ``csv``, ``netcdf``,
  ``geotiff``, ``vtu``, ``shapefile``, ``hmp_package``.
- ``results/importers/`` -- ``hmp_package`` reader plus catalog
  ingestion helpers.

Run API
-------

``Run`` exposes a stable read interface:

- **Metadata**: ``sim_id``, ``name``, ``project``, ``solver``,
  ``status``, ``created_at``, ``duration_s``, ``n_layers``,
  ``n_cells``, ``n_timesteps``, ``tags``, ``hydromodpy_config``,
  ``summary()``.
- **Tabular**: ``parameters`` (DataFrame), ``metrics`` (DataFrame),
  ``provenance`` (DataFrame).
- **Time series**: ``timeseries(variable, station, period=None)``,
  ``observed(variable, station=None)``.
- **Budgets**: ``budget(component=None, zone_id=None,
  period=None)``, ``mass_balance``.
- **Field arrays**: ``field(variable, timestep=-1, layer=None)``,
  ``fields(variable)``.
- **Spatial**: ``mesh``, ``grid``, ``dem``,
  ``geographic_features``, ``catchment_mask``, ``outlet``.
- **Plot**: ``plot(figsize, dpi, save_path)``.
- **Array provider**: ``run.array.dataset(variable=None)`` returns
  an ``xugrid.UgridDataset``; ``to_xarray_batch()``;
  ``at(timestep, layer)``.

Catalog operations
------------------

``SimulationCatalog`` exposes:

- ``hmp.open(project_path)`` -- single catalog door. Default
  ``create=False`` raises ``FileNotFoundError`` when no
  ``catalog.duckdb`` exists; pass ``create=True`` to initialise an
  empty one.
- ``find(**filters)`` -- one return type (a ``SimulationGroup``);
  raises ``ValueError`` listing valid filters on an unknown key.
- ``frame`` -- the full simulations ``DataFrame``.
- ``resolve(prefix)`` -- expand a sim id prefix.
- ``__getitem__(ref)`` -- return a ``Run``.
- ``latest()``, ``best(metric)``, ``worst(metric)``, ``rank(...)``.
- ``read(ref, variable)`` -- by-id field / timeseries / feature read.
- Schema discovery: ``describe()``, ``tables()``, ``columns()``,
  ``variables()``, ``metrics()``, ``stations()``.
- ``query_timeseries(sim_id, station=..., variable=...)``,
  ``query_budget(sim_id, component=...)``,
  ``query_mass_balance(sim_id)``.
- ``calibration_sessions()``,
  ``calibration_iterations(session_id)``.
- ``export_package(sim_id, path)``,
  ``import_package(path)``.
- ``export(sim_id, variable, fmt, path)`` for CSV, NetCDF, GeoTIFF,
  VTU and Shapefile exports.
- ``sql(query, params)`` for cross-run analytics.

Field reads go through the ``hmp.read`` facade (see ``hydromodpy.read``
re-export). The facade dispatches to a Zarr or Parquet reader via
``field_registry.py`` so the same call works regardless of where the
field lives. The by-id path is ``cat.read(ref, variable)``. The legacy
``catalog.query_field`` is removed in v2.

Companion DuckDB views (``v_simulation_summary``,
``v_best_per_project``, ``v_metrics_wide``, ``v_params_wide``)
remain available for ad-hoc SQL.

Cross-project / cross-workspace queries go through the
:class:`~hydromodpy.core.state.global_index.GlobalIndex` exposed as
``hmp.index()``. The index federates every registered workspace via
ATTACH read-only and rebuilds ``all_simulations`` on refresh.

Concurrency
-----------

Every write path is wrapped in ``connect_with_retry`` and
``@with_lock_retry`` so short-lived cross-process lock contention
resolves transparently.

Recommended reading path
------------------------

1. ``hydromodpy/results/catalog/migrations/0001_initial.sql`` for the
   canonical table layout.
2. ``hydromodpy/results/catalog/ports.py`` (Protocol).
3. ``hydromodpy/results/catalog/adapters/duckdb.py`` (in-tree
   implementation).
4. ``hydromodpy/results/catalog/facade.py`` (``SimulationCatalog``).
5. ``hydromodpy/results/run.py`` (``Run`` facade).
6. ``hydromodpy/results/field_registry.py`` for the field dispatch
   used by ``hmp.read``.
7. ``hydromodpy/results/exporters/csv.py`` for an exporter
   reference.
8. ``hydromodpy/results/exporters/hmp_package.py`` for the bundle
   format.

Layer-matrix neighbours
-----------------------

- Allowed targets: ``core``, ``schema``, ``config``, ``results``,
  ``spatial``.
- Documented tolerance: ``results`` -> ``data`` for the read-only
  cross-DB ATTACH bridge.
- Allowed sources: ``display``, ``analysis``, ``calibration``,
  ``reporting``, ``workflow``, ``catalog``, ``project`` and ``cli``.

See also
--------

- :doc:`/architecture/storage-layout` -- DuckDB schema, Zarr stores,
  Parquet directories, basename rule.
- :doc:`/architecture/overview/two-databases` -- cache-vs-catalog
  split.
- :doc:`/architecture/how-to/add-an-exporter` -- step-by-step
  recipe.
- :doc:`/user_guide/results-and-exports` -- user-facing reference.
