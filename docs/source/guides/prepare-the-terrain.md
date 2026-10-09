# Prepare the terrain and the stream network

```{hmp-task}
Task
: Choose how the DEM is conditioned, extract the stream network from it, and make the channel beds of the model top run downhill.

Time
: Twenty minutes. The file below runs in about one minute on two cores.

Needs
: A model cut from a DEM by an outlet or a polygon. For the crossings, a file of roads, railways and bridges, or a provider that serves one.

Gives
: A catchment, a stream network and a model top that route water to the outlet, and two maps to check them.
```

HydroModPy reads the DEM three ways, and each key of this page acts on one of them.

- The **ground** is the DEM as loaded. The crossings notch and the dam carve below
  lower it.
- The **routing DEM** is a conditioned copy of the ground. It delineates the catchment and
  gives the stream network. {toml}`geographic.dem_correc_type` says how it is conditioned.
- The **model top** is the ground clipped to the domain. The solver reads it. The bed
  regularisation below changes it along the channels, and nothing else of this page does.

Each run also builds a descent D, a filled copy of the model top that every cell can drain
down. D never goes back to the solver. It is explained with the exits in
{doc}`../theory/exits`.

The worked case is example 04. The blocks below are merged onto `step1_minimal.toml`, a
steady model that fills the DEM and has no stream network.

{download}`Download the file of this guide <recipes/model/guide_terrain.toml>`.

## What you need first

- A catchment delineated from an outlet or a polygon:
  {toml}`geographic.catchment.catch_def` set to `from_outlet_coord` or `from_polyg_shp`.
  The bed regularisation and the crossings refuse a catchment that is the whole DEM.
- For the crossings: a vector file of the structures, or a provider (step 5).

## 1. Choose how the DEM is conditioned

A DEM holds pits and flats that would trap water. {toml}`geographic.dem_correc_type`
removes them from the routing DEM, one of three ways.

| `dem_correc_type` | What it does | Cells it changes |
|---|---|---|
| `fill` (default) | Raises each closed depression to its spill level, then gives the flats a small gradient. | Many, and only upward. |
| `breach` | Carves a path through the barrier that closes a depression, after raising single-cell pits, with no limit on length or depth. | Far fewer, mostly downward, and it can dig deep. |
| `capped_breach` | Breaches within a depth and a length, then fills what the limits refused. | Few, both ways. |

`fill` is the default because the stream-network criterion of the calibration uses it.

```toml
base_config = "step1_minimal.toml"

[geographic]
dem_correc_type = "capped_breach"

[geographic.capped_breach]
max_depth = 0.5
max_distance = 200.0
```

```{hmp-params}
geographic.dem_correc_type
geographic.capped_breach.max_depth
geographic.capped_breach.max_distance
```

`max_depth` is the lowering summed along one breach path, not the depth of one cell, so a
cell can end up lower than it. The run says so with a warning, and on example 04 the
deepest cell is cut 0.56 m for a limit of 0.5 m. The section
`[geographic.capped_breach]` is refused with any other method.

## 2. Choose the routing engine

{toml}`geographic.terrain_engine` names the engine that conditions the DEM and delineates
the catchment. Left unset, it is `whitebox_workflows`, the engine every number of this
documentation was produced with. `numpy_d8` is a second engine, written on numpy: it
fills only, and it is slow on a large DEM. Another engine joins the list as a plugin of
the `hydromodpy.terrain.engine` entry-point group.

```{hmp-params}
geographic.terrain_engine
```

The two engines do not give the same catchment on every DEM. Keep one engine for the runs
you compare.

## 3. Extract the stream network

`[geographic.river_network]` extracts a stream network from the routing DEM: every cell
that drains more than a threshold area is a stream. It feeds the mesh that follows the
rivers ({doc}`choose-and-build-the-mesh`), the SFR reaches
({doc}`route-streams-with-sfr`), the bed regularisation and the crossings below.

```toml
base_config = "step1_minimal.toml"

[geographic.river_network]
enabled = true
threshold_mode = "area_km2"
threshold_area_km2 = 0.5
```

```{hmp-params}
geographic.river_network.enabled
geographic.river_network.threshold_mode
geographic.river_network.threshold_area_km2
geographic.river_network.prune_short_streams
geographic.river_network.min_stream_length_m
```

The threshold is a model choice, fixed before the run. An observed network such as BD
Topage is never used to draw this one: it is the map the simulated network is scored
against ({doc}`calibrate-on-the-stream-network`).

## 4. Make the channel beds run downhill

On the model top, a channel read from the DEM climbs and drops: a bridge, a hedge or a
pixel of noise is a step up the bed. {toml}`geographic.bed_regularization` fits, along the
cells of the stream network, the bed closest to the ground that never rises downstream.
The drains and the SFR reaches then read that bed.

```toml
base_config = "step1_minimal.toml"

[geographic.river_network]
enabled = true
threshold_mode = "area_km2"
threshold_area_km2 = 0.5

[geographic.bed_regularization]
enabled = true
```

```{hmp-params}
geographic.bed_regularization.enabled
geographic.bed_regularization.min_slope
```

The fit raises some cells and lowers others, and leaves the hillslopes alone. On example
04 it touches 646 cells of the top, all along the network: 354 raised, 292 lowered, half
of them by less than 0.21 m, the largest by 3.5 m. Notched crossings are gaps in the fit,
and declared weirs and dams are drops.

## 5. Notch the road and rail crossings

A road or a railway on an embankment dams a valley in the DEM, and the water routed on it
stops there. {toml}`geographic.crossings` lowers the embankment where it crosses the
stream network, to the bed read on both sides, and delineates the catchment again on the
notched ground. The structures come from a file, or from `[[data.crossings.sources]]`:
`custom`, `bdtopo` (the roads and railways of IGN BD TOPO) or `roe` (the French register
of obstacles to flow).

```toml
# not checked: names a structure file that example 04 does not ship
base_config = "step1_minimal.toml"

[geographic.river_network]
enabled = true
threshold_mode = "area_km2"
threshold_area_km2 = 0.5

[geographic.crossings]
enabled = true
path = "crossings/structures.gpkg"
```

```{hmp-params}
geographic.crossings.enabled
geographic.crossings.path
geographic.crossings.kinds
geographic.crossings.notch_width
geographic.crossings.max_depth
```

Weirs and dams are never notched. A dam that must disappear from the ground, so that a
cutoff wall sits at the dam, is {toml}`geographic.dam_carve`; a lake that streams must
route into is {toml}`geographic.enforce_lakes`. Both need files of your own: see
{doc}`lakes-and-reservoirs` and {doc}`add-a-flow-barrier`.

## 6. Run it and look at the top

The file of this guide puts steps 1, 3 and 4 together and draws `depression_map`, the
cells of the model top that sit in a closed depression.

::::{tab-set}

:::{tab-item} Command line
```bash
hmp run guide_terrain.toml
hmp viz show @last depression_map
```
:::

:::{tab-item} Python
```python
import hydromodpy as hmp

cat = hmp.open(".")
run = hmp.run("guide_terrain.toml")
step1 = cat["nancon_step1_minimal"]
hmp.figure(run, "depression_map")
hmp.figure(run, "conditioning_impact_map", reference=step1)
```
:::

::::

On the top of step 1, 801 cells (3.7 % of the mesh) sit in a closed depression, up to
5.1 m deep. With the bed regularised, 195 cells are left (0.9 %), up to 2.8 m, mostly
single cells on the hillslopes:

```{figure} /_static/figures/guides/prepare-the-terrain/depression_map.webp
:alt: Map of the closed depressions of the model top, a few scattered cells coloured by the fill they need.

`depression_map` of the file of this guide.
```

`conditioning_impact_map` shows where the top differs from the one of step 1, by more than
a centimetre on 2 % of the cells. It needs a reference run, so it is drawn from Python.
Only the cells of the network move:

```{figure} /_static/figures/guides/prepare-the-terrain/conditioning_impact_map.webp
:alt: Map of the difference of the model top with step 1, non-zero only along the stream network.

`conditioning_impact_map` of the file of this guide against step 1.
```

## Check that it worked

1. The note under `depression_map` gives the count of cells in a closed depression, and
   the depth they need. Few cells, and shallow ones, are the aim.
2. `conditioning_impact_map` against a run without the setting changes only the cells
   you meant to change.
3. The catchment area in `watershed_id_card` stays close to the one of a known gauge.
   A conditioning that moves it a lot moves the outlet or a divide.

## What can go wrong

| Symptom | Cause | Fix |
|---|---|---|
| `[geographic.capped_breach] sets the limits of dem_correc_type = 'capped_breach', and dem_correc_type is 'fill', which has none` | The limits without the method. | Set `dem_correc_type = "capped_breach"`, or remove the section. |
| `Capped breach: the realised maximum lowering 0.560 m exceeds max_depth 0.500 m.` (warning) | `max_depth` bounds a whole path, not one cell. | Nothing to fix. Lower `max_depth` if the cut is too deep. |
| `geographic.terrain_engine names '<name>', and this installation serves numpy_d8, whitebox_workflows.` | An engine that is not installed. | Name one of the list, or install the plugin. |
| `numpy_d8 conditions with 'fill' only; 'breach' is not implemented.` | `breach` or `capped_breach` on the numpy engine. | Use `fill`, or the default engine. |
| `[geographic.bed_regularization] enabled = true needs [geographic.river_network] enabled = true` | The bed has no channel to follow. | Switch the network on, as in step 3. |
| `[geographic.crossings] enabled = true needs [geographic.river_network] enabled = true` | The same for the crossings. | Switch the network on. |
| `[geographic.bed_regularization] fits the bed of a delineated catchment: it needs catch_def = 'from_outlet_coord' or 'from_polyg_shp', not catch_def = dem.` | The model is the whole DEM. The crossings refuse it the same way. | Delineate the catchment from an outlet or a polygon. |
| `threshold_area_km2 must be > 0 when threshold_mode='area_km2'.` | The network is on without a threshold. | Write {toml}`geographic.river_network.threshold_area_km2`. |

## Where to go next

- The mesh that follows the network: {doc}`choose-and-build-the-mesh`.
- Streams that route the water down the network: {doc}`route-streams-with-sfr`.
- How the descent D is built from the top: {doc}`../theory/exits`.
- How the simulated network is scored against a map: {doc}`../theory/downslope-distance`.
