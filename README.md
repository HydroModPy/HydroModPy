![logo](https://gitlab.com/Alex-Gauvain/HydroModPy/-/raw/master/docs/readthedocs/source/images/logoHydroModPy_long.png)

HydroModPy: A Python toolbox for deploying catchment-scale shallow groundwater models.

[![Documentation Status](https://readthedocs.org/projects/hydromod/badge/?version=latest)](https://hydromod.readthedocs.io/?badge=latest)

## Presentation

HydroModPy was initiated in 2018 to streamline the deployment of hydrological models in catchments across the crystalline basement regions of Normandy and Brittany, France. The platform integrates a wide range of open-source packages (FloPy, WhiteBoxTools, etc.), making them easily accessible and shareable among scientific communities.
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

- GitLab Project: https://gitlab.com/Alex-Gauvain/HydroModPy/
- Read the Docs: https://hydromod.readthedocs.io/
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
# or include Spyder + JupyterLab
pip install "hydromodpy[ide]"
```

For development mode (editable installation):

```bash
# Clone the repository (see Git installation options below)
cd HydroModPy

# Install in editable mode
pip install -e .

# PyHELP binaries are automatically downloaded on first import
```

### Option 2: conda environment

Two ready-to-use Conda recipes live in `install/`:

- `env_hydromodpy.yml` installs every runtime dependency (including Spyder) so you
  can run scripts and notebooks right away.
- `env_hydromodpy_pkg.yml` mirrors the same stack but finishes with
  `pip install -e ..` to expose the local repository as a package.

```bash
# from the repository root
conda env create -f install/env_hydromodpy.yml -n hydromodpy
conda activate hydromodpy

# editable/package variant
conda env create -f install/env_hydromodpy_pkg.yml -n hydromodpy-pkg
conda activate hydromodpy-pkg
```

### Git installation

To obtain the source code for development:

**Option 1**: Download the `.zip` folder directly from the [GitLab project](https://gitlab.com/Alex-Gauvain/HydroModPy/)

**Option 2**: Clone the repository using a Git management tool like GitHub Desktop

**Option 3**: Use command line with classical Git functions:

```bash
git clone https://gitlab.com/Alex-Gauvain/HydroModPy.git
cd HydroModPy
```

## Launch HydroModPy

(1) Activate HydroModPy environment:
```bash
conda activate hydromodpy-3119
```

(2) Open Spyder or Jupyter Notebook:
```bash
spyder
# or
jupyter notebook
```

(3) Import HydroModPy in Python:

```python
import hydromodpy
from hydromodpy import Watershed

# Check version
print(hydromodpy.__version__)
```

## Usage Examples

Execute Python scripts following the examples below:
```
 - 00_quick_test_of_wide_hydromodpy_capabilities
 - 01_simplified_example_presented_in_the_paper
 - 02_basic_features_and_overview_of_possibilities
 - 03_hydrographic_network_in_steady_state
 - 04_streamflow_intermittence_in_transient
 - 05_piezometry_in_a_heterogeneous_coastal_aquifer
 - 06_particle_tracking_and_residence_times
 - 07_analytical_solution_for_streamflow_recession
 - 08_exponential_distribution_of_residence_times
 - 09_transport_model_for_an_agricultural_catchment
 - 10_coupling_with_land_surface_model_pyhelp
 - 11_for_run_from_scratch_without_plots
```

## Linked publications

Papers published using HydroModPy.

Abhervé, R., Roques, C., de Dreuzy, J.-R., Van Der Veen, T., Dumaine, L., Chatton, E., Brunner, P., Aquilina, L., & Servière, L. (2025). Projected climate change impacts on groundwater-surface water connectivity in a compartmentalized mountain headwater bedrock aquifer. Water Resources Research, 61(10), https://doi.org/10.1029/2025WR040083

Marti, E., Leray, S., & Roques, C. (2024). Catchment landforms predict groundwater-dependent wetland sensitivity to recharge changes. Hydrology and Earth System Sciences Discussions. https://doi.org/10.5194/HESS-2024-381

Floriancic, M. G., Abhervé, R., Bouchez, C., Martinez, J. J., & Roques, C. (2024). Evidence of Groundwater Seepage and Mixing at the Vicinity of a Knickpoint in a Mountain Stream. Geophysical Research Letters, 51. https://doi.org/10.1029/2024GL111325

Le Mesnil, M., Gauvain, A., Gresselin, F., Aquilina, L., & Dreuzy, J. De. (2024). Characterizing coastal aquifer heterogeneity from a single piezometer head chronicle. Journal of Hydrology, 131859. https://doi.org/10.1016/j.jhydrol.2024.131859

Abhervé, R., Roques, C., De Dreuzy, J.-R., Datry, T., Brunner, P., Longuevergne, L., & Aquilina, L. (2024). Improving calibration of groundwater flow models using headwater streamflow intermittence. Hydrological Processes, 38((6)). https://doi.org/10.1002/hyp.15167

Abhervé, R., Roques, C., Gauvain, A., Longuevergne, L., Louaisil, S., Aquilina, L., & de Dreuzy, J.-R. (2023). Calibration of groundwater seepage against the spatial distribution of the stream network to assess catchment-scale hydraulic properties. Hydrology and Earth System Sciences, 27(17), 3221–3239. https://doi.org/10.5194/hess-27-3221-2023

## Coresponding authors

For any questions regarding HydroModPy, please contact us at <alexandre.gauvain.ag@gmail.com> or <ronan.abherve@gmail.com>

## Abstract for the congress IAH 2024

The need for predictive models increases as the pressure of global change intensifies. Regional-scale modeling of shallow unconfined aquifers (10-100 m depth) remains challenging, especially in complex basement aquifers. Controlled both by topography and geology, groundwater flows are organized from hillslope to catchment scale. It is particularly the case in crystalline regions with low aquifer volumes and wet climates, resulting in significant subsurface-surface interactions with very few information available to constrain models.

To address this, we present HydroModPy, an application developed in Python as a toolbox for automatic deployment of groundwater flow models. HydroModPy integrates geospatial processing (WhiteBoxTools) with groundwater flow and transport simulation tools (MODFLOW and MODPATH via FloPy). It is designed to call other groundwater flow solvers, facilitate multi-site deployment, integrate pre- and post-processing functions such as catchment extraction from a DEM and an advanced representation of head and flow results. Emphasis is placed on integrating aquifer geometry complexities and hydraulic properties heterogeneity (compartmentalization, exponential decay, implementation of a 3D geological model, etc.).

HydroModPy's user-friendly Python interface allows for testing and exploring various aquifer models across different geomorphological contexts and recharge conditions. Ongoing improvements include methods for calibrating and estimating hydraulic properties using multiple datasets such as hydrographic network maps, streamflow, and piezometric level data. HydroModPy is developed as an open-source toolkit. It is currently being used in climate change effects on groundwater-dependent ecosystems and water resource management issues. Collaborative development should enhance the modeling capacity of near-surface aquifers, facilitate their extension to the regional scale for predictive purposes.

## How to cite

A paper about HydroModPy is in preparation for the journal Technical Note: Hydrology and Earth System Sciences.

Gauvain, A., Abhervé, R., Coche, A., Le Mesnil, M., Roques, C., Bouchez, C., Marçais, J., Leray, S., Marti, E., Figueroa, R., Bresciani, E., Vautier, C., Boivin, B., Sallou, J., Bourcier, J., Combemale, B., Longuevergne, L., Aquilina, L., and de Dreuzy, J.-R. (2025). Technical note: HydroModPy – a Python toolbox for deploying catchment-scale shallow groundwater models. Hydrology and Earth System Sciences. In prep.
