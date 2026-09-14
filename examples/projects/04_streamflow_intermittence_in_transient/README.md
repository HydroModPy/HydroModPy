# 04 - Streamflow intermittence in transient

Nancon catchment (Brittany, EPSG:2154), extracted from the regional 75 m
DEM by outlet snapping. **Monthly transient** groundwater flow over three
years (2000-2002), solved with **MODFLOW 6**, forced by observed monthly
recharge and runoff.

The theme is intermittence: as recharge oscillates between wet winters and
dry summers, the watertable rises and falls, so the seepage cells and the
simulated active network expand and contract over the year.

## Run

```bash
hmp run examples/projects/04_streamflow_intermittence_in_transient/project.toml

# seasonal intermittence: seepage at the extreme months, via the Python API
python examples/projects/04_streamflow_intermittence_in_transient/run_manual.py

hmp viz gallery examples/projects/04_streamflow_intermittence_in_transient/project.toml
```

Runtime: about 15 s (36 timesteps, COMPLEX solver).

## Data

| File | Family | Role |
|---|---|---|
| `dem/DEM_armorican_massif.tif` | dem | regional 75 m DEM (covers the Nancon) |
| `recharge/recharge_custom_NANCON_*.csv` | recharge | observed monthly recharge (mm/d) |
| `runoff/runoff_custom_NANCON_*.csv` | runoff | monthly runoff, added to baseflow |

## Intermittence

`run_manual.py` counts seepage cells for each month. Over this period, the
wet network goes from ~450 cells (dry month) to ~1670 (wet month): about
**1200 cells switch on and off** over time. These are the intermittent
reaches; the core that stays active throughout is the perennial network.
The script renders `seepage_map` for the wettest and the driest month (same
figure, two `timestep` values).

## Figures

| Figure | What it shows |
|---|---|
| `watershed_id_card` | catchment identity card |
| `mesh_map` | solver grid |
| `piezometric_map` | watertable elevation (last timestep) |
| `watertable_depth_map` | watertable depth + seepage |
| `seepage_map` | seepage zones (time-varying) |
| `simulated_active_network` | active draining network |
| `hydrograph` | simulated discharge over time |
| `flux_timeseries` | water budget per timestep |
| `cross_section` | topography / watertable cross section |
| `water_budget` | cumulative budget per component |

## Technical debt

The legacy script computed a `persistency_index` (fraction of time a cell
is active) and monthly/weekly/daily intermittence maps. These
**time-aggregated fields do not exist yet** as canonical v1 fields. In the
meantime, intermittence is read through the seasonal seepage dynamics
above rather than through a single index. An aggregated `persistency_index`
field would be the natural addition.
