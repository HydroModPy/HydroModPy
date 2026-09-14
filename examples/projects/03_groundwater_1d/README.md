# 03 - Groundwater 1D, analytical case

Pure-Python Dupuit-Forchheimer 1D aquifer, calibrated against a noisy synthetic
head chronicle. No MODFLOW, no filesystem, no network.

## State

There is no `project.toml`. The draft is kept as `project.toml.draft` because
`hmp run` does not dispatch this project: analytical cases live under
`hydromodpy.calibration.cases` and are driven from Python.

## Run

```python
from hydromodpy.calibration.cases.groundwater_1d import (
    build_noisy_groundwater_chronicle,
    calibrate_groundwater,
)

chronicle = build_noisy_groundwater_chronicle()  # see [chronicle] in the draft
result = calibrate_groundwater(
    method="optuna",
    chronicle=chronicle,
    max_iter=50,
    seed=42,
    bounds={"Kam": [1.0, 10.0]},  # see [calibration.parameters] in the draft
)
```

The draft's TOML sections document the keyword arguments both helpers accept.
`docs/source/python_api/calibrate.rst` covers the calibration API.

## Turning the draft into a project

1. Wire `groundwater_1d` into the `hmp run` dispatcher
   (`hydromodpy/cli/commands/run.py`).
2. Give it a schema, or reuse the `[calibration]` subset of `HydroModPyConfig`.
3. Rename `project.toml.draft` to `project.toml` and check it with
   `hmp config check`.
