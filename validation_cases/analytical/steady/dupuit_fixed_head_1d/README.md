# Dupuit Fixed-Head 1D

Steady synthetic groundwater-flow case used to validate the launcher workflow
against the Dupuit analytical profile for an unconfined aquifer with fixed
heads at both ends.

Intent:

- check that the end-to-end launcher workflow reproduces the expected head
  profile on a simple homogeneous domain,
- keep one lightweight, deterministic benchmark for future validation cases.

Comparison:

- simulated observable: `watertable_elevation`
- compared quantity: domain-averaged head profile along `x`
- reference: Dupuit steady fixed-head solution
- configured solver variants: `modflownwt` (default) and `modflow6`

Solver-specific tolerances are stored in:

- `tolerances.toml` for the historical `modflownwt` baseline,
- `tolerances_modflow6.toml` for the `modflow6` variant.

Direct execution:

```bash
python -m validation_cases.analytical.steady.dupuit_fixed_head_1d.run_case --show
python -m validation_cases.analytical.steady.dupuit_fixed_head_1d.run_case --solver modflow6 --no-show
```

The runner saves a PNG figure with:

- numerical mean profile as blue points,
- analytical Dupuit profile as an orange line,
- a residual panel and a metrics summary box.
