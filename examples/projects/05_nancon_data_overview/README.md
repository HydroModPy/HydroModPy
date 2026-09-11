# 05 - Nançon data overview

Nançon catchment (Brittany, EPSG:2154), delineated from outlet coordinates on
the regional 75 m DEM. Overview workflow only, no groundwater solver runs.
`config_overview.toml` loads the full set of data families (geology,
hydrography, hydrometry, piezometry, intermittency, climate series) and
renders every identity-card panel. `config_hydrography_only.toml` is the
minimal case: it loads only BD Topage hydrography and renders
`map_hydrography` over the DEM background.

## Run

```bash
hmp run examples/projects/05_nancon_data_overview/config_overview.toml
hmp run examples/projects/05_nancon_data_overview/config_hydrography_only.toml
```

`--dry-run` resolves either config in about 4 s. A full run downloads BD
Topage, BRGM geology and Hub'Eau/SIM2 time series over the network; duration
is unmeasured here.

## Data

| Source | Family | Role |
|---|---|---|
| `data/dem/DEM_armorican_massif.tif` | dem | regional 75 m DEM, outlet-based delineation |
| BD Topage, provider `bdtopage` | hydrography | observed stream network, both configs |
| BRGM 1:1M, provider `brgm_1m` | geology | lithology map, full config only |
| Hub'Eau, provider `hubeau` | hydrometry, piezometry, intermittency, water_quality | discharge, groundwater level, ONDE and quality stations, full config only |
| SIM2, provider `sim2` | precipitation, etp, temperature, recharge, runoff, wind, humidity, radiation, soil_moisture | climate and recharge series, full config only |

## What it shows

`config_overview.toml` turns on every panel: DEM map, geology map,
hydrography map, stats card, discharge and piezometry time series, climatic
summary, station inventory. `config_hydrography_only.toml` turns every panel
off except `map_hydrography`, so the same workflow can be pointed at one data
family at a time.
