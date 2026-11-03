Data scopes and schema evolution
================================

HydroModPy splits SQL state across two scopes: workspace and project. Each
owns a DuckDB file with a focused role and an independent lifecycle. This page
states the role of each scope, how their schemas evolve, and which formats are
canonical.

**Neither is a place where irreplaceable results live.** Both are an index or
a cache over something else: upstream sources for the workspace cache, the
project's run directories for the project index. The disk is the source of
truth; the databases make it queryable. No file on the machine registers
projects: a workspace is read by walking its tree.

The full on-disk contract, the three classes of data and the rebuild
invariants live in :doc:`storage-layout`.

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

A project pins the state of this cache in ``hydromodpy.lock``, at its root. The file
holds one ``[[input]]`` record per entry, with its ``variable``, ``source``,
``station_id``, ``path``, ``sha256``, ``bytes``, ``file_mtime`` and ``fetched_at``.
``hmp run --frozen``, ``hmp dev lock verify``, a restored archive and the frozen
matching of the cache all read that one record. :doc:`storage-layout` gives the whole
document.

**One writer at a time.** When a project launches its cases, the ``prepare``
phase runs each case up to its data (``hmp run <case>.toml --until
load_data``). A case opens the shared cache read-only, one request at a time,
and registers what it fetched in a private cache, which the launcher merges
into the shared one when the case ends: the launcher is the one writer. The
workers that solve do the same with ``runs/<case>/.hmp/data-cache.duckdb``.
``hmp data`` reads and ``hmp run --frozen`` check the cache read-only.

Project index: ``<project>/.hmp/index.duckdb``
-----------------------------------------------

Indexes the runs of one project: identity, parameters, metrics, the label of
the day, the sites and the cases. It is the query layer over ``runs/`` and
``sessions/``, not their owner. It lives under ``.hmp/`` precisely because
that directory is disposable.

The project index is explicitly **not** a store of irreplaceable output.
What a run needs in order to be read, replayed, resumed or compared is
written into its run folder, and the index is derived from it. A run and a
calibration never open it: the indexer writes it, and ``Catalog`` reads it. A
change that makes a result reachable only through SQL is a regression of this
contract.

Exposed through:

- :class:`hydromodpy.results.catalog.Catalog`, a read-only view
- :class:`hydromodpy.results.run.Run`
- :class:`hydromodpy.results.run.group.RunSet`
- ``hmp.open(project_path)``, which returns the ``Project``; its reads go
  through ``Catalog``
- CLI verb ``hmp catalog ...``
- :func:`hydromodpy.results.catalog.federation.read_workspace_runs`, the read
  across the projects of a workspace, on the ``simulation.parquet`` of each
  run and never on an index
- :func:`hydromodpy.core.state.paths.project_roots_under`, the single place
  that turns a directory into the project roots it stands for

Rebuilding it
~~~~~~~~~~~~~

``hmp catalog reindex`` reads every run directory under ``runs/`` and every
calibration session under ``sessions/``, and rebuilds the index from them.
Per run it reads ``tables.parquet/simulation.parquet``, ``parameters.parquet``,
``metrics.parquet``, the geographic payloads, ``manifest.json``,
``provenance.json`` and ``annotations.json``. A directory with an
``outcome.json`` and no manifest is indexed too, with its effective status, so
a failed case is visible. Per session it reads ``session.json``,
``phases/*/session.json`` and ``trials.jsonl``. After a launch the same
indexer applies a diff keyed by the relative directory, instead of a full
rebuild. Both write a staging database next to the index and install it with
one atomic rename, so ``index.duckdb`` is never absent nor half-written: a
reader that was reading keeps reading the file it opened, the next opener gets
the new one, and building it twice describes the project identically. That
rename is :func:`hydromodpy.core.io.atomic_replace.rename_over_open_file`, the
only publishing path: ``os.replace`` on POSIX, and on Windows, where
``MoveFileEx`` refuses as soon as another handle is on the index, the same
rename asked of the kernel with ``FILE_RENAME_POSIX_SEMANTICS``. There is no
non-atomic fallback: where the kernel supports neither, the write fails, the
previous index stays untouched and readable, and the fix is to close the
processes reading the project and rebuild again. :doc:`storage-layout`
carries the full statement.

The run **name comes from the directory**, never from the files: a rename
moves the directory, so the tree is what the name is. A directory whose
manifest names another run is reported and left out rather than indexed under
a doubtful identity.

What survives a rebuild
~~~~~~~~~~~~~~~~~~~~~~~

The rule is stated once, in :doc:`storage-layout`, and summarised here. The
authoritative description is the module docstring of
``hydromodpy/results/catalog/indexer.py``, which is the code that performs the
rebuild.

.. list-table::
   :header-rows: 1
   :widths: 20 44 36

   * - Class
     - Content
     - Rebuild behaviour
   * - Reconstructible
     - Run identity and geometry, catchment metadata, parameters, metrics,
       input provenance, run environment, geographic features, declared
       observation points, tags and notes (``annotations.json``), calibration
       sessions and trials. The frozen ``config.toml`` stays in the run folder
     - Obligation: written in the run or session folder, restored identically
       by the rebuild
   * - Losable
     - The index as a whole, and the tables with no directory behind them. What
       they recorded has its replacement on disk: ``exports/index.json`` and
       ``figures/index.json`` for what was produced, ``published.jsonl`` for
       what left the project, ``jobs/*/journal.jsonl`` for what was launched,
       ``trials.jsonl`` for the link between a trial and its promoted run
     - Dropped with the file. The runs, their results and their lineage are
       unaffected
   * - Input
     - Observation series and station metadata
     - Out of the results scope. Repopulated from the input cache and the data
       loaders

Two consequences are worth naming. A deleted run lives in ``trash/``, not as a
flag in the index, so a rebuild neither revives it nor forgets it. A deleted
name is never given out again: the version of a name is computed on disk, over
the live directories, the trash and the tombstones.

Provenance bridge
-----------------

Each run seals, in its own ``inputs.json``, which inputs it loaded: provider,
product, version, the full request, path, SHA-256 and licence.
``run.record.inputs`` returns them. The SHA-256 of an entry is the key to the
matching entry of the workspace input cache, so a run received alone still
says what it read. Cross-project lookups read the ``simulation.parquet`` of
each run, never an index.

Why two scopes
--------------

- **Workspace cache**: input sharing between projects covering the same
  geographic area, so a regional DEM is downloaded once.
- **Project index**: fast queries over one project's runs, scoped so a
  project stays usable while other projects write to the same workspace
  cache.

Two scopes, two rebuild costs: the workspace cache from upstream sources
(network cost), the project index from the project's own run directories
(local cost). No scope is a single point of loss for a scientific result.

Shared architecture
-------------------

One set of patterns governs the two databases.

- **Migrations only where the file is not derived**:
  :mod:`hydromodpy.core.migrations.runner` exposes
  ``apply_migrations(db_path, migrations_dir)``, serialised by a
  ``<db_path>.lock`` filelock, and the workspace cache uses it with a flat
  ``migrations/`` directory of numbered SQL files starting at
  ``0001_initial.sql``. The project index has none: it is derived, so a schema
  change there is a new DDL in ``results/catalog/index_schema.py``, a bump of
  ``INDEX_SCHEMA_VERSION`` and a rebuild. The reader refuses an index written
  under another version and names the command that rebuilds it. A ledger holding
  a migration this code does not know means a newer version wrote the cache, and
  it is refused, naming both.
- **Per-scope doors**: one entry point per database.
  ``hmp.open(path)`` returns a ``Project`` for the directory holding
  ``project.toml``, a ``Run`` for a run directory received alone and a
  ``Workspace`` for a workspace root; the project reads its
  ``.hmp/index.duckdb`` through ``Catalog``.
  :class:`hydromodpy.catalog.InputsNamespace`, opened on a workspace root,
  reaches the input cache.
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

Three things move differently, and only the first is migrated.

The workspace cache is a primary record, so it has a migration runner. The
project index is derived, so its schema moves forward by replacing the DDL and
rebuilding from disk with ``hmp catalog reindex``.

The stored documents of a run or a session (the Zarr field store, the Parquet
tables, ``manifest.json``, ``session.json``, the ledgers, ``PUBLICATION.json``)
are never rewritten. Each family reads a window of versions, and every later 2.x
reads every 2.0.0 document, by the rule in
:doc:`storage-layout` and in :mod:`hydromodpy.core.io.document_version`.
``hydromodpy.lock`` follows the same rule with its ``schema`` id, and a lock outside
the window is written again with ``hmp dev lock update``.

User TOML files are out of scope: Pydantic with ``extra="forbid"`` handles them,
and ``hmp doctor --fix-config`` rewrites their grammar. ``workspace.toml`` also
says the oldest HydroModPy that opens the workspace, ``hydromodpy_version_min``,
and an older one refuses it, naming both.

The migration runner
~~~~~~~~~~~~~~~~~~~~

The code is ``hydromodpy/core/migrations/runner.py``, with one migrations folder:
``hydromodpy/data/registry/migrations/`` for the workspace cache.

A migration is a numbered SQL file (``0001_initial.sql``, ``0002_<slug>.sql``, ...).
The runner keeps a ``schema_migrations`` ledger with one row per applied migration
and component, reads the highest applied version, applies every newer file in one
transaction per file, and records a SHA-256 checksum of the SQL. It refuses to go
on when a recorded checksum no longer matches the file, and when the ledger holds
a migration no file describes.

``ensure_schema()`` on a backend deploys the latest schema for its component, so a
user never sees a half-deployed cache. ``hydromodpy/core/migrations/auto_boot.py``
wraps the runner for boot-time upgrades: a lock on ``<db>.lock``, and an atomic
``<db>.bak-<timestamp>`` snapshot that is restored on failure, with at most five
kept. ``HMP_AUTO_MIGRATE=0`` turns a pending migration into
``AutoMigrationDisabled`` and leaves the file untouched.

Rules for a change
~~~~~~~~~~~~~~~~~~

1. **One version per component.** The workspace cache has its own ledger row, the
   project index its ``INDEX_SCHEMA_VERSION``. Each Zarr
   store carries ``zarr_schema_version`` in its root attributes. Each Parquet file
   carries ``hmp.schema_version`` in its key-value metadata. SQL and columnar
   versions never share a number.
2. **Additive first.** Prefer ``ALTER TABLE ... ADD COLUMN`` with a default to a
   deletion or a rename. Zarr fields only grow, and a new Parquet column or JSON key
   is optional. None of this changes the version of a stored document.
3. **Monotone numbering.** Integers, one by one, no gaps. A migration of the
   workspace cache is a one-way door; downgrades are not supported.
4. **A round-trip test for every migration.** Start from a minimal hand-built
   ``v(n)`` fixture, check that the migrated ``v(n+1)`` store reads with the
   current backend, and check that applying the migration twice changes nothing.
5. **A reader-breaking change raises the current version of its family.** A change
   of shape, dtype, column order or meaning of an existing field keeps the oldest
   version of the window and brings the reader of the old version. Nothing upgrades
   the stored document in place. A refactor that does not touch the disk changes nothing. The
   float width of a Zarr field is the exception: ``float32``
   (``field_precision = "compact"``) and ``float64`` (``"exact"``) is a per-store
   choice written in each array's metadata, and every reader returns ``float64``.
6. A published copy carries ``PUBLICATION.json`` with a SHA-256 for every file.
   ``hmp catalog import`` checks every digest before it writes anything into the
   project.

A migration of the workspace cache works only on the handle it is given, and brings
in no table, column or data from outside it. A reader of a stored run is another
matter: it accepts a column or a key it does not know, as rule 2 says.

Where each version is declared
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The values are in the code. Read them there, not here.

.. list-table::
   :header-rows: 1
   :widths: 34 66

   * - What
     - Where
   * - Workspace cache
     - The highest numbered file of ``hydromodpy/data/registry/migrations/``.
   * - Project index
     - ``INDEX_SCHEMA_VERSION`` in ``hydromodpy/results/catalog/index_schema.py``
   * - ``ZARR_SCHEMA_VERSION``
     - ``hydromodpy/results/zarr_store/constants.py``
   * - ``PARQUET_SCHEMA_VERSION``
     - ``hydromodpy/results/storage/parquet_schemas.py``
   * - ``GEOPARQUET_SCHEMA_VERSION``
     - ``hydromodpy/core/io/geoparquet.py``
   * - ``RUN_RECORD_MANIFEST_VERSION`` (run seal: ``manifest.json``)
     - ``hydromodpy/results/manifest.py``
   * - ``SESSION_SCHEMA`` (``session.json``)
     - ``hydromodpy/results/session/descriptor.py``
   * - ``ANNOTATIONS_VERSION`` (``annotations.json``)
     - ``hydromodpy/results/annotations.py``
   * - ``LEDGER_SCHEMA`` (``figures/index.json``, ``exports/index.json``)
     - ``hydromodpy/results/ledger.py``
   * - The documents of a job (``hmp-manifest/v2``, ``hmp-inputset/v1``,
       ``hmp-provenance/v1``, ``hmp-outcome/v1``, ``hmp-chain-outcome/v1``)
     - ``hydromodpy/schema/job/``, beside the writer of each document

.. _artifact-policy:

Artifact policy
---------------

The results of a run live on disk, in Zarr and Parquet, and those files are the
truth. DuckDB holds the indexes, which are rebuilt from them. Other formats are
allowed only when their role is explicit.

.. list-table::
   :header-rows: 1
   :widths: 24 28 48

   * - Category
     - Formats
     - Contract
   * - Project catalog
     - DuckDB
     - Index of cases, simulations, sites, metrics and parameters. Rebuilt from the
       run folders.
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
     - CSV, NetCDF, GeoTIFF, VTU, Shapefile, GeoPackage, STAC, PROV-O, RO-Crate
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
constructors, read-only diagnostics, tests and
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
