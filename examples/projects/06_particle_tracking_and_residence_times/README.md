# 06 - Particle tracking and residence times

Lasset catchment (eastern Pyrenees, EPSG:2154), delineated from its outlet on
a regional 75 m DEM. **Steady-state** groundwater flow with **MODFLOW 6** over
ten layers thickening with depth above a **flat substratum at 1000 m**,
hydraulic conductivity decaying exponentially with depth, followed by particle
tracking with **MODFLOW 6 PRT**.

Particles released over the domain terminate where the water table outcrops:
their pathlines say which recharge feeds the seepage areas, and their travel
times give the residence-time distribution of the aquifer.

## Run

```bash
hmp run examples/projects/06_particle_tracking_and_residence_times/project.toml
```

Runtime: about 4 s (3432 cells over 10 layers, 500 particles).

## Data

| File | Family | Role |
|---|---|---|
| `dem/regional_dem_lasset.tif` | dem | 75 m DEM, a 20 km window centred on the outlet |
| synthetic recharge | recharge | monthly climatology, mean 1.17 mm/d |

The DEM is a window cut from the legacy regional raster (30 MB covering the
whole Pyrenean range): 20 km a side is ample for a 4 km by 5 km catchment, and
the file drops to 240 KB.

## The flat substratum

`kind = "flat_substratum"` sets an absolute base elevation, not a thickness
below the topography: the aquifer is thin under the crests and thick under the
valleys. That is what makes the deep paths long and the shallow ones short,
and therefore what spreads the residence-time distribution.

## Figures

| Figure | What it shows |
|---|---|
| `watershed_id_card` | catchment identity card |
| `mesh_map` | solver grid |
| `piezometric_map` | water-table elevation |
| `watertable_depth_map` | water-table depth + seepage + particles |
| `seepage_map` | seepage areas |
| `accumulation_map` | accumulated drainage flux |
| `particle_tracks` | pathlines coloured by travel time |
| `residence_time_distribution` | travel-time density against the exponential law |
| `cross_section` | topography / water table / aquifer base section |
| `water_budget` | budget per component |

The distribution departs clearly from the exponential beyond `t/tau = 1`: the
conductivity decaying with depth cuts the long tail a homogeneous aquifer
would produce.

## Differences with the legacy example

| Point | legacy | here |
|---|---|---|
| Solver | MODFLOW-NWT + MODPATH6 | MODFLOW 6 + PRT |
| Tracking direction | backward, from 5 boreholes | forward, from the domain |
| Release | 50 particles (5 boreholes x 10 layers) | 500 particles over the domain |

MODFLOW 6 PRT only tracks forward. The legacy example released 50 particles in
five boreholes addressed by hard-coded pixel indices and traced them back to
their recharge areas; released over the domain and tracked forward, those are
the same pathlines drawn from the other end, and every one of them carries a
travel time. Backward tracking needs the MODFLOW-NWT + MODPATH pair, still
available through `solvers = ["modpath"]`.
