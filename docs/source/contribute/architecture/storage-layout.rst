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

**An artifact is written in the directory of what produced it, under a fixed name per class.
There is no other destination inside a project.** A figure of a run is in that run, a report
of a session is in that session, a table over N cases is in ``summary/``. Publishing is a copy
out of the tree (``hmp publish``); nothing in the project points at the copy except the
``published.jsonl`` line of its source.

The directory names of the project are declared in :mod:`hydromodpy.core.state.layout`. The names
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
   ├── hydromodpy.lock         pin of the data cache and of the files of the user
   ├── inputs/                 the author's input files, made by hmp project new
   ├── configs/                the author's variants and overlays, made by hmp project new
   ├── runs/
   │   ├── baseline/           hmp run project.toml
   │   ├── baseline.v2/        hmp run project.toml --set flow.param.K.field.value=2e-5
   │   ├── daily/              hmp run daily.toml
   │   └── calibration/        the promoted best trial of sessions/calibration
   ├── sessions/
   │   └── calibration/        hmp calibrate calibration.toml
   ├── trash/                  runs and sessions deleted by a move; tombstones.txt
   └── .hmp/                   rebuildable: index.duckdb, logs/, products/

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
   ├── summary/                hmp campaign collect: by_case.*, by_site.*, catalog.csv, ...
   ├── jobs/
   │   ├── 20261020-091500-local/   journal.jsonl of the local launcher
   │   └── 20261020-143000-slurm/   prepare.sh, array.sh, cases.txt, journal.jsonl
   ├── trash/
   └── .hmp/                   index.duckdb, logs/, launcher.lease, products/

``runs/`` is flat and sorted by site, so ``ls runs/ | grep J0014010`` lists every case of one site.

**The guard is on outputs, not on the author's files.** A gesture of HydroModPy writes only under
``runs/``, ``sessions/``, ``summary/``, ``plan/``, ``jobs/``, ``trash/`` and ``.hmp/``. Every
``.toml``, ``.csv`` and ``.md`` file at the project root belongs to the author, as do
``inputs/``, ``configs/`` and ``site_overrides/``. ``hmp project new`` creates ``inputs/`` and
``configs/`` next to ``project.toml``, and the name of the project follows the rule of the names
of runs, given below. The entries of the older layouts never exist at a project
root: ``outputs/``, ``catalog.duckdb``, ``simulations/``, ``exports/``, ``figures/``,
``reports/``, ``.solver_scratch/`` and the old publication folder, all listed in
``FORBIDDEN_PROJECT_ENTRIES`` of ``tests/unit/results/test_run_layout_contract.py``. No path
carries the ``.parquet.d`` or ``.zarr.zip`` suffix, and no directory is named after an
identifier.

**The data folder is its sidecars.** ``data/`` of the workspace, or ``<project>/data/`` for a
project with no workspace, holds the files that providers delivered. Each has a sidecar
``<file>.json`` that records its variable, source, extent, period, digest and licence, and nothing
else records them: there is no database, and a ``cache.duckdb`` found there is refused. The files
of the user stay under ``inputs/`` and are no row of the cache. :doc:`data-scopes` gives the
rules of the scan.

The project config file is ``project.toml``, and
:func:`~hydromodpy.core.state.result_dirs.resolve_project_root` anchors on it, never on a database file:
a project stays a project after its index is deleted. Relative paths in a configuration are
relative to the project root, whichever directory the file sits in.

Two state roots
---------------

**The project** ``.hmp/`` **is strictly rebuildable.** It holds the index (``index.duckdb``), the
debug logs (``logs/``), the launcher lease (``launcher.lease``) and the product store
(``products/``). A product is a folder keyed by a sha256 of the inputs the step read, the
processing keys and the code of the package that computes it, so the workflow asks the store for
the mesh, the soil reservoir and the terrain (the conditioned DEM, its D8 directions and its
accumulation, described by ``terrain.json``) before it computes them. ``[workspace]
products_cap_mb`` caps the store at 5000 megabytes by default, and a write past the cap evicts the
oldest products first and never one a running attempt cites. A sealed run never depends on the
store: its mesh lives in the ``mesh/`` group of its ``fields.zarr``, its soil in its own tables,
and its terrain in the rasters the run kept. ``rm -rf .hmp`` followed by ``hmp catalog reindex``
gives back the same project.

**What cannot be rebuilt is visible and named.** ``trash/`` is the trash, ``jobs/`` keeps the
journal and the frozen scripts of each launch, ``runs/<case>/attempts/`` keeps the earlier
attempts of a case, and ``plan/`` keeps the immutable plans. None of them is under ``.hmp/``, so
deleting the internals never empties the trash nor loses an attempt.

**A run** ``.hmp/`` **is the state of the attempt in progress**: its solver scratch (``scratch/``),
its file locks (``locks/``), its step checkpoints (``checkpoints/``) and, while a stop is asked, its
stop flag (``stop.json``). It is outside the seal, never packaged and never published. The seal of
a ``completed`` run removes it. It is never touched on a ``failed``, ``aborted`` or ``stale`` run
until a new attempt or a ``gc`` decides so, because the next attempt resumes from it.
``HMP_SCRATCH_ROOT`` (an environment variable, never an author key and never part of the config
hash) moves the scratch to a machine root such as ``$SLURM_TMPDIR``, under
``<project>/<case>.a<attempt>/``. The terrain the attempt routes, the conditioned DEM with its D8
directions and its accumulation, is a copy read back from the product store under
``_preprocessing/`` of the scratch: an attempt never writes into the store, and a resume reads the
same product again and delineates on it.

Classes of artifacts
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
     - ``fields.zarr/``, ``final_state/``, ``tables.parquet/``, ``config.toml``,
       ``config.resolved.toml``, ``inputs.json``, ``provenance.json``, ``manifest.json``
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
     - ``logs/``: ``run.log``, ``heartbeat.json``, ``job-<id>.out``; ``profile.json``
     - ``logs/``
     - ``.hmp/logs/``
     - no
     - disposable
   * - machine state
     - ``.hmp/``: scratch, locks, checkpoints of the attempt in progress
     - ``.hmp/``
     - ``.hmp/``: index, lease, product store
     - no
     - rebuilt (project) or consumed by the seal (run)

A run folder
------------

.. code-block:: text

   runs/<case>/
   ├── outcome.json        attempt, attempt_id, host, pid, status, sim_id, request_id; written before any step
   ├── request.json        the request as given in JSON or as a dict; written at the claim, never redacted
   ├── README.md           generated at the seal: site, period, version, checks, label, sha256
   ├── config.toml         what the run was given, overrides included; written at the claim; paths relative to the project root
   ├── config.resolved.toml  the same with every default, and what the build decided; a replay compares to it
   ├── inputs.json         sealed: provider, product, version, request, fetched_at, sha256, licence
   ├── provenance.json     environment, versions, git, solver binaries; host and user stay here
   ├── products.json       the products the run read from the store, one per kind, in first-demand order
   ├── manifest.json       the seal, written last
   ├── annotations.json    tags and notes, written after the seal
   ├── fields.zarr/        the array store
   ├── final_state/        sealed: last head, lake and reach stages in float64, read by a restart and the next window
   ├── profile.json        time and memory of each step, solve, figure and export; outside the seal and the identity
   ├── tables.parquet/     the tabular payloads
   ├── figures/            index.json + the figures of this run
   ├── exports/            index.json + the files of each [[export]]
   ├── report/             index.html
   ├── logs/               run.log, heartbeat.json
   ├── published.jsonl     one line per publication of this run; absent until published
   ├── attempts/<n>/       outcome.json, logs/ and stop.json of an earlier attempt; absent at the first
   ├── solver/             the solver folder, kept only with keep_solver_files = true
   ├── ro-crate-metadata.json, stac-item.json, prov.jsonld: views rendered from the seal
   └── .hmp/               state of the attempt in progress; removed by the seal of a completed run

Those names are the whole vocabulary: ``ALLOWED_RUN_ENTRIES`` in
``hydromodpy/results/storage/contract.py`` lists them, and no other name is a run artifact.

``request.json`` is the run request of a run given as JSON or as a dict, the object that
``hmp run x.json`` reads. It is written whole at the claim, by one rename, and it is never
redacted: it holds the document, the ``set`` changes and the options exactly as they came, and
neither the base of the relative paths nor the environment of the call. A run given as a TOML file
or as a built configuration writes none, because its ``config.toml`` already says what it was
given. The file is outside the seal, so ``manifest.json`` does not list it.

``final_state/`` is a Zarr 3 group in float64, written by the extractor of each flow solver when
the solve is done: ``head`` shaped ``(nlay, ncpl)`` with NaN on inactive cells, ``lake_stage``
with its ``lake_ids`` attribute when the run has lakes, ``sfr_stage`` with its ``reaches``
attribute under SFR storage, and the attributes ``schema`` (``hydromodpy.final_state.v1``) and
``at``, the end of the last period. It is sealed with the run. The head of ``fields.zarr`` may be
rounded to 2^-17 under the compact precision, up to 0.8 mm on 100 m, so a restart and the next
window of a chain read ``final_state/`` first, and the last step of ``fields.zarr`` only for a run
of 2.0, which has none.

``profile.json`` (schema ``hydromodpy.profile.v1``) holds one line per step, solve, figure and
export: kind, name, attempt, start, duration, memory peak of the process, and whether the work was
done, rebuilt from an earlier attempt (``prefix``) or read from the product store (``store``, with
its key). The pipeline rewrites it after each step through one rename, so a stopped run keeps the
profile of what it did, and a resume adds its lines under its own attempt. It describes one
machine, so it is outside the seal and the identity. The wall time of the solve is there and in
no table.

A stop is asked by writing ``.hmp/stop.json`` (schema ``hydromodpy.stop.v1``, with ``at`` and
``host``) in the run or session folder, through ``hmp stop`` or ``hmp.stop``. The run reads it
between two steps, and the attempt ends ``aborted`` with ``StopRequested`` and no seal. A stopped
run leaves its outcome, its journal, its partial stores and the flag. The next attempt files the
flag under ``attempts/<k>/stop.json``, and a seal removes it with ``.hmp/``.

``outcome.json`` carries the ``request_id`` of the attempt, written as soon as the inputs are
resolved. It is a sha256 and the field is optional, so an outcome written before the inputs are
resolved has none. The ``sim_id`` is a uuid taken at the claim and is part of no identity.

``manifest.json`` is written last, through a temporary file, ``fsync`` of the file and of the
directory, and a rename. Its blocks are ``run``, ``geometry``, ``period``, ``config``, ``site``,
``lineage`` (by identifiers), ``identity``, ``checks`` and ``artifacts`` (which lists
``inputs.json``), plus the run's ``parameters`` and ``metrics`` summaries.
``geometry.catchment`` carries the catchment area and the outlet: a discharge derived from runoff
is scaled by that area. It also records the DEM correction method (``fill``, ``breach``,
``capped_breach`` or ``provided`` for a DEM declared conditioned elsewhere) and, for a conditioned
DEM, the two counts ``dem_cells_without_descent`` and ``dem_strict_pits``.
``geometry.mesh_engine`` and ``geometry.mesh_engine_version`` name the engine that built the mesh.
A run received alone says its catchment and its facts.

``products.json`` names the products the run read from the product store, one entry per kind, in
the order the steps first asked for them, under the schema ``hydromodpy.products.v1``. A run of
2.0.0 has none and is read as empty. The seal inventories the file at its third version and its
fourth version certifies it. Its keys carry the code of the package that computes each product,
so the file enters no request id, no solution key and no replay class.

The run builds its seal in memory (``RunRecord``) and writes it with ``pyarrow`` and JSON:
``tables.parquet/simulation.parquet``, ``tables.parquet/parameters.parquet``,
``provenance.json``, ``inputs.json``, then ``manifest.json``. The process of a case never opens
the index, a calibration included.

``checks`` are sealed facts with no judgement: water budget and its declared threshold,
convergence, observation coverage, score window, the validities of the calibration criteria,
the bounds hit, whether the code was reproducible. The label (``exploratory``, ``calibrated``,
``evaluated``, ``failed``) is derived on read by :mod:`hydromodpy.results.validity_rules` and the
``[[bug]]`` rows of the register of changes, ``hydromodpy/schema/changes.toml``, shipped in the
wheel, so a run sealed by a version with a known defect is downgraded without rewriting its seal. Every file that leaves a run carries the ``identity`` block
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
   ├── session.json        session_id, sites, cases, bounds, cost, windows, best trial, status
   ├── trials.jsonl        one trial per line; trial unique within the session; phase, restart, cases
   ├── methods.md
   ├── phases/<phase>/     session.json of the phase: status, frozen values, best, cost, windows
   ├── trials/<nnnn>/      kept trials, each shaped like a run; <nnnn>/<case_id>/ with several cases
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
the names. While a search runs it writes ``logs/heartbeat.json``, the pulse a run writes, so a live
session does not read as abandoned.

A session is one search over one or several cases, and it stores everything by table. Whatever
depends on a case has the ``case_id`` as its key, with one entry for a session of one case. Whatever
depends on a period has the name of that period as its key, with one entry for a search with one
window. So a reader of ``session.v4``, ``phase.v2`` and ``trial.v2`` already walks N cases and N
periods, and a joint calibration or a validation period adds keys, not meanings.

- ``session.json`` holds ``sites``, ``cases`` (site, config hash, frozen file, cost and the
  fingerprint of each member of the cache key, by phase), ``bounds``, ``cost_name``, ``cost_label``,
  ``windows``, ``scored``, ``best`` and ``widths``. Its ``case_id`` and ``config_hash`` name the case
  of the plan that this directory is. ``widths`` stays empty until something computes a width.
  ``protocol`` names the protocol a session follows and its version, with every departure from the
  publication in force, and stays null without a protocol.
- A period of ``windows`` has a ``role``: ``calibration`` is what the search scores, ``validation`` is
  kept apart from it and scored beside it, ``evaluation`` is ``[metrics] window`` of a run. Another
  word reads as it is, and no computation counts it as calibration. ``by_case`` gives the window of
  each case when they differ. A promoted run stores the score of its trial on the validation period
  as ``checks.calibrated_by.validation_cost``.
- ``best`` holds one trial, one ``cost`` and one set of ``parameters``, those a phase froze included,
  and ``cases`` holds the run and the cost of that trial in each case. ``cost`` is null when a search
  keeps no single cost, and ``best`` is null when it keeps no single best.
- A line of ``trials.jsonl`` holds the ``params`` the search proposed, the ``cost`` it minimized, and
  ``cases``: for each case its cost, the ``components`` that make it, its ``params_hash``, its run,
  its ``error`` and a free ``detail``. A cached trial reads ``components`` and the cost, and never the
  run of another session.
- The key of the trial cache reads the code by a fingerprint per layer, and the configuration as it
  was written. A release that touches no computing code keeps ``--resume`` and the cache working, and
  a refusal of ``--resume`` names the member of the key that differs.

A calibration session and its promoted run are siblings, ``sessions/<case>/`` and
``runs/<case>/``, with the same version: the session reserves ``N`` and the promoted run takes it.
The link between the two is ``manifest.lineage.session_id`` and ``best.cases.<case_id>.sim_id`` of
``session.json``; the identical name is a convenience for ``ls``. In a joint session a run takes
the name of its case. A case of calibration is done when its ``session.json`` says ``completed`` for
the config hash of the plan.

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
     - ``hmp campaign array``
     - no
   * - ``summary/by_case.*``, ``by_site.*``, ``catalog.csv``, ``exports/``, ``report/``,
       ``README.md``
     - flat views of the index and of the best case of each site
     - ``hmp campaign collect``
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
``[A-Za-z0-9_]+``, ``-`` is the separator and nothing else, and a recipe ending in ``.v<N>`` is
refused.

A run name and a project name follow one rule, ``check_name`` in ``hydromodpy/core/state/names.py``. A name holds ``[a-z0-9_-]``, forty characters at most without
its ``.vN`` suffix, and is not a name Windows reserves for a device (``con``, ``prn``, ``aux``,
``nul``, ``com1`` to ``com9``, ``lpt1`` to ``lpt9``, alone or before a dot). A name that a person
writes (``[simulation] name``, ``name=``, ``--case``, ``hmp project new``, the target of a
rename) and that breaks the rule is refused with an error of code 14, and the sentence proposes
the folded name. A name the code makes from a text that is not a run name (a file stem, the
``case_id`` of a plan, a name of the validation cases) is folded to ASCII and lower case, then
refused when it is still too long or reserved, and a plan whose two cases fold to one name is
refused. Nothing is cut, because two long names with one prefix would fall into one folder. The
rule holds for every name a run takes or continues, so a folder written by 2.0 with capital
letters can still be read and opened, and cannot be continued. No output path carries the
``sim_id`` or a part of it.

**A run launched with** ``--set`` **or** ``--overlay`` **keeps its name.** The override is written
in the frozen ``config.toml`` and in ``manifest.lineage.overrides``, and the version suffix takes
the collision. ``--case <name>`` names the variant for whoever prefers a telling name.
``hmp calibrate`` takes the same three flags: its session and promoted run keep the name of the
file the user named, or ``--case``.

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
of :mod:`hydromodpy.core.state.result_dirs`.

**An identical case is skipped from disk**: the worker reads ``identity.config_hash`` in the
``manifest.json`` of the versions of ``runs/<case>``, never the index. The field holds the solution
key, and ``config.hash`` of the same block holds the same value. A plain run, which is not a
resume, a partial window, a forced run or a replay, whose solution key equals the key of a sealed
run of the same stem, is not computed: the claim is withdrawn without a trace and that run is
given back. ``hmp run`` and ``hmp calibrate`` skip, and no other verb does. Before it gives the
run back, the skip checks that each file of an API source that the ``inputs.json`` of that run
cites is still in the cache with the same sha256, because such a source is fetched after the
identity is known and enters the request by its declaration. ``if_exists`` is ``version`` or
``fail``, and ``fail`` is tested after the skip, so an identical run is always given back.

Two fingerprints say whether two runs compute the same thing
(``hydromodpy/results/request_identity.py``). The request id says what a run asks for. It is the
sha256 of the document as a file writes it, so a key written at its default value is another
request than no key. It leaves out ``[workspace]``, ``[workflow]``, ``simulation.name``, every
``deliver_to`` key, the mesh the run builds and ``[resolved_at_build]``. Each input enters by the
digest and the state of its bytes in place of its path, a URL by its pinned sha256 in place of its
address, and a window that starts from an earlier state adds the digest of the ``final_state/`` of
the window before. The edition of the defaults enters too, and a run leaves its ``[calibration]``
out while a session keeps it. The solution key says what computes the answer. It is the sha256 of
the request id, the fingerprint of the code that computes
(``hydromodpy/core/code_fingerprint.py``), the mesh engine with its version, the sha256 of each
solver binary and the versions of the numeric packages. The code fingerprint holds one digest per
layer that changes a number, over the tokens of each module, so a comment, a docstring or a
reflow moves nothing and a figure or a command is out of its scope. A default that moves is seen
through that fingerprint. The table is in ``provenance.json``, block ``tool``, so two runs that
differ say in which layer. The sha256 of a binary is kept in memory by resolved path, size and
time, so a plan of thousands of cases reads each binary once.

The composition is the one of 2.1. A run or a session sealed by 2.0 carries a key made another way,
so the first identical request that 2.1 meets is computed once more.

The request id reads the run a case starts from by the arrays it takes. A ``restart_from``, and a
``run`` of a ``[[mesh.refinement_zone]]``, name an earlier run. The request id takes the sha256 of
what the step reads from that run, never its name or its ``sim_id``: for a restart the head and
the lake stages of its last step, as float64 values with their shape, and for a zone the fields
the mesh reads. So two runs that leave the same state give the same request, and a later version
of the source run that changes its state gives another one. A reference is a store path, a run
name with or without ``.vN``, a full ``sim_id`` or a prefix of eight characters at least. The
frozen ``config.toml`` keeps the pin ``{sim_id, path}`` of the run, and the lineage keeps its
``parent_sim_id``, because ``sim_id`` carries the lineage and is part of no identity. The frozen
``config.toml`` of a run whose mesh read an earlier run writes the ``sim_id`` of that run in the
zone, taken from the ``zone_runs`` of the mesh summary, so a replay reads the same run. It stops
with a message when that run is no longer in the project.

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
``launcher.lease``, ``hydromodpy.lock``), an integer (``manifest_version``, ``provenance_version``,
``annotations_version``), ``schema`` on the ``checks`` block of a manifest,
``zarr_schema_version`` on a store, ``hmp.schema_version`` on a Parquet table, or the
``schema_version`` row of the index. The documents of a job directory carry a ``schema`` id of
their own, such as ``hmp-outcome/v1`` (``manifest.json``, ``inputset.json``, ``provenance.json``,
``outcome.json``, and ``chain-outcome.json`` at the root of a chain, which the annex writes), and
follow the same rule.

The rule is written once, in :mod:`hydromodpy.core.io.document_version`. Every later 2.x reads
every 2.0.0 document. Each family of sealed documents declares a window next to its current
version, the oldest version it reads and the current one, and the two are equal at 2.0.0. A
change that a reader can ignore (a new optional key, column or array) does not change the
version. A change it cannot ignore raises the current version, keeps the oldest one and brings
the reader of the old version with it. Nothing upgrades a stored document to another version:
a sealed file stays as it was written.

``tests/regression/frozen_runs/`` holds this promise. It keeps a run and a calibration session as
2.0.0 stored them, and the same with a key, a column and an array that a later 2.x could add. Each
commit reads both by the public path and compares the values.

A reader refuses a document outside the window, and the message names the version read, the
version that wrote it when known, what this code reads and what to do:

- newer than the window: upgrade HydroModPy to read it;
- older than the window, or with no version: a pre-release wrote it, so it must be run again;
- the lockfile: ``hmp data lock`` writes it again.

Two kinds of document keep one exact version, because what they hold can be made again:

- the index: ``hmp catalog reindex`` rebuilds it from the directories;
- a transient document (pulse, facts, step journal, lease): delete it and run again.

Inside the window a document written by a later 2.x reads. Models refuse an unknown key when
they write, and every read of a stored document accepts one, at any depth
(:func:`~hydromodpy.core.config_kit.stored.read_stored`). Some documents stay alive after they
are written: ``annotations.json``, ``outcome.json``, ``session.json``,
``phases/<p>/session.json``, the lines of ``trials.jsonl`` and the ledgers. The commands that
own them write them again, at their version, and such a rewrite keeps the keys it does not
understand (:func:`~hydromodpy.core.config_kit.stored.dump_stored`), so a later 2.x finds what
it wrote. The published JSON Schemas under
``hydromodpy/schema/results/`` allow additional properties. A stored field that can grow (a
status, a kind, a regime, a topology) is a string with a written vocabulary: a word outside it
is refused when the model is built to be written, and any word reads back. An append to a
Parquet table keeps a column this code does not declare, and its own rows read it as null.

Where a list or a decision reads a run or a session (``hmp project show``, the cases of ``hmp
project status``, the skip of a case that is done, the trash, the gc, the session ``hmp report
render`` picks when none is named), a document this code cannot read costs one warning naming it
and is left out (:func:`~hydromodpy.results.storage.json_io.readable`). A manifest whose body its
model refuses counts as one that cannot be read, at any version, and ``read_manifest`` and
``read_seal`` read it the same way. A case with an unreadable run is not done, and running it
takes a new version beside the one left out. A session counts as read when its descriptor, its
phases and its journal all read.

The seal says that a run is complete, so a document beside it never takes the run out of a list
(:func:`~hydromodpy.results.storage.json_io.beside_seal`). An ``outcome.json``,
``annotations.json`` or heartbeat of a sealed run that is newer than the window, or damaged, costs
one warning naming it. The run stays in the index, in ``hmp catalog ls``, ``hmp export``, ``hmp
project status`` and the gc, as ``completed``, with what its seal gives. The seal does not say the
host, the process or the last step, so these stay empty, and the tags and notes stay out of the
index while the file stays on disk. A newer outcome inside the window reads, and its unknown keys
are kept.

A gesture that names one document keeps the refusal: ``hmp.open``, ``hmp calibrate --resume``,
``hmp report render <session>``, and the plan ``hmp project status`` reads, because without its
plan the command knows no case.

The one migration of a file HydroModPy keeps is the grammar of a configuration. It is the
``[[migration]]`` rows of ``document = "config"`` in the register of changes,
``hydromodpy/schema/changes.toml``, applied on load by ``config/config_migration.py``;
``hmp doctor --fix-config <file>`` rewrites the file in place. A stored document that changes
its shape, such as a sidecar or the field store, has its own row, ``document = "<id>"``, that the
reader of that document applies. A key that only a pre-release of 2.0 wrote has no row. It is
listed in ``config/prerelease_forms.txt`` and refused, with the way to the doctor of a 2.0.x
release. A file another one inherits stays as it is when its rewrite hangs on a key only
that child writes, since a sibling can write another one, and the doctor says what to write.
``tests/unit/results/test_every_document_carries_its_version.py`` holds the rule and lists the
exempt files with their reason.

Attempt protocol
----------------

A case is run by one worker process, ``hmp run <case>.toml``, which decides alone, from the disk,
to skip, resume or version.

1. The worker first loads the document with its base, checks the environment and checks the run
   name. A refusal there leaves nothing on the disk. Its first act after that creates
   ``runs/<case>/`` and writes the initial ``outcome.json`` (``running``), before geography, data
   or mesh. The claim carries a uuid ``sim_id`` and no identity.
   Then the worker writes ``request.json`` when the request came as JSON or as a dict, writes
   ``config.toml``, resolves the inputs to files with a digest, and writes the ``request_id`` into
   ``outcome.json``.
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
   ``trials.jsonl`` stay. ``--fresh``, or a changed request id, moves the whole content under
   ``attempts/<k>/`` and starts over. An asked ``--resume`` never starts over: its checkpoint
   refuses a configuration that moved and names the sections that did.
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
#. no ``outcome.json``: ``unknown``;
#. a ``manifest.json`` or an ``outcome.json`` this code cannot read: ``unreadable``.

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
``zarr_schema_version = "4"`` in its root attributes. The store is staged
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
derived field is ever written there. A MODFLOW 6 run writes
``derived/hydraulic_conductivity_k33`` every time, and ``derived/hydraulic_conductivity_k22``
and ``derived/conductivity_tensor_angle1`` to ``angle3`` when the flow sets them. All of them
are fields of ``run.field``.

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
(:mod:`hydromodpy.core.fields.precision`): a value moves by at most 2**-17
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
MODFLOW-NWT and Boussinesq, ``storage_ss`` and ``storage_sy`` under MODFLOW 6). Each term has
a descriptor in :mod:`hydromodpy.results.field_registry`, so it can be listed,
exported and read with ``run.field``. The group carries two attributes that
say what the run kept (:mod:`hydromodpy.core.budget.terms`):

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
``drain_accumulation_flux``, ``release_accumulation_flux``, ``budget_flux_per_area`` and
the solute fields ``concentration_seepage``, ``mass_seepage`` and
``mass_seepage_running_sum``. Nothing time-varying is written under ``derived/``. A
store written before holds some of these arrays under ``derived/`` (in
float64 for ``release_flux`` and ``budget_flux_per_area``), and every reader
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
``face_node_connectivity``, ``z_interfaces`` and ``topology``, ``mesh/`` holds the arrays below.
The vertical geometry follows the table.

.. list-table::
   :header-rows: 1
   :widths: 22 12 18 48

   * - Array
     - dtype
     - Axes
     - Content
   * - ``node_x``, ``node_y``
     - float64
     - ``node``
     - The first two columns of ``vertices``, one array per axis, which is what UGRID asks for;
       ``node_coordinates`` of ``topology`` names them
   * - ``crs``
     - int32
     - none
     - A copy of the root ``crs``, written when the run has one, so that ``mesh/`` read alone
       still has its CRS
   * - ``face_x``, ``face_y``
     - float64
     - ``face``
     - Cell center, by the one center rule of the mesh; the attribute ``center_kind`` says
       ``generator``, ``cell_center``, ``vertex_mean`` or ``interior_point``
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
   * - ``z_interfaces``
     - float64
     - ``layer_interface``, ``face``
     - The elevation of every interface of every cell, from the top of the first layer to the
       bottom of the last one
   * - ``idomain``
     - int8
     - ``layer``, ``face``
     - The activity of the solved model: 1 active, 0 inactive, -1 vertical pass-through; the
       attribute ``flag_values`` lists them. It is a static field of ``run.field`` and of
       the exports

**Version 4.** ``zarr_schema_version`` is 4 since every budget flux of every solver has the sign
of MODFLOW, negative when water leaves the aquifer. Boussinesq stored ``drain`` and
``surface_excess`` positive before. Both bounds of the window of the versions are 4, so a store of
an alpha is refused and must be run again.

**Vertical geometry.** Since version 3 a run stores the vertical geometry of
every cell. ``mesh/z_interfaces`` has one column per cell, where it held the column of cell 0
before, and ``mesh/idomain`` holds the ``idomain`` of the solved model, so a column whose first
layer is pinched out reads back as it was solved. The attribute
``vertical_layout`` of ``mesh/`` says how the layers were built, ``column_fractions`` for shares
of the thickness and ``surfaces`` for the base surfaces of ``[domain.layers]``. MODFLOW 6,
MODFLOW-NWT (from ``IBOUND``) and Boussinesq write them, and ``run.mesh.z_interfaces`` is always
one column per cell. Layers are counted from 0 everywhere: a layered field is one variable with a
``layer`` dimension in NetCDF and one array with a component per layer in VTU, at any number of
layers, and a message names layer, row and column from 0. A store below the window of its family is
refused when it is opened, and must be run again (the rule of the versions of the stored documents,
above).
The array ``idomain`` is never rounded, and a reader that needs the top active cell of a column
takes ``top_active_layer`` of ``hydromodpy/core/fields/vertical_column.py``.

The attributes of ``mesh/`` add the ``engine``, its ``engine_version``, its ``engine_seed`` when it
draws random numbers, the ``mesh_request_hash``, the ``crs`` (WKT) the vertices are expressed in,
the mesh ``qa`` (JSON, no ``NaN``), the ``library_versions`` the mesh depends on, the
``vertical_layout`` and, on a regular grid, ``structured_shape``. The edge arrays are the UGRID ones, with the same fill value as
xugrid, so ``xugrid.Ugrid2d`` takes them as stored. A family has one bit, so a mesh holds at most 31
families. ``cell_family_bits`` and ``edge_family_bits`` of ``results/zarr_store/mesh_layout.py``
compute the two bit fields. The order along a river, which a bit field cannot keep, is in the ``mesh_cell_families``
table (``family``, ``chain_id``, ``position`` from upstream, ``cell_id``, and ``offset_m``, null
when the engine publishes no offset for the chain); the faces of the face-intent families (lakes, geology, the
``boundary:*`` sides) are in ``mesh_face_families`` (``face_row``, ``family``, ``edge_id``, the two
nodes, the cell on each side and the zone names). A run whose mesh has no such family writes no
table: an absent table is an empty one when the ``engine`` attribute is present. All of this is
additive. A run sealed before it has none of these
arrays, no ``engine`` and no ``crs`` attribute on ``mesh/``; its readers say so and do not
rebuild them.

**Read by UGRID tools.** ``mesh/`` opens in xugrid as it is stored, with
``xugrid.UgridDataset(xarray.open_zarr(store, group="mesh"))``. A tool that reads NetCDF and not
Zarr, such as QGIS or ParaView, reads the NetCDF export, which carries the same topology.
``node_x``, ``node_y``, ``face_x`` and ``face_y`` carry ``standard_name``
``projection_x_coordinate`` or ``projection_y_coordinate``, and ``face_node_connectivity``
declares ``_FillValue = -1`` for the padding of the short rows. On a run with a CRS, ``topology``
and these coordinates name the ``crs`` of the group in ``grid_mapping``. ``node_coordinates`` of
``topology`` names ``node_x node_y``, where it named ``vertices`` before, and ``vertices`` stays
for the readers of HydroModPy. Its third column, z = 0 for a planar mesh, gets no array of its
own.

**Routing descent.** A MODFLOW 6 or MODFLOW-NWT run stores the descent D it was built with under
``mesh/``, one value per face and none rounded: ``descent_receiver``, ``descent_surface``, the
masks ``descent_base_level``, ``descent_constant_head``, ``descent_raised``, ``descent_channel``
and ``descent_pinned``, the list ``descent_dam_foot`` and the mask ``descent_basin``, the basin of D
at the catchment outlet, whose attributes name the outlet cell (``descent_outlet``), the rule that
found it (``basin_rule``), the area (``basin_area_m2``), whether D was seeded at the outlet
(``basin_seeded_at_outlet``) and the rule version (``basin_version``). The attributes of
``descent_receiver`` name the neighborhood and carry the build report. The solver build leaves D
and its basin in the solver folder as ``<model>.descent.npz`` and the extractor copies them into
the store right after the mesh. ``run.descent`` reads them back, and the flow direction map and ``drain_accumulation_flux`` route on it
(the contract of D is in :doc:`solver/backends`). A Boussinesq run stores the mesh of its
setup like any other and stores no D: its readers rebuild D from the stored top, as for a run
sealed before D was stored. The
arrays are new datasets. A run sealed before D was stored has no
``descent_*`` array, and its readers rebuild D from the stored top, with no channel pin, no
constant-head seed and no lake. A run sealed with D but before ``descent_basin`` has no basin, and
each reader of the catchment says which older support it falls back to.

**Catchment fraction.** When the basin of D closes a catchment and the run has a delineated
polygon, the store also holds ``mesh/catchment_fraction``: a float64 value per face in [0, 1], the
share of the area of the face that lies inside the polygon, with ``units = "1"``. A cell inside the
polygon has 1. The build writes it with ``descent_basin`` and the sidecar of D carries it. It does
not change the basin, which stays all or nothing, and it weights the total over the catchment of a
quantity that varies in space (``hydromodpy.results.derive.views.catchment_total``, see
:doc:`/theory/mesh`). The sidecar and the store refuse a fraction with no basin, a value outside
[0, 1] and an array of another size than the mesh. A run sealed without it, or without a polygon,
counts the whole cells of its basin of D, and its readers say so. A synthetic domain has no polygon and no outlet,
so it stores no fraction, its basin is the largest one of the domain, and its budget has the
domain row only.

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
``forcing/recharge_recharge``.

A gridded recharge also keeps its spatial mean as a station-shaped series under
``forcing/recharge/catchment``, like a gridded runoff, so a reader of
``forcing/recharge`` finds a series whatever the source is. A run whose solver holds
its recharge on the model stamps ``criterion_mean_recharge_m_s`` on the ``forcing``
group: the mean recharge its trials score with, which a figure reads back.

Per-run Parquet directory
-------------------------

Parquet format ``2.6`` written through ``write_table_atomic`` (temporary
file plus ``os.replace``) with ZSTD level 5, 50 000-row groups, page
index and bloom filters on the primary-key columns where the linked
pyarrow build supports them. Each file carries
``hmp.schema_version = "v3"`` plus its schema name, primary key and the
run's ``identity`` block in Parquet key-value metadata, and is exposed as a DuckDB
view named after the payload.

The container directory is ``tables.parquet/`` and the payloads inside
are plain ``.parquet`` files. No suffix marks a container.

The payloads are ``simulation``, ``parameters``, ``metrics``, ``timeseries``, ``budgets``,
``mass_balance``, ``observation_points``, ``sfr_reaches`` (the resolved SFR reach geometry, the
only record of which cell carries which reach, absent when the run built no stream network; its
``reach_id`` is the ``station_id`` of the reach in ``timeseries`` and its ``reach`` counts from 1, as
the TOML does),
``soil_budget`` (one row per soil column and calendar year, absent outside soil mode),
``mesh_cell_families`` and ``mesh_face_families`` (the line families of the mesh, see the cell
mesh above), ``provenance`` and the GeoParquet 1.1 layers ``geographic_*``. Their columns are generated in
:doc:`generated/storage-tree`. ``timeseries`` keys a series on its ``source``, ``simulated`` or
``observed``, so a series and its gauge carry one variable name. A series of a backend
(``discharge``, ``reservoir_storage`` of the ``linear_reservoir`` backend) carries the shape
``time`` of the field registry: one value per period of the time grid, stored at the
``catchment`` station. A run also stores the series it
simulates at each observed gauge, piezometer or lake, under the id of the station. A read with no
station means ``catchment`` when it has the variable. A table says ``catchment`` for the
whole catchment and ``domain`` for the whole model (:doc:`/understand/conventions`), and writes every
``unit`` in udunits spelling.

``simulation.parquet`` is written by the run from its ``RunRecord``: it carries ``project``,
``site``, ``site_fingerprint``, ``recipe``, ``case_id``, ``rel_dir``, ``attempt``, ``attempt_id``,
the flattened ``checks``, ``nse`` and where it was read (``score_station``, ``score_variable``) and
``metric_rule_version``. ``score_window_start``, ``score_window_end`` and ``n_samples`` give the window
and the pairs of the headline score. A promoted run carries the cost of its case in
``calibrated_by_metric`` and ``calibrated_by_cost``, and ``calibrated_by_window_start`` and
``calibrated_by_window_end`` span the periods of role ``calibration`` its case read. Without a
declared gauge and window, ``nse`` is null.

``metrics.parquet`` holds one row per metric, station, variable and period, keyed on ``sim_id``,
``station_id``, ``variable``, ``metric`` and ``window_name``. The scores of a run and the numbers of
the run itself (``variable = "runtime"``, with no period) both land there, through one writer. The
period ``metrics`` is ``[metrics] window``, of role ``evaluation``, and it is the headline: a reader
that wants one row per metric filters on it, so a validation period can sit beside it.
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
- A fetched file is written through ``<name>.part`` and ``os.replace``, then its sidecar the
  same way. A station chronicle is written under a ``filelock`` named after the station
  (``.<prefix>_<source>_<id>.lock`` in the folder of the variable), so two cases that fetch the
  same station write the same bytes in turn and no case needs a private cache.
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

``hydromodpy.lock`` pins the data cache and the files of the user of a project. It is a TOML
document with the id ``schema = "hydromodpy.lock.v2"``, read by the same version rule as the other
documents, and it is meant to be committed and to travel, so it holds no path of the machine that
wrote it. It is read from the sidecars of ``data/`` by ``hmp data lock``, and a file written under
``hydromodpy.lock.v1`` is refused with the order to write it again.

- ``[hydromodpy]`` holds the ``hydromodpy`` version, the git commits, the Python version and the
  sha256 of the config schema.
- ``[[input]]`` is one record per row of the cache, and one per file of the user that the project
  declares: ``variable``, ``source``, ``station_id``, ``product``, the ``path``, ``sha256``,
  ``bytes``, ``license`` and ``fetched_at``, the instant of the snapshot. The path of a row of the
  cache is relative to ``data/``, the path of a file of the user is relative to the project root.
  A station that answered nothing is a record with ``empty = true`` and no ``sha256`` nor
  ``bytes``, whose path is the name its sidecar describes, so a frozen replay serves it too.
  Everything that reads the lock reads this record: the check of ``--frozen``,
  ``hmp data lock --check``, a restored archive and the frozen matching of the data cache.

The ``prepare`` phase writes it once per plan, never each run.
``hmp run --frozen`` refuses any source whose fingerprint changed since, and checks the lockfile
read-only.

The inputs of one run are sealed in its own ``inputs.json``: one entry per loaded variable with
its provider, product, product version, the full request (extent, period, stations, step),
``fetched_at``, path, SHA-256, size and licence. A replay never depends on the project-wide file.

``hmp run <run>/config.toml --frozen`` replays from that record alone. Before anything runs it
refuses an input whose digest differs from ``inputs.json`` or from ``manifest.json``, naming the
file and both digests, and a configuration that differs from ``config.resolved.toml``, naming each
key and both values. A key that this version added, absent from ``config.resolved.toml`` and
at the default of the edition the run sealed, is no difference: the sealed file writes every
default its version knew, so the key is one that version did not know. ``lineage.drift`` lists
such keys under ``new_at_default``. It warns when the solver binary is not the one ``provenance.json`` records,
naming both versions. Once it has run, it says what its build decided otherwise and which file it
read that the source did not. ``hydromodpy.lock`` keeps its role for a project TOML.

A replay never writes into the run it replays. A ``config.toml`` under ``<project>/runs/<name>/``,
or in a kept trial of a session, answers for ``<project>``, with or without a ``project.toml``. A
copy of a run outside any project is refused, and the refusal names the way out,
``hmp run <copy>/config.toml --frozen -w <project>``: the new run goes to that project and reads
its inputs there.

The configuration of a sealed run is two files. ``config.toml`` holds what the run was given,
overrides included, written once at the claim from the loaded configuration, so a run that fails
before the mesh can be resumed. It holds the keys as written, so a validator that tells a written key from its default answers on it as it
did on the run. ``config.resolved.toml`` holds every key with its value, ``edition`` included, and is never read
back as a configuration. A resolved file without ``edition`` reads as edition 2.0. Its body adds what a rule derives from the configuration alone, by the rule the
builders use: ``geographic.terrain_engine``, ``mesh.lake_refinement.shoreline_band`` and
``hfb_buffer``, ``metrics.station``. Its table ``[resolved_at_build]`` holds what the build decided:
the ETP the data step injected, with ``surface_offset_m`` and its reference, the cell sizes the mesh
took from the DEM pixel (``pixel``, ``cell_size``, ``river_cell_size``, ``river_band``), and the
station a run deduced. What the solver adapter decides later goes to ``provenance.json``, block
``solver.options``: the IMS complexity and the XT3D decision of MODFLOW 6.

A run describes its own solve. The run a calibration promotes, a kept trial and the best of a phase
write the parameters they ran with, ``[workflow] mode = "simulation"`` and no ``[calibration]``, so
a replay solves once and searches nothing. ``lineage`` and ``checks.calibrated_by`` name the session.
The ``[calibration]`` section goes to the table ``[searched_under]`` of ``config.resolved.toml``,
where a redraw of the network criterion reads it, so a copy of the run needs no session.

Publishing and packages
-----------------------

``hmp publish <ref> --to <dir>`` copies ``README.md``, ``config.toml``,
``config.resolved.toml``, a redacted ``provenance.json``, ``inputs.json``, ``manifest.json``, ``figures/``, ``exports/`` and
``report/``, generates ``ro-crate-metadata.json`` and writes ``PUBLICATION.json`` (the source
project, relative directory and ``sim_id``, the SHA-256 of the manifest and of every copied file,
the label and its date, the version, the date). ``--with results`` adds the stores and
``--with inputs`` the install index ``INSTALL.toml`` (``hydromodpy/core/payload/``) and the bytes
of every file the run read, addressed by content under ``inputs/``, sidecars included. The source
receives one line in ``published.jsonl``. ``.hmp/``, ``logs/``, host, user and absolute paths
never leave: one function redacts every copy.

The portable package **is** ``hmp publish --with results --with inputs --container tar``. Importing
it (``hmp catalog import``) installs every file of ``INSTALL.toml`` into ``data/`` of the
workspace (identical bytes cost nothing, other bytes at one path are refused by name), merges the
station rows, completes the sidecar of each delivered file from the table of the index and
writes the site in ``data/sites/catalog.csv``, then extracts the run under ``runs/`` and runs an incremental
reindex. ``hmp publish --package`` writes a whole project on the same index, and
``hmp project import`` installs it as ``projects/<name>``.

Reading one cell
----------------

A finished run answers for one precise cell, after the fact.
``hydromodpy/results/run/point.py`` binds the point-to-cell lookup
(``results/spatial_index``) and the on-the-fly derivations
(``results/derive/virtual_fields``) to a run, and exposes the gesture as
``run.probe.series`` and ``group.probe.series``. The cell is named by
project-CRS coordinates, by its zero-based index, or by a depth in
meters below the local model top that picks the layer. A virtual field
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
(``hydromodpy/solver/base/observation_config.py``) validates the
ids and the vertical selector; the run samples the points at the end of
extraction, while it still holds its fields
(``workflow/steps/run_outputs.py``,
``sample_declared_observation_points``). A declaration mistake is logged
and skipped: it must not lose a run whose results are already in.

Both halves of a declared point are run artifacts. The series lands in
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
neighboring cells it never uses. A cell-major layout, or a second copy laid out that way, would
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
