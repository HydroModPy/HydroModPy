# Migrating a v0.5 workspace to the Parquet lakehouse

This guide explains how to move an existing workspace from the
pre-refactor layout (rows in `hydromodpy.duckdb`) to the new Parquet
layout (`simulations/<uuid>.parquet/*.parquet`).

## Who needs this

Anyone with a workspace created by HydroModPy v0.5 or earlier and at
least one row in the `timeseries`, `budgets`, or `mass_balance` tables.

If you run HydroModPy v0.6 code against such a workspace without
migrating, the catalog will open, but `ensure_parquet_views` will log a
warning and skip creating the Parquet-backed views. You will still be
able to `SELECT ... FROM timeseries` via the legacy table, so reads keep
working, but every new `write_timeseries` call goes into
`<uuid>.parquet/` on disk while the DuckDB table keeps its old rows.
That split is not a long-term supported state.

## Running the migration

Shut down any other process that has the workspace catalog open: DuckDB
holds a per-file lock.

Dry-run first to see what would happen:

```
hmp migrate --workspace ~/my_workspace --dry-run
```

Expected output, per view:

```
Workspace: /home/you/my_workspace
Mode: dry-run
  timeseries     sims=   42 rows=   132560
  budgets        sims=   42 rows=     3360
  mass_balance   sims=   42 rows=     3360
```

Apply the migration:

```
hmp migrate --workspace ~/my_workspace
```

The command walks each legacy table, groups rows by `sim_id`, and writes
one Parquet file per `(sim_id, view)` pair via
`COPY (SELECT * FROM <view> WHERE sim_id = ?) TO '...' (FORMAT PARQUET)`.
Each file lands at a sibling `.tmp` path first and is promoted with
`os.replace`. Row counts are verified against the source before the
legacy table is dropped. If any count mismatches, the command aborts and
the legacy tables stay in place.

After a successful run the Parquet views are refreshed on the connection
and `hmp doctor --workspace ~/my_workspace` reports:

```
OK     parquet:layout               42 per-sim Parquet dir(s)
```

## Idempotency

Running `hmp migrate` on an already-migrated workspace is a no-op: no
legacy tables means nothing to do.

## Rollback

The migration is non-destructive until the final `DROP TABLE` step. If
something goes wrong in the middle, rerun the command; rows already
written to Parquet are overwritten in place.

If you need to roll back a completed migration, re-read the Parquet
files and write them back into fresh DuckDB tables. A short script using
the Python API:

```python
import duckdb
conn = duckdb.connect("/path/to/workspace/hydromodpy.duckdb")
conn.execute("""
    CREATE TABLE timeseries AS
    SELECT * FROM read_parquet(
        '/path/to/workspace/simulations/*.parquet/timeseries.parquet')
""")
```

Do the same for `budgets` and `mass_balance`, then drop the views. This
path is untested against `hmp run`, which assumes the new layout, so
only use it for recovery.

## When does the migration not apply

- Fresh workspaces (`hmp init`) start on the new layout. No migration
  needed.
- Workspaces that ran only overview/mesh workflows (no simulation). No
  per-sim rows means nothing to move.
- `.hmp` packages exported before v0.6 contain the legacy
  `catalog_snapshot.duckdb` with the three tables inline. Importing
  such a package on a v0.6 workspace restores the rows into those
  legacy tables. Run `hmp migrate` once more and the rows end up in
  Parquet.
