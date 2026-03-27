# Linearized Unconfined 1D Recharge Step (Deep Aquifer)

Variant of the recharge-step transient benchmark with a deeper aquifer, so the
linearization error remains smaller for the same recharge forcing.

Numerical setup:

- geometry: quasi-1D Cartesian grid (`50 x 5`, single layer),
- flow regime: transient unconfined flow,
- west/east boundaries: fixed at `100.0 m`,
- initial condition: uniform `100.0 m`,
- forcing: constant recharge `10 mm/day` from the first period,
- reference saturated thickness: `100.0 m`,
- simulated observable: `watertable_elevation`.

For `solver=boussinesq`, the validation uses one small balanced triangular strip
projected back to a regular `40 x 3` comparison grid. The runtime itself is
selected through the case `config_boussinesq.toml`.

Run manually:

```powershell
python -m validation_cases.analytical.transient.linearized_unconfined_recharge_step_deep_1d.run_case
python -m validation_cases.analytical.transient.linearized_unconfined_recharge_step_deep_1d.run_case --solver boussinesq --show
```
