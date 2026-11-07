# hydromodpy_annex/solver/nwt_postprocess

The historical TIFF maps of a MODFLOW-NWT run, read from its head and budget files. They cover the water table and its depth, the seepage areas, the drain outflow, the groundwater flux and storage, the outlet discharge, a persistency index and the seepage intermittency by year, month, week and day.

The code lives in the annex because the run workflow never calls it. A run reads its results through `hydromodpy/solver/modflow_nwt/extractors/`, so the wheel has no need for these maps. Three scripts still call them: one in example 12 and two diagnostics of the Brutsaert recession case in `validation_cases/`.

Call `run_post_processing(model, options)` from `run.py`, with a `ModflowNwt` model that has run and a `ModflowPostprocessOptions` from `hydromodpy.solver.modflow_common.options`. The maps go under the `_postprocess` folder of the model. The downslope accumulation stays in the wheel, at `hydromodpy/solver/modflow_nwt/mt3dms/masstransfer.py`, because MT3DMS reads it too.

The annex is not in the wheel. Run a script that imports it from a checkout of the repository, with the repository root on `sys.path`.
