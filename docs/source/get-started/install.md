# Install

HydroModPy needs Python 3.11, 3.12 or 3.13. The current pre-release is `2.0.0a4`; the
{doc}`versions page <../about/versions>` lists the others. On a fast connection pip needs
about two minutes, and a clean environment weighs 1.3 GB: most of it is the geospatial and
scientific wheels.

## Install the package

::::{tab-set}
:sync-group: os

:::{tab-item} Linux and macOS
:sync: unix

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install --pre hydromodpy
```
:::

:::{tab-item} Windows
:sync: windows

In PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install --pre hydromodpy
```
:::

:::{tab-item} conda or micromamba
:sync: conda

You do not need a clone of the repository. Save this file as `environment.yml`:

```yaml
name: hmp
channels:
  - conda-forge
dependencies:
  - python=3.12
  - pip
  - pip:
      - --pre
      - hydromodpy
```

Then create and activate the environment:

```bash
micromamba create -f environment.yml
micromamba activate hmp
```

With conda, write `conda env create -f environment.yml` and `conda activate hmp`. If pip
cannot find a wheel for one geospatial library on your platform, add that library under
`dependencies:` before the `pip:` entry: conda installs it first and pip keeps it.
:::

::::

The `--pre` flag is needed while version 2 is published as `2.0.0aN`. Without it, pip
installs the latest stable release, which is version 1, and `hmp --version` prints `1.0.0`.

The package installs two commands, `hmp` and `hydromodpy`. They are the same program.
Check the version:

```bash
hmp --version
```

To upgrade later, run `pip install --pre --upgrade hydromodpy`.

## Get the solver binaries

MODFLOW 6, MODFLOW-NWT, MODPATH and MT3D-USGS are not part of the package. They are
downloaded into the HydroModPy cache folder (`~/.cache/hydromodpy/bin/` on Linux) the first
time a solver runs. To fetch them now, for example before going offline:

```bash
hmp install-binaries
```

`--subset mf6,mfnwt` takes only some of the programs and `--upgrade` downloads them again.
The other options are in {doc}`the command reference <../reference/cli/install-binaries>`.
The environment variable `HMP_BIN` points HydroModPy at a folder of your own binaries, flat,
with the file names `mf6`, `mfnwt` and so on. When it is set, HydroModPy reads that folder
and downloads nothing. To run without a network after this step, see
{doc}`../guides/work-offline`.

## Check the install

```bash
hmp doctor
```

`hmp doctor` prints one line per check: Python, the core dependencies, the optional ones,
each solver binary, and the workspace (`~/hydromodpy`, or the one you give with
`--workspace`). It exits with an error code when a check is `KO`. A `WARN` does not change
the exit code. On a fresh machine, the binaries and the workspace are `WARN`, because
nothing exists yet:

```text
WARN   solver:mf6                   not cached, not on PATH
       -> Run 'hmp install-binaries --subset mf6' (or let the first simulation trigger a lazy download).
WARN   workspace                    /home/you/hydromodpy does not exist
       -> Run 'hmp workspace init <workspace>' to scaffold one
```

Both are fixed by the next steps. The other options of the command are in
{doc}`the command reference <../reference/cli/doctor>`. From Python:

```python
import hydromodpy
print(hydromodpy.__version__)
```

## Tested platforms

The continuous integration of the repository runs these jobs. A platform that is not listed
may work; nothing checks it.

| Platform | Python | What runs there |
|---|---|---|
| Linux (Ubuntu) | 3.11, 3.12, 3.13 | Every push to `main` and `dev`: lint, architecture gate, fast tests. Python 3.13: unit and integration tests. Weekly: end-to-end tests and the full regression suite (3.12) |
| macOS | 3.11, 3.12, 3.13 | Weekly: unit tests, fast regression and analytical validation, on an install from a clone |
| Windows | 3.11, 3.12, 3.13 | The same weekly job as macOS |

The jobs install from a clone with `pip install -e ".[test,calibration]"`, not from PyPI, and
they do not run the {doc}`staircase <staircase/index>`. The PETSc backend of the Boussinesq
solver is Linux only, and its smoke test is the only job that installs from conda-forge. The
other solvers do not need it. The workflows are in `.github/workflows/` and described in
{doc}`../contribute/project/ci-workflows`.

## Install troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `hmp: command not found` | The environment that holds the command is not active, or the folder of pip scripts is not on `PATH` (a `pip install --user`). | Activate the environment. Or call the module, which is the same program: `python -m hydromodpy --version`. On Windows the command is `.venv\Scripts\hmp.exe`. |
| `hmp --version` prints `1.0.0` | `--pre` was left out, so pip took the stable release. | `pip install --pre --upgrade hydromodpy`. |
| `ImportError: ... cannot open shared object file` when `gmsh`, `pyvista` or `rasterio` loads, on Linux | A system library is missing. The Dockerfile of the repository installs `libglu1-mesa` for gmsh and pyvista, and `libexpat1` for rasterio. | On Debian or Ubuntu: `sudo apt-get install libglu1-mesa libexpat1`. |
| `Could not download the MODFLOW binaries of release <tag> from <address>: [Errno 111] Connection refused. ...` from `hmp install-binaries`, or `step 'run_solver' failed: NetworkError: Could not download ...` from the first run. Exit code 16 | The binaries are downloaded from GitHub and the machine has no direct route to it. | Behind a proxy, set `HTTPS_PROXY` (`urllib` reads it). Offline, download the executables elsewhere, copy them in one flat folder and set `HMP_BIN` to it. |
| `use GITHUB_TOKEN env to bypass rate limit` | GitHub limits the unauthenticated requests that look up the release. | Set `GITHUB_TOKEN` to a token of your own and run the command again. |
| `WARN solver:mf6 not cached, not on PATH` from `hmp doctor` | Nothing was downloaded yet. | Run `hmp install-binaries`, or run any simulation: the first one downloads. |
| Pip builds a library for a long time, or fails on `rasterio` or `pyproj` | No wheel for your Python or platform. | Use the conda tab above and let conda-forge provide that library. |

Other messages are listed by symptom in {doc}`../guides/troubleshooting`.

## Optional extras

Add an extra between brackets: `pip install --pre "hydromodpy[ide,viewer3d]"`.

- `ide`: JupyterLab, Spyder and PySide6.
- `viewer3d`: PyVista, for 3D views of the mesh.
- `calibration`: `cma` and `cmaes`, for the CMA-ES variants. The default `optuna` sampler is in the base install.
- `mesh`: `gmsh`.
- `mf6api`: `modflowapi` and `xmipy`.
- `viz`: `datashader` and `lttb`.
- `fair`: `pystac`, `stac-validator` and `rocrate`.
- `metrics`: `psutil` and `pynvml`.
- `duckdb`: DuckDB, which the base install already holds.
- `all`: `duckdb` and `metrics`. It is not every extra.

The extras `test`, `performance`, `profiling`, `docs` and `dev` are for people who work on
HydroModPy itself; see {doc}`../contribute/index`. The generated list, with the packages
and the version bounds, is on {doc}`../contribute/architecture/generated/extras`.

## Shell completion

Optional. `hmp dev completion bash` prints a completion script for the shell, and `zsh` and
`fish` print one for theirs. To load it in the current bash:

```bash
eval "$(hmp dev completion bash)"
```

{doc}`The command reference <../reference/cli/dev>` gives where to install the script for
bash, zsh and fish, as `hmp dev completion --help` does.

## Next

Run something: the {doc}`quick start <index>`, then the four words the rest of the
documentation uses, in {doc}`concepts`.
