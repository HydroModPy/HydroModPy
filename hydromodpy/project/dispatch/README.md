# `hydromodpy/project/dispatch`

The adapters that need the public `Project` and that lower layers must not import.
`workflow.py` binds a workflow name (`simulation`, `overview`, `calibration`) to the
call that runs it for `hmp run` and `hmp.run`; `rerun.py` reruns a recorded run through a `Project`
for `hmp catalog rerun`. It replays the run from its configuration, which has nothing to do with the
`rerun` of a solver adapter.

## Import rules

`dispatch/` sits inside `hydromodpy/project`, which is above the layer matrix
(`tests/unit/architecture/layer_matrix.yaml`). It is the one place in `project` that imports
`Project` outside `TYPE_CHECKING`, and only inside functions. `launch/` and `exchange/`
never do. `__init__.py` re-exports nothing: import from `dispatch.workflow` or
`dispatch.rerun`. `cli` calls `rerun_config` directly, and no lower layer reaches `rerun.py`.

## Modules

| module | what it answers |
|---|---|
| `workflow.py` | which function runs a workflow name (`DISPATCH`, `dispatch_workflow`); one adapter per workflow (`run_simulation`, `run_overview`, `run_calibration`); whether a plain run was already sealed with the same resolved config (`completed_identical_run`) |
| `rerun.py` | how a recorded run is rerun through a `Project` (`rerun_config`, which returns the new `Run` or `None`) |

## Tree

```
dispatch/
  workflow.py   DISPATCH, dispatch_workflow, run_simulation, run_overview, run_calibration
  rerun.py      rerun_config
```

## Where to add what

| to add | where |
|---|---|
| a workflow name | a `run_*` function and an entry in `DISPATCH` in `workflow.py`; the name list lives in `hydromodpy/workflow/dispatch.py` |
| a run option reaching `hmp run` | the keyword of `run_simulation`, same as on `Project.execute` |
| a provider for a lower layer | a class here, a Protocol and a `register_*` in the lower layer, a hook in `hydromodpy/_bootstrap.py` |
