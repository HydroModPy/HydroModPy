# 03 - Hydrographic network in steady state

Canut catchment (Brittany, EPSG:2154), extracted from the regional 75 m DEM
by outlet snapping. **Steady-state** groundwater flow in a 50 m aquifer
split into **five layers**, solved with **MODFLOW 6**.

Three networks are put side by side:

- the **observed** network, BD Topage (`reference`);
- the network **delineated from the DEM** by flow accumulation (`generated`);
- the **simulated active** network, the cells the watertable feeds
  (`simulated_active`).

This is the "how the perennial network emerges from the watertable" case: as
K varies, the active network shrinks from the whole catchment down to a few
valley-bottom cells.

## Run

```bash
# the reference run and its figure gallery
hmp run examples/projects/03_hydrographic_network_in_steady_state/project.toml

# the K sweep, the core of the example, via the Python API
python examples/projects/03_hydrographic_network_in_steady_state/run_manual.py

# regenerate a run's gallery without replaying it
hmp viz gallery examples/projects/03_hydrographic_network_in_steady_state/project.toml
```

Runtime: about 25 s for the reference run (catchment ~9300 cells, 5 layers),
about 70 s for the 10 sweep runs.

## Data

All shared under `examples/data/`, resolved by file name:

| Source | Family | Role |
|---|---|---|
| `dem/DEM_armorican_massif.tif` | dem | regional 75 m DEM (covers the Canut) |
| `geology/GEO1M.shp` (`CODE_LEG`) | geology | BRGM 1:1,000,000 geological map, context |
| BD Topage, provider `bdtopage` | hydrography | observed network, role `reference` |
| synthetic recharge | recharge | monthly climatology, average 1.17 mm/d |

Geology is declared in `[domain] zone_ids` to be mapped, but no parameter is
zoned on it: K stays homogeneous, which is the condition for the sweep.

The old script also loaded hydrometric stations and ONDE stations as map
decoration. They are not carried over here: the shared data tree has no
time series in the Canut catchment, so `[data.hydrometry]` and
`[data.intermittency]` would load without producing anything. Examples 04
and 05 are the ones that show the station inventory.

## Gallery figures

| Figure | What it shows |
|---|---|
| `watershed_id_card` | catchment identity card |
| `mesh_map` | solver grid colored by topography |
| `piezometric_map` | watertable elevation |
| `watertable_depth_map` | watertable depth |
| `seepage_map` | seepage zones |
| `hydrographic_network_reference` | observed BD Topage network |
| `hydrographic_network_generated` | network delineated from the DEM |
| `hydrographic_network_comparison` | observed vs. delineated, with metrics |
| `simulated_active_network` | active draining cells |
| `simulated_active_network_reference_overlay` | simulated active network over the observed network |
| `accumulation_map` | accumulated drainage flow |
| `cross_section` | topography / watertable / 5 layers cross section |
| `water_budget` | budget per component |

## The K sweep

`run_manual.py` varies K over five decades, from 1e-8 to 1e-3 m/s in ten
log-spaced values, one simulation per value. The active drainage density,
the share of catchment cells with positive routed drain flow, collapses as
K increases: a more transmissive aquifer lowers the watertable, so fewer
cells feed a drain.

| K (m/s) | drainage density (%) | seepage (%) | baseflow (m3/s) |
|---|---|---|---|
| 1.0e-08 | 100 | 100 | 0.337 |
| 4.6e-07 | 95.3 | 93.3 | 0.337 |
| 1.7e-06 | 57.9 | 49.5 | 0.343 |
| 6.0e-06 | 16.1 | 14.3 | 0.344 |
| 2.2e-05 | 5.3 | 4.8 | 0.314 |
| 1.0e-03 | 0.2 | 0.2 | 0.000 |

The baseflow column is not plotted, it is only in the CSV: as long as the
watertable outcrops it is set by recharge, past 1e-5 m/s the aquifer routes
the flow underground and it drops along with the network.

The script writes three figures specific to the example under
`share/hydraulic_conductivity_sweep/`, plus the table above as a CSV:

| Figure | What it shows |
|---|---|
| `sweep_active_network.png` | one map per K, observed network overlaid |
| `sweep_water_table.png` | one watertable per K on the same west-east cross section |
| `sweep_drainage_density.png` | drainage density and seepage against K |

It also serves as an entry point to the Python API: open a project, run
several simulations with a parameter override, read back a field, a derived
view and a budget, and render a registry figure. Everything goes through
public commands, with no hand-built path.

## Switching to MODFLOW-NWT

Replace the solver and the section prefix:

```toml
[[simulation.process]]
id = "flow_main"
type = "flow"
solvers = ["modflow_nwt"]

[modflownwt.sgrid.planar]
mode = "keep_native"

[modflownwt.sgrid.vertical]
genmtd_lay = "constant"
nlay = 5
```
