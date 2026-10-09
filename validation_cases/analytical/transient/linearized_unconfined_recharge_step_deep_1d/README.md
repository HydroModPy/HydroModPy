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

Reference used by the documentation:

- reference: linearized 1D unconfined response to a recharge step in a deep aquifer, where the linearization error is smaller
- boundary positions: each side head is posed where the model holds it, at the
  centre of the boundary column, or at the mean centroid of the boundary
  triangles on the triangle strip; a no-flow side stays on the domain face
  (`validation_cases/shared/strip_geometry.py`)

## Equations

The equations of the reference solution the comparison uses.

$$
S_y\frac{\partial \eta}{\partial t}=T_0\frac{\partial^2 \eta}{\partial x^2}+R_0\,H(t),\qquad h=h_0+\eta
$$

$$
T_0=K\,h_{\mathrm{ref}},\qquad D=\frac{T_0}{S_y}
$$
