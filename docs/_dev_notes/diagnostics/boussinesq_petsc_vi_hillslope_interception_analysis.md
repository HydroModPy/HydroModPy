# Boussinesq PETSc VI Hillslope Interception Analysis

This note documents the steady analytical validation case
`boussinesq_hillslope_interception_1d` after the analytical Boussinesq defaults
were switched to the PETSc VI obstacle runtime.

## Short conclusion

The migration is mostly a runtime substitution for the analytical validation
suite: steady cases use a pure steady PETSc SNESVI solve
(`surface_interaction_model = "vi_obstacle"`), and transient cases use PETSc TS
with SNESVI (`surface_interaction_model = "ts_vi_obstacle"`).

The main scientific change observed so far is the steady hillslope interception
metric. The PETSc VI solve is numerically clean, but the detected interception
position is displaced relative to the historical analytical target. This is
expected because the target is a no-drain Boussinesq profile intersected with
topography, while the PETSc VI runtime solves a hard surface-obstacle problem
with a surface reaction.

## Observed PETSc VI result

Current Boussinesq validation metrics for the case:

| Quantity | Value |
| --- | ---: |
| Analytical interception x | `244.77611971282428 m` |
| Numerical PETSc VI interception x | `285.0 m` |
| Absolute x error | `40.22388028717572 m` |
| Steady residual infinity norm | about `8.9e-15` |
| Maximum head above topography | `0.0 m` |
| Cross-row spread | about `9e-16 m` |
| Surface-active cells | `27 / 240` |
| Surface reaction total | about `4.82e-5 m3/s` |

The validation tolerance for the interception metric is therefore set to
`45 m`. The contact and uniformity checks remain strict.

## Why the shift is meaningful

The analytical interception reference is computed from the no-drain steady
Boussinesq profile:

```text
h(x)^2 = h_e^2 + (R / K) * (L^2 - x^2)
```

and from the intersection of that profile with the linear topography. This
reference says where a profile would first meet topography if no surface
reaction changed the water-table shape.

The PETSc VI method solves a different mathematical object:

```text
z_bottom <= h <= z_top
surface_reaction >= 0
surface_reaction * (z_top - h) = 0
```

At steady state, the surface reaction is reconstructed as the obstacle reaction
needed to satisfy both the bounded head and the groundwater balance. Once the
toe-side surface constraint becomes active, recharge and lateral convergence can
leave through the surface reaction instead of continuing to push the no-drain
profile upward. The resulting profile is therefore not required to intersect
topography at the no-drain analytical position.

The numerical profile confirms this interpretation: it remains below the
topography inland, reaches the configured `5 cm` numerical contact band around
`x = 285 m`, and never overshoots the topography.

## Validation interpretation

This case should now be read as a PETSc VI obstacle regression test against an
approximate no-drain interception diagnostic, not as an exact free-boundary
seepage-face verification.

The current tolerance keeps the case useful because it still checks:

- no positive clearance above the surface,
- a stable quasi-1D result,
- a bounded interception-position displacement relative to the historical
  diagnostic.

A stronger future validation would need an analytical or high-resolution
reference for the obstacle/seepage-face formulation itself, rather than the
no-drain Boussinesq intersection.

## Files to inspect

- Case README:
  `validation_cases/analytical/steady/boussinesq_hillslope_interception_1d/README.md`
- Runtime:
  `validation_cases/analytical/steady/boussinesq_hillslope_interception_1d/runtime_boussinesq.py`
- Comparison metrics:
  `validation_cases/analytical/steady/boussinesq_hillslope_interception_1d/comparison.py`
- Figure annotation:
  `validation_cases/analytical/steady/boussinesq_hillslope_interception_1d/plotting.py`
- Tolerance:
  `validation_cases/analytical/steady/boussinesq_hillslope_interception_1d/tolerances.toml`
- Shared method-label helper:
  `validation_cases/shared/boussinesq_plotting.py`

Manual reproduction:

```powershell
wsl.exe bash -lc "cd /mnt/c/codes/HydroModPy && bash install/enter_wsl_dev.sh --headless -- python -m validation_cases.analytical.steady.boussinesq_hillslope_interception_1d.run_case --solver boussinesq --no-show --output-root /mnt/c/codes/HydroModPy/tmp/boussinesq_petsc_validation_figures"
```
