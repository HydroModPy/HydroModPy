# Boussinesq Fixed-Head Piecewise-K 1D

Steady synthetic groundwater-flow case used to validate the launcher workflow
against the exact 1D Boussinesq solution written on `U = h^2` for an
unconfined aquifer with:

- fixed heads at both ends,
- no recharge,
- piecewise-constant hydraulic conductivity along `x`.

Intent:

- validate heterogeneous `K` mapping on a simple 1D support,
- check flux continuity across conductivity jumps,
- keep a lightweight analytical benchmark for future heterogeneous cases.

Comparison:

- simulated observable: `watertable_elevation`
- compared quantity: domain-averaged head profile along `x`
- reference: steady 1D Boussinesq profile with piecewise-constant `K`

Direct execution:

```bash
python -m validation_cases.analytical.steady.boussinesq_fixed_head_piecewise_k_1d.run_case
```

The runner saves a PNG figure with:

- numerical mean profile as blue points,
- analytical profile as an orange line,
- a residual panel and a metrics summary box.
