# -*- coding: utf-8 -*-

#%% MODULES

# Modules
import sys
from os.path import dirname, abspath
DIR = dirname(dirname(abspath(__file__)))
sys.path.append(DIR)
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import imageio
import warnings
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False

# warnings.filterwarnings("ignore", message=".*An exception was ignored while fetching the attribute.*", category=DeprecationWarning)
# warnings.filterwarnings("ignore", message=".*`np.object` is a deprecated alias for the builtin `object`.*", category=DeprecationWarning)
# warnings.filterwarnings("ignore", message=".*is deprecated. Use tobytes().*", category=DeprecationWarning)
# warnings.filterwarnings("ignore")
# warnings.warn("You won't see this warning")
                                            
# HydroModPy modules
from watershed import watershed_root, forcing
from tools import tif_adds, serie_transf, tif_features, file_adds, vtk
from watershed.data import hydrology, climatic, oceanic, piezometry

#%% LOAD

# General paths
root_path= "D:/Google Drive/1.TRAVAIL/PYTHON/FLOPY/_data/"


# Specific paths
hydrology_path = root_path + 'HYDROLOGY' # cours d'eau
modflow_path = root_path + 'MODFLOW' # executable + bin
dem_path = root_path + "/DEM/" + "BDALTI_25M_09_MERGED.tif"
surfex_path =  root_path + 'SURFEX'

# Selected watershed
library_path = DIR + '/watershed' + '/watershed_library.csv'
# watershed_name = 'Guadeloupe'
watershed_name = 'Lasset'

# Import library
outlets = pd.read_csv(library_path, sep=';', header=0, engine='python')
outlets = outlets[outlets['name'] == watershed_name]

# Results paths
out_path = "D:/Google Drive/1.TRAVAIL/PYTHON/FLOPY/_permanent/_out/"
stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'

# Hydrographic network
# types_obs = ['guadeloupe_rivers']
# fields_obs = ['FID']
types_obs = ['stream_digit'] # shapefile cours d'eau

# Generate watershed
load = False
print('##### '+watershed_name.upper()+' #####')

BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=dem_path, 
                              out_path=out_path,
                              surfex_path=surfex_path, 
                              hydrology_path=hydrology_path,
                              modflow_path=modflow_path,
                              library_path=library_path,
                              load=load,
                              types_obs=types_obs)

# Plot dem
dem_data = imageio.imread(BV.geographic.watershed_dem)
dem_data[dem_data<0] = np.nan
x = plt.imshow(dem_data)

#%% PARAMETERS

# Define recharge
#recharge = 0.75 * (1/365) # m/j
#BV.forcing.update_recharge(recharge, 'steady') # steady or transient
BV.forcing.update_recharge_surfex('REA','historic',1960,2019,'D','steady')

# Define hydraulic conductivity
BV.hydrodynamic.update_hyd_cond(1e-5*3600*24) # m/s en m/j


BV.hydrodynamic.update_thickness(50)

# Name of model
name_model = 'test'
#%%

# from osgeo import gdal
# bv = gdal.Open(BV.geographic.watershed_dem)
# dem = bv.GetRasterBand(1).ReadAsArray()

#%% MODEL

# Launch model
BV.run_modflow(ident=name_model, sea_level=None, lay_number=1, modpath_sim=False)

#%% CALIBRATION

BV.calib_dichotomy(ident=None, calib=True, type_river='stream_digit', climatic=BV.forcing.recharge,
                    lay_number=1, thick=BV.hydrodynamic.thickness, bottom=None, thick_exp=1., 
                    first=10, last=1000, gap=1, porosity=0.01, sea_level=None, cond_decay=0.)

#%% VTK

name_model = 'dic-zhstreams-23.656-0.001-50'
from groundwater_flow import vizualisation
vtk.VTK(BV, name_model)
visu = vizualisation.Vizualisation(BV, name_model)
# visu.visual3D(interactive=True, object_list=['grid','watertable', 'pathlines', 'watertable_depth'], view='south-west')
visu.visual3D(interactive=True, object_list=['grid','watertable', 'watertable_depth'], view='north-east')

#%%

BV.display(type='watershed_geology')

#%% PLOTS

import matplotlib as mpl
from matplotlib.font_manager import FontProperties

mpl.style.use('classic')
# mpl.rcParams['backend'] = 'wxAgg'
mpl.rcParams["figure.facecolor"] = 'white'
mpl.rcParams['grid.color'] = 'darkgrey'
mpl.rcParams['grid.linestyle'] = '-'
mpl.rcParams['grid.alpha'] = 0.8
mpl.rcParams['axes.axisbelow'] = True
mpl.rcParams['axes.linewidth'] = 1.5
mpl.rcParams['figure.dpi'] = 300
mpl.rcParams['savefig.dpi'] = 300
mpl.rcParams['patch.force_edgecolor'] = True
mpl.rcParams['image.interpolation'] = 'nearest'
mpl.rcParams['image.resample'] = True
mpl.rcParams['axes.autolimit_mode'] = 'data' # 'round_numbers' # 
mpl.rcParams['axes.xmargin'] = 0.05
mpl.rcParams['axes.ymargin'] = 0.05
mpl.rcParams['xtick.direction'] = 'in'
mpl.rcParams['ytick.direction'] = 'in'
mpl.rcParams['xtick.major.size'] = 5
mpl.rcParams['xtick.minor.size'] = 3
mpl.rcParams['xtick.major.width'] = 1.5
mpl.rcParams['xtick.minor.width'] = 1
mpl.rcParams['ytick.major.size'] = 5
mpl.rcParams['ytick.minor.size'] = 1.5
mpl.rcParams['ytick.major.width'] = 1.5
mpl.rcParams['ytick.minor.width'] = 1
mpl.rcParams['xtick.top'] = True
mpl.rcParams['ytick.right'] = True
mpl.rcParams['legend.numpoints'] = 1
mpl.rcParams['legend.scatterpoints'] = 1
mpl.rcParams['legend.edgecolor'] = 'grey'
mpl.rcParams['date.autoformatter.year'] = '%Y'
mpl.rcParams['date.autoformatter.month'] = '%Y-%m'
mpl.rcParams['date.autoformatter.day'] = '%Y-%m-%d'
mpl.rcParams['date.autoformatter.hour'] = '%H:%M'
mpl.rcParams['date.autoformatter.minute'] = '%H:%M:%S'
mpl.rcParams['date.autoformatter.second'] = '%H:%M:%S'

smal = 8
intm = 15
medium = 18
large = 20

plt.rc('font', size=smal)                         # controls default text sizes **font
plt.rc('figure', titlesize=large)                   # fontsize of the figure title
plt.rc('legend', fontsize=smal)                     # legend fontsize
plt.rc('axes', titlesize=medium, labelpad=10)        # fontsize of the axes title
plt.rc('axes', labelsize=medium, labelpad=12)        # fontsize of the x and y labels
plt.rc('xtick', labelsize=intm)                   # fontsize of the tick labels
plt.rc('ytick', labelsize=intm)                   # fontsize of the tick labels
plt.rc('font', family='arial')
fontprop = FontProperties()
fontprop.set_family('arial') # for x and y label
fontdic = {'family' : 'arial', 'weight' : 'bold'} # for legend

par = {'mathtext.default': 'regular' }          
mpl.rcParams.update(par)

#%% MAP

from decimal import Decimal
from mpl_toolkits.axes_grid1.anchored_artists import AnchoredSizeBar
from matplotlib_scalebar.scalebar import ScaleBar
import os
from glob import glob
import geopandas as gpd
from osgeo import gdal
import rasterio
from mpl_toolkits.axes_grid1 import make_axes_locatable

git_path = "C:/Users/LocalAdmin/Documents/GitHub/HydroModPy/CORE_COMM/"
file_adds.create_folder(out_path+'/_dichotomy/')

geol_s = gpd.read_file(root_path+'GEOLOGY/'+'GEO001M_CART_FR_S_FGEOL_2154_CMYK.shp')
geol_l = gpd.read_file(root_path+'GEOLOGY/'+'GEO001M_CART_FR_L_STRUCT_2154_CMYK.shp')

obs= 'stream_digit'
    
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
    ax.set_title(watershed_name.upper(), fontproperties=fontprop)
    ax.set(aspect='equal')
    scalebar = AnchoredSizeBar(ax.transData, 2000, '2 km', 'lower right', 
                               pad=0.2, color='white', frameon=False, size_vertical=1,
                               fontproperties=fontprop)
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
    ax.set_title('K = '+('%.1E'%Decimal(koptim/24/3600))+' m/s'+'  -  '+'D = '+str(doptim)+' m', fontproperties=fontprop)
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
    geol_s.plot(ax=ax, color=list(geol_s['hex']),alpha=0.3, edgecolor='dimgrey', zorder=0) 
    geol_l.plot(ax=ax, color=list(geol_l['hex']), alpha=1, zorder=1)
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

git_path = "C:/Users/LocalAdmin/Documents/GitHub/HydroModPy/CORE_COMM/"
file_adds.create_folder(out_path+'/_dichotomy/')

fig, ax = plt.subplots(1, 1, dpi=300, figsize=(5,4.5), sharex=True, sharey=True)
# ax.set_xlabel('$K_{eq}$'+ ' [m.s$^-$$^1$]' + '\n' + 'Hydraulic conductivity')
ax.set_xlabel('K / R'+ ' [-]' + '\n' + 'Hydraulic conductivity / Recharge')
ax.set_ylabel('Distance criterion' + '\n' + '$D_{optim}$' + ' [m]')

cpt1 = 1
cpt2 = 1
 
obs = 'stream_digit'
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

#%% NOTES