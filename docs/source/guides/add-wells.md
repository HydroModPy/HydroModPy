# Add a pumping well

```{hmp-task}
Task
: Take water out of the aquifer, or put it in, at a point and at a rate you give.

Time
: Ten minutes to write. The run of the file below takes about one minute on two cores.

Needs
: A model that runs, the coordinates of the well in the project CRS, and its rate.

Gives
: The heads with the drawdown of the well, and the pumped volume in the water budget.
```

A well is a source or a sink in one cell of the model. You give where it is and how much it
pumps; the solver gives the drawdown. A negative rate pumps water out, a positive rate
injects it. MODFLOW 6 and MODFLOW-NWT write a WEL package, and the Boussinesq solver takes
wells placed by coordinates.

The worked case is example 04. The blocks below are merged onto its
`step1_minimal.toml`, a steady model of the Nançon catchment, and add one well near the
middle of the catchment. The position and the rate are there to make the file complete:
they describe no real borehole.

{download}`Download the file of this guide <recipes/model/guide_wells.toml>`. Save it in the
folder of example 04, next to `step1_minimal.toml`.

## What you need first

- A model that runs. For a rate that changes with time, a transient model such as
  `step4_transient.toml`.
- The well position, as x and y in the CRS of the project ({toml}`geographic.crs_project`,
  EPSG:2154 for example 04), and the layer it draws from when the model has several.
- The rate, in m3/s unless you say otherwise.

## 1. Switch the wells on

A well table does nothing until `"wells"` is in {toml}`flow.active_sinks_sources`. A list in
a file replaces the inherited one, so write `"recharge"` again:

```toml
base_config = "step1_minimal.toml"

[flow]
active_sinks_sources = ["recharge", "wells"]
```

```{hmp-params}
flow.active_sinks_sources
```

## 2. Declare the well

Each well is a table under {toml}`flow.sinks_sources.wells`, named by an id you choose.
It takes a rate and a location.

```toml
base_config = "step1_minimal.toml"

[simulation]
name = "nancon_guide_wells"

[flow]
active_sinks_sources = ["recharge", "wells"]

[flow.sinks_sources.wells.W1]
flux = -0.0116
description = "About 1000 m3/day"

[flow.sinks_sources.wells.W1.location]
kind = "absolute_xy"
x = 391460.0
y = 6821060.0
```

`flux = -0.0116` is 0.0116 m3/s pumped out, about 1000 m3/day. The location takes one of
three kinds:

| `kind` | You write | Works on |
|---|---|---|
| `absolute_xy` | `x` and `y` in the project CRS | every grid |
| `relative_xy` | `x_rel` and `y_rel`, from 0 to 1 across the model extent, west to east and south to north | every grid |
| `cell` | `cell = [layer, row, column]`, counted from 0 | the structured grid only |

A coordinate falls in the cell that holds it. A well draws from the top layer unless its
location names another one.

```{hmp-params}
flow.sinks_sources.wells.<name>.flux
flow.sinks_sources.wells.<name>.location
flow.sinks_sources.wells.<name>.description
```

To give the rate in another unit, set `units` on the well, for example
`units = "m3/day"` with `flux = -1000.0`. The rate is converted to m3/s when the run
starts.

## 3. Give a rate that changes with time

A transient model takes a rate per stress period. Write `flux` as a list with one value
per period, or as one number for all of them. A list of another length stops the run.

For a schedule, a `forcing` table replaces `flux`. It is `constant`, `csv`, `piecewise` or
`seasonal`, chosen by `kind`. This block pumps more in summer than in winter, on the
monthly transient model of step 4:

```toml
base_config = "step4_transient.toml"

[flow]
active_sinks_sources = ["recharge", "wells"]

[flow.sinks_sources.wells.W1]
units = "m3/day"

[flow.sinks_sources.wells.W1.location]
kind = "absolute_xy"
x = 391460.0
y = 6821060.0

[flow.sinks_sources.wells.W1.forcing]
kind = "seasonal"
by_season = { DJF = -200.0, MAM = -600.0, JJA = -1500.0, SON = -800.0 }
```

A `seasonal` forcing needs all four seasons, or all twelve months with `by_month`. A `csv`
forcing reads a chronicle file, `path_file`, with a `date` column and a `value` column,
and averages it over each stress period. A well takes `flux` or `forcing`, never both.

## 4. Run it and look at the drawdown

The file of this guide adds three figures, a map with the well on it, a section through
the well and the water budget. The well marker is drawn from the per-cell well flux, which
the run stores only when {toml}`simulation.results.budget.spatial_fields` is on.

```toml
base_config = "step1_minimal.toml"

[simulation.results.budget]
spatial_fields = true

[display]
figures = ["watertable_depth_map", "cross_section", "water_budget"]

[display.overrides.watertable_depth_map]
overlays = ["watershed", "wells", "outlet"]

[display.overrides.cross_section]
orientation = "we"
through = [391460.0, 6821060.0]
```

::::{tab-set}

:::{tab-item} Command line
```bash
hmp run guide_wells.toml
hmp viz show @last cross_section
```
:::

:::{tab-item} Python
```python
import hydromodpy as hmp

run = hmp.run("guide_wells.toml")
print(run.budget(component="well"))
hmp.figure(run, "cross_section", orientation="we", through=[391460.0, 6821060.0])
```
:::

::::

The section runs west to east through the well. The water table dips into a cone around
it, a few metres deep for this rate:

```{figure} /_static/figures/guides/add-wells/cross_section.webp
:alt: Cross-section of the Nançon aquifer through the well, with a dip of the water table at the well.

`cross_section` of the file above, west to east through the well.
```

```{figure} /_static/figures/guides/add-wells/watertable_depth_map.webp
:alt: Map of the depth to the water table with the pumping well marked by a triangle.

`watertable_depth_map` with the `wells` overlay. The triangle marks the pumping cell.
```

## Check that it worked

1. `run.budget(component="well")` in Python, or the `water_budget` figure, shows a `well`
   term. Its outflow is the rate you wrote, in m3/s: 0.0116 here.
2. The marker of the `wells` overlay sits where you placed the well.
3. The section or a map of the heads shows a cone around the well. A cone too deep for the
   aquifer dries the cell: look for a dry cell before you trust the rate.

## What can go wrong

| Symptom | Cause | Fix |
|---|---|---|
| The run has no `well` term in its budget, and no cone. Neither `hmp config check` nor the run says why. | `"wells"` is missing from {toml}`flow.active_sinks_sources`, so the well tables are not read. | Add `"wells"` to the list, as in step 1. |
| The map has no well marker, and the run log at `-v` says `Overlay 'wells' skipped: run has no well budget field.` | The run did not store the per-cell budget. | Set {toml}`simulation.results.budget.spatial_fields` to `true`. |
| `well requires either flux or forcing` | The well has neither a rate nor a schedule. | Write `flux` or a `forcing` table. |
| `well.flux and well.forcing are mutually exclusive` | The well has both. | Keep one. |
| `well relative coordinates must be within [0, 1]` | An `x_rel` or `y_rel` outside the model extent. | Use a fraction between 0 and 1. |
| `flow.sinks_sources.wells.W1 coordinates are outside the structured solver grid extent.` | The coordinates are outside the model, or in another CRS. | Give them in the project CRS. |
| `flow.sinks_sources.wells.W1 targets an inactive cell (layer 0, cell <n>); place the well inside the catchment.` | The well falls in an inactive cell. | Move it into the active domain. |
| `flow.sinks_sources.wells.W1.cell [lay, row, col] addressing needs a structured grid; use a coordinate-based location on a DISV (Voronoi/triangle) mesh.` | A `cell` location on a Gmsh mesh. | Use `absolute_xy` or `relative_xy`. |
| `flow.sinks_sources.wells.W1.flux length (<n>) must be 1 or match nper (<m>).` | A list of rates that does not have one value per stress period. | Give one value per period, or one value. |
| `flow.sinks_sources.wells.W1.units must be compatible with m3/s (for example m3/day, m3/h, m3/s, l/s). Got: '<unit>'` | A unit that is not a volume per time. `hmp config check` passes it; the run stops on it at its `build_geographic` step. | Write a volume per time. |

## Where to go next

- Refine the mesh around the well: {doc}`choose-and-build-the-mesh`.
- Run the model in time, with a start that is not the pumping state:
  {doc}`time-and-initial-state`.
- Compare the run with and without the well: {doc}`compare-runs`.
- Every key of a well: {toml}`flow.sinks_sources.wells`.
