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

Run manually:

```powershell
python -m validation_cases.analytical.transient.linearized_unconfined_boundary_step_1d.run_case
```
