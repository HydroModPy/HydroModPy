Storage layout
==============

**Disk is the truth. The database is an index rebuilt from disk.**

A project keeps its results as ordinary directories: one per run, one per calibration session.
The DuckDB file under ``.hmp/`` is a query index over those directories. It makes ``ls``,
``show`` and metric ranking fast, and it can be deleted and rebuilt with
``hmp catalog reindex``. Nothing a run needs in order to be read, replayed, resumed or compared
lives only in SQL.

This page is the storage contract: the rules and the names. The Zarr groups, the Parquet
payloads and the index schema are generated from the code in :doc:`generated/storage-tree`.
For the role of each database scope, see :doc:`data-scopes`.

The placement rule
------------------

**An artefact is written in the directory of what produced it, under a fixed name per class.
There is no other destination inside a project.** A figure of a run is in that run, a report
of a session is in that session, a table over N cases is in ``summary/``. Publishing is a copy
out of the tree (``hmp publish``); nothing in the project points at the copy except the
``published.jsonl`` line of its source.

The directory names of the project are declared in :mod:`hydromodpy.core.state.paths`. The names
inside a run or a session directory are declared in :mod:`hydromodpy.results.storage.contract`.
No other module spells them.

Project layout
--------------

A project with one catchment, two runs and a calibration:

.. code-block:: text

   <project>/
   ├── project.toml            the configuration and the marker of the project root
   ├── README.md               written by the author, never rewritten
   ├── daily.toml              a variant, base_config = "project.toml"
   ├── calibration.toml        base_config = "project.toml" + [calibration]
   ├── hydromodpy.lock         pin of the workspace input cache
   ├── runs/
   │   ├── baseline/           hmp run project.toml
   │   ├── baseline.v2/        hmp run project.toml --set flow.param.K.field.value=2e-5
   │   ├── daily/              hmp run daily.toml
   │   └── calibration/        the promoted best trial of sessions/calibration
   ├── sessions/
   │   └── calibration/        hmp calibrate calibration.toml
   ├── trash/                  runs and sessions deleted by a move; tombstones.txt
   └── .hmp/                   rebuildable: index.duckdb, logs/, mesh_cache/

A project of N catchments declares ``[sites]`` and a table of sites; each case is a site crossed
with a recipe, named ``<site>-<recipe>``:

.. code-block:: text

   <project>/
   ├── project.toml            [sites] instead of [site]
   ├── README.md
   ├── sites.csv               one row per site: site, label, gauge, x_outlet, y_outlet, ...
   ├── site_overrides/         one ordinary TOML per site, read when present
   ├── k2e-5.toml              a recipe
   ├── calage.toml             a recipe with [calibration]
   ├── hydromodpy.lock
   ├── plan/
   │   ├── current             text: the hash of the plan in force
   │   └── a3f9c2e1/           plan.json, sites.parquet, cases.parquet, <case>.toml
   ├── runs/
   │   ├── J0014010-base/
   │   ├── J0014010-k2e-5/
   │   ├── J0014010-calage/    promoted run of the calibration of the site
   │   └── ...
   ├── sessions/
   │   ├── J0014010-calage/
   │   └── ...
   ├── summary/                hmp project collect: by_case.*, by_site.*, catalog.csv, ...
   ├── jobs/
   │   ├── 20261020-091500-local/   journal.jsonl of the local launcher
   │   └── 20261020-143000-slurm/   prepare.sh, array.sh, cases.txt, journal.jsonl
   ├── trash/
   └── .hmp/                   index.duckdb, logs/, launcher.lease, mesh_cache/

``runs/`` is flat and sorted by site, so ``ls runs/ | grep J0014010`` lists every case of one site.

**The guard is on outputs, not on the author's files.** A gesture of HydroModPy writes only under
``runs/``, ``sessions/``, ``summary/``, ``plan/``, ``jobs/``, ``trash/`` and ``.hmp/``. Every
``.toml``, ``.csv`` and ``.md`` file at the project root belongs to the author, as do
``configs/`` and ``site_overrides/``. The entries of the older layouts never exist at a project
root: ``outputs/``, ``catalog.duckdb``, ``simulations/``, ``exports/``, ``figures/``,
``reports/``, ``.solver_scratch/`` and the old publication folder, all listed in
``FORBIDDEN_PROJECT_ENTRIES`` of ``tests/unit/results/test_run_layout_contract.py``. No path
carries the ``.parquet.d`` or ``.zarr.zip`` suffix, and no directory is named after an
identifier.

The project config file is ``project.toml``, and
:func:`~hydromodpy.core.state.paths.resolve_project_root` anchors on it, never on a database file:
a project stays a project after its index is deleted. Relative paths in a configuration are
relative to the project root, whichever directory the file sits in.

Two state roots
---------------

**The project** ``.hmp/`` **is strictly rebuildable.** It holds the index (``index.duckdb``), the
debug logs (``logs/``), the launcher lease (``launcher.lease``) and the mesh cache
(``mesh_cache/``). The mesh cache is a true cache: every run copies the mesh entry it consumes into
its own ``mesh/``. ``rm -rf .hmp`` followed by ``hmp catalog reindex`` gives back the same project.

**What cannot be rebuilt is visible and named.** ``trash/`` is the trash, ``jobs/`` keeps the
journal and the frozen scripts of each launch, ``runs/<case>/attempts/`` keeps the earlier
attempts of a case, and ``plan/`` keeps the immutable plans. None of them is under ``.hmp/``, so
deleting the internals never empties the trash nor loses an attempt.

**A run** ``.hmp/`` **is the state of the attempt in progress**: its solver scratch (``scratch/``),
its file locks (``locks/``), its step checkpoints (``checkpoints/``) and its private data cache
(``data-cache.duckdb``). It is outside the seal, never packaged and never published. The seal of
a ``completed`` run removes it. It is never touched on a ``failed``, ``aborted`` or ``stale`` run
until a new attempt or a ``gc`` decides so, because the next attempt resumes from it.
``HMP_SCRATCH_ROOT`` (an environment variable, never an author key and never part of the config
hash) moves the scratch to a machine root such as ``$SLURM_TMPDIR``, under
``<project>/<case>.a<attempt>/``.

Classes of artefacts
--------------------

.. list-table::
   :header-rows: 1
   :widths: 12 30 22 18 8 10

   * - Class
     - Run
     - Session
     - Project (N cases)
     - Sealed
     - Regenerable
   * - raw result
     - ``fields.zarr/``, ``tables.parquet/``, ``config.toml``, ``inputs.json``,
       ``provenance.json``, ``manifest.json``, ``mesh/``
     - ``config.toml``, ``session.json``, ``trials.jsonl``, ``phases/``
     - ``plan/<hash>/``
     - yes
     - no
   * - derived
     - ``figures/`` + ``index.json``
     - ``figures/``
     - ``summary/``
     - no
     - yes
   * - deliverable
     - ``exports/`` + ``index.json``
     -
     - ``summary/exports/``
     - no
     - yes (``hmp export``)
   * - report
     - ``report/index.html``
     - ``report/index.html``
     - ``summary/report/index.html``
     - no
     - yes (``hmp report``)
   * - human map
     - ``README.md``, generated, sha256 of the manifest in its footer
     - ``README.md``
     - ``summary/README.md`` only; the root ``README.md`` is the author's
     - no
     - yes
   * - outcome
     - ``outcome.json``, ``attempts/<n>/``
     - ``outcome.json``
     - ``jobs/<stamp>/journal.jsonl``
     - ``outcome.json`` frozen at the seal
     - no
   * - publication
     - ``published.jsonl``
     - ``published.jsonl``
     -
     - no
     - no
   * - diagnostic
     - ``logs/``: ``run.log``, solver listing, ``heartbeat.json``, ``job-<id>.out``
     - ``logs/``
     - ``.hmp/logs/``
     - no
     - disposable
   * - machine state
     - ``.hmp/``: scratch, locks, checkpoints of the attempt in progress
     - ``.hmp/``
     - ``.hmp/``: index, lease, mesh cache
     - no
     - rebuilt (project) or consumed by the seal (run)

A run folder
------------

.. code-block:: text

   runs/<case>/
   ├── outcome.json        attempt, attempt_id, host, pid, status, sim_id; written before any step
   ├── README.md           generated at the seal: site, period, version, checks, label, sha256
   ├── config.toml         the resolved configuration, frozen; paths relative to the project root
   ├── inputs.json         sealed: provider, product, version, request, fetched_at, sha256, licence
   ├── provenance.json     environment, versions, git, solver binaries; host and user stay here
   ├── manifest.json       the seal, written last
   ├── annotations.json    tags and notes, written after the seal
   ├── fields.zarr/        the array store
   ├── tables.parquet/     the tabular payloads
   ├── mesh/               the mesh entry the run consumed, when it cannot be rebuilt bit for bit
   ├── figures/            index.json + the figures of this run
   ├── exports/            index.json + the files of each [[export]]
   ├── report/             index.html
   ├── logs/               run.log, solver listing, heartbeat.json
   ├── published.jsonl     one line per publication of this run; absent until published
   ├── attempts/<n>/       outcome.json and logs/ of an earlier attempt; absent at the first
   ├── solver/             the solver folder, kept only with keep_solver_files = true
   ├── ro-crate-metadata.json, stac-item.json, prov.jsonld: views rendered from the seal
   └── .hmp/               state of the attempt in progress; removed by the seal of a completed run

Those names are the whole vocabulary: ``ALLOWED_RUN_ENTRIES`` in
``hydromodpy/results/storage/contract.py`` lists them, and no other name is a run artefact.

``manifest.json`` is written last, through a temporary file, ``fsync`` of the file and of the
directory, and a rename. Its blocks are ``run``, ``geometry``, ``period``, ``config``, ``site``,
``lineage`` (by identifiers), ``identity``, ``checks`` and ``artifacts`` (which lists
``inputs.json`` and ``mesh/``), plus the run's ``parameters`` and ``metrics`` summaries.
``geometry.catchment`` carries the catchment area and the outlet: a discharge derived from runoff
is scaled by that area. ``geometry.mesh_engine`` and ``geometry.mesh_engine_version`` name the
engine that built the mesh. A run received alone says its catchment and its facts.

The run builds its seal in memory (``RunRecord``) and writes it with ``pyarrow`` and JSON:
``tables.parquet/simulation.parquet``, ``tables.parquet/parameters.parquet``,
``provenance.json``, ``inputs.json``, then ``manifest.json``. The process of a case never opens
the index, a calibration included.

``checks`` are sealed facts with no judgement: water budget and its declared threshold,
convergence, observation coverage, score window, the validities of the calibration criteria,
the bounds hit, whether the code was reproducible. The label (``exploratory``, ``calibrated``,
``evaluated``, ``failed``) is derived on read by :mod:`hydromodpy.results.validity_rules` and the
``known_issues.toml`` shipped in the wheel, so a run sealed by a version with a known defect is
downgraded without rewriting its seal. Every file that leaves a run carries the ``identity`` block
(site, case, ``sim_id``, period, score window, label, label date, rule version, version): root
attributes of the Zarr store, ``schema.metadata`` of each Parquet file, ``gpkg_metadata`` of a
GeoPackage, metadata and a visible footer of a figure, and a ``<file>.meta.json`` next to a CSV.

A session folder
----------------

.. code-block:: text

   sessions/<case>/
   ├── outcome.json
   ├── README.md           method, phases, best trial, the promoted run and its sim_id
   ├── config.toml         the resolved configuration of the case: the base of a promotion replay
   ├── session.json        site, session_id, config_hash, search_space, best trial, status
   ├── trials.jsonl        one trial per line; trial unique within the case; phase, restart, sim_id
   ├── methods.md
   ├── phases/<phase>/     session.json of the phase: status, frozen values, best
   ├── trials/<nnnn>/      kept trials, each shaped like a run
   ├── trial_series/       opt-in scored series per trial (persist_trial_series)
   ├── candidates/         TOML overlays of the candidates (materialize_candidates)
   ├── figures/            trajectory, cost profile
   ├── report/             index.html
   └── logs/

``session.json`` and ``trials.jsonl`` are written while the calibration runs: the descriptor
before the first trial, one line per trial as it completes, the descriptor again at the end with
the outcome. An interrupted calibration keeps every trial it evaluated. A trial number is unique
within a case across phases and restarts; a number written twice is one trial written twice and
the last line wins. ``ALLOWED_SESSION_ENTRIES`` in ``hydromodpy/results/storage/contract.py`` lists
the names.

A calibration session and its promoted run are siblings, ``sessions/<case>/`` and
``runs/<case>/``, with the same version: the session reserves ``N`` and the promoted run takes it.
The link between the two is ``manifest.lineage.session_id`` and ``session.json`` ``best.sim_id``;
the identical name is a convenience for ``ls``. A case of calibration is done when its
``session.json`` says ``completed`` for the config hash of the plan.

Above the run
-------------

.. list-table::
   :header-rows: 1
   :widths: 30 40 20 10

   * - Path
     - Form
     - Written by
     - Regenerable
   * - ``plan/<hash>/plan.json``, ``sites.parquet``, ``cases.parquet``, ``<case>.toml``
     - immutable, addressed by the fingerprint of ``project.toml``, the recipes, the table and
       the overrides; ``plan/current`` names the plan in force; ``cases.parquet`` has no
       ``status`` column, the state comes from the outcomes
     - ``hmp project plan``
     - yes, never rewritten in place
   * - ``hydromodpy.lock``
     - pin of the workspace input cache, read by ``--frozen``
     - the ``prepare`` phase, once per plan
     - no (provenance)
   * - ``jobs/<stamp>-<local|slurm>/journal.jsonl``
     - one JSON line per event, append-only, one writer (the launcher holding the lease)
     - the launcher; on a cluster, ``hmp project log`` rebuilds it from the outcomes
     - no, and the index does not need it
   * - ``jobs/<stamp>-slurm/cases.txt``, ``prepare.sh``, ``array.sh``
     - frozen when generated
     - ``hmp project array``
     - no
   * - ``summary/by_case.*``, ``by_site.*``, ``catalog.csv``, ``exports/``, ``report/``,
       ``README.md``
     - flat views of the index and of the best case of each site
     - ``hmp project collect``
     - yes

A plan is never rewritten while one of its cases is ``running``: ``hmp project plan`` refuses
without ``--force``, so a task of an array always reads the plan it was given.

Naming and identity
-------------------

The directory under ``runs/`` **is** the run name, with its ``.vN`` version suffix. Without
``[sites]`` the name is ``[simulation] name``, else the stem of the TOML file. A calibration case
is named by the stem of the file that holds ``[calibration]``, unless that file writes
``[simulation] name`` itself; a name inherited through ``base_config`` never names a calibration.
With ``[sites]`` the name is ``case_id = "<site>-<recipe>"``: site and recipe are each
``[A-Za-z0-9_]+``, ``-`` is the separator and nothing else, a recipe ending in ``.v<N>`` is
refused, and a name holds 96 characters at most. ``run_dirname`` folds accents to ASCII, keeps the
case and refuses a longer name with ``RunNameTooLongError`` instead of truncating it. No output
path carries the ``sim_id`` or a part of it.

**A run launched with** ``--set`` **or** ``--overlay`` **keeps its name.** The override is written
in the frozen ``config.toml`` and in ``manifest.lineage.overrides``, and the version suffix takes
the collision. ``--case <name>`` names the variant for whoever prefers a telling name.
``hmp calibrate`` takes the same three flags: its session and promoted run keep the name of the
file the user named (or ``--case``), never the name of the effective copy the command writes
beside it.

**The version is computed on disk and never given out twice.**
:func:`~hydromodpy.results.catalog.registration.reserve_version_dirname` takes ``N`` as one more
than the highest version of the stem among the live directories of ``runs/`` and ``sessions/``,
the trashed directories (by the relative directory they came from) and the lines of
``trash/tombstones.txt``, then creates the directory with ``os.mkdir``. ``mkdir`` only makes the
claim atomic: when another process wins it, the version is computed again. The bare name is
version 1 for life, runs and sessions share one version space, and a deleted name is never
reassigned. A failed attempt does not take a version: the next attempt stays in ``runs/<case>/``.

**Lineage is by identifiers.** ``manifest.lineage`` holds ``parent_sim_id``, ``session_id``,
``phase``, ``trial``, ``kind`` (``rerun``, ``promoted``, ``trial`` or ``version``), ``overrides``
and ``parent_hint``, the relative directory at the time of writing. A rename moves the directory
and the index row; the links by identifier do not move, and a stale hint is never required.

**The reference of a run in the CLI and in Python is its relative directory**: ``baseline.v2``,
``J0014010-base``, ``calibration``, ``sessions/calibration/trials/0004``. ``@last`` and
``@best:<metric>`` resolve to one of them. The two forms, ``runs/<name>`` and
``sessions/<name>/trials/<nnnn>``, are spelled and read only by the relative-directory functions
of :mod:`hydromodpy.core.state.paths`.

**An identical case is skipped from disk**: the worker reads ``identity.config_hash`` in
``runs/<case>/manifest.json``, never the index. ``if_exists`` is ``version`` or ``fail``.

Trash and tombstones
--------------------

Deleting a run or a session moves its directory, it never flips a status.
:func:`~hydromodpy.results.trash.trash_run` moves ``<rel_dir>`` to
``trash/<rel_dir with / replaced by __>@<YYYYmmddTHHMMSS>/``, for instance
``trash/runs__daily@20261014T093000/``; ``restore`` moves it back; ``list_trash`` reads the
trash. A run that holds ``published.jsonl`` is trashed with a warning, because its published
copies now point at a trashed source. Deleting is by exact name: a bare name that has several
versions is refused with the list.

``gc_trash`` frees the bytes of the directories trashed before a cut-off and leaves one line per
directory in ``trash/tombstones.txt``: ``rel_dir,sim_id,date``. The tombstones are written and
flushed before any byte is removed, so a crash can leave a directory with its tombstone, never a
freed name without one. ``ls runs/`` shows only the living.

Versions of the stored documents
--------------------------------

Every document HydroModPy writes carries its version: a ``schema`` id (``outcome.json``,
``inputs.json``, ``session.json``, ``phases/<p>/session.json``, each line of ``trials.jsonl``
and ``published.jsonl``, ``plan.json``, ``PUBLICATION.json``, the ledgers ``index.json``,
``<file>.meta.json``, ``logs/heartbeat.json``, ``facts.json``, ``steps.json``,
``launcher.lease``), an integer (``manifest_version``, ``provenance_version``,
``annotations_version``), ``[hydromodpy] version`` in ``hydromodpy.lock``, or the
``schema_version`` row of the index. A reader refuses a document without a version, or with one
it does not know, and the message names the version read, the version this code reads and what
to do (:mod:`hydromodpy.core.io.document_version`):

- the index: ``hmp catalog reindex`` rebuilds it from the directories;
- a sealed document: read it with the HydroModPy version that wrote it, named in the message;
- a transient one (pulse, facts, step journal, lease): delete it and run again;
- the lockfile: ``hmp dev lock update`` writes it again.

Stored data is never migrated. The one migration kept is the grammar of a configuration file
(``config/config_migration.py``, applied on load; ``hmp doctor --fix-config <file>`` rewrites
the file in place). ``tests/unit/results/test_every_document_carries_its_version.py`` holds the
rule and lists the exempt files with their reason.

Attempt protocol
----------------

A case is run by one worker process, ``hmp run <case>.toml``, which decides alone, from the disk,
to skip, resume or version.

1. **The first act of the worker** creates ``runs/<case>/`` and writes the initial
   ``outcome.json`` (``running``), before validation, geography, data or mesh.
2. **The heartbeat starts at the entry of the process**, on a thread that writes only
   ``logs/heartbeat.json`` through ``os.replace``.
3. ``stale`` (an old heartbeat) is display only. A new attempt requires a proven death: same host
   and absent PID, or the scheduler says the job ended, or an explicit ``--force``.
4. **Claiming an attempt is atomic**: the worker reads ``attempt = k`` in ``outcome.json``,
   proves the death, then creates ``runs/<case>/attempts/<k>/`` with ``os.mkdir``. The loser gets
   ``EEXIST`` and leaves. A re-issued or doubled job therefore never mints a ``.v2`` for an
   identical configuration.
5. **Attempt** ``k+1`` **resumes in place by default**: ``outcome.json`` and ``logs/`` of attempt
   ``k`` move under ``attempts/<k>/``; the checkpoints, the partial store, the scratch and
   ``trials.jsonl`` stay. ``--fresh``, or a changed config hash, moves the whole content under
   ``attempts/<k>/`` and starts over.
6. **A parent writes the outcome of a child that died without writing it** (a native abort, an
   out-of-memory kill, a wall-time ``SIGKILL``): ``failed`` with ``exit_code``, ``signal``,
   ``log_tail`` and ``written_by = "launcher"`` or ``"trap"``.

A failed run is sealed too: ``outcome.json``, ``README.md``, ``config.toml`` and ``logs/`` are
there, ``.hmp/`` is kept for the next attempt, and there is no ``manifest.json``.

Status precedence
-----------------

The effective status of a run directory is read from its files, in this order:

#. ``manifest.json`` present: ``completed``, whatever ``outcome.json`` says. The manifest is
   written before ``outcome.json = completed``.
#. ``outcome.json`` says ``completed`` and there is no manifest: ``partial``.
#. ``outcome.json`` says ``failed`` or ``aborted`` and there is no manifest: ``failed`` or
   ``aborted``.
#. ``outcome.json`` says ``running`` and the heartbeat is old: ``stale``, display only.
#. ``outcome.json`` says ``running`` and the heartbeat is fresh: ``running``.
#. no ``outcome.json``: ``unknown``.

``effective_status`` in :mod:`hydromodpy.results.outcome` is the one implementation.
``hmp project status`` and ``hmp catalog watch`` read the outcomes and the heartbeats, never the
index.

The index
---------

One index per project, ``.hmp/index.duckdb``, derived, built by the launcher and the reader,
never by a run nor by a calibration. Every write of the index is a fresh file installed with one
rename, so a reader always opens a snapshot and never blocks the writer.

**What the reindex reads.** A run directory is indexed from ``tables.parquet/simulation.parquet``,
``parameters.parquet``, ``metrics.parquet``, the geographic payloads, ``manifest.json``,
``provenance.json`` and ``annotations.json``. A directory with an ``outcome.json`` and no manifest
is indexed too, with its effective status, so a failed case is visible. A session is indexed from
``session.json``, ``phases/*/session.json`` and ``trials.jsonl``. The name of a run is taken from
its directory, never from its files: a rename moves the directory, so the tree is the name.

**The incremental reindex is a diff** keyed by the relative directory and the ``sim_id`` or
``attempt_id``: it inserts new directories, updates a row whose directory moved (a rename, a
restore, an extracted archive), deletes rows whose directory disappeared, and moves the previous
attempt to ``attempts`` before inserting the new one. Its trigger is the latest modification time
of the ``outcome.json`` and ``session.json`` files.

**A schema change is a full reindex.** There are no SQL migrations: the index is derived, so it is
rebuilt from the directories. Besides the run tables, the index holds ``sites``, ``cases`` and
``attempts``, and the view ``v_cases`` joins cases, runs, parameters and the metric at the gauge
of the site within the declared window. ``cases.status`` holds only what the disk says of an
attempt, the effective status at indexing time: ``running``, ``completed``, ``partial``,
``failed``, ``aborted`` or ``stale``. The states of the plan (``planned``, ``invalid``,
``skipped`` and ``stale_plan``, a case whose config hash no longer matches the current plan)
are computed by ``hmp project status`` from ``plan/current`` and the outcomes, and never
written in the index.

**What the reindex loses is not needed.** The whole index is losable. The tables with no
directory behind them have their replacement on disk: ``exports/index.json`` and
``figures/index.json`` for what was produced, ``published.jsonl`` for what left the project,
``jobs/*/journal.jsonl`` for what was launched, and ``trials.jsonl`` with its ``sim_id`` for the
link between a trial and its promoted run. Observation series and station metadata are input
data, repopulated from the workspace input cache, never from a results rebuild.

A workspace reads across projects through the ``tables.parquet/simulation.parquet`` of each run,
whose schema travels with the file.

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
at store init. ``derived``, ``budget`` and ``geographic`` are created when a
writer first needs them. ``budget/`` holds the per-cell budget terms and a
default run keeps all of them, storage terms included
(see the per-cell budget below). ``derived/`` holds only the static parameter
fields (hydraulic conductivity, specific yield, ...); no time-varying
derived field is ever written there.

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
concentrations). ``compact``, the default, stores
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

**Per-cell budget.** A run writes under ``budget/`` every per-cell term its
extractor produces, under the canonical CBC name: the exchange terms
(``recharge``, ``drain``, ``river``, ``constant_head``, ``lake``, ``stream``,
``evapotranspiration``, ...) and the storage terms (``storage`` under
MODFLOW-NWT, ``storage_ss`` and ``storage_sy`` under MODFLOW 6). Each term has
a descriptor in :mod:`hydromodpy.results.field_registry`, so it can be listed,
exported and read with ``run.field``. The group carries two attributes that
say what the run kept (:mod:`hydromodpy.core.budget_terms`):

- ``policy``: ``all`` (the default) or ``consumers``, set by
  ``[simulation.results] keep_per_cell_budget = false``;
- ``kept_terms``: under ``all``, the terms written; under ``consumers``, the
  terms the run planned to keep. A kept term without an array is a term the
  model does not produce. A term outside ``kept_terms`` under ``consumers`` was
  not kept.

Readers and missing-field messages read these attributes, never the config.
The lumped ``budgets`` table is not affected by the policy.

**Fields rebuilt on read.** Every derived field is rebuilt from the stored
terms and the stored mesh by the readers
(:mod:`hydromodpy.results.derive.virtual_fields`), on the same grid, with a
range path so a window of steps reads only its slab: ``watertable_elevation``,
``watertable_depth``, ``seepage_mask``, ``release_flux``, ``outflow_drain``,
``accumulation_flux``, ``release_accumulation_flux``, ``fluxes_from_budget`` and
the solute fields ``concentration_seepage``, ``mass_seepage`` and
``mass_accumulated``. Nothing time-varying is written under ``derived/``. A
store written before holds some of these arrays under ``derived/`` (in
float64 for ``release_flux`` and ``fluxes_from_budget``), and every reader
returns the stored array first, so it reads as it always did.

None of this bumps ``zarr_schema_version``: the layout, the names, the
shapes and the meaning of every stored array are unchanged, the float width
is declared by each array's own Zarr metadata, and both an old store and a
new one read the same through every reader.

**Cell mesh.** ``step_persist_mesh`` writes the mesh of a run once, before the solve, from the
``PlanarCellMesh`` the mesh step built. The solver extractors then check their grid against it and
add only what the solved model owns (topography, layer thickness, streambed levels, ``grid_type``)
through ``write_topography``; none of them rewrites vertices or connectivity, and a grid whose
cell count differs from the stored one raises ``IncompatibleMeshError``. Besides ``vertices``,
``face_node_connectivity``, ``z_interfaces`` and ``topology``, ``mesh/`` holds:

.. list-table::
   :header-rows: 1
   :widths: 22 12 18 48

   * - Array
     - dtype
     - Axes
     - Content
   * - ``face_x``, ``face_y``
     - float64
     - ``face``
     - Cell centre, by the one centre rule of the mesh; the attribute ``center_kind`` says
       ``generator``, ``cell_center`` or ``vertex_mean``
   * - ``face_family``
     - int32
     - ``face``
     - Bit field of the line families a cell belongs to; ``flag_masks``, ``flag_meanings``
       (CF-safe names) and ``family_names`` (exact names) give the bit of each family
   * - ``face_zone``
     - int32
     - ``face``
     - Index into the attribute ``zone_names``, ``-1`` when unknown; written only when the mesh
       has zones
   * - ``edge_node_connectivity``
     - int32
     - ``edge``, ``two``
     - The two end nodes of every mesh edge, smaller node first, sorted
   * - ``edge_face_connectivity``
     - int32
     - ``edge``, ``two``
     - The cells on the two sides of every edge, ``-1`` for the domain side of a boundary edge
   * - ``edge_family``
     - int32
     - ``edge``
     - Bit field of the face families an edge lies on; its own ``flag_masks``, ``flag_meanings``
       and ``family_names`` attributes name the bits, which need not match those of ``face_family``

The attributes of ``mesh/`` add the ``engine``, its ``engine_version``, its ``engine_seed`` when it
draws random numbers, the ``mesh_request_hash``, the ``crs`` (WKT) the vertices are expressed in,
the mesh ``qa`` (JSON, no ``NaN``), the ``library_versions`` the mesh depends on and, on a regular
grid, ``structured_shape``. The edge arrays are the UGRID ones, with the same fill value as
xugrid, so ``xugrid.Ugrid2d`` takes them as stored. A family has one bit, so a mesh holds at most 31
families. The order along a river, which a bit field cannot keep, is in the ``mesh_cell_families``
table (``family``, ``chain_id``, ``position`` from upstream, ``cell_id``, and ``offset_m``, null
when the engine publishes no offset for the chain); the faces of the face-intent families (lakes, geology, the
``boundary:*`` sides) are in ``mesh_face_families`` (``face_row``, ``family``, ``edge_id``, the two
nodes, the cell on each side and the zone names). A run whose mesh has no such family writes no
table: an absent table is an empty one when the ``engine`` attribute is present. All of this is
additive, so ``zarr_schema_version`` does not change. A run sealed before it has none of these
arrays, no ``engine`` and no ``crs`` on ``mesh/``; its readers say so and do not rebuild them.

**Routing descent.** A MODFLOW 6 or MODFLOW-NWT run stores the descent D it was built with under
``mesh/``, one value per face and none rounded: ``descent_receiver``, ``descent_surface``, the
masks ``descent_base_level``, ``descent_constant_head``, ``descent_raised``, ``descent_channel``
and ``descent_pinned``, the list ``descent_dam_foot`` and the mask ``descent_basin``, the basin of D
at the catchment outlet, whose attributes name the outlet cell (``descent_outlet``), the rule that
found it (``basin_rule``), the area (``basin_area_m2``), whether D was seeded at the outlet
(``basin_seeded_at_outlet``) and the rule version (``basin_version``). The attributes of
``descent_receiver`` name the neighbourhood and carry the build report. The solver build leaves D
and its basin in the solver folder as ``<model>.descent.npz`` and the extractor copies them into
the store right after the mesh. ``run.descent`` reads them back, and the flow direction map and ``accumulation_flux`` route on it
(the contract of D is in :doc:`solver/backends`). A Boussinesq run stores the mesh of its
setup like any other and stores no D: its readers rebuild D from the stored top, as for a run
sealed before D was stored. The
arrays are new datasets, so ``zarr_schema_version`` does not change. A run sealed before D was stored has no
``descent_*`` array, and its readers rebuild D from the stored top, with no channel pin, no
constant-head seed and no lake. A run sealed with D but before ``descent_basin`` has no basin, and
each reader of the catchment says which older support it falls back to.

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
run's ``identity`` block in Parquet key-value metadata, and is exposed as a DuckDB
view named after the payload.

The container directory is ``tables.parquet/`` and the payloads inside
are plain ``.parquet`` files. No suffix marks a container.

The payloads are ``simulation``, ``parameters``, ``metrics``, ``timeseries``, ``budgets``,
``mass_balance``, ``observation_points``, ``sfr_reaches`` (the resolved SFR reach geometry, the
only record of which cell carries which reach, absent when the run built no stream network),
``soil_budget`` (one row per soil column and calendar year, absent outside soil mode),
``mesh_cell_families`` and ``mesh_face_families`` (the line families of the mesh, see the cell
mesh above), ``provenance`` and the GeoParquet 1.1 layers ``geographic_*``. Their columns are generated in
:doc:`generated/storage-tree`.

``simulation.parquet`` is written by the run from its ``RunRecord``: it carries ``project``,
``site``, ``site_fingerprint``, ``recipe``, ``case_id``, ``rel_dir``, ``attempt``, ``attempt_id``,
the flattened ``checks``, and the metric rule columns ``nse_window_start``, ``nse_window_end``,
``nse_n`` and ``metric_rule_version``. Without a declared gauge and window, ``nse`` is null.
``parameters.parquet`` carries ``calibrated`` and ``origin`` (``declared``, ``site_table``,
``site_override``, ``recipe`` or ``calibrated``).

Concurrency and atomic writes
-----------------------------

- ``manifest.json`` and ``outcome.json`` are written through a temporary file, ``fsync`` of the
  file and of its directory, and a rename. ``provenance.json``, ``inputs.json``,
  ``annotations.json``, the ledgers and ``logs/heartbeat.json`` are written through a temporary
  file and a rename.
- Zarr field writes hold a cross-process ``filelock`` under ``<run>/.hmp/locks/`` and append in
  place. The store directory is promoted with a rename when it is created.
- Parquet writes use a temporary file plus ``os.replace``.
- A run directory and an attempt are claimed with ``os.mkdir``, which fails for the loser.
- The launcher of a project holds ``.hmp/launcher.lease``, created with ``O_EXCL``; a lease of a
  dead process is taken over by the same proof of death as an attempt.
- The workspace input cache has one writer, the launcher. A case, in its ``prepare`` phase or in
  its solve, opens it read-only, one request at a time, and registers what it fetched in a
  private cache (``runs/<case>/.hmp/data-cache.duckdb`` for a worker), which the launcher merges
  when the case ends.
- The index is written as a staging file next to it and installed with one atomic rename. The
  invariant is that ``index.duckdb`` is never absent nor half-written: a reader that was reading
  keeps reading the file it opened, and the next opener gets the new one. ``os.replace`` delivers
  that on POSIX. On Windows the same rename is asked of the kernel through
  ``SetFileInformationByHandle`` with ``FILE_RENAME_INFO_EX`` and
  ``FILE_RENAME_POSIX_SEMANTICS``, which unlinks the target from its directory instead of
  deleting it. Where the kernel supports neither, the write fails and says so: the previous index
  is untouched.

Lockfile and reproducibility
----------------------------

``hydromodpy.lock`` pins the workspace input cache of a project: the ``hydromodpy`` version, git
commit, Python version and config schema fingerprint; the solver binaries with their SHA-256 and
version text; the catalog, Zarr and Parquet schema versions; the input fingerprints (relative
path, SHA-256, size, fetch date). The ``prepare`` phase writes it once per plan, never each run.
``hmp run --frozen`` refuses any source whose fingerprint changed since, and checks the lockfile
read-only.

The inputs of one run are sealed in its own ``inputs.json``: one entry per loaded variable with
its provider, product, product version, the full request (extent, period, stations, step),
``fetched_at``, path, SHA-256, size and licence. A replay never depends on the project-wide file.

Publishing and packages
-----------------------

``hmp publish <ref> --to <dir>`` copies ``README.md``, ``config.toml``, a redacted
``provenance.json``, ``inputs.json``, ``manifest.json``, ``figures/``, ``exports/`` and
``report/``, generates ``ro-crate-metadata.json`` and writes ``PUBLICATION.json`` (the source
project, relative directory and ``sim_id``, the SHA-256 of the manifest and of every copied file,
the label and its date, the version, the date). ``--with results`` adds the stores and
``--with inputs`` the install index ``INSTALL.toml`` (``hydromodpy/core/payload/``) and the bytes
of every file the run read, addressed by content under ``inputs/``, sidecars included. The source
receives one line in ``published.jsonl``. ``.hmp/``, ``logs/``, host, user and absolute paths
never leave: one function redacts every copy.

The portable package **is** ``hmp publish --with results --with inputs --format tar``. Importing
it (``hmp catalog import``) installs every file of ``INSTALL.toml`` into ``data/`` of the
workspace (identical bytes cost nothing, other bytes at one path are refused by name), merges the
station rows, registers the delivered files in ``data/cache.duckdb`` and the site in
``data/sites/catalog.csv``, then extracts the run under ``runs/`` and runs an incremental
reindex. ``hmp project export`` writes a whole project on the same index, and
``hmp project import`` installs it as ``projects/<name>``.

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
scenario comparison.

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

Tested invariants
-----------------

- **Layout.** ``tests/unit/results/test_run_layout_contract.py``: one solved run produces one
  directory named after the run holding only declared names; a completed run carries
  ``outcome.json``, ``README.md``, ``inputs.json`` and ``logs/`` and keeps no ``.hmp/``; nothing is
  written outside the output roots; the project ``.hmp/`` holds only rebuildable entries; an
  author file at the root is never flagged and a removed entry always is; no path carries an
  identifier or a container suffix.
- **Rebuildable internals.** ``tests/unit/results/test_internal_dir_is_reconstructible.py``
  deletes the project ``.hmp/``, reindexes and compares the runs, statuses, parameters, metrics
  and every file outside ``.hmp/``.
- **Naming.** ``tests/unit/results/test_reserve_version_dirname.py`` covers the version
  computation and two real processes reserving one name;
  ``tests/unit/results/test_a_name_is_never_reassigned.py`` trashes a version, with and without
  gc, and checks the next run takes the next number.
- **Trash.** ``tests/unit/results/test_trash_move.py`` checks the move, the identical restore, the
  tombstones written by gc and the trash of a session.
- **Attempts and seal.** ``test_two_workers_one_case.py`` (two workers on one failed case, one
  continues, no ``.v2``), ``test_a_failed_run_is_sealed.py``, ``test_heartbeat_is_atomic.py``.
- **The index.** ``tests/unit/results/test_reindex.py`` (coverage, sufficiency, idempotence,
  atomicity, incremental diff after a rename, a retry and a deletion),
  ``test_a_run_never_opens_the_index.py`` and ``test_a_calibration_never_opens_the_index.py``
  (``Catalog`` patched to raise during ``hmp run`` and ``hmp calibrate``).
- **Outputs.** ``test_every_export_carries_identity.py``, ``test_every_writer_targets_the_run.py``,
  ``test_publish_contents.py``, ``test_publish_redaction.py``.

Known limit
-----------

**The Zarr chunk layout is tuned for map reads.** Chunks are about 1 MiB each, and a whole
timestep sits in one chunk as long as it fits that budget
(``hydromodpy/results/zarr_store/chunks.py``). Reading one cell across time is a single Zarr
call, but it decompresses every chunk the time axis crosses, so a point series pays for the
neighbouring cells it never uses. A cell-major layout, or a second copy laid out that way, would
make it cheap, and neither exists.

**A network file system is not supported.** ``os.mkdir``, ``rename`` and the file locks depend on
the mount options. The layout reduces the shared writers to one (the launcher) and proves
death through the scheduler, but it does not make DuckDB safe on NFS.

See also
--------

- :doc:`data-scopes` for the role of each database scope.
- :doc:`generated/storage-tree` for the tree and the schema.
- :doc:`/contribute/architecture/packages/results` for the Python API on top of
  this storage.
- :doc:`/contribute/architecture/packages/data` for the input cache writer.
