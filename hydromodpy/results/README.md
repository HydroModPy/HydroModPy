# `hydromodpy/results`

What a run leaves on disk, and how it is read back. Each run owns a directory
of Zarr arrays and Parquet tables, sealed by a manifest. A DuckDB index lists
the runs so they can be found, ranked and compared. `Catalog` writes and
reads the project; `Run` is one finished simulation. Exporters turn a run
into the formats others use.
This file is the map of the package: what each part answers, the import
rules, how a run is written and read, and where to add what.

## The rule

Disk is the truth, the index is derived. Everything execution code reads back
from a run is also written inside its directory: `manifest.json` seals the
run, `provenance.json` records the environment, the sidecars
`annotations.json` and `trash.json` keep what a person set afterwards, and
`sessions/<name>/` keeps the calibration trials. `hmp catalog reindex`
(`catalog/reindex.py`) rebuilds `.hmp/index.duckdb` from those files, and
running it twice describes the project identically. The layout is
`storage/contract.py`; the full contract is
`docs/source/contribute/architecture/storage-layout.rst`.

## Parts

| part | answers |
|---|---|
| `storage/` | what a run and a session directory hold (`contract.py`), how a Parquet table is written (`parquet_io.py`, one schema per view in `parquet_schemas.py`), lazy loaders, input fingerprints, layout diagnostics |
| `zarr_store/` | the per-run Zarr 3 array store `SimulationZarr`: writer, reader, finalizer, schema, ACDD and CF metadata, chunk and shard sizes |
| `field_registry.py` | the one table that maps a field name to its place in the Zarr store and to its CF metadata |
| `manifest.py`, `annotations.py`, `trash_marker.py`, `session_journal.py` | the on-disk side of the rule: the seal, the human sidecars, the trial history of a calibration session |
| `catalog/` | `Catalog`, the project facade: registration of a run, writes, reads, discovery by filter, schema discovery, `.hmp` packages, lifecycle, reindex; `ports.py` is the `CatalogBackend` port, `adapters/duckdb.py` its DuckDB adapter, `protocol.py` the `SimulationStore` protocol, `migrations/` the numbered SQL files |
| `run/` | `Run`, one finished simulation, and the providers behind it: `geographic`, `timeseries`, `hydrographic`, `array` (xarray), `point` (one variable at one place), `periods`, `descent`, `particles`; `group.py` is `RunSet`, a view over several runs |
| `derive/` | what is computed on read from stored fields: virtual fields, catchment views, the read dispatch shared by `hmp.read` and `Catalog.read` (`reading.py`), stream-network comparisons, time alignment, downsampling |
| `exporters/` | one writer per format (CSV, GeoTIFF, NetCDF-UGRID, VTU, Shapefile, GeoPackage, `.hmp` package); `vocabulary.py` is the names a user may export and their kind, `request.py` writes one `[[export]]` request |
| `export/` | FAIR views of a run: RO-Crate, STAC, PROV-O, and the same views built from a sealed directory alone (`directory.py`) |
| `importers/` | readers symmetric to the exporters: CSV series, NetCDF fields, one Zarr field, the inputs folder of a `.hmp` archive |
| `geographic_cache.py`, `spatial_index.py`, `grid.py` | the workspace cache of geographic arrays keyed by a fingerprint, point-in-cell lookup on a mesh, the cell size and extent of a run |
| `calibration_trials.py`, `errors.py`, `html_helpers.py` | the trial rows of a session for one run, the typed errors of the reader, HTML helpers shared by report builders |

## Import rules

`tests/unit/architecture/layer_matrix.yaml` gives results `core`, `schema`,
`config`, `spatial` and itself. Today it imports `core`, `schema` and
`spatial`, and no `config`. No `results_layout.yaml` orders the parts inside
the package, and they do import each other: `catalog` composes `run`,
`derive`, `exporters`, `zarr_store` and the sidecars, and `run` and `derive`
call back into `catalog` and `zarr_store`. Rules that hold:

1. `results` never imports `data`, `simulation`, `solver` or `catalog` (the
   top-level facade layer). Names those layers write are restated here and
   point to the module that writes them (`exporters/vocabulary.py`).
2. The cache database of `data` is reached by a read-only DuckDB `ATTACH`
   (`catalog/cross_db.py`), not by an import. The three DuckDB scopes are
   never merged.
3. `catalog/facade.py` opens the DuckDB connection and wraps it in the
   `CatalogBackend` port (`adapters/duckdb.py`). Code outside `results`
   reaches DuckDB through `Catalog`, never through its own connection:
   `tests/unit/architecture/test_storage_boundary.py` checks the direct
   `duckdb.connect` calls of `_api.py` and of the CLI commands. Inside
   `results`, the views, the audit log, the CSV exporter, the `.hmp` package
   and the storage diagnostics still use `duckdb` directly.
4. A new Parquet view or a new stored field changes the layout contract:
   `tests/unit/results/test_run_layout_contract.py` gates it.

Who imports results: `display` (most), `cli`, `workflow`, `analysis`,
`calibration`, `project`, `reporting` and the package root.

## Tree

```
hydromodpy/results/
  __init__.py                  lazy Catalog
  storage/       contract.py  parquet_io.py  parquet_schemas.py  lazy_loaders.py  diagnostics.py
  zarr_store/    simulation_zarr.py  zarr_writer.py  zarr_reader.py  zarr_finalizer.py  chunks.py ...
  field_registry.py  manifest.py  annotations.py  trash_marker.py  session_journal.py
  catalog/       facade.py  ports.py  protocol.py  adapters/duckdb.py  migrations/
                 registration.py  lifecycle.py  writes*.py  reads.py  discovery.py
                 reindex.py  views.py  parquet_views.py  package_io.py  cross_db.py ...
  run/           view.py (Run)  group.py (RunSet)  geographic.py  timeseries.py  hydrographic.py
                 array.py  point.py  periods.py  descent.py  particles.py ...
  derive/        virtual_fields.py  views.py  reading.py  stream_network.py  time_alignment.py ...
  exporters/     csv.py  geotiff.py  netcdf.py  vtu.py  shapefile.py  geopackage.py
                 hmp_package.py  vocabulary.py  request.py
  export/        rocrate.py  stac.py  prov.py  directory.py
  importers/
  geographic_cache.py  spatial_index.py  grid.py
```

## How a run is written and read

1. **Register.** `catalog/registration.py` allocates the `sim_id`, applies the
   collision rule (replace, fail or version), derives `runs/<name>` from the
   final run name and creates `fields.zarr` at its final path, so a reader can
   open it while the run is still solving.
2. **Write.** The solver and extraction code write through the `Catalog`:
   arrays through `writes_zarr.py`, tables through `writes_parquet.py` (each
   one a `pyarrow` table built on a schema of `storage/parquet_schemas.py`),
   index rows through `writes_duckdb.py`.
3. **Seal.** `Catalog.finalize` (`catalog/lifecycle.py`) calls
   `manifest.py`: the parameters table, `provenance.json`, then
   `manifest.json`, written last and atomically. A run directory without a
   manifest never finished.
4. **Find.** `Catalog.find(**filters)` returns a `RunSet`; `catalog[ref]`
   returns a `Run`. `hmp.open` is the door from Python.
5. **Read.** `Run` and its providers read the Zarr and Parquet files.
   `derive/reading.py` is the single dispatch behind `hmp.read` and
   `Catalog.read`: a Zarr field gives an `xarray.DataArray`, a series a
   `pandas.Series`, a geographic feature a `GeoDataFrame`. A virtual field of
   `derive/virtual_fields.py` is computed from stored ones when asked.
6. **Export.** `exporters/request.py` plans the files of one `[[export]]`
   request and hands each to the exporter of its kind. `.hmp` packages and the
   FAIR views carry a whole run.
7. **Rebuild.** `hmp catalog reindex` reads every `runs/<name>/` and
   `sessions/<name>/` back into a fresh index and swaps it in.

The connection opens through `connect_with_retry`, and some write methods carry
`with_lock_retry`, so a short lock held by another process resolves on its own.

## Where to add what

| to add | where |
|---|---|
| a stored field | an entry of `field_registry.py` (name, path, CF metadata), its writer in `zarr_store/` or `catalog/writes_zarr.py`, a name in `exporters/vocabulary.py` if users may export it |
| a Parquet view | a schema in `storage/parquet_schemas.py`, its write in `catalog/writes_parquet.py`, its place in `storage/contract.py`; a view the index needs also gets its rebuild in `catalog/reindex.py` |
| an index table or column | a new numbered file in `catalog/migrations/`, and the matching read-back in `catalog/reindex.py`: nothing the index holds may be missing from disk |
| a value a person sets after the seal | a sidecar next to `manifest.json`, written after the index row, read back by `reindex.py` (`annotations.py` and `trash_marker.py` are the model) |
| a computed field | a function in `derive/virtual_fields.py`, so it needs no storage |
| a `Run` accessor | a provider in `run/` bound in `run/view.py` |
| an export format | a module in `exporters/`, its kind in `exporters/vocabulary.py`, its route in `exporters/request.py`; see `docs/source/contribute/architecture/how-to/add-an-exporter.rst` |
| a FAIR view | a module in `export/`, with its `directory.py` counterpart |
| a catalog backend | an adapter of the `CatalogBackend` port in `catalog/adapters/` |
