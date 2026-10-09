# Linearized Unconfined 1D Periodic Recharge

This case validates the transient linearized Boussinesq-Dupuit response of an
unconfined 1D aquifer submitted to a sinusoidal recharge forcing.

Numerical setup:

- geometry: quasi-1D Cartesian grid (`50 x 5`, single layer),
- flow regime: transient unconfined flow,
- west/east boundaries: fixed at `10.0 m`,
- recharge forcing: `5.0 + 5.0 * sin(2π t / 10 d)` mm/day sampled every `1 day`,
- initial condition: uniform `10.0 m`,
- simulated observable: `watertable_elevation`.

Run manually:

```powershell
python -m validation_cases.analytical.transient.linearized_unconfined_recharge_periodic_1d.run_case
```

Reference used by the documentation:

- reference: linearized 1D unconfined response to a sinusoidal recharge

## Equations

The equations of the reference solution the comparison uses.

$$
S_y\frac{\partial \eta}{\partial t}=T_0\frac{\partial^2 \eta}{\partial x^2}+R(t),\qquad h=h_0+\eta
$$

$$
R(t)=\overline{R}+A\sin\left(2\pi t/P+\phi\right)
$$
