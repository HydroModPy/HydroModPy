# Brutsaert Recession Validation: Thin Nonlinear Aquifer

This transient validation case checks that the `modflow_nwt`, `modflow6` and
`modflow6_irregular_tri` backends reproduce the nonlinear late recession of
Brutsaert and Nieber (1977), `-dQ/dt = a Q^(3/2)`, on a thin aquifer.

Numerical setup:

- homogeneous strip of 50 m by 30 m on a flat substratum, west divide, east
  outlet head on the substratum (`h = 0`),
- one steady day under 2 mm/day of recharge builds the initial water table,
- 128 days of recession without recharge, four time steps a day,
- comparison on the outlet discharge `Q(t)` from day 16, once the water table
  has the separable shape of Boussinesq (1904).

The outlet must sit on the substratum. With an outlet head above it, the tail
turns linear: 1 m gave `b = 1.08` instead of 3/2.

Analytical target:

- the drainage length `B` runs from the divide to the cells that hold the
  outlet head: half a column inside the edge on a structured grid, at the
  boundary triangle centroids on a mesh,
- the outlet width `W`, `K` and `Sy` are read from `config_common.toml`,
- `Q*` is fitted on the run: the late law does not describe the initial water
  table.

Primary metrics, over the window from day 16 to day 128:

- relative error of the fitted `a` (slope of `Q^(-1/2)` against `t`),
- fitted exponent `b` of `-dQ/dt = a Q^b` against 3/2,
- RMSE of `Q / Q_ref - 1`,
- cross-row head spread and monotone recession.

The thresholds come from a grid and time-step refinement
(`tolerances.toml`). Upstream weighting next to the dry outlet gives MODFLOW a
first-order error on `a`: +4.0 % at 1.25 m cells, +2.1 % at 0.625 m, +1.1 % at
0.3125 m. An independent fine-grid solution of the same Boussinesq problem
matches the law to 1e-4.

Reference used by the documentation:

- reference: nonlinear late recession of Brutsaert and Nieber (1977) for a strip drained on one side, `Q(t) = (Q*^(-1/2) + a t / 2)^(-2)`

## Equations

The equations of the reference solution the comparison uses.

$$
-\frac{dQ}{dt}=a\,Q^{3/2},\qquad
Q(t)=\left(Q_*^{-1/2}+\frac{a\,t}{2}\right)^{-2},\qquad
a=\frac{C\,\sqrt{K}\,W}{S_y\,(B\,W)^{3/2}}
$$

$K$ is the hydraulic conductivity, $S_y$ the specific yield, $B$ the drainage
length, $W$ the outlet width and $C = 3\,I^{3/2} = 2.4025$ with
$I=\int_0^1 p\,(1-p^3)^{-1/2}\,dp$. Twice $C$ is the 4.804 of Brutsaert and
Nieber (1977), written for a channel drained from both banks
(`validation_cases/analytical/transient/brutsaert_reference.py`).
