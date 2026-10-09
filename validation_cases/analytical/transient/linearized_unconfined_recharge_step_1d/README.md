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

For `solver=boussinesq`, the validation uses one small balanced triangular strip
projected back to a regular `40 x 3` comparison grid. The runtime itself is
selected through the case `config_boussinesq.toml`, while this geometry avoids
the directional bias that appeared on the earlier `50 x 2` thin-strip harness.

Run manually:

```powershell
python -m validation_cases.analytical.transient.linearized_unconfined_recharge_step_1d.run_case
python -m validation_cases.analytical.transient.linearized_unconfined_recharge_step_1d.run_case --solver boussinesq --show
```

Reference used by the documentation:

- reference: linearized 1D unconfined response to a recharge step
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
\eta(x,t)=\frac{R_0}{2T_0}x(L-x)-\frac{4R_0L^2}{T_0\pi^3}\sum_{n=0}^{\infty}\frac{\sin\left((2n+1)\pi x/L\right)}{(2n+1)^3}\exp\left(-D\left((2n+1)\pi/L\right)^2 t\right)
$$
