# `hydromodpy/project`

A project driven from Python: one object, `Project`, that holds a validated configuration,
builds the model once and runs it as often as asked. `Project` is no execution engine, it calls
the workflow layer, so the interactive route and the TOML route share the same steps. The same
package carries the adapters that bind a workflow name to a `Project`, and `replay.py` plays a
sealed run or a published copy again and classes what it compared. `project` sits above the
matrix and reads every layer; no lower layer reads it, the package root and `cli` excepted. One
global crosses to a lower layer: the trial pipeline of `calibration/runners/trial.py`, filled
here by `fill_trial_pipeline`. No other adapter is wired through a global. The answers column
below is the first line of each module or sub-package docstring.

| module | answers |
|---|---|
| `accessors.py` | Read-only views of a project, its sessions and its workspace. |
| `api.py` | The public verbs that the facade `hydromodpy` imports from `project`. |
| `calibrate.py` | The routing of a calibration: which runner a declaration goes to. |
| `compare.py` | Compare sealed runs of one site: what differs, when, where, against the gauge. |
| `credentials.py` | The reader of `credentials.toml`, one identity per address prefix. |
| `data_cache.py` | The data cache seen from a project: the lockfile, and what a prune must keep. |
| `dispatch/` | The adapters that need `Project` and that lower layers must not import. |
| `environment.py` | The environment of one verb call: its credentials file and its bounds. |
| `examples/` | The shipped examples behind `hmp example`. |
| `exchange/` | Publish a run with its inputs, install a published copy, replay it. |
| `facade.py` | High-level Project API for interactive Python usage. |
| `launch/` | The launcher of a `[sites]` project: plan, lease, launch, status, collect. |
| `phases.py` | Model-phase adapter verbs used by `Project`. |
| `replay.py` | Replay a sealed run or a published copy, and class what it compared. |
| `request.py` | The request of a run: one form for a TOML file, a dict, JSON, a server and Docker. |
| `run_overrides.py` | The `set=` of a run, as changes of its configuration. |
| `runner.py` | Run-phase orchestration for `hydromodpy.project.Project`. |
| `spinup.py` | Cyclic spin-up driver: repeat a forcing window until the state stabilizes. |
| `state.py` | Mutable state container for `hydromodpy.project.Project`. |
| `trial_pipeline.py` | Trial pipeline implementation backed by the project and workflow packages. |
| `windows.py` | Cut a long transient run into windows and play them one after the other. |
