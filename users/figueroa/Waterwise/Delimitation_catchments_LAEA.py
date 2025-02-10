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


site = pd.read_excel('D:/Dropbox/1_CHYN_Neuchatel/2WATERWISE/Study_sites/Waterwise_sites.xlsx')
git_path = 'D:/github/hydromodpy-dev0.1/'
data_path = "D:/Hydromodpy/Waterwise_test/"



out_path = 'D:/Hydromodpy/Waterwise3/'           # no volver a poner nombre de catchments


site_num = 5            #indicate number of study site

watershed_name = str(site.loc[site_num,'ID']) + site.loc[site_num,'ID_name']
from_xyv = [site.loc[site_num,'x_LAEA'], site.loc[site_num,'y_LAEA'], 100, 10, 'EPSG:3035'] # [x, y, snap distance, buffer size [%], crs proj]

dem_name = 'dem'+ site.loc[site_num,'ID_name']# 
dem_path = data_path + dem_name+'.tif'
    



if site.loc[site_num,'shp2'] =='Si':    
    from_shp = [data_path+site.loc[site_num,'ID_name']+"_watershed.shp", 10]
else:
    from_shp = None


    





# from_shp = None
subbasin_path = True # generate subbasins from stations or manual points
from_dem = None # True or False if the process start from a given DEM of xyz file
cell_size = None # specify new resolution from a given DEM or None


#%% LOAD

load = True         #not re run if it's well loaded
# load = False

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
# try:
#     BV = watershed_root.Watershed(watershed_name=watershed_name,
#                                   dem_path=dem_path, 
#                                   out_path=out_path,
#                                   load=load,
#                                   from_shp=from_shp,
#                                   from_dem=from_dem,
#                                   from_xyv=from_xyv)

#     stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
#     simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots 
# except:
#     # if __name__ == "__main__":
#     #     # raster_path = dem_path  
#     #     dem_clipped = out_path+watershed_name+'/'+site.loc[site_num,'ID_name']+"_clipped.tif"      # Ruta del raster recortado
#     #     center_coords = (from_xyv[0], from_xyv[1])       # Coordenadas del punto central (en CRS del raster)
#     #     side_length = 40000                         # Distancia del buffer (en las unidades del CRS)

#     #     clip_raster_to_square(dem_path, dem_clipped, center_coords, side_length)
#     BV = watershed_root.Watershed(watershed_name=watershed_name,
#                                   dem_path=dem_path, 
#                                   out_path=out_path,
#                                   load=load,
#                                   from_shp=from_shp,
#                                   from_dem=from_dem,
#                                   from_xyv=from_xyv)

#     stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
#     simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
        
        
         
  
print(BV.geographic.area.round(2))
print(BV.geographic.slope.round(2))

# try:
#     visualization_watershed.watershed_local(dem_path, BV)
#     visualization_watershed.watershed_dem(BV)
# except:
#     pass

# SUBBASIN

# BV.add_intermittency('None','None')
# BV.add_subbasin(data_path+'_coordinates_additional/', sub_snap_dist=50)
sys.exit(1)
#%% DATA

types_obs = ['stream_network_merge', 'stream_network_perenial']
fields_obs = ['fid', 'fid']
               
BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=dem_path, 
                              out_path=out_path,
                              load=True)

for type_obs, field_obs in zip(types_obs, fields_obs):

    BV.add_hydrography(data_path, types_obs=[type_obs], fields_obs=[field_obs])
    
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

#%% ---- EXPLORATION

#%% UPDATE

iD_explo = 'e1' # with isba recharge ==> change ss with decay factor (details for bad models)
iD_explo = 'he1'

box = True # or False if zou model 
sink_fill = False # or True
sim_state = 'steady' # 'steady' or 'transient'
plot_cross = True
# nlay = 5
nlay = 10
lay_decay = 1.5 # 1 for no decay . 1.5 increase siye layer
verti_cond = None # or [ [1e-5, [0, 20~], K value for diffretn depth
verti_poro = None # or [ [1e-5, [0, 20]],
cond_drain = None # or value of conductance
porosity = 1 / 100 # -
poro_decay = 1/60 # exponential decay : 1/100 - 1/40 (half decrease at 20m)
bc_left = None # or value
bc_right = None # or value
sea_level = 'None' # or value based on specific data : BV.oceanic.MSL
# zone_partic = 'domain' # or watershed
# zone_partic = 'watershed'
cond_decay_val = 1/30 # exponential decay : 1/50 - 1/20 range (half decrease at 20m)
bottom_val = 500 # altitude where the aquifer bottom is flat
thick = None # if bottom is None, aquifer thickness
first_clim = 'mean' # put a float if zou want or 'first'

BV = watershed_root.Watershed(watershed_name=watershed_name, dem_path=dem_path, out_path=out_path, load=True)
area = BV.geographic.area

stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' # necessary for plots
BV.calibration_folder = out_path+'/'+watershed_name+'/'+'results_calibration/'

# https://www.whiteboxgeo.com/manual/wbt_book/tool_index.html
# VectorLinesToRaster: Converts a vector containing polylines into a raster. Found in Data Tools.
# VectorPointsToRaster: Converts a vector containing points into a raster. Found in Data Tools.
# VectorPolygonsToRaster: Converts a vector containing polygons into a raster. Found in Data Tools.

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
# BV.settings.update_input_particules(zone_partic=zone_partic)
BV.settings.update_simulation_state(sim_state)
BV.settings.update_split_temporal(False)
BV.hydraulic.update_cond_decay(cond_decay_val) # 0
BV.hydraulic.update_bottom(bottom_val) # None
BV.hydraulic.update_poro_decay(poro_decay)
BV.hydraulic.update_ss_decay(poro_decay) 
BV.hydraulic.update_thick(thick) # 30 / intervient pas si bottom != None
Ss_formula = 1000*9.8*(1e-10+(porosity*4.4e-10)) # rho*g*(alpha+nBeta)
BV.hydraulic.update_ss(Ss_formula)
BV.climatic.update_first_clim(first_clim)

recharge = 1 / 365  # recharge en m/d ex. 1/365 the recharge is 1 m in one year
BV.climatic.update_recharge(recharge, sim_state=sim_state)
BV.climatic.update_runoff(recharge*0.1, sim_state=sim_state)

KR = np.array([90])
# KR = np.array([75])
Ks = KR*recharge # array([3.1709792e-05])

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
    
#%% MODFLOW PP

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
        
        ### PROBLEMS
        # tif_file = BV.simulations_folder + '/results_stable/geographic/watershed_box_buff_fil.tif'
        # shp_transform_tif = 'D:/Dropbox/1_CHYN_Neuchatel/1PhD_Project/Poschiavo_HMP_model/GIS/shapes/stream_network_perenial.tif'
        # wbt.vector_lines_to_raster(
        #     'D:/Dropbox/1_CHYN_Neuchatel/1PhD_Project/Poschiavo_HMP_model/GIS/shapes/stream_network_perenial.shp', 
        #     shp_transform_tif, 
        #     field="FID", 
        #     nodata=True, 
        #     cell_size=None, 
        #     base=BV.geographic.watershed_box_buff_dem)
        ### PROBLEMS
        
        tif_file = BV.simulations_folder + '/' + model_name + '/_postprocess/_rasters/seepage_areas_t(0).tif'
        tif_file_clip = BV.simulations_folder + '/' + model_name + '/_postprocess/_rasters/seepage_areas_t(0)_clip.tif'
        wbt.clip_raster_to_polygon(
            tif_file, 
            BV.stable_folder + '/geographic/watershed.shp', 
            tif_file_clip, 
            maintain_dimensions=True)
        
        BV.settings.update_input_particles(
                                            # zone_partic = BV.geographic.watershed_box_buff_dem,
                                            # zone_partic = tif_file,
                                            # zone_partic = shp_transform_tif,
                                            zone_partic = tif_file_clip,
                                            # zone_partic = tif_bore,  # indicate where to inject particles, seepage, borehole or entire catchment
                                            cell_div = 3, # 1, distribution of partciles by cell in x and y direction
                                            zloc_div = False,  # False or True, inject partciles in z direction. Same number as cell_div
                                            bore_depth = None, # None or True, None 1 particle in the first layer, If True it will inject 1 particle in every layer.
                                            track_dir = 'backward', # backward or forward 
                                            # track_dir = 'forward', # backward
                                            sel_random = None, # or int
                                            sel_slice = None, # or int
                                            )

        model_modpath = BV.preprocessing_modpath(model_modflow)
        success_modpath = BV.processing_modpath(model_modpath, write_model=True, run_model=True)

        BV.postprocessing_modpath(model_modpath,
                                  ending_point=True,
                                  starting_point=True,
                                  pathlines_shp=True,
                                  particles_shp=False,
                                  random_id=None) # None
        
        BV.filtprocessing_modpath(model_modpath,
                                  norm_flux=True, # for forward only
                                  filt_time=True, # delete particles with time at 0, add a column with time divided by 365 (considering recharge in days)
                                  filt_seep=True, # only forward, keep only particles finishing in zone1 (seepage), keep only particles finishing in k1 (first layer)
                                  filt_inout=True, # delete particles in and out in the same cell (first layer)
                                  calc_rtd=True, # compute residence time distribution
                                  random_id=None, # select randomly to keep
                                  ) # None

