Storage Layout
==============

HydroModPy v2 organises storage around three SQL databases plus columnar
file stores. The model is **workspace > project > run**, with each level
holding its own catalog:

- a **machine-wide global index** (``index.duckdb``) federating registered
  workspaces;
- a per-workspace **input cache** (``data/cache.duckdb``) tracking
  downloaded and custom datasets;
- a per-project **simulation catalog** (``catalog.duckdb``) holding
  simulations, parameters, metrics, provenance, calibration trace, and
  the workflow ledger.

Field arrays are persisted as **Zarr v2** stores under
``simulations/<basename>.zarr/`` or ``.zarr.zip``. Tabular outputs are
persisted as **Parquet v2.6** under ``simulations/<basename>.parquet/``
and exposed as DuckDB views.

For background on the cache/catalog split, see
:doc:`overview/two-databases`. For the migration policy that applies to
every change in this layout, see :doc:`overview/schema-evolution`.

Three-level layout
------------------

.. code-block:: text

   <workspace>/
   |-- workspace.toml                metadata of the research workspace
   |-- data/
   |   |-- cache.duckdb              input cache (one per workspace)
   |   |-- dem/
   |   |   |-- raw/                  immutable downloads + sidecar .json
   |   |   `-- processed/            reprojected and clipped derivatives
   |   |-- climate/
   |   `-- ...
   `-- projects/
       `-- <project_name>/
           |-- hydromodpy.toml       project config (Pydantic root)
           |-- catalog.duckdb        simulation catalog (one per project)
           `-- simulations/
               |-- <basename>.zarr/  or .zarr.zip
               `-- <basename>.parquet/
                   |-- timeseries.parquet
                   |-- budgets.parquet
                   `-- mass_balance.parquet

The machine-wide ``index.duckdb`` lives at ``$XDG_STATE_HOME/hydromodpy/``
(``~/.local/state/hydromodpy/`` on Linux) and federates several workspaces
through ATTACH read-only.

Storage basename rule
---------------------

The per-simulation basename is built by ``StoragePathResolver``:

.. code-block:: text

   <basename> = "<project>__<name>__<sim_id_first_chars>"

The database identity stays the full ``sim_id`` stored in the project
``catalog.duckdb``.

Project catalog DuckDB schema
-----------------------------

Tables in ``<project>/catalog.duckdb`` (see
``hydromodpy/results/catalog/migrations/`` for the authoritative DDL
shipped as Alembic-like migrations).

.. list-table::
   :header-rows: 1
   :widths: 24 76

   * - Table
     - Key columns
   * - ``simulations``
     - ``sim_id`` (UUID v7), ``name``, ``project``, ``solver``,
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
     - ``session_id``, ``iteration``, ``sim_id``, ``params_hash``,
       ``parameters`` (JSON), ``objective_value``
   * - ``provenance``
     - ``sim_id``, ``variable``, ``source_type``, ``source_ref``,
       ``source_sha256``, ``payload_sha256``, ``fetched_at``,
       ``n_records``
   * - ``observation_points``
     - ``sim_id``, ``station_id``, ``x``, ``y``, ``cell_id``,
       ``layer``, ``crs_wkt``, ``crs_epsg``
   * - ``geographic_features``
     - ``sim_id``, ``feature_name``, ``geometry_kind``,
       ``geoparquet_path``
   * - ``runs_environment``
     - ``sim_id``, ``python_version``, ``hydromodpy_version``,
       ``platform``, ``git_commit``, ``solver_binary_sha256``,
       ``rng_seed``
   * - ``tracked_files``
     - ``sim_id``, ``role``, ``category``, ``original_path``
       (workspace-relative), ``canonical_path``, ``sha256``,
       ``size_bytes``
   * - ``stations``
     - ``station_id``, ``name``, ``latitude``, ``longitude``,
       ``variable_type``, ``source``, ``active``
   * - ``observations``
     - ``station_id``, ``variable_type``, ``datetime``, ``value``,
       ``unit``, ``quality``
   * - ``workflow_steps``
     - workflow ledger merged into the catalog: ``step_id``,
       ``sim_id``, ``step_name``, ``status``, ``started_at``,
       ``ended_at``, ``payload``
   * - ``schema_migrations``
     - one row per applied migration: ``version``, ``component``,
       ``slug``, ``checksum``, ``applied_at``

Companion views (read-only):

- ``v_simulation_summary``,
- ``v_best_per_project``,
- ``v_metrics_wide``, ``v_params_wide``.

Workspace cache DuckDB schema
-----------------------------

``<workspace>/data/cache.duckdb`` is keyed on the data variable, source,
and SHA-256 fingerprint. Key tables:

.. list-table::
   :header-rows: 1
   :widths: 24 76

   * - Table
     - Role
   * - ``entries``
     - one row per cached file. Columns ``entry_id``, ``variable``,
       ``source_type``, ``file_path`` (workspace-relative POSIX),
       ``payload_sha256``, ``fetched_at``, ``size_bytes``.
   * - ``artifacts``
     - derived layers (reprojections, clipping, mosaics) tied back to a
       parent ``entries`` row.
   * - ``provenance``
     - upstream source ref, license, citation, query parameters.
   * - ``failures``
     - failed downloads tagged for retry.
   * - ``validation_reports``
     - sidecar JSON validation outcome per ``entries`` row.
   * - ``schema_migrations``
     - same migration ledger format as the project catalog.

Machine global index DuckDB schema
----------------------------------

``$XDG_STATE_HOME/hydromodpy/index.duckdb`` keeps the list of registered
workspaces and rebuilds federated views on demand:

.. list-table::
   :header-rows: 1
   :widths: 24 76

   * - Table or view
     - Role
   * - ``workspaces``
     - one row per registered workspace URI plus the path to its
       ``catalog.duckdb`` files.
   * - ``all_simulations``
     - federated view over every project catalog reachable from
       registered workspaces. Read-only.
   * - ``all_metrics``, ``all_projects``
     - companion federated views used by ``hmp index search``.

Per-simulation Zarr store
-------------------------

Zarr v2 root layout, written atomically (tmp + rename + fsync) under a
file lock:

.. code-block:: text

   <basename>.zarr/
   |-- meta/                  ACDD root attributes + ZARR_SCHEMA_VERSION
   |-- mesh/                  topology, cell types, coordinates
   |-- field/                 head, watertable_*, accumulation_flux, ...
   |-- topography/            DEM-derived rasters (renamed from raster/)
   |-- particles/             particle trajectories (renamed from pathlines/)
   `-- budget/                budget components per timestep

Compression defaults to Blosc-zstd. Each variable carries CF
``standard_name`` and ``_FillValue`` attributes, consolidated metadata
is strict, and ``ZARR_SCHEMA_VERSION`` is pinned to ``"2"``.

Per-simulation Parquet directory
--------------------------------

Parquet v2.6 files produced through ``write_table_atomic`` (tmp +
``os.replace``) with ZSTD compression, row-group size 50 000, page index
and bloom filters where available. Each file carries
``hmp.schema_version = "v2"`` in the KV-metadata mixin and is exposed as
a DuckDB view named after the table.

.. list-table::
   :header-rows: 1
   :widths: 24 76

   * - File
     - Columns
   * - ``timeseries.parquet``
     - ``sim_id``, ``station_id``, ``variable``, ``datetime``,
       ``value``, ``unit``, ``qflag``
   * - ``budgets.parquet``
     - ``sim_id``, ``timestep`` (BIGINT), ``zone_id``, ``component``,
       ``flux_in``, ``flux_out``, ``unit``
   * - ``mass_balance.parquet``
     - ``sim_id``, ``timestep``, ``total_in``, ``total_out``,
       ``storage_in``, ``storage_out``, ``percent_error``

GeoParquet 1.1 is used for vector layers persisted alongside the
simulation (catchment outline, drainage network).

Backend abstraction
-------------------

All SQL access goes through the
:class:`~hydromodpy.results.catalog.ports.CatalogBackend` Protocol. The
in-tree adapter is ``DuckDBBackend``. Alternative adapters can plug in
by implementing the protocol.
Field readers go through ``hmp.read`` which dispatches to Zarr or
Parquet stores via the field registry. See
:doc:`/architecture/packages/results` for the Python surface.

Concurrency and retry
---------------------

DuckDB writes use ``connect_with_retry`` and the ``@with_lock_retry``
decorator on every write path. Zarr writes acquire a ``filelock`` on
the store root, write to a sibling tmp directory, and promote with
``os.replace``. Short-lived cross-process lock contention resolves
transparently instead of surfacing as an error.

Lockfile and reproducibility
----------------------------

Every run writes ``hydromodpy.lock`` next to the project catalog. The
lockfile pins:

- the resolved Pydantic configuration tree;
- ``hydromodpy`` version and git commit;
- the solver binary release tag and SHA-256;
- ``ZARR_SCHEMA_VERSION``, ``PARQUET_SCHEMA_VERSION``, and the catalog
  migration version applied;
- input-data fingerprints from ``provenance``.

A frozen replay (``hmp run --frozen``) refuses any source whose
fingerprint has changed since the lockfile was written.

Portable ``.hmp`` packages
--------------------------

``hmp export <sim_id> -o run.hmp`` bundles:

- the resolved TOML and the lockfile;
- the matched DuckDB rows for that ``sim_id`` plus referenced rows;
- the per-simulation Zarr store and Parquet directory;
- a JSON manifest with the schema version.

``hmp add run.hmp`` re-materialises the bundle in the target project,
refusing packages whose schema version exceeds the current library.

See also
--------

- :doc:`overview/two-databases` for the cache vs catalog split.
- :doc:`overview/schema-evolution` for the migration policy.
- :doc:`/architecture/packages/results` for the Python API on top of
  this storage (``SimulationCatalog``, ``Run``, ``SimulationGroup``,
  ``hmp.read`` facade).
- :doc:`/architecture/packages/data` for the input cache writer.
