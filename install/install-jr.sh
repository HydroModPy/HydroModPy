#!/bin/bash

echo '+--------------------------------------------------------------------+'
echo '|      __  __          __           ____ ___            ________     |'
echo '|     / / / /         / /          / __ `__ \          / / __  /     |'
echo '|    / /_/ /_  ______/ /________  / / / / / /___  ____/ / /_/ /_  __ |'
echo '|   / __  / / / / __  / ___/ __ \/ / / / / / __ \/ __  / ____/ / / / |'
echo '|  / / / / /_/ / /_/ / /  / /_/ / /  \/ / / /_/ / /_/ / /   / /_/ /  |'
echo '| /_/ /_/\__  /_____/_/   \____/_/     /_/\____/_____/_/____\__  /   |'
echo '|       /____/ Hydrological Modelling in Python /_______________/    |'
echo '|                                                                    |'
echo '+--------------------------------------------------------------------+'     

echo "###### Anaconda3 (or Miniconda) ######"

echo "Try to find Anaconda (or Miniconda)..."
echo "Can take several minutes..."

if [[ "$OSTYPE" == "linux-gnu"* ]]; then
  # Linux
  # Find conda.sh
  CONDA_PATH=$(find ~/ -type f -path "*conda3/etc/profile.d/conda.sh" 2>/dev/null)
  source $CONDA_PATH
elif [[ "$OSTYPE" == "darwin"* ]]; then
  # Mac OSX
  CONDA_PATH=$(find ~/ -type f -path "*conda3/etc/profile.d/conda.sh" 2>/dev/null)
  source $CONDA_PATH
elif [[ "$OSTYPE" == "msys" ]]; then
  # Windows
  #Find conda.sh
  CONDA_PATH=$(find C:/ -type f -path "*conda3/etc/profile.d/conda.sh" 2>/dev/null)
  source $CONDA_PATH
fi
echo $CONDA_PATH

# Install anaconda if  not installed
if [ -d "$CONDA_PATH" ];
then
  echo "Conda is not installed. Needd to install Anaconda3 or Miniconda before install HydroModPy"
else
  echo "Conda is already installed. Start to install HydroModPy environment"
fi
read -p "Press enter to install HydroModPy"

echo "###### Build Conda Environment ######"

# Delete if already install
conda deactivate
conda remove --name hydromodpy-test --all -y

# Build HydroModPy environment
conda create -y --name hydromodpy-test python=3.8.10

# Activate HydroModPy environment
conda activate hydromodpy-test

# Check Python version
python --version

echo "###### Install HydroModPy dependencies ######"

# Add necessary librairies

echo 'Install gdal'
conda install -c conda-forge gdal=3.0.2 -y
echo 'Install rasterio'
conda install -c conda-forge rasterio=1.2.10 -y #pip install numpy==1.2.10 --quiet
echo 'Install numpy'
pip install numpy==1.24.3 --quiet
echo 'Install pandas'
pip install pandas==1.5.3 --quiet
echo 'Install geopandas'
pip install geopandas==0.12.2 --quiet # geopandas install matplotlib
# pip install matplotlib==3.7.1 
echo 'Install deepdish'
pip install deepdish==0.3.7 --quiet
echo 'Install flopy'
pip install flopy==3.3.4 --quiet
echo 'Install imageio'
pip install imageio==2.31.1 --quiet
echo 'Install whitebox'
pip install whitebox==2.3.1 --quiet
echo 'Install vedo'
pip install vedo==2023.4.6 --quiet
echo 'Install hydroeval'
pip install hydroeval==0.1.0 --quiet
echo 'Install xarray'
pip install xarray==2023.1.0 --quiet
echo 'Install netCDF4'
pip install netCDF4==1.6.4 --quiet
echo 'Install matplotlib_scalebar'
pip install matplotlib_scalebar==0.8.1 --quiet
echo 'Install contextily'
pip install contextily==1.3.0 --quiet
echo 'Install pyproj'
pip install pyproj==3.5.0 --quiet
echo 'Install selenium'
pip install selenium==4.10.0 --quiet
echo 'Install pyshp'
pip install pyshp==2.3.1 --quiet
echo 'Install jupyter'
pip install jupyter==1.0.0 --quiet
echo 'Install notebook'
pip install notebook --quiet
echo 'Install rtree'
pip install 'rtree>=0.8.3' --quiet
echo 'Install spyder'
pip install spyder==5.4.3 --quiet

echo ''

echo "###### HydroModPy installation completed ######"

echo '+--------------------------------------------------------------------+'
echo '|      __  __          __           ____ ___            ________     |'
echo '|     / / / /         / /          / __ `__ \          / / __  /     |'
echo '|    / /_/ /_  ______/ /________  / / / / / /___  ____/ / /_/ /_  __ |'
echo '|   / __  / / / / __  / ___/ __ \/ / / / / / __ \/ __  / ____/ / / / |'
echo '|  / / / / /_/ / /_/ / /  / /_/ / /  \/ / / /_/ / /_/ / /   / /_/ /  |'
echo '| /_/ /_/\__  /_____/_/   \____/_/     /_/\____/_____/_/____\__  /   |'
echo '|       /____/ Hydrological Modelling in Python /_______________/    |'
echo '|                                                                    |'
echo '+--------------------------------------------------------------------+'  

echo 'Activate HydroModPy environment with this command : conda activate hydromodpy-test'
echo 'HydroModPy is installed. If necessary, you can check if all librairies are completely installed with this command: conda list'

read -p 'Press enter to finish installation...'


