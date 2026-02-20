# Recession Brutsaert Reference Case

This folder provides an analytical groundwater-recession case used as:
- a scientific reference implementation,
- a calibration example built on shared `reference_cases` utilities.

## File Responsibilities

- `baseflow.py`
  - analytical recession equations
  - synthetic profile generation
  - proportional Gaussian noise model
- `example_coarse_sand_profile.py`
  - forward synthetic coarse-sand example
- `example_metrics_coarse_sand.py`
  - metric illustration (`NSE`, `NSElog`, `KGE`)
- `example_calibration_coarse_sand.py`
  - end-to-end `K`-`Sy` calibration
- `example_calibration_coarse_sand.toml`
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

## Calibration Architecture

This case reuses shared modules from `reference_cases/`:
- `calibration_problem.py`
- `calibration_method.py`
- `calibration_da_mh.py`
- `objective_function.py`

The Brutsaert-specific simulator adapter remains in
`example_calibration_coarse_sand.py`.

Supported methods are the same as other cases:
- `grid_search`
- `random_search`
- `nelder_mead`
- `simplex`
- `da_mh_gp`

## Run

From repository root:

```bash
python reference_cases/recession_brutsaert/example_coarse_sand_profile.py
python reference_cases/recession_brutsaert/example_metrics_coarse_sand.py
python reference_cases/recession_brutsaert/example_calibration_coarse_sand.py
```

## Outputs

Generated files are written under:
- `reference_cases/recession_brutsaert/outputs/`

Typical outputs include:
- synthetic profile plot/CSV,
- metrics illustration figure,
- calibration summary figure.

## References

Primary analytical source:
- Brutsaert, W., Nieber, J. L. (1977). Regionalized drought flow hydrographs
  from a mature glaciated plateau. Water Resources Research, 13(3), 637-643.
  DOI: `10.1029/WR013i003p00637`

Calibration metrics:
- Nash, J. E., Sutcliffe, J. V. (1970), DOI: `10.1016/0022-1694(70)90255-6`
- Krause, P., Boyle, D. P., Base, F. (2005), DOI: `10.5194/adgeo-5-89-2005`
- Gupta, H. V., et al. (2009), DOI: `10.1016/j.jhydrol.2009.08.003`
