# From a zone map to the cells

A property such as $K$ is given per zone of a map: geology classes, bands, rings, or the
zones of a raster. The solver needs one value per cell and per layer. This page gives
the rule that turns the first into the second, what that rule means for the
conductivity, and a worked example. How to give a value per zone is in
{doc}`../../guides/k-per-zone`.

::::{dropdown} Notation of this page
```{hmp-notation}
```
::::

(transfer-rule)=
## The rule

A parameter with one value is spread over every cell. A parameter that points to a zone
map through its `field_spatial_id` is mapped in three steps.

1. **Sample the cell.** Each cell $c$ is covered by a regular set of sample points,
   $n_s$ per axis of the cell. A point takes the zone that contains it.
2. **Count the zones.** $F_{c,z}$ is the share of the points of $c$ that fall in zone
   $z$, among the points that fall in a zone. A point outside every zone of a geology
   map or of a raster map is left out of the count.
3. **Average, then scale with depth.** The value of the cell in layer $j$ is

$$
u_{c,j} = f(d_j)\,\sum_{z} F_{c,z}\,v_z ,
\qquad \sum_z F_{c,z} = 1 ,
$$ (eq-cell-value)

with $v_z$ the value of zone $z$ and $f(d_j)$ the depth factor {eq}`eq-depth-factor` at
the depth of the middle of layer $j$. A parameter with one value $v$ gives
$u_{c,j} = f(d_j)\,v$.

$F_{c,z}$ is an estimate of the share of the area of $c$ that lies in $z$. Its
resolution is $1 / n_s^2$ of the cell: a zone that covers less than that may get no
point. The same rule applies to every property, $K$, $S_y$, $S_s$ or the porosity. The
two MODFLOW solvers apply it per layer; the Boussinesq solver applies it once, at the
depth $d = 0$, because it has one layer. In the code: `FieldParam.to_mesh_field`.

A zone of the map with no value in the parameter stops the run, with a message that
names the missing keys. A cell where no point falls in any zone gets
$\sum_z F_{c,z} = 0$, so a value of zero, and a zero $K$ on an active cell is refused.

(transfer-conductivity)=
## What the rule means for the conductivity

{eq}`eq-cell-value` is an arithmetic mean weighted by area. For a cell cut by two
zones, that mean is the right effective value for a flow parallel to the interface,
where the two parts carry water side by side. For a flow across the interface, where the
two parts are in series, the effective value is the harmonic mean, and for a random mix
of zones it lies between the two {cite:p}`renard1997`. The arithmetic mean is the upper
of these bounds. A cell that holds a thin layer of low $K$ across the flow therefore
conducts more in the model than in the ground.

Between two cells, the conductance {eq}`eq-conductance` joins the two cell values in
series. A contrast that follows the cell faces is represented in series; a contrast
inside a cell is represented in parallel.

(transfer-example)=
## A worked example

Three cells of a row, two zones, $v_A = 10^{-5}$ m/s and $v_B = 10^{-7}$ m/s, no depth
factor. The interface between the zones crosses the middle cell.

| Cell | $F_{c,A}$ | $F_{c,B}$ | $u_c$ by {eq}`eq-cell-value` | harmonic mean, for comparison |
|---|---|---|---|---|
| 1 | 1 | 0 | $1.0 \times 10^{-5}$ m/s | $1.0 \times 10^{-5}$ m/s |
| 2 | 0.5 | 0.5 | $5.05 \times 10^{-6}$ m/s | $1.98 \times 10^{-7}$ m/s |
| 3 | 0 | 1 | $1.0 \times 10^{-7}$ m/s | $1.0 \times 10^{-7}$ m/s |

For a flow along the row, across the interface, the middle cell conducts about 25 times
more than its harmonic mean. Refining the mesh at the interface, or aligning the cell
faces with it, removes the mixed cell.

```{eval-rst}
.. plot:: theory/figures/f2c_zones.py
   :alt: Nine square cells cut by a vertical zone boundary with their sample points, and the cell conductivity against the share of zone A.
   :caption: The example above, three rows of it, run through the code. Left: the sample
      points of each cell (:math:`n_s = 8` per axis, the default) take the colour of
      their zone, and :math:`F_{c,A}` counts them. Right: the value
      ``FieldParam.to_mesh_field`` gives each cell (dots) lies on the arithmetic mean;
      the harmonic mean (dashed) is the value for a flow across the boundary. Look at the
      middle cells: :math:`5.05 \times 10^{-6}` m/s against
      :math:`1.98 \times 10^{-7}` m/s.
```

## Assumptions

- A cell holds one value of each property per layer.
- The zone of a point is the zone of the map that contains it; the map is not smoothed.
- The depth factor is the same function in every zone.

## Limits

- **Arithmetic mean only.** The aggregation is `weighted_average`; no geometric or
  harmonic option exists.
- **A sampled share.** $F_{c,z}$ is counted on $n_s$ points per axis, not computed from
  the exact intersection of the cell and the zone.
- **Same rule on every grid.** A coarse structured grid and a fine irregular mesh mix the
  zones differently, so two runs that share a zone map do not share their cell values.
  Compare them on the same grid, or report the grid with the result.

## Parameters of this page

```{hmp-params}
flow.param.K.field.value
flow.param.K.field_vertical_profile.mode
data.geology.cell_samples_per_axis
domain.supports.<name>.default_cell_samples_per_axis
```

## Checked by

```{hmp-tested-by}
hydromodpy.spatial.field.core.field_param
hydromodpy.spatial.field.core.cell_sampling
hydromodpy.spatial.domain.spatial_support
hydromodpy.solver.field_property_mapping
```

## In the code

| What | Where |
|---|---|
| The weighted average and the depth factor | `hydromodpy/spatial/field/core/field_param.py` (`FieldParam.to_mesh_field`, `FieldParam.vertical_factor`) |
| The shares of each zone in a cell | `hydromodpy/spatial/domain/spatial_support.py` (`on_mesh`), `hydromodpy/spatial/field/geology/geology_field.py` (`GeologyField.on_mesh`) |
| The sample points of a cell | `hydromodpy/spatial/field/core/cell_sampling.py` (`sample_points_in_cell`) |
| Per layer, for MODFLOW | `hydromodpy/solver/modflow6/support/property_mapping.py`, `hydromodpy/solver/modflow_common/property_mapping.py` |
| Once, for Boussinesq | `hydromodpy/solver/boussinesq/property_mapping.py` |

## See also

- {doc}`../groundwater-flow`: the properties in the flow equation, and the depth factor.
- {doc}`../mesh`: the cells the values land on.
- {doc}`../../guides/k-per-zone`: give a value per zone.
