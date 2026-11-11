# workflow

The order in which a project is built and run. A file such as `step4_transient.toml` becomes thirteen steps, from validation to the seal of the run. Each step takes an immutable `PipelineState`, does its part and returns the next one. A `Pipeline` chains the steps, records them in the journal of the run and can resume a run from the artifacts of the steps already done. The `Project` facade and every workflow launcher, simulation or calibration, call these steps, so one file always drives one lifecycle.

A run writes its own directory and nothing else. It never opens the index of the project, and nothing here imports `hydromodpy.project`. `steps/` holds the thirteen steps and `steps/prepare_solver/` the step that opens the run. `record/` holds what a run writes about itself: the claim of its directory, its outcome, the step journal and the resume plan. The modules at the root hold the state, the step protocol, the pipeline, the step graph and the choice of a workflow from a file.

It reads every layer below it and nothing reads it but `project`, `cli` and the package root. A lower layer that needs a workflow function receives it as an argument, as calibration does through the `TrialPipeline` protocol.

The page of the package in the developer docs lists the modules, tells how a run goes through the steps and says where to add what.
