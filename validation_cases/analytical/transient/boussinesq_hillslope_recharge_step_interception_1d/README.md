# Boussinesq Hillslope Recharge-Step Interception 1D

Transient synthetic groundwater-flow case used to validate a sloping hillslope
where a recharge step causes an interception zone to appear progressively from
the outlet toward the divide. Six solvers run it: the in-house `flow/boussinesq`
runtime (PETSc TS VI obstacle) and its default local engine
(`boussinesq_local`), and MODFLOW-NWT, MODFLOW 6 on a structured grid, on
irregular triangles and on their Voronoi dual, which drain the land surface
through a DRN.

Intent:

- validate the transient onset of interception on a topographic slope,
- compare the **time of first inland interception** against a linearized
  approximation,
- compare the discrete interception trajectory `x_int(t)` on the early-moving
  front where the approximation remains informative.

Numerical setup:

- same sloping strip geometry as the steady interception benchmark (`40 x 3`),
- linear topography from `10 m` to `5 m`,
- flat bottom at `0 m`,
- initial state: constant head `5 m`,
- east fixed head `5 m`,
- recharge step to `2 mm/day` from the first transient period,
- `12` periods of `10 days`.

The MODFLOW variants (`config_modflownwt.toml` and its overrides) put a DRN on
the land surface (conductance `K * area / b`, `b = 1 m`). Their surface is the
toe elevation, 5 m, at the cell that holds the outlet head (the center of the
last column, `x = 395 m`, on the structured grids), so the toe is in contact from
the start and the front moves inland from there. The two unstructured variants
read the triangle bundle of the steady interception case
(`../../steady/boussinesq_hillslope_interception_1d/mesh_bundles`) and sample the
surface from a 2.5 m raster. Their reference is evaluated at each cell and
averaged over the same 10 m bins as the model. A launcher run stores the state at
the stamp that closes each period, so the period `n` is read at `n * 10 days`. In
the 120 days the head stays below the surface, so the DRN never acts and its
finite conductance, which would hold the head `3.9e-4 m` above the surface (see
the steady case), does not enter.

Reference:

- linearized unconfined response around `H0 = 5 m`,
- west divide / east fixed-head mixed boundary conditions,
- the analytical approximation is used only for interception onset and early
  trajectory diagnostics, not as an exact post-interception free-boundary
  solution.

Compared metrics:

- onset-time error for the first inland contact,
- RMSE / max error of the discrete interception trajectory,
- monotonic inland migration of the numerical front,
- no positive overshoot above topography,
- low cross-row spread.

Direct execution:

```bash
python -m validation_cases.analytical.transient.boussinesq_hillslope_recharge_step_interception_1d.run_case --solver boussinesq
python -m validation_cases.analytical.transient.boussinesq_hillslope_recharge_step_interception_1d.run_case --solver boussinesq --show
```

Reference used by the documentation:

- reference: linearized unconfined response around `H0 = 5 m`, used for the onset time and the early trajectory of the interception front only

## Equations

The equations of the reference solution the comparison uses.

$$
S_y\frac{\partial \eta}{\partial t}=T_0\frac{\partial^2 \eta}{\partial x^2}+R_0\,H(t),\qquad \eta_{\mathrm{steady}}(x)=\frac{R_0}{2T_0}\left(L^2-x^2\right)
$$

$$
z_{\mathrm{top}}(x)=z_{\mathrm{toe}}+S\left(L-x\right),\qquad h(x,t)=z_{\mathrm{top}}(x)\ \text{defines the interception front}
$$
