# 06 - Vire and Selune watersheds

Two Normandy/Brittany catchments delineated from outlet coordinates in
EPSG:2154, on the shared `DEM_armorican_massif.tif` (75 m). Vire (~1258 km2,
outlet `x=400866.1983 y=6923974.693`) and Selune (~367 km2, outlet
`x=379541.3716 y=6845659.878`) share the same config layering: a common
`project_simulation*.toml` base, and a `run_*.toml` overlay per solver and
regime. Transient runs use homogeneous K/Ss/Sy with a top drainage boundary
and SIM2 recharge; steady runs use geology-zoned K from a CSV transfer table
and a constant synthetic recharge.

## Run

```bash
hmp run examples/projects/06_vire_selune/overview_vire.toml                       # watershed overview, hubeau gauges
hmp run examples/projects/06_vire_selune/overview_selune.toml
hmp run examples/projects/06_vire_selune/run_vire_nwt.toml                        # transient, MODFLOW-NWT, structured grid
hmp run examples/projects/06_vire_selune/run_selune_nwt.toml
hmp run examples/projects/06_vire_selune/run_vire_mf6_irregular_steady.toml       # steady, MODFLOW 6, geology+river conformal mesh
hmp run examples/projects/06_vire_selune/run_selune_mf6_irregular_steady.toml
hmp report catchment examples/projects/06_vire_selune/catchment_report_vire.toml  # overview + run + HTML report, one command
```

Unmeasured: the first run of any config downloads DEM-derived delineation,
BD Topage hydrography, Hub'Eau gauging stations, and SIM2 recharge over the
network, and the mf6 irregular runs need a Gmsh-backed mesh build plus the
MODFLOW 6 binary.

Also present: `run_vire_mf6_regular.toml`, `run_vire_mf6_irregular.toml`,
`run_vire_nwt_steady.toml`, `run_vire_nwt_report.toml` (and the matching
Selune files) for the other solver/regime/grid combinations.

## Data

| Source | Family | Role |
|---|---|---|
| `dem/DEM_armorican_massif.tif` | dem | regional 75 m DEM, covers both outlets |
| `geology/GEO1M.shp`, provider `brgm_1m` | geology | BRGM 1:1,000,000 map, context and zoning |
| `geology/geology_K_dummy_demo.csv` | geology | demonstration K transfer table, `dummy_demo_not_for_scientific_use` |
| BD Topage, provider `bdtopage` | hydrography | river network |
| Hub'Eau, provider `hubeau` | hydrometry | gauging stations, in the overview configs |
| SIM2, provider `sim2` | recharge | transient recharge, in the transient configs |
| synthetic recharge | recharge | constant annual average, `220 mm/an`, in the steady configs |

## What it shows

`project_simulation.toml` and `project_simulation_steady.toml` hold everything
shared: geographic setup, domain, flow physics. Each `run_*.toml` overlays
only what changes: solver (`modflow_nwt` or `modflow6`), grid (regular or
irregular/Gmsh), and regime (steady or transient). The steady irregular runs
set `constraints_mode = "geology_rivers"` under `[mesh_catchment]` so the
generated mesh follows both river lines and geology interfaces.

`catchment_report_vire.toml` and `catchment_report_selune.toml` drive
`hmp report catchment`: run the overview, run the transient simulation, then
build one HTML report from both.
