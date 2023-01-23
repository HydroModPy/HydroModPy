# -*- coding: utf-8 -*-
"""
Created on Mon Dec 20 08:05:41 2021

@author: Ronan Abhervé
"""

# %% GENERAL LIBRARIES

# General
from matplotlib.colors import LogNorm
from matplotlib.colors import LightSource
from mpl_toolkits.axes_grid1 import make_axes_locatable
from groundwater_flow import visualization
from tools import vtk
from calibration import calib_root, calib_analysis
from groundwater_flow import visualization, modflow_display
from tools import toolbox, vtk
from watershed import watershed_root, watershed_display
import warnings
import whitebox
import imageio
import os
import glob
import matplotlib.pyplot as plt
from osgeo import gdal, osr
import pandas as pd
import numpy as np
import sys
from os.path import dirname, abspath
DIR = dirname(dirname(dirname(abspath(__file__))))
sys.path.append(DIR)

# Gis
wbt = whitebox.WhiteboxTools()
wbt.verbose = False

# Warnings
warnings.filterwarnings(
    "ignore", message=".*An exception was ignored while fetching the attribute.*", category=DeprecationWarning)
warnings.filterwarnings(
    "ignore", message=".*`np.object` is a deprecated alias for the builtin `object`.*", category=DeprecationWarning)
warnings.filterwarnings(
    "ignore", message=".*is deprecated. Use tobytes().*", category=DeprecationWarning)
warnings.filterwarnings("ignore")
# warnings.warn("You won't see this warning")

# Modules

# Layout
fontprop = toolbox.plot_params(8, 15, 18, 20)  # small, medium, interm, large

# %% PERSONAL PATHS

############################################
# user = 'Martin'
user = 'Ronan'
############################################

if user == 'Ronan':
    # Path to the git repositoty home page
    git_path = "D:/Users/abherve/GITHUB/HydroModPy/CORE_COMM/"
    # Path to the data folder
    data_path = "D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/HYDRODATAPY/HydroDataPy/UNINE/StCharles/"
    # Path where the results will be stored
    out_path = "D:/Users/abherve/UNINE/"

# %% DATABASE ACCESS FOR THIS TESTS

# As an example, all data necessary for this test are stored in this OneDrive folder named 'TEST'

# Hyperlink : 'https://1drv.ms/f/s!ArPhnd6PZcHmjQg8qW15u2DWBR37'
# Password : 'osur-data-hydromodpy-2022'

# %% FOLDER DATA PATHS

# Specify path or boolean to active/enable modules

dems_path = data_path  # reginal DEM or conceptual DEM
shp_path = data_path  # if you want run a model from a shapefile
modflow_path = data_path + 'modflow/'  # add bin/ folder with necessary .exe

# add surfex models in .h5 format (France scale, else, specify None)
surfex_path = data_path + 'surfex/'
geology_path = data_path + 'geology/'  # add geologic layers
oceanic_path = data_path + 'oceanic/'  # add specific sea level files
hydrology_path = data_path  # add hydrographic shapefiles
# add hydrometry data for automatic download
hydrometry_path = data_path + 'hydrometry/'
# add intermittency data for automatic download
intermittency_path = data_path + 'intermittency/'
piezometry_path = True  # add piezometry data for automatic download
subbasin_path = True  # generate subbasins from stations or manual points

# each row is a study site with outlet coordinates
library_path = data_path + 'watershed_library.csv'

# %% TEST CHOICE

# We propose 4 tests :
# 1 - From a outlet coordinates : 'Outlet'
# 2 - From a shpaefile : 'Shapefile'
# 3 - From an actual DEM : 'Dem'
# 4 - From a conceptual DEM : 'Conceptual'

# search the name in watershed_library or just label your result folder
watershed_name = 'StCharles'
print('##### '+watershed_name.upper()+' #####')

dem_name = "mnt_fusionne_5m.tif"  # name of dem
from_shp = None  # specify a path if process start from a given shapefile
from_dem = False  # True or False if the process start from a given DEM of xyz file
cell_size = None  # specify new resolution from a given DEM or None

# list of shapefile name layers for clip hydrology
types_obs = ['Réseau_Hydrographique']
# list of shapefile name columns to translate as a tif
fields_obs = ['fid']

# Depending on the choices
dem_path = dems_path + dem_name
# new_dem_path = dems_path + "SRTM_clipped_large_reprojected.tif"
new_dem_path = dems_path + "mnt_fusionne_5m_resampled.tif"

wbt.resample(
    dem_path, 
    new_dem_path, 
    cell_size=100, 
    base=None, 
    method="cc")

# # Assign projection
fn = new_dem_path
#define a projection
spatref = osr.SpatialReference()
spatref.ImportFromEPSG(32198)
crs_wkt = spatref.ExportToWkt()
# open in edit mode, omit the 1 if you want read only mode
ds = gdal.Open(fn, 1) 
# set the projection
ds.SetProjection(crs_wkt)
#close the dataset
ds.FlushCache()
ds = None

stable_folder = out_path+'/'+watershed_name + \
    '/'+'results_stable/'  # necessary for plots
simulations_folder = out_path+'/'+watershed_name + \
    '/'+'results_simulations/'  # necessary for plots

# %% GENERATING WATERSHED

load = False

BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=new_dem_path,
                              out_path=out_path,
                              modflow_path=modflow_path,
                              library_path=library_path,
                              load=load,
                              from_shp=from_shp,
                              from_dem=from_dem,
                              cell_size=cell_size)

BV.add_oceanic(oceanic_path)
BV.add_hydrology(hydrology_path, types_obs=types_obs, fields_obs=fields_obs)
        
# BV.add_surfex(surfex_path)
# BV.add_geology(geology_path)
# BV.add_hydrometry(hydrometry_path)
# BV.add_intermittency(intermittency_path)
# BV.add_piezometry()
# BV.add_subbasin()

BV.add_hydrodynamic()
BV.add_forcing()

watershed_display.watershed_dem(BV)
watershed_display.watershed_local(dem_path, BV)

# %% SET MODEL PARAMETERS

# Choice temporal of the simulation
sim_state = 'steady'  # 'steady' or 'transient'
time_step = 'M'  # or 'D'
actual_date = True  # False if date is conceptual
# necessary to specify the first time_step date
model_name = sim_state  # just a string

# Recharge
R = 0.5 / 365
BV.forcing.update_recharge(R, sim_state=sim_state)

# Structure of the model
lay_number = 1  # vertical discrtization
bottom = None  # aquifer flat or not
thick_exp = 1  # exponential decay of K with nlay
cond_decay = 0  # exponential decay of K with depth

# Hydraulic properties
K = 5e-5 * 3600 * 24  # m/second to m/day
E = 100  # m
P = 0.01  # -

print(K/R)

# Active of not modules
first_only = False  # if True generate results only for the first tim_step
box = False  # if True generate a rectangular model
sink_fill = False  # permit to fill sinks
modpath_sim = False  # run modpath particle tracking if True
verbose = True  # add print of MODFLOW in console

# Update properties
BV.hydrodynamic.update_hyd_cond(K)
BV.hydrodynamic.update_thickness(E)
BV.hydrodynamic.update_porosity(P)

# %% LAUNCH MODELING

# Run model
success, flow_model = BV.run_modflow(ident=model_name,
                                     modpath_sim=modpath_sim,
                                     first_only=first_only,
                                     sink_fill=sink_fill,
                                     box=box,
                                     lay_number=lay_number,
                                     bottom=bottom,
                                     thick_exp=thick_exp,
                                     cond_decay=cond_decay,
                                     verbose=verbose)

BV.matrix_modflow(success, flow_model,
                  first_only=False,
                  watertable_elevation=True,
                  watertable_depth=True,
                  seepage_areas=True,
                  outflow_drain=True,
                  groundwater_flux=False,
                  specific_discharge=False,
                  accumulation_flux=True,
                  perenn_intermit_shp=True,
                  verbose=True,
                  export_tif=True)

# Extract results
BV.results_modflow(ident=model_name,
                   actual_date=actual_date,
                   time_step=time_step)

fig, ax = plt.subplots(1,1)
res_data = imageio.imread('D:/Users/abherve/SAID/Outlet/results_simulations/steady/_watershed/_tifs/seepage_areas_t(0).tif')
# plt.imshow(res_data)
ax.imshow(np.ma.masked_array(res_data, mask=res_data <= 0))

#%% DICHOTOMY

BV.forcing.update_recharge(0.8 / 365, sim_state=sim_state)

params_df = pd.DataFrame(columns=['params',
                                  'init_values',
                                  'lower_bounds',
                                  'higher_bounds',
                                  'units','scale'])
params_df.loc[0] = ['k1',
                    None,
                    1e-7 * 3600 * 24,
                    1e-4 * 3600 * 24,
                    'm/j',
                    'lin']

params_file = "calib_dicot_hom_1v_k1_stead" # dichotomy on streams, homogeneous, for k1

params_df.to_csv(BV.calibration_folder+'/'+params_file+'.csv', sep=';', index=None)

# Pre-processing
data_calib = ['streams']
calib = calib_root.Calibration(params_file, BV, observations = data_calib)

# Processing
calib.dichotomy(gap=1)

# Post-processing
label_calib = data_calib[0] + '_calibration'
list_path = sorted(glob.glob(os.path.join(BV.calibration_folder, params_file, label_calib, '*.calib')), key=os.path.getmtime)
name_file = list_path[-1].split('\\')[-1] # the last calibration
calib_file = os.path.join(BV.calibration_folder, params_file, label_calib, name_file)
analy = calib_analysis.CalibAnalysis(calib_file)
analy.display_objective_function(save=None)

best_K = analy.params_xyz[-1]

# %% 2D INTERMITTENCY

modflow_display.SurfaceOutputs(flow_model.climatic,
                               simulations_folder,
                               stable_folder,
                               model_name,
                               types_obs,
                               save_gif=True,
                               first_only=True,
                               outflow=True,
                               accflux=True,
                               intermittency=True,
                               chronics=False,
                               sim_state='transient')

# %% 3D VISUALIZATION


# 3D parameters
list_view = ['watertable_depth', 'surface_flow']  # object to represent in 3D
interactive = True
z_scale = 10
view = 'south-west'
lines = 200

vtk.VTK(BV, model_name)
visu = visualization.Visualization(BV, model_name)
visu.visual3D(interactive=interactive, object_list=list_view, z_scale=z_scale, view=view,
              lines=lines, cloc=(0.7, 0.1))

# %% 2D VISUALIZATION

# ☻vtk.VTK(BV, 'modflow')
visu = visualization.Visualization(BV, 'steady')
visu.visual2D(object_list=['map', 'grid', 'watertable', 'watertable_depth', 'drain_flow',
                           'surface_flow',
                           #'pathlines', 'residence_times'
                           ],
              color_scale=[(None, None), (None, None), (None, None), (0, 10),
                           (None, None), (None, None),
                           # (None,None),(None,None)
                           ],
              lines=300)

# %% 2D CROSS-SECTION

interactive = False

dem_data = BV.geographic.dem_data  # dem data
wt_data = imageio.imread(simulations_folder+model_name+'/_watershed/_tifs/' +
                         'watertable_elevation_t(0).tif')  # watertable data
if watershed_name == 'Conceptual':
    river_data = None
else:
    river_data = imageio.imread(
        stable_folder+'/hydrology/'+'sections.tif')  # river data

modflow_display.interactive_cross_section(
    dem_data, wt_data, river_data, interactive=interactive)

# %% PLOT RAW OUTFLOW


lead_numb = '0'
outflow = imageio.imread(
    simulations_folder+'steady/_watershed/_tifs/accumulation_flux_t(0).tif')
demData = imageio.imread(BV.geographic.watershed_dem)
demData = np.ma.masked_array(demData, mask=demData < 0)
res = 100

msk_outflow = (outflow < 0)
outflow = np.ma.masked_array(outflow, mask=msk_outflow)
outflow = (np.ma.masked_where(outflow == 0, outflow) / (res**2))
outflow = outflow * 1000 * 365  # mm/year
outflow = np.log10(outflow)

ls = LightSource(azdeg=45, altdeg=45)
cmap = plt.cm.Greys
rgb = ls.shade(demData, cmap=cmap, blend_mode='soft',
               vert_exag=2, dx=res, dy=res)

fig, ax = plt.subplots(1, 1, figsize=(6, 6), dpi=300)
ax.get_xaxis().set_visible(False)
ax.get_yaxis().set_visible(False)
im = ax.imshow(demData, alpha=0.8, cmap=cmap)
# im = ax.imshow(rgb, alpha=0.8, cmap=cmap)
cf = ax.imshow(outflow, cmap='plasma_r', alpha=1,
               vmin=outflow.min(), vmax=outflow.max())
# cf=ax.imshow(outflow, cmap='jet_r', alpha=1, norm = LogNorm(vmin=outflow.min(), vmax=outflow.max()))

divider = make_axes_locatable(ax)
cax = divider.append_axes("right", size="1%", pad=0.05)
fig.add_axes(cax)
cbar = fig.colorbar(im, cax=cax, orientation="vertical")
val = np.ma.masked_where(demData < 0, demData)
minVal = int(round(np.nanmin(val[np.nonzero(val)], 0)))
maxVal = int(round(np.nanmax(val[np.nonzero(val)], 0)))
meanVal = int(round(minVal+((maxVal-minVal)/2), 0))
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

# %% EXPLORATION CALIBRATION TEST

test_exploration = True
test_dichotomy = False

# Example of calibration from stream network

BV.forcing.update_recharge_surfex(clim_mod='REA', clim_sce='historic',
                                  first_year=2015, last_year=2019, time_step='D', sim_state='steady')

BV.hydrodynamic.update_thickness(30)
BV.hydrodynamic.update_porosity(0.1)

# Necessary to put .csv parameter files of "params_file" in your "calibration_folder"

if test_exploration == True:

    params_file = 'calib_explo_hom_1v_k1'
    calib = calib_root.Calibration(params_file, BV, observations=['streams'])
    calib.exploration(resolution=10)
    typ_calib = 'streams_calibration'
    list_path = sorted(glob.glob(os.path.join(
        BV.calibration_folder, params_file, typ_calib, '*.calib')), key=os.path.getmtime)
    name_file = list_path[-1].split('\\')[-1]
    calib_file = os.path.join(BV.calibration_folder,
                              params_file, typ_calib, name_file)
    test = calib_analysis.CalibAnalysis(calib_file)
    test.display_objective_function(save=None)

if test_dichotomy == True:

    params_file = 'calib_dicot_hom_1v_k1'
    calib = calib_root.Calibration(params_file, BV, observations=['streams'])
    calib.dichotomy(gap=1)
    typ_calib = 'streams_calibration'
    list_path = sorted(glob.glob(os.path.join(
        BV.calibration_folder, params_file, typ_calib, '*.calib')), key=os.path.getmtime)
    name_file = list_path[-1].split('\\')[-1]
    calib_file = os.path.join(BV.calibration_folder,
                              params_file, typ_calib, name_file)
    test = calib_analysis.CalibAnalysis(calib_file)
    test.display_objective_function(save=None)

# %% NOTES
