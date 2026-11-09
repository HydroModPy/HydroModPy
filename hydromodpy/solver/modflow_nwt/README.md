# solver/modflow_nwt

MODFLOW-NWT through FloPy, on a structured grid, with MODPATH and MT3DMS for transport. `flow_to_modflow_adapter.py` says that NWT is to be removed once the lakes run on MODFLOW 6, so its payload builders are not shared with MODFLOW 6.

## Parts

1. `nwt/` is the flow model. `nwt_solver.py` is `ModflowNwt` (pre-processing and processing), `nwt_config.py` is the `[solver.modflow_nwt]` table, `flow_to_modflow_adapter.py` turns the `Model` of the run into the NWT inputs, `payloads/` builds the CHD, recharge, ETP, well and drain records, `_pre_processing.py` assembles the FloPy packages, scales the rates to the solver time unit and checks that the layers connect, and `steady_initial_conditions.py` runs the steady initialization on `steady_variant` of the model.
2. `adapter.py` is the flow adapter. The transport adapters live in the files of their engine: the MT3DMS adapter, solver `mt3dms` of the transport registry, in `mt3dms/mt3dms.py`, and the MODPATH adapter, solver `modpath`, in `modpath/modpath.py`. Each answers `validate`, `build`, `run`, `extract` and `cleanup`, and builds from the frozen `Model` of its flow, the `SolverRun` of that flow and its own options, received in `build(model, options, slot, upstream)`. NWT has no `rerun`, because nothing in its model can change between two solves without a build.
3. `extractors/` read the flow, MODPATH and MT3DMS outputs into the store. The flow extractor takes the dry-cell sentinels from the options of the run, and the start date and the vertical layout from its `Model`.
4. `modpath/` and `mt3dms/` are the transport models. `mt3dms/masstransfer.py` is the downslope accumulation that MT3DMS reads. `modpath/resolvers.py` holds the raster and shapefile lookups of the MODPATH inputs, public because the annex reads them. They read the DEM grid and the catchment from `Model.geometry` through the solver's `inputs`.

The historical TIFF maps and the MODPATH post-processing are in `hydromodpy_annex/solver/nwt_postprocess/` and `hydromodpy_annex/solver/modpath_post/`. No adapter called them: a run reads its results through the extractors.

The adapter builds `ModflowNwt` in the folder and under the name of the `RunSlot`, and makes the name safe for the Fortran solver. `processing` lists the input files it wrote in `input_files`, and writes none when the run says they are written.

`ModflowNwt.pre_processing` receives the frozen `Model` and keeps it in `inputs`. It extrudes its grid from `Model.geometry.cells`, reads the DEM and the routing settings from `Model.geometry.raster`, and never changes the model. The transport models build the same way: MT3DMS and MODPATH work in the folder of the flow run, read its grid and its time steps on the `Model` of that flow, and read its head and budget files on disk. NWT writes the flow-transport link file of MT3DMS when a later transport run reads `face_flow` off it, a fact the runner puts in the `hand_off` member of the slot of the run. The seepage raster that MODPATH releases particles from, `zone_partic = "seepage_clip"`, is built by the MODPATH adapter from the head file of the flow, with the seepage rule the run store derives, and never by a read of the store during the solve.

`modflow_nwt` imports `base`, `modflow_common` and `modflow_grid`, never `modflow6` or `boussinesq`.
