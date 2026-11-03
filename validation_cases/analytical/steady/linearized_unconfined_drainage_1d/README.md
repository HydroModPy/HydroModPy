# Linearized Unconfined Drainage 1D

Steady synthetic groundwater-flow case used to validate HydroModPy's top
drainage boundary condition against a closed-form linearized 1D reference with:

- fixed heads on the west and east sides,
- top drainage everywhere, with no conductance declared: each drain takes
  `C = K * cell_area / b` with `b = solver.drain_bed_thickness_m = 4000 m`, so
  the leakance `K / b = 2.5e-8 1/s` is the same on every mesh,
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
  center of the boundary column, or at the mean centroid of the boundary
  triangles on the triangle strip; a no-flow side stays on the domain face
  (`validation_cases/shared/strip_geometry.py`)

Solver variants:

- `modflownwt` and `modflow6` use the historical structured strip,
- `modflow6_irregular_tri` runs the same benchmark on one shared irregular-triangle strip,
- `modflow6_voronoi` runs it on the Voronoi dual of that strip, one cell per node:
  the side heads sit on the faces, each drain takes `C = K * dual_cell_area / b`, and
  the cells are read at their nodes and binned by area into the 50 columns of the
  reference,
- `boussinesq` runs the PETSc VI obstacle engine on a `50 x 5` strip of equal-area
  triangles (2 m2). The drain is the head-dependent `C * max(h - z_top, 0)` with an
  explicit positive conductance `C = K * A / b = 5e-8 m2/s`, written under
  `flow.bc.drainage`. A positive value is what relaxes the upper obstacle, so that the
  head stands above the drain elevation; the conductance is one scalar per cell, so
  `K * A / b` gives the leakance `K / b` only on equal-area cells. The side heads sit
  at the centroid of the triangle that owns the side edge,
- `boussinesq_local`, the default local engine, is not run: its regularized partition
  releases at the surface all the water a cell receives once its head reaches the
  drain elevation, so it cannot hold the head above the drain this reference needs.

Direct execution:

```bash
python -m validation_cases.analytical.steady.linearized_unconfined_drainage_1d.run_case
python -m validation_cases.analytical.steady.linearized_unconfined_drainage_1d.run_case --solver modflow6_irregular_tri --show
python -m validation_cases.analytical.steady.linearized_unconfined_drainage_1d.run_case --solver modflow6_voronoi --show
```

The runner saves a PNG figure with:

- numerical mean profile as blue points,
- analytical profile as an orange line,
- a residual panel and a metrics summary box.

## Equations

The equations of the reference solution the comparison uses.

$$
T_0\,\frac{\mathrm{d}^2u}{\mathrm{d}x^2}-\lambda_d\,u=0,\qquad u=h-z_d,\qquad \lambda_d=\frac{C_d}{A}=\frac{K}{b}
$$

$$
u(x)=u_w\frac{\sinh\left(\beta(L-x)\right)}{\sinh\left(\beta L\right)}+u_e\frac{\sinh\left(\beta x\right)}{\sinh\left(\beta L\right)},\qquad \beta=\sqrt{\frac{\lambda_d}{T_0}}
$$
