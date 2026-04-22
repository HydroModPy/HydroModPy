# `regional_lab` example

This folder contains one first versioned `regional_lab` example built on top of
one small regional population.

Run the dry-plan expansion with:

`python -m launchers regional-lab run examples/projects/launcher_simulation/regional_lab/config_headwater_100km2_lab.toml`

Three focused overlays are also versioned when you want to inspect one recipe in
isolation without changing the shared catalog or cluster rules:

- `python -m launchers regional-lab run examples/projects/launcher_simulation/regional_lab/config_headwater_100km2_lab_mf6_reference.toml`
- `python -m launchers regional-lab run examples/projects/launcher_simulation/regional_lab/config_headwater_100km2_lab_backend_compare.toml`
- `python -m launchers regional-lab run examples/projects/launcher_simulation/regional_lab/config_headwater_100km2_lab_transient_backend_compare.toml`

Those overlays keep only one `[[regional_lab.recipe]]` enabled and write into
their own output folders, which makes them easier to use as reproducible
documentation or recipe-specific smoke examples.

The example intentionally starts with `execute = false` so the launcher writes:

- `outputs/headwater_100km2_lab/regional_lab_plan.json`
- `outputs/headwater_100km2_lab/regional_lab_report.json`
- `outputs/headwater_100km2_lab/regional_lab_site_inventory.csv`
- `outputs/headwater_100km2_lab/regional_lab_recipe_summary.csv`
- `outputs/headwater_100km2_lab/regional_lab_cluster_summary.csv`
- `outputs/headwater_100km2_lab/regional_lab_summary.md`

without launching the child simulation or method-comparison runs.

The key point of the example is the site catalog contract:

- `site_catalog.csv` carries stable site metadata (`site_id`, `source_selection_id`,
  `site_status`, `maturity`, `region_id`, `tags`, `enabled`);
- the same catalog row also carries launcher-ready asset/config references such
  as `simulation_reference_config` and `backend_comparison_config`;
- the cluster identity is assigned through explicit `[[regional_lab.cluster_rule]]`
  rules rather than only through static `cluster_id` columns;
- recipes stay generic and simply consume those fields through
  `config_path_template` and `required_fields`.

In the committed example, only `headwater_100km2_outlet_2` is fully runnable.
The other headwater sites stay in the selected population but are reported as
coverage gaps for the three recipes because the child configs are intentionally
missing.

Once the expanded plan looks correct, switch `execute = true` in
`config_headwater_100km2_lab.toml` to run the selected child launchers.
