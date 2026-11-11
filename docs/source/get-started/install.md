# Install

HydroModPy needs Python 3.11, 3.12 or 3.13. The version of this site is {{ release }}; the
{doc}`versions page <../about/versions>` says what each release promises. On a fast connection pip needs
about two minutes, and a clean environment weighs 1.3 GB: most of it is the geospatial and
scientific wheels.

Linux on x86_64 is the supported platform. macOS and Windows are best effort until their
CI is green: the weekly jobs below run there, but a failure on them does not block a release.
The terrain tools depend on `whitebox-workflows`, which publishes wheels for glibc 2.35 or
newer on Linux x86_64, macOS arm64 and Windows x64 only, so an older cluster cannot install it.

## Install the package

::::{tab-set}
:sync-group: os

:::{tab-item} Linux and macOS
:sync: unix

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install hydromodpy
```
:::

:::{tab-item} Windows
:sync: windows

In PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install hydromodpy
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

The package installs two commands, `hmp` and `hydromodpy`. They are the same program.
Check the version:

```bash
hmp --version
```

To upgrade later, run `pip install --upgrade hydromodpy`.

## Get the solver binaries

MODFLOW 6, MODFLOW-NWT, MODPATH and MT3D-USGS are not part of the package. They are
downloaded into the HydroModPy cache folder (`~/.cache/hydromodpy/bin/` on Linux) the first
time a solver runs. To fetch them now, for example before going offline:

```bash
hmp install-binaries
```

`--subset mf6,mfnwt` takes only some of the programs and `--upgrade` downloads them again.
Each version of HydroModPy names one MODFLOW release and the sha256 of its files, and a download
that does not match is refused.
The other options are in {doc}`the command reference <../reference/cli/install-binaries>`.
The environment variable `HMP_BIN` points HydroModPy at a folder of your own binaries, flat,
with the file names `mf6`, `mfnwt` and so on. When it is set, HydroModPy reads that folder
and downloads nothing, and `hmp install-binaries` without `--to` fills it. The data still need the network once: a first run fills the cache of
the workspace, and {doc}`hmp run --frozen <../reference/cli/run>` then refuses any new
download.

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

## Run in Docker

The `Dockerfile` of the repository builds a slim image whose entry point is `hmp`, so a container
runs the same program as the command line. The image holds HydroModPy with every extra, the
solver binaries, which `hmp install-binaries` fetched under `/opt/hmp/bin` at the build and
checked against their pinned sha256, and the HTTP server of the repository. The versions of the
build are kept in `/opt/hmp/constraints.txt`. Build it from a clone, with the tag you give it:

```bash
docker build --build-arg HMP_IMAGE_TAG=2.1.0 -t hydromodpy:2.1.0 .
```

A run request is one JSON file that holds the configuration under `config`. A container plays it
from a project folder you mount, and `--base` names the folder its relative paths are read from:

```bash
docker run --rm -v "$PWD/project:/project" hydromodpy:2.1.0 run /project/request.json --base /project
```

The run folder, `request.json` included, is written under `/project/runs/`. The request itself
is described in {doc}`../contribute/architecture/how-to/build-a-frontend`. An image cannot hold its
own digest, so pass it with `-e HMP_IMAGE_DIGEST=sha256:<digest>`. For an image built here,
`docker inspect --format '{{.Id}}' hydromodpy:2.1.0` gives it. A run then writes the tag
and the digest of the image in its `provenance.json`. The server needs the digest to start:

```bash
docker run -d --hostname hmp-server -p 8765:8765 -v /srv/hmp:/project \
  -e HMP_IMAGE_DIGEST=sha256:<digest> \
  --entrypoint python hydromodpy:2.1.0 -m hydromodpy_server --root /project --host 0.0.0.0
```

{doc}`../contribute/architecture/how-to/serve-over-http` describes its routes.

## On a Windows server

Put the projects under a short root such as `D:\hmp\`. A project writes paths up to 160
characters below its folder, and MODFLOW 6 and DuckDB open no path longer than 259 characters,
so the project folder may hold 99 characters at most. A longer folder is refused when the project
is created and when a run or a calibration session takes its folder, before anything is computed.
A root like `D:\hmp\<organisation>\projects\<name>` with names of 40 characters is 97 characters long.

Fill `HMP_BIN` once, from the service account, with `hmp install-binaries`. The runs only read that
folder, so it can be read-only for the account that starts them.

Give the server a fixed host name of 35 characters at most, and with Docker pass
`docker run --hostname hmp-<code>` with a short code. A product being written carries the host
name in its path, 125 characters plus the host name below the project folder, so a name of 35
characters reaches the 160 of the budget. `hmp-` and an organisation name of 40 characters would
reach 169.
A run that was interrupted is recognised as dead from its host name and its process id. A container
that gets a new name at each start leaves every interrupted run `stale` until you use `--force`.

A delivery destination on a network share is written as a UNC path, `\\server\share\folder`,
like a local one. Keep the project itself on a local disk and use the share only as a destination.

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
| `ImportError: ... cannot open shared object file` when `gmsh` or `rasterio` loads, on Linux | A system library is missing. The Dockerfile of the repository installs `libglu1-mesa` for gmsh and `libexpat1` for rasterio. | On Debian or Ubuntu: `sudo apt-get install libglu1-mesa libexpat1`. |
| `Could not download the MODFLOW binaries of release <tag> from <address>: [Errno 111] Connection refused. ...` from `hmp install-binaries`, or `step 'run_solver' failed: NetworkError: Could not download ...` from the first run. Exit code 16 | The binaries are downloaded from GitHub and the machine has no direct route to it. | Behind a proxy, set `HTTPS_PROXY` (`requests` reads it). Offline, download the executables elsewhere, copy them in one flat folder and set `HMP_BIN` to it. |
| `<zip> downloaded from <address> hashes to <digest>, and HydroModPy pins sha256 <digest> for it. ...` from `hmp install-binaries` or the first run. Exit code 16 | The file that arrived is not the one this version was released with. HydroModPy keeps nothing of it. | Check the proxy and try again. If it stays, report it, and meanwhile set `HMP_BIN` to a folder of executables you trust. |
| `WARN solver:mf6 not cached, not on PATH` from `hmp doctor` | Nothing was downloaded yet. | Run `hmp install-binaries`, or run any simulation: the first one downloads. |
| Pip builds a library for a long time, or fails on `rasterio` or `pyproj` | No wheel for your Python or platform. | Use the conda tab above and let conda-forge provide that library. |

Every exit code and its category are listed in {doc}`../reference/cli/exit-codes`.

## Optional extras

Add an extra between brackets: `pip install "hydromodpy[ide,mesh]"`.

- `ide`: JupyterLab, Spyder and PySide6.
- `calibration`: `cma` and `cmaes`, for the CMA-ES variants. The default `optuna` sampler is in the base install.
- `mesh`: `gmsh`.
- `mf6api`: `modflowapi` and `xmipy`.
- `viz`: `datashader` and `lttb`.
- `fair`: `pystac`, `stac-validator` and `rocrate`. These serve every FAIR view: the RO-Crate
  export of the package and, from a checkout of the repository, the STAC and PROV views of the
  annex (`hmp export --as stac`), which declare no dependencies of their own.
- `metrics`: `psutil`.
- `all`: `calibration`, `mesh`, `mf6api`, `viz`, `fair` and `metrics`. The extras for people who work on HydroModPy itself are not in it.

The extras `test`, `performance`, `profiling`, `docs` and `dev` are for people who work on
HydroModPy itself; see {doc}`../contribute/index`. The generated list, with the packages
and the version bounds, is on {doc}`../contribute/architecture/generated/extras`.

## Shell completion

Optional. `hmp completion bash` prints a completion script for the shell, and `zsh` and
`fish` print one for theirs. To load it in the current bash:

```bash
eval "$(hmp completion bash)"
```

The script asks `hmp` for its commands each time you press TAB, so it follows the commands that
exist. In fish, pipe it to `source`: `hmp completion fish | source`.

## Next

Run something: the {doc}`quick start <index>`, then the four words the rest of the
documentation uses, in {doc}`concepts`.
