# Install

HydroModPy needs Python 3.11, 3.12 or 3.13. The current pre-release is `2.0.0a4`.

## Install the package

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install --pre hydromodpy
```

On Windows PowerShell, create and activate the environment with `py -3.12 -m venv .venv`
and `.\.venv\Scripts\Activate.ps1`.

The `--pre` flag is needed while version 2 is published as `2.0.0aN`. Without it, pip
installs the latest stable release, which is version 1.

The package installs two commands, `hmp` and `hydromodpy`. They are the same program.
Check the version:

```bash
hmp --version
```

To upgrade later, run `pip install --pre --upgrade hydromodpy`.

### With conda

If the geospatial libraries are hard to build on your machine, create the environment
with conda first, then install HydroModPy into it with pip. The repository keeps
two environment files in its `install/` folder: `env_hydromodpy.yml` (full stack, with
Spyder and PySide6) and `env_hydromodpy_light.yml` (lighter). Both take their packages from
conda-forge. Neither installs HydroModPy itself.

```bash
conda env create -n hmp -f install/env_hydromodpy.yml
conda activate hmp
pip install --pre hydromodpy
```

### With Docker

The repository has a `Dockerfile` that builds a wheel and runs `hmp` as an unprivileged
user. Build it from a clone:

```bash
docker build -t hydromodpy .
docker run --rm hydromodpy --help
```

The image does not contain the solver binaries. They are downloaded into the container
the first time a solver runs.

## Get the solver binaries

MODFLOW 6, MODFLOW-NWT, MODPATH and MT3D-USGS are not part of the package. They are
downloaded into `~/.cache/hydromodpy/bin/` the first time a solver runs. To fetch them
now, for example before going offline:

```bash
hmp install-binaries
```

`hmp install-binaries --help` lists the options. `--subset mf6,mfnwt` takes only some of
the programs (the names are `mfnwt`, `mf6`, `mp6`, `mp7` and `mt3dusgs`). `--mf6-prt`
installs only the MODFLOW 6 executable that particle tracking uses. `--bindir` sets
another folder, `--release` pins a release tag, `--upgrade` downloads again and `--quiet`
reduces the output. The full list is in {doc}`the command reference <../reference/cli/install-binaries>`.

The environment variable `HMP_BIN` points HydroModPy at a folder of your own binaries. When
it is set, HydroModPy reads that folder instead of the cache. To run without a network
after this step, see {doc}`../guides/work-offline`.

## Check the install

```bash
hmp doctor
```

`hmp doctor` prints one line per check: Python version, the core dependencies, the
optional ones (`gmsh`, `whitebox_workflows`, `geopandas`, `pyvista`), each solver binary,
and the workspace (`~/hydromodpy`, or the one you give with `--workspace`). It exits with an error code when a
check is `KO`. A `WARN` does not change the exit code. The other options of the command are in
{doc}`the command reference <../reference/cli/doctor>`.

You can also check from Python:

```python
import hydromodpy
print(hydromodpy.__version__)
```

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
| `metrics` | `psutil` and `pynvml` |

The extras `test`, `dev`, `docs` and `docs-uml` are for people who work on HydroModPy itself.
To set up an editable clone, run the tests or build this site, see {doc}`../contribute/index`.

## Shell completion

`hmp dev completion` prints a completion script on the standard output for `bash`, `zsh` or
`fish`. The script lists the top-level commands, the actions of every command family and
the long options of each command. It reads the commands at the moment you generate it, so
generate it again after you upgrade HydroModPy. It works for both `hmp` and `hydromodpy`.

For bash, load it into the current shell, or save it in a completion folder:

```bash
# current shell only
eval "$(hmp dev completion bash)"

# system-wide install (requires root)
hmp dev completion bash | sudo tee /etc/bash_completion.d/hmp > /dev/null
```

For zsh, save the script in a folder of `$fpath` and run `compinit` once:

```bash
mkdir -p ~/.zsh/completions
hmp dev completion zsh > ~/.zsh/completions/_hmp
# in ~/.zshrc, before `compinit`:
#   fpath=(~/.zsh/completions $fpath)
#   autoload -U compinit && compinit
```

For fish, save it in the fish completion folder. Fish reads it at the next start:

```bash
hmp dev completion fish > ~/.config/fish/completions/hmp.fish
```

The `argcomplete` package is part of the base install. It gives completion computed at
each key press instead of a generated script. `--argcomplete` prints the line to add to your
shell startup file:

```bash
hmp dev completion bash --argcomplete
```

## Next

Learn the four words the rest of the documentation uses: {doc}`concepts`.
