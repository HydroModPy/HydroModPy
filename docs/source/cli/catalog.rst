hmp catalog
===========

The :command:`hmp catalog` family inspects, queries, and maintains the
DuckDB + Zarr catalog of a workspace. All actions auto-detect the catalog
root by walking up from the current directory; pass ``--workspace`` to point
at a different project.

A run is addressed by **reference**: its name (``cheze_baseline``), a versioned
name (``cheze_baseline.v3``), a unique UUID prefix (``9c41aa02``), the full
UUID, or a selector (``@last``, ``@last~1``, ``@best:nse``, ``@worst:rmse``,
``@running``). A bare name resolves to the latest version of that stem.

Inspecting (read-only)
----------------------

ls
~~

Synopsis: ``hmp catalog ls [--solver <name>] [--catchment <name>] [--project <label>] [--status <code>] [--tag <tag>] [--limit N] [--format table|json|csv]``

List simulations, one row per run with the name, short id, status, solver and
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

Run a raw SQL statement against the catalog DuckDB, read-only, for ad-hoc
exploration beyond the canned filters.

Example::

   hmp catalog query "SELECT solver, COUNT(*) FROM simulations GROUP BY 1"

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

Rename a run. The on-disk storage basename is id-only and never moves, so a
rename is a pure catalog update.

Lifecycle
---------

delete
~~~~~~

Synopsis: ``hmp catalog delete <ref> [--now] [--force] [-y]``

Move a run to the trash (reversible; storage stays in place). ``--now`` purges
it permanently (cascade + storage removal); ``--force`` acts on a pinned run.

Example::

   hmp catalog delete ksweep/trial-004 -y
   hmp catalog delete ksweep/trial-004 --now -y

restore
~~~~~~~

Synopsis: ``hmp catalog restore <ref>``

Bring a trashed run back. If the original name was reused, the stem is
version-bumped so the restore never collides.

trash
~~~~~

Synopsis: ``hmp catalog trash [--empty] [--force]``

List trashed runs, or permanently empty the trash with ``--empty`` (pinned runs
are skipped unless ``--force``).

gc
~~

Synopsis: ``hmp catalog gc [--apply]``

Plan, by default, the garbage collection of orphan caches, tmp parquet and
stale ``running`` rows. It only reports unless ``--apply`` is given (the safe
inverse of the old destructive default). ``gc --apply`` also compacts the
DuckDB file and consolidates Zarr metadata, the maintenance formerly exposed
as the separate ``vacuum`` verb.

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

Re-launch a run from its stored config snapshot, applying dotted-path overrides.

Example::

   hmp catalog rerun cheze_baseline --set flow.hydraulic_conductivity=2e-4

Schema maintenance
------------------

The catalog schema is migrated by :command:`hmp doctor --migrate`. Inspection
commands open the catalog read-only and never migrate it; a catalog whose
schema is behind is reported with that hint. Legacy project TOML keys are
migrated in place by :command:`hmp doctor --fix-config FILE.toml`.
