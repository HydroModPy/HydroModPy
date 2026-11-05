# `hydromodpy/workflow/steps/prepare_solver`

The step that turns a built model into a run on disk: it plans the simulation, binds
the pipeline to its run directory, records the facts of the run, persists the inputs
and freezes the configuration into `config.toml` and `config.resolved.toml`.
`PrepareSolverStep` lives in `__init__.py`, the only name it exports.

## Import rules

Same as `steps/`: `workflow` may import every layer below it
(`tests/unit/architecture/layer_matrix.yaml`), and this folder imports `record`,
`state` and `step`, never the reverse. `resolved.py` is read by
`workflow/replay_checks.py` at the root.

## Modules

In the order a run reaches them: `__init__` plans, `dispatch` opens the run (it calls `facts`, `freeze`, `resolved` and `prepare`), then `__init__` persists the provenance and the forcings.

| module | what it answers |
|---|---|
| `__init__.py` | `PrepareSolverStep`: the order of the work below |
| `dispatch.py` | binds the pipeline to its run directory and records what the run was built from (`bind_run_directory`, `initial_facts`, `step_open_run`) |
| `restart.py` | `[flow] restart_from` by reference: a run name, a `sim_id` or a path (`resolve_restart_source`) |
| `facts.py` | the facts of the run, the config snapshot and the artifact paths (`collect_run_facts`, `store_sim_artifacts`) |
| `freeze.py` | freezes the configuration the run was built from (`freeze_run_config`) |
| `resolved.py` | `config.resolved.toml`: the whole configuration a run used, and the drift a replay compares (`config_drift`, `build_drift`) |
| `prepare.py` | persists params, mesh, geographic data and provenance (`step_persist_params`, `step_write_provenance`) |
| `forcings.py` | persists the input forcings of the run (`step_persist_forcings`) |

## Tree

```
prepare_solver/
  __init__.py   PrepareSolverStep
  dispatch.py   open the run
  restart.py    restart source
  facts.py      facts of the run
  freeze.py     freeze the config
  resolved.py   config.resolved.toml and drift
  prepare.py    persist params, mesh, provenance
  forcings.py   persist forcings
```

## Where to add what

| to add | where |
|---|---|
| a fact recorded at the start of a run | `facts.py` (and a field of `RunFacts` in `results/storage/run_facts.py`) |
| a new input persisted for the run | `forcings.py` (forcings) or `prepare.py` (params, mesh, geographic) |
| a form of `restart_from` | `restart.py` |
| a key of the frozen configuration | `freeze.py`; the resolved form, `resolved.py` |
| work done when the run directory opens | `dispatch.py` |
