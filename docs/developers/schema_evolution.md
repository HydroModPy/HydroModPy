# Schema evolution

**Status:** forward-looking guidance. This document describes how to evolve the
HydroModPy storage schema **in the future**, after the clean-slate migration
(phases P02+) has landed. The principles below do **not** apply to the
existing baseline — the migration starts from a fresh schema defined in
`architecture_cible/04_storage_ideal.md`.

## Scope

The schema boundary covered here is:

- **DuckDB files** `hydromodpy.duckdb` (workspace catalog) and
  `data/cache.duckdb` (input cache).
- **Zarr stores** `simulations/<sim_id>.zarr/`.
- Portable `.hmp` packages produced by `SimulationCatalog.export_simulation`.

It does **not** cover user TOML configs (Pydantic models already provide
versioning through `extra="forbid"`).

## Principles

1. **Single schema version column.** Each DuckDB file carries a
   `_schema_version` table with a single row `(version INTEGER, applied_at
   TIMESTAMP, notes TEXT)`. Zarr stores carry the same information in the
   root `.zattrs` under key `hmp_schema_version`. The writer library holds
   the canonical current version as a module constant.

2. **Additive migrations first.** Prefer `ALTER TABLE ... ADD COLUMN` with a
   default value over column drops or renames. Spatial fields (Zarr arrays)
   should only grow new dataset names; existing dataset names keep their
   shape and dtype.

3. **Monotonic version numbers.** Versions are integers, incremented by one
   per migration. Skipping numbers is forbidden. Downgrades are not
   supported — a migration is a one-way door.

4. **Migration module layout.** Each migration lives at
   `hydromodpy/results/migrations/v{n:03d}_{slug}.py` and exposes a single
   `apply(connection_or_store)` function. The module docstring explains the
   motivation and the shape change. The registry
   `hydromodpy/results/migrations/__init__.py` maps version → module.

5. **Round-trip tests are mandatory.** For every migration `v(n) → v(n+1)`,
   `tests/unit/results/migrations/test_v{n:03d}.py` must cover:
   - a minimal `v(n)` fixture created by hand (not by calling the current
     writer, which only knows the latest version);
   - applying the migration produces a `v(n+1)` store readable by the
     current reader;
   - the migration is **idempotent** — applying it twice is a no-op.

6. **Breaking reader changes require a bump.** Any change to the shape,
   dtype, column order, or semantics of an existing field is a version bump
   plus a migration. Pure internal refactors (renames without on-disk
   impact) do not bump the version.

7. **Export/import boundary.** `.hmp` packages embed the schema version in
   their manifest. Import refuses packages newer than the current library
   and silently migrates older ones through the registry.

## Anti-patterns

- **Do not** silently accept unknown tables or columns. The reader refuses
  stores whose version exceeds the known maximum.
- **Do not** backfill data from outside the migration function. A migration
  operates only on the store it is given.
- **Do not** couple DuckDB and Zarr version numbers. They evolve
  independently, each with its own `_schema_version`.

## Not in scope for phase P01

Phase P01 only documents these principles. The `_schema_version` table, the
`migrations/` directory, and the round-trip harness are introduced in
phase P02 when the clean storage schema is put in place.
