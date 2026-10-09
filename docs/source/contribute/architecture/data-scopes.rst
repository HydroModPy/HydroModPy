Data scopes and schema evolution
================================

HydroModPy splits SQL state across three scopes: machine, workspace,
project. Each scope owns a DuckDB file with a focused role and an
independent lifecycle. This page states the role of each scope, how their
schemas evolve, and which formats are canonical.

**None of the three is a place where irreplaceable results live.** Every
one of them is an index or a cache over something else: registered
projects for the machine scope, upstream sources for the workspace
cache, the project's run directories for the project index. The disk is
the source of truth; the databases make it queryable.

The full on-disk contract, the three classes of data and the rebuild
invariants live in :doc:`storage-layout`.

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
:doc:`storage-layout` carries the full statement.

The run **name comes from the directory**, never from the files: a
rename moves the directory, so the tree is what the name is. A directory
whose manifest names another run is reported and left out rather than
indexed under a doubtful identity.

What survives a rebuild
~~~~~~~~~~~~~~~~~~~~~~~

The rule is stated once, in :doc:`storage-layout`, and summarised
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
it consumed. ``run.input_entries()`` walks the bridge to list them by
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

Schema evolution
----------------

HydroModPy ships a migration runner for the DuckDB files and pins one version on
each columnar store. Covered: the three DuckDB databases, the Zarr field store
(``runs/<name>/fields.zarr/``, Zarr format 3), the Parquet 2.6 outputs, and the
portable ``.hmp`` package. User TOML files are out of scope: Pydantic with
``extra="forbid"`` handles them.

The project index is the exception to the chain-of-migrations model. It is an
index over the run directories, so its schema moves forward by replacing the
initial DDL and rebuilding from disk with ``hmp catalog reindex``, which ships
and is the supported path. The runner still deploys the DDL on a fresh index.

The migration runner
~~~~~~~~~~~~~~~~~~~~

The code is ``hydromodpy/core/migrations/runner.py``, with one migrations folder
per component:

- ``hydromodpy/results/catalog/migrations/`` for the project index;
- ``hydromodpy/data/registry/migrations/`` for the workspace cache;
- ``hydromodpy/core/state/migrations/`` for the machine index.

A migration is a numbered SQL file (``0001_initial.sql``, ``0002_<slug>.sql``, ...).
The runner keeps a ``schema_migrations`` ledger with one row per applied migration
and component, reads the highest applied version, applies every newer file in one
transaction per file, and records a SHA-256 checksum of the SQL. It refuses to go
on when a recorded checksum no longer matches the file.

``ensure_schema()`` on a backend deploys the latest schema for its component, and
``hmp.open`` reaches it on first access, so a user never sees a
half-deployed index. ``hydromodpy/core/migrations/auto_boot.py`` wraps the runner
for boot-time upgrades: a lock on ``<db>.lock``, and for the workspace cache an
atomic ``<db>.bak-<timestamp>`` snapshot that is restored on failure, with at
most five kept. The ``catalog`` and ``index`` components skip the snapshot, listed
in ``NO_BACKUP_COMPONENTS``, because an index is rebuilt and not restored
(``hmp catalog reindex`` for a project, ``hmp workspace register`` for the machine).
``HMP_AUTO_MIGRATE=0`` turns a pending migration into ``AutoMigrationDisabled``
and leaves the file untouched.

Rules for a change
~~~~~~~~~~~~~~~~~~

1. **One version per component.** Each DuckDB has its own ledger row. Each Zarr
   store carries ``zarr_schema_version`` in its root attributes. Each Parquet file
   carries ``hmp.schema_version`` in its key-value metadata. SQL and columnar
   versions never share a number.
2. **Additive first.** Prefer ``ALTER TABLE ... ADD COLUMN`` with a default to a
   deletion or a rename. Zarr fields only grow.
3. **Monotone numbering.** Integers, one by one, no gaps. A migration is a
   one-way door; downgrades are not supported.
4. **A round-trip test for every migration.** Start from a minimal hand-built
   ``v(n)`` fixture, check that the migrated ``v(n+1)`` store reads with the
   current backend, and check that applying the migration twice changes nothing.
5. **A reader-breaking change bumps the version.** A change of shape, dtype,
   column order or meaning of an existing field needs a bump and a migration. A
   refactor that does not touch the disk does not. The float width of a Zarr field
   is the exception: ``float32`` (``field_precision = "compact"``) and ``float64``
   (``"exact"``) is a per-store choice written in each array's metadata, and every
   reader returns ``float64``.
6. A ``.hmp`` archive carries ``format`` and ``format_version`` in its manifest
   and a SHA-256 for every file. Import checks the magic and every checksum before
   it writes anything. It does not gate on ``format_version``, so a package written
   by a newer library shows up only when a checked file fails to read.

Do not silently accept an unknown table or column, and do not inject data from
outside a migration: it works only on the handle it is given.

Where each version is declared
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The values are in the code. Read them there, not here.

.. list-table::
   :header-rows: 1
   :widths: 34 66

   * - What
     - Where
   * - Project index, workspace cache, machine index
     - The highest numbered file of each ``migrations/`` folder above.
   * - ``ZARR_SCHEMA_VERSION``
     - ``hydromodpy/results/zarr_store/constants.py``
   * - ``PARQUET_SCHEMA_VERSION``
     - ``hydromodpy/results/storage/parquet_schemas.py``
   * - ``GEOPARQUET_SCHEMA_VERSION``
     - ``hydromodpy/core/io/geoparquet.py``
   * - ``MANIFEST_SCHEMA_VERSION`` (run seal: ``manifest.json``, ``provenance.json``)
     - ``hydromodpy/results/manifest.py``
   * - ``SESSION_JOURNAL_VERSION`` (``session.json``, ``trials.jsonl``)
     - ``hydromodpy/results/session_journal.py``
   * - ``TRASH_VERSION`` (``trash.json``)
     - ``hydromodpy/results/trash_marker.py``
   * - ``HMP_FORMAT_VERSION`` (``.hmp`` package)
     - ``hydromodpy/results/exporters/hmp_package.py``

.. _artifact-policy:

Artifact policy
---------------

DuckDB, Zarr and Parquet are the canonical stores. Other formats are allowed only
when their role is explicit.

.. list-table::
   :header-rows: 1
   :widths: 24 28 48

   * - Category
     - Formats
     - Contract
   * - Project catalog
     - DuckDB
     - Index of simulations, metrics, parameters, provenance, audit events and the
       workflow ledger. Rebuilt from the run folders.
   * - Input cache
     - DuckDB
     - Cache index of downloaded and custom datasets.
   * - Field arrays
     - Zarr
     - The persisted store of gridded and mesh fields.
   * - Tabular outputs
     - Parquet, GeoParquet
     - Persisted tables and vector layers.
   * - User exports
     - CSV, NetCDF, GeoTIFF, VTU, Shapefile, STAC, PROV-O, RO-Crate, ``.hmp``
     - Documented outputs for humans and external tools. Never the source of
       truth.
   * - Input derivatives
     - Parquet, NetCDF, JSON sidecars
     - Cache artifacts tied to data variables and provenance.
   * - Solver diagnostics
     - NPY, NPZ, JSON, CSV
     - Sidecars for debugging solver state. Not a stable API unless a page names
       the schema.
   * - Validation and calibration truth packages
     - NPZ, CSV, JSON
     - Named benchmark artifacts with local schema expectations.
   * - Legacy hydrology helpers
     - HDF5
     - Localized PyHELP output. Stable only for the owning helper.

.. _direct-duckdb-access:

Direct DuckDB access
~~~~~~~~~~~~~~~~~~~~

The normal path is a catalog or cache adapter. A direct ``duckdb.connect`` is
allowed for migration runners, backend adapters and the concrete catalog and cache
constructors, read-only diagnostics, ``.hmp`` snapshot export and import, tests and
benchmarks, and developer-only CLI inspection commands. A new direct call in the public API or in a user-facing command is a
regression, and ``tests/unit/architecture/test_storage_boundary.py`` fails on it
unless the file is added to its allowlist with a rationale.

See also
--------

- :doc:`storage-layout` for the on-disk contract, the three data classes and the
  rebuild invariants.
- :doc:`contracts` for the protocols and the public facade.
- :doc:`packages/results` for the Python surface of ``hmp.read`` and
  ``CatalogBackend``.
