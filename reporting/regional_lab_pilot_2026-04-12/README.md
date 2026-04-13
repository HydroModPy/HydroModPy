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
- `child_configs/`

The combined pilot catalog keeps:

- 10 `headwater_100km2` sites
- 10 `s3_10km2` sites

The full catalogs are now bootstrap-enriched with bundle validation fields such
as `bundle_missing_top_centroid_count`,
`bundle_boussinesq_steady_ready`, and
`bundle_boussinesq_transient_ready`.

The current pilot is intentionally curated:

- `headwater_100km2_outlet_2` stays wired to repository child configs;
- `headwater_100km2_outlet_27` keeps local mesh assets but is withheld from
  replay generation because its bundle misses 6 topography centroids;
- the 10 retained `s3_10km2` sites are all `boussinesq_steady_ready`;
- `s3_10km2_outlet_5` was removed from the curated pilot after one runtime
  smoke failure, and replaced by `s3_10km2_outlet_14`.

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
- 13 planned child runs
- 27 skipped site x recipe pairs reported as coverage gaps
- 0 executed child runs because the config stays in `execute = false`

Current coverage snapshot:

- `headwater_100km2`: 10 sites, 3 planned runs, 27 gaps
- `s3_10km2`: 10 sites, 10 planned runs, 0 gaps

Recipe snapshot:

- `headwater_mf6_reference`: 1/10 sites wired
- `headwater_backend_compare`: 1/10 sites wired
- `headwater_transient_backend_compare`: 1/10 sites wired
- `s3_future_reference`: 10/10 sites wired

## Runtime qualification

The local `s3_10km2` replays have also been smoke-tested outside the
`regional_lab` dry plan:

- passed: outlets `2, 6, 7, 8, 9, 10, 11, 12, 13, 14`
- excluded from the curated pilot after failure: outlet `5`
- excluded before generation because the bundle is not steady-ready:
  `headwater_100km2_outlet_27`

The local replay base in `child_configs/base_local_boussinesq_mesh_replay.toml`
uses `runtime_max_iterations = 200` to make the regional smoke runs less
fragile than the historical headwater example.
