# Reservoir Reference Case

This folder demonstrates one- and two-reservoir linear models with:
- forward simulation,
- synthetic forcing generation,
- noisy-observation creation,
- end-to-end parameter calibration.

Legacy files were removed in favor of a modular layout:
- `reservoir_equations.py` -> `one_reservoir.py`
- `example_hydrological_daily_precipitation.py` / `example_hydrological_two_reservoirs.py`
  -> `run_forward.py`

## File Responsibilities

- `one_reservoir.py`
  - one linear reservoir equations and simulation routine
- `two_reservoirs.py`
  - two linear reservoirs in parallel with precipitation split (`a`, `Kq`, `Ks`)
- `forcing.py`
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
  - model choice (`model_name`) and associated forcing/parameter values
- `workflow.py`
  - shared calibration-case logic:
    - model registry/selection
    - simulator adapter for generic calibration API
    - calibration orchestration and metrics
- `synthetic_data.py`
  - construction of synthetic reference chronicle:
    - chronicle config parsing
    - forcing + true response generation
    - noisy-observation generation
- `plotting.py`
  - plotting helpers for calibration diagnostics
- `run_calibration.py`
  - short orchestrator:
    - load TOML
    - build chronicle via `synthetic_data.py`
    - calibrate
    - print summary
    - plot/save via `plotting.py`
- `config_calibration.toml`
  - case and calibration configuration

## Units and Conventions

- storage and capacity (`S`, `C`): `[mm]`
- inflow/outflow (`Qin`, `Qout`): `[mm/day]`
- time in examples: daily resolution over one hydrological year (start Oct 1)

## Run

From repository root:

```bash
python hydromodpy/calibration2/cases/reservoir/run_linear_smoke.py
python hydromodpy/calibration2/cases/reservoir/run_forward.py
python hydromodpy/calibration2/cases/reservoir/run_calibration.py
```

Model/parameter selection for the unified script is done in:
- `hydromodpy/calibration2/cases/reservoir/config_forward.toml`

Model/parameter selection for calibration is done in:
- `hydromodpy/calibration2/cases/reservoir/config_calibration.toml`

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
   - `hydromodpy/calibration2/core/parameters.py`
   - `hydromodpy/calibration2/core/engine.py`
   - `hydromodpy/calibration2/core/methods_dispatcher.py`
   - `hydromodpy/calibration2/core/objective_function.py`

## TOML Guide (`config_calibration.toml`)

Main sections:
- `[chronicle]`: synthetic forcing and truth generation
- `[calibration]`: model selection + objective metric + method
- `[bounds]`: parameter bounds for all parameters of the selected model
- `[calibration_method.<method>]`: method-specific hyperparameters
- `[output]`: figure output settings

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
