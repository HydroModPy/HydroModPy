# Reservoir Reference Case

This folder demonstrates one- and two-reservoir linear models with:
- forward simulation,
- synthetic forcing generation,
- noisy-observation creation,
- end-to-end parameter calibration.

Modular layout:
- `reservoir_equations.py` -> `one_reservoir.py`
- `example_hydrological_daily_precipitation.py` / `example_hydrological_two_reservoirs.py`
  -> `run_forward.py`

## File Responsibilities

- `one_reservoir.py`
  - one linear reservoir equations and simulation routine
- `two_reservoirs.py`
  - two linear reservoirs in parallel with precipitation split (`a`, `Kq`, `Ks`)
- `forcing.py`
  - compatibility wrapper around shared forcing helpers in
    `hydromodpy/analysis/calibration/cases/utils/forcing.py`
  - shared forcing helpers:
    - synthetic daily precipitation chronicle
    - annual-total normalization
    - hydrological-year dates
    - precipitation-to-inflow conversion
    - piecewise-constant `Qin(t)` adapter
- `run_linear_smoke.py`
  - minimal forward-run smoke example
- `run_forward.py`
  - unified TOML-driven hydrological example for one/two reservoirs
- `config_forward.toml`
  - model choice (`model_name`), solver backend (`solver_backend`) and associated forcing/parameter values
- `workflow.py`
  - shared calibration-case logic:
    - model registry/selection
    - simulator adapter for generic calibration API
    - calibration orchestration and metrics
- `case_implementation.py`
  - reservoir case implementation inheriting the abstract case interface
  - consumed by `hydromodpy/analysis/calibration/core/case_orchestrator.py`
- `synthetic_data.py`
  - construction of synthetic reference chronicle:
    - chronicle config parsing
    - forcing + true response generation
    - noisy-observation generation
- `plotting.py`
  - plotting helpers for calibration diagnostics
- `run_calibration.py`
  - short orchestration script around generic `case_orchestrator`:
    - load TOML
    - execute case implementation
    - print summary
    - plot/save via `plotting.py`
- `config_calibration_two_reservoir.toml`
  - case and calibration configuration

## Units and Conventions

- storage and capacity (`S`, `C`): `[mm]`
- inflow/outflow (`Qin`, `Qout`): `[mm/day]`
- time in examples: daily resolution over one hydrological year (start Oct 1)

## Forward Performance (Indicative)

Measured on this development machine using direct simulator calls only
(`make_reservoir_simulator(...)(params)`), without calibration/plotting:
- warm-up: 5 calls
- benchmark: 200 calls
- chronicle length: `n_days = 365`

One reservoir (`model_name="one_reservoir"`):
- Parameters:
  - `C = 10.0`
  - `k = 0.04`
  - `s0 = 0.0`
- Chronicle settings:
  - `target_annual_precip_mm = 800.0`
  - `runoff_coeff = 0.15`
  - `losses_mm_day = 1.5`
  - `losses_months = [4, 5, 6, 7, 8, 9]`
- Timing:
  - median: `~48.8 ms`
  - mean: `~50.3 ms`
  - p95: `~65.3 ms`

Two reservoirs (`model_name="two_reservoir"`):
- Parameters:
  - `a = 0.35`
  - `Kq = 3.0`
  - `Ks = 45.0`
  - `sq0 = 0.0`
  - `ss0 = 0.0`
- Chronicle settings:
  - `target_annual_precip_mm = 800.0`
  - `runoff_coeff = 0.15`
  - `losses_mm_day = 1.5`
  - `losses_months = [4, 5, 6, 7, 8, 9]`
- Timing:
  - median: `~112.1 ms`
  - mean: `~111.5 ms`
  - p95: `~137.7 ms`

Notes:
- these values are hardware/Python/BLAS dependent;
- direct simulation cost is only one component of calibration runtime.

## Run

From repository root:

```bash
python hydromodpy/analysis/calibration/cases/reservoir/run_linear_smoke.py
python hydromodpy/analysis/calibration/cases/reservoir/run_forward.py
python hydromodpy/analysis/calibration/cases/reservoir/run_calibration.py
python hydromodpy/analysis/calibration/cases/reservoir/run_calibration.py --preset one_reservoir
```

Model/parameter selection for the unified script is done in:
- `hydromodpy/analysis/calibration/cases/reservoir/config_forward.toml`

Model/parameter selection for calibration is done in:
- `hydromodpy/analysis/calibration/cases/reservoir/config_calibration_two_reservoir.toml`
  (default preset `three_params`, two-reservoir / 3 parameters)
- `hydromodpy/analysis/calibration/cases/reservoir/config_calibration_one_reservoir.toml`
  (preset `one_reservoir`, one-reservoir / 2 parameters + objective surface enabled)

`run_calibration.py` supports:
- `--preset three_params|one_reservoir` (default: `three_params`)
- `--config-file <path>` to use any explicit TOML file

## Alternative Model: Two Reservoirs + Split

The alternative model implemented in `two_reservoirs.py` is:

- `dSq/dt = a * P(t) - Sq / Kq`, `Qq = Sq / Kq`
- `dSs/dt = (1 - a) * P(t) - Ss / Ks`, `Qs = Ss / Ks`
- `Q = Qq + Qs`

Main properties:
- Advantage: captures floods and baseflow with only 3 parameters.
- Limitation: no explicit losses and no storage upper bounds.

## Calibration Workflow (`run_calibration.py`)

1. Generate synthetic precipitation (and derive `Qin` for one-reservoir mode) via `synthetic_data.py`.
2. Simulate a "true" response with known parameters of the selected model.
3. Add proportional Gaussian noise to create pseudo-observations.
4. Calibrate all parameters of the selected model (`[bounds]`):
   - one reservoir: `C`, `k`
   - two reservoirs: `a`, `Kq`, `Ks`
   Bounds are normalized into a shared `CalibrationParameterSet` object before
   launching any calibration method.
   using shared calibration modules:
   - `hydromodpy/analysis/calibration/core/parameters.py`
   - `hydromodpy/analysis/calibration/core/engine.py`
   - `hydromodpy/analysis/calibration/core/methods_dispatcher.py`
   - `hydromodpy/analysis/calibration/core/objective_function.py`

## TOML Guide (`config_calibration_two_reservoir.toml`)

Main sections:
- `[chronicle]`: synthetic forcing and truth generation
  - includes `solver_backend = "analytic" | "ode"` for direct-model integration
- `[calibration]`: model selection + objective metric + method
- `[bounds]`: parameter bounds for all parameters of the selected model
- `[calibration_method.<method>]`: method-specific hyperparameters
- `[output]`: figure output settings (including optional objective surface)

Strict naming convention:
- `model_name` must be `one_reservoir` or `two_reservoir`
- `solver_backend` must be `analytic` or `ode`
- `objective_metric` must be one of `nse`, `nse_log`, `kge`, `rmse`
- `global_method` must be one of the built-in method names listed below

For `gp_mapping`, key controls are:
- `n_init`: initial design size (true model evaluations)
- `n_refine`, `batch_size`: adaptive UCB refinement budget
- `kappa`: exploration/exploitation balance in UCB
- `n_posterior_pool`, `n_posterior_samples`: quality/cost of posterior approximation
- `log_transform`: surrogate built in log-parameter space (recommended for positive parameters)

For `da_mh_gp`, most sensitive settings are:
- `objective_metric = "rmse"` in `[calibration]` (required for DA-MH likelihood)
- `sigma_noise`: controls likelihood sharpness (too small can freeze chain)
- `proposal_scale`: random-walk proposal size for each parameter
- `retrain_interval`: GP surrogate refresh cadence
- `n_samples`, `burn_in`, `thin`: posterior sample quality and cost
- Per-parameter settings can be written explicitly as mappings, e.g.
  `proposal_scale = {a=0.05, Kq=0.5, Ks=5.0}`.

For optional objective-surface plotting:
- `show_objective_surface = true|false`
- `objective_surface_n_evaluations = <int>`
- `objective_surface_seed = <int>`

This panel is available only for 1D/2D calibrated spaces. For 3+ parameters,
schema validation auto-disables `show_objective_surface`.

Surface-construction details:
- 1D: regular sampling + GP interpolation (linear fallback).
- 2D: Sobol sampling + GP interpolation (IDW fallback).
- For parameters spanning multiple orders of magnitude (strictly positive bounds),
  sampling is automatically performed in log scale for those dimensions.
- For sampling-based calibration methods, objective-surface scatter overlays
  posterior/chain solution states (not direct-evaluation design points).

## Diagnosing MCMC Mixing

`da_mh_gp` outputs diagnostics in `CalibrationResults.metadata` and figure summary:
- `stage1_accept_rate` (surrogate pre-filter acceptance)
- `stage2_accept_rate` (true posterior acceptance)
- number of unique parameter states in chain/posterior

If unique states are very low and `stage2_accept_rate` is near zero, chain
mixing is poor.

## Forcing and Rainfall-Runoff References

`forcing.py` uses a pedagogical stochastic weather-generator style:
- seasonal wet/dry occurrence,
- Gamma-distributed event depths,
- occasional heavy storms.

Methodological references:
- Richardson, C. W. (1981), Water Resources Research, 17(1), 182-190.
- Wilks, D. S., Wilby, R. L. (1999), Progress in Physical Geography, 23(3), 329-357.
