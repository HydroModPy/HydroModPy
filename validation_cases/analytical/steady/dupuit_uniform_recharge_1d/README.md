# Dupuit Uniform Recharge 1D

Steady synthetic groundwater-flow case used to validate the launcher workflow
against the Dupuit analytical profile for a homogeneous unconfined aquifer with
uniform recharge and fixed heads at both ends.

Intent:

- validate uniform recharge in a case still compatible with the current
  free-surface / convertible aquifer implementation,
- keep the geometry one-dimensional so that the comparison stays robust.

Comparison:

- simulated observable: `watertable_elevation`
- compared quantity: domain-averaged head profile along `x`
- reference: steady Dupuit profile with uniform recharge

Direct execution:

```bash
python -m validation_cases.analytical.steady.dupuit_uniform_recharge_1d.run_case
```

The runner saves a PNG figure with:

- numerical mean profile as blue points,
- analytical Dupuit profile as an orange line,
- a residual panel and a metrics summary box.
