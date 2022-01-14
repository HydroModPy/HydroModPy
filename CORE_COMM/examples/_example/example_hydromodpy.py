# -*- coding: utf-8 -*-
"""
Created on Mon Dec 20 08:05:41 2021

@author: Ronan Abhervé
"""

# GENERAL LIBRARIES

# General
import sys
import os
from os.path import dirname, abspath
DIR = dirname(dirname(dirname(abspath(__file__))))
sys.path.append(DIR)
from glob import glob
import numpy as np
import pandas as pd
from osgeo import gdal, osr
from IPython import get_ipython

get_ipython().run_line_magic('matplotlib', 'inline')
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
import logging
import warnings
# warnings.filterwarnings("ignore", message=".*An exception was ignored while fetching the attribute.*", category=DeprecationWarning)
# warnings.filterwarnings("ignore", message=".*`np.object` is a deprecated alias for the builtin `object`.*", category=DeprecationWarning)
# warnings.filterwarnings("ignore", message=".*is deprecated. Use tobytes().*", category=DeprecationWarning)
# warnings.filterwarnings("ignore", message=".*`np.typeDict` is a deprecated alias for `np.sctypeDict`.*", category=DeprecationWarning)
# warnings.filterwarnings("ignore") # not working
# warnings.simplefilter("ignore", category=DeprecationWarning) # not working
# warnings.warn("You won't see this warning", category=DeprecationWarning) # to modify warnings
logging.captureWarnings(True)
                 
# HYDROMODPY MODULES
         
from watershed import watershed_root, forcing, watershed_display
from tools import tif_adds, serie_transf, tif_features, file_adds, to_plot, vtk
from watershed.data import hydrology, climatic, oceanic, piezometry
from groundwater_flow import plots

# LAYOUT PLOT

fontprop = to_plot.plot_params(8,15,18,20) # small, medium, interm, large

# NECESSARY PATHS

# Path to the git repositoty home page
git_path = DIR
# Path to the test folder
test_path = git_path + "/examples/_example/"
# Path where the results will be stored
# out_path = "D:/Users/abherve/TEST/"
out_path = "C:/Users/alexa/Dropbox/HydroModPy/"

# We suggest to store the data in specific folder
dems_path = test_path + 'dem/'
hydrology_path = test_path + 'hydrology/' # add hydrographic shapefiles
modflow_path = test_path + 'modflow/' # add bin/ folder with necessary .exe
climate_path =test_path + 'climate/'

piezometry_path = None # add piezometry data or nothing for automatic download
geology_path = None # add geologic layers
oceanic_path = None # add specific sea level files
# Specifically designed to process SURFEX data (France scale)
surfex_path =  None # add surfex models in .h5 format

# Indicate the name of the regional DEM
dem_name = "DEM_test_75m_LAMB93.tif"
# dem_name = "DEM_bzh_75m_LAMB93.tif"
dem_path = dems_path + dem_name

dem = gdal.Open(dem_path)
proj = osr.SpatialReference(wkt=dem.GetProjection())
crs = int(proj.GetAttrValue('AUTHORITY',1))

# Import the library of watersheds to generate
library_path = test_path + 'watershed_library.csv' # each row is a study site
library = pd.read_csv(library_path, sep=';', header=0, engine='python') # explore catchment studied

# Select from the library the interest catchment
watershed_name = 'Example' # add manually study site information in map units
mysite = library[library['watershed_name'] == watershed_name] # specific row

# Paths generated automatically but necessary for plots
stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'

# Specify the hydrologic layers to clip
types_obs = ['streams','sections'] # list of shapefile name layers
fields_obs = ['FID','Persistanc'] # list of shapefile name columns to translate in a tif

# GENERATING WATERSHED

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

watershed_display.watershed_dem(BV)
watershed_display.watershed_local(dem_path, BV)

# SET PARAMETERS

# Choice the state of the simulation
sim_state = 'steady' # steady
first = 2010
last = 2019
time_step = 'M'

# Recharge from a csv
rec = pd.read_csv(climate_path+'_REC_'+time_step+'.csv', sep=';', index_col=[0], parse_dates=True)
rec = rec[(rec.index.year>=first) & (rec.index.year<=last)]
rec = rec.squeeze()
BV.forcing.update_recharge(values = rec / 1000, sim_state=sim_state)

# Finally the rehcarge is set as a value or a serie
R = BV.forcing.recharge # mm/month to m/month

# Plot to control recharge
if sim_state == 'transient':
    fig, ax = plt.subplots(1,1, figsize=(6,3))
    ax.plot(R*1000, c='k', lw=0.5)

# Update hydrualic conductivity
K = 1e-5 * 3600 * 24 * 30 # m/second to m/month
BV.hydrodynamic.update_hyd_cond(K)

# Update aquifer thickness
E = 30 # m
BV.hydrodynamic.update_thickness(E)

# Update effective porosity
P = 0.01 # -
BV.hydrodynamic.update_porosity(P)

# Set name of the model
model_name = sim_state

# RUN MODEL
# Launch a model
BV.run_modflow(ident=model_name, modpath_sim=True, calib=False, sink_fill=False, 
                lay_number=1, bottom=None, thick_exp=1., cond_decay=0., 
                verbose=True)

print('Modeling process completed')

# Extract result chronics
BV.chronics_modflow(ident=model_name, mask=False, outlet_type=True, calib_only=False, 
                    first=first, last=last, time_step='monthly')
print('Result chronics extraction completed')

# VISUALIZATION 3D

from groundwater_flow import visualization
vtk.VTK(BV, model_name)
visu = visualization.Visualization(BV, model_name)
visu.visual3D(interactive=1, object_list=['grid','watertable', 'watertable_depth','pathlines', 'surface_flow', 'drain_flow'], view='north-west', z_scale=5, lines=150, render=1, cloc=(0.7,0.1))

#%% PLOT SURFACE OUTPUTS

if sim_state=='transient':
    plots.SurfaceOutputs(R, simulations_folder, stable_folder, model_name, types_obs, freq_interv=12, save_gif=True)

#%% INTERACTIVE CROSS-SECTION

# Dem data
dem_data = BV.geographic.dem_data
# dem_data = imageio.imread(stable_folder+'/geographic/'+'watershed_box_buff_dem.tif')
# dem_data = imageio.imread(stable_folder+'/geographic/'+'watershed_dem.tif')

# Wt data
wt_data = imageio.imread(simulations_folder+model_name+'/_extraction/'+'watertable_elevation_(000).tif') # buffer size no masked

# River data
river_data = imageio.imread(stable_folder+'/hydrology/'+'sections.tif')

# Function
plots.interactive_cross_section(dem_data, wt_data, river_data, interactive=True)

#%%
