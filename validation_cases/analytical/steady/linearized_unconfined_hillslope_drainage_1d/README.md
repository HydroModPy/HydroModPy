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
- drainage conductance: `1e-5 m2/s`,
- simulated observable: `watertable_elevation`.

Comparison:

- compared quantity: row-averaged head profile along `x`,
- reference: steady linearized solution of `T h'' - c_a (h - z_top) = 0`,
- additional sanity check: the numerical profile must stay above topography so
  the distributed-drainage analytical assumption remains active everywhere.

Solver variants:

- `modflownwt` and `modflow6` use the historical launcher-backed structured grid.

This case is not exposed yet for the local `boussinesq` backend. In that
backend, the current saturation-excess regularization turns the problem into a
different seepage/interception regime, so the right validation target should be
an emergence position / integrated-discharge benchmark rather than this head
profile.

Direct execution:

```bash
python -m validation_cases.analytical.steady.linearized_unconfined_hillslope_drainage_1d.run_case
python -m validation_cases.analytical.steady.linearized_unconfined_hillslope_drainage_1d.run_case --solver modflow6 --show
```
