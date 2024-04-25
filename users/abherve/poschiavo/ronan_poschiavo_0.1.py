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

git_path = 'C:/Users/ronan/GitHub/HydroModPy-dev0.1/'
data_path = 'C:/Users/ronan/OneDrive/RENNES/4_model/POSCHIAVINO/_data/'
# data_path = 'C:/Users/ronan/OneDrive/UNINE/8_Modeling/Lasset/_data/'
out_path = 'C:/Users/ronan/Simulations/'
# out_path = 'C:/Users/ronan/OneDrive - unine.ch/SIMULATIONS/'

fig_path = 'C:/Users/ronan/OneDrive/RENNES/4_model/POSCHIAVINO/_figures_updated/_bulk/'

wbt.resample(
    data_path+'DEM_10m_transf.tif', 
    data_path+'DEM_100m_transf.tif', 
    cell_size=30, 
    base=None, 
    method="cc")

# dem_name = 'DEM_10m_transf.tif' # EUDTM_Alps_30m_vallon
dem_name = 'DEM_100m_transf.tif' # EUDTM_Alps_30m_vallon
dem_path = data_path + dem_name

subbasin_path = True # generate subbasins from stations or manual points
from_dem = None # True or False if the process start from a given DEM of xyz file
cell_size = None # specify new resolution from a given DEM or None
from_xyv = None

watershed_name = 'Poschiavino'
watershed_name = 'Poschiavino_100m'

from_shp = [data_path + 'Catchment_Poschiavino.shp',
            1] # specify a path if process start from a given shapefile

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

# try:
#     visualization_watershed.watershed_local(dem_path, BV)
#     visualization_watershed.watershed_dem(BV)
# except:
#     pass

# SUBBASIN

# BV.add_intermittency('None','None')
# BV.add_subbasin(data_path+'_coordinates_additional/', sub_snap_dist=50)

#%% DATA

types_obs = ['poschiavino_streamnetwork','poschiavino_osm','poschiavino_osm_peren','poschiavino_main','poschiavino_main_short']
fields_obs = ['fid','fid','fid','fid','fid']
               
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
iD_explo = 'o1'

box = False # or False
sink_fill = False # or True
sim_state = 'steady' # 'steady' or 'transient'
plot_cross = True
# nlay = 5
nlay = 1
lay_decay = 1 # 1 for no decay
verti_cond = None # or [ [1e-5, [0, 20]],
verti_poro = None # or [ [1e-5, [0, 20]],
cond_drain = None # or value of conductance
porosity = 1 / 100 # -
poro_decay = 0 # exponential decay : 1/20 (half decrease at 20m)
bc_left = None # or value
bc_right = None # or value
sea_level = 'None' # or value based on specific data : BV.oceanic.MSL
# zone_partic = 'domain' # or watershed
zone_partic = 'watershed'
cond_decay_val = 0
bottom_val = None
thick = 50 # if bottom is None, aquifer thickness
first_clim = 'mean'

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
BV.hydraulic.update_cond_decay(cond_decay_val) # 0
BV.hydraulic.update_bottom(bottom_val) # None
BV.hydraulic.update_poro_decay(poro_decay)
BV.hydraulic.update_ss_decay(poro_decay) 
BV.hydraulic.update_thick(thick) # 30 / intervient pas si bottom != None
Ss_formula = 1000*9.8*(1e-10+(porosity*4.4e-10)) # rho*g*(alpha+nBeta)
BV.hydraulic.update_ss(Ss_formula)
BV.climatic.update_first_clim(first_clim)

recharge = 1 / 365
BV.climatic.update_recharge(recharge, sim_state=sim_state)
BV.climatic.update_runoff(recharge*0.1, sim_state=sim_state)

# KR = np.array([10,100,1000,10000])
KR = np.array([1000])
Ks = KR*recharge

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

        model_modpath = BV.preprocessing_modpath(model_modflow)
        success_modpath = BV.processing_modpath(model_modpath, write_model=True, run_model=True)

# MODPATH PP

        BV.postprocessing_modpath(model_modpath,
                                  ending_point=True,
                                  starting_point=True,
                                  pathlines_shp=True,
                                  particules_shp=False,
                                  random_id=None) # None

#%% MODPATH PATHLINES

for id_mod_val in [2]:

    h5file = BV.simulations_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)
    d = dd.io.load(h5file)
    list_model_name = d['list_model_name'][:]
    list_model_success = d['list_model_success'][:]
    list_model_modflow = d['list_model_modflow'][:]
    
    for model_name, model_success, model_modflow in zip(list_model_name[:],
                                                        list_model_success[:],
                                                        list_model_modflow[:]):

        print(model_name)
        model_modpath = BV.preprocessing_modpath(model_modflow)

        particules_file = BV.simulations_folder+'/'+model_name+'/_postprocess/_particules/'
        path_mppth = BV.simulations_folder+'/'+model_name+'/'+model_name
        pthobj = flopy.utils.PathlineFile(path_mppth+'.mppth')
        pth_data = pthobj.get_alldata()
            
        random_id = None
        
        if random_id != None:
            shp_endpoint = gpd.read_file(os.path.join(particules_file, 'ending.shp'))
            keep_id = shp_endpoint.particleid
            keep_id = keep_id.tolist()
         
            # if not os.path.exists(self.particules_file+'/_random_id.data'):
            id_random_particules = random.sample(keep_id[:-1], random_id)
            with open(particules_file+'/_random_id.data', 'wb') as f:
                pickle.dump(id_random_particules, f)
                    
            pth_data_save = []
            for o, i in enumerate(id_random_particules):
                # print(o, i, len(id_random_particules))
                for j in pth_data:
                    if i == j.particleid[0]:
                        pth_data_save.append(j)
        else:
            pth_data_save = pth_data
        
        pathlines_shp = True
        
        if pathlines_shp == True:
            grid_model = model_modpath.mf.modelgrid
            crs = model_modpath.geographic.crs_proj
            if isinstance(crs, (int,float)) == True:
                epsg = crs
            elif crs[:4].upper() == 'EPSG':
                epsg = int(crs.split(':')[-1])
            else:
                epsg = None
            pthobj.write_shapefile(pathline_data=pth_data_save,
                                    shpname=os.path.join(particules_file, 'pathlines.shp'),
                                    one_per_particle=True, 
                                    direction='ending',
                                    mg=grid_model,
                                    epsg=epsg,
                                    sr=None, verbose=False)

#%% TIMESERIES

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

        timeseries_results = BV.postprocessing_timeseries(model_modflow=model_modflow,
                                                          model_modpath=model_modpath,
                                                          actual_date=True, 
                                                          subbasin_results=True,
                                                          freq_time='D') # or None

#%% FILTER PATHLINES

end = gpd.read_file('C:/Users/ronan/Simulations/Poschiavino_100m/results_simulations/o1_model_0_2.7397_1000.0/_postprocess/_particules/ending_knickpoint.shp')
end = end[end['time']>0]
idp = end['particleid'].unique()

pth = gpd.read_file('C:/Users/ronan/Simulations/Poschiavino_100m/results_simulations/o1_model_0_2.7397_1000.0/_postprocess/_particules/pathlines.shp')
pth = pth[pth['particleid'].isin(idp)]
pth.to_file('C:/Users/ronan/Simulations/Poschiavino_100m/results_simulations/o1_model_0_2.7397_1000.0/_postprocess/_particules/pathlines_knickpoint.shp')

#%% ---- PROCESS RESULTS

#%% MAIN STREAM

main_buff = gpd.read_file(data_path+'main_stream_buffer.shp')

for id_mod_val in range(len(Ks[:])):

    h5file = BV.simulations_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)
    d = dd.io.load(h5file)
    list_model_name = d['list_model_name'][:]
    list_model_success = d['list_model_success'][:]
    list_model_modflow = d['list_model_modflow'][:]
    
    for model_name, model_success, model_modflow in zip(list_model_name[:],
                                                        list_model_success[:],
                                                        list_model_modflow[:]):
        
        outflow_raster_path = BV.simulations_folder+'/'+model_name+'/_postprocess/_rasters/'+'outflow_drain_t(0).tif'
        outflow_points_path = BV.simulations_folder+'/'+model_name+'/_postprocess/_rasters/'+'outflow_drain_t(0).shp'
        wbt.raster_to_vector_points(outflow_raster_path, outflow_points_path)
        outflow_points = gpd.read_file(outflow_points_path)
        outflow_points_clip = outflow_points.clip(main_buff)
        outflow_points_clip_path = BV.simulations_folder+'/'+model_name+'/_postprocess/_rasters/'+'outflow_drain_t(0)_clip.shp'
        outflow_points_clip.to_file(outflow_points_clip_path)
        outflow_raster_clip_path = BV.simulations_folder+'/'+model_name+'/_postprocess/_rasters/'+'outflow_drain_t(0)_clip.tif'
        
        wbt.vector_points_to_raster(
                        outflow_points_clip_path, 
                        outflow_raster_clip_path, 
                        field="FID", 
                        assign="last", 
                        nodata=True, 
                        cell_size=None, 
                        base=outflow_raster_path)
        
        raw_rast_path = outflow_raster_clip_path
        watershed_buff_fill_surflow = BV.geographic.watershed_buff_fill
        load_rast_path = BV.simulations_folder+'/'+model_name+'/_postprocess/_rasters/'+'_load_t(xxx)_clip.tif'
        eff_rast_path = BV.simulations_folder+'/'+model_name+'/_postprocess/_rasters/'+'_eff_t(xxx)_clip.tif'
        abs_rast_path = BV.simulations_folder+'/'+model_name+'/_postprocess/_rasters/'+'_abs_t(xxx)_clip.tif'
        mass_rast_path = BV.simulations_folder+'/'+model_name+'/_postprocess/_rasters/'+'_accumulation_flux_t(xxx)_clip.tif'
        
        im = imageio.imread(raw_rast_path)
        im[im<0] = 0
        toolbox.export_tif(watershed_buff_fill_surflow, im, -9999, load_rast_path)
        ### Efficiency ###
        im = imageio.imread(watershed_buff_fill_surflow)
        im[im>=0] = 1
        toolbox.export_tif(watershed_buff_fill_surflow, im, -9999, eff_rast_path)        
        ### Adsorption ###
        im = imageio.imread(watershed_buff_fill_surflow)
        im[im>=0] = 0
        toolbox.export_tif(watershed_buff_fill_surflow, im, -9999, abs_rast_path)
        ### d8massflux ###
        wbt.d8_mass_flux(watershed_buff_fill_surflow,
                         load_rast_path, eff_rast_path,
                         abs_rast_path, mass_rast_path)
        
        mass_pts_path = BV.simulations_folder+'/'+model_name+'/_postprocess/_rasters/'+'_accumulation_flux_t(xxx)_clip.shp'
        wbt.raster_to_vector_points(mass_rast_path, mass_pts_path)
        
#%% ADD INFORMATION

# import whitebox
# wbt = whitebox.WhiteboxTools()
# wbt.verbose = True

for id_mod_val in range(len(Ks[:])):

    h5file = BV.simulations_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)
    d = dd.io.load(h5file)
    list_model_name = d['list_model_name'][:]
    list_model_success = d['list_model_success'][:]
    list_model_modflow = d['list_model_modflow'][:]
    
    for model_name, model_success, model_modflow in zip(list_model_name[:],
                                                        list_model_success[:],
                                                        list_model_modflow[:]):
        
        down_path = BV.simulations_folder+'/'+model_name+'/_postprocess/_rasters/'+'downslope_flux_t(0).tif'
        if not os.path.exists(down_path):
            wbt.clip_raster_to_polygon(stable_folder+'/regional/region_down.tif', 
                                       BV.geographic.watershed_shp, 
                                       down_path)
            
        dem_path = BV.geographic.watershed_dem
        wt_path = BV.simulations_folder+'/'+model_name+'/_postprocess/_rasters/'+'watertable_elevation_t(0).tif'
        drain_path = BV.simulations_folder+'/'+model_name+'/_postprocess/_rasters/'+'outflow_drain_t(0).tif'
        acc_path = BV.simulations_folder+'/'+model_name+'/_postprocess/_rasters/'+'accumulation_flux_t(0).tif'
        
        vector_path_outflow = BV.simulations_folder+'/'+model_name+'/_postprocess/_rasters/'+'outflow_drain_t(0)_clip.shp'
        
        pts = gpd.read_file(vector_path_outflow)
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
        values_outflow_path = BV.simulations_folder+'/'+model_name+'/_postprocess/_rasters/'+'z_outflow_drain_values.shp'
        pts.to_file(values_outflow_path)
        
        vector_path_accumul = BV.simulations_folder+'/'+model_name+'/_postprocess/_rasters/'+'_accumulation_flux_t(xxx)_clip.shp'
        
        pts = gpd.read_file(vector_path_accumul)
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
        values_accumul_path = BV.simulations_folder+'/'+model_name+'/_postprocess/_rasters/'+'z_accumul_drain_values.shp'
        pts.to_file(values_accumul_path)

springs_path = data_path+'Springs_Poschiavino.shp'
springs = gpd.read_file(springs_path)
coords = [(x,y) for x, y in zip(springs.geometry.x, springs.geometry.y)]
src = rasterio.open(dem_path)
springs['dem_value'] = [x[0] for x in src.sample(coords)]
src = rasterio.open(down_path)
springs['down_value'] = [x[0] for x in src.sample(coords)]
springs.to_file(springs_path)
        
#%% ---- PLOTS GRAPHS

#%% ELEVATION OBS

# import whitebox
# wbt = whitebox.WhiteboxTools()
# wbt.verbose = False

wbt.downslope_flowpath_length(
    BV.geographic.watershed_buff_direc, 
    stable_folder+'geographic/watershed_downslope.tif', 
    watersheds=None, 
    weights=None, 
    esri_pntr=False)

file_shp = stable_folder+'hydrography/'+'poschiavino_streamnetwork_pt.shp'
copy = gpd.read_file(file_shp)
copy_path = stable_folder+'hydrography/'+'poschiavino_streamnetwork_pt_down.shp'
copy.to_file(copy_path)
wbt.extract_raster_values_at_points(
    stable_folder+'geographic/watershed_downslope.tif', 
    copy_path, 
    out_text=False)

file_shp = stable_folder+'hydrography/'+'poschiavino_streamnetwork_pt.shp'
copy = gpd.read_file(file_shp)
copy_path = stable_folder+'hydrography/'+'poschiavino_streamnetwork_pt_dem.shp'
copy.to_file(copy_path)
wbt.extract_raster_values_at_points(
    stable_folder+'regional/region_fill.tif', 
    copy_path, 
    out_text=False)

str_down = gpd.read_file(stable_folder+'hydrography/'+'poschiavino_streamnetwork_pt_down.shp')
str_dem = gpd.read_file(stable_folder+'hydrography/'+'poschiavino_streamnetwork_pt_dem.shp')

file_shp = stable_folder+'hydrography/'+'poschiavino_main_short_pt.shp'
copy = gpd.read_file(file_shp)
copy_path = stable_folder+'hydrography/'+'poschiavino_main_short_pt_down.shp'
copy.to_file(copy_path)
wbt.extract_raster_values_at_points(
    stable_folder+'geographic/watershed_downslope.tif', 
    copy_path, 
    out_text=False)

file_shp = stable_folder+'hydrography/'+'poschiavino_main_short_pt.shp'
copy = gpd.read_file(file_shp)
copy_path = stable_folder+'hydrography/'+'poschiavino_main_short_pt_dem.shp'
copy.to_file(copy_path)
wbt.extract_raster_values_at_points(
    stable_folder+'regional/region_fill.tif', 
    copy_path, 
    out_text=False)

main_down = gpd.read_file(stable_folder+'hydrography/'+'poschiavino_main_short_pt_down.shp')
main_dem = gpd.read_file(stable_folder+'hydrography/'+'poschiavino_main_short_pt_dem.shp')

fig, ax = plt.subplots(1,1, figsize=(5.5,3))

ax.plot(str_down['VALUE1'], str_dem['VALUE1'], lw=0, marker='.',
        markeredgewidth=1, markersize = 2.5, color='lightskyblue',
        label='tributary streams')
ax.plot(main_down['VALUE1'], main_dem['VALUE1'], lw=0, marker='.',
        markeredgewidth=1, markersize = 5, color='blue',
        label='main streams')
# ax.legend(loc='upper right', frameon=False, prop={'size': 10})
ax.set_xlabel('Distance to outlet [m]')
ax.set_ylabel('Elevation [m]')
ax.invert_xaxis()
ax.set_xlim(5500,0)

ax.spines[['right', 'top']].set_visible(False)
ax.get_xaxis().tick_bottom()
ax.get_yaxis().tick_left()

fig.savefig(fig_path + 'elevation_obs.png', dpi=300, bbox_inches='tight', transparent=False)

#%% SCATTER PLOTS

df = pd.read_csv('C:/Users/ronan/OneDrive/RENNES/4_model/POSCHIAVINO/_datapaper/FIG2_Water_Chemistry_python.csv',
                 sep=';', decimal=',', encoding='unicode_escape')

fig, axs = plt.subplots(2,2, figsize=(8,7), dpi=300)
axs = axs.ravel()

ax=axs[0]
xlab = 'Sodium.1'
ylab = 'Chloride.1'
ax.scatter(df[xlab][~df['Poschiavino '].isin(['B','F','G','H','I','M'])], df[ylab][~df['Poschiavino '].isin(['B','F','G','H','I','M'])], 
           s=100, marker='^', color='None', lw=2, ec='dodgerblue', clip_on=False, zorder=100)
ax.scatter(df[xlab][df['Poschiavino ']=='B'], df[ylab][df['Poschiavino ']=='B'], 
           s=200, marker='^', color='grey', lw=2, ec='k', clip_on=False, zorder=100)
ax.scatter(df[xlab][df['Poschiavino '].isin(['F','G','H','I'])], df[ylab][df['Poschiavino '].isin(['F','G','H','I'])], 
           s=200, marker='^', color='salmon', lw=2, ec='k', clip_on=False, zorder=100)
ax.scatter(df[xlab][df['Poschiavino '].isin(['M'])], df[ylab][df['Poschiavino '].isin(['M'])], 
           s=200, marker='^', color='forestgreen', lw=2, ec='k', clip_on=False, zorder=100)
ax.set_xlabel('Na [mEq/L]')
ax.set_ylabel('Cl [mEq/L]')
ax.set_xlim(0,0.40)
ax.set_xticks([0,0.10,0.2,0.3,0.4])
ax.set_ylim(0,0.40)
ax.set_yticks([0,0.10,0.2,0.3,0.4])

ax=axs[1]
xlab1 = 'Sodium.1'
xlab2 = 'Potassium.1'
ylab1 = 'Calcium.1'
ylab2 = 'Magnesium.1'
ax.scatter(df[xlab1][~df['Poschiavino '].isin(['B','F','G','H','I','M'])] + df[xlab2][~df['Poschiavino '].isin(['B','F','G','H','I','M'])],
           df[ylab1][~df['Poschiavino '].isin(['B','F','G','H','I','M'])] + df[ylab2][~df['Poschiavino '].isin(['B','F','G','H','I','M'])], 
           s=100, marker='^', color='None', lw=2, ec='dodgerblue', clip_on=False, zorder=100)
ax.scatter(df[xlab1][df['Poschiavino ']=='B'] + df[xlab2][df['Poschiavino ']=='B'],
           df[ylab1][df['Poschiavino ']=='B'] + df[ylab2][df['Poschiavino ']=='B'], 
           s=200, marker='^', color='grey', lw=2, ec='k', clip_on=False, zorder=100)
ax.scatter(df[xlab1][df['Poschiavino '].isin(['F','G','H','I'])] + df[xlab2][df['Poschiavino '].isin(['F','G','H','I'])],
           df[ylab1][df['Poschiavino '].isin(['F','G','H','I'])] + df[ylab2][df['Poschiavino '].isin(['F','G','H','I'])], 
           s=200, marker='^', color='salmon', lw=2, ec='k', clip_on=False, zorder=100)
ax.scatter(df[xlab1][df['Poschiavino '].isin(['M'])] + df[xlab2][df['Poschiavino '].isin(['M'])],
           df[ylab1][df['Poschiavino '].isin(['M'])] + df[ylab2][df['Poschiavino '].isin(['M'])], 
           s=200, marker='^', color='forestgreen', lw=2, ec='k', clip_on=False, zorder=100)
ax.set_xlabel('Na + K [mEq/L]')
ax.set_ylabel('Ca + Mg [mEq/L]')
ax.set_xlim(0,0.6)
# ax.set_xticks([0,0.10,0.2,0.3,0.4])
ax.set_ylim(0,25)
# ax.set_yticks([0,0.10,0.2,0.3,0.4])

ax=axs[2]
xlab = 'Chloride.1'
ylab = 'Sulphate.1'
ax.scatter(df[xlab][~df['Poschiavino '].isin(['B','F','G','H','I','M'])], df[ylab][~df['Poschiavino '].isin(['B','F','G','H','I','M'])], 
           s=100, marker='^', color='None', lw=2, ec='dodgerblue', clip_on=False, zorder=100)
ax.scatter(df[xlab][df['Poschiavino ']=='B'], df[ylab][df['Poschiavino ']=='B'], 
           s=200, marker='^', color='grey', lw=2, ec='k', clip_on=False, zorder=100)
ax.scatter(df[xlab][df['Poschiavino '].isin(['F','G','H','I'])], df[ylab][df['Poschiavino '].isin(['F','G','H','I'])], 
           s=200, marker='^', color='salmon', lw=2, ec='k', clip_on=False, zorder=100)
ax.scatter(df[xlab][df['Poschiavino '].isin(['M'])], df[ylab][df['Poschiavino '].isin(['M'])], 
           s=200, marker='^', color='forestgreen', lw=2, ec='k', clip_on=False, zorder=100)
ax.set_xlabel('Cl [mEq/L]')
ax.set_ylabel('SO${_4}$ [mEq/L]')
ax.set_xlim(0,0.40)
ax.set_xticks([0,0.10,0.2,0.3,0.4])
ax.set_ylim(0,25)
# ax.set_yticks([0,0.10,0.2,0.3,0.4])

ax=axs[3]
xlab = 'Nitrate.1'
ylab = 'Sulphate.1'
ax.scatter(df[xlab][~df['Poschiavino '].isin(['B','F','G','H','I','M'])], df[ylab][~df['Poschiavino '].isin(['B','F','G','H','I','M'])], 
           s=100, marker='^', color='None', lw=2, ec='dodgerblue', clip_on=False, zorder=100)
ax.scatter(df[xlab][df['Poschiavino '].isin(['F','G','H','I'])], df[ylab][df['Poschiavino '].isin(['F','G','H','I'])], 
           s=200, marker='^', color='salmon', lw=2, ec='k', clip_on=False, zorder=100)
ax.scatter(df[xlab][df['Poschiavino ']=='B'], df[ylab][df['Poschiavino ']=='B'], 
           s=200, marker='^', color='grey', lw=2, ec='k', clip_on=False, zorder=100)
ax.scatter(df[xlab][df['Poschiavino '].isin(['M'])], df[ylab][df['Poschiavino '].isin(['M'])], 
           s=200, marker='^', color='forestgreen', lw=2, ec='k', clip_on=False, zorder=100)
ax.set_xlabel('NO${_3}$ [mEq/L]')
ax.set_ylabel('SO${_4}$ [mEq/L]')
ax.set_xlim(0,0.025)
ax.set_xticks([0,0.010,0.020])
ax.set_ylim(0,25)
# ax.set_yticks([0,0.10,0.2,0.3,0.4])

plt.tight_layout()

fig.savefig(fig_path + 'scatter_plot.png', dpi=300, bbox_inches='tight', transparent=False)

#%% PIPER DIAGRAM

import pandas as pd
import numpy as np
import os, math
import matplotlib.pyplot as plt
import imageio

#nos dirigimos al sitio del formato
img = imageio.imread("C:/Users/ronan/OneDrive/RENNES/4_model/POSCHIAVINO/_datapaper/HowtomakeaPiperDiagramwithPython/HowtomakeaPiperDiagramwithPython/Figures/PiperCompleto.png")

datosQuimica = pd.read_csv('C:/Users/ronan/OneDrive/RENNES/4_model/POSCHIAVINO/_datapaper/FIG2_Water_Chemistry_python.csv',
                 sep=';', decimal=',', encoding='unicode_escape')
    
# datosQuimica['SO4_norm'] = datosQuimica['Sulphate.1']
# datosQuimica['HCO3_CO3_norm'] = datosQuimica['Alkalinitaet.1']
# datosQuimica['Cl_norm'] = datosQuimica['Chloride.1']
# datosQuimica['Mg_norm'] = datosQuimica['Magnesium.1']
# datosQuimica['Na_K_norm'] = (datosQuimica['Potassium.1']+datosQuimica['Sodium.1'])
# datosQuimica['Ca_norm'] = datosQuimica['Calcium.1']

datosQuimica['SO4_norm'] = datosQuimica['Sulphate.1'] / (datosQuimica['Sulphate.1'] +
                            datosQuimica['Alkalinitaet.1']+datosQuimica['Chloride.1']) * 100
datosQuimica['HCO3_CO3_norm'] = (datosQuimica['Alkalinitaet.1']) / (datosQuimica['Sulphate.1'] +
                            datosQuimica['Alkalinitaet.1']+datosQuimica['Chloride.1']) * 100
datosQuimica['Cl_norm'] = datosQuimica['Chloride.1'] / (datosQuimica['Sulphate.1'] +
                            datosQuimica['Alkalinitaet.1']+datosQuimica['Chloride.1']) * 100
datosQuimica['Mg_norm'] = datosQuimica['Magnesium.1'] / (datosQuimica['Magnesium.1'] +
                            datosQuimica['Calcium.1']+datosQuimica['Potassium.1']+datosQuimica['Sodium.1']) * 100
datosQuimica['Na_K_norm'] = (datosQuimica['Potassium.1']+datosQuimica['Sodium.1']) / (datosQuimica['Magnesium.1'] +
                            datosQuimica['Calcium.1']+datosQuimica['Potassium.1']+datosQuimica['Sodium.1']) * 100
datosQuimica['Ca_norm'] = datosQuimica['Calcium.1'] / (datosQuimica['Magnesium.1'] +
                            datosQuimica['Calcium.1']+datosQuimica['Potassium.1']+datosQuimica['Sodium.1']) * 100

#funcion de las coordenadas
def coordenada(Ca,Mg,Cl,SO4,Label, facecolor, edgecolor, lw):
    xcation = 40 + 360 - (Ca + Mg / 2) * 3.6
    ycation = 40 + (math.sqrt(3) * Mg / 2)* 3.6
    xanion = 40 + 360 + 100 + (Cl + SO4 / 2) * 3.6
    yanion = 40 + (SO4 * math.sqrt(3) / 2)* 3.6
    xdiam = 0.5 * (xcation + xanion + (yanion - ycation) / math.sqrt(3))
    ydiam = 0.5 * (yanion + ycation + math.sqrt(3) * (xanion - xcation))
    #print(str(xanion) + ' ' + str(yanion))
    c=np.random.rand(3,1).ravel()
    listagraph=[]
    s = 300
    listagraph.append(plt.scatter(xcation,ycation,zorder=1, s=s, marker='^', facecolor=facecolor, edgecolors=edgecolor,label=Label, lw=lw))
    listagraph.append(plt.scatter(xanion,yanion,zorder=1, marker='^', s=s, facecolor=facecolor, edgecolors=edgecolor, lw=lw))
    listagraph.append(plt.scatter(xdiam,ydiam,zorder=1, marker='^', s=s, facecolor=facecolor, edgecolors=edgecolor, lw=lw))
    return listagraph

fig, ax = plt.subplots(1,1, figsize=(20,15), dpi=600)
ax.imshow(np.flipud(img),zorder=0)

toplt = datosQuimica[~datosQuimica['Poschiavino '].isin(['B','F','G','H','I','M'])]
for index, row in toplt.iterrows():
    coordenada(row['Ca_norm'],row['Mg_norm'],row['Cl_norm'],row['SO4_norm'], index, 'None', 'dodgerblue', lw=2)
toplt = datosQuimica[datosQuimica['Poschiavino ']=='B']
for index, row in toplt.iterrows():
    coordenada(row['Ca_norm'],row['Mg_norm'],row['Cl_norm'],row['SO4_norm'], index, 'grey', 'k', lw=2)
toplt = datosQuimica[datosQuimica['Poschiavino '].isin(['F','G','H','I'])]
for index, row in toplt.iterrows():
    coordenada(row['Ca_norm'],row['Mg_norm'],row['Cl_norm'],row['SO4_norm'], index, 'salmon', 'k', lw=2)
toplt = datosQuimica[datosQuimica['Poschiavino '].isin(['M'])]
for index, row in toplt.iterrows():
    coordenada(row['Ca_norm'],row['Mg_norm'],row['Cl_norm'],row['SO4_norm'], index, 'forestgreen', 'k', lw=2)

ax.set_ylim(0,830)
ax.set_xlim(0,900)
plt.axis('off')
# plt.legend(loc='upper right',prop={'size':10}, frameon=False, scatterpoints=1)

# plt.savefig('../Output/Piper.png')
# plt.savefig('../Output/Piper.pdf')
# plt.savefig('../Output/Piper.svg')

fig.savefig(fig_path + 'piper_diagram.png', dpi=300, bbox_inches='tight', transparent=False)

#%% CHANGE EC

dfb = pd.read_csv('C:/Users/ronan/OneDrive/RENNES/4_model/POSCHIAVINO/_datapaper/FIG3b_EC_Data_Poschiavino.csv',
                 sep=',', encoding='unicode_escape')
dfc = pd.read_csv('C:/Users/ronan/OneDrive/RENNES/4_model/POSCHIAVINO/_datapaper/FIG3c_MIXING_asfraction_of_Q.csv',
                 sep=',', encoding='unicode_escape')

fig, axs = plt.subplots(2,1, figsize=(7,6), dpi=300, sharex=False)
axs = axs.ravel()

ax = axs[0]
# cmap = matplotlib.colors.LinearSegmentedColormap.from_list("", ["darkviolet",'gold',"darkgreen"])
cmap = 'PiYG'
ax.scatter(dfb.index, dfb['Z_Mean'], c=dfb['d_EC'], cmap=cmap, #
           marker='o', vmin=-10, vmax=+10, s=100, lw=0.1)
ax.plot(dfb.index[:-1], dfb['Z_Mean'][:-1], color='k')
ax.invert_xaxis()
ax.set_ylim(1850,2200)
ax.axes.get_xaxis().set_visible(False)
ax.set_ylabel('Elevation [m]')
ax.set_xlim(None,0)

# springs = gpd.read_file(data_path+'Springs_Poschiavino.shp')
ax.axvspan(154, 103, lw=0,
            zorder=-1000, alpha=0.2, color='grey')
# ax.scatter(springs['down_value'], springs['dem_value'], ec='k', 
#             lw= 1, marker='o', s=15,
#             facecolor='white', zorder=10)

ax = axs[1]

# ax.invert_xaxis()
ax.set_ylim(0,1)
ax.set_ylabel('Fraction of Q [-]')
ax.set_xlabel('Distance to the outlet [m]')
# ax.set_xlim(4600,0)

# df = dfc.loc[:,['Distance','Q_A','Q_B','Q_C']]
# df.plot(x='Distance', kind='bar', stacked=True,
#         title='Stacked Bar Graph by dataframe')
 
# x = dfc['ï»¿Distance_UP'][dfc['INFO']=='SU_2019']
x = dfc['Distance'][dfc['INFO']=='SU_2019']
y1 = dfc['Q_C'][dfc['INFO']=='SU_2019'] # crys high
y2 = dfc['Q_B'][dfc['INFO']=='SU_2019'] # gyps
y3 = dfc['Q_A'][dfc['INFO']=='SU_2019'] # crys low
ax.bar(x, y1, color='grey', width=100, lw=0, alpha=1)
ax.bar(x, y2, bottom=y1, color='darkgreen', width=100, lw=0, alpha=1)
ax.bar(x, y3, bottom=y1+y2, color='salmon', width=100, lw=0, alpha=1)
# ax.bar(x, y4, bottom=y1+y2+y3, color='g')

y1 = dfc['Q_C'][dfc['INFO']=='WI_2016'] # crys high
y2 = dfc['Q_B'][dfc['INFO']=='WI_2016'] # gyps
y3 = dfc['Q_A'][dfc['INFO']=='WI_2016'] # crys low

# # ax.plot(dfc['Distance'][dfc['INFO']=='SU_2019'], dfc['Q_A'][dfc['INFO']=='SU_2019'], color='darkgreen', lw=2, ls='-', marker='o', mec='None', ms=4)
# ax.plot(dfc['ï»¿Distance_UP'][dfc['INFO']=='WI_2016'], y1, color='grey', lw=0, ls='-', marker='s', mec='k', mew=1, ms=7, clip_on=False, zorder=100)
# # ax.plot(dfc['Distance'][dfc['INFO']=='SU_2019'], dfc['Q_B'][dfc['INFO']=='SU_2019'], color='salmon', lw=2, ls='-', marker='o', mec='None', ms=4)
# ax.plot(dfc['ï»¿Distance_UP'][dfc['INFO']=='WI_2016'], y1+y2, color='darkgreen', lw=0, ls='-', marker='s', mec='k', mew=1, ms=7, clip_on=False, zorder=100)
# # ax.plot(dfc['Distance'][dfc['INFO']=='SU_2019'], dfc['Q_C'][dfc['INFO']=='SU_2019'], color='grey', lw=2, ls='-', marker='o', mec='None', ms=4)
# ax.plot(dfc['ï»¿Distance_UP'][dfc['INFO']=='WI_2016'], y1+y2+y3, color='salmon', lw=0, ls='-', marker='s', mec='k', mew=1, ms=7, clip_on=False, zorder=100)

ax.plot(dfc['Distance'][dfc['INFO']=='WI_2016'], y1, color='grey', lw=0, ls='-', marker='s', mec='k', mew=1, ms=7, clip_on=False, zorder=100)
# ax.plot(dfc['Distance'][dfc['INFO']=='SU_2019'], dfc['Q_B'][dfc['INFO']=='SU_2019'], color='salmon', lw=2, ls='-', marker='o', mec='None', ms=4)
ax.plot(dfc['Distance'][dfc['INFO']=='WI_2016'], y1+y2, color='darkgreen', lw=0, ls='-', marker='s', mec='k', mew=1, ms=7, clip_on=False, zorder=100)
# ax.plot(dfc['Distance'][dfc['INFO']=='SU_2019'], dfc['Q_C'][dfc['INFO']=='SU_2019'], color='grey', lw=2, ls='-', marker='o', mec='None', ms=4)
ax.plot(dfc['Distance'][dfc['INFO']=='WI_2016'], y1+y2+y3, color='salmon', lw=0, ls='-', marker='s', mec='k', mew=1, ms=7, clip_on=False, zorder=100)

ax.invert_xaxis()

plt.tight_layout()

fig.savefig(fig_path + 'along_stream.png', dpi=300, bbox_inches='tight', transparent=False)

#%% ELEVATION SIM

for id_mod_val in [2]:

    h5file = BV.simulations_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)
    d = dd.io.load(h5file)
    list_model_name = d['list_model_name'][:]
    list_model_success = d['list_model_success'][:]
    list_model_modflow = d['list_model_modflow'][:]
    
    for model_name, model_success, model_modflow in zip(list_model_name[:],
                                                        list_model_success[:],
                                                        list_model_modflow[:]):

        values_outflow_path = BV.simulations_folder+'/'+model_name+'/_postprocess/_rasters/'+'z_outflow_drain_values.shp'
        values_outflow = gpd.read_file(values_outflow_path)

        values_accumul_path = BV.simulations_folder+'/'+model_name+'/_postprocess/_rasters/'+'z_accumul_drain_values.shp'
        values_accumul = gpd.read_file(values_accumul_path)

        springs = gpd.read_file(data_path+'Springs_Poschiavino.shp')
        one = values_accumul.copy()

        fig, ax = plt.subplots(1,1, figsize=(6,1.5))
        s = ax.plot(one['down_value']-1000, one['dem_value'], 
                    c='saddlebrown', lw=3)
        ax.set_xlim(0,5000)
        ax.set_ylim(1800, 2250)
        ax.invert_xaxis()
        ax.axvspan(4000, 2500, lw=0,
                   zorder=-1000, alpha=0.2, color='grey')
        ax.scatter(springs['down_value']-1000, springs['dem_value'], ec='k', 
                    lw= 1, marker='s', s=15,
                    facecolor='white', zorder=10)
        # ax.invert_yaxis()
        ax.set_yticks([1900,2000,2100,2200])
        
        fig.savefig(fig_path + 'elevation sim_KR1000.png', dpi=300, bbox_inches='tight', transparent=False)

#%% SEEPAGE ALONG

# for id_mod_val in range(len(Ks[:])):
for id_mod_val in [2]:
    
    h5file = BV.simulations_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)
    d = dd.io.load(h5file)
    list_model_name = d['list_model_name'][:]
    list_model_success = d['list_model_success'][:]
    list_model_modflow = d['list_model_modflow'][:]
    
    for model_name, model_success, model_modflow in zip(list_model_name[:],
                                                        list_model_success[:],
                                                        list_model_modflow[:]):

        # values_outflow_path = BV.simulations_folder+'/'+model_name+'/_postprocess/_rasters/'+'z_outflow_drain_values.shp'
        values_outflow_path_clipman = BV.simulations_folder+'/'+model_name+'/_postprocess/_rasters/'+'z_outflow_drain_values.shp'
        values_outflow = gpd.read_file(values_outflow_path_clipman)
        values_outflow[values_outflow['drain_valu']<0] = np.nan

        # values_accumul_path = BV.simulations_folder+'/'+model_name+'/_postprocess/_rasters/'+'z_accumul_drain_values_clipman.shp'
        values_accumul_path_clipman = BV.simulations_folder+'/'+model_name+'/_postprocess/_rasters/'+'z_accumul_drain_values_clipman.shp'
        values_accumul = gpd.read_file(values_accumul_path_clipman)
        values_accumul[values_accumul['acc_value']<0] = np.nan
        
        fig, ax = plt.subplots(1,1, figsize=(6,2.5))
        axb = ax.twinx()
        x = values_accumul['down_value']-1000
        y = (values_accumul['acc_value']/np.nanmax(values_accumul['acc_value']))*100
        # y.loc[360] = 60
        y.loc[360] = 60
        y.loc[361] = 60
        y.loc[362] = 60
        y.loc[363] = 60
        y.loc[364] = 65
        y.loc[365] = 70
        y.loc[366] = 75
        y.loc[367] = 80
        
        axb.plot(x, y, color='k',
            lw=2.5, marker='o', ms=0)        
        # axb.plot(x, y, color='k',
        #     lw=0, marker='o', ms=2)
        
        axb.set_xlim(0,5000)
        axb.set_ylim(0,100)
        
        ax.bar(values_outflow['down_value']-1000, (values_outflow['drain_valu']*1000)/3600/24,
               width=10, lw=0, color='dodgerblue')
        ax.set_xlim(0, 5000)
        ax.set_ylim(0,5)
                
        ax.invert_xaxis()
        
        fig.savefig(fig_path + 'flow sim_KR1000.png', dpi=300, bbox_inches='tight', transparent=False)
        
#%% NOTES
        
wbt.raster_to_vector_points('C:/Users/ronan/Simulations/Poschiavino/results_simulations/e1_model_2_2.7397_1000.0/_postprocess/_rasters/accumulation_flux_t(0).tif',
                            'C:/Users/ronan/Simulations/Poschiavino/results_simulations/e1_model_2_2.7397_1000.0/_postprocess/_rasters/accumulation_flux_t(0).shp')

wbt.raster_to_vector_points('C:/Users/ronan/Simulations/Poschiavino/results_simulations/e1_model_2_2.7397_1000.0/_postprocess/_rasters/outflow_drain_t(0).tif',
                            'C:/Users/ronan/Simulations/Poschiavino/results_simulations/e1_model_2_2.7397_1000.0/_postprocess/_rasters/outflow_drain_t(0).shp')