# XT3D on irregular meshes

The two-point flux of {eq}`eq-cell-balance` is exact when the line between two cell centers is
perpendicular to the shared face and the conductivity is the same in every horizontal
direction. On irregular cells it is not. XT3D {cite:p}`provost2017` is the correction MODFLOW 6
offers, and this page gives the rule that turns it on. The angle of a connection is defined on
{ref}`mesh-angle`.

::::{dropdown} Notation of this page
```{hmp-notation}
```
::::

(xt3d-error)=
## The error of the two-point flux

For an isotropic conductivity, the flux through the face shared by cells $n$ and $m$ is
$\mathbf{n}_{nm}\cdot\mathbf{q} = -K\,\mathbf{n}_{nm}\cdot\nabla h$. Write the unit vector of
the connection, $\hat{\mathbf d}_{nm} = \mathbf{d}_{nm} / \lVert\mathbf{d}_{nm}\rVert$, as
$\cos\varphi_{nm}\,\mathbf{n}_{nm} + \sin\varphi_{nm}\,\mathbf{t}_{nm}$, where $\mathbf{t}_{nm}$
is the unit vector along the face. Then

$$
\mathbf{n}_{nm}\cdot\nabla h
= \frac{\hat{\mathbf d}_{nm}\cdot\nabla h}{\cos\varphi_{nm}}
- \tan\varphi_{nm}\;\mathbf{t}_{nm}\cdot\nabla h .
$$ (eq-xt3d-split)

The heads $h_n$ and $h_m$ give the first term only. The conductance $G_{nm}$ keeps it and drops
the second, the head gradient along the face times $\tan\varphi_{nm}$. This share is zero on an
orthogonal connection, 0.27 of the tangential gradient at 15 degrees, 0.58 at 30 degrees and 1
at 45 degrees. A conductivity with two different horizontal values adds a similar term where its
axes do not follow the connections, even on an orthogonal grid. The vertical $K_z$ follows the
layers and needs no XT3D.

(xt3d-correction)=
## What XT3D computes

XT3D writes the flux through each face with the full head gradient, estimated from the heads of
both cells and of their neighbors. The tangential term is then in the balance. The price is a
wider stencil and a matrix that is not symmetric, so HydroModPy promotes a `SIMPLE` IMS preset
to `COMPLEX` ({ref}`solvers-newton-ims`). On the validation case `dupuit_uniform_recharge_1d`
run on irregular triangles, the head RMSE falls from 0.211 m to 0.0077 m, a factor of 27.

```{eval-rst}
.. plot:: theory/figures/xt3d_error.py
   :alt: The dropped share tan phi against the connection angle, and the head errors with and without XT3D.
   :caption: Left: the share :math:`\tan\varphi_{nm}` of :eq:`eq-xt3d-split`, with the 30°
      angle of the rule below. Right: the head errors of the golden reference of the case.
```

(xt3d-rule)=
## When HydroModPy turns it on

The code decides once per run and takes the first row of this table that fits.

| Case | XT3D | Why |
|---|---|---|
| {toml}`modflow6.runtime.mf6_enable_xt3d` is `true` or `false` | as written | your value wins. `false` against a tensor row below raises a `RuntimeWarning`, any other disagreement logs a warning |
| `angle2` or `angle3` not zero on a cell | on, with a `RuntimeWarning` | MODFLOW 6 reads these angles only under XT3D |
| `K22` different from $K$ on a cell whose `angle1` is not a multiple of 90 degrees, or on any cell of an unstructured mesh | on, with a `RuntimeWarning` | the axes of the tensor leave the connections |
| Structured grid | off | the connections are orthogonal and follow the axes |
| Triangle cells | on | the flux between the vertex means of two triangles is not consistent, whatever the angle |
| More than 5 % of the connections, or the 95th percentile of $\varphi_{nm}$, above 30 degrees | on | the dropped term reaches 0.58 of the tangential gradient |
| Otherwise | off | the dropped term is small |

The two tensor rows come first ({ref}`gwf-tensor`), because their error does not shrink with
refinement. Take a steady well with $K_{22} = K/10$ and `angle1` at 30 degrees on a structured
grid. The head error is 2.2 m for a 7 m drawdown, with cells of 40 m and of 20 m. With XT3D it
is 0.04 m, then 0.013 m. XT3D costs from about 1.5 times the MODFLOW 6 run time on one layer
to about 10 times on ten layers, and the `RuntimeWarning` says so. The code also writes the warning to the log. Setting
`mf6_enable_xt3d = true` keeps XT3D on without the warning. The triangle and non-orthogonality
rows only log at INFO level, with no warning.

The Voronoi cells of the `voronoi` engine are orthogonal by construction ({ref}`mesh-voronoi`),
so XT3D stays off there when `K22` equals $K$.

## The same case on two grids

```{image-comparison}
:before: /_static/theory/solvers/xt3d/circular_island_structured_dis.png
:after: /_static/theory/solvers/xt3d/circular_island_irregular_disv.png
:before-label: Structured DIS
:after-label: Irregular triangles, XT3D on
:before-alt: The circular-island case on a structured grid
:after-alt: The same case on irregular triangles with XT3D
:caption: The circular-island case on two MODFLOW 6 grids. Drag the handle to compare. The connections of the triangles are not perpendicular to the faces, so XT3D is on.
```

## Assumptions

- The conductivity is isotropic in the horizontal plane unless the flow sets `K22` or the
  angles.
- The code measures the angle of a connection in the plan. The layers are an extrusion, so the
  vertical connections are orthogonal.

## Limits

- XT3D exists in MODFLOW 6 only. MODFLOW-NWT runs on structured grids, and the Boussinesq solver
  has no correction for skewed cells.
- Any `K22` on an unstructured mesh turns XT3D on, even if the connections happen to follow the
  axes of the tensor.
- Every run of a sweep near the trigger pays for the wider stencil.
- On triangle cells under Newton, XT3D can cycle without converging. MODFLOW 6 scales the XT3D
  face area by the saturation of the upstream cell, but the cross term of XT3D is not zero at
  equal heads, so the discrete system can have no root. The steady state of the Nançon on
  triangles stops with E401 this way, in MODFLOW 6.6.3 and 6.8.1, and ghost nodes (GNC) do not
  converge either. The build warns about it. The `voronoi` engine needs no XT3D and converges on
  the same inputs. With `mf6_enable_xt3d = false` the run converges too, with heads about 0.1 m
  RMSE away from XT3D.

## Parameters of this page

```{hmp-params}
modflow6.runtime.mf6_enable_xt3d
mesh.engine
modflow6.runtime.mf6_ims_complexity
flow.param.K22.field.value
flow.param.angle1.field.value
flow.param.angle2.field.value
```

## Checked by

```{hmp-tested-by}
hydromodpy.solver.modflow6.builders.solver_options
hydromodpy.mesh.planar.quality
```

## In the code

| What | Where |
|---|---|
| The rule and its limits | `hydromodpy/solver/modflow6/builders/solver_options.py` (`resolve_xt3d_decision`, `_recommend_xt3d`, `k_tensor_is_tilted`, `k_tensor_is_off_axis`, `_NONORTH_FRAC_GT30_TRIGGER`, `_NONORTH_P95_TRIGGER_DEG`) |
| The angle of each connection | `hydromodpy/mesh/planar/quality.py` (`connection_nonorthogonality_deg`, `nonorthogonality_summary`) |
| The IMS promotion | `solver_options.py` (`resolve_ims_complexity`) |
| The regression with and without XT3D | `tests/regression/fast/intercomparison/test_xt3d_irregular_tri_fast_regression.py` |

## See also

- {doc}`../mesh`: the mesh engines, the Voronoi cells and the angle of a connection.
- {doc}`../solvers`: the packages MODFLOW 6 writes.
- {doc}`../../reference/cli/report`: `hmp report compare`, a run with XT3D against one without.
