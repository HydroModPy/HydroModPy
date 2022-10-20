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
wbt.verbose = False

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
data_path = "D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/4_model/GUADELOUPE/_data/"
# Path where the results will be stored
out_path = "D:/Users/abherve/GUADELOUPE/"
# Figure folder outputs
res_path = 'D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/4_model/GUADELOUPE/_outputs/'

dems_path = data_path # reginal DEM or conceptual DEM
modflow_path = 'C:/Users/ronan/OneDrive/_HydroDataPy/SOFTWARE/MODFLOW/' # add bin/ folder with necessary .exe

hydrology_path = data_path # add hydrographic shapefiles

dem_name = "BasseTerre_dem_clip.tif" # name of dem

subbasin_path = True # generate subbasins from stations or manual points
from_shp = None # specify a path if process start from a given shapefile
from_dem = False # True or False if the process start from a given DEM of xyz file
cell_size = None # specify new resolution from a given DEM or None
from_xy = []

# Depending on the choices
dem_path = dems_path + dem_name
library_path = data_path + 'watershed_library.csv' # each row is a study site with outlet coordinates

# watershed_names = ['Horn','Leff','Canut','Nancon','Arguenon','Flume','Gael']
# code_names = ['J3014330','J1803010','J7513010','J0014010','J1105810','J7214010','J7313010']

watershed_names = ['Quiock']

# types_obs = ['perennial','perennial_intermittent'] # list of shapefile name layers for clip hydrology
# fields_obs = ['fid','fid']

types_obs = ['L_Quiock_creek2']
fields_obs = ['fid']

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
  
    print(BV.geographic.area.round(2))
    print(BV.geographic.slope.round(2))
    
    watershed_display.watershed_dem(BV)
    watershed_display.watershed_local(dem_path, BV)
        
#%% DATA WATERSHED

for watershed_name in watershed_names[:]:
                   
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True)

    BV.add_hydrology(hydrology_path, types_obs=types_obs, fields_obs=fields_obs)

    print('##### '+watershed_name.upper()+' #####')

    BV.add_hydrodynamic()
    BV.add_forcing()
    
    watershed_display.watershed_dem(BV)
    watershed_display.watershed_local(dem_path, BV)
        
#%% ---- CALIB

#%% DICHOTOMY STREAMS

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

#%% ---- MODEL

#%% CASES TO TYP

# Aquifer
thick = 300 # m
bottom = -100 # aquifer flat or not

# Discretization
nlay = 50 # vertical discrtization
thick_exp = 1.2 # exponential decay of nlay with depth

# Climate
recharge = 2 / 365 # mm/s to m/j

# Porosity
Sy = 0.1

# Hydraulic cond.
k1 = 2.4e-7 / 10
# k2 = 2.4e-7
# k2 = 2.4e-7 / 10
# k2 = 2.4e-7 * 10
k2 = 2.4e-7
thick_k2 = 45
Koptim = k1 # "k2"
cond_decay = 0 # exponential decay of K with depth
# cond_decay = 0.02 # exponential decay of K with depth

# Vertical
verti_k = [ [k2 * 3600 * 24, [0, thick_k2]] ] # "k1", or None
# verti_k = None # "k1", or None

case_list = ['case1', 'case2', 'case3', 'case4', 'case5']

num_case = 5
typ = case_list[num_case-1]

# typ = 'verif'

#%% RUN MODEL

sim_state = 'steady' # 'steady' or 'transient'
modpath_sim = True # run modpath particle tracking if True

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

# Recharge
init_rech = None
BV.forcing.update_recharge(recharge, sim_state=sim_state) #

# Hyd prop.
Ks = np.array([Koptim]) * 3600 * 24 # m/second to m/day
Sys = [Sy]

list_model_name = []
list_of_success = []
list_flow_model = []

# Update properties
compt = 1
for Sy in Sys:
    for K in Ks:

        BV.hydrodynamic.update_nlay(nlay) # 1
        BV.hydrodynamic.update_bottom(bottom) # None
        BV.hydrodynamic.update_cond_decay(cond_decay) # 0
        BV.hydrodynamic.update_thick_exp(thick_exp) # 1
        BV.hydrodynamic.update_thickness(thick) # 30 / intervient pas si bottom != None
        
        BV.hydrodynamic.update_hyd_cond(K) 
        BV.hydrodynamic.update_porosity(Sy)
          
        date_today = datetime.now().strftime("%d/%m/%Y %H:%M:%S") # just a string
        date_today = date_today.replace('/','-')
        date_today = date_today.replace(':','-')
        date_today = date_today.replace(' ','_')
        
        model_name = typ+'_'+str(compt)+'_'+\
                         str(Sy*100)+'-'+str(round(K,2))+'-'+str(thick)+'_'+str(nlay)

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
                                                 verti_k=verti_k)
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
                        
#%% POSTPROCESS MODEL

for typ in case_list[4:5]:

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
                                                          accflux=True,
                                                          intermittency=False,
                                                          chronics=False)

#%% ---- PLOTAUTO

#%% STEADY 2D CROSS INTERAC

for typ in case_list[4:5]:

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
        river_data = imageio.imread(stable_folder+'/hydrology/'+'L_Quiock_creek2.tif') # river data
        modflow_display.interactive_cross_section(dem_data, wt_data, river_data, interactive=interactive)

#%% STEADY 2D MAP VIEW

for typ in case_list[4:5]:

    for watershed_name in watershed_names[:]:
    
        stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
        simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'
        BV = watershed_root.Watershed(watershed_name=watershed_name,
                                      dem_path=dem_path, 
                                      out_path=out_path,
                                      load=True,
                                      modflow_path=modflow_path)
            
        list_path = sorted(glob.glob(simulations_folder+typ+'*'),
                            key=os.path.getmtime, reverse=True)
        model_name = list_path[-1].split('\\')[-1]
    
        visu = visualization.Visualization(BV, model_name)
        
        visu.visual2D(object_list = ['map', 'grid', 'watertable', 'watertable_depth',
                                      'drain_flow', 'surface_flow'],
                      color_scale = [(None,None),(None,None),(None,None),(0,10),
                                      (None,None),(None,None)])
        
        # visu.visual2D(object_list = ['map', 'grid', 'watertable', 'watertable_depth',
        #                               'drain_flow', 'surface_flow','pathlines','residence_times'],
        #               color_scale = [(None,None),(None,None),(None,None),(0,10),
        #                               (None,None),(None,None),(None,None),(None,None)],
        #               lines = None)
        
        # visu.visual2D(object_list = ['pathlines'],
        #               color_scale = [(None,None)],
        #               lines=None)
    
#%% STEADY 3D MAP VIEW

# 3D parameters
list_view = ['watertable_depth'] # object to represent in 3D
list_view = ['pathlines'] # object to represent in 3D
interactive = True
z_scale = 1
view = 'south-west'
lines = 100

vtk.VTK(BV, model_name)
visu = visualization.Visualization(BV, model_name)
visu.visual3D(interactive=interactive, object_list=list_view, z_scale=z_scale, view=view,
              lines=lines, cloc=(0.7,0.1))
    
#%% ---- TYP

#%% CHOICE

typ = 'case5'

#%% ---- LOAD DATA

#%% GENERAL

### GENERAL ###
stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'
BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=dem_path, 
                              out_path=out_path,
                              load=True,
                              modflow_path=modflow_path)

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
streams = imageio.imread(stable_folder+'hydrology/'+'L_Quiock_creek2.tif')
dem_path = BV.geographic.watershed_dem
dem_im = imageio.imread(dem_path)
dem_masked = np.ma.masked_where(dem_im < -100, dem_im)
d8_path = stable_folder+'/geographic/watershed_buff_direc.tif'
acc_path = simulations_folder+model_name+'/'+'_watershed/_tifs/accumulation_flux_t(0).tif'
down_path = simulations_folder+model_name+'/'+'_watershed/_tifs/downslope_flux_t(0).tif'
wbt.downslope_flowpath_length(
    d8_path, 
    down_path, 
    watersheds=None, 
    weights=None, 
    esri_pntr=False)
acc = np.ma.masked_array(imageio.imread(acc_path), mask=dem_masked.mask)
down = np.ma.masked_array(imageio.imread(down_path), mask=dem_masked.mask)

#%% PLOT

wt_data = imageio.imread(simulations_folder+model_name+'/_watershed/_tifs/'+
                          'watertable_elevation_t(0).tif') 

xvalues = np.linspace(-1,1,dem_data.shape[1])
yvalues = np.linspace(-1,1,dem_data.shape[0])
xx, yy = np.meshgrid(xvalues,yvalues)

dem_max = dem_data.max()
dem_prof = dem_data.astype(float)
dem_prof[dem_prof<0] = np.nan
wt_prof = wt_data.astype(float)
wt_prof[wt_prof<0] = np.nan

fig_l, ax_l = plt.subplots(1, 1, figsize=(5,8))

for i, coord in enumerate([[60,55,140,35],[90,90,140,35]]):
    cros = i

    x0, y0 = coord[0], coord[1] # These are in _pixel_ coordinates !
    x1, y1 = coord[2], coord[3]
    num = int(np.hypot(x1-x0, y1-y0))
    num = x1-x0
    # num=100
    x, y = np.linspace(x0, x1, num), np.linspace(y0, y1, num)
    zd = dem_data[y.astype(np.int), x.astype(np.int)]
    zw = wt_data[y.astype(np.int), x.astype(np.int)]
    
    dem_max = dem_data.max()
    dem_prof = dem_data.astype(float)
    dem_prof[dem_prof<0] = np.nan
    dem_plot = np.ma.masked_array(dem_data, mask=(dem_data<0))
    
    wt_prof = wt_data.astype(float)
    wt_prof[wt_prof<0] = np.nan
    
    ax_l.imshow(dem_plot, origin='lower', cmap='terrain', aspect="equal")
    ax_l.set_ylim(ax_l.get_ylim()[::-1])
    d_line = ax_l.plot((x0,x1),(y0,y1), 'k-', lw=3)
    # v_line = ax.axvline(cur_x, color='k', lw=2)
    # h_line = ax.axhline(cur_y, color='k', lw=2)

streams = imageio.imread(stable_folder+'hydrology/'+'L_Quiock_creek2.tif')
ax_l.imshow(np.ma.masked_where(streams<0, streams), cmap=mpl.colors.ListedColormap('navy'))
ax_l.imshow(contour, cmap=mpl.colors.ListedColormap('k'))
ax_l.invert_yaxis()

#%% MODPATH

### MODEL ###
list_path = sorted(glob.glob(simulations_folder+typ+'*'), key=os.path.getmtime, reverse=True)
model_name = list_path[-1].split('\\')[-1]
mf = flopy.modflow.Modflow.load(simulations_folder+model_name+'/'+model_name+'.nam')
fname = simulations_folder+model_name+'/'+model_name+'.hds'
gridname = simulations_folder+model_name+'/'+model_name+'.dis'
grid_model = flopy.discretization.grid.Grid(mf)
# sr_model = flopy.utils.reference.SpatialReference()

def reproj_approx_points(shp_name):
    shp = gpd.read_file(simulations_folder+
                        model_name+'/'+'_pathlines/'+
                        shp_name+'.shp')
    ext_shp = shp.geometry.total_bounds
    crs_code = 32620
    shp.set_crs(epsg=crs_code, inplace=True, allow_override=True)
    # shp.to_crs(utm_crs)
    x = (shp.geometry.x) + ext_mod[0] # - ext_shp[0] # 6.39e5 
    y = (shp.geometry.y) + ext_mod[1] # - ext_shp[3] # 1.78e6 
    gdf = gpd.GeoDataFrame(shp, geometry=gpd.points_from_xy(x, y))
    gdf.to_file(simulations_folder+
                model_name+'/'+'_pathlines/'+
                shp_name+'.shp')

### POINTS ###
print('Create shapefile ending and starting points')
endobj = flopy.utils.EndpointFile(simulations_folder+
                                  model_name+'/'+model_name+'.mpend')
e = endobj.get_alldata()
endobj.write_shapefile(endpoint_data=e,
                        shpname=simulations_folder+
                                model_name+'/'+'_pathlines/'+
                                'ending.shp',
                        direction='ending',
                        mg=grid_model, epsg=32620, sr=None)
endobj.write_shapefile(endpoint_data=e,
                        shpname=simulations_folder+
                                model_name+'/'+'_pathlines/'+
                                'starting.shp',
                        direction='starting',
                        mg=grid_model, epsg=32620, sr=None)
# reproj_approx_points('ending')
# reproj_approx_points('starting')

### PATHLINES ###
print('Create shapefile pathlines')
pthobj = flopy.utils.PathlineFile(simulations_folder+
                                  model_name+'/'+model_name+'.mppth')
pth_data = pthobj.get_alldata()
pthobj.write_shapefile(pathline_data=pth_data,
                        shpname=simulations_folder+
                                model_name+'/'+'_pathlines/'+
                                'pathlines.shp',
                        one_per_particle=True, # False
                        direction='ending',
                        mg=grid_model, epsg=32620, sr=None)

#%% SELECT

cond_lay = 38 # ==> approx. 40 meters

compt = 0
indices_layers = []
superf_p = []
superf_id = []
profon_p = []
profon_id = []
for idx, pline in enumerate(pth_data):
    if all(x < cond_lay for x in pline.k):
        compt += 1
        # print(compt)
        superf_p.append(pline)
        superf_id.append(pline['particleid'][0])
        
    else:
        profon_p.append(pline)
        profon_id.append(pline['particleid'][0])
                
indices_layers = [profon_id, superf_id]

create_rdm = False
num_rdm = 100
# if not os.path.exists(simulations_folder+'indices_layers_rdm_'+str(num_rdm)+'.data'):
if create_rdm == True:
    random.sample(profon_id, num_rdm)
    indices_layers_rdm = [random.sample(profon_id, num_rdm),
                          random.sample(superf_id, num_rdm)]
    data = indices_layers_rdm.copy()
    with open(simulations_folder+'indices_layers_rdm_'+str(num_rdm)+'.data', 'wb') as f:
        pickle.dump(data, f)
else:
    with open(simulations_folder+'indices_layers_rdm_'+str(num_rdm)+'.data', 'rb') as f:
        data = pickle.load(f)
        indices_layers_rdm = data.copy()

#%% ---- V1 FINAL CHOICE

#%% RESIDENCE TIMES ALL - TOP VIEW

folder_results = simulations_folder + '/' + model_name + '/' + '_watershed/_tifs/'

path_res = folder_results+'residence_times_t(0).tif'
path_obs = data_path+'targets_pathlines_points.shp'
path_shp = simulations_folder + '/' + model_name + '/' + '_watershed/_shp/'
toolbox.create_folder(path_shp)
path_dat = path_shp+'residence_times_data.shp'

res_time = rasterio.open(path_res)
res_time_data = res_time.read(1)
res_time_data = res_time_data

shp_obs = gpd.read_file(path_obs)
shp_obs['geometry'] = shp_obs.geometry.buffer(100)
shp_obs.to_file(path_dat, encoding='utf-8') # mode a

# Method 1
wbt.raster_to_vector_polygons(
        path_res, 
        path_shp+'raster_polygonized.shp')
raster_polyg = gpd.read_file(path_shp+'raster_polygonized.shp')
intersect = gpd.overlay(shp_obs, raster_polyg, how='intersection')
intersect[intersect['VALUE']==-np.inf] = np.nan
res_dat = gpd.read_file(path_dat)
res_dat['RES_TIME'] = np.nan
res_dat['STD_TIME'] = np.nan

for ID in intersect['id'].unique():

    mask = (intersect[intersect['id']==ID]['VALUE'] !=0)
    
    mean_ID = np.nanmean(intersect[intersect['id']==ID]['VALUE'][mask])
    res_dat['RES_TIME'][res_dat['id']==ID] = mean_ID
    
    std_ID = np.nanstd(intersect[intersect['id']==ID]['VALUE'][mask])
    res_dat['STD_TIME'][res_dat['id']==ID] = std_ID
    
# Method 2
'''
from rasterstats import zonal_stats
stats = zonal_stats(path_dat, path_res)
# print(stats[0].keys())
# print(stats)
means = [f['mean'] for f in stats]
res_dat = gpd.read_file(path_dat)
res_dat['RES_TIME'] = means
'''

res_dat['RES_TIME'][res_dat['RES_TIME']==-np.inf] = np.nan
res_dat['STD_TIME'][res_dat['STD_TIME']==-np.inf] = np.nan
res_dat.to_file(path_shp + 'extract_RTD.shp', encoding = 'utf-8')

vmin = 0
vmax = 100

fig, ax = plt.subplots(1,1, figsize=(5,5))

res_time_data = np.ma.masked_where(res_time_data < 0, res_time_data)
show(res_time_data, ax=ax, transform=dem.transform, 
      cmap='jet', alpha=1, zorder=2, aspect="auto", vmin=vmin, vmax=vmax)
# shp_obs.plot(ax=ax, color='none', marker='o', markersize=10,
#              edgecolor='k', lw=3, zorder=30)
bounds = dem.bounds
xlim = ([bounds[0], bounds[2]])
ylim = ([bounds[1], bounds[3]])
ax.set_xlim(xlim)
ax.set_ylim(ylim)
scalebar = ScaleBar(1,box_alpha=0, scale_loc = 'bottom', location='upper left')
ax.add_artist(scalebar)
ax.get_xaxis().set_visible(False)
ax.get_yaxis().set_visible(False)
ax.set_title(model_name, fontproperties=fontprop)
ax.set(aspect='equal')
sm = plt.cm.ScalarMappable(cmap='jet', norm=plt.Normalize(vmin=vmin, vmax=vmax))
# sm = plt.cm.ScalarMappable(cmap='jet')
divider = make_axes_locatable(ax)
cax = divider.append_axes(size="2%",position='right', pad=0.05)
fig.add_axes(cax)
cbar = fig.colorbar(sm, cax=cax, orientation="vertical")
cbar.ax.get_ymajorticklabels()
cbar.ax.tick_params(labelsize=10)
cbar.ax.yaxis.set_ticks_position('right')
cbar.ax.tick_params(size=2)
contour_shp = gpd.read_file(BV.geographic.watershed_contour_shp)
contour_shp.plot(ax=ax, lw=1.5, color='k', zorder=20, legend=False, label='Watershed')
cbar.set_ticks(list(cbar.get_ticks()))
# cbar.set_ticklabels(list(cbar.get_ticks())[::-1])
cbar.set_label('Residence times [years]', rotation=270, labelpad=25)

res_dat['coords'] = res_dat['geometry'].apply(lambda x: x.representative_point().coords[:])
res_dat['coords'] = [res_dat[0] for res_dat in res_dat['coords']]
# for idx, row in res_dat.iterrows():
#     row['coords'] = (row['coords'][0], row['coords'][1]+100)
#     ax.annotate(s=row['id'], xy=row['coords'],
#                  horizontalalignment='center')

if compt==0:
    all_dat = res_dat.copy()
all_dat[model_name] = res_dat['RES_TIME']

# all_dat['coords'] = np.nan
# all_dat.to_file(simulations_folder+'residence_times_all.shp', sep=';', encoding='utf-8')

# fig.savefig(simulations_folder + '/' + model_name + '/' +'_figures/' + 
#             'map_residence_time_all'+'.png', dpi=300, bbox_inches='tight')

#%% STARTING RED/BLUE - TOP VIEW

color_layers = ['red', 'dodgerblue']

fig, ax = plt.subplots(1,1, figsize=(3,3))    
ax = ax
ax.set_title('Starting points deep vs. shallow', fontsize=10)
shp_starting = gpd.read_file(simulations_folder+
                    model_name+'/'+'_pathlines/'+
                    'starting.shp')
keep_deep = np.isin(shp_starting.particleid, indices_layers[0])
shp_deep = shp_starting[keep_deep]
keep_shal = np.isin(shp_starting.particleid, indices_layers[1])
shp_shal = shp_starting[keep_shal]

shp_deep[shp_starting.time>0].plot(ax=ax, markersize=4,
                                       c=color_layers[0], lw=0,
                                       alpha=1, zorder=1)
shp_shal[shp_starting.time>0].plot(ax=ax, markersize=4,
                                       c=color_layers[1], lw=0,
                                       alpha=1, zorder=1)
ax.imshow(np.ma.masked_where(streams<=0, streams), cmap=mpl.colors.ListedColormap('navy'), 
          extent=[0,dem_data.shape[1]*5,
                  0,dem_data.shape[0]*5], zorder=3)
ax.imshow(contour, cmap=mpl.colors.ListedColormap('k'), 
          extent=[0,dem_data.shape[1]*5,
                  0,dem_data.shape[0]*5], zorder=4)
ax.get_xaxis().set_visible(False)
ax.get_yaxis().set_visible(False)  
fig.tight_layout()
# fig.savefig(simulations_folder + '/' + model_name + '/' +'_figures/' + 
#             'Pathlines in shallow layer from starting points'+'.png', dpi=300, bbox_inches='tight')

#%% ENDING RED/BLUE - TOP VIEW

color_layers = ['red', 'dodgerblue']

fig, ax = plt.subplots(1,1, figsize=(3,3))    
ax = ax
ax.set_title('Ending points deep vs. shallow', fontsize=10)
shp_ending = gpd.read_file(simulations_folder+
                    model_name+'/'+'_pathlines/'+
                    'ending.shp')
keep_deep = np.isin(shp_ending.particleid, indices_layers[0])
shp_deep = shp_ending[keep_deep]
keep_shal = np.isin(shp_ending.particleid, indices_layers[1])
shp_shal = shp_ending[keep_shal]

shp_deep[shp_ending.time>0].plot(ax=ax, markersize=4,
                                       c=color_layers[0], lw=0,
                                       alpha=1, zorder=1)
shp_shal[shp_ending.time>0].plot(ax=ax, markersize=4,
                                       c=color_layers[1], lw=0,
                                       alpha=1, zorder=1)
ax.imshow(np.ma.masked_where(streams<=0, streams), cmap=mpl.colors.ListedColormap('navy'), 
          extent=[0,dem_data.shape[1]*5,
                  0,dem_data.shape[0]*5], zorder=3)
ax.imshow(contour, cmap=mpl.colors.ListedColormap('k'), 
          extent=[0,dem_data.shape[1]*5,
                  0,dem_data.shape[0]*5], zorder=4)
ax.get_xaxis().set_visible(False)
ax.get_yaxis().set_visible(False)  
fig.tight_layout()
# fig.savefig(simulations_folder + '/' + model_name + '/' +'_figures/' + 
#             'Pathlines in shallow layer from starting points'+'.png', dpi=300, bbox_inches='tight')

#%% PATHLINES RED/BLUE - TOP VIEW

color_layers = ['red', 'dodgerblue']

fig, ax = plt.subplots(1,1, figsize=(3,3))    
ax = ax
ax.set_title('Pathlines deep vs. shallow', fontsize=10)
shp_pathlines = gpd.read_file(simulations_folder+
                    model_name+'/'+'_pathlines/'+
                    'pathlines.shp')
keep_deep = np.isin(shp_pathlines.particleid, indices_layers_rdm[0])
keep_deep = np.isin(shp_pathlines.particleid, indices_layers[0])
shp_deep = shp_pathlines[keep_deep]
keep_shal = np.isin(shp_pathlines.particleid, indices_layers_rdm[1])
keep_shal = np.isin(shp_pathlines.particleid, indices_layers[1])

shp_shal = shp_pathlines[keep_shal]

# shp_deep.plot(ax=ax, color=color_layers[0], lw=1, alpha=0.5, zorder=2)
# shp_shal.plot(ax=ax, color=color_layers[1], lw=1, alpha=0.5, zorder=3)

shp_deep.plot(ax=ax, color=color_layers[0], lw=0.05, alpha=1, zorder=-1000)
shp_shal.plot(ax=ax, color=color_layers[1], lw=0.1, alpha=1, zorder=1000)

ax.imshow(np.ma.masked_where(streams<=0, streams), cmap=mpl.colors.ListedColormap('navy'), 
          extent=[0,dem_data.shape[1]*5,
                  0,dem_data.shape[0]*5], zorder=4)
ax.imshow(contour, cmap=mpl.colors.ListedColormap('k'), 
          extent=[0,dem_data.shape[1]*5,
                  0,dem_data.shape[0]*5], zorder=5)
ax.get_xaxis().set_visible(False)
ax.get_yaxis().set_visible(False)  
fig.tight_layout()
# fig.savefig(simulations_folder + '/' + model_name + '/' +'_figures/' + 
#             'Pathlines in shallow layer from starting points'+'.png', dpi=300, bbox_inches='tight')

#%% PATHLINES - CROSS SECTION

fig, ax = plt.subplots(1,1, figsize=(7, 3))
# modelmap = flopy.plot.PlotMapView(model=mf)
# linecollection = modelmap.plot_grid(linewidth=0.5, color='royalblue')
# line_cross = np.array([(40, 80), (100, 50)])
# xsect = flopy.plot.PlotCrossSection(model=mf, line={'line': line_cross})
xsect = flopy.plot.PlotCrossSection(model=mf, line={'row': 50})
xsect.plot_grid()
# xsect = flopy.plot.PlotCrossSection(model=mf, line={'row': 50})
linecollection = xsect.plot_grid(color='k', alpha=0.25, lw=1)
xsect.get_extent()
# xsect.plot_bc()
hdobj = flopy.utils.HeadFile(fname)
head = hdobj.get_data()
xsect.plot_fill_between(head, color='saddlebrown', edgecolor='none', alpha=0.25)
pc = xsect.plot_array(head,
                      masked_values=[-9999.0], head=head, alpha=0.25,
                      cmap = 'Blues', lw=0,
                      vmin=0, vmax=400)
# patches = xsect.plot_ibound(head=head)
# linecollection = xsect.plot_grid()
cb = plt.colorbar(pc, shrink=0.75)
ax.set_ylim(0,400)
xlims = ax.get_xlim()
# ax.set_xlim(150,1000)

head_profile = pc.get_array()[0:170]

# xsect.plot_pathline(pth_data[3000:3001], method='all', colors='k',
#                     head=pc.get_array())
# xsect.plot_endpoint(e, direction='ending')

for a, b in enumerate(pth_data):
    b_xmin = b.x.min()/5
    b_xmax = b.x.max()/5
    head_restr = head_profile[int(b_xmin):int(b_xmax)]
    # if b.particleid[0] in np.random.choice(indices_layers[0], 100):
    # if b.particleid[0] in indices_layers[0]:
    if b.particleid[0] in indices_layers_rdm[0]:
        # if len(head_restr)>0:
        #     head_max = head_restr.max()
        #     if b.z.max()<head_max:
        ax.plot(b.x, b.z, color='red', lw=0.5)
    # if b.particleid[0] in np.random.choice(indices_layers[1], 100):
    # if b.particleid[0] in indices_layers[1]:
    if b.particleid[0] in indices_layers_rdm[1]:
        # if len(head_restr)>0:
        #     head_max = head_restr.max()
        #     if b.z.max()<head_max:
        ax.plot(b.x, b.z, color='blue', lw=0.5)

#%% ELEVATION DISCHARGE ALL - ALONG RIVERS

acc_masked = np.ma.masked_where(acc <= acc.mean(), acc)
down_masked = np.ma.masked_array(down, mask=acc_masked.mask)

fig, (ax1, ax2) = plt.subplots(1,2, figsize=(8,3))
ax1.imshow(acc_masked)
ax1.set_title('Cumulated flux')
ax2.imshow(down_masked)
ax2.set_title('Downslope lengths')

fig, ax = plt.subplots(1,1, figsize=(6,3))
s = ax.scatter(down, dem_masked, marker='_', lw=3, c=acc_masked,
               s=20,
               # norm=matplotlib.colors.LogNorm()
               )
ax.set_xlabel('Distance [m]')
ax.set_ylabel('Elevation [m]')
cb = fig.colorbar(s)
cb.set_label('Discharge [m3/j]', rotation= 270, labelpad=25)
ax.invert_xaxis()

#%% DISCHARGE RED/BLUE - ALONG RIVERS

"""
acc_masked = np.ma.masked_where(acc <= 0, acc)
down_masked = np.ma.masked_array(down, mask=acc_masked.mask)

fig, ax = plt.subplots(1,1, figsize=(6,3))
s = ax.scatter(down, acc_masked, marker='_', lw=3, color='k',
               s=20,
               # norm=matplotlib.colors.LogNorm()
               )
ax.set_xlabel('Distance [m]')
ax.set_ylabel('Disharge [m3/J]')
# cb = fig.colorbar(s)
# cb.set_label('Discharge [m3/j]', rotation= 270, labelpad=25)
ax.invert_xaxis()
"""

# acc_flux = imageio.imread(simulations_folder+model_name+'/_watershed/_tifs/'+
#                           'accumulation_flux_t(0).tif')
acc_flux = imageio.imread(simulations_folder+model_name+'/_watershed/_tifs/'+
                          'outflow_drain_t(0).tif')
acc_mask = np.ma.masked_where(dem.read(1) < -100, acc_flux)
acc_mask = acc_mask.filled(np.nan)
acc_mask[acc_mask<=0] = np.nan

def flatten_on_xy(x):
    XX,YY = np.meshgrid(np.arange(x.shape[1]),np.arange(x.shape[0]))
    table = np.vstack((x.ravel(),XX.ravel(),YY.ravel())).T
    return table

flat_acc = flatten_on_xy(acc_mask)
flat_acc = pd.DataFrame(flat_acc)
flat_acc = flat_acc.dropna()
flat_acc[0] = flat_acc[0] / 24 / 3600 * 1000
# plt.plot(flat_acc[0], c='k')
flat_cum_acc = flat_acc.groupby(1).sum() # flat_acc = flat_acc.agg({0: "nunique"})
flat_cum_acc[3] = flat_cum_acc[0].cumsum() # 3 is cumulated on sum xaxis in 1

h = 0
res_time = np.zeros(np.shape(dem))
res_count = np.zeros(np.shape(dem))
for j in range(len(e)):
    # time_out = pth_data[j].time[0] # explore pathlines
    # res_time[e[j].i0,e[j].j0] = np.log10(e[j].time) # where infiltrated
    if e[j].particleid in indices_layers[h]:
        res_time[e[j].i,e[j].j] = (e[j].time) /365 # where outputed
        res_count[e[j].i,e[j].j] = res_count[e[j].i,e[j].j] + 1 # where outputed
res_time = np.ma.masked_where(res_time <= 0, res_time)
res_time = np.ma.masked_where(dem_data <= -100, res_time)
res_time = res_time.filled(np.nan)
res_time[res_time<=0] = np.nan
res_time[dem_data<=0] = np.nan
# res_count = res_count - 1
res_count = np.ma.masked_where(res_count <= 0, res_count)
res_count = np.ma.masked_where(dem_data <= -100, res_count)
res_count = res_count.filled(np.nan)
res_count[res_count<=0] = np.nan
res_count[dem_data<=0] = np.nan
res_count = np.ma.masked_invalid(res_count)

acc_deep = np.ma.array(acc_mask, mask=res_count.mask)
acc_deep = acc_deep.filled(np.nan)
flat_deep = flatten_on_xy(acc_deep)
flat_deep = pd.DataFrame(flat_deep)
flat_deep = flat_deep.dropna()
flat_deep[0] = flat_deep[0] / 24 / 3600 * 1000
# plt.plot(flat_deep[0], c='r')
flat_cum_deep = flat_deep.groupby(1).sum() # flat_acc = flat_acc.agg({0: "nunique"})
flat_cum_deep[3] = flat_cum_deep[0].cumsum()

h = 1
res_time = np.zeros(np.shape(dem))
res_count = np.zeros(np.shape(dem))
for j in range(len(e)):
    # time_out = pth_data[j].time[0] # explore pathlines
    # res_time[e[j].i0,e[j].j0] = np.log10(e[j].time) # where infiltrated
    if e[j].particleid in indices_layers[h]:
        res_time[e[j].i,e[j].j] = (e[j].time) /365 # where outputed
        res_count[e[j].i,e[j].j] = res_count[e[j].i,e[j].j] + 1 # where outputed
res_time = np.ma.masked_where(res_time <= 0, res_time)
res_time = np.ma.masked_where(dem_data <= -100, res_time)
res_time = res_time.filled(np.nan)
res_time[res_time<=0] = np.nan
res_time[dem_data<=0] = np.nan
res_count = res_count - 1
res_count = np.ma.masked_where(res_count <= 0, res_count)
res_count = np.ma.masked_where(dem_data <= -100, res_count)
res_count = res_count.filled(np.nan)
res_count[res_count<=0] = np.nan
res_count[dem_data<=0] = np.nan
res_count = np.ma.masked_invalid(res_count)

acc_shal = np.ma.array(acc_mask, mask=res_count.mask)
acc_shal = acc_shal.filled(np.nan)
flat_shal = flatten_on_xy(acc_shal)
flat_shal = pd.DataFrame(flat_shal)
flat_shal = flat_shal.dropna()
flat_shal[0] = flat_shal[0] / 24 / 3600 * 1000 # m3/j to L/s
# plt.plot(flat_shal[0], c='b')
flat_cum_shal = flat_shal.groupby(1).sum() # flat_acc = flat_acc.agg({0: "nunique"})
flat_cum_shal[3] = flat_cum_shal[0].cumsum()

# plt.plot(flat_acc[0], c='k', lw=0, marker='.')
# plt.plot(flat_shal[0], c='b', lw=0, marker='.')
# plt.plot(flat_deep[0], c='r', lw=0, marker='.')

flat_acc = flat_acc.reset_index()
flat_acc = flat_acc.set_index(flat_acc[1])
flat_shal = flat_shal.reset_index()
flat_shal = flat_shal.set_index(flat_shal[1])
flat_deep = flat_deep.reset_index()
flat_deep = flat_deep.set_index(flat_deep[1])

fig, ax = plt.subplots(1,1, figsize=(5,3))
axb = ax.twinx()
axb.plot(dem_data.min(axis=0), color='saddlebrown', lw=2)
axb.set_ylabel('Elevation [m]', rotaTion=270, labelpad=25)
# axb.set_zorder(ax.get_zorder() - 1)
ax.patch.set_visible(False)
# axb.plot(flat_cum_acc.index, flat_cum_acc[0], c='k', lw=0, marker='_', ms=10, alpha=0.7, zorder=0)
# axb.plot(flat_cum_shal.index, flat_cum_shal[0], c='b', lw=0, marker='_', ms=10, alpha=0.7, zorder=0)
# axb.plot(flat_cum_deep.index, flat_cum_deep[0], c='r', lw=0, marker='_', ms=10, alpha=0.7, zorder=0)
ax.plot(flat_cum_acc.index, flat_cum_acc[3], c='k', lw=0, marker='.', ms=5, zorder=1)
ax.plot(flat_cum_shal.index, flat_cum_shal[3], c='b', lw=0, marker='.', ms=5, zorder=1)
ax.plot(flat_cum_deep.index, flat_cum_deep[3], c='r', lw=0, marker='.', ms=5, zorder=1)
# ax.set_xlim(60, 160)
# ax.set_ylim(0, 10)
ax.set_xlim(0, )
ax.set_xlabel('Pixels on X axis')
ax.set_ylabel('Discharge [L/s]')
ax.axvline(x=130, c='k', ls='--')

ax.set_xlim(0,150)

plt.tight_layout()

#%% FLOWPATHS RED/BLUE - ALONG RIVERS

color_layers = ['darkred', 'blue']

fig, ax = plt.subplots(1,1, figsize=(5,3))    
axb = ax.twinx()

h = 1
res_time = np.zeros(np.shape(dem))
res_count = np.zeros(np.shape(dem))
for j in range(len(e)):
    # time_out = pth_data[j].time[0] # explore pathlines
    # res_time[e[j].i0,e[j].j0] = np.log10(e[j].time) # where infiltrated
    if e[j].particleid in indices_layers[h]:
        res_time[e[j].i,e[j].j] = (e[j].time) /365 # where outputed
        res_count[e[j].i,e[j].j] = res_count[e[j].i,e[j].j] + 1 # where outputed
        
res_time = np.ma.masked_where(res_time < 0, res_time)
res_time = np.ma.masked_where(dem_data < -100, res_time)
res_time = res_time.filled(np.nan)
res_time[res_time<0] = np.nan
res_time[dem_data<0] = np.nan
flat_res = flatten_on_xy(res_time)
flat_res = pd.DataFrame(flat_res)
flat_res = flat_res.dropna()

res_count = np.ma.masked_where(res_count < 0, res_count)
res_count = np.ma.masked_where(dem_data < -100, res_count)
res_count = res_count.filled(np.nan)
res_count[res_count<0] = np.nan
res_count[dem_data<0] = np.nan
flat_cts = flatten_on_xy(res_count)
flat_cts = pd.DataFrame(flat_cts)
flat_cts = flat_cts.dropna()
flat_cts = flat_res.groupby(1)
flat_cts = flat_cts.agg({0: "nunique"})

ax = ax
# ax.plot(flat_acc[:,1], flat_acc[:,0], color='k', lw=2)
# ax.step(flat_acc[:,1], flat_acc[:,0], color='k', lw=3)
# ax.fill_between(flat_acc.iloc[:][1], 0, flat_acc.iloc[:][0], lw=2)
ax.scatter(flat_res[1], flat_res[0], c='dodgerblue', lw=0, s=20,
           alpha=0.2, marker='o')
# axb.plot(flat_cts.index, flat_cts[0], c='navy', lw=2,
#            alpha=1)

h = 0
res_time = np.zeros(np.shape(dem))
res_count = np.zeros(np.shape(dem))
for j in range(len(e)):
    # time_out = pth_data[j].time[0] # explore pathlines
    # res_time[e[j].i0,e[j].j0] = np.log10(e[j].time) # where infiltrated
    if e[j].particleid in indices_layers[h]:
        res_time[e[j].i,e[j].j] = (e[j].time) /365 # where outputed
        res_count[e[j].i,e[j].j] = res_count[e[j].i,e[j].j] + 1 # where outputed
        
res_time = np.ma.masked_where(res_time < 0, res_time)
res_time = np.ma.masked_where(dem_data < -100, res_time)
res_time = res_time.filled(np.nan)
res_time[res_time<0] = np.nan
res_time[dem_data<0] = np.nan
flat_res = flatten_on_xy(res_time)
flat_res = pd.DataFrame(flat_res)
flat_res = flat_res.dropna()

res_count = np.ma.masked_where(res_count < 0, res_count)
res_count = np.ma.masked_where(dem_data < -100, res_count)
res_count = res_count.filled(np.nan)
res_count[res_count<0] = np.nan
res_count[dem_data<0] = np.nan
flat_cts = flatten_on_xy(res_count)
flat_cts = pd.DataFrame(flat_cts)
flat_cts = flat_cts.dropna()
flat_cts = flat_res.groupby(1)
flat_cts = flat_cts.agg({0: "nunique"})

ax = ax
# ax.plot(flat_acc[:,1], flat_acc[:,0], color='k', lw=2)
# ax.step(flat_acc[:,1], flat_acc[:,0], color='k', lw=3)
# ax.fill_between(flat_acc.iloc[:][1], 0, flat_acc.iloc[:][0], lw=2)
ax.scatter(flat_res[1], flat_res[0], c='red', lw=0, s=20,
           alpha=0.2, marker='o')
# axb.plot(flat_cts.index, flat_cts[0], c='darkred', lw=2,
#            alpha=1)

# ax.set_xlim(60, 160)
ax.set_ylim(1, 1000)
ax.set_xlabel('Pixels on X axis')
ax.set_ylabel('Residence times [y]')
ax.axvline(x=130, c='k', ls='--')

axb.plot(dem_data.min(axis=0), color='saddlebrown', lw=2)
axb.set_ylabel('Elevation [m]', rotaTion=270, labelpad=25)
# axb.set_xlim(60, 160)
# axb.set_ylim(1, None)
# axb.set_ylabel('Count flowpaths', rotation=270, labelpad=30)

ax.set_yscale('log')

ax.set_xlim(0,150)

plt.tight_layout()

# fig.savefig(simulations_folder + '/' + model_name + '/' +'_figures/' + 
#             'Times and counts'+'.png', dpi=300, bbox_inches='tight')

#%% CONCENTRATION SR - ALON RIVERS

# idx_x = list(pd.DataFrame(flatten_on_xy(acc_flux)).index)
# idx_x = pd.DataFrame(flatten_on_xy(acc_flux))

idx_x = np.arange(0, dem_data.shape[1], 1)
flat_flux = pd.DataFrame(index=idx_x)
flat_flux['Qriv'] = flat_cum_acc[3]
flat_flux['Qdeep'] = flat_cum_deep[0]
flat_flux['Qshal'] = flat_cum_shal[0]
first_index = flat_flux['Qriv'].first_valid_index()
flat_flux = flat_flux[first_index:]
flat_flux = flat_flux.fillna(0)

for i in flat_flux.index:
    if i == first_index:
        print(i)
        nomin = (0.02*flat_flux.loc[i,'Qriv'])+ \
                (1.1*flat_flux.loc[i,'Qdeep'])+ \
                (0.02*flat_flux.loc[i,'Qshal'])
        denom = flat_flux.loc[i,'Qriv'] + flat_flux.loc[i,'Qdeep'] + flat_flux.loc[i,'Qshal']
        if denom == 0 :
            denom = 1
        flat_flux.loc[i,'Csr_riv'] = nomin / denom
    else:
        nomin = (flat_flux.loc[i-1,'Csr_riv']*flat_flux.loc[i-1,'Qriv'])+ \
                                       (1.1*flat_flux.loc[i,'Qdeep'])+ \
                                       (0.02*flat_flux.loc[i,'Qshal'])
        denom = flat_flux.loc[i-1,'Qriv'] + flat_flux.loc[i,'Qdeep'] + flat_flux.loc[i,'Qshal']
        if denom == 0 :
            denom = 1
        flat_flux.loc[i,'Csr_riv'] = nomin / denom

for i in flat_flux.index:
    if i == first_index:
        print(i)
        nomin = (0.7092*flat_flux.loc[i,'Csr_riv']*flat_flux.loc[i,'Qriv'])+ \
                (0.7041*1.1*flat_flux.loc[i,'Qdeep'])+ \
                (0.7092*0.02*flat_flux.loc[i,'Qshal'])
        denom = (flat_flux.loc[i,'Qriv']*flat_flux.loc[i,'Csr_riv']) + \
                (flat_flux.loc[i,'Qdeep']*1.1) + \
                (flat_flux.loc[i,'Qshal']*0.02)
        if denom == 0 :
            denom = 1
        flat_flux.loc[i,'Rsr_riv'] = nomin / denom
    else:
        nomin = (flat_flux.loc[i-1,'Rsr_riv']*flat_flux.loc[i-1,'Csr_riv']*flat_flux.loc[i-1,'Qriv']) + \
                (0.7041*1.1*flat_flux.loc[i,'Qdeep']) + \
                (0.7092*0.02*flat_flux.loc[i,'Qshal'])
        denom =  (flat_flux.loc[i-1,'Qriv']*flat_flux.loc[i-1,'Csr_riv']) + \
                 (flat_flux.loc[i,'Qdeep']*1.1) + \
                 (flat_flux.loc[i,'Qshal']*0.02)
        if denom == 0 :
            denom = 1
        flat_flux.loc[i,'Rsr_riv'] = nomin / denom
      
fig, ax = plt.subplots(1,1, figsize=(4,3))    
axb = ax.twinx()
                              
ax.plot(flat_flux['Csr_riv'], c='tomato', marker='s', lw=0, mec='none')
axb.plot(flat_flux['Rsr_riv'], c='grey', ms=5, marker='s', lw=0, mec='none')
# plt.yscale('log')

# ax.set_xlim(60, 160)
# ax.set_ylim(1, None)
ax.set_xlabel('Pixels on X axis')
ax.set_ylabel('Sr Concenration', c='darkorange')
ax.axvline(x=130, c='k', ls='--')
ax.set_ylim(0, 1)

ax.set_xlim(0,150)

# axb.set_xlim(60, 160)
# axb.set_ylim(1, None)
axb.set_ylabel('Sr Ratio', c='grey', rotation=270, labelpad = 30)
axb.set_ylim(0.7040, 0.710)
axb.ticklabel_format(style='plain')
axb.ticklabel_format(useOffset=False, style='plain')

# flat_flux.to_csv(simulations_folder + '/' + model_name + '/' +'_figures/' + 
#             'q c r'+'.csv', sep=';')

# fig.savefig(simulations_folder + '/' + model_name + '/' +'_figures/' + 
#             'Concentration and Ratio Sr'+'.png', dpi=300, bbox_inches='tight')

#%% ---- OVERVIEW QUICKLY

#%% FOUR MAPS TOPVIEW

layers = [1,0]

fig, axs = plt.subplots(2,2, figsize=(6,5))    
axs = axs.ravel()

color_layers = ['red','dodgerblue']
cp = 0
for h in range(len(layers[:])):
    ax = axs[cp]
    if cp == 0:
        ax.set_title('Times for deep layer')
    else:
        ax.set_title('Times for shallow layer')
    res_time = np.zeros(np.shape(dem))
    res_count = np.zeros(np.shape(dem))
    compt=0
    for j in range(len(e)):
        # time_out = pth_data[j].time[0] # explore pathlines
        # res_time[e[j].i0,e[j].j0] = np.log10(e[j].time) # where infiltrated
        if e[j].particleid in indices_layers[h]:
            res_time[e[j].i,e[j].j] = (e[j].time) /365 # where outputed
            res_count[e[j].i,e[j].j] = res_count[e[j].i,e[j].j] + 1 # where outputed
    res_time = np.ma.masked_where(res_time <= 0, res_time)
    ax.imshow(dem_data, cmap='Greys', alpha=0.8)
    image_hidden = ax.imshow(np.ma.masked_where(BV.geographic.dem_clip<= 0, res_time),
                                  cmap='jet', vmin=0, vmax=100)
    res_count = np.ma.masked_where(res_count <= 0, res_count)
    # image_hidden = plt.imshow(np.ma.masked_where(BV.geographic.dem_clip<= 0, res_count),
    #                               cmap='jet', vmin=None, vmax=None)
    ax.get_xaxis().set_visible(False)
    ax.get_yaxis().set_visible(False)    
    cp+=1
    
cp = 2
for h in range(len(layers[:])):
    ax = axs[cp]
    if cp == 2:
        ax.set_title('Points of deep layer')
    else:
        ax.set_title('Points of shallow layer')
    # axb = ax.twinx()
    shp_pathline = gpd.read_file(simulations_folder+
                        model_name+'/'+'_pathlines/'+
                        'ending.shp')
    shp_endpoint = gpd.read_file(simulations_folder+
                        model_name+'/'+'_endpoints/'+
                        'starting.shp')
    mask_line = np.isin(shp_pathline.particleid, indices_layers[h])
    mask_point = np.isin(shp_endpoint.particleid, indices_layers[h])

    shp_pathline = shp_pathline[mask_line]
    shp_endpoint = shp_endpoint[mask_point]

    x_1 = np.array([*range(0, dem_data.shape[0], 1)])
    x = 5 * x_1      #deltaT is 2 min
    ax.imshow(dem_data, cmap='Greys', alpha=0.8,
              extent=[0,dem_data.shape[1]*5,
                      0,dem_data.shape[0]*5])
    shp_pathline.plot(ax=ax, color=color_layers[h], lw=0.05)
    shp_endpoint[shp_endpoint.time>0].plot(ax=ax, markersize=2, c=color_layers[h], lw=0)
    # ax.invert_yaxis()
    
    ax.get_xaxis().set_visible(False)
    ax.get_yaxis().set_visible(False)
    
    # ax.set_xlim(0, 170)
    # ax.set_ylim(135,0)
    # ax.set_xbound(lower=0.0, upper=170)
    # ax.set_ybound(lower=135, upper=0)
    # axb.set_xlim(0, 170)
    # axb.set_ylim(0, 135)
    
    # scale_factor = 5
    # xmin, xmax = plt.xlim()
    # ymin, ymax = plt.ylim()
    # plt.xlim(xmin / scale_factor, xmax / scale_factor)
    # plt.ylim(ymin / scale_factor, ymax / scale_factor)
        
    cp+=1

plt.tight_layout()

#%% FOUR GRAPHICS XY

fig, axs = plt.subplots(2,2, figsize=(6,5))    
axs = axs.ravel()
    
acc_flux = imageio.imread(simulations_folder+model_name+'/_watershed/_tifs/'+
                          'accumulation_flux_t(0).tif') 
acc_mask = np.ma.masked_where(dem.read(1) < -100, acc_flux)
acc_mask = acc_mask.filled(np.nan)
acc_mask[acc_mask<=0] = np.nan
time_res = imageio.imread(simulations_folder+model_name+'/_watershed/_tifs/'+
                          'residence_times_t(0).tif')
res_mask = np.ma.masked_where(dem.read(1) < -100, time_res)
res_mask = res_mask.filled(np.nan)
res_mask[res_mask<=0] = np.nan

def flatten_on_xy(x):
    XX,YY = np.meshgrid(np.arange(x.shape[1]),np.arange(x.shape[0]))
    table = np.vstack((x.ravel(),XX.ravel(),YY.ravel())).T
    return table

# plt.imshow(res_mask)

flat_acc = flatten_on_xy(acc_mask)
ax = axs[0]
ax.scatter(flat_acc[:,1], flat_acc[:,0], color='k', lw=0, s=5)
ax.set_xlim(60, 160)
ax.set_ylabel('Discharge')
ax.set_xlabel('Distance')

flat_res = flatten_on_xy(res_mask)
ax = axs[1]
ax.scatter(flat_res[:,1], flat_res[:,0], c=flat_res[:,0], lw=0, s=5)
ax.set_xlim(60, 160)
ax.set_ylabel('Residence times')
ax.set_xlabel('Distance')

# ax.invert_xaxis()
# axb.invert_xaxis()

color_layers = ['red','dodgerblue']
cp = 2
for h in range(len(layers[:])):
    ax = axs[cp]
    res_time = np.zeros(np.shape(dem))
    res_count = np.zeros(np.shape(dem))
    compt=0
    for j in range(len(e)):
        # time_out = pth_data[j].time[0] # explore pathlines
        # res_time[e[j].i0,e[j].j0] = np.log10(e[j].time) # where infiltrated
        if e[j].particleid in indices_layers[h]:
            res_time[e[j].i,e[j].j] = (e[j].time) /365 # where outputed
            res_count[e[j].i,e[j].j] = res_count[e[j].i,e[j].j] + 1 # where outputed
    res_time = np.ma.masked_where(res_time <= 0, res_time)
    # image_hidden = plt.imshow(np.ma.masked_where(BV.geographic.dem_clip<= 0, res_time),
    #                              cmap='jet', vmin=0, vmax=100)
    res_count = np.ma.masked_where(res_count <= 0, res_count)
    # image_hidden = plt.imshow(np.ma.masked_where(BV.geographic.dem_clip<= 0, res_count),
    #                               cmap='jet', vmin=None, vmax=None)
    flat_count = flatten_on_xy(res_count)
    ax.scatter(flat_count[:,1], flat_count[:,0], color=color_layers[h], lw=0, s=5)
    ax.set_xlim(60, 160)
    ax.set_ylabel('Count out particle')
    ax.set_xlabel('Distance')
    cp+=1
plt.tight_layout()

#%% CROSS FLOPY PATHLINES

### FLOPY METHOD
fig, ax = plt.subplots(1,1, figsize=(7, 3))
xsect = flopy.plot.PlotCrossSection(model=mf, line={'Row': 50})
linecollection = xsect.plot_grid(color='k', lw=1)
# Kv = np.zeros((2,106,209))
# Kv[0,:,:] = 1e-5 #first layer of lime
# Kv[1,:,:] = 1e-6 #second layer of sand
# xsect.plot_array(Kv)
xsect.get_extent()
# xsect.plot_bc()
hdobj = flopy.utils.HeadFile(fname)
head = hdobj.get_data() 
xsect.plot_fill_between(head, color='saddlebrown', edgecolor='none',
                        alpha=0.5)
pc = xsect.plot_array(head,
                      masked_values=[-9999.0], head=head, alpha=0.5,
                      cmap = 'Blues', lw=0,
                      vmin=200, vmax=400)
# patches = xsect.plot_ibound(head=head)
# linecollection = xsect.plot_grid()
cb = plt.colorbar(pc, shrink=0.75)
# ax.set_xlim(0,dem_data.shape[1]*5)
ax.set_ylim(-100,350)
# xsect.plot_pathline(pth_data[3000:3050], method='all', colors='k')
# xsect.plot_endpoint(e, direction='ending')
# keep = []
# for i, j in enumerate(pth_data[:]):
#     if (j.z<250).any():
#         print(i, len(pth_data))
#         keep.append(j)
#         ax.plot(j.x, j.z, color='red')

xlims = ax.get_xlim()
head_profile = pc.get_array()[0:170]

keep_idx = []
for i, j in enumerate(np.random.choice(pth_data,100)):
    if j.particleid[0] in indices_layers[0]:
        j_xmin = j.x.min()/5
        j_xmax = j.x.max()/5
        head_restr = head_profile[int(j_xmin):int(j_xmax)]
        # if len(head_restr)>0:
        #     head_max = head_restr.max()
        #     if j.z.max()<head_max:
        #         print(i, len(pth_data))
        #         keep_idx.append(i)
        ax.plot(j.x, j.z, color='red', lw=1)

keep_idx = []
for i, j in enumerate(np.random.choice(pth_data,100)):
    if j.particleid[0] in indices_layers[1]:
        j_xmin = j.x.min()/5
        j_xmax = j.x.max()/5
        head_restr = head_profile[int(j_xmin):int(j_xmax)]
        # if len(head_restr)>0:
        #     head_max = head_restr.max()
        #     if j.z.max()<head_max:
        #         print(i, len(pth_data))
        #         keep_idx.append(i)
        ax.plot(j.x, j.z, color='blue', lw=1)

#%% CROSS MANUAL PATHLINES

wbt.vector_lines_to_raster(stable_folder+'geographic/'+'watershed_contour.shp',
                           stable_folder+'geographic/'+'watershed_contour.tif',
                           base = stable_folder+'geographic/'+'watershed_dem.tif')
contour = imageio.imread(stable_folder+'geographic/'+'watershed_contour.tif')
contour = np.ma.masked_where(contour <= 0, contour)

# dem_data = imageio.imread(BV.geographic.watershed_dem)
wt_data = imageio.imread(simulations_folder+model_name+'/_watershed/_tifs/'+
                          'watertable_elevation_t(0).tif') 
# river_data = imageio.imread(stable_folder+'/hydrology/'+'complete.tif')

xvalues = np.linspace(-1,1,dem_data.shape[1])
yvalues = np.linspace(-1,1,dem_data.shape[0])
xx, yy = np.meshgrid(xvalues,yvalues)

# cur_x = dem_data.shape[1] /2
# cur_y = dem_data.shape[0] /2

# cur_x = 65
# cur_y = 40

dem_max = dem_data.max()
dem_prof = dem_data.astype(float)
dem_prof[dem_prof<0] = np.nan
wt_prof = wt_data.astype(float)
wt_prof[wt_prof<0] = np.nan

fig_l, ax_l = plt.subplots(1, 1, figsize=(5,8))

for i, coord in enumerate([[80,60,140,40],[100,100,140,40]]):
    cros = i
# for i, coord in enumerate([[80,60,140,40]]):

    x0, y0 = coord[0], coord[1] # These are in _pixel_ coordinates !
    x1, y1 = coord[2], coord[3]
    num = int(np.hypot(x1-x0, y1-y0))
    num = x1-x0
    # num=100
    x, y = np.linspace(x0, x1, num), np.linspace(y0, y1, num)
    zd = dem_data[y.astype(np.int), x.astype(np.int)]
    zw = wt_data[y.astype(np.int), x.astype(np.int)]
    
    # dem_h_plot = dem_prof[int(cur_y),:]
    # dem_h_plot[dem_h_plot == 0] = np.nan
    # wt_h_plot = wt_prof[int(cur_y),:]
    # wt_h_plot[wt_h_plot == 0] = np.nan
        
    dem_max = dem_data.max()
    dem_prof = dem_data.astype(float)
    dem_prof[dem_prof<0] = np.nan
    dem_plot = np.ma.masked_array(dem_data, mask=(dem_data<0))
    
    wt_prof = wt_data.astype(float)
    wt_prof[wt_prof<0] = np.nan
    
    # axs = axs.ravel()
    # ax = axs[0]
    # ax.autoscale(enable=False)
    # ax.plot(Rech)
    # ax = axs[1]
    # ax.autoscale(enable=False)
    ax_l.imshow(dem_plot, origin='lower', cmap='terrain', aspect="equal")
    ax_l.set_ylim(ax_l.get_ylim()[::-1])
    d_line = ax_l.plot((x0,x1),(y0,y1), 'k-', lw=3)
    # v_line = ax.axvline(cur_x, color='k', lw=2)
    # h_line = ax.axhline(cur_y, color='k', lw=2)

    fig, ax = plt.subplots(1, 1, figsize=(5,5), dpi=300)
    
    wt_h_fill = ax.fill_between(np.arange(x.shape[0]), 0, zw,
                                    color='dodgerblue', alpha=0.5, lw=0)
    wt_h_fill = ax.fill_between(np.arange(x.shape[0]), zw, zd,
                                    color='saddlebrown', alpha=0.5, lw=0)
    d_prof = ax.plot(np.arange(x.shape[0]), zd, 'saddlebrown', lw=2)
    d_prof = ax.plot(np.arange(x.shape[0]), zd-40, 'k', lw=2, ls='--')
    w_prof = ax.plot(np.arange(x.shape[0]), zw, 'navy', lw=2)

    if i == 0 :
        ax.set_xlim(0, 58)
        ax.set_ylim(100, 300)
        ax.axvline(40, c='k', ls='--')
        ax.set_xticks(np.arange(0,58,10))
        # ax.set_xticklabels(np.arange(0,58,10)*5)

    if i == 1 :
        ax.set_xlim(0, 37)
        ax.set_ylim(100, 300)
        ax.axvline(30, c='k', ls='--')
        ax.set_xticks(np.arange(0,37,10))
        # ax.set_xticklabels(np.arange(0,37,10)*5)

    
    # head_profile = dem_data[0][0:60].copy()
    head_profile = wt_data[0][0:60].copy()
    head_prfoile = zw[0:58]
    # head_profile = wt_data[y.astype(np.int), x.astype(np.int)].copy()
        
    # for i, j in enumerate(np.random.choice(pth_data[:],len(pth_data[:]))):
    for i, j in enumerate(np.random.choice(pth_data[:],10)):
    # for i, j in enumerate(pth_data[:]):
        if j.particleid[0] in indices_layers[0]:
            # if j.z.max() < zd.max():
            # if j.z.max() < 270:
            j_xmin = round(j.x.min()/5, 2)
            j_xmax = round(j.x.max()/5, 2)
            head_restr = head_profile[round(j_xmin):round(j_xmax)]
            # if len(head_restr)>0:
            #     head_max = head_restr.max()
            #     head_mean = head_restr.mean()
            #     # if j.z.max()<head_max:
            #     if j.z.max()<=head_max:
            #         # print(j.z.max(), head_max)
            #         # print(i, len(pth_data))
            ax.plot(j.x/5, j.z, color='navy', lw=1, marker=None)

    ax.set_xlabel('Pixels')
    ax.set_ylabel('Elevation [m]')
    
    fig.savefig(simulations_folder + '/' + model_name + '/' +'_figures/' + 
                'cross section 2D pathlines_'+str(cros)+'.png', dpi=300, bbox_inches='tight')

streams = imageio.imread(stable_folder+'hydrology/'+'L_Quiock_creek2.tif')
ax_l.imshow(np.ma.masked_where(streams<0, streams), cmap=mpl.colors.ListedColormap('navy'))
ax_l.imshow(contour, cmap=mpl.colors.ListedColormap('k'))
ax_l.invert_yaxis()

# ax_l.get_xaxis().set_visible(False)
# ax_l.get_yaxis().set_visible(False)

# fig_l.savefig(simulations_folder + '/' + model_name + '/' +'_figures/' + 
#             'cross sections map'+'.png', dpi=300, bbox_inches='tight')

#%% ---- MAPS TOVIEWS

#%% ALL RESIDENCE (MAN)

stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'

BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=dem_path, 
                              out_path=out_path,
                              load=True,
                              modflow_path=modflow_path)

dem = rasterio.open(BV.geographic.watershed_dem)
dem_data = dem.read(1)

list_path = sorted(glob.glob(simulations_folder+typ+'*'),
                    key=os.path.getmtime, reverse=True)
model_name = list_path[-1].split('\\')[-1]

compt=0
# for case, prop in zip(case_list[:], prop_list[:]):
#     for porosity in porosity_list[:]:
    
folder_results = simulations_folder + '/' + model_name + '/' + '_watershed/_tifs/'

path_res = folder_results+'residence_times_t(0).tif'
path_obs = data_path+'targets_pathlines_points.shp'
path_shp = simulations_folder + '/' + model_name + '/' + '_watershed/_shp/'
toolbox.create_folder(path_shp)
path_dat = path_shp+'residence_times_data.shp'

res_time = rasterio.open(path_res)
res_time_data = res_time.read(1)
res_time_data = res_time_data

shp_obs = gpd.read_file(path_obs)
shp_obs['geometry'] = shp_obs.geometry.buffer(100)
# shp_obs = shp_obs[['ID_station', 'geometry']]
shp_obs.to_file(path_dat, encoding='utf-8') # mode a

# wbt.extract_raster_values_at_points(
#                 path_res, 
#                 path_dat, 
#                 out_text=False)

# Method 1
wbt.raster_to_vector_polygons(
        path_res, 
        path_shp+'raster_polygonized.shp')
raster_polyg = gpd.read_file(path_shp+'raster_polygonized.shp')
intersect = gpd.overlay(shp_obs, raster_polyg, how='intersection')
intersect[intersect['VALUE']==-np.inf] = np.nan
res_dat = gpd.read_file(path_dat)
res_dat['RES_TIME'] = np.nan
res_dat['STD_TIME'] = np.nan

for ID in intersect['id'].unique():
    # threshold = 1 #year
    # threshold = threshold*365
    # threshold = np.log10(threshold)
    
    mask = (intersect[intersect['id']==ID]['VALUE'] !=0)
    
    mean_ID = np.nanmean(intersect[intersect['id']==ID]['VALUE'][mask])
    res_dat['RES_TIME'][res_dat['id']==ID] = mean_ID
    
    std_ID = np.nanstd(intersect[intersect['id']==ID]['VALUE'][mask])
    res_dat['STD_TIME'][res_dat['id']==ID] = std_ID
    
# Method 2
'''
from rasterstats import zonal_stats
stats = zonal_stats(path_dat, path_res)
# print(stats[0].keys())
# print(stats)
means = [f['mean'] for f in stats]
res_dat = gpd.read_file(path_dat)
res_dat['RES_TIME'] = means
'''

res_dat['RES_TIME'][res_dat['RES_TIME']==-np.inf] = np.nan
res_dat['STD_TIME'][res_dat['STD_TIME']==-np.inf] = np.nan
res_dat.to_file(path_shp + 'extract_RTD.shp', encoding = 'utf-8')

vmin = 0
vmax = 100

fig, ax = plt.subplots(1,1, figsize=(5,5))
# plt.imshow(res_time_data)
# plt.colorbar()

## Modif res_time_data en annees + vmin et vmax

res_time_data = np.ma.masked_where(res_time_data <= 0, res_time_data)

#show(np.ma.masked_where(dem_data < -0, res_time_data), ax=ax, transform=dem.transform, 
# show(np.ma.masked_where(dem_data <= 0, res_time_data), ax=ax, transform=dem.transform, 
#      cmap='jet', alpha=1, zorder=2, aspect="auto", vmin=vmin, vmax=vmax)
show(res_time_data, ax=ax, transform=dem.transform, 
      cmap='jet', alpha=1, zorder=2, aspect="auto", vmin=vmin, vmax=vmax)

shp_obs.plot(ax=ax, color='none', marker='o', markersize=10,
             edgecolor='k', lw=3, zorder=30)
# res = res_dat.plot(ax=ax, cmap='jet',  marker='o', markersize=10,
#              edgecolor='k', lw=1, column='RES_TIME', zorder=30,
#              vmin=vmin, vmax=vmax)
bounds = dem.bounds
xlim = ([bounds[0], bounds[2]])
ylim = ([bounds[1], bounds[3]])
ax.set_xlim(xlim)
ax.set_ylim(ylim)
scalebar = ScaleBar(1,box_alpha=0, scale_loc = 'bottom', location='upper left')
ax.add_artist(scalebar)
ax.get_xaxis().set_visible(False)
ax.get_yaxis().set_visible(False)
ax.set_title(model_name, fontproperties=fontprop)
ax.set(aspect='equal')
sm = plt.cm.ScalarMappable(cmap='jet', norm=plt.Normalize(vmin=vmin, vmax=vmax))
# sm = plt.cm.ScalarMappable(cmap='jet')
divider = make_axes_locatable(ax)
cax = divider.append_axes(size="2%",position='right', pad=0.05)
fig.add_axes(cax)
cbar = fig.colorbar(sm, cax=cax, orientation="vertical")
cbar.ax.get_ymajorticklabels()
cbar.ax.tick_params(labelsize=10)
cbar.ax.yaxis.set_ticks_position('right')
cbar.ax.tick_params(size=2)
contour = gpd.read_file(BV.geographic.watershed_contour_shp)
contour.plot(ax=ax, lw=1.5, color='k', zorder=20, legend=False, label='Watershed')
cbar.set_ticks(list(cbar.get_ticks()))
# cbar.set_ticklabels(list(cbar.get_ticks())[::-1])
cbar.set_label('Residence times [years]', rotation=270, labelpad=25)

res_dat['coords'] = res_dat['geometry'].apply(lambda x: x.representative_point().coords[:])
res_dat['coords'] = [res_dat[0] for res_dat in res_dat['coords']]
# for idx, row in res_dat.iterrows():
#     row['coords'] = (row['coords'][0], row['coords'][1]+100)
#     ax.annotate(s=row['id'], xy=row['coords'],
#                  horizontalalignment='center')

# fig.savefig(res_path+model_name+'.png', dpi=300, bbox_inches='tight')

'''
fig, ax = plt.subplots(1,1, figsize=(4,4))
mean_obs = res_dat[['CFC11', 'CFC12', 'CFC113']].mean(axis=1)
std_obs = res_dat[['CFC11', 'CFC12', 'CFC113']].std(axis=1)
x=2021-(mean_obs)
xerr=std_obs
mean_sim = res_dat['RES_TIME']
y=mean_sim
yerr = res_dat['STD_TIME']
ax.scatter(x, y, c=y, s=50, cmap=mpl.colors.ListedColormap('k'))
plt.errorbar(x, y , xerr=list(xerr), yerr=yerr, lw=1, fmt="o", color='k')
# ax.legend()
ax.set_xlabel('$Age_{obs}$ [years]')
ax.set_ylabel('$Age_{sim}$ [years]')
ax.set_title(model_name, fontproperties=fontprop)
for i, txt in enumerate(res_dat.id):
    ax.annotate(txt, (x[i], y[i]))
xn=20
xx=80
yn=20
yx=80
ax.set_xlim(xn, xx)
# ax.set_ylim(yn, yx)
# ax.set_xscale('log')
# ax.set_yscale('log')
# ax.plot(np.linspace(xn,xx,50), np.linspace(yn,yx,50), 
#         linestyle='--', color='grey', linewidth=2, zorder=-1)
maxx = max(ax.get_xlim()[0],ax.get_xlim()[1])
maxy = max(ax.get_ylim()[0],ax.get_ylim()[1])
minx = min(ax.get_xlim()[0],ax.get_xlim()[1])
miny = min(ax.get_ylim()[0],ax.get_ylim()[1])
maxt = max(maxx,maxy)
mint = max(minx,miny)
ax.plot(np.linspace(mint,maxt,50),
        np.linspace(mint,maxt,50), 
        linestyle='--', color='grey', linewidth=2, zorder=-1)

fig.savefig(res_path+'obs_vs_sim_'+model_name+'.png', dpi=300, bbox_inches='tight')
'''

if compt==0:
    all_dat = res_dat.copy()
all_dat[model_name] = res_dat['RES_TIME']

compt+=1

# all_dat['coords'] = np.nan
# all_dat.to_file(simulations_folder+'residence_times_all.shp', sep=';', encoding='utf-8')

# fig.savefig(simulations_folder + '/' + model_name + '/' +'_figures/' + 
#             'map_residence_time_all'+'.png', dpi=300, bbox_inches='tight')

#%% RDM PATHLINES (HMP)

stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'

BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=dem_path, 
                              out_path=out_path,
                              load=True,
                              modflow_path=modflow_path)

dem = rasterio.open(BV.geographic.watershed_dem)
dem_data = dem.read(1)

list_path = sorted(glob.glob(simulations_folder+typ+'*'),
                    key=os.path.getmtime, reverse=True)
model_name = list_path[-1].split('\\')[-1]

compt=0
# for case, prop in zip(case_list[:], prop_list[:]):
#     for porosity in porosity_list[:]:
    
folder_results = simulations_folder + '/' + model_name + '/' + '_watershed/_tifs/'

##### LOOOP 2D #####
visu = visualization.Visualization(BV, model_name)
# visu.visual2D(object_list = ['map','grid', 'watertable', 'watertable_depth','drain_flow','surface_flow','pathlines', 'residence_times'],
              # color_scale = [(None,None),(0,140),(0,140),(0,2),(None,None),(None,None),(None,None),(None,None)], lines=10000)
visu.visual2D(object_list = ['pathlines'],
              color_scale = [(None,None)], lines=100)

#%% SEP RESIDENCE AND COUNTS (MAN)

wbt.vector_lines_to_raster(stable_folder+'geographic/'+'watershed_contour.shp',
                           stable_folder+'geographic/'+'watershed_contour.tif',
                           base = stable_folder+'geographic/'+'watershed_dem.tif')
contour = imageio.imread(stable_folder+'geographic/'+'watershed_contour.tif')
contour = np.ma.masked_where(contour <= 0, contour)
    
fig, ax = plt.subplots(1,1, figsize=(5,5))    
for h in [0]:
    ax = ax
    ax.set_title('Residence time from deep layer', fontsize=10)
    res_time = np.zeros(np.shape(dem))
    res_count = np.zeros(np.shape(dem))
    for j in range(len(e)):
        # time_out = pth_data[j].time[0] # explore pathlines
        # res_time[e[j].i0,e[j].j0] = np.log10(e[j].time) # where infiltrated
        if e[j].particleid in indices_layers[h]:
            res_time[e[j].i,e[j].j] = (e[j].time) /365 # where outputed
    ax.imshow(np.ma.masked_where(dem_data<0, dem_data), cmap='Greys', alpha=0.8)
    res_time = np.ma.masked_where(res_time <= 0, res_time)
    image_hidden = ax.imshow((res_time),cmap='jet', vmin=0, vmax=100)
    ax.get_xaxis().set_visible(False)
    ax.get_yaxis().set_visible(False)
    ax.imshow(contour, cmap=mpl.colors.ListedColormap('k'))
# fig.savefig(simulations_folder + '/' + model_name + '/' +'_figures/' + 
#             'Residence time from deep layer'+'.png', dpi=300, bbox_inches='tight')
    
fig, ax = plt.subplots(1,1, figsize=(5,5))    
for h in [0]:
    ax = ax
    ax.set_title('Flowpath count from deep layer', fontsize=10)
    res_time = np.zeros(np.shape(dem))
    res_count = np.zeros(np.shape(dem))
    for j in range(len(e)):
        # time_out = pth_data[j].time[0] # explore pathlines
        # res_time[e[j].i0,e[j].j0] = np.log10(e[j].time) # where infiltrated
        if e[j].particleid in indices_layers[h]:
            res_time[e[j].i,e[j].j] = (e[j].time) /365 # where outputed
            res_count[e[j].i,e[j].j] = res_count[e[j].i,e[j].j] + 1 # where outputed
    ax.imshow(np.ma.masked_where(dem_data<0, dem_data), cmap='Greys', alpha=0.8)
    res_count = np.ma.masked_where(res_count <= 0, res_count)
    image_hidden = ax.imshow(res_count,
                                  cmap='jet', vmin=None, vmax=None)
    ax.get_xaxis().set_visible(False)
    ax.get_yaxis().set_visible(False)   
    ax.imshow(contour, cmap=mpl.colors.ListedColormap('k'), zorder=10)
# fig.savefig(simulations_folder + '/' + model_name + '/' +'_figures/' + 
#             'Flowpath count from deep layer'+'.png', dpi=300, bbox_inches='tight')
    
fig, ax = plt.subplots(1,1, figsize=(5,5))    
for h in [1]:
    ax = ax
    ax.set_title('Residence time from shallow layer', fontsize=10)
    res_time = np.zeros(np.shape(dem))
    res_count = np.zeros(np.shape(dem))
    for j in range(len(e)):
        # time_out = pth_data[j].time[0] # explore pathlines
        # res_time[e[j].i0,e[j].j0] = np.log10(e[j].time) # where infiltrated
        if e[j].particleid in indices_layers[h]:
        # if e[j].particleid in e.particleid:
            res_time[e[j].i,e[j].j] = (e[j].time) /365 # where outputed
    ax.imshow(np.ma.masked_where(dem_data<0, dem_data), cmap='Greys', alpha=0.8)
    res_time = np.ma.masked_where(res_time <= 0, res_time)
    image_hidden = ax.imshow((res_time), cmap='jet', vmin=0, vmax=100)
    ax.get_xaxis().set_visible(False)
    ax.get_yaxis().set_visible(False)
    ax.imshow(contour, cmap=mpl.colors.ListedColormap('k'))
# fig.savefig(simulations_folder + '/' + model_name + '/' +'_figures/' + 
#             'Residence time from shallow layer'+'.png', dpi=300, bbox_inches='tight')
    
fig, ax = plt.subplots(1,1, figsize=(5,5))    
for h in [1]:
    ax = ax
    ax.set_title('Flowpath count from shallow layer', fontsize=10)
    res_time = np.zeros(np.shape(dem))
    res_count = np.zeros(np.shape(dem))
    for j in range(len(e)):
        # time_out = pth_data[j].time[0] # explore pathlines
        # res_time[e[j].i0,e[j].j0] = np.log10(e[j].time) # where infiltrated
        if e[j].particleid in indices_layers[h]:
            res_time[e[j].i,e[j].j] = (e[j].time) /365 # where outputed
            res_count[e[j].i,e[j].j] = res_count[e[j].i,e[j].j] + 1 # where outputed
    ax.imshow(np.ma.masked_where(dem_data<0, dem_data), cmap='Greys', alpha=0.8)
    res_count = np.ma.masked_where(res_count <= 0, res_count)
    image_hidden = ax.imshow(res_count,
                                  cmap='jet', vmin=None, vmax=None)
    ax.get_xaxis().set_visible(False)
    ax.get_yaxis().set_visible(False)   
    ax.imshow(contour, cmap=mpl.colors.ListedColormap('k'), zorder=10)
# fig.savefig(simulations_folder + '/' + model_name + '/' +'_figures/' + 
#             'Flowpath count from shallow layer'+'.png', dpi=300, bbox_inches='tight')
    
#%% SEP PATHLINES AND ENDPOINTS (MAN)

wbt.vector_lines_to_raster(stable_folder+'geographic/'+'watershed_contour.shp',
                           stable_folder+'geographic/'+'watershed_contour.tif',
                           base = stable_folder+'geographic/'+'watershed_dem.tif')
contour = imageio.imread(stable_folder+'geographic/'+'watershed_contour.tif')
contour = np.ma.masked_where(contour <= 0, contour)
streams = imageio.imread(stable_folder+'hydrology/'+'L_Quiock_creek2.tif')

color_layers = ['darkred', 'blue']

h=0
fig, ax = plt.subplots(1,1, figsize=(5,5))    
ax = ax
ax.set_title('Pathlines in deep layer from starting points', fontsize=10)
shp_pathline = gpd.read_file(simulations_folder+
                    model_name+'/'+'_pathlines/'+
                    'ending.shp')
shp_endpoint = gpd.read_file(simulations_folder+
                    model_name+'/'+'_pathlines/'+
                    'starting.shp')
mask_line = np.isin(shp_pathline.particleid, indices_layers[h])
mask_point = np.isin(shp_endpoint.particleid, indices_layers[h])
shp_pathline = shp_pathline[mask_line]
shp_endpoint = shp_endpoint[mask_point]
x_1 = np.array([*range(0, dem_data.shape[0], 1)])
x = 5 * x_1  # delta T is 2 min
# ax.imshow(np.ma.masked_where(dem_data<0, dem_data), cmap='Greys', alpha=0.8,
#           extent=[0,dem_data.shape[1]*5,
#                   0,dem_data.shape[0]*5])
shp_endpoint[shp_endpoint.time>0].plot(ax=ax, markersize=20,
                                       c='lightgrey', lw=0,
                                       alpha=1, zorder=1)
shp_pathline.plot(ax=ax, color=color_layers[h], lw=0.05, zorder=2)
ax.imshow(np.ma.masked_where(streams<=0, streams), cmap=mpl.colors.ListedColormap('navy'), 
          extent=[0,dem_data.shape[1]*5,
                  0,dem_data.shape[0]*5], zorder=3)
ax.imshow(contour, cmap=mpl.colors.ListedColormap('k'), 
          extent=[0,dem_data.shape[1]*5,
                  0,dem_data.shape[0]*5], zorder=4)
ax.get_xaxis().set_visible(False)
ax.get_yaxis().set_visible(False)  
fig.tight_layout()
# fig.savefig(simulations_folder + '/' + model_name + '/' +'_figures/' + 
#             'Pathlines in deep layer from starting points'+'.png', dpi=300, bbox_inches='tight')
     
h=1
fig, ax = plt.subplots(1,1, figsize=(5,5))    
ax = ax
ax.set_title('Pathlines in shallow layer from starting points', fontsize=10)
shp_pathline = gpd.read_file(simulations_folder+
                    model_name+'/'+'_pathlines/'+
                    'ending.shp')
shp_endpoint = gpd.read_file(simulations_folder+
                    model_name+'/'+'_pathlines/'+
                    'starting.shp')
mask_line = np.isin(shp_pathline.particleid, indices_layers[h])
mask_point = np.isin(shp_endpoint.particleid, indices_layers[h])
shp_pathline = shp_pathline[mask_line]
shp_endpoint = shp_endpoint[mask_point]
x_1 = np.array([*range(0, dem_data.shape[0], 1)])
x = 5 * x_1  # delta T is 2 min
# ax.imshow(np.ma.masked_where(dem_data<0, dem_data), cmap='Greys', alpha=0.8,
#           extent=[0,dem_data.shape[1]*5,
#                   0,dem_data.shape[0]*5])
shp_endpoint[shp_endpoint.time>0].plot(ax=ax, markersize=20,
                                       c='lightgrey', lw=0,
                                       alpha=1, zorder=1)
shp_pathline.plot(ax=ax, color=color_layers[h], lw=0.05, zorder=2)
ax.imshow(np.ma.masked_where(streams<=0, streams), cmap=mpl.colors.ListedColormap('navy'), 
          extent=[0,dem_data.shape[1]*5,
                  0,dem_data.shape[0]*5], zorder=3)
ax.imshow(contour, cmap=mpl.colors.ListedColormap('k'), 
          extent=[0,dem_data.shape[1]*5,
                  0,dem_data.shape[0]*5], zorder=4)
ax.get_xaxis().set_visible(False)
ax.get_yaxis().set_visible(False)  
fig.tight_layout()
# fig.savefig(simulations_folder + '/' + model_name + '/' +'_figures/' + 
#             'Pathlines in shallow layer from starting points'+'.png', dpi=300, bbox_inches='tight')

#%% ---- GRAPHICS XY ON X

#%% DISCHARGE

# acc_flux = imageio.imread(simulations_folder+model_name+'/_watershed/_tifs/'+
#                           'outflow_drain_t(0).tif')

acc_flux = imageio.imread(simulations_folder+model_name+'/_watershed/_tifs/'+
                          'accumulation_flux_t(0).tif')
acc_mask = np.ma.masked_where(dem.read(1) < -100, acc_flux)

acc_mask = acc_mask.filled(np.nan)
acc_mask[acc_mask<=0] = np.nan

# time_res = imageio.imread(simulations_folder+model_name+'/_watershed/_tifs/'+
#                           'residence_times_t(0).tif')
# res_mask = np.ma.masked_where(dem.read(1) < -100, time_res)
# res_mask = res_mask.filled(np.nan)
# res_mask[res_mask<=0] = np.nan

def flatten_on_xy(x):
    XX,YY = np.meshgrid(np.arange(x.shape[1]),np.arange(x.shape[0]))
    table = np.vstack((x.ravel(),XX.ravel(),YY.ravel())).T
    return table

flat_acc = flatten_on_xy(acc_mask)
flat_acc = pd.DataFrame(flat_acc)
flat_acc = flat_acc.dropna()
flat_acc[0] = flat_acc[0] / 24 / 3600 * 1000

fig, ax = plt.subplots(1,1, figsize=(4.5,4))    
ax = ax
# ax.plot(flat_acc[:,1], flat_acc[:,0], color='k', lw=2)
# ax.step(flat_acc[:,1], flat_acc[:,0], color='k', lw=3)
# ax.fill_between(flat_acc.iloc[:][1], 0, flat_acc.iloc[:][0], lw=2)
ax.scatter(flat_acc.iloc[:][1], flat_acc.iloc[:][0], color='k', lw=0, s=20)
ax.set_xlim(60, 160)
ax.set_ylim(0, 10)
ax.set_xlabel('Pixels on X axis')
ax.set_ylabel('Dicharge on Y axis [L/s]')
ax.axvline(x=130, c='k', ls='--')
plt.tight_layout()

# fig.savefig(simulations_folder + '/' + model_name + '/' +'_figures/' + 
#             'Discharge'+'.png', dpi=300, bbox_inches='tight')

#%% COUNTS

color_layers = ['darkred', 'blue']

fig, ax = plt.subplots(1,1, figsize=(5,4.5))    
axb = ax.twinx()

h = 1
res_time = np.zeros(np.shape(dem))
res_count = np.zeros(np.shape(dem))
for j in range(len(e)):
    # time_out = pth_data[j].time[0] # explore pathlines
    # res_time[e[j].i0,e[j].j0] = np.log10(e[j].time) # where infiltrated
    if e[j].particleid in indices_layers[h]:
        res_time[e[j].i,e[j].j] = (e[j].time) /365 # where outputed
        res_count[e[j].i,e[j].j] = res_count[e[j].i,e[j].j] + 1 # where outputed
        
res_time = np.ma.masked_where(res_time < 0, res_time)
res_time = np.ma.masked_where(dem_data < -100, res_time)
res_time = res_time.filled(np.nan)
res_time[res_time<0] = np.nan
res_time[dem_data<0] = np.nan
flat_res = flatten_on_xy(res_time)
flat_res = pd.DataFrame(flat_res)
flat_res = flat_res.dropna()

res_count = np.ma.masked_where(res_count < 0, res_count)
res_count = np.ma.masked_where(dem_data < -100, res_count)
res_count = res_count.filled(np.nan)
res_count[res_count<0] = np.nan
res_count[dem_data<0] = np.nan
flat_cts = flatten_on_xy(res_count)
flat_cts = pd.DataFrame(flat_cts)
flat_cts = flat_cts.dropna()
flat_cts = flat_res.groupby(1)
flat_cts = flat_cts.agg({0: "nunique"})

ax = ax
# ax.plot(flat_acc[:,1], flat_acc[:,0], color='k', lw=2)
# ax.step(flat_acc[:,1], flat_acc[:,0], color='k', lw=3)
# ax.fill_between(flat_acc.iloc[:][1], 0, flat_acc.iloc[:][0], lw=2)
ax.scatter(flat_res[1], flat_res[0], c='blue', lw=0, s=20,
           alpha=0.5, marker='o')

axb.plot(flat_cts.index, flat_cts[0], c='navy', lw=2,
           alpha=1)

h = 0
res_time = np.zeros(np.shape(dem))
res_count = np.zeros(np.shape(dem))
for j in range(len(e)):
    # time_out = pth_data[j].time[0] # explore pathlines
    # res_time[e[j].i0,e[j].j0] = np.log10(e[j].time) # where infiltrated
    if e[j].particleid in indices_layers[h]:
        res_time[e[j].i,e[j].j] = (e[j].time) /365 # where outputed
        res_count[e[j].i,e[j].j] = res_count[e[j].i,e[j].j] + 1 # where outputed
        
res_time = np.ma.masked_where(res_time < 0, res_time)
res_time = np.ma.masked_where(dem_data < -100, res_time)
res_time = res_time.filled(np.nan)
res_time[res_time<0] = np.nan
res_time[dem_data<0] = np.nan
flat_res = flatten_on_xy(res_time)
flat_res = pd.DataFrame(flat_res)
flat_res = flat_res.dropna()

res_count = np.ma.masked_where(res_count < 0, res_count)
res_count = np.ma.masked_where(dem_data < -100, res_count)
res_count = res_count.filled(np.nan)
res_count[res_count<0] = np.nan
res_count[dem_data<0] = np.nan
flat_cts = flatten_on_xy(res_count)
flat_cts = pd.DataFrame(flat_cts)
flat_cts = flat_cts.dropna()
flat_cts = flat_res.groupby(1)
flat_cts = flat_cts.agg({0: "nunique"})

ax = ax
# ax.plot(flat_acc[:,1], flat_acc[:,0], color='k', lw=2)
# ax.step(flat_acc[:,1], flat_acc[:,0], color='k', lw=3)
# ax.fill_between(flat_acc.iloc[:][1], 0, flat_acc.iloc[:][0], lw=2)
ax.scatter(flat_res[1], flat_res[0], c='red', lw=0, s=20,
           alpha=0.5, marker='s')

axb.plot(flat_cts.index, flat_cts[0], c='darkred', lw=2,
           alpha=1)

# ax.set_xlim(60, 160)
# ax.set_ylim(1, None)
ax.set_xlabel('Pixels on X axis')
ax.set_ylabel('Residence times on Y axis [y]')
ax.axvline(x=130, c='k', ls='--')

# axb.set_xlim(60, 160)
# axb.set_ylim(1, None)
axb.set_ylabel('Count output flowpaths', rotation=270, labelpad=30)

plt.tight_layout()

# fig.savefig(simulations_folder + '/' + model_name + '/' +'_figures/' + 
#             'Times and counts'+'.png', dpi=300, bbox_inches='tight')

#%% CONCENTRATION

# acc_flux = imageio.imread(simulations_folder+model_name+'/_watershed/_tifs/'+
#                           'accumulation_flux_t(0).tif')
acc_flux = imageio.imread(simulations_folder+model_name+'/_watershed/_tifs/'+
                          'outflow_drain_t(0).tif')
acc_mask = np.ma.masked_where(dem.read(1) < -100, acc_flux)
acc_mask = acc_mask.filled(np.nan)
acc_mask[acc_mask<=0] = np.nan

def flatten_on_xy(x):
    XX,YY = np.meshgrid(np.arange(x.shape[1]),np.arange(x.shape[0]))
    table = np.vstack((x.ravel(),XX.ravel(),YY.ravel())).T
    return table

flat_acc = flatten_on_xy(acc_mask)
flat_acc = pd.DataFrame(flat_acc)
flat_acc = flat_acc.dropna()
flat_acc[0] = flat_acc[0] / 24 / 3600 * 1000
# plt.plot(flat_acc[0], c='k')
flat_cum_acc = flat_acc.groupby(1).sum() # flat_acc = flat_acc.agg({0: "nunique"})
flat_cum_acc[3] = flat_cum_acc[0].cumsum() # 3 is cumulated on sum xaxis in 1

h = 0
res_time = np.zeros(np.shape(dem))
res_count = np.zeros(np.shape(dem))
for j in range(len(e)):
    # time_out = pth_data[j].time[0] # explore pathlines
    # res_time[e[j].i0,e[j].j0] = np.log10(e[j].time) # where infiltrated
    if e[j].particleid in indices_layers[h]:
        res_time[e[j].i,e[j].j] = (e[j].time) /365 # where outputed
        res_count[e[j].i,e[j].j] = res_count[e[j].i,e[j].j] + 1 # where outputed
res_time = np.ma.masked_where(res_time <= 0, res_time)
res_time = np.ma.masked_where(dem_data <= -100, res_time)
res_time = res_time.filled(np.nan)
res_time[res_time<=0] = np.nan
res_time[dem_data<=0] = np.nan
# res_count = res_count - 1
res_count = np.ma.masked_where(res_count <= 0, res_count)
res_count = np.ma.masked_where(dem_data <= -100, res_count)
res_count = res_count.filled(np.nan)
res_count[res_count<=0] = np.nan
res_count[dem_data<=0] = np.nan
res_count = np.ma.masked_invalid(res_count)

acc_deep = np.ma.array(acc_mask, mask=res_count.mask)
acc_deep = acc_deep.filled(np.nan)
flat_deep = flatten_on_xy(acc_deep)
flat_deep = pd.DataFrame(flat_deep)
flat_deep = flat_deep.dropna()
flat_deep[0] = flat_deep[0] / 24 / 3600 * 1000
# plt.plot(flat_deep[0], c='r')
flat_cum_deep = flat_deep.groupby(1).sum() # flat_acc = flat_acc.agg({0: "nunique"})
flat_cum_deep[3] = flat_cum_deep[0].cumsum()

h = 1
res_time = np.zeros(np.shape(dem))
res_count = np.zeros(np.shape(dem))
for j in range(len(e)):
    # time_out = pth_data[j].time[0] # explore pathlines
    # res_time[e[j].i0,e[j].j0] = np.log10(e[j].time) # where infiltrated
    if e[j].particleid in indices_layers[h]:
        res_time[e[j].i,e[j].j] = (e[j].time) /365 # where outputed
        res_count[e[j].i,e[j].j] = res_count[e[j].i,e[j].j] + 1 # where outputed
res_time = np.ma.masked_where(res_time <= 0, res_time)
res_time = np.ma.masked_where(dem_data <= -100, res_time)
res_time = res_time.filled(np.nan)
res_time[res_time<=0] = np.nan
res_time[dem_data<=0] = np.nan
res_count = res_count - 1
res_count = np.ma.masked_where(res_count <= 0, res_count)
res_count = np.ma.masked_where(dem_data <= -100, res_count)
res_count = res_count.filled(np.nan)
res_count[res_count<=0] = np.nan
res_count[dem_data<=0] = np.nan
res_count = np.ma.masked_invalid(res_count)

acc_shal = np.ma.array(acc_mask, mask=res_count.mask)
acc_shal = acc_shal.filled(np.nan)
flat_shal = flatten_on_xy(acc_shal)
flat_shal = pd.DataFrame(flat_shal)
flat_shal = flat_shal.dropna()
flat_shal[0] = flat_shal[0] / 24 / 3600 * 1000 # m3/j to L/s
# plt.plot(flat_shal[0], c='b')
flat_cum_shal = flat_shal.groupby(1).sum() # flat_acc = flat_acc.agg({0: "nunique"})
flat_cum_shal[3] = flat_cum_shal[0].cumsum()

# plt.plot(flat_acc[0], c='k', lw=0, marker='.')
# plt.plot(flat_shal[0], c='b', lw=0, marker='.')
# plt.plot(flat_deep[0], c='r', lw=0, marker='.')

flat_acc = flat_acc.reset_index()
flat_acc = flat_acc.set_index(flat_acc[1])
flat_shal = flat_shal.reset_index()
flat_shal = flat_shal.set_index(flat_shal[1])
flat_deep = flat_deep.reset_index()
flat_deep = flat_deep.set_index(flat_deep[1])

fig, ax = plt.subplots(1,1, figsize=(4.5,4))
axb = ax.twinx()
axb.set_zorder(ax.get_zorder() - 1)
ax.patch.set_visible(False)
# axb.plot(flat_acc[1], flat_acc[0], c='k', lw=0, marker='_', ms=10, alpha=0.7, zorder=0)
# axb.plot(flat_shal[1], flat_shal[0], c='b', lw=0, marker='_', ms=10, alpha=0.7, zorder=0)
# axb.plot(flat_deep[1], flat_deep[0], c='r', lw=0, marker='_', ms=10, alpha=0.7, zorder=0)
# axb.plot(flat_acc.index, flat_acc[0], c='k', lw=0, marker='_', ms=10, alpha=0.7, zorder=0)
# axb.plot(flat_shal.index, flat_shal[0], c='b', lw=0, marker='_', ms=10, alpha=0.7, zorder=0)
# axb.plot(flat_deep.index, flat_deep[0], c='r', lw=0, marker='_', ms=10, alpha=0.7, zorder=0)
axb.plot(flat_cum_acc.index, flat_cum_acc[0], c='k', lw=0, marker='_', ms=10, alpha=0.7, zorder=0)
axb.plot(flat_cum_shal.index, flat_cum_shal[0], c='b', lw=0, marker='_', ms=10, alpha=0.7, zorder=0)
axb.plot(flat_cum_deep.index, flat_cum_deep[0], c='r', lw=0, marker='_', ms=10, alpha=0.7, zorder=0)
ax.plot(flat_cum_acc.index, flat_cum_acc[3], c='k', lw=0, marker='.', ms=10, zorder=1)
ax.plot(flat_cum_shal.index, flat_cum_shal[3], c='b', lw=0, marker='.', ms=10, zorder=1)
ax.plot(flat_cum_deep.index, flat_cum_deep[3], c='r', lw=0, marker='.', ms=10, zorder=1)
# ax.set_xlim(60, 160)
# ax.set_ylim(0, 10)
ax.set_xlabel('Pixels on X axis')
ax.set_ylabel('Dicharge on Y axis [L/s]')
# ax.axvline(x=130, c='k', ls='--')
plt.tight_layout()

# fig.savefig(simulations_folder + '/' + model_name + '/' +'_figures/' + 
#             'Discharge on x detailed'+'.png', dpi=300, bbox_inches='tight')

# idx_x = list(pd.DataFrame(flatten_on_xy(acc_flux)).index)
# idx_x = pd.DataFrame(flatten_on_xy(acc_flux))

idx_x = np.arange(0, dem_data.shape[1], 1)
flat_flux = pd.DataFrame(index=idx_x)
flat_flux['Qriv'] = flat_cum_acc[3]
flat_flux['Qdeep'] = flat_cum_deep[0]
flat_flux['Qshal'] = flat_cum_shal[0]
first_index = flat_flux['Qriv'].first_valid_index()
flat_flux = flat_flux[first_index:]
flat_flux = flat_flux.fillna(0)

for i in flat_flux.index:
    if i == first_index:
        print(i)
        flat_flux.loc[i,'Csr_riv'] = ( (0.02*flat_flux.loc[i,'Qriv'])+
                                       (1.1*flat_flux.loc[i,'Qdeep'])+
                                       (0.02*flat_flux.loc[i,'Qshal']) ) / (
                                       flat_flux.loc[i,'Qriv'] + flat_flux.loc[i,'Qdeep'] + flat_flux.loc[i,'Qshal']
                                       )
    else:
        flat_flux.loc[i,'Csr_riv'] = ( (flat_flux.loc[i-1,'Csr_riv']*flat_flux.loc[i-1,'Qriv'])+
                                       (1.1*flat_flux.loc[i,'Qdeep'])+
                                       (0.02*flat_flux.loc[i,'Qshal']) ) / (
                                       flat_flux.loc[i-1,'Qriv'] + flat_flux.loc[i,'Qdeep'] + flat_flux.loc[i,'Qshal']
                                       )

for i in flat_flux.index:
    if i == first_index:
        print(i)
        flat_flux.loc[i,'Rsr_riv'] = ( (0.7092*flat_flux.loc[i,'Csr_riv']*flat_flux.loc[i,'Qriv'])+
                                       (0.7041*1.1*flat_flux.loc[i,'Qdeep'])+
                                       (0.7092*0.02*flat_flux.loc[i,'Qshal']) ) / (
                                       (flat_flux.loc[i,'Qriv']*flat_flux.loc[i,'Csr_riv']) +
                                       (flat_flux.loc[i,'Qdeep']*1.1)+
                                       (flat_flux.loc[i,'Qshal']*0.02)
                                       )
                    
    else:
        flat_flux.loc[i,'Rsr_riv'] = ( (flat_flux.loc[i-1,'Rsr_riv']*flat_flux.loc[i-1,'Csr_riv']*flat_flux.loc[i-1,'Qriv'])+
                                       (0.7041*1.1*flat_flux.loc[i,'Qdeep'])+
                                       (0.7092*0.02*flat_flux.loc[i,'Qshal']) ) / (
                                       (flat_flux.loc[i-1,'Qriv']*flat_flux.loc[i-1,'Csr_riv']) +
                                       (flat_flux.loc[i,'Qdeep']*1.1)+
                                       (flat_flux.loc[i,'Qshal']*0.02)
                                       )                             
                                                 
fig, ax = plt.subplots(1,1, figsize=(5,4.5))    
axb = ax.twinx()
                              
ax.plot(flat_flux['Csr_riv'], c='tomato', lw=3)
axb.plot(flat_flux['Rsr_riv'], c='grey', lw=3)
# plt.yscale('log')

ax.set_xlim(60, 160)
# ax.set_ylim(1, None)
ax.set_xlabel('Pixels on X axis')
ax.set_ylabel('Sr Concenration', c='darkorange')
ax.axvline(x=130, c='k', ls='--')
ax.set_ylim(0, 1)

axb.set_xlim(60, 160)
# axb.set_ylim(1, None)
axb.set_ylabel('Sr Ratio', c='grey', rotation=270, labelpad = 30)
axb.set_ylim(0.7040, 0.7093)
axb.ticklabel_format(style='plain')
axb.ticklabel_format(useOffset=False, style='plain')

# flat_flux.to_csv(simulations_folder + '/' + model_name + '/' +'_figures/' + 
#             'q c r'+'.csv', sep=';')

# fig.savefig(simulations_folder + '/' + model_name + '/' +'_figures/' + 
#             'Concentration and Ratio Sr'+'.png', dpi=300, bbox_inches='tight')

#%% ---- TEST VRAC NOT USE

#%% FLOPY CROSS SECTION

import flopy
import matplotlib.pyplot as plt

for watershed_name in watershed_names[:]:
    
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)
    
    dem = rasterio.open(BV.geographic.watershed_dem)
    dem_data = np.ma.masked_where(dem.read(1) < -100, dem.read(1)) # dem data
    
    list_path = sorted(glob.glob(simulations_folder+typ+'*'),
                        key=os.path.getmtime, reverse=True)
    model_name = list_path[-1].split('\\')[-1]
    
    mf = flopy.modflow.Modflow.load(
        simulations_folder+model_name+'/'+model_name+'.nam')
    fname = simulations_folder+model_name+'/'+model_name+'.hds'
    gridname = simulations_folder+model_name+'/'+model_name+'.dis'
    
    fig, ax = plt.subplots(1,1, figsize=(7, 3))
    xsect = flopy.plot.PlotCrossSection(model=mf, line={'Row': 50})
    
    linecollection = xsect.plot_grid(color='k', lw=1)
    
    # Kv = np.zeros((2,106,209))
    # Kv[0,:,:] = 1e-5 #first layer of lime
    # Kv[1,:,:] = 1e-6 #second layer of sand
    # xsect.plot_array(Kv)
    
    xsect.get_extent()
    # xsect.plot_bc()
    
    hdobj = flopy.utils.HeadFile(fname)
    head = hdobj.get_data()
        
    xsect.plot_fill_between(head, color='saddlebrown', edgecolor='none',
                            alpha=0.5)

    pc = xsect.plot_array(head,
                          masked_values=[-9999.0], head=head, alpha=0.5,
                          cmap = 'Blues', lw=0,
                          vmin=0, vmax=400)
    # patches = xsect.plot_ibound(head=head)
    # linecollection = xsect.plot_grid()
    cb = plt.colorbar(pc, shrink=0.75)
    ax.set_ylim(0,400)
    ax.set_xlim(150,1000)
    
    
    # xsect.plot_pathline(pth_data[3000:3050], method='all', colors='k')
    # xsect.plot_endpoint(e, direction='ending')
    
    # keep = []
    # for i, j in enumerate(pth_data[:]):
    #     if (j.z<250).any():
    #         print(i, len(pth_data))
    #         keep.append(j)
    #         ax.plot(j.x, j.z, color='red')
"""
    keep_idx = []
    for i, j in enumerate(pth_data):
        if len(np.unique(j.k)) != 1:
            print(i, len(pth_data))
            keep_idx.append(i)
            ax.plot(j.x, j.z, color='darkorange')
"""
#%% EXTRACT RESIDENCE TIMES 2D

stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'

BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=dem_path, 
                              out_path=out_path,
                              load=True,
                              modflow_path=modflow_path)

dem = rasterio.open(BV.geographic.watershed_dem)
dem_data = dem.read(1)

list_path = sorted(glob.glob(simulations_folder+typ+'*'),
                    key=os.path.getmtime, reverse=True)
model_name = list_path[-1].split('\\')[-1]

compt=0
# for case, prop in zip(case_list[:], prop_list[:]):
#     for porosity in porosity_list[:]:
    
folder_results = simulations_folder + '/' + model_name + '/' + '_watershed/_tifs/'

path_res = folder_results+'residence_times_t(0).tif'
path_obs = data_path+'targets_pathlines_points.shp'
path_shp = simulations_folder + '/' + model_name + '/' + '_watershed/_shp/'
toolbox.create_folder(path_shp)
path_dat = path_shp+'residence_times_data.shp'

res_time = rasterio.open(path_res)
res_time_data = res_time.read(1)
res_time_data = res_time_data

shp_obs = gpd.read_file(path_obs)
shp_obs['geometry'] = shp_obs.geometry.buffer(100)
# shp_obs = shp_obs[['ID_station', 'geometry']]
shp_obs.to_file(path_dat, encoding='utf-8') # mode a

# wbt.extract_raster_values_at_points(
#                 path_res, 
#                 path_dat, 
#                 out_text=False)

# Method 1
wbt.raster_to_vector_polygons(
        path_res, 
        path_shp+'raster_polygonized.shp')
raster_polyg = gpd.read_file(path_shp+'raster_polygonized.shp')
intersect = gpd.overlay(shp_obs, raster_polyg, how='intersection')
intersect[intersect['VALUE']==-np.inf] = np.nan
res_dat = gpd.read_file(path_dat)
res_dat['RES_TIME'] = np.nan
res_dat['STD_TIME'] = np.nan

for ID in intersect['id'].unique():
    # threshold = 1 #year
    # threshold = threshold*365
    # threshold = np.log10(threshold)
    
    mask = (intersect[intersect['id']==ID]['VALUE'] !=0)
    
    mean_ID = np.nanmean(intersect[intersect['id']==ID]['VALUE'][mask])
    res_dat['RES_TIME'][res_dat['id']==ID] = mean_ID
    
    std_ID = np.nanstd(intersect[intersect['id']==ID]['VALUE'][mask])
    res_dat['STD_TIME'][res_dat['id']==ID] = std_ID
    
# Method 2
'''
from rasterstats import zonal_stats
stats = zonal_stats(path_dat, path_res)
# print(stats[0].keys())
# print(stats)
means = [f['mean'] for f in stats]
res_dat = gpd.read_file(path_dat)
res_dat['RES_TIME'] = means
'''

res_dat['RES_TIME'][res_dat['RES_TIME']==-np.inf] = np.nan
res_dat['STD_TIME'][res_dat['STD_TIME']==-np.inf] = np.nan
res_dat.to_file(path_shp + 'extract_RTD.shp', encoding = 'utf-8')

vmin = 0
vmax = 30

fig, ax = plt.subplots(1,1, figsize=(5,5))
# plt.imshow(res_time_data)
# plt.colorbar()

## Modif res_time_data en annees + vmin et vmax

res_time_data = np.ma.masked_where(res_time_data <= 0, res_time_data)

#show(np.ma.masked_where(dem_data < -0, res_time_data), ax=ax, transform=dem.transform, 
show(np.ma.masked_where(dem_data <= 0, res_time_data), ax=ax, transform=dem.transform, 
     cmap='jet', alpha=1, zorder=2, aspect="auto", vmin=vmin, vmax=vmax)

shp_obs.plot(ax=ax, color='none', marker='o', markersize=10,
             edgecolor='k', lw=3, zorder=30)
# res = res_dat.plot(ax=ax, cmap='jet',  marker='o', markersize=10,
#              edgecolor='k', lw=1, column='RES_TIME', zorder=30,
#              vmin=vmin, vmax=vmax)
bounds = dem.bounds
xlim = ([bounds[0], bounds[2]])
ylim = ([bounds[1], bounds[3]])
ax.set_xlim(xlim)
ax.set_ylim(ylim)
scalebar = ScaleBar(1,box_alpha=0, scale_loc = 'bottom', location='upper left')
ax.add_artist(scalebar)
ax.get_xaxis().set_visible(False)
ax.get_yaxis().set_visible(False)
ax.set_title(model_name, fontproperties=fontprop)
ax.set(aspect='equal')
sm = plt.cm.ScalarMappable(cmap='jet', norm=plt.Normalize(vmin=vmin, vmax=vmax))
divider = make_axes_locatable(ax)
cax = divider.append_axes(size="2%",position='right', pad=0.05)
fig.add_axes(cax)
cbar = fig.colorbar(sm, cax=cax, orientation="vertical")
cbar.ax.get_ymajorticklabels()
cbar.ax.tick_params(labelsize=10)
cbar.ax.yaxis.set_ticks_position('right')
cbar.ax.tick_params(size=2)
contour = gpd.read_file(BV.geographic.watershed_contour_shp)
contour.plot(ax=ax, lw=1.5, color='k', zorder=20, legend=False, label='Watershed')
cbar.set_ticks(list(cbar.get_ticks()))
# cbar.set_ticklabels(list(cbar.get_ticks())[::-1])
cbar.set_label('Residence times [years]', rotation=270, labelpad=25)

res_dat['coords'] = res_dat['geometry'].apply(lambda x: x.representative_point().coords[:])
res_dat['coords'] = [res_dat[0] for res_dat in res_dat['coords']]
# for idx, row in res_dat.iterrows():
#     row['coords'] = (row['coords'][0], row['coords'][1]+100)
#     ax.annotate(s=row['id'], xy=row['coords'],
#                  horizontalalignment='center')

# fig.savefig(res_path+model_name+'.png', dpi=300, bbox_inches='tight')

'''
fig, ax = plt.subplots(1,1, figsize=(4,4))
mean_obs = res_dat[['CFC11', 'CFC12', 'CFC113']].mean(axis=1)
std_obs = res_dat[['CFC11', 'CFC12', 'CFC113']].std(axis=1)
x=2021-(mean_obs)
xerr=std_obs
mean_sim = res_dat['RES_TIME']
y=mean_sim
yerr = res_dat['STD_TIME']
ax.scatter(x, y, c=y, s=50, cmap=mpl.colors.ListedColormap('k'))
plt.errorbar(x, y , xerr=list(xerr), yerr=yerr, lw=1, fmt="o", color='k')
# ax.legend()
ax.set_xlabel('$Age_{obs}$ [years]')
ax.set_ylabel('$Age_{sim}$ [years]')
ax.set_title(model_name, fontproperties=fontprop)
for i, txt in enumerate(res_dat.id):
    ax.annotate(txt, (x[i], y[i]))
xn=20
xx=80
yn=20
yx=80
ax.set_xlim(xn, xx)
# ax.set_ylim(yn, yx)
# ax.set_xscale('log')
# ax.set_yscale('log')
# ax.plot(np.linspace(xn,xx,50), np.linspace(yn,yx,50), 
#         linestyle='--', color='grey', linewidth=2, zorder=-1)
maxx = max(ax.get_xlim()[0],ax.get_xlim()[1])
maxy = max(ax.get_ylim()[0],ax.get_ylim()[1])
minx = min(ax.get_xlim()[0],ax.get_xlim()[1])
miny = min(ax.get_ylim()[0],ax.get_ylim()[1])
maxt = max(maxx,maxy)
mint = max(minx,miny)
ax.plot(np.linspace(mint,maxt,50),
        np.linspace(mint,maxt,50), 
        linestyle='--', color='grey', linewidth=2, zorder=-1)

fig.savefig(res_path+'obs_vs_sim_'+model_name+'.png', dpi=300, bbox_inches='tight')
'''

if compt==0:
    all_dat = res_dat.copy()
all_dat[model_name] = res_dat['RES_TIME']

compt+=1

# all_dat['coords'] = np.nan
# all_dat.to_file(simulations_folder+'residence_times_all.shp', sep=';', encoding='utf-8')

#%% EXTRACT PATHLINES TIMES 2D

stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'

BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=dem_path, 
                              out_path=out_path,
                              load=True,
                              modflow_path=modflow_path)

dem = rasterio.open(BV.geographic.watershed_dem)
dem_data = dem.read(1)

list_path = sorted(glob.glob(simulations_folder+typ+'*'),
                    key=os.path.getmtime, reverse=True)
model_name = list_path[-1].split('\\')[-1]

compt=0
# for case, prop in zip(case_list[:], prop_list[:]):
#     for porosity in porosity_list[:]:
    
folder_results = simulations_folder + '/' + model_name + '/' + '_watershed/_tifs/'

##### LOOOP 2D #####
visu = visualization.Visualization(BV, model_name)
# visu.visual2D(object_list = ['map','grid', 'watertable', 'watertable_depth','drain_flow','surface_flow','pathlines', 'residence_times'],
              # color_scale = [(None,None),(0,140),(0,140),(0,2),(None,None),(None,None),(None,None),(None,None)], lines=10000)
visu.visual2D(object_list = ['pathlines'],
              color_scale = [(None,None)], lines=1000)

#%% SEPARATE WITH LINECOLLECTION

from matplotlib.collections import LineCollection

color_scale = [(None,None)]

fig, ax = plt.subplots()
show(np.ma.masked_where(dem.read(1) < -100, dem.read(1)), ax=ax, 
         transform=dem.transform, cmap='Greys', alpha=0.75, zorder=0, aspect="auto")

layers = [1,0]
color_layers = ['red','dodgerblue']
dict_layers = dict(zip(layers, color_layers))

indices_layers = []

for lay in layers:
    
    keep_id = []
    
    if lay == 0:
        keep = []
        for i, j in enumerate(pth_data):
            if len(np.unique(j.k))==1:
                if np.unique(j.k)[0] == 0:
                    keep.append(j)
    if lay == 1:
        keep = []
        for i, j in enumerate(pth_data):
            if len(np.unique(j.k)) != 1:
                keep.append(j)
    print(len(keep))
        
    # random_indices = np.random.choice(len(keep), size=1000) # RANDOM LINES
    random_indices = np.arange(len(keep))
    geotx_p = BV.geographic.x_coord
    geoty_p = BV.geographic.y_coord
    geot_p = BV.geographic.geodata
    cols = geotx_p.shape[0]
    rows = geoty_p.shape[0]
    ext = []
    xarr = [0, cols]
    yarr = [0, rows]
    for px in xarr:
        for py in yarr:
            x = geotx_p[0] + (px * geot_p[1]) + (py * geot_p[2])
            y = geoty_p[0] + (px * geot_p[4]) + (py * geot_p[5])
            ext.append([x, y])
    max_time = []
    min_time = []
    for j in random_indices:
        max_time.append(np.max(np.log10(keep[j].time)))
        min_time.append(np.min(np.log10(keep[j].time)))
    for j in random_indices:
        x = keep[j].x + ext[1][0]
        y = keep[j].y + ext[1][1]
        points = np.array([x, y]).T.reshape(-1, 1, 2)
        segments = np.concatenate([points[:-1], points[1:]], axis=1)
        # lc = LineCollection(segments, cmap='jet', alpha=0.5)
        lc = LineCollection(segments, color=dict_layers[lay], alpha=0.5)
        # lc.set_array(np.log10(pth_data[j].time/365)) # log(t) in days
        lc.set_array(pth_data[j].time / 365) # t in years
        lc.set_linewidth(2)
        lc.set_clim(1,np.max(max_time))
        line = ax.add_collection(lc) 
        
        part_id = keep[j]['particleid'][0]
    
        # fig, ax = plt.subplots(1)
        # ax.add_collection(lc)
        # axcb = fig.colorbar(lc, pad=0.02)
        
        keep_id.append(part_id)

    indices_layers.append(keep_id) # lasr layers and first layer

contour = gpd.read_file(BV.geographic.watershed_contour_shp)
contour.plot(ax=ax, lw=2, color='k', zorder=4,legend=True, label='Watershed')

#%% SEPARATE WITH MAPVIEW

fig, ax = plt.subplots(1,1, figsize=(8, 8))
show(np.ma.masked_where(dem.read(1) < -100, dem.read(1)), ax=ax, 
         transform=dem.transform, cmap='Greys', alpha=0.75, zorder=0, aspect="auto")
# mapview = flopy.plot.PlotMapView(model=ml)
# ibound = mapview.plot_ibound()
# linecollection = mapview.plot_grid()
# kwargs = {'layer':'10','colors':'red'}
# pathlines = mapview.plot_pathline(pth_data,
#                                   **kwargs)
# mapview.plot_pathline(pth_data, layer='10', colors="blue");
# line = ax.add_collection(pathlines)
mm = flopy.plot.PlotMapView(model=ml, layer=0)
# mm.plot_grid(lw=0)
mm.plot_pathline(pth_data, layer=1, lw=0.5, colors='red', travel_time=None)
# mm.plot_pathline(pth_data, layer=0, lw=0.5, colors='dodgerblue', travel_time=None)
# mm.plot_endpoint(e, direction="ending", colorbar=True, size=10)
mm.ax.legend()

#%% PATHLINES 3D

import matplotlib.pyplot as p

watershed_name = 'Quiock'

stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'

BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=dem_path, 
                              out_path=out_path,
                              load=True,
                              modflow_path=modflow_path)

dem = rasterio.open(BV.geographic.watershed_dem)
dem_data = dem.read(1)

list_path = sorted(glob.glob(simulations_folder+typ+'*'),
                    key=os.path.getmtime, reverse=True)
modelname = list_path[-1].split('\\')[-1]

from groundwater_flow import visualization
# vtk.VTK(BV, model_name)
# visu = visualization.Visualization(BV, model_name)
# visu.visual3D(interactive=True, object_list=['grid','watertable'], view='south-west')

object_list = ['grid', 'pathlines']
object_list = ['pathlines']
view = 'south-west'
bg = 'lb'
interactive = True
lines=100
z_scale=1
render=1
cscale = 'default'
cmin = -1
cmax = 1
cloc=(0.65,0.75)
size=(1500,1080)

import vedo

vedo.settings.screeshotScale = render
plt = vedo.Plotter(N=len(object_list), axes=dict(xtitle='m', ytitle='m', ztitle='m', 
                                  yzGrid=False), size=size)

# load files
contour = vedo.Mesh(os.path.join(BV.simulations_folder,
                                 modelname,
                                 '_watershed',
                                 'VTK',
                                 'VTU_watershed_contour.vtk'))
contour.scale([1,1,z_scale])
contour.color('k').lw(2)
contour.renderLinesAsTubes(value=True)

try:
    stream = vedo.Mesh(os.path.join(BV.simulations_folder, modelname, '_watershed', 'VTK','VTU_streams.vtk'))
    stream.scale([1,1,z_scale])
    stream.color('b').lw(5)
    stream.renderLinesAsTubes(value=True)
except:
    stream=None
    pass

try:
    grid = os.path.join(BV.simulations_folder, modelname, '_watershed', 'VTK','VTU_Grid.vtu')
    grid_mesh = vedo.Mesh(grid) #grid_mesh
    grid_wireframe = vedo.Mesh(grid).wireframe() #grid_wireframe
    if bg == 'white':
        grid_wireframe.color('black')
    else:
        grid_wireframe.color('white')
    grid_wireframe.scale([1,1,z_scale])
    grid_wireframe.alpha(0.1)
    plt += grid_wireframe.flag()
    
    zvals = grid_mesh.points()[:, 2]
    grid_mesh.addElevationScalars(lowPoint=(0,0,min(zvals)),highPoint=(0,0,max(zvals)), vrange=(min(zvals), max(zvals)))
    grid_mesh.cmap('terrain',zvals, vmin=min(zvals))
    grid_mesh.addScalarBar(pos=cloc, title='Topographic elevation, [m]', horizontal=False, titleFontSize=20)
    grid_mesh.scale([1,1,z_scale])
    

    grid_mesh.alpha(1)
    plt += grid_mesh.flag()     
    plt += grid_mesh.isolines(5).lw(1).c('k')

except:
    print("VTK grid doesn't exist")
    
try: 
    watertable = os.path.join(BV.simulations_folder, modelname, '_watershed', 'VTK','VTU_Watertable_0.vtu')
    watertable_elev = vedo.Mesh(watertable) # 1 Elevation
    watertable_depth = vedo.Mesh(watertable) # 3 Depth
    surface_flow = vedo.UGrid(watertable) # 3 Surface Flow
    drain_flow = vedo.UGrid(watertable) # 3 Drain Flow
    watertable_blue = vedo.Mesh(watertable) # 4 blue
    
    zvals = watertable_elev.points()[:, 2]
    watertable_elev.cmap('jet',zvals, vmin=min(zvals))
    watertable_elev.addScalarBar(pos=cloc, title='Water table elevation, [m]', horizontal=False, titleFontSize=20)
    watertable_elev.scale([1,1,z_scale])
    plt += watertable_elev.flag() 
    
    watertable_depth.mapCellsToPoints()
    watertable_depth.cmap('coolwarm_r',input_array='Drawdown', vmin=0, vmax=1)
    watertable_depth.addScalarBar(pos=cloc, title='Water table depth, [m]', horizontal=False, titleFontSize=20)
    watertable_depth.scale([1,1,z_scale])
    plt += watertable_depth.flag()
    
    watertable_blue.color('b')
    watertable_blue.alpha(0.2)
    watertable_blue.scale([1,1,z_scale])
    watertable_blue.legend('Water table')
    plt += watertable_blue.flag()  
    
    nan_loc = ~np.isnan(surface_flow.celldata['Surfaceflow_log'])
    surface_flow = surface_flow.extractCellsByID([i for i, x in enumerate(nan_loc) if x])
    surface_flow = surface_flow.tomesh()
    surface_flow.cmap('jet','Surfaceflow_log', on='cells')
    surface_flow.addScalarBar(pos=cloc, title='Flow (log)', horizontal=False, titleFontSize=20)
    surface_flow.scale([1,1,z_scale])
    
    nan_loc = ~np.isnan(drain_flow.celldata['Drainflow_log'])
    drain_flow = drain_flow.extractCellsByID([i for i, x in enumerate(nan_loc) if x])
    drain_flow = drain_flow.tomesh()
    # cmin = min(drain_flow.pointdata['Drainflow_log'])
    # cmax = max(drain_flow.pointdata['Drainflow_log'])
    if cscale == 'custom':
        mi = 1
        ma = 4
        drain_flow.cmap('jet','Drainflow_log', on='cells',vmin = mi, vmax=ma)
    else:
        drain_flow.cmap('jet','Drainflow_log', on='cells')
    drain_flow.addScalarBar(pos=cloc, title='Seepage rates, log(Q) [mm/y]', horizontal=False, titleFontSize=20)
    drain_flow.scale([1,1,z_scale])
except:
    print("VTK watertable doesn't exist")
# try:
pathlines = os.path.join(BV.simulations_folder, modelname, '_watershed', 'VTK','VTU_Pathlines.vtk')
pathlines_mesh = vedo.Mesh(pathlines) #5

#Pathlines
if cscale == 'default':
    cmin = int(min(pathlines_mesh.pointdata['Time_log']))
    cmax = int(max(pathlines_mesh.pointdata['Time_log']))
if cscale == 'custom':
    cmin = cmin
    cmax = cmax
pathlines_mesh.cmap('hot_r',input_array='Time_log',vmin = cmin, vmax=cmax).lw(5)
pathlines_mesh.addScalarBar(pos=cloc, title='Residence times, log(t) [y]', horizontal=False, titleFontSize=20)
pathlines_mesh.scale([1,1,z_scale])
pathlines_mesh.renderLinesAsTubes(value=True)
pathlines_mesh.legend('Pathlines')
x = pathlines_mesh.lines()
# x = [x[i] for i in keep_idx]
length = max(map(len, x))
y=np.array([xi+[None]*(length-len(xi)) for xi in x])
number_of_rows = y.shape[0]
# random_indices = np.random.choice(number_of_rows, size=len(x)-n, replace=False)
n = lines
# n = len(x)-1
random_indices = np.arange(0, n, 1)
y1 = y[random_indices, :].flatten()
pts =  y1[y1 != np.array(None)]
pathlines_mesh.deletePoints(pts)
# except:
# print("VTK pathlines doesn't exist")

#View
xs = max(watertable_elev.points()[:, 0]) - min(watertable_elev.points()[:, 0])
ys = max(watertable_elev.points()[:, 1]) - min(watertable_elev.points()[:, 1])
zs = max(watertable_elev.points()[:, 2]) - min(watertable_elev.points()[:, 2])
if view == 'north':
    pos = (min(watertable_elev.points()[:, 0])+ xs ,max(watertable_elev.points()[:,1])+ ys,max(watertable_elev.points()[:, 2])*10)
if view == 'north-east':
    pos = (max(watertable_elev.points()[:, 0])+ xs ,max(watertable_elev.points()[:,1])+ ys,max(watertable_elev.points()[:, 2])*10)
if view == 'east':
    pos = (max(watertable_elev.points()[:, 0])+ xs ,min(watertable_elev.points()[:,1])+ ys,max(watertable_elev.points()[:, 2])*10)
if view == 'south-east':
    pos = (max(watertable_elev.points()[:, 0])+ xs ,max(watertable_elev.points()[:,1])- ys,max(watertable_elev.points()[:, 2])*10)
if view == 'south':
    pos = (min(watertable_elev.points()[:, 0])+ xs ,min(watertable_elev.points()[:,1])- ys,max(watertable_elev.points()[:, 2])*10)
if view == 'south-west':
    pos = (min(watertable_elev.points()[:, 0])- xs ,min(watertable_elev.points()[:,1])- ys,max(watertable_elev.points()[:, 2])*10)
if view == 'west':
    pos = (min(watertable_elev.points()[:, 0])- xs ,min(watertable_elev.points()[:,1])+ ys,max(watertable_elev.points()[:, 2])*10)
if view == 'north-west':
    pos = (min(watertable_elev.points()[:, 0])- xs ,max(watertable_elev.points()[:,1])+ ys,max(watertable_elev.points()[:, 2])*10)
if view == 'custom':
    pos = (max(watertable_elev.points()[:, 0])+ xs ,max(watertable_elev.points()[:,1])+ ys,max(watertable_elev.points()[:, 2])*4)
if view == 'vertical':
    pos = (np.mean(watertable_elev.points()[:, 0]) ,np.mean(watertable_elev.points()[:,1]), np.mean(watertable_elev.points()[:, 2])*400)

focal = (min(watertable_elev.points()[:, 0])+(xs/2), min(watertable_elev.points()[:, 1])+(ys/2), zs)
cam = dict(pos = pos,focalPoint = focal)

for i in range (0,len(object_list)):
    obj = object_list[i]
    if obj == 'grid':
        plt.show(grid_mesh,contour,stream,"Topography elevation", at=i, camera=cam, viewup='z', axes = 13, bg=bg)
    if obj == 'watertable':
        plt.show(grid_wireframe,contour,stream, watertable_elev,"Watertable elevation",camera=cam, viewup ='z', at=i, axes = 13, bg=bg)
    if obj == 'watertable_depth':
        plt.show(grid_wireframe,contour,stream, watertable_depth,"Watertable depth",camera=cam, viewup ='z', at=i, axes = 13, bg=bg)
    if obj == 'pathlines':
        #plt.show(grid_wireframe,contour,stream, watertable_blue, pathlines_mesh,"Groundwater flow paths",camera=cam, viewup ='z', at=i, axes = 13)
        plt.show(grid_wireframe,contour,stream, watertable_blue, pathlines_mesh, "Groundwater flow paths",
                 camera=cam, viewup ='z', at=i, axes = 13, bg=bg)
        #plt.show(grid_wireframe,contour,stream, watertable_blue, pathlines_mesh,camera=cam, viewup ='z', at=i, axes = 13)
        #plt.show(grid_mesh, pathlines_mesh,camera=cam, viewup ='z', at=i, axes = 13)
    if obj == 'surface_flow':
        plt.show(grid_wireframe,contour, watertable_blue, surface_flow,"Surface flow",camera=cam, viewup ='z', at=i, axes = 13, bg=bg)
    if obj == 'drain_flow':
        #plt.show(grid_wireframe,contour,stream, watertable_blue, drain_flow,"Groundwater seepage",camera=cam, viewup ='z', at=i, axes = 13)
        plt.show(grid_wireframe,contour,stream, watertable_blue, drain_flow,"Groundwater seepage",camera=cam, viewup ='z', at=i, axes = 13, bg=bg)
        #plt.show(grid_wireframe,contour,stream, watertable_blue, drain_flow,camera=cam, viewup ='z', at=i, axes = 13)
        #plt.show(grid_mesh,drain_flow,camera=cam, viewup ='z', at=i, axes = 13)

if interactive == True:
    plt.show(interactive=1,interactorStyle=6).close()
else:
    plt.screenshot(os.path.join(BV.simulations_folder, modelname, '_watershed_fig','3Dvisual.png')).close()

#%% ---- NOTES

#%% VRAC

# ax.set_xlim(0, 170)
# ax.set_ylim(135,0)
# ax.set_xbound(lower=0.0, upper=170)
# ax.set_ybound(lower=135, upper=0)
# axb.set_xlim(0, 170)
# axb.set_ylim(0, 135)

# scale_factor = 5
# xmin, xmax = plt.xlim()
# ymin, ymax = plt.ylim()
# plt.xlim(xmin / scale_factor, xmax / scale_factor)
# plt.ylim(ymin / scale_factor, ymax / scale_factor)

test_path = "D:/Users/abherve/GUADELOUPE/Quiock/results_simulations/case4_1_10.0-0.02-300_50/_watershed/_tifs/residence_times_t(0).tif"
test = imageio.imread(test_path)
plt.imshow(np.ma.masked_array(test, mask=(test<0)))

#%% KEEP

"""
head_profile = pc.get_array()[0:170]
keep_idx = []
for i, j in enumerate(np.random.choice(pth_data,7000)):
    if j.particleid[0] in indices_layers[0]:
        j_xmin = j.x.min()/5
        j_xmax = j.x.max()/5
        head_restr = head_profile[int(j_xmin):int(j_xmax)]
        if len(head_restr)>0:
            head_max = head_restr.max()
            if j.z.max()<head_max:
                print(i, len(pth_data))
                keep_idx.append(i)
                ax.plot(j.x, j.z, color='red', lw=1)
"""

#%% PROFIL

# Your catchement DEM
dem_path = "D:/Users/abherve/GUADELOUPE/Quiock/results_stable/geographic/watershed_dem.tif"
# dem_path = "D:/Users/abherve/PAPER/Canut/results_stable/geographic/watershed_dem.tif"

# Your direction flow from DEM
d8_path = "D:/Users/abherve/GUADELOUPE/Quiock/results_stable/geographic/watershed_buff_direc.tif"
# d8_path = "D:/Users/abherve/PAPER/Canut/results_stable/geographic/watershed_buff_direc.tif"

# Your output downslope flowpath (distance pixels to the outlet)
down_path = "D:/Users/abherve/GUADELOUPE/Quiock/results_simulations/case4_1_10.0-0.02-300_50/_watershed/_tifs/downslope_flux_t(0).tif"
# down_path = "D:/Users/abherve/PAPER/Canut/results_simulations/calibr-t6_1_REC-REA-historic_0.1-4.75-30_1960-2019/_watershed/_tifs/downslope_flux_t(0).tif"

# Fonction downslope
wbt.downslope_flowpath_length(
    d8_path, 
    down_path, 
    watersheds=None, 
    weights=None, 
    esri_pntr=False)

# Your cumulated flux from seepage zones areas (we have the fonction in hydromodpy : "surface flow")
acc_path = "D:/Users/abherve/GUADELOUPE/Quiock/results_simulations/case4_1_10.0-0.02-300_50/_watershed/_tifs/accumulation_flux_t(0).tif"
# acc_path = "D:/Users/abherve/PAPER/Canut/results_simulations/calibr-t6_1_REC-REA-historic_0.1-4.75-30_1960-2019/_watershed/_tifs/accumulation_flux_t(0).tif"

# DEM for mask
dem = imageio.imread(dem_path)
dem_masked = np.ma.masked_where(dem < -100, dem)

# Masked data
fig, (ax1, ax2) = plt.subplots(1,2, figsize=(7,3))
acc = np.ma.masked_array(imageio.imread(acc_path), mask=dem_masked.mask)
acc_masked = np.ma.masked_where(acc <= 50, acc)
ax1.imshow(acc_masked)
ax1.set_title('Cumulated flux')
down = np.ma.masked_array(imageio.imread(down_path), mask=dem_masked.mask)
down = down = np.ma.masked_array(down, mask=acc_masked.mask)
ax2.imshow(down)
ax2.set_title('Downslope lengths')

# Figure represent distance outlet verses elevation and cumulated flux colored
fig, ax = plt.subplots(1,1, figsize=(6,3))
s = ax.scatter(down, dem_masked, marker='_', lw=3, c=acc_masked,
               s=20,
               # norm=matplotlib.colors.LogNorm()
               )
ax.set_xlabel('Distance [m]')
ax.set_ylabel('Elevation [m]')
cb = fig.colorbar(s)
cb.set_label('Cum. flux', rotation= 270, labelpad=25)


