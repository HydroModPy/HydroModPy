# Linearized Unconfined Drainage 1D

Steady synthetic groundwater-flow case used to validate HydroModPy's top
drainage boundary condition against a closed-form linearized 1D reference with:

- fixed heads on the west and east sides,
- uniform top drainage conductance applied everywhere,
- a flat drainage elevation below the simulated water table,
- a homogeneous aquifer whose heads stay above the cell top, so the cells are
  full and the reference thickness is the cell thickness, `20 m`.

Intent:

- validate the `drainage` boundary-condition path with an analytical benchmark,
- keep drainage active everywhere so the reference stays closed-form,
- isolate one lightweight 1D equilibrium before tackling more complex seepage-face cases.

Comparison:

- simulated observable: `watertable_elevation`
- compared quantity: domain-averaged head profile along `x`
- reference: steady linearized unconfined profile with distributed top drainage
- boundary positions: each side head is posed where the model holds it, at the
  centre of the boundary column, or at the mean centroid of the boundary
  triangles on the triangle strip; a no-flow side stays on the domain face
  (`validation_cases/shared/strip_geometry.py`)

Solver variants:

- `modflownwt` and `modflow6` use the historical structured strip,
- `modflow6_irregular_tri` runs the same benchmark on one shared irregular-triangle strip,
- the `boussinesq` backend is not exposed here yet because this benchmark keeps the head above the top drainage elevation everywhere, which currently collides with the saturation-excess surface closure instead of staying on the intended linearized distributed-drainage branch.

Direct execution:

```bash
python -m validation_cases.analytical.steady.linearized_unconfined_drainage_1d.run_case
python -m validation_cases.analytical.steady.linearized_unconfined_drainage_1d.run_case --solver modflow6_irregular_tri --show
```

The runner saves a PNG figure with:

- numerical mean profile as blue points,
- analytical profile as an orange line,
- a residual panel and a metrics summary box.

## Equations

The equations of the reference solution the comparison uses.

$$
T_0\,\frac{\mathrm{d}^2u}{\mathrm{d}x^2}-\lambda_d\,u=0,\qquad u=h-z_d,\qquad \lambda_d=\frac{C_d}{A}
$$

$$
u(x)=u_w\frac{\sinh\left(\beta(L-x)\right)}{\sinh\left(\beta L\right)}+u_e\frac{\sinh\left(\beta x\right)}{\sinh\left(\beta L\right)},\qquad \beta=\sqrt{\frac{\lambda_d}{T_0}}
$$
