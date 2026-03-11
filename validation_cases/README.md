# Validation Cases Inventory

This folder hosts reusable validation cases and the small shared runtime used
to execute them outside the `tests/` package.

Current inventory:

| Path | Type | Regime | Reference | Purpose |
| --- | --- | --- | --- | --- |
| `analytical/steady/dupuit_fixed_head_1d` | launcher-backed | steady | Dupuit, fixed heads | Baseline 1D unconfined profile between two imposed heads. |
| `analytical/steady/dupuit_uniform_recharge_1d` | launcher-backed | steady | Dupuit, uniform recharge | 1D recharge benchmark with fixed heads on both sides. |
| `analytical/steady/dupuit_divide_river_1d` | launcher-backed | steady | Dupuit, divide-river | 1D recharge benchmark with west divide and east river head. |
| `analytical/steady/dupuit_circular_island_ocean_2d` | launcher-backed | steady | Radial Dupuit-Boussinesq | 2D circular-island benchmark using the `ocean` boundary condition. |
| `analytical/steady/boussinesq_fixed_head_piecewise_k_1d` | launcher-backed | steady | Boussinesq, fixed heads, piecewise K | 1D heterogeneous benchmark with exact `h^2` profile and conductivity jumps. |
| `analytical/steady/boussinesq_uniform_recharge_piecewise_k_1d` | launcher-backed | steady | Boussinesq, recharge, piecewise K | 1D recharge benchmark with exact piecewise-constant `K` reference. |
| `analytical/steady/boussinesq_divide_fixed_head_piecewise_k_1d` | launcher-backed | steady | Boussinesq, divide, piecewise K | 1D west-divide benchmark without geology dependencies. |
| `analytical/steady/boussinesq_circular_island_piecewise_k_2d` | launcher-backed | steady | Radial Boussinesq, concentric K | 2D circular-island benchmark with concentric heterogeneous conductivity. |
| `analytical/steady/linearized_unconfined_drainage_1d` | launcher-backed | steady | linearized unconfined drainage | 1D equilibrium benchmark for the top-drainage boundary condition. |
| `analytical/transient/linearized_unconfined_1d.py` | module-only | transient | linearized Boussinesq | Standalone analytical helper for transient 1D checks. |
| `analytical/transient/linearized_unconfined_recharge_step_1d` | launcher-backed | transient | linearized recharge step | 1D recharge-step benchmark under equal fixed heads. |
| `analytical/transient/linearized_unconfined_boundary_step_1d` | launcher-backed | transient | linearized boundary step | 1D west-boundary step benchmark with fixed east head. |
| `analytical/transient/linearized_unconfined_recharge_periodic_1d` | launcher-backed | transient | linearized periodic recharge | 1D sinusoidal recharge benchmark. |
| `analytical/transient/linearized_unconfined_boundary_piecewise_1d` | launcher-backed | transient | linearized piecewise boundary forcing | 1D multi-step west-boundary benchmark using CSV forcing. |
| `analytical/transient/late_time_unconfined_pumping_2d` | launcher-backed | transient | late-time Theis proxy | 2D radial pumping benchmark in the late-time unconfined regime. |

Launcher-backed case layout:

- `config_modflownwt.toml`: deterministic launcher configuration
- `reference.py`: analytical solution and literature references
- `comparison.py`: run + compare workflow
- `plotting.py`: optional visualization helper
- `run_case.py`: direct CLI entrypoint
- `metadata.toml`: case metadata consumed by tests
- `tolerances.toml`: acceptance thresholds used by validation tests

Shared helpers live under `validation_cases/shared`.
