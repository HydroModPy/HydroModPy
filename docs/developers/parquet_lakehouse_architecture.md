# Parquet lakehouse architecture

This document describes where per-simulation time series, budgets and
mass-balance rows live on disk, how the catalog exposes them as SQL, and
why the refactor chose this layout.

Supersedes the "timeseries / budgets / mass_balance" portions of
`docs/developers/simulation_catalog_architecture.md`.

## What moved and what did not

Before the v1 Parquet lakehouse refactor, every per-simulation table sat inside the
workspace-level `hydromodpy.duckdb` file:

- `timeseries`: 70 years of daily rows per station per variable per sim.
- `budgets`: water budget per (timestep, zone, component) per sim.
- `mass_balance`: global in/out/percent_error per timestep per sim.

These three tables were the only ones with append-only, high-volume,
per-simulation rows. Keeping them in a single DuckDB file made concurrent
writes impossible (DuckDB holds a single-writer lock per file) and made
the catalog file grow into the multi-gigabyte range on long-running
projects. They are now Parquet files on disk; everything else stays in
DuckDB.

Tables that still live inside `hydromodpy.duckdb`:

- `simulations`, `parameters`, `metrics`, `observation_points`,
  `provenance`, `geographic_features`, `geographic_metadata`,
  `runs_environment`, `tags`, `tracked_files`, `calibration_sessions`,
  `calibration_iterations`, `stations`, `observations`.

## On-disk layout

```
workspace/
├── hydromodpy.duckdb              # metadata only (catalog tables + views)
├── data/
│   ├── cache.duckdb
│   └── <variable>/
├── simulations/
│   ├── <basename>.zarr/           # spatial fields
│   ├── <basename>.zarr.zip        # packed Zarr after finalize
│   └── <basename>.parquet/
│       ├── timeseries.parquet
│       ├── budgets.parquet
│       └── mass_balance.parquet
└── projects/
```

The per-simulation basename comes from `simulations.storage_basename`
(`project_slug__name_slug__short_uuid`). Legacy rows with
`storage_basename NULL` fall back to the raw UUID. The `.parquet` suffix
lets the view glob pick up Parquet files without ever matching a Zarr
directory by accident.

A simulation with no time series (e.g. an overview-only run) has no
`<basename>.parquet/` directory. The view glob tolerates this.

## SQL surface

DuckDB exposes the three data sources as **views** named `timeseries`,
`budgets`, `mass_balance`. Code that previously ran
`SELECT * FROM timeseries WHERE sim_id = ?` keeps working unchanged.

The view is one of two shapes, chosen when the catalog opens:

1. If at least one matching Parquet file exists:
   ```sql
   CREATE OR REPLACE VIEW timeseries AS
   SELECT * FROM read_parquet(
       '<workspace>/simulations/*.parquet/timeseries.parquet',
       union_by_name=true
   );
   ```
2. If no file exists yet: an empty typed view with the same column set,
   so a fresh workspace still answers `SELECT * FROM timeseries` cleanly.

On the first write that creates a Parquet file, the catalog refreshes
the view. After `delete()` removes the last sim, the view collapses back
to the empty form.

DuckDB's UUID and `TIMESTAMPTZ` types round-trip through Parquet via its
native encoding, so the view columns have the same types as the legacy
SQL tables. No casts are needed on the read path.

## Write path

`SimulationCatalog.write_timeseries`, `write_budgets`,
`write_mass_balances` share a common helper
(`_atomic_write_parquet`) that:

1. Normalises the incoming pandas `DataFrame` to a deterministic column
   order and explicit DuckDB types via a `SELECT ... CAST ... FROM
   _hmp_insert` expression.
2. If the target Parquet already exists: unions the existing rows with
   the new ones and keeps the newest per primary key
   (`QUALIFY ROW_NUMBER() OVER (PARTITION BY pk ORDER BY priority DESC) = 1`).
   This matches the old `INSERT OR REPLACE` semantics.
3. Writes the result to a sibling `.tmp` file via DuckDB's native
   `COPY (SELECT ...) TO '<path>.tmp' (FORMAT PARQUET)`.
4. Promotes the file with `os.replace`, which is atomic on POSIX.

A crash mid-write leaves a `.tmp` file behind. Because the glob only
matches `*.parquet`, nothing in the `.tmp` file is visible through the
view. The orphan is harmless and `hmp doctor` reports it as
`results:parquet_tmp` for manual cleanup.

## Concurrency model

Each per-sim Parquet file lives under its own `<basename>.parquet/`
directory, so two writers targeting different sims never contend on
disk. They do still share the DuckDB catalog file, which is the
single-writer lock point. `connect_with_retry` in
`hydromodpy.core.io.db_retry` loops with exponential backoff over
`duckdb.IOException` at connect time, and `@with_lock_retry` does the same
on `execute()` calls for write methods.

Read-only queries never hit the retry path: a reader that collides with
a writer raises naturally and the caller can retry.

See `parquet_lakehouse_concurrency.md` for the failure modes and
matching tests.

## Why this layout, not hive-style partitioning

DuckDB supports `hive_partitioning=true` in `read_parquet` if the path
has `key=value` directories. We evaluated that but rejected it because:

- The partition column (`sim_id`) is already a column inside each
  Parquet file, so hive path components would duplicate it.
- Naming the per-sim directory `sim_id=<uuid>` would add a partition-style
  layer while `sim_id` is already a column inside each file. Keeping the
  suffix `.parquet` on the simulation basename is enough to disambiguate
  from Zarr.
- At our scale (thousands of sims, not millions) DuckDB's row-group
  statistics in the Parquet footer give enough predicate pushdown on
  `WHERE sim_id = ?` that partition pruning by path would not change
  query times noticeably.

If that ever becomes a real bottleneck, moving the layout to
`simulations/sim_id=<uuid>/timeseries.parquet` is a localized change handled
inside `_glob_for_view` and `StoragePathResolver.parquet_dir_for`.
