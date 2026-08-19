The three database scopes
=========================

HydroModPy splits SQL state across three scopes: machine, workspace,
project. Each scope owns a DuckDB file with a focused role and an
independent lifecycle.

**None of the three is a place where irreplaceable results live.** Every
one of them is an index or a cache over something else: registered
projects for the machine scope, upstream sources for the workspace
cache, the project's run directories for the project index. The disk is
the source of truth; the databases make it queryable.

This page states the role of each scope. The full on-disk contract, the
three classes of data and the rebuild invariants live in
:doc:`../storage-layout`. For the migration policy applied to every
database below, see :doc:`schema-evolution`.

Machine global index: ``$XDG_STATE_HOME/hydromodpy/index.duckdb``
-----------------------------------------------------------------

Federates every registered project and answers cross-project queries
through read-only ``ATTACH``. Recreated from the registered projects
alone: it carries no science output of its own.

It stores one table, ``projects``, plus its migration ledger. **One row is
one project root**, because a project root is what owns an index database
at ``.hmp/index.duckdb``. A workspace root owns none, so it is never a row:
registering one expands it into the project roots it holds, and a workspace
with no project yet registers nothing.

The federated view ``all_simulations`` is not stored: it is rebuilt at
attach time as a ``UNION ALL`` over each project's ``v_simulation_summary``,
stamped with the ``project_id`` of its row, and a project whose index file
is missing is skipped with a warning.

Exposed through:

- :class:`hydromodpy.core.state.global_index.GlobalIndex`, whose
  ``register`` / ``unregister`` / ``list_projects`` / ``prune`` surface
  speaks in :class:`~hydromodpy.core.state.global_index.ProjectRecord`
- ``hmp.index()`` for machine-wide discovery
- CLI verbs ``hmp workspace register / list / search / forget / prune``
- :func:`hydromodpy.core.state.paths.project_roots_under`, the single place
  that turns a directory into the project roots it stands for

Workspace input cache: ``<workspace>/data/cache.duckdb``
---------------------------------------------------------

Tracks downloaded or custom datasets used as model inputs. One file per
workspace, shared by every project of that workspace. Purgeable, and
reconstructible from upstream sources at the cost of re-downloading.

Tables: ``entries``, ``api_coverage``, ``artifacts``, ``provenance``,
``stations``, ``coverage``, ``failures``, ``validation_reports``, plus
the view ``v_entries_summary``.

Exposed through:

- :class:`hydromodpy.data.registry.DataCatalogDuckDB` (low level)
- :class:`hydromodpy.catalog.InputsNamespace`, opened on a workspace
  root, and the ``hmp data`` CLI
- the ``project.data`` accessor, which scopes the same cache to one
  project

Each row carries a workspace-relative POSIX ``file_path``, so a cache
stays portable between machines.

Project index: ``<project>/.hmp/index.duckdb``
-----------------------------------------------

Indexes the runs of one project: identity, parameters, metrics,
provenance, calibration trace and workflow trace. It is the query layer
over ``runs/`` and ``sessions/``, not their owner. It lives under
``.hmp/`` precisely because that directory is disposable.

The project index is explicitly **not** a store of irreplaceable output.
What a run needs in order to be read, replayed, resumed or compared is
written into its run folder, and the index is derived from it. A change
that makes a result reachable only through SQL is a regression of this
contract.

Exposed through:

- :class:`hydromodpy.results.catalog.Catalog`
- :class:`hydromodpy.results.run.Run`
- :class:`hydromodpy.results.run.group.RunSet`
- ``hmp.open(project_path)``, which returns the ``Catalog``
- CLI verb ``hmp catalog ...``

Rebuilding it
~~~~~~~~~~~~~

``hmp catalog reindex`` reads every sealed run under ``runs/`` and every
calibration session under ``sessions/``, and rebuilds the index from
them. Per run it reads ``manifest.json`` (the seal of a complete run),
then ``tables.parquet/simulation.parquet``, ``parameters.parquet``,
``metrics.parquet``, ``provenance.parquet``, the ``geographic_*.parquet``
features, ``provenance.json``, ``annotations.json`` and ``trash.json``.
Per session it reads ``session.json`` and ``trials.jsonl``. The rebuild
fills a staging database next to the index and installs it with one
atomic rename, so ``index.duckdb`` is never absent nor half-written: a
reader that was reading keeps reading the file it opened, the next
opener gets the rebuilt one, and two rebuilds describe the project
identically. That rename is
:func:`hydromodpy.core.io.atomic_replace.rename_over_open_file`, the
only publishing path: ``os.replace`` on POSIX, and on Windows, where
``MoveFileEx`` refuses as soon as another handle is on the index, the
same rename asked of the kernel with ``FILE_RENAME_POSIX_SEMANTICS``.
There is no non-atomic fallback: where the kernel supports neither, the
rebuild fails, the previous index stays untouched and readable, and the
fix is to close the processes reading the project and rebuild again.
:doc:`../storage-layout` carries the full statement.

The run **name comes from the directory**, never from the files: a
rename moves the directory, so the tree is what the name is. A directory
whose manifest names another run is reported and left out rather than
indexed under a doubtful identity.

What survives a rebuild
~~~~~~~~~~~~~~~~~~~~~~~

The rule is stated once, in :doc:`../storage-layout`, and summarised
here. The authoritative list is the module docstring of
``hydromodpy/results/catalog/reindex.py``, which is the code that
performs the rebuild.

.. list-table::
   :header-rows: 1
   :widths: 20 44 36

   * - Class
     - Content
     - Rebuild behaviour
   * - Reconstructible
     - Run identity and geometry, catchment metadata, parameters,
       metrics, input provenance, run environment, geographic features,
       tracked files, declared observation points, tags and notes, trash
       state, calibration sessions and trials. The frozen
       ``config.toml`` stays in the run folder
     - Obligation: written in the run or session folder, restored
       identically by the rebuild
   * - Losable
     - Audit log, export log, workflow journal, deletion tombstones,
       purge resume state, and the promoted ``sim_id`` back-filled on a
       trial
     - Dropped, by an explicit decision. The runs, their results and
       their lineage are unaffected
   * - Input
     - Observation series and station metadata
     - Out of the results scope. Repopulated from the input cache and
       the data loaders

Two consequences are worth naming. Losing the audit log means the
machine event history of the project is gone, while run identity,
results and lineage survive because they come from the manifests. Losing
the workflow journal means an interrupted workflow replans from scratch
instead of resuming.

Provenance bridge
-----------------

Each run records, in its ``provenance`` rows, which input-cache entries
it consumed. ``run.input_entries()`` walks the bridge to list them, and
``entry.used_by()`` returns the runs that referenced a given entry by
joining ``tracked_files.sha256``. Cross-project lookups go through the
machine index.

Why three scopes
----------------

- **Machine index**: cross-project discovery without copying data.
- **Workspace cache**: input sharing between projects covering the same
  geographic area, so a regional DEM is downloaded once.
- **Project index**: fast queries over one project's runs, scoped so a
  project stays usable while other projects write to the same workspace
  cache.

Three scopes, three rebuild costs: the machine index is recreated from
the registered projects, the workspace cache from upstream sources
(network cost), the project index from the project's own run
directories (local cost). No scope is a single point of loss for a
scientific result.

Shared architecture
-------------------

One set of patterns governs the three databases.

- **Single migrations runner**:
  :mod:`hydromodpy.core.migrations.runner` exposes
  ``apply_migrations(db_path, migrations_dir)``, serialised by a
  ``<db_path>.lock`` filelock, and is used by all three. Each scope owns
  a flat ``migrations/`` directory of numbered SQL files starting at
  ``0001_initial.sql``. Because the project index is rebuildable, a
  schema change there is a new initial DDL plus a rebuild, not a chain
  of migrations: its only later file, ``0002``, drops the unused
  ``retention_policies`` table rather than reshaping one.
- **Per-scope doors**: one entry point per database.
  ``hmp.open(project_path)`` opens the project directory holding
  ``project.toml`` and ``.hmp/index.duckdb``, and returns its
  ``Catalog``; ``hmp.index()`` federates the machine scope; and
  :class:`hydromodpy.catalog.InputsNamespace`, opened on a workspace
  root, reaches the input cache.
- **Backend Protocol**:
  :class:`hydromodpy.results.catalog.ports.CatalogBackend` is a
  ``typing.Protocol`` with ``execute / query / fetch_one / fetch_all /
  insert / upsert / transaction / close``. Catalog mixins call the
  protocol, so swapping the adapter does not touch call sites.
- **Authentication Protocol**:
  :class:`hydromodpy.core.auth.AuthBackend` exposes a structural
  ``current_user / can_read / can_write`` surface, with
  :class:`~hydromodpy.core.auth.LocalAuthBackend` as the V1 default.
- **URI-aware paths**: every workspace, cache and state argument is
  typed ``Path | UPath``. The runtime accepts local paths and ``file://``
  URIs; any other scheme raises ``NotImplementedError``.

See also
--------

- :doc:`../storage-layout` for the on-disk contract, the three data
  classes and the rebuild invariants.
- :doc:`schema-evolution` for the migration policy.
- :doc:`/architecture/packages/results` for the Python surface.
