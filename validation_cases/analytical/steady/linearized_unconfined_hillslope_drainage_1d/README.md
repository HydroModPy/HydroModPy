# Linearized Unconfined Hillslope Drainage 1D

Steady synthetic groundwater-flow case used to validate one sloping-topography
setup with distributed top drainage under the linearized unconfined model.

The case is intentionally not a true free-boundary seepage-face benchmark.
Instead, it keeps drainage active everywhere by imposing boundary heads slightly
above the local land surface, which makes the analytical comparison explicit
while still exercising:

- linearly varying topography,
- drainage elevation tied to land surface,
- fixed heads on both lateral sides.

Numerical setup:

- geometry: quasi-1D strip (`50 x 5`, single layer for launcher-backed runs),
- topography: linear, from `7.0 m` on the west side to `5.0 m` on the east side,
- aquifer thickness: `30.0 m`,
- west/east heads: `7.25 m` / `5.25 m`,
- drainage: no conductance declared, each drain takes `C = K * cell_area / b`
  with `b = solver.drain_bed_thickness_m = 40 m`, so the leakance
  `K / b = 2.5e-6 1/s` is the same on every mesh,
- simulated observable: `watertable_elevation`.

Comparison:

- compared quantity: row-averaged head profile along `x`,
- reference: steady linearized solution of `T h'' - (K / b) (h - z_top) = 0`,
- boundary positions: each side head is posed where the model holds it, at the
  center of the boundary column, or at the mean centroid of the boundary
  triangles on the triangle strip; a no-flow side stays on the domain face
  (`validation_cases/shared/strip_geometry.py`)
- additional sanity check: the numerical profile must stay above topography so
  the distributed-drainage analytical assumption remains active everywhere.

Solver variants:

- `modflownwt` and `modflow6` use the historical launcher-backed structured grid.
- `modflow6_irregular_tri` runs the same benchmark on one shared irregular-triangle strip.
- `modflow6_voronoi` runs it on the Voronoi dual of that strip, one cell per node. The
  topography is sampled at the nodes, each drain sits at the cell top with
  `C = K * dual_cell_area / b`, and the cells are read at their nodes and binned by area
  into the 50 columns of the reference.
- `boussinesq` runs the PETSc VI obstacle engine on a `50 x 5` strip of equal-area
  triangles (2 m2) with the bottom 30 m under the land surface. The drain is the
  head-dependent `C * max(h - z_top, 0)` with an explicit positive conductance
  `C = K * A / b = 5e-6 m2/s`, written under `flow.bc.drainage`. A positive value is
  what relaxes the upper obstacle, so that the head stands above the land surface; the
  conductance is one scalar per cell, so `K * A / b` gives the leakance `K / b` only on
  equal-area cells.
- `boussinesq_local`, the default local engine, is not run: its regularized partition
  releases at the surface all the water a cell receives once its head reaches the land
  surface, so it cannot hold the head above it as this reference requires.

Direct execution:

```bash
python -m validation_cases.analytical.steady.linearized_unconfined_hillslope_drainage_1d.run_case
python -m validation_cases.analytical.steady.linearized_unconfined_hillslope_drainage_1d.run_case --solver modflow6 --show
python -m validation_cases.analytical.steady.linearized_unconfined_hillslope_drainage_1d.run_case --solver modflow6_irregular_tri --show
python -m validation_cases.analytical.steady.linearized_unconfined_hillslope_drainage_1d.run_case --solver modflow6_voronoi --show
```

## Equations

The equations of the reference solution the comparison uses.

$$
T_0\,\frac{\mathrm{d}^2u}{\mathrm{d}x^2}-\lambda_d\,u=0,\qquad u=h-z_{\mathrm{top}}(x),\qquad \lambda_d=\frac{K}{b}
$$

$$
z_{\mathrm{top}}(x)=z_0+A\left(1-\frac{x-x_{\min}}{L}\right),\qquad u(x)=u_w\frac{\sinh\left(\beta(L-x)\right)}{\sinh\left(\beta L\right)}+u_e\frac{\sinh\left(\beta x\right)}{\sinh\left(\beta L\right)}
$$
