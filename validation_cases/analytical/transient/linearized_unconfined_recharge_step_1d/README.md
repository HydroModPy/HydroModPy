# Linearized Unconfined 1D Recharge Step

This case validates the transient linearized Boussinesq-Dupuit response of an
unconfined 1D aquifer submitted to a recharge step at `t = 0`.

Numerical setup:

- geometry: quasi-1D Cartesian grid (`50 x 5`, single layer),
- flow regime: transient unconfined flow,
- west/east boundaries: fixed at `10.0 m`,
- initial condition: uniform `10.0 m`,
- forcing: constant recharge `10 mm/day` from the first period,
- simulated observable: `watertable_elevation`.

Run manually:

```powershell
python -m validation_cases.analytical.transient.linearized_unconfined_recharge_step_1d.run_case
```
