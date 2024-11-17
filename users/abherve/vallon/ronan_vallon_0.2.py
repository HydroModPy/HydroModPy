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

git_path = "D:/Users/abherve/GITHUB/HydroModPy-dev0.1/"
data_path = 'D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Vallon/_data/'
hgs_path = 'D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Vallon/_hgs/'
out_path = 'E:/_RONAN/_E_SIMULATIONS/VALLON/'
fig_path = 'D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Vallon/_figures/_bulk/'

dems_path = data_path + '_gis/DEM/' # reginal DEM or conceptual DEM
dem_name = 'EUDTM_Alps_2056_bilinear_clip.tif' # EUDTM_Alps_30m_vallon
dem_path = dems_path + dem_name

subbasin_path = True # generate subbasins from stations or manual points
from_dem = None # True or False if the process start from a given DEM of xyz file
cell_size = None # specify new resolution from a given DEM or None
from_shp = None

# watershed_names = ['Both_EUDTM30m',
#                    'Vare_EUDTM30m',
#                    'Nant_EUDTM30m']
# from_xyvs = [ [2572138.212,1122730.976,300,10,'EPSG:2056'],
#               [2574842.267,1122488.817,150,10,'EPSG:2056'],
#               [2574600.362,1122366.973,150,10,'EPSG:2056'] ]

watershed_names = ['Nant_EUDTM30m']
from_xyvs = [ [2574600.362,1122366.973,100,25,'EPSG:2056'] ]

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
  
    try:
        print(BV.geographic.area.round(2))
        print(BV.geographic.slope.round(2))
    except:
        pass
    
    try:
        visualization_watershed.watershed_local(dem_path, BV)
        visualization_watershed.watershed_dem(BV)
    except:
        pass

    BV.add_intermittency('None','None')
    # if watershed_name == 'Vallons_EUDTM30m':
    #     BV.add_subbasin(data_path+'_gis/SIG/'+'_additional_Vallons/', sub_snap_dist=150)
    if watershed_name == 'Nant_EUDTM30m':
        BV.add_subbasin(data_path+'_gis/SIG/'+'_additional_Nant', sub_snap_dist=150)
    # if watershed_name == 'Vare_EUDTM30m':
    #     BV.add_subbasin(data_path+'_gis/SIG/'+'_additional_Vare', sub_snap_dist=150)   

dem_data = imageio.imread(BV.geographic.watershed_box_buff_dem)

#%% HYDRO

hydrography_path = data_path + '_gis/Hydrography_clipped/' # add hydrographic shapefiles

types_obs = ['perennial_natural_streams',
             # 'fully_natural_streams',
             # 'fully_natural_streams_springs',
             # 'fully_natural_streams_springs_wetlands'
             ]
fields_obs = ['fid',
              # 'fid',
              # 'fid',
              # 'fid'
              ]

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

#%% ---- CLIMATE    

#%% IMPORT SUFREX HGS

### SURFEX - CLIP / EXTRACT / DATA

work_dir = data_path + '_safransurfex_climate/'
raw_path = work_dir + 'france/'
clip_path = work_dir + 'vallon/'
mesh_path = work_dir + 'mesh/maille_meteo_fr_pr93_2056.shp'
# site_path = data_path + '_gis/SIG/boxbuff_ref.shp'
site_path = BV.stable_folder+'/geographic/box_buff.shp'
mesh = gpd.read_file(mesh_path)
site = gpd.read_file(site_path)
site_mesh = mesh.clip(site)
fig, ax = plt.subplots(1, 1, figsize=(6, 6))
mesh.plot(ax=ax)
site_mesh.plot(ax=ax)
num_id = list(site_mesh['num_id'].values)
print(num_id)

"""
### FRANCE SCALE TO VALLON SCALE ###
mod_list = ['REA']
var_list = ['TAS','PPT','ETP','RUN','REC','SNOW']
sce_list = ['historic']
for mod in mod_list:
    dic = {}
    dic[mod] = {}        
    for var in var_list:
        dic[mod][var]={}                
        for sce in sce_list:
            # try:
            x = pd.read_hdf(raw_path + mod + '.h5', var + '/' + sce)
            print('YES' + ' - ' + mod.upper()+' - '+var.upper()+' - '+sce.upper())
            # x = x.iloc[:, num_id]
            x = x.loc[:, x.columns.isin(num_id)]
            dic[mod][var][sce] = x
            dic[mod][var][sce].to_hdf(clip_path + mod + '.h5', var + '/' + sce)
            # except: 
            #     print('NO' + ' - ' + mod.upper()+' - '+var.upper()+' - '+sce.upper())
            #     pass
            # values['MEAN'] = values.mean(numeric_only=True, axis=1)
            # values.to_hdf(h5file, var+'/'+sce)
    dd.io.save(clip_path + mod + 'bis.h5', dic) # long but all    

### FRANCE SCALE TO VALLON SCALE ###
simulations = ['REA']
variables = ['TAS','PPT','ETP','RUN','REC','SNOW']
scenarios = ['historic']
values = {}
data_folder = 'G:/UNINE/SIMULATIONS/VALLON/_data/_safransurfex/vallon/'
for sim in simulations:
    try:
        os.remove(data_folder+sim+'.h5')
    except:
        pass
    values[sim] = {}
    h5file = (data_folder+sim+'.h5')
    for var in variables:
        values[sim][var] = {}
        # for sce in scenarios:
        valuesT = pd.read_hdf(raw_path+'/'+sim+'.h5',var+'/'+sce)
        print('Find: '+sim+'-'+var)
        if (sim == 'REA') | (sim == 'OLD') | (sim == 'REAUP'):
            valuesT.index.freq = valuesT.index.inferred_freq
        # values = values.loc[:,self.cells_list]
        valuesT = valuesT[valuesT.columns.intersection(num_id)]
        valuesT['MEAN'] = valuesT.mean(numeric_only=True, axis=1)
        valuesT.to_hdf(h5file, var+'/'+sce)
        values[sim][var][sce] = valuesT
"""

mod = 'REA'
sce = 'historic'

BV = watershed_root.Watershed(watershed_name='Nant_EUDTM30m',
                              dem_path=dem_path, 
                              out_path=out_path,
                              load=True)

stable_folder = out_path+'/'+'Nant_EUDTM30m'+'/'+'results_stable/'
surfex_data = stable_folder + 'climatic/'

if not os.path.exists(stable_folder+'climatic/REA.h5'):
    BV.add_safransurfex(clip_path)

dfd_both = pd.DataFrame()

raws = ['REC', 'RUN', 'ETP', 'PPT', 'TAS','SNOW']
variables = ['REC', 'RUN', 'ETP', 'PPT', 'TAS', 'SNOW','EFF']

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

dfm = dfd.copy() 
mask = dfm.resample("M").count() >= 27
dfm = dfm.resample("M").mean()[mask]

dfm_surf = dfm.copy()
dfm_surf = select_period(dfm_surf, 1960, 2019)
tas = dfm_surf['TAS_REA_historic']
import pyet
dfm_surf['Oudin'] = abs(pyet.oudin(tas, lat=pyet.deg_to_rad(48)))
dfm_surf["Hargreaves"] = abs(pyet.hargreaves(tas, tmax=tas.max(), tmin=tas.min(), lat=pyet.deg_to_rad(48)))
dfm_surf["Hamon"] = abs(pyet.temperature.hamon(tas, lat=pyet.deg_to_rad(48)))
dfm_surf["Macguinness"] = abs(pyet.radiation.mcguinness_bordne(tas, lat=pyet.deg_to_rad(48)))
deficiency_evaporation(dfm_surf, 'PPT_REA_historic',
                            'Oudin', 'PPT-ETP',
                            'ETR', 'RU', 'DE')

dfy = dfd.copy()
mask = dfy.resample("Y").count() >= 364
dfy = dfy.resample("Y").mean()[mask]

rea = dfd[(dfd.index.year>=1960) & (dfd.index.year<=2019)].filter(regex='REA')

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

### HGS - CLIP / EXTRACT / DATA

# init_path = data_path + '_hgs/Additional Clement/Catchment_water_balance/'
init_path = hgs_path + '/Additional/Catchment_water_balance/'

hgs_wb = pd.read_csv(init_path + 'nant_v100fo.water_balance - Copie.dat', 
                       delim_whitespace=True, 
                       # header=True
                       )

hgs_wb.iloc[0]['Time'] = 0
hgs_wb = hgs_wb[hgs_wb['Time'].mul(1e10).mod(1e10).astype(int).isin([0])]

hgs_wb['Time_y'] = hgs_wb['Time'] / 365

# x = pd.date_range(start='01/10/2014', end='30/09/2019', freq='D')

hgs_wb['datetime'] = pd.date_range(start='10/01/2014', end='10/01/2018', freq='D')
hgs_wb.index = hgs_wb['datetime']

### HGS - DATA MIX

# init_path = data_path + '_hgs/Supplementary Information Thornton/full_model/'
init_path = hgs_path + '/Additional/Observed_time_series/Daily/Q/'

Qobs_list =['1_q_vdn_u_s1_obs_NAs_removed.smp',
            '1_q_weir_s2_obs_NAs_removed.smp',
            '1_q_ric_s3_obs_NAs_removed.smp'
            ]
areas = [9.4, 13.7, 14.1]
i = 0
for Sn, Qobs_name in zip(['S1','S2','S3'], Qobs_list[:]):
    print(Sn)
    dfQ = pd.read_csv(init_path+Qobs_name, delim_whitespace=True, header=None)
    dfQ['datetxt'] = dfQ[1]+ ' ' + dfQ[2].apply(str)
    dfQ['datetime'] = [datetime.strptime(date, "%d/%m/%Y %H:%M:%S") for date in dfQ['datetxt']]
    dfQ.index = dfQ['datetime']
    dfQp = dfQ.resample('D').mean()
    data_index = dfQp[3]/(areas[i]*1e6)
    hgs_wb['Q_'+Sn+'_m/d'] = data_index
    i += 1

# init_path = data_path + '_hgs/Supplementary Information Thornton/full_model/'
init_path = hgs_path + '/Additional/Observed_time_series/Daily/GWls/'

Pobs_list = ['1_gwl_n1_obs_NAs_removed.smp',
             '1_gwl_n2_obs_NAs_removed.smp',
             '1_gwl_n3_obs_NAs_removed.smp',
             '1_gwl_n4_obs_NAs_removed.smp'
             ]
i = 0
for Nn, Pobs_name in zip(['N1','N2','N3','N4'], Pobs_list[:]):
    print(Nn)
    dfP = pd.read_csv(init_path+Pobs_name, delim_whitespace=True, header=None)   
    dfP['datetxt'] = dfP[1]+ ' ' + dfP[2].apply(str)
    dfP['datetime'] = [datetime.strptime(date, "%d/%m/%Y %H:%M:%S") for date in dfP['datetxt']]
    dfP.index = dfP['datetime']
    dfPp = dfP.resample('D').mean()
    data_index = dfPp[3]
    hgs_wb['P_'+Nn+'_m'] = data_index
    i += 1

hgs_wb['PPT_m/d'] = hgs_wb['rain_plus_all_melt'] / (37*1e6)
hgs_wb['AET_m/d'] = hgs_wb['ET_4_AET'] / (37*1e6) * -1
hgs_wb['PET_m/d'] = hgs_wb['ET_4_PET'] / (37*1e6)
hgs_wb['OVER_m/d'] = hgs_wb['Overland'] / (37*1e6)
hgs_wb['INFILT_m/d'] = hgs_wb['Infilt'] / (37*1e6)
hgs_wb['EXFILT_m/d'] = hgs_wb['Exfilt'] / (37*1e6) * -1
hgs_wb['PPT-AET_m/d'] = hgs_wb['PPT_m/d']-hgs_wb['AET_m/d']

# plt.plot(hgs_wb['PPT-AET_m/d'])
# plt.plot(hgs_wb['INFILT_m/d'])
# plt.plot(hgs_wb['OVER_m/d'])
# plt.plot(hgs_wb['EXFILT_m/d'])

hgs_drop = hgs_wb.dropna(subset='Q_S2_m/d')
bil_ppt = hgs_drop['PPT_m/d'].resample('Y').mean()*1000*365
bil_aet = hgs_drop['AET_m/d'].resample('Y').mean()*1000*365
bil_dis = hgs_drop['Q_S2_m/d'].resample('Y').mean()*1000*365
print(bil_ppt.mean().astype(int),bil_aet.mean().astype(int),bil_dis.mean().astype(int))

hgs_wb['PPT-AET_m/d_sim1'] = hgs_wb['PPT-AET_m/d']
hgs_wb['PPT-AET_m/d_sim1'][hgs_wb['PPT-AET_m/d_sim1']<0] = 0

bil_rec = hgs_wb['PPT-AET_m/d_sim1'].resample('Y').mean()*1000*365
print(bil_rec)

fig, ax = plt.subplots(1,1, figsize=(7,4))
ax.plot(hgs_wb['PPT_m/d'], c='darkviolet', label='PPT_m/d')
ax.plot(hgs_wb['AET_m/d'], c='darkorange', label='AET_m/d')
ax.plot(hgs_wb['PET_m/d'], c='grey', label='PET_m/d')
ax.plot(hgs_wb['INFILT_m/d'], c='forestgreen', label='INFILT_m')
ax.plot(hgs_wb['EXFILT_m/d'], c='red', label='EXFILT_m/d')
ax.set_xlim(pd.to_datetime('2016'), pd.to_datetime('2017'))
ax.set_ylim(-0.005,0.05)
# ax.plot(hgs_wb['PPT_m/d']-hgs_wb['AET_m/d']-hgs_wb['EXFILT_m/d'], c='k')
# ax.plot(hgs_wb['PPT_m/d']-hgs_wb['AET_m/d'], c='k')
# ax.set_yscale('log')
ax.legend()

fig, ax = plt.subplots(1,1, figsize=(7,3), dpi=300)
ax.plot(hgs_wb['PPT_m/d']*1000, c='purple', label='PPT')
ax.plot(hgs_wb['PPT-AET_m/d_sim1']*1000, c='grey', label='PPT-AET')
# ax.set_yscale('log')
# ax.set_ylim(1e-1, 100)
years_maj = mdates.YearLocator()   # every year
months_maj = mdates.MonthLocator()  # every x month
ax.xaxis.set_major_locator(years_maj)
ax.xaxis.set_minor_locator(months_maj)
# ax.set_xlim(pd.to_datetime('2016'), pd.to_datetime('2019'))
ax.legend(loc='upper right')
ax.set_ylabel('Climatic inputs [mm/d]')
ax.set_xlabel('Date')
# fig.tight_layout()

#%% SURFEX - PLOT RAW

mod = 'REA'
sce = 'historic'
h5file = clip_path + mod + 'bis.h5'
d = dd.io.load(h5file)

var_list = ['TAS','PPT','ETP','RUN','REC','SNOW']
var_list2 = ['PPT','ETP','RUN','REC','SNOW']
couleurs = ['purple','darkorange','dodgerblue','forestgreen','grey']

fig, ax = plt.subplots(figsize=(7,4))
axb = ax.twinx()
for i, var in enumerate(var_list2):
    x = d[mod][var][sce]#.loc[start:end]
    x = x[(x.index.year >= 2014) & (x.index.year <= 2019)]
    x['MEAN'] = x.mean(axis=1)
    if var == 'PPT' or var == 'SNOW':
        axb.plot(x['MEAN'], c=couleurs[i], label=var)
        axb.set_ylim(0,200)
        axb.legend(loc='upper right')
        axb.set_ylabel('PPT / SNOW [mm]')
    else:
        ax.plot(x['MEAN'], c=couleurs[i], label=var)
        ax.set_ylim(0,30)
        ax.legend(loc='lower left')
        ax.set_ylabel('ETP / RUN / REC [mm]')
    ax.set_xlabel('Date')	
    ax.set_xlim([pd.to_datetime(str(x.first_valid_index().year)), 
    pd.to_datetime(str(x.last_valid_index().year))])
    axb.invert_yaxis()
    ax.set_title(mod + ' - ' + sce.upper())
    plt.tight_layout()
    
# ax.set_yscale('symlog')

#%% SURFEX - PLOT BALANCE

df_intm = dfd.resample('M').mean()[dfd.resample("M").count() >= 27]
df_intm = df_intm.groupby([lambda x: x.month]).mean()

fig, ax = plt.subplots(1,1, figsize=(4,5))
axt = ax.twinx()
step = 'pre'

axt.plot(df_intm.index,  ((df_intm['PPT_REA_historic']*30) + (df_intm['SNOW_REA_historic']*30)) - df_intm['ETP_REA_historic']*30,
                color='grey', alpha=1, lw=1, ls='-')
axt.plot(df_intm.index,  ((df_intm['PPT_REA_historic']*30)) - df_intm['ETP_REA_historic']*30,
                color='purple', alpha=1, lw=1, ls='-')
axt.plot(df_intm.index,  ((df_intm['PPT_REA_historic']*30)) + df_intm['SNOW_REA_historic']*30,
                color='k', alpha=1, lw=1, ls=':')
axt.fill_between(df_intm.index, 0, df_intm['PPT_REA_historic']*30,
                interpolate=False, color='purple', alpha=1, lw=3, ec='purple',
                fc='None',
                step=step)
axt.fill_between(df_intm.index, 0, df_intm['SNOW_REA_historic']*30,
                interpolate=False, color='grey', alpha=1, lw=3, ec='grey',
                fc='None',
                step=step)
axt.set_ylim(0,500)

ax.fill_between(df_intm.index, 0, df_intm['REC_REA_historic']*30,
                interpolate=False, color='forestgreen', alpha=1, lw=3, ec='forestgreen',
                fc='None',
                step=step)
ax.fill_between(df_intm.index, 0, df_intm['RUN_REA_historic']*30,
                interpolate=False, color='dodgerblue', alpha=1, lw=3, ec='dodgerblue',
                fc='None',
                step=step)
ax.set_ylim(0,500)

ax.plot(df_intm.index, df_intm['TAS_REA_historic'],
                color='red', alpha=1, lw=3, zorder=1)
ax.plot(df_intm.index, df_intm['ETP_REA_historic']*30,
                color='darkorange', alpha=1, lw=3, zorder=-1)

ax.set_xticks(np.arange(1,13,1))
ax.set_xticklabels(['J','F','M','A','M','J','J','A','S','O','N','D'])
ax.set_xlim(1,12)

axt.invert_yaxis()

#%% SURFEX - PLOT DE

var = 'DE'

df = dfd.copy()
df = select_period(df, 1960, 2019)

dfm = df.resample('M').mean()#.groupby([lambda x: x.month]).mean()

dfm_surf = dfm.copy()
dfm_surf = select_period(dfm_surf, 1960, 2019)
tas = dfm_surf['TAS_REA_historic']
import pyet
dfm_surf['Oudin'] = abs(pyet.oudin(tas, lat=pyet.deg_to_rad(48)))
dfm_surf["Hargreaves"] = abs(pyet.hargreaves(tas, tmax=tas.max(), tmin=tas.min(), lat=pyet.deg_to_rad(48)))
dfm_surf["Hamon"] = abs(pyet.temperature.hamon(tas, lat=pyet.deg_to_rad(48)))
dfm_surf["Macguinness"] = abs(pyet.radiation.mcguinness_bordne(tas, lat=pyet.deg_to_rad(48)))
dfm_surf['PPTSNOW'] = dfm_surf['REC_REA_historic'] + dfm_surf['RUN_REA_historic']
# deficiency_evaporation(dfm_surf, 'PPT_REA_historic',
#                             'Oudin', 'PPT-ETP',
#                             'ETR', 'RU', 'DE')
deficiency_evaporation(dfm_surf, 'PPTSNOW',
                            'Oudin', 'PPT-ETP',
                            'ETR', 'RU', 'DE')

dfm = dfm_surf.copy()

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
wy[wy==0] = 0

tot = dfm.dropna(axis=1, how='all')
tot = dfm.groupby([(dfm.index.year),(dfm.index.month)]).mean()
tot = tot.rename_axis(["year", "month"])
tot = tot.query("month == "+"["+'1,2,3,4,5,6,7,8,9,10,11,12'+"]")
tot = tot.groupby('year').sum()
tot.index =  pd.to_datetime(tot.index, format='%Y')
tot[tot==0] = 0

hw = dfm.dropna(axis=1, how='all')
hw = dfm.groupby([(dfm.index.year),(dfm.index.month)]).mean()
hw = hw.rename_axis(["year", "month"])
hw = hw.query("month == "+"["+'10,11,12'+"]")
hw = hw.groupby('year').sum()
hw.index =  pd.to_datetime(hw.index, format='%Y')
hw[hw==0] = 0

hw2 = dfm.dropna(axis=1, how='all')
hw2 = dfm.groupby([(dfm.index.year),(dfm.index.month)]).mean()
hw2 = hw2.rename_axis(["year", "month"])
hw2 = hw2.query("month == "+"["+'1,2,3'+"]")
hw2 = hw2.groupby('year').sum()
hw2.index =  pd.to_datetime(hw2.index, format='%Y')
hw2[hw2==0] = 0

lw = dfm.dropna(axis=1, how='all')
lw = dfm.groupby([(dfm.index.year),(dfm.index.month)]).mean()
lw = lw.rename_axis(["year", "month"])
lw = lw.query("month == "+"["+'4,5,6'+"]")
lw = lw.groupby('year').sum()
lw.index =  pd.to_datetime(lw.index, format='%Y')
lw[lw==0] = 0

lw2 = dfm.dropna(axis=1, how='all')
lw2 = dfm.groupby([(dfm.index.year),(dfm.index.month)]).mean()
lw2 = lw2.rename_axis(["year", "month"])
lw2 = lw2.query("month == "+"["+'7,8,9'+"]")
lw2 = lw2.groupby('year').sum()
lw2.index =  pd.to_datetime(lw2.index, format='%Y')
lw2[lw2==0] = 0


fig, ax = plt.subplots(1,1,figsize=(7, 3))
# ax.step(tot.index, tot.DE*30, color='k', lw=2, alpha=0.6, where='mid')
ax.step(hw2.index, hw2.DE*30, color='dodgerblue', lw=2, alpha=0.6, where='mid')
ax.step(hw.index, hw.DE*30, color='darkorange', lw=2, alpha=0.6, where='mid')
ax.step(lw.index, lw.DE*30, color='forestgreen', lw=2, alpha=0.6, where='mid')
ax.step(lw2.index, lw2.DE*30, color='red', lw=2, alpha=0.6, where='mid')
# ax.bar(hw.index, hw.DE*30, color='darkorange', width=350, lw=0.5, alpha=0.5)
# ax.bar(hw2.index, hw2.DE*30, color='dodgerblue', width=350, lw=0.5, alpha=0.5)
# ax.bar(lw.index, lw.DE*30, color='forestgreen', width=350, lw=0.5, alpha=0.5)
# ax.bar(lw2.index, lw2.DE*30, color='red', width=350, lw=0.5, alpha=0.5)
# ax.plot(hw.index, hw.DE*30, color='darkorange', lw=2, alpha=1)
# ax.plot(hw2.index, hw2.DE*30, color='dodgerblue', lw=2, alpha=1)
# ax.plot(lw.index, lw.DE*30, color='forestgreen', lw=2, alpha=1)
# ax.plot(lw2.index, lw2.DE*30, color='red', lw=2, alpha=1)
ax.step(wy.index, wy.DE*365, color='k', lw=2, alpha=0.6, where='mid')
ax.set_xlim(pd.to_datetime('1960'), pd.to_datetime('2019'))
ax.set_ylabel('Evaporation \n deficiency [mm/month]')
ax.set_ylim(0, None)
import matplotlib.dates as mdates
years = mdates.YearLocator(10)   # every year
years_min = mdates.YearLocator(1)   # every year
years_fmt = mdates.DateFormatter('%Y')
ax.xaxis.set_major_locator(years)
ax.xaxis.set_major_formatter(years_fmt)
ax.xaxis.set_minor_locator(years_min)
ax.grid(alpha=0.25, zorder=-1)

center_x,center_y, slope, intercept, r_value, p_value, std_err, lenght_reg = linregress(range(len(wy)), wy.DE*365)
plt.plot(wy.index, (np.arange(0,len(wy),1) * slope)+intercept, c='k', ls='--', lw=2)

# for date in ['1976', '1989', '1990', '2003', '2005', '2006', '2017', '2018', '2019']:
# for date in ['1976', '1989', '1990', '2003']:
#     ax.axvline(pd.to_datetime(date), c='k', zorder=-1000, ls='--', lw=1)

plt.tight_layout()

#%% SURFEX - PLOT XY PPTSNOW

mod = 'REA'
sce = 'historic'

fig, axs = plt.subplots(1,3, figsize=(12,4))
axs = axs.ravel()

tit = ['High water','Low water','Water year']

xlims = []
ylims = []

for i, j in enumerate([
                        hw,
                        lw,
                        wy
                       ]):    
    ax = axs[i]
    if i<=1:
        p = j.filter(regex='PPT'+'_'+'REA')
        p = p.dropna(axis=0)  #*182
        sno = j.filter(regex='SNOW'+'_'+'REA')
        sno = sno.dropna(axis=0)  #*182
    else :
        p = j.filter(regex='PPT'+'_'+'REA')
        p = p.dropna(axis=0) *365
        sno = j.filter(regex='SNOW'+'_'+'REA')
        sno = sno.dropna(axis=0) *365
    t = j.filter(regex='TAS'+'_'+'REA')
    t = t.dropna(axis=0)    
    xlims.append(p.min())
    xlims.append(p.max())
    ylims.append(t.min())
    ylims.append(t.max())
    xm = ( (p.min()+sno.min()) + (p.max()+sno.max()) ) / 2
    ym = ( t.min() + t.max() ) / 2

    n = p.index.year
    print(len(p),len(t),len(n))
    scat = ax.scatter(
                        p['PPT'+'_'+mod+'_'+sce] +
                      sno['SNOW'+'_'+mod+'_'+sce]
                      ,
                      t['TAS'+'_'+mod+'_'+sce], c=n, cmap='jet', marker="o",
                      s=200, zorder=1, lw=0.5, alpha=0.75)

    # for k, txt in enumerate(n):
    #     ax.annotate(txt, (p.iloc[k], t.iloc[k]), family='sans-serif', fontsize=4.5, 
    #                 color='black', weight="bold", ha='center', va='center', zorder=2)    
    ax.set_xlabel('Precipitation + Snow [mm/j] ', labelpad = +15)
    ax.set_ylabel('Temperature [°C]', labelpad = +15)    
    ax.set_title(tit[i], pad = +10) #keep only station names
    # ax.spines['right'].set_visible(False)
    # ax.spines['top'].set_visible(False)
    # tick = np.linspace(t.min()[0], t.max()[0] +1, 10)
    # ax.set_yticks(tick)
    # tick = np.linspace(p.min()[0], p.max()[0] +10, 5)
    # ax.set_xticks(tick)
    """
    import matplotlib.ticker as plticker
    loc = plticker.MultipleLocator(base=200) # this locator puts ticks at regular intervals
    ax.xaxis.set_major_locator(loc)
    loc = plticker.MultipleLocator(base=1) # this locator puts ticks at regular intervals
    ax.yaxis.set_major_locator(loc)
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax.yaxis.set_ticks_position('left')
    ax.xaxis.set_ticks_position('bottom')
    """
    # ax.axvline(x=xm[0], c='k', ls='--', zorder=0)
    ax.axhline(y=ym[0], c='k', ls='--', zorder=0)
    ax.set_xlim(1000,2500)
    print(ax.get_xlim())
    ax.set_xticks(np.arange(1000,2600,500))
    
# for a in range(3):
#     fig.axes[a].set_xlim(np.array(xlims).min(), np.array(xlims).max())
#     fig.axes[a].set_ylim(np.array(ylims).min(), np.array(ylims).max())

dates = n
dates = dates[0::10]
leng = len(dates)
cmap = cm.get_cmap('jet', len(n))

cax = fig.add_axes([1.0, 0.25, 0.01, 0.5])
norm = mpl.colors.BoundaryNorm(np.arange(0,len(n)+1)-0.5, len(n))
sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
sm.set_array([])
cbar = plt.colorbar(sm, cax=cax, aspect=30, alpha=0.75)
cbar.set_ticks(np.arange(0,len(n),10))
cbar.set_ticklabels(dates)
cbar.ax.tick_params(labelsize=10) 
    
plt.tight_layout()

# fig.savefig(fig_path+'evolution_xy_temppt'+'.png', dpi=300, bbox_inches='tight')

#%% SURFEX - PLOT RECRUN

mod = 'REA'
sce = 'historic'

fig, axs = plt.subplots(1,3, figsize=(12,4))
axs = axs.ravel()

tit = ['High water','Low water','Water year']

xlims = []
ylims = []

for i, j in enumerate([
                        hw,
                        lw,
                        wy
                       ]):    
    ax = axs[i]
    if i == 2:
        p = j.filter(regex='REC'+'_'+'REA') *365
        p = p.dropna(axis=0)  #*182
        sno = j.filter(regex='RUN'+'_'+'REA') *365
        sno = sno.dropna(axis=0)  #*182
    else:
        p = j.filter(regex='REC'+'_'+'REA')
        p = p.dropna(axis=0)  #*182
        sno = j.filter(regex='RUN'+'_'+'REA')
        sno = sno.dropna(axis=0)  #*182
    t = j.filter(regex='TAS'+'_'+'REA')
    t = t.dropna(axis=0)    
    xlims.append(p.min())
    xlims.append(p.max())
    ylims.append(t.min())
    ylims.append(t.max())
    xm = ( (p.min()+sno.min()) + (p.max()+sno.max()) ) / 2
    ym = ( t.min() + t.max() ) / 2

    n = p.index.year
    print(len(p),len(t),len(n))
    scat = ax.scatter(
                        p['REC'+'_'+mod+'_'+sce] +
                      sno['RUN'+'_'+mod+'_'+sce]
                      ,
                      t['TAS'+'_'+mod+'_'+sce], c=n, cmap='jet', marker="o",
                      s=200, zorder=1, lw=0.5, alpha=0.75)

    # for k, txt in enumerate(n):
    #     ax.annotate(txt, (p.iloc[k], t.iloc[k]), family='sans-serif', fontsize=4.5, 
    #                 color='black', weight="bold", ha='center', va='center', zorder=2)    
    ax.set_xlabel('Recharge + Runoff [mm/j] ', labelpad = +15)
    ax.set_ylabel('Temperature [°C]', labelpad = +15)    
    ax.set_title(tit[i], pad = +10) #keep only station names
    # ax.spines['right'].set_visible(False)
    # ax.spines['top'].set_visible(False)
    # tick = np.linspace(t.min()[0], t.max()[0] +1, 10)
    # ax.set_yticks(tick)
    # tick = np.linspace(p.min()[0], p.max()[0] +10, 5)
    # ax.set_xticks(tick)
    """
    import matplotlib.ticker as plticker
    loc = plticker.MultipleLocator(base=200) # this locator puts ticks at regular intervals
    ax.xaxis.set_major_locator(loc)
    loc = plticker.MultipleLocator(base=1) # this locator puts ticks at regular intervals
    ax.yaxis.set_major_locator(loc)
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax.yaxis.set_ticks_position('left')
    ax.xaxis.set_ticks_position('bottom')
    """
    # ax.axvline(x=xm[0], c='k', ls='--', zorder=0)
    ax.axhline(y=ym[0], c='k', ls='--', zorder=0)
    ax.set_xlim(500,2000)
    print(ax.get_xlim())
    ax.set_xticks(np.arange(500,2100,500))
    
# for a in range(3):
#     fig.axes[a].set_xlim(np.array(xlims).min(), np.array(xlims).max())
#     fig.axes[a].set_ylim(np.array(ylims).min(), np.array(ylims).max())

dates = n
dates = dates[0::10]
leng = len(dates)
cmap = cm.get_cmap('jet', len(n))

cax = fig.add_axes([1.0, 0.25, 0.01, 0.5])
norm = mpl.colors.BoundaryNorm(np.arange(0,len(n)+1)-0.5, len(n))
sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
sm.set_array([])
cbar = plt.colorbar(sm, cax=cax, aspect=30, alpha=0.75)
cbar.set_ticks(np.arange(0,len(n),10))
cbar.set_ticklabels(dates)
cbar.ax.tick_params(labelsize=10) 
    
plt.tight_layout()

# fig.savefig(fig_path+'evolution_xy_temppt'+'.png', dpi=300, bbox_inches='tight')

#%% SURFEX - PLOT INTERMENS

var_list = ['TAS','PPT','SNOW','ETP','RUN','REC']
couleurs = ['red','purple','gray','darkorange','dodgerblue','forestgreen']

fig, axs = plt.subplots(6,1,figsize=(3.5,11), sharex=True, sharey=False)
# axb = ax.twinx()
axs = axs.ravel()

for i, var in enumerate(var_list):
    
    ax = axs[i]
    
    data_index = dfd[var+'_'+mod+'_'+sce]
    
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

#%% HGS - PLOT INPUTS

fig, ax = plt.subplots(figsize=(7,4))
ax.plot(hgs_wb['rain_plus_all_melt'] / (37*1e6) * 1000, c='purple', label='PPT + SNOW MELT')
# ax.plot(hgs_wb['ET_4_PET'] / (37*1e6) * 1000, c='green',  label='PET')
ax.plot((hgs_wb['rain_plus_all_melt'] - (hgs_wb['ET_4_AET']*-1)) / (37*1e6) * 1000 , c='darkgrey',  label='PPT + SNOW MELT - AET')
ax.plot(hgs_wb['ET_4_AET'] / (37*1e6) * 1000 * -1, c='darkorange',  label='AET')
# ax.set_ylim(0,200)
ax.legend(loc='upper right')
ax.set_xlabel('Date')	
years_maj = mdates.YearLocator()   # every year
months_maj = mdates.MonthLocator()  # every x month
ax.xaxis.set_major_locator(years_maj)
ax.xaxis.set_minor_locator(months_maj)
ax.set_xlim(pd.to_datetime('2014-10'), pd.to_datetime('2018-10'))
ax.set_ylabel('HGS input forcing [mm/d]')
ax.axhline(0, ls='--', c='k')

dfQ = pd.read_csv(hgs_path + '_HGS_v0_James/full_model/'+'1_q_weir_s2_obs_NAs_removed.smp', delim_whitespace=True, header=None)
dfQ['datetxt'] = dfQ[1]+ ' ' + dfQ[2].apply(str)
dfQ['datetime'] = [datetime.strptime(date, "%d/%m/%Y %H:%M:%S") for date in dfQ['datetxt']]
dfQ.index = dfQ['datetime']
dfQp = dfQ[3].resample('D').mean()
dfQp = dfQp/(13.7*1e6)*1000
ax.plot(dfQp, c='dodgerblue')

y_pe = (hgs_wb['rain_plus_all_melt'] / (37*1e6) * 1000).resample('Y').sum()
y_q = dfQp.resample('Y').sum()
print(y_pe,y_q)

plt.tight_layout()

sel_ppt = (select_period(hgs_wb['rain_plus_all_melt'],2017,2017).resample('Y').sum() / (37*1e6) * 1000).mean()
sel_aet = (select_period(hgs_wb['ET_4_AET'],2017,2017).resample('Y').sum() / (37*1e6) * 1000 * -1).mean()
sel_inp = sel_ppt-sel_aet
    
# print(sel_ppt, sel_aet, sel_inp)

hgs_wb['Q_S2'] = dfQp

#%% HGS - PLOT QOBS

init_path = hgs_path + '_HGS_v0_James/full_model/'

Qobs_list =[
             '1_q_vdn_u_s1_obs_NAs_removed.smp',
            # '1_q_vdn_u_s1_obs_NAs_removed_reduced.smp',
             '1_q_weir_s2_obs_NAs_removed.smp',
            # '1_q_weir_s2_obs_NAs_removed_reduced.smp',
             '1_q_ric_s3_obs_NAs_removed.smp'
            # '1_q_ric_s3_obs_NAs_removed_reduced.smp'
            ]

fig, axs = plt.subplots(2,1, figsize=(7,6), sharex=True)
axs = axs.ravel()

couleurs = ['dodgerblue','darkorange','forestgreen']
areas = [9.4, 13.7, 14.1]

for i, Qobs_name in enumerate(Qobs_list[:]):
    dfQ = pd.read_csv(init_path+Qobs_name, delim_whitespace=True, header=None)
    
    dfQ['datetxt'] = dfQ[1]+ ' ' + dfQ[2].apply(str)
    dfQ['datetime'] = [datetime.strptime(date, "%d/%m/%Y %H:%M:%S") for date in dfQ['datetxt']]
    dfQ.index = dfQ['datetime']
    dfQp = dfQ.resample('D').mean()
    
    zo = 1
    if i == 0:
        zo=2
    
    ax = axs[0]
    ax.plot(dfQp[3]/24/3600, lw=1,
            label='S'+str(i+1), color=couleurs[i], zorder=zo) # m3/day to m3/seconds
    ax.legend(loc='upper right', frameon=False)
    # ax.set_yscale('log')
    ax.set_ylim(0, 8)
    ax.xaxis.set(minor_locator=mdates.MonthLocator(), major_locator=mdates.YearLocator())
    # ax.set_xlim(pd.to_datetime('2016'), pd.to_datetime('2019'))
    ax.set_ylabel('$Q_{obs}$ [m$^3$/s]')
    # ax.grid()
        
    ax = axs[1]
    ax.plot(dfQp[3]/(areas[i]*1e6)*1000, lw=1,
            label='S'+str(i+1), color=couleurs[i], zorder=zo) # m3/day to mm/day
    ax.legend(loc='lower right', frameon=False)
    ax.set_yscale('log')
    ax.set_ylim(8e-2, 100)
    ax.xaxis.set(minor_locator=mdates.MonthLocator(), major_locator=mdates.YearLocator())
    ax.set_xlim(pd.to_datetime('2016'), pd.to_datetime('2019'))
    ax.set_ylabel('$Q_{obs}$ [mm/d]')
    ax.set_xlabel('Date')
    # ax.grid()
    
    plt.tight_layout()

fig, axs = plt.subplots(1,3, figsize=(9,3), sharey=True)
axs = axs.ravel()

couleurs = ['dodgerblue','darkorange','forestgreen']
areas = [9.4, 13.7, 14.1] # total 37 km2

for i, Qobs_name in enumerate(Qobs_list):
    
    dfQ = pd.read_csv(init_path+Qobs_name, delim_whitespace=True, header=None)
    dfQ['datetxt'] = dfQ[1]+ ' ' + dfQ[2].apply(str)
    dfQ['datetime'] = [datetime.strptime(date, "%d/%m/%Y %H:%M:%S") for date in dfQ['datetxt']]
    zo = 1
    if i == 0:
        zo=2
        
    ax = axs[i]
    
    data_index = dfQ[3]/(areas[i]*1e6)*1000
    data_index.index = dfQ['datetime']
    # data_index = select_period(data_index, 2017,2018)
    
    data_index = data_index[(data_index.index>='2016-09') & (data_index.index<='2017-06')]
            
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
            lw=2, color=couleurs[i], label='S'+str(i+1))
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
    ax.set_ylim(0,15)
    # ax.set_yscale('log')
    
    # ax.set_ylabel(var + ' [mm/d]',labelpad=+10, color=couleurs[i], fontsize=15)
    # ax.set_ylabel(var + ' [°C]',labelpad=+10, color=couleurs[i], fontsize=15)
    # ax.set_title(watershed_name + ' [' + str(first) + ' to ' + str(last) + ']')
    # ax.grid(color='grey', lw=0.5, zorder=0)
    
    # ax.legend(loc='upper left')
    plt.tight_layout()

#%% HGS - PLOT POBS

init_path = hgs_path + '_HGS_v0_James/full_model/'

Pobs_list = ['1_gwl_n1_obs_NAs_removed.smp',
             '1_gwl_n2_obs_NAs_removed.smp',
             '1_gwl_n3_obs_NAs_removed.smp',
             '1_gwl_n4_obs_NAs_removed.smp'
             ]

fig, axs = plt.subplots(3,1, figsize=(8,10), sharex=True)
# fig, ax = plt.subplots(1,1, figsize=(6,4), sharex=True)
axs = axs.ravel()

couleurs = ['navy','darkviolet','skyblue','dodgerblue']
areas = [9.4, 13.7, 14.1]

for i, Pobs_name in enumerate(Pobs_list[:]):
    dfP = pd.read_csv(init_path+Pobs_name, delim_whitespace=True, header=None)
    
    dfP['datetxt'] = dfP[1]+ ' ' + dfP[2].apply(str)
    dfP['datetime'] = [datetime.strptime(date, "%d/%m/%Y %H:%M:%S") for date in dfP['datetxt']]
    zo = 1
    if i == 1:
        zo=-1
    if i == 3:
        zo=-2
    
    ax = axs[0]
    ax.plot(dfP['datetime'], dfP[3], lw=1,
            label='N'+str(i+1), color=couleurs[i], zorder=zo) # m3/day to m3/seconds
    ax.legend(loc='lower left', frameon=False)
    # ax.set_yscale('log')
    # ax.set_ylim(0, 8)
    ax.xaxis.set(minor_locator=mdates.MonthLocator(), major_locator=mdates.YearLocator())
    # ax.set_xlim(pd.to_datetime('2016'), pd.to_datetime('2019'))
    ax.set_ylabel('$WT_{obs}$ [m.a.s.l]')
    # ax.grid()
    if i==0:
        ax.axhline(y=1502.5, c=couleurs[i], ls=':')
    if i==1:
        ax.axhline(y=1505.0, c=couleurs[i], ls=':')
    if i==2:
        ax.axhline(y=1472.5, c=couleurs[i], ls=':')
    if i==3:
        ax.axhline(y=1482.0, c=couleurs[i], ls=':')
    
    ax = axs[2]
    if i==0:
        y=1502.5
    if i==1:
        y=1505.0
    if i==2:
        y=1472.5
    if i==3:
        y=1482.0
    ax.plot(dfP['datetime'], y-dfP[3], lw=1,
            label='N'+str(i+1), color=couleurs[i], zorder=zo) # m3/day to m3/seconds
    ax.legend(loc='lower left', frameon=False)
    # ax.set_yscale('log')
    # ax.set_ylim(0, 8)
    ax.xaxis.set(minor_locator=mdates.MonthLocator(), major_locator=mdates.YearLocator())
    # ax.set_xlim(pd.to_datetime('2016'), pd.to_datetime('2019'))
    ax.set_ylabel('$WTdepth_{obs}$ [m.a.s.l]')
    # ax.grid()
    ax.set_ylim(0,7)
    if i ==3:
        ax.invert_yaxis()
    
    ax = axs[1]
    yn = (dfP[3]-dfP[3].min())/(dfP[3].max()-dfP[3].min())
    ax.plot(dfP['datetime'], yn, lw=1,
            label='N'+str(i+1), color=couleurs[i], zorder=zo) # m3/day to m3/seconds
    ax.legend(loc='lower left', frameon=False)
    # ax.set_yscale('log')
    # ax.set_ylim(0, 8)
    ax.xaxis.set(minor_locator=mdates.MonthLocator(), major_locator=mdates.YearLocator())
    # ax.set_xlim(pd.to_datetime('2016'), pd.to_datetime('2019'))
    ax.set_ylabel('$WT_{obs}$* [m.a.s.l]')

    # ax.grid()

    ax.xaxis.set(minor_locator=mdates.MonthLocator(), major_locator=mdates.YearLocator())
    ax.set_xlim(pd.to_datetime('2017'), pd.to_datetime('2019'))
    ax.set_xlabel('Date')

#%% STREAMFLOW - PLOT UPDATE

import pyreadr

Q_up_path = 'D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Vallon/_data/_updated_discharge/H_Q_minute_VDN-2015-2023.Rdata'
Q_up = pyreadr.read_r(Q_up_path) # also works for Rds
print(Q_up.keys()) # let's check what objects we got
dfqup = Q_up['data2']
dfqup.index = dfqup['time']
dfqup = dfqup['Q']
dfqup_res = dfqup.resample('D').agg(pd.Series.mean, skipna=False)
# dfqup_res = dfqup_res.interpolate()
dfqup_res = dfqup_res*24*3600/1000/(13.7*1e6)*1000
# dfqup_res[dfqup_res > 50] = np.nan
dfqup_res = dfqup_res.to_frame()

fig, ax = plt.subplots(figsize=(8,3))
ax.plot(hgs_wb['Q_S2'], lw=2, c='red', label='old')
ax.plot(dfqup_res['Q'], lw=1, c='dodgerblue', label='update') # s to d, L to m3, m3 to m, m to mm
# ax.set_yscale('log')
# ax.set_ylim(8e-2, 100)
ax.xaxis.set(minor_locator=mdates.MonthLocator(), major_locator=mdates.YearLocator())
# ax.set_xlim(pd.to_datetime('2016'), pd.to_datetime('2022'))
ax.set_ylabel('$Q_{obs}$ [mm/d]')
ax.set_xlabel('Date')
# ax.set_ylim(-1,100)
ax.legend()

#%% ----  K P HGS

#%% K CREATE LIST CLIPPED

# f = open("C:/Users/ronan/OneDrive/UNINE/8_Modeling/Vallon/_data/_hgs/Prop/k_tecplot.dat", "r")
# data = f.read()

path = hgs_path + "Properties/k_tecplot.dat"
datall = [i.strip().split() for i in open(path).readlines()]

start = datall.index(['#', 'x'])
dat = datall[start:]
super_list_X = []
print('X')
for i in range(len(dat)):
    # print(i)
    # print(start)
    # if i+1 > start:
    if dat[i+1] != ['#', 'y']:
        super_list_X.extend(dat[i+1][:])
        # print(i+1)
    else:
        # print(i+1)
        break
        
start = datall.index(['#', 'y'])
dat = datall[start:]
super_list_Y = []
print('Y')
for i in range(len(dat)):
    # print(i)
    # print(start)
    # if i+1 > start:
    if dat[i+1] != ['#', 'z']:
        super_list_Y.extend(dat[i+1][:])
        # print(i+1)
    else:
        # print(i+1)
        break

start = datall.index(['#', 'z'])
dat = datall[start:]
super_list_Z = []
print('Z')
for i in range(len(dat[start:])):
    # print(i)
    # print(start)
    # if i+1 > start:
    if dat[i+1] != ['#', 'zone(cell-centered)']:
        super_list_Z.extend(dat[i+1][:])
        # print(i+1)
    else:
        # print(i+1)
        break

start = datall.index(['#', 'zone(cell-centered)'])
dat = datall[start:]
super_list_ZONE = []
print('ZONE')
for i in range(len(dat)):
    # print(i)
    # print(start)
    # if i+1 > start:
    if dat[i+1] != ['#', 'kxx', '(cell-centered)']:
        super_list_ZONE.extend(dat[i+1][:])
        # print(i+1)
    else:
        # print(i+1)
        break
        
start = datall.index(['#', 'kxx', '(cell-centered)'])
dat = datall[start:]
super_list_KXX = []
print('KXX')
for i in range(len(dat)):
    # print(i)
    # print(start)
    # if i+1 > start:
    if dat[i+1] != ['#', 'kyy', '(cell-centered)']:
        super_list_KXX.extend(dat[i+1][:])
        # print(i+1)
    else:
        # print(i+1)
        break
        
start = datall.index(['#', 'kyy', '(cell-centered)'])
dat = datall[start:]
super_list_KYY = []
print('KYY')
for i in range(len(dat)):
    # print(i)
    # print(start)
    # if i+1 > start:
    if dat[i+1] != ['#', 'kzz', '(cell-centered)']:
        super_list_KYY.extend(dat[i+1][:])
        # print(i+1)
    else:
        # print(i+1)
        break

start = datall.index(['#', 'kzz', '(cell-centered)'])
dat = datall[start+1:]
super_list_KZZ = []
super_list_ELEM = []
print('KZZ + ELEM')
for i in range(len(dat)):
    # print(i)
    # print(start)
    # if i+1 > start:
    if dat[i][0].isdigit() != True:
        super_list_KZZ.extend(dat[i][:])
        # super_list_KZZ.append(dat[i][:])
    else:
        # super_list_ELEM.extend(dat[i][:])
        super_list_ELEM.append(dat[i][:3]+dat[i][4:-1])
        # super_list_ELEM.extend(dat[i][:3]+dat[i][4:-1])
# print(len(pd.Series(super_list_ELEM).unique()))

nodes = pd.DataFrame(columns=['X','Y','Z'])
nodes['X'] = super_list_X
nodes['Y'] = super_list_Y
nodes['Z'] = super_list_Z
nodes['ID'] = np.arange(1, len(nodes)+1, 1)

# if 'clipped' not in globals():
shp = nodes.copy()
geometry = gpd.points_from_xy(shp['X'], shp['Y'], shp['Z'])
gdf = gpd.GeoDataFrame(shp, geometry=gpd.points_from_xy(shp['X'], shp['Y']))
gdf.to_file(hgs_path + "Properties/points_mesh.shp")
nant = gpd.read_file(hgs_path + "_HGS_v0_James/full_model/Nant_shape.shp")
clipped = gdf.clip(nant)
clipped.to_file(hgs_path + "Properties/points_mesh_nant.shp")
clipped.plot()

nodes = clipped.copy()
nodes = nodes.reset_index()

super_list_ELEM_clip = []
elem_to_keep = []
elem_to_delete = []
for n, m in enumerate(super_list_ELEM):
    print(n)
    if all(s in nodes['ID'].values for s in np.array(m).astype(int)):
        super_list_ELEM_clip.append(m)
        elem_to_keep.append(n)
    else:
        elem_to_delete.append(n)
    
# super_list_ZONE_clip = [x for i, x in enumerate(super_list_ZONE) if i in elem_to_keep]
super_list_ZONE_clip = []
for i, x in enumerate(super_list_ZONE):
    print(i)
    if i in elem_to_keep:
        super_list_ZONE_clip.append(x)
        
# super_list_KXX_clip = [x for i, x in enumerate(super_list_KXX) if i in elem_to_keep]
super_list_KXX_clip = []
for i, x in enumerate(super_list_KXX):
    print(i)
    if i in elem_to_keep:
        super_list_KXX_clip.append(x)
        
# super_list_KYY_clip = [x for i, x in enumerate(super_list_KYY) if i in elem_to_keep]
super_list_KYY_clip = []
for i, x in enumerate(super_list_KYY):
    print(i)
    if i in elem_to_keep:
        super_list_KYY_clip.append(x)
        
# super_list_KZZ_clip = [x for i, x in enumerate(super_list_KZZ) if i in elem_to_keep]
super_list_KZZ_clip = []
for i, x in enumerate(super_list_KZZ):
    print(i)
    if i in elem_to_keep:
        super_list_KZZ_clip.append(x)
        
#%% K SAVE LIST CLIPPED

alls = pd.DataFrame(columns=['ID'])
alls['ID'] = super_list_ELEM_clip

alls.to_csv(hgs_path + "Properties/alls_k_nodes.csv", sep=';')

elem = pd.DataFrame(columns=['ZONE','KXX','KYY','KZZ',
                             'ID1','X1','Y1','Z1',
                             'ID2','X2','Y2','Z2',
                             'ID3','X3','Y3','Z3',
                             'ID4','X4','Y4','Z4',
                             'ID5','X5','Y5','Z5',
                             'ID6','X6','Y6','Z6',])

elem['ZONE'] = super_list_ZONE_clip
elem['KXX'] = super_list_KXX_clip
elem['KYY'] = super_list_KYY_clip
elem['KZZ'] = super_list_KZZ_clip

elem.to_csv(hgs_path + "Properties/elem_k_init.csv", sep=';')

#%% K VOLUME LIST CLIPPED

elem = pd.read_csv(hgs_path + "Properties/elem_k_init.csv", sep=';')
alls = pd.read_csv(hgs_path + "Properties/alls_k_nodes.csv", sep=';')
alls = alls['ID']

import time
import ast
start = time.process_time()

delo = []
manu = []

cp = 0
for i in range(len(elem)):
    print(i, len(elem))
    for j in np.arange(1,6+1,1):
        # print('     ', j)
        val_id = int(ast.literal_eval(alls[i])[j-1])
        if np.isnan(val_id):
            elem_id = np.nan
            elem.loc[i,'ID'+str(j)] = val_id
            elem.loc[i,'X'+str(j)] = np.nan
            elem.loc[i,'Y'+str(j)] = np.nan
            elem.loc[i,'Z'+str(j)] = np.nan
        else:
            elem.loc[i,'ID'+str(j)] = int(val_id)
            elem.loc[i,'X'+str(j)] = nodes[nodes['ID']==elem.loc[i,'ID'+str(j)]]['X'].values[0]
            elem.loc[i,'Y'+str(j)] = nodes[nodes['ID']==elem.loc[i,'ID'+str(j)]]['Y'].values[0]
            elem.loc[i,'Z'+str(j)] = nodes[nodes['ID']==elem.loc[i,'ID'+str(j)]]['Z'].values[0]
    cp += 6
    # i = 0
    xdo = [float(elem.loc[i,'X1']), float(elem.loc[i,'X2']), float(elem.loc[i,'X3'])]
    ydo = [float(elem.loc[i,'Y1']), float(elem.loc[i,'Y2']), float(elem.loc[i,'Y3'])]
    zdo = [float(elem.loc[i,'Z1']), float(elem.loc[i,'Z2']), float(elem.loc[i,'Z3'])]
    xup = [float(elem.loc[i,'X4']), float(elem.loc[i,'X5']), float(elem.loc[i,'X6'])]
    yup = [float(elem.loc[i,'Y4']), float(elem.loc[i,'Y5']), float(elem.loc[i,'Y6'])]
    zup = [float(elem.loc[i,'Z4']), float(elem.loc[i,'Z5']), float(elem.loc[i,'Z6'])]
    area_up = 0.5 * (xup[0] * (yup[1] - yup[2]) + xup[1] * (yup[2] - yup[0]) + xup[2] * (yup[0] - yup[1]))
    area_do = 0.5 * (xdo[0] * (ydo[1] - ydo[2]) + xdo[1] * (ydo[2] - ydo[0]) + xdo[2] * (ydo[0] - ydo[1]))
    z_diff = [zup[0]-zdo[0], zup[1]-zdo[1], zup[2]-zdo[2]]
    # print(z_diff, np.array(z_diff).mean())
       
    corners = np.array([
        [xdo[0],ydo[0],zdo[0]], [xdo[1],ydo[1],zdo[1]], [xdo[2],ydo[2],zdo[2]], # lower rectangle
        [xup[0],yup[0],zup[0]], [xup[1],yup[1],zup[1]], [xup[2],yup[2],zup[2]]  # upper rectangle
        ])
    
    from scipy.spatial import Delaunay
    
    try:
        tri = Delaunay(corners)
        tetrahedra = corners[tri.simplices]
        def volume_tetrahedron(tetrahedron):
            matrix = np.array([tetrahedron[0] - tetrahedron[3],
                               tetrahedron[1] - tetrahedron[3],
                                tetrahedron[2] - tetrahedron[3],
                               ])
            return abs(np.linalg.det(matrix))/6
        volumes = np.array([volume_tetrahedron(t) for t in tetrahedra])
        volume = np.nansum(volumes)
    except:
        volume = np.nan
        pass
    
    manu_min = np.nanmin(area_up*np.array(z_diff))
    manu_mean = np.nanmean(area_up*np.array(z_diff))
    manu_max = np.nanmax(area_up*np.array(z_diff))

    elem.loc[i,'AREA'] = area_up
    elem.loc[i,'ZDIFF1'] = z_diff[0]
    elem.loc[i,'ZDIFF2'] = z_diff[1]
    elem.loc[i,'ZDIFF3'] = z_diff[2]
    elem.loc[i,'VOL_DELAUNAY'] = volume
    elem.loc[i,'VOL_MANUMIN'] = manu_min
    elem.loc[i,'VOL_MANUMEAN'] = manu_mean
    elem.loc[i,'VOL_MANUMAX'] = manu_max
    
    # if i == 10:
    #     print(time.process_time() - start)
    # if i == 10:
    #     break

elem_k = elem.copy()
elem_k.to_csv(hgs_path + "Properties/elem_k_fill.csv", sep=';')

#%% P CREATE LIST CLIPPED

# f = open("C:/Users/ronan/OneDrive/UNINE/8_Modeling/Vallon/_data/_hgs/Prop/k_tecplot.dat", "r")
# data = f.read()

path = hgs_path + "Properties/por_tecplot.dat"
datall = [i.strip().split() for i in open(path).readlines()]

start = datall.index(['#', 'x'])
dat = datall[start:]
super_list_X = []
print('X')
for i in range(len(dat)):
    # print(i)
    # print(start)
    # if i+1 > start:
    if dat[i+1] != ['#', 'y']:
        super_list_X.extend(dat[i+1][:])
        # print(i+1)
    else:
        # print(i+1)
        break
        
start = datall.index(['#', 'y'])
dat = datall[start:]
super_list_Y = []
print('Y')
for i in range(len(dat)):
    # print(i)
    # print(start)
    # if i+1 > start:
    if dat[i+1] != ['#', 'z']:
        super_list_Y.extend(dat[i+1][:])
        # print(i+1)
    else:
        # print(i+1)
        break

start = datall.index(['#', 'z'])
dat = datall[start:]
super_list_Z = []
print('Z')
for i in range(len(dat[start:])):
    # print(i)
    # print(start)
    # if i+1 > start:
    if dat[i+1] != ['#', 'zone(cell-centered)']:
        super_list_Z.extend(dat[i+1][:])
        # print(i+1)
    else:
        # print(i+1)
        break

start = datall.index(['#', 'zone(cell-centered)'])
dat = datall[start:]
super_list_ZONE = []
print('ZONE')
for i in range(len(dat)):
    # print(i)
    # print(start)
    # if i+1 > start:
    if dat[i+1] != ['#', 'por(cell-centered)']:
        super_list_ZONE.extend(dat[i+1][:])
        # print(i+1)
    else:
        # print(i+1)
        break
        
start = datall.index(['#', 'por(cell-centered)'])
dat = datall[start+1:]
super_list_POR = []
super_list_ELEM = []
print('POR + ELEM')
for i in range(len(dat)):
    # print(i)
    # print(start)
    # if i+1 > start:
    if dat[i][0].isdigit() != True:
        super_list_POR.extend(dat[i][:])
        # super_list_KZZ.append(dat[i][:])
    else:
        # super_list_ELEM.extend(dat[i][:])
        super_list_ELEM.append(dat[i][:3]+dat[i][4:-1])
        # super_list_ELEM.extend(dat[i][:3]+dat[i][4:-1])
# print(len(pd.Series(super_list_ELEM).unique()))

nodes = pd.DataFrame(columns=['X','Y','Z'])
nodes['X'] = super_list_X
nodes['Y'] = super_list_Y
nodes['Z'] = super_list_Z
nodes['ID'] = np.arange(1, len(nodes)+1, 1)

# if 'clipped' not in globals():
shp = nodes.copy()
geometry = gpd.points_from_xy(shp['X'], shp['Y'], shp['Z'])
gdf = gpd.GeoDataFrame(shp, geometry=gpd.points_from_xy(shp['X'], shp['Y']))
gdf.to_file(hgs_path + "Properties/points_mesh.shp")
nant = gpd.read_file(hgs_path + "_HGS_v0_James/full_model/Nant_shape.shp")
clipped = gdf.clip(nant)
clipped.to_file(hgs_path + "Properties/points_mesh_nant.shp")
clipped.plot()

nodes = clipped.copy()
nodes = nodes.reset_index()

super_list_ELEM_clip = []
elem_to_keep = []
elem_to_delete = []
for n, m in enumerate(super_list_ELEM):
    print(n)
    if all(s in nodes['ID'].values for s in np.array(m).astype(int)):
        super_list_ELEM_clip.append(m)
        elem_to_keep.append(n)
    else:
        elem_to_delete.append(n)

# super_list_ZONE_clip = [x for i, x in enumerate(super_list_ZONE) if i in elem_to_keep]
super_list_ZONE_clip = []
for i, x in enumerate(super_list_ZONE):
    print(i)
    if i in elem_to_keep:
        super_list_ZONE_clip.append(x)
        
# super_list_KXX_clip = [x for i, x in enumerate(super_list_KXX) if i in elem_to_keep]
super_list_POR_clip = []
for i, x in enumerate(super_list_POR):
    print(i)
    if i in elem_to_keep:
        super_list_POR_clip.append(x)
   
#%% P SAVE LIST CLIPPED

alls = pd.DataFrame(columns=['ID'])
alls['ID'] = super_list_ELEM_clip

alls.to_csv(hgs_path + "Properties/alls_p_nodes.csv", sep=';')

elem = pd.DataFrame(columns=['ZONE','POR',
                             'ID1','X1','Y1','Z1',
                             'ID2','X2','Y2','Z2',
                             'ID3','X3','Y3','Z3',
                             'ID4','X4','Y4','Z4',
                             'ID5','X5','Y5','Z5',
                             'ID6','X6','Y6','Z6'])

elem['ZONE'] = super_list_ZONE_clip
elem['POR'] = super_list_POR_clip

elem.to_csv(hgs_path + "Properties/elem_p_init.csv", sep=';')

#%% P VOLUME LIST VOLUME

from scipy.spatial import Delaunay

elem = pd.read_csv(hgs_path + "Properties/elem_p_init.csv", sep=';')
alls = pd.read_csv(hgs_path + "Properties/alls_p_nodes.csv", sep=';')
alls = alls['ID']

import time
import ast
start = time.process_time()

delo = []
manu = []

cp = 0
for i in range(len(elem)):
    print(i, len(elem))
    for j in np.arange(1,6+1,1):
        # print('     ', j)
        val_id = int(ast.literal_eval(alls[i])[j-1])
        if np.isnan(val_id):
            elem_id = np.nan
            elem.loc[i,'ID'+str(j)] = val_id
            elem.loc[i,'X'+str(j)] = np.nan
            elem.loc[i,'Y'+str(j)] = np.nan
            elem.loc[i,'Z'+str(j)] = np.nan
        else:
            elem.loc[i,'ID'+str(j)] = int(val_id)
            elem.loc[i,'X'+str(j)] = nodes[nodes['ID']==elem.loc[i,'ID'+str(j)]]['X'].values[0]
            elem.loc[i,'Y'+str(j)] = nodes[nodes['ID']==elem.loc[i,'ID'+str(j)]]['Y'].values[0]
            elem.loc[i,'Z'+str(j)] = nodes[nodes['ID']==elem.loc[i,'ID'+str(j)]]['Z'].values[0]
    cp += 6
    # i = 0
    xdo = [float(elem.loc[i,'X1']), float(elem.loc[i,'X2']), float(elem.loc[i,'X3'])]
    ydo = [float(elem.loc[i,'Y1']), float(elem.loc[i,'Y2']), float(elem.loc[i,'Y3'])]
    zdo = [float(elem.loc[i,'Z1']), float(elem.loc[i,'Z2']), float(elem.loc[i,'Z3'])]
    xup = [float(elem.loc[i,'X4']), float(elem.loc[i,'X5']), float(elem.loc[i,'X6'])]
    yup = [float(elem.loc[i,'Y4']), float(elem.loc[i,'Y5']), float(elem.loc[i,'Y6'])]
    zup = [float(elem.loc[i,'Z4']), float(elem.loc[i,'Z5']), float(elem.loc[i,'Z6'])]
    area_up = 0.5 * (xup[0] * (yup[1] - yup[2]) + xup[1] * (yup[2] - yup[0]) + xup[2] * (yup[0] - yup[1]))
    area_do = 0.5 * (xdo[0] * (ydo[1] - ydo[2]) + xdo[1] * (ydo[2] - ydo[0]) + xdo[2] * (ydo[0] - ydo[1]))
    z_diff = [zup[0]-zdo[0], zup[1]-zdo[1], zup[2]-zdo[2]]
    # print(z_diff, np.array(z_diff).mean())
       
    corners = np.array([
        [xdo[0],ydo[0],zdo[0]], [xdo[1],ydo[1],zdo[1]], [xdo[2],ydo[2],zdo[2]], # lower rectangle
        [xup[0],yup[0],zup[0]], [xup[1],yup[1],zup[1]], [xup[2],yup[2],zup[2]]  # upper rectangle
        ])
    
    try:
        tri = Delaunay(corners)
        tetrahedra = corners[tri.simplices]
        def volume_tetrahedron(tetrahedron):
            matrix = np.array([tetrahedron[0] - tetrahedron[3],
                               tetrahedron[1] - tetrahedron[3],
                                tetrahedron[2] - tetrahedron[3],
                               ])
            return abs(np.linalg.det(matrix))/6
        volumes = np.array([volume_tetrahedron(t) for t in tetrahedra])
        volume = np.nansum(volumes)
    except:
        volume = np.nan
        pass
    
    manu_min = np.nanmin(area_up*np.array(z_diff))
    manu_mean = np.nanmean(area_up*np.array(z_diff))
    manu_max = np.nanmax(area_up*np.array(z_diff))

    elem.loc[i,'AREA'] = area_up
    elem.loc[i,'ZDIFF1'] = z_diff[0]
    elem.loc[i,'ZDIFF2'] = z_diff[1]
    elem.loc[i,'ZDIFF3'] = z_diff[2]
    elem.loc[i,'VOL_DELAUNAY'] = volume
    elem.loc[i,'VOL_MANUMIN'] = manu_min
    elem.loc[i,'VOL_MANUMEAN'] = manu_mean
    elem.loc[i,'VOL_MANUMAX'] = manu_max
    
    # if i == 10:
    #     print(time.process_time() - start)
    # if i ==10:
    #     break

elem_p = elem.copy()
elem_p.to_csv(hgs_path + "Properties/elem_p_fill.csv", sep=';')

#%% ---- MIX HGS

#%% ALL 1

elem_k = pd.read_csv(hgs_path + "Properties/elem_k_fill.csv", sep=';')
elem_p = pd.read_csv(hgs_path + "Properties/elem_p_fill.csv", sep=';')

elem_ss = pd.read_csv(hgs_path + "Properties/elem_p_fill.csv", sep=';')
elem_ss['Ss'] = np.nan
elem_ss.loc[elem_ss['ZONE'].isin(np.arange(1,18+1,1)),'Ss'] = 1.6e-4 
elem_ss.loc[elem_ss['ZONE'].isin(np.arange(19,25+1,1)),'Ss'] = 1.1e-5

geomean_kxx = np.sum(elem_k['KXX'] * elem_k['VOL_DELAUNAY']) / np.sum(elem_k['VOL_DELAUNAY'])
# geomean_kyy = np.sum(elem_k['KYY'] * elem_k['VOL_DELAUNAY']) / np.sum(elem_k['VOL_DELAUNAY'])
# geomean_kzz = np.sum(elem_k['KZZ'] * elem_k['VOL_DELAUNAY']) / np.sum(elem_k['VOL_DELAUNAY'])
geomean_poro = np.sum(elem_p['POR'] * elem_p['VOL_DELAUNAY']) / np.sum(elem_p['VOL_DELAUNAY'])
geomean_ss = np.sum(elem_ss['Ss'] * elem_ss['VOL_DELAUNAY']) / np.sum(elem_ss['VOL_DELAUNAY'])
print(geomean_kxx/24/3600)
print(geomean_poro*100)
print(geomean_ss)

df_k = pd.DataFrame()
for i, z in enumerate(elem_k['ZONE'].unique()):
    mask = elem_k[elem_k['ZONE']==z]
    # print(z, mask['KXX'].mean()/24/300, mask['VOL_DELAUNAY'].sum())
    df_k.loc[i,'ZONE'] = int(z)
    df_k.loc[i,'KXX_mean'] = mask['KXX'].mean()/24/300
    # df_k.loc[i,'VOL_DELAUNAY'] = mask['VOL_DELAUNAY']
    df_k.loc[i,'VOL_DELAUNAY_sum'] = mask['VOL_DELAUNAY'].sum()
    df_k.loc[i,'Z_mean'] = (mask['Z1'].mean()+mask['Z2'].mean()+mask['Z3'].mean()+mask['Z4'].mean()+mask['Z5'].mean()+mask['Z6'].mean())/6
    df_k.loc[i,'Z_max'] = np.array([mask['Z4'].max(),mask['Z5'].max(),mask['Z6'].max()]).max()
df_k['fac'] = df_k['VOL_DELAUNAY_sum'] / (df_k['VOL_DELAUNAY_sum'].sum())
df_k['KXX_mean_w'] = (df_k['KXX_mean'] * df_k['VOL_DELAUNAY_sum'])

df_p = pd.DataFrame()
for i, z in enumerate(elem_p['ZONE'].unique()):
    mask = elem_p[elem_p['ZONE']==z]
    # print(z, mask['KXX'].mean()/24/300, mask['VOL_DELAUNAY'].sum())
    df_p.loc[i,'ZONE'] = int(z)
    df_p.loc[i,'POR_mean'] = mask['POR'].mean()*100
    df_p.loc[i,'VOL_DELAUNAY_sum'] = mask['VOL_DELAUNAY'].sum()
    df_p.loc[i,'Z_mean'] = (mask['Z1'].mean()+mask['Z2'].mean()+mask['Z3'].mean()+mask['Z4'].mean()+mask['Z5'].mean()+mask['Z6'].mean())/6
    df_p.loc[i,'Z_max'] = np.array([mask['Z4'].max(),mask['Z5'].max(),mask['Z6'].max()]).max()
df_p['fac'] = df_p['VOL_DELAUNAY_sum'] / (df_p['VOL_DELAUNAY_sum'].sum())
df_p['POR_mean_w'] = (df_p['POR_mean'] * df_p['VOL_DELAUNAY_sum']) #/ (df_p['VOL_DELAUNAY_sum'].sum())

fig, axs = plt.subplots(1, 2, figsize=(8,3))
axs = axs.ravel()

ax = axs[0]
ax.set_yscale('log')
Kvals = (df_k['KXX_mean'])
Kgeo = np.sum(df_k['KXX_mean_w']) / df_k['VOL_DELAUNAY_sum'].sum()
ax.boxplot(elem_k['KXX']/24/3600, positions=[0])
ax.boxplot(Kvals, positions=[1])
ax.scatter(1, Kgeo, marker='s', c='r', s=50)
ax.scatter(1, geomean_kxx/24/3600, marker='s', c='limegreen', s=50)
ax.set_title('Hydraulic conductivity [m/s]')
print('or', '{:.2e}'.format(Kgeo))
print('    ', (((elem_k['KXX']/24/3600)*elem_k['VOL_DELAUNAY'])/np.sum(elem_k['VOL_DELAUNAY'])).median())

ax = axs[1]
ax.set_yscale('log')
Pvals = (df_p['POR_mean'])
Pgeo = np.sum(df_p['POR_mean_w']) / df_p['VOL_DELAUNAY_sum'].sum()
ax.boxplot(elem_p['POR']*100, positions=[0])
ax.boxplot(Pvals, positions=[1])
ax.scatter(1, Pgeo, marker='s', c='r', s=50)
ax.scatter(1, geomean_poro*100, marker='s', c='limegreen', s=50)
ax.set_title('Porosity [%]')
# ax.set_ylim()
print('or', round((Pgeo),2))

# df_k = elem_k.groupby('ZONE')['KXX'].unique()
# df_k = elem_k.groupby(['ZONE']).sum()#.groupby(level='ZONE').mean()

#%% ALL 2

from scipy.stats import hmean, gmean

elem_k = pd.read_csv(hgs_path + "Properties/elem_k_fill.csv", sep=';')
elem_p = pd.read_csv(hgs_path + "Properties/elem_p_fill.csv", sep=';')

elem_hp = elem_k.copy()
elem_hp['ZDIFF_MEAN'] = (elem_hp['ZDIFF1'] + elem_hp['ZDIFF2'] + elem_hp['ZDIFF3']) / 3
elem_hp['SYX'] = elem_p['POR']
elem_hp['SSX'] = np.nan
elem_hp.loc[elem_hp['ZONE'].isin(np.arange(1,18+1,1)),'SSX'] = 1.6e-4 
elem_hp.loc[elem_hp['ZONE'].isin(np.arange(19,25+1,1)),'SSX'] = 1.1e-5

tot_area = elem_hp['AREA'].sum() / 23
tot_vol = elem_hp['VOL_DELAUNAY'].sum()

# elem_hp['KXX_w'] = elem_hp['VOL_DELAUNAY'] / tot_vol
elem_hp['KXX_w'] = elem_hp['AREA'] / tot_area
elem_hp['fac'] = elem_hp['VOL_DELAUNAY'] / elem_hp['VOL_DELAUNAY'].sum()
elem_hp['KXX_ms'] = elem_hp['KXX']/24/3600

elem_hp['ID_E_v'] = list(np.arange(1,9608+2,1))*23
df_ev = pd.DataFrame()
for i, z in enumerate(elem_hp['ID_E_v'].unique()):
    mask = elem_hp[elem_hp['ID_E_v']==z]
    df_ev.loc[i,'ID_E_v'] = int(z)
    df_ev.loc[i,'AREA_val'] = mask['AREA'].iloc[0]
    df_ev.loc[i,'VOL_DELAUNAY_sum'] = mask['VOL_DELAUNAY'].sum()
    # df_ev.loc[i,'Kh_init'] = mask['KXX'].iloc[0]
    df_ev.loc[i,'Kh'] = np.sum(mask['KXX_w'] * mask['ZDIFF_MEAN']) / np.sum(mask['ZDIFF_MEAN'])
    df_ev.loc[i,'Kv'] = np.sum(mask['ZDIFF_MEAN']) / np.sum(mask['ZDIFF_MEAN'] / mask['KXX_w'])
    df_ev.loc[i,'Kh_geom'] = 10**(np.sum(np.log10(mask['KXX_ms']) * mask['ZDIFF_MEAN']) / np.sum(mask['ZDIFF_MEAN']))
    df_ev.loc[i,'Kv_harm'] = 10**(np.sum(mask['ZDIFF_MEAN']) / np.sum((mask['ZDIFF_MEAN']/np.log10(mask['KXX_ms']))))
df_ev['Kh/Kv'] = df_ev['Kh'] / df_ev['Kv']
df_ev['Kh_w'] = (df_ev['Kh'] * df_ev['AREA_val']) / (tot_area)
df_ev['Kv_w'] = (df_ev['Kv'] * df_ev['AREA_val']) / (tot_area)
df_ev['Kh_w/Kv_w'] = df_ev['Kh_w'] / df_ev['Kv_w']
df_ev['Kh_ms'] = df_ev['Kh'] / 3600/24
df_ev['Kh_geom_ms'] = df_ev['Kh_geom']
df_ev['Kv_harm_ms'] = df_ev['Kv_harm']

df_hp = pd.DataFrame()
for i, z in enumerate(elem_hp['ZONE'].unique()):
    mask = elem_hp[elem_hp['ZONE']==z]
    df_hp.loc[i,'ZONE'] = int(z)
    df_hp.loc[i,'KXX_val'] = mask['KXX'].iloc[0]
    df_hp.loc[i,'SYX_val'] = mask['SYX'].iloc[0]
    df_hp.loc[i,'SSX_val'] = mask['SSX'].iloc[0]
    df_hp.loc[i,'VOL_DELAUNAY_sum'] = mask['VOL_DELAUNAY'].sum()
    df_hp.loc[i,'Z_mean'] = (mask['Z1'].mean()+mask['Z2'].mean()+mask['Z3'].mean()+mask['Z4'].mean()+mask['Z5'].mean()+mask['Z6'].mean())/6
    df_hp.loc[i,'Z_max'] = np.array([mask['Z4'].max(),mask['Z5'].max(),mask['Z6'].max()]).max()
df_hp['fac'] = df_hp['VOL_DELAUNAY_sum'] / (df_hp['VOL_DELAUNAY_sum'].sum())
df_hp['KXX_val_ms'] = df_hp['KXX_val']/24/3600

kh_arit = np.average(df_hp['KXX_val'], weights=None)/24/3600
kh_geom = gmean(df_hp['KXX_val'], weights=None)/24/3600
kh_harm = hmean(df_hp['KXX_val'], weights=None)/24/3600
kh_arit_w = np.average(df_hp['KXX_val'], weights=df_hp['VOL_DELAUNAY_sum'])/24/3600
kh_geom_w = gmean(df_hp['KXX_val'], weights=df_hp['VOL_DELAUNAY_sum'])/24/3600
kh_harm_w = hmean(df_hp['KXX_val'], weights=df_hp['VOL_DELAUNAY_sum'])/24/3600

# print('{:.2e}'.format(kh_arit), # https://fr.wikipedia.org/wiki/Moyenne_pond%C3%A9r%C3%A9e
#       '{:.2e}'.format(kh_geom), # https://fr.wikipedia.org/wiki/Moyenne_g%C3%A9om%C3%A9trique_pond%C3%A9r%C3%A9e
#       '{:.2e}'.format(kh_harm),  # https://fr.wikipedia.org/wiki/Moyenne_harmonique_pond%C3%A9r%C3%A9e
#        kh_geom / kh_harm
#       )

print('{:.2e}'.format(kh_arit_w), # https://fr.wikipedia.org/wiki/Moyenne_pond%C3%A9r%C3%A9e
      '{:.2e}'.format(kh_geom_w), # https://fr.wikipedia.org/wiki/Moyenne_g%C3%A9om%C3%A9trique_pond%C3%A9r%C3%A9e
      '{:.2e}'.format(kh_harm_w),  # https://fr.wikipedia.org/wiki/Moyenne_harmonique_pond%C3%A9r%C3%A9e
      round(kh_arit_w / kh_harm_w, 2),
      round(kh_geom_w / kh_harm_w, 2)
      )

K_CP_min = np.average(hmean(df_ev['Kh']))
K_CP_max = hmean(np.average(df_ev['Kh']))
K_CP_geom = np.sqrt(K_CP_min*K_CP_max) # K_CP_geom = gmean([K_CP_min,K_CP_max])

print('{:.2e}'.format(K_CP_min), '{:.2e}'.format(K_CP_geom), '{:.2e}'.format(K_CP_max), round(K_CP_max/K_CP_min, 2))

fig, ax = plt.subplots(1, 1, figsize=(4,4))

ax.boxplot(elem_hp['KXX']/24/3600, positions=[1])
ax.boxplot(df_ev['Kh_geom_ms'], positions=[2])
ax.boxplot(df_ev['Kv_harm_ms'], positions=[2.5])

ax.scatter(1, kh_arit_w, marker='s', c='darkred', s=50, zorder=100)
ax.scatter(1, kh_geom_w, marker='s', c='darkorange', s=50, zorder=100)
ax.scatter(1, kh_harm_w, marker='s', c='gold', s=50, zorder=100)
ax.scatter(2, df_ev['Kh_geom_ms'].mean(), marker='s', c='dodgerblue', s=50, zorder=100)
ax.scatter(2.5, df_ev['Kv_harm_ms'].mean(), marker='s', c='navy', s=50, zorder=100)

# ax.scatter(1, K_CP_min, marker='o', c='limegreen', s=50, zorder=100)
# ax.scatter(1, K_CP_max, marker='o', c='limegreen', s=50, zorder=100)
# ax.scatter(1, K_CP_geom, marker='o', c='limegreen', s=50, zorder=100)

ax.set_yscale('log')
ax.set_title('Hydraulic conductivity [m/s]')

# Kh < Keff < Ka

fig, ax = plt.subplots(1, 1, figsize=(7,4))
df_sort = df_hp.sort_values(['SYX_val'])
ax.plot(df_sort['SYX_val']*100, df_sort['fac'])
ax.scatter(df_hp['SYX_val']*100, df_hp['fac'])
ax.set_xscale('log')
fig, ax = plt.subplots(1, 1, figsize=(7,4))
ax.hist(df_hp['SYX_val']*100,
        weights=df_hp['fac'],
        bins=np.logspace(np.log10(100*df_hp['SYX_val'].min()),np.log10(100*df_hp['SYX_val'].max()), 100),
        # density=True,
        histtype='step')
ax.set_xscale('log')
# fig, ax = plt.subplots(1, 1, figsize=(7,4))
# ax.hist(elem_hp['KXX_ms'],
#         weights=elem_hp['VOL_DELAUNAY'],
#         bins=np.logspace(np.log10(elem_hp['KXX_ms'].min()),np.log10(elem_hp['KXX_ms'].max()), 100),
#         # density=True,
#         histtype='step')
# ax.set_xscale('log')

# La deuxième expression ci-dessus montre que le logarithme de la moyenne géométrique pondérée 
# est la moyenne arithmétique pondérée du logarithme des valeurs du jeu de données. 

sy_arit_w = np.average(df_hp['SYX_val'], weights=df_hp['VOL_DELAUNAY_sum'])*100
sy_geom_w = gmean(df_hp['SYX_val'], weights=df_hp['VOL_DELAUNAY_sum'])*100
sy_harm_w = hmean(df_hp['SYX_val'], weights=df_hp['VOL_DELAUNAY_sum'])*100

fig, ax = plt.subplots(1, 1, figsize=(4,4))

ax.boxplot(elem_hp['SYX']*100, positions=[1])

ax.scatter(1, sy_arit_w, marker='s', c='darkred', s=50, zorder=100)
ax.scatter(1, sy_geom_w, marker='s', c='darkorange', s=50, zorder=100)
ax.scatter(1, sy_harm_w, marker='s', c='gold', s=50, zorder=100)

# ax.scatter(1, K_CP_min, marker='o', c='limegreen', s=50, zorder=100)
# ax.scatter(1, K_CP_max, marker='o', c='limegreen', s=50, zorder=100)
# ax.scatter(1, K_CP_geom, marker='o', c='limegreen', s=50, zorder=100)

ax.set_yscale('log')
ax.set_title('Specific yield [%]')

fig, ax = plt.subplots(1, 1, figsize=(7,4))
df_sort = df_hp.sort_values(['KXX_val'])
ax.plot(df_sort['KXX_val_ms'], df_sort['fac'])
ax.scatter(df_hp['KXX_val_ms'], df_hp['fac'])
ax.set_xscale('log')
fig, ax = plt.subplots(1, 1, figsize=(7,4))
ax.hist(df_hp['KXX_val_ms'],
        weights=df_hp['fac'],
        bins=np.logspace(np.log10(df_hp['KXX_val_ms'].min()),np.log10(df_hp['KXX_val_ms'].max()), 100),
        # density=True,
        histtype='step')
ax.set_xscale('log')
# fig, ax = plt.subplots(1, 1, figsize=(7,4))
# ax.hist(elem_hp['KXX_ms'],
#         weights=elem_hp['VOL_DELAUNAY'],
#         bins=np.logspace(np.log10(elem_hp['KXX_ms'].min()),np.log10(elem_hp['KXX_ms'].max()), 100),
#         # density=True,
#         histtype='step')
# ax.set_xscale('log')

#%% ---- CALIBRATION STREAMS

#%% DICHOTOMY FUNCTION

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

hydrography_path = data_path + '_gis/Hydrography_clipped/' # add hydrographic shapefiles

types_obs = ['perennial_natural_streams',
             'fully_natural_streams',
             'fully_natural_streams_springs',
             'fully_natural_streams_springs_wetlands']
fields_obs = ['fid','fid','fid','fid']

# compt = 0

for watershed_name in watershed_names[:]:
    
    # df = pd.DataFrame(np.nan, index=range(1), columns=types_obs)
    
    iD_iter = 't1'
    
    for type_obs, field_obs in zip(types_obs[:], fields_obs[:]):
   
        df = pd.DataFrame()
   
        print('##### '+watershed_name.upper()+' #####')
        
        BV = watershed_root.Watershed(watershed_name=watershed_name, dem_path=dem_path, out_path=out_path, load=True)
        area = BV.geographic.area

        stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
        simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' # necessary for plots
        BV.calibration_folder = os.path.join(out_path, watershed_name, 'results_calibration')
        toolbox.create_folder(BV.calibration_folder)
        
        BV.add_hydrography(hydrography_path, types_obs=[type_obs], fields_obs=[field_obs])
        
        box = False # or False
        sink_fill = False # or True
        sim_state = 'steady' # 'steady' or 'transient'
        plot_cross = False
        
        recharge = select_period(hgs_wb['PPT-AET_m/d_sim1'],2017,2017)
        runoff = select_period(hgs_wb['PPT-AET_m/d_sim1'],2017,2017)
        # recharge = np.nanmean(select_period(dfd['REC_REA_historic'],2014,2019))/1000
        
        first_clim = 'mean' # or 'first or value
        nlay = 1
        lay_decay = 1 # 1 for no decay
        bottom = None # elevation in meters, None for constant auifer thickness, or 2D matrix
        thick = 30 # if bottom is None, aquifer thickness
        cond_decay = 0 # exponential decay : 1/20 (half decrease at 20m)
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
        BV.hydraulic.update_bottom(bottom) # None
        BV.hydraulic.update_thick(thick) # 30 / intervient pas si bottom != None
        BV.hydraulic.update_porosity(porosity)
        BV.hydraulic.update_cond_vertical(verti_cond)
        BV.hydraulic.update_cond_drain(cond_drain)
        BV.hydraulic.update_lay_decay(poro_decay)
        BV.settings.update_bc_sides(bc_left, bc_right)
        BV.add_oceanic(sea_level)
        BV.settings.update_input_particules(zone_partic=zone_partic)
        
        params_df = pd.DataFrame(columns=['params','init_values','lower_bounds','higher_bounds','units','scale'])
        # params_df.loc[0] = ['k1','?',8.64e-04,8.64e-01,'m/j','lin']
        params_df.loc[0] = ['k1','?',1e-8*3600*24,1e-4*3600*24,'m/j','lin'] ### K/R 0.36 to 36 000
        params_file = 'calib_dicot_hom_1v_k1'
        params_df.to_csv(BV.calibration_folder+'/'+params_file+'.csv', sep=';', index=None)
        p_min = params_df['lower_bounds'].values[0]
        p_max = params_df['higher_bounds'].values[0]
        diff = p_max - p_min
        half = (p_min + p_max) / 2
        
        gap = 1
        
        compt = 0
        
        while (diff > ((gap/100) * half)):
            
            half = (p_min + p_max) / 2
            hyd_cond = half.copy() # if K in calib_params.csv
            kr = hyd_cond / BV.climatic.recharge
                        
            BV.hydraulic.update_hyd_cond(hyd_cond)
            
            now = datetime.now()
            oclock = now.strftime("%Y%m%d_%Hh%Mm%Ss") 
            
            model_name = iD_iter+'-'+str(compt)+'-'+type_obs+'-'+str(round(hyd_cond,4)) #+'-'+oclock
            BV.settings.update_model_name(model_name)
            print(model_name)
            
            model_modflow = BV.preprocessing_modflow(for_calib=True) # BV.calibration_folder
            success_modflow = BV.processing_modflow(model_modflow, write_model=True, run_model=True)
            
            # if success_modflow == True:
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
            
            obs = mean_obs_to_sim
            sim = mean_sim_to_obs
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
            
            df.loc[compt,'watershed_name'] = watershed_name
            df.loc[compt,'model_name'] = model_name
            df.loc[compt,'type_obs'] = type_obs
            df.loc[compt,'oclock'] = oclock
            
            df.loc[compt,'KR'] = round(kr, 4)
            df.loc[compt,'K'] = round(hyd_cond, 4)
            df.loc[compt,'R'] = round(recharge, 4)
            
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
        
        df.to_csv(BV.calibration_folder+'/'+watershed_name+'_'+iD_iter+'_'+type_obs+'.csv', sep=';')

#%% DICHOTOMY - APPEND

watershed_names = ['Vallons_EUDTM30m',
                   'Vare_EUDTM30m',
                   'Nant_EUDTM30m']
types_obs = ['perennial_natural_streams',
             'fully_natural_streams',
             'fully_natural_streams_springs',
             'fully_natural_streams_springs_wetlands']
fields_obs = ['fid','fid','fid','fid']

dfs = pd.DataFrame()

for watershed_name in watershed_names[:]:
    
    BV = watershed_root.Watershed(watershed_name=watershed_name, dem_path=dem_path, out_path=out_path, load=True)
    BV.calibration_folder = os.path.join(out_path, watershed_name, 'results_calibration')
    
    iD_iter = 't1'
    
    for type_obs, field_obs in zip(types_obs[:], fields_obs[:]):
        
        df = pd.read_csv(BV.calibration_folder+'/'+watershed_name+'_'+iD_iter+'_'+type_obs+'.csv', sep=';')
        
        dfs = pd.concat([dfs, df],ignore_index = True)

dfs = dfs.dropna(axis=1, how='all')
dfs.to_csv(out_path+'/'+'_calib_'+iD_iter+'_'+'all'+'.csv', sep=';')

#%% DICHOTOMY - PLOT

dfs = pd.read_csv(out_path+'/'+'_calib_'+iD_iter+'_'+'all'+'.csv', sep=';')

fig, ax = plt.subplots(1,1, figsize=(5,3.5))

watershed_names = ['Vallons_EUDTM30m',
                   'Vare_EUDTM30m',
                   'Nant_EUDTM30m']
types_obs = ['perennial_natural_streams',
             'fully_natural_streams',
             'fully_natural_streams_springs',
             'fully_natural_streams_springs_wetlands']
fields_obs = ['fid','fid','fid','fid']

couleurs = {'Vallons_EUDTM30m':'grey',
            'Vare_EUDTM30m':'forestgreen',
            'Nant_EUDTM30m':'darkorange'}
# couleurs = {'Vallons_EUDTM30m':'grey',
#             'Vare_EUDTM30m':'darkcyan',
#             'Nant_EUDTM30m':'chocolate'}
styles = {'perennial_natural_streams':'v',
          'fully_natural_streams':'^',
          'fully_natural_streams_springs':'o',
          'fully_natural_streams_springs_wetlands':'s'}

for watershed_name in watershed_names[:]:
    
    d1 = dfs[dfs['watershed_name']==watershed_name]
   
    couleur = couleurs[watershed_name]
    
    xs = []
    ys = []
    
    for type_obs, field_obs in zip(types_obs[:], fields_obs[:]):
        
        style = styles[type_obs]
        
        d2 = d1[d1['type_obs']==type_obs]
        
        d3 = d2.iloc[-1:]
        
        x = d3['K']/3600/24
        y = (d3['Obs']+d3['Sim'])/2
        ax.scatter(x, y,
                   color=couleur, marker=style, s=100, lw=1, ec='k')
        
        ax.axhline(y=30, ls='--', c='k', lw=1)
        
        ax.set_xlabel('K [m/s]')
        ax.set_xscale('log')
        ax.set_xlim(1e-6,1.2e-4)
        
        ax.set_ylabel('($D_{obs}$ + $D_{sim}$) / 2 [m]')
        # ax.set_yscale('log')
        ax.set_ylim(0,800)
        ax.set_yticks([0,200,400,600,800])
        # ax.set_yticks([0,30,60,120,240,480,960])
        
        xs.append(x.values)
        ys.append(y.values)
    
    ax.fill_between(np.arange(min(xs), max(xs), 1e-8), min(ys), max(ys), zorder=-1, alpha=0.5,
                    color=couleur)
    # ax.axvline(x=min(xs), color=couleur, zorder=-2)
    # ax.axvline(x=max(xs), color=couleur, zorder=-2)

#%% ---- MODELING POROSITY RUN PLOT

#%% PREPROCESSING

iD_iter = 't1'

# dfs = pd.read_csv(out_path+'/'+'_calib_'+iD_iter+'_'+'all'+'.csv', sep=';')

watershed_names = ['Nant_EUDTM30m']
types_obs = ['perennial_natural_streams',
             # 'fully_natural_streams',
             # 'fully_natural_streams_springs',
             # 'fully_natural_streams_springs_wetlands'
             ]

# recharge = select_period(dfd['REC_REA_historic'],2016,2018)/1000
# runoff = select_period(dfd['RUN_REA_historic'],2016,2018)/1000

recharge = select_period(hgs_wb['PPT-AET_m/d_sim1'],2017,2017)
runoff = select_period(hgs_wb['PPT-AET_m/d_sim1'],2017,2017)

# recharge = select_period(hgs_wb['PPT-AET_m/d_sim1'],2016,2018).resample('M').mean()
# runoff = select_period(hgs_wb['PPT-AET_m/d_sim1'],2016,2018).resample('M').mean()

# dic_K = {}
# for watershed_name in watershed_names[:]:
#     d1 = dfs[dfs['watershed_name']==watershed_name]
#     for type_obs in types_obs[:]:
#         d2 = d1[d1['type_obs']==type_obs]
#         d3 = d2.iloc[-1:]
#         val_K = d3.K.values[0]
#         val_KR = d3.KR.values[0]
#         # dic_K[watershed_name] = val_K
#         dic_K[watershed_name] = val_KR * recharge.mean()
#         print(val_KR, val_KR * recharge.mean() / 3600 / 24)
        
box = True # or False
sink_fill = False # or True
sim_state = 'transient' # 'steady' or 'transient'
plot_cross = False
first_clim = 'mean' # or 'first or value
nlay = 1
lay_decay = 1 # 1 for no decay
bottom = None # elevation in meters, None for constant auifer thickness, or 2D matrix
thick = 400 # if bottom is None, aquifer thickness
cond_decay = 0 # exponential decay : 1/20 (half decrease at 20m)
verti_cond = None # or [ [1e-5, [0, 20]],
cond_drain = None # or value of conductance
poro_decay = 0 # exponential decay : 1/20 (half decrease at 20m)
bc_left = None # or value
bc_right = None # or value
sea_level = 'None' # or value based on specific data : BV.oceanic.MSL
zone_partic = 'domain' # or watershed

# list_porosity = np.array([0.1, 0.5, 1, 2, 5, 10, 30]) / 100
list_porosity = np.array([0.1]) / 100
hyd_cond = 1.8e-6 * 3600 * 24

# iD_set_simulations = 'explorSy_test1'
iD_set_simulations = 't1'

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
    print(hyd_cond/BV.climatic.recharge)
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
    
    # hyd_cond = dic_K[watershed_name]
    BV.hydraulic.update_hyd_cond(hyd_cond)
    
    compt = 0
    
    for i, porosity in enumerate(list_porosity[:]):
        
        BV.hydraulic.update_porosity(porosity)
        
        Ss_formula = 1000*9.8*(1e-10+(porosity*4.4e-10)) # rho*g*(alpha+nBeta)
        # print(Ss_formula)

        BV.hydraulic.update_ss(Ss_formula)
        
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
    
    # if watershed_name == 'Vare_EUDTM30m':
        
    #     list_model_name = d['list_model_name'][7:]
    #     list_success_modflow = d['list_success_modflow'][7:]
    #     list_model_modflow = d['list_model_modflow'][7:]

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
                                      intermittency_weekly=False,
                                      intermittency_daily=True,
                                      export_all_tif = False)
    
            timeseries_results = BV.postprocessing_timeseries(model_modflow=model_modflow,
                                                              model_modpath=None,
                                                              actual_date=True, 
                                                              subbasin_results=True,
                                                              freq_time='D')

#%% SEEPAGE

iD_set_simulations = 't1'


for watershed_name in ['Nant_EUDTM30m'][:]:
    
    BV = watershed_root.Watershed(watershed_name=watershed_name, dem_path=dem_path, out_path=out_path, load=True)
    area = BV.geographic.area
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' # necessary for plots

    h5file = simulations_folder+'/'+'results_listing_'+iD_set_simulations
    d = dd.io.load(h5file)
    list_model_name = d['list_model_name'][:]
    list_success_modflow = d['list_success_modflow'][:]
    list_model_modflow = d['list_model_modflow'][:]
    
    simul_list = []
    for si in list_model_name:
        simul_list.append(os.path.join(simulations_folder,si))

    for i, simul in enumerate(simul_list[-1:]):
        

        model_name = simul.split('/')[-1]
        print(i, model_name)
        
        Smod_path = simul+'/_postprocess/_rasters/seepage_areas_t(0).tif'
        im = imageio.imread(Smod_path)

        plt.imshow(np.ma.masked_where(im==0,im))

#%% STREAMFLOW

iD_set_simulations = 'explorSy_test1'
iD_set_simulations = 'explorSy_pptaet1'
iD_set_simulations = 't1'

def select_period(df, first, last):
    df = df[(df.index.year>=first) & (df.index.year<=last)]
    return df
    
for watershed_name in ['Nant_EUDTM30m'][:]:
    
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
        # print('NSE', round(NSE,2))
        # print('NSElog', round(NSElog,2))
        # print('RMSE', round(RMSE,2))
        # print('KGE', round(KGE,2))
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
                    
        # fig.savefig(os.path.join(simulations_folder, '_figures',
        #             'STREAMFLOW_'+model_name+'.png'),
        #             bbox_inches='tight')

#%% SATURATION

types_obs = ['perennial_natural_streams',
             'fully_natural_streams',
             'fully_natural_streams_springs',
             'fully_natural_streams_springs_wetlands']

iD_set_simulations = 'explorSy_test1'
iD_set_simulations = 'explorSy_pptaet1'
iD_set_simulations = 't1'

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
            ax.set_ylim(0,None)
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
                    
        # fig.savefig(os.path.join(simulations_folder, '_figures',
        #             'SATURATION_'+model_name+'.png'),
        #             bbox_inches='tight')
          
#%% ---- EXPLORATION KP RUN PLOT

#%% PREPROCESSING

watershed_names = ['Nant_EUDTM30m']
        
box = False # or False
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

recharge = select_period(hgs_wb['PPT-AET_m/d_sim1'],2016,2018)
runoff = select_period(hgs_wb['PPT-AET_m/d_sim1'],2016,2018)

# recharge = recharge.iloc[:7]
# runoff = runoff.iloc[:7]

# list_hyd_cond = np.array([1e-6]) * 3600 * 24
# list_porosity = np.array([1.0]) / 100

# iD_set_simulations = 'explorSy_test1'
# iD_set_simulations = 'explorSy_pptaet1'
# iD_set_simulations = 'TEST2'
iD_set_simulations = 'EXPLO1'

#%% PRO AND POSTPROCESSING

for watershed_name in watershed_names[:]:
    
    BV = watershed_root.Watershed(watershed_name=watershed_name, dem_path=dem_path, out_path=out_path, load=True)
    area = BV.geographic.area
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' # necessary for plots
    calibration_folder = out_path+'/'+watershed_name+'/'+'results_calibration/'
    
    BV.add_settings()
    BV.add_climatic()
    BV.add_geometric() # soon
    BV.add_hydraulic()
    BV.settings.update_box_model(box)
    BV.settings.update_sink_fill(sink_fill)
    BV.settings.update_active_plot(plot_cross=plot_cross)
    BV.settings.update_bc_sides(bc_left, bc_right)
    BV.settings.update_input_particules(zone_partic=zone_partic)
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
    BV.add_oceanic(sea_level)
    
    BV.settings.update_simulation_state(sim_state)
    
    if watershed_name == 'Nant_EUDTM30m':
        list_hyd_cond = np.geomspace(1e-4,1e-7,10) * 3600 * 24
        list_porosity = np.geomspace(0.1,10,10) / 100
    if watershed_name == 'Vare_EUDTM30m':
        list_hyd_cond = np.geomspace(1e-4,1e-7,10) * 3600 * 24
        list_porosity = np.geomspace(0.1,10,10) / 100
    
    # list_hyd_cond = np.geomspace(1e-4,1e-7,10) * 3600 * 24
    # list_porosity = np.geomspace(0.1,10,10) / 100
    
    compt = 0
    
    for k, hyd_cond in enumerate(list_hyd_cond[:]):
        BV.hydraulic.update_hyd_cond(hyd_cond)
       
        for p, porosity in enumerate(list_porosity[:]):
            BV.hydraulic.update_porosity(porosity)
            
            list_model_name = []
            list_success_modflow = []
            list_model_modflow = []
            
            now = datetime.now()
            oclock = now.strftime("%Y%m%d-%Hh%Mm%Ss")
                
            model_name = iD_set_simulations+'_'+str(compt)+'_'+str(k)+'-'+str(p)+'_'+str(round(hyd_cond,4))+'-'+str(round(porosity,4))+'-'+str(round(thick,4))#+'_'+oclock
            BV.settings.update_model_name(model_name)
            print(model_name)
            
            model_modflow = BV.preprocessing_modflow(for_calib=True)
            
            try:
            
                success_modflow = BV.processing_modflow(model_modflow, write_model=True, run_model=True)
                
                list_model_name.append(model_name)
                list_success_modflow.append(success_modflow)
                list_model_modflow.append(model_modflow)
                    
                dictio = {}
                dictio['list_model_name'] = list_model_name
                dictio['list_success_modflow'] = list_success_modflow
                dictio['list_model_modflow'] = list_model_modflow
                h5file = calibration_folder+'/'+'results_listing_'+model_name
                dd.io.save(h5file, dictio)
                
                compt += 1
                
                if success_modflow == True:
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
                                                                  model_modpath=True,
                                                                  actual_date=True, 
                                                                  subbasin_results=True,
                                                                  freq_time='D')
                
                #### DELETE POSTPROCESSING FILES ####
                            
                dir_modflow = calibration_folder + '/' + model_name
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
                
            except:
                pass

#%% DELETE MODFLOW FILES

for watershed_name in watershed_names[:]:

    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' # necessary for plots
    calibration_folder = out_path+'/'+watershed_name+'/'+'results_calibration/'

    h5files = glob.glob(calibration_folder+'/'+'results_listing_'+iD_set_simulations+'*')
    
    for h5 in h5files[:]:
    
        d = dd.io.load(h5)
        
        list_model_name = d['list_model_name'][:]
        list_success_modflow = d['list_success_modflow'][:]
        list_model_modflow = d['list_model_modflow'][:]
        
        for model_name, success_modflow, model_modflow in zip(list_model_name[:],
                                                              list_success_modflow[:],
                                                              list_model_modflow[:]):

            dir_modflow = calibration_folder + '/' + model_name
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

#%% STREAMFLOW - OBS

CRIT = 'RMSE'

init_path = 'C:/Users/ronan/Downloads/_init/Additional Clement/Observed_time_series/Daily/Q/'

Qobs_list =[
            '1_q_vdn_u_s1_obs_NAs_removed.smp',
            # '1_q_vdn_u_s1_obs_NAs_removed_reduced.smp',
            '1_q_weir_s2_obs_NAs_removed.smp',
            # '1_q_weir_s2_obs_NAs_removed_reduced.smp',
            '1_q_ric_s3_obs_NAs_removed.smp'
            # '1_q_ric_s3_obs_NAs_removed_reduced.smp'
            ]

areas = [
          9.4,
          13.7,
          14.1
         ]

df = pd.DataFrame()

dict_Q_wname = {}

for w, w_name in enumerate(['S1','Nant_EUDTM30m','Vare_EUDTM30m'][:]):
    
    if w_name == 'S1':
        watershed_name = 'Nant_EUDTM30m'
    else:
        watershed_name = w_name
    
    BV = watershed_root.Watershed(watershed_name=watershed_name, dem_path=dem_path, out_path=out_path, load=True)

    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' # necessary for plots
    calibration_folder = out_path+'/'+watershed_name+'/'+'results_calibration/'
    
    dfQ = pd.read_csv(init_path+Qobs_list[w], delim_whitespace=True, header=None)
    dfQ['datetxt'] = dfQ[1]+ ' ' + dfQ[2].apply(str)
    dfQ['datetime'] = [datetime.strptime(date, "%d/%m/%Y %H:%M:%S") for date in dfQ['datetxt']]
    data_index = dfQ[3]/(areas[w]*1e6)
    data_index.index = dfQ['datetime']
    data_index.index= data_index.index.map(lambda t: t.replace(hour=0, minute=0, second=0, microsecond=0))
    Qobs = data_index.copy()

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
        
        Qmod = Smod['outflow_drain'] # m/day
        r = BV.climatic.runoff
        
        mix = Qobs.copy().to_frame()
        mix.columns = ['Qobs']
        mix['Qsim'] = Qmod
        mix = mix.dropna()
        # if w_name == 'Vare_EUDTM30m':
        #     mix = mix[mix.index<='2017-06']
        
        Qobs_stat = mix.Qobs
        Qsim_stat = mix.Qsim
        
        import hydroeval as he
        NSE = he.evaluator(he.nse, Qsim_stat, Qobs_stat)[0]
        NSElog = he.evaluator(he.nse, Qsim_stat, Qobs_stat, transform='log')[0]
        RMSE = np.sqrt(np.nanmean((Qobs_stat.values-Qsim_stat.values)**2)) / (Qobs_stat.max()-Qobs_stat.min())
        KGE = he.evaluator(he.kge, Qsim_stat, Qobs_stat)[0][0]
        # print(model_name.upper())
        # print('NSE', round(NSE,2))
        # print('NSElog', round(NSElog,2))
        # print('RMSE', round(RMSE,2))
        # print('KGE', round(KGE,2))
        
        df.loc[i,'model_name'] = model_name
        
        df.loc[i,'K'] = float(model_name.split('_')[3].split('-')[0])
        df.loc[i,'Sy'] = float(model_name.split('_')[3].split('-')[1])
        df.loc[i,'p1-p2'] = model_name.split('_')[3].split('-')[0]+'-'+model_name.split('_')[3].split('-')[1]
        
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

    p1 = df.K.unique()
    p2 = df.Sy.unique()
    ded = np.zeros((len(p1),len(p2)))
    for i, iv in enumerate(p1):
        for j, jv in enumerate(p2):
            string = str(iv)+'-'+str(jv)
            # print(string)
            ded[j][i] = df[df['p1-p2']==string][CRIT]
        
    fig, ax = plt.subplots(1,1, figsize=(3.8,3.5))
    ax.set_aspect('auto')
    ax.axes.tick_params(which='both', direction='out', zorder=10)
    X,Y = np.meshgrid(df.K.unique(), df.Sy.unique())
    Z = ded.copy()
    
    dict_Q_wname[w] = Z
    
    # Z = 1-Z
    # Z = abs(Z)
    # print(np.nanmin(Z), np.nanmax(Z[Z != np.inf]))
    from numpy import inf
    # Z[Z<0] = 0
    # Z[Z == np.inf] = np.nanmax(Z)
    # Z[np.isneginf(Z)] = np.nanmax(Z)
    # Z[~np.isfinite(Z)] = np.nanmax(Z[Z != np.inf])
    # bounds = np.arange(0,1.1,0.1)
    # norm = mpl.colors.Normalize(vmin=0, vmax=1.0)
    # cmap = 'jet'
    cmap = 'RdYlGn'
    if CRIT == 'OWN':
        cmap = 'RdYlGn_r'
    if CRIT == 'RMSE':
        cmap = 'RdYlGn_r'
    
    # pc = ax.pcolormesh(X/3600/24,Y*100,Z, cmap='RdYlGn', shading='gouraud',
                        # vmin=0, vmax=1
    #                    ) #figadd.cmap_white_jet()
    if w_name == 'Vare_EUDTM30m':
        pc = ax.contourf(X/3600/24, Y*100, Z,
                            # levels=np.arange(0,1.05,0.05), 
                            # levels=np.arange(0,10.05,1), 
                            # vmin=0, vmax=1,
                          alpha=0.5, ec='none', cmap=cmap, 
                            extend='max'
                            # norm = matplotlib.colors.LogNorm()
                          )
    else:
        pc = ax.contourf(X/3600/24, Y*100, Z,
                            # levels=np.arange(0,1.05,0.05), 
                            # levels=np.arange(0,1.05,0.05), 
                            # vmin=0, vmax=1,
                          alpha=0.5, ec='none', cmap=cmap, 
                            extend='max'
                            # norm = matplotlib.colors.LogNorm()
                          )
    position=fig.add_axes([1.05,0.33,0.03,0.5])  ##
    cb = fig.colorbar(pc, cax=position, orientation='vertical')
    # if w_name == 'Vare_EUDTM30m':
    #     cb.set_ticks(np.arange(0,10.05,2))
    # else:
    #     cb.set_ticks(np.arange(0,1.05,0.2))
    # cb.set_label('$NSE_{log}$ [-]', rotation=270, labelpad=40)
    cb.set_label(CRIT, rotation=270, labelpad=40)
    cb.ax.tick_params(top=True,
                bottom=True,
                left=False,
                right=False,
                labelleft=False,
                labelbottom=True)
    
    from matplotlib.ticker import FormatStrFormatter
    cb.ax.yaxis.set_major_formatter(FormatStrFormatter('%.2f'))
    
    ax.set_xscale('log')
    ax.set_yscale('log')
    ax.set_ylabel('θ [%]')
    ax.set_xlabel('K [m/s]')
    ax.tick_params(top=True,
               bottom=True,
               left=True,
               right=False,
               labelleft=True,
               labelbottom=True)
    
    ax.set_title(w_name.split('_')[0], fontsize=8)
    
    plt.tight_layout()
    
    fig.savefig(fig_path+'OBSmatrix2d'+'_'+w_name+'_'+CRIT+'.png', dpi=300, bbox_inches='tight')

# STREAMFLOW - PARETO FRONT

    fig, axs = plt.subplots(1,2, figsize=(7.5,3.5))
    axs = axs.ravel()
    ax = axs[0]
    norm_x = abs(1-df.NSElog) / (abs(1-df.NSElog).max() - abs(1-df.NSElog).min())
    norm_y = abs(df.RMSE) / (abs(df.RMSE).max() - abs(df.RMSE).min())
    df['NSElog-RMSE'] = (abs(1-df.NSElog) / (abs(1-df.NSElog).max() - abs(1-df.NSElog).min())) + (abs(df.RMSE) / (abs(df.RMSE).max() - abs(df.RMSE).min()))
    ax.scatter(norm_x, norm_y, lw=0, c=norm_x+norm_y, cmap='RdYlGn_r')
    ax.set_xlabel('NSElog')
    ax.set_ylabel('RMSE')
    ax = axs[1]
    norm_x = abs(1-df.NSE) / (abs(1-df.NSE).max() - abs(1-df.NSE).min())
    norm_y = abs(1-df.KGE) / (abs(1-df.KGE).max() - abs(1-df.KGE).min())
    df['NSE-KGE'] = (abs(1-df.NSE) / (abs(1-df.NSE).max() - abs(1-df.NSE).min())) + (abs(1-df.KGE) / (abs(1-df.KGE).max() - abs(1-df.KGE).min()))
    ax.scatter(norm_x, norm_y, lw=0, c=norm_x+norm_y, cmap='RdYlGn_r')
    ax.set_xlabel('NSE')
    ax.set_ylabel('KGE')
    # ax.set_xlim(0,5)
    # ax.set_ylim(0,5)
    fig.suptitle(w_name.split('_')[0], fontsize=8)
    plt.tight_layout()
    
    fig.savefig(fig_path+'OBSmatrix2d'+'_'+w_name+'_'+'PARETO'+'.png', dpi=300, bbox_inches='tight')
    
# STREAMFLOW - BEST MODELS
    
    df1 = df[df['NSElog-RMSE']==df['NSElog-RMSE'].min()]
    model_name1 = df1.model_name.values[0]
    df2 = df[df['NSE-KGE']==df['NSE-KGE'].min()]
    model_name2 = df2.model_name.values[0]
    # if w_name == 'Vare_EUDTM30m':
    #     df3 = df[df['K']==8.64]
    #     df3 = df3[df3['NSElog']==df3['NSElog'].max()]
    # else:
    df3 = df[df['NSElog']==df['NSElog'].max()]
    model_name3 = df3.model_name.values[0]
    print(w_name, model_name1, model_name2, model_name3)
    
    if w_name == 'S1':
        Smod1 = pd.read_csv(calibration_folder+model_name1+'/_subbasins/subbasin_S1/_simulated_timeseries.csv', sep=';',
                           index_col='date', parse_dates=True)
        Smod2 = pd.read_csv(calibration_folder+model_name2+'/_subbasins/subbasin_S1/_simulated_timeseries.csv', sep=';',
                           index_col='date', parse_dates=True)
        Smod3 = pd.read_csv(calibration_folder+model_name3+'/_subbasins/subbasin_S1/_simulated_timeseries.csv', sep=';',
                           index_col='date', parse_dates=True)
    else:
        Smod1 = pd.read_csv(calibration_folder+model_name1+'/_postprocess/_timeseries/_simulated_timeseries.csv', sep=';',
                           index_col='date', parse_dates=True)
        Smod2 = pd.read_csv(calibration_folder+model_name2+'/_postprocess/_timeseries/_simulated_timeseries.csv', sep=';',
                           index_col='date', parse_dates=True)
        Smod3 = pd.read_csv(calibration_folder+model_name3+'/_postprocess/_timeseries/_simulated_timeseries.csv', sep=';',
                           index_col='date', parse_dates=True)
    
    Qmod1 = Smod1['outflow_drain'] # m/day
    Qmod2 = Smod2['outflow_drain'] # m/day
    Qmod3 = Smod3['outflow_drain'] # m/day
    # r = BV.climatic.runoff
    Rmod = Smod1['recharge']*1000 # m/day
    
    mix = Qobs.copy().to_frame()
    mix.columns = ['Qobs']
    mix['Qmod1'] = Qmod1
    mix['Qmod2'] = Qmod2
    mix['Qmod3'] = Qmod3
    mix = mix.dropna()
    mix = mix * 1000
            
    fig, (a0, a1) = plt.subplots(1, 2, gridspec_kw={'width_ratios': [3, 1]},
                                 figsize=(10,3))
    
    yearsmaj = mdates.YearLocator(1)   # every year
    yearsmin = mdates.YearLocator(1)
    # monthsmaj = mdates.MonthLocator(6)  # every month
    # monthsmin = mdates.MonthLocator(3)
    # months_fmt = mdates.DateFormatter('%m') #b = name of month ?
    years_fmt = mdates.DateFormatter('%Y')

    ax = a0
    ax.plot(mix.Qobs, color='k', lw=1, ls='-', zorder=0, label='Observed')
    m1 = '{:.2e}'.format(float(model_name1.split('_')[-1].split('-')[0])/3600/24) + ' ; ' + str(round((float(model_name1.split('_')[-1].split('-')[1])*100),2))
    m2 = '{:.2e}'.format(float(model_name2.split('_')[-1].split('-')[0])/3600/24) + ' ; ' + str(round((float(model_name2.split('_')[-1].split('-')[1])*100),2))
    m3 = '{:.2e}'.format(float(model_name3.split('_')[-1].split('-')[0])/3600/24) + ' ; ' + str(round((float(model_name3.split('_')[-1].split('-')[1])*100),2))
    ax.plot(mix.Qmod1, color='red', lw=1, ls='-', zorder=0, label='NSElog, RMSE'+' : '+m1)
    ax.plot(mix.Qmod2, color='darkorange', lw=1, label='NSE, KGE'+' : '+m2)
    ax.plot(mix.Qmod3, color='dodgerblue', lw=1, label='NSElog'+' : '+m3)
    ax.set_xlabel('Date')
    ax.set_ylabel('Q [mm/d]')
    ax.set_yscale('log')
    ax.set_ylim(0.1,100)
    years_maj = mdates.YearLocator()   # every year
    months_maj = mdates.MonthLocator()  # every x month
    ax.xaxis.set_major_locator(years_maj)
    ax.xaxis.set_minor_locator(months_maj)
    ax.set_xlim(pd.to_datetime('2016'), pd.to_datetime('2019'))
    ax.legend(loc='lower left', fontsize=5)
    # ax.set_title(model_name.upper(), fontsize=10)
    ax.set_title(w_name.upper(), fontsize=10)
    
    axb = ax.twinx()
    axb.bar(Rmod.index, Rmod,color='grey', edgecolor='grey', width=1, lw=0)
    axb.set_ylim(0,100)
    axb.invert_yaxis()
    axb.set_yticklabels([0,25])

    ax = a1
    ax.scatter(mix.Qobs, mix.Qmod1,
               s=10, edgecolor='none', alpha=0.75, facecolor='red')
    ax.scatter(mix.Qobs, mix.Qmod2,
               s=10, edgecolor='none', alpha=0.75, facecolor='darkorange')
    ax.scatter(mix.Qobs, mix.Qmod3,
               s=10, edgecolor='none', alpha=0.75, facecolor='dodgerblue')
    ax.set_xscale('log')
    ax.set_yscale('log')
    ax.legend(loc='lower right', frameon=False, labelcolor='dodgerblue')
    # ax.plot((0.1,1000),(0.1,1000), color='grey', zorder=-1)
    # ax.set_xlim(1,500)
    # ax.set_ylim(1,500)
    
    ax.plot((0.0001,1000),(0.0001,1000), c='k', ls='--')
    
    ax.set_xlim(0.1,100)
    ax.set_ylim(0.1,100)
 
    ax.set_xlabel('$Q_{obs}$ [mm/d]',
                  # fontsize=12
                  )
    ax.set_ylabel('$Q_{sim}$ [mm/d]',
                  # fontsize=12
                  )
    
    ax.patch.set_visible(True)
    # ax.set_title('$NSE_{log}$' + '  ' + str(round(NSElog,2)), fontsize=10, color='red')

    # move ax in front
    ax.set_zorder(axb.get_zorder() + 1)
    
    fig.tight_layout()
    
    fig.savefig(fig_path+'OBSmatrix2d'+'_'+w_name+'_'+'BEST MODELS'+'.png', dpi=300, bbox_inches='tight')

#%% STREAMFLOW - HGS

CRIT = 'OWN'

init_path = 'C:/Users/ronan/Downloads/_init/Additional Clement/Simulated_time_series/full_model/Qs/'

Qobs_list =[
            'nant_v100fo.hydrograph.S1_Avancon_Nant_Upper.dat',
            'nant_v100fo.hydrograph.S2_Avancon_Nant_Weir.dat',
            'nant_v100fo.hydrograph.S3_Le_Richard.dat'
            ]

areas = [
          9.4,
          13.7,
          14.1
         ]

df = pd.DataFrame()

for w, w_name in enumerate(['S1','Nant_EUDTM30m','Vare_EUDTM30m'][:]):
    
    if w_name == 'S1':
        watershed_name = 'Nant_EUDTM30m'
    else:
        watershed_name = w_name
    
    BV = watershed_root.Watershed(watershed_name=watershed_name, dem_path=dem_path, out_path=out_path, load=True)

    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' # necessary for plots
    calibration_folder = out_path+'/'+watershed_name+'/'+'results_calibration/'
    
    # dfQ = pd.read_csv(init_path+Qobs_list[w], delim_whitespace=True, header=None)
    # dfQ['datetxt'] = dfQ[1]+ ' ' + dfQ[2].apply(str)
    # dfQ['datetime'] = [datetime.strptime(date, "%d/%m/%Y %H:%M:%S") for date in dfQ['datetxt']]
    # data_index = dfQ[3]/(areas[w]*1e6)
    # data_index.index = dfQ['datetime']
    # data_index.index= data_index.index.map(lambda t: t.replace(hour=0, minute=0, second=0, microsecond=0))
    # Qobs = data_index.copy()
    
    dfQsim = pd.read_csv(init_path+Qobs_list[w],delim_whitespace=True, header=2)
    dfQsim = dfQsim.reset_index()
    dfQsim.columns = ["Time","Surface","Porous media","Total"]
    dfQsim.iloc[0]['Time'] = 0
    dfQsim = dfQsim[dfQsim['Time'].mul(1e10).mod(1e10).astype(int).isin([0])]
    dfQsim['Time_y'] = dfQsim['Time'] / 365
    dfQsim['datetime'] = pd.date_range(start='10/01/2014', end='09/30/2018', freq='D')
    dfQsim.index = dfQsim['datetime']
    Qobs = dfQsim['Total'] / (areas[w]*1e6) # m3/day to mm/day

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
        
        Qmod = Smod['outflow_drain'] # m/day
        r = BV.climatic.runoff
        
        mix = Qobs.copy().to_frame()
        mix.columns = ['Qobs']
        mix['Qsim'] = Qmod
        mix = mix.dropna()
        # if w_name == 'Vare_EUDTM30m':
        #     mix = mix[mix.index<='2017-06']
        
        Qobs_stat = mix.Qobs
        Qsim_stat = mix.Qsim
        
        import hydroeval as he
        NSE = he.evaluator(he.nse, Qsim_stat, Qobs_stat)[0]
        NSElog = he.evaluator(he.nse, Qsim_stat, Qobs_stat, transform='log')[0]
        RMSE = np.sqrt(np.nanmean((Qobs_stat.values-Qsim_stat.values)**2)) / (Qobs_stat.max()-Qobs_stat.min())
        KGE = he.evaluator(he.kge, Qsim_stat, Qobs_stat)[0][0]
        # print(model_name.upper())
        # print('NSE', round(NSE,2))
        # print('NSElog', round(NSElog,2))
        # print('RMSE', round(RMSE,2))
        # print('KGE', round(KGE,2))
        
        df.loc[i,'model_name'] = model_name
        
        df.loc[i,'K'] = float(model_name.split('_')[3].split('-')[0])
        df.loc[i,'Sy'] = float(model_name.split('_')[3].split('-')[1])
        df.loc[i,'p1-p2'] = model_name.split('_')[3].split('-')[0]+'-'+model_name.split('_')[3].split('-')[1]
        
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
        
    p1 = df.K.unique()
    p2 = df.Sy.unique()
    ded = np.zeros((len(p1),len(p2)))
    for i, iv in enumerate(p1):
        for j, jv in enumerate(p2):
            string = str(iv)+'-'+str(jv)
            # print(string)
            ded[j][i] = df[df['p1-p2']==string][CRIT]
        
    fig, ax = plt.subplots(1,1, figsize=(3.8,3.5))
    ax.set_aspect('auto')
    ax.axes.tick_params(which='both', direction='out', zorder=10)
    X,Y = np.meshgrid(df.K.unique(), df.Sy.unique())
    Z = ded.copy()
    
    # Z = 1-Z
    # Z = abs(Z)
    # print(np.nanmin(Z), np.nanmax(Z[Z != np.inf]))
    from numpy import inf
    # Z[Z<0] = 0
    # Z[Z == np.inf] = np.nanmax(Z)
    # Z[np.isneginf(Z)] = np.nanmax(Z)
    # Z[~np.isfinite(Z)] = np.nanmax(Z[Z != np.inf])
    # bounds = np.arange(0,1.1,0.1)
    # norm = mpl.colors.Normalize(vmin=0, vmax=1.0)
    # cmap = 'jet'
    cmap = 'RdYlGn'
    if CRIT == 'RMSE':
        cmap = 'RdYlGn_r'
    if CRIT == 'OWN':
        cmap = 'RdYlGn_r'
    # pc = ax.pcolormesh(X/3600/24,Y*100,Z, cmap='RdYlGn', shading='gouraud',
                        # vmin=0, vmax=1
    #                    ) #figadd.cmap_white_jet()
    if w_name == 'Vare_EUDTM30m':
        pc = ax.contourf(X/3600/24, Y*100, Z,
                            # levels=np.arange(0,1.05,0.05), 
                            levels=np.arange(0,10.05,1), 
                            # vmin=0, vmax=1,
                          alpha=0.5, ec='none', cmap=cmap, 
                            extend='max'
                          )
    else:
        pc = ax.contourf(X/3600/24, Y*100, Z,
                            # levels=np.arange(0,1.05,0.05), 
                            levels=np.arange(0,1.05,0.05), 
                            # vmin=0, vmax=1,
                          alpha=0.5, ec='none', cmap=cmap, 
                           extend='max'
                          )
        
    position=fig.add_axes([1.05,0.33,0.03,0.5])  ##
    cb = fig.colorbar(pc, cax=position, orientation='vertical')
    if w_name == 'Vare_EUDTM30m':
        cb.set_ticks(np.arange(0,10.05,1))
    else:
        cb.set_ticks(np.arange(0,1.05,0.2))
    # cb.set_label('$NSE_{log}$ [-]', rotation=270, labelpad=40)
    cb.set_label(CRIT, rotation=270, labelpad=40)
    cb.ax.tick_params(top=True,
                bottom=True,
                left=False,
                right=False,
                labelleft=False,
                labelbottom=True)
    from matplotlib.ticker import FormatStrFormatter
    cb.ax.yaxis.set_major_formatter(FormatStrFormatter('%.2f'))
    
    ax.set_xscale('log')
    ax.set_yscale('log')
    ax.set_ylabel('θ [%]')
    ax.set_xlabel('K [m/s]')
    ax.tick_params(top=True,
               bottom=True,
               left=True,
               right=False,
               labelleft=True,
               labelbottom=True)
    
    ax.set_title(w_name.split('_')[0], fontsize=8)
    
    plt.tight_layout()
    
    fig.savefig(fig_path+'HGSmatrix2d'+'_'+w_name+'_'+CRIT+'.png', dpi=300, bbox_inches='tight')

# STREAMFLOW - PARETO FRONT

    fig, axs = plt.subplots(1,2, figsize=(7.5,3.5))
    axs = axs.ravel()
    ax = axs[0]
    norm_x = abs(1-df.NSElog) / (abs(1-df.NSElog).max() - abs(1-df.NSElog).min())
    norm_y = abs(df.RMSE) / (abs(df.RMSE).max() - abs(df.RMSE).min())
    df['NSElog-RMSE'] = (abs(1-df.NSElog) / (abs(1-df.NSElog).max() - abs(1-df.NSElog).min())) + (abs(df.RMSE) / (abs(df.RMSE).max() - abs(df.RMSE).min()))
    ax.scatter(norm_x, norm_y, lw=0, c=norm_x+norm_y, cmap='RdYlGn_r')
    ax.set_xlabel('NSElog')
    ax.set_ylabel('RMSE')
    ax = axs[1]
    norm_x = abs(1-df.NSE) / (abs(1-df.NSE).max() - abs(1-df.NSE).min())
    norm_y = abs(1-df.KGE) / (abs(1-df.KGE).max() - abs(1-df.KGE).min())
    df['NSE-KGE'] = (abs(1-df.NSE) / (abs(1-df.NSE).max() - abs(1-df.NSE).min())) + (abs(1-df.KGE) / (abs(1-df.KGE).max() - abs(1-df.KGE).min()))
    ax.scatter(norm_x, norm_y, lw=0, c=norm_x+norm_y, cmap='RdYlGn_r')
    ax.set_xlabel('NSE')
    ax.set_ylabel('KGE')
    # ax.set_xlim(0,5)
    # ax.set_ylim(0,5)
    fig.suptitle(w_name.split('_')[0], fontsize=8)
    plt.tight_layout()
    
    fig.savefig(fig_path+'HGSmatrix2d'+'_'+w_name+'_'+'PARETO'+'.png', dpi=300, bbox_inches='tight')
    
# STREAMFLOW - BEST MODELS
    
    df1 = df[df['NSElog-RMSE']==df['NSElog-RMSE'].min()]
    model_name1 = df1.model_name.values[0]
    df2 = df[df['NSE-KGE']==df['NSE-KGE'].min()]
    model_name2 = df2.model_name.values[0]
    # if w_name == 'Vare_EUDTM30m':
    #     df3 = df[df['K']==8.64]
    #     df3 = df3[df3['NSElog']==df3['NSElog'].max()]
    # else:
    df3 = df[df['NSElog']==df['NSElog'].max()]
    model_name3 = df3.model_name.values[0]
    print(w_name, model_name1, model_name2, model_name3)
    
    if w_name == 'S1':
        Smod1 = pd.read_csv(calibration_folder+model_name1+'/_subbasins/subbasin_S1/_simulated_timeseries.csv', sep=';',
                           index_col='date', parse_dates=True)
        Smod2 = pd.read_csv(calibration_folder+model_name2+'/_subbasins/subbasin_S1/_simulated_timeseries.csv', sep=';',
                           index_col='date', parse_dates=True)
        Smod3 = pd.read_csv(calibration_folder+model_name3+'/_subbasins/subbasin_S1/_simulated_timeseries.csv', sep=';',
                           index_col='date', parse_dates=True)
    else:
        Smod1 = pd.read_csv(calibration_folder+model_name1+'/_postprocess/_timeseries/_simulated_timeseries.csv', sep=';',
                           index_col='date', parse_dates=True)
        Smod2 = pd.read_csv(calibration_folder+model_name2+'/_postprocess/_timeseries/_simulated_timeseries.csv', sep=';',
                           index_col='date', parse_dates=True)
        Smod3 = pd.read_csv(calibration_folder+model_name3+'/_postprocess/_timeseries/_simulated_timeseries.csv', sep=';',
                           index_col='date', parse_dates=True)
    
    Qmod1 = Smod1['outflow_drain'] # m/day
    Qmod2 = Smod2['outflow_drain'] # m/day
    Qmod3 = Smod3['outflow_drain'] # m/day
    # r = BV.climatic.runoff
    Rmod = Smod1['recharge']*1000 # m/day
    
    mix = Qobs.copy().to_frame()
    mix.columns = ['Qobs']
    mix['Qmod1'] = Qmod1
    mix['Qmod2'] = Qmod2
    mix['Qmod3'] = Qmod3
    mix = mix.dropna()
    mix = mix * 1000
            
    fig, (a0, a1) = plt.subplots(1, 2, gridspec_kw={'width_ratios': [3, 1]},
                                 figsize=(10,3))
    
    yearsmaj = mdates.YearLocator(1)   # every year
    yearsmin = mdates.YearLocator(1)
    # monthsmaj = mdates.MonthLocator(6)  # every month
    # monthsmin = mdates.MonthLocator(3)
    # months_fmt = mdates.DateFormatter('%m') #b = name of month ?
    years_fmt = mdates.DateFormatter('%Y')

    ax = a0
    ax.plot(mix.Qobs, color='k', lw=1, ls='-', zorder=0, label='Observed')
    m1 = '{:.2e}'.format(float(model_name1.split('_')[-1].split('-')[0])/3600/24) + ' ; ' + str(round((float(model_name1.split('_')[-1].split('-')[1])*100),2))
    m2 = '{:.2e}'.format(float(model_name2.split('_')[-1].split('-')[0])/3600/24) + ' ; ' + str(round((float(model_name2.split('_')[-1].split('-')[1])*100),2))
    m3 = '{:.2e}'.format(float(model_name3.split('_')[-1].split('-')[0])/3600/24) + ' ; ' + str(round((float(model_name3.split('_')[-1].split('-')[1])*100),2))
    ax.plot(mix.Qmod1, color='red', lw=1, ls='-', zorder=0, label='NSElog, RMSE'+' : '+m1)
    ax.plot(mix.Qmod2, color='darkorange', lw=1, label='NSE, KGE'+' : '+m2)
    ax.plot(mix.Qmod3, color='dodgerblue', lw=1, label='NSElog'+' : '+m3)
    ax.set_xlabel('Date')
    ax.set_ylabel('Q [mm/d]')
    ax.set_yscale('log')
    ax.set_ylim(0.1,100)
    years_maj = mdates.YearLocator()   # every year
    months_maj = mdates.MonthLocator()  # every x month
    ax.xaxis.set_major_locator(years_maj)
    ax.xaxis.set_minor_locator(months_maj)
    ax.set_xlim(pd.to_datetime('2016'), pd.to_datetime('2019'))
    ax.legend(loc='lower left', fontsize=5)
    # ax.set_title(model_name.upper(), fontsize=10)
    ax.set_title(w_name.upper(), fontsize=10)
    
    axb = ax.twinx()
    axb.bar(Rmod.index, Rmod,color='grey', edgecolor='grey', width=1, lw=0)
    axb.set_ylim(0,100)
    axb.invert_yaxis()
    axb.set_yticklabels([0,25])

    ax = a1
    ax.scatter(mix.Qobs, mix.Qmod1,
               s=10, edgecolor='none', alpha=0.75, facecolor='red')
    ax.scatter(mix.Qobs, mix.Qmod2,
               s=10, edgecolor='none', alpha=0.75, facecolor='darkorange')
    ax.scatter(mix.Qobs, mix.Qmod3,
               s=10, edgecolor='none', alpha=0.75, facecolor='dodgerblue')
    ax.set_xscale('log')
    ax.set_yscale('log')
    ax.legend(loc='lower right', frameon=False, labelcolor='dodgerblue')
    # ax.plot((0.1,1000),(0.1,1000), color='grey', zorder=-1)
    # ax.set_xlim(1,500)
    # ax.set_ylim(1,500)
    
    ax.plot((0.0001,1000),(0.0001,1000), c='k', ls='--')
    
    ax.set_xlim(0.1,100)
    ax.set_ylim(0.1,100)
 
    ax.set_xlabel('$Q_{obs}$ [mm/d]',
                  # fontsize=12
                  )
    ax.set_ylabel('$Q_{sim}$ [mm/d]',
                  # fontsize=12
                  )
    
    ax.patch.set_visible(True)
    # ax.set_title('$NSE_{log}$' + '  ' + str(round(NSElog,2)), fontsize=10, color='red')

    # move ax in front
    ax.set_zorder(axb.get_zorder() + 1)
    
    fig.tight_layout()
    
    fig.savefig(fig_path+'HGSmatrix2d'+'_'+w_name+'_'+'BEST MODELS'+'.png', dpi=300, bbox_inches='tight')

#%% SATURATION - OBS

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

#%% CONVOLUTION - OBS

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

#%% ---- TEST SIMULATION RUN PLOT

#%% PREPROCESSING

watershed_name = 'Nant_EUDTM30m'

recharge = select_period(hgs_wb['PPT-AET_m/d_sim1'],2017,2017)
runoff = select_period(hgs_wb['PPT-AET_m/d_sim1'],2017,2017)
# recharge = hgs_wb['PPT-AET_m/d_sim1'].copy()
# runoff = hgs_wb['PPT-AET_m/d_sim1'].copy()
        
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
split_temp = True

porosity = 0.1 / 100
hyd_cond = 1.8e-6 * 3600 * 24
ss = 1.6e-4

# iD_set_simulations = 'explorSy_test1'
iD_set_simulations = 't3'

#%% PROCESSING RUN

list_model_name = []
list_success_modflow = []
list_model_modflow = []

# for watershed_name in watershed_names[:]:
    
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
BV.settings.update_input_particles(zone_partic=zone_partic)
BV.hydraulic.update_ss(ss) # Ss_formula = 1000*9.8*(1e-10+(porosity*4.4e-10)) # rho*g*(alpha+nBeta)
BV.hydraulic.update_hyd_cond(hyd_cond)
BV.hydraulic.update_porosity(porosity)
BV.settings.update_split_temporal(split_temp)

compt = 0

# for i, porosity in enumerate(list_porosity[:]):

now = datetime.now()
oclock = now.strftime("%Y%m%d_%Hh%Mm%Ss")

if bottom != None:
    model_name = iD_set_simulations+'-'+str(compt)+'-'+str(bottom)+'-'+str(round(hyd_cond,4))+'-'+str(round(porosity,4))#+'-'+oclock
else:
    model_name = iD_set_simulations+'-'+str(compt)+'-'+str(thick)+'-'+str(round(hyd_cond,4))+'-'+str(round(porosity,4))#+'-'+oclock
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

# for watershed_name in watershed_names[:]:

BV = watershed_root.Watershed(watershed_name=watershed_name, dem_path=dem_path, out_path=out_path, load=True)

stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' # necessary for plots

h5file = simulations_folder+'/'+'results_listing_'+iD_set_simulations
d = dd.io.load(h5file)
    
list_model_name = d['list_model_name'][:]
list_success_modflow = d['list_success_modflow'][:]
list_model_modflow = d['list_model_modflow'][:]

#%% POSTPROCESSING

# for watershed_name in watershed_names[:]:

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
                                  persistency_index = True,
                                  intermittency_monthly = False,
                                  intermittency_weekly = False,
                                  intermittency_daily = True,
                                  export_all_tif = False)

        timeseries_results = BV.postprocessing_timeseries(model_modflow=model_modflow,
                                                          model_modpath=None,
                                                          actual_date=True, 
                                                          subbasin_results=True,
                                                          freq_time='D')

#%% STREAMFLOW

iD_set_simulations = 't2'

def select_period(df, first, last):
    df = df[(df.index.year>=first) & (df.index.year<=last)]
    return df
        
BV = watershed_root.Watershed(watershed_name=watershed_name, dem_path=dem_path, out_path=out_path, load=True)
area = BV.geographic.area
stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' # necessary for plots

h5file = simulations_folder+'/'+'results_listing_'+iD_set_simulations
d = dd.io.load(h5file)
list_model_name = d['list_model_name'][:]
list_success_modflow = d['list_success_modflow'][:]
list_model_modflow = d['list_model_modflow'][:]

# simul_list = sorted(glob.glob(simulations_folder+iD_set_simulations+'*'), key=os.path.getmtime)
# simul_list = sorted(glob.glob(simulations_folder+'t1'+'*'), key=os.path.getmtime)
simul_list = []
for si in list_model_name:
    simul_list.append(os.path.join(simulations_folder,si))
    
Qobs_name = '1_q_weir_s2_obs_NAs_removed.smp'
Qsim_name = '1_simulated_Q_S2.smp'
init_path = hgs_path + '_HGS_v0_James/full_model/'

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
    # print('NSE', round(hgsNSE,2))
    # print('NSElog', round(hgsNSElog,2))
    # print('RMSE', round(hgsRMSE,2))
    # print('KGE', round(hgsKGE,2))
    
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
    
    ax.set_xlim(0.1,100)
    ax.set_ylim(0.1,100)

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
                
    # fig.savefig(os.path.join(simulations_folder, '_figures',
    #             'STREAMFLOW_'+model_name+'.png'),
    #             bbox_inches='tight')

#%% SATURATION

types_obs = ['perennial_natural_streams',
             # 'fully_natural_streams',
              'fully_natural_streams_springs',
             # 'fully_natural_streams_springs_wetlands'
             ]

iD_set_simulations = 't3'

def select_period(df, first, last):
    df = df[(df.index.year>=first) & (df.index.year<=last)]
    return df
    
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
    
    # ax.set_ylim(0,20)
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
                
    # fig.savefig(os.path.join(simulations_folder, '_figures',
    #             'SATURATION_'+model_name+'.png'),
    #             bbox_inches='tight')
          
#%% ---- NOTES
    
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

#%% HUGO

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


## Level correction and rating curve
# convert_Hr<- function(Hm){
  # Hr=(Hm - (5 - 1.83)) * 100
  # return(Hr)
  # }

# rating_curve<- function(H){
  ## H= hauteur d'eau en m
  ## Q= débit en L.s⁻1
 # Q=19997.7043930816*H^1.62440197434267
  # return(Q)
# }

#%% AVERAGES

# kh_arit = np.average(elem_k['KXX'], weights=None)/24/3600
# kh_geom = gmean(elem_k['KXX'], weights=None)/24/3600
# kh_harm = hmean(elem_k['KXX'], weights=None)/24/3600
# kh_arit_w = np.average(elem_k['KXX'], weights=elem_k['VOL_DELAUNAY'])/24/3600
# kh_geom_w = gmean(elem_k['KXX'], weights=elem_k['VOL_DELAUNAY'])/24/3600
# kh_harm_w = hmean(elem_k['KXX'], weights=elem_k['VOL_DELAUNAY'])/24/3600
# kh_arit_weig = np.sum(elem_k['KXX'] * elem_k['VOL_DELAUNAY']) / np.sum(elem_k['VOL_DELAUNAY'])
# kh_geom_weig = np.exp(np.sum((np.log(elem_k['KXX'])) * elem_k['VOL_DELAUNAY']) / np.sum(elem_k['VOL_DELAUNAY'])) # or 10** and np.log10
# kh_harm_weig = np.sum(elem_k['VOL_DELAUNAY']) / np.sum(elem_k['VOL_DELAUNAY'] / elem_k['KXX']) # or 10** and np.log10

#%% PREPARE INPUT HGS

rain_list = glob.glob(hgs_path + '_HGS_v1_Ronan/' + 'DailyForcingData/' + '*rain*')
rain_file = hgs_path + '_HGS_v1_Ronan/' + '_TempoSAS/' + 'WaSiM_v6_Ronan_mod_d_daily_all_rain_plus_melt.data'
rain_df = pd.DataFrame(rain_list)
rain_df.to_csv(rain_file, sep='\t', header=None)

etp_list = glob.glob(hgs_path + '_HGS_v1_Ronan/' + 'DailyForcingData/' + '*etp*')
etp_file = hgs_path + '_HGS_v1_Ronan/' + '_TempoSAS/' + 'WaSiM_v6_Ronan_mod_d_monthly_then_daily_PET.data'
etp_df = pd.DataFrame(etp_list)
etp_df.to_csv(etp_file, sep='\t', header=None)

#%% COMPARE INPUT RAIN ETP HGS

#%% OPEN TECPLOT

file = hgs_path + '_HGS_v1_Ronan/' + 'full_model/' + 'nant_v100fo.pm.dat'
datall = [i.strip().split() for i in open(file).readlines()]
VARIABLES = ["X","Y","Z","Zone","Head","Sat","Depth2GWT","Vx","Vy","Vz","Kxx","Kyy","Kzz","3D Subsurface evaporation","3D Subsurface transpiration"]

# TITLE = "Mesh version 11                                             "
# VARIABLES ="X","Y","Z","Zone","Head","Sat","Depth2GWT","Vx","Vy","Vz","Kxx","Kyy","Kzz","3D Subsurface evaporation","3D Subsurface transpiration"                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       
# ZONE  T="pm", SOLUTIONTIME= 1.0000000000E-01, DATAPACKING=BLOCK, N=    272376, E=    507771, ZONETYPE=FEBRICK        , VARLOCATION=([         4,      8,      9,     10,     11,     12,     13]=CELLCENTERED)                                                                                                                                                                                                                                                                                                                  
# # x

start = datall.index(['#', 'x'])
dat = datall[start:]
super_list_X = []
print('X')
for i in range(len(dat)):
    # print(i)
    # print(start)
    # if i+1 > start:
    if dat[i+1] != ['#', 'y']:
        super_list_X.extend(dat[i+1][:])
        # print(i+1)
    else:
        # print(i+1)
        break
        
start = datall.index(['#', 'y'])
dat = datall[start:]
super_list_Y = []
print('Y')
for i in range(len(dat)):
    # print(i)
    # print(start)
    # if i+1 > start:
    if dat[i+1] != ['#', 'z']:
        super_list_Y.extend(dat[i+1][:])
        # print(i+1)
    else:
        # print(i+1)
        break

start = datall.index(['#', 'z'])
dat = datall[start:]
super_list_Z = []
print('Z')
for i in range(len(dat[start:])):
    # print(i)
    # print(start)
    # if i+1 > start:
    if dat[i+1] != ['#', 'zone', '(cell', 'centred']:
        super_list_Z.extend(dat[i+1][:])
        # print(i+1)
    else:
        # print(i+1)
        break

start = datall.index(['#', 'zone','(cell', 'centred'])
dat = datall[start:]
super_list_ZONE = []
print('ZONE')
for i in range(len(dat)):
    # print(i)
    # print(start)
    # if i+1 > start:
    if dat[i+1] != ['#', 'head']:
        super_list_ZONE.extend(dat[i+1][:])
        # print(i+1)
    else:
        # print(i+1)
        break
        
start = datall.index(['#', 'kxx', '(cell-centered)'])
dat = datall[start:]
super_list_KXX = []
print('KXX')
for i in range(len(dat)):
    # print(i)
    # print(start)
    # if i+1 > start:
    if dat[i+1] != ['#', 'kyy', '(cell-centered)']:
        super_list_KXX.extend(dat[i+1][:])
        # print(i+1)
    else:
        # print(i+1)
        break
    
nodes = pd.DataFrame(columns=['X','Y','Z'])
nodes['X'] = super_list_X
nodes['Y'] = super_list_Y
nodes['Z'] = super_list_Z
nodes['ID'] = np.arange(1, len(nodes)+1, 1)   
     
starts = datall.index(['#', 'head'])
starts = [i for i in range(len(datall)) if datall[i] == ['#','head']]
for si, start in enumerate(starts):
    dat = datall[start:]
    super_list_HEAD = []
    print('HEAD')
    for i in range(len(dat)):
        # print(i)
        # print(start)
        # if i+1 > start:
        if dat[i+1] != ['#', 'saturation']:
            super_list_HEAD.extend(dat[i+1][:])
            # print(i+1)
        else:
            break
    nodes['HEAD_'+str(si)] = super_list_HEAD
    
starts = datall.index(['#', 'saturation'])
starts = [i for i in range(len(datall)) if datall[i] == ['#','saturation']]
for si, start in enumerate(starts):
    dat = datall[start:]
    super_list_SAT = []
    print('SAT')
    for i in range(len(dat)):
        # print(i)
        # print(start)
        # if i+1 > start:
        if dat[i+1] != ['#', 'Depth2GWT']:
            super_list_SAT.extend(dat[i+1][:])
            # print(i+1)
        else:
            break
    nodes['SAT_'+str(si)] = super_list_SAT
        
# if 'clipped' not in globals():
shp = nodes.copy()
geometry = gpd.points_from_xy(shp['X'], shp['Y'], shp['Z'])
gdf = gpd.GeoDataFrame(shp, geometry=gpd.points_from_xy(shp['X'], shp['Y']))
gdf.to_file(hgs_path + "Postprocess/points_mesh_sat.shp")
nant = gpd.read_file(hgs_path + "_HGS_v0_James/full_model/Nant_shape.shp")
clipped = gdf.clip(nant)
clipped.to_file(hgs_path + "Postprocess/points_mesh_sat_nant.shp")
clipped.plot()

nodes = clipped.copy()
nodes = nodes.reset_index()

nodes['Z'] = nodes['Z'].apply(pd.to_numeric, errors='coerce')
nodes['SAT_0'] = nodes['SAT_0'].apply(pd.to_numeric, errors='coerce')
nodes['XY'] = nodes['X']+'-'+nodes['Y']
fil_nodes = pd.DataFrame()
# for i in nodes['XY'].unique():
#     tempo = nodes[nodes['XY']==i]
#     keep = tempo[tempo['Z']==tempo['Z'].max()]
xt = nodes.groupby(['XY'])['Z'].max()
xt = xt.to_frame()
xt = xt.reset_index()
xt['X-Y'] = xt['XY'].str.split('-')
for i, j in xt.iterrows():
    print(i)
    xt.loc[i,'X'] = float(j['X-Y'][0])
    xt.loc[i,'Y'] = float(j['X-Y'][1])
xt['Cond'] = xt['X'] + xt['Y'] + xt['Z']
Cond_list =  xt['Cond'].values
nodes['Cond'] = nodes['X'].astype(float) + nodes['Y'].astype(float) + nodes['Z'].astype(float)
nodes = nodes[nodes['Cond'].isin(Cond_list)]

nodes_save = nodes[nodes['SAT_0']>=0]
nodes_save.plot('SAT_0', cmap='jet', ec='None', markersize=3)
nodes_save.to_file(hgs_path + "Postprocess/points_mesh_sat_nant_sat0.shp")

# wbt.trend_surface_vector_points(
#     hgs_path + "Postprocess/points_mesh_sat_nant_sat0.shp", 
#     'SAT_0', 
#     hgs_path + "Postprocess/points_mesh_sat_nant_sat0.tif", 
#     30, 
#     order=1)

# wbt.vector_points_to_raster(
#     hgs_path + "Postprocess/points_mesh_sat_nant_sat0.shp", 
#     hgs_path + "Postprocess/points_mesh_sat_nant_sat0.tif", 
#     field="FID", 
#     assign="last", 
#     nodata=True, 
#     cell_size=2, 
#     # base=BV.geographic.watershed_dem
#     )

#%% VTK 1

from vtk import vtkStructuredPointsReader
from vtk.util import numpy_support as VN
from vtk.util.numpy_support import vtk_to_numpy
reader = vtkStructuredPointsReader()
reader.SetFileName(file_name)
reader.ReadAllVectorsOn()
reader.ReadAllScalarsOn()
reader.Update()
data = reader.GetOutput()
dim = data.GetDimensions()
vec = list(dim)
vec = [i-1 for i in dim]
vec.append(3)

u = VN.vtk_to_numpy(data.GetCellData().GetArray('saturation'))
b = VN.vtk_to_numpy(data.GetCellData().GetArray('cell_centered_B'))

u = u.reshape(vec,order='F')
b = b.reshape(vec,order='F')

x = zeros(data.GetNumberOfPoints())
y = zeros(data.GetNumberOfPoints())
z = zeros(data.GetNumberOfPoints())

for i in range(data.GetNumberOfPoints()):
        x[i],y[i],z[i] = data.GetPoint(i)

x = x.reshape(dim,order='F')
y = y.reshape(dim,order='F')
z = z.reshape(dim,order='F')

#%% VTK 2

import SimpleITK as sitk


import vtk
from vtk.util.numpy_support import vtk_to_numpy
import scipy.interpolate
import numpy as np

file_name = "D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Vallon/_hgs/_HGS_v1_Ronan/full_model/nant_v100fo.pm.0001.vtk"
file_out = "D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Vallon/_hgs/_HGS_v1_Ronan/full_model/nant_v100fo.pm.0001.tif"

img_vtk = sitk.ReadImage(file_name)

reader = vtk.vtkGenericDataObjectReader() # Using generic to allow it to match either Unstructured or PolyData
reader.SetFileName(file_name)
reader.Update()
output = reader.GetOutput()

nparray = vtk_to_numpy(output.GetPointData().GetArray(0))

output_bounds = output.GetBounds()
x_grid = range(math.floor(output_bounds[0]),math.ceil(output_bounds[1]),1)
y_grid = range(math.floor(output_bounds[2]),math.ceil(output_bounds[3]),1)
z_grid = range(math.floor(output_bounds[4]),math.ceil(output_bounds[5]),1)
grid = list()
for x in x_grid:
   for y in y_grid:
      for z in z_grid:
         grid.append((x,y,z))
dummy = np.array([1 for i in range(nparray.shape[0])])
npgrid = scipy.interpolate.griddata(nparray,dummy,grid,fill_value=0)

npgrid.reshape(len(x_grid),len(y_grid),len(z_grid))
img = sitk.GetImageFromArray(npgrid)
sitk.WriteImage(img, file_out)

# import meshio
# file_name = "D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Vallon/_hgs/_HGS_v1_Ronan/full_model/nant_v100fo.pm.0001.vtk"
# mesh = meshio.read('file.vtk')

#%% VTK 3

import vtk
from vtk import *
from vtk.util.numpy_support import vtk_to_numpy
from scipy.interpolate import griddata
import numpy as np

file_name = "D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Vallon/_hgs/_HGS_v1_Ronan/full_model/nant_v100fo.pm.0001.vtk"

# load a vtk file as input
reader = vtk.vtkXMLUnstructuredGridReader()
reader = vtk.vtkGenericDataObjectReader()
reader.SetFileName(file_name)
reader.Update()

# Get the coordinates of nodes in the mesh
nodes_vtk_array= reader.GetOutput().GetPoints().GetData()

#The "Temperature" field is the third scalar in my vtk file
temperature_vtk_array = reader.GetOutput().GetPointData().GetArray(0)

#Get the coordinates of the nodes and their temperatures
nodes_nummpy_array = vtk_to_numpy(nodes_vtk_array)
x,y,z= nodes_nummpy_array[:,0] , nodes_nummpy_array[:,1] , nodes_nummpy_array[:,2]

temperature_numpy_array = vtk_to_numpy(temperature_vtk_array)
T = temperature_numpy_array

#Draw contours
npts = 1000
xmin, xmax = min(x), max(x)
ymin, ymax = min(y), max(y)

# define grid
xi = np.linspace(xmin, xmax, npts)
yi = np.linspace(ymin, ymax, npts)
# grid the data
Ti = griddata((x, y), T, (xi[None,:], yi[:,None]), method='cubic')  

plt.imshow(Ti)

# ## CONTOUR: draws the boundaries of the isosurfaces
# CS = plt.contour(xi,yi,Ti,10,linewidths=3,cmap=cm.jet) 

# ## CONTOUR ANNOTATION: puts a value label
# plt.clabel(CS, inline=1,inline_spacing= 3, fontsize=12, colors='k', use_clabeltext=1)

# plt.colorbar() 
# plt.show() 