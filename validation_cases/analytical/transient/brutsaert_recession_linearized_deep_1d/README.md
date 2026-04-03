# Brutsaert Recession Validation: Deep Linearized Aquifer

This transient validation case checks that the available `modflownwt`,
`modflow6`, and local `boussinesq` backends reproduce the linearized
Brutsaert recession law on a deep aquifer.

Numerical setup:

- homogeneous 1D strip with west divide and east imposed head,
- steady uniform recharge used only to build the initial saturated state,
- transient recession started by switching recharge off,
- comparison performed on outlet discharge `Q(t)`.

Analytical target:

- `solution = "exponential"`
- thick aquifer regime with `b = 50 m`,
- `A = 12000 m2`, `L = 30 m`, `ag = 1`, `p = 0.25`.

Primary metrics:

- relative RMSE on `Q(t)`,
- relative max absolute error on `Q(t)`,
- cross-row head spread to verify the strip remains quasi-1D,
- monotone recession check on the outlet discharge series.
