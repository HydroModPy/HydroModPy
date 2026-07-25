Storage Layout
==============

**Disk is the truth. The database is an index rebuilt from disk.**

A project keeps its results as ordinary directories. The DuckDB file next
to them is a query index over those directories: it makes ``find``,
``ls``, metric ranking and cross-project federation fast, and it can be
deleted and rebuilt. Nothing a run needs in order to be read, replayed,
resumed or compared may live only in SQL.

This page is the storage contract. It describes a target that is under
construction: each section marks what is in place today and what is still
being built. Nothing described here as "in place" is aspirational, and no
mechanism is presented as existing before it ships.

For the role of each database scope, see :doc:`overview/two-databases`.
For the migration policy that applies to any change in this layout, see
:doc:`overview/schema-evolution`.

Delivery status
---------------

.. list-table::
   :header-rows: 1
   :widths: 18 82

   * - State
     - Items
   * - In place
     - Per-project DuckDB index (``catalog.duckdb``); per-run Zarr store
       and per-run Parquet directory under ``simulations/``; id-only
       storage basename; opt-in persistence of heavy fields (budget and
       derived); on-disk run heartbeats under ``.hmp/running/``; trash,
       ``gc`` and ``hmp catalog reindex``, which rebuilds the whole index
       from the run directories; ``runs/``, ``sessions/`` and
       ``share/`` ignored by git.
   * - Being built
     - Runs-first folder layout (``runs/<name>/`` with a human name);
       ``manifest.json`` written last; parameters, geographic metadata,
       run environment, workflow trace, frozen config and functional
       tags written into the run folder; ``sessions/<id>/`` with a trials
       journal; ``hmp reindex``; read-only index opening generalised to
       every inspection command (several already do it);
       ``project.toml`` as project-root marker.

Three classes of data
---------------------

The classification is by consumer, not by table. It decides what must
exist on disk before the index can be thrown away, and it is the part of
this contract that is easiest to get wrong.

Class 1: reconstructible (obligation)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Everything runtime code reads back. Each item below must be written into
the run folder (or the session folder) so that a rebuilt index restores
it identically. A value that only a human ever reads is not in this
class; a value that a code path reads is, even if it is rarely hit.

.. list-table::
   :header-rows: 1
   :widths: 26 30 44

   * - Data
     - On-disk home (target)
     - Read by
   * - Run identity, status, solver, mesh and period summary
     - ``runs/<name>/manifest.json``
     - catalog reads, ``hmp catalog ls`` and ``show``, comparison
       selection
   * - Run parameters
     - ``runs/<name>/tables.parquet/parameters.parquet``
     - ``results/catalog/discovery.py`` (search by parameter),
       ``dataset_loader``, comparison audit
   * - Geographic metadata (catchment area, outlet coordinates)
     - ``runs/<name>/manifest.json`` (geometry block)
     - ``simulation/extraction/derivation/catchment_aggregation.py``;
       a missing catchment area currently degrades catchment discharge
       without an error
   * - Run environment (Python, package versions, git commit, solver
       binary fingerprint)
     - ``runs/<name>/provenance.json``
     - ``results/export/context.py``, ``dataset_loader``, rerun
   * - Declared artefacts of the run
     - ``runs/<name>/manifest.json`` (``artifacts[]``)
     - file listing on ``Run``, input bridge, coverage invariant
   * - Metrics
     - ``runs/<name>/tables.parquet/metrics.parquet``
     - ranking, comparison, calibration reporting
   * - Input provenance rows
     - ``runs/<name>/provenance.json``
     - input bridge (``run.input_entries()``), frozen replay
   * - Frozen resolved configuration
     - ``runs/<name>/config.toml``
     - ``hmp run --resume``, ``hmp catalog rerun``
   * - Functional tags
     - ``runs/<name>/annotations.json``
     - tag search, spinup convergence gate
   * - Workflow step trace
     - ``runs/<name>/provenance.json``
     - workflow resume, ``hmp doctor``
   * - Calibration sessions and trials
     - ``sessions/<id>/`` (session manifest plus a trials journal)
     - calibration resume, best promotion, calibration report

Part of this class already lands on disk: a run's Parquet directory
holds ``simulation.parquet`` (the one-row snapshot the rebuild reads),
``metrics.parquet``, ``provenance.parquet``, ``timeseries.parquet``,
``budgets.parquet``, ``mass_balance.parquet`` and the GeoParquet
features. Parameters, geographic metadata, run environment, workflow
steps, tags, the frozen config and the calibration trace are still
SQL-only today. Closing that gap is the precondition for a rebuildable
index, not an optimisation.

Class 2: losable (explicit and assumed)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

These rows are not mirrored on disk. A rebuild drops them, and that is a
decision, not an oversight. Stating the consequence is part of the
contract.

.. list-table::
   :header-rows: 1
   :widths: 24 76

   * - Data
     - Consequence of a rebuild
   * - ``audit_log``
     - the machine event history of the project is lost. Run identity,
       results and lineage are unaffected because they come from the
       manifests.
   * - ``export_log``
     - the record of which export artefacts were emitted is lost. The
       artefacts themselves stay on disk.
   * - ``sim_notes``
     - free-text notes attached to a run are lost unless they were
       written to ``runs/<name>/annotations.json``.
   * - ``deletions``
     - deletion tombstones are lost. The trash directory remains the
       on-disk record of what was removed.
   * - ``purge_journal``
     - an interrupted hard purge is not resumed. The leftover directory
       becomes an orphan that ``gc`` reports.

The measured volume behind this decision, on the Cheze reservoir
project: 194 machine audit events, 31 export rows, zero human note. No
hash-chained ledger, no history lanes and no multi-machine journal are
introduced to protect that content.

Class 3: input (outside the results scope)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Observation series and station metadata are input data. They are
repopulated from their source, that is the workspace input cache and the
data loaders, exactly like a DEM or a climate series. A results rebuild
never tries to recreate them and never treats their absence as a
corrupted run.

Tables not covered by the three classes are the static dimension tables
seeded by the DDL (solvers, statuses, flow regimes, mesh topologies and
the ``dim_*`` tables). A rebuild recreates them from the DDL.

Contract coverage
-----------------

The machine-readable contract in
``hydromodpy/results/storage/contract.py`` currently names three layers:
``catalog``, ``zarr``, ``parquet``. That is one third of what a project
writes. The target contract covers every artefact of a project.

.. list-table::
   :header-rows: 1
   :widths: 26 26 48

   * - Area
     - Path
     - Rule
   * - Run folders
     - ``runs/<name>/``
     - one directory per run, human name, every file declared in the
       manifest
   * - Sessions
     - ``sessions/<id>/``
     - calibration and spinup sessions, trials journal on disk
   * - Exchange packages
     - ``share/``
     - ``.hmp`` archives and exports produced on demand
   * - Technical cache
     - ``.hmp/``
     - index, heartbeats, trash, solver scratch, logs. Entirely
       regenerable, safe to delete
   * - Project configuration
     - ``project.toml`` plus ``configs/``
     - the canonical config and its variants

Testable invariants
~~~~~~~~~~~~~~~~~~~

Three invariants replace the current assertions of
``tests/unit/results/test_result_storage_layout.py``, which pins the
three layer names and the basename rule only.

- **INV0, on-disk sufficiency.** For every table and column that runtime
  code reads (the explicit list of class 1 above), the value is present
  on disk and is read back identically after the index is deleted and
  rebuilt.
- **INV1, coverage.** The set of runs described on disk equals the set of
  runs in the index: one manifest under ``runs/`` maps to exactly one
  indexed run, and every artefact declared in a manifest exists on disk.
  A run directory without a manifest is incomplete, therefore invisible
  to the rebuild and eligible for ``gc``.
- **INV2, idempotence.** Two consecutive rebuilds produce the same index,
  modulo rebuild timestamps.

Project layout
--------------

Target layout of a project root:

.. code-block:: text

   <project>/
   |-- project.toml         canonical config, project-root marker
   |-- configs/             editable config variants
   |-- runs/
   |   `-- <run_name>/      one directory per run (see below)
   |-- sessions/
   |   `-- <session_id>/    calibration and spinup sessions
   |-- share/               .hmp packages and exchange exports
   `-- .hmp/                technical cache, regenerable
       |-- index.duckdb     the index rebuilt from runs/ and sessions/
       |-- running/         live-run heartbeat sidecars
       |-- trash/           deleted runs awaiting purge
       `-- logs/

Layout in place today:

.. code-block:: text

   <project>/
   |-- project.toml
   |-- catalog.duckdb                     the index (project root)
   |-- hydromodpy.lock                    reproducibility lockfile
   |-- figures/  reports/  exports/       rendered outputs
   |-- .hmp/running/                      live-run heartbeat sidecars
   `-- simulations/
       |-- <basename>.zarr/  or .zarr.zip
       `-- <basename>.parquet.d/
           |-- simulation.parquet         one-row snapshot read by reindex
           |-- timeseries.parquet
           |-- budgets.parquet
           |-- mass_balance.parquet
           |-- metrics.parquet
           |-- provenance.parquet
           `-- geographic_*.parquet       GeoParquet vector layers

The project config file is ``project.toml``. Root discovery currently
keys on the presence of ``catalog.duckdb``; the target keys it on
``project.toml``, so a project stays a project after its index is
deleted. A workspace-level ``workspace.toml`` is optional metadata
written by ``hmp workspace init``; it carries no part of this contract
and no project in this repository relies on one.

The machine-wide ``index.duckdb`` lives at ``$XDG_STATE_HOME/hydromodpy/``
(``~/.local/state/hydromodpy/`` on Linux) and federates registered
workspaces through read-only ``ATTACH``.

A run folder
------------

Target contents, all paths relative to ``runs/<run_name>/``:

.. code-block:: text

   runs/<run_name>/
   |-- manifest.json        identity, geometry, artefacts. Written LAST
   |-- config.toml          exact resolved configuration, frozen
   |-- provenance.json      environment, git, input fingerprints, steps
   |-- annotations.json     functional tags and free notes
   |-- fields.zarr/         array store (head by default)
   |-- tables.parquet/      tabular payloads
   `-- run.log              bounded solver and pipeline log

``manifest.json`` is written last, with a temporary file, an ``fsync``
and a rename. That single atomic write is the crash-safety mechanism: a
run directory without a manifest is incomplete by definition. The run is
not staged elsewhere and moved into place, because the Zarr store is
created at registration and appended to during the whole solve, which
live readers depend on.

A session folder
----------------

A calibration or spinup session keeps its own directory under
``sessions/<id>/`` with a session manifest, the frozen search space and
objective, and a trials journal written as it goes. Today the trial
history exists only in the project index, which is precisely why a
rebuild would currently lose a calibration.

Naming and identity
-------------------

The on-disk basename is built by ``StoragePathResolver``:

.. code-block:: text

   <basename> = "<project>__<id8>"

where ``id8`` is the first eight hexadecimal characters of the run
identifier. **The human name never appears in the path.** Renaming,
versioning or replacing a run is a pure index update that touches no
file. The target layout replaces the basename with a human-named
directory under ``runs/``; the identifier stays the index key.

Name collisions follow the ``.vN`` grammar: a bare name is version one
for life, and the next run registered under the same stem becomes
``<stem>.v2``. Replacing a run trashes the predecessor, which keeps its
name and version and stays restorable. Trashing is a status flip today
and becomes a move into ``.hmp/trash/`` with the runs-first layout.

Per-run Zarr store
------------------

Zarr v2 root. The store is staged and promoted to its final path with a
rename at registration, then appended to in place for the whole solve,
under a cross-process file lock. It is not staged again at the end,
because live readers follow that path while the run is solving. An
optional finalisation packs the directory into a ``.zarr.zip``.

.. code-block:: text

   <run>/fields.zarr/
   |-- meta/         ACDD root attributes and ZARR_SCHEMA_VERSION
   |-- mesh/         topology, cell types, coordinates
   |-- state/        head and other state fields
   |-- forcing/      recharge and other forcings
   |-- particles/    particle trajectories
   |-- derived/      created only when a derived field is opted in
   `-- budget/       created only when budget.spatial_fields is on

``derived/`` and ``budget/`` are not pre-created. Heavy fields are opt-in
(``[simulation.results.derived]`` and
``[simulation.results.budget] spatial_fields``), so a default run carries
neither group and the lumped budget still feeds the catchment scalars.

Compression defaults to Blosc-zstd, each variable carries CF
``standard_name`` and ``_FillValue`` attributes, consolidated metadata is
strict, and ``ZARR_SCHEMA_VERSION`` is pinned to ``"2"``. Solver
sentinel values are masked to NaN at write time.

Per-run Parquet directory
-------------------------

Parquet v2.6 files written through ``write_table_atomic`` (temporary file
plus ``os.replace``) with ZSTD compression, 50 000-row groups, page index
and bloom filters where available. Each file carries
``hmp.schema_version = "v2"`` in its key-value metadata and is exposed as
a DuckDB view named after the payload.

The container directory uses the ``.parquet.d`` suffix and the payloads
inside use ``.parquet``, so a plain ``glob`` is never ambiguous.

.. list-table::
   :header-rows: 1
   :widths: 26 74

   * - Payload
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
   * - ``metrics.parquet``
     - one row per metric of the run
   * - ``provenance.parquet``
     - input provenance rows of the run
   * - ``simulation.parquet``
     - one-row snapshot of the run's index entry, read by ``reindex``
   * - ``geographic_*.parquet``
     - GeoParquet 1.1 vector layers (catchment outline, buffered box,
       drainage network)

Project index DuckDB schema
---------------------------

Tables of the project index. The authoritative DDL is
``hydromodpy/results/catalog/migrations/0001_initial.sql``. The
``Class`` column is the classification defined above.

.. list-table::
   :header-rows: 1
   :widths: 22 14 64

   * - Table
     - Class
     - Key columns
   * - ``simulations``
     - index
     - ``sim_id`` (UUID v7), ``name``, ``name_stem``, ``version_int``,
       ``project``, ``solver_id``, ``status_id``, ``mesh_hash``,
       ``n_cells``, ``n_layers``, ``n_timesteps``, ``crs_wkt``,
       ``bbox_*``, ``period_start/end``, ``config_snapshot``,
       ``config_hash``, ``zarr_path``, ``storage_basename``,
       ``duration_s``
   * - ``parameters``
     - index
     - ``sim_id``, ``param_name``, ``zone_id`` (default
       ``"__global__"``), ``value``, ``unit``, ``parameterization``
   * - ``metrics``
     - index
     - ``sim_id``, ``station_id`` (default ``"__outlet__"``),
       ``metric_name``, ``value``, ``n_samples``
   * - ``calibration_sessions``
     - index
     - ``session_id``, ``project``, ``method``, ``objective_name``,
       ``n_iterations``, ``best_sim_id``, ``status``
   * - ``calibration_iterations``
     - index
     - ``session_id``, ``iteration``, ``sim_id``, ``params_hash``,
       ``parameters`` (JSON), ``objective_value``
   * - ``provenance``
     - index
     - ``sim_id``, ``variable``, ``source_type``, ``source_ref``,
       ``source_sha256``, ``payload_sha256``, ``fetched_at``,
       ``n_records``
   * - ``runs_environment``
     - index
     - ``sim_id``, ``python_version``, ``hydromodpy_version``,
       ``platform``, ``git_commit``, ``solver_binary_sha256``,
       ``rng_seed``
   * - ``geographic_metadata``
     - index
     - ``sim_id``, ``key``, ``value``. Holds the catchment area and
       outlet coordinates used by catchment aggregation
   * - ``geographic_features``
     - index
     - ``sim_id``, ``feature_name``, ``geometry_kind``,
       ``geoparquet_path``
   * - ``tracked_files``
     - index
     - ``sim_id``, ``role``, ``category``, ``original_path``
       (project-relative), ``canonical_path``, ``sha256``,
       ``size_bytes``. Becomes the manifest ``artifacts[]`` list
   * - ``workflow_steps``, ``workflow_events``
     - index
     - workflow ledger: ``step_id``, ``sim_id``, ``step_name``,
       ``status``, ``started_at``, ``ended_at``, ``payload``
   * - ``tags``
     - index
     - ``sim_id``, ``tag``. Functional tags gate spinup convergence and
       tag search
   * - ``observation_points``
     - index
     - ``sim_id``, ``station_id``, ``x``, ``y``, ``cell_id``,
       ``layer``, ``crs_wkt``, ``crs_epsg``
   * - ``audit_log``, ``export_log``, ``sim_notes``, ``deletions``,
       ``purge_journal``
     - losable
     - machine event history, export bookkeeping, free notes,
       tombstones, purge resume state
   * - ``stations``, ``observations``
     - input
     - station metadata and observation series, repopulated from the
       input cache
   * - ``solvers``, ``statuses``, ``flow_regimes``,
       ``mesh_topologies``, ``dim_*``, ``metric_definitions``,
       ``retention_policies``
     - dimension
     - static vocabularies seeded by the DDL
   * - ``schema_migrations``
     - dimension
     - one row per applied migration: ``version``, ``component``,
       ``slug``, ``checksum``, ``applied_at``

Companion views, created at runtime by
``hydromodpy/results/catalog/views.py``: ``v_simulation_summary`` (the
view the machine index federates), ``v_best_per_project``,
``v_metrics_wide``, ``v_params_wide``.

Backend abstraction
-------------------

Project index SQL access goes through the
:class:`~hydromodpy.results.catalog.ports.CatalogBackend` Protocol in
normal runtime paths. The in-tree V1 adapter is ``DuckDBBackend``.
HydroModPy V1 does not promise a fully portable non-DuckDB backend:
cache stores, diagnostics, migration runners and portable-package
snapshots are DuckDB-specific by contract. Field readers go through
``hmp.read``, which dispatches to Zarr or Parquet stores via the field
registry. See :doc:`/architecture/packages/results` for the Python
surface.

Concurrency and atomic writes
-----------------------------

- Index writes use ``connect_with_retry`` and the ``@with_lock_retry``
  decorator, so short-lived cross-process contention resolves instead of
  surfacing as an error.
- Zarr field writes hold a cross-process ``filelock`` on the store root
  and append in place. The store directory is promoted with a rename
  when it is created, and packing to ``.zarr.zip`` writes and verifies a
  temporary archive before the rename.
- Parquet writes use a temporary file plus ``os.replace``.
- A solving run refreshes a heartbeat sidecar under ``.hmp/running/`` so
  ``hmp catalog watch`` and ``gc`` read liveness from a file rather than
  from a database a live solve holds locked.

Lockfile and reproducibility
----------------------------

``hydromodpy.lock`` is written best-effort at the project root when the
run can reach the workspace input cache. It is written atomically
(temporary file, ``fsync``, ``os.replace``) and pins:

- the ``hydromodpy`` version, git commit, Python version and config
  schema fingerprint;
- the solver binaries with their SHA-256 and version text;
- the catalog, Zarr and Parquet schema versions;
- input fingerprints (relative path, SHA-256, size, fetch date).

``hmp run --frozen`` refuses any source whose fingerprint changed since
the lockfile was written. When no input cache is available, a normal run
may complete without a lockfile; that is a reproducibility warning, not
a failed run.

Direct DuckDB exceptions
------------------------

The normal application path uses index and cache adapters. Direct
``duckdb.connect`` is accepted only for:

- migration runners that bootstrap schema files;
- concrete backend constructors and adapters;
- read-only diagnostics and doctor output;
- portable ``.hmp`` package snapshots;
- tests and performance benchmarks;
- developer-only CLI inspection commands.

A new direct DuckDB call in a user-facing CLI command or in
``hydromodpy._api`` is a contract regression unless this list is updated
with a rationale.

Portable ``.hmp`` packages
--------------------------

``hmp catalog export <ref> -o run.hmp`` bundles the resolved config, the
provenance, the index rows of the run and its Zarr and Parquet stores
into one archive; several references produce a single multi-run
container. ``hmp catalog import run.hmp`` verifies the checksums and
re-materialises the runs in the target project.

See also
--------

- :doc:`overview/two-databases` for the role of each database scope.
- :doc:`overview/schema-evolution` for the migration policy.
- :doc:`artifact-policy` for non-canonical artefacts and sidecars.
- :doc:`/architecture/packages/results` for the Python API on top of
  this storage (``Catalog``, ``Run``, ``RunSet``, ``hmp.read``).
- :doc:`/architecture/packages/data` for the input cache writer.
