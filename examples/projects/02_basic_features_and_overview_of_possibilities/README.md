# 02 - Basic features and overview of possibilities

Small conceptual demo catchment, delineated from its outlet on a teaching
DEM, solved in **steady state** with **MODFLOW 6**. This is the "whole
chain on a toy domain" case, fully offline, which exercises the full set of
standard figures.

## Run

```bash
hmp run examples/projects/02_basic_features_and_overview_of_possibilities/project.toml

# run + inspection + figures, via the Python API
python examples/projects/02_basic_features_and_overview_of_possibilities/run_manual.py

hmp viz gallery examples/projects/02_basic_features_and_overview_of_possibilities/project.toml
```

Runtime: under 1 s (conceptual catchment ~60 cells).

## Data

| File | Family | Role |
|---|---|---|
| `dem/conceptual_dem.tif` | dem | conceptual 75 m DEM (teaching topography) |
| synthetic recharge | recharge | steady-state average recharge, 1.5 mm/d |

## Recharge scenarios

To explore dry / normal / wet scenarios, change the `values` field of
`[[data.recharge.sources]]` in `project.toml` and rerun: higher recharge
raises the watertable, so more cells outcrop as seepage.

## Figures

| Figure | What it shows |
|---|---|
| `mesh_map` | solver grid |
| `recharge_map` | recharge per cell |
| `piezometric_map` | watertable elevation |
| `watertable_depth_map` | watertable depth + seepage |
| `seepage_map` | seepage zones |
| `accumulation_map` | drain outflow accumulated along the drainage network |
| `particle_tracks` | tracks colored by travel time |
| `residence_time_distribution` | travel-time histogram against the exponential law |
| `cross_section` | topography / watertable / aquifer base cross section |
| `parameter_section` | the same section coloured by K, which steps down at 30 m |
| `water_budget` | budget per component (recharge = drainage at steady state) |
| `mass_balance_error` | solver closure error per timestep |

## Domain definition modes

The legacy script showed four ways to define a catchment. All of them exist
in v1, via `[geographic.catchment].catch_def`:

| Mode | `catch_def` | Example |
|---|---|---|
| from an outlet | `from_outlet_coord` | here, 00, 01, 03, 04 |
| from a polygon | `from_polyg_shp` | - |
| XYZ text grid | `txt` | - |
| analytical domain | `source_mode = "synthetic"` | 00_getting_started |

## Technical debt

- The `catch_def = "dem"` mode (the DEM IS the domain, no delineation) does
  not mask the raster's nodata: nodata cells enter the active domain and
  ruin the figures. Delineating from the outlet is used instead, since it
  masks properly. A nodata mask in `dem` mode would be the fix.
- Sweeping scenarios in a single Python process hits the DuckDB connection
  (`hmp.run` reopens the catalog on every call). The clean multi-run
  pattern is `hmp.Project` + `project.simulate(...)` (see example 03), which
  only overrides flow parameters; varying recharge is therefore done by
  editing the TOML.


## What the legacy example did that this one now does again

The first port of this example flattened it into a one-layer homogeneous box.
The legacy script builds an aquifer with structure, and that structure is back:

| Point | legacy | here |
|---|---|---|
| Layers | 10, thickening 1.2x with depth | same |
| Aquifer base | mirror of the topography, `bottom = -DEM` | a flat base at -78 m, the mean of that mirror |
| Conductivity | 1e-5 m/s over 0-30 m, 1e-7 m/s below | a step vertical profile, same two bands |
| Specific yield | 0.10 | 0.10 |
| Particle tracking | MODPATH6, pathlines and residence times | MODFLOW 6 PRT, `particle_tracks` and `residence_time_distribution` |
| Recharge | a random per-cell field | one constant value |

Two deviations stand. MODFLOW 6 has no depth model that mirrors the
topography, so the flat base is set at the mean of what the legacy one would
have produced: the aquifer is still thick under the highs and thin under the
lows, only less so. And the legacy recharge was `np.random.rand(...) * 100`
mm/month, a different field on every run; a constant is kept here, because an
example whose numbers change every time teaches nothing.
