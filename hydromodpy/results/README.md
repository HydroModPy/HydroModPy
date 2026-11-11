# results

What a run leaves on disk and how it is read back. A run directory holds Zarr 3 arrays and Parquet 2.6 tables, sealed by the `manifest.json` that the run writes last. The DuckDB index `.hmp/index.duckdb` is derived from the run and session directories, so disk is the truth and `hmp catalog reindex` rebuilds the index at no cost.

The package is a layer because the solvers write into it and the readers read from it, and neither side has to know the other. A seal weighs 24 to 36 kB, of which 14 to 19 kB are value digests. The product store under `<project>/.hmp/products/` keeps one folder per sha256 key, and `[workspace] products_cap_mb` caps it at 5000 MB.

A run has a level, read from its lineage. A kept calibration trial is a research run and keeps no figure, no export, no solver file and no face flow. Every other run is a result run and keeps what `[simulation.results]` asks. `Project.gc()` and `hmp catalog gc` remove what the policy allows and report the bytes before and after.

The plan of a project is `plan.json`, `cases.csv` and one TOML per case under `plan/<hash>/`, written once by `plan_store.py`.

`results` reads `core`, `schema`, `catchment`, `mesh`, `model` and itself, never `data`, `solver`, `config` or `display`. `solver`, `calibration`, `display`, `config`, `workflow`, `project` and `cli` read it. `tests/unit/architecture/layer_matrix.yaml` holds the edges and `tests/unit/results/test_run_layout_contract.py` the names of a run directory.

The one README of a port in this package is `exporters/README.md`. The page `docs/source/contribute/architecture/packages/results.rst` lists the modules and tells how the folders work together.
