# core/io

This folder answers: how do I read, write or fetch a file the same safe way everywhere? These are the
low-level primitives; nothing here knows a hydrogeological rule.

## Modules, by use

1. `filesystem.py`, `file_digest.py` and `atomic_replace.py` make folders, give the one SHA-256 of a file, and replace a file in a single rename so a reader never sees half of it.
2. `canonical_json.py` writes deterministic JSON (`json_dumps`, `json_loads`), and `document_version.py` is the version rule of every stored document: a reader refuses a version it does not know and says so.
3. `raster_io.py`, `vector_io.py`, `geoparquet.py` and `parquet.py` load and write rasters, vectors, GeoParquet 1.1 and plain Parquet with the canonical options.
4. `crs.py` and `proj_bootstrap.py` hold the CRS helpers and the opt-in PROJ database setup.
5. `fetch.py` is the single download module. It creates an `HTTPClient` per call with its `Bounds`, resolves final redirect targets manually, caps bytes at 2 GiB by default, refuses private addresses unless allowed by name, and verifies pinned sha256 digests. It also exposes `vsicurl_path` for GDAL.
6. `db_retry.py` is the single open point of every DuckDB file, with its lock retry.

## What other layers import from it

`results`, `catchment`, `data`, `solver`, `schema`, `workflow` and `model`.

## Where to add what

- A new file format: one module, writing through `atomic_replace.py`.
- A new stored document: a `schema` id and a check through `document_version.py`.
- A lock file that is empty or torn JSON for more than 5 s is stale (`TORN_AFTER_S`); a younger one is held.
- A DuckDB open: through `db_retry.py`, never `duckdb.connect` directly.

The layer rules are checked by `tests/unit/architecture/`.
