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
from src.watershed import climatic, geographic, geology, geometric, hydraulic, \
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
out_path = 'D:/Users/abherve/ONEDRIVE_UNINECHYN/OneDrive - unine.ch/SIMULATIONS/'

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

    try:
        visualization_watershed.watershed_local(dem_path, BV)
        visualization_watershed.watershed_dem(BV)
    except:
        pass

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

# SUBBASIN

BV.add_intermittency('None','None')
BV.add_subbasin(data_path+'_coordinates_additional/', sub_snap_dist=50)

#%% CLIMATE

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

#%% NORMALIZE

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
vers = 'v6'

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
        
        verti_cond = None # or [ [1e-5, [0, 20]],
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
        BV.hydraulic.update_cond_drain(cond_drain)
        BV.hydraulic.update_poro_decay(poro_decay)
        BV.settings.update_bc_sides(bc_left, bc_right)
        BV.add_oceanic(sea_level)
        BV.settings.update_input_particules(zone_partic=zone_partic)
        
        # Aquifer bottom
        list_bottom = [None, 0] # aquifer flat or not
        list_bottom.extend([0] * 10)

        # Decay of K
        # list_d_values = [0, 0]
        # list_d_values.extend(np.geomspace(10, 300, 10).round(0).astype(int))
        # print(list_d_values)
        list_d_values = [0, 0, 10, 15, 20, 25, 30, 45, 65, 100, 140, 200, 300]
        list_cond_decay = list(1/np.array(list_d_values))
        list_cond_decay[0] = 0
        list_cond_decay[1] = 0
                
        list_id_mod = [0,1,2,3,4,4.5,5,6,7,8,9,10,11]
       
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
            gap = 0.1
            
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
vers = 'v6'

BV = watershed_root.Watershed(watershed_name=watershed_name, dem_path=dem_path, out_path=out_path, load=True)
BV.calibration_folder = os.path.join(out_path, watershed_name, 'results_calibration')

dfs = pd.DataFrame()

raws_model = glob.glob(BV.calibration_folder+'/'+vers+'_'+'*.csv')
paths_model = sorted(raws_model,
                     key=lambda item: float(item.split('\\')[-1].split('_')[1].split('model')[-1]))

for path_model in paths_model:

    df = pd.read_csv(path_model, sep=';')
        
    dfs = pd.concat([dfs, df], ignore_index = True).drop_duplicates()

dfs['Doptim'] = (dfs['Obs'] + dfs['Sim'])/2
dfs['1/K_decay'] = 1/dfs['K_decay']
dfs['1/K_decay'][dfs['1/K_decay'] == np.inf] = 0

dfs.to_csv(BV.calibration_folder+'/'+'_models'+'_dichotomy_'+vers+'.csv', sep=';')

#%% DICHOTOMY - GRAPH

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

list_id_mod = [0,1,2,3,4,4.5,5,6,7,8,9,10,11]
dfz = pd.DataFrame()
for i in list_id_mod[:]:
    dft = dfp[dfp['id_mod']==i]
    # dfz = pd.concat([dfz, dft.iloc[-1:]])
    dfz = pd.concat([dfz, dft.iloc[(dft['Indicator']-1).abs().argsort()[:1]]])    
 
dfz.to_csv(BV.calibration_folder+'/'+'_models'+'_optimum_'+vers+'.csv', sep=';')
    
fig, ax = plt.subplots(1,1, figsize=(3.6,2.6))

# im = ax.scatter(df.k, (df.Dso+df.Dos)/2, c=df.cond_decay, s=100, cmap='jet')
ax.scatter(dfz[:1]['K']/24/3600, dfz[:1]['Doptim'], c=dfz[:0]['1/K_decay'], s=100, 
            marker='s', lw=2,
            cmap=mpl.colors.ListedColormap('k'),
            # label=dfz['1/K_decay'].values[0]
            )

ax.scatter(dfz[1:2]['K']/24/3600, dfz[1:2]['Doptim'],
            c=dfz[1:2]['1/K_decay'],
            s=100, 
             marker='o', lw=2,
             cmap=mpl.colors.ListedColormap('gray'),
            # label='0'
            )
im = ax.scatter(dfz[2:]['K']/24/3600, dfz[2:]['Doptim'], c=dfz[2:]['1/K_decay'], s=100, 
                cmap='jet',
                norm=mpl.colors.LogNorm(vmin=10, vmax=300),
                lw=2,
                # label=df['1/cond_decay'] 
                )
# ax.legend()
ax.set_xscale('log')
# ax.set_yscale('log')
ax.set_xlabel('K [m/s]')
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
cb.set_ticks([10, 15, 20, 25, 30, 45, 65, 100, 140, 205, 300])
cb.set_ticklabels([10, 15, 20, 25, 30, 45, 65, 100, 140, 205, 300], fontsize=8)
cb.ax.tick_params(direction='in', length=2, width=1, colors='k',
                  grid_color='k', grid_alpha=0.5)
cb.minorticks_off()
# cb.clim()
cb.ax.set_ylabel('1/α [m]', rotation=270, labelpad=25)

# ax.set_yscale('log')

#%% DICHOTOMY - MAPS

dfp = dfs.copy()
dfp['1/K_decay'] = 1/dfp['K_decay']
dfp['1/K_decay'][dfp['1/K_decay'] == np.inf] = 0
dfp['Doptim'] = (dfp['Obs'] + dfp['Sim'])/2
list_id_mod = [0,1,2,3,4,4.5,5,6,7,8,9,10,11]

shp_bv = gpd.read_file(BV.geographic.watershed_shp)
# if vers == 'v3':
#     shp_hydro = gpd.read_file(stable_folder+'hydrography/'+'stream_perennial_wetlands_points.shp')
# if vers == 'v4':
#     shp_hydro = gpd.read_file(stable_folder+'hydrography/'+'stream_perennial_wetlands_osm_points.shp')
if vers == 'v6':
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

#%% ---- EXPLORATION

# 12 models
# 10 porosity per model : 0.1, 0.5, 1, 2, 4, 7, 10, 15, 20, 30

#%% PREPROCESSING

iD_explo = 'e1'

box = True # or False
sink_fill = False # or True
sim_state = 'transient' # 'steady' or 'transient'
plot_cross = True
nlay = 25
lay_decay = 1.25 # 1 for no decay
verti_cond = None # or [ [1e-5, [0, 20]],
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
BV.hydraulic.update_cond_drain(cond_drain)
BV.settings.update_bc_sides(bc_left, bc_right)
BV.add_oceanic(sea_level)
BV.settings.update_input_particules(zone_partic=zone_partic)
BV.settings.update_simulation_state(sim_state)

thick = 30 # if bottom is None, aquifer thickness
BV.hydraulic.update_thick(thick) # 30 / intervient pas si bottom != None

recharge = (sim2['DRAINC_Q'] * norm_factor) / 1000 # mm/d to m/d
recharge_w_res = recharge.resample('W', label='right').mean()
recharge_w_off = recharge.resample('W', label='right', closed='left', loffset=pd.DateOffset(days=3)).mean() # loffset='2T'
recharge_w_int = recharge.interpolate()[::7]
recharge_w_sli = recharge.groupby(np.arange(len(recharge))//7).mean()
recharge_w_sli.index = recharge_w_off.iloc[:-1].index
recharge_w_sli = recharge_w_sli.iloc[:-1]

runoff = (sim2['RUNC_Q'] * norm_factor) / 1000 # mm/d to m/d
runoff_w_res = runoff.resample('W', label='right').mean()
runoff_w_off = runoff.resample('W', label='right', closed='left', loffset=pd.DateOffset(days=3)).mean() # loffset='2T'
runoff_w_int = runoff.interpolate()[::7]
runoff_w_sli = runoff.groupby(np.arange(len(runoff))//7).mean()
runoff_w_sli.index = runoff_w_off.iloc[:-1].index
runoff_w_sli = runoff_w_sli.iloc[:-1]

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
list_d_values = [0, 0, 10, 15, 20, 25, 30, 45, 65, 100, 140, 200, 300]
list_cond_decay = list(1/np.array(list_d_values))
list_cond_decay[0] = 0
list_cond_decay[1] = 0

# Models
list_id_mod = [0,1,2,3,4,4.5,5,6,7,8,9,10,11]

vers = 'v6'
df_optim = pd.read_csv(BV.calibration_folder+'/'+'_models'+'_optimum_'+vers+'.csv', sep=';')

# For transient
list_cond_decay = list_cond_decay
list_bottom = list_bottom
list_koptim = df_optim['K']
list_porosity = np.array([0.1,0.5,1,2,4,8,15,30])/100
list_kroptim = df_optim['KR']

#%% PRO PREPROCESSING

run_model = True
# run_model = False

# for cond_decay_val, bottom_val, koptim_val, id_mod_val in zip(list_cond_decay[-1:], list_bottom[-1:], list_koptim[-1:], list_id_mod[-1:]):
for cond_decay_val, bottom_val, koptim_val, id_mod_val, kroptim_val in zip(list_cond_decay[4:5],
                                                                           list_bottom[4:5],
                                                                           list_koptim[4:5],
                                                                           list_id_mod[4:5],
                                                                           list_kroptim[4:5]):
    
    # print(kroptim_val)
    # koptim_from_kr = kroptim_val * (BV.climatic.recharge.mean())
    # print(koptim_from_kr, koptim_val)
    
    BV.hydraulic.update_cond_decay(cond_decay_val) # 0
    BV.hydraulic.update_bottom(bottom_val) # None
    BV.hydraulic.update_hyd_cond(koptim_val)
    # BV.hydraulic.update_hyd_cond(koptim_from_kr)
    BV.hydraulic.update_poro_decay(cond_decay_val/2)
    
    dictio = {}
    
    list_model_name = []
    list_model_success = []
    list_model_modflow = []
        
    # for ip, poro_val in enumerate(list_porosity[-1:]):
    for ip, poro_val in enumerate(list_porosity[:]):
        
        BV.hydraulic.update_porosity(poro_val)

        if id_mod_val <=1 :
            str_cond_decay = cond_decay_val
            str_poro_decay = cond_decay_val/2
        else:
            str_cond_decay = 1/cond_decay_val
            str_poro_decay = 1/(cond_decay_val/2)
        if bottom_val==None:
            str_bottom = thick
        else:
            str_bottom = bottom_val
        model_name = iD_explo+'_'+str('model')+str(id_mod_val)+'_'+\
                     str(round(str_cond_decay,4))+'-'+str(round(str_bottom,4))+'-'+str("{:.2e}".format(koptim_val/24/3600))+'_'+\
                     str(ip)+'_'+\
                     str(round(str_poro_decay,4))+'-'+str(round(poro_val*100,2))
        
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
    
#%% RELOAD POSTPROCESS

for id_mod_val in list_id_mod[:]:

    h5file = BV.calibration_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)
    d = dd.io.load(h5file)
    list_model_name = d['list_model_name'][:]
    list_model_success = d['list_model_success'][:]
    list_model_modflow = d['list_model_modflow'][:]
    
    for model_name, model_success, model_modflow in zip(list_model_name, list_model_success, list_model_modflow):
    
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
                                  intermittency_daily = True,
                                  export_all_tif = False)

        timeseries_results = BV.postprocessing_timeseries(model_modflow=model_modflow,
                                                          model_modpath=False,
                                                          actual_date=True, 
                                                          subbasin_results=True,
                                                          freq_time='W')

#%% DELETE MODFLOW FILES
"""
for watershed_name in watershed_names[:]:

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
    if os.path.exists(dir_rasters+ '/' +'intermittency_daily_t(0).tif'):
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


    h5files = glob.glob(BV.calibration_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)+'*')
    
    for h5 in h5files[:]:
    
        d = dd.io.load(h5file)
        list_model_name = d['list_model_name'][:]
        list_model_success = d['list_model_success'][:]
        list_model_modflow = d['list_model_modflow'][:]
        
        for model_name, modflow_success, model_modflow in zip(list_model_name[:],
                                                              list_model_success[:],
                                                              list_model_modflow[:]):

            dir_modflow = BV.calibration_folder + '/' + model_name
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
"""
#%% STREAMFLOW PLOT

CRIT = 'RMSE'

init_path = data_path + '_Q/'

Qobs_list =[
             'lasset_Q_Day.Cmd.txt',
             # 'truites_Q_Day.Cmd.txt'
            ]

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

    i = 0

    for id_mod_val in list_id_mod[4:5]:
    
        h5file = BV.calibration_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)
        d = dd.io.load(h5file)
        list_model_name = d['list_model_name'][:]
        list_model_success = d['list_model_success'][:]
        list_model_modflow = d['list_model_modflow'][:]
        
        for model_name, model_success, model_modflow in zip(list_model_name, list_model_success, list_model_modflow):
            
            Smod = pd.read_csv(BV.calibration_folder+'/'+model_name+'/_postprocess/_timeseries/_simulated_timeseries.csv', sep=';',
                               index_col='date', parse_dates=True)
            
            r = runoff_w_sli.copy()
            Qmod = Smod['outflow_drain'] + r # m/day
            
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
            df.loc[i,'K'] = float(['-'.join(model_name.split('_')[2].split('-')[-2:])][0])
            
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
            
plt.scatter(df['O'], df['NSElog'], c=df['aK'])

#%% SATURATION PLOT

types_obs = ['perennial_natural_streams',
             # 'fully_natural_streams',
             # 'fully_natural_streams_springs',
              'fully_natural_streams_springs_wetlands'
             ]

sat_typ = 'total_areas'

init_path = 'xxx'

areas = [
          9.4,
          13.7,
          14.1
         ]

df = pd.DataFrame()

dict_S_wname = {}

for w, w_name in enumerate(['S1','Nant_EUDTM30m','Vare_EUDTM30m'][:]):
    
    if w_name == 'S1':
        watershed_name = 'Nant_EUDTM30m'
    else:
        watershed_name = w_name        
    
    BV = watershed_root.Watershed(watershed_name=watershed_name, dem_path=dem_path, out_path=out_path, load=True)

    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' # necessary for plots
    calibration_folder = out_path+'/'+watershed_name+'/'+'results_calibration/'
    
    if w_name == 'S1':
        dem_data = imageio.imread(stable_folder + 'subbasin/subbasin_S1/' + 'watershed_dem.tif')
    else:
        dem_data = imageio.imread(stable_folder + 'geographic/' + 'watershed_dem.tif')
    
    list_sat_obs = []
    for type_obs in types_obs:
        path_hydro = stable_folder + 'hydrography/' + type_obs + '.tif'
        obs_hydro = imageio.imread(path_hydro)
        obs_hydro = np.ma.masked_where(dem_data==-99999, obs_hydro)
        obs_hydro_masked = np.ma.masked_where(obs_hydro<0, obs_hydro)
        dd_hydro = round(obs_hydro_masked.count() / obs_hydro.count() * 100, 2)
        # plt.imshow(obs_hydro_masked)
        print(dd_hydro)
        list_sat_obs.append(dd_hydro)

    paths = glob.glob(calibration_folder+'/'+iD_set_simulations+'*')
    h5files = sorted(paths,
                     key=lambda item: float((item.split('\\')[-1].split('_')[1])), reverse=False)
        
    for i, h5file in enumerate(h5files):
        model_name = h5file.split('\\')[-1]
        # print(model_name)
        
        if w_name == 'S1':
            Smod = pd.read_csv(h5file+'/_subbasins/subbasin_S1/_simulated_timeseries.csv', sep=';',
                               index_col='date', parse_dates=True)
        else:
            Smod = pd.read_csv(h5file+'/_postprocess/_timeseries/_simulated_timeseries.csv', sep=';',
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
        
        df.loc[i,'K'] = float(model_name.split('_')[3].split('-')[0])
        df.loc[i,'Sy'] = float(model_name.split('_')[3].split('-')[1])
        df.loc[i,'p1-p2'] = model_name.split('_')[3].split('-')[0]+'-'+model_name.split('_')[3].split('-')[1]
        
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
    
    fig, axs = plt.subplots(1,3, figsize=(3.8*3,3.5))
    axs = axs.ravel()
    
    dict_Zs = {}
    
    for ci, choice in enumerate(['S10','S50','S90']):
        
        p1 = df.K.unique()
        p2 = df.Sy.unique()
        ded = np.zeros((len(p1),len(p2)))
        for i, iv in enumerate(p1):
            for j, jv in enumerate(p2):
                string = str(iv)+'-'+str(jv)
                # print(string)
                ded[j][i] = df[df['p1-p2']==string][choice]
            
        X,Y = np.meshgrid(df.K.unique(), df.Sy.unique())
        Z = ded.copy()
        
        ax = axs[ci]
        ax.set_title(w_name.split('_')[0]+' - '+choice, pad=10)

        ax.set_aspect('auto')
        ax.axes.tick_params(which='both', direction='out', zorder=10)
        
        if choice == 'S10':
            Z = ((Z - list_sat_obs[0])**2) / (list_sat_obs[0]**2)
        if choice == 'S50':
            Z = ((Z - ((list_sat_obs[0]+list_sat_obs[-1])/2))**2) / (((list_sat_obs[0]+list_sat_obs[-1])/2)**2)
        if choice == 'S90':
            Z = ((Z - list_sat_obs[-1])**2) / (list_sat_obs[-1]**2)
        # Z=abs(Z)
                
        print(np.nanmin(Z), np.nanmax(Z))
    
        cmap = "RdYlGn_r"
            
        pc = ax.contourf(X/24/3600,Y*100, Z, cmap=cmap, alpha=0.5,
                            # norm=mpl.colors.CenteredNorm(),
                            # norm=mpl.colors.LogNorm(),
                            # norm = divnorm,
                            # vmin=0, vmax=1.0,
                        levels=np.arange(0, 1.05, 0.1),
                        linewidths=0, ec='none', ls=None,
                        extend='max')
         
        ax.set_xscale('log')
        ax.set_yscale('log')
        ax.set_ylabel('θ [%]')
        ax.set_xlabel('K [m/s]')
    
        position=fig.add_axes([1.05,0.33,0.03,0.5])  ##
        cb = fig.colorbar(pc, cax=position, orientation='vertical')
        
        # cb.set_ticklabels(np.round(np.arange(0,11,1),1)) 
        cb.set_ticks(np.arange(0, 1.1, 0.25))
        cb.set_label('$A_{diff}$ [-]', rotation=270, labelpad=40)
        cb.ax.tick_params(top=True,
                    bottom=True,
                    left=False,
                    right=False,
                    labelleft=False,
                    labelbottom=True)
    
        ax.tick_params(top=True,
                   bottom=True,
                   left=True,
                   right=False,
                   labelleft=True,
                   labelbottom=True)
        
        ax.set_xlim(1e-7, 1e-4)
        ax.set_ylim(0.1,10)

        plt.tight_layout()    
    
        fig.savefig(fig_path+'SAT_'+w_name+'_per-med-ful'+'_'+sat_typ+'.png', dpi=300, bbox_inches='tight')

# SUM RATIOS

        dict_Zs[ci] = Z
      
    fig, ax = plt.subplots(1,1, figsize=(3.8,3.5))
    ax.set_aspect('auto')
    ax.axes.tick_params(which='both', direction='out', zorder=10)
    
    X,Y = np.meshgrid(df.K.unique(), df.Sy.unique())
    Z = (dict_Zs[0] + dict_Zs[1] + dict_Zs[2]) / 3
    
    dict_S_wname[w] = Z
    
    ax.set_title(w_name.split('_')[0], pad=10)

    ax.set_aspect('auto')
    ax.axes.tick_params(which='both', direction='out', zorder=10)
            
    cmap = "RdYlGn_r"
        
    pc = ax.contourf(X/24/3600,Y*100, Z, cmap=cmap, alpha=0.5,
                        # norm=mpl.colors.CenteredNorm(),
                        # norm=mpl.colors.LogNorm(),
                        # norm = divnorm,
                        # vmin=0, vmax=1.0,
                    levels=np.arange(0, 1.05, 0.1),
                    linewidths=0, ec='none', ls=None,
                    extend='max')
     
    ax.set_xscale('log')
    ax.set_yscale('log')
    ax.set_ylabel('θ [%]')
    ax.set_xlabel('K [m/s]')

    position=fig.add_axes([1.05,0.33,0.03,0.5])  ##
    cb = fig.colorbar(pc, cax=position, orientation='vertical')
    
    # cb.set_ticklabels(np.round(np.arange(0,11,1),1)) 
    cb.set_ticks(np.arange(0, 1.1, 0.25))
    cb.set_label('$A_{diff}$ [-]', rotation=270, labelpad=40)
    cb.ax.tick_params(top=True,
                bottom=True,
                left=False,
                right=False,
                labelleft=False,
                labelbottom=True)

    ax.tick_params(top=True,
               bottom=True,
               left=True,
               right=False,
               labelleft=True,
               labelbottom=True)
    
    ax.set_xlim(1e-7, 1e-4)
    ax.set_ylim(0.1,10)

    plt.tight_layout()  
    
    fig.savefig(fig_path+'SAT_'+w_name+'_mix_per-med-ful'+'_'+sat_typ+'.png', dpi=300, bbox_inches='tight')

# BEST MODELS
    
    df['OWN_PER'] = ((df['S10'] - df['Obs_per'])**2)/(df['Obs_per']**2)
    df['OWN_MED'] = ((df['S50'] - df['Obs_med'])**2)/(df['Obs_med']**2)
    df['OWN_FUL'] = ((df['S90'] - df['Obs_ful'])**2)/(df['Obs_ful']**2)
    df['OWN_SAT'] = (df['OWN_PER'] + df['OWN_MED'] +df['OWN_FUL']) / 3

    dfP = df[df['OWN_SAT']==df['OWN_SAT'].min()]
    model_nameP = dfP.model_name.values[0]

    if w_name == 'S1':
        SmodP = pd.read_csv(calibration_folder+model_nameP+'/_subbasins/subbasin_S1/_simulated_timeseries.csv', sep=';',
                           index_col='date', parse_dates=True)
    else:
        SmodP = pd.read_csv(calibration_folder+model_nameP+'/_postprocess/_timeseries/_simulated_timeseries.csv', sep=';',
                           index_col='date', parse_dates=True)
    
    Smod = SmodP.copy()
    
    fig, ax = plt.subplots(1, 1, figsize=(6,3))
    
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
    ax.step(Smod.index, Smod['seepage_areas'], color='grey',
            marker=None, markeredgecolor='none',
            markersize=5, lw=1, label='upstream',
            where='pre')
    
    # if watershed_name == 'Nant_EUDTM30m':
    #     ax.set_ylim(0,50)
    # if watershed_name == 'Vare_EUDTM30m':
    #     ax.set_ylim(0,6)
    # ax.set_yticks(np.arange(0,15.05,2.5))
    ax.set_ylim(0,20)
    ax.set_ylabel('$A_{sat}$ [%]')
    ax.set_xlim(pd.to_datetime('2016'), pd.to_datetime('2019'))
    plt.xticks(rotation=0, ha="right")

    years_maj = mdates.YearLocator()   # every year
    months_maj = mdates.MonthLocator()  # every x month
    ax.xaxis.set_major_locator(years_maj)
    ax.xaxis.set_minor_locator(months_maj)
    
    mP = '{:.2e}'.format(float(model_nameP.split('_')[-1].split('-')[0])/3600/24) + ' ; ' + str(round((float(model_nameP.split('_')[-1].split('-')[1])*100),2))
    ax.set_title(w_name + '  -  ' + model_nameP.upper() + '  -  ' + mP, fontsize=6)

    
    for j, hline in enumerate(list_sat_obs[:2]):
        if j == 0:
            cl = 'navy'
        if j == 1:
            cl = 'dodgerblue'
        ax.axhline(hline, c=cl, ls='--')
        
    fig.tight_layout()
                
    fig.savefig(fig_path+'OBSsat'+'_'+w_name+'_'+'BEST MODELS'+'.png', dpi=300, bbox_inches='tight')

#%% CONVOLUTION PLOT

for w, w_name in enumerate(['S1','Nant_EUDTM30m','Vare_EUDTM30m'][:]):
    
    if w_name == 'S1':
        watershed_name = 'Nant_EUDTM30m'
    else:
        watershed_name = w_name        
    
    BV = watershed_root.Watershed(watershed_name=watershed_name, dem_path=dem_path, out_path=out_path, load=True)

    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' # necessary for plots
    calibration_folder = out_path+'/'+watershed_name+'/'+'results_calibration/'
    
    Z_convol = dict_Q_wname[w] + dict_S_wname[w]

    fig, ax = plt.subplots(1,1, figsize=(3.8,3.5))
    ax.set_aspect('auto')
    ax.axes.tick_params(which='both', direction='out', zorder=10)
    
    X,Y = np.meshgrid(df.K.unique(), df.Sy.unique())
        
    ax.set_title(w_name.split('_')[0], pad=10)

    ax.set_aspect('auto')
    ax.axes.tick_params(which='both', direction='out', zorder=10)
            
    cmap = "RdYlGn_r"
    
    if w_name == 'Vare_EUDTM30m':
        pc = ax.contourf(X/24/3600,Y*100, Z_convol, cmap=cmap, alpha=0.5,
                            # norm=mpl.colors.CenteredNorm(),
                            # norm=mpl.colors.LogNorm(),
                            # norm = divnorm,
                            # vmin=0, vmax=1.0,
                        # levels=np.arange(2, 3.05, 0.05),
                        levels=np.arange(0, 1.05, 0.05),
                        linewidths=0, ec='none', ls=None,
                        extend='max')
    else:
        pc = ax.contourf(X/24/3600,Y*100, Z_convol, cmap=cmap, alpha=0.5,
                            # norm=mpl.colors.CenteredNorm(),
                            # norm=mpl.colors.LogNorm(),
                            # norm = divnorm,
                            # vmin=0, vmax=1.0,
                        levels=np.arange(0, 1.05, 0.05),
                        linewidths=0, ec='none', ls=None,
                        extend='max')
     
    ax.set_xscale('log')
    ax.set_yscale('log')
    ax.set_ylabel('θ [%]')
    ax.set_xlabel('K [m/s]')

    position=fig.add_axes([1.05,0.33,0.03,0.5])  ##
    cb = fig.colorbar(pc, cax=position, orientation='vertical')
    
    # cb.set_ticklabels(np.round(np.arange(0,11,1),1))
    if w_name == 'Vare_EUDTM30m':
        # cb.set_ticks(np.arange(2, 3.1, 0.25))
        cb.set_ticks(np.arange(0, 1.1, 0.25))
        # cb.set_ticklabels(np.arange(0, 1.1, 0.25))
    else:
        cb.set_ticks(np.arange(0, 1.1, 0.25))
        # cb.set_ticklabels(np.arange(1, 2.1, 0.25))
    cb.set_label('$A_{diff}$ [-]', rotation=270, labelpad=40)
    cb.ax.tick_params(top=True,
                bottom=True,
                left=False,
                right=False,
                labelleft=False,
                labelbottom=True)

    ax.tick_params(top=True,
               bottom=True,
               left=True,
               right=False,
               labelleft=True,
               labelbottom=True)
    
    ax.set_xlim(1e-7, 1e-4)
    ax.set_ylim(0.1,10)

    plt.tight_layout()  
    
    fig.savefig(fig_path+'CONVOL_'+w_name+'_mix_per-med-ful'+'_'+sat_typ+'.png', dpi=300, bbox_inches='tight')

#%% ---- METHODOLOGY

#%% CROSS SECTIONS PLOT

# model_name = 'egu1_1_10.0-0.0-0.0857-26.68'
# model_name = 'egu1_0_500.0-0-0.0058-30.0'

# list_selects = ['egu1_4_20.0-0.0-0.1359-10.8', 'egu1_8_100.0-0.0-0.0211-3.9']
list_selects = list_model_name[16::17]
list_flowmodel = list_flow_model[16::17]

fig_cross = True

# figt, axt = plt.subplots(1, 2, figsize=(3, 3))

for model_name, flow_model in zip(list_selects[:], list_flowmodel[:]):
    print(model_name)
    # if model_name == 'egu1_0_500.0-0-0.0058-30.0':
    # try:
        
    id_model = int(model_name.split('_')[1])
            
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
    
    if fig_cross == True:
        
        """
        fig, axs = plt.subplots(1, 2, figsize=(12, 3))
        # ax = fig.add_subplot(1, 1, 1)
        axs = axs.ravel()
        modelxsect = flopy.plot.PlotCrossSection(model=mf, line={'Row': int((grid_model.shape[1])/2)})
        linecollection = modelxsect.plot_grid()
        # hdobj = flopy.utils.HeadFile(fname)
        # head_data = hdobj.get_data()
        modelxsect.plot_array(hk_grid.array, ax=axs[0], cmap='viridis', lw=0.1)
        # pc = modelxsect.plot_array(head_data, masked_values=[-9999], head=head_data,
        #                             cmap='Blues', alpha=0.5, ax=axs[1])
        axs[1].set_title('Meshgrid Weat to East')
        axs[0].set_title('Hydraulic conductivity')
        fig.suptitle(model_name.upper(), y=1.05, fontsize=8)
        
        bv_box = gpd.read_file(stable_folder+'geographic/'+'box_buff.shp')
        ext_mod = bv_box.geometry.total_bounds
        
        # axs[0].set_ylim(150, 350)
        # axs[1].set_ylim(150, 350)
        
        # fig.savefig(fig_path+'cross_section_h_'+model_name+'.png', dpi=300, bbox_inches='tight')

        fig, axs = plt.subplots(1, 2, figsize=(12, 3))
        # ax = fig.add_subplot(1, 1, 1)
        axs = axs.ravel()
        modelxsect = flopy.plot.PlotCrossSection(model=mf, line={'Column': int((grid_model.shape[2])/2)})
        linecollection = modelxsect.plot_grid()
        # hdobj = flopy.utils.HeadFile(fname)
        # head_data = hdobj.get_data()
        cb = modelxsect.plot_array(sy_grid, ax=axs[0], cmap='plasma', lw=0.1)
        # pc = modelxsect.plot_array(head_data, masked_values=[-9999], head=head_data,
        #                             cmap='Blues', alpha=0.5, ax=axs[1])
        axs[1].set_title('Meshgrid North to South')
        axs[0].set_title('Specific yield')
        fig.suptitle(model_name.upper(), y=1.05, fontsize=8)
        
        bv_box = gpd.read_file(stable_folder+'geographic/'+'box_buff.shp')
        ext_mod = bv_box.geometry.total_bounds
        """
        
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
        for i in range(val.shape[0]):
            # mask = val[i] == 0
            # val[i][mask] = 1e-100
            val[i][val[i] <= np.nanmin(val[i])] = np.nanmin(val[i][np.nonzero(val[i])])
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
        cb = modelxsect.plot_array(sy_grid*100, ax=ax, cmap='plasma', lw=0.1, vmin=0, vmax=50)
        # pc = modelxsect.plot_array(head_data, masked_values=[-9999], head=head_data,
        #                             cmap='Blues', alpha=0.5, ax=axs[1])
        ax.set_title('Meshgrid North to South')
        ax.set_title('Specific yield')
        ax.set_xticks([0,1000,2000,3000,4000])
        fig.suptitle(model_name.upper(), x=0.5, y=1.0, fontsize=8)
        fig.colorbar(cb)
        plt.tight_layout()
        # fig.set_size_inches(6, 3, forward=True)
        
        fig.savefig(fig_path+'cross_section_'+model_name+'.png', dpi=300, bbox_inches='tight')
        
#%% GRAPH DECAY COND

start = 0
stop = -1 
step = 17
list_k_selects = list_model_name[start:stop:step]
list_k_flowmodel = list_flow_model[start:stop:step]
figk, axk = plt.subplots(1, 1, figsize=(3, 4))

n = 12
colors = pl.cm.jet(np.linspace(0,1,n))

cp = 0
for model_name, flow_model in zip(list_k_selects[:], list_k_flowmodel[:]):
    print(model_name)
    # if model_name == 'egu1_0_500.0-0-0.0058-30.0':
    # try:
        
    id_model = int(model_name.split('_')[1])
    
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
    if cp == 0:
        c = 'k'
    if cp == 1 :
        c = 'grey'
    if cp > 1:
        c = colors[cp]
    axk.plot(list_k, list_z, color=c, lw=2, label=str(decay_k))
    
    cp += 1

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
axk.legend(loc='lower right', frameon=False)

figk.savefig(fig_path+'decay_k.png', dpi=300, bbox_inches='tight')

#%% GRAPH DECAY PORO

for i in range(17):
# for i in []:
    print(i)
    
    start = i
    # stop = -1 
    step = 17
    list_p_selects = list_model_name[start::step]
    list_p_flowmodel = list_flow_model[start::step]
    
    figp, axp = plt.subplots(1, 1, figsize=(3, 4))
    
    n = 12
    colors = pl.cm.jet(np.linspace(0,1,n))
    
    cp = 0
    for model_name, flow_model in zip(list_p_selects[:], list_p_flowmodel[:]):
        
        
        print(model_name)
        # if model_name == 'egu1_0_500.0-0-0.0058-30.0':
        # try:
            
        id_model = int(model_name.split('_')[1])
        
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
        if cp == 0:
            c = 'k'
            zo = 10
        else:
            zo=0
        if cp == 1 :
            c = 'grey'
        if cp > 1:
            c = colors[cp]
        axp.plot(list_p, list_z, color=c, label=str(decay_k), zorder=zo)
        print(np.array(list_p).mean())
        
        cp += 1
    
    # axp.set_xscale('log')
    axp.invert_yaxis()
    axp.set_xlim(0, 50)
    axp.set_ylim(1000, 0)
    
    axp.xaxis.tick_top()
    axp.set_xlabel('θ [%]')
    axp.xaxis.set_label_position('top') 
    axp.set_ylabel('Depth [m]')
    # axp.set_xscale('log')
    axp.spines[['right', 'bottom']].set_visible(False)
    axp.tick_params(right=False)
    axp.legend(loc='lower right', frameon=False)
    
    figp.savefig(fig_path+'decay_p_'+str(i)+'.png', dpi=300, bbox_inches='tight')

begin_by = fig_path+'decay_p_'
filenames = sorted(glob.glob(begin_by+'*.png'), key=os.path.getmtime)
images = []
for filename in filenames:
    images.append(imageio.imread(filename))
gif_name = 'decay_p'
imageio.mimsave(fig_path+gif_name+'.gif', images,
                duration=10, loop=0)

#%% DATAFRAME COND PORO

dk_max = pd.DataFrame()
dk_mean = pd.DataFrame()
dkw_mean = pd.DataFrame()

dp_max = pd.DataFrame()
dp_mean = pd.DataFrame()
dpw_mean = pd.DataFrame()
dpw2_mean = pd.DataFrame()
dpw3_mean = pd.DataFrame()

df_recap = pd.DataFrame()

u = 0

step = 20
    
for i in range(step):
# for i in [16]:
# for i in range(1):
    print(i)
    
    start = i
    # stop = -1 

    list_p_selects = list_model_name[start::step]
    list_p_flowmodel = list_flow_model[start::step]
    figp, axp = plt.subplots(1, 1, figsize=(3, 4))
    
    n = len(list_p_flowmodel)
    colors = pl.cm.jet(np.linspace(0,1,n))
    
    cp = 0
    for model_name, flow_model in zip(list_p_selects[:], list_p_flowmodel[:]):
        
        
        print(model_name)
        # if model_name == 'egu1_0_500.0-0-0.0058-30.0':
        # try:
            
        id_model = int(model_name.split('_')[1])
                
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
        
        zall = flow_model.dem - flow_model.zbot
        
        list_z = []
        list_k = []
        list_p = []
        for j in range(len(zall)):
            list_z.append(zall[j].mean())
            list_k.append((hk_grid.array/24/3600)[j].mean())
            list_p.append((sy_grid*100)[j].mean())
        if cp == 0:
            c = 'k'
        if cp == 1 :
            c = 'grey'
        if cp > 1:
            c = colors[cp]
        axp.plot(list_p, list_z, color=c)
        print(np.array(list_p).mean())
        
        ### WEIGHTED
        # zpond = zall * np.nan
        zthick = zall * np.nan
        for l in range(zall.shape[0]):
            if l == 0:
                # zpond[l] = zall[l] * sy_grid[l]
                zthick[l] = zall[l]
            if (l > 0) & (l < (zall.shape[0]-1)):
                # zpond[l] = (zall[l+1] - zall[l]) * sy_grid[l]
                zthick[l] = (zall[l+1] - zall[l])
            if l == zall.shape[0]-1:
                # zpond[l] = zall[l] * sy_grid[l]
                zthick[l] = zall[l]
        
        k_pond = zall * np.nan
        p_pond = zall * np.nan
        list_kw = []
        list_pw = []
        for m in range(zall.shape[0]):
            k_pond[m] = (hk_grid.array/24/3600)[m] * zthick[m]
            p_pond[m] = (sy_grid*100)[m] * zthick[m]
            list_kw.append(np.nansum(k_pond[m]) / np.nansum(zthick[m]))
            list_pw.append(np.nansum(p_pond[m]) / np.nansum(zthick[m]))
            # list_kw.append(np.nansum(k_pond[m]) / flow_model.dem)
            # list_pw.append(np.nansum(p_pond[m]) / flow_model.dem)
        print(np.array(list_pw).mean())
        
        if cp == 0 :
            list_pw2 = np.nansum(p_pond) / np.nansum(zthick)
            list_pw3 = np.nansum(p_pond) / np.nansum(zthick)
        if cp > 0 :
            list_pw2 = np.nansum(p_pond) / np.nansum(flow_model.dem)
            list_pw3 = np.nansum(p_pond) / np.nansum(zthick)
        print(list_pw2)
        print(list_pw3)
        
        dk_max.loc[i,cp] = np.array(list_k).max()
        dk_mean.loc[i,cp] = np.array(list_k).mean()
        dkw_mean.loc[i,cp] = np.array(list_kw).mean()
        
        dp_max.loc[i,cp] = np.array(list_p).max()
        dp_mean.loc[i,cp] = np.array(list_p).mean()
        dpw_mean.loc[i,cp] = np.array(list_pw).mean()
        dpw2_mean.loc[i,cp] = list_pw2
        dpw3_mean.loc[i,cp] = list_pw3
        
        cp += 1
    
        df_recap.loc[u, 'model_name'] = model_name
        
        df_recap.loc[u, 'dk_max'] = np.array(list_k).max()
        df_recap.loc[u, 'dk_mean'] = np.array(list_k).mean()
        df_recap.loc[u, 'dkw_mean'] = np.array(list_kw).mean()
        
        df_recap.loc[u, 'dp_max'] = np.array(list_p).max()
        df_recap.loc[u, 'dp_mean'] = np.array(list_p).mean()
        df_recap.loc[u, 'dpw_mean'] = np.array(list_pw).mean()
        df_recap.loc[u, 'dpw2_mean'] = list_pw2
        df_recap.loc[u, 'dpw3_mean'] = list_pw3

        u+=1
    
    # axp.set_xscale('log')
    axp.invert_yaxis()
    axp.set_xlim(0, 50)
    # axp.set_ylim(1000, 0)

df_recap.to_csv(simulations_folder+'dfrecap_cond_poro_'+typ+'.csv', sep=';')    

#%% PLOT COND PORO

dkmax = dk_max.T
dkmean = dk_mean.T
dpmax = dp_max.T
dpmean = dp_mean.T

# dkmax = dk_max
# dkmean = dk_mean
# dpmax = dp_max
# dpmean = dp_mean

fig, ax = plt.subplots(1, 1, figsize=(5, 3))
n = 17
colors = pl.cm.plasma(np.linspace(0,1,n))
for i in range(17):
    ax.plot(dkmean.index, dkmean[i], marker='_', mew=2,
            ms=10, lw=0, c='dodgerblue', label=int(round(dkmax[i][0],2)))
    ax.plot(dkmax.index, dkmax[i], marker='o',
            ms=5, lw=0, c='k', label=int(round(dkmax[i][0],2)))
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
ax.text(0.5,0.3, 'Mean', transform=ax.transAxes, c='dodgerblue')
ax.text(0.6,0.7, 'Max', transform=ax.transAxes, c='k')
# fig.savefig(fig_path+'resume_kmeanmax_cases.png', dpi=300, bbox_inches='tight')

fig, ax = plt.subplots(1, 1, figsize=(5, 3))
n = 17
colors = pl.cm.plasma(np.linspace(0,1,n))
for i in range(17):
    ax.plot(dpmean.index, dpmean[i], marker='s',
            ms=3, lw=0, c=colors[i], label=int(round(dpmax[i][0],2)))
ax.set_xticks(np.array([1,2,3,4,5,6,7,8,9,10,11,12])-1)
ax.set_xticklabels([1,2,3,4,5,6,7,8,9,10,11,12])
ax.xaxis.tick_bottom()
ax.set_xlabel('Cases')
ax.set_ylabel('θ mean [%]')
ax.spines[['right', 'top']].set_visible(False)
ax.tick_params(right=False)
ax.legend(frameon=False, bbox_to_anchor=(1.2, 1.05))
ax.set_ylim(0,50)
# fig.savefig(fig_path+'resume_pmean_cases.png', dpi=300, bbox_inches='tight')

fig, ax = plt.subplots(1, 1, figsize=(5, 3))
n = 17
colors = pl.cm.plasma(np.linspace(0,1,n))
for i in range(17):
    ax.plot(dpmax.index, dpmax[i], marker='s',
            ms=3, lw=0, c=colors[i], label=int(round(dpmax[i][0],2)))
ax.set_xticks(np.array([1,2,3,4,5,6,7,8,9,10,11,12])-1)
ax.set_xticklabels([1,2,3,4,5,6,7,8,9,10,11,12])
ax.xaxis.tick_bottom()
ax.set_xlabel('Cases')
ax.set_ylabel('θ max [%]')
ax.spines[['right', 'top']].set_visible(False)
ax.tick_params(right=False)
ax.legend(frameon=False, bbox_to_anchor=(1.2, 1.05))
ax.set_ylim(0,50)
# fig.savefig(fig_path+'resume_pmax_cases.png', dpi=300, bbox_inches='tight')

# dk_max.T.plot(lw=0, marker='o')
# dk_mean.T.plot(lw=0, marker='o')

# dp_max.T.plot(lw=0, marker='o')
# dp_mean.T.plot(lw=0, marker='o')


#%% ---- MODELING

# 12 models
# 1 porosity per model : best on streamflow and intermittence

#%% PREPROCESSING

iD_iter='t1'
dfs = pd.read_csv(out_path+'/'+'_calib_'+iD_iter+'_'+'all'+'.csv', sep=';')
watershed_names = ['Nant_EUDTM30m',
                   'Vare_EUDTM30m',
                   ]
types_obs = ['perennial_natural_streams',
             # 'fully_natural_streams',
             # 'fully_natural_streams_springs',
             # 'fully_natural_streams_springs_wetlands'
             ]

# recharge = select_period(dfd['REC_REA_historic'],2016,2018)/1000
# runoff = select_period(dfd['RUN_REA_historic'],2016,2018)/1000

recharge = select_period(hgs_wb['PPT-AET_m/d_sim1'],2016,2018)
runoff = select_period(hgs_wb['PPT-AET_m/d_sim1'],2016,2018)

dic_K = {}
for watershed_name in watershed_names[:]:
    d1 = dfs[dfs['watershed_name']==watershed_name]
    for type_obs in types_obs[:]:
        d2 = d1[d1['type_obs']==type_obs]
        d3 = d2.iloc[-1:]
        val_K = d3.K.values[0]
        val_KR = d3.KR.values[0]
        # dic_K[watershed_name] = val_K
        dic_K[watershed_name] = val_KR * recharge.mean()
        print(val_KR, val_KR * recharge.mean() / 3600 / 24)
        
box = True # or False
sink_fill = False # or True
sim_state = 'transient' # 'steady' or 'transient'
plot_cross = False
first_clim = 'mean' # or 'first or value
nlay = 1
lay_decay = 1 # 1 for no decay
bottom = None # elevation in meters, None for constant auifer thickness, or 2D matrix
thick = 30 # if bottom is None, aquifer thickness
cond_decay = 0 # exponential decay : 1/20 (half decrease at 20m)
verti_cond = None # or [ [1e-5, [0, 20]],
cond_drain = None # or value of conductance
poro_decay = 0 # exponential decay : 1/20 (half decrease at 20m)
bc_left = None # or value
bc_right = None # or value
sea_level = 'None' # or value based on specific data : BV.oceanic.MSL
zone_partic = 'domain' # or watershed

list_porosity = np.array([0.1, 0.5, 1, 2, 5, 10, 30]) / 100

# iD_set_simulations = 'explorSy_test1'
iD_set_simulations = 'explorSy_pptaet1'

#%% PROCESSING RUN

list_model_name = []
list_success_modflow = []
list_model_modflow = []

for watershed_name in watershed_names[:]:
    
    BV = watershed_root.Watershed(watershed_name=watershed_name, dem_path=dem_path, out_path=out_path, load=True)
    area = BV.geographic.area
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' # necessary for plots
    
    BV.add_settings()
    BV.add_climatic()
    BV.add_geometric() # soon
    BV.add_hydraulic()
    BV.settings.update_box_model(box)
    BV.settings.update_sink_fill(sink_fill)
    BV.settings.update_simulation_state(sim_state)
    BV.settings.update_active_plot(plot_cross=plot_cross)
    BV.climatic.update_recharge(recharge, sim_state=sim_state)
    BV.climatic.update_runoff(runoff, sim_state=sim_state)
    BV.climatic.update_first_clim(first_clim)
    BV.hydraulic.update_nlay(nlay) # 1
    BV.hydraulic.update_lay_decay(lay_decay) # 1
    BV.hydraulic.update_bottom(bottom) # None
    BV.hydraulic.update_thick(thick) # 30 / intervient pas si bottom != None
    BV.hydraulic.update_cond_vertical(verti_cond)
    BV.hydraulic.update_cond_drain(cond_drain)
    BV.hydraulic.update_lay_decay(poro_decay)
    BV.settings.update_bc_sides(bc_left, bc_right)
    BV.add_oceanic(sea_level)
    BV.settings.update_input_particules(zone_partic=zone_partic)
    
    hyd_cond = dic_K[watershed_name]
    BV.hydraulic.update_hyd_cond(hyd_cond)
    
    compt = 0
    
    for i, porosity in enumerate(list_porosity[:]):
        
        BV.hydraulic.update_porosity(porosity)
        
        now = datetime.now()
        oclock = now.strftime("%Y%m%d_%Hh%Mm%Ss")
            
        model_name = iD_set_simulations+'-'+iD_iter+'-'+str(compt)+'-'+str(round(hyd_cond,4))+'-'+str(round(porosity,4))+'-'+oclock
        BV.settings.update_model_name(model_name)
        print(model_name)

        model_modflow = BV.preprocessing_modflow()
        success_modflow = BV.processing_modflow(model_modflow, write_model=True, run_model=True)
        
        list_model_name.append(model_name)
        list_success_modflow.append(success_modflow)
        list_model_modflow.append(model_modflow)

        compt += 1

    dictio = {}
    dictio['list_model_name'] = list_model_name
    dictio['list_success_modflow'] = list_success_modflow
    dictio['list_model_modflow'] = list_model_modflow
    h5file = simulations_folder+'/'+'results_listing_'+iD_set_simulations
        
    dd.io.save(h5file, dictio)
    
#%% RELOAD

for watershed_name in watershed_names[:]:

    BV = watershed_root.Watershed(watershed_name=watershed_name, dem_path=dem_path, out_path=out_path, load=True)

    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' # necessary for plots

    h5file = simulations_folder+'/'+'results_listing_'+iD_set_simulations
    d = dd.io.load(h5file)
    
    if watershed_name == 'Nant_EUDTM30m':
        
        list_model_name = d['list_model_name'][:]
        list_success_modflow = d['list_success_modflow'][:]
        list_model_modflow = d['list_model_modflow'][:]
    
    if watershed_name == 'Vare_EUDTM30m':
        
        list_model_name = d['list_model_name'][7:]
        list_success_modflow = d['list_success_modflow'][7:]
        list_model_modflow = d['list_model_modflow'][7:]

#%% POSTPROCESSING

for watershed_name in watershed_names[:]:

    BV = watershed_root.Watershed(watershed_name=watershed_name, dem_path=dem_path, out_path=out_path, load=True)

    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' # necessary for plots
        
    for model_name, success_modflow, model_modflow in zip(list_model_name[:],
                                                          list_success_modflow[:],
                                                          list_model_modflow[:]):
        if success_modflow == True:
            
            BV.geographic.watershed_box_buff_dem = stable_folder + 'geographic/watershed_box_buff_dem.tif'
            model_modflow.dem_path = BV.geographic.watershed_box_buff_dem
            BV.geographic.watershed_buff_fill = stable_folder + 'geographic/watershed_box_buff_fill.tif'
            model_modflow.geographic.watershed_buff_fill = BV.geographic.watershed_buff_fill
            BV.geographic.watershed_dem = stable_folder + 'geographic/watershed_dem.tif'
            model_modflow.geographic.watershed_dem = BV.geographic.watershed_dem
            
            BV.postprocessing_modflow(model_modflow,
                                      watertable_elevation = True,
                                      watertable_depth= True, 
                                      seepage_areas = True,
                                      outflow_drain = True,
                                      groundwater_flux = True,
                                      groundwater_storage = True,
                                      accumulation_flux = True,
                                      persistency_index=True,
                                      intermittency_monthly=False,
                                      intermittency_daily=True,
                                      export_all_tif = False)
    
            timeseries_results = BV.postprocessing_timeseries(model_modflow=model_modflow,
                                                              model_modpath=None,
                                                              actual_date=True, 
                                                              subbasin_results=True,
                                                              freq_time='D')

#%% STREAMFLOW PLOT

iD_set_simulations = 'explorSy_test1'
iD_set_simulations = 'explorSy_pptaet1'

def select_period(df, first, last):
    df = df[(df.index.year>=first) & (df.index.year<=last)]
    return df
    


for watershed_name in ['Nant_EUDTM30m','Vare_EUDTM30m'][:]:
    
    BV = watershed_root.Watershed(watershed_name=watershed_name, dem_path=dem_path, out_path=out_path, load=True)
    area = BV.geographic.area
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' # necessary for plots
    # simul_list = sorted(glob.glob(simulations_folder+iD_set_simulations+'*'), key=os.path.getmtime)
    # simul_list = sorted(glob.glob(simulations_folder+'t1'+'*'), key=os.path.getmtime)
    
    h5file = simulations_folder+'/'+'results_listing_'+iD_set_simulations
    d = dd.io.load(h5file)
    list_model_name = d['list_model_name'][:]
    list_success_modflow = d['list_success_modflow'][:]
    list_model_modflow = d['list_model_modflow'][:]
    
    if watershed_name == 'Vare_EUDTM30m':
        
        list_model_name = d['list_model_name'][7:]
        list_success_modflow = d['list_success_modflow'][7:]
        list_model_modflow = d['list_model_modflow'][7:]
    
    simul_list = []
    for si in list_model_name:
        simul_list.append(os.path.join(simulations_folder,si))
        
    if watershed_name == 'Nant_EUDTM30m':
        Qobs_name = '1_q_weir_s2_obs_NAs_removed.smp'
        Qsim_name = '1_simulated_Q_S2.smp'
    if watershed_name == 'Vare_EUDTM30m':
        Qobs_name = '1_q_ric_s3_obs_NAs_removed.smp'
        Qsim_name = '1_simulated_Q_S3.smp'
    init_path = data_path + '_hgs/Supplementary Information Thornton/full_model/'
    
    dfQ = pd.read_csv(init_path+Qobs_name, delim_whitespace=True, header=None)
    dfQ['datetxt'] = dfQ[1]+ ' ' + dfQ[2].apply(str)
    dfQ['datetime'] = [datetime.strptime(date, "%d/%m/%Y %H:%M:%S") for date in dfQ['datetxt']]
    dfQ.index = dfQ['datetime']
    dfQ = dfQ.resample('D').mean()
    Qobs = dfQ[3]
    Qobs = (Qobs / (area*1000000)) * 1000 # m3/day to mm/day
    # Qobs = Qobs.resample('M').sum() * 1000 # m/day to mm/month
    
    dfQsim = pd.read_csv(init_path+Qsim_name, delim_whitespace=True, header=None)
    dfQsim['datetxt'] = dfQsim[1]+ ' ' + dfQsim[2].apply(str)
    dfQsim['datetime'] = [datetime.strptime(date, "%d/%m/%Y %H:%M:%S") for date in dfQsim['datetxt']]
    dfQsim.index = dfQsim['datetime']
    dfQsim = dfQsim.resample('D').mean()
    Qsim = dfQsim[3]
    Qsim = (Qsim / (area*1000000)) * 1000 # m3/day to mm/day
    
    for i, simul in enumerate(simul_list[:]):
        
        fig, (a0, a1) = plt.subplots(1, 2, gridspec_kw={'width_ratios': [3, 1]},
                                     figsize=(10,3))
        
        model_name = simul.split('/')[-1]
        print(i, model_name.upper())
        
        Smod_path = simul+'/_postprocess/_timeseries/_simulated_timeseries.csv'
        Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
        
        Qmod = Smod['outflow_drain']
        Qmod = Qmod.squeeze() * 1000
        r = BV.climatic.runoff
        # Qmod = Qmod + (r * 1000)
        Qmod = Qmod
        
        Rmod = Smod['recharge'] * 1000
        
        yearsmaj = mdates.YearLocator(1)   # every year
        yearsmin = mdates.YearLocator(1)
        # monthsmaj = mdates.MonthLocator(6)  # every month
        # monthsmin = mdates.MonthLocator(3)
        # months_fmt = mdates.DateFormatter('%m') #b = name of month ?
        years_fmt = mdates.DateFormatter('%Y')
    
        ax = a0
        ax.plot(Qobs, color='k', lw=1, ls='-', zorder=0, label='Observed')
        ax.plot(Qsim, color='dodgerblue', lw=1, ls='-', zorder=0, label='Simulated HGS')
        ax.plot(Qmod, color='red', lw=1, label='Simulated MF')
        ax.set_xlabel('Date')
        ax.set_ylabel('Q [mm/d]')
        ax.set_yscale('log')
        ax.set_ylim(0.1,100)
        years_maj = mdates.YearLocator()   # every year
        months_maj = mdates.MonthLocator()  # every x month
        ax.xaxis.set_major_locator(years_maj)
        ax.xaxis.set_minor_locator(months_maj)
        ax.set_xlim(pd.to_datetime('2016'), pd.to_datetime('2019'))
        ax.legend(loc='lower left')
        ax.set_title(model_name.upper(), fontsize=10)
        
        axb = ax.twinx()
        axb.bar(Rmod.index, Rmod,color='grey', edgecolor='grey', width=1, lw=0)
        axb.set_ylim(0,100)
        axb.invert_yaxis()
        axb.set_yticklabels([0,25])
        
        mix = Qobs.copy().to_frame()
        mix.columns = ['Qobs']
        mix['Qmod'] = Qmod
        mix['Qsim'] = Qsim
        mix = mix.dropna()
        
        Qobs_stat = mix.Qobs
        Qmod_stat = mix.Qmod
        Qsim_stat = mix.Qsim
        
        import hydroeval as he
        NSE = he.evaluator(he.nse, Qmod_stat, Qobs_stat)[0]
        NSElog = he.evaluator(he.nse, Qmod_stat, Qobs_stat, transform='log')[0]
        RMSE = np.sqrt(np.nanmean((Qobs_stat.values-Qmod_stat.values)**2))
        KGE = he.evaluator(he.kge, Qmod_stat, Qobs_stat)[0][0]
        # print(model_name.upper())
        print('NSE', round(NSE,2))
        print('NSElog', round(NSElog,2))
        print('RMSE', round(RMSE,2))
        print('KGE', round(KGE,2))
        hgsNSE = he.evaluator(he.nse, Qsim_stat, Qobs_stat)[0]
        hgsNSElog = he.evaluator(he.nse, Qsim_stat, Qobs_stat, transform='log')[0]
        hgsRMSE = np.sqrt(np.nanmean((Qobs_stat.values-Qsim_stat.values)**2))
        hgsKGE = he.evaluator(he.kge, Qsim_stat, Qobs_stat)[0][0]
        # print(model_name.upper())
        print('NSE', round(hgsNSE,2))
        print('NSElog', round(hgsNSElog,2))
        print('RMSE', round(hgsRMSE,2))
        print('KGE', round(hgsKGE,2))
        
        ax = a1
        ax.scatter(mix.Qobs, mix.Qmod,
                   s=10, edgecolor='none', alpha=0.75, facecolor='red')
        ax.scatter(mix.Qobs, mix.Qsim,
                   s=10, edgecolor='none', alpha=0.75, facecolor='dodgerblue',
                   label='$NSE_{log}$' + ' = ' + str(hgsNSElog.round(2)))
        ax.set_xscale('log')
        ax.set_yscale('log')
        ax.legend(loc='lower right', frameon=False, labelcolor='dodgerblue')
        # ax.plot((0.1,1000),(0.1,1000), color='grey', zorder=-1)
        # ax.set_xlim(1,500)
        # ax.set_ylim(1,500)
        
        ax.plot((0.0001,1000),(0.0001,1000), c='k', ls='--')
        
        if watershed_name == 'Nant_EUDTM30m':
            ax.set_xlim(0.1,100)
            ax.set_ylim(0.1,100)
        if watershed_name == 'Vare_EUDTM30m':
            ax.set_xlim(0.01,100)
            ax.set_ylim(0.01,100)   
        ax.set_xlabel('$Q_{obs}$ [mm/d]',
                      # fontsize=12
                      )
        ax.set_ylabel('$Q_{sim}$ [mm/d]',
                      # fontsize=12
                      )
        
        ax.patch.set_visible(True)
        ax.set_title('$NSE_{log}$' + '  ' + str(round(NSElog,2)), fontsize=10, color='red')

        # move ax in front
        ax.set_zorder(axb.get_zorder() + 1)
        
        fig.tight_layout()
                    
        fig.savefig(os.path.join(simulations_folder, '_figures',
                    'STREAMFLOW_'+model_name+'.png'),
                    bbox_inches='tight')

#%% SATURATION PLOT

types_obs = ['perennial_natural_streams',
             'fully_natural_streams',
             'fully_natural_streams_springs',
             'fully_natural_streams_springs_wetlands']

iD_set_simulations = 'explorSy_test1'
iD_set_simulations = 'explorSy_pptaet1'

def select_period(df, first, last):
    df = df[(df.index.year>=first) & (df.index.year<=last)]
    return df

for w, watershed_name in enumerate(watershed_names[:]):
    
    BV = watershed_root.Watershed(watershed_name=watershed_name, dem_path=dem_path, out_path=out_path, load=True)
    area = BV.geographic.area
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' # necessary for plots
    
    # dem_tif = imageio.imread(BV.geographic.watershed_dem)
    dem_tif = imageio.imread(stable_folder+'geographic/watershed_dem.tif')
    dds = []
    for type_obs in types_obs:
        hydro_path = stable_folder+'hydrography/'+type_obs+'.tif'
        hydro_tif = imageio.imread(hydro_path)
        hydro_tif_mask = np.ma.masked_where(dem_tif==-99999, hydro_tif)
        hydro_tif_stream_mask = np.ma.masked_where(hydro_tif_mask<0, hydro_tif_mask)
        draind = hydro_tif_stream_mask.count() / hydro_tif_mask.count()
        dds.append(draind)
        print(draind*100)
    
    h5file = simulations_folder+'/'+'results_listing_'+iD_set_simulations
    d = dd.io.load(h5file)
    list_model_name = d['list_model_name'][:]
    list_success_modflow = d['list_success_modflow'][:]
    list_model_modflow = d['list_model_modflow'][:]
    
    if watershed_name == 'Vare_EUDTM30m':
        
        list_model_name = d['list_model_name'][7:]
        list_success_modflow = d['list_success_modflow'][7:]
        list_model_modflow = d['list_model_modflow'][7:]
    
    # simul_list = sorted(glob.glob(simulations_folder+iD_set_simulations+'*'), key=os.path.getmtime)
    # simul_list = sorted(glob.glob(simulations_folder+'t1'+'*'), key=os.path.getmtime)
    simul_list = []
    for si in list_model_name:
        simul_list.append(os.path.join(simulations_folder,si))

    for i, simul in enumerate(simul_list[:]):
    
        model_name = simul.split('/')[-1]
        print(model_name.upper())
        
        Smod_path = simul+'/_postprocess/_timeseries/_simulated_timeseries.csv'
        Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)

        fig, ax = plt.subplots(1, 1, figsize=(6,3))
        
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
        ax.step(Smod.index, Smod['seepage_areas'], color='grey',
                marker=None, markeredgecolor='none',
                markersize=5, lw=1, label='upstream',
                where='pre')
        
        if watershed_name == 'Nant_EUDTM30m':
            ax.set_ylim(0,50)
        if watershed_name == 'Vare_EUDTM30m':
            ax.set_ylim(0,6)
        # ax.set_yticks(np.arange(0,15.05,2.5))
        ax.set_ylabel('$A_{sat}$ [%]')
        ax.set_xlim(pd.to_datetime('2016'), pd.to_datetime('2019'))
        plt.xticks(rotation=0, ha="right")
    
        years_maj = mdates.YearLocator()   # every year
        months_maj = mdates.MonthLocator()  # every x month
        ax.xaxis.set_major_locator(years_maj)
        ax.xaxis.set_minor_locator(months_maj)
        
        ax.set_title(model_name.upper(), fontsize=10)
        
        for j, hline in enumerate(dds[:2]):
            if j == 0:
                cl = 'navy'
            if j == 1:
                cl = 'dodgerblue'
            ax.axhline(hline*100, c=cl, ls='--')
            
        fig.tight_layout()
                    
        fig.savefig(os.path.join(simulations_folder, '_figures',
                    'SATURATION_'+model_name+'.png'),
                    bbox_inches='tight')

#%% RESIDENCE PLOT

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



