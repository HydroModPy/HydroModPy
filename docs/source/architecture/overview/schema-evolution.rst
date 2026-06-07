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

- DuckDB databases: project ``catalog.duckdb``, workspace
  ``data/cache.duckdb``, machine ``index.duckdb``.
- Zarr v2 stores: ``simulations/<basename>.zarr/`` with
  ``ZARR_SCHEMA_VERSION`` pinned in the root ACDD attributes.
- Parquet v2.6 outputs with ``hmp.schema_version`` in KV metadata
  (``PARQUET_SCHEMA_VERSION``).
- Portable ``.hmp`` packages produced by
  ``SimulationCatalog.export_package``.

Out of scope: user TOML files. Their versioning is handled by Pydantic
v2 with ``ConfigDict(extra="forbid")``.

Migration runner
----------------

Source: ``hydromodpy/core/migrations/runner.py`` plus per-component
migration directories:

- ``hydromodpy/results/catalog/migrations/`` for the project catalog;
- ``hydromodpy/data/registry/migrations/`` for the workspace cache;
- ``hydromodpy/core/state/migrations/`` for the global index.

Each migration is a numbered SQL file (``0001_initial.sql``,
``0002_add_<slug>.sql``, ...) and applies cleanly in version order. The
runner:

1. ensures the ``schema_migrations`` ledger exists with columns
   ``version INTEGER``, ``component TEXT``, ``slug TEXT``,
   ``checksum TEXT``, ``applied_at TIMESTAMP``;
2. reads the max applied version for the requested component;
3. applies every newer migration inside one transaction per file;
4. records the migration with a SHA-256 checksum of the SQL payload so
   a tampered migration is detected on re-runs.

Calling ``ensure_schema()`` from a backend (``DuckDBBackend`` or any
other adapter implementing the protocol) deploys the latest schema for
that component.
The facade ``hmp.read`` and ``hmp.open`` call ``ensure_schema()`` on
first access so users never see a half-deployed catalog.

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

6. **Export/import boundary.** ``.hmp`` packages embed the version of
   every component in their manifest. The import path rejects packages
   whose component versions exceed the local library and silently
   migrates older ones through the registry.

Anti-patterns
-------------

- **Do not** silently accept unknown tables or columns. The reader
  rejects stores whose version exceeds the maximum it knows about.
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
   * - Project catalog (``catalog.duckdb``)
     - ``0001``
     - Initial v2 DDL: simulations, parameters, metrics,
       provenance, calibration, workflow_steps, schema_migrations.
   * - Workspace cache (``cache.duckdb``)
     - ``0001``
     - Entries with workspace-relative paths, provenance, failures,
       validation_reports.
   * - Machine global index (``index.duckdb``)
     - ``0001``
     - Workspaces table plus federated views.
   * - Zarr field store
     - ``ZARR_SCHEMA_VERSION = "2"``
     - ACDD root attrs, CF ``_FillValue``, consolidated metadata strict.
   * - Parquet tabular store
     - ``PARQUET_SCHEMA_VERSION = "v2"``
     - pyarrow ``Schema`` + KV metadata mixin, version ``2.6``.
   * - GeoParquet
     - ``GEOPARQUET_SCHEMA_VERSION = "1.1.0"``
     - OGC 1.1, GeoArrow encoding.

See also
--------

- :doc:`../storage-layout` for the storage that this policy applies to.
- :doc:`design-patterns` for the Pydantic config layer that sits above
  the storage.
- :doc:`/architecture/packages/results` for ``hmp.read`` and
  ``CatalogBackend``.
