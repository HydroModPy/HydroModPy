# -*- coding: utf-8 -*-

#%% IMPORT MODULES

# Modules
import sys
import os
from os.path import dirname, abspath
DIR = dirname(dirname(abspath(__file__)))
sys.path.append(DIR)
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import matplotlib as mpl
from osgeo import gdal
import imageio
import rasterio
import geopandas as gpd
from glob import glob
from mpl_toolkits.axes_grid1 import make_axes_locatable
from matplotlib.colors import LightSource
from matplotlib.pyplot import cm
from matplotlib.ticker import MaxNLocator
import warnings

# warnings.filterwarnings("ignore", 
#                         message=".*An exception was ignored while fetching the attribute.*",
#                         category=DeprecationWarning)
# warnings.filterwarnings("ignore", 
#                         message=".*`np.object` is a deprecated alias for the builtin `object`.*",
#                         category=DeprecationWarning)
# warnings.filterwarnings("ignore", 
#                         message=".*is deprecated. Use tobytes().*",
#                         category=DeprecationWarning)
# warnings.filterwarnings("ignore")
# warnings.warn("You won't see this warning")
                                            
# HydroModPy modules
from watershed import watershed_root, forcing, watershed_display
from tools import toolbox
from watershed.data import hydrology, climatic, oceanic, piezometry

import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False

#%% PATHS LOAD

# Users
root_path= "C:/Users/Lucas/Desktop/HYDROMODPY/_data/"
hydrology_path = root_path + 'HYDROLOGY' # cours d'eau
modflow_path = root_path + 'MODFLOW' # executable + bin
dem_path = root_path + "/DEM/" + "DEM_SRTMGL3.tif"
surfex_path =  None
clm_path = None

out_path = "C:/Users/Lucas/Desktop/HYDROMODPY"

library_path =  'C:/Users/Lucas/Documents/HydroModPy/CORE_COMM/watershed/watershed_library.csv'
watershed_name = 'Taiwan2'
outlets = pd.read_csv(library_path, sep=';', header=0, engine='python')
outlets = outlets[outlets['watershed_name'] == watershed_name]

load = True

print('##### '+watershed_name.upper()+' #####')

stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'

types_obs = ['taiwan_rivers_reproj']# files of rivers
fields_obs = ['FID']

BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=dem_path, 
                              out_path=out_path,
                              modflow_path=modflow_path,
                              library_path=library_path,
                              load=load)
BV.add_hydrology(hydrology_path, types_obs=types_obs, fields_obs=fields_obs)


#%% PLOT watershed topography

watershed_display.watershed_dem(BV)
watershed_display.watershed_local(dem_path, BV)

#%% || WORK IN PROGRESS || Create recharge files for watershed

# if os.path.isdir(stable_folder + 'recharge')==False:# create the folder if doesn't exist
#     os.mkdir(stable_folder + "recharge")
# i=0
# filename="qcharge_"
# for path in os.listdir(root_path + "DEM/qcharge/"):# loop on every .tif
#     i=i+1
#     if os.path.isfile(stable_folder + "recharge/" + filename + str(i) + "_cliped.tif")==False:# if croped doesn't exists
#         wbt.clip_raster_to_polygon(root_path + "/DEM/qcharge/" + filename + str(i) + ".tif",# files of recharge over all taiwan
#                                     stable_folder + "geographic/watershed.shp",# shapefile of the watershed
#                                     stable_folder + "recharge/" + filename + str(i) + "_cliped.tif")# watershed recharge per timestep

# data_dir = stable_folder + "recharge"
# file_list = glob(os.path.join(data_dir, '*.tif'))

# def read_file(file):
#     with rasterio.open(file) as src:
#         return(src.read(1))

# # Read all data as a list of numpy arrays 
# array_list = [read_file(x) for x in file_list]
# # Perform averaging
# array_out = np.mean(array_list, axis=(1,2))

#%% Crop netcdf file to get recharge in watershed
import xarray as xr
from shapely.geometry import mapping



with xr.open_dataset(r"C:/Users/Lucas/Desktop/HYDROMODPY/_data/DEM/19860820-19860824_var.nc", decode_coords = 'all') as ds:
    ds.load() #load as dataset
mask_df = gpd.read_file(r"C:/Users/Lucas/Desktop/HYDROMODPY/Taiwan2/results_stable/geographic/watershed.shp") #load as geodataframe
clipped_ds = ds.rio.clip(mask_df.geometry.apply(mapping),
                         mask_df.crs, all_touched = True)

#%% MODELLING
model_name='test3'

recharge = np.loadtxt(open(root_path + "DEM/qcharge/mean_recharge.csv"), delimiter=",")# global recharge timeseries (0 when negative) m/h
# recharge = 0.75 * (3000/1000/365) # m/d
BV.forcing.update_recharge(pd.Series(recharge), 'transient') # steady or transient

BV.hydrodynamic.update_hyd_cond(1e-5*3600) # m/s to m/h
BV.hydrodynamic.update_porosity(0.01)
BV.hydrodynamic.update_thickness(20) # m


# Choice temporal of the simulation
sim_state = 'transient' # 'steady' or 'transient'
init_rech = None # 'first'
period = [1986,1986] # recharge period
first = period[0]
last = period[1]
time_step = 'D' # 'M' or 'D'
actual_date = False # False if date is conceptual
start = '1986-08-20' # necessary to specify the first time_step date

fhist = 1990
lhist = 1991

# Active of not modules
modpath_sim = False # run modpath particle tracking if True
sink_fill = False # permit to fill sinks
box = False # if True generate a rectangular model
verbose = False # add print of MODFLOW in console
post_process = False # print time_step

# Strcture of the model
lay_number = 1 # vertical discrtization
bottom = None # aquifer flat or not
thick_exp = 1 # exponential decay of K with nlay
cond_decay = 0 # exponential decay of K with depth
thick = 20 # m




success, flow_model = BV.run_modflow(ident=model_name,
                                     modpath_sim=modpath_sim,
                                     sink_fill=sink_fill,
                                     box=box,
                                     lay_number=lay_number,
                                     bottom=bottom,
                                     thick_exp=thick_exp,
                                     cond_decay=cond_decay,
                                     verbose=True,
                                     post_process=post_process, 
                                     init_rech=init_rech)




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
                  perenn_intermit_shp = False,
                  groundwater_storage = True,
                  verbose = True,
                  export_tif = True)

# # Extract results
BV.results_modflow(ident=model_name,
                   actual_date=actual_date,
                   start=start,
                   time_step=time_step)



#%% DICHOTOMY CALIBRATION

# Problem with river network layer
BV.calib_dichotomy(ident=None, calib=True, type_river='taiwan_rivers_reproj', climatic=recharge,
                    lay_number=1, thick=50, bottom=None, thick_exp=1., 
                    first=1, last=500, gap=1, porosity=0.01, sea_level=None, cond_decay=0.)

#%% MAP

from decimal import Decimal
from mpl_toolkits.axes_grid1.anchored_artists import AnchoredSizeBar

git_path = "C:/Users/Lucas/Documents/HydroModPy/CORE_COMM/"
file_adds.create_folder(out_path+'/_dichotomy/')

# geol_s = gpd.read_file(root_path+'GEOLOGY/'+'GEO001M_CART_FR_S_FGEOL_2154_CMYK.shp')
# geol_l = gpd.read_file(root_path+'GEOLOGY/'+'GEO001M_CART_FR_L_STRUCT_2154_CMYK.shp')

obs= 'taiwan_rivers_reproj'
    
for idx, row in outlets.iloc[:].iterrows():
    
    fig, axs = plt.subplots(1, 2, figsize=(4,4), dpi=300)
    axs = axs.ravel()
    
    watershed_name = row['name']
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'
    
    print('#################### SITE '+str(idx)+' PLOT '+' : '+watershed_name.upper()+' ####################')
    
    df = pd.read_csv(simulations_folder+'_dichotomy_'+obs+'.csv', sep=';', header=0)
    kroptim = df.iloc[-1]['KR'].round(3)
    koptim = df.iloc[-1]['K'].round(3)
    doptim =  int(((df.iloc[-1]['Oflow'] + df.iloc[-1]['Sflow'].round(3))/2).round(0))
    scan = sorted(glob(simulations_folder+'/'+'dic*'), key=os.path.getmtime)
    for ids, j in enumerate(scan):
        split = j.split('\\')[-1].split('-')[2]
        if split==str(kroptim):
            optimcase = j
            
    streams = gpd.read_file(stable_folder+'hydrology/'+obs+'.shp')
    polyg = gpd.read_file(stable_folder+'geographic/'+'watershed.shp')
    contour = gpd.read_file(stable_folder+'geographic/'+'watershed_contour.shp')
    bounds = contour.geometry.total_bounds
    xlim = ([bounds[0], bounds[2]])
    ylim = ([bounds[1], bounds[3]])   
    dem = stable_folder+'geographic/'+'watershed_extent.tif'
    gdal.Translate(dem, gdal.Open(dem_path), projWin=[xlim[0],ylim[1],xlim[1],ylim[0]], noData=-99999)
    hill = stable_folder+'geographic/'+'watershed_extent_hill.tif'
    wbt.hillshade(dem, hill, azimuth=315.0, altitude=45.0, zfactor=2)    
    dem = rasterio.open(stable_folder+'geographic/'+'watershed_extent.tif')
    hill = rasterio.open(stable_folder+'geographic/'+'watershed_extent_hill.tif')
    img = imageio.imread(stable_folder+'geographic/'+'watershed_extent.tif')
    
    simflow = gpd.read_file(optimcase+'/_dichotomy'+'/simflow.shp')
    raster = rasterio.open(optimcase+'/_dichotomy'+'/simflow.tif')
    
    ax=axs[0] 
    ax.set_xlim(xlim)
    ax.set_ylim(ylim)
    ax.get_xaxis().set_visible(False)
    ax.get_yaxis().set_visible(False)
    ax.set_title(watershed_name.upper())
    ax.set(aspect='equal')
    scalebar = AnchoredSizeBar(ax.transData, 2000, '2 km', 'lower right', 
                               pad=0.2, color='white', frameon=False, size_vertical=1)
    ax.add_artist(scalebar)

    image_hidden = ax.imshow(np.ma.masked_where(dem.read(1) < 0, dem.read(1)), cmap='terrain')
    mnt = rasterio.plot.show(np.ma.masked_where(dem.read(1) < 0, dem.read(1)), ax=ax, transform=dem.transform, cmap='terrain', alpha=1, zorder=2, aspect="auto")
    hil = rasterio.plot.show(np.ma.masked_where(hill.read(1) < 0, hill.read(1)), ax=ax, transform=dem.transform, cmap='Greys_r', alpha=0.5, zorder=2, aspect="auto")
    streams.plot(ax=ax, lw=1, color='navy', zorder=3, edgecolor='none')
    contour.plot(ax=ax, lw=1.5, color='k', zorder=6)
    # simflow.plot(ax=ax, alpha=1, column='VALUE1', cmap=mpl.colors.ListedColormap('red'), 
    #              marker='s', markersize=10, lw=0.1, edgecolor='none', scheme="User_Defined", 
    #              classification_kwds=dict(bins=[75, 500, 1000]), zorder=4)
    divider = make_axes_locatable(ax)
    cax = divider.new_vertical(size="2%", pad=0.05, pack_start=True)
    fig.add_axes(cax)
    cbar = fig.colorbar(image_hidden, cax=cax, orientation="horizontal")
    ticklabels = cbar.ax.get_ymajorticklabels()
    ticks = list(cbar.get_ticks())
    val = np.ma.masked_where(dem.read(1) < 0, dem.read(1))
    minVal =  int(round(np.min(val[np.nonzero(val)],0)))
    maxVal =  int(round(np.max(val[np.nonzero(val)],0)))
    meanVal = int(round(minVal+((maxVal-minVal)/2),0))
    cbar.set_ticks([minVal, meanVal, maxVal])
    cbar.set_ticklabels([minVal, meanVal, maxVal])
    cbar.mappable.set_clim(minVal, maxVal)
    cbar.ax.tick_params(labelsize=10)    
    cbar.ax.yaxis.set_ticks_position('left')
    cbar.ax.tick_params(size=0)
    
    ax=axs[1]
    ax.set_xlim(xlim)
    ax.set_ylim(ylim)
    ax.get_xaxis().set_visible(False)
    ax.get_yaxis().set_visible(False)
    ax.set_title('K = '+('%.1E'%Decimal(koptim/24/3600))+' m/s'+'  -  '+'D = '+str(doptim)+' m')
    # ax.tick_params(axis='both', which='major', labelsize=10)
    # ax.tick_params(axis='y', rotation=90)
    # ax.ticklabel_format(axis='both', style='plain', useOffset=False)
    xlims = ax.get_xlim()[1] - ax.get_xlim()[0]
    ylims = ax.get_ylim()[1] - ax.get_ylim()[0]
    bbox = ax.get_window_extent().transformed(fig.dpi_scale_trans.inverted())
    width, height = bbox.width, bbox.height
    width *= fig.dpi
    height *= fig.dpi
    
    hil = rasterio.plot.show(np.ma.masked_where(hill.read(1) < 0, hill.read(1)), ax=ax, transform=dem.transform, cmap='Greys_r', alpha=0.5, zorder=2)
    # geol_s.plot(ax=ax, color=list(geol_s['hex']),alpha=0.3, edgecolor='dimgrey', zorder=0) 
    # geol_l.plot(ax=ax, color=list(geol_l['hex']), alpha=1, zorder=1)
    streams.plot(ax=ax, lw=1, color='navy', zorder=3, edgecolor='none')
    contour.plot(ax=ax, lw=1.5, color='k', zorder=5)    
    # rast = rasterio.plot.show(np.ma.masked_where(raster.read(1) < 0, raster.read(1)), ax=ax, transform=dem.transform, vmin=0, vmax=1000, cmap='RdYlGn_r', alpha=1, zorder=4)
    simflow.plot(ax=ax, alpha=1, column='VALUE1', cmap="RdYlGn_r", 
                  marker='s', markersize=5, lw=0.1, edgecolor='none', scheme="User_Defined", 
                  classification_kwds=dict(bins=[150, 450, 750]), zorder=4)
    
    # plt.tight_layout()
    fig.tight_layout()
    # fig.savefig(out_path+'/_dichotomy/'+watershed_name+'_'+str(int(kroptim))+'.png', dpi=300, bbox_inches='tight', transparent=False)
    # plt.close()

#%% GRAPH

git_path = "C:/Users/Lucas/Documents/HydroModPy/CORE_COMM/"

file_adds.create_folder(out_path+'/_dichotomy/')

fig, ax = plt.subplots(1, 1, dpi=300, figsize=(5,4.5), sharex=True, sharey=True)
# ax.set_xlabel('$K_{eq}$'+ ' [m.s$^-$$^1$]' + '\n' + 'Hydraulic conductivity')
ax.set_xlabel('K / R'+ ' [-]' + '\n' + 'Hydraulic conductivity / Recharge')
ax.set_ylabel('Distance criterion' + '\n' + '$D_{optim}$' + ' [m]')

cpt1 = 1
cpt2 = 1
 
obs = 'taiwan_rivers_reproj'
couleur = 'k'

for idx, row in outlets.iloc[:].iterrows():
    
    watershed_name = row['name']
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'
    
    print('#################### SITE '+str(idx)+' PLOT '+' : '+watershed_name.upper()+' ####################')
    
    df = pd.read_csv(simulations_folder+'_dichotomy_'+obs+'.csv', sep=';', header=0)
    # x = koptim = df.iloc[-1]['K'].round(3) / 3600 / 24
    x = kroptim = df.iloc[-1]['KR'].round(3)
    y = doptim =  int(((df.iloc[-1]['Oflow'] + df.iloc[-1]['Sflow'].round(3))/2).round(0))

    # couleur = couleurs[idx]
    
    # ax.set_xlim(1e-6,1e-4)
    # ax.set_xlim(1e-3,1)
    # ax.set_ylim(0,300)
    # ax.set_yticks(np.arange(0,301,75))
    ax.set_xscale('log')
    
    ax.scatter(x, y, s=100, marker='o', edgecolor='none', color=couleur, lw=0, alpha=0.5, zorder=cpt1, label=watershed_name)
    ax.scatter(x, y, s=100, marker='o', edgecolor=couleur, color='none', lw=1, alpha=1, zorder=cpt1, label=watershed_name)
    # ax.legend(frameon=False, fontsize=5, loc='upper left', markerscale=0.5, bbox_to_anchor=(1, 1), borderaxespad=0)
    ax.annotate(idx, (x,y), family='sans-serif', fontsize=5, color='dimgray', weight="bold", ha='center', va='center', zorder=cpt2)
    ax.axhline(y=75, ls='--', lw=1, c='k', zorder=0)
    
    cpt1 += 1
    cpt2 += 1
    
fig.tight_layout()
# fig.savefig(out_path+'/_dichotomy/'+'_KRoptim_lithology'+'.png', dpi=300, bbox_inches='tight', transparent=False)


#%% RAW VTK

from groundwater_flow import vizualisation
visu = vizualisation.Vizualisation(BV, 'modflow')
visu.visual3D(interactive=True, object_list=['grid','watertable','pathlines','watertable_depth'], view='south-west')

#%% transient gif

# Extract result chronics
BV.chronics_modflow(ident=model_name, mask=False, outlet_type=True, calib_only=False,
                    first=1, last=120, time_step='daily')
print('Result chronics extraction completed')

# Display simulation
plots.SurfaceOutputs(R, simulations_folder, stable_folder, model_name, types_obs, freq_interv=12, save_gif=True)
#%% extract water table depth 
path = '/Taiwan2/results_simulations/test1/_extraction/'
data = np.load(out_path + path + 'watertable_depth.npy',allow_pickle=True)

