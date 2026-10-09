# Step 1: the shortest file that runs

```{hmp-task}
Task
: Solve the Nançon catchment in steady state from one short file.

Time
: 15 to 25 s for the run (the `Run completed` figure), 25 to 45 s for the command.

Needs
: The example files ({doc}`index`) and the MODFLOW 6 binary, downloaded on first use. No other network access.

Gives
: Five figures and four files: the catchment outline, two GeoTIFFs and a water budget.
```

Step 1 cuts the catchment out of a regional DEM upslope of an outlet point, gives the
aquifer one K and one recharge rate, and lets any cell drain at the ground surface: the
excess water leaves as seepage. It inherits nothing, so this page shows the whole file. The
aquifer is 30 m thick instead of the 50 m default.

```{image} /_static/figures/staircase/step1/watertable_depth_map.webp
:alt: Depth to the water table over the Nançon catchment, from 0 to 30 m. Shallow in the valleys, deep on the ridges.
:class: only-light
:width: 60%
:align: center
```

```{image} /_static/figures/staircase/step1/watertable_depth_map-dark.webp
:alt: Depth to the water table over the Nançon catchment, from 0 to 30 m. Shallow in the valleys, deep on the ridges.
:class: only-dark
:width: 60%
:align: center
```

## The file

```{hmp-step} step1_minimal.toml
```

## Run it

::::{tab-set}
:sync-group: api

:::{tab-item} Command line
:sync: cli

```bash
cd ~/hydromodpy/projects/04_streamflow_intermittence_in_transient
hmp run step1_minimal.toml
```

`hmp run -v` prints every INFO line and `hmp run -q` only warnings and errors.
:::

:::{tab-item} Python
:sync: python

```python
import hydromodpy as hmp

run = hmp.run("step1_minimal.toml")
print(run.name)
```
:::

::::

If you have not fetched the example yet, start with {doc}`index`. Running the file again
does nothing, unless you edited it: see {ref}`the rerun note <staircase-rerun>`.

## What you get

Five figures, in `runs/nancon_step1_minimal/figures/`, listed by {toml}`display.figures`:

| Figure | What it shows |
|---|---|
| `watershed_id_card` | The topography, the outlet, and a table of facts: what was modelled, where, over which period, on which grid |
| `watertable_depth_map` | The depth of the water table below the land surface, in metres |
| `seepage_map` | The cells where the water table reaches the surface, a yes or no for each cell |
| `cross_section` | The land surface, the water table and the seepage segments along a line. Here the line runs south to north through the outlet, so it cuts the tributaries across |
| `water_budget` | One bar per component of the budget, inflow and outflow |

Three {toml}`[[export]] blocks|export` write four files, in `share/nancon_step1_minimal/`:

| Block | Files |
|---|---|
| `variables = "watershed"` | `watershed.gpkg`, the catchment outline |
| `variables = ["watertable_depth", "seepage_mask"]`, `time = "last"` | `watertable_depth_last.tif` and `seepage_mask_last.tif`, one GeoTIFF per variable. A steady run has one state, which `"last"` picks |
| `variables = "budget"` | `budget.csv`, the water budget |

The run also leaves a `RUN.txt` there, which is a note and not an export. Steps 2 to 4
inherit these three blocks.

(staircase-warnings)=
## The warnings of the first run

The run prints `WARNING` lines. None is an error, and each has a reason.

| Warning | Why | What to do |
|---|---|---|
| `Outlet moved 130 m (limit 150 m) onto the flow network, from (389286, 6816519) to (389175, 6816450).` | The coordinate of the file does not fall on a stream cell of the DEM. The delineation starts from the nearest cell of the flow network, within {toml}`geographic.catchment.snap_dist`, here 150 m. The run warns when the move is more than half of that limit. | Nothing, here. A move close to the limit means the coordinate is far from the stream: check it. |
| `Simulated discharge is baseflow only: the run has no runoff forcing, so it underestimates a gauged total streamflow.` | The discharge of steps 1 and 2 is what the drains collect from the aquifer. A gauge measures that plus the surface runoff, and no runoff series is loaded. | Nothing, until step 4: it loads a runoff series, adds it to the discharge, and the warning goes. |
| `Runs of this workspace are sealed without creator_name, creator_institution and a known licence. Add creator_name = "..." and creator_institution = "..." under [workspace] in <workspace.toml>; a licence comes from the 'license' key of each input sidecar (<file>.json).` | A run is sealed with a record of who made it and under which licence, and the workspace says neither. It prints once per workspace, on its first run: if you ran the demo of the quick start, you saw it there. | Cosmetic. Write the two keys under `[workspace]` in `workspace.toml`, or start with `hmp workspace init --creator-name "Your name"`. |

## Key fields

```{hmp-params}
flow.flow_regime
flow.param.K.field.value
domain.depth_model.thickness
flow.active_bc
```

Sy is declared too, for step 4: a steady solve never reads it.

Next: {doc}`step2`, which adds the mapped stream network.
