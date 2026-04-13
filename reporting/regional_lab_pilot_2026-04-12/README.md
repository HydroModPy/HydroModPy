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
- `headwater_100km2_outlet_27` keeps local mesh assets and now also has one
  generated local replay config using a sanitized bundle fallback derived from
  `z_top_mean` / `z_bottom_mean`;
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
- `outputs/regional_pilot_2026_04_12/regional_lab_case_matrix.csv`
- `outputs/regional_pilot_2026_04_12/regional_lab_execution_metrics.csv`
- `outputs/regional_pilot_2026_04_12/regional_lab_recipe_summary.csv`
- `outputs/regional_pilot_2026_04_12/regional_lab_cluster_summary.csv`
- `outputs/regional_pilot_2026_04_12/regional_lab_summary.md`

This pilot is intentionally machine-local because the catalog contains paths
discovered under `C:\Users\dreuzy\HydroModPy\...`.

## Current result

The dry regional-lab expansion has been rerun on `2026-04-12` and now
produces:

- 20 selected sites
- 12 planned child runs
- 29 skipped site x recipe pairs reported as coverage gaps
- 0 executed child runs because the config stays in `execute = false`

Current dry coverage snapshot:

- `headwater_100km2`: 10 sites, 2 planned runs, 29 gaps
- `s3_10km2`: 10 sites, 10 planned runs, 0 gaps

Recipe snapshot:

- `headwater_mf6_reference`: 1/10 sites wired
- `headwater_backend_compare`: 0/10 sites runnable on this Windows machine
  because the child recipe is now marked `allowed_platforms = ["linux"]`
- `headwater_transient_backend_compare`: 0/10 sites runnable on this Windows
  machine for the same reason
- `headwater_local_boussinesq_replay`: 1/1 site wired
- `s3_future_reference`: 10/10 sites wired

## Executed pilot

The executed config has also been rerun:

`python -m launchers regional-lab run reporting/regional_lab_pilot_2026-04-12/config_regional_lab_pilot_execute.toml`

Current execute snapshot:

- 12 planned cases
- 29 skipped cases
- 1 freshly executed case
- 11 reused cases from the previous execute report
- 1 failed case

Operational interpretation:

- the 10 `s3_10km2` local replays are runtime-qualified and now tagged
  `runtime_smoke_ready` in `site_catalog_pilot_20.csv`
- `headwater_100km2_outlet_2` remains runtime-qualified through the repository
  `mf6` reference config
- `headwater_100km2_outlet_27` now has one runnable local replay config, but
  the replay still fails at runtime and is tagged `runtime_smoke_failed`
- the two backend-comparison recipes are no longer executed on Windows and are
  reported as `unsupported_platform` coverage gaps instead of hard failures

## Runtime qualification

The pilot catalog is now synchronized from the executed `regional_lab` report
through:

`python reporting/regional_lab_pilot_2026-04-12/sync_runtime_smoke_to_catalog.py`

This appends per-site runtime fields such as:

- `runtime_smoke_status`
- `runtime_smoke_recipe_id`
- `runtime_smoke_reused_from_report`
- `runtime_smoke_runtime_backend`
- `runtime_smoke_solve_stage`
- `runtime_smoke_residual_norm_inf`

The current runtime status is:

- passed: outlets `2, 6, 7, 8, 9, 10, 11, 12, 13, 14`
- excluded from the curated pilot after failure: outlet `5`
- failed after local sanitized replay generation:
  `headwater_100km2_outlet_27`

The local replay base in `child_configs/base_local_boussinesq_mesh_replay.toml`
uses `runtime_max_iterations = 200` to make the regional smoke runs less
fragile than the historical headwater example.
