# -*- coding: utf-8 -*-
"""
Created on Mon Dec 20 08:05:41 2021

@author: Ronan Abhervé
"""

#%% GENERAL LIBRARIES

# General
import sys
from os.path import dirname, abspath
DIR = dirname(dirname(dirname(abspath(__file__))))
sys.path.append(DIR)
import numpy as np
import pandas as pd
from osgeo import gdal, osr
import matplotlib.pyplot as plt
import time
import os
import os.path
from os import path

# Gis
import imageio
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False


# Warnings
import warnings
warnings.filterwarnings("ignore", message=".*An exception was ignored while fetching the attribute.*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*`np.object` is a deprecated alias for the builtin `object`.*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*is deprecated. Use tobytes().*", category=DeprecationWarning)
warnings.filterwarnings("ignore")
# warnings.warn("You won't see this warning")

# for extraction ERA5
import geopandas as gpd
import xarray as xr 
import rioxarray

                 
#%% HYDROMODPY MODULES
                    
from watershed import watershed_root, watershed_display
from tools import toolbox, vtk
from groundwater_flow import visualization, modflow_display
from calibration import calib_root
from tools import vtk
from groundwater_flow import visualization
from tools import toolbox

#%% close windows explorer
import psutil
from subprocess import PIPE

#%% LAYOUT PLOT

#fontprop = toolbox.plot_params(8,15,18,20) # small, medium, interm, large

#%% PERSONAL PATHS

# Path to the git repositoty home page
git_path = "C:/Users/LocalAdmin/Documents/GitHub/HydroModPy/CORE_COMM/"
# Path to the data folder
data_path = "D:/GoogleDrive/1.TRAVAIL/PYTHON/project/alps_pyr/_data/"
# Path where the results will be stored
out_path = "D:/GoogleDrive/1.TRAVAIL/PYTHON/project/poschiavino/_out/"


#%% FOLDER DATA PATHS

# Specify path or boolean to active/enable modules
dems_path = data_path + 'dem/' # reginal DEM or conceptual DEM
shp_path = data_path + 'shp/' # if you want run a model from a shapefile
modflow_path = data_path + 'modflow/' # add bin/ folder with necessary .exe

surfex_path =  data_path + 'surfex/' # add surfex models in .h5 format (France scale, else, specify None)
geology_path = data_path + 'geology/' # add geologic layers
oceanic_path = data_path + 'oceanic/' # add specific sea level files
hydrology_path = data_path + 'hydrology/' # add hydrographic shapefiles
hydrometry_path = data_path + 'hydrometry/' # add hydrometry data for automatic download
intermittency_path = data_path + 'intermittency/' # add intermittency data for automatic download
piezometry_path = True # add piezometry data for automatic download
subbasin_path = True # generate subbasins from stations or manual points

library_path = data_path + 'watershed_library_GRDC_alps_pyr.csv' # each row is a study site with outlet coordinates
dem_name = "eu_dem_v11_E30-40N20_clip_alps_polyg_EPSG3035.tif" # name of dem
dem_path = dems_path + dem_name

ERA5_folder = data_path + 'climate/era5/'
ERA5_filename = 'adaptor.mars.internal-1646855474.1913588-16842-3-5ad8a136-1ff8-433e-a89f-a0c064ce1122.nc'

#find 
path_points = 'D:/GoogleDrive/1.TRAVAIL/PYTHON/project/poschiavino/_data/outlet_coord/poschiavino_outlet.shp'
points = gpd.read_file(path_points)


#watershed_name = 'poschiavino_z500'
watershed_name = 'poschiavino'
print('working on catchment #' + watershed_name)
x = points.loc[0,'X']
y = points.loc[0,'Y']

stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots

#############################
######## GENERATING WATERSHED
load = True
BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=dem_path, 
                              out_path=out_path,
                              modflow_path=modflow_path,
                              library_path=library_path,
                              load=load,
                              regio_out=True, from_xy=[x,y,500,25])


# watershed_display.watershed_dem(BV)
# watershed_display.watershed_local(dem_path, BV)

# SET PARAMETERS

# Choice the state of the simulation
sim_state = 'steady' # steady

# Finally the rehcarge is set as a value or a serie
R = BV.forcing.recharge

#%%
K = 1E-6 # m/s
BV.hydrodynamic.update_hyd_cond(K)
defKR = np.logspace(-1,1,9)

# Update aquifer thickness
# E = 100 # m
# BV.hydrodynamic.update_thickness(E)


for it in range(0,len(defKR)):
    
    KR = defKR[it]
    KR_name = round(KR, 2)
    
    model_name = watershed_name + '_z500' + "_KR_"+str(KR_name)

    # Update recharge
    rec = K/KR
    BV.forcing.update_recharge(values = (rec), sim_state=sim_state)

    # Update aquifer thickness
    # E = 100 # m
    # BV.hydrodynamic.update_thickness(E)
    
    # Update effective porosity
    P = 0.01 # -
    BV.hydrodynamic.update_porosity(P)
    
    # Choice temporal of the simulation
    period = [2017, 2019] # rehcarge period
    time_step = 'M' # or 'D'
    actual_date = True # False if date is conceptual
    start = str(period[0])+'-01-01' # necessary to specify the first time_step date
    
    first_only = False # if True generate results only for the first tim_step
    box = False # if True generate a rectangular model
    sink_fill = False # permit to fill sinks
    modpath_sim = False # run modpath particle tracking if True
    verbose = True # add print of MODFLOW in console
    
    # Strcture of the model
    lay_number = 1 # vertical discrtization
    bottom = 500 # aquifer flat or not
    thick_exp = 1 # exponential decay of K with nlay
    cond_decay = 0. # exponential decay of K with depth
    
    # Run model
    success,flow_model = BV.run_modflow(ident=model_name,
                    modpath_sim=modpath_sim,
                    first_only=first_only,
                    sink_fill=sink_fill,
                    box=box,
                    lay_number=lay_number,
                    bottom=bottom,
                    thick_exp=thick_exp,
                    cond_decay=cond_decay,
                    verbose=verbose)
    
    BV.matrix_modflow(success,
                      flow_model,
                      first_only = True,
                      watertable_elevation = True,
                      watertable_depth = True, 
                      seepage_areas = True,
                      outflow_drain = True,
                      groundwater_flux = True,
                      specific_discharge = False,
                      accumulation_flux = True,
                      perenn_intermit = False,
                      verbose = True,
                      export_tif = True)
    
    # Extract results
    BV.results_modflow(ident=model_name,
                       actual_date=actual_date,
                       start=start,
                       time_step=time_step)
    
    # 2D VISUALIZATION
    # save_name = 'test'+ str(KR)  
    # visu = visualization.Visualization(BV, model_name)
    # # visu.visual2D(object_list = ['map','grid', 'watertable', 'watertable_depth','drain_flow','surface_flow','pathlines', 'residence_times'],
    # #               color_scale = [(None,None),(0,140),(0,140),(0,2),(None,None),(None,None),(None,None),(None,None)], lines=10000)
    # R_visu = np.log10(rec*1000*365)
    # visu.visual2D(object_list = ['surface_flow','pathlines'],
    #               color_scale = [(R_visu-1,R_visu+2),(0,3)], lines=10)

#%% VISUALIZATION 3D

    # from tools import toolbox, vtk
    # vtk.VTK(BV, model_name)
    # visu = visualization.Visualization(BV, model_name)
    # visu.visual3D(interactive=True,
    #               object_list=['grid','watertable', 'watertable_depth','pathlines', 'surface_flow', 'drain_flow'],
    #               view='south-west', lines=200, cloc=(0.7,0.1))

# #%% PLOT SURFACE OUTPUTS
    
#     # if sim_state == 'transient':
#     #     modflow_display.SurfaceOutputs(R, simulations_folder, stable_folder, model_name,
#     #                                    types_obs, freq_interv=12, save_gif=True)
    
#     x = np.load(simulations_folder+'/test2/_watershed/accumulation_flux.npy', allow_pickle=True).item()
#     x = x[0]
#     x[x<=0] = np.nan
#     plt.imshow(x)

# #%% INTERACTIVE CROSS-SECTION

# # Dem data
# dem_data = BV.geographic.dem_data
# # dem_data = imageio.imread(stable_folder+'/geographic/'+'watershed_box_buff_dem.tif')
# # dem_data = imageio.imread(stable_folder+'/geographic/'+'watershed_dem.tif')

# # Wt data
# wt_data = imageio.imread(simulations_folder+model_name+'/_watershed/_tifs/'+'watertable_elevation_t(000).tif') # buffer size no masked

# # River data
# river_data = imageio.imread(stable_folder+'/hydrology/'+'sections.tif')

# # Function
# modflow_display.interactive_cross_section(dem_data, wt_data, river_data, interactive=True)
