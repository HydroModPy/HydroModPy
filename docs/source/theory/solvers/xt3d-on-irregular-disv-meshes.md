# XT3D on irregular meshes

The two-point flux of {eq}`eq-cell-balance` is exact on a grid whose connections are
perpendicular to the faces, for a conductivity that is the same in every horizontal
direction. On irregular cells it is not. This page gives the error, the correction
MODFLOW 6 offers for it, XT3D {cite:p}`provost2017`, and the rule HydroModPy follows to
turn it on. The angle of a connection is defined on {ref}`mesh-angle`.

::::{dropdown} Notation of this page
```{hmp-notation}
```
::::

(xt3d-error)=
## The error of the two-point flux

The flux through the face shared by cells $n$ and $m$ is the component of the Darcy flux
along the normal of the face, $\mathbf{n}_{nm}\cdot\mathbf{q} = -K\,\mathbf{n}_{nm}\cdot\nabla h$
for an isotropic conductivity. Write the unit vector of the connection,
$\hat{\mathbf d}_{nm} = \mathbf{d}_{nm} / \lVert\mathbf{d}_{nm}\rVert$, as
$\cos\varphi_{nm}\,\mathbf{n}_{nm} + \sin\varphi_{nm}\,\mathbf{t}_{nm}$, with
$\mathbf{t}_{nm}$ the unit vector along the face. Then

$$
\mathbf{n}_{nm}\cdot\nabla h
= \frac{\hat{\mathbf d}_{nm}\cdot\nabla h}{\cos\varphi_{nm}}
- \tan\varphi_{nm}\;\mathbf{t}_{nm}\cdot\nabla h .
$$ (eq-xt3d-split)

The two heads $h_n$ and $h_m$ give the first term only, through
$\hat{\mathbf d}_{nm}\cdot\nabla h \approx (h_m - h_n) / \lVert\mathbf{d}_{nm}\rVert$. The
two-point conductance $G_{nm}$ keeps that term and drops the second. The dropped term is
the head gradient along the face times $\tan\varphi_{nm}$: zero on an orthogonal
connection, 0.27 of the tangential gradient at 15 degrees, 0.58 at 30 degrees, 1 at 45
degrees. A conductivity that differs between two horizontal directions, or whose axes
are turned, adds a term of the same kind, $\mathbf{n}_{nm}\cdot\mathbf{K}\nabla h \ne
K\,\mathbf{n}_{nm}\cdot\nabla h$, even on an orthogonal grid.

(xt3d-correction)=
## What XT3D computes

XT3D writes the flux through the face with the full gradient and the full tensor,

$$
\Phi_{nm} = -\,w_{nm}\,B_{nm}\;\mathbf{n}_{nm}\cdot\mathbf{K}\,\nabla h ,
$$ (eq-xt3d-flux)

with $B_{nm}$ the saturated thickness at the face. It estimates $\nabla h$ in each of the
two cells from the heads of the cell and of its neighbours, and joins the two estimates
so that the normal flux is continuous across the face {cite:p}`provost2017`. The
tangential term of {eq}`eq-xt3d-split` is then in the balance. The price is a wider
stencil: the flux of one face depends on the heads of the neighbours of both cells, so
the matrix has more entries and is no longer symmetric.

On the validation case `dupuit_uniform_recharge_1d` run on irregular triangles, the
golden reference of the regression test `test_xt3d_irregular_tri_fast_regression` records
a head RMSE of 0.238 m without XT3D and 0.035 m with it, a factor of 6.7. The test fails
if the factor falls below 5 or the RMSE with XT3D rises above 0.05 m.

```{eval-rst}
.. plot:: theory/figures/xt3d_error.py
   :alt: The dropped share tan phi against the connection angle, and the head errors with and without XT3D.
   :caption: Left: the share of the tangential gradient that the two-point flux drops,
      :math:`\tan\varphi_{nm}` from :eq:`eq-xt3d-split`, with the 30° angle of the rule
      below. Right: the head errors of the golden reference, read from the test folder at
      build time. Look at the RMSE: 0.238 m without XT3D, 0.035 m with it.
```

(xt3d-rule)=
## When HydroModPy turns it on

The code decides once per run, in this order:

| Case | XT3D | Why |
|---|---|---|
| {toml}`modflow6.runtime.mf6_enable_xt3d` is `true` or `false` | as written | your value wins; the code logs a warning when the checks below disagree |
| Structured grid | off | the connections are orthogonal and the conductivity isotropic |
| Horizontal conductivity anisotropic or turned | on | the tensor term of {ref}`xt3d-error` |
| More than 5 % of the connections above 30 degrees, or a 95th percentile of $\varphi_{nm}$ above 30 degrees | on | the dropped term reaches 0.58 of the tangential gradient on a share of the faces |
| Otherwise | off | the dropped term stays small, XT3D would add cost only |

The two limits are the constants `_NONORTH_FRAC_GT30_TRIGGER` and
`_NONORTH_P95_TRIGGER_DEG`. The anisotropy row does not fire today: the `NPF` package
receives only a horizontal $K$ and a vertical $K_z$, so the horizontal plane is
isotropic. The default Voronoi dual of a Gmsh mesh is orthogonal by construction
({ref}`mesh-voronoi`), so XT3D stays off there; the triangles kept as cells with
{toml}`modflow6.sgrid.grid_dual` are the usual case where it turns on.

When XT3D is on, a `SIMPLE` IMS preset is promoted to `COMPLEX`, because `SIMPLE`
assumes a symmetric matrix ({ref}`solvers-newton-ims`). In the code:
`resolve_xt3d_decision`.

## The same case on two grids

The circular-island validation case on a structured `DIS` grid (left) and on irregular
triangles (right), where the rule above turns XT3D on. Drag the handle to compare.

```{image-comparison}
:before: /_static/theory/solvers/xt3d/circular_island_structured_dis.png
:after: /_static/theory/solvers/xt3d/circular_island_irregular_disv.png
:before-label: Structured DIS
:after-label: Irregular triangles, XT3D on
:before-alt: Structured DIS rendering of the circular-island case
:after-alt: Irregular triangle rendering of the same case with XT3D enabled
:caption: One case, two MODFLOW 6 grids. On the triangles the connections are not perpendicular to the faces, which is what turns XT3D on.
```

## Assumptions

- The conductivity is isotropic in the horizontal plane. The vertical one is aligned with
  the layers and needs no XT3D.
- The angle of a connection is measured in the plan; the layers are an extrusion, so the
  vertical connections are orthogonal.

## Limits

- **MODFLOW 6 only.** MODFLOW-NWT runs on structured grids only. The Boussinesq solver
  has no correction for skewed cells.
- **No horizontal anisotropy input.** The anisotropy branch of the rule is ready and
  never fires.
- **Cost.** XT3D widens the stencil and makes the matrix non-symmetric. On a mesh near
  the trigger, a sweep of many runs pays for it on every run.

## Parameters of this page

```{hmp-params}
modflow6.runtime.mf6_enable_xt3d
modflow6.sgrid.grid_dual
modflow6.runtime.mf6_ims_complexity
```

## Checked by

```{hmp-tested-by}
hydromodpy.solver.modflow6.builders.solver_options
hydromodpy.spatial.mesh.ops.mesh_orthogonality
```

## In the code

| What | Where |
|---|---|
| The rule, its constants | `hydromodpy/solver/modflow6/builders/solver_options.py` (`resolve_xt3d_decision`, `_recommend_xt3d`) |
| The angle of each connection | `hydromodpy/spatial/mesh/ops/mesh_orthogonality.py` (`connection_nonorthogonality_deg`, `nonorthogonality_summary`) |
| The IMS promotion | `solver_options.py` (`resolve_ims_complexity`) |
| The regression with and without XT3D | `tests/regression/fast/intercomparison/test_xt3d_irregular_tri_fast_regression.py` |

## See also

- {doc}`../mesh`: the cells, the Voronoi dual and the angle of a connection.
- {doc}`../solvers`: the packages MODFLOW 6 writes.
- {doc}`../../reference/parameters/analysis/comparison`: compare a run with XT3D and one without.
