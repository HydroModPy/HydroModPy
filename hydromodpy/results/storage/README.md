# results/storage

This folder answers what a run directory holds, under which names, and how the files in it are written. It
holds the layout contract, the Parquet tables with one schema per view, the store of one run, the seal that
closes a run, and the attempt protocol that says who may work in a directory. The index is not here. Disk is
the truth, and the DuckDB index `.hmp/index.duckdb` is derived from these directories by `catalog/indexer.py`.

## How the work flows

1. `attempt.py` claims the run directory and `outcome.json` records how the attempt ends. `run_log.py` keeps the log. The claim holds no identity: the `sim_id` is a uuid taken at the claim. The runner writes `request.json` and `config.toml` right after it, and the `request_id` into `outcome.json` once the inputs are resolved.
2. `RunStore` (`run_store.py`) opens the directory. Its methods write arrays into the Zarr store and tables into
   `tables.parquet/`.
3. A table is built by `arrow_tables.py` on the schema of `parquet_schemas.py` and written by `parquet_io.py`, whole,
   through a temporary file and one rename.
4. The run collects its facts in `run_facts.py`. A soil run adds its columns and `soil_budget` rows (`soil_tables.py`).
5. `sealing.py` builds the record from the store and writes the seal last. A directory without a seal never finished.
6. `scratch.py` empties the solver scratch when the attempt ends.
7. `kept.py` holds `Retention`, built once by the extract step from `[simulation.results]` and the per-cell budget the planning kept. Every `extract` of a solver adapter reads it to know which budget terms to write, and the export step reads it to know whether the raw solver files stay.

A run that restarts from another run reads it once, before the solve. `prior_state.py` opens the Zarr store of
the prior run, checks that its mesh is the mesh of the new run, and gives the final head and the lake stages
as a `PriorState`. No solver adapter opens that store. When the prior run has a `final_state/` it reads that folder first, and the last step of `fields.zarr` otherwise, which is how a run of HydroModPy 2.0 is read.

`final_state/` is written by the extractor of each flow when the solve is done. It is a Zarr 3 group in float64 with the last head, the stage of each lake and, under SFR with storage, the stage of each reach. It is sealed with the run. The head of `fields.zarr` may be rounded to 2^-17 under the compact precision, up to 0.8 mm on 100 m, and a restart must not change the state it starts from. The next window of a chain starts from this group.

`profile.json` says where a run spent its time and memory. `core/runtime/stopwatch.py` measures, and `run_profile.py` writes the document after each step, through one rename. It holds one line per step, per solve, per figure and per export, the attempt that wrote it, and whether the line was computed, rebuilt from an earlier attempt (`prefix`) or read from the project store (`store`). It is outside the seal and the identity, because it describes one machine. The wall time of the solve is in this file and in no table. `hmp catalog show` prints it, and the README of a sealed run gives the cost of a replay from it.

A stop is asked by `request_stop(directory)`, which writes `<directory>/.hmp/stop.json` for a run that is running. The flag lives in `.hmp/` because it is no result: the seal removes it with the attempt state, and the next attempt files it under `attempts/<k>/stop.json`. A stopped run ends `aborted` with `error.type = "StopRequested"`, no signal, and no seal.

## The folder map

```text
storage/
├── contract.py          names inside a run and a session directory, GEOGRAPHIC_FEATURE_PREFIX, geographic_feature_files
├── run_store.py         RunStore, the store of one run (arrays, tables, facts)
├── prior_state.py       the prior run read as a PriorState, read_final_head, verify_restart_mesh
├── final_state.py       FinalState, final_state/ in float64 at the end of a run
├── run_profile.py       Profile and ProfileLine, profile.json of a run
├── run_facts.py         facts a run gathers before its seal
├── sealing.py           seal_completed, build_record, provenance
├── attempt.py           claim and withdrawal of a directory, restart, request_stop, finish_attempt, typed refusals
├── run_log.py           logs/run.log and the tail kept in the outcome
├── scratch.py           what leaves the solver scratch at the end
├── kept.py              Retention, what a run keeps of its solver outputs
├── parquet_schemas.py   one PyArrow schema per Parquet view
├── arrow_tables.py      Arrow tables from records or columns
├── parquet_io.py        atomic Parquet writer, checked reader
├── json_io.py           atomic JSON writer, readers that check the version
├── soil_tables.py       soil columns and soil_budget rows
├── udunits.py           the one spelling of a unit in a table
├── geo_metadata.py      geographic facts a run states about itself
├── licence.py           the licence derived from the inputs read
├── digests.py           sha256 and sizes of files
├── array_fingerprint.py fingerprint of the input arrays
└── diagnostics.py       checks of the layout of a project
```

A run that is given back instead of computed leaves nothing behind. `withdraw_claim` removes a directory the claim created. For a later attempt it puts back the outcome and the logs that the attempt `k` had filed under `attempts/<k>/`, and removes `attempts/<k>/`. `start_over_if_changed` compares the `request_id` of the attempt with the one recorded under `attempts/<k>/`, and files everything the earlier attempt left when they differ. An issue with no `request_id` counts as different. A resume that was asked for, `hmp run --resume`, goes through `refuse_resume_if_changed` instead: when the `request_id` differs it is refused, because an input or a key changed since the stop, with the configuration sections that moved when there are any, and a plain `hmp run` starts the run over.

`request.json` is the request of a run that was given as JSON or as a dict. It is written whole at the claim, by one rename, and never redacted, so a run can be played again from it. A request given as a TOML file or as a built configuration writes none. The file is outside the seal, because `config.toml` already says what the run was given.

`contract.py` is the place to look for a name. `GEOGRAPHIC_FEATURE_PREFIX` is the file prefix of a vector layer in
`tables.parquet/`, and `geographic_feature_files` lists the layers a tables directory holds. A reader of the catalog
finds the layers through that function, in the run directory.

## Where to add what

| To add | Where |
|--------|-------|
| a Parquet view | a schema in `parquet_schemas.py`, its write in `run_store.py`, its name in `contract.py` |
| a file in a run directory | its name in `contract.py`, then the layout test `tests/unit/results/test_run_layout_contract.py` |
| a measured block of a run | a kind in `core/runtime/stopwatch.py`, its line in `run_profile.py` |
| a JSON document | a version field and a reader through `read_sealed_json` in `json_io.py` |
| a fact the run states about itself | `run_facts.py`, then its use in `sealing.py` |
| a unit in a table | the spelling in `udunits.py` |
| a rule on who may write in a directory, or on how a claim is undone | `attempt.py` |
| something a run may keep or drop of its solver outputs | a member of `Retention` in `kept.py`, with the reader that uses it |
