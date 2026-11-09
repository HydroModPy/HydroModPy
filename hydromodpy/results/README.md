# `hydromodpy/results`

What a run leaves on disk, and how it is read back. Each run owns a directory
of Zarr arrays and Parquet tables, sealed by a manifest the run writes
itself. A DuckDB index, derived from those directories by the indexer, lists
the runs so they can be found, ranked and compared. `Catalog` reads the
index; `Run` is one finished simulation. Exporters turn a run into the
formats others use.
This file is the map of the package: what each part answers, the import
rules, how a run is written and read, and where to add what.

## The rule

Disk is the truth, the index is derived. Everything execution code reads back
from a run is also written inside its directory: `manifest.json` seals the
run, `outcome.json` says what became of each attempt, `provenance.json`
records the environment, `annotations.json` keeps the tags and notes a
person set afterwards, and `sessions/<name>/` keeps the calibration trials.
A run and a calibration never open `.hmp/index.duckdb`: the indexer
(`catalog/indexer.py`) writes it from those files, whole on `hmp catalog
reindex` or as a diff after a launch, always into a staging file published
in one rename, and building it twice describes the project identically. The
layout is `storage/contract.py`; the full contract is
`docs/source/contribute/architecture/storage-layout.rst`.

## Parts

| part | answers |
|---|---|
| `storage/` | what a run and a session directory hold (`contract.py`), how a Parquet table is written (`parquet_io.py`, `arrow_tables.py`, one schema per view in `parquet_schemas.py`), the store of one run (`run_store.py`, its facts in `run_facts.py`, the UDUNITS spelling of its units in `udunits.py`), the seal (`sealing.py`), the soil columns and `soil_budget` rows of a soil run (`soil_tables.py`), the claim, the restart and the withdrawal of a run directory (`attempt.py`, `run_log.py`), the emptying of the solver scratch (`scratch.py`), digests, licence and geographic facts, layout diagnostics (`README.md`) |
| `zarr_store/` | the per-run Zarr 3 array store `SimulationZarr`: each write is a function of `zarr_writer.py` and each read one of `zarr_reader.py`, bound on the class as its methods; the schema, the write lock, ACDD and CF metadata, chunk and shard sizes (`README.md`) |
| `field_registry.py` | the one table that maps a field name to its place in the Zarr store and to its CF metadata. A series a backend declares in `writes` carries the shape `time`, one value per period of the time grid, written at the station `catchment` for the whole catchment |
| `manifest.py`, `annotations.py`, `trash.py`, `retention.py` | the on-disk side of the rule: the seal, the human sidecars (`annotations.json`), the trash by move, its tombstones and `remove_for_good` (`trash.py`), and what `hmp catalog gc` collects, read from the tree alone (`retention.py`) |
| `record.py` | `RunRecord`: the seal built in memory by the run and written by it, `simulation.parquet`, `parameters.parquet`, `provenance.json`, `inputs.json`, then `manifest.json` last and durable; never opens the index |
| `outcome.py` | `outcome.json`, the issue of an attempt, and `effective_status()`: the one word a reader derives from a directory (manifest wins, then the outcome, then the pulse). The issue carries the `request_id` of the attempt, written as soon as its inputs are resolved, so the next attempt can tell whether it asks for the same thing |
| `request_identity.py` | what does a run ask for, and what computes the answer? `request_id(document, inputs, edition=)` is the sha256 of the document as a file writes it, without `[workspace]`, `[workflow]`, `simulation.name` and every `deliver_to` key (`REQUEST_EXCLUDED`). Each resolved input enters by the digest and the state of its bytes, and its path or URL leaves the document, so two addresses that give the same bytes ask the same thing. An earlier run the file reads enters by the digest of the arrays the run takes from it, never by its name or its `sim_id`. `solution_key(request_id, ...)` adds the code fingerprint, the mesh engine and its version, the sha256 of each solver binary and the versions of the numeric packages. Two runs with the same key give the same numbers, and a sealed run is given back only on an equal key. The module reads `core` and `results`, so its caller resolves the inputs and passes their digests. A source of an API whose extent comes from the delineated catchment is fetched after the identity is known, so it enters by its declaration, and the skip checks that its cached file still has the sha256 of `inputs.json` |
| `heartbeat.py` | `logs/heartbeat.json`, the pulse of a running attempt, and the thread that writes it |
| `checks.py` | the `checks` block of the seal: the measured facts (budget, convergence, coverage, verdicts, promoting session) a label derives from, and their flat columns |
| `validity_rules.py` | the label of a run as a function of reading: `label_for()` under versioned `ValidityRules`, and the `[[bug]]` rows of `schema/changes.toml` that declass the runs of the versions they touched |
| `identity.py` | the `identity` block every exported file carries, posed and read back per format: Zarr attributes, Parquet metadata, `gpkg_metadata`, PNG text chunk, `.meta.json` sidecar |
| `run_identity.py` | who a run directory is for a file derived from it: the manifest of a sealed run (`read_sealed_manifest`), its label of the day (`label_of`), and the identity block of a run still being computed |
| `lineage.py` | the `lineage` block of the seal: parent run, session, phase, trial, kind and overrides, by ids |
| `source_runs.py` | the run a configuration reads (`[flow] restart_from`, the `run` of a `[[mesh.refinement_zone]]`) named by its `sim_id`: `source_run_id()` resolves a reference, and `resolve_source_runs()` rewrites a configuration dict with it for the frozen `config.toml` |
| `rel_dir.py` | the one validator of every `rel_dir` field of the sealed formats, on `core.state.result_dirs.parse_rel_dir` |
| `ledger.py` | `figures/index.json` and `exports/index.json`: one entry per derived file, with its producer, options, version, digest and identity; `record_derived_file()` adds the entry of a file just written |
| `readme.py` | the generated `README.md` of a run, a session or a summary, with the digest of the manifest in its footer |
| `metric_rule.py` | `MetricsConfig` (the `[metrics]` section), `MetricRule` (station, window, version), `MetricRule.from_config` ([metrics] station, else [site] gauge; [metrics] window), `score()` and `score_run()`: a metric on the declared window only, with its sample count and where it was read; without a window there is no score |
| `fit_metrics.py` | the scores of a run under its rule, from its own timeseries table: `fit_metrics(run_dir, rule=...)` returns the manifest rows and the headline NSE at the rule station |
| `session/` | the formats of `sessions/<case>/`: `session.json` (`descriptor.py`), `trials.jsonl` with one trial number per session (`journal.py`), `phases/<phase>/session.json` (`phase.py`); `view.py` is `Session`, the read-only view of one session directory |
| `plan_store.py` | `plan/<hash>/` written once (plan.json, sites.parquet, cases.parquet, one TOML per case) and `plan/current`; a different content under an existing hash is refused |
| `publication.py` | `PublicationConfig`, `PUBLICATION.json` of a published copy, `published.jsonl` of its source, and `redact()`, the one function that removes host, user and absolute paths from anything that leaves the tree |
| `storage/json_io.py` | the atomic JSON writer of every document above; the durable variant (fsync) for the seal and the outcome; `read_sealed_json` and `read_transient_json`, which refuse a document of another version by the rule of `core/io/document_version.py` |
| `catalog/` | the index and its reader: `index_schema.py` is the DDL (one version, a change is a rebuild), `indexer.py` writes the index from the directories (full or incremental, staging and rename, the label computed and dated; `reindex_project` and `reindex_if_indexed` are what the commands call), `facade.py` is `Catalog`, the read-only view, with `reads.py`, `discovery.py` and `schema.py` as its concerns, `views.py` the summary views (`v_cases`, `v_simulation_summary`), `constants.py` the sense of each metric and `SIMULATIONS_FROM`, the one join of a run row to its codes, `parquet_views.py` the per-connection views over the Parquet payloads, `federation.py` the cross-project read of `simulation.parquet` files and the runs of a workspace (`list_workspace_runs`), `listing.py` the rows `hmp catalog ls`, `show`, `query`, `point`, `diff` and `rank` print, `liveness.py` what `hmp catalog watch` and `hmp doctor` read of running attempts from the directories, `privacy.py` the purge of a run and its certificate; `ports.py` is the `CatalogBackend` port, `adapters/duckdb.py` its DuckDB adapter, `protocol.py` the `SimulationStore` protocol, `registration.py` the reservation of versions and `storage_paths.py` the directory of a run |
| `run/` | `Run`, one finished simulation, and the providers behind it: `geographic`, `timeseries`, `hydrographic`, `array` (xarray), `point` (one variable at one place), `periods`, `descent`, `particles`; `sealed.py` reads what the seal says (site, case, lineage, checks, inputs, label, metrics); `group.py` is `RunSet`, a view over several runs, whose metric columns are named by metric, at the gauge, in the window of each run's rule |
| `run/field_envelope.py` | the minimum and maximum per cell of a field of an earlier sealed run, for the refinement zones of `[mesh]` (`read_run_fields`) |
| `run/tables.py` | the Parquet tables of one run read from its directory (`read_run_table`, `has_rows`); every Run reads its rows there, never from the index |
| `run/sealed_facts.py`, `run/ranking.py` | the facts a table of runs reads from each seal (`read_run_facts`, `overrides_text`, `place_of`), and the rows of sealed runs ranked by one metric under one rule (`rank_rows`, with `group.rank_key`), or why a group has none (`unscored_reason`) |
| `derive/` | what is computed on read from stored fields: virtual fields, catchment views, the read dispatch shared by `hmp.read` and `Catalog.read` (`reading.py`), time alignment, downsampling, the Brutsaert-Nieber recession cloud of a discharge (`recession.py`), and `stream/`, the stream-network criterion read on a finished run: its comparison with the mapped network, its flow extents, the routing surface and the depression floods the figures draw (`derive/stream/README.md`) |
| `exporters/` | one writer per format (CSV, GeoTIFF, NetCDF-UGRID, VTU, Shapefile, GeoPackage), the VTU one through `mesh/io/vtu.py`; `export_spec.py` is the `[[export]]` request and its output planner, `vocabulary.py` is the names a user may export, `request.py` `export_run` writes one `[[export]]` request under `runs/<run>/exports/`, poses the identity block and records `exports/index.json` (`README.md`) |
| `export/` | FAIR views built from a sealed directory (`directory.py`, `rocrate.py`, `stac.py`, `prov.py`); `publish.py` copies a run or a summary out of the tree (directory or tar, `PUBLICATION.json`, redaction, and with inputs the install index a caller builds); `project_package.py` writes a whole project with its data (`hmp publish --package`); `summary_tables.py` writes a table of runs as Parquet, CSV and GeoPackage with the same cells; `campaign_summary.py` writes the page, the README and the RO-Crate of a campaign summary (`hmp campaign collect`) (`README.md`) |
| `importers/` | readers symmetric to the exporters: CSV series, NetCDF fields, one Zarr field |
| `geographic_cache.py`, `spatial_index.py`, `grid.py` | the workspace cache of geographic arrays keyed by a fingerprint, point-in-cell lookup on a mesh, the cell size and extent of a run |
| `calibration_trials.py`, `errors.py` | the trial rows of a session for one run, the typed errors of the reader |

## Import rules

`tests/unit/architecture/layer_matrix.yaml` gives results `core`, `schema`,
`catchment` and itself. It does not import `config`: `PublicationConfig`
(`publication.py`) and `MetricsConfig` (`metric_rule.py`) live here. No `results_layout.yaml` orders the parts inside
the package, and they do import each other: `catalog` composes `run`,
`derive`, `exporters`, `zarr_store` and the sidecars, and `run` and `derive`
call back into `catalog` and `zarr_store`. Rules that hold:

1. `results` never imports `data`, `solver` or `catalog` (the
   top-level facade layer). Names those layers write are restated here and
   point to the module that writes them (`exporters/vocabulary.py`).
2. The cache database of `data` is never opened by `results`: the three
   DuckDB scopes (the data cache, the project index, the in-memory Parquet
   probes of `display`) are never merged.
3. `catalog/facade.py` opens the index read-only and wraps the connection in
   the `CatalogBackend` port (`adapters/duckdb.py`); `catalog/indexer.py` is
   the only writer. Code outside `results` reaches the index through
   `Catalog`, the diagnostics (`hmp doctor`) open it raw
   and read-only, and the verbs that watch a project (`hmp catalog watch`,
   `hmp project status`) read the outcomes and never the index:
   `tests/unit/architecture/test_storage_boundary.py` pins the modules that
   may call `duckdb.connect`, the ones that may open a DuckDB file for
   writing, and patches `Catalog.__init__` to raise under `watch`.
4. A new Parquet view or a new stored field changes the layout contract:
   `tests/unit/results/test_run_layout_contract.py` gates it.

Who imports results: `display` (most), `cli`, `workflow`,
`calibration`, `project` and the package root.

## Tree

```
hydromodpy/results/
  __init__.py                  lazy Catalog
  storage/       contract.py  parquet_io.py  parquet_schemas.py  diagnostics.py
  zarr_store/    simulation_zarr.py  zarr_writer.py  zarr_reader.py  zarr_finalizer.py  chunks.py ...
  field_registry.py  manifest.py  annotations.py  trash.py  retention.py  record.py  outcome.py
  request_identity.py
  run_identity.py  metric_rule.py  fit_metrics.py ...
  catalog/       index_schema.py  indexer.py  facade.py  reads.py  discovery.py  schema.py
                 views.py  parquet_views.py  federation.py  registration.py  storage_paths.py
                 listing.py  liveness.py  privacy.py
                 ports.py  protocol.py  adapters/duckdb.py  dataset_loader.py
  run/           view.py (Run)  group.py (RunSet)  geographic.py  timeseries.py  hydrographic.py
                 array.py  point.py  periods.py  descent.py  particles.py ...
  derive/        virtual_fields.py  views.py  reading.py  run_memo.py  time_alignment.py ...
                 stream/  network.py  extent.py  heads.py  geometry.py  comparison.py  run_extent.py
                          heads_view.py  criterion_settings.py  routing_surface.py  depressions.py
  exporters/     csv.py  geotiff.py  netcdf.py  vtu.py  shapefile.py  geopackage.py
                 vocabulary.py  request.py
  export/        rocrate.py  stac.py  prov.py  directory.py  publish.py  project_package.py  campaign_summary.py
                 summary_tables.py
  importers/
  geographic_cache.py  spatial_index.py  grid.py
```

## How a run is written and read

1. The run claims `runs/<name>[.vN]` on disk (`storage/attempt.py`, and `reserve_version_dirname`
   of `catalog/registration.py` for a new version) and writes `outcome.json` and the pulse. The
   claim holds no identity. Its `sim_id` is a uuid taken here, and it enters no fingerprint.
2. Once the inputs are resolved, the run computes its `request_id` and writes it into
   `outcome.json`. A restart of the directory compares it with the one of the last attempt, and
   starts over when they differ. A run that is not a resume, a window or a forced run then
   computes its `solution_key`. If a sealed run of the same name, or one of its `.vN` versions, has the same key, the claim is
   withdrawn without a trace and that run is given back. A run of 2.0 has no key of this kind, so
   it is computed once again.
3. The solver and extraction code write through the run store of the directory
   (`storage/run_store.py`): arrays into `fields.zarr`, tables into `tables.parquet/` (each one a
   `pyarrow` table built on a schema of `storage/parquet_schemas.py`). No index is opened.
4. The run builds its `RunRecord` (`record.py`) in memory and writes `simulation.parquet`,
   `parameters.parquet`, `provenance.json`, `inputs.json`, then `manifest.json`, last and
   durable. A run directory without a manifest never finished.
5. `Catalog.find(**filters)` returns a `RunSet`, and `catalog[ref]` returns a `Run`. `hmp.open`
   is the door from Python: it returns a `Project` whose `store` is the `Catalog`, `proj[ref]` is
   a `Run` and `proj.runs()` a `RunSet`.
6. `Run` and its providers read the Zarr and Parquet files. `derive/reading.py` is the single
   dispatch behind `hmp.read` and `Catalog.read`: a Zarr field gives an `xarray.DataArray`, a
   series a `pandas.Series`, a geographic feature a `GeoDataFrame`. A virtual field of
   `derive/virtual_fields.py` is computed from stored ones when asked.
7. `exporters/request.py` plans the files of one `[[export]]` request and hands each to the
   exporter of its kind. The FAIR views and `export/publish.py` carry a whole run.
8. The launcher calls `index_new_runs()` once the worker exited, and `hmp catalog reindex`
   rebuilds the whole index. `catalog/indexer.py` reads every `runs/<name>/`, `sessions/<name>/`
   and kept trial into a staging file, computes the label of each sealed run with the rules and
   the bugs of `schema/changes.toml` in this build, and publishes the file in one rename. The
   index keeps no seed of its own: the solver category of a run comes from its manifest,
   `unknown` when the manifest predates it. `cases` lists every directory with its effective
   status, `simulations` the sealed runs, `sites` the sites they name.

## Where to add what

| to add | where |
|---|---|
| a stored field | an entry of `field_registry.py` (name, path, CF metadata), its writer in `zarr_store/`, a name in `exporters/vocabulary.py` if users may export it |
| a Parquet view | a schema in `storage/parquet_schemas.py`, its write in `storage/run_store.py`, its place in `storage/contract.py`; a payload the index copies into a table also gets its read-back in `catalog/indexer.py` |
| an index table or column | its DDL in `catalog/index_schema.py` (bump `INDEX_SCHEMA_VERSION`: a schema change is a full rebuild) and its read-back in `catalog/indexer.py`: nothing the index holds may be missing from disk |
| a stored document | a version field (`schema` id or `*_version`), a reader through `storage/json_io.read_sealed_json` (or `read_transient_json` for attempt state), and a case in `tests/unit/results/test_every_document_carries_its_version.py`; a change of format bumps the version, never a migration |
| a value a person sets after the seal | a sidecar next to `manifest.json`, read back by `indexer.py` and part of the stamp that triggers a refresh (`annotations.py` is the model) |
| a computed field | a function in `derive/virtual_fields.py`, so it needs no storage |
| a `Run` accessor | a provider in `run/` bound in `run/view.py` |
| an export format | a module in `exporters/`, its kind in `exporters/vocabulary.py`, its route in `exporters/request.py`; see `docs/source/contribute/architecture/how-to/add-an-exporter.rst` |
| a FAIR view | a module in `export/`, with its `directory.py` counterpart |
| a catalog backend | an adapter of the `CatalogBackend` port in `catalog/adapters/` |
| a cross-project read | `catalog/federation.py`, on the `simulation.parquet` of each run, never on an index |
