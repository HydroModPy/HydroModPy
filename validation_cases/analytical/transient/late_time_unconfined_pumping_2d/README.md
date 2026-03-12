# Late-Time Unconfined Pumping 2D

This `v1` case validates one transient non-confined pumping response in a
pragmatic way.

Numerical setup:

- geometry: square Cartesian grid (`101 x 101`, single layer),
- flow regime: transient unconfined flow,
- all outer boundaries: fixed at the initial head,
- initial condition: uniform `30.0 m`,
- forcing: one constant pumping well at the domain center,
- simulated observable: `watertable_elevation`.

Reference model:

- the numerical model is non-confined,
- the analytical reference is intentionally limited to the late-time regime,
- drawdown is compared against the Theis well function using
  `T = K * href` and `S = Sy`,
- early delayed-yield effects are excluded from the comparison window.

This is not a full Neuman solution. It is a lightweight validation of:

- transient well forcing,
- late-time radial drawdown scaling,
- numerical radial symmetry around the pumping well.

Run manually:

```powershell
python -m validation_cases.analytical.transient.late_time_unconfined_pumping_2d.run_case
```
