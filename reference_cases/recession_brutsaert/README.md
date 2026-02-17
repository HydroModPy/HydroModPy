# Recession Brutsaert Reference Case

This folder contains a compact analytical reference implementation for
groundwater recession curves, intended for development support and future
unit/non-regression tests.

## Scope

Implemented functions in `baseflow.py`:

- `compute_characteristic_time(...)`
- `simulate_baseflow(...)`
- `generate_baseflow_profile(...)`
- `add_proportional_gaussian_error(...)`
- `generate_noisy_baseflow_profile(...)`

Implemented functions in `objective_fucntion.py`:

- `nse(observed, simulated)`
- `nse_log(observed, simulated)`
- `kge(observed, simulated, return_components=False)`
- `ObjectiveFunction(metric="nse")` with alias-based metric switch

Implemented calibration modules:

- `calibration_problem.py`
  - `BaseflowConfig`
  - `make_baseflow_simulator(...)`
  - `Calibration` (generic class delegating calibration to a method registry)
- `calibration_method.py`
  - `CalibrationMethod` + `DEFAULT_CALIBRATION_METHOD`
  - `grid_search_calibrate(...)`
  - `random_search_calibrate(...)`
  - `nelder_mead_calibrate(...)`
  - `scipy_simplex_calibrate(...)`

Supported recession models:

- `solution="exponential"`
- `solution="boussinesq"`

## Inputs and Conventions

- `Q0`: initial discharge `[m^3/s]`
- `K`: hydraulic conductivity `[m/s]`
- `Sy`: specific yield `[-]`
- `b`: aquifer thickness `[m]` (required for exponential solution)
- `A`: watershed area `[m^2]`
- `L`: channel length `[m]`
- `ag`: active drainage fraction `[-]` (default `0.7`)
- `p`: linearization constant `[-]` (default `0.346`)

Time conventions:

- `t` in `simulate_baseflow` is in seconds.
- `generate_baseflow_profile` returns both seconds and days.

When one of `A` or `L` is missing, the code uses:

- `L = 1.4 * sqrt(A)`
- `A = (L / 1.4)^2`

## Source Reference (Brutsaert)

Primary scientific reference used for this analytical case:

- Brutsaert, W., and J. L. Nieber (1977),
  *Regionalized drought flow hydrographs from a mature glaciated plateau*,
  **Water Resources Research**, 13(3), 637-643.
  DOI: `10.1029/WR013i003p00637`

Local source provided for this integration:

- `C:\Users\dreuzy\Downloads\Water Resources Research - June 1977 - Brutsaert - Regionalized drought flow hydrographs from a mature glaciated plateau.pdf`

## Analytical Formulations

This implementation provides two recession laws:

- `solution="exponential"`: linear-reservoir form
- `solution="boussinesq"`: nonlinear Brutsaert-type recession

### Proportional Gaussian error model

For an analytical discharge value `Q_i`, the noisy value is built as:

```text
epsilon_i ~ N(0, sigma_i^2)
sigma_i = f * |Q_i|
Q_noisy_i = Q_i + epsilon_i
```

where `f` is `error_fraction` (user parameter).

### 1) Exponential solution

Governing ODE:

```text
dQ/dt = -a Q
```

Coefficient:

```text
a = (pi^2 K p b L^2) / (Sy (ag A)^2)
```

Closed-form discharge:

```text
Q(t) = Q0 exp(-a t)
```

Characteristic time:

```text
tc = 1 / a
```

### 2) Boussinesq solution

Governing ODE:

```text
dQ/dt = -beta Q^(3/2)
```

Coefficient:

```text
beta = (4.8038 / 2) * sqrt(K) * L / (Sy (ag A)^(3/2))
```

Closed-form discharge:

```text
Q(t) = (Q0^(-1/2) + beta t)^(-2)
```

Characteristic time:

```text
tc = 1 / (beta sqrt(Q0))
```

### Geometric closure used when one descriptor is missing

```text
L = 1.4 sqrt(A)
A = (L / 1.4)^2
```

## Physical Parameter Reference

## Hydraulic Conductivity K [m/s]

Definition:

- Controls groundwater flow velocity via Darcy's law.

Typical ranges by geology:

- Clay (massive): `1e-13` to `1e-11`
- Silty clay: `1e-12` to `1e-9`
- Silt: `1e-9` to `1e-6`
- Fine sand: `1e-6` to `1e-4`
- Medium sand: `5e-6` to `5e-4`
- Coarse sand: `1e-5` to `1e-3`
- Gravel: `1e-4` to `1e-2`
- Sand-gravel mixtures: `1e-5` to `1e-2`
- Sandstone: `1e-8` to `1e-4`
- Limestone (unfractured): `1e-9` to `1e-5`
- Karst limestone: `1e-6` to `1e-2`
- Granite (unfractured): `1e-12` to `1e-9`
- Fractured granite: `1e-9` to `1e-5`
- Basalt: `1e-9` to `1e-4`
- Fractured volcanic rock: `1e-8` to `1e-3`
- Weathered rock: `1e-7` to `1e-4`

Typical watershed-scale effective range:

- `1e-6` to `1e-4` m/s

Most common modeling value:

- `1e-5` m/s

## Specific Yield Sy [-]

Definition:

- Fraction of aquifer volume that drains under gravity.
- Controls groundwater storage release.

Typical ranges by geology:

- Clay: `0.01` to `0.05`
- Silty clay: `0.03` to `0.08`
- Silt: `0.05` to `0.15`
- Fine sand: `0.10` to `0.25`
- Medium sand: `0.15` to `0.30`
- Coarse sand: `0.20` to `0.35`
- Gravel: `0.15` to `0.30`
- Sandstone: `0.05` to `0.20`
- Limestone (unfractured): `0.01` to `0.10`
- Karst limestone: `0.05` to `0.30`
- Granite (fractured): `0.01` to `0.05`
- Basalt: `0.01` to `0.10`
- Weathered rock: `0.05` to `0.20`

Typical watershed-scale effective range:

- `0.05` to `0.25`

Most common modeling value:

- `0.10` to `0.20`

## Minimal Usage

```python
from reference_cases.recession_brutsaert.baseflow import generate_baseflow_profile

t_s, t_days, q, tc = generate_baseflow_profile(
    Q0=1.0,
    K=1e-5,
    Sy=0.1,
    solution="boussinesq",
    A=10e6,
)
```

## Coarse-Sand Example (50 points + plot)

A ready-to-run example is provided in:

- `reference_cases/recession_brutsaert/example_coarse_sand_profile.py`

The script uses a parameter set consistent with coarse-sand ranges:

- `K = 2.0e-4 m/s` (within `1e-5` to `1e-3`)
- `Sy = 0.28` (within `0.20` to `0.35`)
- `Q0 = 0.35 m^3/s`
- `A = 1.2e6 m^2`
- `solution = "boussinesq"`
- `n_points = 50`
- `t_min_days = 0.1`
- `error_fraction = 0.10` (Gaussian noise with pointwise proportional sigma)

Run from repository root:

```powershell
python reference_cases/recession_brutsaert/example_coarse_sand_profile.py
```

Outputs are written to:

- `reference_cases/recession_brutsaert/outputs/coarse_sand_recession_profile.png`
- `reference_cases/recession_brutsaert/outputs/coarse_sand_recession_points.csv`

The generated plot overlays:

- analytical profile (without error)
- noisy profile (with proportional Gaussian error)

## Metrics Illustration on the Coarse-Sand Example

A second script computes classical hydrological metrics on the previous example:

- `reference_cases/recession_brutsaert/example_metrics_coarse_sand.py`

Computed indicators:

- NSE
- NSElog
- KGE (with `r`, `alpha`, `beta` components)

Run:

```powershell
python reference_cases/recession_brutsaert/example_metrics_coarse_sand.py
```

Output figure:

- `reference_cases/recession_brutsaert/outputs/coarse_sand_metrics_illustration.png`

## K-Sy Calibration from a Noisy Coarse-Sand Chronicle

Example script:

- `reference_cases/recession_brutsaert/example_calibration_coarse_sand.py`
- `reference_cases/recession_brutsaert/example_calibration_coarse_sand.toml`

What it does:

1. Fixes true coarse-sand parameters (`K`, `Sy`)
2. Generates a noisy synthetic chronicle
3. Calibrates unknown (`K`, `Sy`) by optimizing one objective metric:
   - `NSE`
   - `NSElog`
   - `KGE`

All calibration/example parameters are read from the TOML file.
Edit this file to change:

- synthetic chronicle settings,
- calibration objective/method,
- calibration-method hyperparameters,
- output options.

Optimization methods proposed and implemented:

- `grid_search`: robust global scan
- `random_search`: global Monte-Carlo style search
- `nelder_mead`: local refinement (typically after global initialization)
- `simplex`: classic SciPy simplex via `scipy.optimize.fmin`

Separation of concerns:

- Generic calibration workflow and method switch are in `calibration_problem.py` (`Calibration`)
- Optimization algorithms stay in `calibration_method.py`
- End-to-end demonstration is in `example_calibration_coarse_sand.py`

Run:

```powershell
python reference_cases/recession_brutsaert/example_calibration_coarse_sand.py
```

Output figure:

- `reference_cases/recession_brutsaert/outputs/coarse_sand_calibration_<metric>_<method>.png`

## Bibliography for Performance Indicators

NSE:

- Nash, J. E., and J. V. Sutcliffe (1970).
  *River flow forecasting through conceptual models part I - A discussion of principles*.
  Journal of Hydrology, 10(3), 282-290.
  DOI: `10.1016/0022-1694(70)90255-6`

NSElog usage (log-transform for low-flow sensitivity):

- Krause, P., D. P. Boyle, and F. Base (2005).
  *Comparison of different efficiency criteria for hydrological model assessment*.
  Advances in Geosciences, 5, 89-97.
  DOI: `10.5194/adgeo-5-89-2005`

KGE (original 2009 form used here):

- Gupta, H. V., H. Kling, K. K. Yilmaz, and G. F. Martinez (2009).
  *Decomposition of the mean squared error and NSE performance criteria*.
  Journal of Hydrology, 377(1-2), 80-91.
  DOI: `10.1016/j.jhydrol.2009.08.003`
