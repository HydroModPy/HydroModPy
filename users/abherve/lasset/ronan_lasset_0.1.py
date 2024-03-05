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
from src.watershed import climatic, driasclimat, driaseau, geographic, geology, geometric, hydraulic, \
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

git_path = 'D:/Users/abherve/GITHUB/HydroModPy-0.1/'
data_path = 'D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_data/'
# data_path = 'C:/Users/ronan/OneDrive/UNINE/8_Modeling/Lasset/_data/'
out_path = 'D:/Users/abherve/ONEDRIVE_UNINECHYN/OneDrive - unine.ch/SIMULATIONS/'
# out_path = 'C:/Users/ronan/OneDrive - unine.ch/SIMULATIONS/'

fig_path = out_path + 'figures/'

dem_name = 'BDALTI_09_25m.tif' # EUDTM_Alps_30m_vallon
dem_path = data_path +'_DEM/' + dem_name

subbasin_path = True # generate subbasins from stations or manual points
from_dem = None # True or False if the process start from a given DEM of xyz file
cell_size = None # specify new resolution from a given DEM or None
from_shp = None

watershed_names = [ 'Lasset' ]
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

BV.add_intermittency('None','None')
BV.add_subbasin(data_path+'_coordinates_additional/', sub_snap_dist=50)

#%% DATA

# GEOL

BV.add_geology(data_path+'_mix/', types_obs='GEO1M.shp', fields_obs='CODE_LEG')
visualization_watershed.watershed_geology(BV)

# HYDRO

hydrography_path = data_path + '_hydrography/' # add hydrographic shapefiles

types_obs = ['stream_perennial_wetlands_points']
# types_obs = ['stream_perennial_wetlands_osm_points']
fields_obs = ['fid']

for watershed_name in watershed_names[:]:
    
    print('##### '+watershed_name.upper()+' #####')
               
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True)

    BV.add_hydrography(hydrography_path, types_obs=types_obs, fields_obs=fields_obs)
    
    try:
        visualization_watershed.watershed_local(dem_path, BV)
        visualization_watershed.watershed_dem(BV)
    except:
        pass
    
    # wbt.find_main_stem(
    #     stable_folder+'geographic/'+'watershed_buff_direc.tif', 
    #     BV.hydrology.tif_streams, 
    #     stable_folder+'hydrology/'+types_obs[0]+'_main'+'.tif', 
    #     esri_pntr=False, 
    #     zero_background=False)

#%% OBSERVED

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

fig, axs = plt.subplots(1,2, figsize=(9,3),
                        # sharey=True
                        )
axs = axs.ravel()

for i, Qobs_name in enumerate(Qobs_list):
    dfQ = pd.read_csv(init_path+Qobs_name, sep=';', parse_dates=True, index_col='date_temp')

    zo = 1
    if i == 0:
        zo=2
        
    ax = axs[i]
    
    data_index = dfQ['q']/(areas[i]*1e6)*1000
    # data_index = select_period(data_index, 2017,2018)
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
    print(Q10.min())
    print(Q90.mean())
    Max = data_index.resample('Y').max()
    mean_interan_days = data_index.groupby([data_index.index.month,
                                    data_index.index.day], as_index=True).mean().to_frame()
    std_interan_days = data_index.groupby([data_index.index.month,
                        data_index.index.day], as_index=True).std()
    q10_interan_days = data_index.groupby([data_index.index.month,
                        data_index.index.day], as_index=True).quantile(0.10)
    q90_interan_days = data_index.groupby([data_index.index.month,
                        data_index.index.day], as_index=True).quantile(0.90)
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
            lw=2, color=couleurs[i], label=Qobs_name)
    yerrmax = mean_interan_days.q90
    yerrmin = mean_interan_days.q10
    # ax.legend('upper right')
    # ax.fill_between(mean_interan_days.counts, yerrmin, yerrmax,
    #                   color='cyan',edgecolor='grey',
    #                   alpha = 0.5, label='10-90th')
    
    ax.fill_between(mean_interan_days.counts, yerrmin, yerrmax,
                      color='gray',edgecolor='grey', lw=0.5,
                      alpha = 0.25, label='10-90th')
    
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
    ax.legend(loc='upper right', frameon=False)
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

#%% ISBA HYDRO LOAD

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

#%% ISBA HYDRO NORMALIZE

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

# f = dfSIM2['OBSER'].mean() / (dfSIM2['DRAIN']+dfSIM2['RUNOF']+dfSIM2['ECSNOW']).mean()
# f = dfSIM2['OBSER'].mean() / dfSIM2['PPT'].mean()
norm_factor = dfFTP['OBSER'].mean() / (dfFTP['DRAIN']+dfFTP['RUNOF']).mean()
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

#%% SIM2 HYDROCLIMAT LOAD

sim2_1 = pd.read_csv(data_path+'_SIM2/'+'QUOT_SIM2_2020_2023.csv', sep=';', parse_dates=True, index_col='DATE')
sim2_2 = pd.read_csv(data_path+'_SIM2/'+'QUOT_SIM2_2023_2024.csv', sep=';', parse_dates=True, index_col='DATE')

sim2 = pd.concat([sim2_1, sim2_2]).drop_duplicates()
# sim2 = pd.concat([sim2_1, sim2_2], verify_integrity=True)

dfd = sim2.copy()

dfm = dfd.copy()
mask = dfm.resample("M").count() >= 27
dfm = dfm.resample("M").mean()[mask]

dfm_surf = dfm.copy()

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

# SURFEX - PLOT RAW

plt.rcParams["axes.axisbelow"] = False

var_list2 = ['PRELIQ_Q','EVAP_Q','DRAINC_Q','RUNC_Q','PRENEI_Q']
couleurs = ['purple','darkorange','forestgreen','dodgerblue','grey']

fig, ax = plt.subplots(figsize=(8,4))
axb = ax.twinx()
for i, var in enumerate(var_list2):
    x = dfd[var]#.loc[start:end]
    if var == 'PRELIQ_Q' or var == 'PRENEI_Q':
        axb.plot(x, c=couleurs[i], label=var)
        axb.set_ylim(0,100)
        axb.legend(loc='upper right')
        axb.set_ylabel('PPT / SNOW [mm]')
    else:
        ax.plot(x, c=couleurs[i], label=var)
        ax.set_ylim(0,20)
        ax.legend(loc='lower left')
        ax.set_ylabel('ETR / RUN / REC [mm]')
    ax.set_xlabel('Date')	
    ax.set_xlim([pd.to_datetime(str(x.first_valid_index().year)), 
    pd.to_datetime(str(x.last_valid_index().year))])
    axb.invert_yaxis()
    # ax.set_title(mod + ' - ' + sce.upper())
    import matplotlib.dates as mdates
    years_maj = mdates.YearLocator()   # every year
    months_maj = mdates.MonthLocator()  # every x month
    ax.xaxis.set_major_locator(years_maj)
    ax.xaxis.set_minor_locator(months_maj)
    plt.tight_layout()
    
# SURFEX - PLOT BALANCE

df_intm = dfd.resample('M').mean()[dfd.resample("M").count() >= 27]
df_intm = df_intm.groupby([lambda x: x.month]).mean()

fig, ax = plt.subplots(1,1, figsize=(4,5))
axt = ax.twinx()
step = 'pre'

# axt.plot(df_intm.index,  ((df_intm['PRELIQ_Q']*30) + (df_intm['PRENEI_Q']*30)) - df_intm['EVAP_Q']*30,
#                 color='grey', alpha=1, lw=1, ls='-')
# axt.plot(df_intm.index,  ((df_intm['PRELIQ_Q']*30)) - df_intm['EVAP_Q']*30,
#                 color='purple', alpha=1, lw=1, ls='-')
# axt.plot(df_intm.index,  ((df_intm['PRELIQ_Q']*30)) + df_intm['PRENEI_Q']*30,
#                 color='k', alpha=1, lw=1, ls=':')
axt.fill_between(df_intm.index, 0, df_intm['PRELIQ_Q']*30,
                interpolate=False, color='purple', alpha=1, lw=3, ec='purple',
                fc='None',
                step=step)
axt.fill_between(df_intm.index, 0, df_intm['PRENEI_Q']*30,
                interpolate=False, color='grey', alpha=1, lw=3, ec='grey',
                fc='None',
                step=step)
axt.set_ylim(0,250)

ax.fill_between(df_intm.index, 0, df_intm['DRAINC_Q']*30,
                interpolate=False, color='forestgreen', alpha=1, lw=3, ec='forestgreen',
                fc='None',
                step=step)
ax.fill_between(df_intm.index, 0, df_intm['RUNC_Q']*30,
                interpolate=False, color='dodgerblue', alpha=1, lw=3, ec='dodgerblue',
                fc='None',
                step=step)
ax.set_ylim(0,250)

ax.plot(df_intm.index, df_intm['T_Q'],
                color='red', alpha=1, lw=3, zorder=1)
ax.plot(df_intm.index, df_intm['EVAP_Q']*30,
                color='darkorange', alpha=1, lw=3, zorder=-1)

ax.set_xticks(np.arange(1,13,1))
ax.set_xticklabels(['J','F','M','A','M','J','J','A','S','O','N','D'])
ax.set_xlim(1,12)

axt.invert_yaxis()

# SURFEX - PLOT INTERMENS

var_list = ['T_Q','PRELIQ_Q','PRENEI_Q','EVAP_Q','RUNC_Q','DRAINC_Q']
couleurs = ['red','purple','gray','darkorange','dodgerblue','forestgreen']

fig, axs = plt.subplots(6,1,figsize=(3.5,11), sharex=True, sharey=False)
# axb = ax.twinx()
axs = axs.ravel()

for i, var in enumerate(var_list):
    
    ax = axs[i]
    
    data_index = dfd[var]
    
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
    print(Q10.min())
    print(Q90.mean())
    Max = data_index.resample('Y').max()
    mean_interan_days = data_index.groupby([data_index.index.month,
                                    data_index.index.day], as_index=True).mean().to_frame()
    std_interan_days = data_index.groupby([data_index.index.month,
                        data_index.index.day], as_index=True).std()
    q10_interan_days = data_index.groupby([data_index.index.month,
                        data_index.index.day], as_index=True).quantile(0.10)
    q90_interan_days = data_index.groupby([data_index.index.month,
                        data_index.index.day], as_index=True).quantile(0.90)
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
            lw=2, color=couleurs[i], label='xxx')
    yerrmax = mean_interan_days.q75
    yerrmin = mean_interan_days.q25
    # ax.legend('upper right')
    # ax.fill_between(mean_interan_days.counts, yerrmin, yerrmax,
    #                   color='cyan',edgecolor='grey',
    #                   alpha = 0.5, label='10-90th')
    ax.fill_between(mean_interan_days.counts, yerrmin, yerrmax,
                      color='gray',edgecolor='grey', lw=0.5,
                      alpha = 0.25, label='10-90th')
    # plt.yscale('log')
    # ax.yaxis.set_major_formatter(ScalarFormatter())
    ax.set_xlim(0,366)
    if i == 0:
        ax.set_ylim(-10,20)
    if i == 1:
        ax.set_ylim(0,10)
    if i == 2:
        ax.set_ylim(0,10) 
    if i == 3:
        ax.set_ylim(0,10) 
    if i == 4:
        ax.set_ylim(0,10) 
    if i == 5:
        ax.set_ylim(0,10) 
    # ax.set_ylim(0.01,10)
    ax.tick_params(axis='both', which='major', pad=10)
    x1 = np.linspace(0,366,13)
    squad = ['J','F','M','A','M','J','J','A','S','O','N','D','J']
    ax.set_xticks(x1)
    ax.set_xticklabels(squad, minor=False, rotation='horizontal')
    if i == 5:
        ax.set_xlabel('Months', labelpad=+10)
    if i >0:
        ax.set_title(var + ' [mm/d]', color=couleurs[i], fontsize=12)
    #     ax.set_ylabel(var + ' [mm/d]',labelpad=+10, color=couleurs[i], fontsize=15)
    if i==0:
        ax.set_title(var + ' [°C]', color=couleurs[i], fontsize=12)
    #     ax.set_ylabel(var + ' [°C]',labelpad=+10, color=couleurs[i], fontsize=15)
    # ax.set_title(watershed_name + ' [' + str(first) + ' to ' + str(last) + ']')
    # ax.grid(color='grey', lw=0.5, zorder=0)
    
    # ax.legend(loc='upper left')
    plt.tight_layout()

#%% SIM2 HYDROCLIMAT NORMALIZE

init_path = data_path + '_Q/'

Qobs_list =[
             'lasset_Q_Day.Cmd.txt'
            ]

areas = [3.7]

for i, Qobs_name in enumerate(Qobs_list[:]):
    dfQ = pd.read_csv(init_path+Qobs_name, sep=';', parse_dates=True, index_col='date_temp') # m3/d
    dfQ = dfQ['q']/(areas[i]*1e6)

dfSIM2 = pd.DataFrame()
dfSIM2['OBSER'] = dfQ
dfSIM2['PPT'] = (sim2['PRENEI_Q']+sim2['PRELIQ_Q'])/1000
dfSIM2['DRAIN'] = sim2['DRAINC_Q']/1000
dfSIM2['RUNOF'] = sim2['RUNC_Q']/1000
dfSIM2['ECSNOW'] = sim2['ECOULEMENT_Q']/1000

# f = dfSIM2['OBSER'].mean() / (dfSIM2['DRAIN']+dfSIM2['RUNOF']+dfSIM2['ECSNOW']).mean()
# f = dfSIM2['OBSER'].mean() / dfSIM2['PPT'].mean()
norm_factor = dfSIM2['OBSER'].mean() / (dfSIM2['DRAIN']+dfSIM2['RUNOF']).mean()
print(norm_factor)

dfSIM2['INPUT'] = (dfSIM2['DRAIN']+dfSIM2['RUNOF']) * norm_factor

fig, ax = plt.subplots(1,1, figsize=(9,3))
ax.plot(dfSIM2['DRAIN']+dfSIM2['RUNOF'], label='R + r', c='darkorange')
ax.plot(dfSIM2['DRAIN'], label='R', c='forestgreen')
ax.plot(dfSIM2['OBSER'], label='Q', c='k')
ax.plot(dfSIM2['INPUT'], label='INPUT', c='red')
ax.legend()
ax.set_yscale('log')
import matplotlib.dates as mdates
years_maj = mdates.YearLocator()   # every year
months_maj = mdates.MonthLocator()  # every x month
ax.xaxis.set_major_locator(years_maj)
ax.xaxis.set_minor_locator(months_maj)

fig, ax = plt.subplots(1,1, figsize=(4,4))
ax.scatter(dfSIM2['OBSER'], dfSIM2['INPUT'], lw=0, color='k')
ax.set_xscale('log')
ax.set_yscale('log')
ax.set_xlim(1e-4,1)
ax.set_ylim(1e-4,1)

rea_facnorm_sim2 = norm_factor
rea_recharge_sim2 = (sim2['DRAINC_Q']/1000)*norm_factor
rea_runoff_sim2 = (sim2['RUNC_Q']/1000)*norm_factor

#%% DRIAS EAU - NETCDF
"""
BV.add_driaseau('D:/Users/abherve/SIMULATIONS/PYRENEES/results_stable/driaseau/',
                list_models=['all'],
                list_vars=['all']) # 'all'
"""
#%% DRIAS EAU - CSV

data_folder = stable_folder+'/driaseau/'

df = pd.DataFrame()
df.index = pd.date_range(start="1950-01-01",end="2100-12-31")

list_models = ['Model_01','Model_02','Model_03','Model_04','Model_05','Model_06','Model_07','Model_08','Model_09','Model_10','Model_11','Model_12']

list_of_paths = []
for i in list_models:
    list_of_paths_model = glob.glob(os.path.join(data_folder+'/', '*.nc'))
    list_of_paths.extend(list_of_paths_model)

driaseau.driaseau_extract_values(data_folder, list_of_paths, df)

#%% DRIAS CLIMAT NETCDF
"""
BV.add_driasclimat('D:/Users/abherve/SIMULATIONS/PYRENEES/results_stable/driasclimat/',
                   list_models=['all'],
                   list_vars=['all']) # 'all'
"""
#%% DRIAS CLIMAT CSV

data_folder = stable_folder+'/driasclimat/'

df = pd.DataFrame()
df.index = pd.date_range(start="1950-01-01",end="2100-12-31")

list_models = ['Model_01','Model_02','Model_03','Model_04','Model_05','Model_06','Model_07','Model_08','Model_09','Model_10','Model_11','Model_12']

list_of_paths = []
for i in list_models:
    list_of_paths_model = glob.glob(os.path.join(data_folder+'/', '*.nc'))
    list_of_paths.extend(list_of_paths_model)

driasclimat.driasclimat_extract_values(data_folder, list_of_paths, df)

#%% ---- PROJECTION

#%% DRIAS EAU MIX DATA

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

#%% PLOT ALL MODELS

all_proj = pd.read_csv(BV.stable_folder + '/driaseau/' + 'all_proj_driaseau.csv', sep=';', index_col=0, parse_dates=True)

# # For all
# num_list = ['Model_01',
#             'Model_02',
#             'Model_03',
#             'Model_04',
#             'Model_05',
#             'Model_06',
#             'Model_07',
#             'Model_08',
#             'Model_09',
#             'Model_10',
#             'Model_11',
#             'Model_12']
# mod_keep = 'MPI-CCL|ECE-RCA|ECE-RAC|IPS-RCA|CNR-RAC|NOR-R15|CNR-ALA|NOR-HIR|HAD-CCL|IPS-WRF|HAD-REG|MPI-R09'
# mod_list = ['MPI-CCL',
#             'ECE-RCA',
#             'ECE-RAC',
#             'IPS-RCA',
#             'CNR-RAC',
#             'NOR-R15',
#             'CNR-ALA',
#             'NOR-HIR',
#             'HAD-CCL',
#             'IPS-WRF',
#             'HAD-REG',
#             'MPI-R09']

# # For 2.6
# num_list = ['Model_01',
#             'Model_02',
#             'Model_03',
#             # 'Model_04',
#             'Model_05',
#             'Model_06',
#             'Model_07',
#             # 'Model_08',
#             # 'Model_09',
#             # 'Model_10',
#             'Model_11',
#             'Model_12']
# mod_keep = 'MPI-CCL|ECE-RCA|ECE-RAC|CNR-RAC|NOR-R15|CNR-ALA|HAD-REG|MPI-R09'
# mod_list = ['MPI-CCL',
#             'ECE-RCA',
#             'ECE-RAC',
#             # 'IPS-RCA',
#             'CNR-RAC',
#             'NOR-R15',
#             'CNR-ALA',
#             # 'NOR-HIR',
#             # 'HAD-CCL',
#             # 'IPS-WRF',
#             'HAD-REG',
#             'MPI-R09']

# # For 4.5
# num_list = ['Model_01',
#             'Model_02',
#             'Model_03',
#             'Model_04',
#             'Model_05',
#             # 'Model_06',
#             'Model_07',
#             'Model_08',
#             'Model_09',
#             'Model_10',
#             # 'Model_11',
#             'Model_12']
# mod_keep = 'MPI-CCL|ECE-RCA|ECE-RAC|IPS-RCA|CNR-RAC|CNR-ALA|NOR-HIR|HAD-CCL|IPS-WRF|MPI-R09'
# mod_list = ['MPI-CCL',
#             'ECE-RCA',
#             'ECE-RAC',
#             'IPS-RCA',
#             'CNR-RAC',
#             # 'NOR-R15',
#             'CNR-ALA',
#             'NOR-HIR',
#             'HAD-CCL',
#             'IPS-WRF',
#             # 'HAD-REG',
#             # 'MPI-R09'
#             ]

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

#%% PLOT MEDIAN MODELS

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
ax2.set_yscale('log')
ax2.legend()

#%% DRIAS CLIMAT DATA

all_proj = pd.read_csv(BV.stable_folder + '/driasclimat/' + '_ALL_D.csv', sep=';', index_col=0, parse_dates=True)

all_proj2 =  pd.read_csv(BV.stable_folder + '/driaseau/' + '_ALL_D.csv', sep=';', index_col=0, parse_dates=True)

#%% PLOT MEDIAN MODELS

# For all
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
mod_keep = 'MPI-CCL|ECE-RCA|ECE-RAC|IPS-RCA|CNR-RAC|NOR-R15|CNR-ALA|NOR-HIR|HAD-CCL|IPS-WRF|HAD-REG|MPI-R09'
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

# For 2.6
num_list = ['Model_01',
            'Model_02',
            'Model_03',
            # 'Model_04',
            'Model_05',
            'Model_06',
            'Model_07',
            # 'Model_08',
            # 'Model_09',
            # 'Model_10',
            'Model_11',
            'Model_12']
mod_keep = 'MPI-CCL|ECE-RCA|ECE-RAC|CNR-RAC|NOR-R15|CNR-ALA|HAD-REG|MPI-R09'
mod_list = ['MPI-CCL',
            'ECE-RCA',
            'ECE-RAC',
            # 'IPS-RCA',
            'CNR-RAC',
            'NOR-R15',
            'CNR-ALA',
            # 'NOR-HIR',
            # 'HAD-CCL',
            # 'IPS-WRF',
            'HAD-REG',
            'MPI-R09']

# For 4.5
num_list = ['Model_01',
            'Model_02',
            'Model_03',
            'Model_04',
            'Model_05',
            # 'Model_06',
            'Model_07',
            'Model_08',
            'Model_09',
            'Model_10',
            # 'Model_11',
            'Model_12']
mod_keep = 'MPI-CCL|ECE-RCA|ECE-RAC|IPS-RCA|CNR-RAC|CNR-ALA|NOR-HIR|HAD-CCL|IPS-WRF|MPI-R09'
mod_list = ['MPI-CCL',
            'ECE-RCA',
            'ECE-RAC',
            'IPS-RCA',
            'CNR-RAC',
            # 'NOR-R15',
            'CNR-ALA',
            'NOR-HIR',
            'HAD-CCL',
            'IPS-WRF',
            # 'HAD-REG',
            # 'MPI-R09'
            ]

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
            
#%% ---- CALIB

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

# vers = 'v1'
# vers = 'v2'
# vers = 'v3'
# vers = 'v4'
# vers = 'v5'
# vers = 'v6'
# vers = 'v7' # ==> ISBA
vers = 'v8' # ==> SIM2

hydrography_path = data_path + '_hydrography/' # add hydrographic shapefiles
types_obs = ['stream_perennial_wetlands_points']
# types_obs = ['stream_perennial_wetlands_osm_points']
fields_obs = ['fid']

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
        
        BV.add_hydrography(hydrography_path, types_obs=[type_obs], fields_obs=[field_obs])
        
        box = True # or False
        sink_fill = False # or True
        sim_state = 'steady' # 'steady' or 'transient'
        plot_cross = True
        first_clim = 'mean' # or 'first or value
        nlay = 25
        lay_decay = 1.25 # 1 for no decay
        
        ### v1, v2, v3, v4
        # thick = 50 # if bottom is None, aquifer thickness
        ### v5 simf/obsf - with : gap=0.5, streams : RNF, rec : 600 (summer)
        thick = 30 # if bottom is None, aquifer thickness
        
        # rec_summer = sim2[sim2.index.month.isin([7,8,9])]
        # recharge = (rec_summer['DRAINC_Q'] * norm_factor) / 1000 # mm/d to m/d
        recharge = (sim2['DRAINC_Q'] * norm_factor) / 1000 # mm/d to m/d
        # recharge = (isba['REC_REA_historic'] * norm_factor) / 1000 # mm/d to m/d
        
        verti_cond = None # or [ [1e-5, [0, 20]],
        verti_poro = None
        cond_drain = None # or value of conductance
        porosity = 5 / 100 # -
        poro_decay = 0 # exponential decay : 1/20 (half decrease at 20m)
        bc_left = None # or value
        bc_right = None # or value
        sea_level = 'None' # or value based on specific data : BV.oceanic.MSL
        zone_partic = 'domain' # or watershed
        
        BV.add_settings()
        BV.add_climatic()
        BV.add_geometric() # soon
        BV.add_hydraulic()
        BV.settings.update_box_model(box)
        BV.settings.update_sink_fill(sink_fill)
        BV.settings.update_simulation_state(sim_state)
        BV.settings.update_active_plot(plot_cross=plot_cross)
        BV.climatic.update_recharge(recharge, sim_state=sim_state)
        BV.climatic.update_first_clim(first_clim)
        BV.hydraulic.update_nlay(nlay) # 1
        BV.hydraulic.update_lay_decay(lay_decay) # 1
        BV.hydraulic.update_porosity(porosity)
        BV.hydraulic.update_cond_vertical(verti_cond)
        BV.hydraulic.update_poro_vertical(verti_poro)
        BV.hydraulic.update_cond_drain(cond_drain)
        BV.hydraulic.update_poro_decay(poro_decay)
        BV.settings.update_bc_sides(bc_left, bc_right)
        BV.add_oceanic(sea_level)
        BV.settings.update_input_particules(zone_partic=zone_partic)
        
        # Aquifer bottom
        list_bottom = [None, 0] # aquifer flat or not
        list_bottom.extend([0] * 10) ### ATTENTION ###

        # Decay of K
        # list_d_values = [0, 0]
        # list_d_values.extend(np.geomspace(10, 300, 10).round(0).astype(int))
        # print(list_d_values)
        list_d_values = [0, 0, 10, 15, 20, 25, 30, 45, 65, 100, 140, 200]
        list_cond_decay = list(1/np.array(list_d_values))
        list_cond_decay[0] = 0
        list_cond_decay[1] = 0
                
        list_id_mod = [0,1,2,3,4,5,6,7,8,9,10,11]
       
        for cond_decay, bottom, id_mod in zip(list_cond_decay[:], list_bottom[:], list_id_mod[:]):
        # for cond_decay, bottom, id_mod in zip([1/25], [0], [4.5]):
            BV.hydraulic.update_thick(thick) # 30 / intervient pas si bottom != None
            BV.hydraulic.update_cond_decay(cond_decay) # 0
            BV.hydraulic.update_bottom(bottom) # 0
            
            params_df = pd.DataFrame(columns=['params','init_values','lower_bounds','higher_bounds','units','scale'])
            # params_df.loc[0] = ['k1','?',8.64e-04,8.64e-01,'m/j','lin']
            if id_mod == 0:
                params_df.loc[0] = ['k1','?',1e-8*3600*24,1e-5*3600*24,'m/j','lin'] ### K/R 0.36 to 36 000
            if id_mod == 1:
                params_df.loc[0] = ['k1','?',1e-8*3600*24,1e-6*3600*24,'m/j','lin'] ### K/R 0.36 to 36 000
            if id_mod >= 2:
                params_df.loc[0] = ['k1','?',1e-8*3600*24,1e-5*3600*24,'m/j','lin'] ### K/R 0.36 to 36 000
            if (id_mod >= 2) & (id_mod <= 4):
                print('Y')
                params_df.loc[0] = ['k1','?',1e-8*3600*24,1e-4*3600*24,'m/j','lin'] ### K/R 0.36 to 36 000
            if id_mod >= 9:
                params_df.loc[0] = ['k1','?',1e-8*3600*24,1e-6*3600*24,'m/j','lin'] ### K/R 0.36 to 36 000
            # if id_mod >= 10:
            #     params_df.loc[0] = ['k1','?',1e-10*3600*24,1e-6*3600*24,'m/j','lin'] ### K/R 0.36 to 36 000
            params_file = 'calib_dicot_hom_1v_k1'
            params_df.to_csv(BV.calibration_folder+'/'+params_file+'.csv', sep=';', index=None)
            p_min = params_df['lower_bounds'].values[0]
            p_max = params_df['higher_bounds'].values[0]
            diff = p_max - p_min
            half = (p_min + p_max) / 2
            # print(half)
            
            gap = 1.0
            gap = 0.5
            # gap = 0.1
            
            compt = 0
            
            while (diff > ((gap/100) * half)):
                
                half = (p_min + p_max) / 2
                hyd_cond = half.copy() # if K in calib_params.csv
                kr = hyd_cond / BV.climatic.recharge
                            
                BV.hydraulic.update_hyd_cond(hyd_cond)
                
                now = datetime.now()
                oclock = now.strftime("%Y%m%d_%Hh%Mm%Ss") 
                
                if id_mod <=1 :
                    str_cond_decay = cond_decay
                else:
                    str_cond_decay = 1/cond_decay
                if bottom==None:
                    model_name = vers+'_'+str('model')+str(id_mod)+'_'+str(round(str_cond_decay,4))+'-'+str(round(thick,4))+'_'+str(compt)+'-'+str("{:.2e}".format(hyd_cond/24/3600)) #+'-'+oclock
                else:
                    model_name = vers+'_'+str('model')+str(id_mod)+'_'+str(round(str_cond_decay,4))+'-'+str(round(bottom,4))+'_'+str(compt)+'-'+str("{:.2e}".format(hyd_cond/24/3600)) #+'-'+oclock
                BV.settings.update_model_name(model_name)
                # print(model_name)
                
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
                                                                  actual_date=True, 
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
                
                ### v7 simf/obsf - with : gap=0.5, streams : RNF, rec : 1000 (year) ==> isba
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
                df.loc[compt,'K_decay'] = round(cond_decay, 4) # mm
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

# vers = 'v1'
# vers = 'v2'
# vers = 'v3'
# vers = 'v4'
# vers = 'v5'
# vers = 'v6'
vers = 'v7'
# vers = 'v8'

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

#%% DICHOTOMY - GRAPH K

iD_explo = 'e15'

dfp = dfs.copy()

dfp['Doptim'] = ((dfp['Obs']+dfp['Sim'])/2)
# dfp['Doptim'] = (np.log(dfp['Sim']/dfp['Obs']))**2
# dfp['Doptim'] = ((dfp['Obs']+dfp['Sim'])/2) * (1+abs(1-dfp['Indicator']))
# dfp['Doptim'] = ((dfp['Obs']+dfp['Sim'])/2) + abs(dfp['Sim']-dfp['Obs'])
# dfp['Doptim'] = ((dfp['Obs']+dfp['Sim'])/2) / (abs(1-dfp['Indicator']))
# dfp['Doptim'] = dfp['Ind_log']
# dfp['Doptim'] = ( (dfp['Sim'] * 3) - dfp['Obs'] ) / 2
# dfp['Doptim'] = ((dfp['Obs']+dfp['Sim'])/2) * dfp['Indicator']
# dfp['Doptim'] = ((dfp['Obs']+dfp['Sim'])/2) * ((dfp['Sim']/dfp['Obs']))
# dfp['Doptim'] = (dfp['Sim'])
# dfp['Doptim'] = (dfp['Indicator'])
# dfp['Doptim'] = np.log(dfp.mean_simf_to_obs/dfp.mean_obs_to_simf)**2

list_id_mod = [0,1,2,3,4,5,6,7,8,9,10,11]
dfz = pd.DataFrame()
for i in list_id_mod[:]:
    dft = dfp[dfp['id_mod']==i]
    # dfz = pd.concat([dfz, dft.iloc[-1:]])
    dfz = pd.concat([dfz, dft.iloc[(dft['Indicator']-1).abs().argsort()[:1]]])    
 
dfz.to_csv(BV.calibration_folder+'/'+'_models'+'_optimum_'+vers+'.csv', sep=';')
    
fig, ax = plt.subplots(1,1, figsize=(3.6,2.6))

# im = ax.scatter(df.k, (df.Dso+df.Dos)/2, c=df.cond_decay, s=100, cmap='jet')
ax.scatter(dfz[:1]['K']/24/3600, dfz[:1]['Doptim'], s=100, 
            marker='s', lw=2, color='white', ec='k'
            # cmap=mpl.colors.ListedColormap('k'),
            # label=dfz['1/K_decay'].values[0]
            )

ax.scatter(dfz[1:2]['K']/24/3600, dfz[1:2]['Doptim'],
            c=dfz[1:2]['1/K_decay'],
            s=100, 
             marker='^', lw=2,
             cmap=mpl.colors.ListedColormap('gray'),
            # label='0'
            )
im = ax.scatter(dfz[2:]['K']/24/3600, dfz[2:]['Doptim'], c=dfz[2:]['1/K_decay'], s=100, 
                cmap='plasma_r',
                norm=mpl.colors.LogNorm(vmin=10, vmax=200),
                lw=2,
                # label=df['1/cond_decay'] 
                )
# ax.legend()
ax.set_xscale('log')
# ax.set_yscale('log')
ax.set_xlabel('$K_{0}$ [m/s]')
ax.set_xlim(1e-8, 2e-5)
ax.set_ylim(25, 80)
ax.set_ylabel('$D_{optim}$ [m]')
# cb = plt.colorbar()
from matplotlib.ticker import LogFormatter 
formatter = LogFormatter(10, labelOnlyBase=True) 
cb = plt.colorbar(im, ax=ax,
                  cax = fig.add_axes([0.95, 0.10, 0.03, 0.8]))
for t in cb.ax.get_yticklabels():
     t.set_fontsize(10)
# cb.set_clim(10,500)
# cb.set_ticks(np.geomspace(10, 300, 10).astype(int))
# cb.set_ticklabels(np.geomspace(10, 300, 10).astype(int))
# cb.set_ticks([10, 15, 20, 30, 45, 65, 100, 140, 205, 300])
# cb.set_ticklabels([10, 15, 20, 30, 45, 65, 100, 140, 205, 300])
cb.set_ticks([10, 15, 20, 25, 30, 45, 65, 100, 140, 200])
cb.set_ticklabels([10, 15, 20, 25, 30, 45, 65, 100, 140, 200], fontsize=8)
cb.ax.tick_params(direction='in', length=2, width=1, colors='k',
                  grid_color='k', grid_alpha=0.5)
cb.minorticks_off()
# cb.clim()
cb.ax.set_ylabel('1/α [m]', rotation=270, labelpad=25)

# ax.set_yscale('log')

fig.savefig('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_figures_paper/_v0/02_fig_dichotomy/'+
            'DICHOTOMY_K'+'.png',
            bbox_inches='tight')

#%% DICHOTOMY - GRAPH T WITH DEPTH

dfp = dfs.copy()

dfp['Doptim'] = ((dfp['Obs']+dfp['Sim'])/2)
# dfp['Doptim'] = (np.log(dfp['Sim']/dfp['Obs']))**2
# dfp['Doptim'] = ((dfp['Obs']+dfp['Sim'])/2) * (1+abs(1-dfp['Indicator']))
# dfp['Doptim'] = ((dfp['Obs']+dfp['Sim'])/2) + abs(dfp['Sim']-dfp['Obs'])
# dfp['Doptim'] = ((dfp['Obs']+dfp['Sim'])/2) / (abs(1-dfp['Indicator']))
# dfp['Doptim'] = dfp['Ind_log']
# dfp['Doptim'] = ( (dfp['Sim'] * 3) - dfp['Obs'] ) / 2
# dfp['Doptim'] = ((dfp['Obs']+dfp['Sim'])/2) * dfp['Indicator']
# dfp['Doptim'] = ((dfp['Obs']+dfp['Sim'])/2) * ((dfp['Sim']/dfp['Obs']))
# dfp['Doptim'] = (dfp['Sim'])
# dfp['Doptim'] = (dfp['Indicator'])
# dfp['Doptim'] = np.log(dfp.mean_simf_to_obs/dfp.mean_obs_to_simf)**2

list_id_mod = [0,1,2,3,4,5,6,7,8,9,10,11]
dfz = pd.DataFrame()
for i in list_id_mod[:]:
    dft = dfp[dfp['id_mod']==i]
    # dfz = pd.concat([dfz, dft.iloc[-1:]])
    dfz = pd.concat([dfz, dft.iloc[(dft['Indicator']-1).abs().argsort()[:1]]])    
 
dfz.to_csv(BV.calibration_folder+'/'+'_models'+'_optimum_'+vers+'.csv', sep=';')
    
BV.calibration_folder = os.path.join(out_path, watershed_name, 'results_calibration')

fig, ax = plt.subplots(1,1, figsize=(3.6,2.6))

# im = ax.scatter(df.k, (df.Dso+df.Dos)/2, c=df.cond_decay, s=100, cmap='jet')
# m0 = pd.read_csv(BV.calibration_folder+'/'+dfz[:1]['model_name'].values[0]+'/_postprocess/_timeseries/'+'_simulated_timeseries.csv', sep=';')
# wt = thick - m0.watertable_depth
thick = 30
ax.scatter(dfz[:1]['K']/24/3600 * thick, dfz[:1]['Doptim'], c=dfz[:1]['1/K_decay'], s=100, 
            marker='s', lw=2,
            cmap=mpl.colors.ListedColormap('white'),
            # label=dfz['1/K_decay'].values[0]
            )
# idx0 = dfz[:1].index
# dfz.loc[idx0,'wt'] = wt.values[0]

# m1 = pd.read_csv(BV.calibration_folder+'/'+dfz[1:2]['model_name'].values[0]+'/_postprocess/_timeseries/'+'_simulated_timeseries.csv', sep=';')
# wt = 2000 - m0.watertable_depth
ax.scatter(dfz[1:2]['K']/24/3600 * 2000, dfz[1:2]['Doptim'],
            c=dfz[1:2]['1/K_decay'] * 1,
            s=100, 
             marker='o', lw=2,
             cmap=mpl.colors.ListedColormap('gray'),
            # label='0'
            )
# idx1 = dfz[1:2].index
# dfz.loc[idx1,'wt'] = wt.values[0]

# for i in dfz[2:].index:
#     mx = pd.read_csv(BV.calibration_folder+'/'+dfz[dfz.index==i]['model_name'].values[0]+'/_postprocess/_timeseries/'+'_simulated_timeseries.csv', sep=';')
#     wt = dfz[dfz.index==i]['1/K_decay'].values[0]*2 - mx.watertable_depth.values[0]
#     dfz.loc[i,'wt'] = wt
    
im = ax.scatter(dfz[2:]['K']/24/3600 * dfz[2:]['1/K_decay'], dfz[2:]['Doptim'],
                c=dfz[2:]['1/K_decay'], s=100, 
                cmap='jet',
                norm=mpl.colors.LogNorm(vmin=10, vmax=300),
                lw=2,
                # label=df['1/cond_decay'] 
                )
# ax.legend()
ax.set_xscale('log')
# ax.set_yscale('log')
ax.set_xlabel('T [$m^2$/s]')
ax.set_xlim(1e-5, 2e-4)
ax.set_ylim(25, 80)
ax.set_ylabel('$D_{optim}$ [m]')
# cb = plt.colorbar()
from matplotlib.ticker import LogFormatter 
formatter = LogFormatter(10, labelOnlyBase=True) 
cb = plt.colorbar(im, ax=ax,
                  cax = fig.add_axes([0.95, 0.10, 0.03, 0.8]))
for t in cb.ax.get_yticklabels():
     t.set_fontsize(10)
# cb.set_clim(10,500)
# cb.set_ticks(np.geomspace(10, 300, 10).astype(int))
# cb.set_ticklabels(np.geomspace(10, 300, 10).astype(int))
# cb.set_ticks([10, 15, 20, 30, 45, 65, 100, 140, 205, 300])
# cb.set_ticklabels([10, 15, 20, 30, 45, 65, 100, 140, 205, 300])
cb.set_ticks([10, 15, 20, 25, 30, 45, 65, 100, 140, 205])
cb.set_ticklabels([10, 15, 20, 25, 30, 45, 65, 100, 140, 205], fontsize=8)
cb.ax.tick_params(direction='in', length=2, width=1, colors='k',
                  grid_color='k', grid_alpha=0.5)
cb.minorticks_off()
# cb.clim()
cb.ax.set_ylabel('1/α [m]', rotation=270, labelpad=25)

# ax.set_yscale('log')

fig.savefig('C:/Users/ronan/Downloads/figs_'+iD_explo+'/'+'DICHOTOMY_TMAX'+'.png',
            bbox_inches='tight')

#%% DICHOTOMY - GRAPH T WITH WT

dfp = dfs.copy()

dfp['Doptim'] = ((dfp['Obs']+dfp['Sim'])/2)
# dfp['Doptim'] = (np.log(dfp['Sim']/dfp['Obs']))**2
# dfp['Doptim'] = ((dfp['Obs']+dfp['Sim'])/2) * (1+abs(1-dfp['Indicator']))
# dfp['Doptim'] = ((dfp['Obs']+dfp['Sim'])/2) + abs(dfp['Sim']-dfp['Obs'])
# dfp['Doptim'] = ((dfp['Obs']+dfp['Sim'])/2) / (abs(1-dfp['Indicator']))
# dfp['Doptim'] = dfp['Ind_log']
# dfp['Doptim'] = ( (dfp['Sim'] * 3) - dfp['Obs'] ) / 2
# dfp['Doptim'] = ((dfp['Obs']+dfp['Sim'])/2) * dfp['Indicator']
# dfp['Doptim'] = ((dfp['Obs']+dfp['Sim'])/2) * ((dfp['Sim']/dfp['Obs']))
# dfp['Doptim'] = (dfp['Sim'])
# dfp['Doptim'] = (dfp['Indicator'])
# dfp['Doptim'] = np.log(dfp.mean_simf_to_obs/dfp.mean_obs_to_simf)**2

list_id_mod = [0,1,2,3,4,5,6,7,8,9,10,11]
dfz = pd.DataFrame()
for i in list_id_mod[:]:
    dft = dfp[dfp['id_mod']==i]
    # dfz = pd.concat([dfz, dft.iloc[-1:]])
    dfz = pd.concat([dfz, dft.iloc[(dft['Indicator']-1).abs().argsort()[:1]]])    
 
dfz.to_csv(BV.calibration_folder+'/'+'_models'+'_optimum_'+vers+'.csv', sep=';')
    
BV.calibration_folder = os.path.join(out_path, watershed_name, 'results_calibration')

fig, ax = plt.subplots(1,1, figsize=(3.6,2.6))

# im = ax.scatter(df.k, (df.Dso+df.Dos)/2, c=df.cond_decay, s=100, cmap='jet')
m0 = pd.read_csv(BV.calibration_folder+'/'+dfz[:1]['model_name'].values[0]+'/_postprocess/_timeseries/'+'_simulated_timeseries.csv', sep=';')
wt = thick - m0.watertable_depth
ax.scatter(dfz[:1]['K']/24/3600 * wt.values[0], dfz[:1]['Doptim'], c=dfz[:1]['1/K_decay'], s=100, 
            marker='s', lw=2,
            cmap=mpl.colors.ListedColormap('white'),
            # label=dfz['1/K_decay'].values[0]
            )
idx0 = dfz[:1].index
dfz.loc[idx0,'wt'] = wt.values[0]

m1 = pd.read_csv(BV.calibration_folder+'/'+dfz[1:2]['model_name'].values[0]+'/_postprocess/_timeseries/'+'_simulated_timeseries.csv', sep=';')
wt = 2000 - m0.watertable_depth
ax.scatter(dfz[1:2]['K']/24/3600 * wt.values[0], dfz[1:2]['Doptim'],
            c=dfz[1:2]['1/K_decay'] * 1,
            s=100, 
             marker='o', lw=2,
             cmap=mpl.colors.ListedColormap('gray'),
            # label='0'
            )
idx1 = dfz[1:2].index
dfz.loc[idx1,'wt'] = wt.values[0]

for i in dfz[2:].index:
    mx = pd.read_csv(BV.calibration_folder+'/'+dfz[dfz.index==i]['model_name'].values[0]+'/_postprocess/_timeseries/'+'_simulated_timeseries.csv', sep=';')
    wt = dfz[dfz.index==i]['1/K_decay'].values[0]*2 - mx.watertable_depth.values[0]
    dfz.loc[i,'wt'] = wt
    
im = ax.scatter(dfz[2:]['K']/24/3600 * dfz[2:]['wt'], dfz[2:]['Doptim'],
                c=dfz[2:]['1/K_decay'], s=100, 
                cmap='jet',
                norm=mpl.colors.LogNorm(vmin=10, vmax=300),
                lw=2,
                # label=df['1/cond_decay'] 
                )
# ax.legend()
ax.set_xscale('log')
# ax.set_yscale('log')
ax.set_xlabel('T [$m^2$/s]')
ax.set_xlim(1e-5, 2e-4)
ax.set_ylim(25, 80)
ax.set_ylabel('$D_{optim}$ [m]')
# cb = plt.colorbar()
from matplotlib.ticker import LogFormatter 
formatter = LogFormatter(10, labelOnlyBase=True) 
cb = plt.colorbar(im, ax=ax,
                  cax = fig.add_axes([0.95, 0.10, 0.03, 0.8]))
for t in cb.ax.get_yticklabels():
     t.set_fontsize(10)
# cb.set_clim(10,500)
# cb.set_ticks(np.geomspace(10, 300, 10).astype(int))
# cb.set_ticklabels(np.geomspace(10, 300, 10).astype(int))
# cb.set_ticks([10, 15, 20, 30, 45, 65, 100, 140, 205, 300])
# cb.set_ticklabels([10, 15, 20, 30, 45, 65, 100, 140, 205, 300])
cb.set_ticks([10, 15, 20, 25, 30, 45, 65, 100, 140, 205])
cb.set_ticklabels([10, 15, 20, 25, 30, 45, 65, 100, 140, 205], fontsize=8)
cb.ax.tick_params(direction='in', length=2, width=1, colors='k',
                  grid_color='k', grid_alpha=0.5)
cb.minorticks_off()
# cb.clim()
cb.ax.set_ylabel('1/α [m]', rotation=270, labelpad=25)

# ax.set_yscale('log')

fig.savefig('C:/Users/ronan/Downloads/figs_'+iD_explo+'/'+'DICHOTOMY_TWT'+'.png',
            bbox_inches='tight')

#%% DICHOTOMY - MAPS

dfp = dfs.copy()
dfp['1/K_decay'] = 1/dfp['K_decay']
dfp['1/K_decay'][dfp['1/K_decay'] == np.inf] = 0
dfp['Doptim'] = (dfp['Obs'] + dfp['Sim'])/2
list_id_mod = [0,1,2,3,4,5,6,7,8,9,10,11]

shp_bv = gpd.read_file(BV.geographic.watershed_shp)
# if vers == 'v3':
#     shp_hydro = gpd.read_file(stable_folder+'hydrography/'+'stream_perennial_wetlands_points.shp')
# if vers == 'v4':
#     shp_hydro = gpd.read_file(stable_folder+'hydrography/'+'stream_perennial_wetlands_osm_points.shp')
# if vers == 'v6':
#     shp_hydro = gpd.read_file(stable_folder+'hydrography/'+'stream_perennial_wetlands_points.shp')
# if vers == 'v7':
#     shp_hydro = gpd.read_file(stable_folder+'hydrography/'+'stream_perennial_wetlands_points.shp')
if vers == 'v8':
    shp_hydro = gpd.read_file(stable_folder+'hydrography/'+'stream_perennial_wetlands_points.shp')


# types_obs = ['stream_perennial_wetlands_points']
# types_obs = ['stream_perennial_wetlands_osm_points']

dfz = pd.DataFrame()
for i in list_id_mod[:]:
    dft = dfp[dfp['id_mod']==i]
    # dfz = pd.concat([dfz, dft.iloc[-1:]])
    dfz = pd.concat([dfz, dft.iloc[(dft['Indicator']-1).abs().argsort()[:1]]])    

for index, row in dfz.iterrows():
    model_name = row['model_name']
    print(model_name)
    
    fig, ax = plt.subplots(1,1, figsize=(5,10))
    
    shp = gpd.read_file(BV.calibration_folder+'/'+str(model_name)+'/'+'_matchingstreams/'+'sim_pt.shp')
    
    shp_bv.plot(ax=ax, facecolor='None')
    shp_hydro.plot(ax=ax, color='navy', lw=0)
    shp.plot(ax=ax, color='darkorange', lw=0)
    
    ax.set_title(model_name, fontsize=7)
    
    # fig.savefig('C:/Users/ronan/Downloads/figs/'+'MAPS_'+model_name+'.png',
    #             bbox_inches='tight')
    
    fig.savefig('C:/Users/ronan/Downloads/figs_'+iD_explo+'/'+'MAPS_'+model_name+'.png',
                bbox_inches='tight')

#%% ---- EXPLORATION

# 12 models
# 10 porosity per model : 0.1, 0.5, 1, 2, 4, 7, 10, 15, 20, 30

#%% UPDATE PARAMETERS

# iD_explo = 'e0' # with isba recharge
# iD_explo = 'e1' # with sim2 recharge
# iD_explo = 'e2' # with isba recharge ==> decay = /2
# iD_explo = 'e3' # with isba recharge ==> decay = /1
# iD_explo = 'e4' # with isba recharge ==> decay = /4
# iD_explo = 'e5' # with isba recharge ==> decay no and aquifer constant
# iD_explo = 'e6' # with isba recharge ==> n_decay / 2 ==> all models
# iD_explo = 'e7' # with isba recharge ==> n_decay / 0.5 ==> one model
# iD_explo = 'e8' # with isba recharge ==> np n_decay but compartimentalized for poro ==> one model
# iD_explo = 'e9' # with isba recharge ==> np n_decay but compartimentalized for K and poro ==> one model
# iD_explo = 'e10' # with isba recharge ==> np n_decay but compartimentalized for K and poro ==> one model
# iD_explo = 'e12' # with isba recharge ==> change ss
# iD_explo = 'o14' # with isba recharge ==> change ss with decay factor =2 with ss linked : one model
# iD_explo = 'o15' # with isba recharge ==> idem o14 : compartimentalized
# iD_explo = 'o16' # with sim2 recharge  ==> idem o14 : compartimentalized

# iD_explo = 'e14' # with isba recharge ==> change ss with decay factor = 2
# iD_explo = 'e15' # with sim2 recharge ==> change ss with decay factor = 2 - 16 models > 0.1
# iD_explo = 'e16' # with sim2 recharge ==> change ss with decay factor = 2 - 9 models < 0.1
iD_explo = 'e17' # with isba recharge ==> change ss with decay factor (large explo, details for good models)
iD_explo = 'e18' # with isba recharge ==> change ss with decay factor (details for bad models)

decay_factor = 2

vers = 'v7' # dichotomy isba
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

# recharge = (sim2['DRAINC_Q'] * norm_factor) / 1000 # mm/d to m/d
recharge = (isba['REC_REA_historic'] * rea_facnorm_isba) / 1000 # mm/d to m/d
# recharge = select_period(recharge, 2021, 2021)
recharge_w_res = recharge.resample('W', label='right').mean()
recharge_w_off = recharge.resample('W', label='right', closed='left', loffset=pd.DateOffset(days=3)).mean() # loffset='2T'
recharge_w_int = recharge.interpolate()[::7]
recharge_w_sli = recharge.groupby(np.arange(len(recharge))//7).mean()
recharge_w_sli.index = recharge_w_off.iloc[:-1].index
# recharge_w_sli.index = recharge_w_off.iloc[:].index
# recharge_w_sli = recharge_w_sli.iloc[:-1]

# runoff = (sim2['RUNC_Q'] * norm_factor) / 1000 # mm/d to m/d
runoff = (isba['RUN_REA_historic'] * rea_facnorm_isba) / 1000 # mm/d to m/d
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
plt.plot(BV.climatic.recharge)
plt.axhline(first_clim, c='k')

# Aquifer bottom
list_bottom = [None, 0] # aquifer flat or not
list_bottom.extend([0] * 10)

# Decay of K
# list_d_values = [0, 0]
# list_d_values.extend(np.geomspace(10, 300, 10).round(0).astype(int))
list_d_values = [0, 0, 10, 15, 20, 25, 30, 45, 65, 100, 140, 200]
list_cond_decay = list(1/np.array(list_d_values))
list_cond_decay[0] = 0
list_cond_decay[1] = 0

# Models
list_id_mod = [0,1,2,3,4,5,6,7,8,9,10,11]

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

#%% PRO PREPROCESSING

run_model = True
# run_model = False

# for cond_decay_val, bottom_val, koptim_val, id_mod_val in zip(list_cond_decay[-1:], list_bottom[-1:], list_koptim[-1:], list_id_mod[-1:]):
# for cond_decay_val, bottom_val, id_mod_val in zip(list_cond_decay[4:5],
#                                                               list_bottom[4:5],
#                                                               # list_koptim[4:5],
#                                                               list_id_mod[4:5]):
# for cond_decay_val, bottom_val, koptim_val, id_mod_val, kroptim_val in zip(list_cond_decay[:1],
#                                                                             list_bottom[:1],
#                                                                             list_koptim[:1],
#                                                                             list_id_mod[:1],
#                                                                             list_kroptim[:1]):
# for cond_decay_val, bottom_val, koptim_val, id_mod_val, kroptim_val in zip(list_cond_decay[4:5],
#                                                                             list_bottom[4:5],
#                                                                             list_koptim[4:5],
#                                                                             list_id_mod[4:5],
#                                                                             list_kroptim[4:5]):    
for cond_decay_val, bottom_val, koptim_val, id_mod_val, kroptim_val in zip(list_cond_decay[:],
                                                                            list_bottom[:],
                                                                            list_koptim[:],
                                                                            list_id_mod[:],
                                                                            list_kroptim[:]):    
    # for cond_decay_val, bottom_val, koptim_val, id_mod_val, kroptim_val in zip(list_cond_decay[2:3],
#                                                                             list_bottom[2:3],
#                                                                             list_koptim[2:3],
#                                                                             list_id_mod[2:3],
#                                                                             list_kroptim[2:3]):
# for cond_decay_val, bottom_val, koptim_val, id_mod_val, kroptim_val in zip(list_cond_decay[3:4],
#                                                                             list_bottom[3:4],
#                                                                             list_koptim[3:4],
#                                                                             list_id_mod[3:4],
#                                                                             list_kroptim[3:4]):
# for cond_decay_val, bottom_val, koptim_val, id_mod_val, kroptim_val in zip(list_cond_decay[-1:],
#                                                                             list_bottom[-1:],
#                                                                             list_koptim[-1:],
#                                                                             list_id_mod[-1:],
#                                                                             list_kroptim[-1:]):
# for cond_decay_val, bottom_val, koptim_val, id_mod_val, kroptim_val in zip([0],
#                                                                             [0],
#                                                                             [4.82e-6/1000],
#                                                                             [3],
#                                                                             [1]):  
   
    # if id_mod_val in [0,2,3,4,5,6]:
    #     list_porosity = np.array([0.1,0.5,0.6,0.7,0.8,0.9,1.0,1.1,1.2,1.3,1.4,1.5,2,4,8,16])/100
    # else:
    #     list_porosity = np.array([0.1,0.5,1,2,4,8,16])/100
    
    ### e17
    # if id_mod_val in [0,2,3,4,5]:
    #     list_porosity = np.array([0.05,0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8,0.9,1.0,1.1,1.2,1.3,1.4,1.5,2.0,4.0,8.0,16.0])/100
    # else:
    #     list_porosity = np.array([0.1,0.5,1.0,2.0,4.0,8.0,16.0])/100
    
    ### e18
    if id_mod_val in [1,6,7,8,9,10,11]:
        list_porosity = np.array([0.05,0.2,0.3,0.4,0.6,0.7,0.8,0.9,1.1,1.2,1.3,1.4,1.5])/100
       
        # print(id_mod_val)
        # print(kroptim_val)
        # koptim_from_kr = kroptim_val * (BV.climatic.recharge.mean())
        # print(koptim_from_kr, koptim_val)
        
        BV.hydraulic.update_cond_decay(cond_decay_val) # 0
        # BV.hydraulic.update_cond_decay(0) # 0
        BV.hydraulic.update_bottom(bottom_val) # None
        # BV.hydraulic.update_hyd_cond(koptim_val)
        # koptim_val = 0
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

for id_mod_val in list_id_mod[:]:

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

#%% STREAMFLOW CHRONICS ALL

# iD_explo = 'e14'

# iD_explos = ['e15','e16']
iD_explos = ['e17','e18']

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
        
        if iD_explo == 'e17':
            list_id_mod = [0,1,2,3,4,5,6,7,8,9,10,11]
        if iD_explo == 'e18':
            list_id_mod = [1,6,7,8,9,10,11]
            
        for id_mod_val in list_id_mod[:]:
        
            h5file = BV.calibration_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)
            d = dd.io.load(h5file)
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
                
                mix = Qobs.copy().to_frame()
                mix.columns = ['Qobs']
                mix['Qsim'] = Qmod
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
                
                fig.tight_layout()
                            
                # fig.savefig(os.path.join(simulations_folder, '_figures',
                #             'STREAMFLOW_'+model_name+'.png'),
                #             bbox_inches='tight')
                
                plt.close()
                
                fig.savefig('C:/Users/ronan/Downloads/figs_'+iD_explos[0]+'/'+'Q_'+model_name+'.png',
                            bbox_inches='tight')
                
                # fig.savefig('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_figures_paper/_v0/b_sup_calibs/'+
                #             'Q_'+model_name+'.png',
                #                         bbox_inches='tight')

dfcrit_Q = df.copy()

dfcrit_Q.to_csv(BV.simulations_folder+'dfcrit_Q_'+iD_explo[0]+'.csv', sep=';')    

#%% STREAMFLOW CRITERIA ALL

dfcrit_Q = pd.read_csv(BV.simulations_folder+'dfcrit_Q_'+iD_explo[0]+'.csv', sep=';')

iD_explos = ['e17', 'e18']

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

n = 12
colors = pl.cm.jet(np.linspace(0,1,n))
colors = pl.cm.plasma_r(np.linspace(0,1,n))

# fig, axs = plt.subplots(1,5, figsize=(5*6,5),
#                         # sharey=True
#                         )
# axs = axs.ravel()
for icri, cri in enumerate(['NSE','RMSE',
                            # 'KGE',
                            # 'OWN',
                            'NSElog','RMSElog'
                            ][:]):
    
    
    fig, ax = plt.subplots(1,1, figsize=(4.5,3.5),
                            # sharey=True
                            )
    
    # ax = axs[icri]
    # fig, ax = plt.subplots(1,1, figsize=(5,4))
    for imod, mod in enumerate(df['id_mod'].unique()):
        # imod=4
        color=colors[imod-1]
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
        # if cri != 'NSElog':
        ax.plot(dfplot.sort_values('O')['O'], dfplot.sort_values('O')[cri],
                marker='o', ms=1, mew=0,
                lw=1.5,
                color=color)
        # pc = ax.scatter(dfplot['O'], dfplot[cri])
        if cri == 'NSE':
            ax.set_ylabel('NSE [-]')
            ax.set_ylim(0,None)
        if cri == 'NSElog':
            ax.set_ylabel('$NSE_{log}$ [-]')
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
            ax.set_ylim(0.75,1)
        ax.set_xlabel('θ [%]')
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
        ax.set_xlim(0.1,16)
        # ax.set_yscale('log')
        
    plt.tight_layout()

    # fig.savefig('C:/Users/ronan/Downloads/figs_'+iD_explos[0]+'/'+'_Q_'+'criteria_'+cri+'.png', bbox_inches='tight')
        
        # fig.savefig('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_figures_paper/_v0/b_sup_calibs/'+
        #             'Q_'+cri+'.png',
        #                         bbox_inches='tight')
        
    fig.savefig('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_figures_paper/_v0/b_sup_calibs/'+
                '_Q_'+'criteria_'+cri+'.png',
                            bbox_inches='tight')
        
# fig.savefig('C:/Users/ronan/Downloads/figs_'+iD_explos[0]+'/'+'Q_'+'criteria'+'.png', bbox_inches='tight')

#%% STREAMFLOW CHRONICS ONE

# iD_explo = 'e14'

iD_explos = ['e15','e16']
# iD_explos = ['e16']

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
    
        for id_mod_val in list_id_mod[4:5]:
        
            h5file = BV.calibration_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)
            d = dd.io.load(h5file)
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
                
                mix = Qobs.copy().to_frame()
                mix.columns = ['Qobs']
                mix['Qsim'] = Qmod
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
                ax.plot(Qmod, color='red', lw=1.5, label='Simulated')
                # ax.plot(Qmod-(r*1000), color='darkorange', lw=0.25, label='Simulated')
                ax.set_xlabel('Date')
                ax.set_ylabel('Q [mm/w]')
                # ax.set_yscale('log')
                ax.set_ylim(0,300)
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
                ax.set_zorder(axb.get_zorder() + 1)
                
                fig.tight_layout()
                            
                # fig.savefig(os.path.join(simulations_folder, '_figures',
                #             'STREAMFLOW_'+model_name+'.png'),
                #             bbox_inches='tight')
                
                # plt.close()
                
                # fig.savefig('C:/Users/ronan/Downloads/figs_'+iD_explos[0]+'/'+'Q_'+model_name+'.png',
                #             bbox_inches='tight')
                
                # fig.savefig('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_figures_paper/_v0/b_sup_calibs/'+
                #             'Q_'+model_name+'.png',
                #                         bbox_inches='tight')

dfcrit_Q = df.copy()

#%% STREAMFLOW CRITERIA ONE

iD_explos = ['e15','e16']
# iD_explos = ['e17']

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

n = 12
colors = pl.cm.jet(np.linspace(0,1,n))

# fig, axs = plt.subplots(1,5, figsize=(5*6,5),
#                         # sharey=True
#                         )
# axs = axs.ravel()
for icri, cri in enumerate(['NSElog','NSE','RMSE',
                            # 'KGE','OWN'
                            ][:]):
    
    
    fig, ax = plt.subplots(1,1, figsize=(4.5,3.5),
                            # sharey=True
                            )
    
    # ax = axs[icri]
    # fig, ax = plt.subplots(1,1, figsize=(5,4))
    for imod, mod in enumerate(df['id_mod'].unique()):
        imod=4
        color=colors[imod]
        if imod==0:
            color='k'
        if imod==1:
            color='grey'
        color= 'k'
        dfplot = df[df['id_mod']==imod]
        # ax.plot(dfplot['O'], dfplot[cri],
        #         marker='|', ms=10, mew=1,
        #         lw=2,
        #         color=color)
        # ax.plot(dfplot['O'], dfplot[cri],
        #         marker='o', ms=10, mew=1,
        #         lw=0,
        #         color=color)
        ax.plot(dfplot.sort_values('O')['O'], dfplot.sort_values('O')[cri],
                marker='o', ms=6, mew=1,
                lw=2,
                color='gray')
        # pc = ax.scatter(dfplot['O'], dfplot[cri])
        if cri == 'NSE':
            ax.set_ylabel('NSE [-]')
            ax.set_ylim(0.25,0.40)
        if cri == 'NSElog':
            ax.set_ylabel('$NSE_{log}$ [-]')
            # ax.set_ylim(0.25,0.40)
        if cri == 'RMSE':
            ax.set_ylabel('RMSE [mm/w]')
            ax.set_ylim(28,32)
        ax.set_xlabel('θ [%]')
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
        
        fig.savefig('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_figures_paper/_v0/b_sup_calibs/'+
                    'Q_'+cri+'.png',
                                bbox_inches='tight')
        
plt.tight_layout()

# fig.savefig('C:/Users/ronan/Downloads/figs_'+iD_explos[0]+'/'+'Q_'+'criteria'+'.png', bbox_inches='tight')

#%% SATURATION CHRONICS ALL

# iD_explos = ['e15','e16']
# iD_explos = ['e17']
iD_explos = ['e17','e18']

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
list_sat_obs = [7.5,15] # 7


i=0

for iD_explo in iD_explos:
    
    if iD_explo == 'e17':
        list_id_mod = [0,1,2,3,4,5,6,7,8,9,10,11]
    if iD_explo == 'e18':
        list_id_mod = [1,6,7,8,9,10,11]   
        
    for id_mod_val in list_id_mod[:]:
    
        h5file = BV.calibration_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)
        d = dd.io.load(h5file)
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
            
            plt.close()
            
            fig.savefig('C:/Users/ronan/Downloads/figs_'+iD_explos[0]+'/'+'S_'+model_name+'.png',
                        bbox_inches='tight')
            
            # fig.savefig('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_figures_paper/_v0/03_fig_calibrated/'+
            #             'S_'+model_name+'.png',
            #                         bbox_inches='tight')
        
dfcrit_S = df.copy()

dfcrit_S.to_csv(BV.simulations_folder+'dfcrit_S_'+iD_explo[0]+'.csv', sep=';')    

#%% SATURATION CRITERIA ALL

dfcrit_S = pd.read_csv(BV.simulations_folder+'dfcrit_S_'+iD_explo[0]+'.csv', sep=';')

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

n = 12
colors = pl.cm.plasma_r(np.linspace(0,1,n))

# fig, axs = plt.subplots(1,2, figsize=(5*1,5),
#                         # sharey=True
#                         )
# axs = axs.ravel()

fig, ax = plt.subplots(1,1, figsize=(4.5,3.8),
                        # sharey=True
                        )
# axs = axs.ravel()
for icri, cri in enumerate(['OWN'][:]):
    ax = ax
    # fig, ax = plt.subplots(1,1, figsize=(5,4))
    for imod, mod in enumerate(df['id_mod'].unique()):
        color=colors[imod-1]
        # color='k'
        if imod==0:
            color='k'
        if imod==1:
            color='grey'
        # imod = 4
        dfplot = df[df['id_mod']==imod]
        # ax.plot(dfplot['O'], dfplot[cri],
        #         marker='|', ms=10, mew=1,
        #         lw=2,
        #         color=color)
        # ax.plot(dfplot['O'], dfplot[cri],
        #         marker='o', ms=5, mew=1,
        #         lw=0,
        #         color=color)
        ax.plot(dfplot.sort_values('O')['O'], dfplot.sort_values('O')[cri],
                # marker='|', ms=6, mew=1,
                lw=2,
                color=color)
        # pc = ax.scatter(dfplot['O'], dfplot[cri])
        ax.set_ylabel('Ω [-]')
        ax.set_xlabel('$θ_{0}$ [%]')
        # ax.set_title(cri)
        ax.set_xscale('log')
        # ax.set_ylim(1e-3,1.5e-1)
        # ax.set_yscale('log')
        # if 0<=icri<=1:
            # ax.set_ylim(0,0.4)
        ax.set_yscale('log')
        ax.set_ylim(1e-3,1)
        ax.set_xlim(0.1,16)
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

fig.savefig('C:/Users/ronan/Downloads/figs_'+iD_explos[0]+'/'+'_S_'+'criteria'+'.png', bbox_inches='tight')

fig.savefig('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_figures_paper/_v0/03_fig_calibrated/'+
            'S_'+'criteria'+'.png',
                        bbox_inches='tight')

#%% SATURATION CHRONICS ONE

iD_explos = ['e15','e16']
# iD_explos = ['e16']

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

    for id_mod_val in list_id_mod[4:5]:
    
        h5file = BV.calibration_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)
        d = dd.io.load(h5file)
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
            
            plt.close()
            
            # fig.savefig('C:/Users/ronan/Downloads/figs_'+iD_explos[0]+'/'+'S_'+model_name+'.png',
            #             bbox_inches='tight')
            
            # fig.savefig('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_figures_paper/_v0/03_fig_calibrated/'+
            #             'S_'+model_name+'.png',
            #                         bbox_inches='tight')
        
dfcrit_S = df.copy()

#%% SATURATION CRITERIA ONE

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

n = 12
colors = pl.cm.jet(np.linspace(0,1,n))

# fig, axs = plt.subplots(1,2, figsize=(5*1,5),
#                         # sharey=True
#                         )
# axs = axs.ravel()

fig, ax = plt.subplots(1,1, figsize=(4.5,3.5),
                        # sharey=True
                        )
# axs = axs.ravel()
for icri, cri in enumerate(['OWN'][:]):
    ax = ax
    # fig, ax = plt.subplots(1,1, figsize=(5,4))
    for imod, mod in enumerate(df['id_mod'].unique()):
        color=colors[imod]
        color='k'
        if imod==0:
            color='k'
        if imod==1:
            color='grey'
        imod = 4
        dfplot = df[df['id_mod']==imod]
        # ax.plot(dfplot['O'], dfplot[cri],
        #         marker='|', ms=10, mew=1,
        #         lw=2,
        #         color=color)
        # ax.plot(dfplot['O'], dfplot[cri],
        #         marker='o', ms=5, mew=1,
        #         lw=0,
        #         color=color)
        ax.plot(dfplot.sort_values('O')['O'], dfplot.sort_values('O')[cri],
                marker='o', ms=6, mew=1,
                lw=2,
                color='darkmagenta')
        # pc = ax.scatter(dfplot['O'], dfplot[cri])
        ax.set_ylabel('Ω [-]')
        ax.set_xlabel('θ [%]')
        # ax.set_title(cri)
        ax.set_xscale('log')
        ax.set_ylim(1e-3,1.5e-1)
        # ax.set_yscale('log')
        if 0<=icri<=1:
            # ax.set_ylim(0,0.4)
            ax.set_yscale('log')
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

# fig.savefig('C:/Users/ronan/Downloads/figs_'+iD_explos[0]+'/'+'S_'+'criteria'+'.png', bbox_inches='tight')

fig.savefig('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_figures_paper/_v0/03_fig_calibrated/'+
            'S_'+'criteria'+'.png',
                        bbox_inches='tight')

#%% CONVOLUTION CRITERIA ALL

df_Qcrit = dfcrit_Q.copy()
df_Scrit = dfcrit_S.copy()

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

n = 12
colors = pl.cm.plasma_r(np.linspace(0,1,n))

# fig, axs = plt.subplots(1,2, figsize=(5*1,5),
#                         # sharey=True
#                         )
# axs = axs.ravel()

fig, ax = plt.subplots(1,1, figsize=(4.5,3.5),
                        # sharey=True
                        )
# axs = axs.ravel()
for icri, cri in enumerate(['OWN'][:]):
    ax = ax
    # fig, ax = plt.subplots(1,1, figsize=(5,4))
    for imod, mod in enumerate(df['id_mod'].unique()):
        color=colors[imod-1]
        # color='k'
        if imod==0:
            color='k'
        if imod==1:
            color='grey'
        # imod = 4
        dfplot_Q = df_Qcrit[df_Qcrit['id_mod']==imod]
        dfplot_S = df_Scrit[df_Scrit['id_mod']==imod]

        # ax.plot(dfplot['O'], dfplot[cri],
        #         marker='|', ms=10, mew=1,
        #         lw=2,
        #         color=color)
        # ax.plot(dfplot['O'], dfplot[cri],
        #         marker='o', ms=5, mew=1,
        #         lw=0,
        #         color=color)
        ax.plot(dfplot_Q.sort_values('O')['O'], np.abs(1-dfplot_Q.sort_values('O')['NSE']) + dfplot_S.sort_values('O')['OWN'],
                marker='o', ms=0, mew=0,
                lw=1.5,
                color=color)
        # ax.plot(dfplot_Q.sort_values('O')['O'], dfplot_Q.sort_values('O')['NSE'] + dfplot_S.sort_values('O')['OWN'],
        #         marker='o', ms=0, mew=0,
        #         lw=1.5,
        #         color=color)
        # pc = ax.scatter(dfplot['O'], dfplot[cri])
        ax.set_ylabel('Ω [-]')
        ax.set_xlabel('θ [%]')
        # ax.set_title(cri)
        ax.set_xscale('log')
        # ax.set_ylim(1e-3,1.5e-1)
        ax.set_yscale('log')
        # if 0<=icri<=1:
            # ax.set_ylim(0,0.4)
        # ax.set_yscale('log')
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

fig.savefig('C:/Users/ronan/Downloads/figs_'+iD_explos[0]+'/'+'_S_'+'criteria'+'.png', bbox_inches='tight')

# fig.savefig('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_figures_paper/_v0/03_fig_calibrated/'+
#             'S_'+'criteria'+'.png',
#                         bbox_inches='tight')


#%% ---- METHODOLOGY

#%% CROSS SECTIONS PLOT

iD_explo = 'e14'
iD_explo = 'o15'
iD_explo = 't1'

for id_mod_val in list_id_mod[4:5]:

    # h5file = BV.calibration_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)
    h5file = BV.simulations_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)+'_ALL_'+sce
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
    
    for model_name, flow_model in zip(list_selects[:], list_flowmodel[:]):
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
        sy_grid = flow_model.ps
        # sr_model = flopy.utils.reference.SpatialReference()
        
        # if fig_cross == True:
            
        fig, axs = plt.subplots(1, 2, figsize=(9, 3))
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
        cb = modelxsect.plot_array(val, ax=ax, cmap='viridis', lw=0.1,
                                    norm=mpl.colors.LogNorm(vmin=1e-10, 
                                                            vmax=1e-5)
                                   )
        # pc = modelxsect.plot_array(head_data, masked_values=[-9999], head=head_data,
        #                             cmap='Blues', alpha=0.5, ax=axs[1])
        ax.set_title('Meshgrid Weat to East')
        ax.set_title('Hydraulic conductivity')
        # ax.set_xlim(150, 350)
        # ax.set_ylim(150, 350)
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
        cb = modelxsect.plot_array(sy_grid*100, ax=ax, cmap='plasma', lw=0.1,
                                   # vmin=0, vmax=30,
                                    norm=mpl.colors.LogNorm(vmin=0.1, 
                                                            vmax=10))
        # pc = modelxsect.plot_array(head_data, masked_values=[-9999], head=head_data,
        #                             cmap='Blues', alpha=0.5, ax=axs[1])
        ax.set_title('Meshgrid North to South')
        ax.set_title('Specific yield')
        ax.set_xticks([0,1000,2000,3000,4000])
        fig.suptitle(model_name.upper(), x=0.5, y=1.0, fontsize=8)
        fig.colorbar(cb)
        plt.tight_layout()
        # fig.set_size_inches(6, 3, forward=True)
        
        # fig.savefig(fig_path+'cross_section_'+model_name+'.png', dpi=300, bbox_inches='tight')
        
        # fig.savefig('C:/Users/ronan/Downloads/figs_'+iD_explo+'/'+'CS_'+model_name+'.png',
        #             bbox_inches='tight')
        
#%% GRAPH DECAY COND

# start = 0
# stop = -1 
# step = 17
# list_k_selects = list_model_name[start:stop:step]
# list_k_flowmodel = list_flow_model[start:stop:step]

figk, axk = plt.subplots(1, 1, figsize=(4, 4))

iD_explo = 'e14'

n = 12
# colors = pl.cm.jet(np.linspace(0,1,n))
colors = pl.cm.plasma_r(np.linspace(0,1,n))
    
for id_mod_val in list_id_mod[:]:

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
    
    for model_name, flow_model in zip(list_selects[:], list_flowmodel[:]):
        print(model_name)
        # if model_name == 'egu1_0_500.0-0-0.0058-30.0':
    
        # id_model = int(model_name.split('_')[1])
        
        decay_k = model_name.split('_')[-1].split('-')[0]
                
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
        sy_grid = flow_model.ps
        # sr_model = flopy.utils.reference.SpatialReference()
        
        zall = flow_model.dem - flow_model.zbot
        list_z = []
        list_k = []
        list_p = []
        for i in range(len(zall)):
            list_z.append(zall[i].mean())
            list_k.append((hk_grid.array/24/3600)[i].mean())
            list_p.append((sy_grid*100)[i].mean())
        if id_mod_val == 0:
            c = 'k'
        if id_mod_val == 1 :
            c = 'grey'
        if id_mod_val > 1:
            c = colors[id_mod_val]
        axk.plot(list_k, list_z, color=c, lw=2, label=str(decay_k))
        
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


figk.savefig('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_figures_paper/_v0/a_sup_decay/'+
            'K_'+'.png',
                        bbox_inches='tight')

#%% GRAPH DECAY PORO

# start = 0
# stop = -1 
# step = 17
# list_k_selects = list_model_name[start:stop:step]
# list_k_flowmodel = list_flow_model[start:stop:step]

figp, axp = plt.subplots(1, 1, figsize=(4, 4))

iD_explo = 'e14'

n = 12
colors = pl.cm.jet(np.linspace(0,1,n))

for id_mod_val in list_id_mod[:]:

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

    for model_name, flow_model in zip(list_selects[:], list_flowmodel[:]):
        
        print(model_name)
        # if model_name == 'egu1_0_500.0-0-0.0058-30.0':
        # try:
            
        # id_model = int(model_name.split('_')[1])
        
        decay_k = model_name.split('_')[-1].split('-')[0]

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
        sy_grid = flow_model.ps
        # sr_model = flopy.utils.reference.SpatialReference()
        
        zall = flow_model.dem - flow_model.zbot
        list_z = []
        list_k = []
        list_p = []
        for j in range(len(zall)):
            list_z.append(zall[j].mean())
            list_k.append((hk_grid.array/24/3600)[j].mean())
            list_p.append((sy_grid*100)[j].mean())
        if id_mod_val == 0:
            c = 'k'
            zo = 10
        else:
            zo=0
        if id_mod_val == 1 :
            c = 'grey'
        if id_mod_val > 1:
            c = colors[id_mod_val]
        axp.plot(list_p, list_z, color=c, label=str(decay_k), zorder=zo)
        # print(np.array(list_p).mean())
            
    # axp.set_xscale('log')
    axp.invert_yaxis()
    axp.set_xlim(0, 16)
    axp.set_ylim(1000, 0)
    
    axp.xaxis.tick_top()
    axp.set_xlabel('θ [%]')
    axp.xaxis.set_label_position('top') 
    axp.set_ylabel('Depth [m]')
    # axp.set_xscale('log')
    axp.spines[['right', 'bottom']].set_visible(False)
    axp.tick_params(right=False)
    # axp.legend(loc='lower right', frameon=False)
        
    # figp.savefig('C:/Users/ronan/Downloads/figs_'+iD_explo+'/'+'P_'+'decay_'+str(id_mod_val)+'.png',
    #             bbox_inches='tight')

figp.savefig('C:/Users/ronan/Downloads/figs_'+iD_explo+'/'+'P_'+'decay'+'.png',
            bbox_inches='tight')

# begin_by = 'C:/Users/ronan/Downloads/figs_'+iD_explo+'/'+'P_'+'decay_'
# filenames = sorted(glob.glob(begin_by+'*.png'), key=os.path.getmtime)
# images = []
# for filename in filenames:
#     images.append(imageio.imread(filename))
# gif_name = +'P_'+'decay'
# imageio.mimsave(fig_path+gif_name+'.gif', images,
#                 duration=10, loop=0)

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

iD_explo = 'e14'

for id_mod_val in list_id_mod[:]:

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

    for model_name, flow_model in zip(list_selects[:], list_flowmodel[:]):
    
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
        sy_grid = flow_model.ps
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

#%% CHECK PLOT COND PORO

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

n = 12

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
fig.savefig('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_figures_paper/_v0/a_sup_decay/'+
            'Pmean_'+'.png',
                        bbox_inches='tight')
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
fig.savefig('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_figures_paper/_v0/a_sup_decay/'+
            'Pmax_'+'.png',
                        bbox_inches='tight')
# dk_max.T.plot(lw=0, marker='o')
# dk_mean.T.plot(lw=0, marker='o')

# dp_max.T.plot(lw=0, marker='o')
# dp_mean.T.plot(lw=0, marker='o')


#%% ---- PROJECTION

#%% UPDATE PARAMETERS

# iD_explo = 't1' # montly projection test
iD_explo = 'p1' # montly projection all
iD_explo = 'p2' # montly projection 6 models for 3 scenarios

decay_factor = 2

vers = 'v7' # dichotomy isba
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
list_d_values = [20]
list_cond_decay = list(1/np.array(list_d_values))

# Models
list_id_mod = [4]

df_optim = pd.read_csv(BV.calibration_folder+'/'+'_models'+'_optimum_'+vers+'.csv', sep=';')

# For transient
list_cond_decay = list_cond_decay
list_bottom = list_bottom
list_koptim = df_optim['K'][4:5]
list_kroptim = df_optim['KR'][4:5]

list_porosity = [0.9/100]

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

run_model = True
# run_model = False

fig, ax = plt.subplots(1,1, figsize=(7,4))

for sce in ['RCP26','RCP45','RCP85']:
# for sce in ['RCP45']:
    
    rec_keep = all_proj.filter(regex='REC').filter(regex=sce).filter(regex=mod_keep)
    rec_keep = rec_keep.mean(skipna=True, axis=1)
    # rec_keep = select_period(rec_keep,1975,1976)
    run_keep = all_proj.filter(regex='RUN').filter(regex=sce).filter(regex=mod_keep)
    run_keep = run_keep.mean(skipna=True, axis=1)
    # rec_keep = select_period(rec_keep,1975,1976)
    
    recharge_w_sli = rec_keep.resample('M').mean()
    runoff_w_sli = run_keep.resample('M').mean()
    
    # print(select_period(rea_recharge_isba+rea_runoff_isba, 1975, 2004).mean()*1000*365)
    # print(select_period(rec_keep+run_keep, 1975, 2004).mean()*1000*365)
        
    ### IF WEEKLY ###
    """
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
    """
    
    # BV.climatic.update_recharge(select_period(recharge_w_sli, 2022, 2023), sim_state=sim_state)
    # BV.climatic.update_runoff(select_period(runoff_w_sli, 2022, 2023), sim_state=sim_state)
    
    BV.climatic.update_recharge(select_period(recharge_w_sli, 1975, 2099), sim_state=sim_state)
    BV.climatic.update_runoff(select_period(runoff_w_sli, 1975, 2099), sim_state=sim_state)
    
    # recharge_ete = sim2[sim2.index.month.isin([7,8,9])]
    # recharge_ete = (recharge_ete['DRAINC_Q'] * norm_factor) / 1000 # mm/d to m/d
    # print(BV.climatic.recharge.mean())
    
    first_clim = select_period(recharge_w_sli,1980,2004).mean() # or 'first or value
    print(first_clim)
    BV.climatic.update_first_clim(first_clim)
    
    ax.plot(BV.climatic.recharge)
    ax.axhline(first_clim, c='k')
    ax.set_yscale('log')

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
for sce in ['RCP26','RCP45','RCP85']:
    
    for id_mod_val in list_id_mod[:]:
    
        h5file = BV.simulations_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)+'_ALL_'+sce
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
                                      intermittency_monthly = True,
                                      intermittency_weekly = False, # True
                                      intermittency_daily = False,
                                      export_all_tif = False)
    
            timeseries_results = BV.postprocessing_timeseries(model_modflow=model_modflow,
                                                              model_modpath=False,
                                                              actual_date=True, 
                                                              subbasin_results=True,
                                                              freq_time='M') # 'W'
    
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

#%% STREAMFLOW CHRONICS

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

col_list = ['dodgerblue','darkorange','red']
sce_list = ['RCP26','RCP45','RCP85']
dict_scecol = dict(zip(sce_list, col_list))

fig, ax = plt.subplots(1, 1, figsize=(10,3))

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
                # ax.plot(Qobs, color='k', lw=1, ls='-', zorder=0, label='Observed')
                ax.plot(Qmod, color=dict_scecol[sce], lw=1, label=sce)
                ax.plot(select_period(Qmod, 1975, 2010), color='k', lw=1)
                # ax.plot(Qmod-(r*1000), color='darkorange', lw=0.25, label='Simulated')
                ax.set_xlabel('Date')
                ax.set_ylabel('Q [mm/months]')
                # ax.set_yscale('log')
                # ax.set_ylim(0.1,100)
                years_maj = mdates.YearLocator(30)   # every year
                # months_maj = mdates.MonthLocator()  # every x month
                ax.xaxis.set_major_locator(years_maj)
                # ax.xaxis.set_minor_locator(months_maj)
                ax.set_xlim(pd.to_datetime('1980'), pd.to_datetime('2100'))
                ax.legend(loc='lower left')
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

#%% SATURATION CHRONICS

iD_explo = 'p2'

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
            
            ax.set_ylim(5,20)
            ax.set_yticks([5, 10, 15, 20])
            ax.set_ylabel('$A_{sat}$ [%]')
            ax.set_xlim(pd.to_datetime('1980'), pd.to_datetime('2100'))
            plt.xticks(rotation=0, ha="right")
        
            years_maj = mdates.YearLocator(30)   # every year
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

#%% ---- GOOD PROJECTIONS PLOTS

#%% PI ANOMALIES 3 HORIZONS

iD_explo = 'p2'
list_id_mod = [4]

sce_list = ['RCP85']
# sce_list = ['RCP26']
sce_list = ['RCP26','RCP45','RCP85']

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

            begin_h = 5*12
            end_h = 35*12
            
            # Historic
            if begin_h == 0:
                acc_npy_h = list(acc_npy.items())[:end_h]
            else:
                acc_npy_h = list(acc_npy.items())[begin_h:end_h]
            acc_npy_h = list(acc_npy_h)[:]
            for key in range(len(acc_npy_h)):
                acc_npy_h[key] = np.ma.masked_array(acc_npy_h[key][1], mask=(mask<-1e10))
            zero = acc_npy[0] * 0
            for i in range(len(acc_npy_h)):
                tempo = acc_npy_h[i].copy()
                tempo[tempo>0] = 1
                zero = zero + tempo
            days_flux_h = zero.copy() / len(acc_npy_h)
            
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
                acc_npy_f = list(acc_npy_f)[:]
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

                    
                    pc = plt.imshow(np.ma.masked_where((days_flux_ano>-1),
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
                                                cmap = mpl.colors.ListedColormap('dimgray'))
                    
                    pc = ax.imshow(np.ma.masked_where((days_flux_f==0)|(days_flux_h!=0),
                                                      days_flux_f),
                                                cmap = mpl.colors.ListedColormap('navy'))
                    
                    plt.imshow(box, cmap = 'Greys', alpha=0.25, zorder=-1000)
                    
                    ax.imshow(np.ma.masked_where(mask>0, mask),
                                                cmap = mpl.colors.ListedColormap('white'),
                                                alpha=0.5)
                    
                    ax.get_xaxis().set_visible(False)
                    ax.get_yaxis().set_visible(False)
                    # ax.axis('off')
                    
                    ax.imshow(line, cmap=mpl.colors.ListedColormap('k'))
                    # ax.imshow(box, cmap=mpl.colors.ListedColormap('k'))
                    
                    # plt.subplots_adjust(hspace = -0.6)

                    ax.set_title(mod+'_'+sce+'_'+str(season)+'_'+str(interv), fontsize=8)
                    
                    fig.savefig('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_figures_paper/_v0/04_fig_piproj/'+
                                mod+'_'+sce+'_'+str(season)+'_'+str(interv)+'.png',
                                            bbox_inches='tight')

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
                    
superficie.to_csv(folder_fig + 'TABLE_PI_ANOMALY_' + str('ALL') + '.csv', sep=';')

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
                    
                acc_npy = list(acc_npy_raw.items())[5*12:35*12]
                sers = pd.DataFrame()
                for key in range(len(acc_npy)):
                    mask = imageio.imread(BV.geographic.watershed_dem)
                    # mask = imageio.imread(BV.geographic.watershed_box_buff_dem)
                    acc_npy[key] = np.ma.masked_array(acc_npy[key][1], mask=themask)
                    # acc_npy[key] = np.ma.masked_array(acc_npy[key][1], mask=(mask>2000))
                    # acc_npy[key] = acc_npy[key][1][(acc_npy[key][1] > 1600) & (acc_npy[key][1] < 2000)]
                    # acc_npy[key][0] = np.ma.masked_where(mask < 1600)
                    # acc_npy[key][0] = np.ma.masked_where(mask > 2000)
                    sers[str(key)] = acc_npy[key].flatten() / (acc_npy[key].count()*25*25) * 1000
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
                        acc_npy = list(acc_npy_raw.items())[interv[0]*12:]
                    else:
                        acc_npy = list(acc_npy_raw.items())[interv[0]*12:interv[1]*12]
                    sers = pd.DataFrame()
                    for key in range(len(acc_npy)):
                        mask = imageio.imread(BV.geographic.watershed_dem)
                        # mask = imageio.imread(BV.geographic.watershed_box_buff_dem)
                        acc_npy[key] = np.ma.masked_array(acc_npy[key][1], mask=themask)
                        # acc_npy[key] = np.ma.masked_array(acc_npy[key][1], mask=(mask>2000))
                        # acc_npy[key] = acc_npy[key][1][(acc_npy[key][1] > 1600) & (acc_npy[key][1] < 2000)]
                        # acc_npy[key][0] = np.ma.masked_where(mask < 1600)
                        # acc_npy[key][0] = np.ma.masked_where(mask > 2000)
                        sers[str(key)] = acc_npy[key].flatten() / (acc_npy[key].count()*25*25) * 1000
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
                    
                    boxprops = dict(linestyle='-', linewidth=1, color='black',
                                    facecolor=dict_scecol[sce], alpha=0.40)
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
                                      patch_artist=True, boxprops=boxprops)
                    for element in bp['whiskers']:
                        element.set_color('k')
                        element.set_linestyle('-')
                                        
                    ax.vlines(x=ad, 
                                ymin=d.quantile(0.75), 
                                ymax=d.quantile(0.90), color='k', zorder=2)
                    ax.vlines(x=ad, 
                                ymin=d.quantile(0.10), 
                                ymax=d.quantile(0.25), color='k', zorder=2)
                    ax.plot(ad, 
                              d.quantile(0.10), color='k', zorder=2, lw=0,
                              marker='_', mew=1)
                    ax.plot(ad, 
                              d.quantile(0.90), color='k', zorder=2, lw=0,
                              marker='_', mew=1)
                      
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
                    
                    # ax.get_xaxis().set_visible(False)
                    ax.axes.xaxis.set_ticklabels([])
                    
            # ax.set_yscale('log')

fig.savefig('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_figures_paper/_v0/05_fig_qproj/'+
            'BOXPLOT_OUTFLOW_ALTITUDE'+'.png',
                        bbox_inches='tight')

#%% BOX PLOT OUTFLOW - PETLANDS

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
fig, ax = plt.subplots(1,1, figsize=(6,3.8))

for ic, sce in enumerate(sce_list):
    years = pd.date_range(start='01/01/1975', end='31/12/2099', freq='M').year.unique()
    # model_name = 'p2_model4_20.0-0-3.38e-06_40.0-0.9-1.02e-06_ALL-RCP85-1975-2099'
    # Smod = pd.read_csv(BV.simulations_folder+'/'+model_name+'/_postprocess/_timeseries/_simulated_timeseries.csv', sep=';',
    #                    index_col='date', parse_dates=True)
    # df_yearly = pd.DataFrame(np.nan, index=Smod.index, columns=years)
    # df_pi = pd.DataFrame(np.nan, index=range(len(mask.flatten())), columns=years)
    
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

            for i in range(4):
                print(i)
                if i == 0:
                    themask = (mask_lasset < 0)
                if i == 1:
                    themask = (mask_breton < 0)
                if i == 2:
                    themask = (mask_grenou < 0)
                if i == 3:
                    themask = (mask_bombee < 0)
                    
                acc_npy = list(acc_npy_raw.items())[5*12:35*12]
                sers = pd.DataFrame()
                for key in range(len(acc_npy)):
                    # mask = imageio.imread(BV.geographic.watershed_dem)
                    # mask = imageio.imread(BV.geographic.watershed_box_buff_dem)
                    acc_npy[key] = np.ma.masked_array(acc_npy[key][1], mask=themask)
                    # acc_npy[key] = np.ma.masked_array(acc_npy[key][1], mask=(mask>2000))
                    # acc_npy[key] = acc_npy[key][1][(acc_npy[key][1] > 1600) & (acc_npy[key][1] < 2000)]
                    # acc_npy[key][0] = np.ma.masked_where(mask < 1600)
                    # acc_npy[key][0] = np.ma.masked_where(mask > 2000)
                    sers[str(key)] = acc_npy[key].flatten() / (acc_npy[key].count()*25*25) * 1000
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
                        acc_npy = list(acc_npy_raw.items())[interv[0]*12:]
                    else:
                        acc_npy = list(acc_npy_raw.items())[interv[0]*12:interv[1]*12]
                    sers = pd.DataFrame()
                    for key in range(len(acc_npy)):
                        mask = imageio.imread(BV.geographic.watershed_dem)
                        # mask = imageio.imread(BV.geographic.watershed_box_buff_dem)
                        acc_npy[key] = np.ma.masked_array(acc_npy[key][1], mask=themask)
                        # acc_npy[key] = np.ma.masked_array(acc_npy[key][1], mask=(mask>2000))
                        # acc_npy[key] = acc_npy[key][1][(acc_npy[key][1] > 1600) & (acc_npy[key][1] < 2000)]
                        # acc_npy[key][0] = np.ma.masked_where(mask < 1600)
                        # acc_npy[key][0] = np.ma.masked_where(mask > 2000)
                        sers[str(key)] = acc_npy[key].flatten() / (acc_npy[key].count()*25*25) * 1000
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
                    
                    boxprops = dict(linestyle='-', linewidth=1, color='black',
                                    facecolor=dict_scecol[sce], alpha=0.40)
                    medianprops = dict(linestyle='-', linewidth=1, color='black')
                    meanpointprops = dict(markersize=0, marker='o', markeredgecolor='black',
                                          markerfacecolor='k', linestyle='-')
                    
                    posbas = 0 - 0.15
                    if (interv_i==0) & (i==0) & (sce=='RCP26'):
                        ad = posbas - 0.90
                    if (interv_i==0) & (i==0) & (sce=='RCP45'):
                        ad = posbas - 0.75
                    if (interv_i==0) & (i==0) & (sce=='RCP85'):
                        ad = posbas - 0.60
                    if (interv_i==0) & (i==1) & (sce=='RCP26'):
                        ad = posbas - 0.45
                    if (interv_i==0) & (i==1) & (sce=='RCP45'):
                        ad = posbas - 0.30
                    if (interv_i==0) & (i==1) & (sce=='RCP85'):
                        ad = posbas - 0.15
                    if (interv_i==0) & (i==2) & (sce=='RCP26'):
                        ad = posbas + 0
                    if (interv_i==0) & (i==2) & (sce=='RCP45'):
                        ad = posbas + 0.15
                    if (interv_i==0) & (i==2) & (sce=='RCP85'):
                        ad = posbas + 0.30
                    if (interv_i==0) & (i==3) & (sce=='RCP26'):
                        ad = posbas + 0.45
                    if (interv_i==0) & (i==3) & (sce=='RCP45'):
                        ad = posbas + 0.60
                    if (interv_i==0) & (i==3) & (sce=='RCP85'):
                        ad = posbas + 0.75

                    if (interv_i==1) & (i==0) & (sce=='RCP26'):
                        ad = 2 - 0.90
                    if (interv_i==1) & (i==0) & (sce=='RCP45'):
                        ad = 2 - 0.75
                    if (interv_i==1) & (i==0) & (sce=='RCP85'):
                        ad = 2 - 0.60
                    if (interv_i==1) & (i==1) & (sce=='RCP26'):
                        ad = 2 - 0.45
                    if (interv_i==1) & (i==1) & (sce=='RCP45'):
                        ad = 2 - 0.30
                    if (interv_i==1) & (i==1) & (sce=='RCP85'):
                        ad = 2 - 0.15
                    if (interv_i==1) & (i==2) & (sce=='RCP26'):
                        ad = 2 + 0
                    if (interv_i==1) & (i==2) & (sce=='RCP45'):
                        ad = 2 + 0.15
                    if (interv_i==1) & (i==2) & (sce=='RCP85'):
                        ad = 2 + 0.30
                    if (interv_i==1) & (i==3) & (sce=='RCP26'):
                        ad = 2 + 0.45
                    if (interv_i==1) & (i==3) & (sce=='RCP45'):
                        ad = 2 + 0.60
                    if (interv_i==1) & (i==3) & (sce=='RCP85'):
                        ad = 2 + 0.75

                    posbas = 4 + 0.15
                    if (interv_i==2) & (i==0) & (sce=='RCP26'):
                        ad = posbas - 0.90
                    if (interv_i==2) & (i==0) & (sce=='RCP45'):
                        ad = posbas - 0.75
                    if (interv_i==2) & (i==0) & (sce=='RCP85'):
                        ad = posbas - 0.60
                    if (interv_i==2) & (i==1) & (sce=='RCP26'):
                        ad = posbas - 0.45
                    if (interv_i==2) & (i==1) & (sce=='RCP45'):
                        ad = posbas - 0.30
                    if (interv_i==2) & (i==1) & (sce=='RCP85'):
                        ad = posbas - 0.15
                    if (interv_i==2) & (i==2) & (sce=='RCP26'):
                        ad = posbas + 0
                    if (interv_i==2) & (i==2) & (sce=='RCP45'):
                        ad = posbas + 0.15
                    if (interv_i==2) & (i==2) & (sce=='RCP85'):
                        ad = posbas + 0.30
                    if (interv_i==2) & (i==3) & (sce=='RCP26'):
                        ad = posbas + 0.45
                    if (interv_i==2) & (i==3) & (sce=='RCP45'):
                        ad = posbas + 0.60
                    if (interv_i==2) & (i==3) & (sce=='RCP85'):
                        ad = posbas + 0.75
                                        
                    bp = ax.boxplot(d, widths=0.15,
                                    positions=[ad],
                                      whis=False, showfliers=False, showmeans=False, 
                                      medianprops=medianprops, meanprops=meanpointprops,
                                      patch_artist=True, boxprops=boxprops)
                    for element in bp['whiskers']:
                        element.set_color('k')
                        element.set_linestyle('-')
                                        
                    ax.vlines(x=ad, 
                                ymin=d.quantile(0.75), 
                                ymax=d.quantile(0.90), color='k', zorder=2)
                    ax.vlines(x=ad, 
                                ymin=d.quantile(0.10), 
                                ymax=d.quantile(0.25), color='k', zorder=2)
                    ax.plot(ad, 
                              d.quantile(0.10), color='k', zorder=2, lw=0,
                              marker='_', mew=1)
                    ax.plot(ad, 
                              d.quantile(0.90), color='k', zorder=2, lw=0,
                              marker='_', mew=1)
                      
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
                    
                    ax.set_ylim(-100,50)
                    ax.set_yticks([-100,-75,-50,-25,0,25,50])
            
                    ax.axes.xaxis.set_ticklabels([])
            
            # ax.set_yscale('log')

fig.savefig('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_figures_paper/_v0/05_fig_qproj/'+
            'BOXPLOT_OUTFLOW_PEATLANDS'+'.png',
                        bbox_inches='tight')

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
    
    fig.savefig('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_figures_paper/_v0/c_sup_models/'+
                'EVOL_DAYS_DRY-'+sce+'.png',
                            bbox_inches='tight')

#%% EVOLUTION CILMAT
 
if 'all_proj_clim' not in globals():
    all_proj_clim = pd.read_csv(BV.stable_folder + '/driasclimat/' + '_ALL_D.csv', sep=';', index_col=0, parse_dates=True)
    all_proj_eau =  pd.read_csv(BV.stable_folder + '/driaseau/' + '_ALL_D.csv', sep=';', index_col=0, parse_dates=True)

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

# for sce in ['historic','RCP26','RCP45','RCP85']:
#     fig, ax = plt.subplots(1,1)
#     for mod in mod_list:
#         if mod in ['MPI-CCL','ECE-RCA','MPI-R09']:
#             val = all_proj_clim['PPTT'+'_'+mod+'_'+sce].resample('Y').mean()*3600*24*365
#         else:
#             val = all_proj_clim['PPTT'+'_'+mod+'_'+sce].resample('Y').mean()*10
#         plt.plot(val, label=mod)
#         print(mod, val.mean())      
#     plt.legend()

for var in ['TASM','PPTT','SNOW'][:]:
            
    fig, ax = plt.subplots(1,1, figsize=(10,4))
    
    sce_list = ['historic','RCP26','RCP45','RCP85']
    
    col_list = ['dimgrey','dodgerblue','orange','red']
    col_list_b = ['k','navy','darkorange','darkred']
    dict_c = dict(zip(sce_list, col_list))
    dict_c_b = dict(zip(sce_list, col_list_b))
    
    for sce in sce_list:
        
        df = pd.DataFrame()
        dproj = all_proj_clim.copy()
        dproj = dproj.filter(regex=mod_keep)
        
        if var =='PPTT':
            for mod in mod_list:
                if mod in ['MPI-CCL','ECE-RCA','MPI-R09']:
                    dproj[var+'_'+mod+'_'+'historic'] = dproj[var+'_'+mod+'_'+'historic']*3600*24*365
                    if sce != 'historic':
                        dproj[var+'_'+mod+'_'+sce] = dproj[var+'_'+mod+'_'+sce]*3600*24*365
                else:
                    dproj[var+'_'+mod+'_'+'historic'] = dproj[var+'_'+mod+'_'+'historic']*10
                    if sce != 'historic':
                        dproj[var+'_'+mod+'_'+sce] = dproj[var+'_'+mod+'_'+sce]*10
        
                    print(var, sce, dproj[var+'_'+mod+'_'+sce].mean())
        
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
        if var == 'TASM':
            ax.plot(d50.resample('Y').mean().rolling(window=10).mean(), c=dict_c_b[sce], lw=2)
            ax.plot(dm.resample('Y').mean().rolling(window=10).mean(), c=dict_c_b[sce], lw=1)
            ax.fill_between(d50.resample('Y').mean().rolling(window=10).mean().index,
                            d25.resample('Y').mean().rolling(window=10).mean(),
                            d75.resample('Y').mean().rolling(window=10).mean(),
                            color=dict_c[sce], alpha=0.25, ec='None')
        if var == 'PPTT':
                ax.plot(d50.resample('Y').mean().rolling(window=10).mean(), c=dict_c_b[sce], lw=2)
                ax.plot(dm.resample('Y').mean().rolling(window=10).mean(), c=dict_c_b[sce], lw=1)
                ax.fill_between(d50.resample('Y').mean().rolling(window=10).mean().index,
                                d25.resample('Y').mean().rolling(window=10).mean(),
                                d75.resample('Y').mean().rolling(window=10).mean(),
                                color=dict_c[sce], alpha=0.25, ec='None')
        if var == 'SNOW':
            ax.plot(d50.resample('Y').mean().rolling(window=10).mean()*3600*24*365, c=dict_c_b[sce], lw=2)
            ax.plot(dm.resample('Y').mean().rolling(window=10).mean()*3600*24*365, c=dict_c_b[sce], lw=1)
            ax.fill_between(d50.resample('Y').mean().rolling(window=10).mean().index,
                            d25.resample('Y').mean().rolling(window=10).mean()*3600*24*365,
                            d75.resample('Y').mean().rolling(window=10).mean()*3600*24*365,
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

    fig.savefig('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_figures_paper/_v0/c_sup_models/'+
                'EVOL_'+var+'-'+sce+'.png',
                            bbox_inches='tight')

#%% EVOLUTION EAU
 
if 'all_proj_clim' not in globals():
    all_proj_clim = pd.read_csv(BV.stable_folder + '/driasclimat/' + '_ALL_D.csv', sep=';', index_col=0, parse_dates=True)
    all_proj_eau =  pd.read_csv(BV.stable_folder + '/driaseau/' + '_ALL_D.csv', sep=';', index_col=0, parse_dates=True)

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

# plt.plot(all_proj_eau['SWE'+'_'+'MPI-CCL'+'_'+sce].resample('Y').mean()*365)
# plt.plot(all_proj_clim['SNOW'+'_'+'MPI-CCL'+'_'+sce].resample('Y').mean()*3600*24*365)

# for mod in mod_list:
#     # if mod in ['MPI-CCL','ECE-RCA','MPI-R09']:
#     val = all_proj_eau['SWE'+'_'+mod+'_'+sce].resample('Y').mean()*365/10
#     # else:
#     #     val = all_proj_clim['PPTT'+'_'+mod+'_'+sce].resample('Y').mean()*10
#     plt.plot(val, label=mod)
#     print(mod, val.mean())      
# plt.legend()

df = pd.DataFrame()
dproj = all_proj_eau.copy()
dproj = dproj.filter(regex=mod_keep)

for var in ['ETP','RUN','REC','SWE','SWI'][1:]:
            
    fig, ax = plt.subplots(1,1, figsize=(10,4))
    
    sce_list = ['historic','RCP26','RCP45','RCP85']
    
    col_list = ['dimgrey','dodgerblue','orange','red']
    col_list_b = ['k','navy','darkorange','darkred']
    dict_c = dict(zip(sce_list, col_list))
    dict_c_b = dict(zip(sce_list, col_list_b))
    
    for sce in sce_list:
        print(var, sce)
        
        d_hist = dproj.filter(regex=var).filter(regex='historic')
        d_hist = select_period(d_hist, 1975, 2004)
        
        d_tot = dproj.filter(regex=var).filter(regex=sce)
        d_tot = select_period(d_tot, 1975, 2100)
        
        d_fut = dproj.filter(regex=var).filter(regex=sce)
        d_fut = select_period(d_fut, 2006, 2100)

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
        if var != 'SWE':
            ax.plot(d50.resample('Y').sum().rolling(window=10).mean(), c=dict_c_b[sce], lw=2)
            ax.plot(dm.resample('Y').sum().rolling(window=10).mean(), c=dict_c_b[sce], lw=1)
            ax.fill_between(d50.resample('Y').sum().rolling(window=10).mean().index,
                            d25.resample('Y').sum().rolling(window=10).mean(),
                            d75.resample('Y').sum().rolling(window=10).mean(),
                            color=dict_c[sce], alpha=0.25, ec='None')
        else:
            ax.plot(d50.resample('Y').sum().rolling(window=10).mean()/10, c=dict_c_b[sce], lw=2)
            ax.plot(dm.resample('Y').sum().rolling(window=10).mean()/10, c=dict_c_b[sce], lw=1)
            ax.fill_between(d50.resample('Y').sum().rolling(window=10).mean().index,
                            d25.resample('Y').sum().rolling(window=10).mean()/10,
                            d75.resample('Y').sum().rolling(window=10).mean()/10,
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

    fig.savefig('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_figures_paper/_v0/c_sup_models/'+
                'EVOL_'+var+'-'+sce+'.png',
                            bbox_inches='tight')

#%% ---- BULK PROJECTIONS PLOT

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

#%% PI PROJECTIONS SEASON MAPPING

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

#%% FIND DROUGHTS

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

#%% ---- RESIDENCE

#%% ---- DISCUSSION

#%% ---- NOTES

#%% BULK

"""
wbt.polygons_to_lines(
    'G:/UNINE/SIMULATIONS/VALLON/_data/_gis/Wetlands/REN_data/REN_1_LV95/humide.shp', 
    'G:/UNINE/SIMULATIONS/VALLON/_data/_gis/Wetlands/REN_data/REN_1_LV95/humide_line.shp', 
    # callback=default_callback
)
wbt.polygons_to_lines(
    'G:/UNINE/SIMULATIONS/VALLON/_data/_gis/Wetlands/feuchtgebiete_1850_2010/CH_1850_REC_OHNE_GROSSPRJ.shp', 
    'G:/UNINE/SIMULATIONS/VALLON/_data/_gis/Wetlands/feuchtgebiete_1850_2010/CH_1850_REC_OHNE_GROSSPRJ_line.shp', 
    # callback=default_callback
)
wbt.polygons_to_lines(
    'G:/UNINE/SIMULATIONS/VALLON/_data/_gis/Wetlands/feuchtgebiete_1850_2010/CH_1900_REC_OHNE_GROSSPRJ.shp', 
    'G:/UNINE/SIMULATIONS/VALLON/_data/_gis/Wetlands/feuchtgebiete_1850_2010/CH_1900_REC_OHNE_GROSSPRJ_line.shp', 
    # callback=default_callback
)
wbt.polygons_to_lines(
    'G:/UNINE/SIMULATIONS/VALLON/_data/_gis/Wetlands/feuchtgebiete_1850_2010/CH_1950_REC_OHNE_GROSSPRJ.shp', 
    'G:/UNINE/SIMULATIONS/VALLON/_data/_gis/Wetlands/feuchtgebiete_1850_2010/CH_1950_REC_OHNE_GROSSPRJ_line.shp', 
    # callback=default_callback
)
"""

# ax.xaxis.set(
#     minor_locator=mdates.WeekdayLocator(),               # make minor ticks on each Tuesday
#     minor_formatter=mdates.DateFormatter('%d\n%a'),      # format minor ticks
#     major_locator=mdates.MonthLocator(),                 # make major ticks on first day of each month
#     major_formatter=mdates.DateFormatter('\n\n\n%b\n%Y') # format major ticks
# );

### Resampling
"""
wbt.resample(
    data_path+'DEM_2m.tif', 
    data_path+'DEM_10m.tif', 
    cell_size=10, 
    base=None, 
    method="cc")
wbt.modify_no_data_value(
    data_path+'DEM_10m.tif', 
    new_value="-99999")

with rasterio.open(data_path+'DEM_10m.tif') as src:
    data = src.read()
    ras_meta = src.profile
    ras_meta['crs'] = 'EPSG:2056'
with rasterio.open(data_path+'DEM_10m.tif', "w", **ras_meta) as dest:
    dest.write(data)
"""

    # plt.ticklabel_format(style='plain')
    # ax.set_ylim(0.99,1.01)
    # from matplotlib.ticker import ScalarFormatter
    # plt.gca().yaxis.set_major_formatter(ScalarFormatter())
    # ax.ticklabel_format(axis='y', scilimits=(0,10))
    # plt.ticklabel_format(style='plain', axis='x', useOffset=False)
    # import matplotlib.ticker as mticker
    # plt.gca().yaxis.set_major_locator(mticker.MultipleLocator(1))
    # ax.ticklabel_format(useOffset=False)
    # ax.ticklabel_format(useOffset=False, style='plain')
    # ax.ticklabel_format(style='plain', axis='y')

#%% HUGO POINTS RASTER

# df = pd.DataFrame({'x': [x_outlet], 'y': [y_outlet]})
# gdf = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df['x'], df['y']), crs=crs_proj)
# outlet_shp = os.path.join(self.gis_path, 'outlet.shp')
# gdf.to_file(outlet_shp)

# wbt.vector_points_to_raster(
#     i, 
#     output, 
#     field="FID", 
#     assign="last", 
#     nodata=True, 
#     cell_size=None, 
#     base=None, 
#     callback=default_callback
# )

#%% MERGE HYDRO OBSERVED

import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = True

wbt.vector_lines_to_raster('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_data/_hydrography/_manage_osm/_osm_water_lines_custom.shp',
                           'D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_data/_hydrography/_manage_osm/_osm_water_lines_custom.tif',
                           base = 'D:/Users/abherve/ONEDRIVE_UNINECHYN/OneDrive - unine.ch/SIMULATIONS/Lasset/results_stable/geographic/watershed_dem.tif')
wbt.raster_to_vector_points('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_data/_hydrography/_manage_osm/_osm_water_lines_custom.tif',
                            'D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_data/_hydrography/_manage_osm/_osm_water_lines_custom_topt.shp')

x = gpd.read_file('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_data/_hydrography/_manage_osm/_osm_water_polygons_custom.shp')
x.to_file('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_data/_hydrography/_manage_osm/_osm_water_polygons_custom.shp')
wbt.vector_polygons_to_raster('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_data/_hydrography/_manage_osm/_osm_water_polygons_custom.shp',
                           'D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_data/_hydrography/_manage_osm/_osm_water_polygons_custom.tif',
                           base = 'D:/Users/abherve/ONEDRIVE_UNINECHYN/OneDrive - unine.ch/SIMULATIONS/Lasset/results_stable/geographic/watershed_dem.tif')
wbt.raster_to_vector_points('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_data/_hydrography/_manage_osm/_osm_water_polygons_custom.tif',
                            'D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_data/_hydrography/_manage_osm/_osm_water_polygons_custom_topt.shp')

merge_path = 'D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_data/_hydrography/stream_perennial_wetlands_points.shp'+\
             ';'+\
             'D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_data/_hydrography/_manage_osm/_osm_water_lines_custom_topt.shp'+\
             ';'+\
             'D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_data/_hydrography/_manage_osm/_osm_water_polygons_custom_topt.shp'    
wbt.merge_vectors(merge_path,
                  'D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_data/_hydrography/stream_perennial_wetlands_osm_points.shp')

#%% CLIM

x = pd.read_csv('D:/Users/abherve/SIMULATIONS/LASSET/Lasset_decay/results_stable/climatic/_ALL_D.csv', sep=';',
                parse_dates=True, index_col=0)
fig, ax = plt.subplots(1,1, figsize=(6,3))
rec = x['REC_REA_historic']
rec = select_period(rec, 2019, 2021)
run = x['RUN_REA_historic']
run = select_period(run, 2019, 2021)
ax.plot(rec, c='navy', label='DRAIN ISBA SERVEUR FTP')
ax.plot(xv.englobe, c='darkviolet', zorder=5, label='DRAIN ISBA SERVEUR FTP')
ax.plot(run, c='dodgerblue', label='RUNOFF ISBA SERVEUR FTP')
s=sim2['DRAINC_Q']+sim2['RUNC_Q']
# plt.plot(s)
rec_s = sim2['DRAINC_Q']
run_s = sim2['RUNC_Q']
ax.plot(rec_s, c='red', label='DRAIN SIM2 METEO FRANCE')
ax.plot(run_s, c='darkorange', label='RUNOFF SIM2 METEO FRANCE')
ax.set_xlim(pd.to_datetime('2019-09'), pd.to_datetime('2021-09'))
years_maj = mdates.YearLocator()   # every year
months_maj = mdates.MonthLocator()  # every x month
ax.xaxis.set_major_locator(years_maj)
ax.xaxis.set_minor_locator(months_maj)
# ax.set_yscale('log')
ax.legend()
ax.set_ylabel('Value [mm/jour]')

op = pd.read_csv('D:/Users/abherve/SIMULATIONS/LASSET/Lasset_decay/results_stable/climatic/_ALL_D.csv', sep=';',
                 parse_dates=True, index_col=0)

fig, ax = plt.subplots(1,1, figsize=(6,3))
ax.plot(op['PPT_REA_historic'], c='blue', label='PPT ISBA SERVEUR FTP', lw=3)
ax.plot(sim2['PRELIQ_Q'], c='red', label='PPT ISBA SERVEUR FTP', lw=1)
ax.set_xlim(pd.to_datetime('2019-09'), pd.to_datetime('2021-09'))

#%% TEST

# def clip_netcdf(self, data_folder, path_qgis, shp_path, var):

p = 'D:/Users/abherve/DRIAS_EAU/Model_01/DRAINC_France_MPI-M-MPI-ESM-LR_CLMcom-CCLM4-8-17_METEO-FRANCE_ADAMONT-France_SAFRAN_MF-SIM2_Historique_day_19500801-20050731.nc'


with xr.open_dataset(p, decode_coords = 'all') as ds:
    ds.load()
# ds.sel(x = 76000, y = 2273000)
   
geodf = gpd.read_file(BV.geographic.watershed_shp)
geom = geodf.geometry.apply(mapping)
# try :
clipped_ds = ds.clip(geom, geodf.crs)
# except :
#     pass
# clipped_ds = ds.clip(geom, geodf.crs, all_touched = True, drop = True)
# ds.rio.write_crs("epsg:2154", inplace = True)

import geopandas
import rioxarray
from shapely.geometry import mapping

geodf = geopandas.read_file(BV.geographic.watershed_shp)
xds = rioxarray.open_rasterio(p)
clipped = xds.rio.clip(geodf.geometry.apply(mapping), geodf.crs)

#%% CONVERT NETCDF

import xarray as xr
xr.set_options(keep_attrs = True)
import rioxarray as riox
 
file_type = 'modflow'

_basename = 'D:/Users/abherve/DRIAS_EAU/Model_01/DRAINC_France_MPI-M-MPI-ESM-LR_CLMcom-CCLM4-8-17_METEO-FRANCE_ADAMONT-France_SAFRAN_MF-SIM2_Historique_day_19500801-20050731'
input_file = _basename + ''
output_file = _basename + '_QGIS.nc'
(folder_name, file_name) = os.path.split(output_file)

with xr.open_dataset(input_file, decode_coords = 'all') as _dataset:
    _dataset.load()
# Comme les latitudes sont fausses, il vaut mieux les supprimer :
_dataset = _dataset.drop('lon')
_dataset = _dataset.drop('lat')
# Créer les coordonnées 'x' et 'y' à partir de i et j
_dataset = _dataset.assign_coords(
    x = ('i', 52000 + _dataset.i.values*8000))
_dataset = _dataset.assign_coords(
    y = ('j', 1609000 + _dataset.j.values*8000))
# Remplacer i et j par x et y comme coordonnées
_dataset = _dataset.swap_dims(i = 'x', j = 'y')
# Ajouter les attributs standards
_dataset.x.attrs = {'standard_name': 'projection_x_coordinate',
                    'long_name': 'x coordinate of projection',
                    'units': 'Meter'}
_dataset.y.attrs = {'standard_name': 'projection_y_coordinate',
                    'long_name': 'y coordinate of projection',
                    'units': 'Meter'}
_dataset.rio.write_crs("epsg:27572", inplace = True)
_dataset.to_netcdf(output_file)  

#%% Q NETCDF

import xarray as xr
p='H:/SURFEX_CLIMATE_DATA/DRIAS_EAU/Model_01/Debits_France_MPI-M-MPI-ESM-LR_CLMcom-CCLM4-8-17_METEO-FRANCE_ADAMONT-France_SAFRAN_MF-SIM2_Historique_day_19500801-20050731.nc'
# p='H:/SURFEX_CLIMATE_DATA/DRIAS_EAU/Model_01/EVAPC_France_MPI-M-MPI-ESM-LR_CLMcom-CCLM4-8-17_METEO-FRANCE_ADAMONT-France_SAFRAN_MF-SIM2_Historique_day_19500801-20050731.nc'
# p='H:/SURFEX_CLIMATE_DATA/DRIAS_EAU/Model_01/RUNOFFC_France_MPI-M-MPI-ESM-LR_CLMcom-CCLM4-8-17_METEO-FRANCE_ADAMONT-France_SAFRAN_MF-SIM2_Historique_day_19500801-20050731.nc'
# p='H:/SURFEX_CLIMATE_DATA/DRIAS_EAU/Model_01/SWE_France_MPI-M-MPI-ESM-LR_CLMcom-CCLM4-8-17_METEO-FRANCE_ADAMONT-France_SAFRAN_MF-SIM2_Historique_day_19500801-20050731.nc'
# p='H:/SURFEX_CLIMATE_DATA/DRIAS_EAU/Model_01/SWI_France_MPI-M-MPI-ESM-LR_CLMcom-CCLM4-8-17_METEO-FRANCE_ADAMONT-France_SAFRAN_MF-SIM2_Historique_day_19500801-20050731.nc'
with xr.open_dataset(p, decode_coords = 'all') as ds:
    ds.load()
import geopandas
import rioxarray
from shapely.geometry import mapping

geodf = geopandas.read_file(BV.geographic.watershed_shp)
xds = rioxarray.open_rasterio(p)
ds.rio.write_crs("epsg:27572", inplace = True)
clipped = ds.rio.clip(geodf.geometry.apply(mapping), geodf.crs)

with xr.open_dataset('D:/Users/abherve/SIMULATIONS/PYRENEES/results_stable/driaseau/Model_01/DRAINC_France_MPI-M-MPI-ESM-LR_CLMcom-CCLM4-8-17_METEO-FRANCE_ADAMONT-France_SAFRAN_MF-SIM2_Historique_day_19500801-20050731.nc', decode_coords = 'all') as ds:
    ds.load()


