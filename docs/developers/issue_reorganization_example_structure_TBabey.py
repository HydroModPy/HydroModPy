# -*- coding: utf-8 -*-
"""
 * Author: T. Babey
 * Guidel field site simulation
"""

#%% ---- LIBRAIRIES

#%% PYTHON

# Filter warnings (before imports)
import warnings
warnings.filterwarnings('ignore', category=DeprecationWarning)

import pkg_resources # Must be placed after DeprecationWarning as it is itself deprecated
warnings.filterwarnings('ignore', message='.*pkg_resources.*')
warnings.filterwarnings('ignore', message='.*declare_namespace.*')

# Libraries installed by default
import sys
import os

# Libraries need to be installed if not
import numpy as np
import pandas as pd

# Libraries added from 'conda install' procedure
import geopandas as gpd
import matplotlib as mpl
import matplotlib.pyplot as plt
import rasterio
from IPython import get_ipython
get_ipython().run_line_magic('matplotlib', 'inline')
import flopy
import imageio

#%% ROOT

from os.path import dirname, abspath
root_dir = dirname(dirname(dirname(abspath(__file__))))
sys.path.append(root_dir)
print("Root path directory is: {0}".format(root_dir.upper()))

#%% HYDROMODPY

import src
import importlib
importlib.reload(src)

# Import HydroModPy modules
from hydromodpy.backends import get_whitebox_backend
from hydromodpy.legacy.watershed import watershed_root_legacy
from src.display import visualization_watershed, visualization_results, export_vtuvtk
from src.tools import toolbox, folder_root

wbt = get_whitebox_backend()
fontprop = toolbox.plot_params(8,15,18,20) # small, medium, interm, large

#%% ---- PATHS

#%% DEFAULT PATHS

example_path = os.path.join(root_dir, "examples", "Dinan_retenue-val/")
data_path = os.path.join(example_path, "data/")

# The folder out_path is created in the example_path root directory:
out_path = os.path.join(root_dir,'examples', 'results')
# Or use a function to update the root folder
# out_path = folder_root.update_root_folder_results()
# Or define it manually
# out_path = 'C:/Simulations/HydroModPy/'

print('The results of the example will be saved here :', out_path)


#%% USER INPUTS

# Nom du fichier MNT (doit Ãªtre prÃ©sent dans dossier "data")
# Conseil : utiliser un MNT de rÃ©solution 50m voire plus large (75, 100) pour 
# commencer afin de limiter le temps de simulation
dem_name = 'dem_guidel_75m.tif'

# Option pour importer le rÃ©seau hydrographique depuis un fichier extÃ©rieur
# (ex: bdtopage) : oui (True) ou non (False)
isUsed_hydroNetwork = True
# Si utilisÃ©, nom du fichier de rÃ©seau hydro (doit Ãªtre prÃ©sent dans dossier 
# "data")
hydroNetwork_name = 'tronconhydro_guidel_bdtopage'

# Nom bu bassin versant (BV)
watershed_name = 'Guidel_Lannenec'

# CoordonnÃ©es de l'exutoire du BV
# [x, y, snap_distance, buffer_size, coordinate_system]
#    -  x,y, coordinate_system : coordonnÃ©es en x et y de l'exutoire dans le
#                                le systÃ¨me de coordonÃ©es coordinate_system
#                                (par dÃ©faut en France : 'EPSG:2154' pour 
#                                Lambert 93)
#    -  snap_distance : [m] Distance maximum oÃ¹ la position de l'exutoire peut
#                       Ãªtre ajustÃ©e (par dÃ©faut: 200m)
#    -  buffer_size : [en % de la taille du BV] Taille totale du modÃ¨le autour
#                     du BV (par dÃ©faut : 10%)
outlet_coordinates = [214866, 6758551 , 200 , 10 , 'EPSG:2154'] 

# Calcule les dimensions du BV (load = False) ou charge les dimensions du BV 
# calculÃ©es lors des simulations prÃ©cÃ©dentes (load = True). Si load = False 
# renvoie une erreur disant qu'un des fichiers ne peut pas Ãªtre supprimÃ© :
# supprimer toutes les variables dans la fenÃªtre "Variable explorer" (haut 
# droit de l'Ã©cran sous Spyder)
# Utile pour Ã©viter de re-calculer les dimensions du BV quand non nÃ©cessaire
load = False

recharge = 300        # Recharge, en mm/an
nlay = 1              # Nombre de couches verticales du modÃ¨le, dÃ©faut : 1
layer_thickness = 20  # Epaisseur de l'aquifÃ¨re
hk = 1e-5             # ConductivitÃ© hydraulique, en m/s
sy = 1 / 100          # Rendement specifque (specific yield), ~ porositÃ©

# A noter / faire attention:
#    - Prendre un DEM suffisament grand pour bien prendre en compte la zone 
#      d'Ã©tude et son buffer  
#    - Toutes les figures montrÃ©es dans la fenÃªtre "Plot" sont aussi
#      enregistrÃ©es en format image dans le dossier de rÃ©sultats (Ã  explorer
#      pour les trouver)  

#%% INPUT CONSOLIDATION
dem_path = data_path + dem_name
load = load
# load = False
watershed_name = watershed_name
from_lib = None # os.path.join(root_dir,'watershed_library.csv')
from_dem = None # [path, cell size]
from_shp = None # [path, buffer size]
from_xyv = outlet_coordinates # [x, y, snap distance, buffer size]
bottom_path = None # path
modflow_path = os.path.join(root_dir,'bin/')
save_object = True

#%% GEOGRAPHIC

print('##### '+watershed_name.upper()+' #####')

BV = watershed_root_legacy.Watershed(dem_path=dem_path,
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
stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'


#%% ---- DATA

# Clips specific data at the catchment scale
# BV.add_geology(data_path, types_obs='GEO050K_HARM_056_S_FGEOL_2154.shp', fields_obs='CODE_LEG')
if isUsed_hydroNetwork:
    BV.add_hydrography(data_path, types_obs=[hydroNetwork_name], fields_obs=['fid'])

# Vizualization
visualization_watershed.watershed_dem(BV)
# visualization_watershed.watershed_geology(BV)

#%% CASES



# # Necessary to set model parameters
BV.add_climatic()

# # Different cases of recharge implementation
# time_series = pd.Series([10,20,30,40,50,60,60,50,40,30,20,10])
# BV.climatic.update_recharge(time_series, sim_state='transient')
# fig, ax = plt.subplots(1,1, figsize=(6,3))
# R = BV.climatic.recharge
# r = R * 0.1
# ax.plot(R, label='recharge_manual', c='dodgerblue', lw=2)
# ax.plot(r, label='runoff_manual', c='navy', lw=2)
# ax.set_xlabel('Months')
# ax.set_ylabel('[mm/month]')
# ax.legend()


#%% ---- PARAMETRIZATION

#%% DEFINE

# Frame settings
model_name = 'default'
box = True # or False
sink_fill = False # or True
sim_state = 'steady' # 'steady' or 'transient'
plot_cross = True
dis_perlen = False

# Climatic settings
recharge = recharge / 12 / 30 /1000 # m/day
first_clim = 'first' # or 'first or value

# Hydraulic settings
nlay = nlay
lay_decay = 1 # 1 for no decay
bottom = None # elevation in meters, None for constant auifer thickness, or 2D matrix
thick = layer_thickness # if bottom is None, aquifer thickness
hk = hk * 24 * 3600 # m/day
cond_drain = None # or value of conductance
sy = sy # -
ss = 1e-10

# Boundary settings
bc_left = None # or value
bc_right = None # or value
sea_level = 'None' # or value based on specific data : BV.oceanic.MSL

#%% UPDATE

# Import modules
BV.add_settings()
BV.add_climatic()
BV.add_hydraulic()

# Frame settings
BV.settings.update_model_name(model_name)
BV.settings.update_box_model(box)
BV.settings.update_sink_fill(sink_fill)
BV.settings.update_simulation_state(sim_state)
BV.settings.update_check_model(plot_cross=plot_cross)

# Climatic settings
BV.climatic.update_recharge(recharge, sim_state=sim_state)
BV.climatic.update_first_clim(first_clim)

# Hydraulic settings
BV.hydraulic.update_nlay(nlay) # 1
BV.hydraulic.update_lay_decay(lay_decay) # 1
BV.hydraulic.update_bottom(bottom) # None
BV.hydraulic.update_thick(thick) # 30 / intervient pas si bottom != None
BV.hydraulic.update_hk(hk)
BV.hydraulic.update_sy(sy)
BV.hydraulic.update_ss(ss)
BV.hydraulic.update_cond_drain(cond_drain)
# BV.hydraulic.update_hk_decay(1/50, min_value=1e-10*24*3600, log_transf=False)

# Boundary settings
BV.settings.update_bc_sides(bc_left, bc_right)
BV.add_oceanic(sea_level)
BV.settings.update_dis_perlen(dis_perlen=dis_perlen)

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
                              persistency_index = False,
                              intermittency_monthly = False,
                              intermittency_daily = False,
                              export_all_tif = False)

#%% MODPATH

# case = 'bw_seepage'
# case = 'bw_wells'
case = 'fw_recharge'

if case == 'bw_seepage':
    # Prepare backward particle tracking from seepage inside the catchment studied
    tif_seep = BV.simulations_folder + '/' + model_name + '/_postprocess/_rasters/seepage_areas_t(0).tif'
    tif_seep_clip = BV.simulations_folder + '/' + model_name + '/_postprocess/_rasters/seepage_areas_t(0)_clip.tif'
    wbt.clip_raster_to_polygon(
        tif_seep, 
        BV.stable_folder + '/geographic/watershed.shp', 
        tif_seep_clip, 
        maintain_dimensions=True)
    
    BV.settings.update_input_particles(zone_partic = tif_seep,
                                       cell_div = 1, # 1
                                       zloc_div = True,  # or True, add cells at cell bottom
                                       bore_depth = True, # '[0,5,10] for 3 particles or None
                                       track_dir = 'backward',
                                       sel_random = None, # or int
                                       sel_slice = None, # or int
                                       )
        
if case == 'bw_wells':
    # Prepare backward particle tracking from synthetic boreoles across the catchment
    bore = imageio.imread(BV.geographic.watershed_box_buff_dem)
    bore = bore*0
    xbore,ybore = BV.geographic.crs_to_iloc(x_crs = 214594.2, 
                                            y_crs = 6758954.1, 
                                            crs_proj = 'EPSG:2154')
    bore[ybore,xbore] = 1
    # bore[20,20] = 1
    # bore[40,48] = 1
    # bore[38,22] = 1
    # bore[28,21] = 1
    particles_folder = os.path.join(BV.simulations_folder + '/' + model_name, '_postprocess', '_particles')
    toolbox.create_folder(particles_folder)
    toolbox.export_tif(BV.geographic.watershed_box_buff_dem,
                   bore,
                   BV.geographic.simulations_folder+'/'+model_name+'/'+'_postprocess/_particles/'+'synthetic_boreholes.tif',
                   0)
    tif_bore = BV.geographic.simulations_folder+'/'+model_name+'/'+'_postprocess/_particles/'+'synthetic_boreholes.tif'
    
    BV.settings.update_input_particles(zone_partic = tif_bore,
                                       cell_div = 1, # 1
                                       zloc_div = True,  # or True, add cells at cell bottom
                                       bore_depth = True, # '[0,5,10] for 3 particles or None
                                       track_dir = 'backward',
                                       sel_random = None, # or int
                                       sel_slice = None, # or int
                                       )

if case == 'fw_recharge': 
    tif_recharge = BV.geographic.watershed_box_buff_dem
    tif_recharge_clip = BV.simulations_folder + '/' + model_name + '/_postprocess/_rasters/recharge_area.tif'
    wbt.clip_raster_to_polygon(
        tif_recharge, 
        BV.stable_folder + '/geographic/watershed.shp', 
        tif_recharge_clip, 
        maintain_dimensions=True)
    
    BV.settings.update_input_particles(zone_partic = tif_recharge,
                                       cell_div = 1, # 1
                                       zloc_div = False,  # or True, add cells at cell bottom
                                       bore_depth = None, # '[0,5,10] for 3 particles or None
                                       track_dir = 'forward',
                                       sel_random = None, # or int
                                       sel_slice = None, # or int
                                       )

if sim_state == 'steady':
    if success_modflow == True:
        model_modpath = BV.preprocessing_modpath(model_modflow)
        success_modpath = BV.processing_modpath(model_modpath, write_model=True, run_model=True)
    if success_modpath == True:
        BV.postprocessing_modpath(model_modpath,
                                  ending_point=True,
                                  starting_point=True,
                                  pathlines_shp=True,
                                  particles_shp=False,
                                  random_id=None, # select randomly to save (for pathlines and particles)
                                  ) # None
        
        BV.filtprocessing_modpath(model_modpath,
                                  norm_flux=True, # for forward only
                                  filt_time=True, # delete particles with time at 0, add a column with time divided by 365 (considering recharge in days)
                                  filt_seep=True, # only forward, keep only particles finishing in zone1 (seepage), keep only particles finishing in k1 (first layer)
                                  filt_inout=True, # delete particles in and out in the same cell (first layer)
                                  calc_rtd=True, # compute residence time distribution
                                  random_id=None, # select randomly to keep
                                  ) # None

#%% TIMESERIES

timeseries_results = BV.postprocessing_timeseries(model_modflow=model_modflow,
                                                  model_modpath=model_modpath,
                                                  datetime_format=False, 
                                                  subbasin_results=True) # or None

#%% ---- PLOT

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
              lines=500)

#%% SEEPAGE MAP

lead_numb = '0'
outflow = imageio.imread(simulations_folder+model_name+'/_postprocess/_rasters/accumulation_flux_t(0).tif')
demData = imageio.imread(BV.geographic.watershed_dem)
demData = np.ma.masked_array(demData, mask=demData<0)
res = BV.geographic.resolution

msk_outflow = (outflow<0)
outflow = np.ma.masked_array(outflow, mask=msk_outflow)
outflow = ( np.ma.masked_where(outflow==0, outflow) / (res**2) )
outflow = outflow * 1000 * 365 # mm/year
outflow = np.log10(outflow)

from matplotlib.colors import LightSource
ls = LightSource(azdeg=45, altdeg=45)
cmap = plt.cm.Greys
rgb = ls.shade(demData, cmap=cmap, blend_mode='soft', vert_exag=2, dx=res, dy=res)

fig, ax = plt.subplots(1, 1, figsize=(8,8))
ax.get_xaxis().set_visible(False)
ax.get_yaxis().set_visible(False)
im = ax.imshow(demData, alpha=0.8, cmap=cmap)
im = ax.imshow(rgb, alpha=0.8, cmap=cmap)
cf=ax.imshow(outflow, cmap='YlGnBu', alpha=1, vmin=outflow.min(), vmax=outflow.max())
ax.set_title('Seepage outflow (quick view)')

name_fig = 'map_discharge_' + str(lead_numb) + '.png'
plt.tight_layout()

# fig.savefig(os.path.join(simulations_folder, model_name,
#                             '_postprocess', '_figures', 'RAW_'+model_name+'.png'))

#%% RESIDENCE TIMES MAP

shp_pathlines = gpd.read_file(simulations_folder+model_name+'/_postprocess/_particles/pathlines_weighted.shp')
# shp_endpoints = gpd.read_file(simulations_folder+model_name+'/_postprocess/_particles/starting_weighted.shp')
shp_endpoints = gpd.read_file(simulations_folder+model_name+'/_postprocess/_particles/starting_weighted.shp')


try:
    line = gpd.read_file(stable_folder+'geographic/'+'watershed_contour.shp')
except:
    pass

dem_rio = rasterio.open(BV.geographic.watershed_box_buff_dem)
dem_data = dem_rio.read(1)
dem_data = np.ma.masked_where(dem_data < 0, dem_data)

fig, ax = plt.subplots(1,1, figsize=(7,5))

rasterio.plot.show(dem_data, ax=ax, transform=dem_rio.transform, 
                    cmap='Greys', alpha=0.7, zorder=-10)

shp_pathlines.plot(ax=ax, column='time_win_y', cmap='jet', lw=0.5,
                   norm=mpl.colors.LogNorm(vmin=1, vmax=1000),
                   zorder=1)

shp_endpoints.plot(ax=ax, column='time_win_y', cmap='jet', lw=0, markersize=10,
                   # norm=mpl.colors.LogNorm(vmin=0.1, vmax=1000),
                   legend=True,
                   zorder=2)

try:
    line.plot(ax=ax, color='k', lw=2, zorder=-1)
except:
    pass

ax.set_title('Residence times [y]')

ax.get_xaxis().set_visible(False)
ax.get_yaxis().set_visible(False)  

fig.tight_layout()

# fig.savefig(os.path.join(simulations_folder, model_name,
#                             '_postprocess', '_figures', 'RTD_'+model_name+'.png'))

#%% ---- NOTES

os.chdir(root_dir)

# wbt.geomorphons(
#     'xxx/watershed_box_buff_dem.tif', 
#     'xxx/watershed_box_geomorphons.tif', 
#     search=5, # in cell
#     threshold=0, # angle in degree
#     fdist=0, # in cell  
#     skip=0, # in cell
#     forms=True, 
#     residuals=False, 
# )





