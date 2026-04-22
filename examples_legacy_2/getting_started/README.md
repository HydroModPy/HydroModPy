# Getting started

A self-contained 1D Dupuit aquifer example — steady state, uniform
recharge, MODFLOW-NWT. No external DEM or downloaded data is required.

## Files

- `project.toml` — complete HydroModPy configuration (synthetic mode).
- `run_sim.py`   — 10-line Python script that calls `hmp.run(...)`.

## Run it

From the repository root:

```bash
# CLI
hmp run examples/getting_started/project.toml

# Python
python examples/getting_started/run_sim.py
```

Outputs land in `examples/getting_started/`:

- `hydromodpy.duckdb` — unified simulation catalog.
- `simulations/<uuid>.zarr/` — spatial fields and metadata for each run.

## Next steps

- `examples/projects/01_canut/` — a realistic delineated catchment.
- `docs/developers/` — architecture, patterns, and contracts.
