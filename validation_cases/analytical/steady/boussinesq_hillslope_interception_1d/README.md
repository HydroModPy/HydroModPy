# Boussinesq Hillslope Interception 1D

Steady synthetic groundwater-flow case used to validate the seepage face of a
sloping hillslope where the water table reaches the land surface near the
outlet. Six solvers run it: the PETSc VI obstacle `flow/boussinesq` runtime, the
default local engine (`boussinesq_local`), and MODFLOW-NWT, MODFLOW 6 on a
structured grid, MODFLOW 6 on irregular triangles and MODFLOW 6 on their
Voronoi dual, which drain the land surface through a DRN.

Intent:

- validate the emergence/interception position on a topographic slope,
- keep a closed-form inland Boussinesq profile on the dry part of the hillslope,
- benchmark the hard surface-obstacle closure with a metric that remains
  physically meaningful for seepage onset.

Numerical setup:

- quasi-1D strip (`40 x 3`) with alternating triangle diagonals,
- linear topography descending from `10 m` to `5 m`,
- flat impermeable bottom at `0 m`,
- uniform recharge `2 mm/day`,
- homogeneous hydraulic conductivity `1e-4 m/s`,
- fixed head `5 m` on the east side,
- west side left as the natural divide/no-flow boundary.

The MODFLOW variants (`config_modflownwt.toml` and its overrides) put a DRN on
the land surface, as HydroModPy does for a drained hillslope. Its conductance is
`K * area / b` with `b = 1 m`, so the leakance is the same on every cell. The
surface is sampled at the cell centres (linear raster, 5.0625 m at the centre of
the last column), and the east head is the surface there. The two unstructured
variants read the triangle bundle built by `mesh_bundle.py` (586 triangles of
about 6 m, stored under `mesh_bundles/`; rebuild it with
`python -m validation_cases.analytical.steady.boussinesq_hillslope_interception_1d.mesh_bundle`)
and sample the surface from a 2.5 m raster, so that no flat strip lies along
the east face. Their reference is evaluated at each cell and averaged over the
same 10 m bins as the model.

A DRN has a finite conductance: the head stands above the surface by the head
that passes what the face drains, `(R + K S^2) b / K = 3.9e-4 m`. The clearance
check of those variants bounds that excess instead of the obstacle closure.

Comparison:

- simulated observable: `watertable_elevation`,
- reference: the exact steady free-boundary solution under Dupuit. Below the
  emergence point `x_e` the head is the land surface and seeps out; above it
  all the recharge flows through the aquifer and the water table meets the
  surface tangentially at `x_e` (322.4 m here),
- metrics: the head profile on every column, and the contact point, where the
  head comes within `5 cm` of the surface, read the same way on the model and
  on the reference (281.6 m here: the tangent contact starts 41 m upslope of
  `x_e` at that tolerance),
- sanity checks: no overshoot above topography (or, with a DRN, no more than the
  drain excess) and low cross-row spread,
- the solve starts from the outlet head over the whole hillslope, not from the
  answer.

Until 2026-10-09 the reference was the profile without the surface, crossed with
the topography (244.8 m). It ignores the seepage face: its dry heads sit 0.1 to
0.16 m above the exact ones.

Direct execution:

```bash
python -m validation_cases.analytical.steady.boussinesq_hillslope_interception_1d.run_case --solver boussinesq
python -m validation_cases.analytical.steady.boussinesq_hillslope_interception_1d.run_case --solver boussinesq --show
```

## Equations

The equations of the reference solution the comparison uses.

$$
R\left(x_e-x_{\min}\right)=K\,S\left(z_{\mathrm{top}}(x_e)-z_b\right),\qquad z_{\mathrm{top}}(x)=z_{\mathrm{toe}}+S\left(L-x\right)
$$

$$
\left(h-z_b\right)^2=\left(z_{\mathrm{top}}(x_e)-z_b\right)^2+\frac{R}{K}\left[\left(x_e-x_{\min}\right)^2-\left(x-x_{\min}\right)^2\right]\quad (x<x_e),\qquad h=z_{\mathrm{top}}\quad (x\ge x_e)
$$
