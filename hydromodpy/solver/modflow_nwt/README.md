# solver/modflow_nwt

MODFLOW-NWT through FloPy, on a structured grid, with MODPATH and MT3DMS for transport. `flow_to_modflow_adapter.py` says that NWT is to be removed once the lakes run on MODFLOW 6, so its payload builders are not shared with MODFLOW 6.

## Parts

1. `nwt/` is the flow model. `nwt_solver.py` is `ModflowNwt` (pre-processing and processing), `nwt_config.py` is the `[modflownwt]` table, `flow_to_modflow_adapter.py` turns the `Model` of the run into the NWT inputs, `payloads/` builds the CHD, recharge, ETP, well and drain records, `_pre_processing.py` assembles the FloPy packages, scales the rates to the solver time unit and checks that the layers connect, and `steady_initial_conditions.py` runs the steady initialization on `steady_variant` of the model.
2. `adapters/` are the three registry adapters: flow, MODPATH, MT3DMS.
3. `extractors/` read the flow, MODPATH and MT3DMS outputs into the store.
4. `modpath/` and `mt3dms/` are the transport models. `mt3dms/masstransfer.py` is the downslope accumulation that MT3DMS reads. `modpath/resolvers.py` holds the raster and shapefile lookups of the MODPATH inputs, public because the annex reads them. They read the DEM grid and the catchment from `Model.geometry` through the solver's `inputs`.

The historical TIFF maps and the MODPATH post-processing are in `hydromodpy_annex/solver/nwt_postprocess/` and `hydromodpy_annex/solver/modpath_post/`. No adapter called them: a run reads its results through the extractors.

`ModflowNwt.pre_processing` receives the frozen `Model` and keeps it in `inputs`. It extrudes its grid from `Model.geometry.cells`, reads the DEM and the routing settings from `Model.geometry.raster`, and never changes the model. The transport adapters still read `setup.domain` from the setup, because the transport models have no port yet.

`modflow_nwt` imports `base`, `modflow_common` and `modflow_grid`, never `modflow6` or `boussinesq`.
