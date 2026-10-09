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
- boundary positions: each side head is posed where the model holds it, at the
  centre of the boundary column, or at the mean centroid of the boundary
  triangles on the triangle strip; a no-flow side stays on the domain face
  (`validation_cases/shared/strip_geometry.py`)

Direct execution:

```bash
python -m validation_cases.analytical.steady.boussinesq_fixed_head_piecewise_k_1d.run_case
python -m validation_cases.analytical.steady.boussinesq_fixed_head_piecewise_k_1d.run_case --solver boussinesq --show
```

The runner saves a PNG figure with:

- numerical mean profile as blue points,
- analytical profile as an orange line,
- a residual panel and a metrics summary box.

Solver variants:

- `modflownwt` and `modflow6` use the historical launcher-backed structured-grid setup,
- `boussinesq` uses a small triangular-strip bundle projected back to a regular
  `3 x 40` profile grid for plotting and metric comparison.

## Equations

The equations of the reference solution the comparison uses.

$$
U=h^2,\qquad \frac{\mathrm{d}}{\mathrm{d}x}\left(K(x)\,\frac{\mathrm{d}U}{\mathrm{d}x}\right)=0
$$

$$
U(x)=h_w^2+\left(h_e^2-h_w^2\right)\frac{\int_{x_{\min}}^{x}\frac{\mathrm{d}s}{K(s)}}{\int_{x_{\min}}^{x_{\max}}\frac{\mathrm{d}s}{K(s)}}
$$
