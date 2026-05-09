results
=======

``hydromodpy.results`` owns the workspace-level catalog and the
per-run ``Run`` facade. It is the read-write layer between solver
outputs and downstream consumers (display, analysis, exports).

Sub-modules
-----------

- ``results/catalog/`` -- ``SimulationCatalog`` facade plus
  read / write mixins. One DuckDB file per workspace
  (``hydromodpy.duckdb``); see :doc:`/architecture/storage-layout`.
- ``results/catalog_schema.py`` -- canonical column definitions for
  every table (``simulations``, ``parameters``, ``metrics``,
  ``calibration_sessions``, ``calibration_iterations``,
  ``provenance``, etc.).
- ``results/run.py`` -- ``Run`` facade exposing read-only access to
  one persisted simulation.
- ``results/run_array.py`` and ``run_export.py`` -- supporting
  modules for array access and ``Run.export``.
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
- **Plot / export**: ``plot(figsize, dpi, save_path)``,
  ``export(variable, fmt, path)``.
- **Array provider**: ``run.array.dataset(variable=None)`` returns
  an ``xugrid.UgridDataset``; ``to_xarray_batch()``;
  ``at(timestep, layer)``.

Catalog operations
------------------

``SimulationCatalog`` exposes:

- ``open(workspace)`` -- entry point
  (``hydromodpy.open(workspace)``).
- ``list_simulations(project=..., status=..., order_by=...)``
- ``resolve(prefix)`` -- expand a sim id prefix.
- ``__getitem__(sim_id)`` -- return a ``Run``.
- ``latest(project=...)``, ``best(project, metric)``.
- ``query_field(sim_id, variable, timestep)``,
  ``query_timeseries(sim_id, variable, station=...)``,
  ``query_budget(sim_id, component=...)``,
  ``query_mass_balance(sim_id)``.
- ``calibration_sessions()``,
  ``calibration_iterations(session_id)``.
- ``export_package(sim_id, path)``,
  ``import_package(path)``.
- ``sql(query, params)`` for cross-run analytics.

Companion DuckDB views (``v_simulation_summary``,
``v_best_per_project``, ``v_metrics_wide``, ``v_params_wide``)
remain available for ad-hoc SQL.

Concurrency
-----------

Every write path is wrapped in ``connect_with_retry`` and
``@with_lock_retry`` so short-lived cross-process lock contention
resolves transparently.

Recommended reading path
------------------------

1. ``hydromodpy/results/catalog_schema.py`` for the table layout.
2. ``hydromodpy/results/catalog/facade.py`` (``SimulationCatalog``).
3. ``hydromodpy/results/run.py`` (``Run`` facade).
4. ``hydromodpy/results/exporters/csv.py`` for an exporter
   reference.
5. ``hydromodpy/results/exporters/hmp_package.py`` for the bundle
   format.

Layer-matrix neighbours
-----------------------

- Allowed targets: ``core``, ``schema``, ``config``, ``results``.
- Documented tolerances: ``results`` -> ``spatial`` (spatial
  indices), ``results`` -> ``analysis`` (Run exposes stream-network
  diagnostics).
- Allowed sources: ``display``, ``analysis``, ``calibration``,
  ``workflow``, ``cli``.

See also
--------

- :doc:`/architecture/storage-layout` -- DuckDB schema, Zarr stores,
  Parquet directories, basename rule.
- :doc:`/architecture/overview/two-databases` -- cache-vs-catalog
  split.
- :doc:`/architecture/how-to/add-an-exporter` -- step-by-step
  recipe.
- :doc:`/user_guide/results-and-exports` -- user-facing reference.
