# `hydromodpy/catalog`

A read-only view over the input cache of a workspace. The package is one class,
`InputsNamespace`, which answers "what did this workspace download or convert,
and for which extent?" from `<workspace>/data/cache.duckdb`. It is exposed as
`hmp.catalog`. This file is the map of the package, and of the other DuckDB
scope people confuse it with.

## Two DuckDB scopes, two doors, and one read without any

| scope | file | door | returns |
|---|---|---|---|
| input cache of a workspace | `<workspace>/data/cache.duckdb` | `hydromodpy.catalog.InputsNamespace(workspace)` | `InputsNamespace` (this package) |
| runs of a project | `<project>/.hmp/index.duckdb` | `hmp.open(...).store` | `hydromodpy.results.catalog.Catalog`, read-only |
| runs of several projects | none: the `simulation.parquet` of each run | `hydromodpy.results.catalog.read_workspace_runs(...)` | a `DataFrame` |

The index of a project is derived: the run folders (`runs/`, `sessions/`) are the
truth, the indexer (`hydromodpy/results/catalog/indexer.py`) writes it, and
`hmp catalog reindex` rebuilds it. There is no machine-wide registry. The
`hmp catalog` CLI family works on the second scope, not on this package.

## Parts

| part | answers |
|---|---|
| `__init__.py` | the one public name, `InputsNamespace` |
| `inputs.py` | `InputsNamespace`: `db_path`, `has_cache()`, `list(variable=, source=, limit=)`, `find(variable=, source=, station_id=, bbox=)`, `close()` |

`InputsNamespace` opens a `DataCatalogDuckDB` (`hydromodpy/data/registry/`) on its
first call and delegates to its `list_entries` and `find_cached`. It holds no SQL
of its own.

```python
from hydromodpy.catalog import InputsNamespace

inputs = InputsNamespace("~/ws")
inputs.list(variable="recharge")
```

## Import rules

`catalog` imports `core`, `schema`, `data` and `results`
(`tests/unit/architecture/layer_matrix.yaml`). `project`, `cli` and the root
facade import it. The reverse edge is forbidden: `data` and `results` never import
`catalog`, so the package stays a one-way wrapper.

`tests/unit/architecture/test_layer_matrix.py` checks the rule.

## Where to add what

1. **A read of the input cache.** A method of `InputsNamespace` that delegates to
   `DataCatalogDuckDB`. The query itself goes in `hydromodpy/data/registry/`.
2. **A read or a write of the run catalog.** In `hydromodpy/results/catalog/`,
   not here.
3. **A read across projects.** `hydromodpy/results/catalog/federation.py`, on the
   `simulation.parquet` files, never on an index.
