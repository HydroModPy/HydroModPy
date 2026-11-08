# `hydromodpy/workflow/steps`

The thirteen steps of a run, one module per concern. Each module exposes `step_*`
functions and a `*Step` class that adapts them to the `Step` protocol
(`workflow/step.py`). `sequence.py` gives the order; the names are those of
`core/pipeline_steps.py:STEP_NAMES`.

## Import rules

`workflow` may import every layer below it (`tests/unit/architecture/layer_matrix.yaml`).
Inside the package, `steps/` imports `record`, `state`, `step` and `runner`. Nothing
in `record/`, `state.py` or `step.py` imports `steps`. A step never opens the index of
the project; it writes through `run_store(ctx)`. Its `reads`, `writes` and
`config_sections` are exact (checked by `tests/unit/architecture/test_step_payload_keys.py`).

## Modules

In the order `standard_steps()` calls them. Helpers follow the step that uses them.

| module | what it answers |
|---|---|
| `sequence.py` | `standard_steps()`: the thirteen steps in order |
| `validate.py` | step `validate`: is the file valid before anything is built |
| `resolve.py` | step `resolve`: workspace paths and the `WorkflowContext` |
| `setup.py` | steps `build_geographic` and `setup_process`: geographic context, domain, spatial supports, then the process objects |
| `data.py` | step `load_data`: the data of `[data]`, bound to the runtime |
| `data_description.py` | what a data load read, and the `data_description` document that says so |
| `mesh.py` | step `build_mesh`: plan one request, build the cell mesh, cache it |
| `mesh_inputs.py` | what the mesh planner reads besides `[mesh]` from the run context |
| `planning.py` | the `SimulationPlan` and the per-cell budget it keeps |
| `prepare_solver/` | step `prepare_solver`: opens the run (see its README) |
| `run_solver.py` | step `run_solver`: executes the plan with `SimulationRunner`, and puts back the `SolverRun` of each run when a resume starts after it |
| `extract.py` | step `extract`: solver files read into the store, observations ingested, and `retention_of`, what the run keeps |
| `run_outputs.py` | what happens after a solve, each on the `RunContext` of one run: `extract_run_outputs` calls the `extract` of the adapter with the `SolverRun` and the `Retention`, `derive_run_outputs` and `cleanup_solver_outputs` follow, and `extract.py`, `derive.py` and `export.py` call them |
| `derive.py` | step `derive`: catchment aggregates, observation points, fit metrics |
| `display.py` | step `display`: the figures of `[display]` |
| `export.py` | steps `export` and `seal`: the `[[export]]` requests, the scratch cleanup, then the seal |
| `dependencies.py` | `earliest_affected_step`: the first step a set of overrides reaches |
| `calibration.py` | the calibration session report and the trial pipeline provider |

## Tree

```
steps/
  sequence.py        order of the thirteen
  validate.py  resolve.py  setup.py  data.py  mesh.py  run_solver.py
  extract.py  derive.py  display.py  export.py     one module per step
  run_outputs.py  data_description.py  mesh_inputs.py  planning.py  helpers of a step
  dependencies.py  calibration.py                  used by trials
  prepare_solver/    the step that opens the run
```

## Where to add what

| to add | where |
|---|---|
| a step | a module here with its `step_*` function and `*Step` class, exported by `__init__.py`, placed in `sequence.py` and its name in `core/pipeline_steps.py`, with `depends_on`, `reads`, `writes` and `config_sections` |
| a persistent step | `artifacts` and `rebuild_state` on the step, so a resume can skip it |
| a way to bind loaded data | a function in `data.py` calling the binder of `model/boundaries/` or `model/domain/` |
| something done after the solve | a function in `run_outputs.py` and its call in the matching step (`extract.py`, `derive.py` or `export.py`) |
| a config section that moves a step | `config_sections` of the step (read by `dependencies.py`) |
| something written when the run opens | `prepare_solver/` |
