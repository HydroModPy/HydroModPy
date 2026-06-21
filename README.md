![logo](docs/source/images/logoHydroModPy_long.png)

# HydroModPy

A Python toolbox for deploying catchment-scale shallow groundwater models.

[![Documentation](https://img.shields.io/badge/docs-v1-blue)](https://hydromodpy.github.io/v1/)
[![DOI](https://img.shields.io/badge/DOI-10.5194%2Fegusphere--2026--868-blue)](https://doi.org/10.5194/egusphere-2026-868)
[![License: EPL-2.0](https://img.shields.io/badge/License-EPL%202.0-red.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%E2%80%933.13-blue)](pyproject.toml)

> ### HydroModPy v1: the version cited in the paper
>
> This `v1` branch is the version described in the technical note submitted to
> *Hydrology and Earth System Sciences* (EGUsphere preprint, 2026). It is the
> reference cited by the paper and is kept up to date with fixes, so the paper
> link always points to a working v1.
>
> **HydroModPy v2** is the actively developed version on the `main` branch, with
> new features and a redesigned interface.
>
> | | Link |
> |---|---|
> | Paper (preprint) | https://doi.org/10.5194/egusphere-2026-868 |
> | v1 documentation | https://hydromodpy.github.io/v1/ |
> | v2 documentation (latest) | https://hydromodpy.github.io/main/ |
> | Forum (Google Group) | https://groups.google.com/g/hydromodpy |

## Presentation

HydroModPy was initiated in 2018 to streamline the setup and deployment of
hydrogeological models in catchments across the crystalline basement regions of
Normandy and Brittany (France). The platform integrates multiple open-source
libraries (e.g., FloPy, WhiteboxTools), providing a unified and reproducible
framework that is easily accessible to the scientific community. The development
of HydroModPy is driven by two main objectives:

First, it automates the extraction and discretization of watersheds from Digital
Elevation Models (DEMs) and enriches them with key hydrogeological datasets
(e.g., piezometry, hydrography, geology) compiled from local, national, and
global databases. This workflow ensures a standardized and reproducible approach
for building and running simulation ensembles across multiple catchments using
consistent input data.

Second, it facilitates the visualization, analysis, and comparison of outputs
from the different modelling components integrated within the platform. Beyond
research applications, HydroModPy also serves as an educational tool, enabling
students and researchers to explore hydrogeological modelling workflows in a
practical and reproducible environment.

## Authors

Alexandre Gauvain [1,2], Ronan Abhervé [1,3,4], Bastien Boivin [1], Tristan Babey [1], Martin Le Mesnil [1], Alexandre Coche [1], Enzo Maugan [1], Théa Touzeau [1], Imene Issolah [1], Clément Roques [3], Camille Bouchez [1], Jean Marçais [4], Sarah Leray [5], Etienne Marti [5], Etienne Bresciani [6], Ronny Figueroa [3], Mathias Pélissier [3], Simon Carlier [3], Luca Guillaumot [8], Rock S. Bagagnan [1], Camille Vautier [1], Laurent Longuevergne [1], June Sallou [7], Johan Bourcier [8], Benoit Combemale [8], Philip Brunner [3], Luc Aquilina [1], Jean-Raynald de Dreuzy [1].

- [1] Geosciences Rennes -- UMR 6118, CNRS, Université de Rennes, Rennes, France
- [2] Laboratoire de Météorologie Dynamique (LMD), CNRS, Sorbonne Université, Paris, France
- [3] Centre for Hydrogeology and Geothermics (CHYN), Université de Neuchâtel, Neuchâtel, Switzerland
- [4] UMR SAS 1069, INRAE, Centre Bretagne-Normandie, Rennes, France
- [5] UR RiverLy, INRAE, Centre Lyon-Grenoble Auvergne-Rhône-Alpes, Villeurbanne, France
- [6] Pontificia Universidad Católica de Chile, Santiago, Chile
- [7] Instituto de Ciencias de la Ingeniería, Universidad de O'Higgins, Rancagua, Chile
- [8] BRGM - French Geological Survey, Orléans, France
- [9] INF, Wageningen University & Research, Wageningen, Netherlands
- [10] ISA/LIUPPA, Université de Pau et des Pays de l'Adour, Pau, France
- [11] Inria, IRISA, CNRS, Université de Rennes, Rennes, France

## Installation

HydroModPy can be installed with `pip` or by setting up a `conda` environment.

### Prerequisites

- **Anaconda3** or **Miniconda3** installed on your computer.
- **Important**: your local path should not contain white spaces, to stay
  compatible with the MODFLOW-MODPATH suite.

### Download

To obtain the source code:

- **Option 1**: download the `.zip` archive directly from the
  [GitHub project](https://github.com/HydroModPy/HydroModPy/tree/v1).
- **Option 2**: clone the repository with a Git client such as
  [GitHub Desktop](https://desktop.github.com/download/).
- **Option 3**: use the command line:

```bash
git clone https://github.com/HydroModPy/HydroModPy.git
cd HydroModPy
git checkout v1
```

### Option 1: pip install (recommended)

Install HydroModPy from PyPI:

```bash
# without Spyder and JupyterLab
pip install "hydromodpy==1.0.0"
# including Spyder and JupyterLab
pip install "hydromodpy[ide]==1.0.0"
```

MODFLOW, MODPATH and MT3DMS binaries ship with the package. The PyHELP binary
downloads itself on the first call to the corresponding module.

For development (editable) mode from a clone:

```bash
cd HydroModPy
pip install -e .
```

### Option 2: conda environment

Ready-to-use environment files live in the `install/` directory:

- `env_hydromodpy.yml`: full runtime stack, including Spyder.
- `env_hydromodpy_pkg.yml`: same stack, then runs `pip install -e ..` to expose
  the cloned repository as an editable package.
- `env_hydromodpy_light.yml`: minimal headless stack (no IDE, no 3D viewer).
- `requirements-docker-light.txt`: pip requirements for a light Docker/server
  image.

```bash
# from the repository root
conda env create -f install/env_hydromodpy.yml
conda activate hydromodpy
```

## Launch HydroModPy

HydroModPy v1 was primarily developed for use with Spyder, so we recommend
launching it from this IDE:

1. Activate the environment:

```bash
conda activate hydromodpy
```

2. Open Spyder or Jupyter:

```bash
spyder
# or
jupyter notebook
```

3. Import HydroModPy in Python:

```python
import hydromodpy
from hydromodpy import Watershed

# Check version
print(hydromodpy.__version__)
```

## Examples

Run the example scripts in `examples/` in this order:

```
00_quick_test_of_wide_hydromodpy_capabilities
01_simplified_example_presented_in_the_paper
02_basic_features_and_overview_of_possibilities
03_hydrographic_network_in_steady_state
04_streamflow_intermittence_in_transient
05_piezometry_in_a_heterogeneous_coastal_aquifer
06_particle_tracking_and_residence_times
07_analytical_solution_for_streamflow_recession
08_exponential_distribution_of_residence_times
09_transport_model_for_an_agricultural_catchment
10_coupling_with_land_surface_model_pyhelp
11_run_from_scratch_without_plots
```

The same examples are available as notebooks in the
[documentation](https://hydromodpy.github.io/v1/).

## Documentation

- v1 documentation: https://hydromodpy.github.io/v1/
- v2 documentation (latest development): https://hydromodpy.github.io/main/

The v1 documentation is built and published automatically to
`https://hydromodpy.github.io/v1/` on every update of the `v1` branch.

## Publications

Papers published using HydroModPy:

Bagagnan, R. S., Abhervé, R., Laverman, A. M., & Vautier, C. (2026). Groundwater controls on legacy antibiotics and pesticides in an intensive agricultural headwater catchment. Journal of Hydrology, 66. https://doi.org/10.1016/j.jhydrol.2026.135118

Abhervé, R., Roques, C., de Dreuzy, J.-R., Van Der Veen, T., Dumaine, L., Chatton, E., Brunner, P., Aquilina, L., & Servière, L. (2025). Projected climate change impacts on groundwater-surface water connectivity in a compartmentalized mountain headwater bedrock aquifer. Water Resources Research, 61(10). https://doi.org/10.1029/2025WR040083

Floriancic, M. G., Abhervé, R., Bouchez, C., Martinez, J. J., & Roques, C. (2024). Evidence of Groundwater Seepage and Mixing at the Vicinity of a Knickpoint in a Mountain Stream. Geophysical Research Letters, 51. https://doi.org/10.1029/2024GL111325

Le Mesnil, M., Gauvain, A., Gresselin, F., Aquilina, L., & de Dreuzy, J.-R. (2024). Characterizing coastal aquifer heterogeneity from a single piezometer head chronicle. Journal of Hydrology, 642. https://doi.org/10.1016/j.jhydrol.2024.131859

Abhervé, R., Roques, C., De Dreuzy, J.-R., Datry, T., Brunner, P., Longuevergne, L., & Aquilina, L. (2024). Improving calibration of groundwater flow models using headwater streamflow intermittence. Hydrological Processes, 38(6). https://doi.org/10.1002/hyp.15167

Abhervé, R., Roques, C., Gauvain, A., Longuevergne, L., Louaisil, S., Aquilina, L., & de Dreuzy, J.-R. (2023). Calibration of groundwater seepage against the spatial distribution of the stream network to assess catchment-scale hydraulic properties. Hydrology and Earth System Sciences, 27(17), 3221-3239. https://doi.org/10.5194/hess-27-3221-2023

## How to cite

If HydroModPy supports your work, please cite the technical note:

Gauvain, A., Abhervé, R., Boivin, B., Roques, C., Le Mesnil, M., Coche, A., Babey, T., Marçais, J., Bouchez, C., Leray, S., Marti, E., Bresciani, E., Figueroa, R., Pélissier, M., Guillaumot, L., Touzeau, T., Issolah, I., Maugan, E., Bagagnan, R. S., Vautier, C., Sallou, J., Bourcier, J., Combemale, B., Brunner, P., Longuevergne, L., Aquilina, L., and de Dreuzy, J.-R. (2026). Technical note: HydroModPy - a Python toolbox for deploying catchment-scale shallow groundwater models. EGUsphere [preprint]. https://doi.org/10.5194/egusphere-2026-868

## License

HydroModPy is released under the Eclipse Public License v2.0 (EPL-2.0). See
[LICENSE](LICENSE).

## Contact

For any question regarding HydroModPy, please contact:

- <alexandre.gauvain.ag@gmail.com>
- <ronan.abherve@inrae.fr>
- <bastien.boivin@proton.me>
- <jean-raynald.de-dreuzy@univ-rennes.fr>
