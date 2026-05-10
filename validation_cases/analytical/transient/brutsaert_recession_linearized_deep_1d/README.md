# Brutsaert Recession Validation: Deep Linearized Aquifer

This transient validation case checks that the available `modflownwt`,
`modflow6`, and PETSc `boussinesq` backends reproduce the linearized
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

Direct MODFLOW-NWT diagnostic:

```powershell
python validation_cases\analytical\transient\brutsaert_recession_linearized_deep_1d\diagnose_modflownwt_single_boundary.py
```

This script bypasses the analytical comparison and runs four direct NWT probes
on the same strip:

- steady warm-up with a flat IC equal to the east-side head,
- steady warm-up with a small positive IC offset,
- restarted recession with the default `SIMPLE` NWT profile,
- restarted recession with the `COMPLEX` NWT profile.

It writes a compact JSON summary in the generated results directory and is meant
to isolate solver-side mass-balance issues on the single-boundary recession
setup.

Direct NWT vs MODFLOW 6 comparison:

```powershell
python validation_cases\analytical\transient\brutsaert_recession_linearized_deep_1d\diagnose_single_boundary_solver_comparison.py
```

This second script keeps the same Brutsaert strip, the same east-side Dirichlet
boundary, and the same warm-up/recession sequence, but runs the probes in both
`modflownwt` and `modflow6`. It compares:

- flat versus nudged steady warm-up on both solvers,
- the steady-state head fields reached after the NWT nudge,
- the transient outlet recession series `Q(t)` produced by NWT and MF6.

It is meant to answer a narrower question than the analytical validation:
whether the observed mismatch comes from the boundary setup itself or from the
solver-specific transient behavior of `modflownwt`.
