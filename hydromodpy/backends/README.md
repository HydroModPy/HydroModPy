# Backends

`hydromodpy/backends/` contains thin adapters around optional third-party
runtime dependencies.

Today the package exposes one backend family: WhiteboxTools.

## Why this package exists

HydroModPy uses Whitebox operations from several places:

- geographic preprocessing (`catchment_from_point`, `domain_dem`,
  `flow_products`);
- legacy geographic helpers;
- routing and mass-transfer post-processing on the solver side.

Instead of letting those modules instantiate `whitebox.WhiteboxTools`
directly, the project isolates the dependency behind a small file-based
contract. This gives three practical benefits:

- runtime code depends on a narrow HydroModPy API, not on the full third-party
  surface;
- tests can inject a fake backend implementing the same protocol;
- the concrete implementation can change later without rewriting all callers.

## Files

- `whitebox_backend.py`
  Defines `WhiteboxBackend`, a `Protocol` that documents the operations
  expected by HydroModPy runtime code.
- `whitebox_tools_backend.py`
  Provides `WhiteboxToolsBackend`, the default adapter implemented with
  `whitebox.WhiteboxTools`.
- `__init__.py`
  Re-exports the public backend API for callers.

## Design notes

### File-oriented contract

The backend methods operate on paths, not on in-memory arrays. That matches the
way WhiteboxTools is used in HydroModPy pipelines: intermediate rasters and
vectors are materialized on disk and then consumed by the next pipeline step.

### Thin adapter on purpose

`WhiteboxToolsBackend` intentionally contains almost no business logic. Its job
is only to translate HydroModPy method names and keyword arguments to the
underlying WhiteboxTools object.

### Shared default instance

`get_whitebox_backend()` caches a single adapter instance per Python process.
That keeps the default runtime path simple while still allowing explicit
dependency injection where needed.

## Typical usage

```python
from hydromodpy.backends import get_whitebox_backend

wbt = get_whitebox_backend()
wbt.fill_depressions("dem.tif", "dem_filled.tif")
wbt.d8_pointer("dem_filled.tif", "flow_dir.tif")
```

For testability, many HydroModPy functions accept a `wbt_tool` parameter typed
as `WhiteboxBackend | None`. Passing a fake implementation is the preferred way
to isolate filesystem side effects in unit tests.
