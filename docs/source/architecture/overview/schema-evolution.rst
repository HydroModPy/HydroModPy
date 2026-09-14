Schema Evolution
================

HydroModPy V1 ships an **Alembic-like migration runner** that applies
versioned SQL migrations on every DuckDB the toolbox owns, and pins a
single integer schema version on Zarr and Parquet stores. The runner
records each application in a ``schema_migrations`` ledger and keeps one
row per component (catalog, cache, index).

For the storage layout that this policy applies to, see
:doc:`../storage-layout`.

Scope
-----

Covered:

- DuckDB databases: project ``.hmp/index.duckdb``, workspace
  ``data/cache.duckdb``, machine ``index.duckdb``.
- Zarr stores: ``runs/<name>/fields.zarr/``, written in Zarr format 3 and
  carrying HydroModPy's own ``zarr_schema_version`` in the root ACDD
  attributes.
- Parquet 2.6 outputs with ``hmp.schema_version`` in KV metadata
  (``PARQUET_SCHEMA_VERSION``).
- Portable ``.hmp`` packages produced by ``Catalog.export_package``.

Out of scope: user TOML files. Their versioning is handled by Pydantic
v2 with ``ConfigDict(extra="forbid")``.

The project index is the exception to the chain-of-migrations model. It
is an index over the run directories, so its schema evolves by replacing
the initial DDL and rebuilding from disk with ``hmp catalog reindex``,
which ships and is the supported path. The runner still deploys the DDL
on a fresh index; it is simply not the way that scope is meant to move
forward. The doctrine and the rebuild invariants are stated in
:doc:`../storage-layout`.

Migration runner
----------------

Source: ``hydromodpy/core/migrations/runner.py`` plus per-component
migration directories:

- ``hydromodpy/results/catalog/migrations/`` for the project index;
- ``hydromodpy/data/registry/migrations/`` for the workspace cache;
- ``hydromodpy/core/state/migrations/`` for the global index.

Each migration is a numbered SQL file (``0001_initial.sql``,
``0002_add_<slug>.sql``, ...) and applies cleanly in version order. The
runner:

1. ensures the ``schema_migrations`` ledger exists with columns
   ``version INTEGER``, ``component TEXT``, ``slug TEXT``,
   ``checksum TEXT``, ``applied_at TIMESTAMP``, alongside a
   ``_schema_version`` row per component;
2. reads the max applied version for the requested component;
3. applies every newer migration inside one transaction per file;
4. records the migration with a SHA-256 checksum of the SQL payload, and
   refuses to proceed when a recorded checksum no longer matches the file
   on disk.

Calling ``ensure_schema()`` from a backend (``DuckDBBackend`` or any
other adapter implementing the protocol) deploys the latest schema for
that component. The facade ``hmp.read`` and ``hmp.open`` reach it on
first access so users never see a half-deployed index.

``hydromodpy/core/migrations/auto_boot.py`` wraps that runner for
boot-time upgrades: a ``FileLock`` on ``<db>.lock``, an atomic
``<db>.bak-<ISO8601Z>`` snapshot with restore-on-failure, and a rolling
history of at most five snapshots. Only the workspace cache is backed
up. The ``catalog`` and ``index`` components are listed in
``NO_BACKUP_COMPONENTS`` and skip the snapshot, because an index is
rebuilt, not restored: ``hmp catalog reindex`` for a project,
``hmp workspace register`` for the machine scope. ``HMP_AUTO_MIGRATE=0``
turns a pending migration into ``AutoMigrationDisabled`` and leaves the
file untouched.

Principles
----------

1. **One version per component.** Each DuckDB has its own ledger row in
   ``schema_migrations``. Each Zarr store carries
   ``zarr_schema_version`` in its root attributes. Each Parquet file
   carries ``hmp.schema_version`` in KV metadata.

2. **Additive migrations first.** Prefer
   ``ALTER TABLE ... ADD COLUMN`` with a default over deletions or
   renames. Spatial Zarr fields only grow (new datasets); existing
   ones keep their shape and dtype.

3. **Monotone numbering.** Versions are integers incremented by one per
   migration. No gaps. Downgrades are not supported; a migration is a
   one-way door.

4. **Round-trip tests required.** For every migration
   ``v(n) -> v(n+1)`` a test must cover:

   - a minimal hand-built ``v(n)`` fixture;
   - applying the migration produces a ``v(n+1)`` store readable by the
     current backend;
   - the migration is **idempotent**: running it twice is a no-op.

5. **Breaking reader change.** Any change to shape, dtype, column
   order, or semantics of an existing field triggers a version bump and
   a migration. Pure refactors that do not touch disk do not bump the
   version.

6. **Export/import boundary.** A ``.hmp`` archive carries ``format`` and
   ``format_version`` in its own manifest, plus a SHA-256 for every file
   it contains. Import verifies the magic and every checksum before
   materialising anything. It does not currently gate on
   ``format_version``, so a package written by a newer library is
   detected only when a checked file fails to read.

Anti-patterns
-------------

- **Do not** silently accept unknown tables or columns. The reader
  rejects stores whose version differs from the one it knows.
- **Do not** inject data from outside the migration. The function
  operates only on the SQL or store handle handed to it.
- **Do not** couple SQL and field-store version numbers. Each evolves
  independently: ``schema_migrations`` for DuckDB,
  ``ZARR_SCHEMA_VERSION`` and ``PARQUET_SCHEMA_VERSION`` for the
  columnar stores.

Versions today
--------------

.. list-table::
   :header-rows: 1
   :widths: 30 20 50

   * - Component
     - Version
     - Notes
   * - Project index (``.hmp/index.duckdb``)
     - ``0001``
     - Initial v2 DDL: simulations, parameters, metrics, provenance,
       calibration, workflow, tags, schema_migrations. Evolves by
       replacing the DDL plus ``hmp catalog reindex``.
   * - Workspace cache (``data/cache.duckdb``)
     - ``0001``
     - Entries with workspace-relative paths, provenance, failures,
       validation_reports.
   * - Machine global index (``index.duckdb``)
     - ``0001``
     - Projects table, one row per project root; ``all_simulations`` is
       rebuilt at attach time.
   * - Zarr field store
     - ``ZARR_SCHEMA_VERSION = "2"``
     - Zarr format 3, ACDD root attrs, CF ``_FillValue``, consolidated
       metadata.
   * - Parquet tabular store
     - ``PARQUET_SCHEMA_VERSION = "v2"``
     - pyarrow ``Schema`` + KV metadata mixin, format ``2.6``.
   * - GeoParquet
     - ``GEOPARQUET_SCHEMA_VERSION = "1.1.0"``
     - OGC 1.1, GeoArrow encoding.
   * - Run seal
     - ``MANIFEST_SCHEMA_VERSION = 1``
     - ``manifest.json`` and ``provenance.json``, versioned together.
   * - Session journal
     - ``SESSION_JOURNAL_VERSION = 1``
     - ``session.json`` and ``trials.jsonl``.
   * - Trash marker
     - ``TRASH_VERSION = 1``
     - ``trash.json``.
   * - Portable package
     - ``HMP_FORMAT_VERSION = "1.4"``
     - ``.hmp`` archive header, magic ``hydromodpy/hmp``. A multi-run
       container declares ``format_version`` ``2.0``.

See also
--------

- :doc:`../storage-layout` for the storage that this policy applies to.
- :doc:`design-patterns` for the Pydantic config layer that sits above
  the storage.
- :doc:`/architecture/packages/results` for ``hmp.read`` and
  ``CatalogBackend``.
