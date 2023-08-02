#!/bin/bash

echo '+-------------------------------------------------------------+'
echo '| #  #  #  #  ###   ###    ##   #   #   ##   ###   ###   #  # |'
echo '| #  #   # #  #  #  #  #  #  #  ## ##  #  #  #  #  #  #   # # |'
echo '| ####    #   #  #  ###   #  #  # # #  #  #  #  #  ###     #  |'
echo '| #  #   #    #  #  # #   #  #  #   #  #  #  #  #  #      #   |' 
echo '| #  #  #     ###   #  #   ##   #   #   ##   ###   #     #    |'
echo '+-------------------------------------------------------------+'

echo "###### INSTALL ######"

echo "Try to find Anaconda (or Miniconda)..."
echo "Can take several minutes..."
FULL_PATH=$(find C:/ProgramData -type f -path "*conda3/etc/profile.d/conda.sh" 2>/dev/null)
CONDA_PATH=$(dirname "$FULL_PATH")
CONDA_PATH=$(dirname "$CONDA_PATH")
CONDA_PATH=$(dirname "$CONDA_PATH")
echo $CONDA_PATH

# Install anaconda if  not installed
if [ -d "$CONDA_PATH" ];
then
    echo "Conda is already installed. Start to install HydroModPy environment"
    install_conda='True'
else
	echo "Conda is not installed. Needd to install Anaconda3 or Miniconda before install HydroModPy"
  install_conda='False'
fi

if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        #Find conda.sh
	source $CONDA_PATH/etc/profile.d/conda.sh
elif [[ "$OSTYPE" == "darwin"* ]]; then
        # Mac OSX
	echo "Install for mac OSX will be setup soon"
elif [[ "$OSTYPE" == "msys" ]]; then
        #Find conda.sh
	source $CONDA_PATH/etc/profile.d/conda.sh
fi

read -p "Press enter to continue"

# Delete if already install
conda deactivate
conda remove --name hydromodpy-test --all -y

# Build HydroModPy environment
conda create -y --name hydromodpy-test python=3.8.10

# Activate HydroModPy environment
conda activate hydromodpy-test

# Check Python version
python --version

# Add necessary librairies
echo 'Install gdal'
conda install -c conda-forge gdal=3.0.2 -y
echo 'Install rasterio'
pip install rasterio==1.2.10 --quiet #conda install -c conda-forge rasterio=1.2.10
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
echo 'Install spyder'
pip install spyder==5.0.0 --quiet
echo 'Install rtree'
pip install 'rtree>=0.8.3' --quiet

echo ''

echo 'HydroModPy is installed. If necessary, you can check if all librairies are completely installed with this command: conda list'

echo '+-------------------------------------------------------------+'
echo '| #  #  #  #  ###   ###    ##   #   #   ##   ###   ###   #  # |'
echo '| #  #   # #  #  #  #  #  #  #  ## ##  #  #  #  #  #  #   # # |'
echo '| ####    #   #  #  ###   #  #  # # #  #  #  #  #  ###     #  |'
echo '| #  #   #    #  #  # #   #  #  #   #  #  #  #  #  #      #   |' 
echo '| #  #  #     ###   #  #   ##   #   #   ##   ###   #     #    |'
echo '+-------------------------------------------------------------+'

