# core/io

This folder answers: how do I read, write or fetch a file the same safe way everywhere? These are the
low-level primitives; nothing here knows a hydrogeological rule.

## Modules, by use

1. `filesystem.py`, `file_digest.py` and `atomic_replace.py` make folders, give the one SHA-256 of a file, and replace a file in a single rename so a reader never sees half of it.
   `filesystem.py` also knows the Windows path limit. `WINDOWS_PATH_LIMIT` is 259 and `PROJECT_TREE_DEPTH` is 160, the longest path a project writes below its folder, so `check_project_root` refuses a project folder over 99 characters on Windows with a `ConfigError`. `native_io_path` is the one place that adds the `\\?\` prefix. `link_or_copy` hard-links a file and, when the system refuses the link, copies it without ever overwriting the target. `rename_onto_empty_dir` moves a folder onto a name a `mkdir` reserved, with a second step on Windows where `os.replace` refuses a folder. `unlink_when_free` removes a file and tries again on a `PermissionError`, because Windows refuses to remove a file a reader holds open. `replace_when_free` is its sister for a rename: it moves a file with `os.replace` and tries again on a `PermissionError` with the same six tries, which `LockFile` uses to move a lock aside before removing it. Both try again on Windows only; elsewhere the error is permanent and raised at once. `rename_over_open_file` of `atomic_replace.py` publishes a file over one a reader may hold, with the same tries on Windows.
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
- A hard link, a limit on a path length or a rename onto a reserved folder: through `filesystem.py`, never `os.link` or a length test written again elsewhere.
- A removal that a reader may block on Windows: `unlink_when_free`, or a rename: `replace_when_free`. A file published over one a reader may hold: `rename_over_open_file`.
- A DuckDB open: through `db_retry.py`, never `duckdb.connect` directly.

The layer rules are checked by `tests/unit/architecture/`.
