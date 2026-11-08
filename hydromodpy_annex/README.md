# hydromodpy_annex

Code that serves HydroModPy workflows but is not in the wheel. It reads `hydromodpy`, and `hydromodpy` never reads it. `test_annex_one_way` holds that rule, and a second test refuses any import of `tools` from `hydromodpy`.

The editable install knows only `hydromodpy`. A script that imports the annex runs from a checkout with the root of the repository on `sys.path`, as the tests and the examples do.

The export views are the one part reached from `hmp`. `export/stac.py` and `export/prov.py` hold the two `ExportWriter` classes of the export port, and the repository's `pyproject.toml` declares them on the `hydromodpy.export.format` entry-point group, so `hmp export --as stac` resolves them without `hydromodpy` ever importing the annex. An editable install resolves the group after a `pip install -e .`; a checkout on `sys.path` alone serves a Python import, and `hmp export` keeps refusing `stac` and `prov` with the entry point and its target in the message.

| folder | what it holds |
|---|---|
| `export/` | the STAC view and the standalone PROV view of a sealed run, on the export port (`results/exporters/`) |
| `physics/pyhelp/` | the PyHELP recharge model and its ERA5 and grid preprocessing. Example 10 runs it |
| `solver/boussinesq_picard/` | the Picard and L-scheme initializer of the Boussinesq solver. No backend selects it |
| `solver/nwt_postprocess/` | the TIFF maps of a MODFLOW-NWT run. `run_post_processing(model, options)` writes them |
| `solver/modpath_post/` | the MODPATH shapefiles (`write_shapefiles`) and the pathline filter (`filter_pathlines`) |
| `schema/job_chain/` | the runner that chains job directories and writes `chain-outcome.json` |
| `preprocess/` | the catchment identification scan |
| `postprocess/HCDM/` | the HCDM post-processing scripts |

Every folder of this table but `export/` has no `hmp` verb and no caller in the wheel, so it stays out of the package users install. The export views are reached from `hmp export --as`, which resolves them through the entry points.
