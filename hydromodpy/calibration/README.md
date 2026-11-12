# calibration

Fitting model parameters to observations. A `[calibration]` table names the parameters to vary, the outputs to compare, the criterion that scores them and the search method. The package turns that table into a search. An optimizer proposes parameter values, one trial runs the model with them, the outputs are scored against the observations, and the session is written to disk as it goes.

The package is a layer because it sits above the solvers and below the entry points. It runs a solver only through the generic ports of `solver.base`, so a backend can be added or replaced without touching calibration. It never imports `display`.

A calibration occupies two sibling directories of one name, `sessions/<case>/` for what the search evaluated and `runs/<case>/` for the calibrated run. Inside the loop a trial lives in memory, and only a promoted trial becomes a run on disk.

`calibration` reads `core`, `schema`, `catchment`, `mesh`, `model`, `data`, `results`, `solver` and itself, as `tests/unit/architecture/layer_matrix.yaml` says. `config`, `workflow`, `project`, `cli` and the root facade read it. `workflow` is reached only through the `TrialPipeline` that `project` installs.

The two ports of the package are `optim/` (search methods) and `evaluation/` (what one trial answers), and each has its own README. The order of the parts and the modules other layers may import are in `tests/unit/architecture/calibration_layout.yaml`.

The page `docs/source/contribute/architecture/packages/calibration.rst` lists the modules and holds the ten steps of a calibration and where to add what. The phases are in `docs/source/how-to/write-calibration-phases.rst`.
