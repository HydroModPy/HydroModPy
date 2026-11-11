# MODFLOW-NWT backend

MODFLOW-NWT through FloPy, on a structured grid, with MODPATH and MT3DMS for transport. It is a backend of the solver port of `solver/base`, kept until the lakes run on MODFLOW 6, so its payload builders are not shared with MODFLOW 6. It reads `base`, `modflow_common` and `modflow_grid`, never `modflow6` or `boussinesq`.

## What it receives

The flow adapter (`adapter.py`) receives the frozen `Model`, the `[solver.modflow_nwt]` table of `nwt/nwt_config.py` and a `RunSlot`, and builds `ModflowNwt` in the folder and under the name of the slot, with a name made safe for the Fortran solver. `ModflowNwt.pre_processing` keeps the `Model` in `inputs` and never changes it. It extrudes its grid from `Model.geometry.cells` and reads the DEM and the routing settings from `Model.geometry.raster`. MT3DMS (`mt3dms/mt3dms.py`) and MODPATH (`modpath/modpath.py`) receive the `Model` of their flow, its `SolverRun` and their own options, work in the folder of the flow and read its head and budget files on disk.

## What it returns

`processing` lists the input files it wrote in `input_files`, and writes none when the run says they are written. The flow extractor writes the heads, the budget, the listing balance and `final_state/`, the last head in float64 with the dry-cell sentinels as NaN. A run with `keep_face_flows` writes `face_flow/` beside `connection_cells/`, built from `FLOW RIGHT FACE`, `FLOW FRONT FACE` and `FLOW LOWER FACE`, each positive towards the larger flat index `k * nrow * ncol + i * ncol + j`, and a pair that touches a cell with `ibound = 0` is left out. NWT writes the flow-transport link file of MT3DMS when a later transport reads `face_flow` off it, a fact the runner puts in `hand_off`.

## What it declares

The flow is `name = "modflow_nwt"`, `process_type = "flow"`, `accepted_meshes = {"regular"}`, `geometry = "raster"`, `category = "distributed"`, no `native_step`, an empty `mutable` (no `rerun`, because nothing in its model changes between two solves without a build) and no `requires`. Its `supports` lists the side, ocean and drainage boundaries, the drain options, `head_rule` and `steady_start`, recharge, wells, ETP, the properties and the layering. The transports are `mt3dms` and `modpath`, with `requires = (("flow", "modflow_nwt"),)`.

## How it registers and what it refuses

The built-in paths are `flow_modflow_nwt`, `transport_mt3dms` and `transport_modpath` of `_BUILTIN_PATHS` in `solver/base/registry.py`, each with its extractor. A file that asks for a lake, SFR, a stream boundary or any trait outside `supports` is refused when it is read. NWT runs an executable, so a stop asked during the solve waits for its end. `tests/ports/test_solver.py` holds the three classes to the port.
