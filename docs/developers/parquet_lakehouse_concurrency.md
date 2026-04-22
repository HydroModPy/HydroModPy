# Concurrency, retry and atomic writes

This note documents the mechanisms the Parquet lakehouse uses to stay
consistent when multiple processes touch the same workspace.

## The DuckDB lock

DuckDB takes a single-writer lock on the catalog file at `connect()`
time. Losing the race raises `duckdb.IOException`. The lock is not
reentrant across processes; within a single process, the connection is
cheap and writes don't re-contend.

Our catalog retries at two places:

- `connect_with_retry` (`hydromodpy/results/_db_retry.py`) loops over
  `duckdb.connect` with exponential backoff. Used by
  `SimulationCatalog.__init__`.
- `@with_lock_retry()` wraps every `SimulationCatalog` write method
  (register, write_parameters, write_metric, write_provenance,
  register_observation_points, register_tracked_files,
  write_geographic_feature, write_geographic_metadata, finalize, delete
  and the three Parquet writers). Retries on `duckdb.IOException` raised
  from `execute`.

Default backoff is 8 attempts starting at 50 ms, doubling each try. The
total worst-case wait is about 12 seconds, which tolerates the small
overlapping windows that happen during cross-process calls like
`hmp list` running while `hmp run` is committing.

Read-only queries deliberately do **not** retry. A reader that hits a
lock raises immediately and the caller is free to retry at a higher
level. The current codebase has no concurrent reader/writer usage, so
this policy is conservative rather than limiting.

## Atomic Parquet writes

Every Parquet write goes through `_atomic_write_parquet`:

1. Collect the new rows into an `insert_df` pandas DataFrame and
   register it on the DuckDB connection under the alias `_hmp_insert`.
2. Issue `COPY (<select>) TO '<target>.tmp' (FORMAT PARQUET)`. If the
   target already exists, the select unions the existing file with
   `_hmp_insert`, deduplicates on the primary key, and keeps the newer
   row. This mirrors the old `INSERT OR REPLACE` semantics.
3. `os.replace('<target>.tmp', '<target>')` — atomic on POSIX and on
   NTFS when both paths are on the same volume, which they always are
   because the `.tmp` is a sibling of the target.
4. Unregister `_hmp_insert`.
5. If this was the first file for that view, call
   `ensure_parquet_views` so the view DDL upgrades from its empty form
   to the `read_parquet(...)` form.

The glob used by the view (`simulations/*.parquet/timeseries.parquet`)
never matches the `.tmp` file, so a crash between step 2 and step 3
leaves a harmless orphan. `hmp doctor` reports the orphan under
`parquet:orphan_dirs` when the sim_id is unknown to the catalog.

## Concurrent writers to different sims

Because each simulation owns its own `<uuid>.parquet/` directory, two
writers aimed at two different sims never contend on the Parquet files
themselves. They do share the DuckDB catalog for metadata (the
`simulations` row, parameter and metric inserts, and the view DDL
refresh), which is why `connect_with_retry` matters.

The test in
`tests/unit/results/test_parquet_lakehouse.py::TestConcurrentWrites`
exercises this with 8 worker processes writing 8 distinct sims against
a single workspace and asserts no data loss.

## Concurrent writers to the same sim

Two writers targeting the same `(sim_id, view)` both rewrite the same
Parquet file. The order of `os.replace` calls determines which write
survives; the loser's rows are lost. This is acceptable because:

- Inside one simulation, writes happen from one extractor run in a
  single process. The calibration loop is strictly serial
  (`hydromodpy/calibration/engine.py`).
- `write_timeseries` is idempotent against the same input — two calls
  with the same rows produce the same file, regardless of order.

If a future workflow runs parallel workers that all write against the
same sim, this contract needs revisiting: a per-sim file lock, or a
per-(sim, view) lock, would be the smallest fix.

## Failure modes we don't guard against

- **Full disk during COPY**: the `.tmp` file is partial. The target is
  not promoted. Next run will either retry (if the caller tries again)
  or leave the orphan in place.
- **Power loss between COPY and replace**: same story. The target is
  unchanged; the `.tmp` orphan can be removed safely.
- **Process kill mid-COPY**: DuckDB closes the output file as part of
  its COPY handler; if killed, the `.tmp` is incomplete. Again, not
  visible through the view.
- **Concurrent `hmp migrate` and `hmp run` on the same workspace**:
  undefined. Don't. The catalog lock serialises the two processes at
  `connect()` but they can still race on view creation if both start
  within a narrow window. Run migration against a quiesced workspace.
