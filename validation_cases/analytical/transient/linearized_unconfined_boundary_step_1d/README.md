# Linearized Unconfined 1D Boundary Step

This case validates the transient linearized Boussinesq-Dupuit response of an
unconfined 1D aquifer submitted to a west-boundary head step at `t = 0`.

Numerical setup:

- geometry: quasi-1D Cartesian grid (`50 x 5`, single layer),
- flow regime: transient unconfined flow,
- east boundary: fixed at `10.0 m`,
- west boundary: CSV forcing jumping from the initial state to `10.10 m`,
- initial condition: uniform `10.0 m`,
- simulated observable: `watertable_elevation`.

For `solver=boussinesq`, the validation uses one small balanced triangular strip
projected back to a regular `40 x 3` comparison grid. The runtime itself is
selected through the case `config_boussinesq.toml`, so the geometry stays fixed
while the nonlinear backend can evolve independently (`local`, `scipy`,
`scipy_sparse`).

Run manually:

```powershell
python -m validation_cases.analytical.transient.linearized_unconfined_boundary_step_1d.run_case
python -m validation_cases.analytical.transient.linearized_unconfined_boundary_step_1d.run_case --solver boussinesq --show
python -m validation_cases.analytical.transient.linearized_unconfined_boundary_step_1d.run_comparison
```
