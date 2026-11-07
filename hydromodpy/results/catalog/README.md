# results/catalog

This folder answers how the runs of a project are found, ranked and compared. The index `.hmp/index.duckdb` is
derived from the run and session directories, and it can be rebuilt at any time. `Catalog` reads it and nothing
more. The indexer is the only writer.

## How the work flows

1. `registration.py` reserves the name of a run directory (`reserve_version_dirname`) and computes the identity
   hashes of a configuration.
2. The indexer (`indexer.py`) reads every run, session and kept trial into a staging file. It publishes that file
   in one rename. `rebuild_index` does the whole tree and `index_new_runs` does a diff.
3. `index_schema.py` is the DDL of the index. A change of schema is a full rebuild. `views.py` adds the summary views.
4. `Catalog` (`facade.py`) opens the index read-only through the `CatalogBackend` port, with its adapter in
   `adapters/duckdb.py`.
5. `discovery.py` turns a reference (a name, an id, `@last`, `@best:METRIC`) into a run. `reads.py` holds the queries.
6. `catalog[ref]` gives a `Run`. `Catalog.query_timeseries`, `query_budget` and `query_mass_balance` delegate to
   the `Run`. `read_geographic_feature`, `list_geographic_features` and `read_geographic_metadata` read the run
   directory, not the index.
7. `listing.py` holds the reads behind `hmp catalog ls`, `show`, `query`, `point`, `diff` and `rank`. `liveness.py`
   and `privacy.py` read the directories and never open the index, so `hmp catalog watch`, `hmp doctor` and the purge
   of a run answer while the index is being rebuilt.

## The folder map

```text
catalog/
├── facade.py          Catalog, the read-only view
├── discovery.py       references, Run and RunSet discovery
├── reads.py           queries of the index and reads of a run
├── schema.py          tables, columns and describe
├── constants.py       solver codes, metric order, SIMULATIONS_FROM
├── indexer.py         the only writer of the index, and the reindex calls
├── index_schema.py    DDL and schema version
├── views.py           summary views written with the tables
├── registration.py    run directory names, identity hashes
├── storage_paths.py   paths of the artifacts of a run
├── federation.py      sealed runs of several projects, no index
├── listing.py         the rows ls, show, query, point, diff and rank print
├── liveness.py        running and abandoned attempts, read from the directories
├── privacy.py         purge a run for good and check its certificate
├── parquet_views.py   DuckDB views over the Parquet tables of a run
├── dataset_loader.py  a catalog-wide dataset for model training
├── ports.py           CatalogBackend protocol
├── protocol.py        SimulationStore protocol
└── adapters/duckdb.py the DuckDB backend
```

`constants.py` holds `SIMULATIONS_FROM`, the one join of a run row to the codes of its solver, status, flow regime
and mesh topology. Every reader of a run row uses it.

## Where to add what

| To add | Where |
|--------|-------|
| an index table or column | `index_schema.py`, its read-back in `indexer.py`, and a bump of the schema version |
| a summary view | `views.py` |
| a query of the index | `reads.py` |
| a form of reference | `discovery.py` |
| a run row read with its codes | start from `SIMULATIONS_FROM` in `constants.py` |
| another database engine | an adapter of the `CatalogBackend` port in `adapters/` |
| a read across projects | `federation.py` |
| a listing of runs for a command | `listing.py` |
| a read of running attempts that must not need the index | `liveness.py` |
