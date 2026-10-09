# Brutsaert Recession Validation: Deep Linearized Aquifer

This transient validation case checks that the `modflow_nwt`, `modflow6` and
`modflow6_irregular_tri` backends reproduce the linearized recession of a
deep aquifer, whose tail is the exponential law of Brutsaert and Nieber
(1977), `-dQ/dt = a Q`.

Numerical setup:

- homogeneous strip of 400 m by 30 m, west divide, east outlet head 50 m above
  the substratum,
- one steady period of 10 days under 2 mm/day of recharge builds the initial
  water table, a rise of 0.36 m on 50 m,
- 90 days of recession without recharge, in 10-day periods of 100 time steps
  each,
- comparison on the outlet discharge `Q(t)`.

One time step per 10-day period damps each mode by `1 / (1 + a dt)` instead of
`exp(-a dt)`, and the tail then ends 4 times above the law at day 90.

Analytical target:

- the linearized Boussinesq series solution from the steady warm-up, with
  `D = 50 m`, the saturated thickness at the outlet,
- the drainage length `B` runs from the divide to the cells that hold the
  outlet head: half a column inside the edge on a structured grid, at the
  boundary triangle centroids on a mesh,
- the recharged length is the steady discharge over `R W`: a model loses the
  recharge that falls on its fixed-head cells.

Primary metrics:

- relative RMSE and maximum error of `Q(t)` over the whole recession, scaled by
  the initial discharge,
- from day 30: relative error of the fitted decay rate, fitted exponent `b`
  against 1, and RMSE of `Q / Q_ref - 1`, which weighs the last decade of the
  recession as much as the first,
- cross-row head spread and monotone recession.

The thresholds come from a time-step refinement (`tolerances.toml`). Backward
Euler lowers the decay rate by `a dt / 2 = 0.33 %` at 100 steps a period.

Direct MODFLOW-NWT diagnostics:

```powershell
python validation_cases\analytical\transient\brutsaert_recession_linearized_deep_1d\diagnose_modflownwt_single_boundary.py
python validation_cases\analytical\transient\brutsaert_recession_linearized_deep_1d\diagnose_single_boundary_solver_comparison.py
```

These probes were written while MODFLOW-NWT froze on this recession. The cause
is found: the GMRES linear solver (`linmeth = 1`) did not reduce the residual,
and a flux closure of the size of the whole budget let NWT accept the update.
The validation profile now uses chi-MD (`linmeth = 2`) with closures below
the smallest quantity the case resolves (`validation_cases/shared/runtime.py`).

Reference used by the documentation:

- reference: linearized Boussinesq recession of a deep strip after steady recharge, whose tail is the exponential law of Brutsaert and Nieber (1977)

## Equations

The equations of the reference solution the comparison uses.

$$
Q(t)=Q_0\,\frac{B}{B-d}\sum_{n\ge 1}\frac{8\cos\!\left(\frac{k\pi d}{2B}\right)}{k^2\pi^2}\,e^{-k^2 a t},\qquad
k=2n-1,\qquad
a=\frac{\pi^2\,K\,D}{4\,S_y\,B^2}
$$

$Q_0$ is the steady discharge at the end of the warm-up, $K$ the hydraulic
conductivity, $S_y$ the specific yield, $D$ the saturated thickness at the
outlet, $B$ the drainage length and $d$ the length near the outlet that the
model does not recharge. The first term alone is the late exponential law
(`validation_cases/analytical/transient/brutsaert_reference.py`).
