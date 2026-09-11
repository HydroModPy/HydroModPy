# 05 - Piezometry in a coastal aquifer

Gouville coastal strip (Normandy, EPSG:2154). The domain is a polygon
(`model_area`) on a 25 m coastal DEM. **Steady-state** groundwater flow
solved with **MODFLOW 6**, with a **marine boundary**: any cell whose
surface is below mean sea level is held at that level (fixed head). The
watertable therefore drops from the inland recharge mound toward the shore.

## Run

```bash
hmp run examples/projects/05_piezometry_in_a_heterogeneous_coastal_aquifer/project.toml

# coastal watertable gradient, via the Python API
python examples/projects/05_piezometry_in_a_heterogeneous_coastal_aquifer/run_manual.py

hmp viz gallery examples/projects/05_piezometry_in_a_heterogeneous_coastal_aquifer/project.toml
```

Runtime: about 1 s (coastal strip ~5200 cells at 25 m).

## Data

| File | Family | Role |
|---|---|---|
| `dem/DEM_gouville_25m.tif` | dem | 25 m coastal DEM (NGF; the sea is below 0 m) |
| `watershed_polygon/gouville_model_area.shp` | polygon | coastal model extent |
| synthetic recharge | recharge | steady-state average recharge, 1.0 mm/d |

## The marine boundary

The `ocean` BC applies a constant head at sea level (`value = "0 m"` NGF) on
every cell whose DEM is below that threshold. No coastline is required: the
coastal DEM is enough, the sea is identified by elevation. The result (see
`piezometric_map`) is the classic coastal watertable shape: 0 m at the
shore, rising inland (~16 m here).

## Figures

| Figure | What it shows |
|---|---|
| `mesh_map` | solver grid |
| `piezometric_map` | watertable elevation (0 at the shore, rising inland) |
| `watertable_depth_map` | watertable depth + seepage |
| `seepage_map` | seepage zones (including the coastal fringe) |
| `cross_section` | west-east cross section from the sea into the aquifer |
| `water_budget` | budget per component (recharge vs. sea + drainage) |

## Not ported from the legacy script

The legacy case had several refinements that this port leaves out for a
first clean coastal case, and which are the natural technical debt:

- **Zoned heterogeneous conductivity** (`param_zones.shp`): here K is
  homogeneous. v1 handles heterogeneity through a spatial support + value
  table, but wiring zones-shapefile to a K field properly is still to be
  done.
- **Comparison to observed piezometry**: the original case calibrated
  against piezometers. The data and the sim/obs figures exist (see the
  `piezometry` family and `piezo_timeseries_sim_obs`), but the coastal
  calibration is not set up here.
- **Tidal dynamics**: the marine BC is fixed at mean sea level (0 m). A
  tide time series (`[flow.bc.dirichlet.ocean.forcing]`) and a transient
  run would give the watertable's tidal response.
- **5 m DEM**: the port uses the 25 m DEM; the 5 m one refines the
  shoreline.
