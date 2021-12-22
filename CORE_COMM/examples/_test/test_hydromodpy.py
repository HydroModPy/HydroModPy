# -*- coding: utf-8 -*-
"""
Created on Mon Dec 20 08:05:41 2021

@author: Ronan Abhervé
"""

#%% GENERAL LIBRARIES

# General
import sys
import os
from os.path import dirname, abspath
DIR = dirname(dirname(abspath(__file__)))
sys.path.append(DIR)
from glob import glob
import numpy as np
import pandas as pd
from osgeo import gdal, osr
# Plot
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
import matplotlib as mpl
from matplotlib.dates import YearLocator, MonthLocator, DateFormatter
from mpl_toolkits.axes_grid1 import make_axes_locatable
from matplotlib.colors import LightSource
from matplotlib.pyplot import cm
from matplotlib.ticker import MaxNLocator
# Gis
from osgeo import gdal
import imageio
import rasterio
import geopandas as gpd
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = True
# Warnings
import warnings
warnings.filterwarnings("ignore", message=".*An exception was ignored while fetching the attribute.*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*`np.object` is a deprecated alias for the builtin `object`.*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*is deprecated. Use tobytes().*", category=DeprecationWarning)
warnings.filterwarnings("ignore")
# warnings.warn("You won't see this warning")
                 
#%% HYDROMODPY MODULES
                    
from watershed import watershed_root, forcing
from tools import tif_adds, serie_transf, tif_features, file_adds, to_plot, vtk
from watershed.data import hydrology, climatic, oceanic, piezometry

#%% LAYOUT PLOT

fontprop = to_plot.plot_params(8,15,18,20) # small, medium, interm, large

#%% NECESSARY PATHS

# Path to the git repositoty home page
git_path = "D:/Users/abherve/GITHUB/HydroModPy/CORE_COMM/"
# Path to the test folder
test_path = git_path + "examples/_test/"
# Path where the results will be stored
out_path = "D:/Users/abherve/TEST/"

# We suggest to store the data in specific folder
dems_path = test_path + 'dem/'
hydrology_path = test_path + 'hydrology/' # add hydrographic shapefiles
modflow_path = test_path + 'modflow/' # add bin/ folder with necessary .exe

piezometry_path = None # add piezometry data or nothing for automatic download
geology_path = None # add geologic layers
oceanic_path = None # add specific sea level files

# Specifically designed to process SURFEX data (France scale)
surfex_path =  test_path + 'surfex/' # add surfex models in .h5 format

# Indicate the name of the regional DEM
dem_name = "DEM_test_75m_LAMB93.tif"
# dem_name = "BDALTI_bzh_75m.tif"
dem_path = dems_path + dem_name

dem = gdal.Open(dem_path)
proj = osr.SpatialReference(wkt=dem.GetProjection())
crs = int(proj.GetAttrValue('AUTHORITY',1))

# Import the library of watersheds to generate
library_path = test_path + 'watershed_library.csv' # each row is a study site
library = pd.read_csv(library_path, sep=';', header=0, engine='python') # explore catchment studied

# Select from the library the interest catchment
watershed_name = 'Test' # add manually study site information in map units
mysite = library[library['watershed_name'] == watershed_name] # specific row

# Paths generated automatically but necessary for plots
stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'

# Specify the hydrologic layers to clip
types_obs = ['streams'] # list of shapefile name layers
fields_obs = ['FID'] # list of shapefile name columns to translate in a tif

#%% GENERATING WATERSHED

load = True
print('##### '+watershed_name.upper()+' #####')

# try:
BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=dem_path, 
                              out_path=out_path,
                              surfex_path=surfex_path, 
                              geology_path = geology_path, 
                              hydrology_path=hydrology_path,
                              oceanic_path=oceanic_path, 
                              piezometry_path=piezometry_path,
                              modflow_path=modflow_path,
                              library_path=library_path,
                              load=load,
                              types_obs=types_obs,
                              fields_obs=fields_obs)
# except:
#     print('There is a problem to generate the watershed object')

#%% REPROJECT LAYER

if crs == 4326:

    # Reproject raw DEM in WGS84 to specific UTM
    utm_crs = tif_adds.reproject_tif(dem_path,
                                     test_path + 'dem/' + "DEM_test_75m_WGS84" + '.tif',
                                     stable_folder + 'dem/' + "DEM_test_75m_UTM" + '.tif')
    
    # Reproject shapefile layer to specific UTM
    tif_adds.reproject_shp(test_path + 'hydrology/' + types_obs[0] + '.shp',
                           test_path + 'hydrology/' + types_obs[0] + '_utm' + '.shp',
                           utm_crs)
    
    # Convert longitude and latitude WGS84 to specific UTM
    utm_crs, x_utm, y_utm = tif_adds.reproject_coord(-4.53924,
                                                     48.62315)

#%% SET PARAMETERS

# Choice the state of the simulation
sim_state = 'steady' # steady
first = 1995
last = 2000
time_step = 'M'

# If recharge SURFEX is available
# surfex_path=None
if surfex_path != None :
    BV.forcing.update_recharge_surfex(clim_mod = 'REA', clim_sce='historic',
                                      first_year = first, last_year = last, 
                                      time_step = time_step, sim_state=sim_state)
# If recharge SURFEX is note available
else:
    BV.forcing.update_recharge(values = [0.0275], sim_state=sim_state)

# Finally the rehcarge is set as a value or a serie
R = BV.forcing.recharge / 30 # m/month to m/day

# Plot to control recharge 
fig, ax = plt.subplots(1,1, figsize=(6,3))
ax.plot(R*1000, c='k', lw=0.5)

# Update hydrualic conductivity
K = 1e-5 * 3600 * 24 # m/second to m/day
BV.hydrodynamic.update_hyd_cond(K)

# Update aquifer thickness
E = 30 # m
BV.hydrodynamic.update_thickness(E)

# Update effective porosity
P = 0.01 # -
BV.hydrodynamic.update_porosity(P)

# Set name of the model
model_name = 'test_1'

#%% RUN MODEL

BV.run_modflow(ident=model_name, modpath_sim=True, calib=False, sink_fill=False, 
                lay_number=1, bottom=None, thick_exp=1., sea_level=0, cond_decay=0., 
                verbose=True)

#%% VISUALIZATION 3D

from groundwater_flow import vizualisation
vtk.VTK(BV, model_name)
visu = vizualisation.Vizualisation(BV, model_name)
visu.visual3D(interactive=True, object_list=['grid','watertable','pathlines','watertable_depth'], view='south-west')

#%% PLOT SURFACE OUTPUTS


#%% NOTES

