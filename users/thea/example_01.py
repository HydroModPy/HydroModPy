#TYPE OF COMMENTS
# ! Attention : Cette ligne est critique
# ? besoin d'explication TT
# TODO: Implémenter la gestion des erreurs
# * commentaire général TT

#%% ---- LIBRAIRIES
# Filter warnings (before imports)
import warnings
warnings.filterwarnings('ignore', category=DeprecationWarning)

import pkg_resources # Must be placed after DeprecationWarning as it is itself deprecated
warnings.filterwarnings('ignore', message='.*pkg_resources.*')
warnings.filterwarnings('ignore', message='.*declare_namespace.*')

# PYTHON PACKAGES
import sys
import os
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
root_dir = dirname(dirname(dirname(dirname(((abspath(__file__)))))))
sys.path.append(root_dir)
print("Root path directory is: {0}".format(root_dir.upper()))

# HYDROMODPY MODULES
#import src
import importlib
#importlib.reload(src)
from src import watershed_root
from src.watershed import climatic, geographic, geology, hydraulic, hydrography, hydrometry, intermittency, oceanic, piezometry, subbasin
from src.modeling import downslope, modflow, modpath, timeseries
from src.display import visualization_watershed, export_vtuvtk
from src.tools import toolbox, folder_root
from users.touzeau.Examples import visualization_results
fontprop = toolbox.plot_params(8,15,18,20) # small, medium, interm, large

# # Vérifiez si la variable d'environnement est correctement définie
# if not os.path.exists(os.path.join(os.environ['PROJ_LIB'], 'proj.db')):
#     raise RuntimeError(f"PROJ_LIB path does not exist or proj.db not found: {os.environ['PROJ_LIB']}")

#%% ---- PERSONAL PARAMETERS AND PATHS
study_site = 'LA_FLUME'
first_year = 1964
last_year = 2023
parameters = '30_1.3e-5_0.1'

out_path = folder_root.root_folder_results()
#out_path = r"C:\Users\theat\Documents\Python\Output_HydroModPy" # Manually set the output path
data_path = os.path.join(out_path, "data")
specific_data_path = os.path.join(data_path, study_site)


print(f"out_path; {out_path}, Data path: {data_path}, specific_data_folder; {specific_data_path}")
#%% ---- EXTRACT CATCHMENT

# Name of the study site
watershed_name = '_'.join([
    "Example_01",study_site,parameters,str(first_year),str(last_year)
])

print('##### '+watershed_name.upper()+' #####')

# Regional DEM
dem_path = os.path.join(data_path, 'regional dem.tif')

# Outlet coordinates of the catchment
from_xyv = [344964,6797466, 150, 10 , 'EPSG:2154']

# Extract the catchment from a regional DEM
BV = watershed_root.Watershed(dem_path=dem_path,
                              out_path=out_path,
                              load=False,
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

#%% ---- ADD DATA PLOT

# General plot of the study site
visualization_watershed.watershed_local(dem_path, BV)

# Clip specific data at the catchment scale
BV.add_geology(data_path, types_obs='GEO1M.shp', fields_obs='CODE_LEG')
BV.add_hydrography(data_path, types_obs=['regional stream network'])

# Add hydrological data
BV.add_hydrometry(data_path, 'france hydrometric stations.shp')
BV.add_intermittency(data_path, 'regional onde stations.shp')

# subbasin_path = os.path.join(data_path,
#                                   'additional')

# # Extract a subbasin inside the study site
# BV.add_subbasin(subbasin_path, 150) # path, snap_point

# Visualization
visualization_watershed.watershed_geology(BV)
visualization_watershed.watershed_dem(BV)

# #%% ---- PLOT STREAMFLOW
# Qobs = pd.read_csv(data_path+'\\J7214010_QmnJ(n=1_non-glissant)_01011981_31122024.csv', sep=',', index_col=0, parse_dates=True) #m3/s
# Qobs= Qobs.drop(columns=["Statut","Qualification","Méthode","Continuité"])
# Qobs = Qobs.squeeze()
# Qobs = Qobs.rename('Q')

# def select_period(df, first, last):
#     df = df[(df.index.year>=first) & (df.index.year<=last)]
#     return df
# area = BV.geographic.area
# first = 1981
# last = 2024
# Qobs = select_period(Qobs, first, last)
# Qobs = (Qobs / (area*1000000)) * (3600 * 24) * 1000 # m3/s to mm/j
# data_index = Qobs.copy()

# mean_mensual = data_index.resample('M').mean() # mensual mean
# mean_annual = data_index.resample('Y').mean() # annual mean
# Mean = round(data_index.mean(),2)
# Mean = data_index.mean()
# Min = data_index.resample('Y').min()
# Q10 = data_index.resample('Y').quantile(0.10)
# Q25 = data_index.resample('Y').quantile(0.25)
# Q50 = data_index.resample('Y').quantile(0.50)
# Q75 = data_index.resample('Y').quantile(0.75)
# Q90 = data_index.resample('Y').quantile(0.90)
# Max = data_index.resample('Y').max()
# mean_interan_days = data_index.groupby([data_index.index.month,data_index.index.day], as_index=True).mean().to_frame()
# std_interan_days = data_index.groupby([data_index.index.month,data_index.index.day], as_index=True).std()
# q10_interan_days = data_index.groupby([data_index.index.month,data_index.index.day], as_index=True).quantile(0.10)
# q90_interan_days = data_index.groupby([data_index.index.month,data_index.index.day], as_index=True).quantile(0.90)
# q50_interan_days = data_index.groupby([data_index.index.month,data_index.index.day], as_index=True).quantile(0.50)
# mean_interan_days['std'] = std_interan_days
# mean_interan_days['q10'] = q10_interan_days
# mean_interan_days['q90'] = q90_interan_days
# mean_interan_days['q50'] = q50_interan_days
# mean_interan_days.index.names = ['months','days']
# mean_interan_days = mean_interan_days.reset_index()
# mean_interan_days = mean_interan_days.sort_values(['months','days'])
# mean_interan_days['counts'] = np.array(range(1,len(mean_interan_days)+1))

# fig, ax = plt.subplots(figsize=(6,4))
# ax.plot(mean_interan_days.counts, mean_interan_days.q50, lw=2, color='darkred', label='Median')
# yerrmax = mean_interan_days.q90
# yerrmin = mean_interan_days.q10
# ax.fill_between(mean_interan_days.counts, yerrmin, yerrmax, color='cyan', edgecolor='grey', lw=0.5, alpha=0.5, label='10-90th')
# ax.set_yscale('log')
# ax.set_xlim(0,366)
# ax.set_ylim(0.01,10)
# ax.tick_params(axis='both', which='major', pad=10)
# x1 = np.linspace(0,366,13)
# squad = ['J','F','M','A','M','J','J','A','S','O','N','D','J']
# ax.set_xticks(x1)
# ax.set_xticklabels(squad, minor=False, rotation='horizontal')
# ax.set_xlabel('Months', labelpad=+10)
# ax.set_ylabel('Q / A [mm/d]',labelpad=+10)
# ax.set_title(watershed_name + ' [' + str(first) + ' to ' + str(last) + ']\n' )
# ax.grid(alpha=0.25, zorder=0)
# one = 2022
# dates = np.array([one],dtype=np.int64)
# colors = ['blue']
# for z in np.array(range(len(dates))):
#     onlyone = data_index[(data_index.index.year==dates[z])].to_frame()
#     onlyone = onlyone.groupby([onlyone.index.month, onlyone.index.day], as_index=True).mean()
#     onlyone['counts'] = np.array(range(1,len(onlyone)+1))
#     ax.plot(onlyone.counts, onlyone['Q'], color=colors[z], lw=1, label = str(dates[z]))
# ax.legend(loc='lower left')
# plt.tight_layout()

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
BV.settings.update_check_model(plot_cross=False, check_grid=True)
BV.settings.update_dis_perlen(dis_perlen=False)

# Climatic settings
BV.climatic.update_recharge(350 / 1000 / 365, sim_state=BV.settings.sim_state) #* Les valeurs ici sont à changer prendre celle qui sortiront de SIM2
BV.climatic.update_first_clim('mean') # or 'first or value

# Hydraulic settings
BV.hydraulic.update_nlay(1)
BV.hydraulic.update_lay_decay(1) # 1 if not activated
BV.hydraulic.update_bottom(None) # Set a value to set a flat bottom
BV.hydraulic.update_thick(30) # Not consider if bottom != of None
BV.hydraulic.update_hk(1.3e-5 * 24 * 3600) # m/d
BV.hydraulic.update_sy(0.1/100) # -

#* Pour le moment je n'ai pas renseigné ces champs la car je n'ai pas compris leur fonction
# BV.hydraulic.update_hk_decay(1/20, min_value=None, log_transf=False) # Exponential decay with depth : 1/10 (about half decrease at 10m)
# BV.hydraulic.update_sy_decay(1/20, min_value=None, log_transf=False)
# BV.hydraulic.update_ss_decay(1/20, min_value=None, log_transf=False)

BV.hydraulic.update_hk_vertical(None) # or [ [1e-5, [0, 20]], [1e-6, [20,80]] ]
# BV.hydraulic.update_cond_drain(None)

# Boundary settings
BV.settings.update_bc_sides(None, None)
BV.add_oceanic('None') #? On doit le mettre par défaut à None pour que modflow ait bien toute les entrées ? (y/n)

# # Particle tracking settings
# BV.settings.update_input_particles(zone_partic = os.path.join(simulations_folder,model_name,'_postprocess/_rasters/seepage_areas_t(0).tif'),
#                                    track_dir = 'backward')

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
                              export_all_tif=False)

# %%#%% ---- GENERATE TIMESERIES

# timeseries_results = BV.postprocessing_timeseries(model_modflow=model_modflow,
#                                                   model_modpath = None,
#                                                   subbasin_results=False,
#                                                   datetime_format=False)
# #? que veut dire datetime_format: bool=True dans la classe postprocessing_timeseries ? 
# #? qu'est ce que c'est subbassin c'est un sous bassin de notre outlet ou c'est le bassin de l'outlet ? 

#%% ---- GENERATE NETCDF FILES

netcdf_results = BV.postprocessing_netcdf(model_modflow,
                                          datetime_format=False)

#%% ---- PLOT OUTPUT RESULTS
#%% RECHARGE SOURCE

BV.add_climatic()
# # TODO cette class là est faite car la données de sim 2 recharge trop forte pour BZH donc il va lire et récupérer les données ISBA 
first_year = 1994
last_year = 2023
freq_input = 'y' 
sim_state = 'steady' 

##%%% Reanalyse
BV.climatic.update_sim2_reanalysis(var_list=['recharge', 'runoff', 'precip',
                                             'evt', 'etp', 't',
                                              ],
                                       nc_data_path=os.path.join(
                                           specific_data_path,
                                           r"Meteo\Historiques SIM2"),
                                       first_year=first_year,
                                       last_year=last_year,
                                       time_step=freq_input,
                                       sim_state=sim_state,
                                       spatial_mean=True,
                                       geographic=BV.geographic,
                                       disk_clip='watershed') # for clipping the netcdf files saved on disk
                                                                # can be a shapefile path or a flag: 'watershed' or False

# Units
BV.climatic.evt = BV.climatic.evt / 1000 # from mm to m
BV.climatic.etp = BV.climatic.etp / 1000 # from mm to m
BV.climatic.precip = BV.climatic.precip / 1000 # from mm to m
BV.climatic.t = BV.climatic.t / 1000 # from mm to m

# #* cette methode définit la recharge moyenne (en condition stationaire) par rapport au fichier d'entrée _climate_reanalysis.csv, de ce que j'ai compris ca ne fait pas retourner de sous class par rapport à climatic.update_recharge_reanalysis, dans cette class resempling et mean de data c'est tout
# #* en condition transitoire ça ne fais pas la moyenne des données.

# fig, ax = plt.subplots(1,1, figsize=(6,2), dpi=300)
# ax.patch.set_visible(False)
# # axb = ax.twinx()
# R = BV.climatic.recharge
# ax.plot(R.index, R,  color='blue', lw=1, ms=0, clip_on=True)
# # axb.bar(R.resample('Y').sum().index, R.resample('Y').sum(),  color='red', lw=0, width=100, alpha=1, clip_on=True)
# # axb.set_ylim(0,1000)
# # axb.invert_yaxis()
# ax.fill_between(R.index, R*0, R, color='skyblue', clip_on=True, alpha=1)
# ax.set_xlabel('Date')
# # ax.set_ylabel('Recharge [mm/d]', color='blue')
# ax.xaxis.set(minor_locator=mdates.YearLocator(1), major_locator=mdates.YearLocator(5))
# ax.set_ylim(0,8)
# ax.set_xlim(pd.to_datetime('2000'), pd.to_datetime('2020'))
# ax.set_yticks([0,2,4,6,8])
# ax.grid(which='both', axis='x')
# # ax.set_zorder(axb.get_zorder() + 1)
# # plt.setp(axb.get_yticklabels(), color="red")
# ax.invert_yaxis()
# ax.set_title('Recharge [mm/d]', color='blue')

# fig.savefig(out_path+'/'+watershed_name+'/results_simulations/'+model_name+'/_postprocess/_figures/'+'input_rec.png', dpi=300, bbox_inches='tight')

# %% FIXED CROSS SECTION
fig, ax = plt.subplots(1, 1, figsize=(6,4), dpi=300)
print(stable_folder)

mask = imageio.imread(stable_folder+'/geographic/'+'watershed_dem.tif')
watertable_elevation = np.load(simulations_folder+'/'+model_name+'/_postprocess/'+'watertable_elevation'+'.npy', allow_pickle=True).item()

dem_data = imageio.imread(BV.geographic.watershed_dem)
wt_data = watertable_elevation[0]

xvalues = np.linspace(-1,1,dem_data.shape[1])
yvalues = np.linspace(-1,1,dem_data.shape[0])
xx, yy = np.meshgrid(xvalues,yvalues)

cur_x = dem_data.shape[1] /2
cur_x = 65

wt_prof = wt_data.astype(float)
wt_prof[wt_prof<0] = np.nan
dem_max = dem_data.max()
dem_prof = dem_data.astype(float)
dem_prof[dem_prof<0] = np.nan
dem_plot = np.ma.masked_array(dem_data, mask=(dem_data<0))
dem_v_plot = dem_prof[:,int(cur_x)]
dem_v_plot[dem_v_plot == 0] = np.nan
wt_v_plot = wt_prof[:,int(cur_x)]
wt_v_plot[wt_v_plot == 0] = np.nan
           
wt_v_fill = ax.fill_between(np.arange(xx.shape[0])*75, dem_v_plot-20, wt_v_plot, color='dodgerblue', alpha=0.5, lw=0)
w_prof = ax.plot(np.arange(xx.shape[0])*75, wt_v_plot, color='navy', lw=1.5)
wt_v_fill = ax.fill_between(np.arange(xx.shape[0])*75, wt_v_plot, dem_v_plot, color='saddlebrown', alpha=0.5, lw=0)
d_prof = ax.plot(np.arange(xx.shape[0])*75, dem_v_plot, 'saddlebrown', lw=1.5)
ax.fill_between(np.arange(xx.shape[0])*75, 0, dem_v_plot-20, color='lightgrey', alpha=0.5, lw=0)
ax.plot(np.arange(xx.shape[0])*75, dem_v_plot-20, color='dimgray', lw=1.5)

ax.set_xlim(1800, 5000)
ax.set_ylim(60, 140)
ax.set_yticks([90,100,110,120,130])
ax.set_xlabel('Distance [m]')
ax.set_ylabel('Elevation [m]')

plt.tight_layout()

# fig.savefig(out_path+'/'+watershed_name+'/results_simulations/'+model_name+'/_postprocess/_figures/'+'2D_cross.png', dpi=300, bbox_inches='tight')

#%% 2D VISUALIZATION

visu = visualization_results.Visualization(BV, model_name)
visu.visual2D(object_list = [
                             'map',
                             'grid',
                             'watertable',
                             'watertable_depth',
                             'drain_flow',
                             'surface_flow',
                             ],
              color_scale = [
                             (None,None),
                             (80,150),
                             (80,150),
                             (0,10),
                             (0,200),
                             (0,30000),
                             ], 
                             lines=1000)

#%% 3D VISUALIZATION
#? Pour celui là = même erreur que dans le code exmaple01 hydromodpy general, on a 
#?[vedo.file_io] ERROR: in load(), cannot load C:\Users\theat\Documents\Python\Output_HydroModPy\Example_01_Langan_J7214010_2025-01-31\results_simulations\test_0\_postprocess\_vtuvtk\streams.vtk
#? qu'est ce que streams.vtk ?
export_vtuvtk.VTK(BV, model_name)
visu = visualization_results.Visualization(BV, model_name)
visu.visual3D(interactive=True, object_list=[
                                             'grid',
                                             'watertable',
                                             'watertable_depth',
                                             'surface_flow',
                                             'drain_flow',
                                             ],
                                               view='south-west',
                                              # view='north',
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

