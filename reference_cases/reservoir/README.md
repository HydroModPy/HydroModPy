# Reservoir Reference Case

This folder provides a first reference case for a linear reservoir model,
following the same separation principle used in `recession_brutsaert`:

- `reservoir_equations.py`: equations and simulation logic only.
- `example_linear_reservoir.py`: minimal runnable demonstration script.
- `example_hydrological_daily_precipitation.py`: hydrological-style case with
  synthetic daily precipitation over one year and rainfall-to-inflow conversion.
- `example_calibration_reservoir.py`: end-to-end calibration workflow on a
  synthetic noisy chronicle (calibration of `C` and `k`).
- `example_calibration_reservoir.toml`: calibration settings
  (chronicle generation, bounds, method hyperparameters, outputs).

The calibration example uses shared generic modules in the parent folder:
- `reference_cases/calibration_problem.py`
- `reference_cases/calibration_method.py`
- `reference_cases/objective_function.py`

Unit convention used in this folder:
- storage and capacity: water depth `[mm]`
- inflow/outflow (`Qin`, `Qout`): `[mm/day]`

## Run

From repository root:

```bash
python reference_cases/reservoir/example_linear_reservoir.py
python reference_cases/reservoir/example_hydrological_daily_precipitation.py
python reference_cases/reservoir/example_calibration_reservoir.py
```
