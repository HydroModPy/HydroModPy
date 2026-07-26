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

Synopsis: ``hmp catalog gc [--apply]``

Plan, by default, the garbage collection of orphan stores, tmp parquet,
expired trash, stale ``running`` rows, pending purges and orphan
calibration sessions. It only reports unless ``--apply`` is given (the safe
inverse of the old destructive default). ``gc --apply`` also compacts the
DuckDB file and consolidates Zarr metadata, the maintenance formerly
exposed as the separate ``vacuum`` verb.

Example::

   hmp catalog gc            # plan only
   hmp catalog gc --apply    # execute the plan

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
