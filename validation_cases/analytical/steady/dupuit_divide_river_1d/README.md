# Dupuit Divide-River 1D

Steady synthetic groundwater-flow case used to validate the launcher workflow
against the Dupuit analytical profile for a homogeneous unconfined aquifer with:

- a hydrologic divide on the west side (implicit no-flow),
- a fixed head on the east side,
- uniform recharge over the domain.

Intent:

- validate one explicit no-flow side boundary through a simple 1D benchmark,
- keep a clear analytical reference while extending beyond the two-head case.

Comparison:

- simulated observable: `watertable_elevation`
- compared quantity: domain-averaged head profile along `x`
- reference: steady Dupuit profile with west-side divide and east-side river head

Direct execution:

```bash
python -m validation_cases.analytical.steady.dupuit_divide_river_1d.run_case
```

The runner saves a PNG figure with:

- numerical mean profile as blue points,
- analytical Dupuit profile as an orange line,
- a residual panel and a metrics summary box.
