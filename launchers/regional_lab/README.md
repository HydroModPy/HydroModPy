# Regional Lab Launcher

`launchers/regional_lab/` provides one orchestration layer for regional
laboratories built on top of existing launcher families.

The intent is to keep three levels separate:

- the site catalog: which sites are available in one region;
- the recipes: which launcher-backed question should be applied to those sites;
- the execution/reporting layer: which concrete site x recipe runs were planned
  and which ones were executed.

## Scope

The launcher does not replace `simulation`, `mesh_catchment`, or
`method_comparison`.

It expands a declarative regional-lab configuration into concrete child runs
and executes them sequentially through the existing launcher CLI.

## Current MVP

The current version supports:

- CSV or JSONL site catalogs;
- global site selection by `site_id`, `cluster_id`, `region_id`, `family`,
  `scale`, `status`, `maturity`, and `tags`;
- recipe-local filters using the same selectors;
- explicit `[[regional_lab.cluster_rule]]` enrichment rules on top of catalog rows;
- site-contract normalization for labels, provenance, maturity, optional XY/area,
  and path-like asset fields resolved from the catalog directory;
- `simulation` and `method-comparison` child launchers;
- `config_path_template` placeholders based on site metadata;
- recipe-level `required_fields` to distinguish runnable cases from coverage gaps;
- resume/skip semantics based on an existing `regional_lab_report.json`;
- synthesis artifacts: site inventory, case matrix, recipe/cluster/region/family/scale summaries,
  plus one Markdown executive summary.

## CLI

Run one regional-lab config:

`python -m launchers regional-lab run path/to/config_regional_lab.toml`

Print the canonical template:

`python -m launchers regional-lab template`

Bootstrap one `site_catalog.csv` from an outlets table and an optional mesh
batch manifest:

`python -m launchers regional-lab bootstrap-catalog --help`

The bootstrap helper can also scan one `mesh_run_root` directly to discover
`mesh_output_mesh`, `mesh_summary_json`, `mesh_bundle_dir`, and figures by
`outlet_id` when the batch manifest is missing or stale.

When one `mesh_bundle_dir` is available, the bootstrap also inspects the bundle
against the current Boussinesq contract and adds:

- per-bundle counters such as `bundle_missing_top_centroid_count`,
  `bundle_missing_storage_coefficient_count`, and
  `bundle_invalid_vertical_geometry_count`;
- readiness flags `bundle_boussinesq_steady_ready` and
  `bundle_boussinesq_transient_ready`;
- readiness tags `boussinesq_steady_ready` and
  `boussinesq_transient_ready` when the bundle satisfies those profiles.

This keeps `mesh_ready` separate from `solver-ready`: one site may have a
usable mesh asset while still being unsuitable for one replay recipe.

## Template Keys

`config_path_template` can reference:

- canonical aliases: `site_id`, `cluster_id`, `region_id`, `lab_id`,
  `recipe_id`, `recipe_label`, `cluster_family`, `cluster_scale`,
  `site_status`, `maturity`
- any raw field present in the site catalog row
- any field listed under `regional_lab.catalog.path_fields`, resolved to an
  absolute path from the catalog directory

## Recommended Usage

Use `execute = false` first to verify the expanded plan and resolved config
paths. Once the plan looks correct, switch to `execute = true`.

## Versioned Example

One first repository-backed example lives under:

`examples/projects/launcher_simulation/regional_lab/config_headwater_100km2_lab.toml`

It demonstrates three contract choices for `regional_lab`:

- recipe templates do not need to derive child config paths from naming
  conventions alone; they can consume explicit site-level fields from the
  catalog such as `simulation_reference_config` or `backend_comparison_config`;
- cluster identities can be assigned through explicit enrichment rules fed by
  `source_selection_id`;
- one laboratory can carry both runnable sites and inventory-only sites, with
  the latter reported as coverage gaps rather than hard failures.
