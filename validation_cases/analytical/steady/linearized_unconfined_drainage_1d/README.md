# Linearized Unconfined Drainage 1D

Steady synthetic groundwater-flow case used to validate HydroModPy's top
drainage boundary condition against a closed-form linearized 1D reference with:

- fixed heads on the west and east sides,
- uniform top drainage conductance applied everywhere,
- a flat drainage elevation below the simulated water table,
- a homogeneous unconfined aquifer interpreted around one reference thickness.

Intent:

- validate the `drainage` boundary-condition path with an analytical benchmark,
- keep drainage active everywhere so the reference stays closed-form,
- isolate one lightweight 1D equilibrium before tackling more complex seepage-face cases.

Comparison:

- simulated observable: `watertable_elevation`
- compared quantity: domain-averaged head profile along `x`
- reference: steady linearized unconfined profile with distributed top drainage

Direct execution:

```bash
python -m validation_cases.analytical.steady.linearized_unconfined_drainage_1d.run_case
```

The runner saves a PNG figure with:

- numerical mean profile as blue points,
- analytical profile as an orange line,
- a residual panel and a metrics summary box.
