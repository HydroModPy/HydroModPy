# 04 - Data overview

The Nançon at Lécousse, a 64.6 km² catchment near Fougères (Ille-et-Vilaine,
EPSG:2154), built from one outlet coordinate and nothing else.
`[workflow].mode = "overview"` runs the data-only pipeline: no mesh, no
solver. Every layer comes from a public French service; no file ships with
this example, the DEM included.

## Run

```bash
hmp run examples/projects/04_data_overview/project.toml
```

Needs network access. No service asks for a key. About 30 s once the caches
exist. The first run also downloads the BD ALTI archive of the department and
the BRGM departmental map; everything lands in `examples/data/`.

## Data

| Family | Source | Role |
|---|---|---|
| dem | IGN Geoplateforme, BD ALTI 25 m | catchment delineation, elevation maps |
| geology | BRGM 1:50 000 departmental map | lithology map |
| hydrography | Sandre BD TOPAGE | reference stream network |
| hydrometry | Hub'Eau, product `QmnJ` | daily discharge at Lécousse |
| piezometry | Hub'Eau, product `level` | groundwater level at Louvigné-du-Désert |
| intermittency | Hub'Eau ONDE | flow-state observations |
| water_quality | Hub'Eau river quality | nitrates, water temperature, conductivity |
| precipitation, etp | Météo-France SIM2 | monthly climatic summary |

No section names a path or a bounding box, and only the piezometer is named:
no piezometer lies inside the catchment, so the nearest one still recording,
11 km north, is asked for by its BSS code. Every other source is asked over
the delineated watershed, and every time series inherits the `[overview]`
window, 2019 to 2025.

## What it shows

One figure per panel of `[overview.panels]`, all on by default: the regional
situation, DEM with stations, geology and BD TOPAGE maps, a stats card, the
discharge, piezometry, ONDE and water quality series, the P/ETP monthly
summary and a station inventory. To turn one off, add the table and set its
key to `false`.
