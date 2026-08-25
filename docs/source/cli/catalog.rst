hmp catalog
===========

The :command:`hmp catalog` family inspects, queries and maintains the runs
of a project. It reads the project index at ``<project>/.hmp/index.duckdb``
and the run directories under ``<project>/runs/``. All actions auto-detect
the project root by walking up from the current directory to the first
``project.toml``; pass ``--workspace`` to point at a different project.

The index is derived data. ``reindex`` rebuilds it from the run
directories, so nothing a run needs in order to be read, replayed or
compared lives only in SQL.

A run is addressed by **reference**: its name (``cheze_baseline``), a versioned
name (``cheze_baseline.v3``), a unique UUID prefix (``9c41aa02``), the full
UUID, or a selector (``@last``, ``@last~1``, ``@best:nse``, ``@worst:rmse``,
``@running``). A bare name resolves to the latest version of that stem.

Inspecting (read-only)
----------------------

ls
~~

Synopsis: ``hmp catalog ls [--solver <name>] [--catchment <name>]
[--project <label>] [--status <code>] [--tag <tag>] [--limit N]
[--format table|json|csv]``

List runs, one row each with the name, short id, solver, status and
duration. Trashed runs are hidden unless ``--status trashed`` is given. The
``json``/``csv`` formats emit a stable 12-column projection (string ids, ISO
dates, no config blobs).

Example::

   hmp catalog ls --solver mf6 --status completed
   hmp catalog ls --tag pinned --format json

show
~~~~

Synopsis: ``hmp catalog show <ref> [--detail] [--format table|json]``

Show one run's identity card: metadata, version, config hash, tags, notes,
parameters and outlet metrics, plus a footer suggesting the next commands.
``--detail`` expands the Zarr store layout.

Example::

   hmp catalog show cheze_baseline.v3 --detail

diff
~~~~

Synopsis: ``hmp catalog diff <ref_a> <ref_b>``

Compare two runs' parameters and outlet metrics, printing only the keys that
differ.

Example::

   hmp catalog diff cheze_baseline.v2 cheze_baseline.v3

watch
~~~~~

Synopsis: ``hmp catalog watch [--stale-minutes N]``

Show the runs currently in the ``running`` state with their heartbeat age and a
``STALE`` flag when a process died without finalizing.

point
~~~~~

Synopsis: ``hmp catalog point <ref>... --var NAME [--var NAME] (--xy X Y |
--cell N) [--layer N | --depth M] [--label NAME] [--timestep N]
[-o FILE.csv|FILE.parquet] [--format table|json|csv]``

Read the value of a variable in one precise cell of a finished run, after the
fact. The cell is named in one of three ways:

- ``--xy X Y``: coordinates in the simulation CRS, resolved to the cell that
  contains them;
- ``--cell N``: the zero-based cell index, when it is already known;
- ``--depth M`` (with either of the above): metres below the local model top,
  which picks the layer from the mesh layer thicknesses. ``--layer N`` sets the
  layer index directly instead.

The answer is one row per timestep and variable (a single row for a steady
run), with the resolved ``cell``, ``layer`` and coordinates so the table stays
self-describing. Virtual fields answer like persisted ones:
``watertable_depth``, ``watertable_elevation``, ``seepage_mask`` and
``outflow_drain`` are rebuilt on read.

Passing several references reads the *same* point on each of them and stacks
the answers, which is the scenario comparison: the ``run`` column tells the
series apart. Coordinates are resolved per run, since two runs rarely share a
mesh.

``-o`` writes the table to ``.csv`` or ``.parquet`` (the extension picks the
format) in addition to printing it.

Example::

   hmp catalog point @last --var head --xy 327816.965 6777886.670
   hmp catalog point @last --var head --xy 327816.965 6777886.670 --depth 30
   hmp catalog point @last --var head --var watertable_depth --cell 2550 --timestep -1
   hmp catalog point cheze_baseline.v2 cheze_baseline.v3 --var head --cell 2550 -o probe.csv

The point-to-cell lookup is cached per mesh, under
``<project>/.hmp/cache/cell_index/<mesh_hash>.json``. The cache is keyed by the
geometry fingerprint of the run, so a different mesh never reuses it, and
deleting it costs only the rebuild.

For a point known before the run, prefer declaring it in ``[observation]``:
it is then sampled while the run still holds its fields, and reading it back
is a plain table read (``run.timeseries("head", station="obs:<id>")``) instead
of a scan of the whole field. See
:doc:`/user_guide/config_reference/observation`.

The Python form of this action is ``run.probe.series("head", x=..., y=...)``,
and ``group.probe.series(...)`` on a :class:`~hydromodpy.results.run.group.RunSet`
for the multi-run comparison.

query
~~~~~

Synopsis: ``hmp catalog query "<SQL>"``

Run a raw SQL statement against the index, read-only, for ad-hoc
exploration beyond the canned filters.

Query the ``v_simulation_summary`` view rather than the ``simulations``
table: the table stores foreign keys (``solver_id``, ``status_id``), the
view resolves them into readable columns.

Example::

   hmp catalog query "SELECT solver, COUNT(*) AS n FROM v_simulation_summary GROUP BY 1"

Annotating
----------

tag
~~~

Synopsis: ``hmp catalog tag <ref> TAG... [--rm TAG]``

Add or remove tags. ``pinned`` is reserved: a pinned run is refused by every
destructive action without ``--force``.

Example::

   hmp catalog tag cheze_baseline.v3 pinned paper-fig4 --rm draft

note
~~~~

Synopsis: ``hmp catalog note <ref> "<text>"``

Append a timestamped note to a run.

rename
~~~~~~

Synopsis: ``hmp catalog rename <ref> <new_name>``

Rename a run. The run directory is named after the run, so ``runs/<old>/`` is
moved to ``runs/<new>/`` and the index is updated afterwards. The target name
must be free: renaming onto a live run is refused rather than merged.

Lifecycle
---------

delete
~~~~~~

Synopsis: ``hmp catalog delete <ref> [--now] [--force] [-y]``

Move a run to the trash (reversible; the run directory stays in place and
is stamped with a ``trash.json`` marker). ``--now`` purges it permanently
(cascade + storage removal); ``--force`` acts on a pinned run. No byte is
freed until the trash is emptied.

Example::

   hmp catalog delete ksweep_trial_004 -y
   hmp catalog delete ksweep_trial_004 --now -y

restore
~~~~~~~

Synopsis: ``hmp catalog restore <ref>``

Bring a trashed run back. If the original name was reused, the stem is
version-bumped so the restore never collides.

Address a trashed run by its id prefix: name resolution only sees live
runs, so ``hmp catalog trash`` first, then restore with the short id it
prints.

Example::

   hmp catalog trash
   hmp catalog restore 56df62a9

trash
~~~~~

Synopsis: ``hmp catalog trash [--empty] [--force]``

List trashed runs, or permanently empty the trash with ``--empty`` (pinned runs
are skipped unless ``--force``).

gc
~~

Synopsis: ``hmp catalog gc [--apply] [--keep-versions N|all] [--max-age-days DAYS]
[--purge-figures]``

Plan, by default, the garbage collection of orphan stores, tmp parquet,
expired trash, stale ``running`` rows, pending purges and orphan
calibration sessions. It only reports unless ``--apply`` is given (the safe
inverse of the old destructive default). ``gc --apply`` also compacts the
DuckDB file and consolidates Zarr metadata, the maintenance formerly
exposed as the separate ``vacuum`` verb.

Retention policy
^^^^^^^^^^^^^^^^

Three rules decide how much run history a project keeps. They are prudent by
default, so a project that never sets them keeps everything but the tail of a
long lineage:

.. list-table::
   :header-rows: 1
   :widths: 26 16 58

   * - Rule
     - Default
     - What it selects
   * - ``--keep-versions N|all``
     - ``5``
     - Every version of one run name beyond the ``N`` newest
       (``cheze``, ``cheze.v2``, ... is one lineage). ``all`` disables it.
   * - ``--max-age-days DAYS``
     - disabled
     - Runs created more than ``DAYS`` ago.
   * - ``--purge-figures``
     - disabled
     - The ``figures/`` directory of each run, which is rebuildable from the
       run outputs.

No rule destroys anything. A selected run is moved to the project trash: a
reversible status flip stamped on disk as ``runs/<name>/trash.json``, undone
by ``hmp catalog restore``. Its bytes are freed later, by the trash-expiry
rule, once the retention window has passed. Selected figures are moved to
``<project>/.hmp/trash/<stamp>/<run>/figures``. A run tagged ``pinned`` is
exempt from every rule.

Example::

   hmp catalog gc                                  # plan only, default policy
   hmp catalog gc --keep-versions 2 --apply        # keep the two newest per lineage
   hmp catalog gc --max-age-days 365 --apply       # also retire runs older than a year
   hmp catalog gc --keep-versions all              # inspect the rest, keep every version

reindex
~~~~~~~

Synopsis: ``hmp catalog reindex [--workspace <path>] [--format table|json]``

Rebuild the project index from what the run directories declare. It walks
``runs/`` and ``sessions/``, reads each ``manifest.json`` and each
``session.json``, and repopulates every table, reporting the run names, the
session names and the row count per table.

Use it after moving a project, after restoring a backup, or whenever
``hmp doctor --toml`` reports that the index row count and the number of
run directories disagree. Deleting ``.hmp/index.duckdb`` loses nothing that
a rebuild cannot restore.

Example::

   hmp catalog reindex

Sharing and re-running
----------------------

export / import
~~~~~~~~~~~~~~~~

Synopsis: ``hmp catalog export <ref> [-o FILE.hmp]`` / ``hmp catalog import <FILE.hmp> [--force]``

Write a run as a portable ``.hmp`` archive (config snapshot, provenance, Zarr
fields, timeseries, RO-Crate) and restore it into any workspace with checksum
verification. The simulation identity survives the round-trip.

Example::

   hmp catalog export cheze_baseline.v3 -o paper.hmp
   hmp catalog import paper.hmp

rerun
~~~~~

Synopsis: ``hmp catalog rerun <ref> [--set PATH=VALUE ...] [--name <name>]``

Re-launch a run from its frozen ``runs/<name>/config.toml``, applying
dotted-path overrides. Without ``--name`` the result is versioned under the
original stem.

Example::

   hmp catalog rerun demo --set flow.param.K.field.value=2e-4 --name demo_k2

Schema maintenance
------------------

The catalog schema is migrated by :command:`hmp doctor --migrate`. Inspection
commands open the catalog read-only and never migrate it; a catalog whose
schema is behind is reported with that hint. Legacy project TOML keys are
migrated in place by :command:`hmp doctor --fix-config FILE.toml`.
