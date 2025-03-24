# -*- coding: utf-8 -*-
"""
Created on Tue Apr 23 10:04:34 2024

@author: ronan
"""

# -*- coding: utf-8 -*-
"""
Created on Wed Jan 26 10:49:18 2022

@author: ronan ab
"""
import os
#Working directory of Hydromodpy
# dir = 'D:/github/HydroModPy-dev-waterwise/users/figueroa/Waterwise'
# os.chdir(dir)
#%% LIBRARIES MODULES

# General
import sys
from os.path import dirname, abspath
# DIR = dirname(dirname(dirname(abspath(__file__))))
# DIR = "D:/github/hydromodpy-dev-waterwise/users"

import socket
hostname = socket.gethostname()
if hostname in ['CHYN-2208-W']:
    print("Running on Ronny's computer")
    DIR = "D:/github/hydromodpy-dev-waterwise/users" #comment CR: why do we need DIR and DIR2?
    DIR2 = "D:/github/hydromodpy-dev-waterwise" 
    git_path = 'D:/github/hydromodpy-dev0.1/' #I included the data and out paths here
    data_path = "Z:/HDPY_database_forModelling/"
    out_path = 'Z:/HDPY_models/RF'           
    os.makedirs(out_path, exist_ok=True)   
elif hostname in ['CHYN-2115-W']:
    print("Running on Clement's computer")
    DIR = "D:/_GitHub/HydroModPy-dev-waterwise/users"
    DIR2 = "D:/_GitHub/HydroModPy-dev-waterwise"
    data_path = 'Y:\HDPY_database_forModelling/'
    out_path = 'Y:/HDPY_models/CR'
    os.makedirs(out_path, exist_ok=True)
elif hostname in ['Computer Name ORC']:
    print("Running on Odile's computer")
    DIR = "D:/github/hydromodpy-dev-waterwise/users"
    DIR2 = "D:/github/hydromodpy-dev-waterwise"    
    git_path = 'D:/github/hydromodpy-dev0.1/' #I included the data and out paths here
    data_path = "Z:/HDPY_database_forModelling/"
    out_path = 'Z:/HDPY_models/OR'    
else:
    print("Running on HYDRA")
    DIR = "D:/Users/figueroar/Documents/HydroModPy/users"
    DIR2 = "D:/Users/figueroar/Documents/HydroModPy"   

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
from IPython import get_ipython
get_ipython().run_line_magic('matplotlib', 'inline')

# Gis
from rasterio.mask import mask
from shapely.geometry import box
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
# DIR = dirname(dirname(dirname(dirname(abspath(__file__)))))
# DIR = "D:/github/hydromodpy-dev-waterwise"
sys.path.append(DIR2)

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

#Why are these functions here? Are they not in hydromodpy already?

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
    
def clip_raster_to_square(raster_path, output_path, center_coords, side_length):
    x_center, y_center = center_coords
    half_side = side_length / 2

    square = box(
        x_center - half_side,  # Extremo izquierdo
        y_center - half_side,  # Extremo inferior
        x_center + half_side,  # Extremo derecho
        y_center + half_side   # Extremo superior
    )

    with rasterio.open(raster_path) as src:
        geojson_geometry = [square.__geo_interface__]

        out_image, out_transform = mask(src, geojson_geometry, crop=True)

        out_meta = src.meta.copy()
        out_meta.update({
            "driver": "GTiff",
            "height": out_image.shape[1],
            "width": out_image.shape[2],
            "transform": out_transform
        })       
        with rasterio.open(output_path, "w", **out_meta) as dest:
            dest.write(out_image)

#%% ---- CATCHMENT

#%% PATHS
site_file = os.path.join(data_path,'Waterwise_sites.xlsx')
site = pd.read_excel(site_file)

site_num = 2            #indicate number of study site

watershed_name = str(int(site.loc[site_num,'ID'])) + site.loc[site_num,'ID_name']
from_xyv = [site.loc[site_num,'x_LAEA'], site.loc[site_num,'y_LAEA'], 100, 10, 'EPSG:3035'] # [x, y, snap distance, buffer size [%], crs proj]

dem_name = 'dem'+ site.loc[site_num,'ID_name']# 
dem_path = data_path +watershed_name+'/'+ dem_name+'.tif'
    
from_shp = [data_path +watershed_name+'/'+"watershed"+site.loc[site_num,'ID_name']+'.shp', 10]

# from_shp = None
subbasin_path = True # generate subbasins from stations or manual points
from_dem = None # True or False if the process start from a given DEM of xyz file
cell_size = None # specify new resolution from a given DEM or None

# sys.exit(1)
#%% LOAD

load = True         #not re run if it's well loaded
# load = False

print('##### '+ watershed_name.upper()+' #####')
BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=dem_path, 
                              out_path=out_path,
                              load=load,
                              from_shp=from_shp,
                              from_dem=from_dem,
                              from_xyv=from_xyv)

stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots 
       
                  
print('Area: ' + str(BV.geographic.area.round(2)))
print('Slope: ' + str(BV.geographic.slope.round(2)))

try:
    visualization_watershed.watershed_local(dem_path, BV)
    visualization_watershed.watershed_dem(BV)
except:
    pass

# SUBBASIN

# BV.add_intermittency('None','None')
# BV.add_subbasin(data_path+'_coordinates_additional/', sub_snap_dist=50)
# sys.exit(1)

#%% DEFINE

# Frame settings
box = True # or False
sink_fill = False # or True
# sim_state = 'transient' # 'steady' or 'transient'
sim_state = 'steady' # 'steady' or 'transient'
plot_cross = False
check_grid = False
dis_perlen=False

# Climatic settings
# recharge = pd.Series([10,20,30,40,50,60,60,50,40,30,20,10])/30/1000
recharge = 1/365
first_clim = 'mean' # or 'first or value
freq_time = 'M'

# Hydraulic settings
nlay = 1
lay_decay = 1.5 # 1 for nodecay
bottom = None # elevation in meters, None for constant auifer thickness, or 2D matrix
thick = 50 # if bottom is None, aquifer thickness
cond_drain = None # or value of conductance
sy = 1 / 100 # -

K_R = site.loc[site_num,'K/R_cal']
########## LOOP ##########
list_hyd_cond = np.array([K_R*recharge ]) # m/day
# list_hyd_cond = np.geomspace(4e-1,4e0,5)

# Boundary settings
bc_left = None # or value
bc_right = None # or value
sea_level = 'None' # or value based on specific data : BV.oceanic.MSL

# Particle tracking settings
zone_partic = 'domain' # or watershed

#%% UPDATE

# Import modules
BV.add_settings()
BV.add_climatic()
BV.add_hydraulic()

# Frame settings
BV.settings.update_box_model(box)
BV.settings.update_sink_fill(sink_fill)
BV.settings.update_simulation_state(sim_state)
BV.settings.update_check_model(plot_cross=plot_cross, check_grid=check_grid)

# Climatic settings
BV.climatic.update_recharge(recharge, sim_state=sim_state)
BV.climatic.update_first_clim(first_clim)

# Hydraulic settings
BV.hydraulic.update_nlay(nlay) # 1
BV.hydraulic.update_bottom(bottom) # None
BV.hydraulic.update_thick(thick) # 30 / intervient pas si bottom != None
BV.hydraulic.update_sy(sy)
BV.hydraulic.update_cond_drain(cond_drain)
BV.hydraulic.update_lay_decay(lay_decay)

# Boundary settings
BV.settings.update_bc_sides(bc_left, bc_right)
BV.add_oceanic(sea_level)
BV.settings.update_dis_perlen(dis_perlen=dis_perlen)

# Particle tracking settings
BV.settings.update_input_particles(zone_partic=BV.geographic.watershed_box_buff_dem) # or 'seepage_path'

#%% MODFLOW

iD_set_simulations = 'E2'

list_model_name = []
list_success_modflow = []
list_model_modflow = []

for hyd_cond in list_hyd_cond:
    BV.hydraulic.update_hk(hyd_cond)
    model_name = iD_set_simulations+'_'+str(round(hyd_cond,3))
    BV.settings.update_model_name(model_name)
    print(model_name)
    
    model_modflow = BV.preprocessing_modflow(for_calib=False)
    success_modflow = BV.processing_modflow(model_modflow, write_model=True, run_model=True)
    
    list_model_name.append(model_name)
    list_success_modflow.append(success_modflow)
    list_model_modflow.append(model_modflow)

dictio = {}
dictio['list_model_name'] = list_model_name
dictio['list_success_modflow'] = list_success_modflow
dictio['list_model_modflow'] = list_model_modflow
h5file = os.path.join(simulations_folder,'results_listing_'+iD_set_simulations)
    
dd.io.save(h5file, dictio)
    
#%% RELOAD

h5file = os.path.join(simulations_folder,'results_listing_'+iD_set_simulations)
d = dd.io.load(h5file)
list_model_name = d['list_model_name'][:]
list_success_modflow = d['list_success_modflow'][:]
list_model_modflow = d['list_model_modflow'][:]

#%% POSTPROCESSING

for model_name, success_modflow, model_modflow in zip(list_model_name,
                                                      list_success_modflow,
                                                      list_model_modflow):
    if success_modflow == True:
        BV.postprocessing_modflow(model_modflow,
                                  watertable_elevation = True,
                                  watertable_depth= True, 
                                  seepage_areas = True,
                                  outflow_drain = True,
                                  groundwater_flux = True,
                                  groundwater_storage = True,
                                  accumulation_flux = True,
                                  persistency_index=False,
                                  intermittency_monthly=False,
                                  intermittency_daily=False,
                                  export_all_tif = False)

        timeseries_results = BV.postprocessing_timeseries(model_modflow=model_modflow,
                                                          model_modpath=None,
                                                          datetime_format=False, 
                                                          subbasin_results=True) # or None
        
        netcdf_results = BV.postprocessing_netcdf(model_modflow,
                                                  datetime_format=False)

#%% ---- PLOT

#%% CROSS

compt = 1

for model_name, success_modflow, model_modflow in zip(list_model_name,
                                                      list_success_modflow,
                                                      list_model_modflow):

    
    fig, ax = plt.subplots(1, 1, figsize=(5,3), dpi=300)

    stable_folder = os.path.join(out_path, watershed_name, 'results_stable') # necessary for plots
    simulations_folder = os.path.join(out_path, watershed_name, 'results_simulations')

    dem_data = imageio.imread(BV.geographic.watershed_dem)
    dem_data = np.ma.masked_where(dem_data < 0, dem_data)
    
    wt_data = imageio.imread(os.path.join(simulations_folder, model_name, 
                                          r'_postprocess/_rasters/watertable_elevation_t(0).tif'))
    wt_data = np.ma.masked_where(wt_data < 0, wt_data)
    
    # river_data = imageio.imread(os.path.join(stable_folder, 'hydrography', 
    #                                          'regional stream network.tif'))

    xvalues = np.linspace(-1,1,dem_data.shape[1])
    yvalues = np.linspace(-1,1,dem_data.shape[0])
    xx, yy = np.meshgrid(xvalues,yvalues)
    
    cur_x = dem_data.shape[1] /2
    # cur_y = dem_data.shape[0] /2
    
    dem_prof = dem_data.astype(float)
    dem_prof[dem_prof<0] = np.nan
    dem_v_plot = dem_prof[:,int(cur_x)]
    dem_v_plot[dem_v_plot == 0] = np.nan

    wt_prof = wt_data.astype(float)
    wt_prof[wt_prof<0] = np.nan
    wt_v_plot = wt_prof[:,int(cur_x)]
    wt_v_plot[wt_v_plot == 0] = np.nan

    # wt_prof_min = wt_data.astype(float)
    # wt_prof_min[wt_prof_min<0] = np.nan
    # wt_v_plot_min = wt_prof_min[:,int(cur_x)]
    # wt_v_plot_min[wt_v_plot_min == 0] = np.nan
    
    # Facecolor watertable
    wt_v_fill = ax.fill_between(np.arange(xx.shape[0])*75,
                                dem_v_plot-30, wt_v_plot,
                                color='dodgerblue', alpha=0.5, lw=0)
    # Line watertable
    w_prof = ax.plot(np.arange(xx.shape[0])*75, wt_v_plot, color='navy', lw=1)
    
    # Facecolor unsaturated
    wt_v_fill = ax.fill_between(np.arange(xx.shape[0])*75, 
                                wt_v_plot, dem_v_plot,
                                color='saddlebrown', alpha=0.5, lw=0)
    
    # Line unsaturated
    d_prof = ax.plot(np.arange(xx.shape[0])*75, dem_v_plot, 'saddlebrown', lw=1.5)
    
    # Facecolor noflow
    ax.fill_between(np.arange(xx.shape[0])*75,
                    0, dem_v_plot-30,
                    color='lightgrey', alpha=1, lw=0, zorder=10)
    # Line noflow
    ax.plot(np.arange(xx.shape[0])*75, dem_v_plot-30, color='dimgray', lw=1.5)
    
    # Settings
    # ax.set_xlim(1000, 4000)
    ax.set_ylim(2000, 3000)
    # ax.set_yticks([90,100,110,120,130])
    ax.set_xlabel('Distance [m]')
    ax.set_ylabel('Elevation [m]')
    ax.set_title('K = '+'{:.2e}'.format(model_modflow.hk.mean()/24/3600)+' m/s')
    
    compt += 1
    
    # fig.tight_layout
    
    # fig.savefig(os.path.join(model_modflow.figure_file,
    #             'CROSS_'+model_name+'_'+str(compt)+'.png'),
    #             bbox_inches='tight')
        
    # fig.savefig(os.path.join(model_modflow.save_fig,
    #             'CROSS_'+model_name+'_'+str(compt)+'.png'),
    #             bbox_inches='tight')

 
#%% MAP
import rasterio
from rasterio.plot import show
import geopandas as gpd
from rasterio.features import geometry_mask
compt = 0
stream_obs=gpd.read_file(data_path + watershed_name + "/stream_network" + site.loc[site_num,'ID_name'] + '.shp')

   
stable_folder = os.path.join(out_path, watershed_name, 'results_stable') # necessary for plots
simulations_folder = os.path.join(out_path, watershed_name, 'results_simulations')

lin0 = os.path.join(stable_folder, 'geographic', 'watershed_contour.tif')
mask0 = os.path.join(stable_folder, 'geographic', 'watershed_dem.tif')
WC0 = os.path.join(stable_folder, 'geographic', 'watershed.shp')

WC_shp = gpd.read_file(WC0)
stream_obs_clip = gpd.clip(stream_obs, WC_shp)

with rasterio.open(mask0) as src:
    # Leer el raster y obtener las coordenadas
    data = src.read(1)  # Leer la primera banda
    bounds = src.bounds  # Coordenadas de los bordes
    transform = src.transform  # Transformación para georreferenciar
    extent2 = (bounds.left, bounds.right, bounds.bottom, bounds.top)

with rasterio.open(lin0) as src:
    # Leer el raster y obtener las coordenadas
    data = src.read(1)  # Leer la primera banda
    bounds = src.bounds  # Coordenadas de los bordes
    transform = src.transform  # Transformación para georreferenciar
    extent1 = (bounds.left, bounds.right, bounds.bottom, bounds.top)

line = imageio.imread(os.path.join(stable_folder, 'geographic', 'watershed_contour.tif'))
line = np.ma.masked_where(line <= 0, line)

mask = imageio.imread(os.path.join(stable_folder, 'geographic', 'watershed_dem.tif'))
for model_name, success_modflow, model_modflow in zip(list_model_name,
                                                      list_success_modflow,
                                                      list_model_modflow):

    fig, ax = plt.subplots(1, 1, figsize=(5,3), dpi=300)

    stable_folder = os.path.join(out_path, watershed_name, 'results_stable') # necessary for plots
    simulations_folder = os.path.join(out_path, watershed_name, 'results_simulations')
    
    stream_obs_clip.plot(ax=ax, edgecolor="cyan",linewidth=0.5)
    # ax.set_title(str(year)[0:10] + '   ' + '$A_{sat}$ = ' + str(val.round(1)) + ' [%]',
    #              pad=10, fontsize=10)
    ax.imshow(np.ma.masked_where(mask<0, mask), cmap='Greys', alpha=0.5, zorder=0, extent=extent2)

    # dem_data = imageio.imread(BV.geographic.watershed_box_buff_dem)
    # dem_data = np.ma.masked_where(dem_data < 0, dem_data)
    
    # contour = imageio.imread(BV.geographic.watershed_contour_tif)
    # contour = np.ma.masked_where(contour < 0, contour)
    
    # obs_river_data = imageio.imread(os.path.join(stable_folder, 'hydrography',
    #                                              'regional stream network.tif'))
    # obs_river_data = np.ma.masked_where(obs_river_data < 0, obs_river_data)
    
    seep_river_data = imageio.imread(os.path.join(simulations_folder, model_name,
                                                  r'_postprocess/_rasters/seepage_areas_t(0).tif'))
    seep_river_data = np.ma.masked_where((seep_river_data <= 0) | (mask <0), seep_river_data)
    # seep_river_data = rasterio.mask(seep_river_data, WC0)
    
    
    sim_river_data = imageio.imread(os.path.join(simulations_folder, model_name,
                                                 r'_postprocess/_rasters/accumulation_flux_t(0).tif'))
    sim_river_data = np.ma.masked_where((sim_river_data <= 0) | (mask <0), sim_river_data)
    
    
    # im_dem = ax.imshow(dem_data, alpha=0.5, cmap='Greys')
    # im_cont = ax.imshow(contour, alpha=1, cmap=mpl.colors.ListedColormap('k'))
    # im_obs = ax.imshow(obs_river_data, alpha=1, cmap=mpl.colors.ListedColormap('navy'))
    im_sim = ax.imshow(sim_river_data, cmap=mpl.colors.ListedColormap('red'), alpha=0.7, extent=extent2)
    im_seep = ax.imshow(seep_river_data, cmap=mpl.colors.ListedColormap('darkorange'), alpha=0.7, extent=extent2)

    # ax.set_xlabel('X [pixels]')
    # ax.set_ylabel('Y [pixels]')
    # ax.set_title('K = '+'{:.2e}'.format(model_modflow.hk.mean()/24/3600)+' m/s')
    ax.set_title('K = '+'{:.1e}'.format(model_modflow.hk.mean())+' m/d')
    ax.imshow(line, cmap=mpl.colors.ListedColormap('k'), extent=extent1)
    plt.axis('off')
    compt += 1
    
    fig.tight_layout()

    # fig.savefig(os.path.join(model_modflow.figure_file,
    #             'MAP_'+model_name+'_'+str(compt)+'.png'),
    #             bbox_inches='tight')
    
    # fig.savefig(os.path.join(model_modflow.save_fig,
    #             'MAP_'+model_name+'_'+str(compt)+'.png'),
    #             bbox_inches='tight')
    
#%% GRAPH

fig, ax = plt.subplots(1, 1, figsize=(5,4), dpi=300)

for model_name, success_modflow, model_modflow in zip(list_model_name,
                                                      list_success_modflow,
                                                      list_model_modflow):
    
    simulations_folder = os.path.join(out_path, watershed_name, 
                                      'results_simulations')
    
    simul_csv = pd.read_csv(os.path.join(simulations_folder, model_name,
                            r'_postprocess/_timeseries/', '_simulated_timeseries.csv'),
                            sep=';')
    

    ax.plot(model_modflow.hk.mean()/24/3600,
            simul_csv['seepage_areas'],
            marker='o', ms=8, lw=0, color='k')
    
    ax.set_xscale('log')
    ax.set_xlabel('K [m/s]')
    ax.set_ylabel('Drainage density [%]')
    
    # fig.tight_layout()
    
    # fig.savefig(os.path.join(model_modflow.save_fig,
    #             'GRAPH_sat_'+iD_set_simulations+'.png'),
    #             bbox_inches='tight')

#%% ---- NOTES

os.chdir(DIR)

