![logo](https://github.com/HydroModPy/HydroModPy/blob/61d654ca738c488480fd22aa01c2b1002984eac9/docs/readthedocs/source/images/logoHydroModPy_long.png)

HydroModPy: A Python toolbox for deploying catchment-scale shallow groundwater models.

Three engineering claims back the platform:

- **Bit-exact reproducibility** thanks to a frozen `hydromodpy.lock` and the
  `runs_environment` provenance table (Python version, package manifest, git
  commit, host CPU/memory, recorded timestamp).
- **ML-friendly storage** built on a DuckDB catalog, per-simulation Parquet
  tables and per-simulation Zarr chunks, so simulation results plug directly
  into sklearn / PyTorch / xgboost / JAX / xarray / xugrid pipelines.
- **Scientific provenance** kept end-to-end: every solver run, calibration
  iteration and derived metric is traceable from the catalog back to its
  configuration, inputs and binaries.

<!-- Continuous integration (dev branch) -->
[![CI Fast](https://github.com/HydroModPy/HydroModPy/actions/workflows/ci-fast.yml/badge.svg?branch=dev)](https://github.com/HydroModPy/HydroModPy/actions/workflows/ci-fast.yml?query=branch%3Adev)
[![CI Nightly](https://github.com/HydroModPy/HydroModPy/actions/workflows/ci-nightly.yml/badge.svg?branch=dev)](https://github.com/HydroModPy/HydroModPy/actions/workflows/ci-nightly.yml?query=branch%3Adev)
[![CI Weekly](https://github.com/HydroModPy/HydroModPy/actions/workflows/ci-weekly.yml/badge.svg?branch=dev)](https://github.com/HydroModPy/HydroModPy/actions/workflows/ci-weekly.yml?query=branch%3Adev)
[![PETSc Smoke](https://github.com/HydroModPy/HydroModPy/actions/workflows/petsc-smoke.yml/badge.svg?branch=dev)](https://github.com/HydroModPy/HydroModPy/actions/workflows/petsc-smoke.yml?query=branch%3Adev)
[![Docs Gallery Check](https://github.com/HydroModPy/HydroModPy/actions/workflows/docs-gallery-check.yml/badge.svg?branch=dev)](https://github.com/HydroModPy/HydroModPy/actions/workflows/docs-gallery-check.yml?query=branch%3Adev)

<!-- Code quality (dev branch) -->
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Codecov](https://codecov.io/gh/HydroModPy/HydroModPy/branch/dev/graph/badge.svg)](https://codecov.io/gh/HydroModPy/HydroModPy/tree/dev)
[![Documentation](https://readthedocs.org/projects/hydromodpy-docs/badge/?version=dev)](https://hydromodpy-docs.readthedocs.io/en/dev/)

<!-- Project info -->
[![PyPI](https://img.shields.io/pypi/v/hydromodpy.svg)](https://pypi.org/project/hydromodpy/)
[![Downloads](https://img.shields.io/pypi/dm/hydromodpy.svg)](https://pypi.org/project/hydromodpy/)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue.svg)](https://www.python.org/)
[![License: EPL-2.0](https://img.shields.io/badge/license-EPL--2.0-green.svg)](https://opensource.org/licenses/EPL-2.0)

## Presentation

HydroModPy was initiated in 2018 to streamline the deployment of hydrological models in catchments across the crystalline basement regions of Normandy and Brittany, France. The platform integrates a wide range of open-source packages (FloPy, whitebox-workflows, etc.), making them easily accessible and shareable among scientific communities.
The development of HydroModPy was driven by two primary objectives.

First, it automates the extraction and discretization of watersheds from Digital Elevation Models (DEMs), while adding essential data available (e.g. piezometry, hydrography, geology) from local data to national and global databases. This ensures a standardized process for setting up and running simulation batches across different watersheds with uniform input data.

The second goal is to facilitate the visualization and comparison of results from the various modeling programs included within the platform. In addition to its scientific applications, HydroModPy also serves as a valuable educational tool, enabling students and researchers to explore hydrogeological modeling in a practical context.

## Authors

Alexandre Gauvain [1,2], Ronan Abhervé [1,3,9],  Alexandre Coche [1], Martin Le Mesnil [1], Clément Roques [3], Camille Bouchez [1],  Jean Marçais [4], Sarah Leray [5], Etienne Marti [5], Ronny Figueroa [3], Etienne Bresciani [6], Camille Vautier [1], Bastien Boivin [1], Tristan Babey [1], June Sallou [7], Johan Bourcier [8], Benoit Combemale [8], Philip Brunner [3], Laurent Longuevergne [1], Luc Aquilina [1], Jean-Raynald de Dreuzy [1].

- [1] Geosciences Rennes -- UMR 6118, CNRS, Université de Rennes, Rennes, France
- [2] Laboratoire de Météorologie Dynamique (LMD), CNRS, Sorbonne Université, Paris, France
- [3] Centre for Hydrogeology and Geothermics (CHYN), Université de Neuchâtel, Neuchâtel, Switzerland
- [4] INRAE, UR RiverLy, Centre Lyon-Grenoble Auvergne-Rhône-Alpes, Villeurbanne, France
- [5] Pontificia Universidad Católica de Chile, Santiago, Chile
- [6] Instituto de Ciencias de la Ingeniería, Universidad de O'Higgins, Rancagua, Chile
- [7] INF, Wageningen University \& Research, Wageningen, Netherlands
- [8] Inria, IRISA, CNRS, Université de Rennes, Rennes, France
- [9] INRAE, UMR SAS 1069, Centre Bretagne-Normandie, Rennes, France

## Links

- GitHub Project: https://github.com/HydroModPy/HydroModPy
- Documentation (dev branch): https://hydromodpy-docs.readthedocs.io/en/dev/
- Stable documentation: https://hydromodpy-docs.readthedocs.io/en/latest/
- Technical documentation and UMLs (`Architecture` tab): https://hydromodpy-docs.readthedocs.io/en/dev/architecture/
- Scientific documentation (`Scientific documentation` tab): https://hydromodpy-docs.readthedocs.io/en/dev/scientific/
- Google Drive: https://docs.google.com/document/d/11BA4ufhYWbydBvfjQufohoPIc0SaF9pKcyj_KNJ2VQM/edit?usp=sharing
- Forum Group: https://groups.google.com/g/hydromodpy

## Installation

HydroModPy can be installed using pip or by setting up a conda environment.

### Prerequisites

- **Anaconda3** or **Miniconda3** must be installed on your computer
- **Important**: Your local path directory should not contain any white spaces, to be compatible with MODFLOW-MODPATH suite

### Option 1: pip install (recommended)

Install HydroModPy directly from PyPI:

```bash
pip install hydromodpy
# optional extras
pip install "hydromodpy[ide]"
pip install "hydromodpy[test]"
pip install "hydromodpy[viewer3d]"
```

The base runtime no longer pulls IDE, test, or 3D viewer dependencies by
default. Add extras only when you need those workflows.

For development mode (editable installation):

```bash
# Clone the repository (see Git installation options below)
cd HydroModPy

# Install in editable mode
pip install -e .
# or add local test tooling
pip install -e ".[test]"

# PyHELP binaries are automatically downloaded on first import
```

### Option 2: conda environment

Two ready-to-use Conda recipes live in `install/`:

- `env_hydromodpy.yml` installs every runtime dependency (including Spyder) so you
  can run scripts and notebooks right away.
- `env_hydromodpy_pkg.yml` mirrors the same stack but finishes with
  `pip install -e ..` to expose the local repository as a package.
- `env_hydromodpy_light_pkg.yml` provides a lighter editable stack, recommended
  for Linux/WSL command-line development and test runs.

```bash
# from the repository root
conda env create -f install/env_hydromodpy.yml -n hydromodpy
conda activate hydromodpy

# editable/package variant
conda env create -f install/env_hydromodpy_pkg.yml -n hydromodpy-pkg
conda activate hydromodpy-pkg

# lightweight editable variant (recommended on Linux/WSL)
conda env create -f install/env_hydromodpy_light_pkg.yml -n hydromodpy-light-pkg
conda activate hydromodpy-light-pkg
```

### Linux / WSL quick start

For Ubuntu or WSL, the repository now includes a helper script that installs
the minimal Linux system dependency, creates an editable Conda environment,
adds the Linux runtime library needed by `gmsh`, and can optionally add PETSc:

```bash
bash install/setup_wsl_dev.sh --env-name hydromodpy-wsl
# optional PETSc add-on
bash install/setup_wsl_dev.sh --env-name hydromodpy-wsl --with-petsc
```

If Conda is not available inside WSL yet, Miniforge is the simplest route:

```bash
sudo apt update && sudo apt install -y curl git libglu1-mesa
curl -L -O https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh
bash Miniforge3-Linux-x86_64.sh
source ~/miniforge3/etc/profile.d/conda.sh
```

If you create the Conda environment manually instead of using
`install/setup_wsl_dev.sh`, add the `gmsh` runtime shim explicitly on Linux:

```bash
conda install -n hydromodpy-light-pkg -c conda-forge xorg-libxft
```

Typical Linux/WSL test commands after activation:

```bash
export MPLBACKEND=Agg
python -m pytest tests/unit -q
hmp test regression --fast -j 2
hmp test validation --fast
```

### Git installation

To obtain the source code for development:

**Option 1**: Download the `.zip` folder directly from the [GitHub project](https://github.com/HydroModPy/HydroModPy)

**Option 2**: Clone the repository using a Git management tool like GitHub Desktop

**Option 3**: Use command line with classical Git functions:

```bash
git clone https://github.com/HydroModPy/HydroModPy.git
cd HydroModPy
```

## Getting started

The fastest route is to scaffold a project, generate a v1 TOML template,
and run it through the single workflow dispatcher.

```bash
hmp init .
hmp new getting_started --workspace .
hmp run projects/getting_started/run_demo.toml
```

Outputs land in a workspace next to the config:

- `hydromodpy.duckdb` - the unified simulation catalog.
- `simulations/<basename>.zarr.zip` - finalized spatial fields and metadata per run.

Open the results programmatically:

```python
import hydromodpy as hmp

catalog = hmp.open(".")
print(catalog.simulations)              # DataFrame of all sims
sim = catalog.best("getting_started")   # best by default metric
print(catalog.zarr_path_for(sim.sim_id))
sim.plot("watertable_map", save=".")
```

## Machine Learning access

Simulation results are stored in three formats so a machine learning pipeline
can pick whichever fits its workload:

- **Query the catalog in SQL via DuckDB.** The workspace ships with a single
  `hydromodpy.duckdb` file holding the `simulations`, `parameters`, `metrics`,
  `runs_environment`, `calibration_sessions` and `calibration_iterations`
  tables (plus parquet-backed views for `timeseries`, `budgets` and
  `mass_balance`). Connect read-only and run arbitrary SQL:

  ```python
  import duckdb

  con = duckdb.connect("workspace/hydromodpy.duckdb", read_only=True)
  features = con.sql(
      "SELECT s.sim_id, p.K, p.Sy, m.nse "
      "FROM simulations s "
      "JOIN parameters p USING (sim_id) "
      "JOIN metrics m USING (sim_id) "
      "WHERE m.metric_name = 'nse'"
  ).df()
  ```

- **Load batches via Parquet for sklearn / PyTorch pipelines.** Each
  simulation writes its Parquet artefacts under
  `workspace/simulations/<basename>.parquet/<view>.parquet` (`<view>` is one of
  `timeseries`, `budgets`, `mass_balance`). Files are independent, so a
  `pandas` / `pyarrow` reader can fan-out across hundreds of runs without
  hitting the catalog:

  ```python
  import pandas as pd

  ts = pd.read_parquet(
      "workspace/simulations/getting_started__synthetic__a1b2c3d4.parquet/"
      "timeseries.parquet"
  )
  ```

- **Per-simulation Zarr chunks for tensor-friendly access.** Finalized spatial fields
  live in `workspace/simulations/<basename>.zarr.zip` and load straight into
  `xarray` / `xugrid`, ready for `torch.utils.data.Dataset` wrappers:

  ```python
  from hydromodpy.results.zarr_store import SimulationZarr

  sz = SimulationZarr(catalog.zarr_path_for(sim.sim_id))
  try:
      ds = sz.to_xarray()
      head = ds["head"]
  finally:
      sz.close()
  ```

The full walkthrough (DuckDB SQL recipes, Parquet batch loading, Zarr
DataLoader example, `runs_environment` provenance schema, train/val/test
split convention) lives in
[`docs/developers/ML_ACCESS_PATTERN.md`](docs/developers/ML_ACCESS_PATTERN.md).

## Usage Examples

Runnable datasets and reference inputs live under `examples/data/`.
Executable examples live alongside each validation case under
`validation_cases/analytical/` and `validation_cases/numerical/`.

## Annex Tooling (`hydromodpy_annex`)

HydroModPy keeps the reusable core library in `hydromodpy/`.
Project-specific tools that are useful but not part of the core package
(preprocessing helpers, postprocessing workflows, dedicated launchers, exploratory
pipelines) are stored in `hydromodpy_annex/`.

Current migrated annex:

- `hydromodpy_annex/postprocess/HCDM/`

Design rules:

- Dependency direction is one-way: annex tools may import `hydromodpy`, but
  `hydromodpy` must not import from `hydromodpy_annex`.
- Keep generic, stable, reusable APIs in the core package.
- Keep workflow orchestration and case-specific scripts in annex folders.
- Prefer explicit local launchers per annex tool.

## Validation and Testing

HydroModPy uses three complementary test families:

- `tests/unit/`: local API and behavior checks on isolated components.
- `tests/regression/`: non-regression checks against reference outputs and
  workflows.
- `tests/validation/`: scientific benchmark tests against analytical or trusted
  physical references.

Validation tests are backed by reusable cases stored in `validation_cases/`.
They run deterministic launcher configurations, load the generated model
outputs, compute comparison metrics, and fail only when those metrics exceed
explicit tolerances.

Typical commands:

```bash
python -m pytest tests/unit -q
python -m pytest tests/regression -q
python -m pytest tests/validation -q
python -m pytest -m "validation and fast" -q
hmp test unit
hmp test regression --fast
hmp test validation --fast
```

Platform note:

- Most tests are intended to run on both Windows and Linux.
- Some validation tests target the PETSc Boussinesq backend and are Linux-only
  by design; on Windows they are skipped, not failed.
- PETSc-focused validation tests are tagged with `pytest.mark.petsc`, so a
  provisioned Linux environment can run `python -m pytest -m petsc -q`.
- The PETSc smoke workflow runs `bash tools/ci/run_boussinesq_petsc_smoke.sh`
  on a conda environment. The Boussinesq pip path is covered by the
  standard unit and validation tiers.

For the detailed validation workflow, available analytical cases, and guidance
to add a new benchmark, see:

- `tests/validation/README.md`
- `validation_cases/README.md`

## Linked publications

Papers published using HydroModPy.

Abhervé, R., Roques, C., de Dreuzy, J.-R., Van Der Veen, T., Dumaine, L., Chatton, E., Brunner, P., Aquilina, L., & Servière, L. (2025). Projected climate change impacts on groundwater-surface water connectivity in a compartmentalized mountain headwater bedrock aquifer. Water Resources Research, 61(10), https://doi.org/10.1029/2025WR040083

Marti, E., Leray, S., & Roques, C. (2024). Catchment landforms predict groundwater-dependent wetland sensitivity to recharge changes. Hydrology and Earth System Sciences Discussions. https://doi.org/10.5194/HESS-2024-381

Floriancic, M. G., Abhervé, R., Bouchez, C., Martinez, J. J., & Roques, C. (2024). Evidence of Groundwater Seepage and Mixing at the Vicinity of a Knickpoint in a Mountain Stream. Geophysical Research Letters, 51. https://doi.org/10.1029/2024GL111325

Le Mesnil, M., Gauvain, A., Gresselin, F., Aquilina, L., & Dreuzy, J. De. (2024). Characterizing coastal aquifer heterogeneity from a single piezometer head chronicle. Journal of Hydrology, 131859. https://doi.org/10.1016/j.jhydrol.2024.131859

Abhervé, R., Roques, C., De Dreuzy, J.-R., Datry, T., Brunner, P., Longuevergne, L., & Aquilina, L. (2024). Improving calibration of groundwater flow models using headwater streamflow intermittence. Hydrological Processes, 38((6)). https://doi.org/10.1002/hyp.15167

Abhervé, R., Roques, C., Gauvain, A., Longuevergne, L., Louaisil, S., Aquilina, L., & de Dreuzy, J.-R. (2023). Calibration of groundwater seepage against the spatial distribution of the stream network to assess catchment-scale hydraulic properties. Hydrology and Earth System Sciences, 27(17), 3221-3239. https://doi.org/10.5194/hess-27-3221-2023

## Coresponding authors

For any questions regarding HydroModPy, please contact us at <alexandre.gauvain.ag@gmail.com> or <ronan.abherve@gmail.com>

## Abstract for the congress IAH 2024

The need for predictive models increases as the pressure of global change intensifies. Regional-scale modeling of shallow unconfined aquifers (10-100 m depth) remains challenging, especially in complex basement aquifers. Controlled both by topography and geology, groundwater flows are organized from hillslope to catchment scale. It is particularly the case in crystalline regions with low aquifer volumes and wet climates, resulting in significant subsurface-surface interactions with very few information available to constrain models.

To address this, we present HydroModPy, an application developed in Python as a toolbox for automatic deployment of groundwater flow models. HydroModPy integrates geospatial processing through whitebox-workflows-backed Whitebox operations with groundwater flow and transport simulation tools (MODFLOW and MODPATH via FloPy). It is designed to call other groundwater flow solvers, facilitate multi-site deployment, integrate pre- and post-processing functions such as catchment extraction from a DEM and an advanced representation of head and flow results. Emphasis is placed on integrating aquifer geometry complexities and hydraulic properties heterogeneity (compartmentalization, exponential decay, implementation of a 3D geological model, etc.).

HydroModPy's user-friendly Python interface allows for testing and exploring various aquifer models across different geomorphological contexts and recharge conditions. Ongoing improvements include methods for calibrating and estimating hydraulic properties using multiple datasets such as hydrographic network maps, streamflow, and piezometric level data. HydroModPy is developed as an open-source toolkit. It is currently being used in climate change effects on groundwater-dependent ecosystems and water resource management issues. Collaborative development should enhance the modeling capacity of near-surface aquifers, facilitate their extension to the regional scale for predictive purposes.

## How to cite

A paper about HydroModPy is in preparation for the journal Technical Note: Hydrology and Earth System Sciences.

Gauvain, A., Abhervé, R., Coche, A., Le Mesnil, M., Roques, C., Bouchez, C., Marçais, J., Leray, S., Marti, E., Figueroa, R., Bresciani, E., Vautier, C., Boivin, B., Sallou, J., Bourcier, J., Combemale, B., Longuevergne, L., Aquilina, L., and de Dreuzy, J.-R. (2025). Technical note: HydroModPy - a Python toolbox for deploying catchment-scale shallow groundwater models. Hydrology and Earth System Sciences. In prep.
