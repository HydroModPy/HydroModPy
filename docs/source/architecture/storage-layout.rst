Storage Layout
==============

A HydroModPy workspace stores three families of artefacts:

- a **DuckDB catalog** with simulation metadata, parameters, metrics,
  provenance, and calibration trace;
- **Zarr stores** with simulation field arrays, mesh, and rasters;
- **Parquet directories** with per-simulation timeseries, budgets,
  and mass-balance tables, exposed as DuckDB views.

A second DuckDB database (``data/cache.duckdb``) sits next to the
catalog and tracks downloaded and custom input data. See
:doc:`overview/two-databases` for that split.

Workspace layout
----------------

.. code-block:: text

   <workspace>/
   |-- hydromodpy.duckdb                 simulation catalog (one per workspace)
   |-- data/
   |   |-- cache.duckdb                  input data cache
   |   `-- <variable>/                   raw files (CSV, NC, TIF)
   |-- simulations/
   |   |-- <basename>.zarr/  or .zarr.zip   per-simulation field arrays
   |   `-- <basename>.parquet/
   |       |-- timeseries.parquet
   |       |-- budgets.parquet
   |       `-- mass_balance.parquet
   `-- projects/
       `-- <project>/
           |-- project.toml
           `-- run_*.toml

The catalog filename is fixed (``hydromodpy.duckdb``). Zarr and
Parquet sit under ``simulations/`` with a deterministic basename
documented below.

Storage basename rule
---------------------

The per-simulation basename is built by ``StoragePathResolver``:

.. code-block:: text

   <basename> = "<project>__<name>__<sim_id_first_chars>"

Older workspaces that used the raw ``sim_id`` as filename remain
readable. ``hmp manage`` can preview and explicitly normalise legacy
names.

Catalog DuckDB schema
---------------------

Tables in ``hydromodpy.duckdb`` (see
``hydromodpy/results/catalog_schema.py`` for the authoritative
columns).

.. list-table::
   :header-rows: 1
   :widths: 24 76

   * - Table
     - Key columns
   * - ``simulations``
     - ``sim_id`` (UUID), ``name``, ``project``, ``solver``,
       ``status``, ``mesh_hash``, ``n_cells``, ``n_layers``,
       ``n_timesteps``, ``crs_wkt``, ``bbox_xmin/ymin/xmax/ymax``,
       ``period_start/end``, ``zarr_path``, ``storage_basename``,
       ``duration_s``, ``tags``, ``description``,
       ``scientific_objective``
   * - ``parameters``
     - ``sim_id``, ``param_name``, ``zone_id`` (default
       ``"__global__"``), ``value``, ``unit``, ``parameterization``
   * - ``metrics``
     - ``sim_id``, ``station_id`` (default ``"__outlet__"``),
       ``metric_name``, ``value``, ``n_samples``
   * - ``calibration_sessions``
     - ``session_id``, ``project``, ``method``, ``objective_name``,
       ``n_iterations``, ``best_sim_id``, ``status``
   * - ``calibration_iterations``
     - ``session_id``, ``iteration``, ``sim_id`` (NULL until
       promoted), ``params_hash``, ``parameters`` (JSON),
       ``objective_value``
   * - ``provenance``
     - ``sim_id``, ``variable``, ``source_type``
       (``http_api`` / ``custom_file`` / ``data_manager`` /
       ``derived`` / ``cache``), ``source_ref``, ``source_sha256``,
       ``payload_sha256``, ``fetched_at``, ``n_records``
   * - ``observation_points``
     - ``sim_id``, ``station_id``, ``x``, ``y``, ``cell_id``,
       ``layer``, ``crs_wkt``, ``crs_epsg``
   * - ``geographic_features``
     - ``sim_id``, ``feature_name``, ``geometry_kind``
       (``point`` / ``linestring`` / ``polygon`` / ``multipolygon``),
       ``geoparquet_path``
   * - ``runs_environment``
     - ``sim_id``, ``python_version``, ``hydromodpy_version``,
       ``platform``, ``git_commit``, ``mf6_binary_sha256``,
       ``rng_seed``
   * - ``tracked_files``
     - ``sim_id``, ``role``, ``category``, ``original_path``,
       ``canonical_path``, ``sha256``, ``size_bytes``
   * - ``stations``
     - ``station_id``, ``name``, ``latitude``, ``longitude``,
       ``variable_type``, ``source``, ``active``, ``first_valid``,
       ``last_valid``
   * - ``observations``
     - ``station_id``, ``variable_type``, ``datetime``, ``value``,
       ``unit``, ``quality``

Companion views (read-only):

- ``v_simulation_summary`` -- one row per sim with counts and best
  metrics.
- ``v_best_per_project`` -- best simulation per project ranked by an
  agreed metric.
- ``v_metrics_wide`` -- pivoted metrics for cross-run comparison.
- ``v_params_wide`` -- pivoted parameters for cross-run comparison.

Per-simulation Zarr store
-------------------------

The Zarr root is laid out by family:

.. code-block:: text

   <basename>.zarr/
   |-- meta/                  Run-level attributes
   |-- mesh/                  Vertices, connectivity, cell types
   |-- field/                 head, watertable_*, accumulation_flux,
   |                          outflow_drain, seepage_areas, ...
   |-- raster/                Geographic rasters cached for plotting
   `-- budget/                Budget components per timestep

Field arrays use NumPy dtype with chunked layout aligned to the
mesh's cell partitioning. Compression defaults to Blosc-zstd.

Per-simulation Parquet directory
--------------------------------

The Parquet directory holds tabular payloads exposed as DuckDB views
under the original table names (``SELECT ... FROM timeseries`` keeps
working).

.. list-table::
   :header-rows: 1
   :widths: 24 76

   * - File
     - Columns
   * - ``timeseries.parquet``
     - ``sim_id``, ``station_id``, ``variable``, ``datetime``,
       ``value``, ``unit``, ``qflag``
   * - ``budgets.parquet``
     - ``sim_id``, ``timestep``, ``zone_id``, ``component``,
       ``flux_in``, ``flux_out``, ``unit``
   * - ``mass_balance.parquet``
     - ``sim_id``, ``timestep``, ``total_in``, ``total_out``,
       ``storage_in``, ``storage_out``, ``percent_error``

Concurrency and retry
---------------------

DuckDB writes use ``connect_with_retry`` and the ``@with_lock_retry``
decorator on every write path. Short-lived cross-process lock
contention resolves transparently instead of surfacing as an error.

Lockfile and reproducibility
----------------------------

Every run writes ``hydromodpy.lock`` next to the workspace catalog.
The lockfile pins:

- the resolved configuration tree (post-Pydantic),
- the package version and git commit (when available),
- the solver binary release tag and SHA-256,
- the input-data fingerprints recorded under ``provenance``.

A frozen replay (``hmp run --frozen``) refuses any source that has
changed since the lockfile was written.

Portable ``.hmp`` packages
--------------------------

``hmp export <sim_id> -o run.hmp`` bundles:

- the resolved TOML and the lockfile;
- the matched DuckDB rows for that ``sim_id`` plus referenced rows
  (``parameters``, ``metrics``, ``provenance``,
  ``observation_points``, etc.);
- the per-simulation Zarr store and Parquet directory;
- a JSON manifest with the schema version.

``hmp add run.hmp`` (or ``hmp import``) re-materialises the bundle in
the target workspace, refusing packages whose schema version exceeds
the current library.

See also
--------

- :doc:`overview/two-databases` for the cache-vs-catalog split.
- :doc:`overview/schema-evolution` for the migration policy that
  applies to every change in this layout.
- :doc:`packages/results` for the Python API on top of this storage
  (``SimulationCatalog``, ``Run``, ``SimulationGroup``).
- :doc:`packages/data` for the input cache writer.
