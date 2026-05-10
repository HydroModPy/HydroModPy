# Brutsaert Recession Validation: Thin Nonlinear Aquifer

This transient validation case checks that the available `modflownwt`,
`modflow6`, and PETSc `boussinesq` backends reproduce the nonlinear
Brutsaert recession law on a thin aquifer.

Numerical setup:

- homogeneous 1D strip with west divide and east imposed head,
- steady uniform recharge used only to build the initial saturated state,
- transient recession started by switching recharge off,
- comparison performed on outlet discharge `Q(t)`.

Analytical target:

- `solution = "boussinesq"`
- thin aquifer regime with `A / L = 50 m`, matching the numerical flow length,
- effective catchment descriptors `A = 5000 m2`, `L = 100 m`, `ag = 1`.

Primary metrics:

- relative RMSE on `Q(t)`,
- relative max absolute error on `Q(t)`,
- cross-row head spread to verify the strip remains quasi-1D,
- monotone recession check on the outlet discharge series.
