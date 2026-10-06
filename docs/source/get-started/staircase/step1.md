# Step 1: the shortest file that runs

Step 1 solves the Nançon catchment in steady state. It cuts the catchment out of a regional
DEM upslope of an outlet point, gives the aquifer one K and one recharge rate, and lets any
cell drain at the ground surface: the excess water leaves as seepage. It inherits nothing,
so this page shows the whole file. The aquifer is 30 m thick instead of the 50 m default.

## The file

```{hmp-step} step1_minimal.toml
```

## Run it

```bash
cd ~/hydromodpy/projects/04_streamflow_intermittence_in_transient
hmp run step1_minimal.toml
```

If you have not fetched the example yet, start with {doc}`index`. The example catalog gives
about 6 seconds for this step. `hmp run -v` prints every INFO line and `hmp run -q` only
warnings and errors.

## What you get

Five figures, in `runs/nancon_step1_minimal/figures/`, listed by {toml}`display.figures`:

| Figure | What it shows |
|---|---|
| `watershed_id_card` | The topography, the outlet, and a table of facts: what was modelled, where, over which period, on which grid |
| `watertable_depth_map` | The depth of the water table below the land surface, in metres |
| `seepage_map` | The cells where the water table reaches the surface, a yes or no for each cell |
| `cross_section` | The land surface, the water table and the seepage segments along a line. Here the line runs south to north through the outlet, so it cuts the tributaries across |
| `water_budget` | One bar per component of the budget, inflow and outflow |

Three exports, in `share/nancon_step1_minimal/`, one {toml}`[[export]] block|export` each:

| Block | File |
|---|---|
| `variables = "watershed"` | the catchment outline, a GeoPackage |
| `variables = ["watertable_depth", "seepage_mask"]`, `time = "last"` | one GeoTIFF per variable. A steady run has one state, which `"last"` picks |
| `variables = "budget"` | the water budget, a CSV |

Steps 2 to 4 inherit these three blocks.

## Key fields

```{hmp-params}
flow.flow_regime
flow.param.K.field.value
domain.depth_model.thickness
flow.active_bc
```

Sy is declared too, for step 4: a steady solve never reads it.

Next: {doc}`step2`, which adds the mapped river network.
