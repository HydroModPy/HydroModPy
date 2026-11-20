# Dupuit Fixed-Head 1D

Steady synthetic groundwater-flow case used to validate the launcher workflow
against the Dupuit analytical profile for an unconfined aquifer with fixed
heads at both ends.

Intent:

- check that the end-to-end launcher workflow reproduces the expected head
  profile on a simple homogeneous domain,
- keep one lightweight, deterministic benchmark for future validation cases.

Comparison:

- simulated observable: `watertable_elevation`
- compared quantity: domain-averaged head profile along `x`
- reference: Dupuit steady fixed-head solution
- boundary positions: each side head is posed where the model holds it, at the
  center of the boundary column, or at the mean centroid of the boundary
  triangles on the triangle strip, or on the face on the Voronoi dual, whose
  cells are seeded on the face; a no-flow side stays on the domain face
  (`validation_cases/shared/strip_geometry.py`)
- Voronoi dual: one cell per node of the triangle strip, read at its node and
  binned by area-weighted mean into the same 40 columns as the reference
- configured solver variants: `modflownwt` (default), `modflow6`,
  `modflow6_irregular_tri` (triangle strip), `modflow6_voronoi` (its Voronoi dual),
  Linux-only PETSc `boussinesq` VI obstacle, Linux-only `petsc`
  complementarity, and Linux-only `petsc_partition` regularized partition.

Solver-specific tolerances are stored in:

- `tolerances.toml` for the structured grid, shared by `modflownwt` and `modflow6`,
- `tolerances_modflow6_irregular_tri.toml` for the triangle strip,
- `tolerances_modflow6_voronoi.toml` for the Voronoi dual of the triangle strip,
- `tolerances_boussinesq.toml` for the PETSc Boussinesq strip,
- `tolerances_petsc_vi_obstacle.toml` for the PETSc Boussinesq VI obstacle variant,
- `tolerances_petsc.toml` for the Linux PETSc Boussinesq complementarity variant,
- `tolerances_petsc_partition.toml` for the Linux PETSc regularized partition variant.

Direct execution:

```bash
python -m validation_cases.analytical.steady.dupuit_fixed_head_1d.run_case --show
python -m validation_cases.analytical.steady.dupuit_fixed_head_1d.run_case --solver modflow6 --no-show
python -m validation_cases.analytical.steady.dupuit_fixed_head_1d.run_case --solver boussinesq --no-show
python -m validation_cases.analytical.steady.dupuit_fixed_head_1d.run_case --solver petsc --no-show
python -m validation_cases.analytical.steady.dupuit_fixed_head_1d.run_case --solver petsc_partition --no-show
```

The PETSc-backed `boussinesq`, `petsc`, and `petsc_partition` variants require
Linux with `petsc4py` installed.

The runner saves a PNG figure with:

- numerical mean profile as blue points,
- analytical Dupuit profile as an orange line,
- a residual panel and a metrics summary box.

## Equations

The equations of the reference solution the comparison uses.

$$
\frac{\mathrm{d}}{\mathrm{d}x}\left(K\,h\,\frac{\mathrm{d}h}{\mathrm{d}x}\right)=0
$$

$$
h(x)=\sqrt{h_w^2+\left(h_e^2-h_w^2\right)\frac{x-x_{\min}}{x_{\max}-x_{\min}}}
$$
