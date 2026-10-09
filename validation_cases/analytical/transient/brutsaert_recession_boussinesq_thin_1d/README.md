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

Reference used by the documentation:

- reference: nonlinear Brutsaert recession law of a thin aquifer, `Q(t) = (Q0^(-1/2) + beta t)^(-2)`

## Equations

The equations of the reference solution the comparison uses.

$$
Q(t)=\left(Q_0^{-1/2}+\beta\,t\right)^{-2},\qquad
\beta=\frac{4.8038}{2}\,\frac{\sqrt{K}\,L}{S_y\,(a_g A)^{3/2}}
$$

$Q_0$ is the outlet discharge at the start of the recession, $K$ the hydraulic
conductivity, $S_y$ the specific yield, $A$ the catchment area, $L$ the
channel length and $a_g$ the active share of the area
(`validation_cases/analytical/transient/brutsaert_reference.py`).
