# -*- coding: utf-8 -*-
"""
Created on Tue Apr 23 10:04:34 2024

@author: ronan
"""

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

def deficiency_evaporation(dfmonth, ppt_col, etp_col, ppt_etp_col, etr_col, ru_col, de_col,
                           ru_mm):
    calc = pd.DataFrame()
    calc[ppt_etp_col] = (dfmonth[ppt_col]-dfmonth[etp_col]).round(2)
    calc[ru_col] = np.nan
    calc[etp_col] = dfmonth[etp_col]
    calc[ppt_col] = dfmonth[ppt_col]
    
    long = np.array(range(0,len(calc)))
    
    for r in long:
        idx = calc.index[0]
        calc[ru_col][idx] = ru_mm
        if r == len(calc)-1:
            break
        else:
            if (calc[ru_col][r] + calc[ppt_etp_col][r+1]) >= ru_mm:
                calc[ru_col][r+1] = ru_mm      
            if 0 < (calc[ru_col][r] + calc[ppt_etp_col][r+1]) < ru_mm:
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
            # calc[etr_col][idx2] = (calc[ppt_col][idx2] + (calc[ru_col][idx2]-1) - calc[ru_col][idx2]) # old
            calc[etr_col][idx2] = (calc[ppt_col][idx2] + (calc[ru_col][idx2]) - calc[ru_col][idx2]) # new
    
    calc[de_col] = calc[etp_col] - calc[etr_col]

    for n in long:
        if calc[de_col][n] < 0:
            calc[de_col][n] = 0
            
    calc[de_col] = calc[de_col].round(2)
    
    dfmonth[etr_col] = calc[etr_col]
    dfmonth[de_col] = calc[de_col]
    dfmonth[ru_col] = calc[ru_col]
    
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

git_path = 'C:/Users/ronan/GitHub/HydroModPy-dev0.1/'
data_path = 'C:/Users/ronan/OneDrive/UNINE/8_Modeling/Lluiz/_data/'
# data_path = 'C:/Users/ronan/OneDrive/UNINE/8_Modeling/Lasset/_data/'
out_path = 'C:/Users/ronan/Simulations/'
# out_path = 'C:/Users/ronan/OneDrive - unine.ch/SIMULATIONS/'

fig_path = 'C:/Users/ronan/OneDrive/UNINE/8_Modeling/Lluiz/_figures/'

# wbt.resample(
#     data_path+'DEM_10m_transf.tif', 
#     data_path+'DEM_100m_transf.tif', 
#     cell_size=30, 
#     base=None, 
#     method="cc")

wbt.resample(
    data_path+'Contraix/'+'DEM_2m_Contraix/'+'MET_ICGC_2m_ETRS89_contraix.tif', 
    data_path+'Contraix/'+'DEM_2m_Contraix/'+'MET_ICGC_10m_ETRS89_contraix.tif', 
    cell_size=10, 
    base=None, 
    method="cc")

# watershed_name = 'Molieres'
# watershed_name = 'Peatland_large'
# watershed_name = 'Contraix_large'
# watershed_name = 'Contraix_large_30m'
watershed_name = 'Contraix_large_10m'
# watershed_name = 'Contraix_minus_10m'
# watershed_name = 'Poschiavino_100m'
# watershed_name = 'Poschiavino_10m'

if watershed_name == 'Molieres':
    dem_name = 'DEM_larger_study_catchment_30m_ETRS89.tif' # EUDTM_Alps_30m_vallon
    dem_name = 'DEM_larger_study_catchment_10m_ETRS89.tif'
    # dem_name = 'DEM_100m_transf.tif' # EUDTM_Alps_30m_vallon
    dem_path = data_path + 'DEM_30m_10m_2m_large_catchment/' + dem_name
    subbasin_path = True # generate subbasins from stations or manual points
    from_dem = None # True or False if the process start from a given DEM of xyz file
    cell_size = None # specify new resolution from a given DEM or None
    from_xyv = [316470.736, 4721811.911, 100, 10, 'EPSG:25831']
    # from_shp = [data_path + 'Catchment_Poschiavino.shp',
    #             1] # specify a path if process start from a given shapefile
    from_shp = None

if watershed_name == 'Peatland_large':
    dem_name = 'DEM_larger_study_catchment_2m_ETRS89.tif'
    # dem_name = 'DEM_100m_transf.tif' # EUDTM_Alps_30m_vallon
    dem_path = data_path + 'DEM_30m_10m_2m_large_catchment/' + dem_name
    subbasin_path = True # generate subbasins from stations or manual points
    from_dem = None # True or False if the process start from a given DEM of xyz file
    cell_size = None # specify new resolution from a given DEM or None
    from_xyv = None
    # from_shp = [data_path + 'Catchment_Poschiavino.shp',
    #             1] # specify a path if process start from a given shapefile
    from_shp = ['C:/Users/ronan/OneDrive/UNINE/8_Modeling/Lluiz/_data/Catchment polygons/peatland_basin/molieres_peatland.shp',
                '500']
    
if watershed_name == 'Contraix_large_10m':
    # dem_name = 'MET_ICGC_2m_ETRS89_contraix.tif'
    # dem_name = 'MET_ICGC_30m_ETRS89_contraix.tif'
    dem_name = 'MET_ICGC_10m_ETRS89_contraix.tif'
    # dem_name = 'DEM_100m_transf.tif' # EUDTM_Alps_30m_vallon
    dem_path = data_path + 'Contraix/'+'DEM_2m_Contraix/' + dem_name
    subbasin_path = True # generate subbasins from stations or manual points
    from_dem = None # True or False if the process start from a given DEM of xyz file
    cell_size = None # specify new resolution from a given DEM or None
    # from_xyv = [330707.574, 4715389.475, 30, 10, 'EPSG:25831']
    from_xyv = [330707.574, 4715389.475, 100, 10, 'EPSG:25831']
    # from_shp = [data_path + 'Catchment_Poschiavino.shp',
    #             1] # specify a path if process start from a given shapefile
    from_shp = None    

if watershed_name == 'Contraix_minus_10m':
    # dem_name = 'MET_ICGC_2m_ETRS89_contraix.tif'
    # dem_name = 'MET_ICGC_30m_ETRS89_contraix.tif'
    dem_name = 'MET_ICGC_10m_ETRS89_contraix.tif'
    # dem_name = 'DEM_100m_transf.tif' # EUDTM_Alps_30m_vallon
    dem_path = data_path + 'Contraix/'+'DEM_2m_Contraix/' + dem_name
    subbasin_path = True # generate subbasins from stations or manual points
    from_dem = None # True or False if the process start from a given DEM of xyz file
    cell_size = None # specify new resolution from a given DEM or None
    # from_xyv = [330707.574, 4715389.475, 30, 10, 'EPSG:25831']
    from_xyv = [329587.844,4715755.589, 50, 50, 'EPSG:25831']
    # from_shp = [data_path + 'Catchment_Poschiavino.shp',
    #             1] # specify a path if process start from a given shapefile
    from_shp = None    

watershed_names = [watershed_name]

#%% LOAD

load = True
load = False

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

# SUBBASIN

# BV.add_intermittency('None','None')
# BV.add_subbasin(data_path+'_coordinates_additional/', sub_snap_dist=50)

#%% DATA

wbt.verbose = False

# types_obs = ['Stream_network_topo_large_catchment']
# fields_obs = ['fid']
# hydro_path = data_path + 'Stream network/'

# types_obs = ['rivers_wetlands_l_topografia']
# fields_obs = ['fid']
# hydro_path = data_path + 'Contraix/Hidrologia_contriax/'
        
wbt.vector_lines_to_raster(
                data_path + 'Contraix/Hidrologia_contriax/'+'rivers_topografia.shp', 
                data_path + 'Contraix/Hidrologia_contriax/'+'rivers_topografia.tif', 
                field="FID", 
                nodata=True, 
                cell_size=None, 
                base=BV.geographic.watershed_box_buff_dem)
wbt.raster_to_vector_points(data_path + 'Contraix/Hidrologia_contriax/'+'rivers_topografia.tif',
                            data_path + 'Contraix/Hidrologia_contriax/'+'rivers_topografia_pt.shp')
wbt.vector_polygons_to_raster(
                data_path + 'Contraix/Hidrologia_contriax/'+'wetlands_topografia.shp', 
                data_path + 'Contraix/Hidrologia_contriax/'+'wetlands_topografia.tif', 
                field="FID", 
                nodata=True, 
                cell_size=None, 
                base=BV.geographic.watershed_box_buff_dem)
wbt.raster_to_vector_points(data_path + 'Contraix/Hidrologia_contriax/'+'wetlands_topografia.tif',
                            data_path + 'Contraix/Hidrologia_contriax/'+'wetlands_topografia_pt.shp')
list_p = [data_path + 'Contraix/Hidrologia_contriax/'+'rivers_topografia_pt.shp',data_path + 'Contraix/Hidrologia_contriax/'+'wetlands_topografia_pt.shp']
wbt.merge_vectors(
    'C:/Users/ronan/OneDrive/UNINE/8_Modeling/Lluiz/_data/Contraix/Hidrologia_contriax/rivers_topografia_pt.shp;C:/Users/ronan/OneDrive/UNINE/8_Modeling/Lluiz/_data/Contraix/Hidrologia_contriax/wetlands_topografia_pt.shp', 
    'C:/Users/ronan/OneDrive/UNINE/8_Modeling/Lluiz/_data/Contraix/Hidrologia_contriax/rivers_wetlands_topografia_pt.shp')
types_obs = ['rivers_wetlands_topografia_pt']
fields_obs = ['fid']
hydro_path = data_path + 'Contraix/Hidrologia_contriax/'

BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=dem_path, 
                              out_path=out_path,
                              load=True)

for type_obs, field_obs in zip(types_obs, fields_obs):

    BV.add_hydrography(hydro_path, types_obs=[type_obs], fields_obs=[field_obs])
    
    try:
        # visualization_watershed.watershed_local(dem_path, BV)
        visualization_watershed.watershed_dem(BV)
    except:
        pass

# wbt.find_main_stem(
#     stable_folder+'geographic/'+'watershed_buff_direc.tif', 
#     BV.hydrology.tif_streams, 
#     stable_folder+'hydrology/'+types_obs[0]+'_main'+'.tif', 
#     esri_pntr=False, 
#     zero_background=False)

#%% RECHARGE MOLIERES

files_path = glob.glob('C:/Users/ronan/OneDrive/UNINE/8_Modeling/Lluiz/_data/Meteo/'+'*')
# y = pd.DataFrame()
for i, file_path in enumerate(files_path):
    x = pd.read_csv(file_path, parse_dates=True)
    if i == 0:
        y = x.copy()
    else:
        y = pd.concat([y,x], ignore_index = False, sort=True)

y = y.rename(columns={'station_province': 'Alti',
                      'altitude': 'Tmean',
                      'mean_temperature': 'Tmin',
                      'min_temperature': 'Tmax',
                      'max_temperature': 'Hmean',
                      'mean_relative_humidity': 'Hmin',
                      'min_relative_humidity': 'Hmax',
                      'max_relative_humidity': 'P',
                      'precipitation': 'Wdirec',
                      'mean_wind_direction': 'Wspeed',
                      'mean_wind_speed': 'Srad',
                      'global_solar_radiation': 'cX',
                      'geometry': 'cY',
                      }) 

# plt.plot(y['Tmean'])
# plt.plot(y['Tmin'])
# plt.plot(y['Tmax'])
# plt.plot(y['Hmean'])
# plt.plot(y['Hmin'])
# plt.plot(y['Hmax'])
fig, ax = plt.subplots(1,1, figsize=(15,5))
ax.plot(y['P'])
ax.plot(y['Srad'], 'red')

import pyet
y['Oudin'] = abs(pyet.oudin(y['Tmean'], lat=pyet.deg_to_rad(42)))
y["Hargreaves"] = abs(pyet.hargreaves(y['Tmean'], tmax=y['Tmax'], tmin=y['Tmin'], lat=pyet.deg_to_rad(42)))
y["Hamon"] = abs(pyet.temperature.hamon(y['Tmean'], lat=pyet.deg_to_rad(42)))
y["Macguinness"] = abs(pyet.radiation.mcguinness_bordne(y['Tmean'], lat=pyet.deg_to_rad(42)))

fig, ax = plt.subplots(1,1, figsize=(15,5))
ax.plot(y['Oudin'])
ax.plot(y['Hargreaves'])
ax.plot(y['Hamon'])
ax.plot(y['Macguinness'])
ax.legend()

ym = select_period(y, 2020, 2023)
ym = ym.resample('M').sum()

ym = ym.reset_index()
ym = ym.rename(columns={'index': 'Date'})
                      
deficiency_evaporation(ym, 'P',
                            'Oudin', 'PPT-ETP',
                            'ETR', 'RU', 'DE',
                            125
                            )

fig, ax = plt.subplots(1,1, figsize=(15,5))
ax.plot(ym['P'], 'blue')
ax.plot(ym['ETR'], 'green')
ax.plot(ym['P']-ym['Oudin'], 'orange')
ax.plot(ym['P']-ym['ETR'], 'red')
# ax.plot(y['PPT-ETP'])

ym = ym.set_index('Date')
recharge = ym['P']-ym['ETR']
fig, ax = plt.subplots(1,1, figsize=(15,5))
ax.plot(recharge)
print(recharge.resample('Y').sum())
print(recharge.resample('Y').sum().mean())

#%% RECHARGE CONTRAIX

from datetime import datetime
file_path = 'C:/Users/ronan/OneDrive/UNINE/8_Modeling/Lluiz/_data/Contraix/Meteo/meteo_Contraix_2010_2023.csv'
x = pd.read_csv(file_path, sep=';', decimal=',')
x['date'] = pd.to_datetime(x['Dia'], format = '%d.%m.%Y')
x.index = x['date']
x = select_period(x,2021,2022)

x['Oudin'] = abs(pyet.oudin(x['Td'], lat=pyet.deg_to_rad(42)))
x["Hargreaves"] = abs(pyet.hargreaves(x['Td'], tmax=x['Tdmax'], tmin=x['Tdmin'], lat=pyet.deg_to_rad(42)))
x["Hamon"] = abs(pyet.temperature.hamon(x['Td'], lat=pyet.deg_to_rad(42)))
x["Macguinness"] = abs(pyet.radiation.mcguinness_bordne(x['Td'], lat=pyet.deg_to_rad(42)))

# xm = x.resample('M').sum()
xm = x.copy()

deficiency_evaporation(xm, 'precd',
                            'Oudin', 'PPT-ETP',
                            'ETR', 'RU', 'DE',
                            1
                            )

# fig, ax = plt.subplots(1,1, figsize=(15,5))
# ax.plot(xm['precd'], 'blue')
# ax.plot(xm['RU'], 'k')
# ax.plot(xm['ETR'], 'green')
# ax.plot(xm['precd']-xm['Oudin'], 'orange')
# ax.plot(xm['precd']-xm['ETR'], 'red')

xm['recharge'] = xm['precd']-xm['ETR']

fig, ax = plt.subplots(1,1, figsize=(15,5))
# ax.plot(xm['precd'], 'blue')
ax.plot(xm['recharge'], 'red')
# ax.set_yscale('log')

recharge = xm['recharge']

print(xm['precd'].resample('Y').sum())
print(recharge.resample('Y').sum())

#%% ---- CALIB

#%% DICHOTOMY - FUNCTION
"""
import shutil

class MatchingStreams:

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
        
        self.watershed_shp = watershed.geographic.watershed_box_shp
        self.watershed_fill = watershed.geographic.watershed_box_buff_fill
        self.watershed_direc = watershed.geographic.watershed_box_buff_direc
              
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
        shutil.copyfile(self.buff_tif_obs, self.tif_obs)
        # toolbox.clip_tif(self.buff_tif_obs, self.watershed_shp, self.tif_obs, True)
        
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
        shutil.copyfile(tif_sim, self.tif_sim)
        # toolbox.clip_tif(tif_sim, self.watershed_shp, self.tif_sim, True)
        
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
        print(self.watershed_fill, self.tif_obs, self.dist_dem_obs)
        wbt.downslope_distance_to_stream(self.watershed_fill, self.tif_obs, self.dist_dem_obs)
        
        # wbt.downslope_distance_to_stream('C:/Users/ronan/Simulations/Manawa/Regional2/results_stable/geographic/watershed_box_buff_fill.tif',
        #                                   'C:/Users/ronan/Simulations/Manawa/Regional2/results_stable/hydrography/riv_8to9.tif',
        #                                   'C:/Users/ronan/Downloads/test.tif')
        
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

wbt.verbose = False

vers = 'v2'

# types_obs = ['Stream_network_topo_large_catchment']
# fields_obs = ['fid']
# hydro_path = data_path + 'Stream network/'

# types_obs = ['rivers_wetlands_l_topografia']
# fields_obs = ['fid']
# hydro_path = data_path + 'Contraix/Hidrologia_contriax/'

types_obs = ['rivers_wetlands_topografia_pt']
fields_obs = ['fid']
hydro_path = data_path + 'Contraix/Hidrologia_contriax/'
       
df = pd.DataFrame()

for watershed_name in watershed_names[:]:
    
    compt = 0
    id_mod = 0
    
    for type_obs, field_obs in zip(types_obs[:], fields_obs[:]):
   
        print('##### '+watershed_name.upper()+' #####')
        
        
        BV = watershed_root.Watershed(watershed_name=watershed_name, dem_path=dem_path, out_path=out_path, load=True)
        area = BV.geographic.area
        
        shp = gpd.read_file(BV.geographic.watershed_shp)

        stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
        simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' # necessary for plots
        BV.calibration_folder = os.path.join(out_path, watershed_name, 'results_calibration')
        toolbox.create_folder(BV.calibration_folder)
        
        BV.add_hydrography(hydro_path, types_obs=[type_obs], fields_obs=[field_obs])
        
        box = True # or False
        sink_fill = False # or True
        sim_state = 'steady' # 'steady' or 'transient'
        plot_cross = True
        first_clim = 'mean' # or 'first or value
        nlay = 1
        lay_decay = 1 # 1 for no decay
        thick = 50 # if bottom is None, aquifer thickness
        bottom = None
        
        # rec_summer = sim2[sim2.index.month.isin([7,8,9])]
        # recharge = (rec_summer['DRAINC_Q'] * norm_factor) / 1000 # mm/d to m/d
        # recharge = (sim2['DRAINC_Q'] * norm_factor) / 1000 # mm/d to m/d
        # recharge = (isba['REC_REA_historic'] * norm_factor) / 1000 # mm/d to m/d
        recharge = 1200 / 1000 / 365 # mm/d to m/d
        
        verti_cond = None # or [ [1e-5, [0, 20]],
        verti_poro = None
        cond_drain = None # or value of conductance
        porosity = 1 / 100 # -
        poro_decay = 0 # exponential decay : 1/20 (half decrease at 20m)
        cond_decay = 0
        bc_left = None # or value
        bc_right = None # or value
        sea_level = 'None' # or value based on specific data : BV.oceanic.MSL
        zone_partic = 'domain' # or watershed
        
        split_temp = False
        
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
        BV.settings.update_input_particles(zone_partic=zone_partic)        
        BV.hydraulic.update_thick(thick) # 30 / intervient pas si bottom != None
        BV.hydraulic.update_cond_decay(cond_decay) # 0
        BV.hydraulic.update_bottom(bottom) # 0
        BV.settings.update_split_temporal(split_temp)
        
        params_df = pd.DataFrame(columns=['params','init_values','lower_bounds','higher_bounds','units','scale'])
        params_df.loc[0] = ['k1','?',1e-9*3600*24,1e-5*3600*24,'m/j','lin'] ### K/R 0.36 to 36 000
        
        params_file = 'calib_dicot_hom_1v_k1'
        params_df.to_csv(BV.calibration_folder+'/'+params_file+'.csv', sep=';', index=None)
        p_min = params_df['lower_bounds'].values[0]
        p_max = params_df['higher_bounds'].values[0]
        diff = p_max - p_min
        half = (p_min + p_max) / 2
        
        gap = 1.0
                
        while (diff > ((gap/100) * half)):
            
            half = (p_min + p_max) / 2
            hyd_cond = half.copy() # if K in calib_params.csv
            kr = hyd_cond / BV.climatic.recharge
                        
            BV.hydraulic.update_hyd_cond(hyd_cond)
            
            now = datetime.now()
            oclock = now.strftime("%Y%m%d_%Hh%Mm%Ss") 

            model_name = vers+'_'+str(id_mod)+'_'+str(type_obs)+'_'+str(compt)+'_'+str("{:.2e}".format(hyd_cond/24/3600))+'_'+str(round(hyd_cond/recharge,2)) #+'-'+oclock
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
                                                              actual_date=True, 
                                                              subbasin_results=True) # or None
        
            iter_results = MatchingStreams(BV, iteration_label=model_name)
            
            
            obs_to_sim = gpd.read_file(os.path.join(BV.calibration_folder, model_name, '_matchingstreams','obs_pt.shp'))
            obs_to_sim = obs_to_sim.clip(shp)
            obs_to_simf = gpd.read_file(os.path.join(BV.calibration_folder, model_name, '_matchingstreams','obs_ptf.shp'))
            obs_to_simf = obs_to_simf.clip(shp)
            obsf_to_sim = gpd.read_file(os.path.join(BV.calibration_folder, model_name, '_matchingstreams','obsflow.shp'))
            obsf_to_sim = obsf_to_sim.clip(shp)
            obsf_to_simf = gpd.read_file(os.path.join(BV.calibration_folder, model_name, '_matchingstreams','obsflowf.shp'))
            obsf_to_simf = obsf_to_simf.clip(shp)
            
            sim_to_obs = gpd.read_file(os.path.join(BV.calibration_folder, model_name, '_matchingstreams','sim_pt.shp'))
            sim_to_obs = sim_to_obs.clip(shp)
            sim_to_obsf = gpd.read_file(os.path.join(BV.calibration_folder, model_name, '_matchingstreams','sim_ptf.shp'))
            sim_to_obsf = sim_to_obsf.clip(shp)
            simf_to_obs = gpd.read_file(os.path.join(BV.calibration_folder, model_name, '_matchingstreams','simflow.shp'))
            simf_to_obs = simf_to_obs.clip(shp)
            simf_to_obsf = gpd.read_file(os.path.join(BV.calibration_folder, model_name, '_matchingstreams','simflowf.shp'))
            simf_to_obsf = simf_to_obsf.clip(shp)
                    
            mean_obs_to_sim = np.nanmean(obs_to_sim[obs_to_sim['VALUE1']>=0]['VALUE1'])
            mean_obs_to_simf = np.nanmean(obs_to_simf[obs_to_simf['VALUE1']>=0]['VALUE1'])
            mean_obsf_to_sim = np.nanmean(obsf_to_sim[obsf_to_sim['VALUE1']>=0]['VALUE1'])
            mean_obsf_to_simf = np.nanmean(obsf_to_simf[obsf_to_simf['VALUE1']>=0]['VALUE1'])
            
            mean_sim_to_obs = np.nanmean(sim_to_obs[sim_to_obs['VALUE1']>=0]['VALUE1'])
            mean_sim_to_obsf = np.nanmean(sim_to_obsf[sim_to_obsf['VALUE1']>=0]['VALUE1'])
            mean_simf_to_obs = np.nanmean(simf_to_obs[simf_to_obs['VALUE1']>=0]['VALUE1'])
            mean_simf_to_obsf = np.nanmean(simf_to_obsf[simf_to_obsf['VALUE1']>=0]['VALUE1'])
            
            # v1
            # obs = mean_obs_to_sim
            # sim = mean_sim_to_obs
            # indicator = sim/obs
            
            # v2
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
                        
        id_mod += 1
        
df.to_csv(BV.calibration_folder+'/'+vers+'_'+str('models')+'_dichotomy.csv', sep=';')
               
#%% DICHOTOMY - GRAPH K

from matplotlib.ticker import FormatStrFormatter

vers = 'v2'

types_obs = ['rivers_wetlands_topografia_pt']
fields_obs = ['fid']
hydro_path = data_path + 'Contraix/Hidrologia_contriax/'
       
BV.calibration_folder = os.path.join(out_path, watershed_name, 'results_calibration')
df = pd.read_csv(BV.calibration_folder+'/'+vers+'_'+str('models')+'_dichotomy.csv', sep=';')

dfp = df.copy()

df['Doptim'] = ((df['Obs']+df['Sim'])/2)

colors = {}

fig, ax = plt.subplots(1,1, figsize=(5,4
                                     ))

for type_obs, field_obs in zip(types_obs[:], fields_obs[:]):

    dfp = df[df['type_obs']==type_obs]
    
    df_p = dfp.sort_values('Obs')
    ax.plot(df_p['K']/24/3600, df_p['Obs'], c='grey', marker='o', ms=5, lw=1, label='Dos')
    df_p = dfp.sort_values('Sim')
    ax.plot(df_p['K']/24/3600, df_p['Sim'], c='k', marker='o', ms=5, lw=1, label='Dso')

    print(dfp.iloc[-1]['KR'], dfp.iloc[-1]['K']/24/3600)
    
    ax.set_xscale('log')
    # ax.set_yscale('log')
    ax.set_xlabel('K [m/s]')
    ax.set_ylabel('Distances [-]')
    # ax.set_xlim(1e-6, 1e-4)
    # ax.set_ylim(0, 200)
    ax.xaxis.set_minor_formatter(FormatStrFormatter("%.2e"))
    ax.legend()
"""
#%% ---- EXPLORATION

#%% UPDATE

iD_explo = 'e2' # with isba recharge ==> change ss with decay factor (details for bad models)
# iD_explo = 'o1'

box = True # or False
sink_fill = False # or True
sim_state = 'steady' # 'steady' or 'transient'
plot_cross = True
# nlay = 5
nlay = 5
lay_decay = 1.2 # 1 for no decay
verti_cond = None # or [ [1e-5, [0, 20]],
verti_poro = None # or [ [1e-5, [0, 20]],
cond_drain = None # or value of conductance
porosity = 1 / 100 # -
poro_decay = 0 # exponential decay : 1/20 (half decrease at 20m)
bc_left = None # or value
bc_right = None # or value
sea_level = 'None' # or value based on specific data : BV.oceanic.MSL
# zone_partic = 'domain' # or watershed
# zone_partic = 'watershed'
cond_decay_val = 0
bottom_val = None
thick = 50 # if bottom is None, aquifer thickness
first_clim = 'mean'
split_temp = False

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
BV.settings.update_simulation_state(sim_state)
BV.hydraulic.update_cond_decay(cond_decay_val) # 0
BV.hydraulic.update_bottom(bottom_val) # None
BV.hydraulic.update_poro_decay(poro_decay)
BV.hydraulic.update_ss_decay(poro_decay) 
BV.hydraulic.update_thick(thick) # 30 / intervient pas si bottom != None
Ss_formula = 1000*9.8*(1e-10+(porosity*4.4e-10)) # rho*g*(alpha+nBeta)
BV.hydraulic.update_ss(Ss_formula)
BV.climatic.update_first_clim(first_clim)

BV.settings.update_split_temporal(split_temp)

recharge = 1200 / 1000 / 365
BV.climatic.update_recharge(recharge, sim_state=sim_state)
BV.climatic.update_runoff(recharge*0.1, sim_state=sim_state)

# KR = np.array([10,100,1000,10000])
# KR = np.array([1000])
# Ks = KR*recharge
# Ks = [4.1e-06 * 24 * 3600]
Ks = [1e-07 * 24 * 3600]

#%% MODFLOW

run_model = True
    
for id_mod_val, K in enumerate(Ks[:]):  
    
    BV.hydraulic.update_hyd_cond(K)

    dictio = {}
    
    list_model_name = []
    list_model_success = []
    list_model_modflow = []
        
    model_name = iD_explo+'_'+str('model')+'_'+str(id_mod_val)+'_'+\
                 str(round(K,4))+'_'+str(round(K/recharge,4))
    
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
    h5file = BV.simulations_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)
    dd.io.save(h5file, dictio)
    
for id_mod_val in range(len(Ks[:])):

    h5file = BV.simulations_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)
    d = dd.io.load(h5file)
    list_model_name = d['list_model_name'][:]
    list_model_success = d['list_model_success'][:]
    list_model_modflow = d['list_model_modflow'][:]
    
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
                                  persistency_index = False,
                                  intermittency_monthly = False,
                                  intermittency_weekly = False,
                                  intermittency_daily = False,
                                  export_all_tif = False)

#%% MODPATH

from src.modeling import downslope, modflow, modpath, timeseries

for id_mod_val in range(len(Ks[:])):

    h5file = BV.simulations_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)
    d = dd.io.load(h5file)
    list_model_name = d['list_model_name'][:]
    list_model_success = d['list_model_success'][:]
    list_model_modflow = d['list_model_modflow'][:]

    for model_name, model_success, model_modflow in zip(list_model_name[:],
                                                        list_model_success[:],
                                                        list_model_modflow[:]):

        tif_file = BV.simulations_folder + '/' + model_name + '/_postprocess/_rasters/seepage_areas_t(0).tif'
        tif_file_clip = BV.simulations_folder + '/' + model_name + '/_postprocess/_rasters/seepage_areas_t(0)_clip.tif'
        
        wbt.verbose = False
        wbt.clip_raster_to_polygon(
            tif_file, 
            BV.stable_folder + '/geographic/watershed.shp', 
            tif_file_clip, 
            maintain_dimensions=True)
        
        x = imageio.imread(tif_file_clip)
        
        # zone_partic = 'custom' # domain or watershed or path
        # tracking_dir = 'backward' # backward or forward
        BV.settings.update_input_particles(
                                            # zone_partic = BV.geographic.watershed_box_buff_dem,
                                            zone_partic = tif_file_clip,
                                            cell_div = 1, # 1
                                            zloc_div = False,  # or False, add cells at cell bottom
                                            bore_depth = None, # '[0,5,10] for 3 particles
                                            track_dir = 'backward',
                                            # track_dir = 'forward', # backward
                                            sel_random = None, # or int
                                            sel_slice = None, # or int
                                            )
        
        for id_mod_val in range(len(Ks[:])):
        
            h5file = BV.simulations_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)
            d = dd.io.load(h5file)
            list_model_name = d['list_model_name'][:]
            list_model_success = d['list_model_success'][:]
            list_model_modflow = d['list_model_modflow'][:]
            
            for model_name, model_success, model_modflow in zip(list_model_name[:],
                                                                list_model_success[:],
                                                                list_model_modflow[:]):
        
                print(model_modflow.mf.model_ws)
                print(model_name)
        
                model_modpath = BV.preprocessing_modpath(model_modflow)
                success_modpath = BV.processing_modpath(model_modpath, write_model=True, run_model=True)
        
        # MODPATH PP
        
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
                
                timeseries_results = BV.postprocessing_timeseries(model_modflow=model_modflow,
                                                                  model_modpath=model_modpath,
                                                                  actual_date=True, 
                                                                  subbasin_results=True,
                                                                  freq_time='D') # or None

        # x = gpd.read_file(BV.simulations_folder + '/' + model_name + '/_postprocess/_particles/pathlines.shp')
        # y = gpd.read_file(BV.simulations_folder + '/' + model_name + '/_postprocess/_particles/ending.shp')
        # x.plot()
        # y.plot()
        # z = model_modpath.point_data

#%% RTD

from scipy.optimize import curve_fit
end = gpd.read_file(BV.geographic.simulations_folder+'/'+model_name+'/'+'_postprocess/_particles/'+'starting_weighted.shp')
shp = gpd.read_file(BV.geographic.watershed_shp)
# end = end.clip(shp)
end[end['time_win_y']==0] = np.nan
end = end.dropna()                
tau = np.average(end['time_win_y'], weights=end['rchPerc'])
def pdf_function(M, nbin, Weight):    
    bin_min = np.quantile(M, 0.01)
    bin_max = np.quantile(M, 0.99)
    bins = np.logspace(np.log10(bin_min),np.log10(bin_max), nbin)
    pdf, binEdges = np.histogram(M, bins=bins,density=True, weights=Weight)
    dx = np.diff(binEdges)  
    xh =  (binEdges[1:] + binEdges[:-1])/2
    xh = np.array(xh)
    return (xh, pdf)
nbin = int(2*len(end['time_win_y'])**(2/5))          #Scott's Rules
[xh, yh] = pdf_function(end['time_win_y']/tau, nbin, end.rchPerc)
idzeros = np.where(yh != 0)
xfil = xh[idzeros]
yfil = yh[idzeros]
x_log = np.log10(xfil)
y_log = np.log10(yfil)
# x_log = (xfil)
# y_log = (yfil)
def func(x, a, b, c, d, e):
    return a * x**4 + b * x**3 + c * x**2 + d * x + e
params, covariance = curve_fit(func, x_log, y_log)
a, b, c, d, e = params
x_fit = np.linspace(min(x_log), max(x_log), 100)
y_fit = func(x_fit, a, b, c, d, e)

fig = plt.figure(figsize=(5,3))
ax = fig.add_subplot(111)
ax.plot(xh, yh, '.', c='r')
ax.plot(xfil, yfil, '-',c = 'r')
ax.plot(10**x_fit, 10**y_fit, '-',c = 'b')
ax.set_ylabel("PDF")
ax.set_xlabel("t / "+r'$\tau$')
ax.set_xscale('log')
# ax.set_xlim(tmin, tmax)
# ax.set_ylim(-0.1, 13)

#%% ---- NOTES


