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
import geopandas as gpd
from IPython import get_ipython
get_ipython().run_line_magic('matplotlib', 'inline')
import imageio
import rasterio
import glob
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

example_path = os.path.join(root_dir, "teaching/abherve/")
data_path = os.path.join(example_path, "data")

out_path = 'C:/Users/ronan/Simulations/Course/' # Enter your path here with the similar format

watershed_name = 'Canut' # Nancon - # Choice the catchment

#%% ---- EXTRACT CATCHMENT

# Name of the study site
print('##### '+watershed_name.upper()+' #####')

# Regional DEM
dem_path = os.path.join(data_path, 'regional dem.tif')

# Outlet coordinates of the catchment
if watershed_name == 'Canut':
    from_xyv = [327816.965, 6777886.670, 150, 10 , 'EPSG:2154'] # Canut
if watershed_name == 'Nancon':
    from_xyv = [389285.910, 6816518.749, 150, 10 , 'EPSG:2154'] # Nancon

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

# General plot of the study site
visualization_watershed.watershed_local(dem_path, BV)
visualization_watershed.watershed_geology(BV)
visualization_watershed.watershed_dem(BV)

#%% ---- ADDITIONNAL PLOT

# STREAMFLOW PLOT

Qobs = pd.read_csv(data_path+'/'+'hydrometry catchment ' + watershed_name + '.csv', sep=';', index_col=0, parse_dates=True)
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

# STREAM NETWORK MAP

streams = gpd.read_file(stable_folder+'/hydrography/'+'regional stream network.shp')
catch = gpd.read_file(stable_folder+'/geographic/'+'watershed.shp')
mask = imageio.imread(stable_folder+'/geographic/'+'watershed_dem.tif')
dem = rasterio.open(BV.geographic.watershed_dem)
dem_data = np.ma.masked_where(dem.read(1) < 0, dem.read(1)) # dem data

fig, ax = plt.subplots(1,1, figsize=(7,6))
rasterio.plot.show(dem_data, ax=ax, transform=dem.transform, cmap='Greys', alpha=0.5, zorder=0, aspect="auto")
streams_clip = streams.clip(catch)
streams_clip[streams_clip['persistanc']=='Permanent'].plot(ax=ax, lw=3, color='navy', zorder=1)
streams_clip[streams_clip['persistanc']=='Intermittent'].plot(ax=ax, lw=3, color='dodgerblue', zorder=1)
catch.plot(ax=ax, facecolor='none', lw=2)
fig.tight_layout()

#%% ---- RECHARGE INITIAL

BV.add_climatic()
BV.climatic.update_recharge_reanalysis(path_file=os.path.join(data_path,'_climate_REANALYSIS.csv'),
                                       clim_mod='REA',
                                       clim_sce='historic',
                                       first_year=1990,
                                       last_year=2019,
                                       time_step='D',
                                       sim_state='transient')
R = BV.climatic.recharge

fig, ax = plt.subplots(1,1, figsize=(7,3), dpi=300)
ax.patch.set_visible(False)
axb = ax.twinx()
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

#%% ---- MODEL PARAMETRIZATION

# Name of the model/simulation
sim_state = 'steady' # 'transient' - Choice your simulation dynamics
model_name = sim_state + '_' + '1'

# Choice hydraulic parameters
K_value = 1e-8 # m/s - hydraulic conductivity
Sy_value = 5 # m/s - specific yield (porosity)

# Import modules
BV.add_settings()
BV.add_climatic()
BV.add_hydraulic()

# Frame settings
BV.settings.update_model_name(model_name) # Name of the model/simulation
BV.settings.update_box_model(True)
BV.settings.update_sink_fill(False)
BV.settings.update_simulation_state(sim_state) # steady or transient
BV.settings.update_active_plot(plot_cross=False)

# Climatic settings
first = 2001
last = 2003
recharge_mensual = select_period(R.resample('M').mean()/1000, first, last)
factor = (select_period(Qobs.resample('M').mean()/1000, first, last)).sum() / (recharge_mensual.sum())
recharge_mensual = recharge_mensual * factor
BV.climatic.update_recharge(recharge_mensual, sim_state=BV.settings.sim_state)
BV.climatic.update_first_clim('mean') # or 'first or value

# Hydraulic settings
BV.hydraulic.update_nlay(3)
BV.hydraulic.update_lay_decay(1.5) # If 1: descativated
BV.hydraulic.update_bottom(None) # Set a value to set a flat bottom
BV.hydraulic.update_thick(50) # Not consider if bottom != of None
BV.hydraulic.update_hyd_cond(K_value * 24 * 3600) # m/d
BV.hydraulic.update_porosity(Sy_value/100) # -
BV.hydraulic.update_cond_decay(1/10) # Exponential decay with depth : 1/10 (about half decrease at 10m)
BV.hydraulic.update_poro_decay(1/10) # If 0: descativated
BV.hydraulic.update_cond_vertical(None) # or [ [1e-5, [0, 20]], [1e-6, [20,80]] ]
BV.hydraulic.update_cond_drain(None)

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

#%% ---- POST-PROCESSING RESULTS

if success_modflow == True:
    BV.postprocessing_modflow(model_modflow,
                              watertable_elevation=True,
                              watertable_depth=True, 
                              seepage_areas=True,
                              outflow_drain=True,
                              groundwater_flux=True,
                              groundwater_storage=True,
                              accumulation_flux=True,
                              persistency_index=True, # only in transient
                              intermittency_monthly=True, # only in transient
                              intermittency_weekly=False, # only in transient
                              intermittency_daily=False, # only in transient
                              export_all_tif=False,
                              export_netcdf=True)

#%% ---- PARTICLE TRACKING RUN

if BV.settings.sim_state == 'steady':
    
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

else:
    model_modpath = None

#%% ---- GENERATE TIMESERIES

timeseries_results = BV.postprocessing_timeseries(model_modflow=model_modflow,
                                                  model_modpath=model_modpath,
                                                  actual_date=True, 
                                                  subbasin_results=True,
                                                  freq_time='M') # or 'M' or None

#%% ---- STEADY-STATE PLOT RESULTS

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
if watershed_name == 'Canut':
    ax.set_xlim(0, 9000)
    ax.set_ylim(50, 150)
    ax.set_xticks([0,2000,4000,6000,8000])
if watershed_name == 'Nancon':
    ax.set_xlim(0, 11000)
    ax.set_ylim(50, 250)
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
if watershed_name == 'Canut':
    ax.set_xlim(0, 5500)
    ax.set_ylim(50, 150)
    ax.set_xticks([0,1000,2000,3000,4000,5000])
if watershed_name == 'Nancon':
    ax.set_xlim(0, 12500)
    ax.set_ylim(50, 250)
ax.set_xlabel('Distance [m]')
fig.suptitle(model_name.upper(), x=0.5, y=1.0, fontsize=8)
fig.colorbar(cb)
plt.tight_layout()

#%% 2D VISUALIZATION

if BV.settings.sim_state == 'steady':

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
                                 lines=750
                                 )

else:
    
    visu = visualization_results.Visualization(BV, model_name)
    visu.visual2D(object_list = [
                                 'map',
                                 'grid',
                                 'watertable',
                                 'watertable_depth',
                                 'drain_flow',
                                 'surface_flow',
                                 # 'pathlines',
                                 # 'residence_times'
                                 ],
                  color_scale = [
                                 (None,None),
                                 (50,140),
                                 (50,140),
                                 (0,10),
                                 (0,300),
                                 (0,30000),
                                 # (0,2.5),
                                 # (0,5),
                                 ], 
                                 # lines=750
                                 )
    
#%% 3D VISUALIZATION

if BV.settings.sim_state == 'steady':

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

fontprop = toolbox.plot_params(8,15,18,20) # small, medium, interm, large
dem_data = imageio.imread(os.path.join(stable_folder,'geographic','watershed_box_buff_dem.tif')) # dem data
stream_data = imageio.imread(os.path.join(stable_folder,'hydrography','regional stream network.tif')) # river data
watertable_data = imageio.imread(os.path.join(simulations_folder,model_name,'_postprocess/_rasters/','watertable_elevation_t(0).tif')) # watertable data
interactive = True
visu = visualization_results.Visualization(BV, model_name)
visu.interactive_cross_section(dem_data, watertable_data, stream_data, interactive)

#%% CHECK STREAM NETWORKS

fig, ax = plt.subplots(1, 1, figsize=(5,3), dpi=300)

stable_folder = os.path.join(out_path, watershed_name, 'results_stable') # necessary for plots
simulations_folder = os.path.join(out_path, watershed_name, 'results_simulations')

dem_data = imageio.imread(BV.geographic.watershed_box_buff_dem)
dem_data = np.ma.masked_where(dem_data < 0, dem_data)

contour = imageio.imread(BV.geographic.watershed_contour_tif)
contour = np.ma.masked_where(contour < 0, contour)

obs_river_data = imageio.imread(os.path.join(stable_folder, 'hydrography',
                                             'regional stream network.tif'))
obs_river_data = np.ma.masked_where(obs_river_data < 0, obs_river_data)

seep_river_data = imageio.imread(os.path.join(simulations_folder, model_name,
                                              r'_postprocess/_rasters/seepage_areas_t(0).tif'))
seep_river_data = np.ma.masked_where(seep_river_data <= 0, seep_river_data)

sim_river_data = imageio.imread(os.path.join(simulations_folder, model_name,
                                             r'_postprocess/_rasters/accumulation_flux_t(0).tif'))
sim_river_data = np.ma.masked_where(sim_river_data <= 0, sim_river_data)

im_dem = ax.imshow(dem_data, alpha=0.5, cmap='Greys')
im_cont = ax.imshow(contour, alpha=1, cmap=mpl.colors.ListedColormap('k'))
im_obs = ax.imshow(obs_river_data, alpha=1, cmap=mpl.colors.ListedColormap('navy'))
im_sim = ax.imshow(sim_river_data, cmap=mpl.colors.ListedColormap('gold'), alpha=1)
im_seep = ax.imshow(seep_river_data, cmap=mpl.colors.ListedColormap('red'), alpha=1)

ax.set_xlabel('X [pixels]')
ax.set_ylabel('Y [pixels]')
ax.set_title('K = '+'{:.2e}'.format(model_modflow.hyd_cond.mean()/24/3600)+' m/s')

fig.tight_layout()

#%% ---- TRANSIENT PLOT RESULTS

stable_folder = os.path.join(out_path, watershed_name, 'results_stable') # necessary for plots
simulations_folder = os.path.join(out_path, watershed_name, 'results_simulations')
fontprop = toolbox.plot_params(8,15,18,20) # small, medium, interm, large

#%% CHECK MIN MAX STREAMS
    
line = imageio.imread(os.path.join(stable_folder, 'geographic', 'watershed_contour.tif'))
line = np.ma.masked_where(line <= 0, line)

mask = imageio.imread(os.path.join(stable_folder, 'geographic', 'watershed_dem.tif'))

simul_list = sorted(glob.glob(os.path.join(simulations_folder, model_name+'*')),
                   key=os.path.getmtime)
        
for simul in simul_list[:]:
    
    model_nam = os.path.split(simul)[-1]
        
    Smod_path = os.path.join(simul, r'_postprocess/_timeseries/_simulated_timeseries.csv')
    Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
        
    min_area = Smod['total_areas'].min()
    min_idx = np.argmin(Smod['total_areas'])
    max_area = Smod['total_areas'].max()
    max_idx = np.argmax(Smod['total_areas'])
    max_year = Smod['total_areas'].index[max_idx]
    
    acc_npy = np.load(os.path.join(simul, '_postprocess', 'accumulation_flux.npy'), allow_pickle=True).item()
    inf = 0
    sup = 12
    compt = 0
    step = int(round(len(acc_npy)/12))
    
    for i in range(step):
        print(str(i)+'/'+str(step))
        interv = list(acc_npy.items())[inf:sup]
        for key in range(len(interv)):
            interv[key] = np.ma.masked_array(interv[key][1], mask=(mask<0))

        zero = acc_npy[0] * 0
        for j in range(len(interv)):
            tempo = interv[j].copy()
            tempo[tempo>0] = 1
            zero = zero + tempo
        days_flux = zero.copy()
        days_flux = np.ma.masked_array(days_flux, mask=(mask<0))
        days_flux = np.ma.masked_array(days_flux, mask=(days_flux<=0))
    
    fig, axs = plt.subplots(1,2, figsize=(7,6))
    axs = axs = axs.ravel()
    
    for k, j in enumerate([min_idx, max_idx]):
            
        ax = axs[k]
    
        year = Smod['total_areas'].index[j]
        val = Smod.iloc[j]['total_areas']

        days_flux = acc_npy[j]
        
        ax.set_title(str(year)[0:10] + '   ' + '$A_{sat}$ = ' + str(val.round(1)) + ' [%]',
                     pad=10, fontsize=10)
        ax.imshow(np.ma.masked_where(mask<0, mask), cmap='Greys', alpha=0.5, zorder=0)
        ax.imshow(np.ma.masked_where((days_flux<=0) | (mask <0),
                                     days_flux), 
                  cmap = mpl.colors.ListedColormap(['navy'])) # dodgerblue
        ax.imshow(line, cmap=mpl.colors.ListedColormap('k'))
        
        ax.get_xaxis().set_visible(False)
        ax.get_yaxis().set_visible(False)
        ax.axis('off')
        
    fig.suptitle(model_name.upper(), y=0.85, fontsize=8)
    
    fig.tight_layout()

#%% CHECK STREAM INTERMITTENCY

simul_list = sorted(glob.glob(os.path.join(simulations_folder, 
                                           model_name+'*')),
                   key=os.path.getmtime)

line = imageio.imread(os.path.join(stable_folder,
                                   'geographic',
                                   'watershed_contour.tif'))
line = np.ma.masked_where(line <= 0, line)

mask = imageio.imread(os.path.join(stable_folder,
                                   'geographic',
                                   'watershed_dem.tif'))

fig, ax = plt.subplots(1, 1, figsize=(7,6))

for i, simul in enumerate(simul_list[:]):
        
    model_name = os.path.split(simul)[-1]
        
    pi = imageio.imread(os.path.join(simul, r'_postprocess/_rasters',
                                     'persistency_index_t(-).tif'))
    pi = np.ma.masked_where(pi==-9999, pi)
    pi = np.ma.masked_where(mask==-99999, pi)
    
    im = ax.imshow(pi, cmap='jet')
    
    ax.imshow(line, mpl.colors.ListedColormap(['k']),
                  vmin=0, vmax=1)
    
    ax.get_xaxis().set_visible(False)
    ax.get_yaxis().set_visible(False)
    ax.axis('off')
    
    ax.set_title(model_name.upper(), fontsize=8)
    
    # fig.subplots_adjust(right=0.8)
    cbar_ax = fig.add_axes([0.25, 0.05, 0.5, 0.02])
    cb = fig.colorbar(im, cax=cbar_ax, orientation="horizontal", pad=0.2)
    cb.set_label('Persistency index [-]', fontsize=10)  # cax == cb.ax
        
    fig.tight_layout()

fig.tight_layout

#%% CHECK STREAM FLOWS

def select_period(df, first, last):
    df = df[(df.index.year>=first) & (df.index.year<=last)]
    return df

Qobs_path = os.path.join(data_path, 'hydrometry catchment ' + watershed_name + '.csv')
Qobs = pd.read_csv(Qobs_path, sep=';', index_col=0, parse_dates=True)

area = int(round(BV.geographic.area))
Qobs = (Qobs / (area*1000000)) * (3600 * 24) # m3/s to m/day
Qobs = Qobs.resample('M').sum() * 1000 # m/day to mm/month

simul_list = sorted(glob.glob(os.path.join(simulations_folder,
                                           model_name+'*')),
                   key=os.path.getmtime)

for i, simul in enumerate(simul_list[:]):
    
    fig, (a0, a1) = plt.subplots(1, 2, gridspec_kw={'width_ratios': [3, 1]},
                                 figsize=(10,3))

    model_name = os.path.split(simul)[-1]
        
    Smod_path = os.path.join(simul, 
                             r'_postprocess/_timeseries/_simulated_timeseries.csv')
    Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
    
    Qmod = Smod['outflow_drain'] 
    Qmod = Qmod.squeeze() * 30 * 1000 # mm/month
    # Qmod = Qmod + (Qmod * 1)
    Rmod = Smod['recharge'] * 30 * 1000
    
    yearsmaj = mdates.YearLocator(1)   # every year
    yearsmin = mdates.YearLocator(1)
    # monthsmaj = mdates.MonthLocator(6)  # every month
    # monthsmin = mdates.MonthLocator(3)
    # months_fmt = mdates.DateFormatter('%m') #b = name of month ?
    years_fmt = mdates.DateFormatter('%Y')

    ax = a0
    ax.plot(Qobs, color='k', lw=2, ls='-', zorder=0, label='Observed')
    ax.plot(Qmod, color='red', lw=2, label='Simulated')
    ax.set_xlabel('Date')
    ax.set_ylabel('Q / A [mm/month]')
    # ax.set_yscale('log')
    ax.set_ylim(0,200)
    ax.xaxis.set_major_locator(yearsmaj)
    ax.xaxis.set_minor_locator(yearsmin)
    ax.xaxis.set_major_formatter(years_fmt)
    ax.set_xlim(pd.to_datetime('2000'), pd.to_datetime('2005'))
    ax.legend()
    ax.set_title(model_name.upper(), fontsize=10)
    
    axb = ax.twinx()
    axb.bar(Rmod.index, Rmod,color='blue', edgecolor='blue', lw=2.5)
    axb.set_ylim(0,999)
    axb.invert_yaxis()
    axb.set_yticklabels([0,200])
    
    Qobs_stat = select_period(Qobs,2001,2003)
    Qmod_stat = select_period(Qmod,2001,2003)
    print(Qmod_stat.sum() / Qobs_stat.sum())
    
    import hydroeval as he
    NSE = he.evaluator(he.nse, Qmod_stat, Qobs_stat)[0]
    NSElog = he.evaluator(he.nse, Qmod_stat, Qobs_stat, transform='log')[0]
    RMSE = np.sqrt(np.nanmean((Qobs_stat.values-Qmod_stat.values)**2))
    KGE = he.evaluator(he.kge, Qmod_stat, Qobs_stat)[0][0]
    print(model_name.upper())
    print('NSE', round(NSE,2))
    print('NSElog', round(NSElog,2))
    print('RMSE', round(RMSE,2))
    
    ax = a1
    ax.scatter(Qobs_stat, Qmod_stat,
               s=25, edgecolor='none', alpha=0.75, facecolor='forestgreen')
    ax.set_xscale('log')
    ax.set_yscale('log')
    ax.plot((0.1,1000),(0.1,1000), color='grey', zorder=-1)
    ax.set_xlim(1,500)
    ax.set_ylim(1,500)
    # ax.set_xlim(0.1,300)
    # ax.set_ylim(0.1,300)    
    ax.set_xlabel('$Q_{obs}$ / A [mm/month]', fontsize=12)
    ax.set_ylabel('$Q_{sim}$ / A [mm/month]', fontsize=12)

    fig.tight_layout()

#%% CHECK DRAINAGE DENSITY

def select_period(df, first, last):
    df = df[(df.index.year>=first) & (df.index.year<=last)]
    return df

Qobs_path = os.path.join(data_path, 'hydrometry catchment Canut.csv')
Qobs = pd.read_csv(Qobs_path, sep=';', index_col=0, parse_dates=True)

area = int(round(BV.geographic.area))
Qobs = (Qobs / (area*1000000)) * (3600 * 24) # m3/s to m/day
Qobs = Qobs.resample('M').sum() * 1000 # m/day to mm/month

simul_list = sorted(glob.glob(os.path.join(simulations_folder,
                                           model_name+'*')),
                   key=os.path.getmtime)

for i, simul in enumerate(simul_list[:]):
    
    model_name = os.path.split(simul)[-1]
    
    Smod_path = os.path.join(simul, 
                             r'_postprocess/_timeseries/_simulated_timeseries.csv')
    Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
        
    Sonde_path = os.path.join(glob.glob(
        os.path.join(simul, r'_subbasins/intermittency_*'))[0],
        '_simulated_timeseries.csv')
    Sonde = pd.read_csv(Sonde_path, sep=';', index_col=0, parse_dates=True)

    # BV.add_intermittency(data_path, 'regional onde stations.shp')

    d = BV.intermittency.flowing
    assec = d[d==1].dropna()
    invi = d[d==2].dropna()
    low = d[d==3].dropna()
    accep = d[d==4].dropna()
    visib = d[d==5].dropna()
    d = d.resample('M').mean()
    
    Smod['onde'] = d
    
    from datetime import timedelta
    x_months = Smod.index + timedelta(days=-30)
    Smod['date'] = x_months
    Smod.index = Smod['date']
    
    fig, ax = plt.subplots(1, 1, figsize=(6,3))
    
    ax.fill_between(Smod.index, 0, Smod['total_areas'],
                    interpolate=False, color='dodgerblue', alpha=0.5,
                    step='pre', label='intermittent part')
    ax.fill_between(Smod.index, 0, Smod['perenn_areas'],
                    interpolate=False, color='navy', alpha=0.5,
                    step='pre', label='perennial part')
    ax.legend()
    ax.step(Smod.index, Smod['total_areas'], color='dodgerblue',
            marker=None, markeredgecolor='none',
            markersize=5, lw=1, label='upstream',
            where='pre')
    ax.step(Smod.index, Smod['perenn_areas'], color='navy',
            marker=None, markeredgecolor='none',
            markersize=5, lw=1, label='upstream',
            where='pre')

    ax.set_ylim(-0,50)
    # ax.set_yticks(np.arange(0,15.05,2.5))
    ax.set_ylabel('$A_{sat}$ [%]')
    # ax.set_xlim(pd.to_datetime('2000-01'), pd.to_datetime('2002-12'))
    plt.xticks(rotation=0, ha="left")

    years_maj = mdates.YearLocator()   # every year
    months_maj = mdates.MonthLocator()  # every x month
    ax.xaxis.set_major_locator(years_maj)
    ax.xaxis.set_minor_locator(months_maj)
    
    if watershed_name == 'Canut':
        ax.axhline(2, color='navy', ls='--')
        ax.axhline(14, color='dodgerblue', ls='--')
    if watershed_name == 'Nancon':
        ax.axhline(6, color='navy', ls='--')
        ax.axhline(16, color='dodgerblue', ls='--')
    
    ax.set_title(model_name.upper(), fontsize=10)
    
    fig.tight_layout()
                
#%% ---- NOTES

os.chdir(root_dir)
