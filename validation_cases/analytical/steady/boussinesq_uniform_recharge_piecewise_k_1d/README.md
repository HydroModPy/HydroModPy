# Boussinesq Uniform-Recharge Piecewise-K 1D

Steady synthetic groundwater-flow case used to validate the launcher workflow
against the exact 1D Boussinesq solution written on `U = h^2` for an
unconfined aquifer with:

- fixed heads at both ends,
- uniform recharge,
- piecewise-constant hydraulic conductivity along `x`.

Intent:

- validate recharge together with heterogeneous `K` mapping,
- keep one analytical 1D benchmark where all conductivity jumps align with the mesh,
- extend the homogeneous recharge case without leaving the current launcher workflow.

Comparison:

- simulated observable: `watertable_elevation`
- compared quantity: domain-averaged head profile along `x`
- reference: steady 1D Boussinesq profile with uniform recharge and piecewise `K`

Direct execution:

```bash
python -m validation_cases.analytical.steady.boussinesq_uniform_recharge_piecewise_k_1d.run_case
python -m validation_cases.analytical.steady.boussinesq_uniform_recharge_piecewise_k_1d.run_case --solver boussinesq --show
```

The runner saves a PNG figure with:

- numerical mean profile as blue points,
- analytical profile as an orange line,
- a residual panel and a metrics summary box.

Solver variants:

- `modflownwt` and `modflow6` use the historical launcher-backed structured-grid setup,
- `boussinesq` uses a small triangular-strip bundle projected back to a regular
  `3 x 40` profile grid for plotting and metric comparison.
