# Groundwater 1D Unconfined Reference Case

This case implements a transient 1D free-aquifer model with:
- piecewise hydraulic properties (`x < xi` upstream, `x >= xi` downstream),
- implicit finite differences,
- selectable linearized or nonlinear Boussinesq formulation,
- selectable recharge forcing mode:
  - hydrological wet/dry step,
  - recharge derived from reservoir synthetic chronicle,
- synthetic observations for calibration.

## Equations

Domain:
- `x in [0, L]`
- interface at `x = xi`

Piecewise properties:
- `K(x) = Kam` upstream, `Kav` downstream
- `Sy(x) = Syam` upstream, `Syav` downstream

Two formulations are available:

1. Linearized around mean saturated thickness `H`:
   - `T(x) = K(x) * H`
   - `Sy(x) * dh/dt = d/dx( T(x) * dh/dx ) + R(t)`

2. Nonlinear Boussinesq:
   - `Sy(x) * dh/dt = d/dx( K(x) * h * dh/dx ) + R(t)`

Boundary conditions:
- upstream (`x=0`): imposed head `h(0,t) = h0` (constant)
- downstream (`x=L`): no flow `dh/dx(L,t) = 0`

Initial condition:
- `h(x,0) = h0` everywhere (same value as upstream boundary)

## Numerical Method

- finite differences, node-centered,
- implicit Euler in time,
- harmonic mean for interface transmissivity at cell faces,
- tridiagonal solve each time step,
- nonlinear option solved with Picard iterations.

## File Responsibilities

- `model.py`
  - physical model and main `simulate(...)` function
  - mesh build, matrix assembly, implicit time loop, flux computation
- `case_config.py`
  - strict Pydantic validation for `[chronicle]`
- `synthetic_data.py`
  - forcing generation (constant `h0`, transient `R(t)`)
  - supports:
    - `recharge_mode="hydro_step"`
    - `recharge_mode="reservoir_chronicle"` (shared with reservoir forcing utilities)
  - true simulation and noisy synthetic observation creation
- `workflow.py`
  - simulator adapter for `CalibrationEngine`
  - calibration helper and metrics
- `case_implementation.py`
  - case adapter used by generic `core/case_orchestrator.py`
- `plotting.py`
  - calibration figure helper
- `run_forward.py`
  - forward-only demonstration
- `run_calibration.py`
  - full TOML-driven calibration run
- `config_calibration.toml`
  - example configuration

## Run

From repository root:

```bash
python hydromodpy/calibration2/cases/groundwater_1d/run_forward.py
python hydromodpy/calibration2/cases/groundwater_1d/run_calibration.py
```

Optional custom config:

```bash
python hydromodpy/calibration2/cases/groundwater_1d/run_calibration.py --config-file config_calibration.toml
```

## Calibration-Ready Inputs

You can easily modify in TOML:
- hydraulic parameters used for synthetic truth:
  - `Kam_true_m_per_day`, `Kav_true_m_per_day`
  - `Syam_true`, `Syav_true`
  - `xi_true_m`
- forcing:
  - constant upstream head `h0_m`
  - recharge controls:
    - `recharge_mode="hydro_step"` with wet/dry period settings
    - `recharge_mode="reservoir_chronicle"` with reservoir-like precipitation/runoff settings
- discretization and solver controls:
  - `nx`, `dt_days`, Picard settings
- synthetic observation setup:
  - `obs_x_m`, `obs_t_stride`, `obs_noise_std_m`
  - `obs_x_m = []` automatically uses the midpoints of the two zones

Calibration parameters are defined by `[bounds]`:
- `Kam`, `Kav`, `Syam`, `Syav`, `xi`
