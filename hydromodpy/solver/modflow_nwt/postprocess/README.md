# solver/modflow_nwt/postprocess

The maps `ModflowNwt.post_processing` writes as TIFF files from the head and budget files of a run. The workflow does not call it: a run reads its results through `modflow_nwt/extractors/`. It stays for the scripts that call it.

## Modules

1. `run.py` is `run_post_processing`: it reads the files, computes the maps the options ask for and writes them.
2. `fields.py` computes the water table, its depth, the seepage areas, the drain outflow, the groundwater flux and storage, and the outlet discharge.
3. `intermittency.py` writes the yearly, monthly, weekly and daily intermittency of the seepage.
4. `masstransfer.py` accumulates a flow or a mass downslope on the grid. MT3DMS post-processing reads it too.
5. `binary_reader.py` opens the head and budget files at the precision NWT wrote them.
