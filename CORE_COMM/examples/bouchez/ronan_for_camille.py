# -*- coding: utf-8 -*-
"""
Created on Wed Jan 26 10:49:18 2022

@author: ronan
"""

#%% LIBRARIES MODULES£

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

watershed_names = ['Test']

types_obs = ['perennial','perennial_intermittent'] # list of shapefile name layers for clip hydrology
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
  
    print(BV.geographic.area.round(2))
    print(BV.geographic.slope.round(2))
    
    # watershed_display.watershed_dem(BV)
    # watershed_display.watershed_local(dem_path, BV)
        
#%% DATA WATERSHED

types_obs = ['perennial','perennial_intermittent'] # list of shapefile name layers for clip hydrology
fields_obs = ['fid','fid']

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
    
    types_obs = ['perennial','perennial_intermittent'] # list of shapefile name layers for clip hydrology
    fields_obs = ['fid','fid']
        
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
        BV.hydrodynamic.update_thickness(100)
        BV.hydrodynamic.update_bottom(None)
        BV.hydrodynamic.update_cond_decay(0)
        BV.hydrodynamic.update_thick_exp(1)
        
        params_df = pd.DataFrame(columns=['params',
                                          'init_values','lower_bounds','higher_bounds',
                                          'units','scale'])
        params_df.loc[0] = ['k1','?',8.64e-04,8.64e-01,'m/j','lin']
        
        params_file = 'calib_dicot_hom_1v_k1'
        
        params_df.to_csv(BV.calibration_folder+'/'+params_file+'.csv', sep=';', index=None)

        # params_file = 'calib_dicot_het_2v_k1-k2'
        # params_file = 'calib_dicot_hom_2v_k1-n1'
        calib = calib_root.Calibration(params_file, BV, observations = ['streams'])
        
        # dicot = calib.dichotomy(gap=1)

    for i, type_obs in enumerate(types_obs):
        
        typ_calib = 'streams_calibration'
        list_path = sorted(glob.glob(os.path.join(BV.calibration_folder, params_file, typ_calib, '*.calib')),
                           key=os.path.getmtime)
        name_file = list_path[i].split('\\')[-1]
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

#%% CASES TO TEST

#['nlay', 'thickness', 'bottom', 'cond_decay', 'thick_exp']
['thickness', 'bottom', 'cond_decay']

thick_exp = 1.25

dc = np.logspace(np.log10(1/20),np.log10(1/200),3)

case_list = ['case1', 'case2', 'case3', 'case4', 'case5']

prop_list = [[50, None, 0], [50, 1000, 0], [50, 1000, dc[0]], [50, 1000, dc[1]],  [50, 1000, dc[2]]]

porosity_list = np.linspace(0.1, 0.3, 9)

# for case, prop in zip(case_list[:], prop_list[:]):

#%% TYP SIM NAMING

typ = 'case1-k1+k2'

#%% RUN MODEL

sim_state = 'steady' # 'steady' or 'transient'
modpath_sim = True # run modpath particle tracking if True

run = True

for watershed_name in watershed_names[:] :
    
    print('##### '+watershed_name.upper()+' #####')
    
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' 
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)
    
    # Input recharge
    time_step = 'D' # or 'D'
    actual_date = False # False if date is conceptual
    
    # Active of not modules
    box = False # if True generate a rectangular model
    sink_fill = False # permit to fill sinks
    verbose = True # add print of MODFLOW in console
    post_process = False # necessary to decompose post process of process
    
    # Strcture of the model
    nlay = 2 # vertical discrtization
    bottom = None # aquifer flat or not
    thick_exp = 1 # exponential decay of K with nlay
    cond_decay = 0 # exponential decay of K with depth
    thick = 100 # m
    verti_k = [[(2e-6)*3600* 24],
               [40]] # None
    # verti_k = None
    
    # Hydraulic properties
    # Koptim = 40 / 365 / 24 / 3600 # m/y to m/s
    Koptim = 2e-7
    Sy = 0.1

    Ks = np.array([Koptim]) * 3600 * 24 # m/second to m/day
    Sys = [Sy]
    
    # Recharge
    init_rech = None
    
    recharge = 2 / 365 # mm/s to m/j
    BV.forcing.update_recharge(recharge, sim_state=sim_state) #
    
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
                                   start=None,
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

#%% ---- PLOT

#%% STEADY 2D CROSS SECTION

for watershed_name in watershed_names[:]:
    
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)
    
    interactive = False
    
    dem = rasterio.open(BV.geographic.watershed_dem)
    dem_data = np.ma.masked_where(dem.read(1) < -100, dem.read(1)) # dem data
    list_path = sorted(glob.glob(simulations_folder+typ+'*'),
                        key=os.path.getmtime, reverse=True)
    model_name = list_path[-1].split('\\')[-1]
    wt_data = imageio.imread(simulations_folder+model_name+'/_watershed/_tifs/'+'watertable_elevation_t(0).tif') # watertable data
    river_data = imageio.imread(stable_folder+'/hydrology/'+'perennial_intermittent.tif') # river data
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
                        key=os.path.getmtime, reverse=True)
    model_name = list_path[-1].split('\\')[-1]

    visu = visualization.Visualization(BV, model_name)
    
    visu.visual2D(object_list = ['grid', 'watertable', 'watertable_depth',
                                  'drain_flow', 'surface_flow'],
                  color_scale = [(None,None),(None,None),(0,10),
                                  (None,None),(None,None)])
    
    # visu.visual2D(object_list = ['map', 'grid', 'watertable', 'watertable_depth',
    #                               'drain_flow', 'surface_flow','pathlines','residence_times'],
    #               color_scale = [(None,None),(None,None),(None,None),(0,10),
    #                               (None,None),(None,None),(None,None),(None,None)],
    #               lines = 100)
    
    # visu.visual2D(object_list = ['pathlines'],
    #               color_scale = [(None,None)],
    #               lines=None)
    
#%%---- PATHLINES

#%% PLOT CROSS SECTION MAP VIEW

import flopy

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
    
    mf = flopy.modflow.Modflow.load(
        simulations_folder+model_name+'/'+model_name+'.nam')
    fname = simulations_folder+model_name+'/'+model_name+'.hds'
    fig = plt.figure(figsize=(7, 3))
    ax = fig.add_subplot(1, 1, 1)
    xsect = flopy.plot.PlotCrossSection(model=mf, line={'Row': 50})
    linecollection = xsect.plot_grid()
    Kv = np.zeros((2,106,209))
    Kv[0,:,:] = 1e-5 #first layer of lime
    Kv[1,:,:] = 1e-6 #second layer of sand
    # xsect.plot_array(Kv)
    patches = xsect.plot_ibound()
    # linecollection = xsect.plot_grid()
    
    hdobj = flopy.utils.HeadFile(fname)
    head = hdobj.get_data()
    pc = xsect.plot_array(head,
                          masked_values=[-9999.0], head=head, alpha=0.5)
    patches = xsect.plot_ibound(head=head)
    linecollection = xsect.plot_grid()
    cb = plt.colorbar(pc, shrink=0.75)
    ax.set_ylim(100,500)
    
    # xsect.plot_pathline(pth_data, travel_time=None)
    # xsect.plot_endpoint(e, direction='ending')

#%% EXTRACT RESIDENCE TIMES

wateshed_name = 'Test'

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
shp_obs['geometry'] = shp_obs.geometry.buffer(50)
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

fig.savefig(res_path+model_name+'.png', dpi=300, bbox_inches='tight')

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

#%% EXTRACT PATHLINES TIMES

watershed_name = 'Test'

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

#%% FLOPY IMPORT TRACKING DATA

fig, ax = plt.subplots(1,1, figsize=(5,5))

import flopy

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

    res_time = np.zeros(np.shape(dem))
    endobj = flopy.utils.EndpointFile(simulations_folder+
                                      model_name+'/'+model_name+'.mpend')
    e = endobj.get_alldata()
    for j in range(len(e)):
        # time_out = pth_data[j].time[0] # explore pathlines
        # res_time[e[j].i0,e[j].j0] = np.log10(e[j].time) # where infiltrated
        res_time[e[j].i,e[j].j] = (e[j].time) /365 # where outputed
    res_time = np.ma.masked_where(res_time <= 0, res_time)
    image_hidden = ax.imshow(np.ma.masked_where(BV.geographic.dem_clip<= 0, res_time),
                                 cmap='jet', vmin=None, vmax=None)
    # image.append(image_hidden)
    # basemap.append(1)
    # show(np.ma.masked_where(BV.geographic.dem_clip<= 0, res_time), ax=ax, 
    #      transform=dem.transform, cmap='jet', alpha=1, zorder=2, aspect="auto",
    #      vmin=None, vmax=None)
    # endobj.write_shapefile(endpoint_data=e,
    #                        shpname='D:/Users/abherve/GUADELOUPE/Shp/endpoints.shp',
    #                        direction='ending',
    #                        mg=None, epsg=None, sr=None)
    
    pthobj = flopy.utils.PathlineFile(simulations_folder+
                                      model_name+'/'+model_name+'.mppth')
    pth_data = pthobj.get_alldata()
    
    keep = []
    for i, j in enumerate(pth_data):
        if len(np.unique(j.k))==1:
            if np.unique(j.k)[0] == 0:
                keep.append(j)
    
    ml = flopy.modflow.Modflow.load(simulations_folder+model_name+'/'+model_name+'.nam')

#%% PLOT WITH LINECOLLECTION

from matplotlib.collections import LineCollection

color_scale = [(None,None)]

fig, ax = plt.subplots()
show(np.ma.masked_where(dem.read(1) < -100, dem.read(1)), ax=ax, 
         transform=dem.transform, cmap='Greys', alpha=0.75, zorder=0, aspect="auto")

layers = [1,0]
color_layers = ['red','dodgerblue']
dict_layers = dict(zip(layers, color_layers))

for lay in layers:
    
    if lay == 0:
        keep = []
        for i, j in enumerate(pth_data):
            if len(np.unique(j.k))==1:
                if np.unique(j.k)[0] == lay:
                    keep.append(j)
    if lay == 1:
        keep = []
        for i, j in enumerate(pth_data):
            if len(np.unique(j.k))!=1:
                keep.append(j)
        
    random_indices = np.random.choice(len(keep), size=1000) # RANDOM LINES
    # random_indices = np.arange(len(keep))
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
    
        # fig, ax = plt.subplots(1)
        # ax.add_collection(lc)
        # axcb = fig.colorbar(lc, pad=0.02)

contour = gpd.read_file(BV.geographic.watershed_contour_shp)
contour.plot(ax=ax, lw=2, color='k', zorder=4,legend=True, label='Watershed')

#%% PLOT WITH MAPVIEW

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


