# Install

HydroModPy needs Python 3.11, 3.12 or 3.13. The current pre-release is `2.0.0a4`.

## Install the package

```bash
python -m venv .venv
source .venv/bin/activate
pip install --pre hydromodpy
```

The `--pre` flag is needed while version 2 is published as `2.0.0aN`. Without it, pip
installs the latest stable release, which is version 1.

The package installs two commands, `hmp` and `hydromodpy`. They are the same program.
Check the version:

```bash
hmp --version
```

## Get the solver binaries

MODFLOW 6, MODFLOW-NWT, MODPATH and MT3D-USGS are not part of the package. They are
downloaded into `~/.cache/hydromodpy/bin/` the first time a solver runs. To fetch them
now, for example before going offline:

```bash
hmp install-binaries
```

`hmp install-binaries --help` lists the options: `--subset mf6,mfnwt` to take only some of
them, `--bindir` for another folder, `--upgrade` to download again. The environment
variable `HMP_BIN` points HydroModPy at a folder of your own binaries.

## Check the install

```bash
hmp doctor
```

`hmp doctor` prints one line per check: Python version, the core dependencies, the
optional ones (`gmsh`, `whitebox_workflows`, `geopandas`, `pyvista`), each solver binary,
and the workspace (`~/hydromodpy`, or the one you give with `--workspace`). It exits with an error code when a
check is `KO`.

## Optional extras

Add an extra between brackets: `pip install --pre "hydromodpy[ide,viewer3d]"`.

| Extra | Adds |
|---|---|
| `ide` | JupyterLab, Spyder, PySide6 |
| `viewer3d` | PyVista, for 3D views of the mesh |
| `calibration` | `cma` and `cmaes`, for the CMA-ES variants. The default `optuna` sampler is in the base install |
| `mesh` | `gmsh` |
| `mf6api` | `modflowapi` and `xmipy` |
| `viz` | `datashader` and `lttb` |
| `fair` | `pystac`, `stac-validator` and `rocrate` |

To work on HydroModPy itself (editable clone, tests, docs), see {doc}`../contribute/index`.

## Next

Learn the four words the rest of the documentation uses: {doc}`concepts`.
