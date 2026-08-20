Storage Layout
==============

**Disk is the truth. The database is an index rebuilt from disk.**

A project keeps its results as ordinary directories, one per run. The
DuckDB file under ``.hmp/`` is a query index over those directories: it
makes ``ls``, ``show``, metric ranking and cross-project federation fast,
and it can be deleted and rebuilt with ``hmp catalog reindex``. Nothing a
run needs in order to be read, replayed, resumed or compared may live
only in SQL.

This page is the storage contract. It describes what the toolbox writes
today. The last section lists what is *not* in place, so that nothing
here is read as a promise.

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
     - Runs-first layout: ``runs/<name>/`` named after the run, with
       ``manifest.json`` (written last, atomically), ``config.toml``,
       ``provenance.json``, ``annotations.json``, ``trash.json``,
       ``fields.zarr/``, ``tables.parquet/`` and ``figures/``.
       ``sessions/<name>/`` with ``session.json`` and ``trials.jsonl``,
       written live by every calibration. ``share/`` for exports and
       reports. ``.hmp/`` for the index, logs, checkpoints, heartbeats,
       solver scratch and the ``gc`` quarantine. ``project.toml`` as the
       project-root marker. ``hmp catalog reindex``, which rebuilds the
       whole index from ``runs/`` and ``sessions/``. Point interrogation
       (``run.probe.series``, ``group.probe.series``,
       ``hmp catalog point``). Observation points declared in
       ``[observation]``, sampled by the run and persisted as
       ``tables.parquet/observation_points.parquet``. Run retention
       enforced by ``hmp catalog gc``.
   * - Removed
     - ``simulations/``, ``exports/``, ``figures/`` and ``reports/`` at
       the project root; ``.solver_scratch/``; ``catalog.duckdb`` at the
       project root; the ``.parquet.d`` and ``.zarr.zip`` container
       suffixes; the opaque ``<project>__<id8>`` storage basename; the
       adoption verb; the ``retention_policies`` table and the
       ``hmp audit prune`` verb, dropped together by migration ``0002``.
       ``tests/unit/results/test_run_layout_contract.py`` fails if any of
       the layout entries reappears.
   * - Not in place
     - A chunk layout tuned for point reads: a series at one cell still
       decompresses every chunk its time axis crosses. A per-run
       replacement for the project-wide ``hydromodpy.lock``. See
       `What is not in place`_.

Project layout
--------------

Layout of a project root, as written today:

.. code-block:: text

   <project>/
   |-- project.toml         canonical config, and the marker of the root
   |-- configs/             config variants (user-managed, never created)
   |-- hydromodpy.lock      reproducibility lockfile, best effort
   |-- runs/
   |   `-- <run_name>/      one directory per run (see below)
   |-- sessions/
   |   `-- <session_name>/  one directory per calibration session
   |-- share/               exports, reports and .hmp packages
   `-- .hmp/                disposable internals
       |-- index.duckdb     the index rebuilt from runs/ and sessions/
       |-- logs/            hydromodpy_debug.log
       |-- checkpoints/     resolved workflow manifests, for resume
       |-- running/         live-run heartbeat sidecars
       |-- scratch/         solver working directory
       `-- trash/           orphan stores and figures quarantined by gc

``runs/``, ``sessions/``, ``share/`` and ``.hmp/`` are ignored by git.

The project config file is ``project.toml``, and
:func:`~hydromodpy.core.state.paths.resolve_project_root` anchors on it,
never on a database file: a project stays a project after its index is
deleted. A workspace-level ``workspace.toml`` is optional metadata
written by ``hmp workspace init``; it carries no part of this contract.

``hydromodpy.lock`` is the one project-root entry the layout test does
not cover, because it is written by a run and not by the catalog. Its
per-run replacement does not exist yet.

The machine-wide ``index.duckdb`` lives at ``$XDG_STATE_HOME/hydromodpy/``
(``~/.local/state/hydromodpy/`` on Linux) and federates registered
**projects** through read-only ``ATTACH``. One row of its ``projects``
table is one project root, because a project root is what owns the
``.hmp/index.duckdb`` the federation attaches. A workspace root owns
none, so it is never a row: registering one expands it into the project
roots under its ``projects/`` directory, one row each, and a workspace
with no project registers nothing.

A run folder
------------

All paths relative to ``runs/<run_name>/``:

.. code-block:: text

   runs/<run_name>/
   |-- manifest.json        identity, geometry, artefacts. Written LAST
   |-- config.toml          exact resolved configuration, frozen
   |-- provenance.json      environment, git, solver, timing
   |-- annotations.json     tags and notes, written after the seal
   |-- trash.json           present only while the run sits in the trash
   |-- fields.zarr/         array store
   |-- tables.parquet/      tabular payloads
   `-- figures/             figures rendered for this run

Those names are the whole vocabulary: they are declared in
``hydromodpy/results/storage/contract.py`` and no other name is a run
artefact. A run folder holds results, never diagnostics: the pipeline log
stays under ``<project>/.hmp/logs/``, which is disposable, so nothing
sealed by the manifest can grow after the seal.

``manifest.json`` is written last, through a temporary file and a
rename. That single atomic write is the crash-safety mechanism: a run
directory without a manifest is incomplete by definition, and the
rebuild reports it instead of indexing it. The run is not staged
elsewhere and moved into place, because the Zarr store is created at
registration and appended to during the whole solve, which live readers
depend on.

The manifest carries five blocks (``run``, ``geometry``, ``period``,
``config``, ``artifacts``) plus the run's ``parameters`` and ``metrics``
summaries. ``geometry.catchment`` is the important one: the catchment
area and the outlet live there, and a discharge derived from runoff is
scaled by that area, so losing it yields a silently wrong series rather
than an error.

A session folder
----------------

A calibration session keeps its own directory under ``sessions/<name>/``,
named after the instant it started, its method and the first eight
characters of its identifier:

.. code-block:: text

   sessions/20260726-014233-optuna-3f2a1b7c/
   |-- session.json         identity, project, frozen search space,
   |                        objective, dates, status, best trial
   `-- trials.jsonl         one JSON object per trial, appended live

Both files are written **while the calibration runs**: the descriptor
before the first trial, one line per trial as it completes, and the
descriptor once more at the end with the outcome. An interrupted
calibration therefore keeps every trial it had time to evaluate, and
stays in the index as a ``running`` session with the trials it ran.

The format is declared by
``hydromodpy/results/session_journal.py``. It lives in ``results``, not
in ``calibration``, because the rebuild reads it and may not import the
``calibration`` layer. A trial number written twice is one trial written
twice: the last line wins, exactly like the upsert the index does on
``(session_id, iteration)``, so two rebuilds never duplicate a trial.

Spin-up sessions do not write a descriptor. A directory under
``sessions/`` without ``session.json`` is simply not a calibration, and
the rebuild reports it as skipped.

Naming and identity
-------------------

The directory under ``runs/`` **is** the run name, with its ``.vN``
version suffix. ``run_dirname`` folds accents to ASCII and replaces
characters a filesystem cannot carry; it preserves case, and it raises
``RunNameTooLongError`` rather than truncating a name past 96
characters. No output path anywhere carries the ``sim_id`` or its first
eight hex digits.

Name collisions follow the ``.vN`` grammar: a bare name is version one
for life, and the next run registered under the same stem becomes
``<stem>.v2`` in a sibling directory. Renaming a run moves its
directory, through the single ``StoragePathResolver.move`` call site, so
the index and the tree never disagree.

Trashing a run does not move bytes. It flips the index status and writes
``runs/<name>/trash.json``, which holds the name and status the run must
come back as. The marker is what makes the trash survive a rebuild: the
directory is the truth, so a rebuilt index finds the run trashed instead
of quietly resurrecting it. ``hmp catalog trash --empty`` is what
actually frees the bytes.

Three classes of data
---------------------

The classification is by consumer, not by table. It decides what must
exist on disk before the index can be thrown away. The authoritative
statement of the split is the module docstring of
``hydromodpy/results/catalog/reindex.py``, which is the code that
performs the rebuild.

Class 1: reconstructible
~~~~~~~~~~~~~~~~~~~~~~~~

Written into the run or session directory, and restored identically by
``hmp catalog reindex``.

.. list-table::
   :header-rows: 1
   :widths: 30 34 36

   * - Index table
     - Rebuilt from
     - Read by
   * - ``simulations``
     - ``tables.parquet/simulation.parquet``, with the name taken from
       the directory
     - catalog reads, ``hmp catalog ls`` and ``show``, comparison
   * - ``parameters``
     - ``tables.parquet/parameters.parquet``
     - ``results/catalog/discovery.py``, ``dataset_loader``, calibration
   * - ``metrics``
     - ``tables.parquet/metrics.parquet``
     - ranking, comparison, calibration reporting
   * - ``provenance``
     - ``tables.parquet/provenance.parquet``
     - input bridge (``run.input_entries()``), frozen replay
   * - ``geographic_features``
     - ``tables.parquet/geographic_*.parquet``
     - watershed and river figures
   * - ``geographic_metadata``
     - ``manifest.json``, ``geometry.catchment``
     - ``simulation/extraction/derivation/catchment_aggregation.py``
   * - ``runs_environment``
     - ``provenance.json``
     - ``results/export/context.py``, ``dataset_loader``, rerun
   * - ``tags``, ``sim_notes``
     - ``annotations.json``
     - tag search, ``gc`` pinning, spinup convergence gate
   * - ``tracked_files``
     - ``manifest.json``, ``inputs[]`` (path, ``sha256``, size, role)
     - ``entry.used_by()``, cache-to-run linking
   * - trash state
     - ``trash.json``
     - ``hmp catalog trash`` and ``restore``
   * - ``calibration_sessions``
     - ``sessions/<name>/session.json``
     - calibration resume, best promotion, calibration report
   * - ``calibration_iterations``
     - ``sessions/<name>/trials.jsonl``
     - calibration resume, calibration report

The frozen ``config.toml`` is not a table: it stays in the run directory,
and ``hmp run --resume <ref>`` replays it straight from there.
``hmp catalog rerun`` goes through ``simulations.config_snapshot``, which
comes back with ``simulation.parquet``. ``timeseries``, ``budgets``,
``mass_balance`` and ``observation_points`` are not tables either but
DuckDB views over the Parquet payloads, so they come back with the files
themselves.

Class 2: losable
~~~~~~~~~~~~~~~~

Not mirrored on disk. A rebuild drops them, by decision. Stating the
consequence is part of the contract.

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Index table
     - Consequence of a rebuild
   * - ``audit_log``
     - the machine event history of the project is lost. Run identity,
       results and lineage are unaffected because they come from the
       manifests. A fresh index writes one ``migrate`` row of its own.
   * - ``export_log``
     - the record of which artefacts were published under ``share/`` is
       lost. The artefacts themselves stay on disk.
   * - ``workflow_steps``, ``workflow_events``
     - the workflow journal is lost, so an interrupted workflow replans
       from scratch instead of resuming. The resolved manifests under
       ``.hmp/checkpoints/`` are disposable for the same reason.
   * - ``calibration_iterations.sim_id``
     - promotion back-fills that column in the index after the trial is
       journalled. The session keeps its ``best_sim_id`` and each
       promoted run keeps its ``calibration:<session>`` tag on disk, so
       the session-to-run link survives in both directions.
   * - ``deletions``, ``purge_journal``
     - tombstones and purge resume state are lost. An interrupted hard
       purge is not replayed; the leftover directory becomes an orphan
       that ``gc`` reports.

Three bookkeeping columns have no home on disk:
``runs_environment.recorded_at``, ``tracked_files.recorded_at`` and
``provenance.valid_from``. The rebuild dates them from the seal time of
their run (``manifest.json``, ``sealed_at``) rather than from the wall
clock, so a rebuild stays reproducible instead of stamping itself into
the data.

Class 3: input
~~~~~~~~~~~~~~

Observation series and station metadata (``stations``, ``observations``)
are input data. They are repopulated from their source, that is the
workspace input cache and the data loaders, exactly like a DEM or a
climate series. A results rebuild never tries to recreate them and never
treats their absence as a corrupted run.

Tables outside the three classes are the static dimension tables seeded
by the DDL (``solvers``, ``statuses``, ``flow_regimes``,
``mesh_topologies``, ``metric_definitions`` and the ``dim_*`` tables). A
rebuild recreates them from the DDL.

Contract coverage
-----------------

``hydromodpy/results/storage/contract.py`` is the machine-readable half.
It declares the three physical layers (``catalog``, ``zarr``,
``parquet``) with their path templates, and every file name a run or
session directory may carry. Path builders, exporters and this page
share that one vocabulary.

.. list-table::
   :header-rows: 1
   :widths: 26 30 44

   * - Area
     - Path
     - Rule
   * - Index
     - ``.hmp/index.duckdb``
     - one per project, rebuildable, never at the project root
   * - Run folders
     - ``runs/<name>/``
     - one directory per run, named after the run, every file declared
       in the manifest
   * - Sessions
     - ``sessions/<name>/``
     - one directory per calibration session, descriptor plus trials
       journal
   * - Exchange
     - ``share/<label>/``
     - configured exports, reports and ``.hmp`` packages
   * - Technical cache
     - ``.hmp/``
     - index, logs, checkpoints, heartbeats, scratch, quarantine.
       Entirely regenerable, safe to delete
   * - Project configuration
     - ``project.toml`` plus ``configs/``
     - the canonical config and its variants

Tested invariants
~~~~~~~~~~~~~~~~~

- **Layout.** ``tests/unit/results/test_run_layout_contract.py`` asserts
  that one solved run produces exactly one directory named after the
  run, that the tabular payloads are plain ``.parquet`` files in one
  directory, that the project root grows none of the removed entries,
  that no output path carries an opaque identifier, and that no path
  ends in ``.parquet.d`` or ``.zarr.zip``.
- **Naming.** ``tests/unit/results/test_result_storage_layout.py`` pins
  the layer templates, refuses an over-long name instead of truncating
  it, and checks a versioned rerun lands in a sibling directory.
- **Rebuild.** ``tests/unit/results/test_reindex.py`` covers
  coverage (every sealed run on disk is indexed, an unsealed one is
  reported and left out, a manifest naming another run is refused),
  sufficiency (what execution reads back is restored, the frozen config
  stays readable, a trashed run stays trashed), idempotence (two
  rebuilds produce the same index), and atomicity (the previous index
  survives a failed rebuild, a reader keeps reading across the swap).

Per-run Zarr store
------------------

Zarr **format 3** store, carrying HydroModPy's own
``zarr_schema_version = "2"`` in its root attributes. The store is staged
and promoted to its final path with a rename at registration, then
appended to in place for the whole solve, under a cross-process file
lock. It is not staged again at the end, because live readers follow that
path while the run is solving, and there is no packed form: a container
suffix would break those readers.

.. code-block:: text

   runs/<name>/fields.zarr/
   |-- zarr.json     root attributes (ACDD) and consolidated metadata
   |-- meta/         schema and store-level metadata
   |-- mesh/         topology, cell types, coordinates, thicknesses
   |-- state/        solver state fields
   |-- forcing/      recharge and other forcings
   |-- particles/    particle trajectories
   |-- derived/      created only when a derived field is opted in
   |-- budget/       created only when budget.spatial_fields is on
   |-- geographic/   created on demand for the geographic rasters
   |-- head          root array, (time, layer, cell)
   |-- time          root array, the CF time axis
   `-- crs           root array, the CF grid mapping

``meta``, ``mesh``, ``state``, ``particles`` and ``forcing`` are created
at store init. ``derived``, ``budget`` and ``geographic`` are not
pre-created: heavy fields are opt-in
(``[simulation.results.derived]`` and
``[simulation.results.budget] spatial_fields``), so a default run carries
neither group and the lumped budget still feeds the catchment scalars.

Compression defaults to Blosc-zstd with bitshuffle, each variable carries
CF ``standard_name`` and ``_FillValue`` attributes where the CF table has
one, consolidated metadata is written at the root, and solver sentinel
values are masked to NaN at write time. Chunks target about 1 MiB.
Sharding switches on when a variable's total footprint
(``n_timesteps * layer_bytes_per_step``) exceeds 100 MiB, with shards
capped near 64 MiB.

Per-run Parquet directory
-------------------------

Parquet format ``2.6`` written through ``write_table_atomic`` (temporary
file plus ``os.replace``) with ZSTD level 5, 50 000-row groups, page
index and bloom filters on the primary-key columns where the linked
pyarrow build supports them. Each file carries
``hmp.schema_version = "v2"`` plus its schema name, primary key and the
run's identity in Parquet key-value metadata, and is exposed as a DuckDB
view named after the payload.

The container directory is ``tables.parquet/`` and the payloads inside
are plain ``.parquet`` files. No suffix marks a container.

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Payload
     - Content
   * - ``simulation.parquet``
     - one-row snapshot of the run's index entry, read by ``reindex``
   * - ``parameters.parquet``
     - the run parameters, one row each
   * - ``metrics.parquet``
     - ``sim_id``, ``station_id``, ``variable``, ``metric``, ``value``,
       ``n_samples``, validity window
   * - ``timeseries.parquet``
     - ``sim_id``, ``station_id``, ``variable``, ``datetime``,
       ``value``, ``unit``, ``qflag``
   * - ``budgets.parquet``
     - ``sim_id``, ``timestep``, ``zone_id``, ``component``,
       ``flux_in``, ``flux_out``, ``unit``
   * - ``mass_balance.parquet``
     - ``sim_id``, ``timestep``, ``total_in``, ``total_out``,
       ``storage_in``, ``storage_out``, ``percent_error``
   * - ``observation_points.parquet``
     - ``sim_id``, ``station_id``, ``x``, ``y``, ``cell_id``, ``layer``,
       ``crs_wkt``, ``crs_epsg``: the points declared in ``[observation]``
   * - ``provenance.parquet``
     - input provenance rows of the run
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
   :widths: 24 18 58

   * - Table
     - Class
     - Key columns
   * - ``simulations``
     - reconstructible
     - ``sim_id`` (UUID), ``name``, ``name_stem``, ``version_int``,
       ``original_name``, ``project``, ``solver_id``, ``status_id``,
       ``mesh_hash``, ``n_cells``, ``n_layers``, ``n_timesteps``,
       ``crs_wkt``, ``bbox_*``, ``period_start/end``,
       ``config_snapshot``, ``config_hash``, ``zarr_path``,
       ``storage_basename``, ``trashed_at``, ``duration_s``
   * - ``parameters``
     - reconstructible
     - ``sim_id``, ``param_name``, ``zone_id``, ``value``, ``unit``,
       ``parameterization``
   * - ``metrics``
     - reconstructible
     - ``sim_id``, ``station_id``, ``metric_name``, ``value``,
       ``n_samples``
   * - ``provenance``
     - reconstructible
     - ``sim_id``, ``variable``, ``source_type``, ``source_ref``,
       ``source_sha256``, ``payload_sha256``, ``fetched_at``,
       ``n_records``
   * - ``runs_environment``
     - reconstructible
     - ``sim_id``, ``python_version``, ``hydromodpy_version``,
       ``platform``, ``git_commit``, ``solver_binary_sha256``,
       ``env_packages``, ``rng_seed``
   * - ``geographic_metadata``
     - reconstructible
     - ``sim_id``, ``key``, ``value``. Holds the catchment area and
       outlet coordinates used by catchment aggregation
   * - ``geographic_features``
     - reconstructible
     - ``sim_id``, ``feature_name``, ``geometry_kind``,
       ``geoparquet_path``
   * - ``tags``, ``sim_notes``
     - reconstructible
     - ``sim_id``, ``tag`` / ``note``. Mirrored in ``annotations.json``
   * - ``calibration_sessions``
     - reconstructible
     - ``session_id``, ``project``, ``method``, ``objective_name``,
       ``n_iterations``, ``best_sim_id``, ``status_id``
   * - ``calibration_iterations``
     - reconstructible
     - ``session_id``, ``iteration``, ``sim_id``, ``params_hash``,
       ``parameters`` (JSON), ``objective_value``
   * - ``tracked_files``
     - reconstructible
     - ``sim_id``, ``role``, ``category``, ``original_path``,
       ``canonical_path``, ``sha256``, ``size_bytes``, from the
       ``inputs[]`` block of ``manifest.json``
   * - ``workflow_steps``, ``workflow_events``
     - losable
     - workflow journal: ``step_id``, ``run_id``, ``step_name``,
       ``status_id``, ``started_at``, ``ended_at``, ``payload``
   * - ``audit_log``, ``export_log``, ``deletions``, ``purge_journal``
     - losable
     - machine event history, export bookkeeping, tombstones, purge
       resume state
   * - ``stations``, ``observations``
     - input
     - station metadata and observation series, repopulated from the
       input cache
   * - ``solvers``, ``statuses``, ``flow_regimes``,
       ``mesh_topologies``, ``dim_*``, ``metric_definitions``
     - dimension
     - static vocabularies seeded by the DDL
   * - ``schema_migrations``
     - dimension
     - one row per applied migration: ``version``, ``component``,
       ``slug``, ``checksum``, ``applied_at``

``observation_points`` has no row here on purpose: the declaration lives
in the run directory and is exposed as a Parquet-backed view, which is
what makes it survive a rebuild. ``retention_policies`` is gone;
migration ``0002`` dropped it together with the ``hmp audit prune`` verb,
because a per-event-type age sweep deletes rows from the middle of the
``audit_log`` hash chain and would break ``hmp audit verify``
permanently.

Views. ``v_workflow_heartbeats`` comes from the DDL.
``v_simulation_summary`` (the view the machine index federates),
``v_best_per_project``, ``v_metrics_wide``, ``v_params_long`` and
``v_params_wide`` are created at runtime by
``hydromodpy/results/catalog/views.py``. ``timeseries``, ``budgets``,
``mass_balance``, ``observation_points``, ``metrics_parquet`` and
``provenance_parquet`` are views over the run's Parquet payloads,
declared once in ``PARQUET_VIEW_NAMES``
(``hydromodpy/results/catalog/constants.py``).

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
  when it is created.
- Parquet writes use a temporary file plus ``os.replace``.
- ``manifest.json``, ``provenance.json``, ``annotations.json`` and
  ``trash.json`` are written the same way: temporary file, then rename.
- A solving run refreshes a heartbeat sidecar under ``.hmp/running/`` so
  ``hmp catalog watch`` and ``hmp catalog gc`` read liveness from a file
  rather than from a database a live solve holds locked.
- ``hmp catalog reindex`` fills a staging database next to the index
  and installs it with one atomic rename (``_publish`` in
  ``hydromodpy/results/catalog/reindex.py``, the only publishing path).
  The invariant is that ``index.duckdb`` is never absent nor
  half-written: a reader that was reading keeps reading the file it
  opened, and the next opener gets the rebuilt one. ``os.replace``
  delivers exactly that on POSIX. Windows refuses it with
  ``PermissionError`` as soon as another handle is on the index,
  because ``MoveFileEx`` deletes the target eagerly, so the same rename
  is asked of the kernel there through ``SetFileInformationByHandle``
  with ``FILE_RENAME_INFO_EX`` and ``FILE_RENAME_POSIX_SEMANTICS``,
  which unlinks the target from its directory instead of deleting it.
  Both ends are one atomic rename; there is no non-atomic fallback.
  Where the kernel supports neither (below Windows 10 1709, or a volume
  that is not NTFS) the rebuild fails and says so: the previous index is
  untouched and still readable, and the fix is to close the processes
  reading the project and rebuild again.

Lockfile and reproducibility
----------------------------

``hydromodpy.lock`` is written best-effort at the project root when the
run can reach the workspace input cache. It is written atomically and
pins:

- the ``hydromodpy`` version, git commit, Python version and config
  schema fingerprint;
- the solver binaries with their SHA-256 and version text;
- the catalog, Zarr and Parquet schema versions;
- input fingerprints (relative path, SHA-256, size, fetch date).

``hmp run --frozen`` refuses any source whose fingerprint changed since
the lockfile was written; ``hmp run --no-lock`` skips the post-run write.
When no input cache is available, a normal run may complete without a
lockfile; that is a reproducibility warning, not a failed run.

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

``hmp catalog export <ref> -o run.hmp`` bundles the run seal (manifest,
provenance, frozen config), a one-simulation DuckDB snapshot and the
Zarr and Parquet stores into one ``tar.zst`` archive with a SHA-256 per
file; several references produce a single multi-run container. The Zarr
store is packed to ``fields.zarr.zip`` **inside the archive only**, and
import unpacks it back to a directory store, so nothing on disk ever
stays zipped. Without ``-o`` the archive lands in the current directory,
named after the run. A run whose config enables ``[export] package``
writes its archive under ``share/<label>/`` instead.
``hmp catalog import run.hmp`` verifies the magic and every checksum,
then re-materialises the runs in the target project.

Reading one cell
----------------

A finished run answers for one precise cell, after the fact.
``hydromodpy/results/run/point.py`` binds the point-to-cell lookup
(``results/spatial_index``) and the on-the-fly derivations
(``results/derive/virtual_fields``) to a run, and exposes the gesture as
``run.probe.series`` and ``group.probe.series``. The cell is named by
project-CRS coordinates, by its zero-based index, or by a depth in
metres below the local model top that picks the layer. A virtual field
(``watertable_depth`` ...) answers exactly like a persisted one, so a
map read and a point read can never disagree.

.. code-block:: python

   run.probe.series("head", x=352000.0, y=6789000.0)
   run.probe.series("watertable_depth", cell=1204, timestep=-1)
   group.probe.series("head", x=352000.0, y=6789000.0, depth=12.5)

The answer is a long-format table (``run``, ``sim_id``, ``variable``,
``timestep``, ``time``, ``value``, ``unit``, ``cell``, ``layer``, ``x``,
``y``), which makes the multi-run form a plain concatenation ready for a
scenario comparison. The same reader backs the CLI:

.. code-block:: bash

   hmp catalog point @last --var head --xy 395100 6824925
   hmp catalog point @last --var head --cell 5000 --timestep -1
   hmp catalog point run_a run_b --var watertable_depth --cell 5000 -o point.csv

A persisted field is sliced in a single Zarr call
(``array[:, layer, cell]``), so the series costs one decompression pass
over the touched chunks instead of one per timestep. A virtual field is
rebuilt timestep by timestep and reduced to the cell right away, so
memory stays at one field.

Declared observation points
---------------------------

A location known before the run is declared in ``[observation]`` rather
than interrogated afterwards:

.. code-block:: toml

   [observation]
   variables = ["head", "watertable_depth"]

   [[observation.points]]
   id = "piezo_amont"
   x = 395100.0
   y = 6824925.0
   depth = 12.5

Each point names ``x``, ``y`` and either ``layer`` or ``depth``, and may
override the section-level ``variables``. ``ObservationConfig``
(``hydromodpy/simulation/planning/observation_config.py``) validates the
ids and the vertical selector; the run samples the points at the end of
extraction, while it still holds its fields
(``simulation/extraction/post_run.py``,
``sample_declared_observation_points``). A declaration mistake is logged
and skipped: it must not lose a run whose results are already in.

Both halves of a declared point are run artefacts. The series lands in
``tables.parquet/timeseries.parquet`` under the station id
``obs:<point id>``, so a declared probe never collides with a solver
station (gauge, SFR reach, lake). The declaration itself lands in
``tables.parquet/observation_points.parquet`` and is exposed as a
Parquet-backed view, so ``hmp catalog reindex`` finds it again with the
files. This is not ``[data.piezometry]``: that section loads *measured*
series, this one declares *where the model is read*.

Retention and garbage collection
--------------------------------

``hmp catalog gc`` is the single maintenance verb, and it plans by
default: nothing moves without ``--apply``. Nothing is destroyed on the
spot either. The rules are ``RetentionPolicy`` in
``hydromodpy/cli/_workers/catalog.py``:

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Rule
     - Behaviour
   * - ``keep_versions`` (default 5)
     - Keeps the newest versions of one lineage (``name_stem``) and
       trashes the rest. ``--keep-versions all`` disables the rule.
   * - ``max_age_days`` (default off)
     - Trashes runs created more than N days ago. Opt-in through
       ``--max-age-days``.
   * - ``purge_figures`` (default off)
     - Quarantines the regenerable ``figures/`` directory of each run.
   * - ``pinned`` tag
     - ``PROTECTED_TAG``: a run carrying it is exempt from every rule.

A selected run goes to the project trash, a reversible status flip
stamped on disk as ``runs/<name>/trash.json`` and undone by
``hmp catalog restore``. Orphan stores and swept figures are moved to
``<project>/.hmp/trash/<stamp>/``. Bytes are freed later by the trash
expiry rule: a trashed, non-pinned run older than
``TRASH_RETENTION_DAYS`` (30) is listed as ``expired_trash``. The same
sweep also replays interrupted purges, marks stale running runs failed,
drops orphan geographic caches and tmp Parquet files, checkpoints the
DuckDB files and consolidates Zarr metadata (the absorbed ``vacuum``
verb). Every applied sweep writes one ``gc`` row in the project audit
log.

What is not in place
--------------------

Stated here so that nothing above is read as a promise.

- **A chunk layout tuned for point reads.** Chunks are sized for map
  reads: about 1 MiB each, and a whole timestep sits in one chunk as long
  as it fits that budget
  (``hydromodpy/results/zarr_store/chunks.py``). Reading one cell across
  time is a single Zarr call, but it decompresses every chunk the time
  axis crosses, so a point series pays for the neighbouring cells it
  never uses. Making that read cheap needs a cell-major layout, or a
  second copy laid out that way, and neither is written today.
- **A per-run lockfile.** ``hydromodpy.lock`` sits at the project root
  and describes the whole project's input cache. A run seals its own
  inputs in ``manifest.json`` (``inputs[]``), but there is no per-run
  lockfile, so replaying one old run still reads a project-wide file
  that a later run may have rewritten.

See also
--------

- :doc:`overview/two-databases` for the role of each database scope.
- :doc:`overview/schema-evolution` for the migration policy.
- :doc:`artifact-policy` for non-canonical artefacts and sidecars.
- :doc:`/architecture/packages/results` for the Python API on top of
  this storage (``Catalog``, ``Run``, ``RunSet``, ``hmp.read``).
- :doc:`/architecture/packages/data` for the input cache writer.
