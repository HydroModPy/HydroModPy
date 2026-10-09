# Set the depth of the aquifer and its layers

```{hmp-task}
Task
: Place the bottom of the aquifer, cut its thickness into layers, and let the conductivity fall with depth.

Time
: Fifteen minutes. The file below runs in about one minute on two cores.

Needs
: A model that runs. For a bottom that varies from place to place, a raster of the substratum elevation or of the aquifer thickness.

Gives
: An aquifer whose bottom, layers and conductivity profile you chose, and two sections to check them.
```

The top of the model is the ground. Its bottom, the substratum, is a choice you make with
{toml}`domain.depth_model`. Between the two, the aquifer is cut into one or more layers,
and each property can change with depth. This page sets the three in that order.

The worked case is example 04. Its files put the bottom 30 m under the ground, in one
layer, with one K. The file of this guide makes the aquifer 60 m thick, cuts it into four
layers that thicken with depth, and lets K fall with depth. It is merged onto
`step1_minimal.toml`. Its numbers complete the file; they are not a description of the
Nançon aquifer.

{download}`Download the file of this guide <recipes/model/guide_depth.toml>`.

## What you need first

- A model that runs.
- For a raster bottom: a GeoTIFF or an ASCII grid, in metres, that covers the whole domain
  of the model. Example 04 ships none, so step 2 shows what to provide.

## 1. Choose the depth model

{toml}`domain.depth_model.kind` takes one of four models:

| `kind` | The bottom is | Key |
|---|---|---|
| `constant_thickness` (default) | the ground minus one thickness | `thickness`, 50 m by default |
| `flat_substratum` | one elevation everywhere | `substratum_elevation` |
| `raster_thickness` | the ground minus the thickness read in a raster | `[data.substratum]`, `scale` |
| `raster_substratum` | the elevation read in a raster | `[data.substratum]` |

A constant thickness follows the relief: the bottom is a copy of the ground, lower. A flat
substratum is an absolute elevation: where the ground drops under it, no aquifer is left.

```toml
base_config = "step1_minimal.toml"

[simulation]
name = "nancon_guide_depth"

[domain.depth_model]
kind = "constant_thickness"
thickness = "60 m"
```

```{hmp-params}
domain.depth_model.kind
domain.depth_model.thickness
domain.depth_model.substratum_elevation
```

The thickness and the elevation can be calibrated: they are targets of
{doc}`calibrate`. A flat substratum is written the same way. Step 1 writes a `thickness`,
which a flat substratum refuses, so a file that inherits it deletes it:

```toml
base_config = "step1_minimal.toml"

[domain.depth_model]
kind = "flat_substratum"
substratum_elevation = "60 m"
thickness__delete = true
```

## 2. Read the bottom from a raster

The two raster models read the raster declared under `[data.substratum]`, exactly one
file. Its values are the substratum elevation for `raster_substratum`, on the datum of the
DEM, or the aquifer thickness for `raster_thickness`.

```toml
# not checked: names a raster that example 04 does not ship
base_config = "step1_minimal.toml"

[domain.depth_model]
kind = "raster_thickness"
min_thickness = "2 m"
thickness__delete = true

[[data.substratum.sources]]
source = "custom"
path = "substratum_custom_thickness.tif"
```

```{hmp-params}
data.substratum.sources.path
data.substratum.sources.default_crs
domain.depth_model.offset
domain.depth_model.min_thickness
domain.depth_model.scale
```

The raster is reprojected onto the grid of the ground. It must cover every cell of the
domain: the buffered box by default ({toml}`geographic.domain_extent`), or the catchment.
A raster without a CRS is read in {toml}`default_crs|data.substratum.sources.default_crs`,
Lambert-93 unless you set another. `offset` moves the whole bottom up or down, which is a
quick sensitivity test. Where the raster puts the bottom less than `min_thickness` under
the ground, the bottom is lowered to keep that thickness, and a warning counts the cells.

## 3. Cut the aquifer into layers

`[modflow6.sgrid.vertical]` cuts the thickness of every column into layers. One layer is
the default.

| `genmtd_lay` | The layers | Keys |
|---|---|---|
| `constant` (default) | `nlay` layers of equal thickness | `nlay` |
| `decay` | `nlay` layers that thicken with depth, by a factor above 1 | `nlay`, `lay_decay` |
| `list` | one layer per fraction you give, from the top | `lay_proportions`, summing to 1 |

The layers follow the ground and the bottom: a layer is a fraction of the local thickness,
not a fixed elevation. Thin top layers resolve the water table and the drains near the
surface, where the flow changes most.

```toml
base_config = "step1_minimal.toml"

[modflow6.sgrid.vertical]
genmtd_lay = "decay"
nlay = 4
lay_decay = 2.0
```

```{hmp-params}
modflow6.sgrid.vertical.genmtd_lay
modflow6.sgrid.vertical.nlay
modflow6.sgrid.vertical.lay_decay
modflow6.sgrid.vertical.lay_proportions
```

How the layer interfaces are placed is in {ref}`the layers section of the flow theory <gwf-layers>`.
A lake needs at least two layers, so that the aquifer stays active under it
({doc}`lakes-and-reservoirs`).

## 4. Let K change with depth

A depth factor multiplies the value of a property, whatever its zones. It sits in its own
table under the property. With `mode = "exponential"` the factor is $\exp(-d / d_c)$,
where $d$ is the depth of the centre of each layer below the top of the cell and $d_c$ the
{toml}`characteristic depth|flow.param.K.field_vertical_profile.characteristic_depth`.
It never goes below {toml}`min_factor|flow.param.K.field_vertical_profile.min_factor`
when you give one. The value you write for K is therefore its value at the surface.

```toml
base_config = "step1_minimal.toml"

[flow.param.K.field_vertical_profile]
mode = "exponential"
characteristic_depth = "20 m"
min_factor = 0.05
```

```{hmp-params}
flow.param.<id>.field_vertical_profile.mode
flow.param.<id>.field_vertical_profile.characteristic_depth
flow.param.<id>.field_vertical_profile.min_factor
```

`mode = "tabulated"` reads the factor from the lists `depths` and `factors` instead. With
one layer, the factor is taken at half the thickness. The Boussinesq solver has no layers
and takes the factor at the surface, so a profile changes nothing there.

## 5. Run it and look at the sections

::::{tab-set}

:::{tab-item} Command line
```bash
hmp run guide_depth.toml
hmp viz show @last parameter_section
```
:::

:::{tab-item} Python
```python
import hydromodpy as hmp

run = hmp.run("guide_depth.toml")
print(run.n_layers)
hmp.figure(run, "parameter_section", orientation="sn")
```
:::

::::

`cross_section` draws the ground, the water table, the layer interfaces and the bottom
along a line through the outlet. `parameter_section` colours the same section by K: the
four layers carry four values, 4.5e-5, 3.4e-5, 1.8e-5 and 5.5e-6 m/s from the top down,
for 5e-5 m/s written at the surface.

```{figure} /_static/figures/guides/depth-and-substratum/cross_section.webp
:alt: South to north section of the Nançon aquifer with four layers that thicken with depth and the water table near the top.

`cross_section` of the file of this guide, south to north through the outlet.
```

```{figure} /_static/figures/guides/depth-and-substratum/parameter_section.webp
:alt: The same section coloured by hydraulic conductivity, which falls from the top layer to the bottom layer.

`parameter_section` of the same run.
```

## Check that it worked

1. `run.n_layers` gives the layer count, and `cross_section` draws the interfaces.
2. The bottom on `cross_section` follows the ground for `constant_thickness`, and is flat
   for `flat_substratum`.
3. `parameter_section` shows K falling with depth when a profile is set.

## What can go wrong

| Symptom | Cause | Fix |
|---|---|---|
| `domain.depth_model kind = 'raster_thickness' reads the raster declared under [data.substratum]; declare it with one custom source.` | A raster model without its raster. | Write `[[data.substratum.sources]]`. |
| `The substratum raster leaves <n> of the <m> cells of the domain without a value.` | The raster does not cover the domain. | Extend the raster, or take a smaller {toml}`geographic.domain_extent`. |
| `The substratum raster sits within min_thickness=<x> m of the top on <n> of the <m> cells of the domain` (warning) | The raster puts the bottom too close to the ground. | Check the raster: a thickness read as an elevation gives this. |
| `The substratum raster sits within min_thickness of the top on every cell of the domain; no aquifer would remain.` | The same everywhere. Often a thickness raster under `raster_substratum`. | Take the kind that matches the values of the raster. |
| `A substratum raster was given, and depth_model kind 'constant_thickness' does not read one.` | `[data.substratum]` with a depth model that reads no raster. | Choose a raster kind, or remove the section. |
| `lay_decay must be > 1.0 when genmtd_lay='decay'` | A factor of 1 or less. | Give a factor above 1, or take `constant`. |
| `lay_proportions must sum to 1.0` | The fractions of a `list` do not add up. | Fix the fractions. |
| `domain.depth_model.thickness: Extra inputs are not permitted (input='30.0 m')` | A file that switches to another kind inherits the `thickness` of its base file. | Write `thickness__delete = true` under `[domain.depth_model]`. |

## Where to go next

- K and Sy per zone, which the depth factor multiplies: {doc}`k-per-zone`.
- The equations of the layers and of the depth factor: {doc}`../theory/groundwater-flow`.
- A fixed head along a side, which needs every cell of the side below it:
  {doc}`boundary-and-initial-conditions`.
- Every key of the depth model: {toml}`domain.depth_model`.
