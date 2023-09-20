# HydroModPy [![Documentation Status](https://readthedocs.org/projects/hydromod/badge/?version=latest)](https://hydromod.readthedocs.io/?badge=latest)
![logo](./docs/readthedocs/source/images/logoHydroModPy_long.png)

A tool to build hydrological model at catchment scale in Python.

## Installation
        
+--------------------------------------------------------------------+  
|      __  __          __           ____ ___            ________     |  
|     / / / /         / /          / __ `__ \          / / __  /     |  
|    / /_/ /_  ______/ /________  / / / / / /___  ____/ / /_/ /_  __ |  
|   / __  / / / / __  / ___/ __ \/ / / / / / __ \/ __  / ____/ / / / |  
|  / / / / /_/ / /_/ / /  / /_/ / /  \/ / / /_/ / /_/ / /   / /_/ /  |  
| /_/ /_/\__  /_____/_/   \____/_/     /_/\____/_____/_/____\__  /   |  
|       /____/ Hydrological Modelling in Python /_______________/    |  
|                                                                    |  
+--------------------------------------------------------------------+  
      
 
Before install HydromodPy, check Requirements in the next part.

Install Git:
https://git-scm.com/book/en/v2/Getting-Started-Installing-Git

Go to the folder where you want to install HydroModPy:
```
cd "path/where/you/want/clone/Hydromodpy"
```

Clone HydroModPy repository:
```
git clone https://gitlab.com/Alex-Gauvain/HydroModPy.git
```

Go to stable branch:
```
git checkout "v0.1"
```

Go to install folder:

```
cd HydroModPy/install
```

HydroModPy can be installed for Windows and Linux with bash file in the "install" directory :

For Linux :
```
./install.sh
```
For Windows : double clik on install.sh

OR 

Alternatively, HydroModPy can be installed with conda using .yml file in the "install" directory :
```
conda env create -f environment.yml -n hydromodpy 
```

Install ChromeDriver for Selenium library
Selenium is a library that manages interaction with files in the web
It requires the following file to be downloaded: https://chromedriver.chromium.org/downloads
The .exe should be stored in a file
The directory name of the file should be added to the user path of the environment variables (configuration pannel -> system -> system parameter -> environment variables)
Click on "Path" -> modify -> add path of the .exe

## Run HydroModPy

(1) Activate HydroModPy environment :
```
conda activate hydromodpy
```

(2) Open Spyder or Jupyter lab :
```
spyder
jupyter lab
```

(3) Execute python script following examples below

## Requirements

To install HydroModPy, Anaconda3 or Miniconda3 must be installed on your computer.

Works with python>=3.8.10 and pip 23.2.1

The following python packages will be installed with the installation procedure:
  - gdal=3.0.2
  - contextily==1.3.0
  - deepdish==0.3.7
  - flopy==3.3.4
  - geopandas==0.12.2
  - hydroeval==0.1.0
  - imageio==2.31.1
  - jupyter==1.0.0
  - matplotlib_scalebar==0.8.1
  - netcdf4==1.6.4
  - notebook==7.0.0
  - numpy==1.24.3
  - pandas==1.5.3
  - pyproj==3.5.0
  - pyshp==2.3.1
  - rasterio==1.2.10
  - rtree==1.0.1
  - selenium==4.10.0
  - spyder==5.0.0
  - vedo==2023.4.6
  - xarray==2023.1.0
  - whitebox==2.3.1
   
 ## Examples
 
 There is some example notebooks :
 - 01_basic : examples with overview of possibilities
 - 02_hydrographic : hydrographic network in steady state
 - 03_streamflow : streamflow and intermittency in transient state
 - 04_piezometry : piezometry in a coastal context
 - 05_particle : conceptual particle traking for residence times
 - 06_heterogeneity : aquifer complexity and heterogeneity
 - 07_calibration : calibration and multiobjective optimization
 
 ## Publications
 Papers was published on the HydroModPy concept and its different capabilities.
 
 Abhervé, R., Gauvain, A., Roques, C., Longuevergne, L., Louaisil, S., Aquilina, L., and de Dreuzy, J.-R.: Calibration of groundwater seepage on the spatial distribution of the stream network to assess catchment-scale hydraulic conductivity, Hydrol. Earth Syst. Sci. Discuss., 2022.
 [link](https://doi.org/10.5194/hess-2022-175).

 ## Contact
 For any questions regarding HydroModPy, please contact us at <alexandre.gauvain.ag@gmail.com> or <ronan.abherve@unine.ch>
