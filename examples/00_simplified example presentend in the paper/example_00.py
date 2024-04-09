# -*- coding: utf-8 -*-
"""

Created on 2023.

@author: Alexandre Gauvain, Ronan Abhervé, Jean-Raynald de Dreuzy

"""

#%% ---- LIBRAIRIES

# PYTHON PACKAGES

import sys
import os
import warnings
warnings.filterwarnings("ignore", message=".*An exception was ignored while fetching the attribute.*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*`np.object` is a deprecated alias for the builtin `object`.*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*is deprecated. Use tobytes().*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*is deprecated since Matplotlib 3.*", category=DeprecationWarning)
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd
import flopy
import matplotlib as mpl
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from IPython import get_ipython
get_ipython().run_line_magic('matplotlib', 'inline')
import imageio
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False

# ROOT DIRECTORY

from os.path import dirname, abspath
root_dir = dirname(dirname(dirname(abspath(__file__))))
# root_dir = dirname(dirname(os.getcwd())) 
sys.path.append(root_dir)
cwd = os.getcwd()
if not cwd == root_dir:
    os.chdir(root_dir)
print("Root path directory is: {0}".format(root_dir.upper()))

# HYDROMODPY MODEULES

import src
import importlib
importlib.reload(src)
from src import watershed_root
from src.watershed import climatic, geographic, geology, geometric, hydraulic, hydrography, hydrometry, intermittency, oceanic, piezometry, subbasin
from src.modeling import downslope, modflow, modpath, timeseries
from src.display import visualization_watershed, visualization_results, export_vtuvtk
from src.tools import toolbox, folder_root
fontprop = toolbox.plot_params(8,15,18,20) # small, medium, interm, large

#%% ---- PERSONAL PATHS

example_path = os.path.join(root_dir, "examples/00_simplified example presentend in the paper")
data_path = os.path.join(example_path, "data")
out_path = folder_root.update_root_folder_results()
# To change the folder path: out_path = folder_root.update_root_folder_results()
# To search folder path: out_path = folder_root.root_folder_results()

#%% ---- EXTRACT CATCHMENT

# Name of the study site
watershed_name = 'Example'
print('##### '+watershed_name.upper()+' #####')

# Regional DEM
dem_path = os.path.join(data_path, 'regional dem.tif')

# Outlet coordinates of the catchment
from_xyv = [327816.965, 6777886.670, 150, 10 , 'EPSG:2154']

# Extract the catchment from a regional DEM
BV = watershed_root.Watershed(dem_path=dem_path,
                              out_path=out_path,
                              load=True,
                              watershed_name=watershed_name,
                              from_lib=None, # os.path.join(root_dir,'watershed_library.csv')
                              from_dem=None, # [path, cell size]
                              from_shp=None, # [path, buffer size]
                              from_xyv=from_xyv, # [x, y, snap distance, buffer size]
                              bottom_path=None, # path 
                              save_object=True)

# Paths necessary for the script
stable_folder = os.path.join(out_path, watershed_name, 'results_stable')
simulations_folder = os.path.join(out_path, watershed_name, 'results_simulations')

#%% ---- ADD DATA

# Clip specific data at the catchment scale
BV.add_geology(data_path, types_obs='GEO1M.shp', fields_obs='CODE_LEG')
BV.add_hydrography(data_path, types_obs=['regional stream network'])
BV.add_hydrometry(data_path, 'france hydrometric stations.shp')
BV.add_intermittency(data_path, 'regional onde stations.shp')

# Extract a subbasin inside the study site
BV.add_subbasin(os.path.join(data_path, 'additional'), 150)

#%% ---- WATERSHED MAP

# General plot of the study site
visualization_watershed.watershed_local(dem_path, BV)
visualization_watershed.watershed_geology(BV)
visualization_watershed.watershed_dem(BV)

# STREAMFLOW PLOT

Qobs = pd.read_csv(data_path+'/'+'hydrometry catchment Canut.csv', sep=';', index_col=0, parse_dates=True)
Qobs = Qobs.squeeze()
Qobs = Qobs.rename('Q')
def select_period(df, first, last):
    df = df[(df.index.year>=first) & (df.index.year<=last)]
    return df
area = BV.geographic.area
first = 1990
last = 2019
Qobs = select_period(Qobs, first, last)
Qobs = (Qobs / (area*1000000)) * (3600 * 24) * 1000 # m3/s to mm/j
data_index = Qobs.copy()

mean_mensual = data_index.resample('M').mean() # mensual mean
mean_annual = data_index.resample('Y').mean() # annual mean
Mean = round(data_index.mean(),2)
Mean = data_index.mean()
Min = data_index.resample('Y').min()
Q10 = data_index.resample('Y').quantile(0.10)
Q25 = data_index.resample('Y').quantile(0.25)
Q50 = data_index.resample('Y').quantile(0.50)
Q75 = data_index.resample('Y').quantile(0.75)
Q90 = data_index.resample('Y').quantile(0.90)
Max = data_index.resample('Y').max()
mean_interan_days = data_index.groupby([data_index.index.month,data_index.index.day], as_index=True).mean().to_frame()
std_interan_days = data_index.groupby([data_index.index.month,data_index.index.day], as_index=True).std()
q10_interan_days = data_index.groupby([data_index.index.month,data_index.index.day], as_index=True).quantile(0.10)
q90_interan_days = data_index.groupby([data_index.index.month,data_index.index.day], as_index=True).quantile(0.90)
q50_interan_days = data_index.groupby([data_index.index.month,data_index.index.day], as_index=True).quantile(0.50)
mean_interan_days['std'] = std_interan_days
mean_interan_days['q10'] = q10_interan_days
mean_interan_days['q90'] = q90_interan_days
mean_interan_days['q50'] = q50_interan_days
mean_interan_days.index.names = ['months','days']
mean_interan_days = mean_interan_days.reset_index()
mean_interan_days = mean_interan_days.sort_values(['months','days'])
mean_interan_days['counts'] = np.array(range(1,len(mean_interan_days)+1))

fig, ax = plt.subplots(figsize=(6,4))
ax.plot(mean_interan_days.counts, mean_interan_days.q50, lw=2, color='darkred', label='Median')
yerrmax = mean_interan_days.q90
yerrmin = mean_interan_days.q10
ax.fill_between(mean_interan_days.counts, yerrmin, yerrmax, color='cyan', edgecolor='grey', lw=0.5, alpha=0.5, label='10-90th')
ax.set_yscale('log')
ax.set_xlim(0,366)
ax.set_ylim(0.01,10)
ax.tick_params(axis='both', which='major', pad=10)
x1 = np.linspace(0,366,13)
squad = ['J','F','M','A','M','J','J','A','S','O','N','D','J']
ax.set_xticks(x1)
ax.set_xticklabels(squad, minor=False, rotation='horizontal')
ax.set_xlabel('Months', labelpad=+10)
ax.set_ylabel('Q / A [mm/d]',labelpad=+10)
ax.set_title(watershed_name + ' [' + str(first) + ' to ' + str(last) + ']')
ax.grid(alpha=0.25, zorder=0)
one = 2017
dates = np.array([one],dtype=np.int64)
colors = ['blue']
for z in np.array(range(len(dates))):
    onlyone = data_index[(data_index.index.year==dates[z])].to_frame()
    onlyone = onlyone.groupby([onlyone.index.month, onlyone.index.day], as_index=True).mean()
    onlyone['counts'] = np.array(range(1,len(onlyone)+1))
    ax.plot(onlyone.counts, onlyone['Q'], color=colors[z], lw=1, label = str(dates[z]))
ax.legend(loc='lower left')
plt.tight_layout()

#%% ---- MODEL PARAMETRIZATION

# Name of the model/simulation
model_name = 'test_0'

# Import modules
BV.add_settings()
BV.add_climatic()
BV.add_hydraulic()

# Frame settings
BV.settings.update_model_name(model_name) # Name of the model/simulation
BV.settings.update_box_model(True)
BV.settings.update_sink_fill(False)
BV.settings.update_simulation_state('steady') # Transient
BV.settings.update_active_plot(plot_cross=False)

# Climatic settings
BV.climatic.update_recharge(350 / 1000 / 365, sim_state=BV.settings.sim_state)
BV.climatic.update_first_clim('mean') # or 'first or value

# Hydraulic settings
BV.hydraulic.update_nlay(5)
BV.hydraulic.update_lay_decay(1.5) # 1 if not activated
BV.hydraulic.update_bottom(None) # Set a value to set a flat bottom
BV.hydraulic.update_thick(50) # Not consider if bottom != of None
BV.hydraulic.update_hyd_cond(2e-5 * 24 * 3600) # m/d
BV.hydraulic.update_porosity(1/100) # -
BV.hydraulic.update_cond_decay(1/10) # Exponential decay with depth : 1/10 (about half decrease at 10m)
BV.hydraulic.update_cond_vertical(None) # or [ [1e-5, [0, 20]], [1e-6, [20,80]] ]
BV.hydraulic.update_cond_drain(None)
BV.hydraulic.update_poro_decay(0)

# Boundary settings
BV.settings.update_bc_sides(None, None)
BV.add_oceanic('None')

# Particle tracking settings
BV.settings.update_input_particules(zone_partic='watershed') # or 'domain'

#%% ---- GROUNDWATER FLOW MODEL RUN

# Pre-processing
model_modflow = BV.preprocessing_modflow(for_calib=False)

# Processing
success_modflow = BV.processing_modflow(model_modflow, write_model=True, run_model=True)

# Post-processing
if success_modflow == True:
    BV.postprocessing_modflow(model_modflow,
                              watertable_elevation=True,
                              watertable_depth=True, 
                              seepage_areas=True,
                              outflow_drain=True,
                              groundwater_flux=True,
                              groundwater_storage=True,
                              accumulation_flux=True,
                              persistency_index=False, # only in transient
                              intermittency_monthly=False, # only in transient
                              intermittency_weekly=False, # only in transient
                              intermittency_daily=False, # only in transient
                              export_all_tif=False,
                              export_netcdf=True)

#%% ---- PARTICLE TRACKING RUN

# Pre-processing
if success_modflow == True:
    model_modpath = BV.preprocessing_modpath(model_modflow)

# Processing
    success_modpath = BV.processing_modpath(model_modpath, write_model=True, run_model=True)

# Post-processing
if success_modpath == True:
    BV.postprocessing_modpath(model_modpath,
                              ending_point=True,
                              starting_point=True,
                              pathlines_shp=True,
                              particules_shp=False,
                              random_id=None) # None

#%% ---- GENERATE TIMESERIES

timeseries_results = BV.postprocessing_timeseries(model_modflow=model_modflow,
                                                  model_modpath=model_modpath,
                                                  actual_date=True, 
                                                  subbasin_results=True,
                                                  freq_time='D') # or 'M' or None

#%% ---- PLOT RESULTS

#%% RECHARGE INPUT

BV.add_climatic()
BV.climatic.update_recharge_reanalysis(path_file=os.path.join(data_path,'_climate_REANALYSIS.csv'),
                                       clim_mod='REA',
                                       clim_sce='historic',
                                       first_year=1990,
                                       last_year=2019,
                                       time_step='D',
                                       sim_state='transient')

fig, ax = plt.subplots(1,1, figsize=(7,3), dpi=300)
ax.patch.set_visible(False)
axb = ax.twinx()
R = BV.climatic.recharge
ax.plot(R.index, R,  color='blue', lw=1, clip_on=True)
axb.bar(R.resample('Y').sum().index, R.resample('Y').sum(),  color='red', lw=0, width=100, alpha=1, clip_on=True)
axb.set_ylim(0,1000)
axb.invert_yaxis()
ax.fill_between(R.index, R*0, R, color='skyblue', clip_on=True, alpha=1)
ax.set_xlabel('Date')
ax.set_ylabel('Recharge [mm/d]', color='blue')
ax.xaxis.set(minor_locator=mdates.YearLocator(1), major_locator=mdates.YearLocator(5))
ax.set_ylim(0,8)
ax.set_xlim(pd.to_datetime('1990'), pd.to_datetime('2020'))
ax.set_yticks([0,2,4,6,8])
ax.set_zorder(axb.get_zorder() + 1)
ax.grid(which='both', axis='x')
plt.setp(axb.get_yticklabels(), color="red")

#%% MESH DISCRETIZATION

mf = flopy.modflow.Modflow.load(simulations_folder+'/'+model_name+'/'+model_name+'.nam')
gridname = simulations_folder+model_name+'/'+model_name+'.dis'
grid_model = mf.modelgrid
hk_grid = mf.upw.hk
sy_grid = mf.upw.sy

fig, axs = plt.subplots(1, 2, figsize=(12, 4), sharey=True)
axs = axs.ravel()

ax = axs[0]
modelxsect = flopy.plot.PlotCrossSection(model=mf, line={'Row': int((grid_model.shape[1])/2)})
val = hk_grid.array/24/3600 # m/s
try:
    for i in range(val.shape[0]):
        val[i][val[i] <= np.nanmin(val[i])] = np.nanmin(val[i][np.nonzero(val[i])])
except:
    pass
cb = modelxsect.plot_array(val, ax=ax, cmap='viridis', lw=0.5, norm=mpl.colors.LogNorm(vmin=1e-8,vmax=1e-3))
ax.set_title('Hydraulic conductivity [m/s] - Meshgrid West to East', fontsize=12)
ax.set_xlim(0, 9000)
ax.set_ylim(50, 150)
ax.set_xticks([0,2000,4000,6000,8000])
ax.set_xlabel('Distance [m]')
ax.set_ylabel('Elevation [m]')
fig.suptitle(model_name.upper(), x=0.22, y=1.05, fontsize=8)
fig.colorbar(cb)
plt.tight_layout()

ax = axs[1]
modelxsect = flopy.plot.PlotCrossSection(model=mf, line={'Column': int((grid_model.shape[2])/2)})
cb = modelxsect.plot_array(sy_grid.array*100, ax=ax, cmap='viridis', lw=0.5,
                            # vmin=0, vmax=30,
                            norm=mpl.colors.LogNorm(vmin=0.1, 
                                                    vmax=10))
ax.set_title('Specific yield [%] - Meshgrid South to Noth', fontsize=12)
ax.set_xlim(0, 5500)
ax.set_ylim(50, 150)
ax.set_xticks([0,1000,2000,3000,4000,5000])
ax.set_xlabel('Distance [m]')
fig.suptitle(model_name.upper(), x=0.5, y=1.0, fontsize=8)
fig.colorbar(cb)
plt.tight_layout()

#%% 2D VISUALIZATION

visu = visualization_results.Visualization(BV, model_name)
visu.visual2D(object_list = [
                             'map',
                             'grid',
                             'watertable',
                             'watertable_depth',
                             'drain_flow',
                             'surface_flow',
                             'pathlines',
                             'residence_times'
                             ],
              color_scale = [
                             (None,None),
                             (50,140),
                             (50,140),
                             (0,10),
                             (0,300),
                             (0,30000),
                             (0,2.5),
                             (0,5),
                             ], 
                             lines=750)
 
#%% 3D VISUALIZATION

export_vtuvtk.VTK(BV, model_name)
visu = visualization_results.Visualization(BV, model_name)
visu.visual3D(interactive=True, object_list=[
                                             'grid',
                                             'watertable',
                                             'watertable_depth',
                                             'surface_flow',
                                             'drain_flow',
                                             'pathlines'
                                             ],
                                              view='south-west',
                                              lines=None,
                                              cloc=(0.7,0.1),
                                              z_scale=10)

#%% INTERACTIVE CROSS-SECTION

dem_data = imageio.imread(os.path.join(stable_folder,'geographic','watershed_box_buff_dem.tif')) # dem data
stream_data = imageio.imread(os.path.join(stable_folder,'hydrography','regional stream network.tif')) # river data
watertable_data = imageio.imread(os.path.join(simulations_folder,model_name,'_postprocess/_rasters/','watertable_elevation_t(0).tif')) # watertable data
interactive = True
visu = visualization_results.Visualization(BV, model_name)
visu.interactive_cross_section(dem_data, watertable_data, stream_data, interactive)

#%% ---- NOTES

os.chdir(root_dir)
