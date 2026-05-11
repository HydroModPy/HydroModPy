Schema Evolution
================

Status: prospective. This page describes the principles for evolving
the HydroModPy storage schema in future migrations. The versioning is
not yet implemented in the codebase; the rules below apply as soon as
the first migration is introduced.

For the storage layout itself, see :doc:`two-databases`.

Scope
-----

Covered:

- DuckDB files: ``hydromodpy.duckdb`` (workspace catalog) and
  ``data/cache.duckdb`` (input cache).
- Zarr stores: ``simulations/<basename>.zarr/`` or ``.zarr.zip``, with
  legacy fallback on ``sim_id`` when ``simulations.storage_basename`` is
  absent.
- Portable ``.hmp`` packages produced by
  ``SimulationCatalog.export_package``.

Out of scope: user TOML files. Their versioning is handled on the
Pydantic side via ``ConfigDict(extra="forbid")``.

Principles
----------

1. **One version field.** Every DuckDB carries a ``_schema_version``
   table with a single row
   ``(version INTEGER, applied_at TIMESTAMP, notes TEXT)``. Zarr stores
   carry the same information in their root ``.zattrs`` under the key
   ``hmp_schema_version``. The library holds the current version as a
   module-level constant.

2. **Additive migrations first.** Prefer
   ``ALTER TABLE ... ADD COLUMN`` with a default over deletions or
   renames. Spatial Zarr fields only grow (new datasets); existing ones
   keep their shape and dtype.

3. **Monotone numbering.** Versions are integers incremented by one per
   migration. No gaps. Downgrades are not supported; a migration is a
   one-way door.

4. **Module organisation.** Each migration lives under
   ``hydromodpy/results/migrations/v{n:03d}_{slug}.py`` and exposes a
   function ``apply(connection_or_store)``. The module docstring
   explains the motivation and the nature of the change. The registry
   ``hydromodpy/results/migrations/__init__.py`` maps version numbers to
   modules.

5. **Round-trip tests required.** For every migration ``v(n) -> v(n+1)``
   a test ``tests/unit/results/migrations/test_v{n:03d}.py`` must
   cover:

   - a minimal hand-built ``v(n)`` fixture (not built through the
     current writer, which only knows the latest version);
   - applying the migration produces a ``v(n+1)`` store readable by the
     current reader;
   - the migration is **idempotent**: running it twice is a no-op.

6. **Breaking reader change.** Any change to shape, dtype, column
   order, or semantics of an existing field triggers a version bump and
   a migration. Pure internal refactors (renames without disk impact)
   do not bump the version.

7. **Export/import boundary.** ``.hmp`` packages embed the version in
   their manifest. The import path rejects packages that are newer than
   the current library and silently migrates older ones through the
   registry.

Anti-patterns
-------------

- **Do not** silently accept unknown tables or columns. The reader
  rejects stores whose version exceeds the maximum it knows about.
- **Do not** inject data from outside the migration. The function
  operates only on the store handed to it.
- **Do not** couple DuckDB and Zarr version numbers. Each evolves
  independently with its own ``_schema_version``.

Rollout plan
------------

- The ``_schema_version`` field lands simultaneously on DuckDB and Zarr
  at the time of the first effective migration.
- The ``migrations/`` registry then grows with each subsequent schema
  evolution.

See also
--------

- :doc:`two-databases` for the storage layout that this evolution
  policy applies to.
- :doc:`design-patterns` (item 6) for the Pydantic config layer that
  sits above the storage.
