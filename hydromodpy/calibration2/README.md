# Calibration2

`hydromodpy/calibration2/` centralizes generic calibration code and runnable
scientific cases.

## Structure

- `core/`
  - `engine.py`: generic `CalibrationEngine`
  - `parameters.py`: `CalibrationParameter` and `CalibrationParameterSet`
  - `results.py`: canonical `CalibrationResults`
  - `objective_function.py`: metrics (`NSE`, `NSElog`, `KGE`, `RMSE`, `MAE`) and
    `ObjectiveFunction`
  - `config.py`: shared TOML parsing and method-kwargs normalization
  - `methods_dispatcher.py`: calibration method registry (`CalibrationMethod`)
    and default dispatcher (`DEFAULT_CALIBRATION_METHOD`)
  - `methods/`
  - `methods/grid_search.py`: exhaustive grid-search method
  - `methods/random_search.py`: random bounded sampling method
  - `methods/nelder_mead.py`: local Nelder-Mead method
  - `methods/simplex.py`: classic simplex (`scipy.optimize.fmin`) method
  - `methods/gp_mapping.py`: GP surrogate posterior mapping (`gp_mapping`)
  - `methods/da_mh_gp.py`: delayed-acceptance GP-MH (`da_mh_gp`)
- `analysis/`
  - `diagnostics.py`: shared metric/sample diagnostics
  - `plotting.py`: shared plotting utilities for sample/posterior views
- `cases/`
  - `reservoir/`: one/two-reservoir workflow and scripts
  - `recession_brutsaert/`: Brutsaert recession workflow and scripts

## Shared API

All cases follow the same flow:

1. Build a case-specific simulator:
   `simulator(params_dict) -> simulated_series`
2. Instantiate `CalibrationEngine(...)` with observed data, parameter bounds
   (`bounds` or `CalibrationParameterSet`), and metric.
3. Run `calibrate(method=..., **method_kwargs)` and consume
   `CalibrationResults`.

## Calibration Convention

- `[bounds]` must define all parameters of the selected model.
- Partial calibration via `[fixed_parameters]` is intentionally not supported.
- Unknown keys in `[calibration_method.<method>]` are rejected for built-in
  methods.
- Per-parameter method settings can be passed as explicit mappings, e.g.
  `proposal_scale = {a=0.05, Kq=0.5, Ks=5.0}`.

## Available Methods

- `grid_search`
- `random_search`
- `nelder_mead`
- `simplex`
- `gp_mapping`
- `da_mh_gp`

For `da_mh_gp`, `objective_metric = "rmse"` must be used.

## Case Readmes

- `hydromodpy/calibration2/cases/reservoir/README.md`
- `hydromodpy/calibration2/cases/recession_brutsaert/README.md`
