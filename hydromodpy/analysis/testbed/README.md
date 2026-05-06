# Method Testbed Workflow

This package implements `workflow = "testbed"`: an orchestration and evidence
layer for controlled method experiments.

The testbed package does not implement mesh generation, flow solving, or
transport solving. It expands variants, writes self-contained child TOML files,
delegates those children to existing runners, then persists the evidence needed
to audit the experiment.

## Package Map

| File | Responsibility |
| --- | --- |
| `config.py` | Validates the `[testbed]` TOML contract and resolves paths. |
| `runtime.py` | Materializes child configs, runs child workflows, extracts metrics, and writes evidence files. |
| `__init__.py` | Public imports for `TestbedConfig` and `TestbedLauncher`. |

The CLI entry point lives outside this package:

- `hydromodpy/workflow_dispatch.py::run_testbed`
- `hydromodpy/cli/commands/run.py`

## Design Contract

The workflow is intentionally small and explicit.

1. A testbed owns an experimental matrix, not physics.
2. Every enabled variant becomes one child TOML under
   `<output_root>/_generated_configs/`.
3. Generated children are ordinary workflow files:
   `workflow = "mesh"` for `mesh_catchment`, or `workflow = "simulation"` for
   flow children.
4. Generated children never contain `[testbed]`.
5. Evidence files are always written, including dry plans with
   `execute = false`.

Supported pairs are currently:

| Subject | Runner | Generated child workflow |
| --- | --- | --- |
| `mesh` | `mesh_catchment` | `mesh` |
| `flow` | `simulation` | `simulation` |

## TOML Shape

```toml
workflow = "testbed"

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

[testbed.variant.overlay.flow.param.K.field_homogeneous]
value = "5e-6 m/s"

[[testbed.metric]]
name = "head_range_m"
source = "flow_metrics.head_range_m"
required = true
```

For `subject = "flow"`, `testbed.base_config` is mandatory. Keep `[testbed]`
outside the base simulation TOML so the base remains reusable by normal
simulation runs.

For `subject = "mesh"`, `base_config` is optional. Without it, the testbed TOML
itself is used as the base payload after removing `[testbed]`.

## Runtime Sequence

1. Load and validate `TestbedConfig`.
2. Load the base TOML with `load_toml_with_base_config`.
3. Remove `[testbed]` from the child payload.
4. Absolutize path-like values before writing generated children.
5. Merge each variant overlay.
6. Write one generated child TOML per enabled variant.
7. Persist `testbed_plan.json`, `testbed_cases.csv`, `testbed_metrics.csv`,
   `testbed_manifest.json`, and `testbed_report.md`.
8. If `execute = true`, run children sequentially and rewrite evidence after
   each child completes or fails.

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

## Adding A New Subject

To add a future subject such as `transport`:

1. Add the subject to `SUPPORTED_SUBJECTS`.
2. Add the subject-runner pair to `SUPPORTED_SUBJECT_RUNNERS`.
3. Add the runner-to-workflow mapping to `RUNNER_WORKFLOWS`.
4. Add a branch in `TestbedLauncher._run_case`.
5. Add catalog extraction only if the child runner can persist structured
   results that should become testbed metrics.
6. Add a dry-plan test, an execution test with a fake runner, and at least one
   documentation example.

Do not make the testbed package depend on solver internals. Prefer reopening
persisted result stores or consuming runner summaries.

## Validation

Targeted checks:

```powershell
python -m pytest tests/unit/launchers/test_testbed_launcher.py tests/unit/launchers/test_hmp_simulation_cli.py -q
python -m ruff check hydromodpy/analysis/testbed hydromodpy/workflow_dispatch.py hydromodpy/workflow/dispatch.py hydromodpy/cli/commands/run.py tests/unit/launchers/test_testbed_launcher.py tests/unit/launchers/test_hmp_simulation_cli.py
python -m compileall -q hydromodpy/analysis/testbed hydromodpy/workflow_dispatch.py hydromodpy/workflow/dispatch.py hydromodpy/cli/commands/run.py
```

Example dry plans:

```powershell
hmp run examples/projects/10_testbed_workflow/mesh_resolution_testbed.toml
hmp run examples/projects/10_testbed_workflow/flow_k_sensitivity_testbed.toml
```

Both starter files default to `execute = false`; switch to `true` only after
inspecting generated child configs.
