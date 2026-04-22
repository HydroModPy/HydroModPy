# Parquet lakehouse refactor — blast radius

Scope of code touched by moving `timeseries`, `budgets`, `mass_balance` from
DuckDB tables to per-simulation Parquet files, kept visible through DuckDB
views of the same names.

## Workspace layout decision

We keep Zarr untouched at `simulations/<uuid>.zarr/` and place the new
Parquet files under a sibling directory:

```
simulations/
├── <uuid>.zarr/                      # unchanged
├── <uuid>.zarr.zip                   # unchanged (post-finalize)
└── <uuid>.parquet/                   # NEW
    ├── timeseries.parquet
    ├── budgets.parquet
    └── mass_balance.parquet
```

Rationale: the alternative layout in the spec (`<uuid>/data.zarr/`) requires
renaming every Zarr path and touching `open_zarr`, `finalize`,
`hmp_package.py`, and several tests for no functional gain. The Parquet
directory uses the `.parquet` suffix so the glob
`simulations/*.parquet/<name>.parquet` never accidentally matches a Zarr
directory.

No hive partitioning is used — each Parquet file carries its own `sim_id`
column, and DuckDB row-group statistics are enough for predicate pushdown
at our scale.

## Read sites

All go through one of three choke points, which we reproduce as views over
the Parquet glob. No change to the reader surface is required.

- `Run.timeseries`, `Run.budget`, `Run.mass_balance` — façade used by
  every display figure under `hydromodpy/display/figures/`.
- `SimulationCatalog.query_timeseries`, `query_budget`, `query_mass_balance`
  — used by validation loaders, `exporters/csv.py`, and integration tests.
- Raw SQL against the table names, in:
  - `tests/unit/simulation/test_simulation_catalog.py` (counts)
  - `tests/unit/simulation/test_observation_ingest.py` (selects)
  - `tests/e2e/test_export_hmp_roundtrip.py` (`SELECT variable, value FROM timeseries ...`)
  - `hydromodpy/results/run.py::to_csv` (`SELECT ... FROM timeseries`)
  - `hydromodpy/results/exporters/csv.py`
  These remain valid because the view preserves the column set and types.

## Write sites

Writes are strictly serial today — the calibration loop in
`hydromodpy/calibration/engine.py` is single-threaded, no `multiprocessing`
or thread pool in the calibration or batch analysis modules. The Parquet
refactor does not require batching changes to keep correctness, but we do
keep the existing batched-per-sim pattern.

Production call sites:

- `hydromodpy/results/catalog.py` — `write_timeseries`, `write_budget`,
  `write_budgets`, `write_mass_balance`, `write_mass_balances`.
- `hydromodpy/simulation/extraction/extractors/modflow6.py` — one batched
  `write_budgets` and one batched `write_mass_balances` per sim.
- `hydromodpy/simulation/extraction/extractors/modflownwt.py` — same.
- `hydromodpy/simulation/extraction/extractors/gr4j.py` — three
  `write_timeseries` calls per sim, one per variable.
- `hydromodpy/simulation/extraction/extractors/observation_ingest.py` —
  one `write_timeseries` per (station, variable).
- `hydromodpy/simulation/extraction/extractors/catchment_aggregation.py` —
  one `write_timeseries` per aggregated variable.
- `hydromodpy/simulation/extraction/calibration_bridge.py` — one
  `write_timeseries` per (station, variable) in the observation plan.

The timeseries writer is called multiple times per sim. Our implementation
reads the existing per-sim Parquet file (if any), unions the new rows with
a PK dedupe, and atomically replaces the file via a `.tmp` staging file.
For the three-call patterns this is cheap. If profiling ever shows the
rewrite cost matters at scale, a per-sim in-memory buffer flushed at
`finalize()` is a drop-in upgrade.

## Tests

- Direct raw-SQL queries against the three tables work unchanged once
  the tables are replaced by views.
- `tests/unit/simulation/test_catalog_import_export.py` and
  `tests/e2e/test_export_hmp_roundtrip.py` exercise `.hmp` package
  round-trips. The exporter must now include the Parquet files, and the
  importer must restore them into `simulations/<uuid>.parquet/`.
- `tests/_helpers/fixtures_catalog.py::seed_three_simulations` is the
  central fixture; it only calls `write_timeseries` and `write_metric`,
  so it keeps working if the write path stays API-compatible.
- Regression goldens under `tests/regression/reference/golden_references/`
  only snapshot Zarr field stats and solver JSON/npz — none of them embed
  rows from the three tables, so no golden file needs regenerating for
  this refactor.

## .hmp package format

`hydromodpy/results/exporters/hmp_package.py` currently bundles a one-sim
`catalog_snapshot.duckdb`. The three moved tables were previously dumped
into the snapshot via the `PER_SIM_TABLE_NAMES` loop in
`_dump_catalog_snapshot`. After the refactor they will not be in that
snapshot (they are not tables anymore), so the exporter must also:

- copy `simulations/<uuid>.parquet/{timeseries,budgets,mass_balance}.parquet`
  into the staging directory under a known name,
- list them in the manifest with their SHA-256,
- extract them back into `simulations/<uuid>.parquet/` on import.

## Retry decorator

`hydromodpy/data/registry/catalog_duckdb.py` has an inline `for attempt in
range(_RETRY): try / except duckdb.IOException: time.sleep(...)` pattern
(around lines 281–349). `hydromodpy/results/catalog.py` has no retry at
all. We extract a shared decorator (`hydromodpy/results/_db_retry.py`) and
apply it to every `SimulationCatalog` write path. Reads stay untouched —
a reader that hits a lock raises naturally and the caller can retry.
