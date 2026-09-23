# 10 - Coupling with a land surface model (PyHELP)

Urse catchment (Switzerland, EPSG:2056 CH1903+/LV95), 6 km² of Alpine
grassland. The recharge is not a number written in the TOML: it is the daily
percolation **PyHELP** computes cell by cell from three years of
precipitation, air temperature and solar radiation.

**Steady-state** flow with **MODFLOW 6**, then a search for the hydraulic
conductivity from the **hydrographic-network criterion**, with no discharge
data at all.

## Run

```bash
# 1. the land surface model produces the recharge grid
python examples/projects/10_coupling_with_land_surface_model_pyhelp/build_pyhelp_recharge.py

# 2. the groundwater flow it forces
hmp run examples/projects/10_coupling_with_land_surface_model_pyhelp/project.toml

# 3. the conductivity, searched on the observed network
hmp calibrate examples/projects/10_coupling_with_land_surface_model_pyhelp/run_calibration_k.toml
```

Step 1 is optional: the grid it produces is shipped as
`examples/data/recharge/recharge_pyhelp_urse.nc`. Re-running it is how you
change a soil or vegetation parameter and watch the recharge move; it also
draws the yearly and monthly totals to `.pyhelp/pyhelp_recharge.png`, an input
diagnostic no registry figure covers.

Runtimes: PyHELP about 25 s (98 columns, 1095 days), the MODFLOW 6 run about
2 min (28 470 cells).

## Data

| File | Family | Role |
|---|---|---|
| `dem/DEM_urse_25m.tif` | dem | 25 m DEM of the catchment |
| `dem/DEM_urse_250m.tif` | dem | 250 m DEM, geometry of the PyHELP grid |
| `watershed_polygon/urse_watershed.gpkg` | - | catchment outline, defines the domain |
| `hydrography/urse_stream_network.gpkg` | hydrography | observed network, reference of the criterion |
| `pyhelp/urse_precipitation.csv` | - | PyHELP forcing, daily precipitation 2021-2023 |
| `pyhelp/urse_air_temperature.csv` | - | PyHELP forcing, air temperature |
| `pyhelp/urse_solar_radiation.csv` | - | PyHELP forcing, solar radiation |
| `pyhelp/urse_grid_base.csv` | - | PyHELP grid template (soil, vegetation) |
| `recharge/recharge_pyhelp_urse.nc` | recharge | PyHELP **output**, model input |

PyHELP is not a HydroModPy process: it has no TOML surface, it is a
preparation step. `build_pyhelp_recharge.py` is its declaration.

## The coupling

PyHELP is a 1D column model: one daily water balance per cell, whose
percolation below the root zone is the recharge. The grid is deliberately at
250 m, ten times coarser than the groundwater model: running one column per
25 m cell buys nothing, and PyHELP knows no lateral transfer.

Mean recharge obtained: about **800 mm/year**.

The run declares a `[simulation.time]` window even though it is steady. A
gridded forcing is selected on the run window before it is averaged, so a
steady run still has to say which three years it averages; without a window
the selection is empty and the aquifer is solved with no recharge at all.

PyHELP only runs the cells inside the catchment polygon, while the groundwater
domain is the catchment plus a 20% buffer ring. `build_pyhelp_recharge.py`
extends the grid over that ring with the value of the nearest modelled cell:
not a measurement, the least-wrong extension of one.

## The calibration

`run_calibration_k.toml` inherits `project.toml` through `base_config` and
redefines only what changes. The criterion is the signed gap between the
network the water table sustains and the mapped one, driven to zero by
bisection on log K (the method of Abhervé et al.). It is the v2 form of the
hand-written `while diff > gap` loop of the legacy example, with the same
objective.

The drain conductance stays proportional to K (`[flow.bc.drainage]` with no
`value`), without which the criterion loses the K/R invariance it rests on.

## Figures

| Figure | What it shows |
|---|---|
| `watershed_id_card` | catchment identity card |
| `mesh_map` | solver grid |
| `recharge_map` | PyHELP recharge per cell |
| `piezometric_map` | water-table elevation |
| `watertable_depth_map` | water-table depth |
| `seepage_map` | seepage areas |
| `hydrographic_network_reference` | observed network |
| `simulated_active_network` | network the water table sustains |
| `simulated_active_network_reference_overlay` | the two superimposed |
| `cross_section` | topography / water table section |
| `water_budget` | budget per component |

## Differences with the legacy example

| Point | legacy | here |
|---|---|---|
| Solver | MODFLOW-NWT | MODFLOW 6 |
| Calibration | `while` loop written in the script | declarative `[calibration]`, `bisection` method |
| Objective | `MatchingStreams` class (WhiteboxTools chain) | `metric = "distance_gap"`, same criterion |
| Diagnostics | a `df_optim` table built by hand | catalog tables + calibration figures |

Three library fixes came with this port, all in the path between PyHELP and
the data layer, which nothing had ever exercised end to end:

- the NetCDF export named its recharge variable `rechg`, a name the data layer
  cannot look up; it is now `recharge`, like the family that consumes it;
- that NetCDF declared neither a CF grid mapping on its fields nor a nodata
  attribute that survives decoding, so it was refused on load;
- a gridded forcing was read by taking the first data variable of the file,
  which on any CF dataset is the scalar grid-mapping variable rather than the
  field, and on a multi-field export could be any of them.
