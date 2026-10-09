# Linearized Unconfined Boundary Piecewise 1D

Transient synthetic groundwater-flow case used to validate the launcher workflow
against the linearized unconfined analytical response for:

- a west-side Dirichlet boundary varying as a piecewise-constant series,
- a fixed east-side head,
- no recharge,
- a homogeneous 1D aquifer.

Intent:

- validate multi-step lateral boundary forcing through the launcher-managed CSV forcing path,
- exercise analytical superposition beyond the single-step benchmark,
- keep one compact transient 1D case where the reference remains closed-form.

Comparison:

- simulated observable: `watertable_elevation`
- compared quantity: full transient head profile matrix along `x`
- reference: linearized 1D unconfined response to a piecewise west-boundary series
- boundary positions: each side head is posed where the model holds it, at the
  centre of the boundary column, or at the mean centroid of the boundary
  triangles on the triangle strip; a no-flow side stays on the domain face
  (`validation_cases/shared/strip_geometry.py`)

Direct execution:

```bash
python -m validation_cases.analytical.transient.linearized_unconfined_boundary_piecewise_1d.run_case
```

The runner saves a PNG figure with:

- selected analytical and numerical profiles through time,
- monitor-point time series,
- a residual heatmap and summary metrics.

## Equations

The equations of the reference solution the comparison uses.

$$
S_y\frac{\partial \eta}{\partial t}=T_0\frac{\partial^2 \eta}{\partial x^2},\qquad \eta(L,t)=0
$$

$$
\eta(x,t)=\sum_k \Delta h_k\,\eta_{\mathrm{step}}(x,t-t_k)\,H(t-t_k)
$$
