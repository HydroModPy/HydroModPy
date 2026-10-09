Storage layout
==============

**Disk is the truth. The database is an index rebuilt from disk.**

A project keeps its results as ordinary directories, one per run. The DuckDB file under
``.hmp/`` is a query index over those directories: it makes ``ls``, ``show``, metric ranking
and cross-project federation fast, and it can be deleted and rebuilt with
``hmp catalog reindex``. Nothing a run needs in order to be read, replayed, resumed or compared
may live only in SQL.

This page is the storage contract: the rules, not the file lists. The tree of a project, a run
and a session, the Zarr groups, the Parquet payloads and the index schema are generated from the
code in :doc:`generated/storage-tree`. For the role of each database scope and the migration
policy, see :doc:`data-scopes`.

Project layout
--------------

A project root holds ``project.toml`` (the canonical config and the marker of the root),
``configs/`` (config variants, user-managed, never created), ``hydromodpy.lock``, ``runs/``
(one directory per run), ``sessions/`` (one per calibration session), ``share/`` (exports,
reports and ``.hmp`` packages) and ``.hmp/``. The ``.hmp/`` folder is disposable: the index
(``index.duckdb``), the logs, the resolved workflow manifests used for resume, the heartbeats of
live runs, the solver scratch and the ``gc`` quarantine.

These entries do not exist: ``simulations/``, ``exports/``, ``figures/`` and ``reports/`` at the
project root, ``.solver_scratch/``, ``catalog.duckdb`` at the project root, the ``.parquet.d``
and ``.zarr.zip`` container suffixes, and an id-based directory name. The ``retention_policies``
table and the ``hmp audit prune`` verb are gone, dropped together by migration ``0002``.
``tests/unit/results/test_run_layout_contract.py`` fails if a removed entry reappears.

``runs/``, ``sessions/``, ``share/`` and ``.hmp/`` are ignored by git.

Each run, or each calibration session with its trials, phases and
promotions, works in its own ``.hmp/scratch/<config>.p<pid>/``: its
preprocessing, its solver folders and the recharge its trials share.
Several runs of one project therefore run at once without reading each
other's files, and a run that ends sweeps only its own folder. A child
process inherits its parent's folder through ``HMP_RUN_SCRATCH``, and the
next run of the project removes the folders of runs whose process was
killed (:func:`~hydromodpy.core.state.paths.run_scratch`).

The project config file is ``project.toml``, and
:func:`~hydromodpy.core.state.paths.resolve_project_root` anchors on it,
never on a database file: a project stays a project after its index is
deleted. A workspace-level ``workspace.toml`` is optional metadata
written by ``hmp workspace init``; it carries no part of this contract.
A run sealed without ``creator_name``, ``creator_institution`` or a known
licence warns once per workspace. ``.hmp/identity_notice.json``, beside
``workspace.toml`` or at the project root when there is none, records the
warning, and later runs report the gap at ``--verbose`` only. Deleting the
file brings the warning back once.

``hydromodpy.lock`` is a declared project-root entry, covered by
``test_the_reproducibility_lock_is_a_declared_project_entry`` in
``tests/unit/results/test_run_layout_contract.py``. It is an input of the
project, like ``project.toml`` and ``configs/``, not an output of a run.

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

A run folder holds ``manifest.json`` (identity, geometry, artefacts, written last),
``config.toml`` (the exact resolved configuration, frozen), ``provenance.json`` (environment,
git, solver, timing), ``annotations.json`` (tags and notes, written after the seal),
``trash.json`` (only while the run sits in the trash), ``fields.zarr/``, ``tables.parquet/`` and
``figures/``.

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

It holds ``session.json`` (identity, project, frozen search space, objective, dates, status,
best trial), ``trials.jsonl`` (one JSON object per trial, appended live) and, when
``persist_trial_series = true``, one ``trial_series/trial-NNNNNN.parquet`` per trial.

Both ``session.json`` and ``trials.jsonl`` are written **while the
calibration runs**: the descriptor before the first trial, one line per
trial as it completes, and the descriptor once more at the end with the
outcome. An interrupted calibration therefore keeps every trial it had
time to evaluate, and stays in the index as a ``running`` session with
the trials it ran.

The format is declared by
``hydromodpy/results/session_journal.py``. It lives in ``results``, not
in ``calibration``, because the rebuild reads it and may not import the
``calibration`` layer. A trial number written twice is one trial written
twice: the last line wins, exactly like the upsert the index does on
``(session_id, iteration)``, so two rebuilds never duplicate a trial.

``trial_series/`` is opt-in and only ever grown by completed trials, one
Parquet file per trial, named ``trial-NNNNNN.parquet`` so the directory
sorts by trial number. It carries the per-trial detail ``trials.jsonl``
does not: a point/series output's simulated and observed values at its
own scored timestamps (``trial``, ``output``, ``station``, ``time``,
``simulated``, ``observed``), tables only, never ``fields.zarr``. It is
not part of the index; ``hydromodpy.results.session_journal.
read_trial_series`` reads it straight off disk. Network and spatial
outputs are never written there, since their cost is already a scalar
in ``trials.jsonl``. The switch is :toml:`calibration.persist_trial_series`.

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

**A run directory name is unique in the catalog, not in the project.** A
catalog owns exactly one ``runs/`` tree and no path carries the project,
so ``project`` is a label on a row and never a path segment: two projects
registered in one catalog that pick the same run name get one directory
each, the second versioned to ``<stem>.v2``. The column that carries the
invariant is ``storage_basename``, the directory name itself, under the
``ux_sim_storage_basename`` unique index; ``name`` cannot, since two
different names can fold to one directory. ``if_exists`` decides which
run gets displaced, and that stays a question about the caller's
project: ``replace`` never trashes a neighbour project's run because the
two picked the same word. ``fail`` is the exception and it is deliberate:
it exists to forbid a substitute name, so it refuses on any occupied
directory, whatever the project holding it and whether that run is live
or trashed.

Trashing a run does not move bytes. It flips the index status and writes
``runs/<name>/trash.json``, which holds the name and status the run must
come back as. The marker is what makes the trash survive a rebuild: the
directory is the truth, so a rebuilt index finds the run trashed instead
of quietly resurrecting it. ``hmp catalog trash --empty`` is what
actually frees the bytes. Trashing frees the name in the index and not
on disk, so a newcomer asking for the name of a trashed run is versioned
behind it rather than landing in its directory.

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
``hmp catalog reindex``: the run identity and parameters, the metrics, the input provenance, the
geographic features, the catchment metadata, the run environment, the tags and notes, the trash
state, the tracked input files, and the calibration sessions and trials. The table of what is
rebuilt from which file is in the module docstring of
``hydromodpy/results/catalog/reindex.py``, which is the code that does it.

The frozen ``config.toml`` is not a table: it stays in the run directory,
and ``hmp run --resume <ref>`` replays it straight from there.
``hmp catalog rerun`` goes through ``simulations.config_snapshot``, which
comes back with ``simulation.parquet``. ``timeseries``, ``budgets``,
``mass_balance``, ``observation_points``, ``sfr_reaches`` and
``soil_budget`` are not tables either but DuckDB views over the Parquet
payloads, so they come back with the files themselves.

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

``hydromodpy/results/storage/contract.py`` is the machine-readable half. It declares the three
physical layers (``catalog``, ``zarr``, ``parquet``) with their path templates, and every file name
a run or session directory may carry. Path builders, exporters and this page share that one
vocabulary.

Tested invariants
~~~~~~~~~~~~~~~~~

- **Layout.** ``tests/unit/results/test_run_layout_contract.py`` asserts
  that one solved run produces exactly one directory named after the
  run, that the tabular payloads are plain ``.parquet`` files in one
  directory, that the project root grows none of the removed entries,
  that no output path carries an opaque identifier, and that no path
  ends in ``.parquet.d`` or ``.zarr.zip``.
  ``test_the_soil_budget_is_a_plain_parquet_file_of_the_run`` checks the
  same for ``soil_budget.parquet``.
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

The groups are ``meta``, ``mesh`` (topology, cell types, coordinates, thicknesses, routing
descent), ``state`` (solver state fields), ``forcing`` (recharge and other forcings, and
``forcing/soil/`` in soil mode), ``particles``, ``derived``, ``budget`` and ``geographic``, and the
root arrays ``head``, ``time`` and ``crs`` (plus ``quantization_info`` when a field is rounded).
The generated :doc:`generated/storage-tree` lists them.

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

**Precision.** ``[simulation.results.persistence] field_precision`` sets how
the time-varying fields are kept: every array written through
``write_field`` or ``write_field_stack`` (head, per-cell budget terms,
stored derived fields, concentrations). ``compact``, the default, stores
float32 whose mantissa is rounded to nearest at 16 bits
(:mod:`hydromodpy.core.field_precision`): a value moves by at most 2**-17
of itself, 7.6e-6 relative, NaN stays NaN and no finite value becomes
infinite. The zeroed low bits are what bitshuffle and zstd pack away. Such
an array carries the CF-1.11 quantization attributes
``quantization = "quantization_info"`` and ``quantization_nsb = 16``, and
the root holds the ``quantization_info`` container with
``algorithm = "bitround"``. ``exact`` stores float64 as computed. Mesh
geometry, vertices, connectivity, topography, layer thickness, z
interfaces, static parameter fields, indices, coordinates and timestamps
are never rounded. Every library reader returns float fields as float64
whichever precision the store holds.

**Fields rebuilt on read.** ``release_flux`` and ``fluxes_from_budget`` are
not stored: the readers rebuild them from the per-cell budget terms
(:mod:`hydromodpy.results.derive.virtual_fields`) with the function that
used to compute them before writing, so a step read equals the step that
would have been stored. ``[simulation.results.derived] release_flux`` keeps
its meaning, making the field available: it turns the per-cell budget on
and keeps the terms the field is built from when the rest of that budget is
dropped as an intermediate. A store written before holds
``derived/release_flux`` and ``derived/fluxes_from_budget`` in float64, and
every reader returns the stored array first, so it reads as it always did.

Neither change bumps ``zarr_schema_version``: the layout, the names, the
shapes and the meaning of every stored array are unchanged, the float width
is declared by each array's own Zarr metadata, and both an old store and a
new one read the same through every reader.

**Routing descent.** A MODFLOW 6 or MODFLOW-NWT run stores the descent D it was built with under
``mesh/``, one value per face and none rounded: ``descent_receiver``, ``descent_surface``, the
masks ``descent_base_level``, ``descent_constant_head``, ``descent_raised``, ``descent_channel``
and ``descent_pinned``, and the list ``descent_dam_foot``. The attributes of ``descent_receiver``
name the neighbourhood and carry the build report. The solver build leaves D in the solver folder
as ``<model>.descent.npz`` and the extractor copies it into the store right after the mesh.
``run.descent`` reads it back, and the flow direction map and ``accumulation_flux`` route on it
(the contract of D is in :doc:`solver/backends`). Boussinesq has no mesh connectivity and stores
none. The arrays are new datasets, so ``zarr_schema_version`` does not change. A run sealed
before D was stored has no ``descent_*`` array, and its readers rebuild D from the stored top,
with no channel pin, no constant-head seed and no lake.

**Soil reservoir.** A run whose recharge comes from
``[flow.sinks_sources.recharge.soil]`` writes its daily columns under
``forcing/soil/``: ``etr``, ``residual_etp``, ``recharge`` and ``runoff`` in
mm/day, ``soil_storage`` and ``transit_storage`` in mm at the end of the day,
plus the position and capacity of each column (``cell_index``,
``class_index``, ``x``, ``y``, ``ru_mm``, ``cell_fraction``,
``basin_weight``). Two axes carry it, ``record`` and the new
``soil_column``, and every array is float64: these are daily forcing inputs,
not a solved field, so ``field_precision`` never quantizes them. The recharge
grid MODFLOW receives is written the same way a SIM2 recharge would be, as
``forcing/recharge_recharge``: soil mode never opens a ``forcing/recharge/``
group.

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

The payloads are ``simulation``, ``parameters``, ``metrics``, ``timeseries``, ``budgets``,
``mass_balance``, ``observation_points``, ``sfr_reaches`` (the resolved SFR reach geometry, the
only record of which cell carries which reach, absent when the run built no stream network),
``soil_budget`` (one row per soil column and calendar year, absent outside soil mode),
``provenance`` and the GeoParquet 1.1 layers ``geographic_*``. Their columns are generated in
:doc:`generated/storage-tree`.

Project index DuckDB schema
---------------------------

The authoritative DDL is ``hydromodpy/results/catalog/migrations/``, and the generated
:doc:`generated/storage-tree` lists the tables with their class (reconstructible, losable, input
or dimension) as defined above.

``observation_points`` has no table on purpose: the declaration lives
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
``mass_balance``, ``observation_points``, ``metrics_parquet``,
``provenance_parquet``, ``sfr_reaches`` and ``soil_budget`` are views over
the run's Parquet payloads, declared once in ``PARQUET_VIEW_NAMES``
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
registry. See :doc:`/contribute/architecture/packages/results` for the Python
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

Portable ``.hmp`` packages
--------------------------

``hmp export <ref> all --format package`` bundles the run seal (manifest,
provenance, frozen config), a one-simulation DuckDB snapshot and the
Zarr and Parquet stores into one ``tar.zst`` archive with a SHA-256 per
file. The Zarr store is packed to ``fields.zarr.zip`` **inside the archive
only**, and import unpacks it back to a directory store, so nothing on disk
ever stays zipped. The archive lands in ``share/<run>/<run>.hmp`` unless
``--folder`` or ``--file`` names another place. A run whose config holds an
``[[export]]`` block with ``format = "package"`` writes the same archive at
the end of the run, after the seal. ``Catalog.export_package_multi`` still
writes a multi-run container from Python; no verb exposes it.
``hmp catalog import run.hmp`` verifies the magic and every checksum,
then writes the runs into the project you import to.

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

Known limit
-----------

**The Zarr chunk layout is tuned for map reads.** Chunks are about 1 MiB each, and a whole
timestep sits in one chunk as long as it fits that budget
(``hydromodpy/results/zarr_store/chunks.py``). Reading one cell across time is a single Zarr
call, but it decompresses every chunk the time axis crosses, so a point series pays for the
neighbouring cells it never uses. A cell-major layout, or a second copy laid out that way, would
make it cheap, and neither exists.

A per-run lockfile is settled, not missing. ``hydromodpy.lock`` pins the project's whole input
cache before a run starts, and its only readers are ``hmp run --frozen``,
``hmp data add --frozen`` and ``hmp dev lock verify``. The per-run input list lives in
``manifest.json`` (``inputs[]``), sealed when the run ends, so a replay never depends on the
project-wide file.

See also
--------

- :doc:`data-scopes` for the role of each database scope, the migration policy and the
  non-canonical artefacts.
- :doc:`generated/storage-tree` for the tree and the schema.
- :doc:`/contribute/architecture/packages/results` for the Python API on top of
  this storage (``Catalog``, ``Run``, ``RunSet``, ``hmp.read``).
- :doc:`/contribute/architecture/packages/data` for the input cache writer.
