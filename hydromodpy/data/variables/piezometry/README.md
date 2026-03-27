# Piezometry Data Manager

`hydromodpy.data.piezometry` provides tools to load, inspect, and export
piezometric time series as station-level datasets.

## Current layout

- `piezometer.py`: single station object (`Piezometer`).
- `piezometer_set.py`: multi-station orchestrator (`PiezometerSet`).
- `loaders_api.py` / `loaders_local.py`: source-specific loaders.
- `piezometry_config.py`: TOML schema + validation.
- `piezometry.py`: backward-compatible import location for legacy class.
- `cases/run_piezometry_case.py`: executable case runner.
- `cases/run_piezometry_config.toml`: case configuration file.
- `cases/outputs/` and `cases/exports/`: case outputs.

## Backward compatibility

- `run_piezometry_example.py` is kept as a shim and delegates to
  `cases/run_piezometry_case.py`.
- Existing imports of `Piezometer` and `PiezometerSet` are unchanged.

## Run the case

```bash
python hydromodpy/data/piezometry/cases/run_piezometry_case.py
```

Or via legacy shim:

```bash
python hydromodpy/data/piezometry/run_piezometry_example.py
```

