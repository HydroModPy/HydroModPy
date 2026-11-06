# solver/modflow_nwt

MODFLOW-NWT through FloPy, on a structured grid, with MODPATH and MT3DMS for transport. `flow_to_modflow_adapter.py` says that NWT is to be removed once the lakes run on MODFLOW 6, so its payload builders are not shared with MODFLOW 6.

## Parts

1. `nwt/` is the flow model. `nwt_solver.py` is `ModflowNwt` (pre-processing, processing, post-processing), `nwt_config.py` is the `[modflownwt]` table, `flow_to_modflow_adapter.py` turns a `Flow` into the NWT inputs, `payloads/` builds the CHD, recharge, ETP, well and drain records, `_pre_processing.py` assembles the FloPy packages, scales the rates to the solver time unit and checks that the layers connect, and `steady_initial_conditions.py` runs the steady initialization.
2. `adapters/` are the three registry adapters: flow, MODPATH, MT3DMS.
3. `extractors/` read the flow, MODPATH and MT3DMS outputs into the store.
4. `modpath/` and `mt3dms/` are the transport models.
5. `postprocess/` is the historical TIFF post-processing of `ModflowNwt.post_processing`: water table, seepage, drain outflow, persistence and intermittency maps, and the downslope accumulation (`masstransfer.py`). No adapter calls it: a run reads its results through the extractors.

`modflow_nwt` imports `base`, `modflow_common` and `modflow_grid`, never `modflow6` or `boussinesq`.
