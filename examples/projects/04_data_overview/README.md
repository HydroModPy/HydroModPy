# 04 - Data overview

A small unnamed catchment in Brittany (EPSG:2154), delineated from an outlet
coordinate on the regional 75 m DEM. `[workflow].mode = "overview"` runs the
data-only pipeline: no mesh, no solver. It builds the catchment and a
50 m constant-thickness domain, loads geology, hydrography, hydrometry,
intermittency and coastal water level data, and renders a panel of context
figures.

## Run

```bash
hmp run examples/projects/04_data_overview/project.toml
```

Runtime: about 20 s, most of it spent fetching Hub'Eau, ONDE and SHOM data
over the network.

## Data

| Source | Family | Role |
|---|---|---|
| `dem/DEM_armorican_massif.tif` | dem | regional 75 m DEM, catchment delineation |
| BRGM 1:1 000 000 geology, provider `brgm_1m` | geology | geological context map |
| `hydrography/regional_stream_network.shp` (`FID`) | hydrography | custom stream network overlay |
| Hub'Eau, product `QmnJ` | hydrometry | monthly discharge, 2019-2025 |
| Hub'Eau, ONDE stations | intermittency | intermittency observations, 2019-2025 |
| SHOM sea level | oceanic | nearest tide gauge, January 2003 |

## What it shows

The `[overview.panels]` table turns each figure on or off independently:
DEM, geology and hydrography maps, a stats card, discharge and intermittency
time series, and a station inventory. Piezometry, climatic summary and water
quality panels are declared but switched off here because this catchment has
no data for them; the panel table is the place to toggle what a data-overview
run reports without touching the loading logic.
