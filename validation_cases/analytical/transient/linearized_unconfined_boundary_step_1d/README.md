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
while the nonlinear backend can evolve independently. The analytical
`boussinesq` variant now defaults to PETSc TS VI.

Run manually:

```powershell
python -m validation_cases.analytical.transient.linearized_unconfined_boundary_step_1d.run_case
python -m validation_cases.analytical.transient.linearized_unconfined_boundary_step_1d.run_case --solver boussinesq --show
python -m validation_cases.analytical.transient.linearized_unconfined_boundary_step_1d.run_comparison
```

Reference used by the documentation:

- reference: linearized 1D unconfined response to a step of the west boundary head
- boundary positions: each side head is posed where the model holds it, at the
  centre of the boundary column, or at the mean centroid of the boundary
  triangles on the triangle strip; a no-flow side stays on the domain face
  (`validation_cases/shared/strip_geometry.py`)

## Equations

The equations of the reference solution the comparison uses.

$$
S_y\frac{\partial \eta}{\partial t}=T_0\frac{\partial^2 \eta}{\partial x^2},\qquad \eta(0,t)=\Delta h\,H(t),\qquad \eta(L,t)=0
$$

$$
\eta(x,t)=\Delta h\left[1-\frac{x}{L}-\frac{2}{\pi}\sum_{n=1}^{\infty}\frac{\sin\left(n\pi x/L\right)}{n}\exp\left(-D\left(n\pi/L\right)^2 t\right)\right]
$$
