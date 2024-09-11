![logo](docs/readthedocs/source/images/logoHydroModPy_long.png)

HydroModPy: A versatile Python toolbox for automating multi-site groundwater modeling with subsurface-surface interactions.

Stable current version: v0.1 [![Documentation Status](https://readthedocs.org/projects/hydromod/badge/?version=latest)](https://hydromod.readthedocs.io/?badge=latest)

## Abstract

HydroModPy was initiated in 2018 to streamline the deployment of hydrological models in catchments across the crystalline basement regions of Normandy and Brittany, France. The platform integrates a wide range of open-source packages (FloPy, WhiteBoxTools, etc.), making them easily accessible and shareable among scientific communities. 
The development of HydroModPy was driven by two primary objectives. First, it automates the extraction and discretization of watersheds from Digital Elevation Models (DEMs), while adding essential data available (e.g. piezometry, hydrography, geology) from both national and global databases. This ensures a standardized process for setting up and running simulation batches across different watersheds with uniform input data.
The second goal is to facilitate the visualization and comparison of results from the various modeling programs included within the platform. In addition to its scientific applications, HydroModPy also serves as a valuable educational tool, enabling students and researchers to explore hydrogeological modeling in a practical context.

## Authors

Alexandre Gauvain [4], Ronan Abhervé [1],  Martin Le Mesnil [2],  Alexandre Coche [2], Clément Roques [1], Jean Marçais [4], Philip Brunner [2], Camille Bouchez [2], Etienne Marti [8], Ronny Figieroa [1], June Sallou [6], Johan Bourcier [3], Benoit Combemale [3], Hélène Hivert [2], Camille Vautier [2], Nicolas Cornette [2], Sarah Leray [8], Etienne Bresciani [7], Laurent Longuevergne [2], Luc Aquilina [2], Jean-Raynald de Dreuzy [2]. 

- [1] Centre for Hydrogeology and Geothermics (CHYN), Université de Neuchâtel, Neuchâtel, Switzerland
- [2] Univ Rennes, CNRS, Geosciences Rennes - UMR 6118, Rennes, France
- [3] Univ Rennes, Inria, CNRS, IRISA, Rennes, France
- [4] Laboratoire de Météorologie Dynamique (LMD), CNRS, Sorbonne Université, Paris, France
- [5] INRAE, RiverLy, Centre de Lyon-Villeurbanne, Villeurbanne, France
- [6] SERG, Delft University of Technology, Delft, Netherlands
- [7] Universidad de O'Higgins, Rancagua, Chile
- [8] Pontificia Universidad Católica de Chile, Departamento de Ingeniería Hidráulica y Ambiental, Santiago, Chile

## Links

- GitLab software: https://gitlab.com/Alex-Gauvain/HydroModPy
- Read the Docs documentation: https://hydromod.readthedocs.io/en/latest/

- Further information on Google Drive: https://docs.google.com/document/d/11BA4ufhYWbydBvfjQufohoPIc0SaF9pKcyj_KNJ2VQM/edit?usp=sharing
- HydroModPy Users Group: https://groups.google.com/g/hydromodpy

## Git installation

Option 1 : Download zip code directly on this packages

Option 2 : Install with following commands

Step 1 - Install Git:
https://git-scm.com/book/en/v2/Getting-Started-Installing-Git

Step 2 - Opned terminal as administrator (recommended).

Step 3 - Go to the folder where you want to install HydroModPy:
```
cd /d "path/where/you/want/clone/HydroModPy"
```

Step 4 - Clone HydroModPy repository:
```
git clone https://gitlab.com/Alex-Gauvain/HydroModPy.git
```

Step 5 - Go to stable branch:
```
git checkout "v0.1"
```

Step 6 - Go to install folder:
```
cd HydroModPy/install
```

## Environment installation

HydroModPy environment can be installed with "conda" using .yml file in the "install" directory:
```
cd /d "path/where/is/the/install/directory/"
conda env create -f environment_windows.yml -n hydromodpy-0.1
```

## Launch HydroModPy

(1) Activate HydroModPy environment :
```
conda activate hydromodpy-0.1
```

(2) Open Spyder or Jupyter Notebook :
```
spyder
jupyter notebook
```

(3) Execute python script following examples below
```
In spyder or jupyter notebook
```

## Library requirements

To install HydroModPy, Anaconda3 or Miniconda3 must be installed on your computer.
   
## Available examples
 
There is some example notebooks :
 - 00_simplified example presentend in the paper
 - 01_basic features and overview of possibilities
 - 02_hydrographic network in steady state
 - 03_streamflow intermittence in transient
 - 04_piezometry in a heterogeneous coastal aquifer
 - 05_particle tracking for residence times
 
## Linked publications
Papers published using HydroModPy.

Floriancic, M. G., Abhervé, R., Bouchez, C., Martinez, J. J., & Roques, C. (2024). Evidence of Groundwater Seepage and Mixing at the Vicinity of a Knickpoint in a Mountain Stream. Geophysical Research Letters, 51. https://doi.org/10.1029/2024GL111325

Le Mesnil, M., Gauvain, A., Gresselin, F., Aquilina, L., & Dreuzy, J. De. (2024). Characterizing coastal aquifer heterogeneity from a single piezometer head chronicle. Journal of Hydrology, 131859. https://doi.org/10.1016/j.jhydrol.2024.131859

Abhervé, R., Roques, C., De Dreuzy, J.-R., Datry, T., Brunner, P., Longuevergne, L., & Aquilina, L. (2024). Improving calibration of groundwater flow models using headwater streamflow intermittence. Hydrological Processes, 38((6)). https://doi.org/10.1002/hyp.15167

Abhervé, R., Roques, C., Gauvain, A., Longuevergne, L., Louaisil, S., Aquilina, L., & de Dreuzy, J.-R. (2023). Calibration of groundwater seepage against the spatial distribution of the stream network to assess catchment-scale hydraulic properties. Hydrology and Earth System Sciences, 27(17), 3221–3239. https://doi.org/10.5194/hess-27-3221-2023

## Coresponding authors
For any questions regarding HydroModPy, please contact us at <alexandre.gauvain.ag@gmail.com> or <ronan.abherve@gmail.com>

## Abstract for congress IAH 2024
The need for predictive models increases as the pressure of global change intensifies. Regional-scale modeling of shallow unconfined aquifers (10-100 m depth) remains challenging, especially in complex basement aquifers. Controlled both by topography and geology, groundwater flows are organized from hillslope to catchment scale. It is particularly the case in crystalline regions with low aquifer volumes and wet climates, resulting in significant subsurface-surface interactions with very few information available to constrain models.

To address this, we present HydroModPy, an application developed in Python as a toolbox for automatic deployment of groundwater flow models. HydroModPy integrates geospatial processing (WhiteBoxTools) with groundwater flow and transport simulation tools (MODFLOW and MODPATH via FloPy). It is designed to call other groundwater flow solvers, facilitate multi-site deployment, integrate pre- and post-processing functions such as catchment extraction from a DEM and an advanced representation of head and flow results. Emphasis is placed on integrating aquifer geometry complexities and hydraulic properties heterogeneity (compartmentalization, exponential decay, implementation of a 3D geological model, etc.).

HydroModPy's user-friendly Python interface allows for testing and exploring various aquifer models across different geomorphological contexts and recharge conditions. Ongoing improvements include methods for calibrating and estimating hydraulic properties using multiple datasets such as hydrographic network maps, streamflow, and piezometric level data. HydroModPy is developed as an open-source toolkit. It is currently being used in climate change effects on groundwater-dependent ecosystems and water resource management issues. Collaborative development should enhance the modeling capacity of near-surface aquifers, facilitate their extension to the regional scale for predictive purposes.

## How to cite
A paper is in preparation. Target of the journal: Hydrology and Earth System Sciences. 

Gauvain, A., Abhervé, R., Le Mesnil, M., Roques, C., Coche, A., Marçais, J., Marti, E., Sallou, J., Bourcier, J., Bouchez, C., Figueroa, R., Cornette, N., Leray, S., Bresciani, E., Combemale, B., Vautier, C., Hivert, H., Longuevergne, L., Aquilina, L., and de Dreuzy, J.-R. HydroModPy: A versatile Python toolbox for automating multi-site groundwater modeling with subsurface-surface interactions. In preparation for Hydrology and Earth System Sciences.
