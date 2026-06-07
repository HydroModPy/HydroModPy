# Boussinesq Sloping-Substratum Uniform-Recharge 1D

Steady synthetic groundwater-flow case used to validate one sloping substratum
profile under uniform recharge.

Intent:

- extend the sloping-substratum validation suite to a recharge-driven regime,
- keep a simple linear hillslope geometry with fixed heads at both ends,
- compare `modflownwt`, `modflow6`, `modflow6_irregular_tri`, and the local
  `boussinesq` backend against one deterministic semi-analytical reference
  built from the steady 1D Boussinesq balance on `b(x)`.

Numerical setup:

- quasi-1D strip (`40 x 5`, single layer for launcher-backed runs),
- linear topography from `25 m` on the west side to `20 m` on the east side,
- linear substratum from `5 m` on the west side to `0 m` on the east side,
- geometric aquifer thickness `20 m`,
- west/east heads `15 m` / `5 m`,
- uniform recharge `1 mm/day`, homogeneous `K = 1e-4 m/s`,
- no drainage and no surface interception in the reference regime.

Comparison:

- compared quantity: row-averaged head profile along `x`,
- reference: steady 1D sloping-substratum system
  `dq/dx = R`, `db/dx = S0 - q / (K b)` solved by shooting on the west
  discharge and RK4 integration of the thickness profile,
- primary metrics: head-profile RMSE, max abs error, cross-row spread.

Solver variants:

- `modflownwt` and `modflow6` use the launcher-backed structured grid,
- `modflow6_irregular_tri` uses the launcher-backed MODFLOW 6 solver on one
  shared irregular triangular strip mesh,
- `boussinesq` uses the local strip runtime with the same geometry, recharge,
  and lateral boundary conditions.

Direct execution:

```bash
python -m validation_cases.analytical.steady.boussinesq_sloping_substratum_uniform_recharge_1d.run_case
python -m validation_cases.analytical.steady.boussinesq_sloping_substratum_uniform_recharge_1d.run_case --solver modflow6 --show
python -m validation_cases.analytical.steady.boussinesq_sloping_substratum_uniform_recharge_1d.run_case --solver modflow6_irregular_tri --show
```
