# Regional Lab Pilot 2026-04-12

This folder contains one local pilot built from real data available on the
current machine.

## Source data

- `C:\Users\dreuzy\HydroModPy\catchment_identification_scan\headwater_100km2\exutoires_headwater_100km2.csv`
- `C:\Users\dreuzy\HydroModPy\mesh_catchment_runs\s3_10km2\identification\exutoires_s3_10km2.csv`
- `C:\Users\dreuzy\HydroModPy\mesh_catchment_runs\s3_10km2\`
- `C:\Users\dreuzy\HydroModPy\mesh_gallery_headwater_100km2_outlet_27_rivers_only\`

## Generated catalogs

- `headwater_100km2_catalog_full.csv`
- `s3_10km2_catalog_full.csv`
- `site_catalog_pilot_20.csv`

The combined pilot catalog keeps:

- 10 `headwater_100km2` sites
- 10 `s3_10km2` sites

Only `headwater_100km2_outlet_2` is currently wired to existing child configs
stored in the repository. The other sites are intentionally kept as inventory
or mesh-ready candidates so the regional-lab report can expose coverage gaps.

## Pilot run

Run the dry expansion with:

`python -m launchers regional-lab run reporting/regional_lab_pilot_2026-04-12/config_regional_lab_pilot.toml`

The generated summaries land under:

- `outputs/regional_pilot_2026_04_12/regional_lab_plan.json`
- `outputs/regional_pilot_2026_04_12/regional_lab_report.json`
- `outputs/regional_pilot_2026_04_12/regional_lab_site_inventory.csv`
- `outputs/regional_pilot_2026_04_12/regional_lab_recipe_summary.csv`
- `outputs/regional_pilot_2026_04_12/regional_lab_cluster_summary.csv`
- `outputs/regional_pilot_2026_04_12/regional_lab_summary.md`

This pilot is intentionally machine-local because the catalog contains paths
discovered under `C:\Users\dreuzy\HydroModPy\...`.

## Current result

The dry regional-lab expansion has been run once on `2026-04-12` and currently
produces:

- 20 selected sites
- 3 planned child runs
- 37 skipped site x recipe pairs reported as coverage gaps
- 0 executed child runs because the config stays in `execute = false`

Current coverage snapshot:

- `headwater_100km2`: 10 sites, 3 planned runs, 27 gaps
- `s3_10km2`: 10 sites, 0 planned runs, 10 gaps

Recipe snapshot:

- `headwater_mf6_reference`: 1/10 sites wired
- `headwater_backend_compare`: 1/10 sites wired
- `headwater_transient_backend_compare`: 1/10 sites wired
- `s3_future_reference`: 0/10 sites wired
