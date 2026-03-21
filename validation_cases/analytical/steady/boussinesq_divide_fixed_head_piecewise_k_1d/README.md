# Boussinesq Divide-Fixed-Head Piecewise-K 1D

Steady synthetic groundwater-flow case used to validate the launcher workflow
against the exact 1D Boussinesq solution written on `U = h^2` for an
unconfined aquifer with:

- a hydrologic divide on the west side (implicit no-flow),
- a fixed head on the east side,
- uniform recharge over the domain,
- piecewise-constant hydraulic conductivity along `x`.

Intent:

- validate one no-flow side boundary together with heterogeneous `K`,
- keep a clear analytical reference while extending beyond the two-head case,
- avoid synthetic geology dependencies by using generated support bands.

Comparison:

- simulated observable: `watertable_elevation`
- compared quantity: domain-averaged head profile along `x`
- reference: steady 1D Boussinesq profile with west divide, east fixed head, and piecewise `K`

Direct execution:

```bash
python -m validation_cases.analytical.steady.boussinesq_divide_fixed_head_piecewise_k_1d.run_case
python -m validation_cases.analytical.steady.boussinesq_divide_fixed_head_piecewise_k_1d.run_case --solver boussinesq --show
```

The runner saves a PNG figure with:

- numerical mean profile as blue points,
- analytical profile as an orange line,
- a residual panel and a metrics summary box.

Solver variants:

- `modflownwt` and `modflow6` use the historical launcher-backed structured-grid setup,
- `boussinesq` uses a local triangular strip bundle projected back to a regular
  `3 x 40` profile grid for plotting and metric comparison.
