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
# import seaborn as sns
from pyproj import Transformer
from mpl_toolkits.axes_grid1 import make_axes_locatable
from matplotlib.colors import Normalize
from matplotlib import cm
import matplotlib as mpl
import rasterio
import fnmatch
import deepdish as dd
import matplotlib.dates as mdates
import seaborn as sns
import flopy
import pickle
import random

# Plot
from matplotlib_scalebar.scalebar import ScaleBar
from rasterio.plot import show
from matplotlib.colors import LightSource
import earthpy.spatial as es
import earthpy.plot as ep

# Gis
import imageio
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = True

# Warnings
import warnings
warnings.filterwarnings("ignore", message=".*An exception was ignored while fetching the attribute.*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*`np.object` is a deprecated alias for the builtin `object`.*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*is deprecated. Use tobytes().*", category=DeprecationWarning)
warnings.filterwarnings("ignore")
# warnings.warn("You won't see this warning")
               
#%HYDROMODPY MODULES
                    
from watershed import watershed_root, watershed_display, forcing
from watershed.data import climatic
from tools import toolbox, vtk
from groundwater_flow import visualization, modflow_display
from calibration import calib_root

# LAYOUT PLOT

fontprop = toolbox.plot_params(8,15,18,20) # small, medium, interm, large

#%% CLASS FUNCTIONS

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
# sklearn_linregress(hyst.xw.values.reshape(len(hyst.xw),1),
#                     hyst.yw.values)
    
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

#%% ---- CATCH

#%% PATH WATERSHED

git_path = "D:/Users/abherve/GITHUB/HydroModPy/CORE_COMM/"
# Path to the data folder
data_path = "D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/4_model/POSCHIAVINO/_data/"
# Path where the results will be stored
out_path = "D:/Users/abherve/POSCHIAVINO/"
# Figure folder outputs
res_path = 'D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/4_model/POSCHIAVINO/_outputs/'

dems_path = data_path # reginal DEM or conceptual DEM
modflow_path = 'D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/HYDRODATAPY/HydroDataPy/SOFTWARE/MODFLOW/' # add bin/ folder with necessary .exe

hydrology_path = data_path # add hydrographic shapefiles



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

### 1
# watershed_names = ['Poschiavino']
# dem_name = "copernicus_eu_dem_v11_E40_N20_clip_poschiavo_all2.tif" # name of dem
# subbasin_path = True # generate subbasins from stations or manual points
# from_dem = False # True or False if the process start from a given DEM of xyz file
# cell_size = None # specify new resolution from a given DEM or None
# path_points = data_path + 'poschiavino_outlet.shp'
# points = gpd.read_file(path_points)
# x = points.loc[0,'X']
# y = points.loc[0,'Y']
# from_xy = [x,y,500,25]
# from_shp = None # specify a path if process start from a given shapefile

### ==> (5/2)**2 = 5 ==> 6 times faster

### 2
# watershed_names = ['Upstream10']
# # watershed_names = ['Pathlines10']
# dem_name = 'DEM_10m.tif' # 'DEM_Poschiavino.tif'
# subbasin_path = True # generate subbasins from stations or manual points
# from_shp = None # specify a path if process start from a given shapefile
# from_dem = True # True or False if the process start from a given DEM of xyz file
# cell_size = None # specify new resolution from a given DEM or None
# # x = 1242256.298
# # y = 6613054.622
# from_xy = []

### 3
# watershed_names = ['Ownoutlet10m']
# dem_name = 'DEM_10m.tif' # 'DEM_Poschiavino.tif'
# subbasin_path = True # generate subbasins from stations or manual points
# from_shp = None # specify a path if process start from a given shapefile
# from_dem = False # True or False if the process start from a given DEM of xyz file
# cell_size = None # specify new resolution from a given DEM or None
# x = 802122.384
# y = 141971.022
# from_xy = [x,y,25,10]
# from_shp = None

### 4
watershed_names = ['Ownoutlet10m_v4']
dem_name = 'DEM_10m.tif' # 'DEM_Poschiavino.tif'
subbasin_path = True # generate subbasins from stations or manual points
from_dem = False # True or False if the process start from a given DEM of xyz file
cell_size = None # specify new resolution from a given DEM or None
from_xy = []
from_shp = data_path + 'Catchment_Poschiavino_transf.shp' # specify a path if process start from a given shapefile


# Depending on the choices
dem_path = dems_path + dem_name
library_path = data_path + 'watershed_library.csv' # each row is a study site with outlet coordinates

dem_data = imageio.imread(dem_path)
# dem_data = imageio.imread('D:/Users/abherve/PAPER/Nancon/results_stable/geographic/watershed_buff_dem.tif')

# types_obs = ['perennial','perennial_intermittent'] # list of shapefile name layers for clip hydrology
# fields_obs = ['fid','fid']

types_obs = ['poschiavino_streamnetwork_transf_main','poschiavino_streamnetwork_transf']
fields_obs = ['fid','fid']

#%% GENERATE WATERSHED

load = True

for watershed_name in watershed_names[:]:
        
    print('##### '+watershed_name.upper()+' #####')
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  modflow_path=modflow_path,
                                  library_path=library_path,
                                  load=load,
                                  from_shp=from_shp,
                                  from_dem=from_dem,
                                  from_xy=from_xy,
                                  cell_size=cell_size)
    
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots  
  
    try:
        print(BV.geographic.area.round(2))
        print(BV.geographic.slope.round(2))
    except:
        pass
            
#%% DATA WATERSHED

for watershed_name in watershed_names[:]:
    
    print('##### '+watershed_name.upper()+' #####')
               
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True)

    BV.add_hydrology(hydrology_path, types_obs=types_obs, fields_obs=fields_obs)


    BV.add_hydrodynamic()
    BV.add_forcing()
    
    try:
        watershed_display.watershed_dem(BV)
        watershed_display.watershed_local(dem_path, BV)
    except:
        pass
    
    # import imageio
    # import whitebox
    # wbt = whitebox.WhiteboxTools()
    # wbt.verbose = True
    
    # wbt.find_main_stem(
    #     stable_folder+'geographic/'+'watershed_buff_direc.tif', 
    #     BV.hydrology.tif_streams, 
    #     stable_folder+'hydrology/'+types_obs[0]+'_main'+'.tif', 
    #     esri_pntr=False, 
    #     zero_background=False)
        
#%% ---- CALIB

#%% DICHOTOMY STREAMS
"""
hydrology_path = data_path # add hydrographic shapefiles

from calibration import calib_root, calib_dichotomy, calib_analysis, calib_exploration, calib_basis

for watershed_name in watershed_names[:] :
        
    df = pd.DataFrame(np.nan, index=range(1), columns=types_obs)
    
    for type_obs, field_obs in zip(types_obs, fields_obs):
   
        print('##### '+watershed_name.upper()+' #####')
        
        BV = watershed_root.Watershed(watershed_name=watershed_name,
                                      dem_path=dem_path, 
                                      out_path=out_path,
                                      load=True,
                                      modflow_path=modflow_path)
        BV.add_forcing()
        BV.add_hydrodynamic()
        BV.add_oceanic('none')
        
        BV.add_hydrology(hydrology_path, types_obs=[type_obs], fields_obs=[field_obs])
        
        # watershed_display.watershed_dem(BV)
        # watershed_display.watershed_local(dem_path, BV)

        area = BV.geographic.area
        
        stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
            
        recharge = 2 / 365  # m/y to m/d
        
        BV.forcing.update_recharge(recharge, sim_state='steady') #

        # BV.hydrodynamic.update_porosity(0.1)
        # BV.hydrodynamic.update_hyd_cond(2)
        BV.hydrodynamic.update_nlay(1)
        BV.hydrodynamic.update_thickness(300)
        BV.hydrodynamic.update_bottom(-100)
        # BV.hydrodynamic.update_bottom(None)
        BV.hydrodynamic.update_cond_decay(0)
        BV.hydrodynamic.update_thick_exp(1)
        
        params_df = pd.DataFrame(columns=['params',
                                          'init_values','lower_bounds','higher_bounds',
                                          'units','scale'])
        params_df.loc[0] = ['k1','?',8.64e-04,8.64e-01,'m/j','lin']
        
        params_file = 'calib_dicot_hom_1v_k1'
        
        params_df.to_csv(BV.calibration_folder+'/'+params_file+'.csv', sep=',', index=None)

        # params_file = 'calib_dicot_het_2v_k1-k2'
        # params_file = 'calib_dicot_hom_2v_k1-n1'
        calib = calib_root.Calibration(params_file, BV, observations = ['streams'])
        
        dicot = calib.dichotomy(gap=1)
        
        typ_calib = 'streams_calibration'
        list_path = sorted(glob.glob(os.path.join(BV.calibration_folder, params_file, typ_calib, '*.calib')),
                           key=os.path.getmtime)
        name_file = list_path[-1].split('\\')[-1]
        calib_file = os.path.join(BV.calibration_folder, params_file, typ_calib, name_file)
        test = calib_analysis.CalibAnalysis(calib_file)
        test.display_objective_function(save=None)
        
        koptim = test.calib['params_values'][-1]
        kr = koptim / test.calib['recharge']
        obj_func = test.calib['objective_function'][-1]
        
        # df.loc[0,watershed_name] = koptim / 24 / 3600
        # df.loc[1,watershed_name] = kr
        # df.loc[2,watershed_name] = obj_func
        
        df.loc[0,type_obs] = koptim / 24 / 3600
        df.loc[1,type_obs] = kr
        df.loc[2,type_obs] = obj_func
        
    df.to_csv(BV.calibration_folder+'/'+watershed_name+'_koptims_dichotomy_streams.csv', sep=';')
    df = pd.read_csv(BV.calibration_folder+'/'+watershed_name+'_koptims_dichotomy_streams.csv', sep=';')
"""
#%% ---- MODEL

#%% CASES TO TYP

# Aquifer
thick = 50 # m
# bottom = 500 # aquifer flat or not
bottom = None

# Discretization
nlay = 1 # vertical discrtization
thick_exp = 1 # exponential decay of nlay with depth

# Porosity
Sy = 0.1

# Hydraulic cond.
K = 1e-6 * 3600 * 24
cond_decay = 0 # exponential decay of K with depth

# Recharge
recharge = 1 / 365

# Typ name
typ = 'constant_50m'

#%% RUN MODEL

sim_state = 'steady' # 'steady' or 'transient'
modpath_sim = True # run modpath particle tracking if True
modpath_sim = False # run modpath particle tracking if True

run = True
    
print('##### '+watershed_name.upper()+' #####')

stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' 
BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=dem_path, 
                              out_path=out_path,
                              load=True,
                              modflow_path=modflow_path)

BV.add_forcing()
BV.add_hydrodynamic()
BV.add_oceanic('None')

# Input recharge
time_step = 'D' # or 'D'
actual_date = False # False if date is conceptual

# Active of not modules
box = True # if True generate a rectangular model
sink_fill = False # permit to fill sinks
verbose = True # add print of MODFLOW in console
post_process = False # necessary to decompose post process of process

list_model_name = []
list_of_success = []
list_flow_model = []

# defKR = np.logspace(-1,1,9)
# defKR = [2.0,5.0,10.0]
defKR = [1.0,10.0,100.0,1000.0]

# defKR = [10.0]
# defKR = [0.1]

# defKR = defKR[0:1]

# Update properties
compt = 1

for it in range(0,len(defKR)):
    
    KR = defKR[it]
    KR_name = round(KR, 2)
    
    model_name = typ + '_z500' + "_KR_"+str(KR_name)

    # Update recharge
    init_rech = None
    
    # print(KR_name, recharge*1000*365)

    # recharge = 1 / 365 # 10
    BV.forcing.update_recharge(values = (recharge), sim_state=sim_state)

    BV.hydrodynamic.update_nlay(nlay) # 1
    BV.hydrodynamic.update_bottom(bottom) # None
    BV.hydrodynamic.update_cond_decay(cond_decay) # 0
    BV.hydrodynamic.update_thick_exp(thick_exp) # 1
    if bottom == None:
        BV.hydrodynamic.update_thickness(thick) # 30 / intervient pas si bottom != None
    
    K = KR * recharge
    
    print(KR_name, K/3600/24)

    BV.hydrodynamic.update_hyd_cond(K) 
    BV.hydrodynamic.update_porosity(Sy)
      
    date_today = datetime.now().strftime("%d/%m/%Y %H:%M:%S") # just a string
    date_today = date_today.replace('/','-')
    date_today = date_today.replace(':','-')
    date_today = date_today.replace(' ','_')

    # Run model
    from watershed import watershed_root, watershed_display, forcing
    from watershed.data import climatic
    from tools import toolbox, vtk
    from groundwater_flow import visualization, modflow_display
    from calibration import calib_root
    
    if run == True:
        # try:
        print('SIM - ' + model_name)
        success, flow_model = BV.run_modflow(ident=model_name,
                                             modpath_sim=modpath_sim,
                                             sink_fill=sink_fill,
                                             box=box,
                                             verbose=verbose,
                                             post_process=post_process, 
                                             init_rech=init_rech,
                                             verti_k=None)
    if success == True:
        print(     'Success')
    else:
        print(     'Error')
    # except:
    #     pass
    list_model_name.append(model_name)
    list_of_success.append(success)
    list_flow_model.append(flow_model)
    compt+=1
        
print(list_of_success)

dictio = {}
dictio['list_model_name'] = list_model_name
dictio['list_of_success'] = list_of_success
dictio['list_flow_model'] = list_flow_model
h5file = simulations_folder+'/'+'list_'+typ

dd.io.save(h5file, dictio)
                        
#### POSTPROCESS MODEL

for watershed_name in watershed_names[:] :
    
    print('##### '+watershed_name.upper()+' #####')
    
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' 
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)

    h5file = simulations_folder+'/'+'list_'+typ
    d = dd.io.load(h5file)
    list_model_name = d['list_model_name'][:]
    list_of_success = d['list_of_success'][:]
    list_flow_model = d['list_flow_model'][:]
    
    for model_name, success, flow_model in zip(list_model_name, list_of_success, list_flow_model):
            
        if success==True:
                print(success)
                
                if modpath_sim == True:
                    residence_times=True
                else:
                    residence_times=False
                
                BV.matrix_modflow(success,
                                  flow_model,
                                  first_only = True,
                                  watertable_elevation = True,
                                  watertable_depth = True, 
                                  seepage_areas = True,
                                  outflow_drain = True,
                                  groundwater_flux = False,
                                  specific_discharge = False,
                                  accumulation_flux = True,
                                  perenn_intermit_shp = False,
                                  groundwater_storage = True,
                                  residence_times = residence_times,
                                  verbose = True,
                                  export_tif = True)
                
                # Necessary for results_modflow
                BV.forcing.update_recharge(flow_model.climatic,
                                           sim_state=sim_state)
                
                # # Extract results
                BV.results_modflow(ident=model_name,
                                   actual_date=actual_date,
                                   time_step=time_step)
                
                ## Plot maps
                surf = modflow_display.SurfaceOutputs(flow_model.climatic, simulations_folder, stable_folder,
                                                      model_name, types_obs,
                                                      save_gif=False,
                                                      first_only=True,
                                                      sim_state=sim_state,
                                                      outflow=False,
                                                      accflux=False,
                                                      intermittency=False,
                                                      chronics=False)

#%% ---- PLOTAUTO

#%% STEADY 2D CROSS SECTION

for watershed_name in watershed_names[:]:
    
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)
    
    interactive = True
    
    dem = rasterio.open(BV.geographic.watershed_dem)
    dem_data = np.ma.masked_where(dem.read(1) < -100, dem.read(1)) # dem data
    list_path = sorted(glob.glob(simulations_folder+typ+'*'),
                        key=os.path.getmtime, reverse=True)
    model_name = list_path[-1].split('\\')[-1]
    wt_data = imageio.imread(simulations_folder+model_name+'/_watershed/_tifs/'+'watertable_elevation_t(0).tif') # watertable data
    # river_data = imageio.imread(stable_folder+'/hydrology/'+'xxx.tif') # river data
    river_data = None
    modflow_display.interactive_cross_section(dem_data, wt_data, river_data, interactive=interactive)

#%% STEADY 2D MAP VIEW

for watershed_name in watershed_names[:]:

    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)
        
    list_path = sorted(glob.glob(simulations_folder+typ+'*'),
                        key=os.path.getmtime, reverse=False)
    
    for it in range(len(list_path)):
        model_name = list_path[it].split('\\')[-1]
    
        visu = visualization.Visualization(BV, model_name)
        
        visu.visual2D(object_list = ['map', 'grid', 'watertable', 'watertable_depth',
                                      'drain_flow', 
                                       'surface_flow'
                                      ],
                      color_scale = [(None,None),(None,None),(1500,3000),(0,10),
                                      (0,100),
                                       (0,300000)
                                      ])
        
        # visu.visual2D(object_list = ['map', 'grid', 'watertable', 'watertable_depth',
        #                               'drain_flow', 'surface_flow','pathlines','residence_times'],
        #               color_scale = [(None,None),(None,None),(None,None),(0,10),
        #                               (None,None),(None,None),(None,None),(None,None)],
        #               lines = 100)
        
        # visu.visual2D(object_list = ['pathlines'],
        #               color_scale = [(None,None)],
        #               lines=None)

#%% STEADY 3D MAP VIEW

# 3D parameters
list_view = ['watertable_depth'] # object to represent in 3D
# list_view = ['pathlines'] # object to represent in 3D
interactive = True
z_scale = 1
view = 'south-west'
lines = 100

vtk.VTK(BV, model_name)
visu = visualization.Visualization(BV, model_name)
visu.visual3D(interactive=interactive, object_list=list_view, z_scale=z_scale, view=view,
              lines=lines, cloc=(0.7,0.1))
    
#%% ---- CLEMENT V1

#%% GENERAL

typ = 'constant_50m'

### GENERAL ###
stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'
BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=dem_path, 
                              out_path=out_path,
                              load=True,
                              modflow_path=modflow_path)

list_path = sorted(glob.glob(simulations_folder+typ+'*'),
                    key=os.path.getmtime, reverse=False)

for it in range(len(list_path)):
    model_name = list_path[it].split('\\')[-1]
    print(model_name)

    ### SIG ###
    dem = rasterio.open(BV.geographic.watershed_dem)
    dem_data = np.ma.masked_where(dem.read(1) < -100, dem.read(1)) # dem data
    try:
        bv = gpd.read_file(BV.geographic.watershed_shp)
        ext_mod = bv.geometry.total_bounds
    except:
        pass
    wbt.vector_lines_to_raster(stable_folder+'geographic/'+'watershed_contour.shp',
                               stable_folder+'geographic/'+'watershed_contour.tif',
                               base = stable_folder+'geographic/'+'watershed_dem.tif')
    try:
        contour = imageio.imread(stable_folder+'geographic/'+'watershed_contour.tif')
        contour = np.ma.masked_where(contour <= 0, contour)
    except:
        pass
    # streams = imageio.imread(stable_folder+'hydrology/'+'poschiavino_streamnetwork.tif')
    dem_path = BV.geographic.watershed_dem
    dem_im = imageio.imread(dem_path)
    dem_masked = np.ma.masked_where(dem_im < -100, dem_im)
    d8_path = stable_folder+'/geographic/watershed_buff_direc.tif'
    # d8_path = stable_folder+'/geographic/watershed_direc.tif'
    # try:
    # acc_path = simulations_folder+model_name+'/'+'_watershed/_tifs/accumulation_flux_t(0).tif'
    acc_path = simulations_folder+model_name+'/'+'_watershed/_tifs/outflow_drain_t(0).tif'
    down_path = simulations_folder+model_name+'/'+'_watershed/_tifs/downslope_flux_t(0).tif'
    wbt.downslope_flowpath_length(
        d8_path, 
        down_path, 
        watersheds=None, 
        weights=None, 
        esri_pntr=False)
    acc = np.ma.masked_array(imageio.imread(acc_path), mask=dem_masked.mask)
    down = np.ma.masked_array(imageio.imread(down_path), mask=dem_masked.mask)
    # except:
    #     pass

    springs = gpd.read_file(data_path+'Springs_Poschiavino_transf.shp')
    
    # import fiona
    # with fiona.open(data_path+'Springs_Poschiavino_transf.shp', "r") as shapefile:
    #     features = [feature["geometry"] for feature in shapefile]
    
    # from rasterio.plot import show    
    # fig, ax = plt.subplots(1,1)
    # show(dem_data, ax=ax, transform=dem.transform)
    # springs.plot(ax=ax)

#%% OUTFLOW MAPS

typ = 'constant_50m'

dem_path = BV.geographic.watershed_dem
dem_im = imageio.imread(dem_path)
dem_masked = np.ma.masked_where(dem_im < -100, dem_im)

list_path = sorted(glob.glob(simulations_folder+typ+'*'),
                    # key=os.path.getmtime, 
                    # key=os.path.basename,
                    key=lambda x:float(re.findall("\d+\.\d+",x)[0]),
                    reverse=False,
                    )

fig, axs = plt.subplots(1,2, figsize=(8,8))
axs = axs.ravel()

for it in range(len(list_path[:])):
    model_name = list_path[it].split('\\')[-1]
    print(model_name)
    
    ax = axs[it]
    
    drain_path = simulations_folder+model_name+'/'+'_watershed/_tifs/outflow_drain_t(0).tif'
    acc_path = simulations_folder+model_name+'/'+'_watershed/_tifs/accumulation_flux_t(0).tif'
    down_path = simulations_folder+model_name+'/'+'_watershed/_tifs/downslope_flux_t(0).tif'
    
    drain = np.ma.masked_array(imageio.imread(drain_path), mask=dem_masked.mask)
    # acc = np.ma.masked_array(imageio.imread(acc_path), mask=dem_masked.mask)
    down = np.ma.masked_array(imageio.imread(down_path), mask=dem_masked.mask)

    # drain_masked = ( np.log10(drain) - np.nanmean(np.log10(drain)) ) / np.std(np.log10(drain))
    # drain_masked = ( (drain)  / np.nanmean((drain)) ) #/ np.std(np.log10(drain))
    # drain_masked = ( np.log10(drain)  - np.nanmean(np.log10(drain)) ) / np.std(np.log10(drain))
    drain_masked = ( (drain)  - np.nanmean((drain)) ) / np.std((drain))
    # drain_masked = ( (drain)  - np.nanmean((drain)) ) / np.nanmean((drain))
    drain_masked = np.ma.masked_where(drain_masked <= 0, drain_masked)
    
    drain_masked_path = simulations_folder+model_name+'/'+'_watershed/_tifs/drainmasked_flux_t(0).tif'
    toolbox.export_tif(dem_path, drain_masked, -9999, drain_masked_path)
    
    
    # drain_masked = np.ma.masked_where(drain <= drain.mean(), drain)
    # acc_masked = np.ma.masked_where(acc <= acc.mean(), acc)
    down_masked = np.ma.masked_array(down, mask=drain_masked.mask)

    vmin = None
    vmax = None
    s = ax.imshow(drain_masked, 
                    norm=matplotlib.colors.LogNorm(vmin = 0.1, vmax = 20)
                  )
    
    # ax.get_xaxis().set_visible(False)
    # ax.get_yaxis().set_visible(False)

    # ax.set_xlabel('Distance [m]')
    # ax.set_ylabel('Elevation [m]')

    # ax.set_title(model_name)
    # ax.set_ylim(1500, 3000)
    # ax.set_xlim(0, 7000)
    # ax.set_xticks(np.arange(0,7001,1500))
    # ax.invert_xaxis()
    
    # contour_tif = imageio.imread(stable_folder+'geographic/watershed_contour.tif')
    # stream_tif = imageio.imread(stable_folder+'hydrology/poschiavino_streamnetwork_transf.tif')
    stream_tif = imageio.imread(stable_folder+'hydrology/poschiavino_streamnetwork_transf_main.tif')
    ax.imshow(contour, cmap=mpl.colors.ListedColormap('k'), 
              # extent=[0,dem_data.shape[1]*5,
              #         0,dem_data.shape[0]*5],
              zorder=4)
    # ax.imshow(np.ma.masked_where(stream_tif<0, stream_tif), cmap=mpl.colors.ListedColormap('blue'), 
    #           # extent=[0,dem_data.shape[1]*5,
    #           #         0,dem_data.shape[0]*5],
    #           zorder=4)
    
fig.subplots_adjust(right=0.8)
cbar_ax = fig.add_axes([1.0, 0.35, 0.02, 0.3])
cb = fig.colorbar(s, cax=cbar_ax,
                  # ticks=np.arange(0.0,200,50)
                  )    
# cb = fig.colorbar(s, ax=axs.tolist())
cb.set_label('Discharge [m3/j]', rotation= 270, labelpad=25)

plt.tight_layout()

#%% ELEVATION vs DISTANCE col ACCUMULATED

dem_path = BV.geographic.watershed_dem
dem_im = imageio.imread(dem_path)
dem_masked = np.ma.masked_where(dem_im < -100, dem_im)

list_path = sorted(glob.glob(simulations_folder+typ+'*'),
                    # key=os.path.getmtime, 
                    # key=os.path.basename,
                    key=lambda x:float(re.findall("\d+\.\d+",x)[0]),
                    reverse=False,
                    )

fig, axs = plt.subplots(2,1, figsize=(5,6))
axs = axs.ravel()

for it in range(len(list_path[:])):
    model_name = list_path[it].split('\\')[-1]
    # print(model_name)
    
    ax = axs[it]
    
    # drain_path = simulations_folder+model_name+'/'+'_watershed/_tifs/outflow_drain_t(0).tif'
    drain_path = simulations_folder+model_name+'/'+'_watershed/_tifs/accumulation_flux_t(0).tif'
    # acc_path = simulations_folder+model_name+'/'+'_watershed/_tifs/accumulation_flux_t(0).tif'
    down_path = simulations_folder+model_name+'/'+'_watershed/_tifs/downslope_flux_t(0).tif'
    
    drain = np.ma.masked_array(imageio.imread(drain_path), mask=dem_masked.mask)
    # acc = np.ma.masked_array(imageio.imread(acc_path), mask=dem_masked.mask)
    down = np.ma.masked_array(imageio.imread(down_path), mask=dem_masked.mask)

    # drain_masked = ( np.log10(drain) - np.nanmean(np.log10(drain)) ) / np.std(np.log10(drain))
    # drain_masked = ( (drain)  / np.nanmean((drain)) ) #/ np.std(np.log10(drain))
    # drain_masked = ( np.log10(drain)  - np.nanmean(np.log10(drain)) ) / np.std(np.log10(drain))
    drain_masked = ( (drain)  - np.nanmean((drain)) ) / np.std((drain))
    # drain_masked = ( (drain)  - np.nanmean((drain)) ) / np.nanmean((drain))
    drain_masked = np.ma.masked_where(drain_masked <= 0, drain_masked)
    
    # drain_masked = np.ma.masked_where(drain <= drain.mean(), drain)
    # acc_masked = np.ma.masked_where(acc <= acc.mean(), acc)
    down_masked = np.ma.masked_array(down, mask=drain_masked.mask)
    
    down_masked = np.ma.masked_where(stream_tif < 0, down_masked)
    drain_masked = np.ma.masked_where(stream_tif < 0, drain_masked)
    # dem_masked = np.ma.masked_where(down_masked < 0, dem_masked)
    # dem_masked = np.ma.masked_where(stream_tif > 0, dem_masked)

    print(model_name, drain_masked.min(), drain_masked.mean(), drain_masked.max())

    # plt.imshow(drain_masked)
    # plt.colorbar()

    # fig, (ax1, ax2) = plt.subplots(1,2, figsize=(8,3))
    # ax1.imshow(acc_masked)
    # ax1.set_title('Cumulated flux')
    # ax2.imshow(down_masked)
    # ax2.set_title('Downslope lengths')
    # ax1.get_xaxis().set_visible(False)
    # ax1.get_yaxis().set_visible(False)
    # ax2.get_xaxis().set_visible(False)
    # ax2.get_yaxis().set_visible(False)  

    # down_masked_vec = down_masked.flatten('F')
    # down_masked_vec[down_masked_vec<0] = np.nan
    # down_masked_vec = pd.Series(down_masked_vec)
    # down_masked_vec = down_masked_vec.dropna()
    # dem_masked_vec = dem_masked.flatten('F')
    # dem_masked_vec[dem_masked_vec<0] = np.nan
    # dem_masked_vec = pd.Series(dem_masked_vec)
    # dem_masked_vec = dem_masked_vec.dropna()
    # drain_masked_vec = drain_masked.flatten('F')
    # drain_masked_vec[drain_masked_vec<0] = np.nan
    # drain_masked_vec = pd.Series(drain_masked_vec)
    # drain_masked_vec = drain_masked_vec.dropna()
    # drain_masked_vec = drain_masked_vec.diff(periods=1)
    # # drain_masked_vec = np.diff((drain_masked_vec))
    
    # plt.scatter(down_masked_vec, dem_masked_vec, c=drain_masked_vec)

    # fig, ax = plt.subplots(1,1, figsize=(6,3))
    s = ax.scatter(down_masked, dem_masked, marker='.', lw=0, 
                    c=drain_masked,
                    s=20,
                    norm=matplotlib.colors.LogNorm(vmin = 1, vmax = 35)
                    )
    # s = ax.scatter(down_masked_vec, dem_masked_vec, marker='.', lw=0, 
    #                c=drain_masked_vec,
    #                s=20,
    #                 # norm=matplotlib.colors.LogNorm(vmin = 1, vmax = 35)
    #                )
    ax.set_xlabel('Distance [m]')
    ax.set_ylabel('Elevation [m]')

    # ax.set_title(model_name)
    
    
    # springs.plot(ax,ax)
    
    ax.set_ylim(1800, 2200)
    ax.set_xlim(0, 5000)
    
    
    
    # ax.set_ylim(1500, 3000)
    # ax.set_xlim(0, 7000)
    # ax.set_xticks(np.arange(0,7001,1500))
    
    ax.invert_xaxis()
    
    
    
fig.subplots_adjust(right=0.8)
cbar_ax = fig.add_axes([1.03, 0.35, 0.02, 0.3])
cb = fig.colorbar(s, cax=cbar_ax,
                  # ticks=np.arange(0.0,200,50)
                  )    
# cb = fig.colorbar(s, ax=axs.tolist())
cb.set_label('Discharge [m3/j]', rotation= 270, labelpad=25)

plt.tight_layout()



#%% ELEVATION vs DISTANCE col OUTFLOW

dem_path = BV.geographic.watershed_dem
dem_im = imageio.imread(dem_path)
dem_masked = np.ma.masked_where(dem_im < -100, dem_im)

list_path = sorted(glob.glob(simulations_folder+typ+'*'),
                    # key=os.path.getmtime, 
                    # key=os.path.basename,
                    key=lambda x:float(re.findall("\d+\.\d+",x)[0]),
                    reverse=False,
                    )

fig, axs = plt.subplots(2,1, figsize=(5,6))
axs = axs.ravel()

for it in range(len(list_path[:])):
    model_name = list_path[it].split('\\')[-1]
    # print(model_name)
    
    ax = axs[it]
    
    drain_path = simulations_folder+model_name+'/'+'_watershed/_tifs/outflow_drain_t(0).tif'
    # acc_path = simulations_folder+model_name+'/'+'_watershed/_tifs/accumulation_flux_t(0).tif'
    down_path = simulations_folder+model_name+'/'+'_watershed/_tifs/downslope_flux_t(0).tif'
    
    drain = np.ma.masked_array(imageio.imread(drain_path), mask=dem_masked.mask)
    # acc = np.ma.masked_array(imageio.imread(acc_path), mask=dem_masked.mask)
    down = np.ma.masked_array(imageio.imread(down_path), mask=dem_masked.mask)

    # drain_masked = ( np.log10(drain) - np.nanmean(np.log10(drain)) ) / np.std(np.log10(drain))
    # drain_masked = ( (drain)  / np.nanmean((drain)) ) #/ np.std(np.log10(drain))
    # drain_masked = ( np.log10(drain)  - np.nanmean(np.log10(drain)) ) / np.std(np.log10(drain))
    drain_masked = ( (drain)  - np.nanmean((drain)) ) / np.std((drain))
    # drain_masked = ( (drain)  - np.nanmean((drain)) ) / np.nanmean((drain))
    drain_masked = np.ma.masked_where(drain_masked <= 0, drain_masked)
    
    # drain_masked = np.ma.masked_where(drain <= drain.mean(), drain)
    # acc_masked = np.ma.masked_where(acc <= acc.mean(), acc)
    down_masked = np.ma.masked_array(down, mask=drain_masked.mask)
    
    down_masked = np.ma.masked_where(stream_tif < 0, down_masked)
    # dem_masked = np.ma.masked_where(stream_tif > 0, dem_masked)

    print(model_name, drain_masked.min(), drain_masked.mean(), drain_masked.max())

    # plt.imshow(drain_masked)
    # plt.colorbar()

    # fig, (ax1, ax2) = plt.subplots(1,2, figsize=(8,3))
    # ax1.imshow(acc_masked)
    # ax1.set_title('Cumulated flux')
    # ax2.imshow(down_masked)
    # ax2.set_title('Downslope lengths')
    # ax1.get_xaxis().set_visible(False)
    # ax1.get_yaxis().set_visible(False)
    # ax2.get_xaxis().set_visible(False)
    # ax2.get_yaxis().set_visible(False)  
    
    # fig, ax = plt.subplots(1,1, figsize=(6,3))
    s = ax.scatter(down_masked, dem_masked, marker='.', lw=0, c=drain_masked,
                   s=20,
                    norm=matplotlib.colors.LogNorm(vmin = 1, vmax = 35)
                   )
    ax.set_xlabel('Distance [m]')
    ax.set_ylabel('Elevation [m]')

    # ax.set_title(model_name)
    
    
    # springs.plot(ax,ax)
    
    ax.set_ylim(1800, 2200)
    ax.set_xlim(0, 5000)
    
    
    
    # ax.set_ylim(1500, 3000)
    # ax.set_xlim(0, 7000)
    # ax.set_xticks(np.arange(0,7001,1500))
    
    ax.invert_xaxis()
    
    
    
fig.subplots_adjust(right=0.8)
cbar_ax = fig.add_axes([1.03, 0.35, 0.02, 0.3])
cb = fig.colorbar(s, cax=cbar_ax,
                  # ticks=np.arange(0.0,200,50)
                  )    
# cb = fig.colorbar(s, ax=axs.tolist())
cb.set_label('Discharge [m3/j]', rotation= 270, labelpad=25)

plt.tight_layout()

#%% PROFILE ELEVATION

fig, ax = plt.subplots(1,1, figsize=(5,3))
axb = ax.twinx()
axb.plot(dem_data.min(axis=1), color='saddlebrown', lw=2)
axb.set_ylabel('Elevation [m]', rotation=270, labelpad=25)
# axb.set_zorder(ax.get_zorder() - 1)
ax.patch.set_visible(False)
ax.axvline(x=200, c='k', ls='--')

plt.tight_layout()

#%% ---- CLEMENT V2

#%% GENERAL

typ = 'constant_50m'

### GENERAL ###
stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'
BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=dem_path, 
                              out_path=out_path,
                              load=True,
                              modflow_path=modflow_path)

list_path = sorted(glob.glob(simulations_folder+typ+'*'),
                    key=os.path.getmtime, reverse=False)

for it in range(len(list_path)):
    model_name = list_path[it].split('\\')[-1]
    print(model_name)

    ### SIG ###
    dem = rasterio.open(BV.geographic.watershed_dem)
    dem_data = np.ma.masked_where(dem.read(1) < -100, dem.read(1)) # dem data
    
    bv = gpd.read_file(BV.geographic.watershed_shp)
    ext_mod = bv.geometry.total_bounds
    wbt.vector_lines_to_raster(stable_folder+'geographic/'+'watershed_contour.shp',
                               stable_folder+'geographic/'+'watershed_contour.tif',
                               base = stable_folder+'geographic/'+'watershed_dem.tif')
    contour = imageio.imread(stable_folder+'geographic/'+'watershed_contour.tif')
    contour = np.ma.masked_where(contour <= 0, contour)
    
    dem_masked = np.ma.masked_where(dem_data < -100, dem_data)
    d8_path = stable_folder+'/geographic/watershed_buff_direc.tif'
    # d8_path = stable_folder+'/geographic/watershed_direc.tif'

    drain_path = simulations_folder+model_name+'/'+'_watershed/_tifs/outflow_drain_t(0).tif'
    acc_path = simulations_folder+model_name+'/'+'_watershed/_tifs/accumulation_flux_t(0).tif'
    
    vector_path = simulations_folder+model_name+'/'+'_watershed/_tifs/vector_points_t(0).shp'
    wbt.raster_to_vector_points(acc_path, vector_path)
    
    down_path = simulations_folder+model_name+'/'+'_watershed/_tifs/downslope_flux_t(0).tif'
    wbt.downslope_flowpath_length(
        d8_path,
        down_path, 
        watersheds=None, # None
        weights=None, 
        esri_pntr=False)
    
    acc = np.ma.masked_array(imageio.imread(acc_path), mask=dem_masked.mask)
    down = np.ma.masked_array(imageio.imread(down_path), mask=dem_masked.mask)
    drain = np.ma.masked_array(imageio.imread(drain_path), mask=dem_masked.mask)
    
    acc_catchment_path = simulations_folder+model_name+'/'+'_watershed/_tifs/acc_catchment_t(0).tif'
    toolbox.export_tif(BV.geographic.watershed_fill, acc, -9999, acc_catchment_path)
    main_path = simulations_folder+model_name+'/'+'_watershed/_tifs/main_stream_t(0).tif'
    wbt.find_main_stem(
        stable_folder+'/geographic/watershed_direc.tif', 
        acc_catchment_path, 
        main_path, 
        esri_pntr=False, 
        zero_background=False)
    
    springs = gpd.read_file(data_path+'Springs_Poschiavino_transf.shp')
    
    # import fiona
    # with fiona.open(data_path+'Springs_Poschiavino_transf.shp', "r") as shapefile:
    #     features = [feature["geometry"] for feature in shapefile]
    
    # from rasterio.plot import show    
    # fig, ax = plt.subplots(1,1)
    # show(dem_data, ax=ax, transform=dem.transform)
    # springs.plot(ax=ax)
    
    ### WORK WITH SHAPEFILES
    pts = gpd.read_file(vector_path)
    pts.index = range(len(pts))
    coords = [(x,y) for x, y in zip(pts.geometry.x, pts.geometry.y)]
    src = rasterio.open(dem_path)
    pts['Value 1'] = [x[0] for x in src.sample(coords)]
    src = rasterio.open(down_path)
    pts['Value 2'] = [x[0] for x in src.sample(coords)]
    pts['VALUE'] = ( (pts['VALUE'])  - np.nanmean((pts['VALUE'])) ) / np.std((pts['VALUE']))
    fig, ax = plt.subplots(1,1, figsize=(6,3))
    ax.scatter(pts['Value 2'], pts['Value 1'], c=pts['VALUE'], ec='None',
               marker='.', lw=0, s=20,
               norm=matplotlib.colors.LogNorm(vmin = 1, vmax = 35))
    ax.set_xlim(0, 5000)
    ax.set_ylim(1800, 2200)
    ax.invert_xaxis()
    

#%% ---- CLEMENT V3

#%% COMPUTING

typ = 'constant_50m'

### GENERAL ###
stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'
BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=dem_path, 
                              out_path=out_path,
                              load=True,
                              modflow_path=modflow_path)

list_path = sorted(glob.glob(simulations_folder+typ+'*'),
                    key=os.path.getmtime, reverse=False)

for it in range(len(list_path)):
    model_name = list_path[it].split('\\')[-1]
    print(model_name)
    
    dem_path = BV.geographic.watershed_dem
    down_path = simulations_folder+model_name+'/'+'_watershed/_tifs/downslope_flux_t(0).tif'
    wt_path = simulations_folder+model_name+'/'+'_watershed/_tifs/watertable_elevation_t(0).tif'
    drain_path = simulations_folder+model_name+'/'+'_watershed/_tifs/outflow_drain_t(0).tif'
    acc_path = simulations_folder+model_name+'/'+'_watershed/_tifs/accumulation_flux_t(0).tif'
    vector_path = simulations_folder+model_name+'/'+'_watershed/_tifs/vector_points_t(0).shp'
    
    wbt.raster_to_vector_points(acc_path, vector_path)
    # d8_path = stable_folder+'/geographic/watershed_buff_direc.tif'
    if not os.path.exists(down_path):
        wbt.clip_raster_to_polygon(stable_folder+'/geographic/regional/region_down.tif', 
                                   BV.geographic.watershed_shp, 
                                   down_path)
    # wbt.downslope_flowpath_length(
    #     d8_path,
    #     down_path, 
    #     watersheds=None, # None
    #     weights=None, 
    #     esri_pntr=False)
    
    pts = gpd.read_file(vector_path)
    pts.index = range(len(pts))
    coords = [(x,y) for x, y in zip(pts.geometry.x, pts.geometry.y)]
    src = rasterio.open(wt_path)
    pts['wt_value'] = [x[0] for x in src.sample(coords)]
    src = rasterio.open(drain_path)
    pts['drain_value'] = [x[0] for x in src.sample(coords)]
    src = rasterio.open(dem_path)
    pts['dem_value'] = [x[0] for x in src.sample(coords)]
    src = rasterio.open(down_path)
    pts['down_value'] = [x[0] for x in src.sample(coords)]
    src = rasterio.open(acc_path)
    pts['acc_value'] = [x[0] for x in src.sample(coords)]
    # pts['VALUE'] = ( (pts['VALUE'])  - np.nanmean((pts['VALUE'])) ) / np.std((pts['VALUE']))
    pts = pts.drop('VALUE', axis=1)
    values_path = simulations_folder+model_name+'/'+'_watershed/_tifs/vector_values_t(0).shp'
    pts.to_file(values_path)
    
#%% VECTOR VALUES

typ = 'constant_50m'

### GENERAL ###
stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'
BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=dem_path, 
                              out_path=out_path,
                              load=True,
                              modflow_path=modflow_path)

list_path = sorted(glob.glob(simulations_folder+typ+'*'),
                    key=os.path.getmtime, reverse=False)

for it in range(len(list_path)):
    model_name = list_path[it].split('\\')[-1]
    print(model_name)
    
    dem_path = BV.geographic.watershed_dem
    dem_path = BV.geographic.watershed_dem
    down_path = simulations_folder+model_name+'/'+'_watershed/_tifs/downslope_flux_t(0).tif'
    wt_path = simulations_folder+model_name+'/'+'_watershed/_tifs/watertable_elevation_t(0).tif'
    drain_path = simulations_folder+model_name+'/'+'_watershed/_tifs/outflow_drain_t(0).tif'
    acc_path = simulations_folder+model_name+'/'+'_watershed/_tifs/accumulation_flux_t(0).tif'
    vector_path = simulations_folder+model_name+'/'+'_watershed/_tifs/vector_points_t(0).shp'
    values_path = simulations_folder+model_name+'/'+'_watershed/_tifs/vector_values_t(0).shp'

    pts = gpd.read_file(values_path)
    
    if model_name.split('_')[-1] == str(float(1)):
        pts[pts.acc_value<1600] = np.nan
    if model_name.split('_')[-1] == str(float(10)):
        pts[pts.acc_value<1600] = np.nan
    if model_name.split('_')[-1] == str(float(100)):
        pts[pts.acc_value<1600] = np.nan
    # if model_name.split('_')[-1] == str(float(1000)):
    #     pts[pts.acc_value<1600] = np.nan
    
    main_path = simulations_folder+model_name+'/'+'_watershed/_tifs/vector_main_t(0).shp'
    pts.to_file(main_path)
    
#%% ONE AFTER QGIS

typ = 'constant_50m'

### GENERAL ###
stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'
BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=dem_path, 
                              out_path=out_path,
                              load=True,
                              modflow_path=modflow_path)

list_path = sorted(glob.glob(simulations_folder+typ+'*'),
                    key=os.path.getmtime, reverse=False)

for it in range(len(list_path)):
    model_name = list_path[it].split('\\')[-1]
    print(model_name)    
    
    # =============================================================================
    #     AT THIS STEP : DELETE SOME STREAM POINTS ON QGIS
    # =============================================================================
    
    one_path = simulations_folder+model_name+'/'+'_watershed/_tifs/vector_one_t(0).shp'
    shp_id = gpd.read_file(one_path)
    if model_name.split('_')[-1] == str(float(1)):
        one_id_1 = shp_id.FID
    if model_name.split('_')[-1] == str(float(10)):
        one_id_10 = shp_id.FID
    if model_name.split('_')[-1] == str(float(100)):
        one_id_100 = shp_id.FID
    if model_name.split('_')[-1] == str(float(1000)):
        one_id_1000 = shp_id.FID

#%% FINAL SHP

typ = 'constant_50m'

### GENERAL ###
stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'
BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=dem_path, 
                              out_path=out_path,
                              load=True,
                              modflow_path=modflow_path)

list_path = sorted(glob.glob(simulations_folder+typ+'*'),
                    key=os.path.getmtime, reverse=False)

for it in range(len(list_path[:])):
    model_name = list_path[it].split('\\')[-1]
    print(model_name)
    
    if model_name.split('_')[-1] == str(float(1)):
        one_id = one_id_1
    if model_name.split('_')[-1] == str(float(10)):
        one_id = one_id_10
    if model_name.split('_')[-1] == str(float(100)):
        one_id = one_id_100
    if model_name.split('_')[-1] == str(float(1000)):
        one_id = one_id_1000
        
    one_path = simulations_folder+model_name+'/'+'_watershed/_tifs/vector_one_t(0).shp'
    final_path = simulations_folder+model_name+'/'+'_watershed/_tifs/vector_final_t(0).shp'

    # vector = gpd.read_file(vector_path)
    # values = gpd.read_file(values_path)
    # main = gpd.read_file(main_path)

    one = gpd.read_file(one_path)
    one = one.dropna(how='all')
    # one = gpd.read_file(main_path)
    # one = one[one['FID'].isin(one_id)]
    one['acc_norm'] = ( (one['acc_value'])  - np.nanmean((one['acc_value'])) ) / np.std((one['acc_value']))
    one['acc_diff'] = one['acc_value'].diff(periods=10) # rolling
    # one['acc_rol'] = one['acc_value'].rolling(window=10).diff() # rolling
    print(one['acc_diff'].min(), one['acc_diff'].mean(), one['acc_diff'].max())
    print(one['acc_value'].min(), one['acc_value'].mean(), one['acc_value'].max())
    one.to_file(final_path)

#%% FIGURES

typ = 'constant_50m'

### GENERAL ###
stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'
BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=dem_path, 
                              out_path=out_path,
                              load=True,
                              modflow_path=modflow_path)

list_path = sorted(glob.glob(simulations_folder+typ+'*'),
                    key=os.path.getmtime, reverse=False)

for it in range(len(list_path[:])):
    model_name = list_path[it].split('\\')[-1]
    print(model_name)
    
    dem_rast = rasterio.open(BV.geographic.watershed_dem)
    dem_data = np.ma.masked_where(dem_rast.read(1) < -100, dem_rast.read(1)) # dem data
    dem_masked = np.ma.masked_where(dem_data < 0, dem_data)
    
    hill_rast = rasterio.open(data_path+"hillshade_z1_dem10m.tif")
    hill_data = hill_rast.read(1)
    hill_path = stable_folder+'/geographic/hillshade.tif'
    toolbox.export_tif(BV.geographic.watershed_dem, 
                       hill_data, -9999, hill_path)
    hill_rast = rasterio.open(hill_path)
    hill_data = np.ma.masked_where(hill_rast.read(1) < 0, hill_rast.read(1)) # dem data
    hill_masked = np.ma.masked_where(dem_data.mask, hill_data)
    
    bv = gpd.read_file(BV.geographic.watershed_shp)
    ext_mod = bv.geometry.total_bounds
    
    springs_path = data_path+'Springs_Poschiavino_transf.shp'
    acc_path = simulations_folder+model_name+'/'+'_watershed/_tifs/accumulation_flux_t(0).tif'
    down_path = simulations_folder+model_name+'/'+'_watershed/_tifs/downslope_flux_t(0).tif'
    drain_path = simulations_folder+model_name+'/'+'_watershed/_tifs/outflow_drain_t(0).tif'
    vector_path = simulations_folder+model_name+'/'+'_watershed/_tifs/vector_points_t(0).shp'
    values_path = simulations_folder+model_name+'/'+'_watershed/_tifs/vector_values_t(0).shp'
    main_path = simulations_folder+model_name+'/'+'_watershed/_tifs/vector_main_t(0).shp'
    one_path = simulations_folder+model_name+'/'+'_watershed/_tifs/vector_one_t(0).shp'
    final_path = simulations_folder+model_name+'/'+'_watershed/_tifs/vector_final_t(0).shp'

    springs = gpd.read_file(springs_path)
    coords = [(x,y) for x, y in zip(springs.geometry.x, springs.geometry.y)]
    src = rasterio.open(dem_path)
    springs['dem_value'] = [x[0] for x in src.sample(coords)]
    src = rasterio.open(down_path)
    springs['down_value'] = [x[0] for x in src.sample(coords)]

    # acc = np.ma.masked_array(imageio.imread(acc_path), mask=dem_masked.mask)
    # down = np.ma.masked_array(imageio.imread(down_path), mask=dem_masked.mask)
    # drain = np.ma.masked_array(imageio.imread(drain_path), mask=dem_masked.mask)
    acc_rast = rasterio.open(acc_path)
    acc_data = acc_rast.read(1) # dem data
    acc_masked = np.ma.masked_where((dem_data.mask)|(acc_data<=0), acc_data)
    
    one = gpd.read_file(final_path)
    one[['acc_value','acc_diff']] = one[['acc_value','acc_diff']] / 1000
    
    print(one['acc_diff'].min(), one['acc_diff'].mean(), one['acc_diff'].max())
    print(one['acc_value'].min(), one['acc_value'].mean(), one['acc_value'].max())
    
    one[one['acc_value']<0] = np.nan
    
    fig, ax = plt.subplots(1,1, figsize=(6,3))
    
    # fig, ax = plt.subplots(1,1, figsize=(6,3))
    axb = ax.twinx()
    axb.bar(one['down_value'], one['acc_diff'],
            width=20, lw=0, color='dimgray', zorder=-1000)
    axb.set_ylim(0, 8)
    axb.spines[['top']].set_visible(False)
    axb.tick_params(top=False)
    axb.yaxis.label.set_color('dimgray')
    axb.tick_params(axis='y', colors='dimgray')
    # axb.tick_params(right=False)
    
    # axbb = ax.twinx()
    # ax.plot(one['down_value'], one['dem_value'], color='saddlebrown')
    # ax.plot(one['down_value'], one['wt_value'], color='navy')

    # ax.scatter(values['down_value'], values['dem_value'], c=values['acc_value'], ec='None',
    #            marker='.', lw=0, s=20,
    #            norm=matplotlib.colors.LogNorm(vmin = 1, vmax = 15000))
    s = ax.scatter(one['down_value'], one['dem_value'], 
               c=one['acc_value'],
               cmap='jet',
               marker="|", lw=2, s=25,
                vmin=0, 
                vmax=25,
                # norm=matplotlib.colors.LogNorm(vmin=100, vmax=100000)
               )
    ax.scatter(springs['down_value'], springs['dem_value'], ec='k', 
                lw= 1, marker='.', s=10,
                facecolor='None')
    ax.set_xlim(2000, 6000)
    ax.set_ylim(1850, 2250)
    fig.subplots_adjust(right=0.8)
    cbar_ax = fig.add_axes([1.03, 0.30, 0.02, 0.5])
    cb = fig.colorbar(s, cax=cbar_ax,
                      # ticks=np.arange(0.0,200,50)
                      )    
    # cb = fig.colorbar(s, ax=axs.tolist())
    cb.set_label('Discharge [L/j]', rotation= 270, labelpad=25)
    
    # ax.spines[['right', 'top']].set_visible(False)
    # ax.tick_params(top=False)
    # ax.tick_params(right=False)
        
    ax.invert_xaxis()
    # axb.invert_xaxis()
    
    # fig.set_zorder(ax.get_zorder()+1)
    # fig.patch.set_visible(False)
    
    ax.zorder = 2 # fills in back
    axb.zorder = 1 # then the line
    # ax2.zorder = 3 # then the points
    ax.patch.set_visible(False)
    
    plt.tight_layout()

    fig.savefig("D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/4_model/POSCHIAVINO/_results/"+
                "v4/"+"profile_"+model_name+'.png', dpi=300, bbox_inches='tight')

    fig, ax = plt.subplots(1,1, figsize=(6,3))
    bv.plot(ax=ax, facecolor='None')
    ax.get_xaxis().set_visible(False)
    ax.get_yaxis().set_visible(False)
    
    show(hill_masked, ax=ax, transform=dem_rast.transform, cmap='Greys_r', alpha=0.5)
    show(dem_data, ax=ax, transform=dem_rast.transform, cmap='Greys', alpha=0.5)
    
    show(acc_masked, ax=ax, transform=dem_rast.transform, cmap=mpl.colors.ListedColormap('k'), alpha=1)
    
    one.plot(ax=ax, column='acc_diff', ec='None',
             marker="o", lw=0.5, s=5,
              vmin=0, vmax=1,
             # norm=matplotlib.colors.LogNorm(vmin=100, vmax=100000)
             )
    springs.plot(ax=ax, ec='k', 
                lw=0.5, marker='.',
                facecolor='None')
    
    plt.axis('off')
    
    fig.savefig("D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/4_model/POSCHIAVINO/_results/"+
                "v4/"+"map_"+model_name+'.png', dpi=300, bbox_inches='tight')
    
    """
    fig, ax = plt.subplots(1,1, figsize=(6,3))
    ax.plot(one['down_value'], one['dem_value'], color='saddlebrown')
    ax.plot(one['down_value'], one['wt_value'], color='navy')
    ax.set_xlim(2000, 6000)
    ax.set_ylim(1850, 2250)
    ax.invert_xaxis()
    """
    
#%% NOTES

# acc_catchment_path = simulations_folder+model_name+'/'+'_watershed/_tifs/acc_catchment_t(0).tif'
# toolbox.export_tif(BV.geographic.watershed_fill, acc, -9999, acc_catchment_path)
# main_path = simulations_folder+model_name+'/'+'_watershed/_tifs/main_stream_t(0).tif'
# wbt.find_main_stem(
#     d8_path, 
#     acc_catchment_path, 
#     main_path, 
#     esri_pntr=False, 
#     zero_background=False)

# from rasterio.plot import show    
# fig, ax = plt.subplots(1,1)
# show(dem_data, ax=ax, transform=dem.transform)
# springs.plot(ax=ax)