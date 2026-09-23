# 00 - Quick test of wide HydroModPy capabilities

Port to the v1 architecture of
`examples/00_quick_test_of_wide_hydromodpy_capabilities/example_00.py` at tag `v1.0.0`,
solved with **MODFLOW 6** instead of MODFLOW-NWT.

Aber catchment (Brittany, EPSG:2154), extracted from a regional 75 m DEM by
outlet snapping. One monthly transient year (2017) on the buffered
rectangular box, one 50 m aquifer layer, two pumping wells, hillslope
drainage, and particle tracking.

## Run

```bash
# via the TOML
hmp run examples/projects/00_quick_test_of_wide_hydromodpy_capabilities/project.toml

# via the Python API (same config, same results)
python examples/projects/00_quick_test_of_wide_hydromodpy_capabilities/run_manual.py

# re-render the figures without re-simulating
hmp viz gallery examples/projects/00_quick_test_of_wide_hydromodpy_capabilities/project.toml
```

Runtime: about 5 s (980 cells, 12 stress periods).

## Data

All shared under `examples/data/`, resolved by bare file name:

| File | Family | Role |
|---|---|---|
| `dem/regional_dem_aber.tif` | dem | regional 75 m DEM (legacy `regional dem.tif`) |
| `hydrography/regional_stream_network.shp` | hydrography | reference network |
| `recharge/recharge_custom_00_*.csv` | recharge | monthly recharge, mm/d |
| `wells/wells_custom_00_*.csv` | (well forcing) | monthly rates, m3/d |

## Mapping to the legacy script

| Legacy | v1 |
|---|---|
| `from_xyv = [x, y, 100, 10]` | `[geographic.catchment]` `from_outlet_coord`, `snap_dist`, `buff_area` |
| `update_box_model(True)` | `geographic.domain_extent = "box"` |
| `update_sink_fill(False)` | `geographic.dem_correc_type = "breach"` |
| `update_dis_perlen(True)` | `simulation.time.substeps_per_period = 30` |
| `update_thick(50)` / `update_nlay(1)` | `[domain.depth_model]` / `[modflow6.sgrid.vertical]` |
| `update_hk/sy/ss` | `[flow.param.K/Sy/Ss.field]` |
| `update_well_pumping(...)` | `[flow.sinks_sources.wells.W1/W2]` |
| `update_first_clim('mean')` | `flow.first_period_steady = true` |
| MODPATH backward from the seepage zones | MODFLOW 6 PRT forward (see below) |
| matplotlib plots in the script | `[display].figures` |

### Particle tracking: why forward

The legacy script ran MODPATH **backward** from the seepage zones to show
which recharge feeds them. MODFLOW 6 PRT only tracks downstream: the same
physics is written the other way round, particles are released over the
domain and end where the watertable outcrops. The figure reads the same way.

## Figures

All come from the HydroModPy registry, none is hardcoded in a `.py`.

| Figure | What it shows | Legacy equivalent |
|---|---|---|
| `watershed_id_card` | catchment identity card | `watershed_local` |
| `mesh_map` | solver grid colored by topography | `visual2D(['grid'])` |
| `recharge_map` | recharge per cell | - |
| `piezometric_map` | watertable elevation | `visual2D(['watertable'])` |
| `watertable_depth_map` | watertable depth + seepage + tracks + wells | the script's composite map |
| `seepage_map` | seepage zones | - |
| `flow_persistence_map` | share of the year each cell carried flow | `persistency_index` |
| `flow_intermittence_map` | perennial, intermittent and dry cells | `intermittency_monthly` |
| `particle_tracks` | tracks colored by travel time | `pathlines` |
| `residence_time_distribution` | travel-time histogram against the exponential law | `residence_times` |
| `cross_section` | topography / watertable / aquifer base cross section | the script's fixed cross section |
| `flux_timeseries` | water budget per timestep, mm/period | the recharge / drain / well plot |
| `water_budget` | cumulative budget per component | - |

The composite map is declarative, not hardcoded:

```toml
[display.overrides.watertable_depth_map]
overlays = ["watershed", "seepage", "particles", "wells", "outlet"]
```

`on_error = "raise"`: a figure that applies but fails makes the run fail. A
figure that does not apply to this run is skipped, with an explicit reason
in the log.

## Switching to MODFLOW-NWT

Only the solver name and the section prefix change. Particle tracking then
switches from PRT to MODPATH, which supports backward tracking:

```toml
[[simulation.process]]
id = "flow_main"
type = "flow"
solvers = ["modflow_nwt"]

[[simulation.process]]
id = "particles"
type = "transport"
solvers = ["modpath"]

[transport.modpath.parameters]
zone_partic = "seepage_clip"
track_dir = "backward"

[modflownwt.sgrid.planar]
mode = "keep_native"

[modflownwt.sgrid.vertical]
nlay = 1
```


## Two corrections to the first port

The pumping rates were a tenth of the legacy ones. They are back to
-200 and -100 m3/day on the first well, -500 m3/day on three months of the
second, which is what makes the two cones of depression visible on the
water-table map and on the section that runs through both wells.

Both of those figures are now pinned to the first period, January, the month
the two wells pump hardest in. The legacy figures were captioned `time 1/12`
for that reason; without the pin they showed December, when nothing pumps.

The legacy `persistency_index` and `intermittency_monthly` rasters are the
two maps added above. Both read `accumulation_flux` rather than a field of
their own: the persistence share is the fraction of timesteps a cell carried
flow, the intermittence classes split that into carried it always and carried
it sometimes, over one calendar year rather than over a fixed block of twelve
steps.
