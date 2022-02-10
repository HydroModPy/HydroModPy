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
                 
# HYDROMODPY MODULES
                    
from watershed import watershed_root, watershed_display
from tools import toolbox, vtk
from groundwater_flow import visualization, modflow_display
from calibration import calib_root

# LAYOUT PLOT

fontprop = toolbox.plot_params(8,15,18,20) # small, medium, interm, large

#%% PERSONAL PATHS

user = 'Ronan'

if user == 'Alexandre':
    # # Path to the git repositoty home page
    git_path = "C:/Users/alexa/Documents/GitHub/HydroModPy/CORE_COMM/"
    # # Path to the data folder
    data_path = "C:/Users/alexa/OneDrive/_HydroDataPy/TEST/"
    # # Path where the results will be stored
    out_path = 'C:/Users/alexa/Dropbox/HydroModPy/'

if user == 'Ronan':
    # Path to the git repositoty home page
    git_path = "D:/Users/abherve/GITHUB/HydroModPy/CORE_COMM/"
    # Path to the data folder
    data_path = "C:/Users/ronan/OneDrive/_HydroDataPy/TEST/"
    # Path where the results will be stored
    out_path = "D:/Users/abherve/TEST/"
    
if user == 'Clément':
    # Path to the git repositoty home page
    git_path = ""
    # Path to the data folder
    data_path = ""
    # Path where the results will be stored
    out_path = ""

#%% DATABASE ACCESS FOR THIS TESTS

# As an example, all data necessary for this test are stored in this OneDrive folder named 'TEST'

# Hyperlink :
'https://1drv.ms/f/s!ArPhnd6PZcHmjQg8qW15u2DWBR37'
# Password :
'osur-data-hydromodpy-2022'

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

library_path = data_path + 'watershed_library.csv' # each row is a study site with outlet coordinates

#%% TEST CHOICE

# We propose 4 tests :
    # 1 - From a outlet coordinates : 'Outlet'
    # 2 - From a shpaefile : 'Shapefile'
    # 3 - From an actual DEM : 'Dem'
    # 4 - From a conceptual DEM : 'Conceptual'

watershed_name = 'Outlet' # search the name in watershed_library or just label your result folder
print('##### '+watershed_name.upper()+' #####')

if watershed_name == 'Outlet':
    dem_name = "DEM_test_75m_LAMB93.tif" # name of dem
    from_shp = None # specify a path if process start from a given shapefile
    from_dem = False # True or False if the process start from a given DEM of xyz file
    cell_size = None # specify new resolution from a given DEM or None
    
if watershed_name == 'Shapefile':
    dem_name = "DEM_test_75m_LAMB93.tif"
    from_shp = shp_path + 'lambda.shp'
    from_dem = False
    cell_size = None

if watershed_name == 'Dem':
    dem_name = "DEM_circle_75m_LAMB93.tif"
    from_shp = None
    from_dem = True
    cell_size = None
    
if watershed_name == 'Conceptual':
    dem_name = 'topoxyz_Uhigh.txt'
    from_shp = None
    from_dem = True
    cell_size = 100

types_obs = ['streams','sections'] # list of shapefile name layers for clip hydrology
fields_obs = ['FID', 'Persistanc'] # list of shapefile name columns to translate as a tif

# Depending on the choices
dem_path = dems_path + dem_name

stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots

#%% GENERATING WATERSHED

load = True

BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=dem_path, 
                              out_path=out_path,
                              modflow_path=modflow_path,
                              library_path=library_path,
                              load=load,
                              from_shp=from_shp,
                              from_dem=from_dem,
                              cell_size=cell_size)

if watershed_name != 'Conceptual':
    if load != True :
        BV.add_surfex(surfex_path) 
        # BV.add_geology(geology_path) 
        # BV.add_hydrology(hydrology_path, types_obs=types_obs, fields_obs=fields_obs)
        # BV.add_oceanic(oceanic_path)
        # BV.add_hydrometry(hydrometry_path)
        # BV.add_intermittency(intermittency_path)
        # if piezometry_path == True:
        #     BV.add_piezometry()
        # if subbasin_path == True:
        #     BV.add_subbasin()

watershed_display.watershed_dem(BV)
watershed_display.watershed_local(dem_path, BV)

#%% REPROJECT LAYER

# All metric should be in meters (UTM or Lambert) during process
# If your projection files is WGS84 (EPSG:4326), these tools could reproject layers
# Below few examples to convert your data

# d = gdal.Open(dem_path)
# proj = osr.SpatialReference(wkt=d.GetProjection())
# crs = int(proj.GetAttrValue('AUTHORITY',1))
# d = None
crs = None

if crs == 4326:

    # Reproject raw DEM in WGS84 to specific UTM
    utm_crs = toolbox.reproject_tif(dem_path,
                                    data_path + 'dem/' + "DEM_test_75m_WGS84" + '.tif',
                                    data_path + 'dem/' + "DEM_test_75m_UTM" + '.tif')
    
    # Reproject shapefile layer to specific UTM
    toolbox.reproject_shp(data_path + 'hydrology/' + types_obs[0] + '.shp',
                          data_path + 'hydrology/' + types_obs[0] + '_utm' + '.shp',
                          utm_crs)
    
    # Convert longitude and latitude WGS84 to specific UTM
    utm_crs, x_utm, y_utm = toolbox.reproject_coord(-4.53924, 48.62315)

#%% SET MODEL PARAMETERS

# Choice temporal of the simulation
sim_state = 'steady' # 'steady' or 'transient'
period = [2017, 2019] # rehcarge period
time_step = 'M' # or 'D'
actual_date = True # False if date is conceptual
start = str(period[0])+'-01-01' # necessary to specify the first time_step date

model_name = sim_state # just a string

# Strcture of the model
lay_number = 1 # vertical discrtization
bottom = None # aquifer flat or not
thick_exp = 1 # exponential decay of K with nlay
cond_decay = 0 # exponential decay of K with depth

# Hydraulic properties
K = 1e-5 * 3600 * 24 # m/second to m/day
E = 100 # m
P = 0.01 # -

# Active of not modules
first_only = False # if True generate results only for the first tim_step
box = False # if True generate a rectangular model
sink_fill = False # permit to fill sinks
modpath_sim = True # run modpath particle tracking if True
verbose = True # add print of MODFLOW in console

# Update properties
BV.hydrodynamic.update_hyd_cond(K)
BV.hydrodynamic.update_thickness(E)
BV.hydrodynamic.update_porosity(P)

# Update actural recharge
if watershed_name != 'Conceptual':
    BV.forcing.update_recharge_surfex(clim_mod = 'REA', clim_sce='historic',
                                      first_year = period[0], last_year = period[1], 
                                      time_step = time_step, sim_state=sim_state)
    if time_step == 'M':
        R = BV.forcing.recharge / 30 # m/month to m/day
        BV.forcing.update_recharge(values = R, sim_state = sim_state)

KR=100

# Upadate conceptual recharge
conceptual_serie = np.random.sample(24)/10
if watershed_name == 'Conceptual':
    R = (pd.Series(0.015) / 30).mean() # m/month to m/day
    BV.forcing.update_recharge(R, sim_state=sim_state)
    BV.hydrodynamic.update_hyd_cond(KR*R)
    actual_date = False

# Check recharge
if sim_state=='transient':
    fig, ax = plt.subplots(1,1, figsize=(8,2), dpi=300)
    ax.plot(R*1000, c='k', lw=2) # m/months to mm/months

#%% LAUNCH MODELING

# Run model
BV.run_modflow(ident=model_name,
                modpath_sim=modpath_sim,
                first_only=first_only,
                sink_fill=sink_fill,
                box=box,
                lay_number=lay_number,
                bottom=bottom,
                thick_exp=thick_exp,
                cond_decay=cond_decay,
                verbose=verbose)

# Extract results
BV.results_modflow(ident=model_name,
                   actual_date=actual_date,
                   start=start,
                   time_step=time_step)

# x = imageio.imread('D:/Users/abherve/TEST/Conceptual/results_stable/geographic/watershed_dem.tif')
# plt.imshow(x)

#%% 3D VISUALIZATION

from tools import toolbox, vtk
from groundwater_flow import visualization, modflow_display

# 3D parameters
list_view = ['pathlines','drain_flow'] # object to represent in 3D
interactive = True
z_scale = 2
view = 'south-west'
lines = 200

vtk.VTK(BV, model_name)
visu = visualization.Visualization(BV, model_name)
visu.visual3D(interactive=interactive, object_list=list_view, z_scale=z_scale, view=view, lines=lines, cloc=(0.7,0.1))

#%% 2D MAP VIEW

from groundwater_flow import visualization, modflow_display

freq_interv = 12 # number of tim_step to take account in intermittency check
save_gif = True # save a gif after plots

# if sim_state=='transient':
modflow_display.SurfaceOutputs(R, simulations_folder, stable_folder, model_name, 
                               types_obs, freq_interv=freq_interv, save_gif=save_gif,
                               outflow=True, intermittency=False, sim_state=sim_state)

#%% 2D CROSS-SECTION

interactive = True

dem_data = BV.geographic.dem_data # dem data
wt_data = imageio.imread(simulations_folder+model_name+'/_watershed/_tifs/'+'watertable_elevation_t(000).tif') # watertable data
if watershed_name == 'Conceptual':
    river_data = None
else:
    river_data = imageio.imread(stable_folder+'/hydrology/'+'sections.tif') # river data

modflow_display.interactive_cross_section(dem_data, wt_data, river_data, interactive=interactive)

#%% CALIBRATION

test_calib = True

# Example of calibration from stream network
if test_calib==True:
    BV.forcing.update_recharge_surfex(clim_mod = 'REA', clim_sce='historic', first_year = 2015, last_year=2019, time_step = 'D', sim_state='steady')#
    BV.hydrodynamic.update_thickness(30)
    BV.hydrodynamic.update_porosity(0.1)
    BV.hydrodynamic.update_hyd_cond(4.26)
    params_file = data_path + 'calib/calib_params.csv'
    calib = calib_root.Calibration(params_file, BV, observations = ['streams'])
    calib.exploration(resolution=50)

#%% NOTES

# library = pd.read_csv(library_path, sep=';', header=0, engine='python') # explore catchment studied
# mysite = library[library['watershed_name'] == watershed_name] # specific row

#%% PLOT 2D

import matplotlib.pyplot as plt
from mpl_toolkits.axes_grid1 import make_axes_locatable
from matplotlib.colors import LightSource
from matplotlib.colors import LogNorm

lead_numb = '000'
outflow = imageio.imread('D:/Users/abherve/TEST/Conceptual/results_simulations/steady/_watershed/_tifs/outflow_drain_t(000).tif')
demData = BV.geographic.dem_data
res = 100

msk_outflow = (outflow<0)
outflow = np.ma.masked_array(outflow, mask=msk_outflow)
outflow = ( np.ma.masked_where(outflow==0, outflow) / (res**2) )
outflow = outflow *1000 *365 # mm/year
outflow = np.log10(outflow)

ls = LightSource(azdeg=45, altdeg=45)
cmap = plt.cm.Greys
rgb = ls.shade(demData, cmap=cmap, blend_mode='soft', vert_exag=2, dx=res, dy=res)

fig, ax = plt.subplots(1, 1, figsize=(6,6), dpi=300)
ax.get_xaxis().set_visible(False)
ax.get_yaxis().set_visible(False)
im = ax.imshow(rgb, alpha=0.8, cmap=cmap)
cf=ax.imshow(outflow, cmap='jet_r', alpha=1, vmin=outflow.min(), vmax=outflow.max())
# cf=ax.imshow(outflow, cmap='jet_r', alpha=1, norm = LogNorm(vmin=outflow.min(), vmax=outflow.max()))

divider = make_axes_locatable(ax)
cax = divider.append_axes("right", size="1%", pad=0.05)
fig.add_axes(cax)
cbar = fig.colorbar(im, cax=cax, orientation="vertical")
val = np.ma.masked_where(demData < 0, demData)
minVal =  int(round(np.min(val[np.nonzero(val)],0)))
maxVal =  int(round(np.max(val[np.nonzero(val)],0)))
meanVal = int(round(minVal+((maxVal-minVal)/2),0))
cbar.set_ticks([minVal, meanVal, maxVal])
cbar.set_ticklabels([minVal, meanVal, maxVal])
cbar.mappable.set_clim(minVal, maxVal)
cbar.ax.tick_params(labelsize=10)

cax = divider.new_vertical(size="2%", pad=0.05, pack_start=True)
fig.add_axes(cax)
cbar = fig.colorbar(cf, cax=cax, orientation="horizontal")
ticks = np.linspace(0, outflow.max(), 5)
cbar.set_ticks(ticks)
cbar.set_ticklabels(ticks.round(1))
cbar.set_label('Seepage rates [Log(Q) mm/year]')

plt.tight_layout()
name_fig = 'map_discharge_' + str(lead_numb) + '.png'
plt.tight_layout()

# plt.savefig(self.pngdir + name_fig)

#%% 2D VISUAL

from tools import vtk
from groundwater_flow import visualization
#☻vtk.VTK(BV, 'modflow')
visu = visualization.Visualization(BV, 'steady')
visu.visual2D(object_list = ['map','grid', 'watertable', 'watertable_depth','drain_flow',
                             'surface_flow','pathlines', 'residence_times'],
              color_scale = [(None,None),(None,None),(0,35),(0,10),
                             (None,None),(None,None),(None,None),(None,None)], 
              lines=300)

