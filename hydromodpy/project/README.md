# project

The public face of HydroModPy. `api.py` holds the fifteen verbs that `hydromodpy` and `hmp` expose: `open`, `run`, `check`, `calibrate`, `spinup`, `replay`, `stop`, `status`, `trash`, `compare`, `show`, `export`, `publish`, `example` and `doctor`. A verb takes text, numbers, paths and mappings and gives back a value with `to_dict`, a path or diagnostics, so a server sends what it gets. A reference is a path, a name read in `workspace`, or the object itself, and nothing is looked for above the working directory. `kept_readers.py` keeps `read`, `index` and `Catalog` at the top level beside the verbs.

`Project` is one object that holds a validated configuration, builds the model once and runs it as often as asked. It is no execution engine, because it calls the workflow layer, so the interactive route and the TOML route share the same steps. `launch/` runs a `[sites]` project as one process per case, `exchange/` publishes, installs and replays a copy of a run, `dispatch/` binds a workflow name to the call that runs it, and `examples/` serves `hmp example`.

It sits above the layer matrix and reads every layer below it. Only the package root, `cli` and `hydromodpy_server` read it. One global crosses to a lower layer, the trial pipeline of `calibration/runners/trial.py`, which `fill_trial_pipeline` fills here.

The page of the package in the developer docs lists the modules and tells how the folders fit together and where to add what.
