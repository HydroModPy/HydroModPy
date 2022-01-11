# -*- coding: utf-8 -*-
"""
Created on Tue Jan 11 22:28:15 2022

@author: LocalAdmin
"""

# -*- coding: utf-8 -*-

#%% GENERAL LIBRARIES

# General
import sys
import os
from os.path import dirname, abspath
DIR = dirname(dirname(dirname(abspath(__file__))))
sys.path.append(DIR)
from glob import glob
import numpy as np
import pandas as pd
from osgeo import gdal, osr
from IPython import get_ipython
get_ipython().run_line_magic('matplotlib', 'inline')
# Plot
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
import matplotlib as mpl
from matplotlib.dates import YearLocator, MonthLocator, DateFormatter
from mpl_toolkits.axes_grid1 import make_axes_locatable
from matplotlib.colors import LightSource
from matplotlib.pyplot import cm
from matplotlib.ticker import MaxNLocator
# Gis
from osgeo import gdal
import imageio
import rasterio
import geopandas as gpd
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = True
# Warnings
import logging
import warnings
# warnings.filterwarnings("ignore", message=".*An exception was ignored while fetching the attribute.*", category=DeprecationWarning)
# warnings.filterwarnings("ignore", message=".*`np.object` is a deprecated alias for the builtin `object`.*", category=DeprecationWarning)
# warnings.filterwarnings("ignore", message=".*is deprecated. Use tobytes().*", category=DeprecationWarning)
# warnings.filterwarnings("ignore", message=".*`np.typeDict` is a deprecated alias for `np.sctypeDict`.*", category=DeprecationWarning)
# warnings.filterwarnings("ignore") # not working
# warnings.simplefilter("ignore", category=DeprecationWarning) # not working
# warnings.warn("You won't see this warning", category=DeprecationWarning) # to modify warnings
logging.captureWarnings(True)
                 
#%% HYDROMODPY MODULES
         
from watershed import watershed_root, forcing, watershed_display
from tools import tif_adds, serie_transf, tif_features, file_adds, to_plot, vtk
from watershed.data import hydrology, climatic, oceanic, piezometry
from groundwater_flow import plots

#%% LAYOUT PLOT

fontprop = to_plot.plot_params(8,15,18,20) # small, medium, interm, large


#%% LOAD

# General paths
root_path= os.path.join("D:/GoogleDrive/1.TRAVAIL/PYTHON/FLOPY/_data/")


# Specific paths
hydrology_path = os.path.join(root_path, "HYDROLOGY") # cours d'eau
modflow_path = os.path.join(root_path, "MODFLOW") # executable + bin
dem_path = os.path.join(root_path,"DEM","BDALTI_25M_09_MERGED.tif")
surfex_path =  os.path.join(root_path,"SURFEX")

# Selected watershed
library_path = os.path.join(DIR,"examples", "roques", "watershed_library.csv")
# watershed_name = 'Guadeloupe'
watershed_name = "Lasset"

# Import library
outlets = pd.read_csv(library_path, sep=';', header=0, engine='python')
outlets = outlets[outlets['watershed_name'] == watershed_name]

# Results paths
out_path = os.path.join("D:/GoogleDrive/1.TRAVAIL/PYTHON/FLOPY/_permanent/_out/")
stable_folder = os.path.join(out_path,watershed_name,"results_stable/")
simulations_folder = os.path.join(out_path, watershed_name, "results_simulations/")

#%% Merger les points shp
pt_streams = stable_folder + 'hydrology/' + 'stream_digit_pt.shp'
pt_zh = stable_folder + 'hydrology/' + 'zh_digit_pt.shp'
merge_path = pt_streams+';'+pt_zh
pt_zhstreams = stable_folder + 'hydrology/' + 'zhstreams_pt.shp'
wbt.merge_vectors(merge_path, pt_zhstreams)

#Merger les tifs
tif_streams = stable_folder + 'hydrology/' + 'stream_digit.tif'
tif_zh = stable_folder + 'hydrology/' + 'zh_digit.tif'
merge_path = tif_streams+';'+tif_zh
tif_zhstreams = stable_folder + 'hydrology/' + 'zhstreams.tif'
wbt.mosaic(tif_zhstreams, inputs=merge_path, method="nn")

types_obs = ["streams"] # shapefile cours d'eau

#%%  Generate watershed
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
#dem_data = imageio.imread(BV.geographic.watershed_dem)
#dem_data[dem_data<0] = np.nan
#x = plt.imshow(dem_data)

#%% Merge streams and ZH


#%% PARAMETERS

# Define recharge
#recharge = 0.75 * (1/365) # m/j
#BV.forcing.update_recharge(recharge, 'steady') # steady or transient
first = 2010
last = 2019
BV.forcing.update_recharge_surfex('REA','historic',first,last,'D','steady')

# Define hydraulic conductivity
K_dic = 3.7312*BV.forcing.recharge
#BV.hydrodynamic.update_hyd_cond(K_dic) # m/s en m/j
BV.hydrodynamic.update_hyd_cond(1e-5*3600*24) # m/s en m/j

length_K_decay = 10
length_K_decay_inv = length_K_decay**-1
thick = 10*length_K_decay

BV.hydrodynamic.update_thickness(thick)

thick_exp = 1.25
layer_min_thick = 5
nlay = int(np.log(1-thick*(1-thick_exp)/layer_min_thick) / np.log(thick_exp))
#nlay = 1


#%% CALIBRATION

BV.calib_dichotomy(ident=None, calib=True, type_river = 'zhstreams', climatic=BV.forcing.recharge,
                    lay_number=nlay, thick=BV.hydrodynamic.thickness, bottom=1000, thick_exp = thick_exp, 
                    first=1, last=100, gap=1, porosity=0.01, sea_level=None, cond_decay = length_K_decay_inv)

#%% MODEL
K_R = 27.104

K_dic = K_R*BV.forcing.recharge
BV.hydrodynamic.update_hyd_cond(K_dic) # m/d
BV.hydrodynamic.update_porosity = 0.01

# Name of model
model_name = "test_visu3D_permanent"
# Launch model
# BV.run_modflow(ident=name_model, sea_level=None, lay_number=nlay, modpath_sim=True,
#                thick_exp = thick_exp, cond_decay = length_K_decay_inv, bottom=1000)

# Launch a model
BV.run_modflow(ident=model_name, modpath_sim=True, calib=False, sink_fill=False, 
                lay_number=nlay, bottom=1000, thick_exp=thick_exp, cond_decay=length_K_decay_inv, 
                verbose=True)
print('Modeling process completed')

# Extract result chronics
BV.chronics_modflow(ident=model_name, mask=False, outlet_type=True, calib_only=False, 
                    first=first, last=last, time_step='monthly')
print('Result chronics extraction completed')

#%% VTK

# from groundwater_flow import vizualisation
# vtk.VTK(BV, name_model)
# visu = vizualisation.Vizualisation(BV, name_model)
# # visu.visual3D(interactive=True, object_list=['grid','watertable', 'pathlines', 'watertable_depth'], view='south-west')
# visu.visual3D(interactive=True, object_list=['watertable_depth'], view='north-east',z_scale = 1)

from groundwater_flow import visualization
vtk.VTK(BV, model_name)
visu = visualization.Visualization(BV, model_name)
visu.visual3D(interactive=True, object_list=['grid','watertable', 'pathlines', 'watertable_depth'], view='north-east',z_scale = 1)

#%% Transient simulation

name_model = "selected_heterogeneous_historic"

K_R = 27.104

K_dic = K_R*BV.forcing.recharge

BV.hydrodynamic.update_hyd_cond(K_dic*30) # m/j en m/M
BV.hydrodynamic.update_porosity = 0.01

BV.forcing.update_recharge_surfex('REA','historic',1960,2019,'M','transient')

BV.run_modflow(ident=name_model, sea_level=None, lay_number=nlay, modpath_sim=False,
               thick_exp = thick_exp, cond_decay = length_K_decay_inv, bottom=1000)



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
#from matplotlib_scalebar.scalebar import ScaleBar
import os
from glob import glob
import geopandas as gpd
from osgeo import gdal
import rasterio
from mpl_toolkits.axes_grid1 import make_axes_locatable

name_model = "dic-zhstreams-27.104-0.001-100"

git_path = "C:/Users/LocalAdmin/Documents/GitHub/HydroModPy/CORE_COMM/"
file_adds.create_folder(out_path+'/_dichotomy/')

geol_s = gpd.read_file(root_path+'GEOLOGY/'+'GEO001M_CART_FR_S_FGEOL_2154_CMYK.shp')
geol_l = gpd.read_file(root_path+'GEOLOGY/'+'GEO001M_CART_FR_L_STRUCT_2154_CMYK.shp')

obs= 'zhstreams'
    
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
    #scalebar = AnchoredSizeBar(ax.transData, 2000, '2 km', 'lower right', 
     #                          pad=0.2, color='white', frameon=False, size_vertical=1,
      #                         fontproperties=fontprop)
    #ax.add_artist(scalebar)

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
 
obs = 'zhstreams'
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

#%% VTK

from groundwater_flow import vizualisation

vtk.VTK(BV, name_model)
visu = vizualisation.Vizualisation(BV, name_model)
# visu.visual3D(interactive=True, object_list=['grid','watertable', 'pathlines', 'watertable_depth'], view='south-west')
visu.visual3D(interactive=None, object_list=['grid','watertable', 'watertable_depth'], view='north-east',z_scale = 1)