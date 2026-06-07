# Boussinesq Sloping-Substratum Constant-Thickness 1D

Steady synthetic groundwater-flow case used to validate the handling of one
sloping impermeable bottom on the simplest exact Boussinesq profile.

Intent:

- isolate the substratum-slope contribution without recharge, drainage, or seepage,
- keep an exact solution where the saturated thickness stays constant,
- compare `modflownwt`, `modflow6`, `modflow6_irregular_tri`, and the local
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
- primary metrics: head-profile RMSE, max abs error, cross-row spread.

Solver variants:

- `modflownwt` and `modflow6` use the launcher-backed structured grid,
- `modflow6_irregular_tri` uses the launcher-backed MODFLOW 6 solver on one
  shared irregular triangular strip mesh,
- `boussinesq` uses the local strip runtime with the same geometry and
  boundary conditions.

Direct execution:

```bash
python -m validation_cases.analytical.steady.boussinesq_sloping_substratum_constant_thickness_1d.run_case
python -m validation_cases.analytical.steady.boussinesq_sloping_substratum_constant_thickness_1d.run_case --solver modflow6 --show
python -m validation_cases.analytical.steady.boussinesq_sloping_substratum_constant_thickness_1d.run_case --solver modflow6_irregular_tri --show
```
