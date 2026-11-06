# data/registry

This folder is the index of the data cache. The files on disk and their sidecars stay the truth.
The index is a DuckDB file (`data/cache.duckdb` in a workspace) that answers one question fast:
which file holds this variable, from this source, over this box and these dates.

## Three ways to open the cache

- Read-write, the default. One process owns the file while it is open.
- Read-only (`read_only=True`). Many processes read together and nothing is written.
  `hmp data` and the `--frozen` check open it this way.
- Layered, inside a case that the launcher started. The environment names a private cache. Writes go
  there. A read asks the shared cache first, opened read-only for that one query, then the private
  file. `merge_private_cache` folds the private file into the shared one when the case ends.

## The folder map

```text
registry/
├── catalog_duckdb.py   DataCatalogDuckDB, the class callers use, and merge_private_cache
├── cache_store.py      connection helpers, register, path encoding, frozen-mode checks, sidecar emit
├── cache_queries.py    read-only lookups: find_cached, entry_for_file, list_entries
├── cache_lifecycle.py  invalidate, prune, cleanup, repair, and the small insert tables
├── backend.py          the SQL port (CacheBackend) and its DuckDB adapter
├── freeze.py           write, verify and archive hydromodpy.lock from the index
├── input_cache.py      InputCache, the read-only view of a workspace cache
├── constants.py        the two sentinel paths of a custom or empty entry
└── migrations/         numbered SQL files and the runner that applies them at open
```

## Why the class and the three modules are separate

`DataCatalogDuckDB` passes itself as first argument to the functions of the three modules. The
layered cache needs this. A lookup runs the same function on the shared catalog and then on the
private one, so the function cannot live inside one instance. The cost is that a method of the
class repeats the keyword list of its function. When you add a parameter, change both.

## Rules

- A shipped migration never changes, not even a comment. A cache records its checksum and refuses
  any other. Write a new numbered file.
- Every SQL statement goes through `catalog.backend`. No module reads the raw connection.
- The files and their sidecars are the truth. A chronicle sidecar speaks without the index.
- A cache miss in frozen mode is an error, never a download.

## Changing the code

The tests are in `tests/unit/data/registry/` and `tests/unit/data/migrations/`. The SQL is held
still by `tests/regression/data/test_data_catalog_golden.py`.
