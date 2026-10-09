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
- boundary positions: each side head is posed where the model holds it, at the
  centre of the boundary column, or at the mean centroid of the boundary
  triangles on the triangle strip; a no-flow side stays on the domain face
  (`validation_cases/shared/strip_geometry.py`)

Direct execution:

```bash
python -m validation_cases.analytical.steady.dupuit_uniform_recharge_1d.run_case
```

The runner saves a PNG figure with:

- numerical mean profile as blue points,
- analytical Dupuit profile as an orange line,
- a residual panel and a metrics summary box.

## Equations

The equations of the reference solution the comparison uses.

$$
\frac{\mathrm{d}}{\mathrm{d}x}\left(K\,h\,\frac{\mathrm{d}h}{\mathrm{d}x}\right)+R=0
$$

$$
h(x)^2=h_w^2+\left(h_e^2-h_w^2\right)\frac{\xi}{L}+\frac{R}{K}\,\xi\left(L-\xi\right),\quad \xi=x-x_{\min}
$$
