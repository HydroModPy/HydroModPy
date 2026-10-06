# `hydromodpy/catalog`

A read-only view over the input cache of a workspace. The package is one class,
`InputsNamespace`, which answers "what did this workspace download or convert,
and for which extent?" from `<workspace>/data/cache.duckdb`. It is exposed as
`hmp.catalog`. This file is the map of the package, and of the two other DuckDB
scopes people confuse it with.

## Three DuckDB scopes, three doors

| scope | file | door | returns |
|---|---|---|---|
| input cache of a workspace | `<workspace>/data/cache.duckdb` | `hydromodpy.catalog.InputsNamespace(workspace)` | `InputsNamespace` (this package) |
| runs of a project | `<project>/.hmp/index.duckdb` | `hmp.open(...)` | `hydromodpy.results.catalog.Catalog` |
| projects of the machine | the global index | `hmp.index(...)` | `hydromodpy.core.state.global_index.GlobalIndex` |

The index of a project is derived: the run folders (`runs/`, `sessions/`) are the
truth, and `hmp catalog reindex` rebuilds it. The `hmp catalog` CLI family works
on the second scope, not on this package.

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

## Writes to the run catalog

The write surface of the run catalog is not in this package. It lives in
`hydromodpy/results/catalog/writes_duckdb.py` (`WritesMixinDuckDB`, consumed by
`Catalog`). Four mutators edit what a run already has. Each is audited, wrapped
in `with_lock_retry` so concurrent CLI calls serialise, and returns early when
`PersistenceConfig.save_catalog` is false, so one switch governs the DuckDB sink.

| mutator | effect |
|---|---|
| `rename_simulation(sim_id, new_name)` | moves the run directory and updates the row; raises `DuplicateSimulationNameError` when the name slot or the directory is taken |
| `remove_tag(sim_id, tag)` | drops one tag; returns `True` when a row was removed |
| `update_parameter(sim_id, param_name, value, *, zone_id=None, unit=None, parameterization=None)` | updates an existing parameter row; raises `KeyError` when the `(sim_id, param_name, zone_id)` row is absent |
| `remove_tracked_file(sim_id, role, canonical_path)` | drops one row of `tracked_files`; returns `True` when a row was removed |

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
3. **A machine-wide read.** In `hydromodpy/core/state/global_index.py`.
