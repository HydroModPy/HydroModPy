# Boussinesq Sloping-Substratum Constant-Thickness 1D

Steady synthetic groundwater-flow case used to validate the handling of one
sloping impermeable bottom on the simplest exact Boussinesq profile.

Intent:

- isolate the substratum-slope contribution without recharge, drainage, or seepage,
- keep an exact solution where the saturated thickness stays constant,
- compare `modflownwt`, `modflow6`, `modflow6_irregular_tri`, `modflow6_voronoi`, and the local
  `boussinesq` backend on the same sloping geometry.

Numerical setup:

- quasi-1D strip (`40 x 5`, single layer for launcher-backed runs),
- linear topography from `25 m` on the west side to `20 m` on the east side,
- linear substratum from `5 m` on the west side to `0 m` on the east side,
- geometric aquifer thickness `20 m`,
- west/east heads `13 m` / `8 m`,
- no recharge, no drainage, homogeneous `K = 1e-4 m/s`.

Comparison:

- compared quantity: row-averaged head profile along `x`,
- reference: exact steady profile `H(x) = z_b(x) + b*` with `b* = 8 m`,
- boundary positions: each side head is posed where the model holds it, at the
  centre of the boundary column, or at the mean centroid of the boundary
  triangles on the triangle strip, or on the face on the Voronoi dual, whose
  cells are seeded on the face; a no-flow side stays on the domain face
  (`validation_cases/shared/strip_geometry.py`)
- Voronoi dual: one cell per node of the triangle strip, read at its node and
  binned by area-weighted mean into the same 40 columns as the reference
- primary metrics: head-profile RMSE, max abs error, cross-row spread.

Solver variants:

- `modflownwt` and `modflow6` use the launcher-backed structured grid,
- `modflow6_irregular_tri` uses the launcher-backed MODFLOW 6 solver on one
  shared irregular triangular strip mesh,
- `modflow6_voronoi` uses the same strip mesh with `grid_dual = "voronoi"`, one
  cell per mesh node,
- `boussinesq` uses the local strip runtime with the same geometry and
  boundary conditions.

Known gap on `modflow6_voronoi`: the reference is the uniform flow, so a small
flux error drifts the thickness. The mesh bundle holds 3 face nodes 25 m apart,
and three interior Voronoi cells own 1 to 4.5 m of the held face as a no-flow
edge. Face nodes every 5 m bring the RMSE from 7.1e-3 m to 8.4e-4 m
(`tolerances_modflow6_voronoi.toml`).

Direct execution:

```bash
python -m validation_cases.analytical.steady.boussinesq_sloping_substratum_constant_thickness_1d.run_case
python -m validation_cases.analytical.steady.boussinesq_sloping_substratum_constant_thickness_1d.run_case --solver modflow6 --show
python -m validation_cases.analytical.steady.boussinesq_sloping_substratum_constant_thickness_1d.run_case --solver modflow6_irregular_tri --show
python -m validation_cases.analytical.steady.boussinesq_sloping_substratum_constant_thickness_1d.run_case --solver modflow6_voronoi --show
```

## Equations

The equations of the reference solution the comparison uses.

$$
H(x)=z_b(x)+b^\ast,\qquad z_b(x)=z_{b,0}+\Delta z_b\left(1-\frac{x-x_{\min}}{L}\right)
$$

$$
q=-K\,b^\ast\,\frac{\mathrm{d}H}{\mathrm{d}x}=K\,b^\ast\,S_0,\qquad S_0=\frac{z_b(x_{\min})-z_b(x_{\max})}{L}
$$
