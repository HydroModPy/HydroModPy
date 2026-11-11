# MODFLOW 6 backend

MODFLOW 6 through FloPy: a GWF flow model, and GWT or PRT transport on the same simulation. It is a backend of the solver port of `solver/base`. It reads `base`, `modflow_common` and `modflow_grid`, never `modflow_nwt` or `boussinesq`.

## What it receives

The flow adapter (`adapter.py`) receives the frozen `Model`, the `[solver.modflow6]` table of `modflow6_config.py` and a `RunSlot`, and builds `Modflow6` in the folder and under the name of the slot. `Modflow6` keeps the `Model` as `inputs` and never changes it. The start heads of a restart arrive on the model as a `PriorState`. The two transports, GWT in `transport.py` and PRT in `prt.py`, receive the `Model` of their flow, the `SolverRun` of that flow and the options of their `[transport.<name>]` table, and they add their model to the simulation of the flow, in its folder.

## What it returns

`run` writes the input files unless the run already holds them, solves with the `mf6` executable or in process through `libmf6`, and returns the `SolverRun`. The extractor writes the heads, the per-cell budget, the listing balance, the lake and stream series, and `final_state/`, the last head in float64 and the last lake and reach stages, which the next run or window reads first. A chain of windows gives back the run in one piece to the bit. A run with `keep_face_flows` writes `face_flow/` beside `connection_cells/`. GWT writes concentrations and PRT particle tracks.

## What it declares

The flow is `name = "modflow6"`, `process_type = "flow"`, `accepted_meshes` the `regular`, `triangle` and `voronoi` engines and any planar engine that is not lumped, `geometry = "cells"`, `category = "distributed"`, no `native_step`, `mutable = {"K", "Sy"}` and no `requires`. Its `supports` covers every boundary of the closed table, the drain options, the `head_rule`, `steady_start`, `cyclic_start` and `prior_state` starts, recharge, wells, ETP, the flow barriers and the cutoff wall, the soil reservoir, the K tensor and the layering. The transports are `modflow6` and `modflow6_prt` of `process_type = "transport"`, with `requires = (("flow", "modflow6"),)`.

## How it registers and what it refuses

The built-in paths are `flow_modflow6`, `transport_modflow6` and `transport_modflow6_prt` of `_BUILTIN_PATHS` in `solver/base/registry.py`, each with its extractor. `rerun` (`rerun.py`) solves a model that differs by K, Sy or both, and returns `None` so the runner builds when the change needs a build, when the start is a steady or cyclic solve, or when the simulation carries a transport. On Windows, a workspace whose paths `mf6` cannot open is refused before the solve. Through `libmf6` the run reads the stop flag at the end of each time step, and through `mf6` it reads nothing.

## What tests it

`tests/ports/test_solver.py` holds the three classes to the port, and `tests/unit/solver/modflow6/` holds the builders, the extractors and the rerun.
