# 17 - Site selection workflow

The `site_selection` workflow screens candidate monitoring sites over a French
administrative territory (Lambert-93, the IGN Geoplateforme DEM's native CRS)
against hard-reject, warning and soft-score criteria: station influence, area
range, geology, basin overlap. Candidates come from three input modes:
pre-delineated catchments (CSV), Hub'Eau hydrometric stations, or DEM-generated
outlets by flow accumulation. There is no groundwater solver here; basin
delineation uses the IGN Geoplateforme DEM, optionally snapped to a BD Topage
reference network.

## Run

```bash
hmp site-selection plan configs/bretagne_hydrometry_primary.toml       # validate a config, print the resolved plan
hmp run configs/calvados_dem_area_light_100km2_fast.toml               # DEM-generated candidates, one department
hmp run configs/bretagne_hydrometry_50_500_small.toml                  # Hub'Eau stations, direct DEM snap
hmp run configs/bretagne_hydrometry_50_500_small_bdtopage.toml         # same stations, snapped via BD Topage
hmp run configs/auvergne_rhone_alpes_hydrometry_preview.toml           # Hub'Eau stations, region-wide DEM
hmp run configs/corse_hydrometry_preview.toml                          # Hub'Eau stations, region-wide DEM
```

`hmp site-selection plan` takes about 8 s, all Python import cost, no network
call. Every `hmp run` above downloads an IGN DEM tile or queries Hub'Eau on
first use, so its runtime depends on network and on what the local DEM cache
already holds; unmeasured here.

## Data

No shared inputs under `examples/data/`. Each config declares its own DEM
source under `[site_selection.dem]` (IGN Geoplateforme, BD ALTI, 25 m) and its
own fixtures under `fixtures/`: pre-delineated catchment CSVs with their basin
GeoJSON, and a small synthetic DEM for offline checks.

## What it shows

Four ways to feed the same selection pipeline:

| Config | Input mode | Territory |
|---|---|---|
| `bretagne_hydrometry_primary.toml` | pre-delineated catchments, CSV | Bretagne |
| `bretagne_hydrometry_50_500_small.toml` / `_bdtopage.toml` | Hub'Eau stations | Bretagne |
| `auvergne_rhone_alpes_area_only.toml` | pre-delineated catchments, CSV | Auvergne-Rhone-Alpes |
| `calvados_dem_area_light_100km2_fast.toml` | DEM-generated candidates | Calvados (one department) |

Every run writes `selected_sites.csv` and `rejected_sites.csv` under
`output_root`. With `[site_selection.output] write_report_html = true`, set in
all the configs above, it also writes `review/index.html` and
`review/site_selection_map.png`.
