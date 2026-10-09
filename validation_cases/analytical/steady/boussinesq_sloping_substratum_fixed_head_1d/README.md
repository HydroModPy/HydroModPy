# Boussinesq Sloping-Substratum Fixed-Head 1D

Steady synthetic groundwater-flow case used to validate one sloping substratum
profile beyond the trivial constant-thickness solution.

Intent:

- keep the same simple sloping geometry as the constant-thickness case,
- remove recharge and drainage so the comparison isolates only the lateral
  Boussinesq balance on a sloping bottom,
- compare `modflownwt`, `modflow6`, `modflow6_irregular_tri`, and the local
  `boussinesq` backend against one semi-analytical no-recharge profile.

Numerical setup:

- quasi-1D strip (`40 x 5`, single layer for launcher-backed runs),
- linear topography from `25 m` on the west side to `20 m` on the east side,
- linear substratum from `5 m` on the west side to `0 m` on the east side,
- geometric aquifer thickness `20 m`,
- west/east heads `15 m` / `5 m`,
- no recharge, no drainage, homogeneous `K = 1e-4 m/s`.

Comparison:

- compared quantity: row-averaged head profile along `x`,
- reference: steady no-recharge Boussinesq relation on `b(x)` above a linear
  substratum, solved through its implicit integral law,
- boundary positions: each side head is posed where the model holds it, at the
  centre of the boundary column, or at the mean centroid of the boundary
  triangles on the triangle strip; a no-flow side stays on the domain face
  (`validation_cases/shared/strip_geometry.py`)
- primary metrics: head-profile RMSE, max abs error, cross-row spread.

Solver variants:

- `modflownwt` and `modflow6` use the launcher-backed structured grid,
- `modflow6_irregular_tri` uses the launcher-backed MODFLOW 6 solver on one
  shared irregular triangular strip mesh,
- `boussinesq` uses the local strip runtime with the same geometry and
  boundary conditions.

Direct execution:

```bash
python -m validation_cases.analytical.steady.boussinesq_sloping_substratum_fixed_head_1d.run_case
python -m validation_cases.analytical.steady.boussinesq_sloping_substratum_fixed_head_1d.run_case --solver modflow6 --show
python -m validation_cases.analytical.steady.boussinesq_sloping_substratum_fixed_head_1d.run_case --solver modflow6_irregular_tri --show
```

## Equations

The equations of the reference solution the comparison uses.

$$
q=K\,b\left(S_0-\frac{\mathrm{d}b}{\mathrm{d}x}\right),\qquad S_0=-\frac{\mathrm{d}z_b}{\mathrm{d}x}
$$

$$
x-x_{\min}=\int_{b_w}^{b(x)} \frac{K\,\eta}{K\,\beta\,\eta-q}\,\mathrm{d}\eta,\qquad \beta=S_0,\qquad H(x)=z_b(x)+b(x)
$$
