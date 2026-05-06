# Boussinesq Hillslope Interception 1D

Steady synthetic groundwater-flow case used to validate the PETSc VI obstacle
`flow/boussinesq` runtime on a sloping hillslope where the water table reaches
the land surface near the outlet.

Intent:

- validate the emergence/interception position on a topographic slope,
- keep a closed-form inland Boussinesq profile on the dry part of the hillslope,
- benchmark the hard surface-obstacle closure with a metric that remains
  physically meaningful for seepage onset.

Numerical setup:

- quasi-1D strip (`40 x 3`) with alternating triangle diagonals,
- linear topography descending from `10 m` to `5 m`,
- flat impermeable bottom at `0 m`,
- uniform recharge `2 mm/day`,
- homogeneous hydraulic conductivity `1e-4 m/s`,
- fixed head `5 m` on the east side,
- west side left as the natural divide/no-flow boundary.

Comparison:

- simulated observable: `watertable_elevation`,
- primary metric: inland interception position along `x`,
- secondary sanity checks: no overshoot above topography and low cross-row spread,
- reference: analytical no-drain steady Boussinesq recharge profile with west
  divide and east fixed head, intersected with the linear topography,
- numerical interception is detected with a small `5 cm` contact tolerance on
  the row-averaged profile.

Important limitation:

- this case is intentionally exposed only for `solver=boussinesq`;
- `solver=boussinesq` runs with `runtime_backend = "petsc"` and
  `surface_interaction_model = "vi_obstacle"`;
- the analytical target is an interception-position approximation inherited
  from the no-drain profile, not a full free-boundary seepage-face solution;
- the PETSc VI obstacle result is numerically clean but shifts the interception
  position relative to that no-drain diagnostic; see
  `docs/developers/boussinesq_petsc_vi_hillslope_interception_analysis.md`;
- dry-zone profile metrics are reported for diagnosis, but the asserted
  benchmark remains the emergence position itself.

Direct execution:

```bash
python -m validation_cases.analytical.steady.boussinesq_hillslope_interception_1d.run_case --solver boussinesq
python -m validation_cases.analytical.steady.boussinesq_hillslope_interception_1d.run_case --solver boussinesq --show
```
