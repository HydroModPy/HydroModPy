# -*- coding: utf-8 -*-
"""

Created on 2023.

@author: Alexandre Gauvain, Ronan Abhervé, Jean-Raynald de Dreuzy

"""

#%% ---- LIBRAIRIES

#%% PYTHON

# Libraries installed by default
import sys
import os
import warnings
warnings.filterwarnings("ignore", message=".*An exception was ignored while fetching the attribute.*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*`np.object` is a deprecated alias for the builtin `object`.*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*is deprecated. Use tobytes().*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*is deprecated since Matplotlib 3.*", category=DeprecationWarning)
warnings.filterwarnings("ignore")

# Libraries need to be installed if not
import numpy as np
import pandas as pd

# Libraries added from 'conda install' procedure
import matplotlib as mpl        # install automatically by geopandas
import matplotlib.pyplot as plt
from mpl_toolkits.axes_grid1 import make_axes_locatable
from IPython import get_ipython
get_ipython().run_line_magic('matplotlib', 'inline')

# # Libraries added from 'pip install' procedure
import imageio
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False

#%% ROOT

from os.path import dirname, abspath
root_dir = dirname(dirname(dirname(abspath(__file__))))
sys.path.append(root_dir)

cwd = os.getcwd()
if not cwd == root_dir:
    os.chdir(root_dir)
    # print("Root path directory is: {0}".format(cwd))

#%% HYDROMODPY

import src
import importlib
importlib.reload(src)

# Import HydroModPy modules
from src import watershed_root
from src.display import visualization_watershed, visualization_results, export_vtuvtk
from src.tools import toolbox, folder_root

fontprop = toolbox.plot_params(8,15,18,20) # small, medium, interm, large

#%% ---- PATHS

#%% PERSONAL

example_path = os.path.join(root_dir, 
                            "examples",
                            "01_basic features and overview of possibilities")
data_path = os.path.join(example_path, "data")
out_path = folder_root.update_root_folder_results()
# To change the folder path: out_path = folder_root.update_root_folder_results()
# To search folder path: out_path = folder_root.root_folder_results()

#%% ---- WATERSHED

#%% OPTIONS

# case = 'FromLIB'
# case = 'FromDEM'
case = 'FromSHP'
# case = 'FromXYV'

if case == 'FromLIB':
    dem_path = os.path.join(data_path, 'regional dem.tif')
    load = False
    watershed_name = 'FromLIB'
    from_lib = os.path.join(data_path,'watershed_library.csv')
    from_dem = None # [path, cell size]
    from_shp = None # [path, buffer size]
    from_xyv = None # [x, y, snap distance, buffer size]
    bottom_path = None # path
    save_object = True

if case == 'FromDEM':
    dem_path = os.path.join(data_path, 'conceptual dem.tif')
    load = False
    watershed_name = 'FromDEM'
    from_lib = None # os.path.join(root_dir,'watershed_library.csv')
    from_dem = [dem_path, 100] # [path, cell size]
    from_shp = None # [path, buffer size]
    from_xyv = None # [x, y, snap distance, buffer size]
    bottom_path = None # path
    save_object = True

if case == 'FromSHP':
    dem_path = os.path.join(data_path, 'regional dem.tif')
    load = False
    watershed_name = 'FromSHP'
    from_lib = None # os.path.join(root_dir,'watershed_library.csv')
    from_dem = None # [path, cell size]
    from_shp = [data_path + '/' + 'conceptual shp.shp', 10] # [path, buffer size]
    from_xyv = None # [x, y, snap distance, buffer size]
    bottom_path = None # path
    save_object = True

if case == 'FromXYV':
    dem_path = os.path.join(data_path, 'regional dem.tif')
    load = False
    watershed_name = 'FromXYV'
    from_lib = None # os.path.join(root_dir,'watershed_library.csv')
    from_dem = None # [path, cell size]
    from_shp = None # [path, buffer size]
    from_xyv = [127307.551 , 6835727.567 , 200 , 10 , 'EPSG:2154'] # [x, y, snap distance, buffer size, crs proj]
    bottom_path = None # path
    save_object = True

#%% GEOGRAPHIC

print('##### '+watershed_name.upper()+' #####')

load = True
BV = watershed_root.Watershed(dem_path=dem_path,
                              out_path=out_path,
                              load=load,
                              watershed_name=watershed_name,
                              from_lib=from_lib, # os.path.join(root_dir,'watershed_library.csv')
                              from_dem=from_dem, # [path, cell size]
                              from_shp=from_shp, # [path, buffer size]
                              from_xyv=from_xyv, # [x, y, snap distance, buffer size]
                              bottom_path=bottom_path, # path
                              save_object=save_object)

# Paths generated automatically but necessary for plots
stable_folder = os.path.join(out_path,watershed_name,"results_stable")
simulations_folder = os.path.join(out_path,watershed_name,"results_simulations")

#%% DATA

if from_dem == None:
    # Clip specific data at the catchment scale
    BV.add_geology(data_path, types_obs='GEO1M.shp', fields_obs='CODE_LEG')
    BV.add_hydrography(data_path, types_obs=['regional stream network'], fields_obs=['fid'])
    BV.add_hydrometry(data_path, 'france hydrometric stations.shp')
    # BV.add_intermittency(data_path, 'regional onde stations.shp')
    # BV.add_piezometry()

    # Extract some subbasin from data available above
    #BV.add_subbasin(data_path+'additional/', 200)

# General plot of the study site
if from_dem == None:
    visualization_watershed.watershed_local(dem_path, BV)
    visualization_watershed.watershed_geology(BV)
visualization_watershed.watershed_dem(BV)

#%% ---- RECHARGE

#%% CASES

# # Necessary to set model parameters
BV.add_climatic()

# Different cases of recharge implementation

# recharge_data = 'reanalysis'
# recharge_data = 'explore1'
# recharge_data = 'explore2'
# recharge_data = 'synthetic'
recharge_data = 'manual'
# recharge_data = 'raster'
# recharge_data = 'evapotranspiration'

if recharge_data == 'reanalysis':
    BV.climatic.update_recharge_reanalysis(path_file=os.path.join(data_path,'_climate_REANALYSIS.csv'),
                                           clim_mod='REA',
                                           clim_sce='historic',
                                           first_year=1990,
                                           last_year=2019,
                                           time_step='D',
                                           sim_state='transient')
    BV.climatic.update_runoff_reanalysis(path_file=os.path.join(data_path,'_climate_REANALYSIS.csv'),
                                         clim_mod='REA',
                                         clim_sce='historic',
                                         first_year=1990,
                                         last_year=2019,
                                         time_step='D',
                                         sim_state='transient')
    fig, ax = plt.subplots(1,1, figsize=(6,3))
    R = BV.climatic.recharge.resample('Y').sum()*1000
    r = BV.climatic.runoff.resample('Y').sum()*1000
    ax.plot(R, label='recharge_reanalysis', c='dodgerblue', lw=2)
    ax.plot(r, label='runoff_reanalysis', c='navy', lw=2)
    ax.set_xlabel('Date')
    ax.set_ylabel('[mm/year]')
    ax.legend()

if recharge_data == 'explore1':
    BV.climatic.update_recharge_explore1(path_file=os.path.join(data_path,'_climate_EXPLORE1.csv'),
                                         clim_mod='IPS1',
                                         clim_sce='RCP8.5',
                                         first_year=2020,
                                         last_year=2099,
                                         time_step='D',
                                         sim_state='transient')
    BV.climatic.update_runoff_explore1(path_file=os.path.join(data_path,'_climate_EXPLORE1.csv'),
                                         clim_mod='IPS1',
                                         clim_sce='RCP8.5',
                                         first_year=2020,
                                         last_year=2099,
                                         time_step='D',
                                         sim_state='transient')
    fig, ax = plt.subplots(1,1, figsize=(6,3))
    R = BV.climatic.recharge.resample('Y').sum()*1000
    r = BV.climatic.runoff.resample('Y').sum()*1000
    ax.plot(R, label='recharge_explore1', c='dodgerblue', lw=2)
    ax.plot(r, label='runoff_explore1', c='navy', lw=2)
    ax.set_xlabel('Date')
    ax.set_ylabel('[mm/year]')
    ax.legend()

if recharge_data == 'explore2':
    BV.climatic.update_recharge_explore2(path_file=os.path.join(data_path,'_climate_EXPLORE2.csv'),
                                         gcm_mod='CNR',
                                         rcm_mod='ALA',
                                         sce_mod='RCP8.5',
                                         first_year=2020,
                                         last_year=2099,
                                         sim_state='transient')
    BV.climatic.update_runoff_explore2(path_file=os.path.join(data_path,'_climate_EXPLORE2.csv'),
                                         gcm_mod='CNR',
                                         rcm_mod='ALA',
                                         sce_mod='RCP8.5',
                                         first_year=2020,
                                         last_year=2099,
                                         sim_state='transient')
    fig, ax = plt.subplots(1,1, figsize=(6,3))
    R = BV.climatic.recharge.resample('Y').sum()*1000
    r = BV.climatic.runoff.resample('Y').sum()*1000
    ax.plot(R, label='recharge_explore2', c='dodgerblue', lw=2)
    ax.plot(r, label='runoff_explore2', c='navy', lw=2)
    ax.set_xlabel('Date')
    ax.set_ylabel('[mm/year]')
    ax.legend()

if recharge_data == 'synthetic':
    rtot = 500 / 1000
    shape = 24
    years = 5
    start_date = "2000-01"
    freq = 'D' # None
    dis = 'normal' # 'inverse-gaussian', 'uniform', 'normal'
    # dis = 'inverse-gaussian'
    # dis = 'uniform'

    fig, ax = plt.subplots(1,1, figsize=(8,3), dpi=300)
    
    BV.climatic.update_recharge_synthetic(rtot, shape, years, start_date=start_date, freq=freq, dis=dis)
    R = BV.climatic.recharge
    r = R * 0.1
    ax.plot(R * 1000, label='recharge_synthetic', c='dodgerblue', lw=2)
    ax.plot(r * 1000, label='runoff_synthetic', c='navy', lw=2)
    ax.set_xlabel('Date')
    ax.set_ylabel('[mm/day]')
    ax.legend()
    print(R.resample('Y').sum()*1000)

if recharge_data == 'manual':
    
    time_series = pd.Series([10,20,30,40,50,60,60,50,40,30,20,10]) # mm/month
    BV.climatic.update_recharge(time_series, sim_state='transient')
    fig, ax = plt.subplots(1,1, figsize=(6,3))
    R = BV.climatic.recharge / 1000 / 30
    r = R * 0.1
    ax.plot(R, label='recharge_manual', c='dodgerblue', lw=2)
    ax.plot(r, label='runoff_manual', c='navy', lw=2)
    ax.set_xlabel('Months')
    ax.set_ylabel('[mm/month]')
    ax.legend()

if recharge_data == 'raster':
    
    dem_struct = imageio.imread(os.path.join(stable_folder,r'geographic/watershed_box_buff_dem.tif')) * 0
    dem_struct = dem_struct + 10/1000/30
    dem_struct[:,int(dem_struct.shape[1]/2):] = dem_struct[:,int(dem_struct.shape[1]/2):] + 1000/1000/30
    
    list_of_arrays = [dem_struct, dem_struct, dem_struct] # transient
    # list_of_arrays = [dem_struct] # steay
        
    dictio = {}
    
    for i in range(len(list_of_arrays)):
        dictio[i] = list_of_arrays[i]
    
    R = dictio.copy()
    r = R.copy()
    for i in range(len(R)):
        r[i] = r[i] * 0.1
    
    fig, ax = plt.subplots(1,1, figsize=(6,3))
    ax.imshow(R[0])

if recharge_data == 'evapotranspiration':
    
    time_series = pd.Series([10,20,30,-20,-100,-40,20,50,40,30,20,10]) # mm/month
    BV.climatic.update_recharge(time_series, sim_state='transient')
    fig, ax = plt.subplots(1,1, figsize=(6,3))
    R = BV.climatic.recharge / 1000 / 30
    r = R
    ax.plot(R, label='effective precipitation_manual', c='dodgerblue', lw=2)
    ax.set_xlabel('Months')
    ax.set_ylabel('[mm/month]')
    ax.legend()

#%% ---- PARAMETRIZATION

#%% DEFINE

# Frame settings
model_name = 'default'
box = True # or False
sink_fill = False # or True
# sim_state = 'transient' # 'steady' or 'transient'
sim_state = 'steady' # 'steady' or 'transient'
plot_cross = True

# Climatic settings
recharge = R.copy()
first_clim = 'mean' # or 'first or value
freq_time = 'M' # or 'D'

# Hydraulic settings
nlay = 5
lay_decay = 1. # 1 for no decay
bottom = -1 # elevation in meters, None for constant auifer thickness, or 2D matrix
thick = 50 # if bottom is None, aquifer thickness
hyd_cond = 1e-5 * 24 * 3600 # m/day
cond_decay = 0 # exponential decay : 1/20 (half decrease at 20m)
verti_cond = None # or [ [1e-5, [0, 20]], [1e-6, [20,80]] ]
cond_drain = None # or value of conductance
porosity = 10 / 100 # -
poro_decay = 0 # exponential decay : 1/20 (half decrease at 20m)

# Boundary settings
bc_left = None # or value
bc_right = None # or value
sea_level = 'None' # or value based on specific data : BV.oceanic.MSL

# Particle tracking settings
zone_partic = 'domain' # or watershed

#%% UPDATE

# Import modules
BV.add_settings()
BV.add_climatic()
BV.add_geometric() # soon
BV.add_hydraulic()

# Frame settings
BV.settings.update_model_name(model_name)
BV.settings.update_box_model(box)
BV.settings.update_sink_fill(sink_fill)
BV.settings.update_simulation_state(sim_state)
BV.settings.update_active_plot(plot_cross=plot_cross)

# Climatic settings
BV.climatic.update_recharge(recharge, sim_state=sim_state)
BV.climatic.update_first_clim(first_clim)

# Hydraulic settings
BV.hydraulic.update_nlay(nlay) # 1
BV.hydraulic.update_lay_decay(lay_decay) # 1
BV.hydraulic.update_bottom(bottom) # None
BV.hydraulic.update_thick(thick) # 30 / intervient pas si bottom != None
BV.hydraulic.update_hyd_cond(hyd_cond)
BV.hydraulic.update_porosity(porosity)
BV.hydraulic.update_cond_vertical(verti_cond)
BV.hydraulic.update_cond_drain(cond_drain)
BV.hydraulic.update_poro_decay(poro_decay)

# Boundary settings
BV.settings.update_bc_sides(bc_left, bc_right)
BV.add_oceanic(sea_level)

# Particle tracking settings
BV.settings.update_input_particules(zone_partic=zone_partic)

#%% ---- MODELING

#%% MODFLOW

model_modflow = BV.preprocessing_modflow(for_calib=False)
success_modflow = BV.processing_modflow(model_modflow, write_model=True, run_model=True)
if success_modflow == True:
    BV.postprocessing_modflow(model_modflow,
                              watertable_elevation = True,
                              watertable_depth= True, 
                              seepage_areas = True,
                              outflow_drain = True,
                              groundwater_flux = True,
                              groundwater_storage = True,
                              accumulation_flux = True,
                              persistency_index=False,
                              intermittency_monthly=False,
                              intermittency_daily=False,
                              export_all_tif = False,
                              export_netcdf = True)

#%% MODPATH

if sim_state == 'steady':
    if success_modflow == True:
        model_modpath = BV.preprocessing_modpath(model_modflow)
        success_modpath = BV.processing_modpath(model_modpath, write_model=True, run_model=True)
    if success_modpath == True:
        BV.postprocessing_modpath(model_modpath,
                                  ending_point=True,
                                  starting_point=True,
                                  pathlines_shp=True,
                                  particules_shp=True,
                                  random_id=100)

#%% TIMESERIES

if from_dem == None:
    subbasin_results = True
else:
    subbasin_results = False

if sim_state == 'steady':
    model_modpath = model_modpath
else:
    model_modpath = None

timeseries_results = BV.postprocessing_timeseries(model_modflow=model_modflow,
                                                  model_modpath=model_modpath,
                                                  actual_date=True, 
                                                  subbasin_results=subbasin_results,
                                                  freq_time=freq_time) # or None

#%% ---- PLOT

#%% CHRONICS

# fig, ax = plt.subplots(1, 1, figsize=(5,3), dpi=300)
# csv = pd.read_csv(simulations_folder+'/'+model_name+'/_postprocess/_timeseries/_simulated_timeseries.csv',
#                   sep=';')
# ax.plot(csv['outflow_drain'])

#%% 2D

# if sim_state == 'steady':
visu = visualization_results.Visualization(BV, model_name)
visu.visual2D(object_list = ['map','grid',
                             'watertable', 'watertable_depth',
                             'drain_flow','surface_flow',
                             'pathlines', 'residence_times'
                             ],
              color_scale = [(None,None),(None,None),
                             (None,None),(0,10),
                             (None,None),(None,None),
                             (0,100),(None,None),
                             ], 
              lines=250)

#%% 3D

if from_dem == None:
    export_vtuvtk.VTK(BV, model_name)
    visu = visualization_results.Visualization(BV, model_name)
    visu.visual3D(interactive=True, object_list=['grid','watertable', 'watertable_depth',
                                                  'surface_flow',
                                                  'drain_flow',
                                                  'pathlines'], view='south-west', lines=100, cloc=(0.7,0.1), z_scale=10)

#%% RAW

lead_numb = '0'
outflow = imageio.imread(os.path.join(simulations_folder,model_name,r'_postprocess/_rasters/outflow_drain_t(0).tif'))
accflow = imageio.imread(os.path.join(simulations_folder,model_name,r'_postprocess/_rasters/accumulation_flux_t(0).tif'))
demData = imageio.imread(BV.geographic.watershed_dem)
demData = np.ma.masked_array(demData, mask=demData<0)
res = BV.geographic.resolution

msk_outflow = (outflow<0)
outflow = np.ma.masked_array(outflow, mask=msk_outflow)
outflow = ( np.ma.masked_where(outflow==0, outflow) )
outflow = outflow  / (res**2)
outflow = outflow * 1000 # * 365 # mm/day or mm/year
# outflow = np.log10(outflow)

from matplotlib.colors import LightSource
ls = LightSource(azdeg=45, altdeg=45)
cmap = plt.cm.Greys
rgb = ls.shade(demData, cmap=cmap, blend_mode='soft', vert_exag=2, dx=res, dy=res)

fig, ax = plt.subplots(1, 1, figsize=(8,8), dpi=300)
ax.get_xaxis().set_visible(False)
ax.get_yaxis().set_visible(False)
im = ax.imshow(demData, alpha=0.8, cmap=cmap)
im = ax.imshow(rgb, alpha=0.8, cmap=cmap)
cf=ax.imshow(outflow, cmap='jet', alpha=1,
             # vmin=outflow.min(), vmax=1000
             )
try:
    cont = imageio.imread(BV.geographic.watershed_contour_tif)
    ax.imshow(np.ma.masked_where(cont<0, cont), cmap=mpl.colors.ListedColormap(['k']))
except:
    pass

divider = make_axes_locatable(ax)
cax = divider.append_axes("right", size="1%", pad=0.05)
fig.add_axes(cax)
cbar = fig.colorbar(im, cax=cax, orientation="vertical")

val = np.ma.masked_where(demData < 0, demData)
minVal =  int(round(np.nanmin(val[np.nonzero(val)],0)))
maxVal =  int(round(np.nanmax(val[np.nonzero(val)],0)))
meanVal = int(round(minVal+((maxVal-minVal)/2),0))
cbar.set_ticks([minVal, meanVal, maxVal])
cbar.set_ticklabels([minVal, meanVal, maxVal])
cbar.mappable.set_clim(minVal, maxVal)
cbar.ax.tick_params(labelsize=10)

cax = divider.new_vertical(size="2%", pad=0.05, pack_start=True)
fig.add_axes(cax)
cbar = fig.colorbar(cf, cax=cax, orientation="horizontal")
ticks = np.linspace(0, 20, 5)
cbar.set_ticks(ticks)
# cbar.set_ticklabels(ticks.round(1))
cbar.mappable.set_clim(0, 20)
cbar.set_label('Seepage outflow log [mm/day]')

plt.tight_layout()
name_fig = 'map_discharge_' + str(lead_numb) + '.png'
plt.tight_layout()

fig.savefig(os.path.join(simulations_folder, model_name,
                            '_postprocess', '_figures', 'RAW_'+model_name+'.png'))

#%% CROSS

dem_data = imageio.imread(os.path.join(stable_folder,'geographic','watershed_box_buff_dem.tif')) # dem data
if from_dem == None:
    stream_data = imageio.imread(os.path.join(stable_folder,'hydrography','regional stream network.tif')) # river data
else:
    stream_data = None
watertable_data = imageio.imread(os.path.join(simulations_folder,model_name,r'_postprocess/_rasters/','watertable_elevation_t(0).tif')) # watertable data
interactive = True
visu = visualization_results.Visualization(BV, model_name)
visu.interactive_cross_section(dem_data, watertable_data, stream_data, interactive)

#%% ---- NOTES

os.chdir(root_dir)
