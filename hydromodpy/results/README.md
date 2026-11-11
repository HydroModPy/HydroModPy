# `hydromodpy/results`

What a run leaves on disk and how it is read back: a directory of Zarr 3 arrays and Parquet 2.6
tables, sealed by the `manifest.json` the run writes last, plus the DuckDB index derived from
those directories. Disk is the truth and the index is derived, so `hmp catalog reindex` rebuilds
it and a deleted `.hmp/` costs nothing. `storage/` holds the layout contract and the seal order,
`record/` the seal of a run and its value digests, `catalog/` the index and its reader, `run/`
the `Run` view, and `export/` and `exporters/` the files that leave a run. A seal weighs 24 to
36 kB, of which 14 to 19 kB are value digests. The product store under `<project>/.hmp/products/`
keeps one folder per sha256 key, and `[workspace] products_cap_mb` caps it at 5000 MB.
A run has a level, read from its lineage: a kept calibration trial is a research run, keeps no figure
and no export, and keeps neither its solver files nor its face flows, while every other run is a result
run and keeps what `[simulation.results]` asks. `retention.py` weighs a project by family, and
`Project.gc()` or `hmp catalog gc` removes what its policy allows and reports the bytes before and after.
An attempt writes two logs, `<run>/logs/run.log` and `<project>/.hmp/logs/hydromodpy_debug.log`, and neither is a
handler of the package logger. `core/logging.py` keeps one router on that logger, and the router sends each record
to the files listed in the context variable `RUN_SINKS`. So two runs in two threads of one process fill two
`run.log` files and no line crosses. The project log rotates at 8 MiB and keeps three old files. A thread pool of a run
submits its tasks through `contextvars.copy_context().run`, so a task keeps the files of the thread that started it.
The
package reads `core`, `schema`, `catchment`, `mesh`, `model` and itself, and never `data`,
`solver`, `config` or `display`. `tests/unit/architecture/layer_matrix.yaml` holds the edges, and
`tests/unit/results/test_run_layout_contract.py` the names of a run directory. The plan of a
project is `plan.json`, `cases.csv` and one TOML per case under `plan/<hash>/`, written once by
`plan_store.py` and read back by `read_plan`, whose `sites` is a table of text. The answers
column below is the first line of each module docstring.

| module | answers |
|---|---|
| `annotations.py` | Run annotations: the tags and notes a human adds after the seal. |
| `calibration_trials.py` | Read the trials and the phases of the session a run was promoted from. |
| `catalog/` | The project index: its reader, its indexer and its errors. |
| `derive/` | Compute-on-read products derived from a stored Run. |
| `errors.py` | Typed exceptions for the results / reader layer. |
| `export/` | FAIR views of a sealed run or job directory, read from the directory alone. |
| `exporters/` | One writer per exported format, with the request and the vocabulary it reads. |
| `field_registry.py` | Canonical field registry for HydroModPy simulation outputs. |
| `grid.py` | Scalar metadata of the DEM raster a simulation was built from. |
| `heartbeat.py` | The pulse of a running attempt: `logs/heartbeat.json`. |
| `identity.py` | The `identity` block: what every file that leaves a run says about itself. |
| `importers/` | Importers symmetric to `hydromodpy.results.exporters`. |
| `ledger.py` | The ledger of a `figures/` or `exports/` directory: `index.json`. |
| `method.py` | The method text and the label sentence of a sealed run, in English or in French. |
| `metric_rule.py` | The metric of a run is a complete rule: a station, a window, a version. |
| `outcome.py` | The issue of an attempt: `outcome.json`, and the status a reader derives. |
| `plan_store.py` | The immutable plan of a project: `plan/<hash>/` and `plan/current`. |
| `products/` | The product store, its keys and the products a run cites. |
| `publication.py` | What a published copy records, and what the source remembers of it. |
| `readme.py` | The `README.md` of a run, a session or a summary, rendered from the seal. |
| `record/` | The record of a run: the seal, its checks, its label and the class of a replay. |
| `rel_dir.py` | One check for every `rel_dir` a result document carries. |
| `retention.py` | What `hmp catalog gc` collects in a project, read from the tree alone. |
| `run/` | Per-simulation and multi-simulation views over the results catalog. |
| `score.py` | The one pairing of a simulated series with its observations, and the score of a run. |
| `session/` | The formats of a calibration session directory, `sessions/<case>/`: the trial journal in events (`proposed`, `finished`, `linked`) read as one line per trial, and the versioned trial series. `session/summary.py` holds `SessionSummary`, `session_summary(session)` and `summary_rows(summary)`, the one writer of the rows that the session page and `hmp show` print. `session/journal.py` holds `BOUND_TOLERANCE` and `on_bound`, which say that a value ended on a bound of its range. `Session.of_run(run)` (`session/view.py`) returns the `Session` a run was promoted from, or `None`, reading the lineage through `session_dir_of`. |
| `source_runs.py` | The earlier run a configuration reads, named by its `sim_id`. |
| `spatial_index.py` | Point-in-cell lookup on unstructured meshes, cached per mesh geometry. |
| `storage/` | The layout contract, the store of one run, the seal and the attempt protocol. |
| `trash.py` | Project trash: deleting a run moves its directory, it never flips a flag. |
| `validity_rules.py` | The label of a run is a function of reading, not a value of the seal. |
| `zarr_store/` | Zarr v3 per-simulation store (CF-1.11 + ACDD-1.3 + UGRID-1.0). |
