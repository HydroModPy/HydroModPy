# 08 - Exponential distribution of residence times

Synthetic 1D aquifer, 1000 m long and 10 m thick over a flat substratum, fed
by a uniform 1 mm/d recharge and drained by a penetrating stream on its west
edge. **Steady state** with **MODFLOW 6**, then forward particle tracking with
**MODFLOW 6 PRT**.

The travel-time density of the particles is put next to the exponential law a
single well-mixed store produces:

```
p(t) = exp(-t/tau) / tau        tau = n H / R
```

That is the classic result for a Dupuit aquifer under uniform recharge: the
age of the water leaving at the stream is exponentially distributed.

## Run

```bash
hmp run examples/projects/08_exponential_distribution_of_residence_times/project.toml
```

Runtime: about 5 s (800 cells over 2 layers, 796 particles tracked).

## Result

Over `t/tau` from 0.1 to 5 the simulated distribution follows the exponential.
Below `t/tau = 0.05` it runs above it: those are the particles released a few
cells from the stream, which leave before they have seen the aquifer. Measured
mean residence time: **2.2 years**.

## Figures

| Figure | What it shows |
|---|---|
| `mesh_map` | solver grid |
| `piezometric_map` | water-table elevation |
| `cross_section` | water table / substratum section |
| `particle_tracks` | pathlines coloured by travel time |
| `residence_time_distribution` | travel-time density against the exponential law |
| `water_budget` | budget per component |

`residence_time_distribution` is a figure added with this port: nothing in the
registry built a distribution out of the particles.

## Differences with the legacy example

| Point | legacy | here |
|---|---|---|
| Solver | MODFLOW-NWT + MODPATH6 | MODFLOW 6 + PRT |
| Layers | 10 | 2 |
| DEM | a raster generated inside the script | `source_mode = "synthetic"` |
| Weighting | recharge flux per particle (`rchPerc`) | one particle, one weight |

Two layers rather than ten: MODFLOW 6 refuses a fixed head below a cell
bottom, and the stream sits at mid-thickness. The spread of travel times comes
from the distance to the stream, which is what the exponential law is derived
from.

The extractors write no per-particle weight to the store, so the density is
that of the release the run asked for, not a recharge-weighted one. Here the
release covers the domain uniformly, so the two coincide; over a partial
release zone they would not.
