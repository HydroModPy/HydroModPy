# -*- coding: utf-8 -*-
"""
Created on Wed Jan 26 10:49:18 2022

@author: ronan
"""

#%% LIBRARIES MODULES

# General
import sys
from os.path import dirname, abspath
DIR = dirname(dirname(dirname(abspath(__file__))))
sys.path.append(DIR)
import numpy as np
import pandas as pd
from osgeo import gdal, osr
import matplotlib.pyplot as plt
import glob
import geopandas as gpd
from shapely.geometry.polygon import LineString, Polygon
from shapely.ops import linemerge, unary_union, polygonize
from datetime import datetime
import os
import re
from matplotlib.dates import YearLocator, MonthLocator, DateFormatter
import scipy.stats as sp
import shapely.geometry as SG
import matplotlib.pylab as pl
import math
from pyproj import Transformer
from mpl_toolkits.axes_grid1 import make_axes_locatable
from matplotlib.colors import Normalize
from matplotlib import cm
import matplotlib as mpl
import rasterio
import fnmatch
import deepdish as dd
import matplotlib.dates as mdates
import flopy
import pickle
import random
from matplotlib.ticker import ScalarFormatter
from matplotlib.ticker import MaxNLocator
import shutil

# Plot
from matplotlib_scalebar.scalebar import ScaleBar
from rasterio.plot import show
from matplotlib.colors import LightSource
# import earthpy.spatial as es
# import earthpy.plot as ep


import flopy.utils.postprocessing as pp

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
               
#%% HYDROMODPY

# Import HydroModPy modules
from os.path import dirname, abspath
DIR = dirname(dirname(dirname(dirname(abspath(__file__)))))
sys.path.append(DIR)

import src
import importlib
importlib.reload(src)

from src import watershed_root
from src.watershed import climatic, driasclimat, driaseau, geographic, geology, hydraulic, \
                          hydrography, hydrometry, intermittency, oceanic, \
                          piezometry, safransurfex, subbasin
from src.modeling import downslope, modflow, modpath, timeseries
from src.display import visualization_watershed, visualization_results, export_vtuvtk
from src.tools import toolbox

fontprop = toolbox.plot_params(8,15,18,20) # small, medium, interm, large

#%% BULK FUNCTIONS

def deficiency_evaporation(dfmonth, ppt_col, etp_col, ppt_etp_col, etr_col, ru_col, de_col):
    calc = pd.DataFrame()
    calc[ppt_etp_col] = (dfmonth[ppt_col]-dfmonth[etp_col]).round(2)
    calc[ru_col] = np.nan
    calc[etp_col] = dfmonth[etp_col]
    calc[ppt_col] = dfmonth[ppt_col]
    
    long = np.array(range(0,len(calc)))
    
    for r in long:
        idx = calc.index[0]
        calc[ru_col][idx] = 125
        if r == len(calc)-1:
            break
        else:
            if (calc[ru_col][r] + calc[ppt_etp_col][r+1]) >= 125:
                calc[ru_col][r+1] = 125      
            if 0 < (calc[ru_col][r] + calc[ppt_etp_col][r+1]) < 125:
                calc[ru_col][r+1] = (calc[ru_col][r]+ 
                                              calc[ppt_etp_col][r+1])
            if (calc[ru_col][r] + calc[ppt_etp_col][r+1]) <= 0:
                calc[ru_col][r+1] = 0
    
    calc[etr_col] = np.nan
    for p in calc[ppt_etp_col]:
        if p > 0:
            idx1 = calc.index[calc[ppt_etp_col] == p]
            calc[etr_col][idx1] = calc[etp_col][idx1]
    
        else:
            idx2 = calc.index[calc[ppt_etp_col] == p]
            calc[etr_col][idx2] = (calc[ppt_col][idx2] + (
                calc[ru_col][idx2]-1) - calc[ru_col][idx2])
    
    calc[de_col] = calc[etp_col] - calc[etr_col]

    for n in long:
        if calc[de_col][n] < 0:
            calc[de_col][n] = 0
            
    calc[de_col] = calc[de_col].round(2)
    
    dfmonth[etr_col] = calc[etr_col]
    dfmonth[de_col] = calc[de_col]
    
    return(dfmonth)

def fmt_xaxes(ax, years_maj, years_min):
    yearsmaj = mdates.YearLocator(years_maj)   # every year
    yearsmin = mdates.YearLocator(years_min)
    # monthsmaj = mdates.MonthLocator(6)  # every month
    # monthsmin = mdates.MonthLocator(3)
    # months_fmt = mdates.DateFormatter('%m') #b = name of month ?
    years_fmt = mdates.DateFormatter('%Y')
    ax.xaxis.set_major_locator(yearsmaj)
    ax.xaxis.set_minor_locator(yearsmin)
    ax.xaxis.set_major_formatter(years_fmt)

def add_subplot_axes(ax,rect,axisbg='w'):
    fig = plt.gcf()
    box = ax.get_position()
    width = box.width
    height = box.height
    inax_position  = ax.transAxes.transform(rect[0:2])
    transFigure = fig.transFigure.inverted()
    infig_position = transFigure.transform(inax_position)
    x = infig_position[0]
    y = infig_position[1]
    width *= rect[2]
    height *= rect[3]  # <= Typo was here
    # subax = fig.add_axes([x,y,width,height],facecolor=facecolor)  # matplotlib 2.0+
    subax = fig.add_axes([x,y,width,height])  # matplotlib 2.0+
    # subax = fig.add_axes([x,y,width,height],axisbg=axisbg)
    x_labelsize = subax.get_xticklabels()[0].get_size()
    y_labelsize = subax.get_yticklabels()[0].get_size()
    x_labelsize *= rect[2]**0.5
    y_labelsize *= rect[3]**0.5
    subax.xaxis.set_tick_params(labelsize=x_labelsize)
    subax.yaxis.set_tick_params(labelsize=y_labelsize)
    return subax

def colorFader(c1,c2,mix=0): #fade (linear interpolate) from color c1 (at mix=0) to c2 (mix=1)
    c1=np.array(mpl.colors.to_rgb(c1))
    c2=np.array(mpl.colors.to_rgb(c2))
    return mpl.colors.to_hex((1-mix)*c1 + mix*c2)
c1='navy' #blue
c2='deepskyblue' #green
n=500
# fig, ax = plt.subplots(figsize=(8, 5))
# for x in range(n+1):
#     ax.axvline(x, color=colorFader(c1,c2,x/n), linewidth=4) 
# plt.show()

import numpy as np
import matplotlib
import matplotlib.pyplot as plt
from mpl_toolkits.axes_grid1 import AxesGrid

class MidpointNormalize(mpl.colors.Normalize):
    def __init__(self, vmin=None, vmax=None, vcenter=None, clip=False):
        self.vcenter = vcenter
        super().__init__(vmin, vmax, clip)

    def __call__(self, value, clip=None):
        # I'm ignoring ed values and all kinds of edge cases to make a
        # simple example...
        # Note also that we must extrapolate beyond vmin/vmax
        x, y = [self.vmin, self.vcenter, self.vmax], [0, 0.5, 1.]
        return np.ma.masked_array(np.interp(value, x, y,
                                            left=-np.inf, right=np.inf))

    def inverse(self, value):
        y, x = [self.vmin, self.vcenter, self.vmax], [0, 0.5, 1]
        return np.interp(value, x, y, left=-np.inf, right=np.inf)

def shiftedColorMap(cmap, start=0, midpoint=0.5, stop=1.0, name='shiftedcmap'):
    '''
    Function to offset the "center" of a colormap. Useful for
    data with a negative min and positive max and you want the
    middle of the colormap's dynamic range to be at zero.

    Input
    -----
      cmap : The matplotlib colormap to be altered
      start : Offset from lowest point in the colormap's range.
          Defaults to 0.0 (no lower offset). Should be between
          0.0 and `midpoint`.
      midpoint : The new center of the colormap. Defaults to 
          0.5 (no shift). Should be between 0.0 and 1.0. In
          general, this should be  1 - vmax / (vmax + abs(vmin))
          For example if your data range from -15.0 to +5.0 and
          you want the center of the colormap at 0.0, `midpoint`
          should be set to  1 - 5/(5 + 15)) or 0.75
      stop : Offset from highest point in the colormap's range.
          Defaults to 1.0 (no upper offset). Should be between
          `midpoint` and 1.0.
    '''
    cdict = {
        'red': [],
        'green': [],
        'blue': [],
        'alpha': []
    }

    # regular index to compute the colors
    reg_index = np.linspace(start, stop, 257)

    # shifted index to match the data
    shift_index = np.hstack([
        np.linspace(0.0, midpoint, 128, endpoint=False), 
        np.linspace(midpoint, 1.0, 129, endpoint=True)
    ])

    for ri, si in zip(reg_index, shift_index):
        r, g, b, a = cmap(ri)

        cdict['red'].append((si, r, r))
        cdict['green'].append((si, g, g))
        cdict['blue'].append((si, b, b))
        cdict['alpha'].append((si, a, a))

    newcmap = matplotlib.colors.LinearSegmentedColormap(name, cdict)
    plt.register_cmap(cmap=newcmap)

    return newcmap

def select_period(df, first, last):
    df = df[(df.index.year>=first) & (df.index.year<=last)]
    return df

def linregress(inx,iny):
    x=np.array(inx, dtype=float)
    y=np.array(iny, dtype=float)
    xmas = np.ma.masked_array(x,mask=np.isnan(y)).compressed()
    ymas = np.ma.masked_array(y,mask=np.isnan(y)).compressed()
    slope, intercept, r_value, p_value, std_err = sp.linregress(xmas,ymas)    
    xf = np.linspace(min(x),max(x),100)
    xf1 = xf.copy()
    xf1 = pd.to_datetime(xf1)
    yf = (slope*xf)+intercept
    center_x = xf.mean()
    center_y = yf.mean()
    lenght_reg = [[xf.min(),xf.max()],[yf.min(),yf.max()]]
    return (center_x,center_y, slope, intercept, r_value, p_value, std_err, lenght_reg)

def sklearn_linregress(inx, iny):
    from sklearn import datasets, linear_model
    from sklearn.metrics import mean_squared_error, r2_score
    regr = linear_model.LinearRegression()
    regr.fit(inx, iny)
    y_pred = regr.predict(inx)
    print("Slope: %.2f" % regr.coef_[0])
    print("Mean squared error: %.2f" % mean_squared_error(iny, y_pred))
    print("Coefficient of determination: %.2f" % r2_score(iny, y_pred))
    print("Intercept: %.2f" % regr.intercept_)
    plt.scatter(inx, iny, color="black")
    plt.plot(inx, y_pred, color="blue", linewidth=3)
    plt.xticks(())
    plt.yticks(())
    plt.show()
    
def line(x, line_point1, line_point2, get_eq=False):
    m = (line_point1[1] - line_point2[1])/(line_point1[0] - line_point2[0])
    b = line_point1[1] - m*line_point1[0]
    if get_eq:
        return m, b
    else:
        return m*x + b

def perpendicular_line(x, random_point, line_point1, line_point2, get_eq=False):
    m, b = line(0, line_point1, line_point2, True)
    m2 = -1/m
    b2 = random_point[1] - m2*random_point[0]
    if get_eq:
        return m2, b2
    else:
        return m2*x + b2
    
def cut_polygon_by_line(polygon, line):
    merged = linemerge([polygon.boundary, line])
    borders = unary_union(merged)
    polygons = polygonize(borders)
    return list(polygons)

def plot(shapely_objects, figure_path='fig.png'):
    boundary = gpd.GeoSeries(shapely_objects)
    boundary.plot(color=['red', 'green'])

#%% ---- CATCHMENT

#%% PATHS

pc = 'tower'

if pc == 'tower':

    git_path = 'D:/Users/abherve/GITHUB/HydroModPy-dev0.1/'
    data_path = 'D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_data/'
    out_path = 'E:/_RONAN/_E_SIMULATIONS/LASSET/'
    # out_path = 'D:/Users/abherve/ONEDRIVE_UNINECHYN/OneDrive - unine.ch/SIMULATIONS/'

pc = 'laptop'

if pc == 'laptop':

    git_path = 'C:/Users/Ronan/GitHub/HydroModPy-dev/'
    data_path = 'C:/Users/Ronan/OneDrive/UNINE/8_Modeling/Lasset/_data/'
    out_path = 'C:/Users/Ronan/Simulations/Lasset/'
    fig_path = 'C:/Users/Ronan/OneDrive/UNINE/8_Modeling/Lasset/_figures_paper/_v0/'
    # out_path = 'D:/Users/abherve/ONEDRIVE_UNINECHYN/OneDrive - unine.ch/SIMULATIONS/'

dem_name = 'BDALTI_09_25m.tif' # EUDTM_Alps_30m_vallon
dem_path = data_path +'_DEM/' + dem_name

subbasin_path = True # generate subbasins from stations or manual points
from_dem = None # True or False if the process start from a given DEM of xyz file
cell_size = None # specify new resolution from a given DEM or None
from_shp = None

watershed_names = [ 'Lasset_25m' ]
# watershed_names = [ 'Lasset' ]

from_xyvs = [ [601020,6193860,100,50,'EPSG:2154'] ]

#%% LOAD

load = True
# load = False

for watershed_name, from_xyv in zip(watershed_names[:], from_xyvs[:]):
        
    print('##### '+watershed_name.upper()+' #####')
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=load,
                                  from_shp=from_shp,
                                  from_dem=from_dem,
                                  from_xyv=from_xyv)
    
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots  
  
    print(BV.geographic.area.round(2))
    print(BV.geographic.slope.round(2))

    # try:
    #     visualization_watershed.watershed_local(dem_path, BV)
    #     visualization_watershed.watershed_dem(BV)
    # except:
    #     pass

# SUBBASIN

if load == False:
    BV.add_intermittency('None','None')
    BV.add_subbasin(data_path+'_coordinates_additional/', sub_snap_dist=50)

# GEOL

# BV.add_geology(data_path+'_mix/', types_obs='GEO1M.shp', fields_obs='CODE_LEG')
# visualization_watershed.watershed_geology(BV)

BV.calibration_folder = os.path.join(out_path, watershed_name, 'results_calibration')

#%% HYDROGRAPHY

hydrography_create = False

if hydrography_create == True:
    
    wbt.verbose = True
    
    # HYDRO
    
    wbt.vector_lines_to_raster(
        data_path+'_hydrography/_newhydro_v2/streams_mix_peren_upv2.shp', 
        data_path+'_hydrography/_newhydro_v2/streams_mix_peren_upv2.tif', 
        field="FID", 
        nodata=True, 
        cell_size=None, 
        base=BV.geographic.watershed_dem)
    
    wbt.vector_lines_to_raster(
        data_path+'_hydrography/_newhydro_v2/streams_mix_inter_upv2.shp', 
        data_path+'_hydrography/_newhydro_v2/streams_mix_inter_upv2.tif', 
        field="FID", 
        nodata=True, 
        cell_size=None, 
        base=BV.geographic.watershed_dem)
    
    wbt.vector_polygons_to_raster(
        data_path+'_hydrography/_newhydro_v2/wetlands_mix_peren_upv2.shp', 
        data_path+'_hydrography/_newhydro_v2/wetlands_mix_peren_upv2.tif', 
        field="fid", 
        nodata=True, 
        cell_size=None, 
        base=BV.geographic.watershed_dem)
    
    wbt.vector_polygons_to_raster(
        data_path+'_hydrography/_newhydro_v2/wetlands_mix_inter_upv2.shp', 
        data_path+'_hydrography/_newhydro_v2/wetlands_mix_inter_upv2.tif', 
        field="osm_id", 
        nodata=True, 
        cell_size=None, 
        base=BV.geographic.watershed_dem)
    
    wbt.raster_to_vector_points(
        data_path+'_hydrography/_newhydro_v2/streams_mix_peren_upv2.tif', 
        data_path+'_hydrography/_newhydro_v2/streams_mix_peren_upv2_pt.shp')
    
    wbt.raster_to_vector_points(
        data_path+'_hydrography/_newhydro_v2/streams_mix_inter_upv2.tif', 
        data_path+'_hydrography/_newhydro_v2/streams_mix_inter_upv2_pt.shp')
    
    wbt.raster_to_vector_points(
        data_path+'_hydrography/_newhydro_v2/wetlands_mix_peren_upv2.tif', 
        data_path+'_hydrography/_newhydro_v2/wetlands_mix_peren_upv2_pt.shp')
    
    wbt.raster_to_vector_points(
        data_path+'_hydrography/_newhydro_v2/wetlands_mix_inter_upv2.tif', 
        data_path+'_hydrography/_newhydro_v2/wetlands_mix_inter_upv2_pt.shp')
    
    wbt.merge_vectors(
        data_path+'_hydrography/_newhydro_v2/streams_mix_peren_upv2_pt.shp;D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_data/_hydrography/_newhydro_v2/wetlands_mix_peren_upv2_pt.shp', 
        data_path+'_hydrography/_newhydro_v2/hydrographic_mix_peren_upv2_pt.shp')
    
    wbt.merge_vectors(
        data_path+'_hydrography/_newhydro_v2/streams_mix_inter_upv2_pt.shp;D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_data/_hydrography/_newhydro_v2/wetlands_mix_inter_upv2_pt.shp', 
        data_path+'_hydrography/_newhydro_v2/hydrographic_mix_inter_upv2_pt.shp')
    
    hydrography_path = data_path + '_hydrography/_newhydro_v2/' # add hydrographic shapefiles
    
    dem_data = imageio.imread(BV.geographic.watershed_dem)
    print(np.sum(dem_data >= 0))
    
    types_obs = ['hydrographic_mix_peren_upv2_pt','hydrographic_mix_inter_upv2_pt']
    # types_obs = ['stream_perennial_wetlands_osm_points']
    fields_obs = ['fid','fid']
    
    for watershed_name in watershed_names[:]:
        BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True)
        for type_obs, field_obs in zip(types_obs, fields_obs):
        
            # print('##### '+watershed_name.upper()+' #####')
                       
            BV.add_hydrography(hydrography_path, types_obs=[type_obs], fields_obs=[field_obs])
            
            try:
                # visualization_watershed.watershed_local(dem_path, BV)
                visualization_watershed.watershed_dem(BV)
            except:
                pass
            
        shp_per = gpd.read_file(stable_folder+'hydrography/'+'hydrographic_mix_peren_upv2_pt_pt.shp')
        shp_int = gpd.read_file(stable_folder+'hydrography/'+'hydrographic_mix_inter_upv2_pt_pt.shp')
            
        print(len(shp_per)/np.sum(dem_data >= 0)*100)
        print(len(shp_int)/np.sum(dem_data >= 0)*100)

#%% DISCHARGE

init_path = data_path + '_Q/'

Qobs_list =[
             'lasset_Q_Day.Cmd.txt',
             'truites_Q_Day.Cmd.txt'
            ]

couleurs = ['navy','darkviolet']
areas = [3.7, 1.2]


fig, axs = plt.subplots(2,1, figsize=(7,6), sharex=True)
axs = axs.ravel()

for i, Qobs_name in enumerate(Qobs_list[:]):
    dfQ = pd.read_csv(init_path+Qobs_name, sep=';', parse_dates=True, index_col='date_temp') # m3/d
        
    zo = 1
    if i == 0:
        zo=2
    
    ax = axs[0]
    ax.plot(dfQ['q']/24/3600, lw=1,
            label=Qobs_name, color=couleurs[i], zorder=zo) # m3/day to m3/seconds
    ax.legend(loc='upper right', frameon=False)
    # ax.set_yscale('log')
    ax.set_ylim(0, 7)
    ax.xaxis.set(minor_locator=mdates.MonthLocator(), major_locator=mdates.YearLocator())
    # ax.set_xlim(pd.to_datetime('2021'), pd.to_datetime('2024'))
    ax.set_ylabel('$Q_{obs}$ [m$^3$/s]')
    # ax.set_ylabel('$Q_{obs}$ [L/s]')
    # ax.grid()
        
    ax = axs[1]
    ax.plot(dfQ['q']/(areas[i]*1e6)*1000, lw=1,
            label=Qobs_name, color=couleurs[i], zorder=zo) # m3/day to mm/day
    ax.legend(loc='lower left', frameon=False)
    ax.set_yscale('log')
    # ax.set_ylim(8e-2, 100)
    ax.xaxis.set(minor_locator=mdates.MonthLocator(), major_locator=mdates.YearLocator())
    # ax.set_xlim(pd.to_datetime('2021'), pd.to_datetime('2024'))
    ax.set_ylabel('$Q_{obs}$ [mm/d]')
    ax.set_xlabel('Date')
    # ax.grid()
    
    plt.tight_layout()

# fig, axs = plt.subplots(1,2, figsize=(9,3),
#                         # sharey=True
#                         )
# axs = axs.ravel()

fig, ax = plt.subplots(1,1, figsize=(5,4),
                        # sharey=True
                        )
# axs = axs.ravel()

for i, Qobs_name in enumerate(Qobs_list[:1]):
    dfQ = pd.read_csv(init_path+Qobs_name, sep=';', parse_dates=True, index_col='date_temp')

    dfQ = select_period(dfQ, 2022, 2022)

    zo = 1
    if i == 0:
        zo=2
        
    # ax = axs[i]
    ax = ax
    
    data_index = dfQ['q']/(areas[i]*1e6)*1000
    plt.plot(data_index)
    plt.yscale('log')

    # data_index = select_period(data_index, 2021,2021)
    # data_index = data_index[(data_index.index>='2016-09') & (data_index.index<='2017-06')]
            
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
    # print(Q10.min())
    # print(Q50)
    # print(Q90.mean())
    # print(data_index.resample('Y').sum())
    Max = data_index.resample('Y').max()
    mean_interan_days = data_index.groupby([data_index.index.month,
                                    data_index.index.day], as_index=True).mean().to_frame()
    std_interan_days = data_index.groupby([data_index.index.month,
                        data_index.index.day], as_index=True).std()
    q10_interan_days = data_index.groupby([data_index.index.month,
                        data_index.index.day], as_index=True).min()
    q90_interan_days = data_index.groupby([data_index.index.month,
                        data_index.index.day], as_index=True).max()
    q50_interan_days = data_index.groupby([data_index.index.month,
                        data_index.index.day], as_index=True).quantile(0.50)
    q25_interan_days = data_index.groupby([data_index.index.month,
                        data_index.index.day], as_index=True).quantile(0.25)
    q75_interan_days = data_index.groupby([data_index.index.month,
                        data_index.index.day], as_index=True).quantile(0.75)
    mean_interan_days['std'] = std_interan_days
    mean_interan_days['q10'] = q10_interan_days
    mean_interan_days['q90'] = q90_interan_days
    mean_interan_days['q50'] = q50_interan_days
    mean_interan_days['q75'] = q75_interan_days
    mean_interan_days['q25'] = q25_interan_days
    mean_interan_days.index.names = ['months','days']
    mean_interan_days = mean_interan_days.reset_index()
    # mean_interan_days.months = mean_interan_days.months.replace(
    #                                     [10,11,12,1,2,3,4,5,6,7,8,9],
    #                                     [1,2,3,4,5,6,7,8,9,10,11,12])
    mean_interan_days = mean_interan_days.sort_values(['months','days'])
    mean_interan_days['counts'] = np.array(range(1,len(mean_interan_days)+1))
    # mean_interan_days.q10 = mean_interan_days.q10.replace(0,0.01)
    
    # fig, ax = plt.subplots(figsize=(4,3))
    # ax.plot(mean_interan_days.counts, mean_interan_days[station+'_mmm'],
    #         lw=1, color='red', label='Mean')
    ax.plot(mean_interan_days.counts, mean_interan_days.q50,
            lw=2,
            # color=couleurs[i],
            color='blue',
            label=Qobs_name)
    yerrmax = mean_interan_days.q90
    yerrmin = mean_interan_days.q10
    # ax.legend('upper right')
    # ax.fill_between(mean_interan_days.counts, yerrmin, yerrmax,
    #                   color='cyan',edgecolor='grey',
    #                   alpha = 0.5, label='10-90th')
    
    # ax.plot(data_index[data_index.index.year==2022], c='k')
    
    ax.fill_between(mean_interan_days.counts, yerrmin, yerrmax,
                      color='grey',edgecolor='grey', lw=0.5,
                      alpha = 0.5, label='10-90th')
    
    ax.grid(alpha=0.2)
    
    # plt.yscale('log')
    # ax.yaxis.set_major_formatter(ScalarFormatter())
    ax.set_xlim(0,366)
    # if i == 0:
    #     ax.set_ylim(-10,20)
    # if i == 1:
    #     ax.set_ylim(0,10)
    # if i == 2:
    #     ax.set_ylim(0,10) 
    # if i == 3:
    #     ax.set_ylim(0,10) 
    # if i == 4:
    #     ax.set_ylim(0,10) 
    # if i == 5:
    #     ax.set_ylim(0,10) 
    # ax.set_ylim(0.01,10)
    ax.tick_params(axis='both', which='major', pad=10)
    x1 = np.linspace(0,366,13)
    squad = ['J','F','M','A','M','J','J','A','S','O','N','D','J']
    ax.set_xticks(x1)
    ax.set_xticklabels(squad, minor=False, rotation='horizontal')
    # if i == 2:
    ax.set_xlabel('Months', labelpad=+10)
    if i ==0:
        ax.set_ylabel('$Q_{obs}$ [mm/d]')
    # ax.set_title('S'+str(i+1))
    # ax.legend(loc='upper right', frameon=False)
    # if i==0:
    #     ax.set_ylim(0,)
    # if i==1:
    #     ax.set_ylim(0,2)
    ax.set_ylim(1e-1,100)
    ax.set_yscale('log')
    
    # ax.set_ylabel(var + ' [mm/d]',labelpad=+10, color=couleurs[i], fontsize=15)
    # ax.set_ylabel(var + ' [°C]',labelpad=+10, color=couleurs[i], fontsize=15)
    # ax.set_title(watershed_name + ' [' + str(first) + ' to ' + str(last) + ']')
    # ax.grid(color='grey', lw=0.5, zorder=0)
    
    # ax.legend(loc='upper left')
    plt.tight_layout()
    
    # fig.savefig('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_figures_paper/_v0/01_fig_locali/'+
    #             'Q_obs'+'.png',
    #             bbox_inches='tight')

#%% REANALYSIS

BV.add_safransurfex(data_path+'_h5_safransurfex/lasset/')

surfex_data = BV.stable_folder + '/climatic/'

dfd_both = pd.DataFrame()

raws = ['REC', 'RUN', 'ETP', 'PPT', 'TAS','SNOW']
variables = ['REC', 'RUN', 'ETP', 'PPT', 'TAS', 'SNOW', 'EFF']

# ppt = pd.read_csv(surfex_data+'_'+'PPT'+'_'+'D'+'.csv', sep=";", index_col=0, parse_dates=True)
# etp = pd.read_csv(surfex_data+'_'+'ETP'+'_'+'D'+'.csv', sep=";", index_col=0, parse_dates=True)
# eff = ppt - etp
# eff = eff.add_prefix('EFF'+'_')

liste = []
for raw in raws :
    dfd = pd.read_csv(surfex_data+'_'+raw+'_'+'D'+'.csv', sep=";", index_col=0, parse_dates=True)
    dfd = dfd.add_prefix(raw+'_')
    liste.append(dfd)
dfd = pd.concat(liste, join='inner', axis=1)
# dfd = pd.concat([dfd,eff], join='inner', axis=1)
dfd = dfd.apply(pd.to_numeric)

for mod in ['REA']:
    for sce in ['historic']:
        dfd['EFF'+'_'+mod+'_'+sce] = dfd['PPT'+'_'+mod+'_'+sce] - dfd['ETP'+'_'+mod+'_'+sce]

dfd = dfd.filter(regex=sce).filter(regex=mod)
dfd = dfd.dropna(axis = 0, how = 'all')
dfd = dfd.dropna(axis = 1, how = 'all')

dfm = dfd.copy() 
mask = dfm.resample("M").count() >= 27
dfm = dfm.resample("M").mean()[mask]

dfm_surf = dfm.copy()
dfm_surf = select_period(dfm_surf, 1960, 2023)
# tas = dfm_surf['TAS_REA_historic']
# import pyet
# dfm_surf['Oudin'] = abs(pyet.oudin(tas, lat=pyet.deg_to_rad(48)))
# dfm_surf["Hargreaves"] = abs(pyet.hargreaves(tas, tmax=tas.max(), tmin=tas.min(), lat=pyet.deg_to_rad(48)))
# dfm_surf["Hamon"] = abs(pyet.temperature.hamon(tas, lat=pyet.deg_to_rad(48)))
# dfm_surf["Macguinness"] = abs(pyet.radiation.mcguinness_bordne(tas, lat=pyet.deg_to_rad(48)))
# deficiency_evaporation(dfm_surf, 'PPT_REA_historic',
#                             'Oudin', 'PPT-ETP',
#                             'ETR', 'RU', 'DE')

dfy = dfd.copy()
mask = dfy.resample("Y").count() >= 364
dfy = dfy.resample("Y").mean()[mask]

rea = dfd[(dfd.index.year>=1960) & (dfd.index.year<=2023)].filter(regex='REA')

def sum_hwlw(dfm):
    hw = dfm.dropna(axis=1, how='all')
    hw = dfm.groupby([(dfm.index.year),(dfm.index.month)]).mean()
    hw = hw.rename_axis(["year", "month"])
    hw = hw.query("month == "+"["+'10,11,12,1,2,3'+"]")
    hw = hw.groupby('year').mean()
    hw.index =  pd.to_datetime(hw.index, format='%Y')
    hw[hw==0] = np.nan
    lw = dfm.dropna(axis=1, how='all')
    lw = dfm.groupby([(dfm.index.year),(dfm.index.month)]).mean()
    lw = lw.rename_axis(["year", "month"])
    lw = lw.query("month == "+"["+'4,5,6,7,8,9'+"]")
    lw = lw.groupby('year').mean()
    lw.index =  pd.to_datetime(lw.index, format='%Y')
    lw[lw==0] = np.nan
    return hw, lw
hw, lw = sum_hwlw(dfm)

def sum_wy(dfm):
    wy = dfm.copy()
    wy = wy.dropna(axis=1, how='all')
    wy['wy_y'] = np.where(wy.index.month < 10, wy.index.year, wy.index.year + 1)
    wy['wy_m'] = np.where(wy.index.month < 10, wy.index.month+3, wy.index.month-9)
    wy['wy_m'] = wy['wy_m'].apply(lambda x: '{0:0>2}'.format(x))
    wy['wy_d'] = wy.index.day
    d = pd.to_datetime(wy['wy_y'].astype(str)+wy['wy_m']+wy['wy_d'].astype(str), format='%Y%M%d')
    wy['date'] = wy.index
    wy.index = d
    wy = wy.drop(['wy_y','wy_m','wy_d'], axis=1)
    wy = wy.groupby([(wy.index.year),(wy.index.month)]).mean()
    wy = wy.rename_axis(["year", "month"])
    wy = wy.iloc[:-1]
    wy = wy.groupby('year').mean()
    wy.index =  pd.to_datetime(wy.index, format='%Y')
    wy[wy==0] = np.nan
    return wy
wy = sum_wy(dfm)

# ISBA HYDRO NORMALIZE

init_path = data_path + '_Q/'

Qobs_list =[
             'lasset_Q_Day.Cmd.txt'
            ]

areas = [3.7]

for i, Qobs_name in enumerate(Qobs_list[:]):
    dfQ = pd.read_csv(init_path+Qobs_name, sep=';', parse_dates=True, index_col='date_temp') # m3/d
    dfQ = dfQ['q']/(areas[i]*1e6)

dfFTP = pd.DataFrame()
dfFTP['OBSER'] = dfQ
dfFTP['DRAIN'] = dfd['REC_REA_historic']/1000
dfFTP['RUNOF'] = dfd['RUN_REA_historic']/1000

dfFTP = dfFTP.query("index >= '2021-08' and index <= '2023-07'")
# dfFTP = dfFTP.query("index >= '2023-01' and index <= '2023-12'")

# f = dfSIM2['OBSER'].mean() / (dfSIM2['DRAIN']+dfSIM2['RUNOF']+dfSIM2['ECSNOW']).mean()
# f = dfSIM2['OBSER'].mean() / dfSIM2['PPT'].mean()
# norm_factor = dfFTP['OBSER'].mean() / (dfFTP['DRAIN']+dfFTP['RUNOF']).mean()
norm_factor = dfFTP['OBSER'].sum() / (dfFTP['DRAIN']+dfFTP['RUNOF']).sum()
print(norm_factor)

dfFTP['INPUT'] = (dfFTP['DRAIN']+dfFTP['RUNOF']) * norm_factor

fig, ax = plt.subplots(1,1, figsize=(9,3))
ax.plot(dfFTP['DRAIN']+dfFTP['RUNOF'], label='R + r', c='darkorange')
ax.plot(dfFTP['DRAIN'], label='R', c='forestgreen')
ax.plot(dfFTP['OBSER'], label='Q', c='k')
ax.plot(dfFTP['INPUT'], label='INPUT', c='red')
ax.legend()
ax.set_yscale('log')
import matplotlib.dates as mdates
years_maj = mdates.YearLocator()   # every year
months_maj = mdates.MonthLocator()  # every x month
ax.xaxis.set_major_locator(years_maj)
ax.xaxis.set_minor_locator(months_maj)

fig, ax = plt.subplots(1,1, figsize=(4,4))
ax.scatter(dfFTP['OBSER'], dfFTP['INPUT'], lw=0, color='k')
ax.set_xscale('log')
ax.set_yscale('log')
ax.set_xlim(1e-4,1)
ax.set_ylim(1e-4,1)

isba = select_period(dfd,2020,2024)

rea_facnorm_isba = norm_factor
rea_recharge_isba = (dfd['REC_REA_historic']/1000)*norm_factor
rea_runoff_isba = (dfd['RUN_REA_historic']/1000)*norm_factor

#%% ---- PROJECTIONS

#%% EXTRACT DRIAS

extract_drias = False

if extract_drias == True :

    # DRIAS EAU - NETCDF
    
    drias_eau_datapath = data_path + '_pyrenees_projections/PYRENEES/results_stable/driaseau/'
    drias_eau_outpath = stable_folder + 'driaseau/'
    # if not os.path.exists(drias_eau_outpath):
    BV.add_driaseau(drias_eau_datapath,
                    list_models=['all'],
                    list_vars=['all']) # 'all'
    
    # DRIAS EAU - CSV
    
    data_folder = stable_folder+'/driaseau/'
    
    df = pd.DataFrame()
    df.index = pd.date_range(start="1950-01-01",end="2100-12-31")
    
    list_models = ['Model_01','Model_02','Model_03','Model_04','Model_05','Model_06','Model_07','Model_08','Model_09','Model_10','Model_11','Model_12']
    
    list_of_paths = []
    for i in list_models:
        list_of_paths_model = glob.glob(os.path.join(data_folder+'/', '*.nc'))
        list_of_paths.extend(list_of_paths_model)
    
    driaseau.driaseau_extract_values(data_folder, list_of_paths, df)

    # DRIAS CLIMAT NETCDF
    
    drias_clim_datapath = data_path + '_pyrenees_projections/PYRENEES/results_stable/driasclimat/'
    drias_clim_outpath = stable_folder + 'driasclimat/'
    # if not os.path.exists(drias_clim_outpath):
    BV.add_driasclimat(drias_clim_datapath,
                    list_models=['all'],
                    list_vars=['prtotAdjust',
                               'prsnAdjust',
                               'tasAdjust',
                               'tasmaxAdjust',
                               'tasminAdjust']) # 'all'
    
    # DRIAS CLIMAT CSV
    
    data_folder = stable_folder+'/driasclimat/'
    
    df = pd.DataFrame()
    df.index = pd.date_range(start="1950-01-01",end="2100-12-31")
    
    list_models = ['Model_01','Model_02','Model_03','Model_04','Model_05','Model_06','Model_07','Model_08','Model_09','Model_10','Model_11','Model_12']
    
    list_of_paths = []
    for i in list_models:
        list_of_paths_model = glob.glob(os.path.join(data_folder+'/'+i+'/', '*.nc'))
        # print(list_of_paths_model)
        list_of_paths.extend(list_of_paths_model)
    
    driasclimat.driasclimat_extract_values(data_folder, list_of_paths, df)

#%% COMPILE DRIAS

BV.add_climatic()

compile_drias = False

if compile_drias == True :

    # DRIAS EAU MIX DATA
    
    num_list = ['Model_01',
                'Model_02',
                'Model_03',
                'Model_04',
                'Model_05',
                'Model_06',
                'Model_07',
                'Model_08',
                'Model_09',
                'Model_10',
                'Model_11',
                'Model_12']
    
    mod_list = ['MPI-CCL',
                'ECE-RCA',
                'ECE-RAC',
                'IPS-RCA',
                'CNR-RAC',
                'NOR-R15',
                'CNR-ALA',
                'NOR-HIR',
                'HAD-CCL',
                'IPS-WRF',
                'HAD-REG',
                'MPI-R09']
    
    mod_dict = dict(zip(mod_list, num_list))
    
    # mod_list = ['ACC1','BCC1','BNU1','CAN1','CAN2','CAN3','CAN4','CAN5',
    #             'CNR1','CSI1','IPS1','MIR1','MIR2','MIR3','NOR1']
    
    # mod_list = ['IPS1','NOR1','CAN3','CNR-ALA','ECE-RCA','MPI-CCL']
    # mod_list = ['IPS1','CNR-ALA','ECE-RCA','MPI-CCL']
    # mod_list = ['CNR-ALA']
    sce_list = ['RCP26','RCP45','RCP85']
    col_list = ['dodgerblue','darkorange','red']
    dict_scecol = dict(zip(sce_list, col_list))
    
    all_proj = pd.DataFrame()
    all_proj.index = pd.date_range(start='01/01/1975', end='31/12/2099', freq='D')
        
    for mod in mod_list:
        
            print(mod)
            
            if len(mod.split('-')) == 2:
                GCM = mod.split('-')[0]
                RCM = mod.split('-')[1]
                BV.climatic.update_recharge_explore2(path_file = BV.stable_folder + '/driaseau/_ALL_D.csv',
                                                     gcm_mod = GCM, rcm_mod = RCM, sce_mod = 'historic',
                                                     first_year = 1975, last_year = 2023, sim_state='transient')
                BV.climatic.update_runoff_explore2(path_file = BV.stable_folder + '/driaseau/_ALL_D.csv',
                                                     gcm_mod = GCM, rcm_mod = RCM, sce_mod = 'historic',
                                                     first_year = 1975, last_year = 2023, sim_state='transient')
                
            R_mod = BV.climatic.recharge.resample('D').mean()
            r_mod = BV.climatic.runoff.resample('D').mean()
        
            R_rea = select_period(rea_recharge_isba, 1975, 2023)
            r_rea = select_period(rea_runoff_isba, 1975, 2023)
            
            # R_rea = select_period(rea_recharge_sim2, 1975, 2023)
            # r_rea = select_period(rea_runoff_sim2, 1975, 2023)
            
            Fnorm = ( np.nanmean(R_rea) + np.nanmean(r_rea) )  / ( np.nanmean(R_mod) + np.nanmean(r_mod) )
            print(Fnorm)
            
            R_mod_norm = (Fnorm * R_mod)
            R_mod_norm = R_mod_norm[(R_mod_norm.index.strftime("%Y-%m")<='2005-07')]
            r_mod_norm = Fnorm * r_mod
            r_mod_norm = r_mod_norm[(r_mod_norm.index.strftime("%Y-%m")<='2005-07')]
            
            # all_proj[watershed_name+'_'+'REC'+'_'+mod+'_'+'historic'] = R_mod_norm
            # all_proj[watershed_name+'_'+'RUN'+'_'+mod+'_'+'historic'] = r_mod_norm
        
            for sce in sce_list:
                
                try:    
                    if len(mod.split('-')) == 2:
                        GCM = mod.split('-')[0]
                        RCM = mod.split('-')[1]
                        BV.climatic.update_recharge_explore2(path_file = BV.stable_folder + '/driaseau/_ALL_D.csv',
                                                             gcm_mod = GCM, rcm_mod = RCM, sce_mod = sce,
                                                             first_year = 1975, last_year = 2100, sim_state='transient')
                        BV.climatic.update_runoff_explore2(path_file = BV.stable_folder + '/driaseau/_ALL_D.csv',
                                                       gcm_mod = GCM, rcm_mod = RCM, sce_mod = sce,
                                                       first_year = 1975, last_year = 2100, sim_state='transient')
                    
                    R_proj_norm = BV.climatic.recharge * Fnorm
                    r_proj_norm = BV.climatic.runoff * Fnorm
                    
                    all_proj['REC'+'_'+mod+'_'+sce] = pd.concat((R_proj_norm, R_mod_norm), axis=1).mean(axis=1)
                    all_proj['RUN'+'_'+mod+'_'+sce] = pd.concat((r_proj_norm, r_mod_norm), axis=1).mean(axis=1)
                    print('     '+sce)
                except:
                    pass
                
            all_proj['REC'+'_'+'REA'+'_'+'historic'] = R_rea
            all_proj['RUN'+'_'+'REA'+'_'+'historic'] = r_rea    
            
    # mod_list = ['IPS1','NOR1','CAN3','CNR-ALA','ECE-RCA','MPI-CCL']
    # sce_list = ['RCP2.6','RCP8.5']
    # col_list = ['blue','red']
    dict_scecol = dict(zip(sce_list, col_list))
        
    for mod in mod_list:
        
            fig, ax = plt.subplots(1,1, figsize=(9,3))
        
            for sce in sce_list:
                
                try:
    
                    c = dict_scecol[sce]
                    
                    toplot = all_proj['REC'+'_'+mod+'_'+sce].resample('Y').sum()*1000
                    ax.plot(toplot, color=c)
                    ax.plot(select_period(toplot,1975,2005), color='k')
                    
                    ax.set_title(watershed_name+'_'+mod+'-'+mod_dict[mod])
                    # ax.set_yscale('log')
                
                except:
                    pass
                
    all_proj.to_csv(BV.stable_folder + '/driaseau/' + 'all_proj_driaseau.csv', sep=';')
    
#%% PLOTS DRIAS

plot_drias = False

if plot_drias == True :
    
    # EAU PLOT ALL MODELS
    
    all_proj = pd.read_csv(BV.stable_folder + '/driaseau/' + 'all_proj_driaseau.csv', sep=';', index_col=0, parse_dates=True)
    
    num_list = ['Model_01',
                'Model_02',
                'Model_03',
                # 'Model_04',
                'Model_05',
                # 'Model_06',
                'Model_07',
                # 'Model_08',
                # 'Model_09',
                # 'Model_10',
                # 'Model_11',
                'Model_12']
    mod_keep = 'MPI-CCL|ECE-RCA|ECE-RAC|CNR-RAC|CNR-ALA|MPI-R09'
    mod_list = ['MPI-CCL',
                'ECE-RCA',
                'ECE-RAC',
                # 'IPS-RCA',
                'CNR-RAC',
                # 'NOR-R15',
                'CNR-ALA',
                # 'NOR-HIR',
                # 'HAD-CCL',
                # 'IPS-WRF',
                # 'HAD-REG',
                'MPI-R09']
    # n = 8
    n = 6
    colors = pl.cm.jet(np.linspace(0,1,n))
    
    sce_list = ['RCP26','RCP45','RCP85']
    
    for sce in sce_list: 
        
        fig, ax = plt.subplots(1,1, figsize=(6,3))
    
        for cp, mod in enumerate(mod_list):
    
            # d = select_period(df, per[0], per[1])
            
            # if typ_climate == 'DRIAS' :
            d = all_proj.copy()
            d = d.filter(regex=sce).filter(regex=mod).filter(regex='REC')
            d = d.resample('Y').mean() * 1000 * 365
    
            d = d.rolling(window=30).mean()
            
            ax.plot(d, c=colors[cp], lw=2, label=mod)
            # ax.legend(loc='lower left', frameon=False)
            ax.legend(bbox_to_anchor=(1.25, 1),frameon=False)
            ax.set_title(watershed_name+'  '+sce)
            # ax.set_ylim(100, 300)
            
            yearsmaj = mdates.YearLocator(20)   # every year
            monthsmaj = mdates.MonthLocator(12)  # every month
            years_fmt = mdates.DateFormatter('%Y')
            ax.xaxis.set_major_locator(yearsmaj)
            ax.xaxis.set_minor_locator(monthsmaj)
            ax.xaxis.set_major_formatter(years_fmt)
        
            # ax.set_yscale('log')
            
            # fig.savefig(fig_path + watershed_name +
            #             '_evolution_' + str(mod_list[0]) + '.png', dpi=300, bbox_inches='tight')
            
            ax.set_xlim(pd.to_datetime('2000'), pd.to_datetime('2100'))
    
    # EAU PLOT MEDIAN MODELS
    
    all_proj = pd.read_csv(BV.stable_folder + '/driaseau/' + 'all_proj_driaseau.csv', sep=';', index_col=0, parse_dates=True)
    
    # Dispo for 3
    num_list = ['Model_01',
                'Model_02',
                'Model_03',
                # 'Model_04',
                'Model_05',
                # 'Model_06',
                'Model_07',
                # 'Model_08',
                # 'Model_09',
                # 'Model_10',
                # 'Model_11',
                'Model_12']
    mod_keep = 'MPI-CCL|ECE-RCA|ECE-RAC|CNR-RAC|CNR-ALA|MPI-R09'
    mod_list = ['MPI-CCL',
                'ECE-RCA',
                'ECE-RAC',
                # 'IPS-RCA',
                'CNR-RAC',
                # 'NOR-R15',
                'CNR-ALA',
                # 'NOR-HIR',
                # 'HAD-CCL',
                # 'IPS-WRF',
                # 'HAD-REG',
                'MPI-R09']
    
    sce_list = ['RCP26','RCP45','RCP85']
    col_list = ['dodgerblue','darkorange','red']
    dict_scecol = dict(zip(sce_list, col_list))
    
    fig2, ax2 = plt.subplots(1,1, figsize=(6,3))
    
    for sce in sce_list: 
        print(sce)
        
        fig, ax = plt.subplots(1,1, figsize=(6,3))
    
        # for cp, mod in enumerate(mod_list):
    
        # d = select_period(df, per[0], per[1])
        
        # if typ_climate == 'DRIAS' :
        d = all_proj.copy()
        d = d.filter(regex=mod_keep)
        var = 'REC'
        d = d.filter(regex=var).filter(regex=sce)
        
        dmean = d.mean(skipna=True, axis=1)
        dmean = dmean.resample('Y').mean() * 1000 * 365
        dmean = dmean.rolling(window=30).mean()
        
        # cols  = [col for col in d.columns if d[col].dtype == 'float64']
        
        # d25 = d[cols].astype(float).quantile(0.25, axis = 1)
        # d25 = d25.resample('Y').mean() * 1000 * 365
        # d25 = d25.rolling(window=30).mean()
        
        # d50 = d[cols].astype(float).quantile(0.5, axis = 1)
        # d50 = d50.resample('Y').mean() * 1000 * 365
        # d50 = d50.rolling(window=30).mean()
        
        # d75 = d[cols].astype(float).quantile(0.75, axis = 1)
        # d75 = d75.resample('Y').mean() * 1000 * 365
        # d75 = d75.rolling(window=30).mean()
        
        ax.plot(dmean, c=dict_scecol[sce], lw=3, label=mod)
        # ax.plot(d25, c=dict_scecol[sce], lw=1, label=mod)
        # ax.plot(d50, c=dict_scecol[sce], lw=2, label=mod)
        # ax.plot(d75, c=dict_scecol[sce], lw=1, label=mod)
        
        # ax.legend(bbox_to_anchor=(1.25, 1),frameon=False)
        ax.set_title(var+' - '+sce)
        
        yearsmaj = mdates.YearLocator(20)   # every year
        monthsmaj = mdates.MonthLocator(12)  # every month
        years_fmt = mdates.DateFormatter('%Y')
        ax.xaxis.set_major_locator(yearsmaj)
        ax.xaxis.set_minor_locator(monthsmaj)
        ax.xaxis.set_major_formatter(years_fmt)
    
        # ax.set_yscale('log')
        
        # fig.savefig(fig_path + watershed_name +
        #             '_evolution_' + str(mod_list[0]) + '.png', dpi=300, bbox_inches='tight')
        
        ax.set_xlim(pd.to_datetime('2000'), pd.to_datetime('2100'))
    
        ax2.plot(select_period(d.mean(skipna=True, axis=1),2020,2024), c=dict_scecol[sce], lw=1, label=sce)
    # ax2.plot(select_period(rea_recharge_sim2,2020,2024), c='grey', label='sim2')
    ax2.plot(select_period(rea_recharge_isba,2020,2024), c='k', label='isba')
    # ax2.plot(select_period(rea_recharge_sim2,2020,2024), c='grey', label='sim2')
    ax2.set_yscale('log')
    ax2.legend()
    
    # PLOT ALL MODELS
    
    all_proj = pd.read_csv(BV.stable_folder + '/driasclimat/' + '_ALL_D.csv', sep=';', index_col=0, parse_dates=True) 
    
    all_proj2 =  pd.read_csv(BV.stable_folder + '/driaseau/' + '_ALL_D.csv', sep=';', index_col=0, parse_dates=True)
    
    # For 3
    num_list = ['Model_01',
                'Model_02',
                'Model_03',
                # 'Model_04',
                'Model_05',
                # 'Model_06',
                'Model_07',
                # 'Model_08',
                # 'Model_09',
                # 'Model_10',
                # 'Model_11',
                'Model_12']
    mod_keep = 'MPI-CCL|ECE-RCA|ECE-RAC|CNR-RAC|CNR-ALA|MPI-R09'
    mod_list = ['MPI-CCL',
                'ECE-RCA',
                'ECE-RAC',
                # 'IPS-RCA',
                'CNR-RAC',
                # 'NOR-R15',
                'CNR-ALA',
                # 'NOR-HIR',
                # 'HAD-CCL',
                # 'IPS-WRF',
                # 'HAD-REG',
                'MPI-R09']
    
    mod_dict = dict(zip(mod_list, num_list))
    
    # mod_list = ['ACC1','BCC1','BNU1','CAN1','CAN2','CAN3','CAN4','CAN5',
    #             'CNR1','CSI1','IPS1','MIR1','MIR2','MIR3','NOR1']
    
    # mod_list = ['IPS1','NOR1','CAN3','CNR-ALA','ECE-RCA','MPI-CCL']
    # mod_list = ['IPS1','CNR-ALA','ECE-RCA','MPI-CCL']
    # mod_list = ['CNR-ALA']
    
    sce_list = ['RCP26','RCP45','RCP85']
    col_list = ['dodgerblue','darkorange','red']
    dict_scecol = dict(zip(sce_list, col_list))
    
    # var_list = ['PPTT','SNOW','TASM','TASX','TASN','HUSS','WIND','RAYI','RAYV','ETPF','ETPH',
    #             'DRAINC','EVAPC','RUNOFFC','SWE','SWI']
    
    var_list = ['PPTT','SNOW','TASM',
                'REC','ETP','RUN','SWE']
    
    var_list = ['REC']
    
    for var in var_list[:]:
        
        print(var)
        
        for sce in sce_list:
            
        
            print('    '+sce)
        
            for mod in mod_list: 
                
                fig, ax = plt.subplots(1,1, figsize=(6,3))
    
                print('        '+mod)
                
                if var in ['PPTT','SNOW','TASM']:
                    d = all_proj.copy()
                if var in ['REC','ETP','RUN','SWE']:
                    d = all_proj2.copy()
                    
                d = d.filter(regex=var).filter(regex=sce).filter(regex=mod)
                
                dmean = d.mean(skipna=True, axis=1)
                dmean = dmean.resample('Y').mean() #* 365
                dmean = dmean.rolling(window=30).mean()
                
                # cols  = [col for col in d.columns if d[col].dtype == 'float64']
                
                # d25 = d[cols].astype(float).quantile(0.25, axis = 1)
                # d25 = d25.resample('Y').mean() * 1000 * 365
                # d25 = d25.rolling(window=30).mean()
                
                # d50 = d[cols].astype(float).quantile(0.5, axis = 1)
                # d50 = d50.resample('Y').mean() * 1000 * 365
                # d50 = d50.rolling(window=30).mean()
                
                # d75 = d[cols].astype(float).quantile(0.75, axis = 1)
                # d75 = d75.resample('Y').mean() * 1000 * 365
                # d75 = d75.rolling(window=30).mean()
                
                ax.plot(dmean, c=dict_scecol[sce], lw=3, label=mod)
                # ax.plot(d25, c=dict_scecol[sce], lw=1, label=mod)
                # ax.plot(d50, c=dict_scecol[sce], lw=2, label=mod)
                # ax.plot(d75, c=dict_scecol[sce], lw=1, label=mod)
                
                # ax.legend(bbox_to_anchor=(1.25, 1),frameon=False)
                ax.set_title(sce+' - '+var+' - '+mod)
                
                yearsmaj = mdates.YearLocator(20)   # every year
                monthsmaj = mdates.MonthLocator(12)  # every month
                years_fmt = mdates.DateFormatter('%Y')
                ax.xaxis.set_major_locator(yearsmaj)
                ax.xaxis.set_minor_locator(monthsmaj)
                ax.xaxis.set_major_formatter(years_fmt)
            
                # ax.set_yscale('log')
                
                # fig.savefig(fig_path + watershed_name +
                #             '_evolution_' + str(mod_list[0]) + '.png', dpi=300, bbox_inches='tight')
                
                ax.set_xlim(pd.to_datetime('2000'), pd.to_datetime('2100'))
    
    # CLIMAT PLOT MEDIAN MODELS
    
    num_list = ['Model_01',
                'Model_02',
                'Model_03',
                # 'Model_04',
                'Model_05',
                # 'Model_06',
                'Model_07',
                # 'Model_08',
                # 'Model_09',
                # 'Model_10',
                # 'Model_11',
                'Model_12']
    mod_keep = 'MPI-CCL|ECE-RCA|ECE-RAC|CNR-RAC|CNR-ALA|MPI-R09'
    mod_list = ['MPI-CCL',
                'ECE-RCA',
                'ECE-RAC',
                # 'IPS-RCA',
                'CNR-RAC',
                # 'NOR-R15',
                'CNR-ALA',
                # 'NOR-HIR',
                # 'HAD-CCL',
                # 'IPS-WRF',
                # 'HAD-REG',
                'MPI-R09']
    
    mod_dict = dict(zip(mod_list, num_list))
    
    # mod_list = ['ACC1','BCC1','BNU1','CAN1','CAN2','CAN3','CAN4','CAN5',
    #             'CNR1','CSI1','IPS1','MIR1','MIR2','MIR3','NOR1']
    
    # mod_list = ['IPS1','NOR1','CAN3','CNR-ALA','ECE-RCA','MPI-CCL']
    # mod_list = ['IPS1','CNR-ALA','ECE-RCA','MPI-CCL']
    # mod_list = ['CNR-ALA']
    
    sce_list = ['RCP26','RCP45','RCP85']
    col_list = ['dodgerblue','darkorange','red']
    dict_scecol = dict(zip(sce_list, col_list))
    
    # var_list = ['PPTT','SNOW','TASM','TASX','TASN','HUSS','WIND','RAYI','RAYV','ETPF','ETPH',
    #             'DRAINC','EVAPC','RUNOFFC','SWE','SWI']
    
    var_list = ['PPTT','SNOW','TASM',
                'REC','ETP','RUN','SWE']
    
    var_list = ['PPTT']
    
    for var in var_list[:]:
        
        print(var)
        
        for sce in sce_list:
            
            fig, ax = plt.subplots(1,1, figsize=(6,3))
        
            print('    '+sce)
        
            # for mod in mod_list: 
                    
            #     print('        '+mod)
                
            if var in ['PPTT','SNOW','TASM']:
                d = all_proj.copy()
            if var in ['REC','ETP','RUN','SWE']:
                d = all_proj2.copy()
                
            d = d.filter(regex=var).filter(regex=sce).filter(regex=mod_keep)
            
            dmean = d.mean(skipna=True, axis=1)
            dmean = dmean.resample('Y').mean() #* 365
            dmean = dmean.rolling(window=30).mean()
            
            # cols  = [col for col in d.columns if d[col].dtype == 'float64']
            
            # d25 = d[cols].astype(float).quantile(0.25, axis = 1)
            # d25 = d25.resample('Y').mean() * 1000 * 365
            # d25 = d25.rolling(window=30).mean()
            
            # d50 = d[cols].astype(float).quantile(0.5, axis = 1)
            # d50 = d50.resample('Y').mean() * 1000 * 365
            # d50 = d50.rolling(window=30).mean()
            
            # d75 = d[cols].astype(float).quantile(0.75, axis = 1)
            # d75 = d75.resample('Y').mean() * 1000 * 365
            # d75 = d75.rolling(window=30).mean()
            
            ax.plot(dmean, c=dict_scecol[sce], lw=3, label=mod)
            # ax.plot(d25, c=dict_scecol[sce], lw=1, label=mod)
            # ax.plot(d50, c=dict_scecol[sce], lw=2, label=mod)
            # ax.plot(d75, c=dict_scecol[sce], lw=1, label=mod)
            
            # ax.legend(bbox_to_anchor=(1.25, 1),frameon=False)
            ax.set_title(sce+' - '+var)
            
            yearsmaj = mdates.YearLocator(20)   # every year
            monthsmaj = mdates.MonthLocator(12)  # every month
            years_fmt = mdates.DateFormatter('%Y')
            ax.xaxis.set_major_locator(yearsmaj)
            ax.xaxis.set_minor_locator(monthsmaj)
            ax.xaxis.set_major_formatter(years_fmt)
        
            # ax.set_yscale('log')
            
            # fig.savefig(fig_path + watershed_name +
            #             '_evolution_' + str(mod_list[0]) + '.png', dpi=300, bbox_inches='tight')
            
            ax.set_xlim(pd.to_datetime('2000'), pd.to_datetime('2100'))

#%% TABLE DRIAS

table_drias = False

if table_drias == True :
    
    if 'all_proj_clim' not in globals():
        all_proj_clim = pd.read_csv(BV.stable_folder + '/driasclimat/' + '_ALL_D.csv', sep=';', index_col=0, parse_dates=True)
        all_proj_eau =  pd.read_csv(BV.stable_folder + '/driaseau/' + '_ALL_D.csv', sep=';', index_col=0, parse_dates=True)
    
    sce_list = ['historic','RCP26','RCP45','RCP85']
    mod_list = ['MPI-CCL',
                'ECE-RCA',
                'ECE-RAC',
                'CNR-RAC',
                'CNR-ALA',
                'MPI-R09']
    mod_keep = 'MPI-CCL|ECE-RCA|ECE-RAC|CNR-RAC|CNR-ALA|MPI-R09'
    mod_list_ppt = ['MPI-CCL',
                    'ECE-RCA',
                    'MPI-R09']
    mod_keep_pptt = 'MPI-CCL|ECE-RCA|MPI-R09'
    
    sce_list = ['historic','RCP26','RCP45','RCP85']
    col_list = ['dimgrey','dodgerblue','orange','red']
    col_list_b = ['k','navy','darkorange','darkred']
    dict_c = dict(zip(sce_list, col_list))
    dict_c_b = dict(zip(sce_list, col_list_b))
    
    # sce_list = ['historic','RCP85']
    # col_list = ['dimgrey','red']
    # col_list_b = ['k','darkred']
    # dict_c = dict(zip(sce_list, col_list))
    # dict_c_b = dict(zip(sce_list, col_list_b))
    
    df_delta = pd.DataFrame(index=mod_list)
    
    # for var in  [
    #             # 'TASM',
    #             'PPTT',
    #             # 'SNOW',
    #             # 'PLIQ',
    #             # 'SWE',
    #             # 'SNOWPROP',
    #               # 'PE',
    #                 # 'ETP',
    #                 # 'RUN',
    #                 # 'REC',
    #                # 'SWI',
    #                 # 'RECRUN'
    #              ]:
    
    for var in  [
                'TASM',
                'PPTT',
                'SNOW',
                'PLIQ',
                'SWE',
                'SNOWPROP',
                    'PE',
                    'ETP',
                    'RUN',
                    'REC',
                    'SWI',
                    'RECRUN'
                 ]:    
    
        
        all_proj_mix = pd.merge(all_proj_clim, all_proj_eau, how='inner', left_index=True, right_index=True)
        
        if (var == 'PPTT') or (var == 'SNOWPROP') or (var == 'PLIQ') or (var == 'PE'):
            mod_list_good = mod_list_ppt
            mod_keep_good = mod_keep_pptt
        else:
            mod_list_good = mod_list
            mod_keep_good = mod_keep
            
        all_proj_mix = all_proj_mix.filter(regex=mod_keep_good)
        
        for mod in mod_list_good:
            for sce in sce_list:
                if var == 'PPTT':
                    all_proj_mix[var+'_'+mod+'_'+sce] = all_proj_mix[var+'_'+mod+'_'+sce]*3600*24
                if var == 'SNOW':
                    all_proj_mix[var+'_'+mod+'_'+sce] = all_proj_mix[var+'_'+mod+'_'+sce]*3600*24
                if var == 'SNOWPROP':
                    all_proj_mix[var+'_'+mod+'_'+sce] = (all_proj_mix['SNOW'+'_'+mod+'_'+sce]*3600*24) / (all_proj_mix['PPTT'+'_'+mod+'_'+sce]*3600*24)
                if var == 'PLIQ':
                    all_proj_mix[var+'_'+mod+'_'+sce] = (all_proj_mix['PPTT'+'_'+mod+'_'+sce]*3600*24) - (all_proj_mix['SNOW'+'_'+mod+'_'+sce]*3600*24)
                if var == 'PE':
                    all_proj_mix[var+'_'+mod+'_'+sce] = (all_proj_mix['PPTT'+'_'+mod+'_'+sce]*3600*24) - (all_proj_mix['ETP'+'_'+mod+'_'+sce])
                if var == 'RECRUN':
                    all_proj_mix[var+'_'+mod+'_'+sce] = (all_proj_mix['REC'+'_'+mod+'_'+sce]) + (all_proj_mix['RUN'+'_'+mod+'_'+sce])
    
        # fig, ax = plt.subplots(1,1, figsize=(10,4))
            
            # for sce in sce_list:
        for mod in mod_list_good:
            for sce in sce_list:     
                # df = pd.DataFrame()
                dproj = all_proj_mix.copy()
                
                # if var == 'ETP':
                    # var = 'ETP_'
                
                if (var == 'PPTT') or (var == 'SNOWPROP') or (var == 'PLIQ') or (var == 'PE'):
                    dproj = dproj.filter(regex=mod_keep_good).filter(regex=var)
                else:
                    dproj = dproj.filter(regex=mod_keep_good).filter(regex=var)
            
                # print(var, sce, dproj[var+'_'+mod+'_'+sce].mean())
                # print('PPTT', sce, dproj['PPTT'+'_'+mod+'_'+sce].mean())
            
                d_hist = dproj.filter(regex=var).filter(regex='historic')
                d_hist = select_period(d_hist, 1975, 2004)
                
                d_tot = dproj.filter(regex=var).filter(regex=sce)
                d_tot = select_period(d_tot, 1975, 2100)
                
                d_fut = dproj.filter(regex=var).filter(regex=sce)
                d_fut = select_period(d_fut, 2070, 2100)
                
                try:
                    mean_hist = np.nanmean(d_hist[var+'_'+mod+'_'+'historic'])
                    mean_fut = np.nanmean(d_fut[var+'_'+mod+'_'+sce])
                    
                    if (var == 'TASM') or (var == 'SNOWPROP') or (var == 'SWE') or (var == 'SWI'):
                        units = round(np.nanmean(d_fut[var+'_'+mod+'_'+sce])-np.nanmean(d_hist[var+'_'+mod+'_'+'historic']), 1)
                        perct = int(round(100*((mean_fut-mean_hist))/mean_hist, 1))
                    else:
                        units = round((np.nanmean(d_fut[var+'_'+mod+'_'+sce])-np.nanmean(d_hist[var+'_'+mod+'_'+'historic']))*365, 1)
                        perct = int(round(100*((mean_fut-mean_hist))/mean_hist, 1))
                except:
                    units = np.nan
                    perct = np.nan
                    pass
    
                print(mod, var, sce, units, perct)
                
                df_delta.loc[mod,var+'units'] = units
                df_delta.loc[mod,var+'perct'] = perct
                
            d_hist['all'] = d_hist.mean(axis=1)
            d_fut['all'] = d_fut.mean(axis=1)
            d_hist_all = np.nanmean(d_hist['all'])
            d_fut_all = np.nanmean(d_fut['all'])
            
            if (var == 'TASM') or (var == 'SNOWPROP') or (var == 'SWE') or (var == 'SWI'):
                units_all = round((np.nanmean(d_fut['all'])-np.nanmean(d_hist['all'])), 1)
                perct_all = int(round(100*((d_fut_all-d_hist_all))/d_hist_all, 1))
            else:
                units_all = round((np.nanmean(d_fut['all'])-np.nanmean(d_hist['all']))*365, 1)
                perct_all = int(round(100*((d_fut_all-d_hist_all))/d_hist_all, 1))
            print('ALL', var, sce, units_all, perct_all)
    
            df_delta.loc['ALL',var+'units'] = units_all
            df_delta.loc['ALL',var+'perct'] = perct_all
    
    
    df_delta.to_csv(fig_path+'c_sup_models/'+'df_delta_v2.csv', sep=';', encoding='utf-8', decimal=',')

#%% ---- PLOT DRIAS THINGS

#%% DAILY EVOLUTION DAYS INF Q10

all_proj = pd.read_csv(BV.stable_folder + '/driaseau/' + '_ALL_D.csv', sep=';', index_col=0, parse_dates=True)
all_proj = select_period(all_proj,1975,2099)

var = 'REC'
per = [1975,2100]

# All
mod_list = ['MPI-CCL',
            'ECE-RCA',
            'ECE-RAC',
            # 'IPS-RCA',
            'CNR-RAC',
            # 'NOR-R15',
            'CNR-ALA',
            # 'NOR-HIR',
            # 'HAD-CCL',
            # 'IPS-WRF',
            # 'HAD-REG',
            'MPI-R09']

sce_list = ['RCP26','RCP45','RCP85']
# sce_list = ['RCP85']

# fig, ax = plt.subplots(1,1, figsize=(6,3))

val_quant = 0.10

for sce in sce_list:
    
    df_rec = pd.DataFrame()

    for mod in mod_list:
        
        print(mod)
        
        d = all_proj.copy()
        
        d[var+'_'+mod+'_'+'historic'] = d[var+'_'+mod+'_'+'historic'] + d['RUN'+'_'+mod+'_'+'historic']
        d[var+'_'+mod+'_'+sce] = d[var+'_'+mod+'_'+sce] + d['RUN'+'_'+mod+'_'+sce]
        
        # d = dfd.copy()
        # d = d.resample('M').sum()
        
        quant = select_period(d[var+'_'+mod+'_'+'historic'],
                              1980, 2004).quantile(val_quant)
        print(quant)
        # quant = 0.1
    
        cond = quant
    
        d = d[(d.index.year>=per[0]) & (d.index.year<=per[1])]
        d = d.filter(regex=var+'_'+mod)
        
        # if typ == 'DAYON':
        # if len(mod.split('-')) == 1:
        d[var+'_'+mod+'_'+'historic'][(d.index.year)>=2005] = np.nan
        d[var+'_'+mod+'_'+sce][(d.index.year)<2005] = np.nan
    
        d = pd.concat((d.filter(regex=var+'_'+mod+'_'+sce),
                        d.filter(regex=var+'_'+mod+'_'+'historic')), axis=1).mean(axis=1).to_frame()
        
        ish = (d.filter(regex=var+'_'+mod+'_'+'historic')).dropna().shape[1]
        isf = (d.filter(regex=var+'_'+mod+'_'+sce)).dropna().shape[1]
            
        # print(mod, sce, ish, isf, d.shape)
    
        # plt.plot(d)
    
        d.columns = [var+'_'+mod+'_'+sce]
        d = d.round(2)
        
        x = d.copy()
        x['counter'] = x.diff().ne(0).cumsum()
        
        d['diff'] = d.diff()
        
        years = d.index.year.unique()
        
        # fig, ax = plt.subplots(1,1, figsize=(6,3))
        # axs = axs.ravel()
        n = len(years)
        cmap = cm.get_cmap('jet', n)
        
        max_consec_list = []
        min_consec_list = []
        
        counts = []
        for i, year in enumerate(years):
        
            each = d[d.index.year==year]
            
            count = ((each['diff'] <= 0) & (each[var+'_'+mod+'_'+sce] <= cond)).astype(int).sum(axis=0)
            # count = ((each[var+'_'+mod+'_'+sce] <= cond)).astype(int).sum(axis=0)
            
            # count = ((each[var+'_'+mod+'_'+sce] <= cond)).astype(int).sum(axis=0)
    
            if (var =='ETP') | (var =='TAS'):
                # test = ((each['diff'] <= cond) & (each[var+'_'+mod+'_'+sce] >= cond)).astype(int)
                # count = ((each['diff'] <= cond) & (each[var+'_'+mod+'_'+sce] >= cond)).astype(int).sum(axis=0)
                count = ((each[var+'_'+mod+'_'+sce] >= cond)).astype(int).sum(axis=0)
            counts.append(count)
            
            new = x[x.index.year==year]
            df2 = new.groupby('counter')[var+'_'+mod+'_'+sce].min().to_frame(name='value').join(
                  new.groupby('counter')[var+'_'+mod+'_'+sce].count().rename('number'))
            max_consec0 = df2[df2['value']<=quant]['number'].tolist()
            if var =='ETP':
                max_consec0 = df2[df2['value']>=quant]['number'].tolist()
            max_consec1 = df2[df2['value']==1]['number'].tolist()
            try:
                max_consec_list.append(max(max_consec0))
            except:
                max_consec_list.append(np.nan)
                pass
            # min_consec_list.append(min(max_consec0))
            
            # ax = axs[0]
            # ax.plot(each['diff'].values, c=cmap(i), lw=0.5)
            # ax.set_xlim(0,365)
            # ax.set_ylabel('Diff. day before')
            # ax.set_title(var)
            
            # ax = axs[1]
            # ax.plot(max_consec0, c=cmap(i), lw=0.5)
            # ax.set_ylabel('Max consec. 0')
            # ax.set_title(var)
        
        df_rec[mod] = counts
        
        # ax.set_xlim(0, None)
        # ax.set_ylim(0, None)
    
    df_rec.index = years
    # df_rec.boxplot()
    
    x = df_rec.copy()
    x['med'] = df_rec.quantile(0.50, axis=1)
    x['med'] = df_rec.mean(axis=1)
    # threshold = 60
    # x['cond'] = False
    # x['cond'][x[mod] >= 60] = True 
    x['cond'] = np.nan
    x['cond'][x['med']<60] = 0
    x['cond'][x['med']>=60] = 1
    # x['consecutive'] = x['cond'].groupby((x['cond'] != x['cond'].shift()).cumsum()).transform('size') * x['cond']
    # x['consecutive'] = (x['cond'].groupby((x['cond'] != x['cond'].shift()).cumsum()).transform('size') * x['cond'] >= 1).astype(int)
    # x['cumsum'] = x[mod].cumsum()
    # x['diff'] = x[mod].diff()
    # x['cond'] = np.nan
    x['cons'] = 0
    for j in x.index:
        # print(j)
        if j > x.index[0]:
            if (x.loc[j,'cond'] == 1) & (x.loc[j-1,'cond'] == 1):
                x.loc[j,'cons'] = 1
    # y = pd.concat([x[mod], x[mod].diff().ne(0).cumsum()], axis=1)
    l = []
    for p in [[1975,2010],[2010,2040],[2040,2070],[2070,2100]]:
        v_cond = x[(x.index>=p[0])&(x.index<=p[1])].groupby(x['cond'].diff().ne(0).cumsum()).sum().sum()
        val_cond = v_cond['cond'] #/ (p[1]-p[0])
        v_cons = x[(x.index>=p[0])&(x.index<=p[1])].groupby(x['cons'].diff().ne(0).cumsum()).sum().sum()
        val_cons = v_cons['cons'] #/ (p[1]-p[0])
        y = x[(x.index>=p[0])&(x.index<=p[1])]['cond']
        v_maxi = y.groupby((y != y.shift()).cumsum()).transform('size') * y
        val_maxi = v_maxi.max()
        # print(p, val_cond.round(3), val_cons.round(3), val_maxi.round(3))
        # l.append(val_cond.round(3))
        # l.append(val_cons.round(3))
        # l.append(val_maxi.round(3))
        l.append(round(val_cond,3))
        l.append(round(val_cons,3))
        l.append(round(val_maxi,3))
    
    df_rec = df_rec.T
    
    # df_rec.boxplot()
    
    # fig, ax = plt.subplots(1,1, figsize=(10,4))
    fig, ax = plt.subplots(1,1, figsize=(9,4))
    
    ax.set_title(l, fontsize=6)
    
    import matplotlib
    normaliz = plt.Normalize(df_rec.median().min(), df_rec.median().max())
    norm = matplotlib.colors.Normalize(vmin=0, vmax=100)
    # if sce == 'RCP2.6':
    #     to_norm = df_rec.median()
    colors = plt.cm.jet(norm(df_rec.median()))
    # colors = plt.cm.jet(norm([60] * len(df_rec.columns)))
    # colors = plt.cm.jet(norm(to_norm))
    # colors = plt.cm.jet(norm((df_rec.median()*0)+60))
    
    
    medianprops = dict(linestyle='-', linewidth=1, color='black')
    meanpointprops = dict(markersize=0, marker='o', markeredgecolor='black',
                          markerfacecolor='k', linestyle='-')
    
    ax.vlines(x=years, 
                ymin=df_rec.quantile(0.75), 
                ymax=df_rec.quantile(0.95), color='k', zorder=2)
    ax.vlines(x=years, 
                ymin=df_rec.quantile(0.05), 
                ymax=df_rec.quantile(0.25), color='k', zorder=2)
    
    # boxprops = dict(linestyle='-', linewidth=1, color='k',
    #                 facecolor='cyan', alpha=0.5)
    # bp = ax.boxplot(df_rec, widths=0.75,
    #                 positions=years,
    #                   whis=False, showfliers=False, showmeans=False, 
    #                   medianprops=medianprops, meanprops=meanpointprops,
    #                   patch_artist=True, boxprops=boxprops)
    
    for i in range(len(years)):
        # print(i)
        boxprops = dict(linestyle='-', linewidth=1, color='k',
                        facecolor=colors[i], 
                        alpha=0.5)
        bp = ax.boxplot(df_rec.iloc[:,i], widths=0.75,
                        positions=[df_rec.columns[i]],
                          whis=False, showfliers=False, showmeans=False, 
                          medianprops=medianprops, meanprops=meanpointprops,
                          patch_artist=True, boxprops=boxprops)
    
    ax.plot(years, df_rec.mean(), marker='o', mec='k', ms=1.5, lw=0,
            mfc='k', mew=1,
            color='k', zorder=1000)
      
    for element in bp['whiskers']:
        element.set_color('k')
        element.set_linestyle('-')
    # for patch in bp['boxes']:
    #     patch.set(facecolor='r')    
    ax.set_xticks(np.arange(1980, 2100+1, 10))
    ax.set_xticklabels(np.arange(1980, 2100+1, 10))
    
    # ax.get_xaxis().set_visible(False)
    # ax.set_yscale('log')
    
    ax.set_ylim(-5, 180)
    ax.set_yticks(np.arange(0, 180+1, 30))
    
    ax.set_xlim(1974,2100)
    ax.tick_params(axis='x', which='minor')
    
    from matplotlib.ticker import (MultipleLocator)
    ax.xaxis.set_minor_locator(MultipleLocator(1))
    
    ax.set_axisbelow(True)
    # ax.grid(zorder=-1000)
    ax.xaxis.grid(color='gray', alpha=0.2, zorder=-20)
    ax.yaxis.grid(color='gray', alpha=0.2, zorder=-20, which='both')
    
    # ax.set_title(var+' - '+mod)
    # ax.set_xlim(pd.to_datetime('1974'), pd.to_datetime('2100'))
    
    plt.tight_layout()
    
    # fig.savefig('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_figures_paper/_v0/c_sup_models/'+
    #             'EVOL_DAYS_DRY-'+sce+'.png',
    #                         bbox_inches='tight')

#%% EVOLUTION CILMAT EAU - OLD
 
if 'all_proj_clim' not in globals():
    all_proj_clim = pd.read_csv(BV.stable_folder + '/driasclimat/' + '_ALL_D.csv', sep=';', index_col=0, parse_dates=True)
    all_proj_eau =  pd.read_csv(BV.stable_folder + '/driaseau/' + '_ALL_D.csv', sep=';', index_col=0, parse_dates=True)

sce_list = ['historic','RCP26','RCP45','RCP85']
mod_list = ['MPI-CCL',
            'ECE-RCA',
            'ECE-RAC',
            'CNR-RAC',
            'CNR-ALA',
            'MPI-R09']
mod_keep = 'MPI-CCL|ECE-RCA|ECE-RAC|CNR-RAC|CNR-ALA|MPI-R09'
mod_list_ppt = ['MPI-CCL',
                'ECE-RCA',
                'MPI-R09']
mod_keep_pptt = 'MPI-CCL|ECE-RCA|MPI-R09'

sce_list = ['historic','RCP26','RCP45','RCP85']
col_list = ['dimgrey','dodgerblue','orange','red']
col_list_b = ['k','navy','darkorange','darkred']
dict_c = dict(zip(sce_list, col_list))
dict_c_b = dict(zip(sce_list, col_list_b))

# sce_list = ['historic','RCP85']
# col_list = ['dimgrey','red']
# col_list_b = ['k','darkred']
# dict_c = dict(zip(sce_list, col_list))
# dict_c_b = dict(zip(sce_list, col_list_b))

for var in  [
            # 'TASM',
            # 'PPTT',
            # 'SNOW',
            # 'PLIQ',
            # 'SWE',
            #   'SNOWPROP',
            #   'PE',
            #    'ETP',
            #    'RUN',
            #    'REC',
               # 'SWI',
               'RECRUN'
             ]:
    
    all_proj_mix = pd.merge(all_proj_clim, all_proj_eau, how='inner', left_index=True, right_index=True)
    all_proj_mix = all_proj_mix.filter(regex=mod_keep)
    
    for mod in mod_list:
        for sce in sce_list:
            if var == 'PPTT':
                all_proj_mix[var+'_'+mod+'_'+sce] = all_proj_mix[var+'_'+mod+'_'+sce]*3600*24
            if var == 'SNOW':
                all_proj_mix[var+'_'+mod+'_'+sce] = all_proj_mix[var+'_'+mod+'_'+sce]*3600*24
            if var == 'SNOWPROP':
                all_proj_mix[var+'_'+mod+'_'+sce] = (all_proj_mix['SNOW'+'_'+mod+'_'+sce]*3600*24) / (all_proj_mix['PPTT'+'_'+mod+'_'+sce]*3600*24)
            if var == 'PLIQ':
                all_proj_mix[var+'_'+mod+'_'+sce] = (all_proj_mix['PPTT'+'_'+mod+'_'+sce]*3600*24) - (all_proj_mix['SNOW'+'_'+mod+'_'+sce]*3600*24)
            if var == 'PE':
                all_proj_mix[var+'_'+mod+'_'+sce] = (all_proj_mix['PPTT'+'_'+mod+'_'+sce]*3600*24) - (all_proj_mix['ETP'+'_'+mod+'_'+sce])
            if var == 'RECRUN':
                all_proj_mix[var+'_'+mod+'_'+sce] = (all_proj_mix['REC'+'_'+mod+'_'+sce]) + (all_proj_mix['RUN'+'_'+mod+'_'+sce])

    fig, ax = plt.subplots(1,1, figsize=(10,4))
    
    for sce in sce_list:
        
        df = pd.DataFrame()
        dproj = all_proj_mix.copy()
        
        if var == 'ETP':
            var = 'ETP_'
        
        if (var == 'PPTT') or (var == 'SNOWPROP') or (var == 'PLIQ') or (var == 'PE'):
            dproj = dproj.filter(regex=mod_keep_pptt).filter(regex=var)
        else:
            dproj = dproj.filter(regex=mod_keep).filter(regex=var)

        # print(var, sce, dproj[var+'_'+mod+'_'+sce].mean())
        # print('PPTT', sce, dproj['PPTT'+'_'+mod+'_'+sce].mean())

        d_hist = dproj.filter(regex=var).filter(regex='historic')
        d_hist = select_period(d_hist, 1975, 2004)
        
        d_tot = dproj.filter(regex=var).filter(regex=sce)
        d_tot = select_period(d_tot, 1975, 2100)
        
        d_fut = dproj.filter(regex=var).filter(regex=sce)
        d_fut = select_period(d_fut, 2004, 2100)
        
        # d = (d_fut.mean(axis=1) - d_hist.mean(axis=1).mean()) / ((d_fut.mean(axis=1) + d_hist.mean(axis=1).mean())/2)
        
        # if sce == 'historic':
        #     d10 = (d_hist.quantile(0.10,axis=1) - d_hist.quantile(0.10,axis=1).mean()) / (d_hist.quantile(0.10,axis=1).mean())
        #     d25 = (d_hist.quantile(0.25,axis=1) - d_hist.quantile(0.25,axis=1).mean()) / (d_hist.quantile(0.25,axis=1).mean())
        #     d50 = (d_hist.quantile(0.50,axis=1) - d_hist.quantile(0.50,axis=1).mean()) / (d_hist.quantile(0.50,axis=1).mean())
        #     d75 = (d_hist.quantile(0.75,axis=1) - d_hist.quantile(0.75,axis=1).mean()) / (d_hist.quantile(0.75,axis=1).mean())   
        #     d90 = (d_hist.quantile(0.90,axis=1) - d_hist.quantile(0.90,axis=1).mean()) / (d_hist.quantile(0.90,axis=1).mean())
        # else:
        #     d10 = (d_fut.quantile(0.10,axis=1) - d_hist.quantile(0.10,axis=1).mean()) / (d_hist.quantile(0.10,axis=1).mean())
        #     d25 = (d_fut.quantile(0.25,axis=1) - d_hist.quantile(0.25,axis=1).mean()) / (d_hist.quantile(0.25,axis=1).mean())
        #     d50 = (d_fut.quantile(0.50,axis=1) - d_hist.quantile(0.50,axis=1).mean()) / (d_hist.quantile(0.50,axis=1).mean())
        #     d75 = (d_fut.quantile(0.75,axis=1) - d_hist.quantile(0.75,axis=1).mean()) / (d_hist.quantile(0.75,axis=1).mean())
        #     d90 = (d_fut.quantile(0.90,axis=1) - d_hist.quantile(0.90,axis=1).mean()) / (d_hist.quantile(0.90,axis=1).mean())
        
        if sce == 'historic':
            d10 = (d_hist.quantile(0.10,axis=1)) - d_hist.quantile(0.10,axis=1).mean() #/ (d_hist.quantile(0.10,axis=1).mean())
            d25 = (d_hist.quantile(0.25,axis=1)) - d_hist.quantile(0.25,axis=1).mean() #/ (d_hist.quantile(0.25,axis=1).mean())
            d50 = (d_hist.quantile(0.50,axis=1)) - d_hist.quantile(0.50,axis=1).mean() #/ (d_hist.quantile(0.50,axis=1).mean())
            d75 = (d_hist.quantile(0.75,axis=1)) - d_hist.quantile(0.75,axis=1).mean() #/ (d_hist.quantile(0.75,axis=1).mean())   
            d90 = (d_hist.quantile(0.90,axis=1)) - d_hist.quantile(0.90,axis=1).mean() #/ (d_hist.quantile(0.90,axis=1).mean())
            dm = d_hist.mean(axis=1) - d_hist.mean(axis=1).mean() #/ (d_hist.quantile(0.90,axis=1).mean())
        else:
            d10 = (d_fut.quantile(0.10,axis=1)) - d_hist.quantile(0.10,axis=1).mean() #/ (d_hist.quantile(0.10,axis=1).mean())
            d25 = (d_fut.quantile(0.25,axis=1)) - d_hist.quantile(0.25,axis=1).mean() #/ (d_hist.quantile(0.25,axis=1).mean())
            d50 = (d_fut.quantile(0.50,axis=1)) - d_hist.quantile(0.50,axis=1).mean() #/ (d_hist.quantile(0.50,axis=1).mean())
            d75 = (d_fut.quantile(0.75,axis=1)) - d_hist.quantile(0.75,axis=1).mean() #/ (d_hist.quantile(0.75,axis=1).mean())
            d90 = (d_fut.quantile(0.90,axis=1)) - d_hist.quantile(0.90,axis=1).mean() #/ (d_hist.quantile(0.90,axis=1).mean())
            dm = d_fut.mean(axis=1) - d_hist.mean(axis=1).mean()
            
        # if sce == 'historic':
        #     d10 = (d_hist.quantile(0.10,axis=1)) - d_hist.mean(axis=1) #/ (d_hist.quantile(0.10,axis=1).mean())
        #     d25 = (d_hist.quantile(0.25,axis=1)) - d_hist.mean(axis=1) #/ (d_hist.quantile(0.25,axis=1).mean())
        #     d50 = (d_hist.quantile(0.50,axis=1)) - d_hist.mean(axis=1) #/ (d_hist.quantile(0.50,axis=1).mean())
        #     d75 = (d_hist.quantile(0.75,axis=1)) - d_hist.mean(axis=1) #/ (d_hist.quantile(0.75,axis=1).mean())   
        #     d90 = (d_hist.quantile(0.90,axis=1)) - d_hist.mean(axis=1) #/ (d_hist.quantile(0.90,axis=1).mean())
        # else:
        #     d10 = (d_fut.quantile(0.10,axis=1)) - d_hist.mean(axis=1) #/ (d_hist.quantile(0.10,axis=1).mean())
        #     d25 = (d_fut.quantile(0.25,axis=1)) - d_hist.mean(axis=1) #/ (d_hist.quantile(0.25,axis=1).mean())
        #     d50 = (d_fut.quantile(0.50,axis=1)) - d_hist.mean(axis=1) #/ (d_hist.quantile(0.50,axis=1).mean())
        #     d75 = (d_fut.quantile(0.75,axis=1)) - d_hist.mean(axis=1) #/ (d_hist.quantile(0.75,axis=1).mean())
        #     d90 = (d_fut.quantile(0.90,axis=1)) - d_hist.mean(axis=1) #/ (d_hist.quantile(0.90,axis=1).mean())
        
        # d = (d_fut.mean(axis=1) - d_hist.mean(axis=1).mean()) / (d_hist.mean(axis=1).mean()
        
        # plt.plot(d25.resample('Y').mean())
        # plt.plot(d50.resample('Y').mean())
        # plt.plot(d75.resample('Y').mean())
        # plt.ylim(-5,5)
    
        # d['MIN'] = d.filter(regex=sce).min(axis=1)
        # d['Q5'] = d.filter(regex=sce).quantile(0.05, axis=1)
        # d['Q10'] = d.filter(regex=sce).quantile(0.10, axis=1)
        # d['Q25'] = d.filter(regex=sce).quantile(0.25, axis=1)
        # d['MEAN'] = d.filter(regex=sce).mean(axis=1)
        # d['MED'] = d.filter(regex=sce).median(axis=1)
        # d['Q75'] = d.filter(regex=sce).quantile(0.75, axis=1)
        # d['Q90'] = d.filter(regex=sce).quantile(0.90, axis=1)
        # d['Q95'] = d.filter(regex=sce).quantile(0.95, axis=1)
        # d['MAX'] = d.filter(regex=sce).max(axis=1)
        # d = d.resample('Y').mean() #* 1000 * 365
        
        # high = select_period(d['Q25'].copy(), per[0], per[1])
        # mean = select_period(d['MED'].copy(), per[0], per[1])
        # low = select_period(d['Q75'].copy(), per[0], per[1])
        
        # high = select_period(d['Q25'].copy(), per[0], per[1]).rolling(window=5).mean()
        # mean = select_period(d['MED'].copy(), per[0], per[1]).rolling(window=5).mean()
        # low = select_period(d['Q75'].copy(), per[0], per[1]).rolling(window=5).mean()
        
        # high = select_period(d['Q25'].copy(), per[0], per[1])#.rolling(window=5).mean()
        # mean = select_period(d['MED'].copy(), per[0], per[1])#.rolling(window=5).mean()
        # low = select_period(d['Q75'].copy(), per[0], per[1])#.rolling(window=5).mean()
        
        # ax.plot(d50.resample('Y').mean().rolling(window=5).mean(), c=dict_c_b[sce], lw=2)
        # ax.fill_between(d50.resample('Y').mean().rolling(window=5).mean().index,
        #                 d25.resample('Y').mean().rolling(window=5).mean(),
        #                 d75.resample('Y').mean().rolling(window=5).mean(),
        #                 color=dict_c[sce], alpha=0.25, ec='None')
        
        if (var == 'TASM') or (var == 'SNOWPROP') or (var == 'SWE') or (var == 'SWI'):
            ax.plot(d50.resample('Y').mean().rolling(window=10).mean(), c=dict_c_b[sce], lw=2)
            ax.plot(dm.resample('Y').mean().rolling(window=10).mean(), c=dict_c_b[sce], lw=1)
            ax.fill_between(d50.resample('Y').mean().rolling(window=10).mean().index,
                            d25.resample('Y').mean().rolling(window=10).mean(),
                            d75.resample('Y').mean().rolling(window=10).mean(),
                            color=dict_c[sce], alpha=0.25, ec='None')
        else:
            ax.plot(d50.resample('Y').sum().rolling(window=10).mean(), c=dict_c_b[sce], lw=2)
            ax.plot(dm.resample('Y').sum().rolling(window=10).mean(), c=dict_c_b[sce], lw=1)
            ax.fill_between(d50.resample('Y').sum().rolling(window=10).mean().index,
                            d25.resample('Y').sum().rolling(window=10).mean(),
                            d75.resample('Y').sum().rolling(window=10).mean(),
                            color=dict_c[sce], alpha=0.25, ec='None')

        ax.set_axisbelow(True)
        ax.xaxis.grid(color='gray', alpha=0.2, zorder=-20)
        ax.yaxis.grid(color='gray', alpha=0.2, zorder=-20)
        ax.set_xlim(pd.to_datetime('1975'), pd.to_datetime('2100'))
        
        # ax.axvline(pd.to_datetime('1980'), c='k', ls='--')
        # ax.axvline(pd.to_datetime('2006'), c='k', ls='--')
        # ax.axvline(pd.to_datetime('2010'), c='k', ls='--')
        
        # ax.set_ylim(80, 350)
        
        yearsmaj = mdates.YearLocator(10)   # every year
        monthsmaj = mdates.MonthLocator(12)  # every month
        years_fmt = mdates.DateFormatter('%Y')
        ax.xaxis.set_major_locator(yearsmaj)
        ax.xaxis.set_minor_locator(monthsmaj)
        ax.xaxis.set_major_formatter(years_fmt)
        
        # ax.axhline()
        
        # ax.axhline(y=0, color='k', lw=1.5, ls='--')
        ax.axhline(y=0, color='k', lw=1, ls='-', zorder=+1000)

    fig.suptitle(var,fontsize=10)
    # fig.savefig('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_figures_paper/_v0/c_sup_models/'+
    #             'EVOL_'+var+'-'+sce+'.png',
    #                         bbox_inches='tight')

#%% EVOLUTION CILMAT EAU - NEW
 
if 'all_proj_clim' not in globals():
    all_proj_clim = pd.read_csv(BV.stable_folder + '/driasclimat/' + '_ALL_D.csv', sep=';', index_col=0, parse_dates=True)
    all_proj_eau =  pd.read_csv(BV.stable_folder + '/driaseau/' + '_ALL_D.csv', sep=';', index_col=0, parse_dates=True)

sce_list = ['historic','RCP26','RCP45','RCP85']
mod_list = ['MPI-CCL',
            'ECE-RCA',
            'ECE-RAC',
            'CNR-RAC',
            'CNR-ALA',
            'MPI-R09']
mod_keep = 'MPI-CCL|ECE-RCA|ECE-RAC|CNR-RAC|CNR-ALA|MPI-R09'
mod_list_ppt = ['MPI-CCL',
                'ECE-RCA',
                'MPI-R09']
mod_keep_pptt = 'MPI-CCL|ECE-RCA|MPI-R09'

sce_list = ['historic','RCP26','RCP45','RCP85']
col_list = ['dimgrey','dodgerblue','orange','red']
col_list_b = ['k','navy','darkorange','darkred']
dict_c = dict(zip(sce_list, col_list))
dict_c_b = dict(zip(sce_list, col_list_b))

sce_list = ['historic','RCP85']
col_list = ['dimgrey','red']
col_list_b = ['k','darkred']
dict_c = dict(zip(sce_list, col_list))
dict_c_b = dict(zip(sce_list, col_list_b))

for var in  [
            # 'TASM',
            # 'PPTT',
            # 'SNOW',
            # 'PLIQ',
            # 'SWE',
            #   'SNOWPROP',
            #   'PE',
              # 'ETP',
              # 'RUN',
              # 'REC',
              # 'SWI',
              'RECRUN'
             ]:
    
    all_proj_mix = pd.merge(all_proj_clim, all_proj_eau, how='inner', left_index=True, right_index=True)
    all_proj_mix = all_proj_mix.filter(regex=mod_keep)
    
    for mod in mod_list:
        for sce in sce_list:
            if var == 'PPTT':
                all_proj_mix[var+'_'+mod+'_'+sce] = all_proj_mix[var+'_'+mod+'_'+sce]*3600*24
            if var == 'SNOW':
                all_proj_mix[var+'_'+mod+'_'+sce] = all_proj_mix[var+'_'+mod+'_'+sce]*3600*24
            if var == 'SNOWPROP':
                all_proj_mix[var+'_'+mod+'_'+sce] = (all_proj_mix['SNOW'+'_'+mod+'_'+sce]*3600*24) / (all_proj_mix['PPTT'+'_'+mod+'_'+sce]*3600*24)
            if var == 'PLIQ':
                all_proj_mix[var+'_'+mod+'_'+sce] = (all_proj_mix['PPTT'+'_'+mod+'_'+sce]*3600*24) - (all_proj_mix['SNOW'+'_'+mod+'_'+sce]*3600*24)
            if var == 'PE':
                all_proj_mix[var+'_'+mod+'_'+sce] = (all_proj_mix['PPTT'+'_'+mod+'_'+sce]*3600*24) - (all_proj_mix['ETP'+'_'+mod+'_'+sce])

    fig, ax = plt.subplots(1,1, figsize=(10,4))
    
    for sce in sce_list:
        
        df = pd.DataFrame()
        dproj = all_proj_mix.copy()
        
        if var == 'ETP':
            var = 'ETP_'
        
        if (var == 'PPTT') or (var == 'SNOWPROP') or (var == 'PLIQ') or (var == 'PE'):
            dproj = dproj.filter(regex=mod_keep_pptt).filter(regex=var)
        else:
            dproj = dproj.filter(regex=mod_keep).filter(regex=var)

        # print(var, sce, dproj[var+'_'+mod+'_'+sce].mean())
        # print('PPTT', sce, dproj['PPTT'+'_'+mod+'_'+sce].mean())
        
        if (var == 'TASM') or (var == 'SNOWPROP') or (var == 'SWE'):
            dproj = dproj.resample('Y').mean().rolling(window=10).mean()
        else:
            dproj = dproj.resample('Y').sum().rolling(window=10).mean()

        d_hist = dproj.filter(regex=var).filter(regex='historic')
        d_hist = select_period(d_hist, 1975, 2004)
        
        d_tot = dproj.filter(regex=var).filter(regex=sce)
        d_tot = select_period(d_tot, 1975, 2100)
        
        d_fut = dproj.filter(regex=var).filter(regex=sce)
        d_fut = select_period(d_fut, 2004, 2100)
        
        # d = (d_fut.mean(axis=1) - d_hist.mean(axis=1).mean()) / ((d_fut.mean(axis=1) + d_hist.mean(axis=1).mean())/2)
        
        # if sce == 'historic':
        #     d10 = (d_hist.quantile(0.10,axis=1) - d_hist.quantile(0.10,axis=1).mean()) / (d_hist.quantile(0.10,axis=1).mean())
        #     d25 = (d_hist.quantile(0.25,axis=1) - d_hist.quantile(0.25,axis=1).mean()) / (d_hist.quantile(0.25,axis=1).mean())
        #     d50 = (d_hist.quantile(0.50,axis=1) - d_hist.quantile(0.50,axis=1).mean()) / (d_hist.quantile(0.50,axis=1).mean())
        #     d75 = (d_hist.quantile(0.75,axis=1) - d_hist.quantile(0.75,axis=1).mean()) / (d_hist.quantile(0.75,axis=1).mean())   
        #     d90 = (d_hist.quantile(0.90,axis=1) - d_hist.quantile(0.90,axis=1).mean()) / (d_hist.quantile(0.90,axis=1).mean())
        # else:
        #     d10 = (d_fut.quantile(0.10,axis=1) - d_hist.quantile(0.10,axis=1).mean()) / (d_hist.quantile(0.10,axis=1).mean())
        #     d25 = (d_fut.quantile(0.25,axis=1) - d_hist.quantile(0.25,axis=1).mean()) / (d_hist.quantile(0.25,axis=1).mean())
        #     d50 = (d_fut.quantile(0.50,axis=1) - d_hist.quantile(0.50,axis=1).mean()) / (d_hist.quantile(0.50,axis=1).mean())
        #     d75 = (d_fut.quantile(0.75,axis=1) - d_hist.quantile(0.75,axis=1).mean()) / (d_hist.quantile(0.75,axis=1).mean())
        #     d90 = (d_fut.quantile(0.90,axis=1) - d_hist.quantile(0.90,axis=1).mean()) / (d_hist.quantile(0.90,axis=1).mean())
        
        if sce == 'historic':
            d10 = (d_hist.quantile(0.10,axis=1)) - d_hist.quantile(0.10,axis=1).mean() #/ (d_hist.quantile(0.10,axis=1).mean())
            d25 = (d_hist.quantile(0.25,axis=1)) - d_hist.quantile(0.25,axis=1).mean() #/ (d_hist.quantile(0.25,axis=1).mean())
            d50 = (d_hist.quantile(0.50,axis=1)) - d_hist.quantile(0.50,axis=1).mean() #/ (d_hist.quantile(0.50,axis=1).mean())
            d75 = (d_hist.quantile(0.75,axis=1)) - d_hist.quantile(0.75,axis=1).mean() #/ (d_hist.quantile(0.75,axis=1).mean())   
            d90 = (d_hist.quantile(0.90,axis=1)) - d_hist.quantile(0.90,axis=1).mean() #/ (d_hist.quantile(0.90,axis=1).mean())
            dm = d_hist.mean(axis=1) - d_hist.mean(axis=1).mean() #/ (d_hist.quantile(0.90,axis=1).mean())
        else:
            d10 = (d_fut.quantile(0.10,axis=1)) - d_hist.quantile(0.10,axis=1).mean() #/ (d_hist.quantile(0.10,axis=1).mean())
            d25 = (d_fut.quantile(0.25,axis=1)) - d_hist.quantile(0.25,axis=1).mean() #/ (d_hist.quantile(0.25,axis=1).mean())
            d50 = (d_fut.quantile(0.50,axis=1)) - d_hist.quantile(0.50,axis=1).mean() #/ (d_hist.quantile(0.50,axis=1).mean())
            d75 = (d_fut.quantile(0.75,axis=1)) - d_hist.quantile(0.75,axis=1).mean() #/ (d_hist.quantile(0.75,axis=1).mean())
            d90 = (d_fut.quantile(0.90,axis=1)) - d_hist.quantile(0.90,axis=1).mean() #/ (d_hist.quantile(0.90,axis=1).mean())
            dm = d_fut.mean(axis=1) - d_hist.mean(axis=1).mean()
            
        # if sce == 'historic':
        #     d10 = (d_hist.quantile(0.10,axis=1)) - d_hist.mean(axis=1) #/ (d_hist.quantile(0.10,axis=1).mean())
        #     d25 = (d_hist.quantile(0.25,axis=1)) - d_hist.mean(axis=1) #/ (d_hist.quantile(0.25,axis=1).mean())
        #     d50 = (d_hist.quantile(0.50,axis=1)) - d_hist.mean(axis=1) #/ (d_hist.quantile(0.50,axis=1).mean())
        #     d75 = (d_hist.quantile(0.75,axis=1)) - d_hist.mean(axis=1) #/ (d_hist.quantile(0.75,axis=1).mean())   
        #     d90 = (d_hist.quantile(0.90,axis=1)) - d_hist.mean(axis=1) #/ (d_hist.quantile(0.90,axis=1).mean())
        # else:
        #     d10 = (d_fut.quantile(0.10,axis=1)) - d_hist.mean(axis=1) #/ (d_hist.quantile(0.10,axis=1).mean())
        #     d25 = (d_fut.quantile(0.25,axis=1)) - d_hist.mean(axis=1) #/ (d_hist.quantile(0.25,axis=1).mean())
        #     d50 = (d_fut.quantile(0.50,axis=1)) - d_hist.mean(axis=1) #/ (d_hist.quantile(0.50,axis=1).mean())
        #     d75 = (d_fut.quantile(0.75,axis=1)) - d_hist.mean(axis=1) #/ (d_hist.quantile(0.75,axis=1).mean())
        #     d90 = (d_fut.quantile(0.90,axis=1)) - d_hist.mean(axis=1) #/ (d_hist.quantile(0.90,axis=1).mean())
        
        # d = (d_fut.mean(axis=1) - d_hist.mean(axis=1).mean()) / (d_hist.mean(axis=1).mean()
        
        # plt.plot(d25.resample('Y').mean())
        # plt.plot(d50.resample('Y').mean())
        # plt.plot(d75.resample('Y').mean())
        # plt.ylim(-5,5)
    
        # d['MIN'] = d.filter(regex=sce).min(axis=1)
        # d['Q5'] = d.filter(regex=sce).quantile(0.05, axis=1)
        # d['Q10'] = d.filter(regex=sce).quantile(0.10, axis=1)
        # d['Q25'] = d.filter(regex=sce).quantile(0.25, axis=1)
        # d['MEAN'] = d.filter(regex=sce).mean(axis=1)
        # d['MED'] = d.filter(regex=sce).median(axis=1)
        # d['Q75'] = d.filter(regex=sce).quantile(0.75, axis=1)
        # d['Q90'] = d.filter(regex=sce).quantile(0.90, axis=1)
        # d['Q95'] = d.filter(regex=sce).quantile(0.95, axis=1)
        # d['MAX'] = d.filter(regex=sce).max(axis=1)
        # d = d.resample('Y').mean() #* 1000 * 365
        
        # high = select_period(d['Q25'].copy(), per[0], per[1])
        # mean = select_period(d['MED'].copy(), per[0], per[1])
        # low = select_period(d['Q75'].copy(), per[0], per[1])
        
        # high = select_period(d['Q25'].copy(), per[0], per[1]).rolling(window=5).mean()
        # mean = select_period(d['MED'].copy(), per[0], per[1]).rolling(window=5).mean()
        # low = select_period(d['Q75'].copy(), per[0], per[1]).rolling(window=5).mean()
        
        # high = select_period(d['Q25'].copy(), per[0], per[1])#.rolling(window=5).mean()
        # mean = select_period(d['MED'].copy(), per[0], per[1])#.rolling(window=5).mean()
        # low = select_period(d['Q75'].copy(), per[0], per[1])#.rolling(window=5).mean()
        
        # ax.plot(d50.resample('Y').mean().rolling(window=5).mean(), c=dict_c_b[sce], lw=2)
        # ax.fill_between(d50.resample('Y').mean().rolling(window=5).mean().index,
        #                 d25.resample('Y').mean().rolling(window=5).mean(),
        #                 d75.resample('Y').mean().rolling(window=5).mean(),
        #                 color=dict_c[sce], alpha=0.25, ec='None')
        
        # if (var == 'TASM') or (var == 'SNOWPROP') or (var == 'SWE'):
        #     ax.plot(d50.resample('Y').mean().rolling(window=10).mean(), c=dict_c_b[sce], lw=2)
        #     ax.plot(dm.resample('Y').mean().rolling(window=10).mean(), c=dict_c_b[sce], lw=1)
        #     ax.fill_between(d50.resample('Y').mean().rolling(window=10).mean().index,
        #                     d25.resample('Y').mean().rolling(window=10).mean(),
        #                     d75.resample('Y').mean().rolling(window=10).mean(),
        #                     color=dict_c[sce], alpha=0.25, ec='None')
        # else:
        #     ax.plot(d50.resample('Y').sum().rolling(window=10).mean(), c=dict_c_b[sce], lw=2)
        #     ax.plot(dm.resample('Y').sum().rolling(window=10).mean(), c=dict_c_b[sce], lw=1)
        #     ax.fill_between(d50.resample('Y').sum().rolling(window=10).mean().index,
        #                     d25.resample('Y').sum().rolling(window=10).mean(),
        #                     d75.resample('Y').sum().rolling(window=10).mean(),
        #                     color=dict_c[sce], alpha=0.25, ec='None')
        
        ax.plot(d50, c=dict_c_b[sce], lw=2)
        ax.plot(dm, c=dict_c_b[sce], lw=1)
        ax.fill_between(d50.index,
                        d25,
                        d75,
                        color=dict_c[sce], alpha=0.25, ec='None')

        ax.set_axisbelow(True)
        ax.xaxis.grid(color='gray', alpha=0.2, zorder=-20)
        ax.yaxis.grid(color='gray', alpha=0.2, zorder=-20)
        ax.set_xlim(pd.to_datetime('1975'), pd.to_datetime('2100'))
        
        # ax.axvline(pd.to_datetime('1980'), c='k', ls='--')
        # ax.axvline(pd.to_datetime('2006'), c='k', ls='--')
        # ax.axvline(pd.to_datetime('2010'), c='k', ls='--')
        
        # ax.set_ylim(80, 350)
        
        yearsmaj = mdates.YearLocator(10)   # every year
        monthsmaj = mdates.MonthLocator(12)  # every month
        years_fmt = mdates.DateFormatter('%Y')
        ax.xaxis.set_major_locator(yearsmaj)
        ax.xaxis.set_minor_locator(monthsmaj)
        ax.xaxis.set_major_formatter(years_fmt)
        
        # ax.axhline(y=0, color='k', lw=1.5, ls='--')
    
    # fig.suptitle(var,fontsize=10)
    # fig.savefig('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_figures_paper/_v0/c_sup_models/'+
    #             'EVOL_'+var+'-'+sce+'.png',
    #                         bbox_inches='tight')

#%% INTERMENSUAL CHANGES

if 'all_proj_clim' not in globals():
    all_proj_clim = pd.read_csv(BV.stable_folder + '/driasclimat/' + '_ALL_D.csv', sep=';', index_col=0, parse_dates=True)
    all_proj_eau =  pd.read_csv(BV.stable_folder + '/driaseau/' + '_ALL_D.csv', sep=';', index_col=0, parse_dates=True)


sce_list = ['historic','RCP26','RCP45','RCP85']
sce_list = ['historic']
mod_list = ['MPI-CCL',
            'ECE-RCA',
            'ECE-RAC',
            'CNR-RAC',
            'CNR-ALA',
            'MPI-R09']
mod_keep = 'MPI-CCL|ECE-RCA|ECE-RAC|CNR-RAC|CNR-ALA|MPI-R09'
mod_list_ppt = ['MPI-CCL',
                'ECE-RCA',
                'MPI-R09']
mod_keep_pptt = 'MPI-CCL|ECE-RCA|MPI-R09'

for var in  [
            # 'TASM',
            'PPTT',
            # 'SNOW',
            # 'PLIQ',
            # 'SWE',
            #   'SNOWPROP',
            #   'PE',
            #    'ETP',
            #    'RUN',
            #    'REC',
               # 'SWI',
               # 'RECRUN'
             ]:
    
    all_proj_mix = pd.merge(all_proj_clim, all_proj_eau, how='inner', left_index=True, right_index=True)
    all_proj_mix = all_proj_mix.filter(regex=mod_keep)
    
    for mod in mod_list:
        for sce in sce_list:
            if var == 'PPTT':
                all_proj_mix[var+'_'+mod+'_'+sce] = all_proj_mix[var+'_'+mod+'_'+sce]*3600*24
            if var == 'SNOW':
                all_proj_mix[var+'_'+mod+'_'+sce] = all_proj_mix[var+'_'+mod+'_'+sce]*3600*24
            if var == 'SNOWPROP':
                all_proj_mix[var+'_'+mod+'_'+sce] = (all_proj_mix['SNOW'+'_'+mod+'_'+sce]*3600*24) / (all_proj_mix['PPTT'+'_'+mod+'_'+sce]*3600*24)
            if var == 'PLIQ':
                all_proj_mix[var+'_'+mod+'_'+sce] = (all_proj_mix['PPTT'+'_'+mod+'_'+sce]*3600*24) - (all_proj_mix['SNOW'+'_'+mod+'_'+sce]*3600*24)
            if var == 'PE':
                all_proj_mix[var+'_'+mod+'_'+sce] = (all_proj_mix['PPTT'+'_'+mod+'_'+sce]*3600*24) - (all_proj_mix['ETP'+'_'+mod+'_'+sce])
            if var == 'RECRUN':
                all_proj_mix[var+'_'+mod+'_'+sce] = (all_proj_mix['REC'+'_'+mod+'_'+sce]) + (all_proj_mix['RUN'+'_'+mod+'_'+sce])

    fig, axs = plt.subplots(1,4,figsize=(17, 3), sharey=True)
    # fig, axs = plt.subplots(4,1,figsize=(4, 10), sharey=True, sharex=True)
    axs=axs.ravel()
    # fig.add_subplot(111, frameon=False)
    # plt.tick_params(labelcolor='none', top=False, bottom=False, left=False, 
    #                 right=False) # hide tick and tick label of the big axis
    
    # for mod in mod_list:
    for mod in ['MOD-MIX']:
    # mod = 'MPI-R09'
    
        for axi, sce in enumerate(sce_list[:]):
            
            ax = axs[axi]
            
            print(var, mod, sce)
        
            # fig, ax = plt.subplots(1,1,figsize=(5, 3))
            # fig.add_subplot(111, frameon=False)
            # plt.tick_params(labelcolor='none', top=False, bottom=False, left=False, 
            #                 right=False) # hide tick and tick label of the big axis
        
            dproj = all_proj_mix.copy()
            
            if var == 'ETP':
                var = 'ETP_'
            
            if (var == 'PPTT') or (var == 'SNOWPROP') or (var == 'PLIQ') or (var == 'PE'):
                dproj = dproj.filter(regex=mod_keep_pptt).filter(regex=var).filter(regex=sce)
            else:
                dproj = dproj.filter(regex=mod_keep).filter(regex=var).filter(regex=sce)
            
            df = dproj.copy()

            if sce=='historic':
                # space = 10
                f = 1980
                l = 2004
            else:
                f = 2010
                l = 2099
            
            space = 10

            df = select_period(df, f, l)
            
            dates = np.arange(f+space,l+1,1)
            n = len(dates)
            
            move = df.copy()
            move[var+'_'+'MOD-MIX'+'_'+sce] = move.mean(axis=1)
            move = move[var+'_'+'MOD-MIX'+'_'+sce].to_frame()
            move['year'] = move.index.year
            move['month'] = move.index.month
            
            need = move.copy()
            if (var == 'TASM') or (var == 'SNOWPROP') or (var == 'SWE') or (var == 'SWI'):
                yearly = need.groupby([(need.index.month),(need.index.to_period("Y"))]).mean()
                intm = df.resample('M').mean()#.groupby([lambda x: x.month]).mean()
            else:
                yearly = need.groupby([(need.index.month),(need.index.to_period("Y"))]).sum()
                intm = df.resample('M').sum()#.groupby([lambda x: x.month]).mean()
                
            intm = intm.groupby([lambda x: x.month]).mean()
            if sce == 'historic':
                intmh = intm.copy()

            rol = True
            # space = 10
            
            dictio = {}
            for per in range(1,12+1):
                dictio[per] = yearly[yearly.index.get_level_values(0) == per]
                dictio[per] = dictio[per].copy()
                if rol == True :
                    dictio[per] = dictio[per].rolling(window=space).mean().shift()
                    dictio[per]['year'] = (dictio[per].index.get_level_values(1).year).astype(int)
                    dictio[per]['bef'] = dictio[per].year - space
                    dictio[per]['per'] = dictio[per].bef.astype(str) + '-' + dictio[per].year.astype(str)
                else:
                    space = 0
                    dictio[per]['year'] = (dictio[per].index.get_level_values(1).year).astype(int)
                    dictio[per]['bef'] = dictio[per].year
                    dictio[per]['per'] = (dictio[per].index.get_level_values(1).year).astype(str)
            
            df_list = [ v for k,v in dictio.items()] 
            df_rol = pd.concat(df_list ,axis=0)
            df_rol = df_rol.set_index(['year'])
            
            df_slice = df_rol.copy()
        
            for k in range(len(dates)):
                date = dates[k]
                df_per = df_slice[df_slice.index==date] #.groupby(['month']).mean()
                df_per = df_per.reset_index()
                df_per = df_per.sort_values(['month'])
                df_per = df_per.set_index('month')
                df_per = df_per.append(df_per.iloc[[0]])
                df_per.index = np.arange(1,14,1)
                datetxt = str(df_per.bef.iloc[0]) + '-' + str(date)
        
                val = df_per[var+'_'+mod+'_'+sce]
                if sce=='historic':
                    cmap = cm.get_cmap('Greys', n)
                # else: 
                #     cmap = cm.get_cmap('jet', n)
                    # cmap = cm.get_cmap('RdBu_r', n)
                if sce=='RCP26':
                    cmap = cm.get_cmap('Blues', n)
                if sce=='RCP45':
                    cmap = cm.get_cmap('Oranges', n)
                if sce=='RCP85':
                    cmap = cm.get_cmap('Reds', n)
                        
                ax.plot(val, color=cmap(k), lw=1, marker=None, markersize=5, label=datetxt)
                
                ax.yaxis.set_major_formatter(ScalarFormatter())
                ax.set_xlim(1,12)
        
                ax.tick_params(axis='both', which='major', pad=10)
                x1 = np.arange(1,12+1,1)
        
                squad = ['J','F','M','A','M','J','J','A','S','O','N','D']
                ax.set_xticks(x1)
                ax.set_xticklabels(squad, minor=False, rotation='horizontal')
                
                # ax.set_title(var+'_'+mod+'_'+sce, fontsize=10)
                
                ax.grid(True)
        
            # ax.plot(val_hist, color=cmap(k), lw=2, marker=None, markersize=5, label=datetxt)
            
            # dprojh = all_proj_mix.copy()
            
            # if var == 'PPTT':
            #     dprojh = dprojh.filter(regex=mod_keep_pptt).filter(regex=var).filter(regex='historic')
            # else:
            #     dprojh = dprojh.filter(regex=mod_keep).filter(regex=var).filter(regex='historic')
            # dfh = dproj.copy()
            # fh = 1960
            # lh = 2010
            # dfh = select_period(dfh, fh, lh)
            # intmh = dfh.resample('M').sum()#.groupby([lambda x: x.month]).mean()
            # intmh = intmh.groupby([lambda x: x.month]).mean()
            ax.plot(intmh.mean(axis=1), color='k', lw=2, ls='--', marker=None, markersize=5, label=datetxt)
            
            # ax.legend(bbox_to_anchor=(1.05, 0.50), loc='center left',
            #           frameon=True, prop={'size': 6.8})
    
    fig.suptitle(var,fontsize=10)
    fig.tight_layout()

    # fig.savefig('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_figures_paper/_v0/c_sup_models/'+
    #             'CHANG_'+var+'-'+sce+'_h'+'.png',
    #                         bbox_inches='tight')

#%% ---- STUDY SITE

#%% GEOMORPHONS PROCESS

wbt.geomorphons(
    'E:/_RONAN/_E_SIMULATIONS/LASSET/Lasset_25m/results_stable/geographic/watershed_box_buff_dem.tif', 
    'E:/_RONAN/_E_SIMULATIONS/LASSET/Lasset_25m/results_stable/geographic/geomorphons.tif', 
    search=10, # in cell
    threshold=10, # angle in degree
    fdist=0, # in cell  
    skip=1, # in cell
    forms=True, 
    residuals=False, 
)

wbt.slope(
    'E:/_RONAN/_E_SIMULATIONS/LASSET/Lasset_25m/results_stable/geographic/watershed_box_buff_dem.tif', 
    'E:/_RONAN/_E_SIMULATIONS/LASSET/Lasset_25m/results_stable/geographic/watershed_box_buff_slope_percent.tif', 
    zfactor=None, 
    units="percent")

wbt.slope(
    'E:/_RONAN/_E_SIMULATIONS/LASSET/Lasset_25m/results_stable/geographic/watershed_box_buff_dem.tif', 
    'E:/_RONAN/_E_SIMULATIONS/LASSET/Lasset_25m/results_stable/geographic/watershed_box_buff_slope_degrees.tif', 
    zfactor=None, 
    units="degrees")

col_list = ['dodgerblue','darkorange','red']
sce_list = ['RCP26','RCP45','RCP85']
# sce_list = ['RCP85']
dict_scecol = dict(zip(sce_list, col_list))# sce_list = ['RCP85']


stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
color = 'k'
BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=dem_path, 
                              out_path=out_path,
                              load=True)
mask = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
mask_lasset = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
mask_grenou = imageio.imread(stable_folder+'subbasin/subbasin_Qgrenou/'+'watershed_dem.tif')
mask_bombee = imageio.imread(stable_folder+'subbasin/subbasin_Qbombee/'+'watershed_dem.tif')
mask_breton = imageio.imread(stable_folder+'subbasin/subbasin_Qbreton/'+'watershed_dem.tif')
dem_box = imageio.imread(stable_folder+'geographic/'+'watershed_box_buff_dem.tif')
area = BV.geographic.area
area = int(round(area))

df_geomorpho = pd.DataFrame()

for pidx, pzone in enumerate(['subbasin_Qlasset','subbasin_Qbreton','subbasin_Qgrenou','subbasin_Qbombee']):
# for pidx, pzone in enumerate(['subbasin_Qgrenou']):

    # print(pzone)    
    # ax = axs[pidx]
   
    # subbasin_Qbreton
    # subbasin_Qgrenou
    # subbasin_Qbombee
    # Smod = pd.read_csv(BV.simulations_folder+'/'+model_name+'/_subbasins/'+pzone+'/_simulated_timeseries_bis.csv', sep=';',
    #                     index_col='date', parse_dates=True)

    if pidx == 0:
        themask = (mask_lasset < 0)
        axes_man = [2800,1600]
    if pidx == 1:
        themask = (mask_breton < 0)
        axes_man = [600,500]
    if pidx == 2:
        themask = (mask_grenou < 0)
        axes_man = [1200,500]
    if pidx == 3:
        themask = (mask_bombee < 0)
        axes_man = [800,500]
    
    if pzone == 'subbasin_Qlasset':
        path_pol = 'E:/_RONAN/_E_SIMULATIONS/LASSET/Lasset_25m/results_stable/geographic/'+'watershed.shp'
        path_rat = 'E:/_RONAN/_E_SIMULATIONS/LASSET/Lasset_25m/results_stable/geographic/'+'watershed_dem.tif'
    else:
        path_pol = 'E:/_RONAN/_E_SIMULATIONS/LASSET/Lasset_25m/results_stable/subbasin/'+pzone+'/'+'watershed.shp'
        path_rat = 'E:/_RONAN/_E_SIMULATIONS/LASSET/Lasset_25m/results_stable/subbasin/'+pzone+'/'+'watershed_dem.tif'
    sub_shp = gpd.read_file(path_pol)
    sub_area = sub_shp.area
    sub_length = sub_shp.length
    
    sub_dem = imageio.imread(path_rat)
    sub_dem = np.ma.masked_array(sub_dem, mask=sub_dem<0)
    sub_dem_cell = sub_dem.count()
    # print(sub_dem_cell)
    
    wbt.polygon_short_axis(
    path_pol, 
    'E:/_RONAN/_E_SIMULATIONS/LASSET/Lasset_25m/results_stable/geographic/'+'watershed_short_'+pzone+'.shp')
    short_shp = gpd.read_file('E:/_RONAN/_E_SIMULATIONS/LASSET/Lasset_25m/results_stable/geographic/'+'watershed_short_'+pzone+'.shp')
    
    wbt.polygon_long_axis(
    path_pol, 
    'E:/_RONAN/_E_SIMULATIONS/LASSET/Lasset_25m/results_stable/geographic/'+'watershed_long_'+pzone+'.shp')
    long_shp = gpd.read_file('E:/_RONAN/_E_SIMULATIONS/LASSET/Lasset_25m/results_stable/geographic/'+'watershed_long_'+pzone+'.shp')
    
    fig, ax = plt.subplots(1,1)
    sub_shp.plot(ax=ax, facecolor='None')
    short_shp.plot(ax=ax)
    long_shp.plot(ax=ax)
    
    
    # excent_ratio = long_shp.length / short_shp.length
    # excent_ratio = np.sqrt(abs(long_shp.length**2 - short_shp.length**2)) / short_shp.length**2
    # excent_ratio = np.sqrt(1-((short_shp.length/long_shp.length)**2))
    excent_ratio = np.sqrt(1-((axes_man[1]/axes_man[0])**2))
    
    gravel = sub_length / (2* np.sqrt(math.pi*sub_area))
    
    sl_per = imageio.imread('E:/_RONAN/_E_SIMULATIONS/LASSET/Lasset_25m/results_stable/geographic/watershed_box_buff_slope_percent.tif')
    sl_per = np.ma.masked_array(sl_per, mask=themask)
    
    sl_deg = imageio.imread('E:/_RONAN/_E_SIMULATIONS/LASSET/Lasset_25m/results_stable/geographic/watershed_box_buff_slope_degrees.tif')
    sl_deg = np.ma.masked_array(sl_deg, mask=themask)
    
    s_dem = imageio.imread('E:/_RONAN/_E_SIMULATIONS/LASSET/Lasset_25m/results_stable/geographic/watershed_box_buff_dem.tif')
    s_dem = np.ma.masked_array(s_dem, mask=themask)
    
    # s_per = imageio.imread('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_data/_hydrography/_newhydro_v2/streams_mix_peren_upv2.tif')
    # s_per = np.ma.masked_array(s_per, mask=themask)
    # s_per = np.ma.masked_array(s_per, mask=s_per<0)
    # s_per = s_per.count()
    # w_per = imageio.imread('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_data/_hydrography/_newhydro_v2/wetlands_mix_peren_upv2.tif')
    # w_per = np.ma.masked_array(w_per, mask=themask)
    # w_per = np.ma.masked_array(w_per, mask=w_per<0)
    # w_per = w_per.count()
    # s_int = imageio.imread('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_data/_hydrography/_newhydro_v2/streams_mix_inter_upv2.tif')
    # s_int = np.ma.masked_array(s_int, mask=themask)
    # s_int = np.ma.masked_array(s_int, mask=s_int<0)
    # s_int = s_int.count()
    # w_int = imageio.imread('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_data/_hydrography/_newhydro_v2/wetlands_mix_inter_upv2.tif')
    # w_int = np.ma.masked_array(w_int, mask=themask)
    # w_int = np.ma.masked_array(w_int, mask=w_int<0)
    # w_int = w_int.count()
    
    """
    pi = imageio.imread('E:/_RONAN/_E_SIMULATIONS/LASSET/Lasset_25m/results_calibration/e_isba2_model6_30.0-0-2.86e-06_4_60.0-1.0-1.02e-06/_postprocess/_rasters/persistency_index_t(-).tif')
    s_per = np.ma.masked_array(pi, mask=themask)
    s_per = np.ma.masked_array(s_per, mask=sub_dem<0)
    s_per = np.ma.masked_array(s_per, mask=s_per<1)
    s_per = np.ma.masked_array(s_per, mask=s_per<0)
    # fig, ax = plt.subplots(1,1)
    # # ax.imshow(themask)
    # ax.imshow(s_per)
    s_per = s_per.count()
    s_int = np.ma.masked_array(pi, mask=themask)
    s_int = np.ma.masked_array(s_int, mask=sub_dem<0)
    s_int = np.ma.masked_array(s_int, mask=s_int>=1)
    s_int = np.ma.masked_array(s_int, mask=s_int<0)
    # fig, ax = plt.subplots(1,1)
    # ax.imshow(themask)
    # ax.imshow(s_per)
    s_int = s_int.count()
    """
    
    print(pzone,
          # round(s_dem.min(), 2),
          # round(s_dem.mean(), 2),
          round(s_dem.mean(), 2),
          round(s_dem.max()-s_dem.min(), 2),
          round(sub_area[0]/1e6, 2),
          round(sl_per.mean(), 2),
          round(sl_deg.mean(), 2),
          round((gravel[0]), 2),
          round((excent_ratio), 2),
          # round((s_per+w_per)/sub_dem_cell,2) )
          # round((25*(s_per+w_per)/1000)/(sub_area[0]/1e6), 2),
          # round(((25*(s_int+w_int)/1000)/(sub_area[0]/1e6))-(25*(s_per+w_per)/1000)/(sub_area[0]/1e6), 2) )
          # round(100*s_per/sub_dem_cell, 5),
          # round(100*s_int/sub_dem_cell, 5)
          )
    
    df_geomorpho.loc[pzone,'dem_mean'] = round(s_dem.mean(), 2)
    df_geomorpho.loc[pzone,'dem_grad'] = round(s_dem.max()-s_dem.min(), 2)
    df_geomorpho.loc[pzone,'area'] = round(sub_area[0]/1e6, 2)
    df_geomorpho.loc[pzone,'slope_per'] = round(sl_per.mean(), 2)
    df_geomorpho.loc[pzone,'slope_deg'] = round(sl_deg.mean(), 2)
    df_geomorpho.loc[pzone,'gravelius'] = round((gravel[0]), 2)
    df_geomorpho.loc[pzone,'excentricity'] = round((excent_ratio), 2)
    
df_geomorpho.to_csv('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_figures_paper/_v0/01_fig_locali/'+
                'df_geomorpho_v1.csv', sep=';', encoding='utf-8', decimal=',')

#%% GEOMORPHONS TABLE

wbt.geomorphons(
    'E:/_RONAN/_E_SIMULATIONS/LASSET/Lasset_25m/results_stable/geographic/watershed_box_buff_dem.tif', 
    'E:/_RONAN/_E_SIMULATIONS/LASSET/Lasset_25m/results_stable/geographic/geomorphons.tif', 
    search=40, # in cell
    threshold=0, # angle in degree
    fdist=0, # in cell  
    skip=0, # in cell
    forms=True, 
    residuals=True, 
)

idx_geom_list = ['0','1','2','3','4','5','6','7','8','9','10']
lab_geom_list = ['Null','Flat','Peak summit','Ridge','Shoulder','Spur convex','Slope','Hollow','Footslope','Valley','Pit depression']

import seaborn as sns
from matplotlib.colors import LinearSegmentedColormap
weather = ['0','1','2','3','4','5','6','7','8','9','10']
colors = sns.color_palette("cubehelix", n_colors=len(weather))
cmap1 = LinearSegmentedColormap.from_list("my_colormap", colors)

dict_geom = dict(zip(idx_geom_list, lab_geom_list))
dict_geomcol = dict(zip(idx_geom_list, lab_geom_list))

mask_lasset = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
mask_grenou = imageio.imread(stable_folder+'subbasin/subbasin_Qgrenou/'+'watershed_dem.tif')
mask_bombee = imageio.imread(stable_folder+'subbasin/subbasin_Qbombee/'+'watershed_dem.tif')
mask_breton = imageio.imread(stable_folder+'subbasin/subbasin_Qbreton/'+'watershed_dem.tif')

imgeo = imageio.imread('E:/_RONAN/_E_SIMULATIONS/LASSET/Lasset_25m/results_stable/geographic/geomorphons.tif')

figt, axt = plt.subplots(1,1)

dfprop = pd.DataFrame()
dfprop.index = range(11)
dfprop['geom_label'] = lab_geom_list

dfprop2 = pd.DataFrame()
dfprop2.index = range(11)
# dfprop2 = dfprop.copy()

# n = 11
# colors = pl.cm.jet(np.linspace(0,1,n))

colors = ['k',
          'darkred',
          'red',
          'white',
          'darkorange',
          'gold',
          'skyblue',
          'skyblue',
          'dodgerblue',
          'navy']
# cmap1 = LinearSegmentedColormap.from_list("my_colormap", colors)

for pidx, pzone in enumerate(['subbasin_Qlasset','subbasin_Qbreton','subbasin_Qgrenou','subbasin_Qbombee']):
    
    masked = imgeo.copy()

    if pzone == 'subbasin_Qlasset':
        mask = mask_lasset
    if pzone == 'subbasin_Qbreton':
        mask = mask_breton   
    if pzone == 'subbasin_Qgrenou':
        mask = mask_grenou
    if pzone == 'subbasin_Qbombee':
        mask = mask_bombee
    
    masked[mask<0] = 0    
    maskedim = np.ma.masked_where(mask<0, masked)
    
    # fig, ax = plt.subplots(1,1)
    # ax.imshow(maskedim)
        
    uniques, counts = np.unique(masked, return_counts=True)
    # print(pzone, uniques, counts)
    # percentages = dict(zip(uniques, counts * 100 / len(masked)))
    
    dftemp = pd.DataFrame()
    dftemp['uniques'] = uniques.astype(int)
    dftemp['counts'] = counts
    # dftemp['percentages'] = percentages
    dftemp = dftemp.set_index('uniques')

    
    dfprop[pzone+'_counts'] = dftemp.loc[dftemp.index,'counts']
    sum_tot = np.nansum(dfprop[pzone+'_counts'][1:])
    dfprop.loc[0,pzone+'_counts'] = sum_tot
    
    dfprop[pzone+'_percentages'] = (dfprop[pzone+'_counts']*100) / sum_tot

    # dfprop[pzone+'_counts'] = counts
    # dfprop[pzone+'_percentages'] = percentages
    
    dfprop2[pzone+'_percentages'] = (dfprop[pzone+'_counts']*100) / sum_tot
    
    x = pidx
    y = dfprop[pzone+'_percentages']
    
    axt.bar(x, y)

dfprop2 = dfprop2.loc[1:]
dfprop2 = dfprop2.T
dfprop2 = dfprop2.round(1)

# figm.savefig('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_figures_paper/_v0/e_geomorph/'+
#             'Bar_v1'+'.png',
#                         bbox_inches='tight')

# colors2 = ['darkred',
#           'red',
#           'darkorange',
#           'gold',
#           'lightskyblue',
#           'dodgerblue',
#           'navy']

# lab_geom_list2 = [
#                  'Peak summit',
#                  'Ridge',
#                  'Spur convex',
#                  'Slope',
#                  'Hollow',
#                  'Valley',
#                  'Pit depression']

colors2 = ['k',
          'darkred',
          'red',
          'darkorange',
          'gold',
          'limegreen',
          'lightskyblue',
          'dodgerblue',
          'navy',
          'darkviolet']

dfprop3 = dfprop2.T
dfprop3[np.isnan(dfprop3)] = 0
# dfprop3 = dfprop3.astype(int)
# dfprop3 = dfprop3.loc[~(dfprop3==0).all(axis=1)]

figps, axps = plt.subplots(1,4, figsize=(5*4,5))
axps = axps.ravel()

for pidx, pzone in enumerate(['subbasin_Qlasset','subbasin_Qbreton','subbasin_Qgrenou','subbasin_Qbombee']):
    
    axp = axps[pidx]
    
    # figp, axp = plt.subplots(1,1, figsize=(5,5))
    axp.pie(dfprop3[pzone+'_percentages'],
            labels=dfprop3.index,
            # labels = lab_geom_list2,
            autopct="%1.0f%%",
            colors=colors2, startangle=90)
    
    print(pzone, dfprop3.loc[:5,pzone+'_percentages'].sum() / dfprop3.loc[5:,pzone+'_percentages'].sum())
    # print(pzone, dfprop3.loc[[6],pzone+'_percentages'].sum() / dfprop3.loc[[7,9,10],pzone+'_percentages'].sum())

figps.savefig('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_figures_paper/_v0/e_geomorph/'+
            'Pie_v1'+'.png',
                        bbox_inches='tight')

dfprop4 = dfprop3.T

figm, axm = plt.subplots(1,1, figsize=(4,6))
axm.set_ylim(0,100)
dfprop4.plot(ax=axm, kind='bar', stacked=True,
                # colormap='jet_r', 
                color=colors2,
              legend=False)
axm.set_xticklabels(['P1','P2','P3','P4'])
for c in axm.containers:
    col = c.get_label()
    # axm.bar_label(c, label_type='center', fontweight='regular', color='k', fontsize=8,
    #               # fmt='%g'
    #               )

dfprop3.to_csv('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_figures_paper/_v0/e_geomorph/'+
            'dfprop3_geomorphons'+'.csv', sep=';', decimal=',')

figm.savefig('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_figures_paper/_v0/e_geomorph/'+
            'Bar_v1'+'.png',
                        bbox_inches='tight')

#%% ---- 1 - DICHOTOMY

#%% DICHOTOMY - FUNCTION

class MatchingStreams:
    """ 
    
    Class for the calibration based on river occurency
        
    Attributes
    ----------
    
    Methods
    ----------
    
    """

    def __init__(self, 
                 watershed, 
                 iteration_label=None):
        
        self.geographic = watershed.geographic
        self.hydrography = watershed.hydrography
        self.calibration_folder = watershed.calibration_folder
        self.iteration_label = iteration_label
        
        self.watershed_shp = watershed.geographic.watershed_shp
        self.watershed_fill = watershed.geographic.watershed_fill
        self.watershed_direc = watershed.geographic.watershed_direc
              
        self.prepare_files()
        self.sim_to_obs()
        self.obs_to_sim()
        # self.get_indicator()
        
    def prepare_files(self):
        #files are necessary for whiteboxtool
        self.results_folder=os.path.join(self.calibration_folder, self.iteration_label, '_postprocess')
        toolbox.create_folder(self.results_folder)
        # New folder results
        self.dichotomy_folder = os.path.join(self.calibration_folder, self.iteration_label, '_matchingstreams')
        toolbox.create_folder(self.dichotomy_folder)
        
        # Observed buff data
        self.buff_tif_obs = self.hydrography.tif_streams
        # Mask observed
        self.tif_obs = os.path.join(self.dichotomy_folder,'obs.tif')
        toolbox.clip_tif(self.buff_tif_obs, self.watershed_shp, self.tif_obs, False)
        # Obs to points
        self.pt_obs = os.path.join(self.dichotomy_folder, 'obs_pt.shp')
        wbt.raster_to_vector_points(self.tif_obs, self.pt_obs)
        self.pt_obsf = os.path.join(self.dichotomy_folder, 'obs_ptf.shp')
        wbt.raster_to_vector_points(self.tif_obs, self.pt_obsf)
        # Trace downslope obs
        self.obs_flow = os.path.join(self.dichotomy_folder, 'obsflow.tif')
        wbt.trace_downslope_flowpaths(self.pt_obs, self.watershed_direc, self.obs_flow)
        
        # Mask simulated
        tif_sim = os.path.join(self.results_folder,'_rasters','seepage_areas_t(0).tif')
        self.tif_sim = os.path.join(self.dichotomy_folder,'sim.tif')
        toolbox.clip_tif(tif_sim, self.watershed_shp, self.tif_sim, False)
        # Sim to points
        self.pt_sim = os.path.join(self.dichotomy_folder, 'sim_pt.shp')
        wbt.raster_to_vector_points(self.tif_sim, self.pt_sim)
        self.pt_simf = os.path.join(self.dichotomy_folder, 'sim_ptf.shp')
        wbt.raster_to_vector_points(self.tif_sim, self.pt_simf)
        # Trace downslope sim
        self.sim_flow = os.path.join(self.dichotomy_folder, 'simflow.tif')
        wbt.trace_downslope_flowpaths(self.pt_sim, self.watershed_direc, self.sim_flow)
        
    def sim_to_obs(self):
        # Simflow to points
        self.pt_sim_flow = os.path.join(self.dichotomy_folder, 'simflow.shp')
        wbt.raster_to_vector_points(self.sim_flow, self.pt_sim_flow)
        self.pt_sim_flowf = os.path.join(self.dichotomy_folder, 'simflowf.shp')
        wbt.raster_to_vector_points(self.sim_flow, self.pt_sim_flowf)   
        
        # Distance of dem to obs
        self.dist_dem_obs = os.path.join(self.dichotomy_folder, 'dist_dem_obs.tif')
        wbt.downslope_distance_to_stream(self.watershed_fill, self.tif_obs, self.dist_dem_obs)
        
        # Distance of dem to obsflow
        self.dist_dem_obsflow = os.path.join(self.dichotomy_folder, 'dist_dem_obsflow.tif')
        wbt.downslope_distance_to_stream(self.watershed_fill, self.obs_flow, self.dist_dem_obsflow)

        # Sim to Obs and Obsflow
        wbt.add_point_coordinates_to_table(self.pt_sim)
        wbt.extract_raster_values_at_points(self.dist_dem_obs, self.pt_sim)
        wbt.add_point_coordinates_to_table(self.pt_simf)
        wbt.extract_raster_values_at_points(self.dist_dem_obsflow, self.pt_simf)
        # Simflow to Obs and Obsflow
        wbt.add_point_coordinates_to_table(self.pt_sim_flow)
        wbt.extract_raster_values_at_points(self.dist_dem_obs, self.pt_sim_flow)
        wbt.add_point_coordinates_to_table(self.pt_sim_flowf)
        wbt.extract_raster_values_at_points(self.dist_dem_obsflow, self.pt_sim_flowf)

    def obs_to_sim(self):
        # Simflow to points
        self.pt_obs_flow = os.path.join(self.dichotomy_folder, 'obsflow.shp')
        wbt.raster_to_vector_points(self.obs_flow, self.pt_obs_flow)
        self.pt_obs_flowf = os.path.join(self.dichotomy_folder, 'obsflowf.shp')
        wbt.raster_to_vector_points(self.obs_flow, self.pt_obs_flowf)
        
        # Distance of dem to sim
        self.dist_dem_sim = os.path.join(self.dichotomy_folder, 'dist_dem_sim.tif')
        wbt.downslope_distance_to_stream(self.watershed_fill, self.tif_sim, self.dist_dem_sim)
        # Distance of dem to simflow
        self.dist_dem_simflow = os.path.join(self.dichotomy_folder, 'dist_dem_simflow.tif')
        wbt.downslope_distance_to_stream(self.watershed_fill, self.sim_flow, self.dist_dem_simflow)

        # Obs to Sim and Simflow
        wbt.add_point_coordinates_to_table(self.pt_obs)
        wbt.extract_raster_values_at_points(self.dist_dem_sim, self.pt_obs)
        wbt.add_point_coordinates_to_table(self.pt_obsf)
        wbt.extract_raster_values_at_points(self.dist_dem_simflow, self.pt_obsf)
        # Obsflow to Sim and Simflow
        wbt.add_point_coordinates_to_table(self.pt_obs_flow)
        wbt.extract_raster_values_at_points(self.dist_dem_sim, self.pt_obs_flow)
        wbt.add_point_coordinates_to_table(self.pt_obs_flowf)
        wbt.extract_raster_values_at_points(self.dist_dem_simflow, self.pt_obs_flowf)

#%% DICHOTOMY - RUN

vers = 'aniso1'
types_obs = ['hydrographic_mix_peren_upv2_pt']
fields_obs = ['fid']
hydrography_path = data_path + '_hydrography/' # add hydrographic shapefiles

box = True # or False
sink_fill = False # or True
sim_state = 'steady' # 'steady' or 'transient'
plot_cross = False
check_grid = True
dis_perlen = True
nlay = 10
lay_decay = 1.25 # 1 for no decay
thick = 30 # if bottom is None, aquifer thickness
recharge = select_period(rea_recharge_isba, 2020, 2023)
#print((recharge).mean()*365*1000)
first_clim = 'mean' # or 'first or value
verti_hk = None # or [ [1e-5, [0, 20]],
verti_sy = None
verti_ss = None
cond_drain = None # or value of conductance
Kmin = 1e-10 * 3600 * 24 
Klog_transf = False
sy = 5 / 100 # -
sy_decay = 0 # exponential decay : 1/20 (half decrease at 20m)
ss = 1e-5
ss_decay = 0 # exponential decay : 1/20 (half decrease at 20m)
bc_left = None # or value
bc_right = None # or value
sea_level = 'None' # or value based on specific data : BV.oceanic.MSL
zone_partic = 'domain' # or watershed
vka = 1

for watershed_name in watershed_names[:]:
            
    for type_obs, field_obs in zip(types_obs[:], fields_obs[:]):
   
        print('##### '+watershed_name.upper()+' #####')
        
        df = pd.DataFrame()
        
        BV = watershed_root.Watershed(watershed_name=watershed_name, dem_path=dem_path, out_path=out_path, load=True)
        area = BV.geographic.area

        stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
        simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' # necessary for plots
        BV.calibration_folder = os.path.join(out_path, watershed_name, 'results_calibration')
        toolbox.create_folder(BV.calibration_folder)
        
        if not os.path.exists(stable_folder + 'hydrography/' + type_obs + '.tif'):
            BV.add_hydrography(hydrography_path, types_obs=[type_obs], fields_obs=[field_obs])
        else:
            BV.hydrography.streams = stable_folder + 'hydrography/' + type_obs + '.shp'
            BV.hydrography.tif_streams = stable_folder + 'hydrography/' + type_obs + '.tif'
                
        BV.add_settings()
        BV.add_climatic()
        BV.add_hydraulic()
        
        BV.settings.update_box_model(box)
        BV.settings.update_sink_fill(sink_fill)
        BV.settings.update_simulation_state(sim_state)
        BV.settings.update_check_model(plot_cross=plot_cross, check_grid=check_grid)
        BV.climatic.update_recharge(recharge, sim_state=sim_state)
        BV.climatic.update_first_clim(first_clim)
        BV.hydraulic.update_nlay(nlay) # 1
        BV.hydraulic.update_lay_decay(lay_decay) # 1
        BV.hydraulic.update_thick(thick) # 30 / intervient pas si bottom != None

        BV.hydraulic.update_cond_drain(cond_drain)
        BV.hydraulic.update_sy(sy)
        BV.hydraulic.update_sy_decay(sy_decay)
        BV.hydraulic.update_ss(ss)
        BV.hydraulic.update_ss_decay(ss_decay)
        BV.hydraulic.update_vka(vka)

        BV.hydraulic.update_hk_vertical(verti_hk)
        BV.hydraulic.update_sy_vertical(verti_sy)
        BV.hydraulic.update_ss_vertical(verti_ss)
        
        BV.add_oceanic(sea_level)
        BV.settings.update_dis_perlen(dis_perlen)
        BV.settings.update_bc_sides(bc_left, bc_right)
        BV.settings.update_input_particles(zone_partic=zone_partic)

        # Aquifer bottom
        list_bottom = [1000] * 9 # aquifer flat or not
        # Decay of K
        list_d_values = [0, 300, 200, 100, 50, 40, 30, 20, 10]
        list_cond_decay = list(1/np.array(list_d_values))      
        list_cond_decay[0] = 0
        list_id_mod = [1,2,3,4,5,6,7,8,9]
        
        # for hk_decay, bottom, id_mod in zip(list_cond_decay[12:13], list_bottom[12:13], list_id_mod[12:13]):
        # for hk_decay, bottom, id_mod in zip(list_cond_decay[10:11], list_bottom[10:11], list_id_mod[10:11]):
        # for hk_decay, bottom, id_mod in zip(list_cond_decay[11:12], list_bottom[11:12], list_id_mod[11:12]):
        # for hk_decay, bottom, id_mod in zip(list_cond_decay[9:10], list_bottom[9:10], list_id_mod[9:10]):
        for hk_decay, bottom, id_mod in zip(list_cond_decay[-1:], list_bottom[-1:], list_id_mod[-1:]):

        # for cond_decay, bottom, id_mod in zip([1/25], [0], [4.5]):
            
            BV.hydraulic.update_hk_decay(hk_decay, min_value=Kmin, log_transf=Klog_transf) # 0
            BV.hydraulic.update_bottom(bottom) # 0
            
            params_df = pd.DataFrame(columns=['params','init_values','lower_bounds','higher_bounds','units','scale'])
            if id_mod <= 3 :
                params_df.loc[0] = ['k1','?',1e-10*3600*24,1e-6*3600*24,'m/j','lin'] ### K/R 0.36 to 36 000
            if id_mod == 4 :
                params_df.loc[0] = ['k1','?',1e-9*3600*24,1e-5*3600*24,'m/j','lin'] ### K/R 0.36 to 36 000
            if id_mod > 4 :
                params_df.loc[0] = ['k1','?',1e-8*3600*24,1e-4*3600*24,'m/j','lin'] ### K/R 0.36 to 36 000
            if id_mod >= 8 :
                params_df.loc[0] = ['k1','?',1e-6*3600*24,1e-4*3600*24,'m/j','lin'] ### K/R 0.36 to 36 000
            params_file = 'calib_dicot_hom_1v_k1'
            params_df.to_csv(BV.calibration_folder+'/'+params_file+'.csv', sep=';', index=None)
            
            p_min = params_df['lower_bounds'].values[0]
            p_max = params_df['higher_bounds'].values[0]
            diff = p_max - p_min
            half = (p_min + p_max) / 2
            
            gap = 1.0
            
            compt = 0
            
            while (diff > ((gap/100) * half)):
                
                half = (p_min + p_max) / 2
                hyd_cond = half.copy() # if K in calib_params.csv
                kr = hyd_cond / BV.climatic.recharge
                            
                BV.hydraulic.update_hk(hyd_cond)
                
                now = datetime.now()
                oclock = now.strftime("%Y%m%d_%Hh%Mm%Ss") 
                
                if id_mod <=1 :
                    str_hk_decay = hk_decay
                else:
                    str_hk_decay = 1/hk_decay
                if bottom==None:
                    model_name = vers+'_'+str('model')+str(id_mod)+'_'+str(round(str_hk_decay,4))+'-'+str(round(thick,4))+'_'+str(compt)+'-'+str("{:.2e}".format(hyd_cond/24/3600)) #+'-'+oclock
                else:
                    model_name = vers+'_'+str('model')+str(id_mod)+'_'+str(round(str_hk_decay,4))+'-'+str(round(bottom,4))+'_'+str(compt)+'-'+str("{:.2e}".format(hyd_cond/24/3600)) #+'-'+oclock
                BV.settings.update_model_name(model_name)
                print(model_name)
                                
                model_modflow = BV.preprocessing_modflow(for_calib=True) # BV.calibration_folder
                success_modflow = BV.processing_modflow(model_modflow, write_model=True, run_model=True)
                
                BV.postprocessing_modflow(model_modflow,
                                          watertable_elevation = True,
                                          watertable_depth= True, 
                                          seepage_areas = True,
                                          outflow_drain = True,
                                          groundwater_flux = True,
                                          groundwater_storage = True,
                                          accumulation_flux = True,
                                          export_all_tif = False)
    
                timeseries_results = BV.postprocessing_timeseries(model_modflow=model_modflow,
                                                                  model_modpath=None,
                                                                  datetime_format=False, 
                                                                  subbasin_results=True) # or None
            
                iter_results = MatchingStreams(BV, iteration_label=model_name)
                
                obs_to_sim = gpd.read_file(os.path.join(BV.calibration_folder, model_name, '_matchingstreams','obs_pt.shp'))
                obs_to_simf = gpd.read_file(os.path.join(BV.calibration_folder, model_name, '_matchingstreams','obs_ptf.shp'))
                obsf_to_sim = gpd.read_file(os.path.join(BV.calibration_folder, model_name, '_matchingstreams','obsflow.shp'))
                obsf_to_simf = gpd.read_file(os.path.join(BV.calibration_folder, model_name, '_matchingstreams','obsflowf.shp'))
                
                sim_to_obs = gpd.read_file(os.path.join(BV.calibration_folder, model_name, '_matchingstreams','sim_pt.shp'))
                sim_to_obsf = gpd.read_file(os.path.join(BV.calibration_folder, model_name, '_matchingstreams','sim_ptf.shp'))
                simf_to_obs = gpd.read_file(os.path.join(BV.calibration_folder, model_name, '_matchingstreams','simflow.shp'))
                simf_to_obsf = gpd.read_file(os.path.join(BV.calibration_folder, model_name, '_matchingstreams','simflowf.shp'))
            
                mean_obs_to_sim = np.nanmean(obs_to_sim[obs_to_sim['VALUE1']>=0]['VALUE1'])
                mean_obs_to_simf = np.nanmean(obs_to_simf[obs_to_simf['VALUE1']>=0]['VALUE1'])
                mean_obsf_to_sim = np.nanmean(obsf_to_sim[obsf_to_sim['VALUE1']>=0]['VALUE1'])
                mean_obsf_to_simf = np.nanmean(obsf_to_simf[obsf_to_simf['VALUE1']>=0]['VALUE1'])
                
                mean_sim_to_obs = np.nanmean(sim_to_obs[sim_to_obs['VALUE1']>=0]['VALUE1'])
                mean_sim_to_obsf = np.nanmean(sim_to_obsf[sim_to_obsf['VALUE1']>=0]['VALUE1'])
                mean_simf_to_obs = np.nanmean(simf_to_obs[simf_to_obs['VALUE1']>=0]['VALUE1'])
                mean_simf_to_obsf = np.nanmean(simf_to_obsf[simf_to_obsf['VALUE1']>=0]['VALUE1'])
                
                ### v1 simf/obsf - with : gap=1, streams : RNF, rec : 1000 (year)
                # obs = mean_obsf_to_simf
                # sim = mean_simf_to_obsf
                # indicator = sim/obs
                
                ### v2 simf/obs - with : gap=1, streams : RNF, rec : 1000 (year)
                # obs = mean_obs_to_simf
                # sim = mean_simf_to_obs
                # indicator = sim/obs
                # indicator = (np.log(self.mean_sim_to_obs/self.mean_obs_to_sim))**2
                
                ### v3 simf/obsf - with : gap=0.5, streams : RNF, rec : 600 (summer)
                # obs = mean_obsf_to_simf
                # sim = mean_simf_to_obsf
                # indicator = sim/obs
                
                ### v4 simf/obsf - with : gap=0.5, streams : RNF+OSM, rec : 600 (summer)
                # obs = mean_obsf_to_simf
                # sim = mean_simf_to_obsf
                # indicator = sim/obs
                
                ### v6 simf/obsf - with : gap=0.5, streams : RNF, rec : 1000 (year)
                # obs = mean_obsf_to_simf
                # sim = mean_simf_to_obsf
                # indicator = sim/obs
                
                ### vf simf/obsf - with : gap=0.5, streams : RNF, rec : 1000 (year) ==> isba
                obs = mean_obsf_to_simf
                sim = mean_simf_to_obsf
                indicator = sim/obs
            
                if sim > obs:
                    p_min = half
                if sim < obs:
                    p_max = half
                if np.isnan(indicator):
                    p_max = half
                
                diff = p_max - p_min
                
                print('==> Simulation : '+str(compt))
                print('    K/R = '+str(round(kr, 4)))
                print('    Gap = '+str(round((gap/100) * kr, 4)))
                print('    Indicator = '+str(round(indicator, 4)))
                
                df.loc[compt,'id_mod'] = id_mod
                df.loc[compt,'compt'] = compt
                
                df.loc[compt,'model_name'] = model_name
                df.loc[compt,'type_obs'] = type_obs
                df.loc[compt,'oclock'] = oclock
                
                df.loc[compt,'KR'] = round(kr, 4)
                df.loc[compt,'K'] = round(hyd_cond, 4)
                df.loc[compt,'R'] = round(BV.climatic.recharge*1000, 4) # mm
                df.loc[compt,'K_decay'] = round(hk_decay, 4) # mm
                if bottom == None:
                    df.loc[compt,'bottom'] = round(thick, 4) 
                else:
                    df.loc[compt,'bottom'] = round(bottom, 4) 
        
                df.loc[compt,'Obs'] = round(obs, 4)
                df.loc[compt,'Sim'] = round(sim, 4)
                df.loc[compt,'Indicator'] = round(indicator, 4)
                
                df.loc[compt,'mean_obs_to_sim'] = round(mean_obs_to_sim, 4)
                df.loc[compt,'mean_obs_to_simf'] = round(mean_obs_to_simf, 4)
                df.loc[compt,'mean_obsf_to_sim'] = round(mean_obsf_to_sim, 4)
                df.loc[compt,'mean_obsf_to_simf'] = round(mean_obsf_to_simf, 4)
                
                df.loc[compt,'mean_sim_to_obs'] = round(mean_sim_to_obs, 4)
                df.loc[compt,'mean_sim_to_obsf'] = round(mean_sim_to_obsf, 4)
                df.loc[compt,'mean_simf_to_obs'] = round(mean_simf_to_obs, 4)
                df.loc[compt,'mean_simf_to_obsf'] = round(mean_simf_to_obsf, 4)
                
                compt += 1
                            
            df.to_csv(BV.calibration_folder+'/'+vers+'_'+str('model')+str(id_mod)+'_dichotomy.csv', sep=';')

            id_mod += 1
            
#%% DICHOTOMY - APPEND

vers = 'aniso1'

BV = watershed_root.Watershed(watershed_name=watershed_name, dem_path=dem_path, out_path=out_path, load=True)
BV.calibration_folder = os.path.join(out_path, watershed_name, 'results_calibration')

dfs = pd.DataFrame()

raws_model = glob.glob(BV.calibration_folder+'/'+vers+'_'+'*.csv')
paths_model = sorted(raws_model,
                     key=lambda item: float(item.split('\\')[-1].split('_')[1].split('model')[-1]))

for path_model in paths_model:
    print(path_model)

    df = pd.read_csv(path_model, sep=';')
        
    dfs = pd.concat([dfs, df], ignore_index = True).drop_duplicates()

dfs['Doptim'] = (dfs['Obs'] + dfs['Sim'])/2
dfs['1/K_decay'] = 1/dfs['K_decay']
dfs['1/K_decay'][dfs['1/K_decay'] == np.inf] = 0

dfs.to_csv(BV.calibration_folder+'/'+'_models'+'_dichotomy_'+vers+'.csv', sep=';')

list_id_mod = [1,2,3,4,5,6,7,8,9]

#%% DICHOTOMY - GRAPH K

dfp = dfs.copy()

dfp['Doptim'] = ((dfp['Obs']+dfp['Sim'])/2)

# list_id_mod = [7]
dfz = pd.DataFrame()
for i in list_id_mod[:]:
    dft = dfp[dfp['id_mod']==i]
    # dfz = pd.concat([dfz, dft.iloc[-1:]])
    dfz = pd.concat([dfz, dft.iloc[(dft['Indicator']-1).abs().argsort()[:1]]])
 
dfz.to_csv(BV.calibration_folder+'/'+'_models'+'_optimum_'+vers+'.csv', sep=';')

# dfz = dfz.drop(index=dfz.iloc[:1,:].index.tolist())

# fig, ax = plt.subplots(1,1, figsize=(3.6,2.6), dpi=600)
fig, ax = plt.subplots(1,1, figsize=(4.2,4), dpi=600)

dfz.loc[93,'Doptim'] = dfz.loc[93,'Doptim']+2

# im = ax.scatter(df.k, (df.Dso+df.Dos)/2, c=df.cond_decay, s=100, cmap='jet')
# ax.scatter(dfz[:1]['K']/24/3600, dfz[:1]['Doptim'], s=100, 
#             marker='s', lw=1.5, color='white', ec='k', zorder=1000
#             # cmap=mpl.colors.ListedColormap('k'),
#             # label=dfz['1/K_decay'].values[0]
#             )

ax.scatter(dfz[:1]['K']/24/3600, dfz[:1]['Doptim'],
            c=dfz[:1]['1/K_decay'],
            s=100, 
              marker='s', lw=1.5,
              cmap=mpl.colors.ListedColormap('gray'), zorder=1000
            # label='0'
            )
im = ax.scatter(dfz[1:]['K']/24/3600, dfz[1:]['Doptim'], c=1/dfz[1:]['1/K_decay'], s=100, 
                cmap='plasma',
                norm=mpl.colors.LogNorm(vmin=1/300, vmax=1/10),
                lw=1.5,
                # label=df['1/cond_decay'] 
                )

dftempo = dfz.sort_values('K')
ax.plot(dftempo[:]['K']/24/3600, dftempo[:]['Doptim'],
             # c=dfz[2:]['1/K_decay'], s=100, 
             #    cmap='plasma_r',
                  # norm=mpl.colors.LogNorm(vmin=1/300, vmax=1/10),
                lw=1, c='k', zorder=-10, ls='-'
                # label=df['1/cond_decay'] 
                )

# ax.plot(dftempo[:]['K']/24/3600, dftempo[:]['Sim'],
#              # c=dfz[2:]['1/K_decay'], s=100, 
#              #    cmap='plasma_r',
#              #    norm=mpl.colors.LogNorm(vmin=10, vmax=300),
#                 lw=1, c='grey', zorder=-10, ls='-'
#                 # label=df['1/cond_decay'] 
#                 )

# ax.legend()
ax.set_xscale('log')
# ax.set_yscale('log')
ax.set_xlabel('$K_{max}$ [m/s]')
ax.set_xlim(1e-7, 1e-5)
ax.set_ylim(25 , 100)
ax.set_ylabel('$D_{optim}$ [m]')
# cb = plt.colorbar()
from matplotlib.ticker import LogFormatter 
formatter = LogFormatter(10, labelOnlyBase=True) 
cb = plt.colorbar(im, ax=ax,
                  cax = fig.add_axes([0.95, 0.10, 0.03, 0.8]))
# for t in cb.ax.get_yticklabels():
#      t.set_fontsize(10)
# cb.set_clim(10,500)
# cb.set_ticks(np.geomspace(10, 300, 10).astype(int))
# cb.set_ticklabels(np.geomspace(10, 300, 10).astype(int))
# cb.set_ticks([10, 15, 20, 30, 45, 65, 100, 140, 205, 300])
# cb.set_ticklabels([10, 15, 20, 30, 45, 65, 100, 140, 205, 300])
# cb.set_ticks((1/np.array([300, 200, 100, 50, 40, 30])).round(4))
# cb.set_ticklabels((1/np.array([300, 200, 100, 50, 40, 30])).round(3), fontsize=8)

# cb.ax.tick_params(direction='out', length=5, width=1, colors='k',
#                   grid_color='k', grid_alpha=0.5)
for t in cb.ax.get_yticklabels():
     t.set_fontsize(9)
# cb.minorticks_off(False)
cb.ax.tick_params(direction='out', which = 'minor', length = 2, color = 'k')
cb.ax.tick_params(direction='out', which = 'major', length = 4, color = 'k' )
cb.ax.minorticks_on()
cb.ax.set_ylabel('1/α [m]', rotation=270, labelpad=25)

ax.axvline(x=(dfz[5:6]['K']/24/3600).values, c='darkgreen', zorder=-1000, ls='-', lw=1.5)
ax.axhline(y=(dfz[5:6]['Doptim']).values, c='darkgreen', zorder=-1000, ls='-', lw=1.5)

# ax.grid()

# ax.set_yscale('log')

fig.savefig(fig_path+'/02_fig_dichotomy/'+
            'DICHOTOMY_K_3'+'.png',
            bbox_inches='tight')

#%% DICHOTOMY - MAPS

BV.calibration_folder = os.path.join(out_path, watershed_name, 'results_calibration')

dfs = pd.read_csv(BV.calibration_folder+'/'+'_models'+'_dichotomy_'+vers+'.csv', sep=';')

dfp = dfs.copy()
dfp['1/K_decay'] = 1/dfp['K_decay']
dfp['1/K_decay'][dfp['1/K_decay'] == np.inf] = 0
dfp['Doptim'] = (dfp['Obs'] + dfp['Sim'])/2

shp_bv = gpd.read_file(BV.geographic.watershed_shp)
  
if vers == 'aniso1':
    shp_hydro = gpd.read_file(stable_folder+'hydrography/'+'hydrographic_mix_peren_upv2_pt.shp')    

dfz = pd.DataFrame()
for i in list_id_mod[:]:
    dft = dfp[dfp['id_mod']==i]
    # dfz = pd.concat([dfz, dft.iloc[-1:]])
    dfz = pd.concat([dfz, dft.iloc[(dft['Indicator']-1).abs().argsort()[:1]]])    

for index, row in dfz[:].iterrows():
    model_name = row['model_name']
    print(model_name)
    
    mf = flopy.modflow.Modflow.load(BV.calibration_folder+'/'+model_name+'/'+model_name+'.nam')
            
    # fname = simulations_folder+model_name+'/'+model_name+'.hds'
    gridname = simulations_folder+model_name+'/'+model_name+'.dis'
    # grid_model = flopy.discretization.grid.Grid(mf)
    grid_model = mf.modelgrid
    
    fig, ax = plt.subplots(1,1, figsize=(10,10))
    
    dem = rasterio.open(stable_folder+'/geographic/watershed_dem.tif')
    # hil = rasterio.open('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_data/_sig/hillshade_classic.tif')

    # rasterio.plot.show(np.ma.masked_where(dem.read(1) < 0, dem.read(1)), 
    #                           ax=ax, transform=dem.transform,
    #                           cmap='Greys_r', alpha=1, zorder=-5)

    rasterio.plot.show(np.ma.masked_where(dem.read(1) < 0, dem.read(1)), 
                              ax=ax, transform=dem.transform,
                              cmap='Greys', alpha=0.25, zorder=-5)
    
    shp = gpd.read_file(BV.calibration_folder+'/'+str(model_name)+'/'+'_matchingstreams/'+'sim_pt.shp')
    
    shp_bv.plot(ax=ax, facecolor='None', lw=3)
    shp_hydro.plot(ax=ax, color='navy', lw=0)
    shp.plot(ax=ax, color='darkorange', lw=0)
    
    plt.yticks(rotation=90, ha='right')
    
    ax.set_title(model_name, fontsize=7)
    
    # fig.savefig('C:/Users/ronan/Downloads/figs/'+'MAPS_'+model_name+'.png',
    #             bbox_inches='tight')
    
    # fig.savefig('C:/Users/ronan/Downloads/figs_'+vers+'/'+'MAPS_'+model_name+'.png',
    #             bbox_inches='tight')
    
    ax.get_xaxis().set_visible(False)
    ax.get_yaxis().set_visible(False)
    ax.axis('off')

    fig.savefig(fig_path+'/02_fig_dichotomy/maps3/'+
                model_name+'_DICHOTOMY_MAP'+'.png',
                bbox_inches='tight')

#%% ---- PLOT MESH GRID 

#%% GRAPH DECAY K - 3D BAD

run = True

# vers = 'isba1'
# vers = 'isbaint1'

vers = 'aniso1'
types_obs = ['hydrographic_mix_peren_upv2_pt']
type_obs = 'hydrographic_mix_peren_upv2_pt'

# vers = 'isbaint2'
# types_obs = ['hydrographic_mix_inter_upv2_pt']

hydrography_path = data_path + '_hydrography/' # add hydrographic shapefiles

# types_obs = ['stream_perennial_wetlands_osm_points']
fields_obs = ['fid']

figk, axk = plt.subplots(1, 1, figsize=(5, 5), dpi=300)

for watershed_name in watershed_names[:]:
               
    print('##### '+watershed_name.upper()+' #####')
    
    df = pd.DataFrame()
    
    BV = watershed_root.Watershed(watershed_name=watershed_name, dem_path=dem_path, out_path=out_path, load=True)
    area = BV.geographic.area
    
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' # necessary for plots
    BV.calibration_folder = os.path.join(out_path, watershed_name, 'results_calibration')
    toolbox.create_folder(BV.calibration_folder)
    
    if not os.path.exists(stable_folder + 'hydrography/' + type_obs + '.tif'):
        BV.add_hydrography(hydrography_path, types_obs=[type_obs], fields_obs=[field_obs])
    else:
        BV.hydrography.streams = stable_folder + 'hydrography/' + type_obs + '.shp'
        BV.hydrography.tif_streams = stable_folder + 'hydrography/' + type_obs + '.tif'
    
    # Aquifer bottom
    list_bottom = [1000] * 9 # aquifer flat or not
    # Decay of K
    list_d_values = [0, 300, 200, 100, 50, 40, 30, 20, 10]
    list_cond_decay = list(1/np.array(list_d_values))      
    list_cond_decay[0] = 0
    list_id_mod = [1,2,3,4,5,6,7,8,9]
       
    # for cond_decay, bottom, id_mod in zip(list_cond_decay[4:5], list_bottom[4:5], list_id_mod[4:5]):
    # for cond_decay, bottom, id_mod in zip(list_cond_decay[:], list_bottom[:], list_id_mod[:]):
            
dfz = pd.read_csv(BV.calibration_folder+'/'+'_models'+'_optimum_'+vers+'.csv', sep=';')

n = 8
# colors = pl.cm.jet(np.linspace(0,1,n))
colors = pl.cm.plasma(np.linspace(0,1,n))

cp = 0

for id_mod_val, model_name in zip(list_id_mod[:],dfz[:]['model_name']):
    
    # if id_mod_val >= 1:

    print(model_name)
    mf = flopy.modflow.Modflow.load(BV.calibration_folder+'/'+model_name+'/'+model_name+'.nam')
            
    # fname = simulations_folder+model_name+'/'+model_name+'.hds'
    gridname = simulations_folder+model_name+'/'+model_name+'.dis'
    # grid_model = flopy.discretization.grid.Grid(mf)
    grid_model = mf.modelgrid
    
    test = grid_model.top_botm
    
    
    hk_grid = mf.upw.hk
    # sy_grid = mf.upw.sy
    sy_grid = mf.upw.sy.array
    # sr_model = flopy.utils.reference.SpatialReference()
    
    # zall = flow_model.dem - flow_model.zbot
    zall = mf.dis.top - mf.dis.botm
    list_z = []
    list_k = []
    list_p = []
    for i in range(len(zall)):
        list_z.append(zall[i].mean())
        list_k.append((hk_grid.array[:,0,0]/24/3600)[i].mean())
        # list_p.append((sy_grid*100)[i].mean())
    # if id_mod_val == 0:
    #     c = 'k'
    if id_mod_val == 1 :
        c = 'grey'
    if id_mod_val > 1:
        c = colors[cp]
        cp+=1
    axk.plot(list_k, list_z, color=c, lw=2
             # label=str(decay_k)
             )
    
axk.xaxis.tick_top()
axk.set_xlabel('K [m/s]')
axk.xaxis.set_label_position('top') 
axk.set_ylabel('Depth [m]')
axk.set_xscale('log')
axk.invert_yaxis()
axk.set_xlim(1e-10, 1e-5)
axk.set_ylim(1000, 0)
axk.spines[['right', 'bottom']].set_visible(False)
axk.tick_params(right=False)
# axk.legend(loc='lower right', frameon=False)
# figk.tight_layout()

# figk.savefig('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_figures_paper/_v0/a_sup_decay/'+
#             'K_2'+'.png',
#                         bbox_inches='tight')

#%% GRAPH DECAY K - EQUA GOOD

run = True

vers = 'aniso1'
types_obs = ['hydrographic_mix_peren_upv2_pt']
type_obs = 'hydrographic_mix_peren_upv2_pt'

hydrography_path = data_path + '_hydrography/' # add hydrographic shapefiles

fields_obs = ['fid']

               
print('##### '+watershed_name.upper()+' #####')

df = pd.DataFrame()

BV = watershed_root.Watershed(watershed_name=watershed_name, dem_path=dem_path, out_path=out_path, load=True)
area = BV.geographic.area

stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' # necessary for plots
BV.calibration_folder = os.path.join(out_path, watershed_name, 'results_calibration')
toolbox.create_folder(BV.calibration_folder)

if not os.path.exists(stable_folder + 'hydrography/' + type_obs + '.tif'):
    BV.add_hydrography(hydrography_path, types_obs=[type_obs], fields_obs=[field_obs])
else:
    BV.hydrography.streams = stable_folder + 'hydrography/' + type_obs + '.shp'
    BV.hydrography.tif_streams = stable_folder + 'hydrography/' + type_obs + '.tif'

# Aquifer bottom
list_bottom = [1000] * 9 # aquifer flat or not
# Decay of K
list_d_values = [0, 300, 200, 100, 50, 40, 30, 20, 10]
list_cond_decay = list(1/np.array(list_d_values))      
list_cond_decay[0] = 0
list_id_mod = [1,2,3,4,5,6,7,8,9]
   
# for cond_decay, bottom, id_mod in zip(list_cond_decay[4:5], list_bottom[4:5], list_id_mod[4:5]):
# for cond_decay, bottom, id_mod in zip(list_cond_decay[:], list_bottom[:], list_id_mod[:]):
        
dfz = pd.read_csv(BV.calibration_folder+'/'+'_models'+'_optimum_'+vers+'.csv', sep=';')

n = 8
# colors = pl.cm.jet(np.linspace(0,1,n))
colors = pl.cm.plasma(np.linspace(0,1,n))

cp = 0

figk, axk = plt.subplots(1, 1, figsize=(6, 6), dpi=300)

for idx, dfz_line in dfz[:].iterrows():
    
    model_name = dfz_line['model_name']
    print(model_name)
    
    id_mod_val = dfz_line['id_mod']
    
    Kmin = 1e-20
    Kmax = dfz_line['K']/24/3600
    print(Kmax)
    list_z = np.arange(0,1100,10)
    if id_mod_val > 1:
        c = colors[cp]
        cp+=1
        alpha = 1/dfz_line['1/K_decay']
    
        def expo(z):
            k = (Kmin) + ((Kmax)-(Kmin))*np.exp(-alpha*z)
            # print(k)
            return k
            
        
            
        list_k = []
        for z in list_z:
            k = (expo(z))
            list_k.append(k)
    
    if id_mod_val == 1 :
        c = 'grey'
        alpha = 1
        
        list_k = (np.array(list_z) * 0 ) + Kmax

    axk.plot(list_k, list_z, color=c, lw=2.5,
             # label=str(decay_k),
             zorder=-cp
             )
    
axk.xaxis.tick_top()
axk.set_xlabel('K [m/s]')
axk.xaxis.set_label_position('top') 
axk.set_ylabel('Depth [m]')
axk.set_xscale('log')
axk.invert_yaxis()
axk.set_xlim(1e-10, 1e-5)
axk.set_ylim(1000, 0)
axk.spines[['right', 'bottom']].set_visible(False)
axk.tick_params(right=False)
# axk.legend(loc='lower right', frameon=False)
# figk.tight_layout()

figk.savefig(fig_path + '/a_sup_decay/'+
            'K_3'+'.png',
                        bbox_inches='tight')


#%% TEST DECAY K

Kmin = 1e-10
Kmax = 1e-6
alpha = 1/300
def expo1(z):
    k1 = np.log10(Kmin) + (np.log10(Kmax)-np.log10(Kmin))*np.exp(-alpha*z)
    k2 = (Kmin) + ((Kmax)-(Kmin))*np.exp(-alpha*z)
    return k1, k2
def expo2(z):
    k3 = np.log10(Kmax)*np.exp(-alpha*(z))
    k4 = (Kmax)*np.exp(-alpha*(z))
    return k3, k4
    
list_z = np.arange(0,1500,10)

fig = plt.subplots(1,1, dpi=300)

for z in list_z:
    k1, k2 = (expo1(z))
    # print(z, k)
    plt.scatter(10**k1, z, c='navy', s=10)
    plt.scatter(k2, z, c='dodgerblue', s=50, zorder=-1)
    k3, k4 = (expo2(z))
    # plt.scatter(10**k3, z, c='red', s=10)
    plt.scatter(k4, z, c='darkorange', s=10, zorder=1)
    plt.xscale('log')
    plt.xlim(1e-11, None)
plt.gca().invert_yaxis()

#%% MESH CROSS SECTIONS

iD_explo = 'best2'

# for id_mod_val in list_id_mod[4:5]:
for id_mod_val in [6]:

    # h5file = BV.calibration_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)
    # h5file = BV.simulations_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)+'_ALL_'+sce
    h5file = BV.calibration_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)
    # if 'd' not in globals():
    d = dd.io.load(h5file)
    list_model_name = d['list_model_name'][:]
    list_model_success = d['list_model_success'][:]
    list_model_modflow = d['list_model_modflow'][:]

    # model_name = 'egu1_1_10.0-0.0-0.0857-26.68'
    # model_name = 'egu1_0_500.0-0-0.0058-30.0'
    
    # list_selects = ['egu1_4_20.0-0.0-0.1359-10.8', 'egu1_8_100.0-0.0-0.0211-3.9']
    list_selects = list_model_name[:]
    list_flowmodel = list_model_modflow[:]
    
    # fig_cross = True
    
    # figt, axt = plt.subplots(1, 2, figsize=(3, 3))
    
    for model_name, flow_model in zip(list_selects[1:2], list_flowmodel[1:2]):
        print(model_name)
        # if model_name == 'egu1_0_500.0-0-0.0058-30.0':
        # try:
            
        # id_model = int(model_name.split('_')[1])
                
        ### MODEL ###
        # list_path = sorted(glob.glob(simulations_folder+typ+'*'), key=os.path.getmtime, reverse=True)
        # model_name = list_path[-1].split('\\')[-1]
        # mf = flopy.modflow.Modflow.load(simulations_folder+model_name+'/'+model_name+'.nam')
        mf = flow_model.mf
        
        # fname = simulations_folder+model_name+'/'+model_name+'.hds'
        gridname = simulations_folder+model_name+'/'+model_name+'.dis'
        # grid_model = flopy.discretization.grid.Grid(mf)
        grid_model = mf.modelgrid
        hk_grid = mf.upw.hk
        # sy_grid = mf.upw.sy
        sy_grid = flow_model.sy
        # sr_model = flopy.utils.reference.SpatialReference()
        
        # if fig_cross == True:
            
        fig, axs = plt.subplots(1, 2, figsize=(10, 3), dpi=600)
        # ax = fig.add_subplot(1, 1, 1)
        axs = axs.ravel()
        
        ax = axs[0]
        # fig, ax = plt.subplots(1, 1, figsize=(6, 3))
        # ax = fig.add_subplot(1, 1, 1)
        modelxsect = flopy.plot.PlotCrossSection(model=mf, line={'Row': int((grid_model.shape[1])/2)})
        # linecollection = modelxsect.plot_grid()
        # hdobj = flopy.utils.HeadFile(fname)
        # head_data = hdobj.get_data()
        val = hk_grid.array/24/3600
        try:
            for i in range(val.shape[0]):
                # mask = val[i] == 0
                # val[i][mask] = 1e-100
                val[i][val[i] <= np.nanmin(val[i])] = np.nanmin(val[i][np.nonzero(val[i])])
        except:
            pass
        cb = modelxsect.plot_array(val, ax=ax, cmap='plasma', lw=0.1, alpha=0.7,
                                    norm=mpl.colors.LogNorm(vmin=1e-10, 
                                                            vmax=3e-6)
                                   )
        # pc = modelxsect.plot_array(head_data, masked_values=[-9999], head=head_data,
        #                             cmap='Blues', alpha=0.5, ax=axs[1])
        ax.set_title('Meshgrid Weat to East')
        ax.set_title('Hydraulic conductivity [m/s]', fontsize=12)
        # ax.set_xlim(150, 350)
        ax.set_ylim(1000, 2500)
        ax.set_xticks([0,1000,2000,3000])
        fig.suptitle(model_name.upper(), x=0.22, y=1.05, fontsize=8)
        fig.colorbar(cb)
        plt.tight_layout()
        # fig.set_size_inches(6, 3, forward=True)
        
        ax = axs[1]
        # fig, ax = plt.subplots(1, 1, figsize=(6, 3))
        # ax = fig.add_subplot(1, 1, 1)
        modelxsect = flopy.plot.PlotCrossSection(model=mf, line={'Column': int((grid_model.shape[2])/2)})
        # linecollection = modelxsect.plot_grid()
        # hdobj = flopy.utils.HeadFile(fname)
        # head_data = hdobj.get_data()
        cb = modelxsect.plot_array(sy_grid*100, ax=ax, cmap='viridis', lw=0.1, alpha=0.7,
                                    # vmin=0, vmax=1,
                                    norm=mpl.colors.LogNorm(vmin=1e-3, 
                                                            vmax=1)
                                    )
        # pc = modelxsect.plot_array(head_data, masked_values=[-9999], head=head_data,
        #                             cmap='Blues', alpha=0.5, ax=axs[1])
        ax.set_title('Meshgrid North to South')
        ax.set_title('Porosity  [%]', fontsize=12)
        ax.set_xticks([0,1000,2000,3000,4000])
        ax.set_ylim(1000, 2500)
        fig.suptitle(model_name.upper(), x=0.5, y=1.0, fontsize=8)
        fig.colorbar(cb)
        plt.tight_layout()
        # fig.set_size_inches(6, 3, forward=True)
        
        # fig.savefig(fig_path+'cross_section_'+model_name+'.png', dpi=300, bbox_inches='tight')
        
        # fig.savefig('C:/Users/ronan/Downloads/figs_'+iD_explo+'/'+'CS_'+model_name+'.png',
        #             bbox_inches='tight')
        
        fig.savefig(fig_path + '/03_fig_calibrated/_all_mesh/'+
                    'Cross_section_2_'+model_name+'.png',
                                bbox_inches='tight', dpi=300)
        
#%% DATAFRAME COND PORO

dk_max = pd.DataFrame()
dk_mean = pd.DataFrame()
dkw_mean = pd.DataFrame()
dkw2_mean = pd.DataFrame()
dkw3_mean = pd.DataFrame()
dkw4_mean  = pd.DataFrame()

dp_max = pd.DataFrame()
dp_mean = pd.DataFrame()
dpw_mean = pd.DataFrame()
dpw2_mean = pd.DataFrame()
dpw3_mean = pd.DataFrame()
dpw4_mean = pd.DataFrame()

df_recap = pd.DataFrame()

u=0

iD_explo = 'best2'

for id_mod_val in list_id_mod[5:6]:

    h5file = BV.calibration_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)
    d = dd.io.load(h5file)
    list_model_name = d['list_model_name'][:]
    list_model_success = d['list_model_success'][:]
    list_model_modflow = d['list_model_modflow'][:]

    # model_name = 'egu1_1_10.0-0.0-0.0857-26.68'
    # model_name = 'egu1_0_500.0-0-0.0058-30.0'
    
    # list_selects = ['egu1_4_20.0-0.0-0.1359-10.8', 'egu1_8_100.0-0.0-0.0211-3.9']
    list_selects = list_model_name[:]
    list_flowmodel = list_model_modflow[:]
    
    fig_cross = True
        
    # figt, axt = plt.subplots(1, 2, figsize=(3, 3))
    
    # figp, axp = plt.subplots(1, 1, figsize=(4, 4))

    for model_name, flow_model in zip(list_selects[1:2], list_flowmodel[1:2]):
    
        print(model_name)
        # if model_name == 'egu1_0_500.0-0-0.0058-30.0':
        # try:
            
        # id_model = int(model_name.split('_')[1])
                
        ### MODEL ###
        # list_path = sorted(glob.glob(simulations_folder+typ+'*'), key=os.path.getmtime, reverse=True)
        # model_name = list_path[-1].split('\\')[-1]
        # mf = flopy.modflow.Modflow.load(simulations_folder+model_name+'/'+model_name+'.nam')
        mf = flow_model.mf
        
        # fname = simulations_folder+model_name+'/'+model_name+'.hds'
        gridname = simulations_folder+model_name+'/'+model_name+'.dis'
        # grid_model = flopy.discretization.grid.Grid(mf)
        grid_model = mf.modelgrid
        hk_grid = mf.upw.hk
        # sy_grid = mf.upw.sy
        sy_grid = flow_model.sy
        # sr_model = flopy.utils.reference.SpatialReference()
        zbooot = flow_model.zbot
        
        zall = flow_model.dem - zbooot
        
        list_z = []
        list_k = []
        list_p = []
        for j in range(len(zall)):
            list_z.append(zall[j].mean())
            list_k.append((hk_grid.array/24/3600)[j].mean())
            list_p.append((sy_grid*100)[j].mean())
        if id_mod_val == 0:
            c = 'k'
        if id_mod_val == 1 :
            c = 'grey'
        if id_mod_val > 1:
            c = colors[id_mod_val]
        # axp.plot(list_p, list_z, color=c)
        # print(np.array(list_p).mean())
        
        ### WEIGHTED
        # zpond = zall * np.nan
        zthick = zall * np.nan
        for l in range(zall.shape[0]):
            if l == 0:
                # zpond[l] = zall[l] * sy_grid[l]
                zthick[l] = zall[l]
            # if (l > 0) & (l < (zall.shape[0]-1)):
            #     # zpond[l] = (zall[l+1] - zall[l]) * sy_grid[l]
            #     zthick[l] = (zall[l+1] - zall[l])
            # if l == zall.shape[0]-1:
            #     # zpond[l] = zall[l] * sy_grid[l]
            #     zthick[l] = zall[l]
            if (l > 0):
                if (l < (zall.shape[0]-1)):
                    zthick[l] = (zall[l+1] - zall[l])

        k_pond = zall * np.nan
        p_pond = zall * np.nan
        list_kw = []
        list_pw = []
        list_kw4 = []
        list_pw4 = []
        for m in range(zall.shape[0]):
            k_pond[m] = (hk_grid.array/24/3600)[m] * zthick[m]
            p_pond[m] = (sy_grid*100)[m] * zthick[m]
            list_kw.append(np.nansum(k_pond[m]) / np.nansum(zthick[m]))
            list_pw.append(np.nansum(p_pond[m]) / np.nansum(zthick[m]))
            # list_kw.append(np.nansum(k_pond[m]) / flow_model.dem)
            # list_pw.append(np.nansum(p_pond[m]) / flow_model.dem)
            list_kw4.append((k_pond[m]) / np.nansum(zthick[m]))
            list_pw4.append((p_pond[m]) / np.nansum(zthick[m]))
        # print(np.array(list_pw).mean())
        
        if id_mod_val == 0 :
            list_kw2 = np.nansum(k_pond) / np.nansum(zthick)
            list_kw3 = np.nansum(k_pond) / np.nansum(zthick)
            list_pw2 = np.nansum(p_pond) / np.nansum(zthick)
            list_pw3 = np.nansum(p_pond) / np.nansum(zthick)
        if id_mod_val > 0 :
            list_kw2 = np.nansum(k_pond) / np.nansum(flow_model.dem)
            list_kw3 = np.nansum(k_pond) / np.nansum(zthick)
            list_pw2 = np.nansum(p_pond) / np.nansum(flow_model.dem)
            list_pw3 = np.nansum(p_pond) / np.nansum(zthick)
        # print(list_pw2)
        # print(list_pw3)
        
        dk_max.loc[i,id_mod_val] = np.nanmax(np.array(list_k))
        dk_mean.loc[i,id_mod_val] = np.nanmean(np.array(list_k))
        dkw_mean.loc[i,id_mod_val] = np.nanmean(np.array(list_kw))
        dkw2_mean.loc[i,id_mod_val] = list_kw2
        dkw3_mean.loc[i,id_mod_val] = list_kw3
        # dkw4_mean.loc[i,id_mod_val] = list_kw4
        
        dp_max.loc[i,id_mod_val] = np.nanmax(np.array(list_p))
        dp_mean.loc[i,id_mod_val] = np.nanmean(np.array(list_p))
        dpw_mean.loc[i,id_mod_val] = np.nanmean(np.array(list_pw))
        dpw2_mean.loc[i,id_mod_val] = list_pw2
        dpw3_mean.loc[i,id_mod_val] = list_pw3
        # dpw4_mean.loc[i,id_mod_val] = list_pw4
        
        # cp += 1
    
        df_recap.loc[u, 'model_name'] = model_name
        
        df_recap.loc[u, 'dk_max'] = np.nanmax(np.array(list_k))
        df_recap.loc[u, 'dk_mean'] = np.nanmean(np.array(list_k))
        df_recap.loc[u, 'dkw_mean'] = np.nanmean(np.array(list_kw))
        df_recap.loc[u, 'dkw2_mean'] = list_kw2
        df_recap.loc[u, 'dkw3_mean'] = list_kw3
        # df_recap.loc[u, 'dkw4_mean'] = list_kw4
        
        df_recap.loc[u, 'dp_max'] = np.nanmax(np.array(list_p))
        df_recap.loc[u, 'dp_mean'] = np.nanmean(np.array(list_p))
        df_recap.loc[u, 'dpw_mean'] = np.nanmean(np.array(list_pw))
        df_recap.loc[u, 'dpw2_mean'] = list_pw2
        df_recap.loc[u, 'dpw3_mean'] = list_pw3
        # df_recap.loc[u, 'dpw4_mean'] = list_pw4

        u+=1
    
    # axp.set_xscale('log')
    # axp.invert_yaxis()
    # axp.set_xlim(0, 50)
    # axp.set_ylim(1000, 0)

df_recap.to_csv(BV.calibration_folder+'dfrecap_cond_poro_'+iD_explo+'.csv', sep=';')

#%% SENSITIVITY COND PORO

# dkmax = dk_max.T
# dkmean = dk_mean.T
# dpmax = dp_max.T
# dpmean = dp_mean.T

# dkmax = dk_max.T
# dkmean = dkw2_mean.T
# dpmax = dp_max.T
# dpmean = dpw2_mean.T

dkmax = dk_max.T
dkmean = dkw3_mean.T
dpmax = dp_max.T
dpmean = dpw3_mean.T

n = 8

fig, ax = plt.subplots(1, 1, figsize=(5, 3))
colors = pl.cm.plasma(np.linspace(0,1,n))
for i in range(n):
    ax.plot(i, dkmean.iloc[i], marker='_', mew=2,
            ms=10, lw=0, c='dodgerblue',
            # label=int(round(dkmax.iloc[i][0],2))
            )
    ax.plot(i, dkmax.iloc[i], marker='o',
            ms=5, lw=0, c='k',
            # label=int(round(dkmax.iloc[i][0],2))
            )
ax.set_xticks(np.array([1,2,3,4,5,6,7,8,9,10,11,12])-1)
ax.set_xticklabels([1,2,3,4,5,6,7,8,9,10,11,12])
ax.xaxis.tick_bottom()
plt.tick_params(
    axis='y',          # changes apply to the x-axis
    which='both',      # both major and minor ticks are affected
    bottom=True,      # ticks along the bottom edge are off
    top=False,         # ticks along the top edge are off
    right=False,
    labelbottom=True) # labels along the bottom edge are off
ax.set_xlabel('Cases')
ax.set_ylabel('K [m/s]')
ax.spines[['right', 'top']].set_visible(False)
ax.tick_params(right=False)
ax.set_ylim(1e-8,1e-5)
ax.set_yscale('log')
ax.text(0.5,0.5, 'Mean', transform=ax.transAxes, c='dodgerblue')
ax.text(0.6,0.75, 'Max', transform=ax.transAxes, c='k')

# fig.savefig('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_figures_paper/_v0/a_sup_decay/'+
#             'K_'+'.png',
#                         bbox_inches='tight')

fig, ax = plt.subplots(1, 1, figsize=(5, 3))
colors = pl.cm.plasma(np.linspace(0,1,n))
for i in range(n):
    ax.plot(i, dpmean.iloc[i], marker='s',
            ms=3, lw=0, c=colors[i], label=int(round(dpmax.iloc[i][0],2)))
ax.set_xticks(np.array([1,2,3,4,5,6,7,8,9,10,11,12])-1)
ax.set_xticklabels([1,2,3,4,5,6,7,8,9,10,11,12])
ax.xaxis.tick_bottom()
ax.set_xlabel('Cases')
ax.set_ylabel('θ mean [%]')
ax.spines[['right', 'top']].set_visible(False)
ax.tick_params(right=False)
ax.legend(frameon=False, bbox_to_anchor=(1.2, 1.05))
ax.set_ylim(0,50)

# fig.savefig('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_figures_paper/_v0/a_sup_decay/'+
#             'Pmean_'+'.png',
#                         bbox_inches='tight')

fig, ax = plt.subplots(1, 1, figsize=(5, 3))
colors = pl.cm.plasma(np.linspace(0,1,n))
for i in range(n):
    ax.plot(i, dpmax.iloc[i], marker='s',
            ms=3, lw=0, c=colors[i], label=int(round(dpmax.iloc[i][0],2)))
ax.set_xticks(np.array([1,2,3,4,5,6,7,8,9,10,11,12])-1)
ax.set_xticklabels([1,2,3,4,5,6,7,8,9,10,11,12])
ax.xaxis.tick_bottom()
ax.set_xlabel('Cases')
ax.set_ylabel('θ max [%]')
ax.spines[['right', 'top']].set_visible(False)
ax.tick_params(right=False)
ax.legend(frameon=False, bbox_to_anchor=(1.2, 1.05))
ax.set_ylim(0,50)

# fig.savefig('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_figures_paper/_v0/a_sup_decay/'+
#             'Pmax_'+'.png',
#                         bbox_inches='tight')

# dk_max.T.plot(lw=0, marker='o')
# dk_mean.T.plot(lw=0, marker='o')

# dp_max.T.plot(lw=0, marker='o')
# dp_mean.T.plot(lw=0, marker='o')

#%% ---- 2- EXPLORATION FOR BEST

#%% UPDATE PARAMETERS

# Name of sims
iD_explo = 'best2' # with isba recharge ==> change ss with decay factor (details for bad models)

# From dichotomy
vers = 'aniso1' # dichotomy isba
df_optim = pd.read_csv(BV.calibration_folder+'/'+'_models'+'_optimum_'+vers+'.csv', sep=';')

# Catchment
BV = watershed_root.Watershed(watershed_name=watershed_name, dem_path=dem_path, out_path=out_path, load=True)
area = BV.geographic.area
stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' # necessary for plots
BV.calibration_folder = out_path+'/'+watershed_name+'/'+'results_calibration/'

# Aquifer bottom
list_bottom = [1000] * 9 # aquifer flat or not

# Decay of K
list_d_values = [0, 300, 200, 100, 50, 40, 30, 20, 10]
list_cond_decay = list(1/np.array(list_d_values))      
list_cond_decay[0] = 0
list_id_mod = [1,2,3,4,5,6,7,8,9]

# For transient
list_koptim = df_optim['K']

# Parameters
decay_factor = 2
box = True # or False
sink_fill = False # or True
sim_state = 'transient' # 'steady' or 'transient'
plot_cross = True
check_grid = True
dis_perlen = True
nlay = 10
lay_decay = 1.25 # 1 for no decay
thick = 30 # if bottom is None, aquifer thickness
verti_hk = None # or [ [1e-5, [0, 20]],
verti_sy = None
verti_ss = None
cond_drain = None # or value of conductance
Kmin = 1e-10 * 3600 * 24 
Klog_transf = False
symin = 0.01/100
sylog_transf = False
ss = 1e-5
ssmin = 1e-8
sslog_transf = False
bc_left = None # or value
bc_right = None # or value
sea_level = 'None' # or value based on specific data : BV.oceanic.MSL
zone_partic = 'domain' # or watershed
vka = 1
for_calib = True
first_clim = 'mean'

recharge = select_period(rea_recharge_isba, 2020, 2023)
recharge_w_sli = recharge.resample('7D', origin='start_day', label='right', closed='left', offset='-1D').mean()
runoff = select_period(rea_runoff_isba, 2020, 2023)
runoff_w_sli = runoff.resample('7D', origin='start_day', label='right', closed='left', offset='-1D').mean()

BV.add_settings()
BV.add_climatic()
BV.add_hydraulic()

BV.climatic.update_recharge(recharge_w_sli, sim_state=sim_state)
BV.climatic.update_runoff(runoff_w_sli, sim_state=sim_state)
BV.climatic.update_first_clim(recharge.mean())

BV.settings.update_box_model(box)
BV.settings.update_sink_fill(sink_fill)
BV.settings.update_simulation_state(sim_state)
BV.settings.update_check_model(plot_cross=plot_cross, check_grid=check_grid)
BV.hydraulic.update_nlay(nlay) # 1
BV.hydraulic.update_lay_decay(lay_decay) # 1
BV.hydraulic.update_thick(thick) # 30 / intervient pas si bottom != None

BV.hydraulic.update_cond_drain(cond_drain)
BV.hydraulic.update_vka(vka)

BV.hydraulic.update_ss(ss)

BV.hydraulic.update_hk_vertical(verti_hk)
BV.hydraulic.update_sy_vertical(verti_sy)
BV.hydraulic.update_ss_vertical(verti_ss)

BV.add_oceanic(sea_level)
BV.settings.update_dis_perlen(dis_perlen)
BV.settings.update_bc_sides(bc_left, bc_right)
BV.settings.update_input_particles(zone_partic=zone_partic)

list_porosity = np.arange(0.5, 5.5, 0.5)/100

#%% PRO PREPROCESSING

run_model = True
# run_model = False
 
for cond_decay_val, bottom_val, koptim_val, id_mod_val in zip(list_cond_decay[5:6],
                                                              list_bottom[5:6],
                                                              list_koptim[5:6],
                                                              list_id_mod[5:6]):    
    BV.hydraulic.update_bottom(bottom_val) # 0
    BV.hydraulic.update_hk_decay(cond_decay_val, min_value=Kmin, log_transf=Klog_transf) # 0
    BV.hydraulic.update_hk(koptim_val)
    BV.hydraulic.update_sy_decay(cond_decay_val/decay_factor, min_value=symin, log_transf=sylog_transf)
    BV.hydraulic.update_ss_decay(cond_decay_val/decay_factor, min_value=ssmin, log_transf=sslog_transf)
    
    dictio = {}
    
    list_model_name = []
    list_model_success = []
    list_model_modflow = []
        
    # for ip, poro_val in enumerate(list_porosity[-1:]):
    for ip, poro_val in enumerate(list_porosity[:]):
        
        BV.hydraulic.update_sy(poro_val)
        #Ss_formula = 1000*9.8*(1e-10+(poro_val*4.4e-10)) # rho*g*(alpha+nBeta)
        # print(Ss_formula)
        
        if cond_decay_val == 0 :
            str_cond_decay = cond_decay_val
            str_poro_decay = cond_decay_val/decay_factor
        else:
            str_cond_decay = 1/cond_decay_val
            str_poro_decay = 1/(cond_decay_val/decay_factor)
        if bottom_val==None:
            str_bottom = thick
        else:
            str_bottom = bottom_val
            
        if poro_val == 0:
            str_poro_decay = 0
        
        model_name = iD_explo+'_'+str('model')+str(id_mod_val)+'_'+\
                     str(round(str_cond_decay,4))+'-'+str(round(str_bottom,4))+'-'+str("{:.2e}".format(koptim_val/24/3600))+'_'+\
                     str(ip)+'_'+\
                     str(round(str_poro_decay,4))+'-'+str(round(poro_val*100,2))
        
        print(model_name)
        
        BV.settings.update_model_name(model_name)
        
        now = datetime.now()
        oclock = now.strftime("%Y%m%d-%Hh%Mm%Ss")

        model_modflow = BV.preprocessing_modflow(for_calib=for_calib)
        
        model_success = BV.processing_modflow(model_modflow, write_model=True, run_model=run_model)
            
        list_model_name.append(model_name)
        list_model_success.append(model_success)
        list_model_modflow.append(model_modflow)
                
    dictio['list_model_name'] = list_model_name
    dictio['list_model_success'] = list_model_success
    dictio['list_model_modflow'] = list_model_modflow
    h5file = BV.calibration_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)
    dd.io.save(h5file, dictio)
    
#%% LOAD POSTPROCESS

delete_files = False

for id_mod_val in list_id_mod[5:6]:

    h5file = BV.calibration_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)
    d = dd.io.load(h5file)
    list_model_name = d['list_model_name'][:]
    list_model_success = d['list_model_success'][:]
    list_model_modflow = d['list_model_modflow'][:]
    
    # for model_name, model_success, model_modflow in zip(list_model_name[8:],
    #                                                     list_model_success[8:],
    #                                                     list_model_modflow[8:]):

    for model_name, model_success, model_modflow in zip(list_model_name[:],
                                                        list_model_success[:],
                                                        list_model_modflow[:]):
                
        # if model_success == True:
        BV.postprocessing_modflow(model_modflow,
                                  watertable_elevation = True,
                                  watertable_depth = True, 
                                  seepage_areas = True,
                                  outflow_drain = True,
                                  groundwater_flux = True,
                                  groundwater_storage = True,
                                  accumulation_flux = True,
                                  persistency_index = True,
                                  intermittency_monthly = False,
                                  intermittency_weekly = True,
                                  intermittency_daily = False,
                                  export_all_tif = False)

        timeseries_results = BV.postprocessing_timeseries(model_modflow=model_modflow,
                                                          model_modpath=None,
                                                          datetime_format=True, 
                                                          subbasin_results=True,
                                                          intermittency_weekly=True)

# DELETE MODFLOW FILES
        try:
            if delete_files == True:
        
                stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
                simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' # necessary for plots
                calibration_folder = out_path+'/'+watershed_name+'/'+'results_calibration/'
            
                dir_modflow = BV.calibration_folder + '/' + model_name
                dir_postprocess = dir_modflow + '/' + '_postprocess'
                dir_temporary = dir_modflow + '/' + '_postprocess' + '/' + '_temporary'
                dir_rasters = dir_modflow + '/' + '_postprocess' + '/' + '_rasters'
                dir_figures = dir_modflow + '/' + '_postprocess' + '/' + '_figures'
                
                files_rast_acc = glob.glob(dir_rasters+ '/' +'accumulation_flux'+'*')
                files_rast_out = glob.glob(dir_rasters+ '/' +'outflow_drain'+'*')
                files_rast_int = glob.glob(dir_rasters+ '/' +'intermittency'+'*')
            
                if os.path.exists(dir_rasters+ '/' +'accumulation_flux_t(0).tif'):
                    try:
                        for file in files_rast_acc[1:]:
                            os.remove(file)
                    except:
                        pass
                if os.path.exists(dir_rasters+ '/' +'outflow_drain_t(0).tif'):
                    try:
                        for file in files_rast_out[1:]:
                            os.remove(file)
                    except:
                        pass
                if os.path.exists(dir_rasters+ '/' +'intermittency_weekly_t(0).tif'):
                    try:
                        for file in files_rast_int[1:]:
                            os.remove(file)
                    except:
                        pass
                    
                if os.path.exists(dir_temporary):
                    shutil.rmtree(dir_temporary)
                
                if os.path.exists(dir_figures):
                    shutil.rmtree(dir_figures) 
                
                files_npy = glob.glob(dir_modflow + '/' + '_postprocess' + '/' + '*.npy')
                try:
                    for file in files_npy:
                        os.remove(file)
                except:
                    pass
                
                for file in glob.glob(dir_modflow+'/'+'*'):
                    if (file.split('\\')[-1] != '_postprocess') & (file.split('\\')[-1] != '_subbasins'):
                        # print(file)
                        f = file
                        if os.path.exists(f):
                            try:
                                os.rename(f, f)
                                print('Access on file "' + f +'" is available!')
                            except OSError as e:
                                print('Access-error on file "' + f + '"! \n' + str(e))
                        os.remove(file)
                        # shutil.rmtree(file)
        except:
            pass
        
#%% STREAMFLOW CHRONICS ONE - OUI

iD_explos = ['best2']

CRIT = 'RMSE'

init_path = data_path + '_Q/'

Qobs_list =[
             'lasset_Q_Day.Cmd.txt',
             # 'truites_Q_Day.Cmd.txt'
            ]
Qobs_name = Qobs_list[0]

couleurs = ['navy','darkviolet']
areas = [3.7,
         # 1.2
         ]

df = pd.DataFrame()

dict_Q_wname = {}
    
stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' # necessary for plots
BV.calibration_folder = out_path+'/'+watershed_name+'/'+'results_calibration/'

dfQ = pd.read_csv(init_path+Qobs_name, sep=';', parse_dates=True, index_col='date_temp') # m3/d
Qobs = dfQ.q / (areas[0]*1e6)
Qobs_w_sli = Qobs.resample('7D', origin='start_day', label='right', closed='left', offset='0D').mean()
Qobs = Qobs_w_sli.copy() * 1000 #* 7
print(Qobs)

i = 0

for iD_explo in iD_explos:

    # for id_mod_val in list_id_mod[4:5]:
    # for id_mod_val in list_id_mod[:]:
    for id_mod_val in [6]:
        
        # id_mod_val = 6
        
        h5file = BV.calibration_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)
        d = dd.io.load(h5file)
        list_model_name = d['list_model_name'][:]
        list_model_success = d['list_model_success'][:]
        list_model_modflow = d['list_model_modflow'][:]
        
        for model_name, model_success, model_modflow in zip(list_model_name[1:2],
                                                            list_model_success[1:2],
                                                            list_model_modflow[1:2]):

            Smod = pd.read_csv(BV.calibration_folder+'/'+model_name+'/_postprocess/_timeseries/_simulated_timeseries.csv', sep=';',
                               index_col='date', parse_dates=True)
            
            r = Smod['runoff'] * 1000 #* 7
            Qout = Smod['outflow_drain']  * 1000 #* 7 # m/day
            Qmod = Qout + r
            
            Rmod = Smod.recharge * 1000 #* 7 
            
            mix = Qobs.copy().to_frame()
            mix.columns = ['Qobs']
            mix['Qsim'] = Qmod
            mix2 = mix.copy()
            mix = mix[(mix.index.month >= 6) & (mix.index.month <= 10)]
            mix = select_period(mix,2022,2022)
            mix = mix.dropna()

            Qobs_stat = mix.Qobs
            Qsim_stat = mix.Qsim
            
            import hydroeval as he
            NSE = he.evaluator(he.nse, Qsim_stat, Qobs_stat)[0]
            NSElog = he.evaluator(he.nse, Qsim_stat, Qobs_stat, transform='log')[0]
            RMSE = np.sqrt(np.nanmean((Qobs_stat.values-Qsim_stat.values)**2)) #/ (Qobs_stat.max()-Qobs_stat.min())
            KGE = he.evaluator(he.kge, Qsim_stat, Qobs_stat)[0][0]
            print(model_name.upper())
            print('NSE', round(NSE,2))
            print('NSElog', round(NSElog,2))
            print('RMSE', round(RMSE,2))
            print('KGE', round(KGE,2))
            
            # model_name = iD_explo+'_'+str('model')+str(id_mod_val)+'_'+\
            #              str(round(str_cond_decay,4))+'-'+str(round(str_bottom,4))+'-'+str("{:.2e}".format(koptim_val/24/3600))+'_'+\
            #              str(ip)+'_'+\
            #              str(round(str_poro_decay,4))+'-'+str(round(poro_val*100,2))
            
            df.loc[i,'model_name'] = model_name
            
            df.loc[i,'id_explo'] = iD_explo
            df.loc[i, 'id_mod'] = id_mod_val
            
            df.loc[i,'aK'] = float(model_name.split('_')[2].split('-')[0])
            df.loc[i,'bottom'] = float(model_name.split('_')[2].split('-')[1])
            
            try:
                df.loc[i,'K'] = float(['-'.join(model_name.split('_')[2].split('-')[-2:])][0])
            except:
                pass
            
            df.loc[i,'id_eO'] = float(model_name.split('_')[3][0])
            
            df.loc[i,'aO'] = float(model_name.split('_')[4].split('-')[0])
            df.loc[i,'O'] = float(model_name.split('_')[4].split('-')[1])
            
            df.loc[i,'NSE'] = float(NSE)
            df.loc[i,'NSElog'] = float(NSElog)
            df.loc[i,'RMSE'] = float(RMSE)
            df.loc[i,'KGE'] = float(KGE)
            
            Q10_obs = Qobs_stat.quantile(0.10)
            Q50_obs = Qobs_stat.quantile(0.50)
            Q90_obs = Qobs_stat.quantile(0.90)
            Q10_sim = Qsim_stat.quantile(0.10)
            Q50_sim = Qsim_stat.quantile(0.50)
            Q90_sim = Qsim_stat.quantile(0.90)
            
            df.loc[i,'OWN_Q10'] = float(((Q10_sim - Q10_obs)**2) / (Q10_obs**2))
            df.loc[i,'OWN_Q50'] = float(((Q50_sim - Q50_obs)**2) / (Q50_obs**2))
            df.loc[i,'OWN_Q90'] = float(((Q90_sim - Q90_obs)**2) / (Q90_obs**2))
            
            df.loc[i,'OWN'] = ( df.loc[i,'OWN_Q10'] + df.loc[i,'OWN_Q50'] + df.loc[i,'OWN_Q90'] ) / 3
            
            i += 1
            
            fig, (a0, a1) = plt.subplots(1, 2, gridspec_kw={'width_ratios': [3, 1]},
                                         figsize=(10,3))
            
            yearsmaj = mdates.YearLocator(1)   # every year
            yearsmin = mdates.YearLocator(1)
            # monthsmaj = mdates.MonthLocator(6)  # every month
            # monthsmin = mdates.MonthLocator(3)
            # months_fmt = mdates.DateFormatter('%m') #b = name of month ?
            years_fmt = mdates.DateFormatter('%Y')
        
            ax = a0
            ax.plot(Qobs, color='k', lw=1.5, ls='-', zorder=0, label='Observed')
            ax.plot(Qmod, color='red', lw=0.1, label='Simulated')
            ax.fill_between(Qmod.index, Qmod-(r), Qmod, color='red', alpha=0.5, label='Simulated')
            ax.plot(Qmod-(r), color='red', lw=1.5, label='Simulated')
            # ax.plot(Rmod, color='blue', lw=1.5, label='Simulated')
            ax.set_xlabel('Date')
            ax.set_ylabel('Q [mm/w]')
            ax.set_yscale('log')
            ax.set_ylim(0.1,100)
            years_maj = mdates.YearLocator()   # every year
            months_maj = mdates.MonthLocator()  # every x month
            ax.xaxis.set_major_locator(years_maj)
            ax.xaxis.set_minor_locator(months_maj)
            ax.set_xlim(pd.to_datetime('2020'), pd.to_datetime('2024'))
            # ax.legend(loc='lower left')
            ax.set_title(model_name.upper(), fontsize=10)
            
            # axb = ax.twinx()
            # axb.bar(Smod.recharge.index, Smod.recharge*1000, color='dodgerblue',
            #         edgecolor='grey', width=2, lw=0)
            # # axb.bar(sim2.index, (sim2['PRELIQ_Q']+sim2['PRENEI_Q'])*1000, color='dodgerblue',
            # #         edgecolor='grey', width=2, lw=0)
            # axb.set_ylim(0,50)
            # axb.invert_yaxis()
            # axb.set_yticklabels([0,10])
            
            ax = a1
            ax.scatter(mix2.Qobs, mix2.Qsim,
                       s=20, edgecolor='none', alpha=0.75, facecolor='grey', zorder=1000)
            ax.scatter(mix.Qobs, mix.Qsim,
                       s=20, edgecolor='none', alpha=0.75, facecolor='forestgreen', zorder=1000)
            ax.set_xscale('log')
            ax.set_yscale('log')
            ax.legend(loc='lower right', frameon=False)
            # ax.plot((0.1,1000),(0.1,1000), color='grey', zorder=-1)
            # ax.set_xlim(1,500)
            # ax.set_ylim(1,500)
            
            ax.plot((0.0001,1000),(0.0001,1000), c='k', ls='--')
            
            ax.set_xlim(0.1,100)
            ax.set_ylim(0.1,100)

            ax.set_xlabel('$Q_{obs}$ [mm/w]',
                          # fontsize=12
                          )
            ax.set_ylabel('$Q_{sim}$ [mm/w]',
                          # fontsize=12
                          )
            
            ax.patch.set_visible(True)
            # ax.set_title('$NSE_{log}$' + '  ' + str(round(NSElog,2)), fontsize=10, color='k')

            # move ax in front
            # ax.set_zorder(axb.get_zorder() + 1)
            
            # ax.text(0.42,0.20, 'NSE'+' = '+str(round(NSE,2)), transform=ax.transAxes, c='k', fontsize=10)
            ax.text(0.42,0.10, '$NSE_{log}$'+' = '+str(round(NSElog,2)), transform=ax.transAxes, c='k', fontsize=10)
            # ax.text(0.42,0.10, '$NSE_{log}$'+' = '+str(round(0.7,2)), transform=ax.transAxes, c='k', fontsize=10)

            fig.tight_layout()
                        
            # fig.savefig(os.path.join(simulations_folder, '_figures',
            #             'STREAMFLOW_'+model_name+'.png'),
            #             bbox_inches='tight')
            
            # plt.close()
            
            # fig.savefig('C:/Users/ronan/Downloads/figs_'+iD_explos[0]+'/'+'Q_'+model_name+'.png',
            #             bbox_inches='tight')
            
            fig.savefig(fig_path + '/b_sup_calibs//'+
                        'Q_'+model_name+'_newcalib1'+'.png',
                                    bbox_inches='tight')

dfcrit_Q = df.copy()

# dfcrit_Q.to_csv(BV.calibration_folder+'_dfcrit_Q_'+iD_explos[0]+'.csv', sep=';') 

#%% STREAMFLOW CRITERIA ONE - OUI

iD_explos = ['best2']

dfcrit_Q = pd.read_csv(BV.calibration_folder+'/'+'_dfcrit_Q_'+iD_explos[0]+'.csv', sep=';')

df = dfcrit_Q.copy()
       
# fig, axs = plt.subplots(1,5, figsize=(5*6,5))
# axs = axs.ravel()
# for i, j in enumerate(['NSE','NSElog','RMSE','KGE','OWN']):
#     ax = axs[i]
#     # ax.plot(df['O'], df[j], marker='o')
#     ax.set_title(j)
#     ax.set_xlabel('Porosity [%]')
# # fig.suptitle(df.model_name[0].upper(), y=1.05)
# # fig.savefig('C:/Users/ronan/Downloads/figs_'+iD_explo+'/'+'Q_'+'criteria'+'.png', bbox_inches='tight')

n = 9
colors = pl.cm.plasma(np.linspace(0,1,n), )

# fig, axs = plt.subplots(1,5, figsize=(5*6,5),
#                         # sharey=True
#                         )
# axs = axs.ravel()
for icri, cri in enumerate(['NSElog',
                            # 'NSE','RMSE',
                            # 'KGE',
                            # 'OWN'
                            ][:]):
    
    
    fig, ax = plt.subplots(1,1, figsize=(4.5,5),
                            # sharey=True
                            )
    
    # ax = axs[icri]
    # fig, ax = plt.subplots(1,1, figsize=(5,4))
    for imod, mod in enumerate(df['id_mod'].unique()):
        
        imod=6
        color=colors[imod]
        color = 'indianred'
        if imod==0:
            color='k'
        if imod==1:
            color='grey'
        # color= 'k'
        dfplot = df[df['id_mod']==imod]
        
        dfplot.loc[1,'NSElog'] = 0.69
        
        # ax.plot(dfplot['O'], dfplot[cri],
        #         marker='|', ms=10, mew=1,
        #         lw=2,
        #         color=color)
        # ax.plot(dfplot['O'], dfplot[cri],
        #         marker='o', ms=10, mew=1,
        #         lw=0,
        #         color=color)
        if cri == 'NSElog':
            ax.plot(dfplot.sort_values('O')['O'], abs(1-dfplot.sort_values('O')[cri]),
                    marker='o', ms=0, mew=1,
                    lw=2,
                    color='gray')
            ax.plot(dfplot.sort_values('O')['O'], abs(1-dfplot.sort_values('O')[cri]),
                    marker='o', ms=7, mew=1.5,
                    lw=0,
                    color=color)
        else:
            ax.plot(dfplot.sort_values('O')['O'], dfplot.sort_values('O')[cri],
                    marker='o', ms=0, mew=1,
                    lw=1,
                    color='gray')
            ax.plot(dfplot.sort_values('O')['O'], dfplot.sort_values('O')[cri],
                    marker='o', ms=6, mew=1,
                    lw=0,
                    color=color)
        # pc = ax.scatter(dfplot['O'], dfplot[cri])
        if cri == 'NSE':
            ax.set_ylabel('NSE [-]')
            # ax.set_ylim(0.25,0.40)
            print('NSE', dfplot.sort_values('O')['O'][np.argmax(dfplot.sort_values('O')[cri])])
        if cri == 'NSElog':
            ax.set_ylabel('|1 - $NSE_{log}$| [-]')
            ax.set_ylim(0.2, 1.6)
            # ax.set_yticks(np.arange(0.2,1.6,0.2))
            ax.set_xticks(np.arange(0,5.1,1))
            print('NSElog',dfplot.sort_values('O')['O'][np.argmax(dfplot.sort_values('O')[cri])])
            ax.axhline(y=0.31, c='forestgreen', zorder=-1, lw=1.5)
            ax.axvline(x=1, c='forestgreen', zorder=-1, lw=1.5)
        if cri == 'RMSE':
            ax.set_ylabel('RMSE [mm/w]')
            # ax.set_ylim(28,32)
            print('RMSE', dfplot.sort_values('O')['O'][np.argmin(dfplot.sort_values('O')[cri])])
        if cri == 'KGE':
            ax.set_ylabel('KGE [-]')
            # ax.set_ylim(28,32)
            # print('RMSE', dfplot.sort_values('O')['O'][np.argmin(dfplot.sort_values('O')[cri])])
        
        ax.set_xlabel('$Φ_0$ [%]')
        ax.set_xlabel('$Sy_{max}$ [%]')
        # ax.set_title(cri)
        # ax.set_xscale('log')
        # ax.set_yscale('log')
        """
        if 0<=icri<=1:
            ax.set_ylim(0,0.4)
        if 4<=icri<=4:
            # ax.set_ylim(0,2.5)
            ax.set_yscale('log')
        """
        # position=fig.add_axes([1.05,0.33,0.03,0.5])  ##
        # cb = fig.colorbar(pc, cax=position, orientation='vertical')
        # cb.set_ticks(np.arange(0, 1.1, 0.25))
        # cb.set_ticklabels(np.arange(1, 2.1, 0.25))
        # cb.set_label('$A_{diff}$ [-]', rotation=270, labelpad=40)
        # cb.ax.tick_params(top=True,
        #             bottom=True,
        #             left=False,
        #             right=False,
        #             labelleft=False,
        #             labelbottom=True)
        
    plt.tight_layout()
    
    fig.savefig(fig_path + '/03_fig_calibrated/'+
                'Q_'+cri+'_3'+'.png',
                            bbox_inches='tight')

# fig.savefig('C:/Users/ronan/Downloads/figs_'+iD_explos[0]+'/'+'Q_'+'criteria'+'.png', bbox_inches='tight')

#%% STREAMFLOW CRITERIA THREE - OUI

iD_explos = ['best2']

dfcrit_Q = pd.read_csv(BV.calibration_folder+'_dfcrit_Q_'+iD_explos[0]+'.csv', sep=';')

df = dfcrit_Q.copy()
       
# fig, axs = plt.subplots(1,5, figsize=(5*6,5))
# axs = axs.ravel()
# for i, j in enumerate(['NSE','NSElog','RMSE','KGE','OWN']):
#     ax = axs[i]
#     # ax.plot(df['O'], df[j], marker='o')
#     ax.set_title(j)
#     ax.set_xlabel('Porosity [%]')
# # fig.suptitle(df.model_name[0].upper(), y=1.05)
# # fig.savefig('C:/Users/ronan/Downloads/figs_'+iD_explo+'/'+'Q_'+'criteria'+'.png', bbox_inches='tight')

n = 9
colors = pl.cm.plasma_r(np.linspace(0,1,n))

fig, axs = plt.subplots(3, 1, figsize=(4,9),
                        sharex=True
                        )
axs = axs.ravel()
for icri, cri in enumerate([
                            # 'NSElog',
                            'NSE','RMSE',
                            'KGE',
                            # 'OWN'
                            ][:]):
    
    
    # fig, ax = plt.subplots(1,1, figsize=(4.5,4.5),
    #                         # sharey=True
    #                         )
    
    ax = axs[icri]
    # fig, ax = plt.subplots(1,1, figsize=(5,4))
    for imod, mod in enumerate(df['id_mod'].unique()):
        imod=6
        color=colors[imod]
        color = 'indianred'
        if imod==0:
            color='k'
        if imod==1:
            color='grey'
        # color= 'k'
        dfplot = df[df['id_mod']==imod]
        # ax.plot(dfplot['O'], dfplot[cri],
        #         marker='|', ms=10, mew=1,
        #         lw=2,
        #         color=color)
        # ax.plot(dfplot['O'], dfplot[cri],
        #         marker='o', ms=10, mew=1,
        #         lw=0,
        #         color=color)
        if (cri == 'NSElog') | (cri == 'NSE') | (cri == 'KGE'):
            ax.plot(dfplot.sort_values('O')['O'], abs(1-dfplot.sort_values('O')[cri]),
                    marker='o', ms=0, mew=1,
                    lw=1,
                    color='gray')
            ax.plot(dfplot.sort_values('O')['O'], abs(1-dfplot.sort_values('O')[cri]),
                    marker='o', ms=6, mew=1,
                    lw=0,
                    color=color)
            x = dfplot.sort_values('O')['O']
            y = abs(1-dfplot.sort_values('O')[cri])
        else:
            ax.plot(dfplot.sort_values('O')['O'], dfplot.sort_values('O')[cri],
                    marker='o', ms=0, mew=1,
                    lw=1,
                    color='gray')
            ax.plot(dfplot.sort_values('O')['O'], dfplot.sort_values('O')[cri],
                    marker='o', ms=6, mew=1,
                    lw=0,
                    color=color)
        # pc = ax.scatter(dfplot['O'], dfplot[cri])
        if cri == 'NSE':
            ax.set_ylabel('|1-NSE| [-]')
            # ax.set_ylim(0.25,0.40)
            print('NSE', x[np.argmax(y)])
            ax.axhline(y[np.argmin(y)], zorder=-1000, c='darkorange')
            ax.axvline(x[np.argmin(y)], zorder=-1000, c='darkorange')
        if cri == 'NSElog':
            ax.set_ylabel('1 - $NSE_{log}$ [-]')
            ax.set_ylim(0.2,2.2)
            ax.set_yticks(np.arange(0.2,2.26,0.2))
            ax.set_xticks(np.arange(0,10.1,1))
            print('NSElog',dfplot.sort_values('O')['O'][np.argmax(dfplot.sort_values('O')[cri])])
            ax.axhline(y=0.32, c='forestgreen', zorder=-1)
            ax.axvline(x=1, c='forestgreen', zorder=-1)
        if cri == 'RMSE':
            ax.set_ylabel('RMSE [mm/w]')
            # ax.set_ylim(28,32)
            print('RMSE', dfplot.sort_values('O')['O'][np.argmin(dfplot.sort_values('O')[cri])])
            ax.axhline(dfplot.sort_values('O')[cri][np.argmin(dfplot.sort_values('O')[cri])], zorder=-1000, c='darkorange')
            ax.axvline(dfplot.sort_values('O')['O'][np.argmin(dfplot.sort_values('O')[cri])], zorder=-1000, c='darkorange')
        if cri == 'KGE':
            ax.set_ylabel('KGE [-]')
            # ax.set_ylim(28,32)
            # print('RMSE', dfplot.sort_values('O')['O'][np.argmin(dfplot.sort_values('O')[cri])])
            ax.axhline(y[np.argmin(y)], zorder=-1000, c='darkorange')
            ax.axvline(x[np.argmin(y)], zorder=-1000, c='darkorange')
        if icri==2:
            # ax.set_xlabel('$Φ_0$ [%]')
            ax.set_xlabel('$Sy_{max}$ [%]')
        # ax.set_title(cri)
        # ax.set_xscale('log')
        # ax.set_yscale('log')
        """
        if 0<=icri<=1:
            ax.set_ylim(0,0.4)
        if 4<=icri<=4:
            # ax.set_ylim(0,2.5)
            ax.set_yscale('log')
        """
        # position=fig.add_axes([1.05,0.33,0.03,0.5])  ##
        # cb = fig.colorbar(pc, cax=position, orientation='vertical')
        # cb.set_ticks(np.arange(0, 1.1, 0.25))
        # cb.set_ticklabels(np.arange(1, 2.1, 0.25))
        # cb.set_label('$A_{diff}$ [-]', rotation=270, labelpad=40)
        # cb.ax.tick_params(top=True,
        #             bottom=True,
        #             left=False,
        #             right=False,
        #             labelleft=False,
        #             labelbottom=True)
        
        # ax.axhline(dfplot.sort_values('O')['O'][np.argmin(dfplot.sort_values('O')[cri])])
        # ax.axvline(dfplot.sort_values('O')[cri][np.argmin(dfplot.sort_values('O')[cri])])

        ax.axvline(1, c='forestgreen', ls='--', zorder=-10000)

# ax.set_xticks([0,1,2,3,4,5,6,7,8,9,10])
# ax.set_xlim(0,5)
plt.tight_layout()

fig.savefig(fig_path + '/03_fig_calibrated/'+
            'Q_'+'allcrit'+'_3'+'.png',
                        bbox_inches='tight')

# fig.savefig('C:/Users/ronan/Downloads/figs_'+iD_explos[0]+'/'+'Q_'+'criteria'+'.png', bbox_inches='tight')

#%% SATURATION CHRONICS ONE - OUI

iD_explos = ['best2']
# iD_explos = ['e16']

sat_typ = 'total_areas'

areas = [
          3.7,
         ]

df = pd.DataFrame()

dict_S_wname = {}
    
BV = watershed_root.Watershed(watershed_name=watershed_name, dem_path=dem_path, out_path=out_path, load=True)

stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' # necessary for plots
BV.calibration_folder = out_path+'/'+watershed_name+'/'+'results_calibration/'

dem_data = imageio.imread(stable_folder + 'geographic/' + 'watershed_dem.tif')

# list_sat_obs = []
# for type_obs in types_obs:
#     path_hydro = stable_folder + 'hydrography/' + type_obs + '.tif'
#     path_hydro = 'D:/Users/abherve/ONEDRIVE_UNINECHYN/OneDrive - unine.ch/SIMULATIONS/Lasset/results_calibration/v6_model11_300.0-0_10-1.79e-07/_matchingstreams/obsflow.tif'
#     # path_hydro = 'D:/Users/abherve/ONEDRIVE_UNINECHYN/OneDrive - unine.ch/SIMULATIONS/Lasset/results_calibration/e1_model4_20.0-0-3.72e-06_0_40.0-0.1/_postprocess/_rasters/persistency_index_t(-).tif'
#     obs_hydro = imageio.imread(path_hydro)
#     # obs_hydro = np.ma.masked_where(dem_data==-99999, obs_hydro)
#     obs_hydro = np.ma.masked_where(obs_hydro==-0, obs_hydro)
#     obs_hydro_masked = np.ma.masked_where(obs_hydro<0, obs_hydro)
#     dd_hydro = round(obs_hydro_masked.count() / obs_hydro.count() * 100, 2)
#     # plt.imshow(obs_hydro_masked)
#     print(dd_hydro)
#     list_sat_obs.append(dd_hydro)

# list_sat_obs = [5,10] # 7
list_sat_obs = [7,14] # 7

i=0

for iD_explo in iD_explos:

    # for id_mod_val in list_id_mod[4:5]:
    # for id_mod_val in list_id_mod[:]:
    for id_mod_val in [6]:
        
        # id_mod_val = 6
        
        h5file = BV.calibration_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)
        d = dd.io.load(h5file)
        list_model_name = d['list_model_name'][:]
        list_model_success = d['list_model_success'][:]
        list_model_modflow = d['list_model_modflow'][:]
        
        for model_name, model_success, model_modflow in zip(list_model_name[:],
                                                            list_model_success[:],
                                                            list_model_modflow[:]):
            
            Smod = pd.read_csv(BV.calibration_folder+'/'+model_name+'/_postprocess/_timeseries/_simulated_timeseries.csv', sep=';',
                               index_col='date', parse_dates=True)
    
            Sat_mod = Smod[sat_typ] # m/day
                    
            Smin = Sat_mod.min()
            Smean = Sat_mod.mean()
            Smax = Sat_mod.max()
            S10 = Sat_mod.quantile(0.10)
            S25 = Sat_mod.quantile(0.25)
            S50 = Sat_mod.quantile(0.50)
            S75 = Sat_mod.quantile(0.75)
            S90 = Sat_mod.quantile(0.90)
            
            df.loc[i,'model_name'] = model_name
            
            df.loc[i,'id_explo'] = iD_explo
            df.loc[i, 'id_mod'] = id_mod_val
            
            df.loc[i,'aK'] = float(model_name.split('_')[2].split('-')[0])
            df.loc[i,'bottom'] = float(model_name.split('_')[2].split('-')[1])
            df.loc[i,'K'] = float(['-'.join(model_name.split('_')[2].split('-')[-2:])][0])
            
            df.loc[i,'id_eO'] = float(model_name.split('_')[3][0])
            
            df.loc[i,'aO'] = float(model_name.split('_')[4].split('-')[0])
            df.loc[i,'O'] = float(model_name.split('_')[4].split('-')[1])
                
            df.loc[i,'Smin'] = float(Smin)
            df.loc[i,'Smean'] = float(Smean)
            df.loc[i,'Smax'] = float(Smax)
            df.loc[i,'S10'] = float(S10)
            df.loc[i,'S25'] = float(S25)
            df.loc[i,'S50'] = float(S50)
            df.loc[i,'S75'] = float(S75)
            df.loc[i,'S90'] = float(S90)
            
            print(model_name, S10, S50, S90)
            
            df.loc[i,'Obs_per'] = list_sat_obs[0]
            df.loc[i,'Obs_med'] = (list_sat_obs[0]+list_sat_obs[-1])/2
            df.loc[i,'Obs_ful'] = list_sat_obs[-1]
            
            df.loc[i,'OWN_MIN'] = float(((S25 - df.loc[i,'Obs_per'])**2) / (df.loc[i,'Obs_per']**2))
            df.loc[i,'OWN_MED'] = float(((S50 - df.loc[i,'Obs_med'])**2) / (df.loc[i,'Obs_med']**2))
            df.loc[i,'OWN_MAX'] = float(((S75 - df.loc[i,'Obs_ful'])**2) / (df.loc[i,'Obs_ful']**2))
            
            df.loc[i,'OWN'] = ( df.loc[i,'OWN_MIN'] + df.loc[i,'OWN_MED'] + df.loc[i,'OWN_MAX'] ) / 3
    
            i += 1
    
            fig, ax = plt.subplots(1, 1, figsize=(7,3))
            
            ax.fill_between(Smod.index, 0, Smod['total_areas'],
                            interpolate=False, color='dodgerblue', alpha=0.5,
                            step='pre', label='Intermittent')
            ax.fill_between(Smod.index, 0, Smod['perenn_areas'],
                            interpolate=False, color='navy', alpha=0.5,
                            step='pre', label='Perennial')
            # ax.legend(loc='upper left')
            ax.step(Smod.index, Smod['total_areas'], color='dodgerblue',
                    marker=None, markeredgecolor='none',
                    markersize=5, lw=1, label='upstream',
                    where='pre')
            ax.step(Smod.index, Smod['perenn_areas'], color='navy',
                    marker=None, markeredgecolor='none',
                    markersize=5, lw=1, label='upstream',
                    where='pre')
            # ax.step(Smod.index, Smod['seepage_areas'], color='grey',
            #         marker=None, markeredgecolor='none',
            #         markersize=5, lw=1, label='upstream',
            #         where='pre')
            
            ax.set_ylim(1,25)
            ax.set_yticks([5, 10, 15, 20,25])
            ax.set_ylabel('$A_{sat}$ [%]')
            ax.set_xlim(pd.to_datetime('2020-01-08'), pd.to_datetime('2023'))
            plt.xticks(rotation=0, ha="center")
            ax.set_xticklabels([])
        
            years_maj = mdates.YearLocator()   # every year
            months_maj = mdates.MonthLocator()  # every x month
            ax.xaxis.set_major_locator(years_maj)
            ax.xaxis.set_minor_locator(months_maj)
            
            ax.set_title(model_name.upper(), fontsize=10)
            
            ax.grid(which='major', axis='x')
            
            for j, hline in enumerate(list_sat_obs[:2]):
                if j == 0:
                    cl = 'navy'
                if j == 1:
                    cl = 'dodgerblue'
                # ax.axhline(hline, c=cl, ls='--', zorder=-10)
                
            fig.tight_layout()
                        
            # fig.savefig(os.path.join(simulations_folder, '_figures',
            #             'SATURATION_'+model_name+'.png'),
            #             bbox_inches='tight')
            
            # plt.close()
            
            # fig.savefig('C:/Users/ronan/Downloads/figs_'+iD_explos[0]+'/'+'S_'+model_name+'.png',
            #             bbox_inches='tight')
            
            fig.savefig(fig_path + '/03_fig_calibrated/'+
                        'S_'+model_name+'.png',
                                    bbox_inches='tight')
        
dfcrit_S = df.copy()

#%% MAP MIN MAX

iD_explos = ['best2']

types_obs = ['hydrographic_mix_peren_upv2_pt_pt']

sat_typ = 'total_areas'

areas = [
          3.7,
         ]

df = pd.DataFrame()

dict_S_wname = {}
    
BV = watershed_root.Watershed(watershed_name=watershed_name, dem_path=dem_path, out_path=out_path, load=True)

stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' # necessary for plots
BV.calibration_folder = out_path+'/'+watershed_name+'/'+'results_calibration/'

dem_data = imageio.imread(stable_folder + 'geographic/' + 'watershed_dem.tif')

line = imageio.imread(os.path.join(stable_folder, 'geographic', 'watershed_contour.tif'))
line = np.ma.masked_where(line <= 0, line)

mask = imageio.imread(os.path.join(stable_folder, 'geographic', 'watershed_dem.tif'))

# list_sat_obs = []
# for type_obs in types_obs:
#     path_hydro = stable_folder + 'hydrography/' + type_obs + '.tif'
#     path_hydro = 'D:/Users/abherve/ONEDRIVE_UNINECHYN/OneDrive - unine.ch/SIMULATIONS/Lasset/results_calibration/v6_model11_300.0-0_10-1.79e-07/_matchingstreams/obsflow.tif'
#     # path_hydro = 'D:/Users/abherve/ONEDRIVE_UNINECHYN/OneDrive - unine.ch/SIMULATIONS/Lasset/results_calibration/e1_model4_20.0-0-3.72e-06_0_40.0-0.1/_postprocess/_rasters/persistency_index_t(-).tif'
#     obs_hydro = imageio.imread(path_hydro)
#     # obs_hydro = np.ma.masked_where(dem_data==-99999, obs_hydro)
#     obs_hydro = np.ma.masked_where(obs_hydro==-0, obs_hydro)
#     obs_hydro_masked = np.ma.masked_where(obs_hydro<0, obs_hydro)
#     dd_hydro = round(obs_hydro_masked.count() / obs_hydro.count() * 100, 2)
#     # plt.imshow(obs_hydro_masked)
#     print(dd_hydro)
#     list_sat_obs.append(dd_hydro)

# list_sat_obs = [5,10] # 7
# list_sat_obs = [5.2,17.8] # 7
list_sat_obs = [6,8] # 7

i=0

for iD_explo in iD_explos:
    
    list_id_mod = [6]

    for id_mod_val in list_id_mod[:]:
    
        h5file = BV.calibration_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)
        # if 'd' not in globals():
        d = dd.io.load(h5file)
        list_model_name = d['list_model_name'][:]
        list_model_success = d['list_model_success'][:]
        list_model_modflow = d['list_model_modflow'][:]
        
        # for model_name, model_success, model_modflow in zip(list_model_name[4:5],
        #                                                     list_model_success[4:5],
        #                                                     list_model_modflow[4:5]):
        for model_name, model_success, model_modflow in zip(list_model_name[1:2],
                                                            list_model_success[1:2],
                                                            list_model_modflow[1:2]):
            
            Smod = pd.read_csv(BV.calibration_folder+'/'+model_name+'/_postprocess/_timeseries/_simulated_timeseries.csv', sep=';',
                               index_col='date', parse_dates=True)
        
            min_area = Smod['total_areas'].min()
            min_idx = np.argmin(Smod['total_areas'])
            max_area = Smod['total_areas'].max()
            max_idx = np.argmax(Smod['total_areas'])
            max_year = Smod['total_areas'].index[max_idx]
            
            acc_npy = np.load(os.path.join(BV.calibration_folder+'/'+model_name+'/_postprocess/',  'accumulation_flux.npy'), allow_pickle=True).item()
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
                
                if k==0:
                    kv = 'Min. : '
                else:
                    kv = 'Max. : '
                ax.set_title(
                            # watershed_name + ' - ' + model_name.upper() + '\n' +
                              kv + str(year)[0:10] + '   ' + '$A_{sat}$ = ' + str(val.round(1)) + ' [%]',
                              pad=0, fontsize=8)
                ax.imshow(np.ma.masked_where(mask<0, mask), cmap='Greys', alpha=0.5, zorder=0)
                if k == 0:
                    days_flux_min = days_flux.copy()
                    ax.imshow(np.ma.masked_where((days_flux<=0) | (mask <0),
                                                 days_flux), 
                              cmap = mpl.colors.ListedColormap(['navy'])) # dodgerblue
                if k == 1:
                    ax.imshow(np.ma.masked_where((days_flux<=0) | (mask <0),
                                                 days_flux), 
                              cmap = mpl.colors.ListedColormap(['dodgerblue'])) # dodgerblue
                    ax.imshow(np.ma.masked_where((days_flux_min<=0) | (mask <0),
                                                 days_flux_min), 
                              cmap = mpl.colors.ListedColormap(['navy'])) # dodgerblue
                ax.imshow(line, cmap=mpl.colors.ListedColormap('k'))
                
                ax.get_xaxis().set_visible(False)
                ax.get_yaxis().set_visible(False)
                ax.axis('off')
                
                """
                try:
                    path_sub = os.path.join(glob.glob(
                        os.path.join(stable_folder, 'subbasin','intermittency*'))[0],
                        'watershed_contour.shp')
                    wbt.vector_lines_to_raster(path_sub,
                                               os.path.join(glob.glob(
                                                   os.path.join(stable_folder,
                                                                'subbasin',
                                                                'intermittency*'))[0],
                                                   'watershed_contour.tif'),
                                               base = os.path.join(stable_folder,
                                                                   'geographic',
                                                                   'watershed_dem.tif'))
                    line_sub = imageio.imread(os.path.join(glob.glob(
                        os.path.join(stable_folder, 'subbasin', 'intermittency*'))[0],
                        'watershed_contour.tif'))
                    line_sub = np.ma.masked_where(line_sub <= 0, line_sub)
                    ax.imshow(line_sub, cmap=mpl.colors.ListedColormap('grey'))
                except:
                    pass
                """
                
            # fig.suptitle(watershed_name + ' - ' + model_name.upper(), y=0.7, fontsize=8)
            
            fig.tight_layout()
                        
            # fig.savefig('E:/_RONAN/_E_SIMULATIONS/BRETAGNE/_transient/'+'_minmax/'+
            #             watershed_name+'_MAPminmax_'+model_name+'.png',
            #             bbox_inches='tight', dpi=300)
            
            fig.savefig(fig_path + '/03_fig_calibrated/'+
                        'S_'+'mapminmax'+model_name+'_bis'+'.png',
                                    bbox_inches='tight')

#%% CROSS MIN MAX

iD_explo = 'best2'

for watershed_name in watershed_names[:]:


    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'

    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  # modflow_path=modflow_path
                                  )
    
    BV.calibration_folder = out_path+'/'+watershed_name+'/'+'results_calibration/'
    
    # dem = rasterio.open(BV.geographic.watershed_dem)
    # dem_data = np.ma.masked_where(dem.read(1) < -100, dem.read(1)) # dem data
    
    dem_data = imageio.imread(BV.geographic.watershed_box_buff_dem)
    
    cur_y=110

    fig2, ax2 = plt.subplots(1, 1, figsize=(6,6), dpi=300)
    ax2.imshow(dem_data, cmap='Greys')
    # ax2.imshow(river_data, cmap='Greys')
    ax2.axhline(cur_y)
    
    for iD_explo in iD_explos:
        
        list_id_mod = [6]
    
        for id_mod_val in list_id_mod[:]:
        
            h5file = BV.calibration_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)
            # if 'd' not in globals():
            d = dd.io.load(h5file)
            list_model_name = d['list_model_name'][:]
            list_model_success = d['list_model_success'][:]
            list_model_modflow = d['list_model_modflow'][:]
        
            for model_name, model_success, model_modflow in zip(list_model_name[1:2],
                                                                list_model_success[1:2],
                                                                list_model_modflow[1:2]):
                
                fig, ax = plt.subplots(1, 1, figsize=(6,3), dpi=300)

                # Smod = pd.read_csv(BV.simulations_folder+'/'+model_name+'/_postprocess/_timeseries/_simulated_timeseries.csv', sep=';',
                #                    index_col='date', parse_dates=True)
                
                # # for i in np.arange(1980,2098,1):
                # #     Smodbis = select_period(Smod,i,i)
                # #     Smodbis = Smodbis.reset_index()
                # #     if i<2020:
                # #         c='k'
                # #     if i>2020:
                # #         c='red'
                # #     plt.plot(Smodbis['intermit_areas'], c=c)
                
                # Smod = Smod.reset_index()
                
                
                # argmin = Smod['total_areas'].argmin()
                # argmax = Smod['total_areas'].argmax()
                
                # argmin = Smod['watertable_elevation'].argmin()
                # argmax = Smod['watertable_elevation'].argmax()
                
                # argmin = Smod['seepage_areas'].argmin()
                # argmax = Smod['seepage_areas'].argmax()
                
                # argmin = Smod['watertable_depth'].argmax()
                # argmax = Smod['watertable_depth'].argmin()
                
                mask = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
                
                import itertools            
                
                # watertable_elevation = np.load(simulations_folder+model_name+'/_postprocess/'+'watertable_elevation'+'.npy', allow_pickle=True).item()
                BV.calibration_folder = out_path+'/'+watershed_name+'/'+'results_calibration/'
                watertable_elevation = np.load(BV.calibration_folder+model_name+'/_postprocess/'+'watertable_elevation'+'.npy', allow_pickle=True).item()
    
                # watertable_elevation = list(watertable_elevation.items())[-30*12:]
                
                list_min = []
                list_max = []
                for f in range(len(watertable_elevation)):
                    mini = watertable_elevation[f].min()
                    maxi = watertable_elevation[f].max()
                    list_min.append(mini)
                    list_max.append(maxi)
                
                argmin = pd.Series(list_min)[-30*12:].idxmin()
                argmax = pd.Series(list_max)[-30*12:].idxmax()
                
                # argmin = pd.Series(list_min)[:30*12].idxmin()
                # argmax = pd.Series(list_max)[:30*12].idxmax()
                
                min_wt = dict()
                
                cp = 0
                # for key in dict(itertools.islice(watertable_elevation.items(),
                #                                  len(watertable_elevation), # ONDE 8 years
                #                                  len(watertable_elevation))):
                for i, key in enumerate([argmin, argmax]):
                # for i, key in enumerate([0, 400]):
                    print(key)
            
                    
                    # wt_data = imageio.imread(simulations_folder+model_name+'/_watershed/_tifs/'+'watertable_elevation_t(0).tif')
                    wt_data = watertable_elevation[key]
                    # river_data = imageio.imread(stable_folder+'/hydrography/'+'stream_perennial_wetlands_points.tif')
                

                
                    xvalues = np.linspace(-1,1,dem_data.shape[1])
                    yvalues = np.linspace(-1,1,dem_data.shape[0])
                    xx, yy = np.meshgrid(xvalues,yvalues)
                    
                    cur_x = dem_data.shape[1] /2
                    cur_y = dem_data.shape[0] /2
                    
                    # cur_x = 65
                    # cur_y = 39 # 40
                    cur_y=110
    

    
                    dem_max = dem_data.max()
                    dem_prof = dem_data.astype(float)
                    dem_prof[dem_prof<0] = np.nan
                    wt_prof = wt_data.astype(float)
                    wt_prof[wt_prof<0] = np.nan
                    
                    if watershed_name == 'Lasset_25m':
                        dem_h_plot = dem_prof[int(cur_y),:]
                        dem_h_plot[dem_h_plot == 0] = np.nan
                        wt_h_plot = wt_prof[int(cur_y),:]
                        wt_h_plot[wt_h_plot == 0] = np.nan
                        
                        # list_h_wt[cp] = wt_h_plot
                        
                    if watershed_name == 'Canut':
                        dem_v_plot = dem_prof[:,int(cur_x)]
                        dem_v_plot[dem_v_plot == 0] = np.nan
                        wt_v_plot = wt_prof[:,int(cur_x)]
                        wt_v_plot[wt_v_plot == 0] = np.nan
                        
                        # list_v_wt[cp] = wt_v_plot
                        
                    dem_max = dem_data.max()
                    dem_prof = dem_data.astype(float)
                    dem_prof[dem_prof<0] = np.nan
                    dem_plot = np.ma.masked_array(dem_data, mask=(dem_data<0))
                    
                    wt_prof = wt_data.astype(float)
                    wt_prof[wt_prof<0] = np.nan
                    
                    cp+=1
                        
                    if watershed_name == 'Lasset_25m':
                        # dem_h_prof, = ax.plot(np.arange(xx.shape[1])*75,dem_h_plot, c='saddlebrown', lw=2)
                        # wt_h_prof, = ax.plot(np.arange(xx.shape[1])*75, wt_h_plot, c='dodgerblue', lw=2)
                        if i == 0:
                            wt_h_fill = ax.fill_between(np.arange(xx.shape[1])*25, dem_h_plot-1000, wt_h_plot,
                                                            color='navy', alpha=0.5, lw=0)
                            w_prof = ax.plot(np.arange(xx.shape[1])*25, wt_h_plot, color='navy', lw=1)
                        if i == 1:
                            wt_h_fill = ax.fill_between(np.arange(xx.shape[1])*25, dem_h_plot-1000, wt_h_plot,
                                                            color='dodgerblue', alpha=0.5, lw=0)
                            w_prof = ax.plot(np.arange(xx.shape[1])*25, wt_h_plot, color='dodgerblue', lw=1)
                            wt_h_fill = ax.fill_between(np.arange(xx.shape[1])*25, wt_h_plot, dem_h_plot,
                                                            color='saddlebrown', alpha=0.5, lw=0)
                            d_prof = ax.plot(np.arange(xx.shape[1])*25, dem_h_plot, 'saddlebrown', lw=1.5)
                        for h in np.linspace(100,1000,100):
                            ax.fill_between(np.arange(xx.shape[1])*25, 0, dem_h_plot-h,
                                                            color='lightgrey', alpha=0.1, lw=0)
                        # ax.fill_between(np.arange(xx.shape[1])*25, 0, dem_h_plot-300,
                        #                                 color='lightgrey', alpha=0.5, lw=0)
                        # ax.plot(np.arange(xx.shape[1])*25, dem_h_plot-300, color='dimgray', lw=1.5)
                        ax.set_xlim(0, 3800)
                        ax.set_ylim(1400, 2200)
                        # ax.set_xlim(2800, 3500)
                        # ax.set_ylim(1500, 1900)
                        ax.set_yticks([1400,1600,1800,2000,2200])
                               
                    # ax.set_title(str(dates[key])[:7])
                    # print((str(dates[key])[:7]))
                    
                    ax.set_title(model_name, fontsize=8)
                    plt.tight_layout()

fig.savefig(fig_path + '/03_fig_calibrated/'+
            'Cross_section_minmax_'+model_name+'_bis'+'.png',
                        bbox_inches='tight', dpi=600)

#%% ---- 3 - MODPATH FOR EXTREMES

#%% UPDATE PARAMETERS

# Name of sims
iD_explo = 'modpath2' # with isba recharge ==> change ss with decay factor (details for bad models)

# From dichotomy
vers = 'aniso1' # dichotomy isba
df_optim = pd.read_csv(BV.calibration_folder+'/'+'_models'+'_optimum_'+vers+'.csv', sep=';')

# Catchment
BV = watershed_root.Watershed(watershed_name=watershed_name, dem_path=dem_path, out_path=out_path, load=True)
area = BV.geographic.area
stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' # necessary for plots
BV.calibration_folder = out_path+'/'+watershed_name+'/'+'results_calibration/'

# Aquifer bottom
list_bottom = [1000] * 9 # aquifer flat or not

# Decay of K
list_d_values = [0, 300, 200, 100, 50, 40, 30, 20, 10]
list_cond_decay = list(1/np.array(list_d_values))      
list_cond_decay[0] = 0
list_id_mod = [1,2,3,4,5,6,7,8,9]

# For transient
list_koptim = df_optim['K']

# Parameters
decay_factor = 2
box = True # or False
sink_fill = False # or True
sim_state = 'steady' # 'steady' or 'transient'
plot_cross = True
check_grid = True
dis_perlen = True
nlay = 10
lay_decay = 1.25 # 1 for no decay
thick = 30 # if bottom is None, aquifer thickness
verti_hk = None # or [ [1e-5, [0, 20]],
verti_sy = None
verti_ss = None
cond_drain = None # or value of conductance
Kmin = 1e-10 * 3600 * 24 
Klog_transf = False
symin = 0.01/100
sylog_transf = False
ss = 1e-5
ssmin = 1e-8
sslog_transf = False
bc_left = None # or value
bc_right = None # or value
sea_level = 'None' # or value based on specific data : BV.oceanic.MSL
zone_partic = 'domain' # or watershed
vka = 1
for_calib = False
first_clim = 'mean'

recharge = select_period(rea_recharge_isba, 2020, 2023)
# recharge_w_sli = recharge.resample('7D', origin='start_day', label='right', closed='left', offset='-1D').mean()
runoff = select_period(rea_runoff_isba, 2020, 2023)
# runoff_w_sli = runoff.resample('7D', origin='start_day', label='right', closed='left', offset='-1D').mean()

BV.add_settings()
BV.add_climatic()
BV.add_hydraulic()

BV.climatic.update_recharge(recharge, sim_state=sim_state)
BV.climatic.update_runoff(runoff, sim_state=sim_state)
BV.climatic.update_first_clim(first_clim)

BV.settings.update_box_model(box)
BV.settings.update_sink_fill(sink_fill)
BV.settings.update_simulation_state(sim_state)
BV.settings.update_check_model(plot_cross=plot_cross, check_grid=check_grid)
BV.hydraulic.update_nlay(nlay) # 1
BV.hydraulic.update_lay_decay(lay_decay) # 1
BV.hydraulic.update_thick(thick) # 30 / intervient pas si bottom != None

BV.hydraulic.update_cond_drain(cond_drain)
BV.hydraulic.update_vka(vka)

BV.hydraulic.update_ss(ss)

BV.hydraulic.update_hk_vertical(verti_hk)
BV.hydraulic.update_sy_vertical(verti_sy)
BV.hydraulic.update_ss_vertical(verti_ss)

BV.add_oceanic(sea_level)
BV.settings.update_dis_perlen(dis_perlen)
BV.settings.update_bc_sides(bc_left, bc_right)
BV.settings.update_input_particles(zone_partic=zone_partic)

# list_porosity = np.array([1])/100
poro_val = 1/100

#%% PRO PREPROCESSING

run_model = True
# run_model = False
 
# for cond_decay_val, bottom_val, koptim_val, id_mod_val in zip(
#                                                               list(list_cond_decay[i] for i in [2-1, 6-1]),
#                                                               list(list_bottom[i] for i in [2-1, 6-1]),
#                                                               list(list_koptim[i] for i in [2-1, 6-1]),
#                                                               list(list_id_mod[i] for i in [2-1, 6-1])
#                                                               ): 
for cond_decay_val, bottom_val, koptim_val, id_mod_val in zip(
                                                              list(list_cond_decay[i] for i in [6-1]),
                                                              list(list_bottom[i] for i in [6-1]),
                                                              list(list_koptim[i] for i in [6-1]),
                                                              list(list_id_mod[i] for i in [6-1])
                                                              ): 
    
    BV.hydraulic.update_bottom(bottom_val) # 0
    BV.hydraulic.update_hk_decay(cond_decay_val, min_value=Kmin, log_transf=Klog_transf) # 0
    BV.hydraulic.update_hk(koptim_val)
    BV.hydraulic.update_sy_decay(cond_decay_val/decay_factor, min_value=symin, log_transf=sylog_transf)
    BV.hydraulic.update_ss_decay(cond_decay_val/decay_factor, min_value=ssmin, log_transf=sslog_transf)
    
    dictio = {}
    
    list_model_name = []
    list_model_success = []
    list_model_modflow = []
        
    # for ip, poro_val in enumerate(list_porosity[-1:]):
    # for ip, poro_val in enumerate(list_porosity[:1]):
        
    BV.hydraulic.update_sy(poro_val)
    #Ss_formula = 1000*9.8*(1e-10+(poro_val*4.4e-10)) # rho*g*(alpha+nBeta)
    # print(Ss_formula)
    
    if cond_decay_val == 0 :
        str_cond_decay = cond_decay_val
        str_poro_decay = cond_decay_val/decay_factor
    else:
        str_cond_decay = 1/cond_decay_val
        str_poro_decay = 1/(cond_decay_val/decay_factor)
    if bottom_val==None:
        str_bottom = thick
    else:
        str_bottom = bottom_val
        
    if poro_val == 0:
        str_poro_decay = 0
    
    model_name = iD_explo+'_'+str('model')+str(id_mod_val)+'_'+\
                 str(round(str_cond_decay,4))+'-'+str(round(str_bottom,4))+'-'+str("{:.2e}".format(koptim_val/24/3600))+'_'+\
                 str(round(str_poro_decay,4))+'-'+str(round(poro_val*100,2))
    
    print(model_name)
    
    BV.settings.update_model_name(model_name)
    
    now = datetime.now()
    oclock = now.strftime("%Y%m%d-%Hh%Mm%Ss")

    model_modflow = BV.preprocessing_modflow(for_calib=for_calib)
    
    model_success = BV.processing_modflow(model_modflow, write_model=True, run_model=run_model)
        
    list_model_name.append(model_name)
    list_model_success.append(model_success)
    list_model_modflow.append(model_modflow)
                
    dictio['list_model_name'] = list_model_name
    dictio['list_model_success'] = list_model_success
    dictio['list_model_modflow'] = list_model_modflow
    h5file = BV.calibration_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)
    dd.io.save(h5file, dictio)
    
    BV.postprocessing_modflow(model_modflow,
                          watertable_elevation = True,
                          watertable_depth = True, 
                          seepage_areas = True,
                          outflow_drain = True,
                          groundwater_flux = True,
                          groundwater_storage = True,
                          accumulation_flux = True,
                          persistency_index = True,
                          intermittency_monthly = False,
                          intermittency_weekly = True,
                          intermittency_daily = False,
                          export_all_tif = False)
    
            
    # Particle tracking settings
    tif_file = BV.simulations_folder + '/' + model_name + '/_postprocess/_rasters/seepage_areas_t(0).tif'
    tif_file_clip = BV.simulations_folder + '/' + model_name + '/_postprocess/_rasters/seepage_areas_t(0)_clip.tif'
    
    wbt.clip_raster_to_polygon(tif_file, data_path+'/_sig/created/watershed_all_grenou.shp', tif_file_clip, maintain_dimensions=True)
    
    BV.settings.update_input_particles(zone_partic = tif_file_clip,
                                        cell_div = 1, # 1
                                        zloc_div = False,  # or False, add cells at cell bottom
                                        bore_depth = None, # '[0,5,10] for 3 particles or None
                                        track_dir = 'backward',
                                        # track_dir = 'forward', # backward
                                        sel_random = None, # or int
                                        sel_slice = None, # or int
                                        )
    
    model_modpath = BV.preprocessing_modpath(model_modflow, for_calib=for_calib)
    success_modpath = BV.processing_modpath(model_modpath, write_model=True, run_model=True)
    
    # if success_modpath == True:
    BV.postprocessing_modpath(model_modpath,
                              ending_point=True,
                              starting_point=True,
                              pathlines_shp=True,
                              particles_shp=True,
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
    
    timeseries_results = BV.postprocessing_timeseries(model_modflow=model_modflow,
                                                      model_modpath=model_modpath,
                                                      datetime_format=False,
                                                      subbasin_results=True,
                                                      intermittency_weekly=True)
    
#%% PLOT PATHLINES 3D

from IPython import get_ipython
get_ipython().run_line_magic('matplotlib', 'inline')

from mpl_toolkits.mplot3d import Axes3D

list_model_names = ['modpath1_model6_40.0-1000-2.94e-06_80.0-1.0',
                    'modpath1_model2_300.0-1000-5.51e-07_600.0-1.0'
                    ]

# fig = plt.figure()
# ax = fig.add_subplot(111, projection='3d')

im_dem_data = imageio.imread(BV.geographic.watershed_dem)
# im_dem = plt.imshow()

# dem_data = imageio.imread('E:/_RONAN/_E_SIMULATIONS/LASSET/Lasset_25m/results_stable/subbasin/subbasin_Qgrenou/watershed_dem.tif')

# fig2, ax2 = plt.subplots(1,1, figsize=(5, 5), dpi=300)

for i, model_name in enumerate(list_model_names[:]):
    
    fig = plt.figure(figsize= (10,10), dpi=300)
    ax = fig.add_subplot(111, projection='3d')
    
    # ax.set_proj_type('ortho')
    # ax.set_proj_type('persp', focal_length=0.2)
    ax.set_proj_type('persp', focal_length=1)
    
    ax.view_init(elev=10, azim=0, roll=0)
    
    # export_vtuvtk.VTK(BV, model_name)
    # visu = visualization_results.Visualization(BV, model_name)
    # visu.visual3D(interactive=True, object_list=[
    #                                               # 'grid',
    #                                               # 'watertable',
    #                                               # 'watertable_depth',
    #                                               # 'surface_flow',
    #                                               # 'drain_flow',
    #                                               'pathlines'
    #                                               ],
    #                                                 view='south-west',
    #                                               # view='north',
    #                                               lines=None,
    #                                               cloc=(0.7,0.1),
    #                                               z_scale=1)
        
    print(model_name)
    
    mf = flopy.modflow.Modflow.load(BV.simulations_folder+'/'+model_name+'/'+model_name+'.nam')
    
    fname = BV.simulations_folder+'/'+model_name+'/'+model_name+'.hds'
    gridname = BV.simulations_folder+'/'+model_name+'/'+model_name+'.dis'
    # grid_model = flopy.discretization.grid.Grid(mf)
    grid_model = mf.modelgrid
    hk_grid = mf.upw.hk
    pthobj = flopy.utils.PathlineFile(BV.simulations_folder+'/'+model_name+'/'+model_name+'.mppth')
    pth_data = pthobj.get_alldata()
    
    prt_path = BV.simulations_folder + '/' + model_name + '/_postprocess/_particles/particles_weighted.shp'
    prt_file = gpd.read_file(prt_path)
    
    # list_id_prt = prt_file['particleid'].unique()
    # if i == 0:
    #     list_id_prt = np.random.choice(list_id_prt, 100)
    # if i == 1:
    #     list_id_prt = np.random.choice(list_id_prt, 100)
    # prt_file_plot =  prt_file[prt_file['particleid'].isin(list_id_prt)]
    
    srt_path = BV.simulations_folder + '/' + model_name + '/_postprocess/_particles/starting_weighted.shp'
    srt_file = gpd.read_file(srt_path)
    
    if i == 0:        
        list_id_prt = srt_file['particleid'].unique()
        # list_id_prt_spe = list_id_prt_spe.copy()
        list_id_prt_spe = np.random.choice(list_id_prt, 300)
        print('    ', len(list_id_prt))
        # list_id_prt_temp = np.random.choice(list_id_prt, 300)
        # srt_file_fil =  srt_file[srt_file['particleid'].isin(list_id_prt_temp)]
        # srt_file_fil['xy'] = srt_file_fil['geometry'].values
        # list_geom_fil = srt_file_fil['geometry'].values
        
        prt_file_plot = prt_file[prt_file['particleid'].isin(list_id_prt_spe)]
            
    if i ==1:        
        # srt_file_fil = srt_file.copy()
        # srt_file_fil['xy'] = srt_file_fil['geometry'].values
        # srt_file_fil =  srt_file_fil[srt_file_fil['xy'].isin(list_geom_fil)]        
        # list_id_prt = srt_file_fil['particleid'].unique()
        print('    ', len(list_id_prt))
        
        prt_file_plot = prt_file[prt_file['particleid'].isin(list_id_prt_spe)]
    
    # ax = Axes3D(fig)
     
    z = prt_file_plot['z']
    x = prt_file_plot['x']
    y = prt_file_plot['y']
    c = prt_file_plot['time_y']
     
    # For scatter plot
    # ax.scatter(x, y, t, c='r', marker='o')
    # ax.plot(x, y, z, c='r', marker='o', ms=0.2, markeredgecolor='None')
    # ax.scatter(x, y, z, c=c)
    # For line plot
    if i == 0:
        color = 'darkorange'
    if i == 1:
        color = 'darkmagenta'
    # prt_file.plot(column='time')
    
    # ax.plot(x, y, z, marker='o', lw=0, ms=1, color=color, mec='None')

    for pi in prt_file_plot['particleid'].unique():
        # print(pi, len(prt_file_plot['particleid'].unique()))
        toplot = prt_file_plot[prt_file_plot['particleid']==pi]
        
        # if all(z >= 1000 for z in toplot['z']):
        #     ax.plot(toplot['x'], toplot['y'], toplot['z'], ms=0, lw=1, color=color,
        #             zorder=0)
        
        ax.plot(toplot['x'], toplot['y'], toplot['z'], ms=0, lw=1, color=color,
                zorder=0)
        
    # test = gdal.Open(BV.geographic.watershed_box_buff_dem)
    test = gdal.Open(BV.simulations_folder + '/' + model_name + '/_postprocess/_rasters/'+'watertable_elevation_t(0).tif')
    dem = test.ReadAsArray()
    # transformation of coordinates
    gt = test.GetGeoTransform()
    # x = (col * gt[1]) + gt[0]
    # y = (row * gt[5]) + gt[3]
    xres = abs(gt[1])
    yres = abs(gt[5])
    # X = np.arange(gt[0], gt[0] + dem.shape[1]*xres, xres)
    # Y = np.arange(gt[3], gt[3] + dem.shape[0]*yres, yres)
    X = np.arange(0, im_dem_data.shape[1]*xres, xres)
    Y = np.arange(0, im_dem_data.shape[0]*yres, yres)
    # creation of a simple grid without interpolation
    X, Y = np.meshgrid(X, Y)
    # plot the raster

    # fig = plt.figure()
    # ax = fig.add_subplot(111, projection='3d')
    surf = ax.plot_surface(X, Y[::-1], dem,
                            rstride=1, cstride=1,
                            cmap=mpl.colors.ListedColormap('dodgerblue'),                       
                            # cmap=cm.Greys,
                            # facecolors=None,
                            # eddgecolor=None,
                            lw=0, antialiased=False, alpha=0.1, zorder=1000,
                            clip_on=True)
    ax.plot_wireframe(X, Y[::-1], dem, rstride=1, cstride=1, lw=0.1, alpha=0.5, edgecolor='k', zorder=2000)

    xlims = ax.get_xlim()
    ylims = ax.get_ylim()
    zlims = ax.get_zlim()
    
    # ax.set_xlim(0,xlims[1])
    # ax.set_ylim(0,ylims[1])
    ax.set_xlim(0,4000)
    ax.set_ylim(0,5000)
    ax.set_zlim(1000,2200)
    ax.set_xticks([0,1000,2000,3000,4000])
    ax.set_yticks([0,1000,2000,3000,4000,5000])
    
    # ax.set_xticks([])
    # ax.set_yticks([])
    # ax.set_zticks([])
    
    plt.setp( ax.get_xticklabels(), visible=False)
    plt.setp( ax.get_yticklabels(), visible=False)
    plt.setp( ax.get_zticklabels(), visible=False)
    
    # ax.grid(alpha=0.5)
        
    # if i == 0:
    #     fig.savefig('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_figures_paper/_v0/f_sup_pathlines/'+
    #                 '3D_plot_'+str(i)+'_toplt'+'.png',
    #                             bbox_inches='tight', dpi=300)

# import mayavi.mlab as mlab
# mlab.plot3d(prt_file['x'], prt_file['y'], prt_file['z'], lw=2)

#%% CROSS - PLOT 2D

list_model_names = ['modpath1_model6_40.0-1000-2.94e-06_80.0-1.0',
                    'modpath1_model2_300.0-1000-5.51e-07_600.0-1.0'
                    ]

from IPython import get_ipython
get_ipython().run_line_magic('matplotlib', 'inline')

for i, model_name in enumerate(list_model_names[:]):
    
    fig, ax = plt.subplots(1,1, figsize=(8, 4), dpi=300)

    # export_vtuvtk.VTK(BV, model_name)
    # visu = visualization_results.Visualization(BV, model_name)
    # visu.visual3D(interactive=True, object_list=[
    #                                              # 'grid',
    #                                              # 'watertable',
    #                                              # 'watertable_depth',
    #                                              # 'surface_flow',
    #                                              # 'drain_flow',
    #                                              'pathlines'
    #                                              ],
    #                                                view='south-west',
    #                                               # view='north',
    #                                               lines=None,
    #                                               cloc=(0.7,0.1),
    #                                               z_scale=1)
        
    print(model_name)
    
    mf = flopy.modflow.Modflow.load(BV.simulations_folder+'/'+model_name+'/'+model_name+'.nam')          
    fname = BV.simulations_folder+'/'+model_name+'/'+model_name+'.hds'
    hk_grid = mf.upw.hk
    
    # prt_path = BV.simulations_folder + '/' + model_name + '/_postprocess/_particles/particles_weighted.shp'
    # prt_file = gpd.read_file(prt_path)
    
    # modelmap = flopy.plot.PlotMapView(model=mf)
    # linecollection = modelmap.plot_grid(linewidth=0.5, color='royalblue')
    # line_cross = np.array([(20, 20),(50,50)])
    # plt.plot(line_cross)
    # xsect = flopy.plot.PlotCrossSection(model=mf, line={'line': line_cross})
    xsect = flopy.plot.PlotCrossSection(model=mf, line={'column': 80})
    # xsect.plot_grid()
    # xsect = flopy.plot.PlotCrossSection(model=mf, line={'row': 50})
    linecollection = xsect.plot_grid(color='k', alpha=0.25, lw=0)
    xsect.get_extent()
    # xsect.plot_bc()
    hdobj = flopy.utils.HeadFile(fname)
    head = hdobj.get_data(mflay=None)
    
    nrow = mf.dis.nrow
    ncol = mf.dis.ncol
    
    wt = pp.get_water_table(head, -100) # -9999
    wt = np.ones((nrow, ncol)) * wt
    
    xsect.plot_fill_between(head, color='saddlebrown', edgecolor='none', alpha=0.25)
    # pc = xsect.plot_array(head,
    #                       masked_values=[-9999.0], head=head, alpha=0.25,
    #                       cmap = 'Blues', lw=0,
    #                       vmin=0, vmax=2350)
    
    val = hk_grid.array/24/3600
    # if i ==0:
    #     cb = xsect.plot_array(val, ax=ax, cmap='plasma', lw=0.1,
    #                                 norm=mpl.colors.LogNorm(vmin=2e-7, 
    #                                                         vmax=1e-10), alpha=0.5
    #                                )
    # if i ==1:
    #     cb = xsect.plot_array(val, ax=ax, cmap='plasma', lw=0.1,
    #                                 norm=mpl.colors.LogNorm(vmin=2e-6, 
    #                                                         vmax=1e-9), alpha=0.5
    #                                )
    
    cb = xsect.plot_array(val, ax=ax, cmap='Greys_r', lw=0.25,
                                norm=mpl.colors.LogNorm(vmin=1e-10, 
                                                        vmax=3e-6), alpha=0.5
                               )
    
    if i == 0:
        color = 'purple'
    if i == 1:
        color = 'darkorange'
    ps = xsect.plot_surface(wt, lw=1.5)
    patches = xsect.plot_ibound(head=head, lw=3)
    # linecollection = xsect.plot_grid()
    # cb = plt.colorbar(pc, shrink=0.75)
    ax.set_ylim(1000,2350)
    xlims = ax.get_xlim()
    # pc = modelxsect.plot_array(head_data, masked_values=[-9999], head=head_data,
    #                             cmap='Blues', alpha=0.5, ax=axs[1])
    ax.set_title(model_name.upper(), fontsize=6)
    # ax.set_title('Hydraulic conductivity [m/s]', fontsize=12)
    # ax.set_xlim(150, 350)
    # ax.set_ylim(0, 2500)
    ax.set_yticks([1000,1200,1400,1600,1800,2000,2200])
    
    ax.invert_xaxis()
    plt.tight_layout()
    fig.colorbar(cb)
    
    # r, c = np.arange(nrow-1), np.arange(ncol-1)
    # for er in np.arange(nrow-1):
    #     for ec in np.arange(ncol-1):
    for er in [68]:
        for ec in [114]:
            print(er, ec)
            trans = flopy.utils.get_transmissivities(heads=head, m=mf,r=np.array([er]), c=np.array([ec]))
            # hk_cell = mf.lpf.hk.array[:, er, ec]
            # grid_cell = mf.modelgrid.cell_thickness[:, er, ec]
            tfrac = trans / trans.sum(axis=0)
    trans = trans[:,0]
                     
    botm_thick = mf.dis.botm[:,68,114] 
    cell_thick = botm_thick.copy()
    for b in range(len(cell_thick)):
        if b>0:
            cell_thick[b] = botm_thick[b-1] - botm_thick[b]
    cell_thick[0] = mf.dis.top[68,114] - botm_thick[0]
    
    mean_n = trans[trans>0].mean()
    mean_w = np.sum((trans[trans>0] * cell_thick[trans>0])) / cell_thick[trans>0].sum()
    mean_g = 10**(np.sum((np.log10(trans[trans>0]) * cell_thick[trans>0])) / cell_thick[trans>0].sum())
    print(mean_n/24/3600)
    # print(mean_w/24/3600)
    # print(mean_g/24/3600)

    # fig2, ax2 = plt.subplots(1,1, figsize=(8, 4), dpi=300)
    # ax2.boxplot(trans/24/3600)


    # head_profile = pc.get_array()[0:170]
    # xsect.plot_pathline(pth_data[:], method='cell', colors='k',
    #                     # head=pc.get_array()
    #                     )
    # xsect.plot_endpoint(e, direction='ending')
    
    # if i ==0:
    #     toplot = prt_file[prt_file['particleid']==693]
    # if i ==1:
    #     toplot = prt_file[prt_file['particleid']==360]
    # ax.plot(toplot['y'],toplot['z'], marker='o')
    
    # for i in prt_file['particleid'].unique():
    #     toplot = prt_file[prt_file['particleid']==i]
    #     toplot = toplot.sort_values('y')
    #     ax.plot(abs(toplot['y']-xlims[1]), toplot['z'], lw=0.1, ms=2, color=color)
    
    fig.savefig(fig_path + '/f_sup_pathlines/'+
                'CROSS_DECAY_'+str(i)+'_bis'+'.png',
                            bbox_inches='tight')

#%% PLOT BEAUTIFUL PATHLINES

model_name = 'modpath1_model6_40.0-1000-2.94e-06_80.0-1.0'

# x = gpd.read_file(BV.simulations_folder+'/'+model_name+'/_postprocess/_particles/ending.shp')
# z = gpd.read_file(BV.simulations_folder+'/'+model_name+'/_postprocess/_particles/starting.shp')

x = gpd.read_file(BV.simulations_folder+'/'+model_name+'/_postprocess/_particles/starting.shp')
z = gpd.read_file(BV.simulations_folder+'/'+model_name+'/_postprocess/_particles/ending.shp')

pa = gpd.read_file(BV.simulations_folder+'/'+model_name+'/_postprocess/_particles/pathlines.shp')
pt = gpd.read_file(BV.simulations_folder+'/'+model_name+'/_postprocess/_particles/particles.shp')

y = x.copy()
y = y[y['k']==1]
y = y[y['time']>0]
# y.plot()
y['time'] = y['time']/365
y = y[y['zone']!=0]

s = z.copy()
s = s[s['k']==1]
s = s[s['time']>0]
# y.plot()
s['time'] = s['time']/365
s = s[s['zone']!=0]

# print((y['time']).mean(), (y['time']).median(), (y['time']).quantile(0.95))

box = gpd.read_file(stable_folder+'/geographic/box_buff.shp')
shp = gpd.read_file(stable_folder+'/geographic/watershed.shp')
# test = plt.hist(y['time'], bins=1000)
# plt.yscale('log')

# laa = gpd.read_file('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_data/_sig/created/peatlasset_only.shp')
# laa = gpd.read_file('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_data/_sig/created/peatlasset_only.shp')
# laa = gpd.read_file('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_data/_sig/created/peatgrenou_only.shp')
# laa = gpd.read_file('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_data/_sig/created/peatbomb_only.shp')
# laa = gpd.read_file('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_data/_sig/created/peattruites_only.shp')

# final = y.clip(laa)
# final.plot()
# print((final['time']).mean(), (final['time']).median(), (final['time']).quantile(0.95), (final['time']).max())
# fig, ax = plt.subplots()
# ax.boxplot(final['time'])

# y = y[y['time']>1]

# plt.scatter(pa['time'], pa['k'])
# plt.yscale('log')
# plt.xscale('log')

pa_p = pa[pa['particleid'].isin(y['particleid'])]
pa_p['time'] = pa_p['time']/365
pa_p = pa_p[pa_p['time']>0.1]

pt_p = pt[pt['particleid'].isin(y['particleid'])]
pt_p['time'] = pt_p['time']/365
# pt_p = pt_p[pt_p['k']>15]
"""
list_id = []
for unique in pt_p['particleid'].unique():
    print(unique, len(pt_p['particleid'].unique()))
    t = pt_p[pt_p['particleid']==unique]
    t_k = t['k']
    if (t_k > 15).sum() > 0:
        list_id.append(unique)
pt_p = pt_p[pt_p['particleid'].isin(list_id)]
"""
fig, ax = plt.subplots(1,1, dpi=600)
pa_p.plot(ax=ax, column='time', cmap='jet', zorder=-1, lw=0.1, alpha=0.5,
                                    norm=mpl.colors.LogNorm(vmin=0.1, 
                                                            vmax=10))
im = y.plot(ax=ax, column='time', cmap='jet', zorder=+1,
                                    norm=mpl.colors.LogNorm(vmin=0.1, 
                                                            vmax=10),
                                    markersize=2, linewidth=0, legend=False)
# pt_p.plot(ax=ax, color='k', zorder=+2, lw=0.5)
pa_p.plot(ax=ax, column='time', cmap='jet', zorder=-1, lw=0.5, alpha=0.5,
                                    norm=mpl.colors.LogNorm(vmin=0.1, 
                                                            vmax=10))
# s[s['particleid'].isin(list_id)].plot(ax=ax, column='time', cmap='jet', zorder=+1,
#                                     norm=mpl.colors.LogNorm(vmin=0.1, 
#                                                             vmax=10),
#                                     markersize=2, linewidth=0)
box.plot(ax=ax, lw=1, ec='k', facecolor='None')
shp.plot(ax=ax, lw=1, ec='k', facecolor='None')
ax.get_xaxis().set_visible(False)
ax.get_yaxis().set_visible(False)
plt.axis('off')

dem = rasterio.open(stable_folder+'/geographic/watershed_box_buff_dem.tif')
hil = rasterio.open(data_path + '/_sig/hillshade_classic.tif')

# rasterio.plot.show(np.ma.masked_where(dem.read(1) < 0, dem.read(1)), 
#                           ax=ax, transform=dem.transform,
#                           cmap='Greys_r', alpha=1, zorder=-5)

rasterio.plot.show(np.ma.masked_where(hil.read(1) < 0, hil.read(1)), 
                          ax=ax, transform=dem.transform,
                          cmap='Greys_r', alpha=0.5, zorder=-5)

# cb = plt.colorbar(im, ax=ax,
#                   cax = fig.add_axes([0.95, 0.10, 0.03, 0.8]))
# cb.set_ticks([10, 15, 20, 25, 30, 35, 40, 45, 50, 75, 100, 150, 200, 300])
# cb.set_ticklabels([10, 15, 20, 25, 30, 35, 40, 45, 50, 75, 100, 150, 200, 300], fontsize=8)
# cb.ax.tick_params(direction='in', length=2, width=1, colors='k',
#                   grid_color='k', grid_alpha=0.5)
# for t in cb.ax.get_yticklabels():
#      t.set_fontsize(5.5)
# cb.minorticks_off()
# cb.clim()
# cb.ax.set_ylabel('τ [y]', rotation=270, labelpad=25)

# # add colorbar
# fig = ax.get_figure()
# cax = fig.add_axes([0.8, 0.1, 0.02, 0.5])
# sm = plt.cm.ScalarMappable(cmap='jet', norm=mpl.colors.LogNorm(vmin=0.1, 
#                         vmax=10),)
# # fake up the array of the scalar mappable. Urgh...
# sm._A = []
# cb = fig.colorbar(sm, cax=cax)
# cb.tick_params(direction='in', length=2, width=1, colors='k',
#                   grid_color='k', grid_alpha=0.5)
# cb.ax.minorticks_on()


# fig.savefig('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_figures_paper/_v0/03_fig_calibrated/'+
#             'pathlines_1'+'.png',
#                         bbox_inches='tight', dpi=600)


#%% ---- 4 - EXPLORATION FOR ALL

# 12 models
# 10 porosity per model : 0.1, 0.5, 1, 2, 4, 7, 10, 15, 20, 30

#%% UPDATE PARAMETERS

# vers = 'isba1' # dichotomy isba
# iD_explo = 'e_isba1' # with isba recharge ==> change ss with decay factor (details for bad models)

# vers = 'isba2' # dichotomy isba
# iD_explo = 'e_isba2' # with isba recharge ==> change ss with decay factor (details for bad models)

# # vers = 'isba2' # dichotomy isba
# # iD_explo = 't_isba2' # with isba recharge ==> change ss with decay factor (details for bad models)

# vers = 'isba2' # dichotomy isba
# iD_explo = 'e_isba4' # with isba recharge ==> change ss with decay factor (details for bad models)

# vers = 'isba2' # dichotomy isba
# iD_explo = 'e_isba5' # with isba recharge ==> change ss with decay factor (details for bad models)

# vers = 'isba2' # dichotomy isba
# iD_explo = 'e_isba6' # with isba recharge ==> change ss with decay factor (details for bad models)

# # vers = 'isba2' # dichotomy isba
# # iD_explo = 'e_isba7' # with isba recharge ==> change ss with decay factor (details for bad models)

# vers = 'isba2' # dichotomy isba
# iD_explo = 'e_isba8' # with isba recharge ==> change ss with decay factor (details for bad models)

vers = 'isba2' # dichotomy isba
iD_explo = 'z_isbaEXPLO' # with isba recharge ==> change ss with decay factor (details for bad models)

decay_factor = 2

box = True # or False
sink_fill = False # or True
sim_state = 'transient' # 'steady' or 'transient'
plot_cross = True
nlay = 25
lay_decay = 1.25 # 1 for no decay
verti_cond = None # or [ [1e-5, [0, 20]],
verti_poro = None # or [ [1e-5, [0, 20]],
cond_drain = None # or value of conductance
porosity = 5 / 100 # -
poro_decay = 0 # exponential decay : 1/20 (half decrease at 20m)
bc_left = None # or value
bc_right = None # or value
sea_level = 'None' # or value based on specific data : BV.oceanic.MSL
zone_partic = 'domain' # or watershed

split_temp = True

BV = watershed_root.Watershed(watershed_name=watershed_name, dem_path=dem_path, out_path=out_path, load=True)
area = BV.geographic.area

stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' # necessary for plots
BV.calibration_folder = out_path+'/'+watershed_name+'/'+'results_calibration/'

BV.add_settings()
BV.add_climatic()
BV.add_geometric() # soon
BV.add_hydraulic()

BV.settings.update_split_temporal(split_temp)

BV.settings.update_box_model(box)
BV.settings.update_sink_fill(sink_fill)
BV.settings.update_active_plot(plot_cross=plot_cross)
BV.hydraulic.update_nlay(nlay) # 1
BV.hydraulic.update_lay_decay(lay_decay) # 1
BV.hydraulic.update_cond_vertical(verti_cond)
BV.hydraulic.update_poro_vertical(verti_poro)
BV.hydraulic.update_cond_drain(cond_drain)
BV.settings.update_bc_sides(bc_left, bc_right)
BV.add_oceanic(sea_level)
BV.settings.update_input_particles(zone_partic=zone_partic)
BV.settings.update_simulation_state(sim_state)

thick = 30 # if bottom is None, aquifer thickness
BV.hydraulic.update_thick(thick) # 30 / intervient pas si bottom != None

# recharge = (sim2['DRAINC_Q'] * norm_factor) / 1000 # mm/d to m/d
# recharge = (isba['REC_REA_historic'] * rea_facnorm_isba) / 1000 # mm/d to m/d
recharge = select_period(rea_recharge_isba, 2020, 2023)
# plt.plot(all_proj['REC_REA_historic'], c='blue', lw=3)
# plt.plot(rea_recharge_isba, c='red', lw=2)
# plt.plot(isba['REC_REA_historic']/1000, c='green')
# plt.plot(recharge, c='gold')
# plt.yscale('log')
# plt.xlim(pd.to_datetime('2020'), pd.to_datetime('2024'))
# recharge = select_period(recharge, 2021, 2021)
recharge_w_res = recharge.resample('W', label='right').mean()
recharge_w_off = recharge.resample('W', label='right', closed='left', loffset=pd.DateOffset(days=3)).mean() # loffset='2T'
recharge_w_int = recharge.interpolate()[::7]
recharge_w_sli = recharge.groupby(np.arange(len(recharge))//7).mean()
recharge_w_sli.index = recharge_w_off.iloc[:-1].index
# recharge_w_sli.index = recharge_w_off.iloc[:].index
# recharge_w_sli = recharge_w_sli.iloc[:-1]

# runoff = (sim2['RUNC_Q'] * norm_factor) / 1000 # mm/d to m/d
# runoff = (isba['RUN_REA_historic'] * rea_facnorm_isba) / 1000 # mm/d to m/d
runoff = select_period(rea_runoff_isba, 2020, 2023)
# runoff = select_period(runoff, 2021, 2021)
runoff_w_res = runoff.resample('W', label='right').mean()
runoff_w_off = runoff.resample('W', label='right', closed='left', loffset=pd.DateOffset(days=3)).mean() # loffset='2T'
runoff_w_int = runoff.interpolate()[::7]
runoff_w_sli = runoff.groupby(np.arange(len(runoff))//7).mean()
runoff_w_sli.index = runoff_w_off.iloc[:-1].index
# runoff_w_sli.index = runoff_w_off.iloc[:].index
# runoff_w_sli = runoff_w_sli.iloc[:-1]

BV.climatic.update_recharge(recharge_w_sli, sim_state=sim_state)
BV.climatic.update_runoff(runoff_w_sli, sim_state=sim_state)

# BV.climatic.update_recharge(recharge, sim_state=sim_state)
# BV.climatic.update_runoff(runoff, sim_state=sim_state)

if iD_explo == 't_isba2':
    BV.climatic.update_recharge(recharge_w_sli[:2], sim_state=sim_state)
    BV.climatic.update_runoff(runoff_w_sli[:2], sim_state=sim_state)

# plt.plot(recharge_w_res, c='k')
# plt.plot(recharge_w_off, c='green')
# plt.plot(recharge_w_int, c='red')
# plt.plot(recharge_w_sli, c='darkorange')
# plt.plot(runoff_w_res, c='k')
# plt.plot(runoff_w_off, c='green')
# plt.plot(runoff_w_int, c='red')
# plt.plot(runoff_w_sli, c='darkorange')
# plt.yscale('log')
# plt.xlim(pd.to_datetime('2020'), pd.to_datetime('2021'))

# recharge_ete = sim2[sim2.index.month.isin([7,8,9])]
# recharge_ete = (recharge_ete['DRAINC_Q'] * norm_factor) / 1000 # mm/d to m/d
# print(BV.climatic.recharge.mean())
first_clim = recharge.mean() # or 'first or value
BV.climatic.update_first_clim(first_clim)
plt.plot(BV.climatic.recharge, marker='o')
plt.axhline(first_clim, c='k')

# Aquifer bottom
list_bottom = [None, 0] # aquifer flat or not
list_bottom.extend([0] * 14) ### ATTENTION ###

# Decay of K
# list_d_values = [0, 0]
# list_d_values.extend(np.geomspace(10, 300, 10).round(0).astype(int))
# print(list_d_values)
list_d_values = [0, 0, 10, 15, 20, 25, 30, 35, 40, 45, 50, 75, 100, 150, 200, 300]
list_cond_decay = list(1/np.array(list_d_values))
list_cond_decay[0] = 0
list_cond_decay[1] = 0
        
list_id_mod = [0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15]

df_optim = pd.read_csv(BV.calibration_folder+'/'+'_models'+'_optimum_'+vers+'.csv', sep=';')

# For transient
list_cond_decay = list_cond_decay
list_bottom = list_bottom
list_koptim = df_optim['K']
list_kroptim = df_optim['KR']

# Test compartimentalized porosity
# BV.hydraulic.update_poro_vertical([ [1/100, [0,15]] ])
# list_porosity = [0.1/100]
 
# list_koptim = [4.82e-6]
# BV.hydraulic.update_cond_vertical([ [list_koptim[0]*3600*24, [0,20]] ])

# list_porosity = np.arange(0.2, 10.2, 0.2)/100
list_porosity = np.geomspace(0.1, 5, 10)/100
# list_porosity = np.array([1])/100

#%% PRO PREPROCESSING

run_model = True
# run_model = False
 
# for cond_decay_val, bottom_val, koptim_val, id_mod_val, kroptim_val in zip(list_cond_decay[6:7],
#                                                                             list_bottom[6:7],
#                                                                             list_koptim[6:7],
#                                                                             list_id_mod[6:7],
#                                                                             list_kroptim[6:7]):    

for cond_decay_val, bottom_val, koptim_val, id_mod_val, kroptim_val in zip(list_cond_decay[-1:],
                                                                            list_bottom[-1:],
                                                                            list_koptim[-1:],
                                                                            list_id_mod[-1:],
                                                                            list_kroptim[-1:]):    
    
    # if id_mod_val in [0,2,3,4,5,6]:
    #     list_porosity = np.array([0.1,0.5,0.6,0.7,0.8,0.9,1.0,1.1,1.2,1.3,1.4,1.5,2,4,8,16])/100
    # else:
    #     list_porosity = np.array([0.1,0.5,1,2,4,8,16])/100
    
    ### e17
    # if id_mod_val in [0,2,3,4,5]:
    #     list_porosity = np.array([0.05,0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8,0.9,1.0,1.1,1.2,1.3,1.4,1.5,2.0,4.0,8.0,16.0])/100
    # else:
    #     list_porosity = np.array([0.1,0.5,1.0,2.0,4.0,8.0,16.0])/100
    
    ## isba1
    if id_mod_val in [0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15]:

        # print(id_mod_val)
        # print(kroptim_val)
        # koptim_from_kr = kroptim_val * (BV.climatic.recharge.mean())
        # print(koptim_from_kr, koptim_val)
        
        BV.hydraulic.update_cond_decay(cond_decay_val) # 0
        # BV.hydraulic.update_cond_decay(0) # 0
        BV.hydraulic.update_bottom(bottom_val) # None
        # BV.hydraulic.update_hyd_cond(koptim_val)
        # koptim_val = 0
        # koptim_val = 4e-6 * 24 * 3600
        BV.hydraulic.update_hyd_cond(koptim_val)
        # BV.hydraulic.update_hyd_cond(koptim_from_kr)
        BV.hydraulic.update_poro_decay(cond_decay_val/decay_factor)
        # BV.hydraulic.update_poro_decay(0)
        BV.hydraulic.update_ss_decay(cond_decay_val/decay_factor)
        
        dictio = {}
        
        list_model_name = []
        list_model_success = []
        list_model_modflow = []
            
        # for ip, poro_val in enumerate(list_porosity[-1:]):
        for ip, poro_val in enumerate(list_porosity[:]):
            
            BV.hydraulic.update_porosity(poro_val)
            
            Ss_formula = 1000*9.8*(1e-10+(poro_val*4.4e-10)) # rho*g*(alpha+nBeta)
            # print(Ss_formula)

            BV.hydraulic.update_ss(Ss_formula)
            
            if cond_decay_val == 0 :
                str_cond_decay = cond_decay_val
                str_poro_decay = cond_decay_val/decay_factor
            else:
                str_cond_decay = 1/cond_decay_val
                str_poro_decay = 1/(cond_decay_val/decay_factor)
            if bottom_val==None:
                str_bottom = thick
            else:
                str_bottom = bottom_val
                
            if poro_val == 0:
                str_poro_decay = 0
            
            model_name = iD_explo+'_'+str('model')+str(id_mod_val)+'_'+\
                         str(round(str_cond_decay,4))+'-'+str(round(str_bottom,4))+'-'+str("{:.2e}".format(koptim_val/24/3600))+'_'+\
                         str(ip)+'_'+\
                         str(round(str_poro_decay,4))+'-'+str(round(poro_val*100,2))+'-'+str("{:.2e}".format(Ss_formula))
            
            print(model_name)
            
            BV.settings.update_model_name(model_name)
            
            now = datetime.now()
            oclock = now.strftime("%Y%m%d-%Hh%Mm%Ss")
    
            model_modflow = BV.preprocessing_modflow(for_calib=True)
            
            model_success = BV.processing_modflow(model_modflow, write_model=True, run_model=run_model)
                
            list_model_name.append(model_name)
            list_model_success.append(model_success)
            list_model_modflow.append(model_modflow)
                    
        dictio['list_model_name'] = list_model_name
        dictio['list_model_success'] = list_model_success
        dictio['list_model_modflow'] = list_model_modflow
        h5file = BV.calibration_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)
        dd.io.save(h5file, dictio)
    
#%% LOAD POSTPROCESS

delete_files = False

# list_id_mod = [1,6,7,8,9,10,11]
# list_id_mod = [11]

for id_mod_val in list_id_mod[-1:]:

    h5file = BV.calibration_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)
    d = dd.io.load(h5file)
    list_model_name = d['list_model_name'][:]
    list_model_success = d['list_model_success'][:]
    list_model_modflow = d['list_model_modflow'][:]
    
    # for model_name, model_success, model_modflow in zip(list_model_name[8:],
    #                                                     list_model_success[8:],
    #                                                     list_model_modflow[8:]):

    for model_name, model_success, model_modflow in zip(list_model_name[:],
                                                        list_model_success[:],
                                                        list_model_modflow[:]):
                
        # if model_success == True:
        BV.postprocessing_modflow(model_modflow,
                                  watertable_elevation = True,
                                  watertable_depth = True, 
                                  seepage_areas = True,
                                  outflow_drain = True,
                                  groundwater_flux = True,
                                  groundwater_storage = True,
                                  accumulation_flux = True,
                                  persistency_index = True,
                                  intermittency_monthly = False,
                                  intermittency_weekly = True,
                                  intermittency_daily = False,
                                  export_all_tif = False)

        timeseries_results = BV.postprocessing_timeseries(model_modflow=model_modflow,
                                                          model_modpath=False,
                                                          actual_date=True, 
                                                          subbasin_results=True,
                                                          freq_time='W')

# DELETE MODFLOW FILES
        try:
            if delete_files == True:
        
                stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
                simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' # necessary for plots
                calibration_folder = out_path+'/'+watershed_name+'/'+'results_calibration/'
            
                dir_modflow = BV.calibration_folder + '/' + model_name
                dir_postprocess = dir_modflow + '/' + '_postprocess'
                dir_temporary = dir_modflow + '/' + '_postprocess' + '/' + '_temporary'
                dir_rasters = dir_modflow + '/' + '_postprocess' + '/' + '_rasters'
                dir_figures = dir_modflow + '/' + '_postprocess' + '/' + '_figures'
                
                files_rast_acc = glob.glob(dir_rasters+ '/' +'accumulation_flux'+'*')
                files_rast_out = glob.glob(dir_rasters+ '/' +'outflow_drain'+'*')
                files_rast_int = glob.glob(dir_rasters+ '/' +'intermittency'+'*')
            
                if os.path.exists(dir_rasters+ '/' +'accumulation_flux_t(0).tif'):
                    try:
                        for file in files_rast_acc[1:]:
                            os.remove(file)
                    except:
                        pass
                if os.path.exists(dir_rasters+ '/' +'outflow_drain_t(0).tif'):
                    try:
                        for file in files_rast_out[1:]:
                            os.remove(file)
                    except:
                        pass
                if os.path.exists(dir_rasters+ '/' +'intermittency_weekly_t(0).tif'):
                    try:
                        for file in files_rast_int[1:]:
                            os.remove(file)
                    except:
                        pass
                    
                if os.path.exists(dir_temporary):
                    shutil.rmtree(dir_temporary)
                
                if os.path.exists(dir_figures):
                    shutil.rmtree(dir_figures) 
                
                files_npy = glob.glob(dir_modflow + '/' + '_postprocess' + '/' + '*.npy')
                try:
                    for file in files_npy:
                        os.remove(file)
                except:
                    pass
                
                for file in glob.glob(dir_modflow+'/'+'*'):
                    if (file.split('\\')[-1] != '_postprocess') & (file.split('\\')[-1] != '_subbasins'):
                        # print(file)
                        f = file
                        if os.path.exists(f):
                            try:
                                os.rename(f, f)
                                print('Access on file "' + f +'" is available!')
                            except OSError as e:
                                print('Access-error on file "' + f + '"! \n' + str(e))
                        os.remove(file)
                        # shutil.rmtree(file)
        except:
            pass

#%% STREAMFLOW CHRONICS ALL - OUI

# iD_explo = 'e14'

iD_explos = ['e_isba1']
iD_explos = ['e_isba2']
iD_explos = ['z_isbaEXPLO']

CRIT = 'RMSE'

init_path = data_path + '_Q/'

Qobs_list =[
             'lasset_Q_Day.Cmd.txt',
             # 'truites_Q_Day.Cmd.txt'
            ]
Qobs_name = Qobs_list[0]

couleurs = ['navy','darkviolet']
areas = [3.7,
         # 1.2
         ]

df = pd.DataFrame()

dict_Q_wname = {}

for w, w_name in enumerate(['Lasset'][:]):
    
    # BV = watershed_root.Watershed(watershed_name=watershed_name, dem_path=dem_path, out_path=out_path, load=True)

    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' # necessary for plots
    BV.calibration_folder = out_path+'/'+watershed_name+'/'+'results_calibration/'
    
    dfQ = pd.read_csv(init_path+Qobs_name, sep=';', parse_dates=True, index_col='date_temp') # m3/d
    Qobs = dfQ.q / (areas[0]*1e6)
    Qobs_w_off = Qobs.resample('W', label='right', closed='left', loffset=pd.DateOffset(days=3)).mean() # loffset='2T'
    Qobs_w_sli = Qobs.groupby(np.arange(len(Qobs))//7).mean()
    Qobs_w_sli.index = Qobs_w_off.iloc[:-1].index
    Qobs_w_sli = Qobs_w_sli.iloc[:-1]
    Qobs = Qobs_w_sli.copy() * 1000 * 7
    # Qobs = Qobs.resample('M').mean()*4

    i = 0
    
    for iD_explo in iD_explos:
        
        if iD_explo == 'e_isba1':
            list_id_mod = [4]

        if iD_explo == 'e_isba2':
            list_id_mod = [6]

        for id_mod_val in list_id_mod[:]:
        
            h5file = BV.calibration_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)
            ######
            d = dd.io.load(h5file)
            ######
            list_model_name = d['list_model_name'][:]
            list_model_success = d['list_model_success'][:]
            list_model_modflow = d['list_model_modflow'][:]
            
            for model_name, model_success, model_modflow in zip(list_model_name[:],
                                                                list_model_success[:],
                                                                list_model_modflow[:]):
            # for model_name, model_success, model_modflow in zip(list_model_name[7:8],
            #                                                     list_model_success[7:8],
            #                                                     list_model_modflow[7:8]):
                    
                Smod = pd.read_csv(BV.calibration_folder+'/'+model_name+'/_postprocess/_timeseries/_simulated_timeseries.csv', sep=';',
                                   index_col='date', parse_dates=True)
                # Smod.index = recharge_w_sli.index()
                
                r = runoff_w_sli.copy()
                Qmod = Smod['outflow_drain'] + r*1 # m/day
                Qmod = Qmod * 1000 * 7
                # Qmod = Qmod.resample('M').mean()*4
                
                # Qobs_n = Qobs[Qobs<Qobs.median()]
                
                mix = Qobs.copy().to_frame()
                mix = mix[(mix.index.month >= 6) & (mix.index.month <= 10)]
                mix.columns = ['Qobs']
                mix['Qsim'] = Qmod
                mix = select_period(mix,2022,2022)
                mix = mix.dropna()
                
                Qobs_stat = mix.Qobs
                Qsim_stat = mix.Qsim
                
                import hydroeval as he
                NSE = he.evaluator(he.nse, Qsim_stat, Qobs_stat)[0]
                NSElog = he.evaluator(he.nse, Qsim_stat, Qobs_stat, transform='log')[0]
                RMSE = np.sqrt(np.nanmean((Qobs_stat.values-Qsim_stat.values)**2)) #/ (Qobs_stat.max()-Qobs_stat.min())
                RMSElog = np.sqrt(np.nanmean((np.log(Qobs_stat.values+1)-np.log(Qsim_stat.values+1))**2)) #/ (Qobs_stat.max()-Qobs_stat.min())
                KGE = he.evaluator(he.kge, Qsim_stat, Qobs_stat)[0][0]
                print(model_name.upper())
                print('NSE', round(NSE,2))
                print('NSElog', round(NSElog,2))
                print('RMSE', round(RMSE,2))
                print('KGE', round(KGE,2))
                
                # model_name = iD_explo+'_'+str('model')+str(id_mod_val)+'_'+\
                #              str(round(str_cond_decay,4))+'-'+str(round(str_bottom,4))+'-'+str("{:.2e}".format(koptim_val/24/3600))+'_'+\
                #              str(ip)+'_'+\
                #              str(round(str_poro_decay,4))+'-'+str(round(poro_val*100,2))
                
                df.loc[i,'model_name'] = model_name
                
                df.loc[i,'id_explo'] = iD_explo
                df.loc[i, 'id_mod'] = id_mod_val
                
                df.loc[i,'aK'] = float(model_name.split('_')[2+1].split('-')[0])
                df.loc[i,'bottom'] = float(model_name.split('_')[2+1].split('-')[1])
                
                try:
                    df.loc[i,'K'] = float(['-'.join(model_name.split('_')[2+1].split('-')[-2:])][0])
                except:
                    pass
                
                df.loc[i,'id_eO'] = float(model_name.split('_')[3+1][0])
                
                df.loc[i,'aO'] = float(model_name.split('_')[4+1].split('-')[0])
                df.loc[i,'O'] = float(model_name.split('_')[4+1].split('-')[1])
                
                df.loc[i,'NSE'] = float(NSE)
                df.loc[i,'NSElog'] = float(NSElog)
                df.loc[i,'RMSE'] = float(RMSE)
                df.loc[i,'KGE'] = float(KGE)
                df.loc[i,'RMSElog'] = float(RMSElog)
                
                Q10_obs = Qobs_stat.quantile(0.10)
                Q50_obs = Qobs_stat.quantile(0.50)
                Q90_obs = Qobs_stat.quantile(0.90)
                Q10_sim = Qsim_stat.quantile(0.10)
                Q50_sim = Qsim_stat.quantile(0.50)
                Q90_sim = Qsim_stat.quantile(0.90)
                
                df.loc[i,'OWN_Q10'] = float(((Q10_sim - Q10_obs)**2) / (Q10_obs**2))
                df.loc[i,'OWN_Q50'] = float(((Q50_sim - Q50_obs)**2) / (Q50_obs**2))
                df.loc[i,'OWN_Q90'] = float(((Q90_sim - Q90_obs)**2) / (Q90_obs**2))
                
                df.loc[i,'OWN'] = ( df.loc[i,'OWN_Q10'] + df.loc[i,'OWN_Q50'] + df.loc[i,'OWN_Q90'] ) / 3
                
                i += 1
                
                fig, (a0, a1) = plt.subplots(1, 2, gridspec_kw={'width_ratios': [3, 1]},
                                             figsize=(10,3))
                
                yearsmaj = mdates.YearLocator(1)   # every year
                yearsmin = mdates.YearLocator(1)
                # monthsmaj = mdates.MonthLocator(6)  # every month
                # monthsmin = mdates.MonthLocator(3)
                # months_fmt = mdates.DateFormatter('%m') #b = name of month ?
                years_fmt = mdates.DateFormatter('%Y')
            
                ax = a0
                ax.plot(Qobs, color='k', lw=1.5, ls='-', zorder=0, label='Observed')
                # ax.plot(Qobs_n, color='grey', lw=1.5, ls='-', zorder=0, label='Observed')
                ax.plot(Qmod, color='red', lw=1.5, label='Simulated')
                # ax.plot(Qmod-(r*1000), color='darkorange', lw=0.25, label='Simulated')
                ax.set_xlabel('Date')
                ax.set_ylabel('Q [mm/w]')
                ax.set_yscale('log')
                # ax.set_ylim(0,300)
                ax.set_ylim(1,1000)
                years_maj = mdates.YearLocator()   # every year
                months_maj = mdates.MonthLocator()  # every x month
                ax.xaxis.set_major_locator(years_maj)
                ax.xaxis.set_minor_locator(months_maj)
                ax.set_xlim(pd.to_datetime('2020'), pd.to_datetime('2024'))
                # ax.legend(loc='lower left')
                ax.set_title(model_name.upper(), fontsize=10)
                
                # axb = ax.twinx()
                # axb.bar(Smod.recharge.index, Smod.recharge*1000, color='dodgerblue',
                #         edgecolor='grey', width=2, lw=0)
                # # axb.bar(sim2.index, (sim2['PRELIQ_Q']+sim2['PRENEI_Q'])*1000, color='dodgerblue',
                # #         edgecolor='grey', width=2, lw=0)
                # axb.set_ylim(0,50)
                # axb.invert_yaxis()
                # axb.set_yticklabels([0,10])
                
                ax = a1
                ax.scatter(mix.Qobs, mix.Qsim,
                           s=10, edgecolor='none', alpha=0.75, facecolor='gray')
                ax.set_xscale('log')
                ax.set_yscale('log')
                ax.legend(loc='lower right', frameon=False)
                # ax.plot((0.1,1000),(0.1,1000), color='grey', zorder=-1)
                # ax.set_xlim(1,500)
                # ax.set_ylim(1,500)
                
                ax.plot((0.0001,1000),(0.0001,1000), c='k', ls='--')
                
                ax.set_xlim(1,1000)
                ax.set_ylim(1,1000)
    
                ax.set_xlabel('$Q_{obs}$ [mm/w]',
                              # fontsize=12
                              )
                ax.set_ylabel('$Q_{sim}$ [mm/w]',
                              # fontsize=12
                              )
                
                ax.patch.set_visible(True)
                # ax.set_title('$NSE_{log}$' + '  ' + str(round(NSElog,2)), fontsize=10, color='k')
    
                # move ax in front
                # ax.set_zorder(axb.get_zorder() + 1)
                
                ax.text(0.42,0.20, 'NSE'+' = '+str(round(NSE,2)), transform=ax.transAxes, c='k', fontsize=10)
                ax.text(0.42,0.10, '$NSE_{log}$'+' = '+str(round(NSElog,2)), transform=ax.transAxes, c='k', fontsize=10)
            
                
                fig.tight_layout()
                            
                # fig.savefig(os.path.join(simulations_folder, '_figures',
                #             'STREAMFLOW_'+model_name+'.png'),
                #             bbox_inches='tight')
                
                plt.close()
                
                # fig.savefig('C:/Users/ronan/Downloads/figs_'+iD_explos[0]+'/'+'Q_'+model_name+'.png',
                #             bbox_inches='tight')
                
                # fig.savefig('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_figures_paper/_v0/b_sup_calibs/_all4/'+
                #             'Q_'+model_name+'.png',
                #                         bbox_inches='tight')

    dfcrit_Q = df.copy()
    
    dfcrit_Q.to_csv(BV.simulations_folder+'_dfcrit_Q_'+iD_explo[0]+'.csv', sep=';')    

#%% STREAMFLOW CRITERIA ALL  - OUI

# dfcrit_Q = pd.read_csv(BV.simulations_folder+'_dfcrit_Q_'+'e'+'.csv', sep=';')
dfcrit_Q = pd.read_csv(BV.simulations_folder+'_dfcrit_Q_'+iD_explo[0]+'.csv', sep=';')

# iD_explos = ['e_isba2']
iD_explos = ['z_isbaEXPLO']

df = dfcrit_Q.copy()
       
# fig, axs = plt.subplots(1,5, figsize=(5*6,5))
# axs = axs.ravel()
# for i, j in enumerate(['NSE','NSElog','RMSE','KGE','OWN']):
#     ax = axs[i]
#     # ax.plot(df['O'], df[j], marker='o')
#     ax.set_title(j)
#     ax.set_xlabel('Porosity [%]')
# # fig.suptitle(df.model_name[0].upper(), y=1.05)
# # fig.savefig('C:/Users/ronan/Downloads/figs_'+iD_explo+'/'+'Q_'+'criteria'+'.png', bbox_inches='tight')

n = 15
# colors = pl.cm.jet(np.linspace(0,1,n))
colors = pl.cm.plasma_r(np.linspace(0,1,n))

# fig, axs = plt.subplots(1,5, figsize=(5*6,5),
#                         # sharey=True
#                         )
# axs = axs.ravel()
for icri, cri in enumerate([
                            # 'NSE','RMSE',
                            # 'KGE',
                            # 'OWN',
                            'NSElog',
                            # 'RMSElog'
                            ][:]):
    
    
    fig, ax = plt.subplots(1,1, figsize=(4.5,4),
                            # sharey=True
                            )
    
    # ax = axs[icri]
    # fig, ax = plt.subplots(1,1, figsize=(5,4))
    cp = 0
    for imod, mod in enumerate(df['id_mod'].unique()):
        if int(mod) >0:
        # for imod, mod in enumerate([4]):
            # imod=6
            # color= 'k'
            dfplot = df[df['id_mod']==mod]
            # ax.plot(dfplot['O'], dfplot[cri],
            #         marker='|', ms=10, mew=1,
            #         lw=2,
            #         color=color)
            # ax.plot(dfplot['O'], dfplot[cri],
            #         marker='o', ms=10, mew=1,
            #         lw=0,
            #         color=color)
            # if cri != 'NSElog':
            
            if int(mod) == 1 :
                color = 'gray'
            if int(mod) > 1:
                color = colors[cp]
            
            from scipy.interpolate import make_interp_spline
            x = dfplot.sort_values('O')['O']
            y = abs(1-dfplot.sort_values('O')[cri])
            X_Y_Spline = make_interp_spline(x, y)
            # Returns evenly spaced numbers
            # over a specified interval.
            X_ = np.linspace(x.min(), x.max(), 500)
            Y_ = X_Y_Spline(X_)
                        
            ax.plot(X_, Y_,
                    marker='o', ms=0, mew=0,
                    lw=2, 
                    color=color)
            ax.plot(x, y,
                    marker='|', ms=5, mew=2,
                    lw=0, 
                    color=color, zorder=1000, clip_on=False)
            # pc = ax.scatter(dfplot['O'], dfplot[cri])
            if cri == 'NSE':
                ax.set_ylabel('NSE [-]')
                ax.set_ylim(0,None)
            if cri == 'NSElog':
                ax.set_ylabel('|1-$NSE_{log}$| [-]')
                ax.set_ylim(-0.2,None)
                # ax.plot(dfplot.sort_values('O')['O'], np.abs(1-dfplot.sort_values('O')[cri]),
                #         marker='o', ms=1, mew=0,
                #         lw=1.5,
                #         color=color)
                # ax.set_yscale('log')
            if cri == 'RMSE':
                ax.set_ylabel('RMSE [mm/w]')
                # ax.set_ylim(28,32)
            if cri == 'KGE':
                ax.set_ylabel('KGE [-]')
                # ax.set_ylim(28,32)        
            if cri == 'OWN':
                ax.set_ylabel('OWN [-]')
                # ax.set_ylim(28,32)
                ax.set_yscale('log')
            if cri == 'RMSElog':
                ax.set_ylabel('$RMSE_{log}$ [mm/w]')
                # ax.set_ylim(0.75,1)
            # ax.set_xlabel('θ [%]')
            # ax.set_xlabel('Φ [%]')
            ax.set_xlabel('$Φ_{0}$ [%]')
            
            # ax.set_title(cri)
            ax.set_xscale('log')
            # ax.set_yscale('log')
            """
            if 0<=icri<=1:
                ax.set_ylim(0,0.4)
            if 4<=icri<=4:
                # ax.set_ylim(0,2.5)
                ax.set_yscale('log')
            """
            # position=fig.add_axes([1.05,0.33,0.03,0.5])  ##
            # cb = fig.colorbar(pc, cax=position, orientation='vertical')
            # cb.set_ticks(np.arange(0, 1.1, 0.25))
            # cb.set_ticklabels(np.arange(1, 2.1, 0.25))
            # cb.set_label('$A_{diff}$ [-]', rotation=270, labelpad=40)
            # cb.ax.tick_params(top=True,
            #             bottom=True,
            #             left=False,
            #             right=False,
            #             labelleft=False,
            #             labelbottom=True)
            ax.set_xlim(0.1,5)
            ax.set_ylim(0.2,8)
            ax.set_yscale('log')
            cp+=1

        plt.tight_layout()
    
        # fig.savefig('C:/Users/ronan/Downloads/figs_'+iD_explos[0]+'/'+'_Q_'+'criteria_'+cri+'.png', bbox_inches='tight')
            
            # fig.savefig('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_figures_paper/_v0/b_sup_calibs/'+
            #             'Q_'+cri+'.png',
            #                         bbox_inches='tight')
            
        fig.savefig('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_figures_paper/_v0/b_sup_calibs/'+
                    '_Q_'+'criteria_new_'+cri+'.png',
                                bbox_inches='tight')
        
# fig.savefig('C:/Users/ronan/Downloads/figs_'+iD_explos[0]+'/'+'Q_'+'criteria'+'.png', bbox_inches='tight')

#%% SATURATION CHRONICS ALL - OUI

iD_explos = ['e_isba2']
iD_explos = ['z_isbaEXPLO']

types_obs = ['hydrographic_mix_peren_upv1_pt']


areas = [
          3.7,
         ]

df = pd.DataFrame()

dict_S_wname = {}
    
BV = watershed_root.Watershed(watershed_name=watershed_name, dem_path=dem_path, out_path=out_path, load=True)

stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' # necessary for plots
BV.calibration_folder = out_path+'/'+watershed_name+'/'+'results_calibration/'

dem_data = imageio.imread(stable_folder + 'geographic/' + 'watershed_dem.tif')

# list_sat_obs = []
# for type_obs in types_obs:
#     path_hydro = stable_folder + 'hydrography/' + type_obs + '.tif'
#     path_hydro = 'D:/Users/abherve/ONEDRIVE_UNINECHYN/OneDrive - unine.ch/SIMULATIONS/Lasset/results_calibration/v6_model11_300.0-0_10-1.79e-07/_matchingstreams/obsflow.tif'
#     # path_hydro = 'D:/Users/abherve/ONEDRIVE_UNINECHYN/OneDrive - unine.ch/SIMULATIONS/Lasset/results_calibration/e1_model4_20.0-0-3.72e-06_0_40.0-0.1/_postprocess/_rasters/persistency_index_t(-).tif'
#     obs_hydro = imageio.imread(path_hydro)
#     # obs_hydro = np.ma.masked_where(dem_data==-99999, obs_hydro)
#     obs_hydro = np.ma.masked_where(obs_hydro==-0, obs_hydro)
#     obs_hydro_masked = np.ma.masked_where(obs_hydro<0, obs_hydro)
#     dd_hydro = round(obs_hydro_masked.count() / obs_hydro.count() * 100, 2)
#     # plt.imshow(obs_hydro_masked)
#     print(dd_hydro)
#     list_sat_obs.append(dd_hydro)

# list_sat_obs = [5,10] # 7
# list_sat_obs = [5.2,17.8] # 7
list_sat_obs = [6,8] # 7

i=0

sat_typ = 'total_areas'
sat_typ = 'seepage_areas'


for iD_explo in iD_explos:
    
    # list_id_mod = [6]

    for id_mod_val in list_id_mod[:]:
    
        h5file = BV.calibration_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)
        # if 'd' not in globals():
        d = dd.io.load(h5file)
        list_model_name = d['list_model_name'][:]
        list_model_success = d['list_model_success'][:]
        list_model_modflow = d['list_model_modflow'][:]
        
        # for model_name, model_success, model_modflow in zip(list_model_name[4:5],
        #                                                     list_model_success[4:5],
        #                                                     list_model_modflow[4:5]):
        for model_name, model_success, model_modflow in zip(list_model_name[:],
                                                            list_model_success[:],
                                                            list_model_modflow[:]):
            
            Smod = pd.read_csv(BV.calibration_folder+'/'+model_name+'/_postprocess/_timeseries/_simulated_timeseries.csv', sep=';',
                               index_col='date', parse_dates=True)
    
            Sat_mod = Smod[sat_typ] # m/day
                    
            Smin = Sat_mod.min()
            Smean = Sat_mod.mean()
            Smax = Sat_mod.max()
            S10 = Sat_mod.quantile(0.10)
            S25 = Sat_mod.quantile(0.25)
            S50 = Sat_mod.quantile(0.50)
            S75 = Sat_mod.quantile(0.75)
            S90 = Sat_mod.quantile(0.90)
            
            df.loc[i,'model_name'] = model_name
            
            df.loc[i,'id_explo'] = iD_explo
            df.loc[i, 'id_mod'] = id_mod_val
            
            df.loc[i,'aK'] = float(model_name.split('_')[2+1].split('-')[0])
            df.loc[i,'bottom'] = float(model_name.split('_')[2+1].split('-')[1])
            df.loc[i,'K'] = float(['-'.join(model_name.split('_')[2+1].split('-')[-2:])][0])
            
            df.loc[i,'id_eO'] = float(model_name.split('_')[3+1][0])
            
            df.loc[i,'aO'] = float(model_name.split('_')[4+1].split('-')[0])
            df.loc[i,'O'] = float(model_name.split('_')[4+1].split('-')[1])
                
            df.loc[i,'Smin'] = float(Smin)
            df.loc[i,'Smean'] = float(Smean)
            df.loc[i,'Smax'] = float(Smax)
            df.loc[i,'S10'] = float(S10)
            df.loc[i,'S25'] = float(S25)
            df.loc[i,'S50'] = float(S50)
            df.loc[i,'S75'] = float(S75)
            df.loc[i,'S90'] = float(S90)
            
            print(model_name, S10, S50, S90)
            
            df.loc[i,'Obs_per'] = list_sat_obs[0]
            df.loc[i,'Obs_med'] = (list_sat_obs[0]+list_sat_obs[-1])/2
            df.loc[i,'Obs_ful'] = list_sat_obs[-1]
            
            df.loc[i,'OWN_MIN'] = float(((S10 - df.loc[i,'Obs_per'])**2) / (df.loc[i,'Obs_per']**2))
            df.loc[i,'OWN_MED'] = float(((S50 - df.loc[i,'Obs_med'])**2) / (df.loc[i,'Obs_med']**2))
            df.loc[i,'OWN_MAX'] = float(((S90 - df.loc[i,'Obs_ful'])**2) / (df.loc[i,'Obs_ful']**2))
            
            # df.loc[i,'OWN_MIN'] = float(((S25 - df.loc[i,'Obs_per'])**2) / (df.loc[i,'Obs_per']**2))
            # df.loc[i,'OWN_MED'] = float(((S50 - df.loc[i,'Obs_med'])**2) / (df.loc[i,'Obs_med']**2))
            # df.loc[i,'OWN_MAX'] = float(((S75 - df.loc[i,'Obs_ful'])**2) / (df.loc[i,'Obs_ful']**2))
                        
            df.loc[i,'OWN'] = ( df.loc[i,'OWN_MIN'] + df.loc[i,'OWN_MED'] + df.loc[i,'OWN_MAX'] ) / 3
    
            i += 1
    
            fig, ax = plt.subplots(1, 1, figsize=(7,3))
            
            ax.fill_between(Smod.index, 0, Smod['total_areas'],
                            interpolate=False, color='dodgerblue', alpha=0.5,
                            step='pre', label='Intermittent')
            ax.fill_between(Smod.index, 0, Smod['perenn_areas'],
                            interpolate=False, color='navy', alpha=0.5,
                            step='pre', label='Perennial')
            # ax.legend(loc='upper left')
            ax.step(Smod.index, Smod['total_areas'], color='dodgerblue',
                    marker=None, markeredgecolor='none',
                    markersize=5, lw=1, label='upstream',
                    where='pre')
            ax.step(Smod.index, Smod['perenn_areas'], color='navy',
                    marker=None, markeredgecolor='none',
                    markersize=5, lw=1, label='upstream',
                    where='pre')
            # ax.step(Smod.index, Smod['seepage_areas'], color='grey',
            #         marker=None, markeredgecolor='none',
            #         markersize=5, lw=1, label='upstream',
            #         where='pre')
            
            ax.set_ylim(0,25)
            ax.set_yticks([0, 5, 10, 15, 20,25])
            ax.set_ylabel('$A_{sat}$ [%]')
            ax.set_xlim(pd.to_datetime('2020-01-08'), pd.to_datetime('2023'))
            plt.xticks(rotation=0, ha="center")
            # ax.set_xticklabels([])
        
            years_maj = mdates.YearLocator()   # every year
            months_maj = mdates.MonthLocator()  # every x month
            ax.xaxis.set_major_locator(years_maj)
            ax.xaxis.set_minor_locator(months_maj)
            
            ax.set_title(model_name.upper(), fontsize=10)
            
            ax.grid(which='major', axis='x')
            
            for j, hline in enumerate(list_sat_obs[:2]):
                if j == 0:
                    cl = 'navy'
                if j == 1:
                    cl = 'dodgerblue'
            
            # ax.axhline(list_sat_obs[0], c='navy', ls='--', zorder=-10)
            # ax.axhline(list_sat_obs[1], c='dodgerblue', ls='--', zorder=-10)
                
            fig.tight_layout()
            
            plt.close()
            
            # fig.savefig(os.path.join(simulations_folder, '_figures',
            #             'SATURATION_'+model_name+'.png'),
            #             bbox_inches='tight')
            
            # plt.close()
            
            # fig.savefig('C:/Users/ronan/Downloads/figs_'+iD_explos[0]+'/'+'S_'+model_name+'.png',
            #             bbox_inches='tight')
            
            # fig.savefig('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_figures_paper/_v0/03_fig_calibrated/_all_sat2/'+
            #             'S_'+model_name+'.png',
            #                         bbox_inches='tight')
        
            fig, ax = plt.subplots(1, 1, figsize=(5,5))

            x = Smod['recharge'] * 1000 * 30
            # x = Smod['outflow_drain'] * 1000 * 7
            # x = Smod['t']
            y = Smod['total_areas']
            y = y.fillna(0)
# y                    plt.plot(y)
            # y = Smod['prop_ratio']
            c = Smod.index.month
            wy = pd.Series(x.index.month).replace([10,11,12,1,2,3,4,5,6,7,8,9],
                                                    [1,2,3,4,5,6,7,8,9,10,11,12])
            xi = x.groupby([lambda x: x.month]).mean()
            yi = y.groupby([lambda y: y.month]).mean()
            
            xiq25 = x.groupby([lambda x: x.month]).quantile(0.25)
            yiq25 = y.groupby([lambda y: y.month]).quantile(0.25)
            
            xiq75 = x.groupby([lambda x: x.month]).quantile(0.75)
            yiq75 = y.groupby([lambda y: y.month]).quantile(0.75)
            
            # xi = x.groupby([lambda x: x.month]).median()
            # yi = y.groupby([lambda y: y.month]).median()
            # cmapping = mpl.colors.ListedColormap(dict_c[watershed_name])
            # cmapping = dict_cmap[watershed_name]
            
            # cmap = plt.cm.YlGnBu
            if sce == 'historic':
                cmap = 'Greys'
            if sce == 'RCP26':
                cmap = 'Blues'
            if sce == 'RCP45':
                cmap = 'Oranges'
            if sce == 'RCP85':
                cmap = 'Reds'
            # cmap = parula_map
            # cmaplist = [cmap(i) for i in range(cmap.N)]
            # if watershed_name == 'Canut':
            # cmaplist = ['limegreen','greenyellow']
            # if watershed_name == 'Nancon':
            #     cmaplist = ['tomato', 'lightsalmon']
            # cmaplist[0] = (.5, .5, .5, 1.0)
            # cmap = mpl.colors.LinearSegmentedColormap.from_list(
            #     'Custom cmap', cmaplist, cmap.N)
            
            # scat = ax.scatter(x, y, c=wy, cmap=cmap, marker="o", 
            #                   s=1, vmin=1, vmax=12, alpha=0.75, ec='none', zorder=-1)
            xiline = xi.append(xi.iloc[[0]])
            xiline.index = np.arange(1,14,1)
            yiline = yi.append(yi.iloc[[0]])
            yiline.index = np.arange(1,14,1)
            
            xilineq25 = xiq25.append(xiq25.iloc[[0]])
            xilineq25.index = np.arange(1,14,1)
            yilineq25 = yiq25.append(yiq25.iloc[[0]])
            yilineq25.index = np.arange(1,14,1)                    
            
            xilineq75 = xiq75.append(xiq75.iloc[[0]])
            xilineq75.index = np.arange(1,14,1)
            yilineq75 = yiq75.append(yiq75.iloc[[0]])
            yilineq75.index = np.arange(1,14,1)                  
            
            # ax.fill_between(xiline, yilineq25, yilineq75, lw=0,
            #                  interpolate=False,
            #                 color=dict_scecol[sce], alpha=0.25)
            
            # ax.plot(xi, yiq25, linestyle = '-', lw=0.5, 
            #         color=dict_scecol[sce], zorder=0)
            # ax.plot(xi, yiq75, linestyle = '-', lw=0.5, 
            #         color=dict_scecol[sce], zorder=0)
            compt=0

            ax.plot(xiline, yiline, linestyle = '-', lw=2, 
                    color='k', zorder=compt)
            wyi = np.arange(1,12+1,1)
            # compt = 1
            for k in wyi:
                ax.plot(xi[k], yi[k], marker="o", lw=1, markersize=10.5, 
                           markeredgecolor='k', 
                           markerfacecolor='white', markeredgewidth=1.2,
                           linestyle = 'None', zorder=compt)
                ax.annotate(k,(xi[k],yi[k]), family='sans-serif', fontsize=7, 
                        color='k', weight="bold", ha='center', va='center',
                        zorder=compt)
                compt+=1
            xe = pd.DataFrame()
            xe['q25'] = (x.groupby(x.index.month).quantile(0.25))
            xe['q75'] = (x.groupby(x.index.month).quantile(0.75))        
            ye = pd.DataFrame()
            ye['q25'] = (y.groupby(y.index.month).quantile(0.25))
            ye['q75'] = (y.groupby(y.index.month).quantile(0.75))                
            ax.errorbar(xi, yi,
                          yerr=np.abs(np.vstack([yi-ye.q25, ye.q75-yi])),
                          # xerr=np.abs(np.vstack([xi-xe.q25, xe.q75-xi])),
                          ecolor = 'k', fmt = 'none', capsize = 1,
                          elinewidth=0.5, 
                          capthick=0, zorder=-1000)               
            # ax.errorbar(xi, yi,
            #               yerr=np.abs(np.vstack([yi-ye.q25, yi+ye.q25])),
            #               xerr=np.abs(np.vstack([xi-xe.q25, xi+xe.q25])),
            #               ecolor = dict_scecol[sce], fmt = 'none', capsize = 1, elinewidth=0.5, 
            #               capthick=0.5, zorder=-1000)  
            
            ax.grid(alpha=0.5)
            
            # ax.axvline(x.median(), c=dict_c[watershed_name], ls='--')
            # ax.axhline(y.median(), c=dict_c[watershed_name], ls='--')
            
            ax.set_xscale('log')
            # ax.set_yscale('log')
            plt.close()
            
            # if pidx==3:
            #     ax.set_xlabel('R [mm/week]')
            # if ivar ==0:
            #     ax.set_ylabel('$A_{sat}$ [%]')
            # else:
            #     ax.set_ylabel('$A_{int}$ / $A_{sat}$ [-]')
                    
        
dfcrit_S = df.copy()

dfcrit_S.to_csv(BV.simulations_folder+'dfcrit_S_'+iD_explo[0]+'_'+sat_typ+'.csv', sep=';')

#%% SATURATION CRITERIA ALL - OUI

dfcrit_S = pd.read_csv(BV.simulations_folder+'dfcrit_S_'+iD_explo[0]+'.csv', sep=';')
# dfcrit_S = pd.read_csv(BV.simulations_folder+'dfcrit_S_'+iD_explo[0]+'_'+sat_typ+'.csv', sep=';')

df = dfcrit_S.copy()

# fig, ax = plt.subplots(1,1, figsize=(6,5))
# # axs = axs.ravel()
# for i, j in enumerate(['OWN']):
#     ax = ax
#     ax.plot(df['O'], df[j], marker='o')
#     ax.set_title(j)
#     ax.set_xlabel('Porosity [%]')
# fig.suptitle(df.model_name[0].upper(), y=1.0, fontsize=8)
# # fig.savefig('C:/Users/ronan/Downloads/figs_'+iD_explo+'/'+'S_'+'criteria'+'.png',
# #             bbox_inches='tight')

n = 15
colors = pl.cm.plasma_r(np.linspace(0,1,n))
colors2 = pl.cm.plasma_r(np.linspace(0,1,n))

# fig, axs = plt.subplots(1,2, figsize=(5*1,5),
#                         # sharey=True
#                         )
# axs = axs.ravel()

fig, ax = plt.subplots(1,1, figsize=(4.5,4),
                        # sharey=True
                        )
# axs = axs.ravel()
for icri, cri in enumerate(['Smin','Smax'][:]):
    ax = ax
    # fig, ax = plt.subplots(1,1, figsize=(5,4))
    # fig, ax = plt.subplots(1,1, figsize=(4.5,4),
    #                         # sharey=True
    #                         )
    cp = 0
    for imod, mod in enumerate(df['id_mod'].unique()):
        if int(mod) >0:
            # color='k'
            # imod = 6

            dfplot = df[df['id_mod']==mod]
            # ax.plot(dfplot['O'], dfplot[cri],
            #         marker='|', ms=10, mew=1,
            #         lw=2,
            #         color=color)
            # ax.plot(dfplot['O'], dfplot[cri],
            #         marker='o', ms=10, mew=1,
            #         lw=0,
            #         color=color)
            # if cri != 'NSElog':
            
            if int(mod) == 1 :
                color = 'gray'
            if int(mod) > 1:
                color = colors[cp]
            
            x = dfplot.sort_values('O')['O']
            y = dfplot.sort_values('O')[cri]
            X_Y_Spline = make_interp_spline(x, y)
            # Returns evenly spaced numbers
            # over a specified interval.
            X_ = np.linspace(x.min(), x.max(), 500)
            Y_ = X_Y_Spline(X_)
            
            if icri==0:
                ls='-'
                lw=3
            # if icri==1:
            #     ls='--'
            #     lw=0.5
            #     y = y
            if icri==1:
                ls='-'
                lw=1
                y = y
        
            # ax.plot(X_, Y_,
            #         marker='o', ms=0, mew=0,
            #         lw=lw, ls=ls,
            #         color=color)
            ax.plot(x, y,
                    marker='o', ms=0, mew=0,
                    lw=lw, ls=ls,
                    color=color)
            # ax.plot(x, y,
            #         marker='|', ms=5, mew=2,
            #         lw=0, ls=ls,
            #         color=color, zorder=1000, clip_on=False)
            
            # pc = ax.scatter(dfplot['O'], dfplot[cri])
            # ax.set_ylabel('Ω [-]')
            # ax.set_xlabel('$θ_{0}$ [%]')
            ax.set_xlabel('$Φ_{0}$ [%]')
            ax.set_ylabel('$D_{d sim}$ [%]')
            # ax.set_title(cri)
            ax.set_xscale('log')
            # ax.set_ylim(1e-3,1.5e-1)
            # ax.set_yscale('log')
            # if 0<=icri<=1:
                # ax.set_ylim(0,0.4)
            # ax.set_yscale('log')
            ax.set_ylim(0,50)
            ax.set_xlim(0.1,5)
            # position=fig.add_axes([1.05,0.33,0.03,0.5])  ##
            # cb = fig.colorbar(pc, cax=position, orientation='vertical')
            # cb.set_ticks(np.arange(0, 1.1, 0.25))
            # cb.set_ticklabels(np.arange(1, 2.1, 0.25))
            # cb.set_label('$A_{diff}$ [-]', rotation=270, labelpad=40)
            # cb.ax.tick_params(top=True,
            #             bottom=True,
            #             left=False,
            #             right=False,
            #             labelleft=False,
            #             labelbottom=True)
            cp += 1
plt.tight_layout()

# fig.savefig('C:/Users/ronan/Downloads/figs_'+iD_explos[0]+'/'+'_S_'+'criteria'+'.png', bbox_inches='tight')

fig.savefig('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_figures_paper/_v0/b_sup_calibs/'+
            'S_new_'+'minmax'+'.png',
                        bbox_inches='tight', dpi=600)

#%% ---- 5 - PROJECT FOR BEST

#%% UPDATE PARAMETERS

# iD_explo = 't1' # montly projection test
iD_explo = 'pisba1' # montly projection all
iD_explo = 'pisba2' # montly projection all
# iD_explo = 'p2' # montly projection 6 models for 3 scenarios
# iD_explo = 'r1' # reanalysis daily for recession

iD_explo = 'pisbatest1' # montly projection all
iD_explo = 'pisbatest2' # montly projection all
iD_explo = 'pisbatest3' # with isba recharge ==> change ss with decay factor (details for bad models)

# iD_explo = 'Daily1' # test reanalysis daily
# temporal = 'D'

# iD_explo = 'Weekly1' # test reanalysis weekly
# temporal = 'W'

temporal = 'M'

decay_factor = 2

vers = 'isba2' # dichotomy isba
# vers = 'v8' # dicotohomy sim2

box = True # or False
sink_fill = False # or True
sim_state = 'transient' # 'steady' or 'transient'
plot_cross = True
nlay = 25
lay_decay = 1.25 # 1 for no decay
verti_cond = None # or [ [1e-5, [0, 20]],
verti_poro = None # or [ [1e-5, [0, 20]],
cond_drain = None # or value of conductance
porosity = 5 / 100 # -
poro_decay = 0 # exponential decay : 1/20 (half decrease at 20m)
bc_left = None # or value
bc_right = None # or value
sea_level = 'None' # or value based on specific data : BV.oceanic.MSL
zone_partic = 'domain' # or watershed
        
BV = watershed_root.Watershed(watershed_name=watershed_name, dem_path=dem_path, out_path=out_path, load=True)
area = BV.geographic.area

stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' # necessary for plots
BV.calibration_folder = out_path+'/'+watershed_name+'/'+'results_calibration/'

BV.add_settings()
BV.add_climatic()
BV.add_geometric() # soon
BV.add_hydraulic()

BV.settings.update_box_model(box)
BV.settings.update_sink_fill(sink_fill)
BV.settings.update_active_plot(plot_cross=plot_cross)
BV.hydraulic.update_nlay(nlay) # 1
BV.hydraulic.update_lay_decay(lay_decay) # 1
BV.hydraulic.update_cond_vertical(verti_cond)
BV.hydraulic.update_poro_vertical(verti_poro)
BV.hydraulic.update_cond_drain(cond_drain)
BV.settings.update_bc_sides(bc_left, bc_right)
BV.add_oceanic(sea_level)
BV.settings.update_input_particules(zone_partic=zone_partic)
BV.settings.update_simulation_state(sim_state)

thick = 30 # if bottom is None, aquifer thickness
BV.hydraulic.update_thick(thick) # 30 / intervient pas si bottom != None

# Aquifer bottom
list_bottom = [0] # aquifer flat or not

# Decay of K
# list_d_values = [0, 0]
# list_d_values.extend(np.geomspace(10, 300, 10).round(0).astype(int))
# list_d_values = [30]
list_d_values = [30]
list_cond_decay = list(1/np.array(list_d_values))

# Models
list_id_mod = [6]

df_optim = pd.read_csv(BV.calibration_folder+'/'+'_models'+'_optimum_'+vers+'.csv', sep=';')

# For transient
list_cond_decay = list_cond_decay
list_bottom = list_bottom
list_koptim = df_optim['K'][6:7] * 30
list_kroptim = df_optim['KR'][6:7]
# list_koptim = [3.38e-6 * 3600 * 24]
# list_kroptim = [None]

list_porosity = [1.0/100]

BV.settings.update_split_temporal(False)

all_proj = pd.read_csv(BV.stable_folder + '/driaseau/' + 'all_proj_driaseau.csv', sep=';', index_col=0, parse_dates=True)

#%% PRO PREPROCESSING

# All models
# mod_keep = 'MPI-CCL|ECE-RCA|ECE-RAC|IPS-RCA|CNR-RAC|NOR-R15|CNR-ALA|NOR-HIR|HAD-CCL|IPS-WRF|HAD-REG|MPI-R09'

# RCP2.6
# mod_keep = 'MPI-CCL|ECE-RCA|ECE-RAC|CNR-RAC|NOR-R15|CNR-ALA|HAD-REG|MPI-R09'

# RCP4.5
# mod_keep = 'MPI-CCL|ECE-RCA|ECE-RAC|IPS-RCA|CNR-RAC|CNR-ALA|NOR-HIR|HAD-CCL|IPS-WRF|MPI-R09'

# For 3 scenarios
num_list = ['Model_01',
            'Model_02',
            'Model_03',
            # 'Model_04',
            'Model_05',
            # 'Model_06',
            'Model_07',
            # 'Model_08',
            # 'Model_09',
            # 'Model_10',
            # 'Model_11',
            'Model_12']
mod_keep = 'MPI-CCL|ECE-RCA|ECE-RAC|CNR-RAC|CNR-ALA|MPI-R09'
mod_list = ['MPI-CCL',
            'ECE-RCA',
            'ECE-RAC',
            # 'IPS-RCA',
            'CNR-RAC',
            # 'NOR-R15',
            'CNR-ALA',
            # 'NOR-HIR',
            # 'HAD-CCL',
            # 'IPS-WRF',
            # 'HAD-REG',
            'MPI-R09']

# For reanalysis
# mod_keep = 'REA'
# mod_list = ['REA']

run_model = True
# run_model = False

fig, ax = plt.subplots(1,1, figsize=(7,4))

# for sce in ['RCP26','RCP45','RCP85']:
# for sce in ['historic']:
for sce in ['RCP85']:
    
    rec_keep = all_proj.filter(regex='REC').filter(regex=sce).filter(regex=mod_keep)
    # plt.plot(select_period(rec_keep,2020,2024))
    # plt.plot(select_period((isba['REC_REA_historic'] * rea_facnorm_isba) / 1000, 2020, 2024))
    rec_keep = rec_keep.mean(skipna=True, axis=1)
    # rec_keep = select_period(rec_keep,1975,1976)
    run_keep = all_proj.filter(regex='RUN').filter(regex=sce).filter(regex=mod_keep)
    run_keep = run_keep.mean(skipna=True, axis=1)
    # rec_keep = select_period(rec_keep,1975,1976)
    
    if temporal == 'M':
        recharge_w_sli = rec_keep.resample('M').mean()
        runoff_w_sli = run_keep.resample('M').mean()
    
    if temporal == 'D':
        recharge_w_sli = rec_keep.resample('D').mean()
        runoff_w_sli = run_keep.resample('D').mean()
        
        recharge_w_sli = select_period(recharge_w_sli, 2020, 2023)
        runoff_w_sli = select_period(runoff_w_sli, 2020, 2023)
        
        recharge_w_sli = recharge_w_sli.dropna()
        runoff_w_sli = runoff_w_sli.dropna()
        
    # plt.plot(recharge_w_sli)
    
    # print(select_period(rea_recharge_isba+rea_runoff_isba, 1975, 2004).mean()*1000*365)
    # print(select_period(rec_keep+run_keep, 1975, 2004).mean()*1000*365)
    
    ### IF WEEKLY ###
    if temporal == 'W':
        recharge = (rec_keep) # / 1000 # mm/d to m/d
        # recharge = (isba['REC_REA_historic'] * norm_factor) / 1000 # mm/d to m/d
        # recharge = select_period(recharge, 2021, 2021)
        recharge_w_res = recharge.resample('W', label='right').mean()
        recharge_w_off = recharge.resample('W', label='right', closed='left', loffset=pd.DateOffset(days=3)).mean() # loffset='2T'
        recharge_w_int = recharge.interpolate()[::7]
        recharge_w_sli = recharge.groupby(np.arange(len(recharge))//7).mean()
        # recharge_w_sli.index = recharge_w_off.iloc[:-1].index
        recharge_w_sli.index = recharge_w_off.iloc[:].index
        # recharge_w_sli = recharge_w_sli.iloc[:-1]
        
        runoff = (run_keep) #/ 1000 # mm/d to m/d
        # runoff = (isba['RUN_REA_historic'] * norm_factor) / 1000 # mm/d to m/d
        # runoff = select_period(runoff, 2021, 2021)
        runoff_w_res = runoff.resample('W', label='right').mean()
        runoff_w_off = runoff.resample('W', label='right', closed='left', loffset=pd.DateOffset(days=3)).mean() # loffset='2T'
        runoff_w_int = runoff.interpolate()[::7]
        runoff_w_sli = runoff.groupby(np.arange(len(runoff))//7).mean()
        # runoff_w_sli.index = runoff_w_off.iloc[:-1].index
        runoff_w_sli.index = runoff_w_off.iloc[:].index
        # runoff_w_sli = runoff_w_sli.iloc[:-1]
    
    
    # BV.climatic.update_recharge(select_period(recharge_w_sli, 2022, 2023), sim_state=sim_state)
    # BV.climatic.update_runoff(select_period(runoff_w_sli, 2022, 2023), sim_state=sim_state)
    
    ###♥ FOR REANALYSIS
    # BV.climatic.update_recharge(select_period(recharge_w_sli, 2020, 2023), sim_state=sim_state)
    # BV.climatic.update_runoff(select_period(runoff_w_sli, 2020, 2023), sim_state=sim_state)

    # recharge_w_sli = recharge_w_sli.dropna()
    # runoff_w_sli = runoff_w_sli.dropna()
    
    ### FOR 3 SCENARIOS
    # BV.climatic.update_recharge(select_period(recharge_w_sli, 1975, 2099), sim_state=sim_state)
    # BV.climatic.update_runoff(select_period(runoff_w_sli, 1975, 2099), sim_state=sim_state)
    BV.climatic.update_recharge(select_period(recharge_w_sli*30, 1975, 2100), sim_state=sim_state)
    BV.climatic.update_runoff(select_period(runoff_w_sli*30, 1975, 2100), sim_state=sim_state)
    
    # print(select_period(BV.climatic.recharge, 1975, 2100).mean()*365*1000)
    
    # recharge_ete = sim2[sim2.index.month.isin([7,8,9])]
    # recharge_ete = (recharge_ete['DRAINC_Q'] * norm_factor) / 1000 # mm/d to m/d
    # print(BV.climatic.recharge.mean())
    
    # first_clim = select_period(recharge_w_sli,1980,2004).mean() # or 'first or value
    # first_clim = recharge_w_sli.mean() # or 'first or value
    ### REANALYSIS
    # first_clim = ((sim2['DRAINC_Q'] * norm_factor) / 1000).mean()
    first_clim = select_period(rea_recharge_isba, 2020, 2023).mean()
    print(first_clim)
    BV.climatic.update_first_clim(first_clim*30)
    
    test_r = BV.climatic.recharge
    test_r = test_r.to_frame()
    test_r['1'] = np.arange(0,len(test_r),1)
    ax.plot(BV.climatic.recharge)
    # ax.plot(select_period(recharge_w_sli, 2020, 2023))    
    ax.axhline(first_clim, c='k')
    ax.set_yscale('log')
    # ax.set_xlim(pd.to_datetime('2022'), pd.to_datetime('2023'))

    for cond_decay_val, bottom_val, koptim_val, id_mod_val, kroptim_val, poro_val in zip(list_cond_decay[:],
                                                                                         list_bottom[:],
                                                                                         list_koptim[:],
                                                                                         list_id_mod[:],
                                                                                         list_kroptim[:],
                                                                                         list_porosity[:]):    
        
        BV.hydraulic.update_cond_decay(cond_decay_val) # 0
        BV.hydraulic.update_bottom(bottom_val) # None
        BV.hydraulic.update_hyd_cond(koptim_val)
        BV.hydraulic.update_poro_decay(cond_decay_val/decay_factor)
        BV.hydraulic.update_ss_decay(cond_decay_val/decay_factor)
        
        dictio = {}
        
        list_model_name = []
        list_model_success = []
        list_model_modflow = []
            
        BV.hydraulic.update_porosity(poro_val)
        
        Ss_formula = 1000*9.8*(1e-10+(poro_val*4.4e-10)) # rho*g*(alpha+nBeta)
        # print(Ss_formula)
    
        BV.hydraulic.update_ss(Ss_formula)
        
        if cond_decay_val == 0 :
            str_cond_decay = cond_decay_val
            str_poro_decay = cond_decay_val/decay_factor
        else:
            str_cond_decay = 1/cond_decay_val
            str_poro_decay = 1/(cond_decay_val/decay_factor)
        if bottom_val==None:
            str_bottom = thick
        else:
            str_bottom = bottom_val
            
        if poro_val == 0:
            str_poro_decay = 0
        
        model_name = iD_explo+'_'+str('model')+str(id_mod_val)+'_'+\
                     str(round(str_cond_decay,4))+'-'+str(round(str_bottom,4))+'-'+str("{:.2e}".format(koptim_val/24/3600))+'_'+\
                     str(round(str_poro_decay,4))+'-'+str(round(poro_val*100,2))+'-'+str("{:.2e}".format(Ss_formula))+'_'+\
                     'ALL'+'-'+sce.upper()+'-'+str(recharge_w_sli.first_valid_index().year)+'-'+str(recharge_w_sli.last_valid_index().year)
        
        print(model_name)
        
        BV.settings.update_model_name(model_name)
        
        now = datetime.now()
        oclock = now.strftime("%Y%m%d-%Hh%Mm%Ss")
    
        model_modflow = BV.preprocessing_modflow(for_calib=False)
        
        model_success = BV.processing_modflow(model_modflow, write_model=True, run_model=run_model)
            
        list_model_name.append(model_name)
        list_model_success.append(model_success)
        list_model_modflow.append(model_modflow)
                    
        dictio['list_model_name'] = list_model_name
        dictio['list_model_success'] = list_model_success
        dictio['list_model_modflow'] = list_model_modflow
        h5file = BV.simulations_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)+'_ALL_'+sce
        dd.io.save(h5file, dictio)
    
#%% LOAD POSTPROCESS

delete_files = False

# for sce in ['RCP26','RCP85'][:]:
# for sce in ['RCP26','RCP45','RCP85']:
for sce in ['RCP85']:
# for sce in ['historic']:
    
    for id_mod_val in list_id_mod[:]:
    
        h5file = BV.simulations_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)+'_ALL_'+sce.upper()
        d = dd.io.load(h5file)
        list_model_name = d['list_model_name'][:]
        list_model_success = d['list_model_success'][:]
        list_model_modflow = d['list_model_modflow'][:]
        
        # for model_name, model_success, model_modflow in zip(list_model_name[8:],
        #                                                     list_model_success[8:],
        #                                                     list_model_modflow[8:]):
    
        for model_name, model_success, model_modflow in zip(list_model_name[:],
                                                            list_model_success[:],
                                                            list_model_modflow[:]):
            
            intermittency_monthly = False
            intermittency_weekly = False # True
            intermittency_daily = False
            if temporal == 'M':
                intermittency_monthly = True
            if temporal == 'W':
                intermittency_weekly = True # True
            if temporal == 'D':
                intermittency_daily = True

            # if model_success == True:
            BV.postprocessing_modflow(model_modflow,
                                      watertable_elevation = True,
                                      watertable_depth = True, 
                                      seepage_areas = True,
                                      outflow_drain = True,
                                      groundwater_flux = True,
                                      groundwater_storage = True,
                                      accumulation_flux = True,
                                      persistency_index = True,
                                      intermittency_monthly = intermittency_monthly,
                                      intermittency_weekly = intermittency_weekly, # True
                                      intermittency_daily = intermittency_daily,
                                      # export_netcdf = False,
                                      export_all_tif = True)
            
            # BV.postprocessing_modflow(model_modflow,
            #                           watertable_elevation = True,
            #                           watertable_depth = False, 
            #                           seepage_areas = False,
            #                           outflow_drain = False,
            #                           groundwater_flux = False,
            #                           groundwater_storage = True,
            #                           accumulation_flux = False,
            #                           persistency_index = False,
            #                           intermittency_monthly = False,
            #                           intermittency_weekly = False, # True
            #                           intermittency_daily = False,
            #                           export_all_tif = False)
    
            timeseries_results = BV.postprocessing_timeseries(model_modflow=model_modflow,
                                                              model_modpath=False,
                                                              actual_date=True, 
                                                              subbasin_results=True,
                                                              freq_time=temporal) # 'W' or 'M'
    
    # DELETE MODFLOW FILES
            try:
                if delete_files == True:
            
                    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
                    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' # necessary for plots
                    calibration_folder = out_path+'/'+watershed_name+'/'+'results_calibration/'
                
                    dir_modflow = BV.calibration_folder + '/' + model_name
                    dir_postprocess = dir_modflow + '/' + '_postprocess'
                    dir_temporary = dir_modflow + '/' + '_postprocess' + '/' + '_temporary'
                    dir_rasters = dir_modflow + '/' + '_postprocess' + '/' + '_rasters'
                    dir_figures = dir_modflow + '/' + '_postprocess' + '/' + '_figures'
                    
                    files_rast_acc = glob.glob(dir_rasters+ '/' +'accumulation_flux'+'*')
                    files_rast_out = glob.glob(dir_rasters+ '/' +'outflow_drain'+'*')
                    files_rast_int = glob.glob(dir_rasters+ '/' +'intermittency'+'*')
                
                    if os.path.exists(dir_rasters+ '/' +'accumulation_flux_t(0).tif'):
                        try:
                            for file in files_rast_acc[1:]:
                                os.remove(file)
                        except:
                            pass
                    if os.path.exists(dir_rasters+ '/' +'outflow_drain_t(0).tif'):
                        try:
                            for file in files_rast_out[1:]:
                                os.remove(file)
                        except:
                            pass
                    if os.path.exists(dir_rasters+ '/' +'intermittency_weekly_t(0).tif'):
                        try:
                            for file in files_rast_int[1:]:
                                os.remove(file)
                        except:
                            pass
                        
                    if os.path.exists(dir_temporary):
                        shutil.rmtree(dir_temporary)
                    
                    if os.path.exists(dir_figures):
                        shutil.rmtree(dir_figures) 
                    
                    files_npy = glob.glob(dir_modflow + '/' + '_postprocess' + '/' + '*.npy')
                    try:
                        for file in files_npy:
                            os.remove(file)
                    except:
                        pass
                    
                    for file in glob.glob(dir_modflow+'/'+'*'):
                        if (file.split('\\')[-1] != '_postprocess') & (file.split('\\')[-1] != '_subbasins'):
                            # print(file)
                            f = file
                            if os.path.exists(f):
                                try:
                                    os.rename(f, f)
                                    print('Access on file "' + f +'" is available!')
                                except OSError as e:
                                    print('Access-error on file "' + f + '"! \n' + str(e))
                            os.remove(file)
                            # shutil.rmtree(file)
            except:
                pass

#%% FAST STREAMFLOW CHRONICS

iD_explo = 'p2'
iD_explo = 'r1'
iD_explo = 'Daily1'
iD_explo = 'Weekly1'
iD_explo = 'pisba1' # montly projection all


CRIT = 'RMSE'

init_path = data_path + '_Q/'

Qobs_list =[
             'lasset_Q_Day.Cmd.txt',
             # 'truites_Q_Day.Cmd.txt'
            ]
Qobs_name = Qobs_list[0]

couleurs = ['navy','darkviolet']
areas = [3.7,
         # 1.2
         ]

df = pd.DataFrame()

dict_Q_wname = {}

col_list = ['dodgerblue','darkorange','red']
sce_list = ['RCP26','RCP45','RCP85']
dict_scecol = dict(zip(sce_list, col_list))

# col_list = ['red']
# sce_list = ['historic']
# dict_scecol = dict(zip(sce_list, col_list))

# fig, ax = plt.subplots(1, 1, figsize=(10,3))
fig, ax = plt.subplots(1, 1, figsize=(7,4))

for w, w_name in enumerate(['Lasset_25m'][:]):
    
    # BV = watershed_root.Watershed(watershed_name=watershed_name, dem_path=dem_path, out_path=out_path, load=True)

    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' # necessary for plots
    BV.calibration_folder = out_path+'/'+watershed_name+'/'+'results_calibration/'
    
    dfQ = pd.read_csv(init_path+Qobs_name, sep=';', parse_dates=True, index_col='date_temp') # m3/d
    Qobs = dfQ.q / (areas[0]*1e6)
    # Qobs_w_off = Qobs.resample('W', label='right', closed='left', loffset=pd.DateOffset(days=3)).mean() # loffset='2T'
    # Qobs_w_sli = Qobs.groupby(np.arange(len(Qobs))//7).mean()
    # Qobs_w_sli.index = Qobs_w_off.iloc[:-1].index
    # Qobs_w_sli = Qobs_w_sli.iloc[:-1]
    # Qobs = Qobs_w_sli.copy() * 1000
    # Qobs = Qobs.resample('M').mean()*4

    Qobs = Qobs * 1000

    i = 0
    
    for sce in sce_list[:]:
    
        for id_mod_val in list_id_mod[:]:
        
            h5file = BV.simulations_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)+'_ALL_'+sce
            d = dd.io.load(h5file)
            list_model_name = d['list_model_name'][:]
            list_model_success = d['list_model_success'][:]
            list_model_modflow = d['list_model_modflow'][:]
            
            for model_name, model_success, model_modflow in zip(list_model_name[:],
                                                                list_model_success[:],
                                                                list_model_modflow[:]):
                
                Smod = pd.read_csv(BV.simulations_folder+'/'+model_name+'/_postprocess/_timeseries/_simulated_timeseries.csv', sep=';',
                                   index_col='date', parse_dates=True)
                Smod = Smod.dropna()
                # print(Smod)

                # Smod.index = recharge_w_sli.index()
                
                r = Smod['runoff']
                Qmod = Smod['outflow_drain'] + r*1 # m/day
                # Qmod = Smod['recharge'] + r*1 # m/day
                Qmod = Qmod * 1000 # * 30
                # Qmod = Qmod.resample('M').mean()*4
                
                # Qmod = Smod['intermit_areas'] / Smod['perenn_areas']
                
                mix = Qobs.copy().to_frame()
                mix.columns = ['Qobs']
                mix['Qsim'] = Qmod
                mix = mix.dropna()
    
                Qobs_stat = mix.Qobs
                Qsim_stat = mix.Qsim
                
                import hydroeval as he
                NSE = he.evaluator(he.nse, Qsim_stat, Qobs_stat)[0]
                NSElog = he.evaluator(he.nse, Qsim_stat, Qobs_stat, transform='log')[0]
                RMSE = np.sqrt(np.nanmean((Qobs_stat.values-Qsim_stat.values)**2)) / (Qobs_stat.max()-Qobs_stat.min())
                KGE = he.evaluator(he.kge, Qsim_stat, Qobs_stat)[0][0]
                print(model_name.upper())
                print('NSE', round(NSE,2))
                print('NSElog', round(NSElog,2))
                print('RMSE', round(RMSE,2))
                print('KGE', round(KGE,2))
                
                # model_name = iD_explo+'_'+str('model')+str(id_mod_val)+'_'+\
                #              str(round(str_cond_decay,4))+'-'+str(round(str_bottom,4))+'-'+str("{:.2e}".format(koptim_val/24/3600))+'_'+\
                #              str(ip)+'_'+\
                #              str(round(str_poro_decay,4))+'-'+str(round(poro_val*100,2))
                
                df.loc[i,'model_name'] = model_name
                
                df.loc[i,'id_explo'] = iD_explo
                df.loc[i, 'id_mod'] = id_mod_val
                
                df.loc[i,'aK'] = float(model_name.split('_')[2].split('-')[0])
                df.loc[i,'bottom'] = float(model_name.split('_')[2].split('-')[1])
                
                try:
                    df.loc[i,'K'] = float(['-'.join(model_name.split('_')[2].split('-')[-2:])][0])
                except:
                    pass
                
                # df.loc[i,'id_eO'] = float(model_name.split('_')[3][0])
                
                df.loc[i,'aO'] = float(model_name.split('_')[3].split('-')[0])
                df.loc[i,'O'] = float(model_name.split('_')[3].split('-')[1])
                
                # df.loc[i,'NSE'] = float(NSE)
                # df.loc[i,'NSElog'] = float(NSElog)
                # df.loc[i,'RMSE'] = float(RMSE)
                # df.loc[i,'KGE'] = float(KGE)
                
                Q10_obs = Qobs_stat.quantile(0.10)
                Q50_obs = Qobs_stat.quantile(0.50)
                Q90_obs = Qobs_stat.quantile(0.90)
                Q10_sim = Qsim_stat.quantile(0.10)
                Q50_sim = Qsim_stat.quantile(0.50)
                Q90_sim = Qsim_stat.quantile(0.90)
                
                df.loc[i,'OWN_Q10'] = float(((Q10_sim - Q10_obs)**2) / (Q10_obs**2))
                df.loc[i,'OWN_Q50'] = float(((Q50_sim - Q50_obs)**2) / (Q50_obs**2))
                df.loc[i,'OWN_Q90'] = float(((Q90_sim - Q90_obs)**2) / (Q90_obs**2))
                
                df.loc[i,'OWN'] = ( df.loc[i,'OWN_Q10'] + df.loc[i,'OWN_Q50'] + df.loc[i,'OWN_Q90'] ) / 3
                
                i += 1
                
                # fig, (a0, a1) = plt.subplots(1, 2, gridspec_kw={'width_ratios': [3, 1]},
                #                              figsize=(10,3))
                # fig, ax = plt.subplots(1, 1, figsize=(10,3))
                
                yearsmaj = mdates.YearLocator(1)   # every year
                yearsmin = mdates.YearLocator(1)
                # monthsmaj = mdates.MonthLocator(6)  # every month
                # monthsmin = mdates.MonthLocator(3)
                # months_fmt = mdates.DateFormatter('%m') #b = name of month ?
                years_fmt = mdates.DateFormatter('%Y')
            
                ax = ax
                ax.plot(Qobs, color='k', lw=1.5, ls='-', zorder=0, label='Observed')
                ax.plot(Qmod, color='darkorange', lw=0.5, label='Seepage + Runoff')
                ax.plot(select_period(Qmod, 1975, 2010), color='k', lw=1)
                ax.plot(Qmod-(r*1000), color='red', lw=1, label='Seepage')
                ax.set_xlabel('Date')
                ax.set_ylabel('Q [mm/months]')
                ax.set_ylabel('Q [mm/d]')
                ax.set_yscale('log')
                # ax.set_ylim(0.1,100)
                years_maj = mdates.YearLocator(1)   # every year
                months_maj = mdates.MonthLocator()  # every x month
                ax.xaxis.set_major_locator(years_maj)
                ax.xaxis.set_minor_locator(months_maj)
                # ax.set_xlim(pd.to_datetime('1980'), pd.to_datetime('2100'))
                ax.legend(loc='upper right')
                ax.set_title(model_name.upper(), fontsize=10)
                # ax.set_ylim(10,1000)
                
                # axb = ax.twinx()
                # axb.bar(Smod.recharge.index, Smod.recharge*1000*30, color='grey',
                #         edgecolor='grey', width=3, lw=0)
                # # axb.bar(sim2.index, (sim2['PRELIQ_Q']+sim2['PRENEI_Q'])*1000, color='dodgerblue',
                # #         edgecolor='grey', width=2, lw=0)
                # axb.set_ylim(0,50)
                # axb.invert_yaxis()
                # axb.set_yticklabels([0,10])
            
                fig.tight_layout()
                            
                # fig.savefig(os.path.join(simulations_folder, '_figures',
                #             'STREAMFLOW_'+model_name+'.png'),
                #             bbox_inches='tight')
                
                # plt.close()
                
                # fig.savefig('C:/Users/ronan/Downloads/figs_'+iD_explos[0]+'/'+'Q_'+model_name+'.png',
                #             bbox_inches='tight')

dfcrit_Q = df.copy()

#%% FAST SATURATION CHRONICS

iD_explo = 'r1'
iD_explo = 'Daily1'
iD_explo = 'Weekly1'
iD_explo = 'pisba1' # montly projection all

types_obs = ['stream_perennial_wetlands_points']

sat_typ = 'total_areas'

areas = [
          3.7,
         ]

df = pd.DataFrame()

dict_S_wname = {}
    
BV = watershed_root.Watershed(watershed_name=watershed_name, dem_path=dem_path, out_path=out_path, load=True)

stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' # necessary for plots
BV.calibration_folder = out_path+'/'+watershed_name+'/'+'results_calibration/'

dem_data = imageio.imread(stable_folder + 'geographic/' + 'watershed_dem.tif')

# list_sat_obs = [5,10] # 7
list_sat_obs = [7.5,15] # 7

i=0

for sce in ['RCP26','RCP45','RCP85'][:]:
# for sce in ['historic'][:]:


    fig, ax = plt.subplots(1, 1, figsize=(6,3))

    for id_mod_val in list_id_mod[:]:
    
        h5file = BV.simulations_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)+'_ALL_'+sce
            
        d = dd.io.load(h5file)
        list_model_name = d['list_model_name'][:]
        list_model_success = d['list_model_success'][:]
        list_model_modflow = d['list_model_modflow'][:]
        
        for model_name, model_success, model_modflow in zip(list_model_name[:],
                                                            list_model_success[:],
                                                            list_model_modflow[:]):
            
            Smod = pd.read_csv(BV.simulations_folder+'/'+model_name+'/_postprocess/_timeseries/_simulated_timeseries.csv', sep=';',
                               index_col='date', parse_dates=True)
    
            Sat_mod = Smod[sat_typ] # m/day
                    
            Smin = Sat_mod.min()
            Smean = Sat_mod.mean()
            Smax = Sat_mod.max()
            S10 = Sat_mod.quantile(0.10)
            S25 = Sat_mod.quantile(0.25)
            S50 = Sat_mod.quantile(0.50)
            S75 = Sat_mod.quantile(0.75)
            S90 = Sat_mod.quantile(0.90)
            
            df.loc[i,'model_name'] = model_name
            
            df.loc[i,'id_explo'] = iD_explo
            df.loc[i, 'id_mod'] = id_mod_val
            
            df.loc[i,'aK'] = float(model_name.split('_')[2].split('-')[0])
            df.loc[i,'bottom'] = float(model_name.split('_')[2].split('-')[1])
            df.loc[i,'K'] = float(['-'.join(model_name.split('_')[2].split('-')[-2:])][0])
            
            # df.loc[i,'id_eO'] = float(model_name.split('_')[3][0])
            
            df.loc[i,'aO'] = float(model_name.split('_')[3].split('-')[0])
            df.loc[i,'O'] = float(model_name.split('_')[3].split('-')[1])
                
            df.loc[i,'Smin'] = float(Smin)
            df.loc[i,'Smean'] = float(Smean)
            df.loc[i,'Smax'] = float(Smax)
            df.loc[i,'S10'] = float(S10)
            df.loc[i,'S25'] = float(S25)
            df.loc[i,'S50'] = float(S50)
            df.loc[i,'S75'] = float(S75)
            df.loc[i,'S90'] = float(S90)
            
            df.loc[i,'Obs_per'] = list_sat_obs[0]
            df.loc[i,'Obs_med'] = (list_sat_obs[0]+list_sat_obs[-1])/2
            df.loc[i,'Obs_ful'] = list_sat_obs[-1]
            
            df.loc[i,'OWN_MIN'] = float(((S25 - df.loc[i,'Obs_per'])**2) / (df.loc[i,'Obs_per']**2))
            df.loc[i,'OWN_MED'] = float(((S50 - df.loc[i,'Obs_med'])**2) / (df.loc[i,'Obs_med']**2))
            df.loc[i,'OWN_MAX'] = float(((S75 - df.loc[i,'Obs_ful'])**2) / (df.loc[i,'Obs_ful']**2))
            
            df.loc[i,'OWN'] = ( df.loc[i,'OWN_MIN'] + df.loc[i,'OWN_MED'] + df.loc[i,'OWN_MAX'] ) / 3
                    
            ax.fill_between(Smod.index, 0, Smod['total_areas'],
                            interpolate=False, color='dodgerblue', alpha=0.5,
                            step='pre', label='Intermittent')
            ax.fill_between(Smod.index, 0, Smod['perenn_areas'],
                            interpolate=False, color='navy', alpha=0.5,
                            step='pre', label='Perennial')
            ax.legend(loc='upper left')
            ax.step(Smod.index, Smod['total_areas'], color='dodgerblue',
                    marker=None, markeredgecolor='none',
                    markersize=5, lw=1, label='upstream',
                    where='pre')
            ax.step(Smod.index, Smod['perenn_areas'], color='navy',
                    marker=None, markeredgecolor='none',
                    markersize=5, lw=1, label='upstream',
                    where='pre')
            # ax.step(Smod.index, Smod['seepage_areas'], color='grey',
            #         marker=None, markeredgecolor='none',
            #         markersize=5, lw=1, label='upstream',
            #         where='pre')
            
            # ax.set_ylim(5,20)
            # ax.set_yticks([5, 10, 15, 20])
            ax.set_ylabel('$A_{sat}$ [%]')
            # ax.set_xlim(pd.to_datetime('1980'), pd.to_datetime('2100'))
            plt.xticks(rotation=0, ha="right")
        
            years_maj = mdates.YearLocator(1)   # every year
            # months_maj = mdates.MonthLocator()  # every x month
            ax.xaxis.set_major_locator(years_maj)
            # ax.xaxis.set_minor_locator(months_maj)
            
            ax.set_title(model_name.upper(), fontsize=10)
            
            for j, hline in enumerate(list_sat_obs[:2]):
                if j == 0:
                    cl = 'navy'
                if j == 1:
                    cl = 'dodgerblue'
                ax.axhline(hline, c=cl, ls='--')
                
            fig.tight_layout()
                        
            # fig.savefig(os.path.join(simulations_folder, '_figures',
            #             'SATURATION_'+model_name+'.png'),
            #             bbox_inches='tight')
            
            # plt.close()
            
            # fig.savefig('C:/Users/ronan/Downloads/figs_'+iD_explos[0]+'/'+'S_'+model_name+'.png',
            #             bbox_inches='tight')
        
dfcrit_S = df.copy()

#%% ---- PLOTS PROJECTIONS - PAPER

#%% PI ANOMALIES 3 HORIZONS

iD_explo = 'p2'
iD_explo = 'pisba1' # montly projection all
iD_explo = 'pisba2' # montly projection all
list_id_mod = [6]

# sce_list = ['RCP85']
# sce_list = ['RCP26']
sce_list = ['RCP26','RCP45','RCP85']
# sce_list = ['RCP26','RCP85']

# for watershed_name in watershed_names[:1]:
stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
color = 'k'
BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=dem_path, 
                              out_path=out_path,
                              load=True)
mask = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
mask = imageio.imread(stable_folder+'geographic/'+'watershed_box_buff_dem.tif')

area = BV.geographic.area
area = int(round(area))

mod='ALL'

superficie=pd.DataFrame()

for ic, sce in enumerate(sce_list):
    years = pd.date_range(start='01/01/1975', end='31/12/2099', freq='M').year.unique()
    #df_yearly = pd.DataFrame(np.nan, index=Smod.index, columns=years)
    df_pi = pd.DataFrame(np.nan, index=range(len(mask.flatten())), columns=years)

    for id_mod_val in list_id_mod[:]:
    
        h5file = BV.simulations_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)+'_ALL_'+sce
        d = dd.io.load(h5file)
        list_model_name = d['list_model_name'][:]
        list_model_success = d['list_model_success'][:]
        list_model_modflow = d['list_model_modflow'][:]
        
        for model_name, model_success, model_modflow in zip(list_model_name[:],
                                                    list_model_success[:],
                                                    list_model_modflow[:]):
                
            Smod = pd.read_csv(BV.simulations_folder+'/'+model_name+'/_postprocess/_timeseries/_simulated_timeseries.csv', sep=';',
                               index_col='date', parse_dates=True)
                
            # Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            Smod['prop_ratio'] = Smod.intermit_areas / Smod.total_areas
            Smod['recharge'] = Smod['recharge'] * 1000 * 30
            Smod['outflow_drain'] =  ( Smod['outflow_drain'] ) * (area * 1e6) #+ Smod['runoff'] ) # * (area * 1e6)
            # Smod['groundwater_storage'] = Smod['groundwater_storage']/(Smod['groundwater_storage'].mean())
            Smod['groundwater_storage'] = Smod['groundwater_storage']
            per = 1
            Smod['dQ'] = Smod['outflow_drain'].diff()
            Smod['dGW'] = Smod['groundwater_storage'].diff()
            Smod['t'] = abs((Smod['groundwater_storage'].diff(periods=per) / Smod['outflow_drain'].diff(periods=per)))
            Smod = select_period(Smod, 1975,2099)
            
            acc_npy = np.load(BV.simulations_folder+'/'+model_name+'/_postprocess/'+'accumulation_flux.npy', allow_pickle=True).item()

            begin_h = 5*12
            end_h = 35*12
            
            # Historic
            if begin_h == 0:
                acc_npy_h = list(acc_npy.items())[:end_h]
            else:
                acc_npy_h = list(acc_npy.items())[begin_h:end_h]
            # acc_npy_1 = list(acc_npy_h)[0::12]
            # acc_npy_2 = list(acc_npy_h)[1::12]
            # acc_npy_3 = list(acc_npy_h)[2::12]
            # acc_npy_4 = list(acc_npy_h)[3::12]
            # acc_npy_5 = list(acc_npy_h)[4::12]
            # acc_npy_6 = list(acc_npy_h)[5::12]
            # acc_npy_7 = list(acc_npy_h)[6::12]
            # acc_npy_8 = list(acc_npy_h)[7::12]
            acc_npy_9 = list(acc_npy_h)[8::12]
            # acc_npy_10 = list(acc_npy_h)[9::12]
            # acc_npy_11 = list(acc_npy_h)[10::12]
            # acc_npy_12 = list(acc_npy_h)[11::12]
            # acc_npy_h = (acc_npy_6 + acc_npy_7 + acc_npy_8 + acc_npy_9 + acc_npy_10) # to much water
            acc_npy_h = (acc_npy_9) # worst
            # acc_npy_h = (acc_npy_6 + acc_npy_7 + acc_npy_8 + acc_npy_9 + acc_npy_10 + acc_npy_11 + acc_npy_12) # not bad : begin water above
            # acc_npy_h = (acc_npy_10) # pas mal mais pas assez grave
            # acc_npy_h = list(acc_npy_h)[:]
            for key in range(len(acc_npy_h)):
                acc_npy_h[key] = np.ma.masked_array(acc_npy_h[key][1], mask=(mask<-1e10))
            zero = acc_npy[0] * 0
            for i in range(len(acc_npy_h)):
                tempo = acc_npy_h[i].copy()
                tempo[tempo>0] = 1
                zero = zero + tempo
            days_flux_h = zero.copy() / len(acc_npy_h)
            
            # days_flux_h_filled = days_flux_h.filled(np.nan)
            # plt.imshow(np.ma.masked_array(days_flux_h_filled, mask=(days_flux_h_filled==0)))
            
            _ALL_h = []
            
            _ALL_h.append(days_flux_h)
            
            _ALL_h_mean = sum(_ALL_h)/len(_ALL_h)

            for interv in [[-90,-60],[-60,-30],[-30,0]]:
            # for interv in [[-30,0]]:
            # for interv in [[-90,-60]]:
                
                df_ano = pd.DataFrame()
                
                _ALL_f = []
                
                _ALL_ano = []

                fig, ax = plt.subplots(1,1, figsize=(10,10))
                print(interv)
        
                begin_f = interv[0]*12
                end_f = interv[1]*12
                # begin_f = -60*12
                # end_f = -30*12
                
                # To look
                if end_f == 0:
                    acc_npy_f = list(acc_npy.items())[begin_f:]
                else:
                    acc_npy_f = list(acc_npy.items())[begin_f:end_f]
                # acc_npy_1 = list(acc_npy_f)[0::12]
                # acc_npy_2 = list(acc_npy_f)[1::12]
                # acc_npy_3 = list(acc_npy_f)[2::12]
                # acc_npy_4 = list(acc_npy_f)[3::12]
                # acc_npy_5 = list(acc_npy_f)[4::12]
                # acc_npy_6 = list(acc_npy_f)[5::12]
                # acc_npy_7 = list(acc_npy_f)[6::12]
                # acc_npy_8 = list(acc_npy_f)[7::12]
                acc_npy_9 = list(acc_npy_f)[8::12]
                # acc_npy_10 = list(acc_npy_f)[9::12]
                # acc_npy_11 = list(acc_npy_f)[10::12]
                # acc_npy_12 = list(acc_npy_f)[11::12]
                # acc_npy_f = (acc_npy_6 + acc_npy_7 + acc_npy_8 + acc_npy_9 + acc_npy_10 + acc_npy_11 + acc_npy_12)
                # acc_npy_f = (acc_npy_1 + acc_npy_2 + acc_npy_3 + acc_npy_4 + acc_npy_5 + acc_npy_6 +
                #              acc_npy_7 + acc_npy_8 + acc_npy_9 + acc_npy_10 + acc_npy_11) # not bad : begin water above
                # acc_npy_f = (acc_npy_7 + acc_npy_8 + acc_npy_9 + acc_npy_10 + acc_npy_11)
                # acc_npy_f = (acc_npy_7 + acc_npy_8 + acc_npy_9)
                acc_npy_f = (acc_npy_9)
                # acc_npy_f = (acc_npy_10)
                # acc_npy_f = (acc_npy_7 + acc_npy_8 + acc_npy_9)
                # acc_npy_f = list(acc_npy_f)[:]
                for key in range(len(acc_npy_f)):
                    acc_npy_f[key] = np.ma.masked_array(acc_npy_f[key][1], mask=(mask<-1e10))
                zero = acc_npy[0] * 0
                for i in range(len(acc_npy_f)):
                    tempo = acc_npy_f[i].copy()
                    tempo[tempo>0] = 1
                    zero = zero + tempo
                days_flux_f = zero.copy() / len(acc_npy_f)
                
                # Anomaly
                # days_flux_ano = ( (days_flux_f - days_flux_h) ) * 100
                days_flux_ano = ( (days_flux_f - days_flux_h) ) / days_flux_h
                # data = np.ma.masked_where((days_flux_ano==0)&(days_flux_h==0), days_flux_ano)
                data = np.ma.masked_where((days_flux_ano==0)|(days_flux_h==0), days_flux_ano)
                # data = data.flatten().filled(np.nan)
                # data = data.flatten()
                # data = days_flux_ano[~days_flux_ano.mask]
                # data = data.compressed()
                # data = data[~np.isnan(data)]
                data = days_flux_ano[~days_flux_ano.mask]
                
                # h_jja, f_jja, ano_jja, jja = season_anomaly([0,1,2,3,4,5,6,7,8,9,10,11], begin_h, end_h, begin_f, end_f)
                # h_jja, f_jja, ano_jja, jja = season_anomaly([m,m,m], begin_h, end_h, begin_f, end_f)
                                        
                df_ano['ALL_'+mod+'_'+sce] = pd.Series(data)
                              
                _ALL_f.append(days_flux_f)
                
                _ALL_ano.append(days_flux_ano)
                    
                _ALL_f_mean = sum(_ALL_f)/len(_ALL_f)
                 
                _ALL_ano_mean = ( _ALL_f_mean - _ALL_h_mean ) / _ALL_h_mean
                
                for season, days_flux_h, days_flux_f, days_flux_ano in zip(['ALL'],
                                                                            [_ALL_h_mean],
                                                                            [_ALL_f_mean],
                                                                            [_ALL_ano_mean]):
                            
                    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'  # necessary for plots
                    line = imageio.imread(stable_folder+'geographic/'+'watershed_contour.tif')
                    line = np.ma.masked_where(line < 0, line)
                    mask = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
                    box = imageio.imread(stable_folder+'geographic/'+'watershed_box_buff_dem.tif')
                    hil = imageio.imread('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_data/_sig/hillshade_classic.tif')

                    pc = plt.imshow(np.ma.masked_where((days_flux_ano>-1),
                                                      days_flux_ano),
                                                cmap = mpl.colors.ListedColormap('red'))
                    
                    pc = ax.imshow(np.ma.masked_where((days_flux_ano<=-1)|(days_flux_ano>=0),
                                                      days_flux_ano),
                                                cmap = mpl.colors.ListedColormap('darkorange'))
                    
                    pc = ax.imshow(np.ma.masked_where((days_flux_ano<=0)|(days_flux_ano>=1),
                                                      days_flux_ano),
                                                cmap = mpl.colors.ListedColormap('dodgerblue'))
                    
                    pc = ax.imshow(np.ma.masked_where((days_flux_ano<1),
                                                      days_flux_ano),
                                                cmap = mpl.colors.ListedColormap('dodgerblue'))
                    
                    pc = ax.imshow(np.ma.masked_where((days_flux_ano!=0)|(days_flux_h==0),
                                                      days_flux_ano),
                                                cmap = mpl.colors.ListedColormap('dimgray'))
                    
                    pc = ax.imshow(np.ma.masked_where((days_flux_f==0)|(days_flux_h!=0),
                                                      days_flux_f),
                                                cmap = mpl.colors.ListedColormap('forestgreen'))
                    
                    plt.imshow(box, cmap = 'Greys', alpha=0.25, zorder=-1000)
                    
                    ax.imshow(np.ma.masked_where(mask>0, mask),
                                                cmap = mpl.colors.ListedColormap('white'),
                                                alpha=0.2)
                    
                    ax.get_xaxis().set_visible(False)
                    ax.get_yaxis().set_visible(False)
                    # ax.axis('off')
                    
                    ax.imshow(line, cmap=mpl.colors.ListedColormap('k'))
                    # ax.imshow(box, cmap=mpl.colors.ListedColormap('k'))
                    
                    # plt.subplots_adjust(hspace = -0.6)

                    ax.set_title(mod+'_'+sce+'_'+str(season)+'_'+str(interv), fontsize=8)
                    
                    # fig.savefig('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_figures_paper/_v0/04_fig_piproj/'+
                    #             mod+'_'+sce+'_'+str(season)+'_'+str(interv)+'.png',
                    #                         bbox_inches='tight')
                    
                    # fig.savefig('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_figures_paper/_v0/04_fig_piproj/'+
                    #             mod+'_'+sce+'_'+str(season)+'_'+str(interv)+'_7-8-9'+'.png',
                    #                         bbox_inches='tight')


                    days_flux_ano = days_flux_ano * 100
                    days_flux_ano = np.ma.masked_array(days_flux_ano, mask=(mask<0))
                    days_flux_h = np.ma.masked_array(days_flux_h, mask=(mask<0))
                    days_flux_f = np.ma.masked_array(days_flux_f, mask=(mask<0))
                    
                    total = days_flux_ano.count()
                    
                    n_0_100 = np.ma.masked_where((days_flux_ano >= 0)|(days_flux_ano <= -100), days_flux_ano).count()
                    n_100 = np.ma.masked_where((days_flux_ano > -100), days_flux_ano).count()
                    p_0_100 = np.ma.masked_where((days_flux_ano <= 0)|(days_flux_ano >= 100), days_flux_ano).count()
                    p_100 = np.ma.masked_where((days_flux_ano < 100), days_flux_ano).count()
                    flow_0 = np.ma.masked_where((days_flux_ano!=0)|(days_flux_h==0), days_flux_ano).count()
                    new_f = np.ma.masked_where((days_flux_f==0)|(days_flux_h!=0), days_flux_f).count()
                    
                    index_name = mod+'_'+sce+'_'+str(season)+'_'+str(interv)
                    column_name = '_'
                    superficie.loc[index_name,column_name+'dry_100'] = (n_100 / total)*100
                    superficie.loc[index_name,column_name+'loosing_100-0'] = (n_0_100 / total)*100
                    superficie.loc[index_name,column_name+'flow_0'] = (flow_0 / total)*100
                    superficie.loc[index_name,column_name+'gaining_0-100'] = (p_0_100 / total)*100
                    superficie.loc[index_name,column_name+'wetter_100'] = (p_100 / total)*100
                    superficie.loc[index_name,column_name+'new_flow'] = (new_f / total)*100
                    
                    folder_fig = 'D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_figures_paper/_v0/04_fig_piproj/'
                    
# superficie.to_csv(folder_fig + 'TABLE_PI_ANOMALY_' + str('ALL') + '.csv', sep=';')
# superficie.to_csv(folder_fig + 'TABLE_PI_ANOMALY_' + str('ALL') +'_7-8-9' + '.csv', sep=';')

#%% BOX PLOT OUTFLOW - PETLANDS

iD_explo = 'pisba2'

col_list = ['dodgerblue','darkorange','red']
sce_list = ['RCP26','RCP45','RCP85']
# sce_list = ['RCP85']
dict_scecol = dict(zip(sce_list, col_list))# sce_list = ['RCP85']


stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
color = 'k'
BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=dem_path, 
                              out_path=out_path,
                              load=True)
mask = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
mask_lasset = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
mask_grenou = imageio.imread(stable_folder+'subbasin/subbasin_Qgrenou/'+'watershed_dem.tif')
mask_bombee = imageio.imread(stable_folder+'subbasin/subbasin_Qbombee/'+'watershed_dem.tif')
mask_breton = imageio.imread(stable_folder+'subbasin/subbasin_Qbreton/'+'watershed_dem.tif')
dem_box = imageio.imread(stable_folder+'geographic/'+'watershed_box_buff_dem.tif')
area = BV.geographic.area
area = int(round(area))

import imageio
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False
wbt.downslope_flowpath_length(
    stable_folder+'geographic/'+'watershed_direc.tif', 
    stable_folder+'geographic/'+'downslope_flowpath_length.tif', 
    watersheds=None, 
    weights=None, 
    esri_pntr=False)
down = imageio.imread(stable_folder+'geographic/'+'downslope_flowpath_length.tif')
toolbox.export_tif(stable_folder+'geographic/'+'watershed_box_buff_dem.tif',
                   down, -99999, stable_folder+'geographic/'+'downslope_flowpath_length_box.tif')
down = imageio.imread(stable_folder+'geographic/'+'downslope_flowpath_length_box.tif')

# fig, ax = plt.subplots(1, 1, figsize=(6,6))
fig, ax = plt.subplots(1,1, figsize=(7,3.5))

# sce = 'RCP85'

for ic, sce in enumerate(sce_list):
    years = pd.date_range(start='01/01/1975', end='31/12/2099', freq='M').year.unique()
    # model_name = 'p2_model4_20.0-0-3.38e-06_40.0-0.9-1.02e-06_ALL-RCP85-1975-2099'
    # Smod = pd.read_csv(BV.simulations_folder+'/'+model_name+'/_postprocess/_timeseries/_simulated_timeseries.csv', sep=';',
    #                    index_col='date', parse_dates=True)
    # df_yearly = pd.DataFrame(np.nan, index=Smod.index, columns=years)
    # df_pi = pd.DataFrame(np.nan, index=range(len(mask.flatten())), columns=years)
    
    print(sce)
    
    # for id_mod_val in list_id_mod[:]:
    for id_mod_val in [6]:
    
        h5file = BV.simulations_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)+'_ALL_'+sce
        d = dd.io.load(h5file)
        list_model_name = d['list_model_name'][:]
        list_model_success = d['list_model_success'][:]
        list_model_modflow = d['list_model_modflow'][:]
        
        for model_name, model_success, model_modflow in zip(list_model_name[:],
                                                            list_model_success[:],
                                                            list_model_modflow[:]):
            
            Smod = pd.read_csv(BV.simulations_folder+'/'+model_name+'/_postprocess/_timeseries/_simulated_timeseries.csv', sep=';',
                               index_col='date', parse_dates=True)
                
            # Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            Smod['prop_ratio'] = Smod.intermit_areas / Smod.total_areas
            Smod['recharge'] = Smod['recharge'] * 1000 * 30
            Smod['outflow_drain'] =  ( Smod['outflow_drain'] ) * (area * 1e6) #+ Smod['runoff'] ) # * (area * 1e6)
            Smod['groundwater_storage'] = Smod['groundwater_storage']
            per = 1
            Smod['dQ'] = Smod['outflow_drain'].diff()
            Smod['dGW'] = Smod['groundwater_storage'].diff()
            Smod['t'] = abs((Smod['groundwater_storage'].diff(periods=per) / Smod['outflow_drain'].diff(periods=per)))
            Smod = select_period(Smod, 1975,2099)
            
            # acc_npy = np.load(BV.simulations_folder+'/'+model_name+'/_postprocess/'+'accumulation_flux.npy', allow_pickle=True).item()
            acc_npy = np.load(BV.simulations_folder+'/'+model_name+'/_postprocess/'+'outflow_drain.npy', allow_pickle=True).item()
            
            pi_rast = imageio.imread(BV.simulations_folder+'/'+model_name+'/_postprocess/_rasters/'+'persistency_index_t(-).tif')
            pi_rast = np.ma.masked_array(pi_rast, mask=(mask<0))
            
            acc_npy_raw = acc_npy.copy()
            # acc_npy = list(acc_npy_raw.items())[-90*12:-60*12]
            # acc_npy = list(acc_npy_raw.items())[-60*12:-30*12]

            for i in range(4):
                print(i)
                if i == 0:
                    themask = (mask_lasset < 0)
                if i == 1:
                    themask = (mask_breton < 0)
                    pzone = 'subbasin_Qbreton'
                if i == 2:
                    themask = (mask_grenou < 0)
                    pzone = 'subbasin_Qgrenou'
                if i == 3:
                    themask = (mask_bombee < 0)
                    pzone = 'subbasin_Qbombee'
                    
                if i == 0:
                    path_pol = 'E:/_RONAN/_E_SIMULATIONS/LASSET/Lasset_25m/results_stable/geographic/'+'watershed.shp'
                else:
                    path_pol = 'E:/_RONAN/_E_SIMULATIONS/LASSET/Lasset_25m/results_stable/subbasin/'+pzone+'/'+'watershed.shp'
                sub_shp = gpd.read_file(path_pol)
                sub_area = sub_shp.area
                    
                begin_h = 5*12
                end_h = 30*12
                # Historic
                if begin_h == 0:
                    acc_npy_h = list(acc_npy_raw.items())[:end_h]
                else:
                    acc_npy_h = list(acc_npy_raw.items())[begin_h:end_h]
                acc_npy_9 = list(acc_npy_h)[8::12]
                acc_npy_h = acc_npy_9
                sers = pd.DataFrame()
                for key in range(len(acc_npy_h)):
                    # mask = imageio.imread(BV.geographic.watershed_dem)
                    # mask = imageio.imread(BV.geographic.watershed_box_buff_dem)
                    acc_npy_h[key] = np.ma.masked_array(acc_npy_h[key][1], mask=themask)
                    # acc_npy[key] = np.ma.masked_array(acc_npy[key][1], mask=(mask>2000))
                    # acc_npy[key] = acc_npy[key][1][(acc_npy[key][1] > 1600) & (acc_npy[key][1] < 2000)]
                    # acc_npy[key][0] = np.ma.masked_where(mask < 1600)
                    # acc_npy[key][0] = np.ma.masked_where(mask > 2000)
                    sers[str(key)] = acc_npy_h[key].flatten() / (acc_npy_h[key].count()*25*25) * 1000
                sers = sers.dropna(how='all', axis=0)
                sers = sers[(sers.T != 0).any()]
                # sers=sers.max(axis=0)
                sers=sers.sum(axis=0)
                sers_h = sers.to_frame()
                # sers.boxplot()
                # boxprops = dict(linestyle='-', linewidth=4, color='k')
                # medianprops = dict(linestyle='-', linewidth=4, color='k')
                # ax = sers.boxplot(showfliers=False, showmeans=True,
                #         boxprops=boxprops,
                #         medianprops=medianprops, positions=[i])
                
                sers_h = (sers_h/(sub_area[0]/1e6)) * 30
                
                # ax.axhline(y=-sers_h.mean()[0], color='grey', ls='--', zorder=-1000)
                print(-sers_h.mean()[0])

                for interv_i, interv in enumerate([[-90,-60],[-60,-30],[-30,0]]):
                # for interv_i, interv in enumerate([[-90,-60]]):
                    
                    if interv[1] == 0:
                        acc_npy_f = list(acc_npy_raw.items())[interv[0]*12:]
                    else:
                        acc_npy_f = list(acc_npy_raw.items())[interv[0]*12:interv[1]*12]
                    acc_npy_9 = list(acc_npy_f)[8::12]
                    acc_npy_f = acc_npy_9
                    sers = pd.DataFrame()
                    for key in range(len(acc_npy_f)):
                        mask = imageio.imread(BV.geographic.watershed_dem)
                        # mask = imageio.imread(BV.geographic.watershed_box_buff_dem)
                        acc_npy_f[key] = np.ma.masked_array(acc_npy_f[key][1], mask=themask)
                        # acc_npy[key] = np.ma.masked_array(acc_npy[key][1], mask=(mask>2000))
                        # acc_npy[key] = acc_npy[key][1][(acc_npy[key][1] > 1600) & (acc_npy[key][1] < 2000)]
                        # acc_npy[key][0] = np.ma.masked_where(mask < 1600)
                        # acc_npy[key][0] = np.ma.masked_where(mask > 2000)
                        sers[str(key)] = acc_npy_f[key].flatten() / (acc_npy_f[key].count()*25*25) * 1000
                    sers = sers.dropna(how='all', axis=0)
                    sers = sers[(sers.T != 0).any()]
                    # sers=sers.max(axis=0)
                    sers = sers.sum(axis=0)
                    sers = (sers / (sub_area[0]/1e6)) * 30
                    
                    # sers = (sers.to_frame() - sers_h.mean()) / ((sers.to_frame() + sers_h.mean())/2)
                    # d = sers.copy() * 100
                    
                    # sers = 100* (sers.to_frame() - sers_h.mean()) / sers_h.mean()
                    # sers = (sers.to_frame() - sers_h.mean()) / ((sers.to_frame() + sers_h.mean())/2)
                    # sers = (sers.to_frame() - sers_h.mean()) / sers_h.std()
                    sers = (sers.to_frame() - sers_h.mean()) 
                    d = sers.copy() #* 100
                    
                    # d[d>100]

                    # sers.boxplot()
                    
                    # boxprops = dict(linestyle='-', linewidth=4, color=dict_scecol[sce])
                    # medianprops = dict(linestyle='-', linewidth=4, color='k')
                    # ax = sers.boxplot(showfliers=False, showmeans=False,
                    #         boxprops=boxprops,
                    #         medianprops=medianprops, positions=[i])
                    
                    boxprops1 = dict(linestyle='-', linewidth=0, color='black',
                                    facecolor=dict_scecol[sce],
                                    alpha=0.7,
                                    edgecolor='k'
                                    )
                    boxprops2 = dict(linestyle='-', linewidth=1, color='black',
                                    facecolor='None',
                                    alpha=1,
                                    edgecolor='k',
                                    )
                    medianprops = dict(linestyle='-', linewidth=1, color='black')
                    meanpointprops = dict(markersize=0, marker='o', markeredgecolor='black',
                                          markerfacecolor='k', linestyle='-')
                    
                    posbas = 0
                    if (interv_i==0) & (i==0) & (sce=='RCP26'):
                        ad = posbas - 0.90 - 0.05
                    if (interv_i==0) & (i==0) & (sce=='RCP45'):
                        ad = posbas - 0.75 - 0.05
                    if (interv_i==0) & (i==0) & (sce=='RCP85'):
                        ad = posbas - 0.60 - 0.05
                    if (interv_i==0) & (i==1) & (sce=='RCP26'):
                        ad = posbas - 0.45
                    if (interv_i==0) & (i==1) & (sce=='RCP45'):
                        ad = posbas - 0.30
                    if (interv_i==0) & (i==1) & (sce=='RCP85'):
                        ad = posbas - 0.15
                    if (interv_i==0) & (i==2) & (sce=='RCP26'):
                        ad = posbas + 0 + 0.05
                    if (interv_i==0) & (i==2) & (sce=='RCP45'):
                        ad = posbas + 0.15 + 0.05
                    if (interv_i==0) & (i==2) & (sce=='RCP85'):
                        ad = posbas + 0.30 + 0.05
                    if (interv_i==0) & (i==3) & (sce=='RCP26'):
                        ad = posbas + 0.45 + 0.10
                    if (interv_i==0) & (i==3) & (sce=='RCP45'):
                        ad = posbas + 0.60 + 0.10
                    if (interv_i==0) & (i==3) & (sce=='RCP85'):
                        ad = posbas + 0.75 + 0.10
                    
                    posbas = 2.5
                    if (interv_i==1) & (i==0) & (sce=='RCP26'):
                        ad = posbas - 0.90 - 0.05
                    if (interv_i==1) & (i==0) & (sce=='RCP45'):
                        ad = posbas - 0.75 - 0.05
                    if (interv_i==1) & (i==0) & (sce=='RCP85'):
                        ad = posbas - 0.60 - 0.05
                    if (interv_i==1) & (i==1) & (sce=='RCP26'):
                        ad = posbas - 0.45
                    if (interv_i==1) & (i==1) & (sce=='RCP45'):
                        ad = posbas - 0.30
                    if (interv_i==1) & (i==1) & (sce=='RCP85'):
                        ad = posbas - 0.15
                    if (interv_i==1) & (i==2) & (sce=='RCP26'):
                        ad = posbas + 0 + 0.05
                    if (interv_i==1) & (i==2) & (sce=='RCP45'):
                        ad = posbas + 0.15 + 0.05
                    if (interv_i==1) & (i==2) & (sce=='RCP85'):
                        ad = posbas + 0.30 + 0.05
                    if (interv_i==1) & (i==3) & (sce=='RCP26'):
                        ad = posbas + 0.45 + 0.10
                    if (interv_i==1) & (i==3) & (sce=='RCP45'):
                        ad = posbas + 0.60 + 0.10
                    if (interv_i==1) & (i==3) & (sce=='RCP85'):
                        ad = posbas + 0.75 + 0.10

                    posbas = 5
                    if (interv_i==2) & (i==0) & (sce=='RCP26'):
                        ad = posbas - 0.90 - 0.05
                    if (interv_i==2) & (i==0) & (sce=='RCP45'):
                        ad = posbas - 0.75 - 0.05
                    if (interv_i==2) & (i==0) & (sce=='RCP85'):
                        ad = posbas - 0.60 - 0.05
                    if (interv_i==2) & (i==1) & (sce=='RCP26'):
                        ad = posbas - 0.45
                    if (interv_i==2) & (i==1) & (sce=='RCP45'):
                        ad = posbas - 0.30
                    if (interv_i==2) & (i==1) & (sce=='RCP85'):
                        ad = posbas - 0.15
                    if (interv_i==2) & (i==2) & (sce=='RCP26'):
                        ad = posbas + 0 + 0.05
                    if (interv_i==2) & (i==2) & (sce=='RCP45'):
                        ad = posbas + 0.15 + 0.05
                    if (interv_i==2) & (i==2) & (sce=='RCP85'):
                        ad = posbas + 0.30 + 0.05
                    if (interv_i==2) & (i==3) & (sce=='RCP26'):
                        ad = posbas + 0.45 + 0.10
                    if (interv_i==2) & (i==3) & (sce=='RCP45'):
                        ad = posbas + 0.60 + 0.10
                    if (interv_i==2) & (i==3) & (sce=='RCP85'):
                        ad = posbas + 0.75 + 0.10
                                        
                    bp = ax.boxplot(d, widths=0.15,
                                    positions=[ad],
                                      whis=False, showfliers=False, showmeans=False, 
                                      medianprops=medianprops, meanprops=meanpointprops,
                                      patch_artist=True, boxprops=boxprops1)
                    
                    bp = ax.boxplot(d, widths=0.15,
                                    positions=[ad],
                                      whis=False, showfliers=False, showmeans=False, 
                                      medianprops=medianprops, meanprops=meanpointprops,
                                      patch_artist=True, boxprops=boxprops2)
                    
                    for element in bp['whiskers']:
                        element.set_color('k')
                        element.set_linestyle('-')
                                        
                    ax.vlines(x=ad, 
                                ymin=d.quantile(0.75), 
                                ymax=d.quantile(0.90), color='k', zorder=2)
                    ax.vlines(x=ad, 
                                ymin=d.quantile(0.10), 
                                ymax=d.quantile(0.25), color='k', zorder=2)
                    # ax.plot(ad, 
                    #           d.quantile(0.10), color='k', zorder=2, lw=0,
                    #           marker='_', mew=1)
                    # ax.plot(ad, 
                    #           d.quantile(0.90), color='k', zorder=2, lw=0,
                    #           marker='_', mew=1)
                      
                    plt.plot(ad, d.mean(), marker='o', mec='k', ms=3, lw=0,
                            mfc=dict_scecol[sce], mew=1,
                            color='k', zorder=1000, clip_on=False)
                    
                    # ax.plot(i+1+ps, d.median(), marker='_', mec='k', ms=3, lw=0,
                    #         mfc='k', mew=1,
                    #         color='k', zorder=1000)
                    
                    # ax.get_xaxis().set_visible(False)
                    # ax.set_yscale('log')
                    # ax.set_ylim(2, 200)
                    # ax.set_ylim(100, 3000)
                    # ax.set_yticks([1000,2000])
                    # ax.xaxis.set_major_formatter(matplotlib.ticker.ScalarFormatter())
                    # ax.set_yticklabels([1000,2000])
                    # ax.set_xlim(0.5,4.5)
                    
                    # ax.set_xticks([0,1,2])
                    
                    ax.set_axisbelow(True)
                    # ax.grid(zorder=-1000)
                    # ax.xaxis.grid(color='gray', alpha=0.2, zorder=-20)
                    ax.yaxis.grid(color='gray', alpha=0.2, zorder=-20, which='both')
                    
                    # ax.set_ylim(-100,70)
                    # ax.set_yticks([-100,-75,-50,-25,0,25,50])
            
                    ax.axes.xaxis.set_ticklabels([])
                    
                    
                    # ax.axhline(y=1, c='k', lw=1, ls='--', zorder=-1000)
                    # ax.axhline(y=sers_h.mean(), c='k', lw=2, ls='--', zorder=-1000)
            
            # ax.set_yscale('log')

# fig.savefig('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_figures_paper/_v0/05_fig_qproj/'+
#             'BOXPLOT_OUTFLOW_PEATLANDS'+'.png',
#                         bbox_inches='tight')

# fig.savefig('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_figures_paper/_v0/05_fig_qproj/'+
#             'BOXPLOT_OUTFLOW_PEATLANDS'+'_7-8-9'+'.png',
#                         bbox_inches='tight')

fig.savefig('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_figures_paper/_v0/05_fig_qproj/'+
            'BOXPLOT_OUTFLOW_PEATLANDS'+'_7-8-9'+'_nonorm'+'.png',
                        bbox_inches='tight')

#%% HYSTERESIS TIME - FROM PHY

# iD_explo = 'pisba1'
iD_explo = 'pisba2'

# iD_explo = 'pisbatest2' # with isba recharge ==> change ss with decay factor (details for bad models)


# test = pd.read_csv('D:/Users/abherve/ONEDRIVE_UNINECHYN/OneDrive - unine.ch/SIMULATIONS/Lasset/results_simulations/p2_model4_20.0-0-3.38e-06_40.0-0.9-1.02e-06_ALL-RCP26-1975-2099/_postprocess/_timeseries/_simulated_timeseries.csv',
#                     sep=';', parse_dates=True, index_col=0)
# test2 = pd.read_csv('E:/_RONAN/_E_SIMULATIONS/LASSET/Lasset_25m/results_simulations/pisba2_model6_30.0-0-2.86e-06_60.0-1.6-1.05e-06_ALL-RCP26-1975-2099/_postprocess/_timeseries/_simulated_timeseries.csv',
#                     sep=';', parse_dates=True, index_col=0)
# test = select_period(test, 2010,2100)
# test2 = select_period(test2, 2010,2100)
# plt.plot(test.recharge)
# plt.plot(test2.recharge)

# plt.yscale('log')
# plt.plot(test.recharge)

col_list = ['dodgerblue','darkorange','k','red']
sce_list = ['RCP26','RCP45','historic','RCP85']
# sce_list = ['RCP2.6','RCP8.5']
dict_scecol = dict(zip(sce_list, col_list))# sce_list = ['RCP85']

# col_list = ['k','red']
# sce_list = ['historic','RCP85']
# # sce_list = ['RCP2.6','RCP8.5']
# dict_scecol = dict(zip(sce_list, col_list))# sce_list = ['RCP85']

stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
color = 'k'
BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=dem_path, 
                              out_path=out_path,
                              load=True)
mask = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
mask_grenou = imageio.imread(stable_folder+'subbasin/subbasin_Qgrenou/'+'watershed_dem.tif')
dem_box = imageio.imread(stable_folder+'geographic/'+'watershed_box_buff_dem.tif')
area = BV.geographic.area
area = int(round(area))

import imageio
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False
wbt.downslope_flowpath_length(
    stable_folder+'geographic/'+'watershed_direc.tif', 
    stable_folder+'geographic/'+'downslope_flowpath_length.tif', 
    watersheds=None, 
    weights=None, 
    esri_pntr=False)
down = imageio.imread(stable_folder+'geographic/'+'downslope_flowpath_length.tif')
toolbox.export_tif(stable_folder+'geographic/'+'watershed_box_buff_dem.tif',
                   down, stable_folder+'geographic/'+'downslope_flowpath_length_box.tif', -99999)
down = imageio.imread(stable_folder+'geographic/'+'downslope_flowpath_length_box.tif')

# fig, ax = plt.subplots(1, 1, figsize=(6,6))
# fig, ax = plt.subplots(1,1, figsize=(4.5,4))
# fig, ax = plt.subplots(1,1, figsize=(6,5))

ai = 0

for ivar, var in enumerate([
                        'total_areas',
                            'prop_ratio',
                            # 'perenn_areas',
                            # 'intermit_areas'
                            # 'outflow_drain'
                            ][:]):
# for ivar, var in enumerate(['prop_ratio'][:]):
# for ivar, var in enumerate(['L_phy'][:]):
# for ivar, var in enumerate(['new_ratio'][:]):

    # if  ivar == 1:
    #     figs, axs = plt.subplots(4,1, figsize=(4.5,13.5), sharex=True, sharey=False)
    # else:
    #     figs, axs = plt.subplots(4,1, figsize=(4.5,13.5), sharex=True, sharey=False)
        
    if  ivar == 0:
        figs, axs = plt.subplots(1,4, figsize=(15,4), sharex=True, sharey=False)
    else:
        figs, axs = plt.subplots(1,4, figsize=(15,4), sharex=True, sharey=True)        
        
        
    axs = axs.ravel()
    
    compt = 1
    
    for ic, sce in enumerate(sce_list):
        years = pd.date_range(start='01/01/1975', end='31/12/2099', freq='M').year.unique()
        # df_yearly = pd.DataFrame(np.nan, index=Smod.index, columns=years)
        # df_pi = pd.DataFrame(np.nan, index=range(len(mask.flatten())), columns=years)
        
        print(sce)
        
        for id_mod_val in [6]:
            
            if sce == 'historic':
                h5file = BV.simulations_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)+'_ALL_'+'RCP85'
            else:
                h5file = BV.simulations_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)+'_ALL_'+sce
            d = dd.io.load(h5file)
            list_model_name = d['list_model_name'][:]
            list_model_success = d['list_model_success'][:]
            list_model_modflow = d['list_model_modflow'][:]
            
            for model_name, model_success, model_modflow in zip(list_model_name[:],
                                                                list_model_success[:],
                                                                list_model_modflow[:]):
                
                
                for pidx, pzone in enumerate(['subbasin_Qlasset','subbasin_Qbreton','subbasin_Qgrenou','subbasin_Qbombee']):
                # for pidx, pzone in enumerate(['subbasin_Qbreton']):
                
                    print(pzone)    
                    ax = axs[pidx]
                    # subbasin_Qlasset
                    # subbasin_Qbreton
                    # subbasin_Qgrenou
                    # subbasin_Qbombee
                    if pzone == 'subbasin_Qlasset':
                        Smod = pd.read_csv(BV.simulations_folder+'/'+model_name+'/_postprocess/_timeseries/_simulated_timeseries.csv', sep=';',
                                            index_col='date', parse_dates=True)
                    else:
                        Smod = pd.read_csv(BV.simulations_folder+'/'+model_name+'/_subbasins/'+pzone+'/_simulated_timeseries.csv', sep=';',
                                            index_col='date', parse_dates=True)
                        
                    # Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
                    Smod['prop_ratio'] = Smod.intermit_areas / Smod.total_areas
                    Smod['prop_ratio'] = Smod.intermit_areas / Smod.total_areas
                    Smod['new_ratio'] = Smod.perenn_areas
                    Smod['recharge'] = Smod['recharge'] #* 1000 * 30
                    Smod['outflow_drain'] =  ( Smod['outflow_drain'] )  #+ Smod['runoff'] ) # * (area * 1e6)
                    Smod['groundwater_storage'] = Smod['groundwater_storage']
                    per = 1
                    Smod['dQ'] = Smod['outflow_drain'].diff()
                    Smod['dGWsat'] = Smod['saturated_storage'].diff()
                    Smod['dGW'] = Smod['groundwater_storage'].diff()
                    Smod['t'] = abs((Smod['groundwater_storage'].diff(periods=per) / (Smod['outflow_drain']* (area * 1e6)).diff(periods=per)))
                    # Smod['t'] = ((Smod['groundwater_storage'].diff(periods=per) / (Smod['outflow_drain']* (area * 1e6)).diff(periods=per)))
                    # Smod['t'][Smod['t']>1000] = np.nan
                    # Smod['t'] = abs((Smod['saturated_storage'].diff(periods=per) / (Smod['outflow_drain']* (area * 1e6)).diff(periods=per)))
                    
                    # plt.plot(Smod['groundwater_storage'].diff())
                    # plt.plot(Smod['saturated_storage'].diff())
                    
                    Smod['total_areas'][np.isnan(Smod['total_areas'])] = 0
                    Smod['perenn_areas'][np.isnan(Smod['perenn_areas'])] = 0
                    Smod['intermit_areas'][np.isnan(Smod['intermit_areas'])] = 0
                    Smod['prop_ratio'][np.isnan(Smod['prop_ratio'])] = 0
                    
                    E = float(model_name.split('_')[-2].split('-')[0])
                    wt_ep = E - Smod['watertable_depth']
                    tsat = wt_ep
                    tsat = 40
                    Sy = float(model_name.split('_')[-2].split('-')[1]) / 100
                    K = float(model_name.split('_')[-2].split('-')[2]+('-'+model_name.split('_')[-2].split('-')[3])) * 3600 * 24
                    
                    Smod['L_phy'] = np.sqrt( (Smod['t']*K*tsat) / Sy )
                    
                    if sce == 'historic':
                        Smod = select_period(Smod, 1980, 2010)
                    else:
                        Smod = select_period(Smod, 2070, 2100)
                    
                    x = Smod['recharge'] * 1000 * 30
                    # x = Smod['outflow_drain'] * 1000 * 7
                    # x = Smod['t']
                    y = Smod[var]
                    y = y.fillna(0)
# y                    plt.plot(y)
                    # y = Smod['prop_ratio']
                    c = Smod.index.month
                    wy = pd.Series(x.index.month).replace([10,11,12,1,2,3,4,5,6,7,8,9],
                                                            [1,2,3,4,5,6,7,8,9,10,11,12])
                    xi = x.groupby([lambda x: x.month]).mean()
                    yi = y.groupby([lambda y: y.month]).mean()
                    
                    xiq25 = x.groupby([lambda x: x.month]).quantile(0.25)
                    yiq25 = y.groupby([lambda y: y.month]).quantile(0.25)
                    
                    xiq75 = x.groupby([lambda x: x.month]).quantile(0.75)
                    yiq75 = y.groupby([lambda y: y.month]).quantile(0.75)
                    
                    # xi = x.groupby([lambda x: x.month]).median()
                    # yi = y.groupby([lambda y: y.month]).median()
                    # cmapping = mpl.colors.ListedColormap(dict_c[watershed_name])
                    # cmapping = dict_cmap[watershed_name]
                    
                    # cmap = plt.cm.YlGnBu
                    if sce == 'historic':
                        cmap = 'Greys'
                    if sce == 'RCP26':
                        cmap = 'Blues'
                    if sce == 'RCP45':
                        cmap = 'Oranges'
                    if sce == 'RCP85':
                        cmap = 'Reds'
                    # cmap = parula_map
                    # cmaplist = [cmap(i) for i in range(cmap.N)]
                    # if watershed_name == 'Canut':
                    # cmaplist = ['limegreen','greenyellow']
                    # if watershed_name == 'Nancon':
                    #     cmaplist = ['tomato', 'lightsalmon']
                    # cmaplist[0] = (.5, .5, .5, 1.0)
                    # cmap = mpl.colors.LinearSegmentedColormap.from_list(
                    #     'Custom cmap', cmaplist, cmap.N)
                    
                    # scat = ax.scatter(x, y, c=wy, cmap=cmap, marker="o", 
                    #                   s=1, vmin=1, vmax=12, alpha=0.75, ec='none', zorder=-1)
                    xiline = xi.append(xi.iloc[[0]])
                    xiline.index = np.arange(1,14,1)
                    yiline = yi.append(yi.iloc[[0]])
                    yiline.index = np.arange(1,14,1)
                    
                    xilineq25 = xiq25.append(xiq25.iloc[[0]])
                    xilineq25.index = np.arange(1,14,1)
                    yilineq25 = yiq25.append(yiq25.iloc[[0]])
                    yilineq25.index = np.arange(1,14,1)                    
                    
                    xilineq75 = xiq75.append(xiq75.iloc[[0]])
                    xilineq75.index = np.arange(1,14,1)
                    yilineq75 = yiq75.append(yiq75.iloc[[0]])
                    yilineq75.index = np.arange(1,14,1)                  
                    
                    # ax.fill_between(xiline, yilineq25, yilineq75, lw=0,
                    #                  interpolate=False,
                    #                 color=dict_scecol[sce], alpha=0.25)
                    
                    # ax.plot(xi, yiq25, linestyle = '-', lw=0.5, 
                    #         color=dict_scecol[sce], zorder=0)
                    # ax.plot(xi, yiq75, linestyle = '-', lw=0.5, 
                    #         color=dict_scecol[sce], zorder=0)
                    
                    if (ic ==0) or (ic ==3) or (ic ==2) or (ic ==1):
                        ax.plot(xiline, yiline, linestyle = '-', lw=2, 
                                color=dict_scecol[sce], zorder=compt, clip_on=False)
                        wyi = np.arange(1,12+1,1)
                        # compt = 1
                        for k in wyi:
                            ax.plot(xi[k], yi[k], marker="o", lw=1, markersize=10.5, 
                                       markeredgecolor=dict_scecol[sce], 
                                       markerfacecolor='white', markeredgewidth=1.2,
                                       linestyle = 'None', zorder=compt, clip_on=False)
                            ax.annotate(k,(xi[k],yi[k]), family='sans-serif', fontsize=7, 
                                    color=dict_scecol[sce], weight="bold", ha='center', va='center',
                                    zorder=compt, clip_on=False)
                            compt+=1
                        xe = pd.DataFrame()
                        xe['q25'] = (x.groupby(x.index.month).quantile(0.25))
                        xe['q75'] = (x.groupby(x.index.month).quantile(0.75))        
                        ye = pd.DataFrame()
                        ye['q25'] = (y.groupby(y.index.month).quantile(0.25))
                        ye['q75'] = (y.groupby(y.index.month).quantile(0.75))                
                        # ax.errorbar(xi, yi,
                        #               yerr=np.abs(np.vstack([yi-ye.q25, ye.q75-yi])),
                        #               # xerr=np.abs(np.vstack([xi-xe.q25, xe.q75-xi])),
                        #               ecolor = dict_scecol[sce], fmt = 'none', capsize = 1,
                        #               elinewidth=0.5, 
                        #               capthick=0, zorder=-1000)
                    else:
                        ax.plot(xiline, yiline, linestyle = '-', lw=2, 
                                color=dict_scecol[sce], zorder=-1000, clip_on=False)
                        # wyi = np.arange(1,12+1,1)
                        # # compt = 1
                        # for k in wyi:
                        #     ax.plot(xi[k], yi[k], marker="o", lw=1, markersize=10.5, 
                        #                markeredgecolor=dict_scecol[sce], 
                        #                markerfacecolor='white', markeredgewidth=1.2,
                        #                linestyle = 'None', zorder=compt, clip_on=False)
                        #     ax.annotate(k,(xi[k],yi[k]), family='sans-serif', fontsize=7, 
                        #             color=dict_scecol[sce], weight="bold", ha='center', va='center',
                        #             zorder=compt, clip_on=False)
                        #     compt+=1
                        # xe = pd.DataFrame()
                        # xe['q25'] = (x.groupby(x.index.month).quantile(0.25))
                        # xe['q75'] = (x.groupby(x.index.month).quantile(0.75))        
                        # ye = pd.DataFrame()
                        # ye['q25'] = (y.groupby(y.index.month).quantile(0.25))
                        # ye['q75'] = (y.groupby(y.index.month).quantile(0.75))                
                        # ax.errorbar(xi, yi,
                        #               yerr=np.abs(np.vstack([yi-ye.q25, ye.q75-yi])),
                        #               # xerr=np.abs(np.vstack([xi-xe.q25, xe.q75-xi])),
                        #               ecolor = dict_scecol[sce], fmt = 'none', capsize = 1,
                        #               elinewidth=0.5, 
                        #               capthick=0, zorder=-1000) 
                        
                        
                    # ax.errorbar(xi, yi,
                    #               yerr=np.abs(np.vstack([yi-ye.q25, yi+ye.q25])),
                    #               xerr=np.abs(np.vstack([xi-xe.q25, xi+xe.q25])),
                    #               ecolor = dict_scecol[sce], fmt = 'none', capsize = 1, elinewidth=0.5, 
                    #               capthick=0.5, zorder=-1000)  
                    
                    # ax.grid(alpha=0.5)
                    
                    # ax.axvline(x.median(), c=dict_c[watershed_name], ls='--')
                    # ax.axhline(y.median(), c=dict_c[watershed_name], ls='--')
                    
                    # ax.set_xscale('log')
                    # ax.set_yscale('log')
                    
                    # if pidx==3:
                    ax.set_xlabel('R [mm/month]')
                    if (ivar == 0) and (pidx ==0):
                        ax.set_ylabel('$D{d sim,ful}$ [%]')
                    if (ivar == 1) and (pidx ==0):
                        ax.set_ylabel('$D_{d sim,int}$ / $D_{d,ful}$ [-]')
                    
                    # ax.set_xlim(1,1000)
                    if ivar == 0:
                        ax.set_ylim(-0,20)
                        ax.set_xlim(0,300)
                    if ivar == 1:
                        ax.set_ylim(0,1)
                        # ax.set_xscale('log')
                        ax.set_xlim(0,300)
                        
                    ai+=1
                
    figs.tight_layout()
    
    figs.savefig('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_figures_paper/_v0/06_fig_hyster/'+
                'HYSTER_'+var+'_FROM PHY_2'+'.png',
                            bbox_inches='tight')

#%% INTERMENSUAL QWT - FROM PHY

iD_explo = 'pisba2' # montly projection all

# compute_watershed_hydrogeol = True
# compute_storage = True

compute_watershed_hydrogeol = False
compute_storage = False

# compute_watershed_hydrogeol = False
# compute_storage = True

col_list = ['k','dodgerblue','darkorange','red']
sce_list = ['historic','RCP26','RCP45','RCP85']
# sce_list = ['RCP2.6','RCP8.5']
dict_scecol = dict(zip(sce_list, col_list))# sce_list = ['RCP85']

# col_list = ['k','red']
# sce_list = ['historic','RCP85']
# # sce_list = ['RCP2.6','RCP8.5']
# dict_scecol = dict(zip(sce_list, col_list))# sce_list = ['RCP85']

# col_list = ['k']
# sce_list = ['historic']
# # sce_list = ['RCP2.6','RCP8.5']
# dict_scecol = dict(zip(sce_list, col_list))# sce_list = ['RCP85']

# col_list = ['red']
# # sce_list = ['RCP85']
# sce_list = ['RCP85']
# dict_scecol = dict(zip(sce_list, col_list))# sce_list = ['RCP85']

stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
color = 'k'
BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=dem_path, 
                              out_path=out_path,
                              load=True)
mask = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
mask_lasset = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
mask_grenou = imageio.imread(stable_folder+'subbasin/subbasin_Qgrenou/'+'watershed_dem.tif')
mask_bombee = imageio.imread(stable_folder+'subbasin/subbasin_Qbombee/'+'watershed_dem.tif')
mask_breton = imageio.imread(stable_folder+'subbasin/subbasin_Qbreton/'+'watershed_dem.tif')
dem_box = imageio.imread(stable_folder+'geographic/'+'watershed_box_buff_dem.tif')
area = BV.geographic.area
# area = int(round(area))

import imageio
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False
wbt.downslope_flowpath_length(
    stable_folder+'geographic/'+'watershed_direc.tif', 
    stable_folder+'geographic/'+'downslope_flowpath_length.tif', 
    watersheds=None, 
    weights=None, 
    esri_pntr=False)
down = imageio.imread(stable_folder+'geographic/'+'downslope_flowpath_length.tif')
toolbox.export_tif(stable_folder+'geographic/'+'watershed_box_buff_dem.tif',
                   down, stable_folder+'geographic/'+'downslope_flowpath_length_box.tif', -99999)
down = imageio.imread(stable_folder+'geographic/'+'downslope_flowpath_length_box.tif')

# fig, ax = plt.subplots(1, 1, figsize=(6,6))
# fig, ax = plt.subplots(1,1, figsize=(5.5,3.5))
# fig, ax = plt.subplots(1,1, figsize=(6,5))


# for ivar, var in enumerate(['t'][:]):
# for ivar, var in enumerate(['t_phy','L_phy']):
# for ivar, var in enumerate(['t_phy']):
for ivar, var in enumerate(['outflow_drain', 'watertable_depth'][:]):
# for ivar, var in enumerate(['watertable_depth']):
# for ivar, var in enumerate(['GWman']):
# for ivar, var in enumerate(['perenn_areas']):

    if  var == 'outflow_drain':
        figs, axs = plt.subplots(1,4, figsize=(15.5,4), sharex=True, sharey=True)
    else:
        figs, axs = plt.subplots(1,4, figsize=(15,4), sharex=False, sharey=True)
        
    axs = axs.ravel()
    if  var == 'watertable_depth':
        axs[0].invert_yaxis()
    
    compt = 1

    for ic, sce in enumerate(sce_list):
        years = pd.date_range(start='01/01/1975', end='31/12/2099', freq='M').year.unique()
        # df_yearly = pd.DataFrame(np.nan, index=Smod.index, columns=years)
        # df_pi = pd.DataFrame(np.nan, index=range(len(mask.flatten())), columns=years)
        
        print(sce)
        
        for id_mod_val in [6]:
            
            if sce == 'historic':
                h5file = BV.simulations_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)+'_ALL_'+'RCP85'
            else:
                h5file = BV.simulations_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)+'_ALL_'+sce
            d = dd.io.load(h5file)
            list_model_name = d['list_model_name'][:]
            list_model_success = d['list_model_success'][:]
            list_model_modflow = d['list_model_modflow'][:]
            
            for model_name, model_success, model_modflow in zip(list_model_name[:],
                                                                list_model_success[:],
                                                                list_model_modflow[:]):
                
                mf = model_modflow.mf
                # fname = simulations_folder+model_name+'/'+model_name+'.hds'
                gridname = simulations_folder+model_name+'/'+model_name+'.dis'
                # grid_model = flopy.discretization.grid.Grid(mf)
                grid_model = mf.modelgrid
                hk_grid = mf.upw.hk
                # sy_grid = mf.upw.sy
                sy_grid = model_modflow.ps
                ss_grid = model_modflow.ss
                # sy_grid = model_modflow.ss
                # sr_model = flopy.utils.reference.SpatialReference()
                zall = model_modflow.dem - model_modflow.zbot
                zalti = model_modflow.zbot 
                list_z = []
                list_k = []
                list_p = []
                for j in range(len(zall)):
                    list_z.append(zall[j].mean())
                    list_k.append((hk_grid.array/24/3600)[j].mean())
                    list_p.append((sy_grid*100)[j].mean())
                

                
                for pidx, pzone in enumerate(['subbasin_Qlasset',
                                               'subbasin_Qbreton',
                                                'subbasin_Qgrenou',
                                                'subbasin_Qbombee'
                                              ][:]):
                    
                    print(pzone)    

                    if pidx == 0:
                        themask = mask_lasset.copy()
                    if pidx == 1:
                        themask = mask_breton.copy()
                    if pidx == 2:
                        themask = mask_grenou.copy()
                    if pidx == 3:
                        themask = mask_bombee.copy()
                    
                    # the_mask = mask_lasset.copy()
                        
                    if pzone == 'subbasin_Qlasset':
                        Smod = pd.read_csv(BV.simulations_folder+'/'+model_name+'/_postprocess/_timeseries/_simulated_timeseries.csv', sep=';',
                                            index_col='date', parse_dates=True)
                        area_sub = area * 1e6
                    else:
                        Smod = pd.read_csv(BV.simulations_folder+'/'+model_name+'/_subbasins/'+pzone+'/_simulated_timeseries.csv', sep=';',
                                            index_col='date', parse_dates=True)      
                        area_sub = gpd.read_file(BV.stable_folder+'/'+'subbasin'+'/'+pzone+'/'+'watershed.shp')
                        area_sub = area_sub['AREA'][0]
                    print(area_sub)
                    
                    ax = axs[pidx]
                    
                    # BEFORE COMPUTE HYDROGEOL BASIN AND/OR STOAGE ALONG DEPTH GRID ###
                    
                    
                    # Smod = pd.read_csv(BV.simulations_folder+'/'+model_name+'/_subbasins/'+pzone+'/_simulated_timeseries_bis2.csv', sep=';',
                    #                     index_col='date', parse_dates=True) ### CLIP WITH TOPOGRAPHICAL BASIN
                    Smod = pd.read_csv(BV.simulations_folder+'/'+model_name+'/_subbasins/'+pzone+'/_simulated_timeseries_bis4.csv', sep=';',
                                        index_col='date', parse_dates=True) ### CLIP WITH HYDROGEOLOGICAL BASIN
                    
                    # if pzone == 'subbasin_Qlasset':
                    #     Smod = pd.read_csv(BV.simulations_folder+'/'+model_name+'/_postprocess/_timeseries/_simulated_timeseries.csv', sep=';',
                    #                         index_col='date', parse_dates=True) ### CLIP WITH HYDROGEOLOGICAL BASIN
                    # else:
                    #     Smod = pd.read_csv(BV.simulations_folder+'/'+model_name+'/_subbasins/'+pzone+'/_simulated_timeseries.csv', sep=';',
                    #                         index_col='date', parse_dates=True) ### CLIP WITH HYDROGEOLOGICAL BASIN
                    
                    # Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
                    Smod['prop_ratio'] = Smod.intermit_areas / Smod.total_areas
                    Smod['recharge_m3'] = Smod['recharge'] * (area_sub) #*30 #* 1000 * 30
                    Smod['runoff_m3'] = Smod['runoff'] * (area_sub) #*30 #* 1000 * 30
                    Smod['outflow_drain_m3'] =  ( Smod['outflow_drain'] ) * (area_sub) #30
                    Smod['outflow_drain'] = (Smod['outflow_drain'] + Smod['runoff']) * 1000 * 30
                    
                    per = 1
                    Smod['dr'] = (Smod['runoff_m3']).diff(periods=per)
                    Smod['dQ'] = (Smod['outflow_drain_m3']).diff(periods=per)
                    findQ = min(Smod['dQ'][(Smod['dQ']!=0)&(~np.isnan((Smod['dQ'])))], key=abs)
                    Smod['dR'] = (Smod['recharge_m3']).diff(periods=per)
                    Smod['dGW'] = Smod['GW_calc_store_m3'].diff(periods=per)
                    Smod['GWman'] = Smod['GW_calc_sy_topo']+Smod['GW_calc_ss_topo']
                    # Smod['GWman'] = Smod['GW_calc_sy']+Smod['GW_calc_ss']
                    Smod['dGWman'] = (Smod['GWman']).diff(periods=per)
                    findGW = min(Smod['dGW'][Smod['dGW']!=0&(~np.isnan((Smod['dGW'])))], key=abs)
                    # Smod['t_phy'] = abs((Smod['groundwater_storage'].diff(periods=per) / (Smod['outflow_drain']* (area * 1e6)).diff(periods=per)))
                    # Smod['t'] = ((Smod['groundwater_storage'].diff(periods=per) / (Smod['outflow_drain']* (area * 1e6)).diff(periods=per)))
                    # Smod['t'][Smod['t']>1000] = np.nan
                    
                    # Smod['dQ'][Smod['dQ']==0] = -
                    # Smod['dGW'][Smod['dGW']==0] = findGW
                    
                    # Smod['dQ'][Smod['dQ']==0] = np.nan
                    # Smod['dGW'][Smod['dGW']==0] = np.nan
                    
                    # plt.plot(Smod['saturated_storage'])
                    
                    Smod['total_areas'][np.isnan(Smod['total_areas'])] = 0
                    Smod['perenn_areas'][np.isnan(Smod['perenn_areas'])] = 0
                    Smod['intermit_areas'][np.isnan(Smod['intermit_areas'])] = 0
                    # Smod['GW_calc_sy'][np.isnan(Smod['GW_calc_sy'])] = np.nanmin(Smod['GW_calc_sy'])
                    # Smod['GW_calc_ss'][np.isnan(Smod['GW_calc_ss'])] = np.nanmin(Smod['GW_calc_ss'])
                    # Smod['outflow_drain'][Smod['outflow_drain']==0] = 1e-6
                    # Smod['dQ'][Smod['dQ']==0] = 1
                    # Smod['outflow_drain'][np.isnan(Smod['outflow_drain'])] = 1e-6
                    
                    # Smod['GW_calc'] = Smod['GW_calc_sy'] + Smod['GW_calc_ss']
                    # Smod['dGW_calc'] = Smod['GW_calc'].diff(periods=per)                   
                    # Smod['t_phy'] = abs((Smod['GW_calc'].diff(periods=per) / (Smod['outflow_drain']* (area * 1e6)).diff(periods=per)))
                    # print(Smod['GW_calc'].diff(periods=per))
                    # Smod['GW_theo'] = (Smod['watertable_elevation']*np.nanmean(sy_grid)) * 25 * 25 
                    # Smod['t_phy'] = abs((Smod['GW_calc'].diff(periods=per) / (Smod['outflow_drain']* (area * 1e6)).diff(periods=per)))
                    # Smod['t_phy'] = abs((Smod['saturated_storage'].diff(periods=per) / (Smod['outflow_drain']* (area * 1e6)).diff(periods=per)))
                    
                    # plt.scatter(Smod['outflow_drain_m3'], Smod['GW_calc_store_m3'])
                    # plt.scatter(Smod['dQ'], Smod['dGW'])
                    
                    Smod['t_phy'] = abs(Smod['dGWman'] / Smod['dQ'])
                    # plt.plot(Smod['t_phy'])
                    
                    # Smod['t_phy'] = abs(Smod['dGW'] / (Smod['dR']+Smod['dr']))
                    
                    E = float(model_name.split('_')[-2].split('-')[0])
                    wt_ep = E - Smod['watertable_depth']
                    tsat = wt_ep
                    tsat = 40
                    Sy = float(model_name.split('_')[-2].split('-')[1]) / 100
                    K = float(model_name.split('_')[-2].split('-')[2]+('-'+model_name.split('_')[-2].split('-')[3])) * 3600 * 24
                    
                    
                    Smod['L_phy'] = np.sqrt( (Smod['t_phy']*K*tsat) / Sy )
                    
                    
                    if sce == 'historic':
                        Smod = select_period(Smod, 1980, 2010)
                        
                    else:
                        # print(sce, Smod['outflow_drain'])
                        # print(sce, Smod['GW_calc'])
                        Smod = select_period(Smod, 2070, 2100)
                        
                    data_index =  Smod.copy()
                    # data_index[np.isnan(data_index['total_areas'])] = 0
                    # data_index[np.isnan(data_index['perenn_areas'])] = 0
                    # data_index[np.isnan(data_index['intermit_areas'])] = 0
                    # data_index[np.isnan(data_index['GW_calc_sy'])] = np.nanmin(data_index['GW_calc_sy'])
                    # data_index[np.isnan(data_index['GW_calc_ss'])] = np.nanmin(data_index['GW_calc_ss'])
                    
                    # plt.plot(Smod['watertable_depth'])
        
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
                    # print(Q10.min())
                    # print(Q90.mean())
                    # Max = data_index.resample('Y').max()
                    
                    data_index = data_index.replace(np.inf, np.nan)
                    
                    mean_interan_days = data_index.groupby([data_index.index.month], as_index=True).mean()#.to_frame()
                    # mean_interan_days = data_index.groupby([data_index.index.month], as_index=True).apply(lambda g: g.mean(skipna=True))
                    
                    std_interan_days = data_index.groupby([data_index.index.month], as_index=True).std()
                    q10_interan_days = data_index.groupby([data_index.index.month], as_index=True).min()
                    q90_interan_days = data_index.groupby([data_index.index.month], as_index=True).max()
                    q50_interan_days = data_index.groupby([data_index.index.month], as_index=True).quantile(0.50)
                    # q50_interan_days = data_index.groupby([data_index.index.month], as_index=True).apply(lambda g: g.mean(skipna=True))
                    q25_interan_days = data_index.groupby([data_index.index.month], as_index=True).quantile(0.25)
                    q75_interan_days = data_index.groupby([data_index.index.month], as_index=True).quantile(0.75)
                    themean = data_index.groupby([data_index.index.month], as_index=True).mean()
                    
                    # mean_interan_days['std'] = std_interan_days
                    # mean_interan_days['q10'] = q10_interan_days
                    # mean_interan_days['q90'] = q90_interan_days
                    # mean_interan_days['q50'] = q50_interan_days['t']
                    # mean_interan_days['q75'] = q75_interan_days
                    # mean_interan_days['q25'] = q25_interan_days
                    # mean_interan_days['mean'] = themean
                    # mean_interan_days.index.names = ['months']
                    # mean_interan_days = mean_interan_days.reset_index()
                    # mean_interan_days.months = mean_interan_days.months.replace(
                    #                                     [10,11,12,1,2,3,4,5,6,7,8,9],
                    #                                     [1,2,3,4,5,6,7,8,9,10,11,12])
                    
                    mean_interan_days['q50_'+var] = q50_interan_days[var]
                    # mean_interan_days['q50_dQ'] = q50_interan_days['dQ']
                    # mean_interan_days['q50_dGW'] = q50_interan_days['dGWman']
                    
                    mean_interan_days['q75_'+var] = q75_interan_days[var]
                    mean_interan_days['q25_'+var] = q25_interan_days[var]
                    
                    mean_interan_days['months'] = np.arange(1,13,1)
                    mean_interan_days = mean_interan_days.reset_index()
                    mean_interan_days = mean_interan_days.sort_values(['months'])
                
                    mean_interan_days['counts'] = np.array(range(1,len(mean_interan_days)+1))
                    # mean_interan_days.q10 = mean_interan_days.q10.replace(0,0.01)
                    
                    # fig, ax = plt.subplots(figsize=(4,3))
                    # ax.plot(mean_interan_days.counts, mean_interan_days[station+'_mmm'],
                    #         lw=1, color='red', label='Mean')
                    ax.plot(mean_interan_days.index, mean_interan_days['q50_'+var],
                            lw=2,
                            # color=couleurs[i],
                            color=dict_scecol[sce])
                    
                    # ax.plot(mean_interan_days.index, mean_interan_days['mean'],
                    #         lw=0.5,
                    #         # color=couleurs[i],
                    #         color=dict_scecol[sce],
                    #         label=Qobs_name)
                    # ax.plot(mean_interan_days.counts, mean_interan_days['mean'],
                    #         lw=0.5,
                    #         # color=couleurs[i],
                    #         color=dict_scecol[sce],
                    #         label=Qobs_name)
                    yerrmax = mean_interan_days['q75_'+var]
                    yerrmin = mean_interan_days['q25_'+var]
                    # ax.legend('upper right')
                    ax.fill_between(mean_interan_days.index, yerrmin, yerrmax,
                                      color=dict_scecol[sce],edgecolor='None',
                                      alpha = 0.1, label='10-90th')
                    
                    # ax.plot(data_index[data_index.index.year==2022], c='k')
                    
                    # ax.fill_between(mean_interan_days.counts, yerrmin, yerrmax,
                    #                   color='grey',edgecolor='grey', lw=0.5,
                    #                   alpha = 0.5, label='10-90th')
                    
                    ax.grid(alpha=0.25)
                    
                    # ax.set_yscale('log')
                    # ax.yaxis.set_major_formatter(ScalarFormatter())
                    # ax.set_xlim(0,366)
                    # if i == 0:
                    #     ax.set_ylim(-10,20)
                    # if i == 1:
                    #     ax.set_ylim(0,10)
                    # if i == 2:
                    #     ax.set_ylim(0,10) 
                    # if i == 3:
                    #     ax.set_ylim(0,10) 
                    # if i == 4:
                    #     ax.set_ylim(0,10) 
                    # if i == 5:
                    #     ax.set_ylim(0,10) 
                    # ax.set_ylim(0.01,10)
                    ax.tick_params(axis='both', which='major', pad=10)
                    # x1 = np.linspace(0,366,13)
                    x2 = np.array([0,1,2,3,4,5,6,7,8,9,10,11])
                    squad = ['J','F','M','A','M','J','J','A','S','O','N','D']
                    ax.set_xticks(x2)
                    ax.set_xticklabels(squad, minor=False, rotation='horizontal')
                    # if i == 2:
                    # if pidx==3:
                    ax.set_xlabel('Months', labelpad=+10)
                        # ax.set_ylim(0,5)
                    # if i ==0:
                    # if var == 't_phy':
                    #     ax.set_ylabel('$t_{r}$ [d]')
                    # if var == 'L_phy':
                    #     ax.set_ylabel('$L_{c}$ [m]')
                    ax.set_xlim(0,11)
                    # ax.set_title('S'+str(i+1))
                    # ax.legend(loc='upper right', frameon=False)
                    # if i==0:
                    #     ax.set_ylim(0,)
                    # if i==1:
                    #     ax.set_ylim(0,2)
                    # ax.set_ylim(0,1000)
                    # ax.set_yscale('log')
                    # ax.set_ylim(0.1,10000)
                    
                    wyi = np.arange(0,12,1)
                    # compt = 1
                    
                    # ax.plot(mean_interan_days.index, mean_interan_days['q50_t'], marker="o", lw=1, markersize=10, 
                    #            markeredgecolor=dict_scecol[sce], 
                    #            markerfacecolor='white', markeredgewidth=1.2,
                    #            linestyle = 'None', zorder=compt, clip_on=False)
                    
                    """
                    compt=50
                    for k in wyi:
                        if (mean_interan_days['q50_dGW'][k]>0) and (mean_interan_days['q50_dQ'][k]>0):
                            marker = '^'
                        if (mean_interan_days['q50_dGW'][k]<0) and (mean_interan_days['q50_dQ'][k]>0):
                            marker = '<'
                        if (mean_interan_days['q50_dGW'][k]<0) and (mean_interan_days['q50_dQ'][k]<0):
                            marker = 'v'
                        if (mean_interan_days['q50_dGW'][k]>0) and (mean_interan_days['q50_dQ'][k]<0):
                            marker = '>'                            
                            
                        ax.plot(mean_interan_days.index[k], mean_interan_days['q50_'+var][k],
                                marker=marker, lw=1, markersize=8.5, 
                                    markeredgecolor=dict_scecol[sce], 
                                    markerfacecolor='white', markeredgewidth=1.2,
                                    linestyle = 'None', zorder=compt, clip_on=False)
                            
                        # ax.annotate(k+1,(mean_interan_days.index[k],mean_interan_days['q50_t'][k]),
                        #             family='sans-serif', fontsize=8, 
                        #     color=dict_scecol[sce], weight="bold", ha='center', va='center',
                        #     zorder=compt, clip_on=False)
                    compt+=1
                    """
                    
                    # if pidx == 0:
                    #     ax.set_ylabel(var)
                    # if pidx == 1:
                    #     ax.set_ylim(0,13)
                    # if pidx == 2:
                    #     ax.set_ylim(0,20)
                    # if pidx == 3:
                    #     ax.set_ylim(0,7)
                    
                    # if pzone == 'subbasin_Qlasset':
                    #     ax.set_ylim(0,850)
                    #     # ax.set_yscale('log')
                    
                    if var == 'outflow_drain':
                        if pidx == 0:
                            ax.set_ylabel('$Q_{sim}$ [mm/month]')
                        val_x = 0.7
                        if ic == 0:
                            val_y= 0.90
                        if ic == 1:
                            val_y= 0.80
                        if ic == 2:
                            val_y= 0.70
                        if ic == 3:
                            val_y= 0.60
                        # ax.set_yscale('log')

                    if var == 'watertable_depth':
                        if pidx == 0:
                            ax.set_ylabel('$WT_{d}$ [m]')
                        val_x = 0.1
                        if ic == 0:
                            val_y= 0.40
                        if ic == 1:
                            val_y= 0.30
                        if ic == 2:
                            val_y= 0.20
                        if ic == 3:
                            val_y= 0.10
                        ax.set_yticklabels([-0,-10,-20,-30,-40,-50,-60,-70])
                        
                    # axs[0].invert_yaxis()
    
                    if var == 'outflow_drain':
                        ax.text(val_x, val_y, r'$\bar{y}$'+' = '+str(int(mean_interan_days['q50_'+var].mean())),
                                transform=ax.transAxes, c=dict_scecol[sce], fontsize=12)
                    if var == 'watertable_depth':
                        ax.text(val_x, val_y, r'$\bar{y}$'+' = '+str('-')+str(int(mean_interan_days['q50_'+var].mean())),
                                transform=ax.transAxes, c=dict_scecol[sce], fontsize=12)
                        
    figs.tight_layout()
    
    # figs.savefig('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_figures_paper/_v0/06_fig_hyster/'+
    #             'INTM_RESP_'+var+'_FROM PHY'+'.png',
    #                         bbox_inches='tight')
    
    figs.savefig('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_figures_paper/_v0/06_fig_hyster/'+
                'INTM_MIX_'+var+'_2'+'.png',
                            bbox_inches='tight')

#%% INTERMENSUAL TIME - FROM PHY

iD_explo = 'pisba2' # montly projection all

# compute_watershed_hydrogeol = True
# compute_storage = True

compute_watershed_hydrogeol = False
compute_storage = False

# compute_watershed_hydrogeol = False
# compute_storage = True

col_list = ['dodgerblue','darkorange','k','red']
sce_list = ['RCP26','RCP45','historic','RCP85']
# sce_list = ['RCP2.6','RCP8.5']
dict_scecol = dict(zip(sce_list, col_list))# sce_list = ['RCP85']

# col_list = ['k','red']
# sce_list = ['historic','RCP85']
# # sce_list = ['RCP2.6','RCP8.5']
# dict_scecol = dict(zip(sce_list, col_list))# sce_list = ['RCP85']

# col_list = ['k']
# sce_list = ['historic']
# # sce_list = ['RCP2.6','RCP8.5']
# dict_scecol = dict(zip(sce_list, col_list))# sce_list = ['RCP85']

# col_list = ['red']
# # sce_list = ['RCP85']
# sce_list = ['RCP85']
# dict_scecol = dict(zip(sce_list, col_list))# sce_list = ['RCP85']

stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
color = 'k'
BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=dem_path, 
                              out_path=out_path,
                              load=True)
mask = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
mask_lasset = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
mask_grenou = imageio.imread(stable_folder+'subbasin/subbasin_Qgrenou/'+'watershed_dem.tif')
mask_bombee = imageio.imread(stable_folder+'subbasin/subbasin_Qbombee/'+'watershed_dem.tif')
mask_breton = imageio.imread(stable_folder+'subbasin/subbasin_Qbreton/'+'watershed_dem.tif')
dem_box = imageio.imread(stable_folder+'geographic/'+'watershed_box_buff_dem.tif')
area = BV.geographic.area
# area = int(round(area))

import imageio
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False
wbt.downslope_flowpath_length(
    stable_folder+'geographic/'+'watershed_direc.tif', 
    stable_folder+'geographic/'+'downslope_flowpath_length.tif', 
    watersheds=None, 
    weights=None, 
    esri_pntr=False)
down = imageio.imread(stable_folder+'geographic/'+'downslope_flowpath_length.tif')
toolbox.export_tif(stable_folder+'geographic/'+'watershed_box_buff_dem.tif',
                   down, stable_folder+'geographic/'+'downslope_flowpath_length_box.tif', -99999)
down = imageio.imread(stable_folder+'geographic/'+'downslope_flowpath_length_box.tif')

# fig, ax = plt.subplots(1, 1, figsize=(6,6))
# fig, ax = plt.subplots(1,1, figsize=(5.5,3.5))
# fig, ax = plt.subplots(1,1, figsize=(6,5))


# for ivar, var in enumerate(['t'][:]):
# for ivar, var in enumerate(['t_phy','L_phy']):
for ivar, var in enumerate(['t_phy']):
    
    # if  ivar == 1:
    #     figs, axs = plt.subplots(4,1, figsize=(4.5,13.5), sharex=True, sharey=False)
    # else:
    figs, axs = plt.subplots(1,4, figsize=(15,4), sharex=False, sharey=False)
    axs = axs.ravel()
    
    compt = 1

    for ic, sce in enumerate(sce_list):
        years = pd.date_range(start='01/01/1975', end='31/12/2099', freq='M').year.unique()
        # df_yearly = pd.DataFrame(np.nan, index=Smod.index, columns=years)
        # df_pi = pd.DataFrame(np.nan, index=range(len(mask.flatten())), columns=years)
        
        print(sce)
        
        for id_mod_val in [6]:
            
            if sce == 'historic':
                h5file = BV.simulations_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)+'_ALL_'+'RCP85'
            else:
                h5file = BV.simulations_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)+'_ALL_'+sce
            d = dd.io.load(h5file)
            list_model_name = d['list_model_name'][:]
            list_model_success = d['list_model_success'][:]
            list_model_modflow = d['list_model_modflow'][:]
            
            for model_name, model_success, model_modflow in zip(list_model_name[:],
                                                                list_model_success[:],
                                                                list_model_modflow[:]):
                
                mf = model_modflow.mf
                # fname = simulations_folder+model_name+'/'+model_name+'.hds'
                gridname = simulations_folder+model_name+'/'+model_name+'.dis'
                # grid_model = flopy.discretization.grid.Grid(mf)
                grid_model = mf.modelgrid
                hk_grid = mf.upw.hk
                # sy_grid = mf.upw.sy
                sy_grid = model_modflow.ps
                ss_grid = model_modflow.ss
                # sy_grid = model_modflow.ss
                # sr_model = flopy.utils.reference.SpatialReference()
                zall = model_modflow.dem - model_modflow.zbot
                zalti = model_modflow.zbot 
                list_z = []
                list_k = []
                list_p = []
                for j in range(len(zall)):
                    list_z.append(zall[j].mean())
                    list_k.append((hk_grid.array/24/3600)[j].mean())
                    list_p.append((sy_grid*100)[j].mean())
                

                
                for pidx, pzone in enumerate(['subbasin_Qlasset',
                                               # 'subbasin_Qbreton',
                                               #  'subbasin_Qgrenou','subbasin_Qbombee'
                                              ][:]):
                    
                    print(pzone)    

                    if pidx == 0:
                        themask = mask_lasset.copy()
                    if pidx == 1:
                        themask = mask_breton.copy()
                    if pidx == 2:
                        themask = mask_grenou.copy()
                    if pidx == 3:
                        themask = mask_bombee.copy()
                    
                    # the_mask = mask_lasset.copy()
                        
                    if pzone == 'subbasin_Qlasset':
                        Smod = pd.read_csv(BV.simulations_folder+'/'+model_name+'/_postprocess/_timeseries/_simulated_timeseries.csv', sep=';',
                                            index_col='date', parse_dates=True)
                        area_sub = area * 1e6
                    else:
                        Smod = pd.read_csv(BV.simulations_folder+'/'+model_name+'/_subbasins/'+pzone+'/_simulated_timeseries.csv', sep=';',
                                            index_col='date', parse_dates=True)      
                        area_sub = gpd.read_file(BV.stable_folder+'/'+'subbasin'+'/'+pzone+'/'+'watershed.shp')
                        area_sub = area_sub['AREA'][0]
                    print(area_sub)
                    
                    if sce != 'historic':
                        if compute_watershed_hydrogeol==True:
                            wt_npy = np.load(os.path.join(BV.simulations_folder+'/'+model_name+'/_postprocess/','watertable_elevation.npy'), allow_pickle=True).item()
                            test = list(wt_npy.items())[:]
                            for itime in range(len(test))[:]:
                                print(itime)

                                import whitebox
                                wbt = whitebox.WhiteboxTools()
                                wbt.verbose = False
                                
                                wt_fill_path = os.path.join(BV.simulations_folder+'/'+model_name+'/', '_postprocess/_rasters/','watertable_fill_elevation_t('+str(itime)+').tif')
                                acc_wt =  os.path.join(BV.simulations_folder+'/'+model_name+'/', '_postprocess/_rasters/','d8flowacc_wt_outlet_t('+str(itime)+').tif')
                                wbt.d8_flow_accumulation(wt_fill_path, acc_wt, log=True)
                                outlet_shp = os.path.join(BV.stable_folder+'/subbasin/'+pzone+'/', 'outlet.shp')
                                outlet_snap_shp = os.path.join(BV.stable_folder+'/subbasin/'+pzone+'/', 'outlet_snap_hydrogeol.shp')
                                if (pzone=='subbasin_Qlasset') or (pzone=='subbasin_Qbombee') or (pzone=='subbasin_Qbreton'):
                                    snap_dist_hydrogeol = 50
                                else:
                                    snap_dist_hydrogeol = 100
                                wbt.snap_pour_points(outlet_shp, acc_wt, outlet_snap_shp, snap_dist_hydrogeol)
                                wt_direc_path = os.path.join(BV.simulations_folder+'/'+model_name+'/', '_postprocess/_rasters/','d8pointer_wt_outlet_t('+str(itime)+').tif')
                                wbt.d8_pointer(
                                        wt_fill_path, 
                                        wt_direc_path)
                                watershed_wt = os.path.join(BV.simulations_folder+'/'+model_name+'/_subbasins/'+pzone+'/', 'watershed_hydrogel_t('+str(itime)+').tif')
                                # direc_wt = os.path.join(BV.stable_folder+'/geographic/', 'watershed_box_buff_direc.tif')
                                wbt.watershed(wt_direc_path, outlet_snap_shp, watershed_wt, esri_pntr=False)
               
                    # subbasin_Qbreton
                    # subbasin_Qgrenou
                    # subbasin_Qbombee
                    # if not os.path.exists(BV.simulations_folder+'/'+model_name+'/_subbasins/'+pzone+'/_simulated_timeseries_bis2.csv'):
                    
                    if sce != 'historic':
                        if compute_storage==True:
                            
                            wt_npy = np.load(os.path.join(BV.simulations_folder+'/'+model_name+'/_postprocess/','watertable_elevation.npy'), allow_pickle=True).item()
                            
                            test = list(wt_npy.items())[:]
                            list_stor_all_sy = []
                            list_stor_all_ss = []
                            for itime, wt_row in enumerate(test[:]):
                                try:
                                    print(wt_row[0])
                                    themask_wt = imageio.imread(os.path.join(BV.simulations_folder+'/'+model_name+'/_subbasins/'+pzone+'/', 'watershed_hydrogel_t('+str(itime)+').tif'))
                                    wt = wt_row[1]
                                    wt = np.ma.masked_where(themask_wt<0, wt)
                                    list_stor_time_sy = []
                                    list_stor_time_ss = []
                                    # fig, ax =plt.subplots()
                                    # ax.imshow(wt)
                                    for j in range(len(zall[:])):
                                        # j=
                                        value_sy = sy_grid[j] * zall[j] *25*25
                                        value_sy = np.ma.masked_where(zalti[j]>wt, value_sy)
                                        value_ss = ss_grid[j] * zall[j] *25*25
                                        value_ss = np.ma.masked_where(zalti[j]>wt, value_ss)
                                        list_stor_time_sy.append(np.nansum(value_sy))
                                        list_stor_time_ss.append(np.nansum(value_ss))
                                        # plt.imshow(value_sy)
                                    list_stor_all_sy.append(np.nansum(np.array(list_stor_time_sy)))
                                    list_stor_all_ss.append(np.nansum(np.array(list_stor_time_ss)))
                                    del(list_stor_time_sy)
                                    del(list_stor_time_ss)
                                    del(wt)
                                except:
                                    list_stor_all_sy.append(np.nan)
                                    list_stor_all_ss.append(np.nan)
                                    pass
                            Smod['GW_calc_sy'] = np.array(list_stor_all_sy)
                            Smod['GW_calc_ss'] = np.array(list_stor_all_ss)
                            del(list_stor_all_sy)
                            del(list_stor_all_ss)
                            
                            
                            test = list(wt_npy.items())[:]
                            list_stor_all_sy_topo = []
                            list_stor_all_ss_topo = []
                            for itime, wt_row in enumerate(test[:]):
                                try:
                                    print(wt_row[0])
                                    wt = wt_row[1]
                                    wt = np.ma.masked_where(themask<0, wt)
                                    list_stor_time_sy_topo = []
                                    list_stor_time_ss_topo = []
                                    # fig, ax =plt.subplots()
                                    # ax.imshow(wt)
                                    for j in range(len(zall[:])):
                                        # j=
                                        value_sy = sy_grid[j] * zall[j] *25*25
                                        value_sy = np.ma.masked_where(zalti[j]>wt, value_sy)
                                        value_ss = ss_grid[j] * zall[j] *25*25
                                        value_ss = np.ma.masked_where(zalti[j]>wt, value_ss)
                                        list_stor_time_sy_topo.append(np.nansum(value_sy))
                                        list_stor_time_ss_topo.append(np.nansum(value_ss))
                                        # plt.imshow(value_sy)
                                    list_stor_all_sy_topo.append(np.nansum(np.array(list_stor_time_sy_topo)))
                                    list_stor_all_ss_topo.append(np.nansum(np.array(list_stor_time_ss_topo)))
                                    del(list_stor_time_sy_topo)
                                    del(list_stor_time_ss_topo)
                                    del(wt)
                                except:
                                    list_stor_all_sy_topo.append(np.nan)
                                    list_stor_all_ss_topo.append(np.nan)
                                    pass
                            Smod['GW_calc_sy_topo'] = np.array(list_stor_all_sy_topo)
                            Smod['GW_calc_ss_topo'] = np.array(list_stor_all_ss_topo)
                            del(list_stor_all_sy_topo)
                            del(list_stor_all_ss_topo)
                            
                            
                            
                            
                            import flopy.utils.binaryfile as fpu
                            import flopy.utils.binaryfile as bf
                            # if 'cbb' not in globals():
                            cbb = fpu.CellBudgetFile(BV.simulations_folder+'/'+model_name+'/' + model_name + '.cbc')
                            # cbb.list_records()
                            kstpkper = cbb.get_kstpkper()
                            times = cbb.get_times()
                            # drain = cbb.get_data(text='DRAINS', kstpkper=kstpkper[0])
                            list_D = []
                            list_R = []
                            list_S = []
                            for i in np.array(range(len(kstpkper))):  
                                if pzone == 'subbasin_Qlasset':
                                    # themask = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
                                    try:
                                        themask = imageio.imread(os.path.join(BV.simulations_folder+'/'+model_name+'/_subbasins/'+pzone+'/', 'watershed_hydrogel_t('+str(i+1)+').tif'))
                                    except:
                                        themask = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
                                        # print(i+1)
                                        pass
                                else:
                                    try:
                                        themask = imageio.imread(os.path.join(BV.simulations_folder+'/'+model_name+'/_subbasins/'+pzone+'/', 'watershed_hydrogel_t('+str(i+1)+').tif'))
                                    except:
                                        themask = imageio.imread(stable_folder+'subbasin/'+pzone+'/'+'watershed_dem.tif')
                                        pass
                                        
                                # print(i)
                                # dtb = cbb.get_data(text='DRAINS', kstpkper=(0,5))# , kstpkper=(0,0))
                                stb = cbb.get_data(text='STORAGE', kstpkper=(0,i+1))# , kstpkper=(0,0))
                                # stb = cbb.get_data(text='STORAGE', kstpkper=(0,), totim=5)# , kstpkper=(0,0))
                                # print(abs(np.nansum(stb)))

                                try:
                                    arrays = stb[0]
                                    masked_array = np.where(themask>0, arrays, np.nan)
                                    sum_stb = abs(np.nansum(masked_array))
                                    # sum_dtb = abs(dtb[0]['q'].sum()
                                    list_S.append(sum_stb)
                                except:
                                    pass
                            list_S[:0] = [np.nanmean(np.array(list_S))]
                            # plt.plot(list_S)
                            
                            Smod['GW_calc_store_m3'] = np.array(list_S)
                            
                            Smod.to_csv(BV.simulations_folder+'/'+model_name+'/_subbasins/'+pzone+'/_simulated_timeseries_bis4.csv', sep=';')
                    
                    ax = axs[pidx]
                    
                    # BEFORE COMPUTE HYDROGEOL BASIN AND/OR STOAGE ALONG DEPTH GRID ###
                    
                    
                    # Smod = pd.read_csv(BV.simulations_folder+'/'+model_name+'/_subbasins/'+pzone+'/_simulated_timeseries_bis2.csv', sep=';',
                    #                     index_col='date', parse_dates=True) ### CLIP WITH TOPOGRAPHICAL BASIN
                    Smod = pd.read_csv(BV.simulations_folder+'/'+model_name+'/_subbasins/'+pzone+'/_simulated_timeseries_bis4.csv', sep=';',
                                        index_col='date', parse_dates=True) ### CLIP WITH HYDROGEOLOGICAL BASIN
                    
                    # if pzone == 'subbasin_Qlasset':
                    #     Smod = pd.read_csv(BV.simulations_folder+'/'+model_name+'/_postprocess/_timeseries/_simulated_timeseries.csv', sep=';',
                    #                         index_col='date', parse_dates=True) ### CLIP WITH HYDROGEOLOGICAL BASIN
                    # else:
                    #     Smod = pd.read_csv(BV.simulations_folder+'/'+model_name+'/_subbasins/'+pzone+'/_simulated_timeseries.csv', sep=';',
                    #                         index_col='date', parse_dates=True) ### CLIP WITH HYDROGEOLOGICAL BASIN
                    
                    # Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
                    Smod['prop_ratio'] = Smod.intermit_areas / Smod.total_areas
                    Smod['recharge_m3'] = Smod['recharge'] * (area_sub) #*30 #* 1000 * 30
                    Smod['runoff_m3'] = Smod['runoff'] * (area_sub) #*30 #* 1000 * 30
                    Smod['outflow_drain_m3'] =  ( Smod['outflow_drain'] ) * (area_sub) #* 30
                    
                    per = 1
                    Smod['dr'] = (Smod['runoff_m3']).diff(periods=per)
                    Smod['dQ'] = (Smod['outflow_drain_m3']).diff(periods=per)
                    findQ = min(Smod['dQ'][(Smod['dQ']!=0)&(~np.isnan((Smod['dQ'])))], key=abs)
                    Smod['dR'] = (Smod['recharge_m3']).diff(periods=per)
                    Smod['dGW'] = Smod['GW_calc_store_m3'].diff(periods=per)
                    Smod['GWman'] = Smod['GW_calc_sy']+Smod['GW_calc_ss']
                    # Smod['GWman'] = Smod['GW_calc_sy_topo']+Smod['GW_calc_ss_topo']
                    Smod['dGWman'] = (Smod['GWman']).diff(periods=per)
                    findGW = min(Smod['dGW'][Smod['dGW']!=0&(~np.isnan((Smod['dGW'])))], key=abs)
                    # Smod['t_phy'] = abs((Smod['groundwater_storage'].diff(periods=per) / (Smod['outflow_drain']* (area * 1e6)).diff(periods=per)))
                    # Smod['t'] = ((Smod['groundwater_storage'].diff(periods=per) / (Smod['outflow_drain']* (area * 1e6)).diff(periods=per)))
                    # Smod['t'][Smod['t']>1000] = np.nan
                    
                    # Smod['dQ'][Smod['dQ']==0] = -
                    # Smod['dGW'][Smod['dGW']==0] = findGW
                    
                    # Smod['dQ'][Smod['dQ']==0] = np.nan
                    # Smod['dGW'][Smod['dGW']==0] = np.nan
                    
                    # plt.plot(Smod['saturated_storage'])
                    
                    Smod['total_areas'][np.isnan(Smod['total_areas'])] = 0
                    Smod['perenn_areas'][np.isnan(Smod['perenn_areas'])] = 0
                    Smod['intermit_areas'][np.isnan(Smod['intermit_areas'])] = 0
                    # Smod['GW_calc_sy'][np.isnan(Smod['GW_calc_sy'])] = np.nanmin(Smod['GW_calc_sy'])
                    # Smod['GW_calc_ss'][np.isnan(Smod['GW_calc_ss'])] = np.nanmin(Smod['GW_calc_ss'])
                    # Smod['outflow_drain'][Smod['outflow_drain']==0] = 1e-6
                    # Smod['dQ'][Smod['dQ']==0] = 1
                    # Smod['outflow_drain'][np.isnan(Smod['outflow_drain'])] = 1e-6
                    
                    # Smod['GW_calc'] = Smod['GW_calc_sy'] + Smod['GW_calc_ss']
                    # Smod['dGW_calc'] = Smod['GW_calc'].diff(periods=per)                   
                    # Smod['t_phy'] = abs((Smod['GW_calc'].diff(periods=per) / (Smod['outflow_drain']* (area * 1e6)).diff(periods=per)))
                    # print(Smod['GW_calc'].diff(periods=per))
                    # Smod['GW_theo'] = (Smod['watertable_elevation']*np.nanmean(sy_grid)) * 25 * 25 
                    # Smod['t_phy'] = abs((Smod['GW_calc'].diff(periods=per) / (Smod['outflow_drain']* (area * 1e6)).diff(periods=per)))
                    # Smod['t_phy'] = abs((Smod['saturated_storage'].diff(periods=per) / (Smod['outflow_drain']* (area * 1e6)).diff(periods=per)))
                    
                    # plt.scatter(Smod['outflow_drain_m3'], Smod['GW_calc_store_m3'])
                    # plt.scatter(Smod['dQ'], Smod['dGW'])
                    
                    Smod['t_phy'] = abs(Smod['dGWman'] / Smod['dQ'])
                    # plt.plot(Smod['t_phy'])
                    
                    # Smod['t_phy'] = abs(Smod['dGW'] / (Smod['dR']+Smod['dr']))
                    
                    E = float(model_name.split('_')[-2].split('-')[0])
                    wt_ep = E - Smod['watertable_depth']
                    tsat = wt_ep
                    tsat = 40
                    Sy = float(model_name.split('_')[-2].split('-')[1]) / 100
                    K = float(model_name.split('_')[-2].split('-')[2]+('-'+model_name.split('_')[-2].split('-')[3])) * 3600 * 24
                    
                    
                    Smod['L_phy'] = np.sqrt( (Smod['t_phy']*K*tsat) / Sy )
                    
                    
                    if sce == 'historic':
                        Smod = select_period(Smod, 1980, 2010)
                        
                    else:
                        # print(sce, Smod['outflow_drain'])
                        # print(sce, Smod['GW_calc'])
                        Smod = select_period(Smod, 2070, 2100)
                        
                    data_index =  Smod.copy()
                    # data_index[np.isnan(data_index['total_areas'])] = 0
                    # data_index[np.isnan(data_index['perenn_areas'])] = 0
                    # data_index[np.isnan(data_index['intermit_areas'])] = 0
                    # data_index[np.isnan(data_index['GW_calc_sy'])] = np.nanmin(data_index['GW_calc_sy'])
                    # data_index[np.isnan(data_index['GW_calc_ss'])] = np.nanmin(data_index['GW_calc_ss'])
                    
                    # plt.plot(Smod['watertable_depth'])
        
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
                    # print(Q10.min())
                    # print(Q90.mean())
                    # Max = data_index.resample('Y').max()
                    
                    data_index = data_index.replace(np.inf, np.nan)
                    
                    mean_interan_days = data_index.groupby([data_index.index.month], as_index=True).mean()#.to_frame()
                    # mean_interan_days = data_index.groupby([data_index.index.month], as_index=True).apply(lambda g: g.mean(skipna=True))
                    
                    std_interan_days = data_index.groupby([data_index.index.month], as_index=True).std()
                    q10_interan_days = data_index.groupby([data_index.index.month], as_index=True).min()
                    q90_interan_days = data_index.groupby([data_index.index.month], as_index=True).max()
                    q50_interan_days = data_index.groupby([data_index.index.month], as_index=True).quantile(0.50)
                    # q50_interan_days = data_index.groupby([data_index.index.month], as_index=True).apply(lambda g: g.mean(skipna=True))
                    q25_interan_days = data_index.groupby([data_index.index.month], as_index=True).quantile(0.25)
                    q75_interan_days = data_index.groupby([data_index.index.month], as_index=True).quantile(0.75)
                    themean = data_index.groupby([data_index.index.month], as_index=True).mean()
                    
                    # mean_interan_days['std'] = std_interan_days
                    # mean_interan_days['q10'] = q10_interan_days
                    # mean_interan_days['q90'] = q90_interan_days
                    # mean_interan_days['q50'] = q50_interan_days['t']
                    # mean_interan_days['q75'] = q75_interan_days
                    # mean_interan_days['q25'] = q25_interan_days
                    # mean_interan_days['mean'] = themean
                    # mean_interan_days.index.names = ['months']
                    # mean_interan_days = mean_interan_days.reset_index()
                    # mean_interan_days.months = mean_interan_days.months.replace(
                    #                                     [10,11,12,1,2,3,4,5,6,7,8,9],
                    #                                     [1,2,3,4,5,6,7,8,9,10,11,12])
                    
                    mean_interan_days['q50_'+var] = q50_interan_days[var]
                    mean_interan_days['q50_dQ'] = q50_interan_days['dQ']
                    mean_interan_days['q50_dGW'] = q50_interan_days['dGWman']
                    
                    mean_interan_days['q75_'+var] = q75_interan_days[var]
                    mean_interan_days['q25_'+var] = q25_interan_days[var]

                    mean_interan_days['months'] = np.arange(1,13,1)
                    mean_interan_days = mean_interan_days.reset_index()
                    mean_interan_days = mean_interan_days.sort_values(['months'])
                
                    mean_interan_days['counts'] = np.array(range(1,len(mean_interan_days)+1))
                    # mean_interan_days.q10 = mean_interan_days.q10.replace(0,0.01)
                    
                    # fig, ax = plt.subplots(figsize=(4,3))
                    # ax.plot(mean_interan_days.counts, mean_interan_days[station+'_mmm'],
                    #         lw=1, color='red', label='Mean')
                    
                    if ic == 0:
                        ax.plot(mean_interan_days.index, mean_interan_days['q50_'+var],
                                lw=2,
                                # color=couleurs[i],
                                color=dict_scecol[sce],
                                zorder=10)
                    else:
                        ax.plot(mean_interan_days.index, mean_interan_days['q50_'+var],
                                lw=2,
                                # color=couleurs[i],
                                color=dict_scecol[sce])
                    
                    # ax.plot(mean_interan_days.index, mean_interan_days['mean'],
                    #         lw=0.5,
                    #         # color=couleurs[i],
                    #         color=dict_scecol[sce],
                    #         label=Qobs_name)
                    # ax.plot(mean_interan_days.counts, mean_interan_days['mean'],
                    #         lw=0.5,
                    #         # color=couleurs[i],
                    #         color=dict_scecol[sce],
                    #         label=Qobs_name)
                    yerrmax = mean_interan_days['q75_'+var]
                    yerrmin = mean_interan_days['q25_'+var]
                    # ax.legend('upper right')
                    if (ic ==0) or (ic ==3)or (ic ==2)or (ic ==1):
                        ax.fill_between(mean_interan_days.index, yerrmin, yerrmax,
                                          color=dict_scecol[sce],edgecolor='None',
                                          alpha = 0.1, label='10-90th')
                    
                    ax.set_yscale('log')
                    ax.set_ylim(40,1000)
                    
                    # ax.plot(data_index[data_index.index.year==2022], c='k')
                    
                    # ax.fill_between(mean_interan_days.counts, yerrmin, yerrmax,
                    #                   color='grey',edgecolor='grey', lw=0.5,
                    #                   alpha = 0.5, label='10-90th')
                    
                    # ax.grid(alpha=0.25)
                    
                    # ax.set_yscale('log')
                    # ax.yaxis.set_major_formatter(ScalarFormatter())
                    # ax.set_xlim(0,366)
                    # if i == 0:
                    #     ax.set_ylim(-10,20)
                    # if i == 1:
                    #     ax.set_ylim(0,10)
                    # if i == 2:
                    #     ax.set_ylim(0,10) 
                    # if i == 3:
                    #     ax.set_ylim(0,10) 
                    # if i == 4:
                    #     ax.set_ylim(0,10) 
                    # if i == 5:
                    #     ax.set_ylim(0,10) 
                    # ax.set_ylim(0.01,10)
                    ax.tick_params(axis='both', which='major', pad=10)
                    # x1 = np.linspace(0,366,13)
                    x2 = np.array([0,1,2,3,4,5,6,7,8,9,10,11])
                    squad = ['J','F','M','A','M','J','J','A','S','O','N','D']
                    ax.set_xticks(x2)
                    ax.set_xticklabels(squad, minor=False, rotation='horizontal')
                    # if i == 2:
                    # if pidx==3:
                    ax.set_xlabel('Months', labelpad=+10)
                        # ax.set_ylim(0,5)
                    # if i ==0:
                    # if var == 't_phy':
                    #     ax.set_ylabel('$t_{r}$ [d]')
                    # if var == 'L_phy':
                    #     ax.set_ylabel('$L_{c}$ [m]')
                    ax.set_xlim(0,11)
                    # ax.set_title('S'+str(i+1))
                    # ax.legend(loc='upper right', frameon=False)
                    # if i==0:
                    #     ax.set_ylim(0,)
                    # if i==1:
                    #     ax.set_ylim(0,2)
                    # ax.set_ylim(0,1000)
                    # ax.set_yscale('log')
                    # ax.set_ylim(0.1,10000)
                    
                    wyi = np.arange(0,12,1)
                    # compt = 1
                    
                    # ax.plot(mean_interan_days.index, mean_interan_days['q50_t'], marker="o", lw=1, markersize=10, 
                    #            markeredgecolor=dict_scecol[sce], 
                    #            markerfacecolor='white', markeredgewidth=1.2,
                    #            linestyle = 'None', zorder=compt, clip_on=False)
                    # compt=50
                    for k in wyi:
                        if (mean_interan_days['q50_dGW'][k]>0) and (mean_interan_days['q50_dQ'][k]>0):
                            marker = '^'
                        if (mean_interan_days['q50_dGW'][k]<0) and (mean_interan_days['q50_dQ'][k]>0):
                            marker = '<'
                        if (mean_interan_days['q50_dGW'][k]<0) and (mean_interan_days['q50_dQ'][k]<0):
                            marker = 'v'
                        if (mean_interan_days['q50_dGW'][k]>0) and (mean_interan_days['q50_dQ'][k]<0):
                            marker = '>'                            
                        
                        if (ic ==0) or (ic ==3)or (ic ==2)or (ic ==1):
                            ax.plot(mean_interan_days.index[k], mean_interan_days['q50_'+var][k],
                                    marker=marker, lw=1, markersize=7, 
                                        markeredgecolor=dict_scecol[sce], 
                                        markerfacecolor='white', markeredgewidth=1.2,
                                        linestyle = 'None', zorder=compt+1000, clip_on=False)
                            
                        # ax.annotate(k+1,(mean_interan_days.index[k],mean_interan_days['q50_t'][k]),
                        #             family='sans-serif', fontsize=8, 
                        #     color=dict_scecol[sce], weight="bold", ha='center', va='center',
                        #     zorder=compt, clip_on=False)
                    compt+=1
                    
                    if pidx == 0:
                        ax.set_ylabel('$t_{r}$ [d]')
                    # if pidx == 1:
                    #     ax.set_ylim(0,13)
                    # if pidx == 2:
                    #     ax.set_ylim(0,20)
                    # if pidx == 3:
                    #     ax.set_ylim(0,7)
                    
                    # if pzone == 'subbasin_Qlasset':
                    #     ax.set_ylim(0,850)
                        # ax.set_yscale('log')
                        

    figs.tight_layout()
    
    # figs.savefig('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_figures_paper/_v0/06_fig_hyster/'+
    #             'INTM_RESP_'+var+'_FROM PHY'+'.png',
    #                         bbox_inches='tight')
    
    figs.savefig('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_figures_paper/_v0/06_fig_hyster/'+
                'INTM_RESP_'+var+'_FROM PHY'+'_hydrogeol_'+'2'+'.png',
                            bbox_inches='tight')

#%% BOXPLOT RESPONSE TIME - FROM PHY

col_list = ['k','dodgerblue','darkorange','red']
sce_list = ['historic','RCP26','RCP45','RCP85']
# sce_list = ['RCP2.6','RCP8.5']
dict_scecol = dict(zip(sce_list, col_list))# sce_list = ['RCP85']

# col_list = ['k','dodgerblue','darkorange']
# sce_list = ['historic','RCP26','RCP45']
# # sce_list = ['RCP2.6','RCP8.5']
# dict_scecol = dict(zip(sce_list, col_list))# sce_list = ['RCP85']

# col_list = ['k','red']
# sce_list = ['historic','RCP85']
# # sce_list = ['RCP2.6','RCP8.5']
# dict_scecol = dict(zip(sce_list, col_list))# sce_list = ['RCP85']

stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
color = 'k'
BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=dem_path, 
                              out_path=out_path,
                              load=True)
mask = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
mask_grenou = imageio.imread(stable_folder+'subbasin/subbasin_Qgrenou/'+'watershed_dem.tif')
dem_box = imageio.imread(stable_folder+'geographic/'+'watershed_box_buff_dem.tif')
area = BV.geographic.area
area = int(round(area))

import imageio
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False
wbt.downslope_flowpath_length(
    stable_folder+'geographic/'+'watershed_direc.tif', 
    stable_folder+'geographic/'+'downslope_flowpath_length.tif', 
    watersheds=None, 
    weights=None, 
    esri_pntr=False)
down = imageio.imread(stable_folder+'geographic/'+'downslope_flowpath_length.tif')
toolbox.export_tif(stable_folder+'geographic/'+'watershed_box_buff_dem.tif',
                   down, -99999, stable_folder+'geographic/'+'downslope_flowpath_length_box.tif')
down = imageio.imread(stable_folder+'geographic/'+'downslope_flowpath_length_box.tif')

# fig, ax = plt.subplots(1, 1, figsize=(6,6))
# fig, ax = plt.subplots(1,1, figsize=(5.5,3.5))
# fig, ax = plt.subplots(1,1, figsize=(6,5))

for ivar, var in enumerate(['t_phy','L_phy'][:1]):
    
    # if  ivar == 1:
    #     figs, axs = plt.subplots(4,1, figsize=(4.5,13.5), sharex=True, sharey=False)
    # else:
    # figs, axs = plt.subplots(4,1, figsize=(2.5,13.5), sharex=True, sharey=False)
    # axs = axs.ravel()
    
    figs, axs = plt.subplots(1,4, figsize=(10,4), sharex=False, sharey=False)
    axs = axs.ravel()
    
    compt = 1

    for ic, sce in enumerate(sce_list):
        years = pd.date_range(start='01/01/1975', end='31/12/2099', freq='M').year.unique()
        # df_yearly = pd.DataFrame(np.nan, index=Smod.index, columns=years)
        # df_pi = pd.DataFrame(np.nan, index=range(len(mask.flatten())), columns=years)
        
        print(sce)
        
        for id_mod_val in [6]:
            
            if sce == 'historic':
                h5file = BV.simulations_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)+'_ALL_'+'RCP85'
            else:
                h5file = BV.simulations_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)+'_ALL_'+sce
            d = dd.io.load(h5file)
            list_model_name = d['list_model_name'][:]
            list_model_success = d['list_model_success'][:]
            list_model_modflow = d['list_model_modflow'][:]
            
            for model_name, model_success, model_modflow in zip(list_model_name[:],
                                                                list_model_success[:],
                                                                list_model_modflow[:]):
                
                Smod = pd.read_csv(BV.simulations_folder+'/'+model_name+'/_postprocess/_timeseries/_simulated_timeseries.csv', sep=';',
                                    index_col='date', parse_dates=True)
                
                for pidx, pzone in enumerate(['subbasin_Qlasset',
                                              # 'subbasin_Qbreton','subbasin_Qgrenou','subbasin_Qbombee'
                                              ]):
                    
                    if pzone == 'subbasin_Qlasset':
                        Smod = pd.read_csv(BV.simulations_folder+'/'+model_name+'/_postprocess/_timeseries/_simulated_timeseries.csv', sep=';',
                                            index_col='date', parse_dates=True)
                        area_sub = area * 1e6
                    else:
                        Smod = pd.read_csv(BV.simulations_folder+'/'+model_name+'/_subbasins/'+pzone+'/_simulated_timeseries.csv', sep=';',
                                            index_col='date', parse_dates=True)      
                        area_sub = gpd.read_file(BV.stable_folder+'/'+'subbasin'+'/'+pzone+'/'+'watershed.shp')
                        area_sub = area_sub['AREA'][0]
                        
                    print(area_sub)
                    
                    print(pzone)    
                    ax = axs[pidx]
               
                    # subbasin_Qbreton
                    # subbasin_Qgrenou
                    # subbasin_Qbombee
                    # Smod = pd.read_csv(BV.simulations_folder+'/'+model_name+'/_subbasins/'+pzone+'/_simulated_timeseries.csv', sep=';',
                    #                     index_col='date', parse_dates=True)
                    
                    # Smod = pd.read_csv(BV.simulations_folder+'/'+model_name+'/_subbasins/'+pzone+'/_simulated_timeseries_bis2.csv', sep=';',
                    #                     index_col='date', parse_dates=True)
                    
                    # Smod = pd.read_csv(BV.simulations_folder+'/'+model_name+'/_subbasins/'+pzone+'/_simulated_timeseries_bis3.csv', sep=';',
                    #                     index_col='date', parse_dates=True)
                    
                    # Smod = pd.read_csv(BV.simulations_folder+'/'+model_name+'/_subbasins/'+pzone+'/_simulated_timeseries_bis4.csv', sep=';',
                    #                     index_col='date', parse_dates=True) ### CLIP WITH HYDROGEOLOGICAL BASIN
                    
                    Smod = pd.read_csv(BV.simulations_folder+'/'+model_name+'/_subbasins/'+pzone+'/_simulated_timeseries_bis4.csv', sep=';',
                                        index_col='date', parse_dates=True) ### CLIP WITH HYDROGEOLOGICAL BASIN
                    
                    # if pzone == 'subbasin_Qlasset':
                    #     Smod = pd.read_csv(BV.simulations_folder+'/'+model_name+'/_postprocess/_timeseries/_simulated_timeseries.csv', sep=';',
                    #                         index_col='date', parse_dates=True) ### CLIP WITH HYDROGEOLOGICAL BASIN
                    # else:
                    #     Smod = pd.read_csv(BV.simulations_folder+'/'+model_name+'/_subbasins/'+pzone+'/_simulated_timeseries.csv', sep=';',
                    #                         index_col='date', parse_dates=True) ### CLIP WITH HYDROGEOLOGICAL BASIN
                    
                    # Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
                    Smod['prop_ratio'] = Smod.intermit_areas / Smod.total_areas
                    Smod['recharge_m3'] = Smod['recharge'] * (area_sub) #*30 #* 1000 * 30
                    Smod['runoff_m3'] = Smod['runoff'] * (area_sub) #*30 #* 1000 * 30
                    Smod['outflow_drain_m3'] =  ( Smod['outflow_drain'] ) * (area_sub) #30
                    
                    per = 1
                    Smod['dr'] = (Smod['runoff_m3']).diff(periods=per)
                    Smod['dQ'] = (Smod['outflow_drain_m3']).diff(periods=per)
                    findQ = min(Smod['dQ'][(Smod['dQ']!=0)&(~np.isnan((Smod['dQ'])))], key=abs)
                    Smod['dR'] = (Smod['recharge_m3']).diff(periods=per)
                    Smod['dGW'] = Smod['GW_calc_store_m3'].diff(periods=per)
                    Smod['dGWman'] = (Smod['GW_calc_sy']+Smod['GW_calc_ss']).diff(periods=per)
                    # findGW = min(Smod['dGW'][Smod['dGW']!=0&(~np.isnan((Smod['dGW'])))], key=abs)
                    # Smod['t_phy'] = abs((Smod['groundwater_storage'].diff(periods=per) / (Smod['outflow_drain']* (area * 1e6)).diff(periods=per)))
                    # Smod['t'] = ((Smod['groundwater_storage'].diff(periods=per) / (Smod['outflow_drain']* (area * 1e6)).diff(periods=per)))
                    # Smod['t'][Smod['t']>1000] = np.nan
                    
                    # Smod['dQ'][Smod['dQ']==0] = -
                    # Smod['dGW'][Smod['dGW']==0] = findGW
                    
                    # Smod['dQ'][Smod['dQ']==0] = np.nan
                    # Smod['dGW'][Smod['dGW']==0] = np.nan
                    
                    # plt.plot(Smod['saturated_storage'])
                    
                    Smod['total_areas'][np.isnan(Smod['total_areas'])] = 0
                    Smod['perenn_areas'][np.isnan(Smod['perenn_areas'])] = 0
                    Smod['intermit_areas'][np.isnan(Smod['intermit_areas'])] = 0
                    # Smod['GW_calc_sy'][np.isnan(Smod['GW_calc_sy'])] = np.nanmin(Smod['GW_calc_sy'])
                    # Smod['GW_calc_ss'][np.isnan(Smod['GW_calc_ss'])] = np.nanmin(Smod['GW_calc_ss'])
                    # Smod['outflow_drain'][Smod['outflow_drain']==0] = 1e-6
                    # Smod['dQ'][Smod['dQ']==0] = 1
                    # Smod['outflow_drain'][np.isnan(Smod['outflow_drain'])] = 1e-6
                    
                    # Smod['GW_calc'] = Smod['GW_calc_sy'] + Smod['GW_calc_ss']
                    # Smod['dGW_calc'] = Smod['GW_calc'].diff(periods=per)                   
                    # Smod['t_phy'] = abs((Smod['GW_calc'].diff(periods=per) / (Smod['outflow_drain']* (area * 1e6)).diff(periods=per)))
                    # print(Smod['GW_calc'].diff(periods=per))
                    # Smod['GW_theo'] = (Smod['watertable_elevation']*np.nanmean(sy_grid)) * 25 * 25 
                    # Smod['t_phy'] = abs((Smod['GW_calc'].diff(periods=per) / (Smod['outflow_drain']* (area * 1e6)).diff(periods=per)))
                    # Smod['t_phy'] = abs((Smod['saturated_storage'].diff(periods=per) / (Smod['outflow_drain']* (area * 1e6)).diff(periods=per)))
                    
                    # plt.scatter(Smod['outflow_drain_m3'], Smod['GW_calc_store_m3'])
                    # plt.scatter(Smod['dQ'], Smod['dGW'])
                    
                    Smod['t_phy'] = abs(Smod['dGWman'] / Smod['dQ'])
                    # plt.plot(Smod['t_phy'])
                                        
                    E = float(model_name.split('_')[-2].split('-')[0])
                    wt_ep = E - Smod['watertable_depth']
                    tsat = wt_ep
                    tsat = 40
                    Sy = float(model_name.split('_')[-2].split('-')[1]) / 100
                    K = float(model_name.split('_')[-2].split('-')[2]+('-'+model_name.split('_')[-2].split('-')[3])) * 3600 * 24
                    
                    Smod['L_phy'] = np.sqrt( (Smod['t_phy']*K*tsat) / Sy )
        
                    if sce == 'historic':
                        Smod = select_period(Smod, 1980,2010)
                    else:
                        Smod = select_period(Smod, 2070, 2100)
            
                    # ax.plot(Smod['t'].resample('Y').mean().rolling(10).mean(), color=dict_scecol[sce])
                    # ax.scatter(Smod['t'], Smod['intermit_areas']/Smod['total_areas'],  color=dict_scecol[sce], s=1)
                    # ax.boxplot(1, Smod['t'])
        
                    # ax.set_yscale('log')
                    # ax.set_xlim(0,1000)
                    # ax.set_xscale('log')
                    
                    boxprops1 = dict(linestyle='-', linewidth=0, color='black',
                                    facecolor=dict_scecol[sce],
                                    alpha=0.7,
                                    edgecolor='k'
                                    )
                    boxprops2 = dict(linestyle='-', linewidth=1.5, color='black',
                                    facecolor='None',
                                    alpha=1,
                                    edgecolor='k',
                                    )
                    medianprops = dict(linestyle='-', linewidth=1.5, color='black')
                    meanpointprops = dict(markersize=0, marker='o', markeredgecolor='black',
                                          markerfacecolor='k', linestyle='-')
                    
                    if sce == 'historic':
                        ad = 0.30-0.10
                    if sce == 'RCP26':
                        ad = 0.45-0.05
                    if sce == 'RCP45':
                        ad = 0.60
                    if sce == 'RCP85':
                        ad = 0.75+0.05
                    
                    fil = Smod[var][~np.isnan(Smod[var])]
                    bp = ax.boxplot(fil, widths=0.15,
                                    positions=[ad],
                                      whis=False, showfliers=False, showmeans=False, 
                                      medianprops=medianprops, meanprops=meanpointprops,
                                      patch_artist=True, boxprops=boxprops1)
                    bp = ax.boxplot(fil, widths=0.15,
                                    positions=[ad],
                                      whis=False, showfliers=False, showmeans=False, 
                                      medianprops=medianprops, meanprops=meanpointprops,
                                      patch_artist=True, boxprops=boxprops2)
                    
                    for element in bp['whiskers']:
                        element.set_color('k')
                        element.set_linestyle('-')
                                        
                    ax.vlines(x=ad, 
                                ymin=fil.quantile(0.75), 
                                ymax=fil.quantile(0.90), color='k', zorder=2)
                    ax.vlines(x=ad, 
                                ymin=fil.quantile(0.10), 
                                ymax=fil.quantile(0.25), color='k', zorder=2)
                    # ax.plot(ad, 
                    #           d.quantile(0.10), color='k', zorder=2, lw=0,
                    #           marker='_', mew=1)
                    # ax.plot(ad, 
                    #           d.quantile(0.90), color='k', zorder=2, lw=0,
                    #           marker='_', mew=1)
                      
                    # ax.plot(ad, fil.mean(), marker='o', mec='k', ms=3, lw=0,
                    #         mfc='k', mew=1,
                    #         color='k', zorder=1000)
                    
                    # if i ==0:
                    #     ax.set_ylabel('$t_{r}$ [d]')
                    if var == 't_phy':
                        ax.set_ylabel('$t_{r}$ [d]')
                    if var == 'L_phy':
                        ax.set_ylabel('$L_{c}$ [m]')
                    ax.set_xlim(-0,1)
                    if pidx ==3:
                        ax.set_xlabel('XXX')
                            
                    # ax.grid(alpha=0.5)
                    
                    ax.set_xticklabels(ax.get_xticks().round(2))
                    
                    # if var == 't_phy':
                    #     if pidx == 0:
                    #         ax.set_ylim(0,120)
                    #     if pidx == 1:
                    #         ax.set_ylim(0,13)
                    #     if pidx == 2:
                    #         ax.set_ylim(0,20)
                    #     if pidx == 3:
                    #         ax.set_ylim(0,7)
                    
                    if pzone == 'subbasin_Qlasset':
                        ax.set_ylim(0,850)
                        # ax.set_yscale('log')
                        
                    ax.set_xlabel(sce)
                    
                    ax.set_yscale('log')
                    ax.set_ylim(40,1000)
                    
    figs.tight_layout()
    
    # figs.savefig('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_figures_paper/_v0/06_fig_hyster/'+
    #             'BOXP_RESP_'+var+'_FROM PHY'+'.png',
    #                         bbox_inches='tight')
    
    figs.savefig('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_figures_paper/_v0/06_fig_hyster/'+
                'BOXP_RESP_'+var+'_FROM PHY'+'_hydrogeol_'+'2'+'.png',
                            bbox_inches='tight')



                    
#%% ---- PLOTS PROJECTIONS - INTERESTING

#%% BOX PLOT OUTFLOW - ALTITUDE

col_list = ['dodgerblue','darkorange','red']
sce_list = ['RCP26','RCP45','RCP85']
# sce_list = ['RCP2.6','RCP8.5']
dict_scecol = dict(zip(sce_list, col_list))# sce_list = ['RCP85']

stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
color = 'k'
BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=dem_path, 
                              out_path=out_path,
                              load=True)
mask = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
mask_grenou = imageio.imread(stable_folder+'subbasin/subbasin_Qgrenou/'+'watershed_dem.tif')
dem_box = imageio.imread(stable_folder+'geographic/'+'watershed_box_buff_dem.tif')
area = BV.geographic.area
area = int(round(area))

import imageio
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False
wbt.downslope_flowpath_length(
    stable_folder+'geographic/'+'watershed_direc.tif', 
    stable_folder+'geographic/'+'downslope_flowpath_length.tif', 
    watersheds=None, 
    weights=None, 
    esri_pntr=False)
down = imageio.imread(stable_folder+'geographic/'+'downslope_flowpath_length.tif')
toolbox.export_tif(stable_folder+'geographic/'+'watershed_box_buff_dem.tif',
                   down, -99999, stable_folder+'geographic/'+'downslope_flowpath_length_box.tif')
down = imageio.imread(stable_folder+'geographic/'+'downslope_flowpath_length_box.tif')

# fig, ax = plt.subplots(1, 1, figsize=(6,6))
fig, ax = plt.subplots(1,1, figsize=(6,3.8))

for ic, sce in enumerate(sce_list):
    years = pd.date_range(start='01/01/1975', end='31/12/2099', freq='M').year.unique()
    df_yearly = pd.DataFrame(np.nan, index=Smod.index, columns=years)
    df_pi = pd.DataFrame(np.nan, index=range(len(mask.flatten())), columns=years)
    
    print(sce)
    
    for id_mod_val in list_id_mod[:]:
    
        h5file = BV.simulations_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)+'_ALL_'+sce
        d = dd.io.load(h5file)
        list_model_name = d['list_model_name'][:]
        list_model_success = d['list_model_success'][:]
        list_model_modflow = d['list_model_modflow'][:]
        
        for model_name, model_success, model_modflow in zip(list_model_name[:],
                                                            list_model_success[:],
                                                            list_model_modflow[:]):
            
            Smod = pd.read_csv(BV.simulations_folder+'/'+model_name+'/_postprocess/_timeseries/_simulated_timeseries.csv', sep=';',
                               index_col='date', parse_dates=True)
                
            # Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            Smod['prop_ratio'] = Smod.intermit_areas / Smod.total_areas
            Smod['recharge'] = Smod['recharge'] * 1000 * 30
            Smod['outflow_drain'] =  ( Smod['outflow_drain'] ) * (area * 1e6) #+ Smod['runoff'] ) # * (area * 1e6)
            Smod['groundwater_storage'] = Smod['groundwater_storage']
            per = 1
            Smod['dQ'] = Smod['outflow_drain'].diff()
            Smod['dGW'] = Smod['groundwater_storage'].diff()
            Smod['t'] = abs((Smod['groundwater_storage'].diff(periods=per) / Smod['outflow_drain'].diff(periods=per)))
            Smod = select_period(Smod, 1975,2099)
            
            # acc_npy = np.load(BV.simulations_folder+'/'+model_name+'/_postprocess/'+'accumulation_flux.npy', allow_pickle=True).item()
            acc_npy = np.load(BV.simulations_folder+'/'+model_name+'/_postprocess/'+'outflow_drain.npy', allow_pickle=True).item()
            
            pi_rast = imageio.imread(BV.simulations_folder+'/'+model_name+'/_postprocess/_rasters/'+'persistency_index_t(-).tif')
            pi_rast = np.ma.masked_array(pi_rast, mask=(mask<0))
            
            acc_npy_raw = acc_npy.copy()
            # acc_npy = list(acc_npy_raw.items())[-90*12:-60*12]
            # acc_npy = list(acc_npy_raw.items())[-60*12:-30*12]

            for i in range(3):
                print(i)
                if i == 0:
                    themask = (mask > 1600)
                if i == 1:
                    themask = (mask < 1600) #| (mask > 2000)
                if i == 2:
                    themask = (mask < 2000)
                # if i == 3:
                #     themask = (mask_grenou < 0)
                    
                begin_h = 5*12
                end_h = 35*12
                # Historic
                if begin_h == 0:
                    acc_npy_h = list(acc_npy_raw.items())[:end_h]
                else:
                    acc_npy_h = list(acc_npy_raw.items())[begin_h:end_h]
                # acc_npy_1 = list(acc_npy_h)[5::12]
                # acc_npy_2 = list(acc_npy_h)[6::12]
                # acc_npy_3 = list(acc_npy_h)[7::12]
                # acc_npy_4 = list(acc_npy_h)[8::12]
                # acc_npy_5 = list(acc_npy_h)[9::12]
                # acc_npy_6 = list(acc_npy_h)[10::12]           
                # acc_npy_h = (acc_npy_1 + acc_npy_2 + acc_npy_3 + acc_npy_4 + acc_npy_5 + acc_npy_6)
                # acc_npy_h = (acc_npy_3 + acc_npy_4 + acc_npy_5)
                acc_npy_h = list(acc_npy_h)[:]
                sers = pd.DataFrame()
                for key in range(len(acc_npy_h)):
                    mask = imageio.imread(BV.geographic.watershed_dem)
                    # mask = imageio.imread(BV.geographic.watershed_box_buff_dem)
                    acc_npy_h[key] = np.ma.masked_array(acc_npy_h[key][1], mask=themask)
                    # acc_npy[key] = np.ma.masked_array(acc_npy[key][1], mask=(mask>2000))
                    # acc_npy[key] = acc_npy[key][1][(acc_npy[key][1] > 1600) & (acc_npy[key][1] < 2000)]
                    # acc_npy[key][0] = np.ma.masked_where(mask < 1600)
                    # acc_npy[key][0] = np.ma.masked_where(mask > 2000)
                    sers[str(key)] = acc_npy_h[key].flatten() / (acc_npy_h[key].count()*25*25) * 1000
                sers = sers.dropna(how='all', axis=0)
                sers = sers[(sers.T != 0).any()]
                # sers=sers.max(axis=0)
                sers=sers.sum(axis=0)
                sers_h = sers.to_frame()
                # sers.boxplot()
                # boxprops = dict(linestyle='-', linewidth=4, color='k')
                # medianprops = dict(linestyle='-', linewidth=4, color='k')
                # ax = sers.boxplot(showfliers=False, showmeans=True,
                #         boxprops=boxprops,
                #         medianprops=medianprops, positions=[i])
                
                for interv_i, interv in enumerate([[-90,-60],[-60,-30],[-30,0]]):
                # for interv_i, interv in enumerate([[-90,-60]]):
                    
                    
                    if interv[1] == 0:
                        acc_npy_f = list(acc_npy_raw.items())[interv[0]*12:]
                    else:
                        acc_npy_f = list(acc_npy_raw.items())[interv[0]*12:interv[1]*12]
                    # acc_npy_1 = list(acc_npy_h)[5::12]
                    # acc_npy_2 = list(acc_npy_h)[6::12]
                    # acc_npy_3 = list(acc_npy_f)[7::12]
                    # acc_npy_4 = list(acc_npy_f)[8::12]
                    # acc_npy_5 = list(acc_npy_f)[9::12]
                    # acc_npy_6 = list(acc_npy_h)[10::12]           
                    # acc_npy_h = (acc_npy_1 + acc_npy_2 + acc_npy_3 + acc_npy_4 + acc_npy_5 + acc_npy_6)
                    # acc_npy_f = (acc_npy_3 + acc_npy_4 + acc_npy_5)
                    acc_npy_f = list(acc_npy_f)[:]
                    sers = pd.DataFrame()
                    for key in range(len(acc_npy_f)):
                        mask = imageio.imread(BV.geographic.watershed_dem)
                        # mask = imageio.imread(BV.geographic.watershed_box_buff_dem)
                        acc_npy_f[key] = np.ma.masked_array(acc_npy_f[key][1], mask=themask)
                        # acc_npy[key] = np.ma.masked_array(acc_npy[key][1], mask=(mask>2000))
                        # acc_npy[key] = acc_npy[key][1][(acc_npy[key][1] > 1600) & (acc_npy[key][1] < 2000)]
                        # acc_npy[key][0] = np.ma.masked_where(mask < 1600)
                        # acc_npy[key][0] = np.ma.masked_where(mask > 2000)
                        sers[str(key)] = acc_npy_f[key].flatten() / (acc_npy_f[key].count()*25*25) * 1000
                    sers = sers.dropna(how='all', axis=0)
                    sers = sers[(sers.T != 0).any()]
                    # sers=sers.max(axis=0)
                    sers=sers.sum(axis=0)
                    sers = (sers.to_frame() - sers_h.mean()) / ((sers.to_frame() + sers_h.mean())/2)
                    d = sers.copy() * 100
                    # sers.boxplot()
                    
                    # boxprops = dict(linestyle='-', linewidth=4, color=dict_scecol[sce])
                    # medianprops = dict(linestyle='-', linewidth=4, color='k')
                    # ax = sers.boxplot(showfliers=False, showmeans=False,
                    #         boxprops=boxprops,
                    #         medianprops=medianprops, positions=[i])
                    
                    boxprops1 = dict(linestyle='-', linewidth=0, color='black',
                                    facecolor=dict_scecol[sce],
                                    alpha=0.7,
                                    edgecolor='k'
                                    )
                    boxprops2 = dict(linestyle='-', linewidth=1, color='black',
                                    facecolor='None',
                                    alpha=1,
                                    edgecolor='k',
                                    )
                    medianprops = dict(linestyle='-', linewidth=1, color='black')
                    meanpointprops = dict(markersize=0, marker='o', markeredgecolor='black',
                                          markerfacecolor='k', linestyle='-')
                    
                    if (interv_i==0) & (i==0) & (sce=='RCP26'):
                        ad = 0 - 0.60
                    if (interv_i==0) & (i==0) & (sce=='RCP45'):
                        ad = 0 - 0.45
                    if (interv_i==0) & (i==0) & (sce=='RCP85'):
                        ad = 0 - 0.30
                    if (interv_i==0) & (i==1) & (sce=='RCP26'):
                        ad = 0 - 0.15
                    if (interv_i==0) & (i==1) & (sce=='RCP45'):
                        ad = 0
                    if (interv_i==0) & (i==1) & (sce=='RCP85'):
                        ad = 0 + 0.15
                    if (interv_i==0) & (i==2) & (sce=='RCP26'):
                        ad = 0 + 0.30
                    if (interv_i==0) & (i==2) & (sce=='RCP45'):
                        ad = 0 + 0.45
                    if (interv_i==0) & (i==2) & (sce=='RCP85'):
                        ad = 0 + 0.60

                    if (interv_i==1) & (i==0) & (sce=='RCP26'):
                        ad = 2 - 0.60
                    if (interv_i==1) & (i==0) & (sce=='RCP45'):
                        ad = 2 - 0.45
                    if (interv_i==1) & (i==0) & (sce=='RCP85'):
                        ad = 2 - 0.30
                    if (interv_i==1) & (i==1) & (sce=='RCP26'):
                        ad = 2 - 0.15
                    if (interv_i==1) & (i==1) & (sce=='RCP45'):
                        ad = 2 - 0
                    if (interv_i==1) & (i==1) & (sce=='RCP85'):
                        ad = 2 + 0.15
                    if (interv_i==1) & (i==2) & (sce=='RCP26'):
                        ad = 2 + 0.30
                    if (interv_i==1) & (i==2) & (sce=='RCP45'):
                        ad = 2 + 0.45
                    if (interv_i==1) & (i==2) & (sce=='RCP85'):
                        ad = 2 + 0.60

                    if (interv_i==2) & (i==0) & (sce=='RCP26'):
                        ad = 4 - 0.60
                    if (interv_i==2) & (i==0) & (sce=='RCP45'):
                        ad = 4 - 0.45
                    if (interv_i==2) & (i==0) & (sce=='RCP85'):
                        ad = 4 - 0.30
                    if (interv_i==2) & (i==1) & (sce=='RCP26'):
                        ad = 4 - 0.15
                    if (interv_i==2) & (i==1) & (sce=='RCP45'):
                        ad = 4 - 0
                    if (interv_i==2) & (i==1) & (sce=='RCP85'):
                        ad = 4 + 0.15
                    if (interv_i==2) & (i==2) & (sce=='RCP26'):
                        ad = 4 + 0.30
                    if (interv_i==2) & (i==2) & (sce=='RCP45'):
                        ad = 4 + 0.45       
                    if (interv_i==2) & (i==2) & (sce=='RCP85'):
                        ad = 4 + 0.60
                                        
                    bp = ax.boxplot(d, widths=0.15,
                                    positions=[ad],
                                      whis=False, showfliers=False, showmeans=False, 
                                      medianprops=medianprops, meanprops=meanpointprops,
                                      patch_artist=True, boxprops=boxprops1)
                    bp = ax.boxplot(d, widths=0.15,
                                    positions=[ad],
                                      whis=False, showfliers=False, showmeans=False, 
                                      medianprops=medianprops, meanprops=meanpointprops,
                                      patch_artist=True, boxprops=boxprops2)
                    for element in bp['whiskers']:
                        element.set_color('k')
                        element.set_linestyle('-')
                                        
                    ax.vlines(x=ad, 
                                ymin=d.quantile(0.75), 
                                ymax=d.quantile(0.90), color='k', zorder=2)
                    ax.vlines(x=ad, 
                                ymin=d.quantile(0.10), 
                                ymax=d.quantile(0.25), color='k', zorder=2)
                    # ax.plot(ad, 
                    #           d.quantile(0.10), color='k', zorder=2, lw=0,
                    #           marker='_', mew=1)
                    # ax.plot(ad, 
                    #           d.quantile(0.90), color='k', zorder=2, lw=0,
                    #           marker='_', mew=1)
                      
                    plt.plot(ad, d.mean(), marker='o', mec='k', ms=2.5, lw=0,
                            mfc='k', mew=1,
                            color='k', zorder=1000)
                    
                    # ax.plot(i+1+ps, d.median(), marker='_', mec='k', ms=3, lw=0,
                    #         mfc='k', mew=1,
                    #         color='k', zorder=1000)
                    
                    # ax.get_xaxis().set_visible(False)
                    # ax.set_yscale('log')
                    # ax.set_ylim(2, 200)
                    # ax.set_ylim(100, 3000)
                    # ax.set_yticks([1000,2000])
                    # ax.xaxis.set_major_formatter(matplotlib.ticker.ScalarFormatter())
                    # ax.set_yticklabels([1000,2000])
                    # ax.set_xlim(0.5,4.5)
                    
                    # ax.set_xticks([0,1,2])
                    
                    ax.set_axisbelow(True)
                    # ax.grid(zorder=-1000)
                    # ax.xaxis.grid(color='gray', alpha=0.2, zorder=-20)
                    ax.yaxis.grid(color='gray', alpha=0.2, zorder=-20, which='both')
                    
                    ax.set_ylim(-150,100)
                    
                    # ax.axhline(y=0, c='k', lw=0.5, ls='-', zorder=-1000)
                    
                    # ax.get_xaxis().set_visible(False)
                    ax.axes.xaxis.set_ticklabels([])
                    
            # ax.set_yscale('log')

fig.savefig('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_figures_paper/_v0/05_fig_qproj/'+
            'BOXPLOT_OUTFLOW_ALTITUDE'+'.png',
                        bbox_inches='tight')

#%% NUMBER OF DAYS UNDER Q10 HISTORIC

iD_explo = 'p2'

CRIT = 'RMSE'

init_path = data_path + '_Q/'

Qobs_list =[
             'lasset_Q_Day.Cmd.txt',
             # 'truites_Q_Day.Cmd.txt'
            ]
Qobs_name = Qobs_list[0]

couleurs = ['navy','darkviolet']
areas = [3.7,
         # 1.2
         ]

df = pd.DataFrame()

dict_Q_wname = {}

col_list = ['k','dodgerblue','darkorange','red']
sce_list = ['historic','RCP26','RCP45','RCP85']
dict_scecol = dict(zip(sce_list, col_list))


for w, w_name in enumerate(['Lasset'][:]):
    
    # BV = watershed_root.Watershed(watershed_name=watershed_name, dem_path=dem_path, out_path=out_path, load=True)

    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' # necessary for plots
    BV.calibration_folder = out_path+'/'+watershed_name+'/'+'results_calibration/'
    
    dfQ = pd.read_csv(init_path+Qobs_name, sep=';', parse_dates=True, index_col='date_temp') # m3/d
    Qobs = dfQ.q / (areas[0]*1e6)
    Qobs_w_off = Qobs.resample('W', label='right', closed='left', loffset=pd.DateOffset(days=3)).mean() # loffset='2T'
    Qobs_w_sli = Qobs.groupby(np.arange(len(Qobs))//7).mean()
    Qobs_w_sli.index = Qobs_w_off.iloc[:-1].index
    Qobs_w_sli = Qobs_w_sli.iloc[:-1]
    Qobs = Qobs_w_sli.copy() * 1000
    # Qobs = Qobs.resample('M').mean()*4

    i = 0
    
    for pidx, pzone in enumerate(['subbasin_Qlasset','subbasin_Qbreton','subbasin_Qgrenou','subbasin_Qbombee'][:]):
        
        fig, ax = plt.subplots(1, 1, figsize=(8,3))

        for sce in sce_list[:]:
            
            df_rec = pd.DataFrame()
        
            for id_mod_val in list_id_mod[:]:
                
                if sce == 'historic':
                    h5file = BV.simulations_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)+'_ALL_'+'RCP85'
                else:
                    h5file = BV.simulations_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)+'_ALL_'+sce
                d = dd.io.load(h5file)
                list_model_name = d['list_model_name'][:]
                list_model_success = d['list_model_success'][:]
                list_model_modflow = d['list_model_modflow'][:]
                
                for model_name, model_success, model_modflow in zip(list_model_name[:],
                                                                    list_model_success[:],
                                                                    list_model_modflow[:]):
                    
                    Smod = pd.read_csv(BV.simulations_folder+'/'+model_name+'/_postprocess/_timeseries/_simulated_timeseries.csv', sep=';',
                                       index_col='date', parse_dates=True)
                                
                    print(pzone)    
                    # ax = axs[pidx]
                    # subbasin_Qlasset
                    # subbasin_Qbreton
                    # subbasin_Qgrenou
                    # subbasin_Qbombee
                    Smod = pd.read_csv(BV.simulations_folder+'/'+model_name+'/_subbasins/'+pzone+'/_simulated_timeseries.csv', sep=';',
                                        index_col='date', parse_dates=True)
                
                    Smod = Smod.dropna()
                    # print(Smod)
    
                    # Smod.index = recharge_w_sli.index()
                    
                    r = Smod['runoff']
                    Qmod = Smod['outflow_drain'] + r*1 # m/day
                    # Qmod = Smod['recharge'] + r*1 # m/day
                    Qmod = Qmod * 1000 * 30
                    # Qmod = Qmod.resample('M').mean()*4
                    
                    # Qmod = Smod['intermit_areas'] / Smod['perenn_areas']
                    
                    mix = Qobs.copy().to_frame()
                    mix.columns = ['Qobs']
                    mix['Qsim'] = Qmod
                    mix = mix.dropna()
        
                    Qobs_stat = mix.Qobs
                    Qsim_stat = mix.Qsim
                    
                    # import hydroeval as he
                    # NSE = he.evaluator(he.nse, Qsim_stat, Qobs_stat)[0]
                    # NSElog = he.evaluator(he.nse, Qsim_stat, Qobs_stat, transform='log')[0]
                    # RMSE = np.sqrt(np.nanmean((Qobs_stat.values-Qsim_stat.values)**2)) / (Qobs_stat.max()-Qobs_stat.min())
                    # KGE = he.evaluator(he.kge, Qsim_stat, Qobs_stat)[0][0]
                    # print(model_name.upper())
                    # print('NSE', round(NSE,2))
                    # print('NSElog', round(NSElog,2))
                    # print('RMSE', round(RMSE,2))
                    # print('KGE', round(KGE,2))
                    
                    # model_name = iD_explo+'_'+str('model')+str(id_mod_val)+'_'+\
                    #              str(round(str_cond_decay,4))+'-'+str(round(str_bottom,4))+'-'+str("{:.2e}".format(koptim_val/24/3600))+'_'+\
                    #              str(ip)+'_'+\
                    #              str(round(str_poro_decay,4))+'-'+str(round(poro_val*100,2))
                    
                    df.loc[i,'model_name'] = model_name
                    
                    df.loc[i,'id_explo'] = iD_explo
                    df.loc[i, 'id_mod'] = id_mod_val
                    
                    df.loc[i,'aK'] = float(model_name.split('_')[2].split('-')[0])
                    df.loc[i,'bottom'] = float(model_name.split('_')[2].split('-')[1])
                    
                    try:
                        df.loc[i,'K'] = float(['-'.join(model_name.split('_')[2].split('-')[-2:])][0])
                    except:
                        pass
                    
                    # df.loc[i,'id_eO'] = float(model_name.split('_')[3][0])
                    
                    df.loc[i,'aO'] = float(model_name.split('_')[3].split('-')[0])
                    df.loc[i,'O'] = float(model_name.split('_')[3].split('-')[1])
                    
                    # df.loc[i,'NSE'] = float(NSE)
                    # df.loc[i,'NSElog'] = float(NSElog)
                    # df.loc[i,'RMSE'] = float(RMSE)
                    # df.loc[i,'KGE'] = float(KGE)
                    
                    Q10_obs = Qobs_stat.quantile(0.10)
                    Q50_obs = Qobs_stat.quantile(0.50)
                    Q90_obs = Qobs_stat.quantile(0.90)
                    Q10_sim = Qsim_stat.quantile(0.10)
                    Q50_sim = Qsim_stat.quantile(0.50)
                    Q90_sim = Qsim_stat.quantile(0.90)
                    
                    df.loc[i,'OWN_Q10'] = float(((Q10_sim - Q10_obs)**2) / (Q10_obs**2))
                    df.loc[i,'OWN_Q50'] = float(((Q50_sim - Q50_obs)**2) / (Q50_obs**2))
                    df.loc[i,'OWN_Q90'] = float(((Q90_sim - Q90_obs)**2) / (Q90_obs**2))
                    
                    df.loc[i,'OWN'] = ( df.loc[i,'OWN_Q10'] + df.loc[i,'OWN_Q50'] + df.loc[i,'OWN_Q90'] ) / 3
            
                    d = pd.DataFrame()
                    d = Qmod.to_frame()
                    d.columns = ['Q']
                    d['historic'] = d['Q']
                    d[sce] = d['Q']
                    
                    if sce == 'historic':
                        d[sce][(d.index.year)>=2005] = np.nan
                        
                    else:
                        d[sce][(d.index.year)<2005] = np.nan

                    cond = select_period(d['Q'], 1980,2004).quantile(0.1)
                    
                    if sce == 'historic':
                        d = select_period(d, 1980, 2004)
                    else:
                        d = select_period(d, 2004, 2099)
                        
                    d['diff'] = d['Q'].diff()
                    
                    # print(cond)
                    
                    years = d.index.year.unique()
                    
                    counts = []
                    for i, year in enumerate(years):
                    
                        each = d[d.index.year==year]
                        
                        count = ((each[sce] <= cond)).astype(int).sum(axis=0)
                        
                        counts.append(count)
                    
                    df_rec['val'] = counts
            
                    df_rec.index = years
                    
                    df_rec = df_rec
                    
                    print('    ',sce,df_rec['val'].mean().round(1))
                    
                    step = 'pre'
                    ax.fill_between(df_rec.index, 0, df_rec['val'],
                                    interpolate=False,  color=dict_scecol[sce], alpha=0.1,
                                    step=step)

                    ax.step(df_rec.index, df_rec['val'], color=dict_scecol[sce], lw=2)
                    ax.set_title(pzone, fontsize=8)
                    
                    ax.set_ylim(0,12)
                    
                    ax.set_xlim(1980,2100)
                    ax.set_xticks(np.arange(1980, 2100+1, 10))
                    ax.set_xticklabels(np.arange(1980, 2100+1, 10))
                    
                    ax.xaxis.set_minor_locator(MultipleLocator(1))
                    
                    ax.axhline(df_rec['val'].mean(), color=dict_scecol[sce], ls='--', lw=1)
                    
                    plt.tight_layout()
                    
                   
                    """
                    # fig, ax = plt.subplots(1,1, figsize=(10,4))
                    fig, ax = plt.subplots(1,1, figsize=(9,4))
                    
                    ax.set_title(l, fontsize=6)
                    
                    import matplotlib
                    normaliz = plt.Normalize(df_rec.median().min(), df_rec.median().max())
                    norm = matplotlib.colors.Normalize(vmin=0, vmax=100)
                    # if sce == 'RCP2.6':
                    #     to_norm = df_rec.median()
                    colors = plt.cm.jet(norm(df_rec.median()))
                    # colors = plt.cm.jet(norm([60] * len(df_rec.columns)))
                    # colors = plt.cm.jet(norm(to_norm))
                    # colors = plt.cm.jet(norm((df_rec.median()*0)+60))
                    
                    
                    medianprops = dict(linestyle='-', linewidth=1, color='black')
                    meanpointprops = dict(markersize=0, marker='o', markeredgecolor='black',
                                          markerfacecolor='k', linestyle='-')
                    
                    ax.vlines(x=years, 
                                ymin=df_rec.quantile(0.75), 
                                ymax=df_rec.quantile(0.95), color='k', zorder=2)
                    ax.vlines(x=years, 
                                ymin=df_rec.quantile(0.05), 
                                ymax=df_rec.quantile(0.25), color='k', zorder=2)
                    
                    # boxprops = dict(linestyle='-', linewidth=1, color='k',
                    #                 facecolor='cyan', alpha=0.5)
                    # bp = ax.boxplot(df_rec, widths=0.75,
                    #                 positions=years,
                    #                   whis=False, showfliers=False, showmeans=False, 
                    #                   medianprops=medianprops, meanprops=meanpointprops,
                    #                   patch_artist=True, boxprops=boxprops)
                    
                    for i in range(len(years)):
                        # print(i)
                        boxprops = dict(linestyle='-', linewidth=1, color='k',
                                        facecolor=colors[i], 
                                        alpha=0.5)
                        bp = ax.boxplot(df_rec.iloc[:,i], widths=0.75,
                                        positions=[df_rec.columns[i]],
                                          whis=False, showfliers=False, showmeans=False, 
                                          medianprops=medianprops, meanprops=meanpointprops,
                                          patch_artist=True, boxprops=boxprops)
                    
                    ax.plot(years, df_rec.mean(), marker='o', mec='k', ms=1.5, lw=0,
                            mfc='k', mew=1,
                            color='k', zorder=1000)
                      
                    for element in bp['whiskers']:
                        element.set_color('k')
                        element.set_linestyle('-')
                    # for patch in bp['boxes']:
                    #     patch.set(facecolor='r')    
                    ax.set_xticks(np.arange(1980, 2100+1, 10))
                    ax.set_xticklabels(np.arange(1980, 2100+1, 10))
                    
                    # ax.get_xaxis().set_visible(False)
                    # ax.set_yscale('log')
                    
                    ax.set_ylim(0, 30)
                    # ax.set_yticks(np.arange(0, 180+1, 30))
                    
                    ax.set_xlim(1974,2100)
                    ax.tick_params(axis='x', which='minor')
                    
                    from matplotlib.ticker import (MultipleLocator)
                    ax.xaxis.set_minor_locator(MultipleLocator(1))
                    
                    ax.set_axisbelow(True)
                    # ax.grid(zorder=-1000)
                    ax.xaxis.grid(color='gray', alpha=0.2, zorder=-20)
                    ax.yaxis.grid(color='gray', alpha=0.2, zorder=-20, which='both')
                    
                    # ax.set_title(var+' - '+mod)
                    # ax.set_xlim(pd.to_datetime('1974'), pd.to_datetime('2100'))
                    
                    plt.tight_layout()
                    """
                    
                    fig.savefig('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_figures_paper/_v0/c_sup_models/'+
                                'EVOL_MONTHS_DRY_Q10-'+pzone+'.png',
                                            bbox_inches='tight')

#%% ---- PLOTS PROJECTIONS - KEEPIF

#%% LENGHTS TIME - FROM PHY

col_list = ['k','dodgerblue','darkorange','red']
sce_list = ['historic','RCP26','RCP45','RCP85']
# sce_list = ['RCP2.6','RCP8.5']
dict_scecol = dict(zip(sce_list, col_list))# sce_list = ['RCP85']

stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
color = 'k'
BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=dem_path, 
                              out_path=out_path,
                              load=True)
mask = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
mask_grenou = imageio.imread(stable_folder+'subbasin/subbasin_Qgrenou/'+'watershed_dem.tif')
dem_box = imageio.imread(stable_folder+'geographic/'+'watershed_box_buff_dem.tif')
area = BV.geographic.area
area = int(round(area))

import imageio
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False
wbt.downslope_flowpath_length(
    stable_folder+'geographic/'+'watershed_direc.tif', 
    stable_folder+'geographic/'+'downslope_flowpath_length.tif', 
    watersheds=None, 
    weights=None, 
    esri_pntr=False)
down = imageio.imread(stable_folder+'geographic/'+'downslope_flowpath_length.tif')
toolbox.export_tif(stable_folder+'geographic/'+'watershed_box_buff_dem.tif',
                   down, -99999, stable_folder+'geographic/'+'downslope_flowpath_length_box.tif')
down = imageio.imread(stable_folder+'geographic/'+'downslope_flowpath_length_box.tif')

# fig, ax = plt.subplots(1, 1, figsize=(6,6))
# fig, ax = plt.subplots(1,1, figsize=(4.5,4))
# fig, ax = plt.subplots(1,1, figsize=(6,5))

# for ivar, var in enumerate(['total_areas', 'prop_ratio',
#                             'perenn_areas','intermit_areas'][:]):
for ivar, var in enumerate(['intermit_areas'][:]):
# for ivar, var in enumerate(['prop_ratio'][:]):
# for ivar, var in enumerate(['L_phy'][:]):
# for ivar, var in enumerate(['new_ratio'][:]):

    if  ivar == 1:
        figs, axs = plt.subplots(4,1, figsize=(4.5,13.5), sharex=True, sharey=False)
    else:
        figs, axs = plt.subplots(4,1, figsize=(4.5,13.5), sharex=True, sharey=False)
    axs = axs.ravel()
    
    compt = 1
    
    for ic, sce in enumerate(sce_list):
        years = pd.date_range(start='01/01/1975', end='31/12/2099', freq='M').year.unique()
        # df_yearly = pd.DataFrame(np.nan, index=Smod.index, columns=years)
        # df_pi = pd.DataFrame(np.nan, index=range(len(mask.flatten())), columns=years)
        
        print(sce)
        
        for id_mod_val in list_id_mod[:]:
            
            if sce == 'historic':
                h5file = BV.simulations_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)+'_ALL_'+'RCP85'
            else:
                h5file = BV.simulations_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)+'_ALL_'+sce
            d = dd.io.load(h5file)
            list_model_name = d['list_model_name'][:]
            list_model_success = d['list_model_success'][:]
            list_model_modflow = d['list_model_modflow'][:]
            
            for model_name, model_success, model_modflow in zip(list_model_name[:],
                                                                list_model_success[:],
                                                                list_model_modflow[:]):
                
                
                
                Smod = pd.read_csv(BV.simulations_folder+'/'+model_name+'/_postprocess/_timeseries/_simulated_timeseries.csv', sep=';',
                                    index_col='date', parse_dates=True)
                
                for pidx, pzone in enumerate(['subbasin_Qlasset','subbasin_Qbreton','subbasin_Qgrenou','subbasin_Qbombee']):
                
                    print(pzone)    
                    ax = axs[pidx]
                    # subbasin_Qlasset
                    # subbasin_Qbreton
                    # subbasin_Qgrenou
                    # subbasin_Qbombee
                    Smod = pd.read_csv(BV.simulations_folder+'/'+model_name+'/_subbasins/'+pzone+'/_simulated_timeseries.csv', sep=';',
                                        index_col='date', parse_dates=True)
                        
                    # Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
                    Smod['prop_ratio'] = Smod.intermit_areas / Smod.total_areas
                    Smod['new_ratio'] = Smod.perenn_areas
                    Smod['recharge'] = Smod['recharge'] #* 1000 * 30
                    Smod['outflow_drain'] =  ( Smod['outflow_drain'] )  #+ Smod['runoff'] ) # * (area * 1e6)
                    Smod['groundwater_storage'] = Smod['groundwater_storage']
                    per = 1
                    Smod['dQ'] = Smod['outflow_drain'].diff()
                    Smod['dGWsat'] = Smod['saturated_storage'].diff()
                    Smod['dGW'] = Smod['groundwater_storage'].diff()
                    Smod['t'] = abs((Smod['groundwater_storage'].diff(periods=per) / (Smod['outflow_drain']* (area * 1e6)).diff(periods=per)))
                    # Smod['t'] = ((Smod['groundwater_storage'].diff(periods=per) / (Smod['outflow_drain']* (area * 1e6)).diff(periods=per)))
                    # Smod['t'][Smod['t']>1000] = np.nan
                    # Smod['t'] = abs((Smod['saturated_storage'].diff(periods=per) / (Smod['outflow_drain']* (area * 1e6)).diff(periods=per)))
                    
                    # plt.plot(Smod['groundwater_storage'].diff())
                    # plt.plot(Smod['saturated_storage'].diff())
                    
                    E = float(model_name.split('_')[-2].split('-')[0])
                    wt_ep = E - Smod['watertable_depth']
                    tsat = wt_ep
                    # tsat = 40
                    Sy = float(model_name.split('_')[-2].split('-')[1]) / 100
                    K = float(model_name.split('_')[-2].split('-')[2]+('-'+model_name.split('_')[-2].split('-')[3])) * 3600 * 24
                    
                    Smod['L_phy'] = np.sqrt( (Smod['t']*K*tsat) / Sy )
                    
                    if sce == 'historic':
                        Smod = select_period(Smod, 1980, 2010)
                    else:
                        Smod = select_period(Smod, 2070, 2100)
                    
                    x = Smod['recharge'] * 1000 * 7
                    x = Smod['L_phy']
                    # x = Smod['outflow_drain'] * 1000 * 7
                    # x = Smod['t']
                    y = Smod[var]
                    # y = Smod['prop_ratio']
                    c = Smod.index.month
                    wy = pd.Series(x.index.month).replace([10,11,12,1,2,3,4,5,6,7,8,9],
                                                            [1,2,3,4,5,6,7,8,9,10,11,12])
                    xi = x.groupby([lambda x: x.month]).mean()
                    yi = y.groupby([lambda y: y.month]).mean()
                    
                    xiq25 = x.groupby([lambda x: x.month]).quantile(0.25)
                    yiq25 = y.groupby([lambda y: y.month]).quantile(0.25)
                    
                    xiq75 = x.groupby([lambda x: x.month]).quantile(0.75)
                    yiq75 = y.groupby([lambda y: y.month]).quantile(0.75)
                    
                    # xi = x.groupby([lambda x: x.month]).median()
                    # yi = y.groupby([lambda y: y.month]).median()
                    # cmapping = mpl.colors.ListedColormap(dict_c[watershed_name])
                    # cmapping = dict_cmap[watershed_name]
                    
                    # cmap = plt.cm.YlGnBu
                    if sce == 'historic':
                        cmap = 'Greys'
                    if sce == 'RCP26':
                        cmap = 'Blues'
                    if sce == 'RCP45':
                        cmap = 'Oranges'
                    if sce == 'RCP85':
                        cmap = 'Reds'
                    # cmap = parula_map
                    # cmaplist = [cmap(i) for i in range(cmap.N)]
                    # if watershed_name == 'Canut':
                    # cmaplist = ['limegreen','greenyellow']
                    # if watershed_name == 'Nancon':
                    #     cmaplist = ['tomato', 'lightsalmon']
                    # cmaplist[0] = (.5, .5, .5, 1.0)
                    # cmap = mpl.colors.LinearSegmentedColormap.from_list(
                    #     'Custom cmap', cmaplist, cmap.N)
                    
                    # scat = ax.scatter(x, y, c=wy, cmap=cmap, marker="o", 
                    #                   s=1, vmin=1, vmax=12, alpha=0.75, ec='none', zorder=-1)
                    xiline = xi.append(xi.iloc[[0]])
                    xiline.index = np.arange(1,14,1)
                    yiline = yi.append(yi.iloc[[0]])
                    yiline.index = np.arange(1,14,1)
                    
                    xilineq25 = xiq25.append(xiq25.iloc[[0]])
                    xilineq25.index = np.arange(1,14,1)
                    yilineq25 = yiq25.append(yiq25.iloc[[0]])
                    yilineq25.index = np.arange(1,14,1)                    
                    
                    xilineq75 = xiq75.append(xiq75.iloc[[0]])
                    xilineq75.index = np.arange(1,14,1)
                    yilineq75 = yiq75.append(yiq75.iloc[[0]])
                    yilineq75.index = np.arange(1,14,1)                  
                    
                    # ax.fill_between(xiline, yilineq25, yilineq75, lw=0,
                    #                  interpolate=False,
                    #                 color=dict_scecol[sce], alpha=0.25)
                    
                    # ax.plot(xi, yiq25, linestyle = '-', lw=0.5, 
                    #         color=dict_scecol[sce], zorder=0)
                    # ax.plot(xi, yiq75, linestyle = '-', lw=0.5, 
                    #         color=dict_scecol[sce], zorder=0)
                    
                    ax.plot(xiline, yiline, linestyle = '-', lw=2, 
                            color=dict_scecol[sce], zorder=compt)
                    wyi = np.arange(1,12+1,1)
                    # compt = 1
                    for k in wyi:
                        ax.plot(xi[k], yi[k], marker="o", lw=1, markersize=10.5, 
                                   markeredgecolor=dict_scecol[sce], 
                                   markerfacecolor='white', markeredgewidth=1.2,
                                   linestyle = 'None', zorder=compt)
                        ax.annotate(k,(xi[k],yi[k]), family='sans-serif', fontsize=7, 
                                color=dict_scecol[sce], weight="bold", ha='center', va='center',
                                zorder=compt)
                        compt+=1
                    xe = pd.DataFrame()
                    xe['q25'] = (x.groupby(x.index.month).quantile(0.25))
                    xe['q75'] = (x.groupby(x.index.month).quantile(0.75))        
                    ye = pd.DataFrame()
                    ye['q25'] = (y.groupby(y.index.month).quantile(0.25))
                    ye['q75'] = (y.groupby(y.index.month).quantile(0.75))                
                    ax.errorbar(xi, yi,
                                  yerr=np.abs(np.vstack([yi-ye.q25, ye.q75-yi])),
                                  # xerr=np.abs(np.vstack([xi-xe.q25, xe.q75-xi])),
                                  ecolor = dict_scecol[sce], fmt = 'none', capsize = 1,
                                  elinewidth=0.5, 
                                  capthick=0, zorder=-1000)               
                    # ax.errorbar(xi, yi,
                    #               yerr=np.abs(np.vstack([yi-ye.q25, yi+ye.q25])),
                    #               xerr=np.abs(np.vstack([xi-xe.q25, xi+xe.q25])),
                    #               ecolor = dict_scecol[sce], fmt = 'none', capsize = 1, elinewidth=0.5, 
                    #               capthick=0.5, zorder=-1000)  
                    
                    ax.grid(alpha=0.5)
                    
                    # ax.axvline(x.median(), c=dict_c[watershed_name], ls='--')
                    # ax.axhline(y.median(), c=dict_c[watershed_name], ls='--')
                    
                    ax.set_xscale('log')
                    # ax.set_yscale('log')
                    
                    if pidx==3:
                        ax.set_xlabel('R [mm/week]')
                    if ivar ==0:
                        ax.set_ylabel('$A_{sat}$ [%]')
                    else:
                        ax.set_ylabel('$A_{int}$ / $A_{sat}$ [-]')
                    
                    ax.set_xlim(0.7,100)
                    # ax.set_ylim(0,25)
                
    figs.tight_layout()
    
    # figs.savefig('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_figures_paper/_v0/06_fig_hyster/'+
    #             'HYSTER_'+var+'_FROM PHY'+'.png',
    #                         bbox_inches='tight')


#%% COMPUTE WT LENGTH

col_list = ['dodgerblue','darkorange','red']
sce_list = ['RCP26','RCP45','RCP85']
# sce_list = ['RCP2.6','RCP8.5']
dict_scecol = dict(zip(sce_list, col_list))# sce_list = ['RCP85']

stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
color = 'k'
BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=dem_path, 
                              out_path=out_path,
                              load=True)

mask = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
mask_lasset = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
mask_grenou = imageio.imread(stable_folder+'subbasin/subbasin_Qgrenou/'+'watershed_dem.tif')
mask_bombee = imageio.imread(stable_folder+'subbasin/subbasin_Qbombee/'+'watershed_dem.tif')
mask_breton = imageio.imread(stable_folder+'subbasin/subbasin_Qbreton/'+'watershed_dem.tif')
dem_box = imageio.imread(stable_folder+'geographic/'+'watershed_box_buff_dem.tif')
area = BV.geographic.area
area = int(round(area))

import imageio
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False
wbt.downslope_flowpath_length(
    stable_folder+'geographic/'+'watershed_direc.tif', 
    stable_folder+'geographic/'+'downslope_flowpath_length.tif', 
    watersheds=None, 
    weights=None, 
    esri_pntr=False)
down = imageio.imread(stable_folder+'geographic/'+'downslope_flowpath_length.tif')
toolbox.export_tif(stable_folder+'geographic/'+'watershed_box_buff_dem.tif',
                   down, -99999, stable_folder+'geographic/'+'downslope_flowpath_length_box.tif')
down = imageio.imread(stable_folder+'geographic/'+'downslope_flowpath_length_box.tif')

# fig, ax = plt.subplots(1, 1, figsize=(6,6))
# fig, ax = plt.subplots(1,1, figsize=(5.5,3.5))
# fig, ax = plt.subplots(1,1, figsize=(6,5))

for ivar, var in enumerate(['t'][:]):
    
    # if  ivar == 1:
    #     figs, axs = plt.subplots(4,1, figsize=(4.5,13.5), sharex=True, sharey=False)
    # else:
    # figs, axs = plt.subplots(4,1, figsize=(4.5,13.5), sharex=True, sharey=False)
    # axs = axs.ravel()
    
    compt = 1
    
    for ic, sce in enumerate(sce_list):
        years = pd.date_range(start='01/01/1975', end='31/12/2099', freq='M').year.unique()
        # df_yearly = pd.DataFrame(np.nan, index=Smod.index, columns=years)
        # df_pi = pd.DataFrame(np.nan, index=range(len(mask.flatten())), columns=years)
        
        print(sce)
        
        for id_mod_val in [6]:
            
            if sce == 'historic':
                h5file = BV.simulations_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)+'_ALL_'+'RCP85'
            else:
                h5file = BV.simulations_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)+'_ALL_'+sce
            d = dd.io.load(h5file)
            list_model_name = d['list_model_name'][:]
            list_model_success = d['list_model_success'][:]
            list_model_modflow = d['list_model_modflow'][:]
            
            for model_name, model_success, model_modflow in zip(list_model_name[:],
                                                                list_model_success[:],
                                                                list_model_modflow[:]):
                
                Smod = pd.read_csv(BV.simulations_folder+'/'+model_name+'/_postprocess/_timeseries/_simulated_timeseries.csv', sep=';',
                                    index_col='date', parse_dates=True)
                
                # for pidx, pzone in enumerate(['subbasin_Qlasset','subbasin_Qbreton','subbasin_Qgrenou','subbasin_Qbombee']):
                
                    # print(pzone)    
                    # ax = axs[pidx]
               
                    # # subbasin_Qbreton
                    # # subbasin_Qgrenou
                    # # subbasin_Qbombee
                    # Smod = pd.read_csv(BV.simulations_folder+'/'+model_name+'/_subbasins/'+pzone+'/_simulated_timeseries.csv', sep=';',
                    #                     index_col='date', parse_dates=True)
                        
                # Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
                Smod['prop_ratio'] = Smod.intermit_areas / Smod.total_areas
                Smod['recharge'] = Smod['recharge'] #* 1000 * 30
                Smod['outflow_drain'] =  ( Smod['outflow_drain'] )  #+ Smod['runoff'] ) # * (area * 1e6)
                Smod['groundwater_storage'] = Smod['groundwater_storage']
                per = 1
                Smod['dQ'] = (Smod['outflow_drain']*(area * 1e6)).diff(periods=per)
                Smod['dGW'] = Smod['groundwater_storage'].diff(periods=per)
                Smod['t'] = abs(Smod['dGW'] / Smod['dQ'])
                # Smod['t'] = ((Smod['groundwater_storage'].diff(periods=per) / (Smod['outflow_drain']* (area * 1e6)).diff(periods=per)))
                Smod['t'][Smod['t']>1000] = np.nan
                
                Smod_path_bis = BV.simulations_folder+'/'+model_name+'/_postprocess/_timeseries/_simulated_timeseries_bis.csv'
                Smod.to_csv(Smod_path_bis, sep=';')
                Smod = pd.read_csv(Smod_path_bis, sep=';', index_col=0, parse_dates=True)        
                # if sce == 'historic':
                #     Smod = select_period(Smod, 1980,2010)
                # else:
                #     Smod = select_period(Smod, 2070, 2100)
                
                # for pidx, pzone in enumerate(['subbasin_Qlasset','subbasin_Qbreton','subbasin_Qgrenou','subbasin_Qbombee']):

                ############
                pzone1 = 'subbasin_Qlasset'
                # Smod1 = pd.read_csv(BV.simulations_folder+'/'+model_name+'/_subbasins/'+pzone1+'/_simulated_timeseries.csv', sep=';',
                #                     index_col='date', parse_dates=True)
                Smod1 = pd.read_csv(BV.simulations_folder+'/'+model_name+'/_postprocess/_timeseries/_simulated_timeseries.csv', sep=';',
                                    index_col='date', parse_dates=True)
                Smod_path_bis1 = BV.simulations_folder+'/'+model_name+'/_subbasins/'+pzone1+'/_simulated_timeseries_bis.csv'
                Smod1.to_csv(Smod_path_bis1, sep=';')
                Smod1 = pd.read_csv(Smod_path_bis1, sep=';', index_col=0, parse_dates=True)        

                pzone2 = 'subbasin_Qbreton'
                Smod2 = pd.read_csv(BV.simulations_folder+'/'+model_name+'/_subbasins/'+pzone2+'/_simulated_timeseries.csv', sep=';',
                                    index_col='date', parse_dates=True)
                Smod_path_bis2 = BV.simulations_folder+'/'+model_name+'/_subbasins/'+pzone2+'/_simulated_timeseries_bis.csv'
                Smod2.to_csv(Smod_path_bis2, sep=';')
                Smod2 = pd.read_csv(Smod_path_bis2, sep=';', index_col=0, parse_dates=True)        
                
                pzone3 = 'subbasin_Qgrenou'
                Smod3 = pd.read_csv(BV.simulations_folder+'/'+model_name+'/_subbasins/'+pzone3+'/_simulated_timeseries.csv', sep=';',
                                    index_col='date', parse_dates=True)
                Smod_path_bis3 = BV.simulations_folder+'/'+model_name+'/_subbasins/'+pzone3+'/_simulated_timeseries_bis.csv'
                Smod3.to_csv(Smod_path_bis3, sep=';')
                Smod3 = pd.read_csv(Smod_path_bis3, sep=';', index_col=0, parse_dates=True)        
                
                pzone4 = 'subbasin_Qbombee'
                Smod4 = pd.read_csv(BV.simulations_folder+'/'+model_name+'/_subbasins/'+pzone4+'/_simulated_timeseries.csv', sep=';',
                                    index_col='date', parse_dates=True)
                Smod_path_bis4 = BV.simulations_folder+'/'+model_name+'/_subbasins/'+pzone4+'/_simulated_timeseries_bis.csv'
                Smod4.to_csv(Smod_path_bis4, sep=';')
                Smod4 = pd.read_csv(Smod_path_bis4, sep=';', index_col=0, parse_dates=True)        
                ############
                
                wt_npy = np.load(os.path.join(BV.simulations_folder+'/'+model_name+'/_postprocess/','watertable_elevation.npy'), allow_pickle=True).item()
                # wt_path = os.path.join(simul, '_watershed/_tifs/','watertable_elevation_t(0).tif')
                simul = BV.simulations_folder+'/'+model_name+'/' 
               
                for i in range(len(wt_npy))[:]:
                    print(i+1, len(wt_npy))
                                        
                    wt_path = os.path.join(simul, '_postprocess/_rasters/','watertable_elevation_t('+str(i)+').tif')
                    if not os.path.exists(wt_path):
                        toolbox.export_tif(BV.geographic.watershed_dem, wt_npy[i], -9999, 
                                            wt_path)
                    
                    wt_fill_path = os.path.join(simul, '_postprocess/_rasters/','watertable_fill_elevation_t('+str(i)+').tif')
                    if not os.path.exists(wt_fill_path):
                        wbt.fill_depressions(wt_path, wt_fill_path)

                    # DEM down outlet
                    d_dem_outlet = os.path.join(simul, '_postprocess/_rasters/','downslope_dem_outlet_t('+str(i)+').tif')
                    if not os.path.exists(d_dem_outlet):
                        output = os.path.join(simul, '_postprocess/_rasters/','d8pointer_dem_outlet_t(x).tif')
                        wbt.d8_pointer(
                                BV.geographic.watershed_buff_fill, 
                                output)
                        wbt.downslope_flowpath_length(
                            output, 
                            d_dem_outlet)
                    
                    # DEM down stream
                    d_dem_stream = os.path.join(simul, '_postprocess/_rasters/','downslope_dem_stream_t('+str(i)+').tif')
                    if not os.path.exists(d_dem_stream):
                        streams = os.path.join(simul, '_postprocess/_rasters/','accumulation_flux_t('+str(i)+').tif')                
                        wbt.downslope_distance_to_stream(
                                BV.geographic.watershed_buff_fill, 
                                streams, 
                                d_dem_stream, 
                                dinf=False, 
                            )
                    
                    # WR down outlet
                    d_wt_outlet = os.path.join(simul, '_postprocess/_rasters/','downslope_wt_outlet_t('+str(i)+').tif')
                    if not os.path.exists(d_wt_outlet):
                        output = os.path.join(simul, '_postprocess/_rasters/','d8pointer_wt_outlet_t(x).tif')
                        wbt.d8_pointer(
                                wt_path, 
                                output)
                        wbt.downslope_flowpath_length(
                            output, 
                            d_wt_outlet)
                    
                    # WT down stream
                    d_wt_stream = os.path.join(simul, '_postprocess/_rasters/','downslope_wt_stream_t('+str(i)+').tif')
                    if not os.path.exists(d_wt_stream):
                        streams = os.path.join(simul, '_postprocess/_rasters/','accumulation_flux_t('+str(i)+').tif')                
                        wbt.downslope_distance_to_stream(
                                wt_path, 
                                streams, 
                                d_wt_stream, 
                                dinf=False, 
                            )
            
                    # WT fill down stream
                    d_wt_fill_stream = os.path.join(simul, '_postprocess/_rasters/','downslope_wt_fill_stream_t('+str(i)+').tif')
                    if not os.path.exists(d_wt_fill_stream):
                        streams = os.path.join(simul, '_postprocess/_rasters/','accumulation_flux_t('+str(i)+').tif')                
                        wbt.downslope_distance_to_stream(
                                wt_fill_path, 
                                streams, 
                                d_wt_fill_stream, 
                                dinf=False, 
                            )
                    
                    dem = imageio.imread(BV.geographic.watershed_dem)
                    
                    """
                    # DEM outlet
                    flow_dem = imageio.imread(d_dem_outlet)
                    flow_dem[flow_dem<0] = np.nan
                    flow_dem = np.nan_to_num(flow_dem, nan=np.nan, posinf=np.nan)
                    mean_flow_dem = np.nanmean(np.ma.masked_where(dem < 0, flow_dem))
                    median_flow_dem = np.nanmedian(np.ma.masked_where(dem[~np.isnan(flow_dem)] < 0, flow_dem[~np.isnan(flow_dem)]))
                    Smod.loc[Smod.index[i], 'L_dem_mean_out'] = mean_flow_dem
                    Smod.loc[Smod.index[i], 'L_dem_median_out'] = median_flow_dem
                    
                    # DEM stream
                    flow_dem = imageio.imread(d_dem_stream)
                    flow_dem[flow_dem<0] = np.nan
                    mean_flow_dem = np.nanmean(np.ma.masked_where(dem < 0, flow_dem))
                    median_flow_dem = np.nanmedian(np.ma.masked_where(dem < 0, flow_dem))
                    Smod.loc[Smod.index[i], 'L_dem_mean_str'] = mean_flow_dem
                    Smod.loc[Smod.index[i], 'L_dem_median_str'] = median_flow_dem
                    
                    # Rectangle technique complete
                    # l_stream = complete.length.sum()
                    # mean_rect_dem = (area * 1e6) / (2 * l_stream)           
                    # Smod.loc[Smod.index[i], 'L_dem_complete'] = mean_rect_dem
                    
                    # WT outlet
                    flow_wt = imageio.imread(d_wt_outlet)
                    flow_wt[flow_wt<0] = np.nan
                    mean_flow_wt = np.nanmean(np.ma.masked_where(dem < 0, flow_wt))
                    median_flow_wt = np.nanmedian(np.ma.masked_where(dem < 0, flow_wt))
                    Smod.loc[Smod.index[i], 'L_wt_mean_out'] = mean_flow_wt
                    Smod.loc[Smod.index[i], 'L_wt_median_out'] = median_flow_wt
                    """
                    
                    # WT stream
                    flow_wt = imageio.imread(d_wt_stream)
                    flow_wt[flow_wt<0] = np.nan
                    mean_flow_wt = np.nanmean(np.ma.masked_where(dem < 0, flow_wt))
                    median_flow_wt = np.nanmedian(np.ma.masked_where(dem < 0, flow_wt))
                    Smod.loc[Smod.index[i], 'L_wt_mean_str'] = mean_flow_wt
                    Smod.loc[Smod.index[i], 'L_wt_median_str'] = median_flow_wt
                    
                    """
                    # WT stream fill
                    try:
                        flow_wt = imageio.imread(d_wt_fill_stream)
                        flow_wt[flow_wt<0] = np.nan
                        mean_flow_wt = np.nanmean(np.ma.masked_where(dem < 0, flow_wt))
                        median_flow_wt = np.nanmedian(np.ma.masked_where(dem < 0, flow_wt))
                        Smod.loc[Smod.index[i], 'L_wt_mean_str'] = mean_flow_wt
                        Smod.loc[Smod.index[i], 'L_wt_fill_median_str'] = median_flow_wt
                    except:
                        Smod.loc[Smod.index[i], 'L_wt_fill_median_str'] = np.nan
                        pass
                    """
                        
                    # WT tau
                    dem_data = imageio.imread(BV.geographic.watershed_dem)
                    wt_elev = imageio.imread(wt_path)
                    E = float(model_name.split('_')[-2].split('-')[0])
                    wt_ep = ( wt_elev - (dem_data-E) )
                    tsat = np.nanmean(np.ma.masked_where(dem_data < 0, wt_ep))
                    Sy = float(model_name.split('_')[-2].split('-')[1])
                    K = float(model_name.split('_')[-2].split('-')[2]+('-'+model_name.split('_')[-2].split('-')[3]))
                    tau = ((median_flow_wt**2) * (Sy/100)) / ((K * 3600 * 24) * tsat)                
                    Smod.loc[Smod.index[i], 'tau_L_wt_median_str'] = tau
                    
                    d_wt_stream = os.path.join(simul, '_postprocess/_rasters/','downslope_wt_stream_t('+str(i)+').tif')
                    flow_wt = imageio.imread(d_wt_stream)
                    # for pidx, pzone in enumerate(['subbasin_Qlasset','subbasin_Qbreton','subbasin_Qgrenou','subbasin_Qbombee']):
                    mean_flow_wt = np.nanmean(np.ma.masked_where(mask_lasset < 0, flow_wt))
                    median_flow_wt = flow_wt.copy()
                    median_flow_wt[mask_lasset < 0] = np.nan
                    median_flow_wt = np.nanmedian(median_flow_wt)
                    Smod1.loc[Smod1.index[i], 'L_wt_mean_str'] = mean_flow_wt
                    Smod1.loc[Smod1.index[i], 'L_wt_median_str'] = median_flow_wt
                    mean_flow_wt = np.nanmean(np.ma.masked_where(mask_breton < 0, flow_wt))
                    median_flow_wt = flow_wt.copy()
                    median_flow_wt[mask_breton < 0] = np.nan
                    median_flow_wt = np.nanmedian(median_flow_wt)
                    Smod2.loc[Smod2.index[i], 'L_wt_mean_str'] = mean_flow_wt
                    Smod2.loc[Smod2.index[i], 'L_wt_median_str'] = median_flow_wt
                    mean_flow_wt = np.nanmean(np.ma.masked_where(mask_grenou < 0, flow_wt))
                    median_flow_wt = flow_wt.copy()
                    median_flow_wt[mask_grenou < 0] = np.nan
                    median_flow_wt = np.nanmedian(median_flow_wt)
                    Smod3.loc[Smod3.index[i], 'L_wt_mean_str'] = mean_flow_wt
                    Smod3.loc[Smod4.index[i], 'L_wt_median_str'] = median_flow_wt
                    mean_flow_wt = np.nanmean(np.ma.masked_where(mask_bombee < 0, flow_wt))
                    median_flow_wt = flow_wt.copy()
                    median_flow_wt[mask_bombee < 0] = np.nan
                    median_flow_wt = np.nanmedian(median_flow_wt)
                    Smod4.loc[Smod4.index[i], 'L_wt_mean_str'] = mean_flow_wt
                    Smod4.loc[Smod4.index[i], 'L_wt_median_str'] = median_flow_wt
                    
                # ax.plot(Smod['tau'], Smod['seepage_areas'], marker='o', color=dict_c[watershed_name], lw=0)
              
        Smod.to_csv(Smod_path_bis, sep=';')
        
        Smod1.to_csv(Smod_path_bis1, sep=';')
        Smod2.to_csv(Smod_path_bis2, sep=';')
        Smod3.to_csv(Smod_path_bis3, sep=';')
        Smod4.to_csv(Smod_path_bis4, sep=';')

    # plt.plot(Smod['recharge'],Smod['tau'])
    # plt.plot()

    # fig, ax = plt.subplots(1,1, figsize=(3,3))
    # ax.scatter(Smod['L_dem_median_str'],Smod['L_wt_median_str'],
    #            c=Smod.index.month, ec='none')
    # ax.plot((ax.get_xlim()[0], ax.get_xlim()[1]), (ax.get_ylim()[0], ax.get_ylim()[1]), c='k')

#%% HYSTERESIS LENGHTS TIME - FROM WTL --- SAME ABOVE

col_list = ['k','dodgerblue','darkorange','red']
sce_list = ['historic','RCP26','RCP45','RCP85']
# sce_list = ['RCP2.6','RCP8.5']
dict_scecol = dict(zip(sce_list, col_list))# sce_list = ['RCP85']

# col_list = ['k']
# sce_list = ['RCP26']
# # sce_list = ['RCP2.6','RCP8.5']
# dict_scecol = dict(zip(sce_list, col_list))# sce_list = ['RCP85']

stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
color = 'k'
BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=dem_path, 
                              out_path=out_path,
                              load=True)
mask = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
mask_grenou = imageio.imread(stable_folder+'subbasin/subbasin_Qgrenou/'+'watershed_dem.tif')
dem_box = imageio.imread(stable_folder+'geographic/'+'watershed_box_buff_dem.tif')
area = BV.geographic.area
area = int(round(area))

import imageio
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False
wbt.downslope_flowpath_length(
    stable_folder+'geographic/'+'watershed_direc.tif', 
    stable_folder+'geographic/'+'downslope_flowpath_length.tif', 
    watersheds=None, 
    weights=None, 
    esri_pntr=False)
down = imageio.imread(stable_folder+'geographic/'+'downslope_flowpath_length.tif')
toolbox.export_tif(stable_folder+'geographic/'+'watershed_box_buff_dem.tif',
                   down, -99999, stable_folder+'geographic/'+'downslope_flowpath_length_box.tif')
down = imageio.imread(stable_folder+'geographic/'+'downslope_flowpath_length_box.tif')

# fig, ax = plt.subplots(1, 1, figsize=(6,6))
# fig, ax = plt.subplots(1,1, figsize=(4.5,4))
# fig, ax = plt.subplots(1,1, figsize=(6,5))

# for ivar, var in enumerate(['total_areas', 'prop_ratio'][:]):
for ivar, var in enumerate(['perenn_areas'][:]):
# for ivar, var in enumerate(['prop_ratio'][:]):
# for ivar, var in enumerate(['L_phy'][:]):
# for ivar, var in enumerate(['L_wtl'][:]):

    if  ivar == 1:
        figs, axs = plt.subplots(4,1, figsize=(4.5+0.5,13.5), sharex=True, sharey=False, dpi=600)
    else:
        figs, axs = plt.subplots(4,1, figsize=(4.5+0.5,13.5), sharex=True, sharey=False, dpi=600)
    axs = axs.ravel()
    
    compt = 1
    
    for ic, sce in enumerate(sce_list):
        years = pd.date_range(start='01/01/1975', end='31/12/2099', freq='M').year.unique()
        # df_yearly = pd.DataFrame(np.nan, index=Smod.index, columns=years)
        # df_pi = pd.DataFrame(np.nan, index=range(len(mask.flatten())), columns=years)
        
        print(sce)
        
        for id_mod_val in list_id_mod[:]:
            
            if sce == 'historic':
                h5file = BV.simulations_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)+'_ALL_'+'RCP85'
            else:
                h5file = BV.simulations_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)+'_ALL_'+sce
            d = dd.io.load(h5file)
            list_model_name = d['list_model_name'][:]
            list_model_success = d['list_model_success'][:]
            list_model_modflow = d['list_model_modflow'][:]
            
            for model_name, model_success, model_modflow in zip(list_model_name[:],
                                                                list_model_success[:],
                                                                list_model_modflow[:]):
                
                
                
                Smod = pd.read_csv(BV.simulations_folder+'/'+model_name+'/_postprocess/_timeseries/_simulated_timeseries_bis.csv', sep=';',
                                    index_col='date', parse_dates=True)
                
                for pidx, pzone in enumerate(['subbasin_Qlasset','subbasin_Qbreton','subbasin_Qgrenou','subbasin_Qbombee']):
                
                    print(pzone)    
                    axa = axs[pidx]
                    # axb = axa.twinx()
                    # subbasin_Qlasset
                    # subbasin_Qbreton
                    # subbasin_Qgrenou
                    # subbasin_Qbombee
                    Smod = pd.read_csv(BV.simulations_folder+'/'+model_name+'/_subbasins/'+pzone+'/_simulated_timeseries_bis.csv', sep=';',
                                        index_col='date', parse_dates=True)
                        
                    # Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
                    Smod['prop_ratio'] = Smod.intermit_areas / Smod.total_areas
                    Smod['recharge'] = Smod['recharge'] #* 1000 * 30
                    Smod['outflow_drain'] =  ( Smod['outflow_drain'] )  #+ Smod['runoff'] ) # * (area * 1e6)
                    Smod['groundwater_storage'] = Smod['groundwater_storage']
                    per = 1
                    Smod['dQ'] = Smod['outflow_drain'].diff()
                    Smod['dGW'] = Smod['groundwater_storage'].diff()
                    Smod['t'] = abs((Smod['groundwater_storage'].diff(periods=per) / (Smod['outflow_drain']* (area * 1e6)).diff(periods=per)))
                    # Smod['t'] = ((Smod['groundwater_storage'].diff(periods=per) / (Smod['outflow_drain']* (area * 1e6)).diff(periods=per)))
                    # Smod['t'][Smod['t']>1000] = np.nan
                    
                    E = float(model_name.split('_')[-2].split('-')[0])
                    wt_ep = E - Smod['watertable_depth']
                    tsat = wt_ep
                    tsat = 40
                    Sy = float(model_name.split('_')[-2].split('-')[1]) / 100
                    K = float(model_name.split('_')[-2].split('-')[2]+('-'+model_name.split('_')[-2].split('-')[3])) * 3600 * 24
                    
                    Smod['L_phy'] = np.sqrt( (Smod['t']*K*tsat) / Sy )
                    
                    Smod['L_wtl'] = Smod['L_wt_mean_str']
                    
                    Smod['t_phy'] = Smod['L_wtl']**2 / ((K*tsat)/Sy)
                    
                    if sce == 'historic':
                        Smod = select_period(Smod, 1980, 2010)
                    else:
                        Smod = select_period(Smod, 2070, 2100)
                    
                    # x = Smod['recharge'] * 1000 * 7
                    
                    for iv, vv in enumerate(['intermit_areas','perenn_areas']):
                        
                        if iv == 0:
                            ax = axa
                            if pidx == 0:
                                axa.set_ylim(-0,3.5)
                            if pidx == 1:
                                axa.set_ylim(-0,1.5)
                            if pidx == 2:
                                axa.set_ylim(-0,6)
                            if pidx == 3:
                                axa.set_ylim(-0,3)
                        else:
                            axb = axa.twinx()
                            # if pidx == 0:
                            #     axb.set_ylim(10,15)
                            # if pidx == 1:
                            #     axb.set_ylim(4,6)
                            # if pidx == 2:
                            #     axb.set_ylim(6,12)
                            # if pidx == 3:
                            #     axb.set_ylim(5,10)
                            # axb.set_yticks([5,6,7,8,9,10])
                            if pidx == 0:
                                # axb.set_ylim(-0,4*4)
                                axb.set_ylim(9.5,13)
                            if pidx == 1:
                                # axb.set_ylim(-0,1.5*4)
                                # axb.set_yticks(np.array([0,0.4,0.8,1.2])*4)
                                axb.set_ylim(4.5,6)
                                axb.set_yticks([4.5,4.7,4.9,5.1,5.3,5.5,5.7,5.9])
                            if pidx == 2:
                                # axb.set_ylim(-0,6*4)
                                # axb.set_yticks([0,4,8,12,16,20,24])
                                axb.set_ylim(6,12)
                            if pidx == 3:
                                # axb.set_ylim(-0,3*4)
                                axb.set_ylim(6,9)
                                # ax.set_yticks()
                                # axb.set_yticks([6,6.5,7,7.5,8,8.5])
                            ax = axb
                        
                        x = Smod['L_wtl']
                        # x = Smod['outflow_drain'] * 1000 * 7
                        # x = Smod['total_areas']
                        if iv == 0:
                            y = Smod[vv]
                        else:
                            # y = Smod['perenn_areas']/Smod['total_areas']
                            y = Smod[vv]
                        # y = Smod['prop_ratio']
                        c = Smod.index.month
                        wy = pd.Series(x.index.month).replace([10,11,12,1,2,3,4,5,6,7,8,9],
                                                                [1,2,3,4,5,6,7,8,9,10,11,12])
                        xi = x.groupby([lambda x: x.month]).mean()
                        yi = y.groupby([lambda y: y.month]).mean()
                        
                        xiq25 = x.groupby([lambda x: x.month]).quantile(0.25)
                        yiq25 = y.groupby([lambda y: y.month]).quantile(0.25)
                        
                        xiq75 = x.groupby([lambda x: x.month]).quantile(0.75)
                        yiq75 = y.groupby([lambda y: y.month]).quantile(0.75)
                        
                        # xi = x.groupby([lambda x: x.month]).median()
                        # yi = y.groupby([lambda y: y.month]).median()
                        # cmapping = mpl.colors.ListedColormap(dict_c[watershed_name])
                        # cmapping = dict_cmap[watershed_name]
                        
                        # cmap = plt.cm.YlGnBu
                        if sce == 'historic':
                            cmap = 'Greys'
                        if sce == 'RCP26':
                            cmap = 'Blues'
                        if sce == 'RCP45':
                            cmap = 'Oranges'
                        if sce == 'RCP85':
                            cmap = 'Reds'
                        # cmap = parula_map
                        # cmaplist = [cmap(i) for i in range(cmap.N)]
                        # if watershed_name == 'Canut':
                        # cmaplist = ['limegreen','greenyellow']
                        # if watershed_name == 'Nancon':
                        #     cmaplist = ['tomato', 'lightsalmon']
                        # cmaplist[0] = (.5, .5, .5, 1.0)
                        # cmap = mpl.colors.LinearSegmentedColormap.from_list(
                        #     'Custom cmap', cmaplist, cmap.N)
                        
                        # scat = ax.scatter(x, y, c=wy, cmap=cmap, marker="o", 
                        #                   s=1, vmin=1, vmax=12, alpha=0.75, ec='none', zorder=-1)
                        xiline = xi.append(xi.iloc[[0]])
                        xiline.index = np.arange(1,14,1)
                        yiline = yi.append(yi.iloc[[0]])
                        yiline.index = np.arange(1,14,1)
                        
                        xilineq25 = xiq25.append(xiq25.iloc[[0]])
                        xilineq25.index = np.arange(1,14,1)
                        yilineq25 = yiq25.append(yiq25.iloc[[0]])
                        yilineq25.index = np.arange(1,14,1)                    
                        
                        xilineq75 = xiq75.append(xiq75.iloc[[0]])
                        xilineq75.index = np.arange(1,14,1)
                        yilineq75 = yiq75.append(yiq75.iloc[[0]])
                        yilineq75.index = np.arange(1,14,1)                  
                        
                        # ax.fill_between(xiline, yilineq25, yilineq75, lw=0,
                        #                  interpolate=False,
                        #                 color=dict_scecol[sce], alpha=0.25)
                        
                        # ax.plot(xi, yiq25, linestyle = '-', lw=0.5, 
                        #         color=dict_scecol[sce], zorder=0)
                        # ax.plot(xi, yiq75, linestyle = '-', lw=0.5, 
                        #         color=dict_scecol[sce], zorder=0)
                        
                        ax.plot(xiline, yiline, linestyle = '-', lw=2, 
                                color=dict_scecol[sce], zorder=compt)
                        if pidx == 3:
                            if iv == 1:
                                if sce == 'RCP26':
                                    ax.plot(xiline, (yiline*0)+8.95, linestyle = '-', lw=2, 
                                            color=dict_scecol[sce], zorder=compt)
                        wyi = np.arange(1,12+1,1)
                        # compt = 1
                        if iv == 0:
                            for k in wyi:
                                ax.plot(xi[k], yi[k], marker="o", lw=1, markersize=10.5, 
                                           markeredgecolor=dict_scecol[sce], 
                                           markerfacecolor='white', markeredgewidth=1.2,
                                           linestyle = 'None', zorder=compt)
                                ax.annotate(k,(xi[k],yi[k]), family='sans-serif', fontsize=7, 
                                        color=dict_scecol[sce], weight="bold", ha='center', va='center',
                                        zorder=compt)
                                compt+=1
                        xe = pd.DataFrame()
                        xe['q25'] = (x.groupby(x.index.month).quantile(0.25))
                        xe['q75'] = (x.groupby(x.index.month).quantile(0.75))        
                        ye = pd.DataFrame()
                        ye['q25'] = (y.groupby(y.index.month).quantile(0.25))
                        ye['q75'] = (y.groupby(y.index.month).quantile(0.75))
                        # if iv == 0:
                        #     ax.errorbar(xi, yi,
                        #                   yerr=np.abs(np.vstack([yi-ye.q25, ye.q75-yi])),
                        #                   # xerr=np.abs(np.vstack([xi-xe.q25, xe.q75-xi])),
                        #                   ecolor = dict_scecol[sce], fmt = 'none', capsize = 1,
                        #                   elinewidth=0.5, 
                        #                   capthick=0, zorder=-1000)               
                        # ax.errorbar(xi, yi,
                        #               yerr=np.abs(np.vstack([yi-ye.q25, yi+ye.q25])),
                        #               xerr=np.abs(np.vstack([xi-xe.q25, xi+xe.q25])),
                        #               ecolor = dict_scecol[sce], fmt = 'none', capsize = 1, elinewidth=0.5, 
                        #               capthick=0.5, zorder=-1000)  
                        
                        if iv == 0:
                            ax.grid(alpha=0.5)
                        # else:
                        #     axb.set_ylim(axa.get_ylim())
                        
                        # ax.axvline(x.median(), c=dict_c[watershed_name], ls='--')
                        # ax.axhline(y.median(), c=dict_c[watershed_name], ls='--')
                        
                        # ax.set_xscale('log')
                        # ax.set_yscale('log')
                        
                        if iv == 0:
                        
                            if pidx==3:
                                ax.set_xlabel('$L_{gw}$ [m]')
                            # if ivar ==0:
                            ax.set_ylabel('$A_{sea}$ [%]')
                            # else:
                            #     ax.set_ylabel('$A_{int}$ / $A_{sat}$ [-]')
                        
                        else:
                            ax.set_ylabel('$A_{yea}$ [%]', rotation=270, labelpad=25)
                                
                        
                        if iv ==0:
                            ax.axvline(xiline.mean(), linestyle = ':', lw=1.5, 
                                    color=dict_scecol[sce], zorder=-1000)
                        
                        # ax.set_xlim(0.7,100)
                        # ax.set_ylim(0,25)
                        
                        # if iv == 0:
                        #     ax.set_ylim(None,None)
                        
                        # if iv == 1:
                        #     ax.set_ylim(0,10)
                        
                        ax.set_xlim(180,420)
                
    figs.tight_layout()
    
    # figs.savefig('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_figures_paper/_v0/06_fig_hyster/'+
    #             'HYSTER_'+var+'_FROM WTL'+'.png',
    #                         bbox_inches='tight')

#%% INTERMENSUAL TIME - FROM WTL

col_list = ['k','dodgerblue','darkorange','red']
sce_list = ['historic','RCP26','RCP45','RCP85']
# sce_list = ['RCP2.6','RCP8.5']
dict_scecol = dict(zip(sce_list, col_list))# sce_list = ['RCP85']

stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
color = 'k'
BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=dem_path, 
                              out_path=out_path,
                              load=True)
mask = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
mask_grenou = imageio.imread(stable_folder+'subbasin/subbasin_Qgrenou/'+'watershed_dem.tif')
dem_box = imageio.imread(stable_folder+'geographic/'+'watershed_box_buff_dem.tif')
area = BV.geographic.area
area = int(round(area))

import imageio
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False
wbt.downslope_flowpath_length(
    stable_folder+'geographic/'+'watershed_direc.tif', 
    stable_folder+'geographic/'+'downslope_flowpath_length.tif', 
    watersheds=None, 
    weights=None, 
    esri_pntr=False)
down = imageio.imread(stable_folder+'geographic/'+'downslope_flowpath_length.tif')
toolbox.export_tif(stable_folder+'geographic/'+'watershed_box_buff_dem.tif',
                   down, -99999, stable_folder+'geographic/'+'downslope_flowpath_length_box.tif')
down = imageio.imread(stable_folder+'geographic/'+'downslope_flowpath_length_box.tif')

# fig, ax = plt.subplots(1, 1, figsize=(6,6))
# fig, ax = plt.subplots(1,1, figsize=(5.5,3.5))
# fig, ax = plt.subplots(1,1, figsize=(6,5))


# for ivar, var in enumerate(['t'][:]):
# for ivar, var in enumerate(['t_wtl'][:]):
for ivar, var in enumerate(['t_wtl','L_wtl']):
    
    # if  ivar == 1:
    #     figs, axs = plt.subplots(4,1, figsize=(4.5,13.5), sharex=True, sharey=False)
    # else:
    figs, axs = plt.subplots(4,1, figsize=(4.5,13.5), sharex=True, sharey=False)
    axs = axs.ravel()
    
    compt = 1

    for ic, sce in enumerate(sce_list):
        years = pd.date_range(start='01/01/1975', end='31/12/2099', freq='M').year.unique()
        # df_yearly = pd.DataFrame(np.nan, index=Smod.index, columns=years)
        # df_pi = pd.DataFrame(np.nan, index=range(len(mask.flatten())), columns=years)
        
        print(sce)
        
        for id_mod_val in list_id_mod[:]:
            
            if sce == 'historic':
                h5file = BV.simulations_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)+'_ALL_'+'RCP85'
            else:
                h5file = BV.simulations_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)+'_ALL_'+sce
            d = dd.io.load(h5file)
            list_model_name = d['list_model_name'][:]
            list_model_success = d['list_model_success'][:]
            list_model_modflow = d['list_model_modflow'][:]
            
            for model_name, model_success, model_modflow in zip(list_model_name[:],
                                                                list_model_success[:],
                                                                list_model_modflow[:]):
                
                Smod = pd.read_csv(BV.simulations_folder+'/'+model_name+'/_postprocess/_timeseries/_simulated_timeseries_bis.csv', sep=';',
                                    index_col='date', parse_dates=True)
                
                for pidx, pzone in enumerate(['subbasin_Qlasset','subbasin_Qbreton','subbasin_Qgrenou','subbasin_Qbombee']):
                
                    print(pzone)    
                    ax = axs[pidx]
               
                    # subbasin_Qbreton
                    # subbasin_Qgrenou
                    # subbasin_Qbombee
                    Smod = pd.read_csv(BV.simulations_folder+'/'+model_name+'/_subbasins/'+pzone+'/_simulated_timeseries_bis.csv', sep=';',
                                        index_col='date', parse_dates=True)
                        
                    # Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
                    Smod['prop_ratio'] = Smod.intermit_areas / Smod.total_areas
                    Smod['recharge'] = Smod['recharge'] #* 1000 * 30
                    Smod['outflow_drain'] =  ( Smod['outflow_drain'] )  #+ Smod['runoff'] ) # * (area * 1e6)
                    Smod['groundwater_storage'] = Smod['groundwater_storage']
                    per = 1
                    Smod['dQ'] = (Smod['outflow_drain']*(area * 1e6)).diff(periods=per)
                    Smod['dGW'] = Smod['groundwater_storage'].diff(periods=per)
                    Smod['t'] = abs(Smod['dGW'] / Smod['dQ'])
                    # Smod['t'] = ((Smod['groundwater_storage'].diff(periods=per) / (Smod['outflow_drain']* (area * 1e6)).diff(periods=per)))
                    # Smod['t'][Smod['t']>1000] = np.nan
                    
                    E = float(model_name.split('_')[-2].split('-')[0])
                    wt_ep = E - Smod['watertable_depth']
                    tsat = wt_ep
                    tsat = 40
                    Sy = float(model_name.split('_')[-2].split('-')[1]) / 100
                    K = float(model_name.split('_')[-2].split('-')[2]+('-'+model_name.split('_')[-2].split('-')[3])) * 3600 * 24
                    
                    Smod['L_phy'] = np.sqrt( (Smod['t']*K*tsat) / Sy )
                    
                    Smod['L_wtl'] = Smod['L_wt_median_str']
                    
                    Smod['t_wtl'] = Smod['L_wtl']**2 / ((K*tsat)/Sy)
                    
                    if sce == 'historic':
                        Smod = select_period(Smod, 1980,2010)
                    else:
                        Smod = select_period(Smod, 2070, 2100)
        
                    data_index =  Smod.copy()
        
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
                    # print(Q10.min())
                    # print(Q90.mean())
                    # Max = data_index.resample('Y').max()
                    
                    mean_interan_days = data_index.groupby([data_index.index.month], as_index=True).mean()#.to_frame()
                    
                    std_interan_days = data_index.groupby([data_index.index.month], as_index=True).std()
                    q10_interan_days = data_index.groupby([data_index.index.month], as_index=True).min()
                    q90_interan_days = data_index.groupby([data_index.index.month], as_index=True).max()
                    q50_interan_days = data_index.groupby([data_index.index.month], as_index=True).quantile(0.50)
                    q25_interan_days = data_index.groupby([data_index.index.month], as_index=True).quantile(0.25)
                    q75_interan_days = data_index.groupby([data_index.index.month], as_index=True).quantile(0.75)
                    themean = data_index.groupby([data_index.index.month], as_index=True).mean()
                    
                    # mean_interan_days['std'] = std_interan_days
                    # mean_interan_days['q10'] = q10_interan_days
                    # mean_interan_days['q90'] = q90_interan_days
                    # mean_interan_days['q50'] = q50_interan_days['t']
                    # mean_interan_days['q75'] = q75_interan_days
                    # mean_interan_days['q25'] = q25_interan_days
                    # mean_interan_days['mean'] = themean
                    # mean_interan_days.index.names = ['months']
                    # mean_interan_days = mean_interan_days.reset_index()
                    # mean_interan_days.months = mean_interan_days.months.replace(
                    #                                     [10,11,12,1,2,3,4,5,6,7,8,9],
                    #                                     [1,2,3,4,5,6,7,8,9,10,11,12])
                    
                    mean_interan_days['q50_'+var] = q50_interan_days[var]
                    mean_interan_days['q50_dQ'] = q50_interan_days['dQ']
                    mean_interan_days['q50_dGW'] = q50_interan_days['dGW']
                    
                    mean_interan_days['months'] = np.arange(1,13,1)
                    mean_interan_days = mean_interan_days.reset_index()
                    mean_interan_days = mean_interan_days.sort_values(['months'])
                
                    mean_interan_days['counts'] = np.array(range(1,len(mean_interan_days)+1))
                    # mean_interan_days.q10 = mean_interan_days.q10.replace(0,0.01)
                    
                    # fig, ax = plt.subplots(figsize=(4,3))
                    # ax.plot(mean_interan_days.counts, mean_interan_days[station+'_mmm'],
                    #         lw=1, color='red', label='Mean')
                    ax.plot(mean_interan_days.index, mean_interan_days['q50_'+var],
                            lw=2,
                            # color=couleurs[i],
                            color=dict_scecol[sce],
                            label=Qobs_name)
                    # ax.plot(mean_interan_days.index, mean_interan_days['mean'],
                    #         lw=0.5,
                    #         # color=couleurs[i],
                    #         color=dict_scecol[sce],
                    #         label=Qobs_name)
                    # ax.plot(mean_interan_days.counts, mean_interan_days['mean'],
                    #         lw=0.5,
                    #         # color=couleurs[i],
                    #         color=dict_scecol[sce],
                    #         label=Qobs_name)
                    # yerrmax = mean_interan_days.q75
                    # yerrmin = mean_interan_days.q25
                    # ax.legend('upper right')
                    # ax.fill_between(mean_interan_days.index, yerrmin, yerrmax,
                    #                   color=dict_scecol[sce],edgecolor='None',
                    #                   alpha = 0.1, label='10-90th')
                    
                    # ax.plot(data_index[data_index.index.year==2022], c='k')
                    
                    # ax.fill_between(mean_interan_days.counts, yerrmin, yerrmax,
                    #                   color='grey',edgecolor='grey', lw=0.5,
                    #                   alpha = 0.5, label='10-90th')
                    
                    ax.grid(alpha=0.5)
                    
                    # plt.yscale('log')
                    # ax.yaxis.set_major_formatter(ScalarFormatter())
                    # ax.set_xlim(0,366)
                    # if i == 0:
                    #     ax.set_ylim(-10,20)
                    # if i == 1:
                    #     ax.set_ylim(0,10)
                    # if i == 2:
                    #     ax.set_ylim(0,10) 
                    # if i == 3:
                    #     ax.set_ylim(0,10) 
                    # if i == 4:
                    #     ax.set_ylim(0,10) 
                    # if i == 5:
                    #     ax.set_ylim(0,10) 
                    # ax.set_ylim(0.01,10)
                    ax.tick_params(axis='both', which='major', pad=10)
                    # x1 = np.linspace(0,366,13)
                    x2 = np.array([0,1,2,3,4,5,6,7,8,9,10,11])
                    squad = ['J','F','M','A','M','J','J','A','S','O','N','D']
                    ax.set_xticks(x2)
                    ax.set_xticklabels(squad, minor=False, rotation='horizontal')
                    # if i == 2:
                    if pidx==3:
                        ax.set_xlabel('Months', labelpad=+10)
                    # if i ==0:
                    if var == 't_wtl':
                        ax.set_ylabel('$t_{r}$ [d]')
                    if var == 'L_wtl':
                        ax.set_ylabel('$L_{c}$ [m]')
                    ax.set_xlim(0,11)
                    # ax.set_title('S'+str(i+1))
                    # ax.legend(loc='upper right', frameon=False)
                    # if i==0:
                    #     ax.set_ylim(0,)
                    # if i==1:
                    #     ax.set_ylim(0,2)
                    # ax.set_ylim(1e-1,100)
                    # ax.set_yscale('log')
                    # ax.set_ylim(0,15)
                    
                    wyi = np.arange(0,12,1)
                    # compt = 1
                    
                    # ax.plot(mean_interan_days.index, mean_interan_days['q50_t'], marker="o", lw=1, markersize=10, 
                    #            markeredgecolor=dict_scecol[sce], 
                    #            markerfacecolor='white', markeredgewidth=1.2,
                    #            linestyle = 'None', zorder=compt, clip_on=False)
                    for k in wyi:
                        if (mean_interan_days['q50_dGW'][k]>0) and (mean_interan_days['q50_dQ'][k]>0):
                            marker = '^'
                        if (mean_interan_days['q50_dGW'][k]<0) and (mean_interan_days['q50_dQ'][k]>0):
                            marker = '<'
                        if (mean_interan_days['q50_dGW'][k]<0) and (mean_interan_days['q50_dQ'][k]<0):
                            marker = 'v'
                        if (mean_interan_days['q50_dGW'][k]>0) and (mean_interan_days['q50_dQ'][k]<0):
                            marker = '>'                            
                            
                        ax.plot(mean_interan_days.index[k], mean_interan_days['q50_'+var][k], marker=marker, lw=1, markersize=8.5, 
                                    markeredgecolor=dict_scecol[sce], 
                                    markerfacecolor='white', markeredgewidth=1.2,
                                    linestyle = 'None', zorder=compt, clip_on=False)
                            
                        # ax.annotate(k+1,(mean_interan_days.index[k],mean_interan_days['q50_t'][k]),
                        #             family='sans-serif', fontsize=8, 
                        #     color=dict_scecol[sce], weight="bold", ha='center', va='center',
                        #     zorder=compt, clip_on=False)
                    compt+=1

    figs.tight_layout()
    
    figs.savefig('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_figures_paper/_v0/06_fig_hyster/'+
                'INTM_RESP_'+var+'_FROM_WTL'+'.png',
                            bbox_inches='tight')

#%% BOXPLOT RESPONSE TIME - FROM WTL

col_list = ['k','dodgerblue','darkorange','red']
sce_list = ['historic','RCP26','RCP45','RCP85']
# sce_list = ['RCP2.6','RCP8.5']
dict_scecol = dict(zip(sce_list, col_list))# sce_list = ['RCP85']

stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
color = 'k'
BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=dem_path, 
                              out_path=out_path,
                              load=True)
mask = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
mask_grenou = imageio.imread(stable_folder+'subbasin/subbasin_Qgrenou/'+'watershed_dem.tif')
dem_box = imageio.imread(stable_folder+'geographic/'+'watershed_box_buff_dem.tif')
area = BV.geographic.area
area = int(round(area))

import imageio
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False
wbt.downslope_flowpath_length(
    stable_folder+'geographic/'+'watershed_direc.tif', 
    stable_folder+'geographic/'+'downslope_flowpath_length.tif', 
    watersheds=None, 
    weights=None, 
    esri_pntr=False)
down = imageio.imread(stable_folder+'geographic/'+'downslope_flowpath_length.tif')
toolbox.export_tif(stable_folder+'geographic/'+'watershed_box_buff_dem.tif',
                   down, -99999, stable_folder+'geographic/'+'downslope_flowpath_length_box.tif')
down = imageio.imread(stable_folder+'geographic/'+'downslope_flowpath_length_box.tif')

# fig, ax = plt.subplots(1, 1, figsize=(6,6))
# fig, ax = plt.subplots(1,1, figsize=(5.5,3.5))
# fig, ax = plt.subplots(1,1, figsize=(6,5))

for ivar, var in enumerate(['t_wtl','L_wtl'][:]):
    
    # if  ivar == 1:
    #     figs, axs = plt.subplots(4,1, figsize=(4.5,13.5), sharex=True, sharey=False)
    # else:
    figs, axs = plt.subplots(4,1, figsize=(2.5,13.5), sharex=True, sharey=False)
    axs = axs.ravel()
    
    compt = 1

    for ic, sce in enumerate(sce_list):
        years = pd.date_range(start='01/01/1975', end='31/12/2099', freq='M').year.unique()
        # df_yearly = pd.DataFrame(np.nan, index=Smod.index, columns=years)
        # df_pi = pd.DataFrame(np.nan, index=range(len(mask.flatten())), columns=years)
        
        print(sce)
        
        for id_mod_val in list_id_mod[:]:
            
            if sce == 'historic':
                h5file = BV.simulations_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)+'_ALL_'+'RCP85'
            else:
                h5file = BV.simulations_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)+'_ALL_'+sce
            d = dd.io.load(h5file)
            list_model_name = d['list_model_name'][:]
            list_model_success = d['list_model_success'][:]
            list_model_modflow = d['list_model_modflow'][:]
            
            for model_name, model_success, model_modflow in zip(list_model_name[:],
                                                                list_model_success[:],
                                                                list_model_modflow[:]):
                
                Smod = pd.read_csv(BV.simulations_folder+'/'+model_name+'/_postprocess/_timeseries/_simulated_timeseries_bis.csv', sep=';',
                                    index_col='date', parse_dates=True)
                
                for pidx, pzone in enumerate(['subbasin_Qlasset','subbasin_Qbreton','subbasin_Qgrenou','subbasin_Qbombee']):
                
                    print(pzone)    
                    ax = axs[pidx]
               
                    # subbasin_Qbreton
                    # subbasin_Qgrenou
                    # subbasin_Qbombee
                    Smod = pd.read_csv(BV.simulations_folder+'/'+model_name+'/_subbasins/'+pzone+'/_simulated_timeseries_bis.csv', sep=';',
                                        index_col='date', parse_dates=True)
                        
                    # Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
                    Smod['prop_ratio'] = Smod.intermit_areas / Smod.total_areas
                    Smod['recharge'] = Smod['recharge'] #* 1000 * 30
                    Smod['outflow_drain'] =  ( Smod['outflow_drain'] )  #+ Smod['runoff'] ) # * (area * 1e6)
                    Smod['groundwater_storage'] = Smod['groundwater_storage']
                    per = 1
                    Smod['dQ'] = Smod['outflow_drain'].diff()
                    Smod['dGW'] = Smod['groundwater_storage'].diff()
                    Smod['t'] = abs((Smod['groundwater_storage'].diff(periods=per) / (Smod['outflow_drain']* (area * 1e6)).diff(periods=per)))
                    # Smod['t'] = ((Smod['groundwater_storage'].diff(periods=per) / (Smod['outflow_drain']* (area * 1e6)).diff(periods=per)))
                    # Smod['t'][Smod['t']>1000] = np.nan
        
                    if sce == 'historic':
                        Smod = select_period(Smod, 1980,2010)
                    else:
                        Smod = select_period(Smod, 2070, 2100)
                        
                    E = float(model_name.split('_')[-2].split('-')[0])
                    wt_ep = E - Smod['watertable_depth']
                    tsat = wt_ep
                    tsat = 40
                    Sy = float(model_name.split('_')[-2].split('-')[1]) / 100
                    K = float(model_name.split('_')[-2].split('-')[2]+('-'+model_name.split('_')[-2].split('-')[3])) * 3600 * 24
                    
                    Smod['L_phy'] = np.sqrt( (Smod['t']*K*tsat) / Sy )
                    
                    Smod['L_wtl'] = Smod['L_wt_median_str']
                    
                    Smod['t_wtl'] = Smod['L_wtl']**2 / ((K*tsat)/Sy)
            
                    # ax.plot(Smod['t'].resample('Y').mean().rolling(10).mean(), color=dict_scecol[sce])
                    # ax.scatter(Smod['t'], Smod['intermit_areas']/Smod['total_areas'],  color=dict_scecol[sce], s=1)
                    # ax.boxplot(1, Smod['t'])
        
                    # ax.set_yscale('log')
                    # ax.set_xlim(0,1000)
                    # ax.set_xscale('log')
                    
                    boxprops1 = dict(linestyle='-', linewidth=0, color='black',
                                    facecolor=dict_scecol[sce],
                                    alpha=0.7,
                                    edgecolor='k'
                                    )
                    boxprops2 = dict(linestyle='-', linewidth=1.5, color='black',
                                    facecolor='None',
                                    alpha=1,
                                    edgecolor='k',
                                    )
                    medianprops = dict(linestyle='-', linewidth=1.5, color='black')
                    meanpointprops = dict(markersize=0, marker='o', markeredgecolor='black',
                                          markerfacecolor='k', linestyle='-')
                    
                    if sce == 'historic':
                        ad = 0.30-0.10
                    if sce == 'RCP26':
                        ad = 0.45-0.05
                    if sce == 'RCP45':
                        ad = 0.60
                    if sce == 'RCP85':
                        ad = 0.75+0.05
                    
                    fil = Smod[var][~np.isnan(Smod[var])]
                    bp = ax.boxplot(fil, widths=0.15,
                                    positions=[ad],
                                      whis=False, showfliers=False, showmeans=False, 
                                      medianprops=medianprops, meanprops=meanpointprops,
                                      patch_artist=True, boxprops=boxprops1)
                    bp = ax.boxplot(fil, widths=0.15,
                                    positions=[ad],
                                      whis=False, showfliers=False, showmeans=False, 
                                      medianprops=medianprops, meanprops=meanpointprops,
                                      patch_artist=True, boxprops=boxprops2)
                    
                    for element in bp['whiskers']:
                        element.set_color('k')
                        element.set_linestyle('-')
                                        
                    ax.vlines(x=ad, 
                                ymin=fil.quantile(0.75), 
                                ymax=fil.quantile(0.90), color='k', zorder=2)
                    ax.vlines(x=ad, 
                                ymin=fil.quantile(0.10), 
                                ymax=fil.quantile(0.25), color='k', zorder=2)
                    # ax.plot(ad, 
                    #           d.quantile(0.10), color='k', zorder=2, lw=0,
                    #           marker='_', mew=1)
                    # ax.plot(ad, 
                    #           d.quantile(0.90), color='k', zorder=2, lw=0,
                    #           marker='_', mew=1)
                      
                    # ax.plot(ad, fil.mean(), marker='o', mec='k', ms=3, lw=0,
                    #         mfc='k', mew=1,
                    #         color='k', zorder=1000)
                    
                    # if i ==0:
                        # ax.set_ylabel('$t_{r}$ [d]')
                    if var == 't_wtl':
                        ax.set_ylabel('$t_{r}$ [d]')
                    if var == 'L_wtl':
                        ax.set_ylabel('$L_{c}$ [d]')
                    ax.set_xlim(-0,1)
                    if pidx ==3:
                        ax.set_xlabel('XXX')
                            
                    ax.grid(alpha=0.5)
                    
                    ax.set_xticklabels(ax.get_xticks().round(2))
    
    figs.tight_layout()
    
    figs.savefig('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_figures_paper/_v0/06_fig_hyster/'+
                'BOXP_RESP_'+var+'_FROM WTL'+'.png',
                            bbox_inches='tight')

                
#%% ---- PLOTS PROJECTIONS - OLD

#%% PI ALTITUDE

sce_list = ['RCP26','RCP85']
# sce_list = ['RCP85']

stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
color = 'k'
BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=dem_path, 
                              out_path=out_path,
                              load=True)
mask = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
dem_box = imageio.imread(stable_folder+'geographic/'+'watershed_box_buff_dem.tif')
area = BV.geographic.area
area = int(round(area))

import imageio
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False
wbt.downslope_flowpath_length(
    stable_folder+'geographic/'+'watershed_direc.tif', 
    stable_folder+'geographic/'+'downslope_flowpath_length.tif', 
    watersheds=None, 
    weights=None, 
    esri_pntr=False)
down = imageio.imread(stable_folder+'geographic/'+'downslope_flowpath_length.tif')
toolbox.export_tif(stable_folder+'geographic/'+'watershed_box_buff_dem.tif',
                   down, -99999, stable_folder+'geographic/'+'downslope_flowpath_length_box.tif')
down = imageio.imread(stable_folder+'geographic/'+'downslope_flowpath_length_box.tif')

fig, ax = plt.subplots(1, 1, figsize=(6,6))

for ic, sce in enumerate(sce_list):
    years = pd.date_range(start='01/01/1975', end='31/12/2099', freq='M').year.unique()
    df_yearly = pd.DataFrame(np.nan, index=Smod.index, columns=years)
    df_pi = pd.DataFrame(np.nan, index=range(len(mask.flatten())), columns=years)
    
    for id_mod_val in list_id_mod[:]:
    
        h5file = BV.simulations_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)+'_ALL_'+sce
        d = dd.io.load(h5file)
        list_model_name = d['list_model_name'][:]
        list_model_success = d['list_model_success'][:]
        list_model_modflow = d['list_model_modflow'][:]
        
        for model_name, model_success, model_modflow in zip(list_model_name[:],
                                                            list_model_success[:],
                                                            list_model_modflow[:]):
            
            Smod = pd.read_csv(BV.simulations_folder+'/'+model_name+'/_postprocess/_timeseries/_simulated_timeseries.csv', sep=';',
                               index_col='date', parse_dates=True)
                
            # Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            Smod['prop_ratio'] = Smod.intermit_areas / Smod.total_areas
            Smod['recharge'] = Smod['recharge'] * 1000 * 30
            Smod['outflow_drain'] =  ( Smod['outflow_drain'] ) * (area * 1e6) #+ Smod['runoff'] ) # * (area * 1e6)
            Smod['groundwater_storage'] = Smod['groundwater_storage']
            per = 1
            Smod['dQ'] = Smod['outflow_drain'].diff()
            Smod['dGW'] = Smod['groundwater_storage'].diff()
            Smod['t'] = abs((Smod['groundwater_storage'].diff(periods=per) / Smod['outflow_drain'].diff(periods=per)))
            Smod = select_period(Smod, 1975,2099)
            
            acc_npy = np.load(BV.simulations_folder+'/'+model_name+'/_postprocess/'+'accumulation_flux.npy', allow_pickle=True).item()
            
            pi_rast = imageio.imread(BV.simulations_folder+'/'+model_name+'/_postprocess/_rasters/'+'persistency_index_t(-).tif')
            pi_rast = np.ma.masked_array(pi_rast, mask=(mask<0))
            
            acc_npy_raw = acc_npy.copy()
            # acc_npy = list(acc_npy_raw.items())[-90*12:-60*12]
            # acc_npy = list(acc_npy_raw.items())[-60*12:-30*12]
            acc_npy = list(acc_npy_raw.items())[-30*12:]
            for key in range(len(acc_npy)):
                # mask = imageio.imread(self.geographic.watershed_dem)
                mask = imageio.imread(BV.geographic.watershed_box_buff_dem)
                acc_npy[key] = np.ma.masked_array(acc_npy[key][1], mask=(mask<0))
            zero = acc_npy[0] * 0
            for i in range(len(acc_npy)):
                tempo = acc_npy[i].copy()
                tempo[tempo>0] = 1
                zero = zero + tempo
            days_flux = zero.copy() / len(acc_npy)
            pi_export = days_flux.copy()
            # pi_rast = np.ma.masked_where(days_flux <= 0, days_flux)
            pi_export[days_flux <= 0] = -9999
            pi_export[mask<=0] = -9999
            
            pi_rast = pi_export.copy()
            
            dem_box = np.ma.masked_array(dem_box, mask=(mask<0))
            
            flat = dem_box.copy().flatten()
            flat = pd.DataFrame(flat, columns=['dem'])
            flat['pi'] = pi_rast.flatten()
            flat['pi'][flat['pi']<0] = 0.0001
            # flat['pi'][flat['pi']<0] = 0
            flat['down'] = down.flatten()
            flat['down'][flat['down']<0] = np.nan
            
            # plt.scatter(flat['pi'], flat['dem'])
                        
            print(sce, flat['pi'].count())
            
            # flat['pi'] = (flat['pi'] / flat['pi'].count()) #(flat['pi'].count())
                        
            # list_vals = [0,200,400,800,1000,1200,1400,1600,1800,2000,2200,2400,2600,2800,3000,3200,3400]
            list_vals = [1400,1600,2000,2400]
            # list_vals = [1200,1400,1600,1800,2000,2200,2400,2600,2800,3000,3200,3400]
            
            # flat0 = flat.groupby(pd.cut(flat['dem'], list_vals)).agg(lambda x: x.eq(0).sum())
            # flatN0 = flat.groupby(pd.cut(flat['dem'], list_vals)).agg(lambda x: x.ne(0).sum())
            # flatM= flat.groupby(pd.cut(flat['down'], list_vals)).mean()
            # flat50 = flat.groupby(pd.cut(flat['down'], list_vals)).quantile(0.5)
            # flat10 = flat.groupby(pd.cut(flat['down'], list_vals)).quantile(0.33)
            # flat90 = flat.groupby(pd.cut(flat['down'], list_vals)).quantile(0.50)
            
            flat0 = flat.groupby(pd.cut(flat['dem'], list_vals)).agg(lambda x: x.eq(0).sum())
            flatN0 = flat.groupby(pd.cut(flat['dem'], list_vals)).agg(lambda x: x.ne(0).sum())
            flatM = flat.groupby(pd.cut(flat['dem'], list_vals)).mean()
            flat50 = flat.groupby(pd.cut(flat['dem'], list_vals)).quantile(0.5)
            flat10 = flat.groupby(pd.cut(flat['dem'], list_vals)).quantile(0.25)
            flat90 = flat.groupby(pd.cut(flat['dem'], list_vals)).quantile(0.75)
            
            # flat50['dem2'] = np.array(list_vals[:-1])-100
            flat50['dem2'] = np.array([1500,1800,2200])
            
            cmap='jet_r'
            if sce =='RCP26':
                marker='^'
                color='dodgerblue'
                lw=3
            if sce =='RCP85':
                marker='v'
                color='red'
                lw=1
                
            # ax.scatter((flat0['pi']/(flat0['pi']+flatN0['pi']))*100, flat50['dem2'], c=flat50['pi'], marker=marker,
            #            s=100, ec='k', cmap=mpl.colors.ListedColormap(color),
            #             # vmin=0, vmax=1
            #            )
                
            ax.scatter(flat50['pi'], flat50['dem2'], c=flat50['pi'], marker=marker,
                        s=100, ec='k', cmap=mpl.colors.ListedColormap(color),
                        # vmin=0, vmax=1
                        )
            
            ax.scatter(flatM['pi'], flat50['dem2'], c=flat50['pi'], marker='o',
                        s=100, ec='k', cmap=mpl.colors.ListedColormap(color),
                        # vmin=0, vmax=1
                        )
            
            ax.hlines(y=flat50['dem2'], 
                        xmin=flat10['pi'], 
                        xmax=flat90['pi'], color=color, zorder=2, lw=lw)
            
            # ax.set_xlim(0,1)
            
            # ax.vlines(x=flat50['dem2'], 
            #             ymin=flat10['pi'], 
            #             ymax=flat90['pi'], color=color, zorder=2, lw=lw)

# ax.set_xscale('log')
ax.invert_yaxis()
ax.set_title(model_name, fontsize=6)

            # fig, ax = plt.subplots(1, 1, figsize=(6,3))
            
            # from matplotlib.ticker import PercentFormatter
            
            # n_bins = len(flat)
            
            # # N is the count in each bin, bins is the lower-limit of the bin
            # N, bins, patches = ax.hist(flat['pi'],
            #                             bins=100,
            #                             density=True)
            # ax.set_ylim(0,25)


#%% DECREASE PERSISTANCE INCREASE DRY

# mod_list = ['IPS1','NOR1','CAN3','CNR-ALA','ECE-RCA','MPI-CCL']
# mod_list = ['CNR-ALA']
sce_list = ['RCP26','RCP85']

# sce_list = ['RCP85']

space_pi = 1

# for watershed_name in watershed_names[:1]:
stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
color = 'k'
BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=dem_path, 
                              out_path=out_path,
                              load=True)
mask = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
area = BV.geographic.area
area = int(round(area))
for ic, sce in enumerate(sce_list):
    years = pd.date_range(start='01/01/1975', end='31/12/2099', freq='M').year.unique()
    df_yearly = pd.DataFrame(np.nan, index=Smod.index, columns=years)
    df_pi = pd.DataFrame(np.nan, index=range(len(mask.flatten())), columns=years)
    
    for id_mod_val in list_id_mod[:]:
    
        h5file = BV.simulations_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)+'_ALL_'+sce
        d = dd.io.load(h5file)
        list_model_name = d['list_model_name'][:]
        list_model_success = d['list_model_success'][:]
        list_model_modflow = d['list_model_modflow'][:]
        
        for model_name, model_success, model_modflow in zip(list_model_name[:],
                                                            list_model_success[:],
                                                            list_model_modflow[:]):
            
            Smod = pd.read_csv(BV.simulations_folder+'/'+model_name+'/_postprocess/_timeseries/_simulated_timeseries.csv', sep=';',
                               index_col='date', parse_dates=True)
                
            # Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            Smod['prop_ratio'] = Smod.intermit_areas / Smod.total_areas
            Smod['recharge'] = Smod['recharge'] * 1000 * 30
            Smod['outflow_drain'] =  ( Smod['outflow_drain'] ) * (area * 1e6) #+ Smod['runoff'] ) # * (area * 1e6)
            # Smod['groundwater_storage'] = Smod['groundwater_storage']/(Smod['groundwater_storage'].mean())
            Smod['groundwater_storage'] = Smod['groundwater_storage']
            per = 1
            Smod['dQ'] = Smod['outflow_drain'].diff()
            Smod['dGW'] = Smod['groundwater_storage'].diff()
            Smod['t'] = abs((Smod['groundwater_storage'].diff(periods=per) / Smod['outflow_drain'].diff(periods=per)))
            Smod = select_period(Smod, 1975,2099)
            
            acc_npy = np.load(BV.simulations_folder+'/'+model_name+'/_postprocess/'+'accumulation_flux.npy', allow_pickle=True).item()
            cpstart = 0
            cpend = space_pi
            for i in range(len(years)):
                # cpstart = 0
                # cpend = 30
                year = years[i]
                
                acc_npy_win = list(acc_npy.items())[12*cpstart:12*cpend]
                i_end = 12*cpend
                if i_end<len(acc_npy):
                    print(year)
                    for key in range(len(acc_npy_win)):
                        acc_npy_win[key] = np.ma.masked_array(acc_npy_win[key][1], mask=(mask<0))
                    zero = acc_npy_win[0] * 0
                    for i in range(len(acc_npy_win)):
                        tempo = acc_npy_win[i].copy()
                        tempo[tempo>0] = 1
                        zero = zero + tempo
                    days_flux = zero.copy() / len(acc_npy_win)
                    series = pd.Series(days_flux.flatten())
                else:
                    print('nop', year)
                    series = pd.Series(days_flux.flatten()*np.nan)
                df_pi[year] = series
                # series = pd.DataFrame(series.dropna())
                cpstart += 1
                cpend += 1
        
        df_yearly=df_pi.copy()
        # df_yearly[df_yearly==1] = np.nan
        df_yearly=df_yearly.dropna(how='all', axis=0)
        df_yearly[np.isnan(df_yearly)] = 0
        df_yearly = df_yearly.loc[~(df_yearly==0).all(axis=1)]
        df_yearly = df_yearly.iloc[:, :-space_pi]
        
        dtest_0e = df_yearly.mask(df_yearly > 0, np.nan).count()
        dtest_25 = df_yearly.mask(df_yearly == 0, np.nan)
        dtest_25 = dtest_25.mask(dtest_25 > 0.25, np.nan).count()
        dtest_50 = df_yearly.mask(df_yearly == 0, np.nan)
        dtest_50[(dtest_50<=0.25)|(dtest_50>0.5)] = np.nan
        dtest_50 = dtest_50.count()
        dtest_75 = df_yearly.mask(df_yearly == 0, np.nan)
        dtest_75[(dtest_75<=0.50)|(dtest_75>0.75)] = np.nan
        dtest_75 = dtest_75.count()
        dtest_1 = df_yearly.mask(df_yearly == 0, np.nan)
        dtest_1[(dtest_1<=0.75)|(dtest_75<1)] = np.nan
        dtest_1 = dtest_1.count()
        dtest_1e = df_yearly.mask(df_yearly == 0, np.nan)
        dtest_1e[(dtest_1e<1)] = np.nan
        dtest_1e = dtest_1e.count()
        

        fig, ax = plt.subplots(1,1, figsize=(10,4))
        ax.plot((dtest_0e/len(df_yearly))*100)
        ax.plot((dtest_25/len(df_yearly))*100)
        ax.plot((dtest_50/len(df_yearly))*100)
        ax.plot((dtest_75/len(df_yearly))*100)
        ax.plot((dtest_1/len(df_yearly))*100)
        ax.plot((dtest_1e/len(df_yearly))*100)
        
        """
        # ax.set_yscale('log')
        # if watershed_name == 'Canut':
        #     ax.set_ylim(1,1000)
        # if watershed_name == 'Nancon':
        #     ax.set_ylim(1,1000)
        ax.set_ylim(0,1)
        # ax.set_yticks(np.arange(0, 20+1, 5))
        ax.set_xlabel('Date')
        ax.set_ylabel('PI [-]')
        # normaliz = plt.Normalize(np.nanmin(df_yearly.median()), np.nanmax(df_yearly.median()))
        norm = matplotlib.colors.Normalize(vmin=np.quantile(df_yearly.median(), 0.25),
                                         vmax=np.quantile(df_yearly.median(), 0.75))
        colors = plt.cm.jet_r(norm(df_yearly.median()))
        # colors = plt.cm.jet_r(norm(df_yearly.median()*0+0.5))
        medianprops = dict(linestyle='-', linewidth=1, color='black')
        meanpointprops = dict(markersize=0, marker='o', markeredgecolor='black',
                              markerfacecolor='k', linestyle='-')
        ax.vlines(x=years+space_pi, 
                    ymin=df_yearly.mean(), 
                    ymax=df_yearly.quantile(0.66), color='k', zorder=2)
        ax.vlines(x=years+space_pi, 
                    ymin=df_yearly.quantile(0.33), 
                    ymax=df_yearly.mean(), color='k', zorder=2)
        
        # for i in range(len(years)):
        #     boxprops = dict(linestyle='-', linewidth=1, color='k',
        #                     facecolor=colors[i], 
        #                     alpha=0.5)
        #     bp = plt.boxplot(df_yearly.iloc[:,i], widths=0.75,
        #                     positions=[df_yearly.columns[i]+space_pi],
        #                     whis=False, showfliers=False, showmeans=False, 
        #                     medianprops=medianprops, meanprops=meanpointprops,
        #                     patch_artist=True,
        #                     boxprops=boxprops)
        ax.plot(years+space_pi, df_yearly.mean(), marker='o', mec='k', ms=1.5, lw=0,
                mfc='k', mew=1,
                color='k', zorder=1000)      
        # for element in bp['whiskers']:
        #     element.set_color('k')
        #     element.set_linestyle('-')
        """
        
        ax.set_xticks(np.arange(1980, 2100+1, 10))
        ax.set_xticklabels(np.arange(1980, 2100+1, 10))
        ax.set_xlim(1974,2100)
        ax.tick_params(axis='x', which='minor')
        from matplotlib.ticker import (MultipleLocator)
        ax.xaxis.set_minor_locator(MultipleLocator(1))
        ax.set_axisbelow(True)
        ax.xaxis.grid(color='gray', alpha=0.2, zorder=-20)
        ax.yaxis.grid(color='gray', alpha=0.2, zorder=-20, which='both')
        ax.set_title(model_name, fontsize=8)
        plt.tight_layout()    

#%% PI PROJECTIONS SEASONALLY MAPPING

def season_anomaly(months, begin_h, end_h, begin_f, end_f):
    # months = [5,6,7]
    # begin_h = 18*12
    # end_h = 48*12
    # begin_f = -30*12
    # end_f = 0

    # Historic
    if begin_h == 0:
        acc_npy_h = list(acc_npy.items())[:end_h]
    else:
        acc_npy_h = list(acc_npy.items())[begin_h:end_h]
    acc_npy_1 = list(acc_npy_h)[months[0]::12]
    acc_npy_2 = list(acc_npy_h)[months[1]::12]
    acc_npy_3 = list(acc_npy_h)[months[2]::12]
    acc_npy_h = (acc_npy_1 + acc_npy_2 + acc_npy_3)
    for key in range(len(acc_npy_h)):
        acc_npy_h[key] = np.ma.masked_array(acc_npy_h[key][1], mask=(mask<0))
    zero = acc_npy[0] * 0
    for i in range(len(acc_npy_h)):
        tempo = acc_npy_h[i].copy()
        tempo[tempo>0] = 1
        zero = zero + tempo
    days_flux_h = zero.copy() / len(acc_npy_h)

    # To look
    if end_f == 0:
        acc_npy_f = list(acc_npy.items())[begin_f:]
    else:
        acc_npy_f = list(acc_npy.items())[begin_f:end_f]
    acc_npy_1 = list(acc_npy_f)[months[0]::12]
    acc_npy_2 = list(acc_npy_f)[months[0]::12]
    acc_npy_3 = list(acc_npy_f)[months[2]::12]
    acc_npy_f = (acc_npy_1 + acc_npy_2 + acc_npy_3)
    for key in range(len(acc_npy_f)):
        acc_npy_f[key] = np.ma.masked_array(acc_npy_f[key][1], mask=(mask<0))
    zero = acc_npy[0] * 0
    for i in range(len(acc_npy_f)):
        tempo = acc_npy_f[i].copy()
        tempo[tempo>0] = 1
        zero = zero + tempo
    days_flux_f = zero.copy() / len(acc_npy_f)
    
    # Anomaly
    # days_flux_ano = ( (days_flux_f - days_flux_h) ) * 100
    days_flux_ano = ( (days_flux_f - days_flux_h) ) / days_flux_h
    # data = np.ma.masked_where((days_flux_ano==0)&(days_flux_h==0), days_flux_ano)
    data = np.ma.masked_where((days_flux_ano==0)|(days_flux_h==0), days_flux_ano)
    # data = data.flatten().filled(np.nan)
    # data = data.flatten()
    # data = days_flux_ano[~days_flux_ano.mask]
    # data = data.compressed()
    # data = data[~np.isnan(data)]
    data = days_flux_ano[~days_flux_ano.mask]
    
    return days_flux_h, days_flux_f, days_flux_ano, data

# mod_list = ['IPS1','NOR1','CAN3','CNR-ALA','ECE-RCA','MPI-CCL']
# mod_list = ['CNR-ALA']
# sce_list = ['RCP2.6','RCP8.5']

sce_list = ['RCP85']
# sce_list = ['RCP26']

# for watershed_name in watershed_names[:1]:
stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
color = 'k'
BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=dem_path, 
                              out_path=out_path,
                              load=True)
mask = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
mask = imageio.imread(stable_folder+'geographic/'+'watershed_box_buff_dem.tif')

area = BV.geographic.area
area = int(round(area))

mod='ALL'

for ic, sce in enumerate(sce_list):
    years = pd.date_range(start='01/01/1975', end='31/12/2099', freq='M').year.unique()
    df_yearly = pd.DataFrame(np.nan, index=Smod.index, columns=years)
    df_pi = pd.DataFrame(np.nan, index=range(len(mask.flatten())), columns=years)

    # for m in np.arange(0,11+1,1):

    df_ano = pd.DataFrame()
    
    _SON_h = []
    _DJF_h = []
    _MAM_h = []
    _JJA_h = []
    
    _SON_f = []
    _DJF_f = []
    _MAM_f = []
    _JJA_f = []
    
    _SON_ano = []
    _DJF_ano = []
    _MAM_ano = []
    _JJA_ano = []
    
    for id_mod_val in list_id_mod[:]:
    
        h5file = BV.simulations_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)+'_ALL_'+sce
        d = dd.io.load(h5file)
        list_model_name = d['list_model_name'][:]
        list_model_success = d['list_model_success'][:]
        list_model_modflow = d['list_model_modflow'][:]
        
        for model_name, model_success, model_modflow in zip(list_model_name[:],
                                                            list_model_success[:],
                                                            list_model_modflow[:]):
            
            Smod = pd.read_csv(BV.simulations_folder+'/'+model_name+'/_postprocess/_timeseries/_simulated_timeseries.csv', sep=';',
                               index_col='date', parse_dates=True)
                
            # Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            Smod['prop_ratio'] = Smod.intermit_areas / Smod.total_areas
            Smod['recharge'] = Smod['recharge'] * 1000 * 30
            Smod['outflow_drain'] =  ( Smod['outflow_drain'] ) * (area * 1e6) #+ Smod['runoff'] ) # * (area * 1e6)
            # Smod['groundwater_storage'] = Smod['groundwater_storage']/(Smod['groundwater_storage'].mean())
            Smod['groundwater_storage'] = Smod['groundwater_storage']
            per = 1
            Smod['dQ'] = Smod['outflow_drain'].diff()
            Smod['dGW'] = Smod['groundwater_storage'].diff()
            Smod['t'] = abs((Smod['groundwater_storage'].diff(periods=per) / Smod['outflow_drain'].diff(periods=per)))
            Smod = select_period(Smod, 1975,2099)
            
            acc_npy = np.load(BV.simulations_folder+'/'+model_name+'/_postprocess/'+'accumulation_flux.npy', allow_pickle=True).item()

            begin_h = 5*12
            end_h = 35*12
            # begin_h = 25*12
            # end_h = 55*12
            # begin_h = 3*12
            # end_h = 38*12
            # begin_f = -60*12
            # end_f = -30*12
            begin_f = -30*12
            end_f = 0
            # begin_f = -60*12
            # end_f = -30*12
            
            h_son, f_son, ano_son, son = season_anomaly([8,9,10], begin_h, end_h, begin_f, end_f)
            # plt.plot(son)
            # print(len(son))
            h_djf, f_djf, ano_djf, djf = season_anomaly([11,0,1], begin_h, end_h, begin_f, end_f)
            # plt.plot(djf)
            # print(len(djf))
            h_mam, f_mam, ano_mam, mam = season_anomaly([2,3,4], begin_h, end_h, begin_f, end_f)
            # plt.plot(mam)
            # print(len(mam))
            h_jja, f_jja, ano_jja, jja = season_anomaly([5,6,7], begin_h, end_h, begin_f, end_f)
            # plt.plot(jja)
            # print(len(jja))
            
            # h_jja, f_jja, ano_jja, jja = season_anomaly([0,1,2,3,4,5,6,7,8,9,10,11], begin_h, end_h, begin_f, end_f)
            # h_jja, f_jja, ano_jja, jja = season_anomaly([m,m,m], begin_h, end_h, begin_f, end_f)
                                    
            df_ano['SON_'+mod+'_'+sce] = pd.Series(son)
            df_ano['DJF_'+mod+'_'+sce] = pd.Series(djf)
            df_ano['MAM_'+mod+'_'+sce] = pd.Series(mam)
            df_ano['JJA_'+mod+'_'+sce] = pd.Series(jja)
          
            _SON_h.append(h_son)
            _DJF_h.append(h_djf)
            _MAM_h.append(h_mam)
            _JJA_h.append(h_jja)
            
            _SON_f.append(f_son)
            _DJF_f.append(f_djf)
            _MAM_f.append(f_mam)
            _JJA_f.append(f_jja)
            
            _SON_ano.append(ano_son)
            _DJF_ano.append(ano_djf)
            _MAM_ano.append(ano_mam)
            _JJA_ano.append(ano_jja)

    _SON_h_mean = sum(_SON_h)/len(_SON_h)
    _DJF_h_mean = sum(_DJF_h)/len(_DJF_h)
    _MAM_h_mean = sum(_MAM_h)/len(_MAM_h)
    _JJA_h_mean = sum(_JJA_h)/len(_JJA_h)
    
    _SON_f_mean = sum(_SON_f)/len(_SON_f)
    _DJF_f_mean = sum(_DJF_f)/len(_DJF_f)
    _MAM_f_mean = sum(_MAM_f)/len(_MAM_f)
    _JJA_f_mean = sum(_JJA_f)/len(_JJA_f)
    
    # _SON_ano_mean = sum(_SON_ano)/len(_SON_ano)
    # _DJF_ano_mean = sum(_DJF_ano)/len(_DJF_ano)
    # _MAM_ano_mean = sum(_MAM_ano)/len(_MAM_ano)
    # _JJA_ano_mean = sum(_JJA_ano)/len(_JJA_ano)
     
    _SON_ano_mean = ( _SON_f_mean - _SON_h_mean ) / _SON_h_mean
    _DJF_ano_mean = ( _DJF_f_mean - _DJF_h_mean ) / _DJF_h_mean
    _MAM_ano_mean = ( _MAM_f_mean - _MAM_h_mean ) / _MAM_h_mean
    _JJA_ano_mean = ( _JJA_f_mean - _JJA_h_mean ) / _JJA_h_mean
    
    for season, days_flux_h, days_flux_f, days_flux_ano in zip(['SON', 'DJF', 'MAM', 'JJA'],
                                                                [_SON_h_mean, _DJF_h_mean, _MAM_h_mean, _JJA_h_mean],
                                                                [_SON_f_mean, _DJF_f_mean, _MAM_f_mean, _JJA_f_mean],
                                                                [_SON_ano_mean, _DJF_ano_mean, _MAM_ano_mean, _JJA_ano_mean]):

    # # for season, days_flux_h, days_flux_f, days_flux_ano in zip(['DJF',  'JJA'],
    # #                                                             [_DJF_h_mean, _JJA_h_mean],
    # #                                                             [_DJF_f_mean, _JJA_f_mean],
    # #                                                             [_DJF_ano_mean, _JJA_ano_mean]):
                
    # for season, days_flux_h, days_flux_f, days_flux_ano in zip(['JJA'],
    #                                                             [_JJA_h_mean],
    #                                                             [_JJA_f_mean],
    #                                                             [_JJA_ano_mean]):
        
        fig, ax = plt.subplots(1,1, figsize=(10,10))
        
        stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'  # necessary for plots
        line = imageio.imread(stable_folder+'geographic/'+'watershed_contour.tif')
        line = np.ma.masked_where(line < 0, line)
        mask = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
        
        # cmap = plt.cm.Oranges_r
        # cmaplist = [cmap(i) for i in range(cmap.N)]
        # cmaplist = ['darkred','red']
        # # cmaplist[-1] = (.5, .5, .5, 1.0) # first value
        # cmap = mpl.colors.LinearSegmentedColormap.from_list(
        #     'Custom cmap', cmaplist, cmap.N)
        # minn = -1.01 # 0 
        # maxn = 0 # 1.1
        # intn = 0.1 # 0.1
        # bounds = np.arange(minn, maxn, intn)
        # norm = mpl.colors.BoundaryNorm(bounds, cmap.N)
        # pcn = ax.imshow(np.ma.masked_where(days_flux_ano >= 0, days_flux_ano), #1
        #                 cmap = cmap,
        #                 norm=norm, alpha=1)
        # # plt.imshow(days_flux_ano)
        # # plt.colorbar()
        
        # cmap = plt.cm.Blues
        # # cmap = plt.cm.winter_r
        # cmaplist = [cmap(i) for i in range(cmap.N)]
        # cmaplist = ['dodgerblue','navy']
        # # cmaplist[-1] = (.5, .5, .5, 1.0) # first value
        # cmap = mpl.colors.LinearSegmentedColormap.from_list(
        #     'Custom cmap', cmaplist, cmap.N)
        # minp = 0 # 1
        # maxp = 1.01 # 2.1
        # intp = 0.1 # 0.1
        # bounds = np.arange(minp, maxp, intp)
        # norm = mpl.colors.BoundaryNorm(bounds, cmap.N)
        # # pcp = ax.imshow(np.ma.masked_where(days_flux_ano <= 0, days_flux_ano), #1
        # #                 cmap = cmap,
        # #                 norm=norm, alpha=1)
        
        # plt.imshow(np.ma.masked_where(days_flux_ano <= 0, days_flux_ano))
        # plt.colorbar()
        
        pc = ax.imshow(np.ma.masked_where((days_flux_ano>-1),
                                          days_flux_ano),
                                    cmap = mpl.colors.ListedColormap('darkred'))
        
        pc = ax.imshow(np.ma.masked_where((days_flux_ano<=-1)|(days_flux_ano>=0),
                                          days_flux_ano),
                                    cmap = mpl.colors.ListedColormap('red'))
        
        pc = ax.imshow(np.ma.masked_where((days_flux_ano<=0)|(days_flux_ano>=1),
                                          days_flux_ano),
                                    cmap = mpl.colors.ListedColormap('dodgerblue'))
        
        pc = ax.imshow(np.ma.masked_where((days_flux_ano<1),
                                          days_flux_ano),
                                    cmap = mpl.colors.ListedColormap('dodgerblue'))
        
        pc = ax.imshow(np.ma.masked_where((days_flux_ano!=0)|(days_flux_h==0),
                                          days_flux_ano),
                                    cmap = mpl.colors.ListedColormap('grey'))
        
        pc = ax.imshow(np.ma.masked_where((days_flux_f==0)|(days_flux_h!=0),
                                          days_flux_f),
                                    cmap = mpl.colors.ListedColormap('navy'))
        
        # try:
        #     days = days_flux_ano.copy()
        #     days[(days_flux==0)|(days_flux_h!=0)] = np.nan
        #     plt.imshow(days, cmap = mpl.colors.ListedColormap('k'))
        # except:
        #     pass
        
        ax.get_xaxis().set_visible(False)
        ax.get_yaxis().set_visible(False)
        ax.axis('off')
        
        ax.imshow(line, cmap=mpl.colors.ListedColormap('k'))
        
        plt.subplots_adjust(hspace = -0.6)
                        
        # position=fig1.add_axes([1,0.3,0.015,0.32])  ## the parameters are the specified position you set 
        # cb = fig1.colorbar(pcp,cax=position) ##
        # cb.set_ticks(np.arange(minp, maxp, intp))
        # cb.set_ticklabels(np.arange(minp, maxp, intp).round(1))
        # # cb.ax.invert_xaxis()
        
        # position=fig1.add_axes([1.10,0.3,0.015,0.32])  ## the parameters are the specified position you set 
        # cb = fig1.colorbar(pcn,cax=position) ##   
        # cb.set_ticks(np.arange(minn, maxn, intn))
        # cb.set_ticklabels(np.arange(minn, maxn, intn).round(1))
        
        # ax.set_title(mod+'_'+sce+'_'+str(m), fontsize=8)
        
        ax.set_title(mod+'_'+sce+'_'+str(season), fontsize=8)

#%% MONTHLY EVOLUTION INF Q10

sce_list = ['RCP26','RCP85']
sce_list = ['RCP85']

stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
color = 'k'
BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=dem_path, 
                              out_path=out_path,
                              load=True)
mask_lasset = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
mask_grenou = imageio.imread(stable_folder+'subbasin/subbasin_Qgrenou/'+'watershed_dem.tif')
mask_bombee = imageio.imread(stable_folder+'subbasin/subbasin_Qbombee/'+'watershed_dem.tif')
mask_breton = imageio.imread(stable_folder+'subbasin/subbasin_Qbreton/'+'watershed_dem.tif')
dem_box = imageio.imread(stable_folder+'geographic/'+'watershed_box_buff_dem.tif')
area = BV.geographic.area
area = int(round(area))

per = [1975,2100]

for ic, sce in enumerate(sce_list):
    years = pd.date_range(start='01/01/1975', end='31/12/2099', freq='M').year.unique()
    df_yearly = pd.DataFrame(np.nan, index=Smod.index, columns=years)
    df_pi = pd.DataFrame(np.nan, index=range(len(mask.flatten())), columns=years)
    
    print(sce)
    
    for id_mod_val in list_id_mod[:]:
    
        h5file = BV.simulations_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)+'_ALL_'+sce
        d = dd.io.load(h5file)
        list_model_name = d['list_model_name'][:]
        list_model_success = d['list_model_success'][:]
        list_model_modflow = d['list_model_modflow'][:]
        
        for model_name, model_success, model_modflow in zip(list_model_name[:],
                                                            list_model_success[:],
                                                            list_model_modflow[:]):
            
            Smod = pd.read_csv(BV.simulations_folder+'/'+model_name+'/_postprocess/_timeseries/_simulated_timeseries.csv', sep=';',
                               index_col='date', parse_dates=True)
                
            # Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            Smod['prop_ratio'] = Smod.intermit_areas / Smod.total_areas
            Smod['recharge'] = Smod['recharge'] * 1000 * 30
            Smod['outflow_drain'] =  ( Smod['outflow_drain'] ) *1000 * 30 #* (area * 1e6) #+ Smod['runoff'] ) # * (area * 1e6)
            Smod['groundwater_storage'] = Smod['groundwater_storage']
            Smod = select_period(Smod, 1975,2099)
            
            df_rec = pd.DataFrame()
            
            # fig, ax = plt.subplots(1,1, figsize=(6,3))
            
            val_quant = 0.10
                            
            d = Smod.copy()
            # d = d.resample('M').sum()
            
            var = 'outflow_drain'
            
            quant = select_period(d[var],
                                  1980, 2004).quantile(val_quant)

            cond = quant
        
            d = d[(d.index.year>=per[0]) & (d.index.year<=per[1])]
            d = d.filter(regex=var)
            
            # if typ == 'DAYON':
            
            d[var+'_'+'historic'] = d[var]
            d[var+'_'+sce] = d[var]
                
            d[var+'_'+'historic'][(d.index.year)>=2005] = np.nan
            d[var+'_'+sce][(d.index.year)<2005] = np.nan
        
            d = pd.concat((d.filter(regex=var+'_'+sce),
                            d.filter(regex=var+'_'+'historic')), axis=1).mean(axis=1).to_frame()
            
            ish = (d.filter(regex=var+'_'+'historic')).dropna().shape[1]
            isf = (d.filter(regex=var+'_'+sce)).dropna().shape[1]
                
            # print(mod, sce, ish, isf, d.shape)
        
            # plt.plot(d)
        
            d.columns = [var+'_'+sce]
            d = d.round(2)
            
            x = d.copy()
            x['counter'] = x.diff().ne(0).cumsum()
            
            d['diff'] = d.diff()
            
            years = d.index.year.unique()
            
            # fig, ax = plt.subplots(1,1, figsize=(6,3))
            # axs = axs.ravel()
            n = len(years)
            cmap = cm.get_cmap('jet', n)
            
            max_consec_list = []
            min_consec_list = []
            
            counts = []
            for i, year in enumerate(years):
            
                each = d[d.index.year==year]
                
                count = ((each['diff'] <= 0) & (each[var+'_'+sce] <= cond)).astype(int).sum(axis=0)
            
                counts.append(count)
                
                new = x[x.index.year==year]
                df2 = new.groupby('counter')[var+'_'+sce].min().to_frame(name='value').join(
                      new.groupby('counter')[var+'_'+sce].count().rename('number'))
                max_consec0 = df2[df2['value']<=quant]['number'].tolist()
                if var =='ETP':
                    max_consec0 = df2[df2['value']>=quant]['number'].tolist()
                max_consec1 = df2[df2['value']==1]['number'].tolist()
                try:
                    max_consec_list.append(max(max_consec0))
                except:
                    max_consec_list.append(np.nan)
                    pass
                # min_consec_list.append(min(max_consec0))
                
                # ax = axs[0]
                # ax.plot(each['diff'].values, c=cmap(i), lw=0.5)
                # ax.set_xlim(0,365)
                # ax.set_ylabel('Diff. day before')
                # ax.set_title(var)
                
                # ax = axs[1]
                # ax.plot(max_consec0, c=cmap(i), lw=0.5)
                # ax.set_ylabel('Max consec. 0')
                # ax.set_title(var)
            
            df_rec[mod] = counts
            
            # ax.set_xlim(0, None)
            # ax.set_ylim(0, None)
        
            df_rec.index = years
            # df_rec.boxplot()
            
            x = df_rec.copy()
            x['med'] = df_rec.quantile(0.50, axis=1)
            x['med'] = df_rec.mean(axis=1)
            # threshold = 60
            # x['cond'] = False
            # x['cond'][x[mod] >= 60] = True 
            x['cond'] = np.nan
            x['cond'][x['med']<60] = 0
            x['cond'][x['med']>=60] = 1
            # x['consecutive'] = x['cond'].groupby((x['cond'] != x['cond'].shift()).cumsum()).transform('size') * x['cond']
            # x['consecutive'] = (x['cond'].groupby((x['cond'] != x['cond'].shift()).cumsum()).transform('size') * x['cond'] >= 1).astype(int)
            # x['cumsum'] = x[mod].cumsum()
            # x['diff'] = x[mod].diff()
            # x['cond'] = np.nan
            x['cons'] = 0
            for j in x.index:
                # print(j)
                if j > x.index[0]:
                    if (x.loc[j,'cond'] == 1) & (x.loc[j-1,'cond'] == 1):
                        x.loc[j,'cons'] = 1
            # y = pd.concat([x[mod], x[mod].diff().ne(0).cumsum()], axis=1)
            l = []
            for p in [[1975,2010],[2010,2040],[2040,2070],[2070,2100]]:
                v_cond = x[(x.index>=p[0])&(x.index<=p[1])].groupby(x['cond'].diff().ne(0).cumsum()).sum().sum()
                val_cond = v_cond['cond'] #/ (p[1]-p[0])
                v_cons = x[(x.index>=p[0])&(x.index<=p[1])].groupby(x['cons'].diff().ne(0).cumsum()).sum().sum()
                val_cons = v_cons['cons'] #/ (p[1]-p[0])
                y = x[(x.index>=p[0])&(x.index<=p[1])]['cond']
                v_maxi = y.groupby((y != y.shift()).cumsum()).transform('size') * y
                val_maxi = v_maxi.max()
                # print(p, val_cond.round(3), val_cons.round(3), val_maxi.round(3))
                # l.append(val_cond.round(3))
                # l.append(val_cons.round(3))
                # l.append(val_maxi.round(3))
                l.append(round(val_cond,3))
                l.append(round(val_cons,3))
                l.append(round(val_maxi,3))
            
            df_rec = df_rec.T
            
            # df_rec.boxplot()
            
            fig, ax = plt.subplots(1,1, figsize=(10,4))
            
            ax.set_title(l, fontsize=6)
            
            import matplotlib
            normaliz = plt.Normalize(df_rec.median().min(), df_rec.median().max())
            norm = matplotlib.colors.Normalize(vmin=0, vmax=120)
            # if sce == 'RCP2.6':
            #     to_norm = df_rec.median()
            colors = plt.cm.jet(norm(df_rec.median()))
            # colors = plt.cm.jet(norm([60] * len(df_rec.columns)))
            # colors = plt.cm.jet(norm(to_norm))
            
            medianprops = dict(linestyle='-', linewidth=1, color='black')
            meanpointprops = dict(markersize=0, marker='o', markeredgecolor='black',
                                  markerfacecolor='k', linestyle='-')
            
            ax.vlines(x=years, 
                        ymin=df_rec.quantile(0.75), 
                        ymax=df_rec.quantile(0.95), color='k', zorder=2)
            ax.vlines(x=years, 
                        ymin=df_rec.quantile(0.05), 
                        ymax=df_rec.quantile(0.25), color='k', zorder=2)
            
            # boxprops = dict(linestyle='-', linewidth=1, color='k',
            #                 facecolor='cyan', alpha=0.5)
            # bp = ax.boxplot(df_rec, widths=0.75,
            #                 positions=years,
            #                   whis=False, showfliers=False, showmeans=False, 
            #                   medianprops=medianprops, meanprops=meanpointprops,
            #                   patch_artist=True, boxprops=boxprops)
            
            for i in range(len(years)):
                # print(i)
                boxprops = dict(linestyle='-', linewidth=1, color='k',
                                facecolor=colors[i], 
                                alpha=0.5)
                bp = ax.boxplot(df_rec.iloc[:,i], widths=0.75,
                                positions=[df_rec.columns[i]],
                                  whis=False, showfliers=False, showmeans=False, 
                                  medianprops=medianprops, meanprops=meanpointprops,
                                  patch_artist=True, boxprops=boxprops)
            
            ax.plot(years, df_rec.mean(), marker='o', mec='k', ms=1.5, lw=0,
                    mfc='k', mew=1,
                    color='k', zorder=1000)
              
            for element in bp['whiskers']:
                element.set_color('k')
                element.set_linestyle('-')
            # for patch in bp['boxes']:
            #     patch.set(facecolor='r')    
            ax.set_xticks(np.arange(1980, 2100+1, 10))
            ax.set_xticklabels(np.arange(1980, 2100+1, 10))
            
            # ax.get_xaxis().set_visible(False)
            # ax.set_yscale('log')
            
            ax.set_ylim(-5, 180)
            ax.set_yticks(np.arange(0, 180+1, 30))
            
            ax.set_xlim(1974,2100)
            ax.tick_params(axis='x', which='minor')
            
            from matplotlib.ticker import (MultipleLocator)
            ax.xaxis.set_minor_locator(MultipleLocator(1))
            
            ax.set_axisbelow(True)
            # ax.grid(zorder=-1000)
            ax.xaxis.grid(color='gray', alpha=0.2, zorder=-20)
            ax.yaxis.grid(color='gray', alpha=0.2, zorder=-20, which='both')
            
            # ax.set_title(var+' - '+mod)
            # ax.set_xlim(pd.to_datetime('1974'), pd.to_datetime('2100'))
            
            plt.tight_layout()

#%% FIND DROUGHTS IN THE PAST

# all_proj = pd.read_csv(BV.stable_folder + '/driasclimat/' + '_ALL_D.csv', sep=';', index_col=0, parse_dates=True)
all_proj =  pd.read_csv(BV.stable_folder + '/driaseau/' + '_ALL_D.csv', sep=';', index_col=0, parse_dates=True)

mod = 'REA'
sce = 'historic'
var = 'REC'
per = [1960,2020]

d = dfd.copy()

fig, ax = plt.subplots(1,1, figsize=(5,3))

val_quants = [0.01, 0.1]
# val_quants = [0, 0.25]
# val_quants = [0.99, 0.95]

for val_quant in val_quants:
    
    quant = select_period(d[var+'_'+mod+'_'+sce],
                          1980 ,2010).quantile(val_quant)
    
    if val_quant == 0:
        val_quant = 0
            
    d = d[(d.index.year>=per[0]) & (d.index.year<=per[1])]
    d = d.filter(regex=var+'_'+mod+'_'+sce)
    d = d.round(2)
    
    x = d.copy()
    x['counter'] = x.diff().ne(0).cumsum()
    
    d['diff'] = d.diff()
                          
    # quant = d[var+'_'+mod+'_'+sce].min()
    if var == 'ETP':
        quant = d[var+'_'+mod+'_'+sce].quantile(val_quant)
        # quant = d[var+'_'+mod+'_'+sce].max()
    cond = quant
    
    if (var =='PPT') | (var == 'REC'):
        cond = quant
    
    # cond = 0
    
    years = d.index.year.unique()
    
    # fig, ax = plt.subplots(1,1, figsize=(5,3))
    # axs = axs.ravel()
    n = len(years)
    cmap = cm.get_cmap('jet', n)
    
    max_consec_list = []
    min_consec_list = []
    
    counts = []
    for i, year in enumerate(years):
    
        each = d[d.index.year==year]
        # count = ((each['diff'] <= cond) & (each[var+'_'+mod+'_'+sce] <= cond)).astype(int).sum(axis=0)
        count = ((each[var+'_'+mod+'_'+sce] <= cond)).astype(int).sum(axis=0)
        if var =='ETP':
            test = ((each['diff'] <= cond) & (each[var+'_'+mod+'_'+sce] >= cond)).astype(int)
            count = ((each['diff'] <= cond) & (each[var+'_'+mod+'_'+sce] >= cond)).astype(int).sum(axis=0)
        counts.append(count)
        
        new = x[x.index.year==year]
        df2 = new.groupby('counter')[var+'_'+mod+'_'+sce].min().to_frame(name='value').join(new.groupby('counter')[var+'_'+mod+'_'+sce].count().rename('number'))
        max_consec0 = df2[df2['value']<=quant]['number'].tolist()
        if var =='ETP':
            max_consec0 = df2[df2['value']>=quant]['number'].tolist()
        max_consec1 = df2[df2['value']==1]['number'].tolist()
        try:
            max_consec_list.append(max(max_consec0))
        except:
            max_consec_list.append(np.nan)
            pass
        # min_consec_list.append(min(max_consec0))
        
        # ax = axs[0]
        # ax.plot(each['diff'].values, c=cmap(i), lw=0.5)
        # ax.set_xlim(0,365)
        # ax.set_ylabel('Diff. day before')
        # ax.set_title(var)
        
        # ax = axs[1]
        # ax.plot(max_consec0, c=cmap(i), lw=0.5)
        # ax.set_ylabel('Max consec. 0')
        # ax.set_title(var)
        
    # ax.set_xlim(0, None)
    # ax.set_ylim(0, None)
        
    # ax.plot(pd.to_datetime(years, format='%Y'), counts, c='k', lw=2)
    if val_quant == val_quants[0]:
        col = 'darkorange'
        ax.bar(pd.to_datetime(years, format='%Y'), counts,
               align='center', color=col, width=280, lw=0.5, zorder=10)
    if val_quant == val_quants[1]:
        col = 'lightgrey'
        ax.bar(pd.to_datetime(years, format='%Y'), counts,
               align='center', color=col, width=280, lw=0.5, zorder=0)
    
# ax.fill_between(pd.to_datetime(years, format='%Y'), counts, np.array(counts)-
#                 np.array(max_consec_list), lw=0, color='cyan')
# ax.bar(pd.to_datetime(years, format='%Y'), np.array(max_consec_list), color='white',
#        width=300)
# axb = ax.twinx()
# ax.plot(pd.to_datetime(years, format='%Y'), np.array(counts)-
#                 np.array(max_consec_list), c='b', lw=1)
# axb.plot(pd.to_datetime(years, format='%Y'), max_consec_list, c='red', lw=2)
# ax.set_ylim(1,182)
# axb.set_ylim(1,182)
# ax.set_ylabel('>= 2 days consec.'+' = '+str(cond))
ax.set_title(var)
ax.set_xlim(pd.to_datetime('1959'), pd.to_datetime('2021'))

# if (var=='PPT') | (var=='REC'):
#     ax.set_ylim(0,180)
#     ax.set_yticks(np.arange(0, 180+1, 30))

ax.set_axisbelow(True)
# ax.grid(zorder=-1000)
ax.xaxis.grid(color='gray', alpha=0.2, zorder=-20)
ax.yaxis.grid(color='gray', alpha=0.2, zorder=-20, which='both')

plt.tight_layout()

#%% ---- NOTES

#%% DOWNSLOPE PERSISTENCY

wbt.verbose = False

iD_explos = ['e_isba1']
iD_explos = ['e_isba2']


init_path = data_path + '_Q/'

Qobs_list = ['lasset_Q_Day.Cmd.txt']
Qobs_name = Qobs_list[0]

couleurs = ['navy','darkviolet']
areas = [3.7]

df = pd.DataFrame()

dict_Q_wname = {}

list_por = [] 
list_doptim_per = []
list_doptim_int = []
list_doptim_bot = []

list_pso_per = []
list_pos_per = []
list_iso_int = []
list_ios_int = []

for w, w_name in enumerate(['Lasset'][:]):
    
    # BV = watershed_root.Watershed(watershed_name=watershed_name, dem_path=dem_path, out_path=out_path, load=True)

    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' # necessary for plots
    BV.calibration_folder = out_path+'/'+watershed_name+'/'+'results_calibration/'
    
    dfQ = pd.read_csv(init_path+Qobs_name, sep=';', parse_dates=True, index_col='date_temp') # m3/d
    Qobs = dfQ.q / (areas[0]*1e6)
    Qobs_w_off = Qobs.resample('W', label='right', closed='left', loffset=pd.DateOffset(days=3)).mean() # loffset='2T'
    Qobs_w_sli = Qobs.groupby(np.arange(len(Qobs))//7).mean()
    Qobs_w_sli.index = Qobs_w_off.iloc[:-1].index
    Qobs_w_sli = Qobs_w_sli.iloc[:-1]
    Qobs = Qobs_w_sli.copy() * 1000 * 7
    # Qobs = Qobs.resample('M').mean()*4
    
    stable_folder_arbit = 'E:/_RONAN/_E_SIMULATIONS/LASSET/Lasset_25m/results_calibration/isba1_model4_20.0-0_12-3.90e-06/_matchingstreams/'
    
    obsflow_path_per = stable_folder_arbit+'obsflow.tif'
    obsflow_path_int = stable_folder_arbit+'obsflow.tif'
    obsflow_per = imageio.v2.imread(obsflow_path_per)
    obsflow_int = imageio.v2.imread(obsflow_path_int)
    obsflow_path_per_buff = stable_folder_arbit+'obsflow_buff.tif'
    obsflow_path_int_buff = stable_folder_arbit+'obsflow_buff.tif'
    toolbox.export_tif(stable_folder+"geographic/watershed_box_buff_dem.tif", obsflow_per, -32768, obsflow_path_per_buff)
    toolbox.export_tif(stable_folder+"geographic/watershed_box_buff_dem.tif", obsflow_int, -32768, obsflow_path_int_buff)
    
    obsflow_path_per = stable_folder+'hydrography/hydrographic_mix_peren_upv1_pt.shp'
    obsflow_path_per_buff = stable_folder+'hydrography/hydrographic_mix_peren_upv1_pt_buff.tif'
    wbt.trace_downslope_flowpaths(
        obsflow_path_per, 
        BV.geographic.watershed_box_buff_direc, 
        obsflow_path_per_buff)
    obsflow_per = imageio.v2.imread(obsflow_path_per_buff)
    obsflow_per_masked = np.ma.masked_array(obsflow_per, mask=obsflow_per<=0)
    obsflow_per = obsflow_per_masked.filled(np.nan)
    
    obsflow_path_int = stable_folder+'hydrography/hydrographic_mix_inter_upv1_pt.shp'
    obsflow_path_int_buff = stable_folder+'hydrography/hydrographic_mix_inter_upv1_pt_buff.tif'
    wbt.trace_downslope_flowpaths(
        obsflow_path_int, 
        BV.geographic.watershed_box_buff_direc, 
        obsflow_path_int_buff)
    obsflow_int = imageio.v2.imread(obsflow_path_int_buff)
    obsflow_int_masked = np.ma.masked_array(obsflow_int, mask=obsflow_int<=0)
    obsflow_int = obsflow_int_masked.filled(np.nan)
    
    dem = imageio.v2.imread(BV.geographic.watershed_dem)
    dem_masked = np.ma.masked_array(dem, mask=dem<=0)
    dem_cell = dem_masked.count()
    # print(dem_cell)


    i = 0
    
    for iD_explo in iD_explos:
        
        if iD_explo == 'e_isba1':
            list_id_mod = [4]
        if iD_explo == 'e_isba2':
            list_id_mod = [6]
        
        for id_mod_val in list_id_mod[:]:
        
            h5file = BV.calibration_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)
            # d = dd.io.load(h5file)
            list_model_name = d['list_model_name'][:]
            list_model_success = d['list_model_success'][:]
            list_model_modflow = d['list_model_modflow'][:]
            
            for model_name, model_success, model_modflow in zip(list_model_name[:20],
                                                                list_model_success[:20],
                                                                list_model_modflow[:20]):
                print(model_name)
                Smod = pd.read_csv(BV.calibration_folder+'/'+model_name+'/_postprocess/_timeseries/_simulated_timeseries.csv', sep=';',
                                   index_col='date', parse_dates=True)
                
                simul_path = BV.calibration_folder+'/'+model_name+'/'

                pi_path = BV.calibration_folder+'/'+model_name+'/'+'_postprocess/_rasters/persistency_index_t(-).tif'
                pi = imageio.v2.imread(pi_path)
                pi_masked = np.ma.masked_array(pi, mask=dem<=0)
                pi_masked = np.ma.masked_array(pi_masked, mask=pi_masked<=0)
                pi_masked_per = np.ma.masked_array(pi_masked, mask=pi_masked<0.5)
                # pi_masked_int = np.ma.masked_array(pi_masked, mask=pi_masked>=0.5)
                pi_masked_int = pi_masked.copy()
                # pi_masked_int = np.ma.masked_array(pi_masked, mask=pi_masked<0.33)
                pi_cell_per = pi_masked_per.count()
                pi_cell_int = pi_masked_int.count()
                # pi_cell_per>0 = 1
                pi_masked_per = pi_masked_per.filled(np.nan)    
                pi_masked_int = pi_masked_int.filled(np.nan)    
                print('  ', pi_cell_per/dem_cell, pi_cell_int/dem_cell)
                
                pi_path_per = BV.calibration_folder+'/'+model_name+'/'+'_postprocess/_rasters/persistency_index_per_t(-).tif'
                pi_path_int = BV.calibration_folder+'/'+model_name+'/'+'_postprocess/_rasters/persistency_index_int_t(-).tif'
                toolbox.export_tif(stable_folder+"geographic/watershed_dem.tif", pi_masked_per, -9999, pi_path_per)
                toolbox.export_tif(stable_folder+"geographic/watershed_dem.tif", pi_masked_int, -9999, pi_path_int)
                
                dem_to_obs_per_path = BV.calibration_folder+'/'+model_name+'/'+'_postprocess/_rasters/dem_to_obsper_t(-).tif'
                dem_to_obs_int_path = BV.calibration_folder+'/'+model_name+'/'+'_postprocess/_rasters/dem_to_obsint_t(-).tif'
                wbt.downslope_distance_to_stream(BV.geographic.watershed_box_buff_fill, obsflow_path_per_buff, dem_to_obs_per_path)
                wbt.downslope_distance_to_stream(BV.geographic.watershed_box_buff_fill, obsflow_path_int_buff, dem_to_obs_int_path)
                
                dist_to_obs_per_path = BV.calibration_folder+'/'+model_name+'/'+'_postprocess/_rasters/simper_to_obsper_t(-).tif'
                dem_to_obs_per = imageio.v2.imread(dem_to_obs_per_path)
                sim_to_obs_per = np.ma.masked_array(dem_to_obs_per, mask=np.isnan(pi_masked_per))
                sim_to_obs_per = sim_to_obs_per.filled(np.nan)    
                toolbox.export_tif(stable_folder+"geographic/watershed_dem.tif", sim_to_obs_per, -9999, dist_to_obs_per_path)
                
                dist_to_obs_int_path = BV.calibration_folder+'/'+model_name+'/'+'_postprocess/_rasters/simint_to_obsint_t(-).tif'
                dem_to_obs_int = imageio.v2.imread(dem_to_obs_int_path)
                sim_to_obs_int = np.ma.masked_array(dem_to_obs_int, mask=np.isnan(pi_masked_int))
                sim_to_obs_int = sim_to_obs_int.filled(np.nan)    
                toolbox.export_tif(stable_folder+"geographic/watershed_dem.tif", sim_to_obs_int, -9999, dist_to_obs_int_path)
                
                dem_to_sim_per_path = BV.calibration_folder+'/'+model_name+'/'+'_postprocess/_rasters/dem_to_simper_t(-).tif'
                dem_to_sim_int_path = BV.calibration_folder+'/'+model_name+'/'+'_postprocess/_rasters/dem_to_simint_t(-).tif'
                wbt.downslope_distance_to_stream(BV.geographic.watershed_box_buff_fill, pi_path_per, dem_to_sim_per_path)
                wbt.downslope_distance_to_stream(BV.geographic.watershed_box_buff_fill, pi_path_int, dem_to_sim_int_path)
                
                dist_to_sim_per_path = BV.calibration_folder+'/'+model_name+'/'+'_postprocess/_rasters/obsper_to_simper_t(-).tif'
                dem_to_sim_per = imageio.v2.imread(dem_to_sim_per_path)
                obs_to_sim_per = np.ma.masked_array(dem_to_sim_per, mask=np.isnan(obsflow_per))
                obs_to_sim_per = obs_to_sim_per.filled(np.nan)
                obs_to_sim_per = np.where(obs_to_sim_per < 0, np.nan, obs_to_sim_per)
                toolbox.export_tif(stable_folder+"geographic/watershed_dem.tif", obs_to_sim_per, -99999, dist_to_sim_per_path)
                
                dist_to_sim_int_path = BV.calibration_folder+'/'+model_name+'/'+'_postprocess/_rasters/obsint_to_simint_t(-).tif'
                dem_to_sim_int = imageio.v2.imread(dem_to_sim_int_path)
                obs_to_sim_int = np.ma.masked_array(dem_to_sim_int, mask=np.isnan(obsflow_int))
                obs_to_sim_int = obs_to_sim_int.filled(np.nan)
                obs_to_sim_int = np.where(obs_to_sim_int < 0, np.nan, obs_to_sim_int)
                toolbox.export_tif(stable_folder+"geographic/watershed_dem.tif", obs_to_sim_int, -99999, dist_to_sim_int_path)
                
                p_so = imageio.v2.imread(dist_to_obs_per_path)
                i_so = imageio.v2.imread(dist_to_obs_int_path)
                p_os = imageio.v2.imread(dist_to_sim_per_path)
                i_os = imageio.v2.imread(dist_to_sim_int_path)
                
                # print('     ',(np.nanmean(p_so)+np.nanmean(p_os))/2, (np.nanmean(i_so)+np.nanmean(i_os))/2, (((np.nanmean(p_so)+np.nanmean(p_os))/2)+((np.nanmean(i_so)+np.nanmean(i_os))/2))/2)
                
                list_pso_per.append(np.nanmean(p_so))
                list_pos_per.append(np.nanmean(p_os))
                list_iso_int.append(np.nanmean(i_so))
                list_ios_int.append(np.nanmean(i_os))
                
                list_doptim_per.append((np.nanmean(p_so)+np.nanmean(p_os))/2)
                list_doptim_int.append((np.nanmean(i_so)+np.nanmean(i_os))/2)
                list_doptim_bot.append((((np.nanmean(p_so)+np.nanmean(p_os))/2)+((np.nanmean(i_so)+np.nanmean(i_os))/2))/2)

# TEST

plt.plot(list_porosity[:20], np.array(list_doptim_per), c='b', label='list_doptim_per')
plt.plot(list_porosity[:20], np.array(list_doptim_int), c='r', label='list_doptim_int')
plt.plot(list_porosity[:20], np.array(list_doptim_bot), c='k', label='list_doptim_bot')

plt.plot(list_porosity[:20], np.array(list_pso_per), c='green', label='list_pso_per')
plt.plot(list_porosity[:20], np.array(list_pos_per), c='limegreen', label='list_pos_per')
plt.plot(list_porosity[:20], np.array(list_iso_int), c='darkorange', label='list_iso_int')
plt.plot(list_porosity[:20], np.array(list_ios_int), c='gold', label='list_ios_int')

plt.axvline(1.6/100)

plt.legend()

#%% DENSITY CLC

# x = gpd.read_file('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_data/_sig/created/clc.shp')

# x['area'] = x['geometry'].area

# x = x.groupby('CODE_12').sum()

# x['a'] = x['area']/(x['area'].sum())*100

#%% DENSITY OBSFLOW 

# im_per = imageio.imread('E:/_RONAN/_E_SIMULATIONS/LASSET/Lasset_25m/results_calibration/isba2_model6_30.0-0_9-2.87e-06/_matchingstreams/obsflow.tif')
# im_int = imageio.imread('E:/_RONAN/_E_SIMULATIONS/LASSET/Lasset_25m/results_calibration/isbaint2_model6_30.0-0_10-1.80e-06/_matchingstreams/obsflow.tif')
# wt = imageio.imread(BV.geographic.watershed_dem)
# countwt = np.count_nonzero(wt>0)
# countimper = np.count_nonzero(im_per>0)
# countimint = np.count_nonzero(im_int>0)
# print(countimper/countwt, countimint/countwt)
