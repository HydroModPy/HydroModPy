# Reference Cases

`reference_cases/` contains:
- shared, model-agnostic calibration utilities,
- runnable scientific case studies using these utilities.

The goal is to keep calibration logic generic and case physics isolated.

## Structure

- `objective_function.py`
  - performance metrics (`NSE`, `NSElog`, `KGE`, `RMSE`, `MAE`)
  - `ObjectiveFunction` wrapper with metric aliases
- `calibration_engine.py`
  - generic `CalibrationEngine` class
  - connects `observed`, `simulator`, `bounds`, objective metric, and selected method
- `calibration_results.py`
  - canonical `CalibrationResults` object returned by `CalibrationEngine.calibrate(...)`
  - stores best solution + optional parameter-distribution samples
- `calibration_parameters.py`
  - `CalibrationParameter` and `CalibrationParameterSet`
  - centralizes parameter order, bounds validation, and dict/vector conversions
- `calibration_method.py`
  - calibration method registry (`CalibrationMethod`)
  - deterministic and stochastic optimizers
- `calibration_da_mh.py`
  - delayed-acceptance Metropolis-Hastings with GP surrogate (`da_mh_gp`)
- `calibration_gp_mapping.py`
  - surrogate posterior mapping with Gaussian processes (`gp_mapping`)
- `calibration_config.py`
  - shared TOML parsing helpers for calibration settings (`bounds`, method kwargs)
  - enforces full-parameter calibration; `[fixed_parameters]` is not supported
- `calibration_visualization.py`
  - shared plotting helpers for posterior diagnostics and parameter distributions
- `reservoir/`
  - unified one/two-reservoir examples (forward run + calibration)
  - dedicated modules for chronicle generation, calibration orchestration, and plotting
- `recession_brutsaert/`
  - analytical groundwater recession case (Brutsaert-Nieber style)

## Shared Calibration API

All cases follow the same pattern:
1. Build a case-specific simulator adapter:
   - `simulator(params_dict) -> simulated_series`
2. Instantiate `CalibrationEngine(...)` with:
   - `observed`,
   - parameter `bounds` (or a `CalibrationParameterSet`),
   - objective metric (`nse`, `nse_log`, `kge`, or `rmse`)
3. Run:
   - `calibrate(method=..., **method_kwargs)`
   - returns a `CalibrationResults` object

This keeps case code focused on physics while optimization stays in shared modules.

## CalibrationEngine Overview

`CalibrationEngine` is the generic bridge between:
- observed data (calibration target),
- simulator callable (forward model),
- calibrated parameter space (bounds / `CalibrationParameterSet`),
- objective metric,
- selected calibration method.

Main workflow methods:
- `simulate(params)`: run the simulator and validate output shape.
- `score(params)`: compute objective metric value.
- `cost(params)`: compute minimization target from the configured metric.
- `calibrate(method=..., **kwargs)`: dispatch to a calibration method and return `CalibrationResults`.

Design intent:
- model-agnostic forward model interface,
- metric-agnostic objective evaluation,
- method-agnostic optimization dispatch,
- clear separation between model simulation and optimization logic.

## TOML Calibration Convention

- `[bounds]` must define every parameter of the selected model.
- `[fixed_parameters]` is intentionally not supported.
- For built-in methods, unknown keys in `[calibration_method.<method>]`
  are rejected early with an explicit error.
- Method-specific per-parameter settings (for example `proposal_scale`,
  `prior_mean`, `prior_std`) can be:
  - scalar,
  - explicit mappings by parameter name (recommended), e.g.
    `proposal_scale = {a=0.05, Kq=0.5, Ks=5.0}`.

## Available Calibration Methods

- `grid_search`: exhaustive global scan (robust, expensive).
- `random_search`: Monte-Carlo global search (simple baseline).
- `nelder_mead`: local derivative-free refinement.
- `simplex`: SciPy `fmin` simplex variant.
- `gp_mapping`: GP surrogate posterior mapping with UCB refinement.
- `da_mh_gp`: Bayesian delayed-acceptance MCMC with surrogate pre-screening.

## Notes About `da_mh_gp`

- In `CalibrationResults`:
  - `samples` stores the post-processed posterior chain (`burn_in` + `thin`),
  - raw full chain is available in `metadata["chain_samples"]`.
- Diagnostics include:
  - `stage1_accept_rate`,
  - `stage2_accept_rate`,
  - optional `full_mh_accept_rate`.
- `da_mh_gp` assumes `objective_cost(theta) = RMSE(theta)`.
- In TOML, use `objective_metric = "rmse"` when `global_method = "da_mh_gp"`.
- The likelihood scale is controlled by `sigma_noise`:
  `loglik = -0.5 * (RMSE / sigma_noise)^2`.

## Case Readmes

- `reference_cases/reservoir/README.md`
- `reference_cases/recession_brutsaert/README.md`
