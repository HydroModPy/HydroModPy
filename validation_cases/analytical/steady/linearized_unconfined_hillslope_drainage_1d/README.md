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
- `modflow6_irregular_tri` runs the same benchmark on one shared irregular-triangle strip.

This case is not exposed yet for the `boussinesq` backend. In that
backend, the current saturation-excess regularization turns the problem into a
different seepage/interception regime, so the right validation target should be
an emergence position / integrated-discharge benchmark rather than this head
profile.

Direct execution:

```bash
python -m validation_cases.analytical.steady.linearized_unconfined_hillslope_drainage_1d.run_case
python -m validation_cases.analytical.steady.linearized_unconfined_hillslope_drainage_1d.run_case --solver modflow6 --show
python -m validation_cases.analytical.steady.linearized_unconfined_hillslope_drainage_1d.run_case --solver modflow6_irregular_tri --show
```

## Equations

The equations of the reference solution the comparison uses.

$$
T_0\,\frac{\mathrm{d}^2u}{\mathrm{d}x^2}-\lambda_d\,u=0,\qquad u=h-z_{\mathrm{top}}(x)
$$

$$
z_{\mathrm{top}}(x)=z_0+A\left(1-\frac{x-x_{\min}}{L}\right),\qquad u(x)=u_w\frac{\sinh\left(\beta(L-x)\right)}{\sinh\left(\beta L\right)}+u_e\frac{\sinh\left(\beta x\right)}{\sinh\left(\beta L\right)}
$$
