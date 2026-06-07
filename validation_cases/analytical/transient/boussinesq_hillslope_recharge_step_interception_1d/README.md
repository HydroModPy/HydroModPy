# Boussinesq Hillslope Recharge-Step Interception 1D

Transient synthetic groundwater-flow case used to validate the dense in-house
`flow/boussinesq` runtime on a sloping hillslope where a recharge step causes
an interception zone to appear progressively from the outlet toward the divide.

Intent:

- validate the transient onset of interception on a topographic slope,
- compare the **time of first inland interception** against a linearized
  approximation,
- compare the discrete interception trajectory `x_int(t)` on the early-moving
  front where the approximation remains informative.

Numerical setup:

- same sloping strip geometry as the steady interception benchmark (`40 x 3`),
- linear topography from `10 m` to `5 m`,
- flat bottom at `0 m`,
- initial state: constant head `5 m`,
- east fixed head `5 m`,
- recharge step to `2 mm/day` from the first transient period,
- `12` periods of `10 days`.

Reference:

- linearized unconfined response around `H0 = 5 m`,
- west divide / east fixed-head mixed boundary conditions,
- the analytical approximation is used only for interception onset and early
  trajectory diagnostics, not as an exact post-interception free-boundary
  solution.

Compared metrics:

- onset-time error for the first inland contact,
- RMSE / max error of the discrete interception trajectory,
- monotonic inland migration of the numerical front,
- no positive overshoot above topography,
- low cross-row spread.

Direct execution:

```bash
python -m validation_cases.analytical.transient.boussinesq_hillslope_recharge_step_interception_1d.run_case --solver boussinesq
python -m validation_cases.analytical.transient.boussinesq_hillslope_recharge_step_interception_1d.run_case --solver boussinesq --show
```
