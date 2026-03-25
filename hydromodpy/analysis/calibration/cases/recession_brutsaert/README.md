# Recession Brutsaert Reference Case

This folder provides an analytical groundwater-recession case used as:
- a scientific reference implementation,
- a calibration example built on shared `hydromodpy/analysis/calibration` utilities.

## File Responsibilities

- `model.py`
  - analytical recession equations
  - synthetic profile generation
  - proportional Gaussian noise model
- `run_profile.py`
  - forward synthetic coarse-sand example
- `run_metrics.py`
  - metric illustration (`NSE`, `NSElog`, `KGE`)
- `workflow.py`
  - shared Brutsaert calibration logic:
    - chronicle generation
    - simulator adapter
    - calibration orchestration
- `case_implementation.py`
  - Brutsaert case implementation inheriting the abstract case interface
  - consumed by `hydromodpy/analysis/calibration/core/case_orchestrator.py`
- `run_calibration.py`
  - end-to-end `K`-`Sy` calibration orchestrated by generic `case_orchestrator`
- `config_calibration.toml`
  - calibration and output configuration

## Supported Recession Laws

- `solution="exponential"`
  - `dQ/dt = -a Q`
  - `Q(t) = Q0 exp(-a t)`
- `solution="boussinesq"`
  - `dQ/dt = -beta Q^(3/2)`
  - `Q(t) = (Q0^(-1/2) + beta t)^(-2)`

Characteristic time is available through `compute_characteristic_time(...)`.

## Inputs and Conventions

- `Q0`: initial discharge `[m^3/s]`
- `K`: hydraulic conductivity `[m/s]`
- `Sy`: specific yield `[-]`
- `A`: watershed area `[m^2]`
- `L`: channel length `[m]`
- `b`: aquifer thickness `[m]` (needed for exponential solution)
- `ag`: active drainage fraction `[-]` (default `0.7`)
- `p`: linearization constant `[-]` (default `0.346`)

Time:
- analytical simulation uses seconds internally,
- profile generators return both seconds and days.

If one of `A` or `L` is missing, geometric closure is used:
- `L = 1.4 * sqrt(A)`
- `A = (L / 1.4)^2`

## Forward Performance (Indicative)

Measured on this development machine using direct simulator calls only
(`make_baseflow_simulator(...)(params)`), without calibration/plotting:
- warm-up: 10 calls
- benchmark: 4000 to 5000 calls

Reference parameterization:
- `Q0 = 0.35`
- `K = 2.0e-4`
- `Sy = 0.28`
- `solution = "boussinesq"`
- `A = 1.2e6`
- `ag = 0.7`
- `p = 0.346`
- `log_spacing = true`

Timing:
- `n_points = 50`
  - median: `~0.0049 ms`
  - mean: `~0.0060 ms`
  - p95: `~0.0097 ms`
- `n_points = 365`
  - median: `~0.0097 ms`
  - mean: `~0.0122 ms`
  - p95: `~0.0161 ms`

Notes:
- these values are hardware/Python dependent;
- Brutsaert forward equations are analytical and extremely cheap, so calibration
  runtime is dominated by repeated evaluations and algorithm overhead.

## Calibration Architecture

This case reuses shared modules from `hydromodpy/analysis/calibration/`:
- `core/parameters.py`
- `core/engine.py`
- `core/methods_dispatcher.py`
- `core/methods/da_mh_gp.py`
- `core/objective_function.py`

The Brutsaert-specific simulator adapter lives in `workflow.py` and is called
through `case_implementation.py` when using the generic orchestrator.

Supported methods are the same as other cases:
- `grid_search`
- `random_search`
- `nelder_mead`
- `simplex`
- `gp_mapping`
- `da_mh_gp`

For `da_mh_gp`, set:
- `objective_metric = "rmse"` in TOML.

Strict naming convention in TOML:
- `objective_metric` must be one of `nse`, `nse_log`, `kge`, `rmse`
- `global_method` must be one of the built-in method names above

For per-parameter method settings (for example `proposal_scale`, `prior_mean`,
`prior_std`), TOML can use explicit mappings such as
`proposal_scale = {K=2.0e-5, Sy=0.01}`.

## Run

From repository root:

```bash
python hydromodpy/analysis/calibration/cases/recession_brutsaert/run_profile.py
python hydromodpy/analysis/calibration/cases/recession_brutsaert/run_metrics.py
python hydromodpy/analysis/calibration/cases/recession_brutsaert/run_calibration.py
```

## Outputs

Generated files are written under:
- `hydromodpy/analysis/calibration/cases/recession_brutsaert/outputs/`

Typical outputs include:
- synthetic profile plot/CSV,
- metrics illustration figure,
- calibration summary figure.

Optional objective-surface panel (in `config_calibration.toml`, `[output]`):
- `show_objective_surface = true|false`
- `objective_surface_n_evaluations = <int>`
- `objective_surface_seed = <int>`

When enabled and the calibrated space is 1D/2D, the calibration figure includes
an approximated objective-cost map built from additional direct model
evaluations.

## References

Primary analytical source:
- Brutsaert, W., Nieber, J. L. (1977). Regionalized drought flow hydrographs
  from a mature glaciated plateau. Water Resources Research, 13(3), 637-643.
  DOI: `10.1029/WR013i003p00637`

Calibration metrics:
- Nash, J. E., Sutcliffe, J. V. (1970), DOI: `10.1016/0022-1694(70)90255-6`
- Krause, P., Boyle, D. P., Base, F. (2005), DOI: `10.5194/adgeo-5-89-2005`
- Gupta, H. V., et al. (2009), DOI: `10.1016/j.jhydrol.2009.08.003`
