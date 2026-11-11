# `hydromodpy/project`

A project driven from Python: one object, `Project`, that holds a validated configuration,
builds the model once and runs it as often as asked. `Project` is no execution engine, it calls
the workflow layer, so the interactive route and the TOML route share the same steps. The same
package carries the adapters that bind a workflow name to a `Project`, and `replay.py` plays a
sealed run or a published copy again and classes what it compared. `project` sits above the
matrix and reads every layer; no lower layer reads it, the package root and `cli` excepted. One
global crosses to a lower layer: the trial pipeline of `calibration/runners/trial.py`, filled
here by `fill_trial_pipeline`. No other adapter is wired through a global. Each entry that reads
the pipeline fills it: `route_calibration`, `calibrate_project`, `promote_trial` and `rerun_config`.
The command line fills nothing.

`api.py` holds the fifteen verbs that `hydromodpy` and `hmp` expose, and its `__all__` is these fifteen. A
verb takes text, numbers, paths and mappings and gives back a value with `to_dict`, a path or
diagnostics, so a server sends what it gets. A reference is a path, a name read in `workspace`, or
the object; nothing is looked for above the working directory. `kept_readers.py` holds `read`,
`index` and `Catalog`, which the top level keeps beside the verbs because the runs of 2.0.0 are
read through them.

| verb | what it does |
|---|---|
| `open` | Gives the project, run, session or workspace a path stands for. |
| `run` | Runs a simulation or an overview and gives its `RunOutcome`, or its plan with `dry_run`. |
| `check` | Gives every diagnostic of a document or a file. |
| `calibrate` | Runs a calibration, or gives its `CalibrationPlan` with `dry_run`. |
| `spinup` | Repeats a window until the state settles, then runs from it if asked. |
| `replay` | Plays a sealed run or a copy again and classes its values. |
| `stop` | Writes the stop flag of a running run or session. |
| `status` | Gives the outcome of each run and session, read from the disk, or the plan of a project. |
| `trash` | Moves a run or a session to `trash/`, or brings it back. |
| `compare` | Compares sealed runs, the first one as the reference. |
| `show` | Reads one line of `show.SHOWN`: a summary, a table, a field, a figure, a report. |
| `export` | Writes data of a run to files, or delivers its `[[export]]` blocks. |
| `publish` | Copies a run, the summary or a whole project out of the tree. |
| `example` | Lists, shows or installs a shipped example. |
| `doctor` | Says what this machine runs. |

The answers column below is the first line of each module or sub-package docstring.

| module | answers |
|---|---|
| `accessors.py` | Read-only views of a project, its sessions and its workspace. |
| `api.py` | The fifteen public verbs of HydroModPy, the ones `hydromodpy` and `hmp` expose. |
| `calibrate.py` | The routing of a calibration: which runner a declaration goes to. `write_session_reports` writes the session reports once the search is over; `report=False` skips it. |
| `check_source.py` | What `check` reads in a configuration: a document, a file and its chain, a `[sites]` project. |
| `compare.py` | Compare sealed runs of one site: what differs, when, where, against the gauge. |
| `credentials.py` | The reader of `credentials.toml`, one identity per address prefix. |
| `data_cache.py` | The data cache seen from a project: the lockfile, and what a prune must keep. |
| `deliver.py` | Deliver the export files of a sealed run to folders and remote servers. |
| `doctor.py` | What this machine runs: Python, HydroModPy, the packages and the solver executables. |
| `dispatch/` | The adapters that need `Project` and that lower layers must not import. |
| `environment.py` | The environment of one verb call: its credentials file and its bounds. |
| `examples/` | The shipped examples behind `hmp example`. |
| `exchange/` | Publish a run with its inputs, install a published copy, replay it. |
| `facade.py` | High-level Project API for interactive Python usage. |
| `kept_readers.py` | The three readers the top level keeps beside the verbs: read, index and Catalog. |
| `launch/` | The launcher of a `[sites]` project: plan, lease, launch, status, collect. |
| `old_paths.py` | The old public paths the top level refuses, with what answers in their place. |
| `phases.py` | Model-phase adapter verbs used by `Project`. |
| `replay.py` | Replay a sealed run or a published copy, and class what it compared. |
| `report.py` | The reports of a sealed run and of a calibration session: `report_run` and `report_session`. It is the one place that assembles the texts (`results/method.py`, `schema/phrases.py`) and the pages (`display/report/`). |
| `request.py` | The request of a run: one form for a TOML file, a dict, JSON, a server and Docker. |
| `run_overrides.py` | The `set=` of a run, as changes of its configuration. |
| `runner.py` | Run-phase orchestration for `hydromodpy.project.facade.Project`. |
| `show.py` | What `show` reads, one line per value of `what`, and the function that draws. |
| `spinup.py` | Cyclic spin-up driver: repeat a forcing window until the state stabilizes. |
| `state.py` | Mutable state container for `hydromodpy.project.facade.Project`. |
| `trial_pipeline.py` | Trial pipeline implementation backed by the project and workflow packages. |
| `windows.py` | Cut a long transient run into windows and play them one after the other. |
