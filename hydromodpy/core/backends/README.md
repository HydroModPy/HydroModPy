# Backends

`hydromodpy/core/backends/` contains thin adapters around optional third-party
runtime dependencies.

Today the package exposes one backend family implemented with
`whitebox_workflows.WbEnvironment`.

## Why this package exists

HydroModPy uses Whitebox operations from several places:

- geographic preprocessing (`catchment_from_point`, `domain_dem`,
  `flow_products`);
- legacy geographic helpers;
- routing and mass-transfer post-processing on the solver side.

Instead of letting those modules instantiate workflow objects directly, the
project isolates the dependency behind a small HydroModPy contract. This gives
three practical benefits:

- runtime code depends on a narrow HydroModPy API, not on the full third-party
  surface;
- tests can inject a fake backend implementing the same protocol;
- the concrete implementation can change later without rewriting all callers.

## Files

- `whitebox_backend.py`
  Defines `WhiteboxBackend`, a `Protocol` that documents the operations
  expected by HydroModPy runtime code.
- `whitebox_workflows_backend.py`
  Provides `WhiteboxWorkflowsBackend`, the runtime adapter implemented with
  `whitebox_workflows.WbEnvironment`.
- `__init__.py`
  Re-exports the public backend API for callers.

## Design notes

### Hybrid contract

The public runtime contract remains file-oriented because HydroModPy still
persists canonical rasters and vectors on disk. The workflows backend also
exposes in-memory helpers so chained geographic operations can avoid redundant
read/write cycles between intermediate steps.

### Thin adapter on purpose

The backend intentionally contains almost no business logic. Its job is to
translate HydroModPy method names and keyword arguments to the underlying
third-party implementation.

### Shared default instance

`get_whitebox_backend()` caches a single adapter instance per Python process.
That keeps the default runtime path simple while still allowing explicit
dependency injection where needed.

### Workflows-only runtime

HydroModPy runtime code no longer selects between `whitebox` and
`whitebox_workflows`. `get_whitebox_backend()` always resolves to the
workflows-backed adapter and rejects the legacy `whitebox` selector. The old
`WhiteboxToolsBackend` compatibility shim has been removed.

## Typical usage

```python
from hydromodpy.core.backends import get_whitebox_backend

wbt = get_whitebox_backend()
wbt.fill_depressions("dem.tif", "dem_filled.tif")
wbt.d8_pointer("dem_filled.tif", "flow_dir.tif")
```

For testability, many HydroModPy functions accept a `backend` parameter typed
as `WhiteboxBackend | None`. Passing a fake implementation is the preferred way
to isolate filesystem side effects in unit tests.
