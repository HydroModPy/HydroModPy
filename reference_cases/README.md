# Reference Cases

This folder contains runnable scientific examples and shared helpers.

## Shared generic modules

- `calibration_method.py`: calibration search methods and registry.
- `calibration_da_mh.py`: delayed-acceptance MH sampler with GP surrogate.
- `calibration_problem.py`: generic `Calibration` class.
- `objective_function.py`: hydrological objective metrics (NSE, NSElog, KGE, etc.).

These modules are intentionally model-agnostic and can be reused by multiple
reference cases (e.g. Brutsaert recession and reservoir calibration examples).
