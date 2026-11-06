# solver/modflow6/support

What the MODFLOW 6 build, run and extraction share.

## Modules

1. `names.py`: the model name MODFLOW 6 accepts (16 characters, no space) and the output stem that stays below the Windows path limit.
2. `computational_top.py`: the computational top `T' = G + (Dmax - D)` the DISV carries, so that under Newton every raised top cell has the same thickness and the conductance carries no thickness bias, and the ground sidecar the store reads back.
3. `property_mapping.py`: K, K33 and the K tensor on the solver mesh, in the NPF arguments.
4. `steady_initial_conditions.py`: the auxiliary steady solve or cyclic spin-up whose final heads start the run.
5. `time_series.py`: the TS6 files of a non-constant lake or stream forcing.
6. `lake_band_runoff.py`: the runoff of the exposed band of a lake, coupled in process through `libmf6`.
7. `windows_paths.py`: refuses a workspace whose paths MODFLOW 6 cannot open on Windows.
8. `written_grid.py`: how far the grid FloPy writes (rounded text, clockwise rings) may differ from the stored mesh.
9. `flopy_header_cache.py` and `flopy_structure_warmup.py`: two FloPy patches, one for long chronicles, one for parallel calibration trials. They go once FloPy fixes both.
