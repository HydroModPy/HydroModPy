# 09 - Transport model for an agricultural catchment

Kervidy-Naizin catchment (Brittany, EPSG:2154), a long-observed agricultural
headwater. **Monthly transient** flow over a drought year with **MODFLOW 6**,
coupled to a **MODFLOW 6 GWT** model that carries nitrate: the aquifer starts
at 100 mg/L, the recharge brings 50 mg/L in, with a first-order decay of
two-year mean life.

The theme is what the aquifer does to a solute applied at the land surface:
how long the old water keeps feeding the stream, and where the concentration
stays high when the recharge stops for eight months.

## Run

```bash
hmp run examples/projects/09_transport_model_for_an_agricultural_catchment/project.toml

# one map per timestep, then a GIF and an HTML slider
python examples/projects/09_transport_model_for_an_agricultural_catchment/build_concentration_animation.py
```

Runtime: about 7 minutes, the heaviest example of the set (five layers over
~10 000 cells, 12 monthly periods, 5 solver steps per period, flow then
transport).

## Data

| File | Family | Role |
|---|---|---|
| `dem/DEM_naizin_25m.tif` | dem | 25 m DEM, a 12 km window centred on the outlet |
| `hydrography/naizin_stream_network.gpkg` | hydrography | BD Topage 2024, with its perennial / intermittent attribute |
| synthetic recharge | recharge | drought year: 2 mm/d from November to February, 0 otherwise |

The DEM and the network are windows cut from the legacy raster and shapefile
(8 MB and 3 MB), down to 500 KB and 540 KB.

## The unit traps of transport

`[transport.modflow6gwt.parameters]` runs on the SI seconds clock while the
flow model runs in days:

| Key | Unit | Here |
|---|---|---|
| `sconc_init`, `sconc_input` | kg/m³ | 0.1 and 0.05, i.e. 100 and 50 mg/L |
| `diffu_coeff` | m²/**s** | 1e-10 |
| `rate_decay` | **1/s** | 1.585e-8, a two-year mean life |
| `disp_transh`, `disp_transv` | **ratios** of `disp_long` | 0.1 and 0.01, i.e. 0.5 m and 0.05 m |

A per-day value in `diffu_coeff` or `rate_decay` is 86400 times too large, and
an absolute transverse dispersivity in `disp_transh` gets multiplied by
`disp_long`.

## Figures

| Figure | What it shows |
|---|---|
| `watershed_id_card` | catchment identity card |
| `mesh_map` | solver grid |
| `piezometric_map` | water-table elevation |
| `watertable_depth_map` | water-table depth |
| `seepage_map` | seepage areas |
| `concentration_map` | nitrate per cell, at the end of the drought |
| `concentration_boxplot` | distribution of the nitrate over the domain, month by month |
| `hydrographic_network_reference` | observed network |
| `simulated_active_network` | network the water table sustains |
| `hydrograph` | simulated baseflow |
| `flux_timeseries` | budget components over time |
| `water_budget` | budget per component |
| `mass_balance_error` | solver closure error per timestep, water and solute |

## Differences with the legacy example

| Point | legacy | here |
|---|---|---|
| Flow | MODFLOW-NWT | MODFLOW 6 |
| Transport | MT3DMS | MODFLOW 6 GWT |
| Timestep | 52 weekly periods | 12 monthly periods |
| Layers | 10 | 5 |
| Pathlines | MODPATH backward from the seepage areas | see example 06 |
| GIF and slider | matplotlib loop inside the script | `build_concentration_animation.py`, registered figure |
| Concentration boxplot | numpy stats drawn by hand | registered figure `concentration_boxplot` |
| `Ss` | 1e-10 | 1e-9, the schema's physical floor |

The legacy recharge signal was already monthly: it built a weekly series then
filtered it by month. Monthly periods therefore lose nothing and divide the
cost by four.

Two internal inconsistencies of the legacy script are settled here:
`sconc_init` is 100 mg/L (its own comment said 50), and `disp_transh` /
`disp_transv` are read as ratios, the reading its own figure legend gave
(0.5 m and 0.05 m).
