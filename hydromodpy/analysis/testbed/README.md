# Method Testbed Workflow

This package implements `[workflow].mode = "testbed"`: an orchestration and evidence
layer for controlled method experiments.

The testbed package does not implement mesh generation, flow solving, or
transport solving. It expands variants, writes self-contained child TOML files,
delegates those children to existing runners, then persists the evidence needed
to audit the experiment.

## Package Map

| File | Responsibility |
| --- | --- |
| `config.py` | Validates the `[testbed]` TOML contract and resolves paths. |
| `catalog_variants.py` | Expands optional catalog rows into concrete testbed variants. |
| `contracts.py` | Registers workflow adapters and delegates child execution. |
| `profiles.py` | Resolves `[testbed].profile` and routes specialized profiles. |
| `regional_lab_adapter.py` | Projects regional site x recipe cases onto testbed cases. |
| `regional_lab.py` | Runs the regional catalog profile backed by `[regional_lab]`. |
| `regional_lab_*.py` | Regional profile config, catalog, planning, reporting, and bootstrap helpers. |
| `runtime.py` | Materializes child configs, runs child workflows, extracts metrics, and writes evidence files. |
| `site_selection_catalog.py` | Resolves `site_selection_manifest.json` outputs as catalog sources. |
| `__init__.py` | Public imports for `TestbedConfig` and `TestbedLauncher`. |

The CLI entry point lives outside this package:

- `hydromodpy/project/dispatch/workflow.py::run_testbed`
- `hydromodpy/cli/commands/run.py`

## Design Contract

The workflow is intentionally small and explicit.

1. A testbed owns an experimental matrix, not physics.
2. Every enabled variant becomes one child TOML under
   `<output_root>/_generated_configs/`.
3. Variants may be explicit `[[testbed.variant]]` blocks or generated from a
   CSV/JSONL `[testbed.catalog]` plus `[[testbed.variant_from_catalog]]`
   overlay templates. A catalog may be addressed directly with `path` or
   through `from_site_selection_manifest`.
4. Generated children are ordinary workflow files:
   `[workflow].mode = "simulation"` for mesh, flow, and transport children, or
   `[workflow].mode = "comparison"` / `"calibration"` for comparison and
   calibration children. Mesh-only children use `[[simulation.process]]` with
   `type = "mesh"` and `backend = "catchment"`.
5. Generated children never contain `[testbed]`.
6. Evidence files are always written, including dry plans with
   `execute = false`.

`regional_lab` is the regional catalog profile of this general campaign model.
New regional campaigns can enter through `[workflow].mode = "testbed"` with
`[testbed].profile = "regional_lab"`. The profile keeps regional concepts such
as site selection, cluster rules, status/maturity fields, coverage gaps, and
recipes, but shares the common catalog loader in `hydromodpy.analysis.catalog`,
the site-selection manifest catalog resolver, and the child-runner contract
used by generic testbeds.

Supported pairs are currently:

| Subject | Runner | Generated child workflow |
| --- | --- | --- |
| `mesh` | `simulation` | `simulation` |
| `flow` | `simulation` | `simulation` |
| `flow` | `comparison` | `comparison` |
| `flow` | `calibration` | `calibration` |
| `transport` | `simulation` | `simulation` |
| `transport` | `comparison` | `comparison` |

## TOML Shape

```toml
[workflow]
mode = "testbed"

[testbed]
id = "flow_k_sensitivity"
subject = "flow"
purpose = "robustness"
base_config = "flow_base.toml"
output_root = "outputs/flow_k_sensitivity"
execute = false

[testbed.runner]
type = "simulation"
no_display = true

[[testbed.variant]]
id = "low_k"
axis = "hydraulic_conductivity"

[testbed.variant.overlay.flow.param.K.field]
value = "5e-6 m/s"

[[testbed.metric]]
name = "head_range_m"
source = "flow_metrics.head_range_m"
required = true
```

For `subject = "flow"`, `testbed.base_config` is mandatory when the runner is
`simulation`, `comparison` or `calibration`. Keep `[testbed]` outside the base
child TOML so the base remains reusable by normal simulation, comparison or
calibration runs.

With `runner.type = "comparison"`, the base config is a normal
`[workflow].mode = "comparison"` TOML. A catalog-backed variant typically renders
`comparison.comparison_id`, `comparison.output_root`, and
`comparison.base_simulation_overlay`. The comparison launcher then applies that
shared base overlay to every generated child simulation before applying each
solver-specific `comparison.simulation.overlay`.

When no `[[testbed.metric]]` block is declared for `runner.type = "comparison"`,
the testbed writes a small default comparison summary to `testbed_metrics.csv`:
comparison id, audit status, row counts, and numerical-closure diagnostics when
the comparison produced them. Use explicit `[[testbed.metric]]` blocks only when
a campaign needs a non-default metric set.

With `runner.type = "calibration"`, the base config is a normal
`[workflow].mode = "calibration"` TOML. The testbed materializes one
calibration child per variant and delegates execution through the registered
workflow adapter. Declare explicit `[[testbed.metric]]` blocks for the
calibration summary fields that should be promoted to `testbed_metrics.csv`.

For `subject = "mesh"`, `base_config` is optional. Without it, the testbed TOML
itself is used as the base payload after removing `[testbed]`.

## Site-Selection Catalogs

Generic testbeds and regional-lab profiles can consume the stable
`site_selection_manifest.json` hand-off. The catalog resolver reads the
manifest `outputs` map and turns the selected output into the actual CSV path.
The default output key is `regional_lab_sites_csv`; use `output` to select a
different manifest output.

Generic testbed catalog:

```toml
[testbed.catalog]
from_site_selection_manifest = "../17_site_selection_workflow/outputs/aura_area_only_v1/site_selection_manifest.json"
output = "regional_lab_sites_csv"
id_field = "site_id"
label_field = "site_label"
axis_field = "region_id"
tags_field = "tags"
```

Regional-lab catalog:

```toml
[regional_lab.catalog]
from_site_selection_manifest = "../17_site_selection_workflow/outputs/aura_area_only_v1/site_selection_manifest.json"
output = "regional_lab_sites_csv"
site_id_field = "site_id"
site_label_field = "site_label"
region_field = "region_id"
tags_field = "tags"
```

The resolved catalog path and source manifest provenance are written into
`testbed_manifest.json`, `regional_lab_plan.json` and
`regional_lab_report.json`.

## Runtime Sequence

1. Load and validate `TestbedConfig`.
2. Load the base TOML with `load_toml_with_base_config`.
3. Remove `[testbed]` from the child payload.
4. Absolutize path-like values before writing generated children.
5. Merge each variant overlay.
6. Write one generated child TOML per enabled variant.
7. Persist `testbed_plan.json`, `testbed_cases.csv`, `testbed_metrics.csv`,
   `testbed_manifest.json`, and `testbed_report.md`.
8. If `execute = true`, run children sequentially through the registered
   workflow adapter and rewrite evidence after each child completes or fails.

## Flow Catalog Metrics

Flow children delegate to the normal simulation workflow. After a child run,
`runtime.py` tries to reopen the result through the `SimulationCatalog` and
adds these summary blocks:

- `catalog`: run identity, solver, status, duration, cell count, timestep count.
- `parameters`: persisted scalar parameters.
- `budget`: component totals for inflow, outflow, and net flow.
- `mass_balance`: scalar mass-balance indicators.
- `field_summary`: summary statistics for persisted fields.
- `flow_metrics`: flat scalar keys suitable for `[[testbed.metric]]`.

Known metric examples from the smoke-tested flow starter:

- `flow_metrics.duration_s`
- `flow_metrics.n_cells`
- `flow_metrics.param_K`
- `flow_metrics.max_abs_mass_balance_percent_error`
- `flow_metrics.head_range_m`
- `flow_metrics.budget_chd_total_out`
- `flow_metrics.budget_rcha_total_in`

Budget component names come from solver outputs. For MODFLOW 6, prescribed
heads are exposed as `chd`; recharge is exposed as `rcha` in the current
starter case.

## Evidence Files

| File | Use |
| --- | --- |
| `testbed_plan.json` | Planned variants and generated child config paths. |
| `testbed_cases.csv` | One row per variant with status, runner, child config, and child artifacts. |
| `testbed_metrics.csv` | Declared metrics or flattened numeric child summaries. |
| `testbed_manifest.json` | Machine-readable contract for the whole testbed run. |
| `testbed_report.md` | Compact human summary. |

Read outputs in this order: generated configs, cases CSV, metrics CSV,
manifest, report.

## Adding A New Runner Or Subject

To add a future subject:

1. Add the subject to `SUPPORTED_SUBJECTS`.
2. Add the subject-runner pair to `SUPPORTED_SUBJECT_RUNNERS`.
3. Add a dry-plan test, an execution test with a fake runner, and at least one
   documentation example.

To add a future runner:

1. Add a `TestbedWorkflowAdapter` implementation in `contracts.py`, or register
   one with `register_testbed_workflow_adapter()`.
2. Expose the corresponding provider method on `TestbedRunnerProvider` and
   `ProjectTestbedRunnerProvider`.
3. Add the subject-runner pair to `SUPPORTED_SUBJECT_RUNNERS`.
4. Add default metrics or child-artifact extraction only if the child runner can
   persist structured results that should become testbed metrics.
5. Add a dry-plan test, an execution test with a fake runner, and at least one
   documentation example.

Do not make the testbed package depend on solver internals. Prefer reopening
persisted result stores or consuming runner summaries.

## Validation

Targeted checks:

```powershell
python -m pytest tests/unit/launchers/test_testbed_launcher.py tests/unit/launchers/test_hmp_simulation_cli.py -q
python -m ruff check hydromodpy/analysis/testbed hydromodpy/project/dispatch/workflow.py hydromodpy/workflow/dispatch.py hydromodpy/cli/commands/run.py tests/unit/launchers/test_testbed_launcher.py tests/unit/launchers/test_hmp_simulation_cli.py
python -m compileall -q hydromodpy/analysis/testbed hydromodpy/project/dispatch/workflow.py hydromodpy/workflow/dispatch.py hydromodpy/cli/commands/run.py
```

Example dry plans:

```powershell
hmp run examples/projects/10_testbed_workflow/mesh_resolution_testbed.toml
hmp run examples/projects/10_testbed_workflow/flow_k_sensitivity_testbed.toml
hmp run examples/projects/18_site_selection_to_testbed/site_selection_catalog_testbed.toml
hmp run examples/projects/18_site_selection_to_testbed/site_selection_regional_lab.toml
```

Both starter files default to `execute = false`; switch to `true` only after
inspecting generated child configs.
