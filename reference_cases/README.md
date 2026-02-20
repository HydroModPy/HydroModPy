# Reference Cases

`reference_cases/` contains:
- shared, model-agnostic calibration utilities,
- runnable scientific case studies using these utilities.

The goal is to keep calibration logic generic and case physics isolated.

## Structure

- `objective_function.py`
  - performance metrics (`NSE`, `NSElog`, `KGE`, `RMSE`, `MAE`)
  - `ObjectiveFunction` wrapper with metric aliases
- `calibration_problem.py`
  - generic `Calibration` class
  - connects `observed`, `simulator`, `bounds`, objective metric, and selected method
- `calibration_method.py`
  - calibration method registry (`CalibrationMethod`)
  - deterministic and stochastic optimizers
- `calibration_da_mh.py`
  - delayed-acceptance Metropolis-Hastings with GP surrogate (`da_mh_gp`)
- `calibration_config.py`
  - shared TOML parsing helpers for calibration settings (`bounds`, method kwargs, fixed parameters)
- `reservoir/`
  - linear-reservoir examples (forward run + calibration), plus a two-reservoir split alternative
- `recession_brutsaert/`
  - analytical groundwater recession case (Brutsaert-Nieber style)

## Shared Calibration API

All cases follow the same pattern:
1. Build a case-specific simulator adapter:
   - `simulator(params_dict) -> simulated_series`
2. Instantiate `Calibration(...)` with:
   - `observed`,
   - parameter `bounds`,
   - objective metric (`nse`, `nse_log`, or `kge`)
3. Run:
   - `calibrate(method=..., **method_kwargs)`

This keeps case code focused on physics while optimization stays in shared modules.

## Available Calibration Methods

- `grid_search`: exhaustive global scan (robust, expensive).
- `random_search`: Monte-Carlo global search (simple baseline).
- `nelder_mead`: local derivative-free refinement.
- `simplex`: SciPy `fmin` simplex variant.
- `da_mh_gp`: Bayesian delayed-acceptance MCMC with surrogate pre-screening.

## Notes About `da_mh_gp`

- The sampler returns both:
  - full chain: `samples`,
  - post-processed chain: `posterior_samples` (`burn_in` + `thin`).
- Diagnostics include:
  - `stage1_accept_rate`,
  - `stage2_accept_rate`,
  - optional `full_mh_accept_rate`.
- If `observed` + `simulator` are provided, `da_mh_gp` uses a Gaussian RMSE
  likelihood for the posterior; reported objective metric (`NSE`, `KGE`, etc.)
  is still computed separately for calibration summaries.

## Case Readmes

- `reference_cases/reservoir/README.md`
- `reference_cases/recession_brutsaert/README.md`
