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

#%% PATH WATERSHED

git_path = "D:/Users/abherve/GITHUB/HydroModPy/CORE_COMM/"
# Path to the data folder
data_path = "C:/Users/ronan/OneDrive/_HydroDataPy/"
# Path where the results will be stored
out_path = "D:/Users/abherve/INTERMITTENCY/"

# git_path = "D:/abherve/GITHUB/HydroModPy/CORE_COMM/"
# # Path to the data folder
# data_path = "D:/abherve/HYDRODATAPY/"
# # Path where the results will be stored
# out_path = "D:/abherve/INTERMITTENCY/"

dems_path = data_path + 'DEM/France/' # reginal DEM or conceptual DEM
shp_path = data_path + 'SHAPEFILE/' # if you want run a model from a shapefile
modflow_path = data_path + 'SOFTWARE/MODFLOW/' # add bin/ folder with necessary .exe

# surfex_path =  data_path + 'CLIMATE/France/SURFEX/Rennes/'
surfex_path =  data_path + 'CLIMATE/France/SURFEX/Brittany/' # add surfex models in .h5 format (France scale, else, specify None)
geology_path = data_path + 'GEOLOGY/France/Layer/' # add geologic layers
oceanic_path = data_path + 'OCEANIC/' # add specific sea level files
hydrology_path = data_path + 'HYDROLOGY/France/Hydrographic/D035/' # add hydrographic shapefiles
hydrometry_path = data_path + 'HYDROLOGY/France/Hydrometry/' # add hydrometry data for automatic download
intermittency_path = data_path + 'HYDROLOGY/France/Intermittency/' # add intermittency data for automatic download
piezometry_path = False # add piezometry data for automatic download
subbasin_path = False # generate subbasins from stations or manual points

dem_name = "BDALTI_bzh_75m.tif" # name of dem
from_shp = None # specify a path if process start from a given shapefile
from_dem = False # True or False if the process start from a given DEM of xyz file
cell_size = None # specify new resolution from a given DEM or None

from_xy = []
# Depending on the choices
dem_path = dems_path + dem_name

library_path = git_path + 'watershed/' + 'watershed_library.csv' # each row is a study site with outlet coordinates
watershed_names = ['Canut'] # search the name in watershed_library or just label your result folder

#%% GENERATE WATERSHED

# coords_list = []
# watershed_names = []
# codes_names = ['J7513010','J1803010','J3403020']
# points = gpd.read_file(os.path.join(out_path, '_analysis', 'points.shp'))
# for m in codes_names:
#     for i, j in enumerate(points['watershed_']):
#         if j.split('_')[0] == m:
#             coords_list.append([points.loc[i,'x'],points.loc[i,'y'],200,10])
#             watershed_names.append(j.split('_')[1])
            
types_obs = ['complete','intermittent','perennial','river'] # list of shapefile name layers for clip hydrology
fields_obs = ['persistanc','fid','fid','fid'] # list of shapefile name columns to translate as a tif

types_obs = ['complete'] # list of shapefile name layers for clip hydrology
fields_obs = ['persistanc']

# x = gpd.read_file("C:/Users/ronan/OneDrive/_HydroDataPy/HYDROLOGY/France/Hydrographic/D035/complete.shp")
# c = gpd.read_file(BV.geographic.watershed_shp)
# z = gpd.clip(x, c)
# w = 'D:/Users/abherve/INTERMITTENCY/Canut/results_stable/hydrology/test.shp'
# z.to_file(w)
# y = gpd.read_file(w)

load = True

# for watershed_name, from_xy in zip(watershed_names, coords_list):
for watershed_name in watershed_names:

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
        
    if load != True :
        BV.add_surfex(surfex_path) 
        BV.add_geology(geology_path) 
        BV.add_hydrology(hydrology_path, types_obs=types_obs, fields_obs=fields_obs)
        BV.add_oceanic(oceanic_path)
        BV.add_hydrometry(hydrometry_path)
        BV.add_intermittency(intermittency_path)
        if piezometry_path == True:
            BV.add_piezometry()
        if subbasin_path == True:
            BV.add_subbasin()

    watershed_display.watershed_dem(BV)
    watershed_display.watershed_local(dem_path, BV)

#%% PLOT BV

from matplotlib_scalebar.scalebar import ScaleBar
from rasterio.plot import show
from matplotlib.colors import LightSource
import earthpy.spatial as es
import earthpy.plot as ep

fig, ax = plt.subplots(1, 1, figsize=(5,5), dpi=300)
#polyg = gpd.read_file(BV.geographic.watershed_shp)
contour = gpd.read_file(BV.geographic.watershed_contour_shp)
dem = rasterio.open(BV.geographic.watershed_box_buff_dem)
#bounds = contour.geometry.total_bounds
bounds = dem.bounds
xlim = ([bounds[0], bounds[2]])
ylim = ([bounds[1], bounds[3]])
ax.set_xlim(xlim)
ax.set_ylim(ylim)
scalebar = ScaleBar(1,box_alpha=0, scale_loc = 'bottom', location='upper left')
ax.add_artist(scalebar)
ax.get_xaxis().set_visible(False)
ax.get_yaxis().set_visible(False)
#ax.set_title(BV.name, fontproperties=fontprop)
ax.set(aspect='equal') 
cmap = 'gist_earth'
wbt.hillshade(BV.geographic.watershed_box_buff_dem,
              stable_folder+'geographic/'+'watershed_box_buff_dem_hill.tif',
              azimuth=315.0, 
              altitude=30.0, 
              zfactor=10)
hill = rasterio.open(stable_folder+'geographic/'+'watershed_box_buff_dem_hill.tif')
show(hill.read(1), ax=ax, transform=dem.transform, cmap='Greys_r', alpha=0.5, zorder=2, aspect="auto")
image_hidden = ax.imshow(np.ma.masked_where(dem.read(1) < -100, dem.read(1)), 
                         cmap=cmap, alpha=0.75)
show(np.ma.masked_where(dem.read(1) < -100, dem.read(1)), ax=ax, transform=dem.transform, 
      cmap=cmap, alpha=0.75, zorder=2, aspect="auto")
# ls = LightSource(azdeg=315, altdeg=45)
# rgb = ls.shade(imageio.imread(BV.geographic.watershed_box_buff_dem), cmap=plt.cm.gist_earth,
#                 blend_mode='soft', vert_exag=10, dx=75, dy=75)
# ax.imshow(rgb)

# hillshade = es.hillshade(dem.read(1), altitude=10)
# ax.imshow(hillshade, cmap="Greys", alpha=0.5)
# Plot the hillshade layer with the modified angle altitude
# ep.plot_bands(hillshade, ax=ax, cbar=False)
try:
    streams = gpd.read_file(BV.hydrology.streams)
    streams[streams.persistanc=='Permanent'].plot(ax=ax, lw=2, color='navy',
                                                  zorder=3,legend=True, label='Streams')
    streams[streams.persistanc=='Intermittent'].plot(ax=ax, lw=2, color='navy', ls='--',
                                                  zorder=3,legend=True, label='Streams')
    
except:
    pass
contour.plot(ax=ax, lw=1.5, color='k', zorder=4,legend=True, label='Watershed')
try:
    if os.path.exists(BV.piezometry.piezos_shp):
        piezos = gpd.read_file(BV.piezometry.piezos_shp)
        piezos.plot(ax=ax, color='blue', marker='^', zorder=6, 
                    edgecolor='k', lw=1, legend=True, label='Piezometers: continue')
except:
    pass
try:
    if len(BV.piezometry.x_coord_discrete)>0:
        ax.scatter(BV.piezometry.x_coord_discrete, BV.piezometry.y_coord_discrete, c='darkorange',
                   marker='^', zorder=5, label='Piezometers: discrete')
except:
    pass   
try:
    if os.path.exists(BV.hydrometry.hydrometric_clip):
        hydromet = gpd.read_file(BV.hydrometry.hydrometric_clip)
        hydromet.plot(ax=ax, color='yellow', zorder=7, marker='o', markersize=70,
                      edgecolor='k', lw=1, legend=True, label='Hydrometric: continue')
except:
    pass 
try:
    if os.path.exists(BV.intermittency.onde_clip):
        intermit = gpd.read_file(BV.intermittency.onde_clip)
        intermit.plot(ax=ax, color='yellow', zorder=8, marker='s',markersize=50,
                      edgecolor='black', lw=1, legend=True, label='Intermittency: discrete')
except:
    pass
# ax.legend(loc='lower right', title = BV.watershed_name,framealpha=0.8)
divider = make_axes_locatable(ax)
cax = divider.append_axes(size="2%",position='right', pad=0.05)
fig.add_axes(cax)
cbar = fig.colorbar(image_hidden, cax=cax, orientation="vertical")
cbar.ax.get_ymajorticklabels()
list(cbar.get_ticks())
val = np.ma.masked_where(BV.geographic.dem_box_data < 0, BV.geographic.dem_box_data)
minVal =  int(round(np.min(val[np.nonzero(val)],0)))
maxVal =  int(round(np.max(val[np.nonzero(val)],0)))
meanVal = int(round(minVal+((maxVal-minVal)/2),0))
cbar.set_ticks([minVal, meanVal, maxVal])
cbar.set_ticklabels([minVal, meanVal, maxVal])
cbar.mappable.set_clim(minVal, maxVal)
cbar.ax.tick_params(labelsize=10)
cbar.ax.yaxis.set_ticks_position('right')
cbar.ax.tick_params(size=2)
#cbar.set_label('Elevation (m)', size=12)
fig.tight_layout()
# fig.savefig(os.path.join(BV.figure_folder,'watershed_dem.png'), dpi=300, 
#             bbox_inches='tight', transparent=False)
    
#%% ---

#%% CLASS FUNCTIONS

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

# CLASS

class Hysteresis:
    
    def __init__(self, df, name):
        
        self.df = df
        self.name = name
    
    def prepare_xy_raw(self):
        
        self.first = self.df.first_valid_index().year
        self.last = self.df.last_valid_index().year
        self.years = self.df.index.year.unique()
        
        self.x = self.df.x
        self.y = self.df.y
        self.wy = pd.Series(self.df.index.month).replace([10,11,12,1,2,3,4,5,6,7,8,9],[1,2,3,4,5,6,7,8,9,10,11,12])
        
        self.xi = self.x.groupby([lambda x: x.month]).mean()
        self.yi = self.y.groupby([lambda y: y.month]).mean()
        self.wyi = np.arange(1,12+1,1)
        
        self.xe = pd.DataFrame()
        self.xe['q25'] = (self.x.groupby(self.x.index.month).quantile(0.25))
        self.xe['q75'] = (self.x.groupby(self.x.index.month).quantile(0.75))

        self.ye = pd.DataFrame()
        self.ye['q25'] = (self.y.groupby(self.y.index.month).quantile(0.25))
        self.ye['q75'] = (self.y.groupby(self.y.index.month).quantile(0.75))
    
        self.xiline = self.xi.append(self.xi.iloc[[0]])
        self.xiline.index = np.arange(1,14,1)
        self.yiline = self.yi.append(self.yi.iloc[[0]])
        self.yiline.index = np.arange(1,14,1)
        
        self.date_range = pd.date_range(str(self.first), str(self.last), freq='M')
        self.xw = self.x.copy()
        self.xw.index = self.date_range
        self.xrecap = pd.DataFrame(columns=self.years)
        for year in self.years[0:-1]:
            self.xrecap[year] = self.xw[self.xw.index.year == year].values
        self.xrecap.index = [10,11,12,1,2,3,4,5,6,7,8,9]
        self.xrecap = self.xrecap.sort_index()       
        self.xrecap['xi'] = self.xi
        self.xrecap = self.xrecap.dropna(axis=1, how='all')
        
        self.yw = self.y.copy()
        self.yw.index = self.date_range
        self.yrecap = pd.DataFrame(columns=self.years)        
        for year in self.years[0:-1]:
            self.yrecap[year] = self.yw[self.yw.index.year == year].values
        self.yrecap.index = [10,11,12,1,2,3,4,5,6,7,8,9]
        self.yrecap = self.yrecap.sort_index()              
        self.yrecap['yi'] = self.yi
        self.yrecap = self.yrecap.dropna(axis=1, how='all')
                    
    def plot_xy_obs(self, x_label, y_label, x_lim, y_lim, cmap):
        
        logs = ['linear', 'log']
        
        fig, axs = plt.subplots(1,2,figsize=(7, 3.5))
        fig.add_subplot(111, frameon=False)
        plt.tick_params(labelcolor='none', top=False, bottom=False, left=False, right=False) # hide tick and tick label of the big axis
        axs = axs.ravel()
        
        for i, log in enumerate(logs):
            
            ax = axs[i]
            scat = ax.scatter(self.x, self.y, c=self.wy, cmap=cmap, marker="o", 
                              s=10, vmin=1, vmax=12, alpha=0.75, ec='none')
            ax.plot(self.xi, self.yi, marker="o", markersize=9, markeredgecolor='black', 
                    markerfacecolor='white', linestyle = 'None') 
            for k in self.wyi:
                ax.annotate(k,(self.xi[k],self.yi[k]), family='sans-serif', fontsize=5, 
                            color='black', weight="bold", ha='center', va='center')
            if log != 'log':
                maxi = max(max(x_lim),max(y_lim))
                mini = min(min(x_lim),min(y_lim))
                ax.plot((mini,maxi), (mini,maxi), 
                            linestyle='-', color='grey', linewidth=1.5, zorder=0)
            else:
                # ax.plot(np.linspace(*ax.get_xlim()), np.linspace(*ax.get_xlim()), 
                #         linestyle='-', color='grey', linewidth=1.5, zorder=0)
                ax.plot(np.linspace(0.1,max(x_lim),50), np.linspace(0.1,max(x_lim),50), 
                        linestyle='-', color='grey', linewidth=1.5, zorder=0)
            ax.errorbar(self.xi, self.yi,
                        yerr=np.vstack([self.yi-self.ye.q25, self.ye.q75-self.yi]),
                        xerr=np.vstack([self.xi-self.xe.q25, self.xe.q75-self.xi]),
                        ecolor = 'black', fmt = 'none', capsize = 1, elinewidth=0.5, 
                        capthick=0.5, zorder=1)
            ax.plot(self.xiline, self.yiline, linestyle = '-', lw=1.5, color='k', zorder=-1)
            
            ax.set_xlabel(x_label)
            if i == 0:
                ax.set_ylabel(y_label)
                ax.set_title(self.name)
            else:
                ax.set_title(str(self.first)+'-'+str(self.last))
            ax.set_xlim(x_lim[0], x_lim[1])
            ax.set_ylim(y_lim[0]+0.1, y_lim[1])
            ax.set_xticks(np.linspace(x_lim[0], x_lim[1], 5))
            ax.set_yticks(np.linspace(y_lim[0]+0.1, y_lim[1], 5))
            
            ax.set_yscale(log)
            
        plt.tight_layout()
        position = fig.add_axes([0.95,0.32,0.02,0.5])
        cb = plt.colorbar(scat,cax=position)
        x1 = [1,2,3,4,5,6,7,8,9,10,11,12]
        squad = ['Oct','Nov','Dec','Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep']
        cb.set_ticks(x1)
        cb.set_ticklabels(squad)
        cb.ax.tick_params(labelsize=10)
        cb.update_ticks()

        # fig.savefig(path+'.png', dpi=300, bbox_inches='tight')
    
    def compute_xy_metrics(self, temporal, space, norm):
                
        self.xrecapl = self.xrecap.copy()
        self.xrecapl = self.xrecapl.append(self.xrecapl.iloc[[0]])
        self.xrecapl.index = np.arange(1,14,1)
        
        self.yrecapl = self.yrecap.copy()
        self.yrecapl = self.yrecapl.append(self.yrecapl.iloc[[0]])
        self.yrecapl.index = np.arange(1,14,1)
        
        if norm == True:
            self.xrecapl = (self.xrecapl - self.xrecapl.min()) / \
                           (self.xrecapl.max() - self.xrecapl.min())
            self.yrecapl = (self.yrecapl - self.yrecapl.min()) / \
                         (self.yrecapl.max() - self.yrecapl.min())

        if temporal == False:
            columns_x = self.xrecapl.columns[-1:]
            columns_y = self.yrecapl.columns[-1:]

        else:
            columns_x = self.xrecapl.columns[:]
            columns_y = self.yrecapl.columns[:]
            if space!=0 :
                compt=-1
                itneg=space-1
                for i, col in enumerate(sorted(columns_y[:-1], key=int, reverse=True)):
                    self.xspace = self.xrecapl.iloc[:, itneg:compt]
                    self.yspace = self.yrecapl.iloc[:, itneg:compt]
                    if len(self.xspace.columns) == abs(space):
                        self.xrecapl[col] = self.xspace.mean(axis=1).values
                        self.yrecapl[col] = self.yspace.mean(axis=1).values
                    itneg-=1
                    compt-=1
                self.xrecapl = self.xrecapl.iloc[:,abs(space):]
                self.yrecapl = self.yrecapl.iloc[:,abs(space):]
                columns_x = self.xrecapl.columns
                columns_y = self.yrecapl.columns
        
        # fig, ax = plt.subplots(1,1, figsize=(4,3))
        # n = len(columns_x)
        # colors = pl.cm.jet(np.linspace(0,1,n))        
        
        self.dfmet = pd.DataFrame(columns=[])
        
        for i, (colx, coly) in enumerate(zip(columns_x, columns_y)):
            
            # print(colx)
            
            self.xlist = self.xrecapl[colx]
            self.ylist = self.yrecapl[coly]
            
            self.data = pd.DataFrame()
            self.data['inx'] = self.xlist.values
            self.data['iny'] = self.ylist.values
            
            # ax.scatter(self.data.inx, self.data.iny, s=0, color=colors[i], cmap='jet')
            # ax.plot(self.data.inx,self.data.iny, linestyle = '-', lw=1, color=colors[i], zorder=-1)
            # ax.set_yscale('log') 
            # if colx == 'xi':
            #     if temporal==True:
            #         ax.set_title(str(columns_x[0]) + ' - ' + str(columns_x[-2]))
            #         if space!=0:
            #             ax.set_title(str(columns_x[0]) + ' - ' + str(columns_x[-2]) + ' / ' + str(abs(space)))
            #     else:
            #         ax.set_title(str(self.xrecapl.columns[0]) + ' - ' + str(self.xrecapl.columns[-2]))
            #     ax.plot(self.data.inx,self.data.iny, linestyle = '-', lw=3, color='k', zorder=-1)
            
            # ax.set_xscale('log')
            # plt.close()
              
            self.qmax = self.ylist.max()
            self.qmin = self.ylist.min()
            self.qmed = self.ylist.median()
            self.qmean = self.ylist.mean()
            self.absmin = self.xlist.min()
            self.absmax = self.xlist.max()
            self.q10 = self.ylist.quantile(0.1)
            self.q90 = self.ylist.quantile(0.9)
            self.centerx = self.xlist.mean()
            self.centery = self.ylist.mean()
            self.center = self.centerx / self.centery
            
            self.q0 = self.ylist.iloc[10]
            self.qmid = (self.q0+self.qmax)/2
            self.qsep = (self.qmin+self.qmax)/2
            
            line_loop = SG.LineString(list(zip(self.data.inx,self.data.iny)))            
            line_qmid = SG.LineString([(min(self.data.inx), self.qmid), 
                                        (max(self.data.inx), self.qmid)])
            self.inters_qmid_loop = np.array(line_loop.intersection(line_qmid))

            if len(self.inters_qmid_loop)>=2:
                try:
                    max_hi = np.amax(self.inters_qmid_loop, axis=0)[0]
                    min_hi = np.amin(self.inters_qmid_loop, axis=0)[0]
                    self.hi = max_hi - min_hi
                except:
                    max_hi = np.nan
                    min_hi = np.nan
                    self.hi = np.nan
                    pass
            else:
                max_hi = np.nan
                min_hi = np.nan
                self.hi = np.nan
            
            id_min = self.data.iny.index[self.data.iny == self.data.iny.min()].values[0]
            id_max = self.data.iny.index[self.data.iny == self.data.iny.max()].values[0]
            xmax = self.data.inx[id_max]
            xmin = self.data.inx[id_min]
            
            x_lim = [self.data.inx.min(), self.data.inx.max()]    
            y_lim = [self.data.iny.min(), self.data.iny.max()]    
            maxi = max(max(x_lim),max(y_lim))
            mini = min(min(x_lim),min(y_lim))
            
            self.long = np.sqrt( (xmax - xmin)**2 + (self.qmax - self.qmin)**2 )
            x_m_point = (self.data.inx[id_min] + self.data.inx[id_max])/2
            y_m_point = (self.qmin + self.qmax)/2
            long_min = (xmin, self.qmin)
            long_max = (xmax, self.qmax)
            
            id_y_min = self.data.inx.index[self.data.inx == self.data.inx.min()].values[0]
            id_y_max = self.data.inx.index[self.data.inx == self.data.inx.max()].values[0]
            themax = self.data.iny[id_y_max]
            themin = self.data.iny[id_y_min]
            abs_min = (self.absmin, themin)
            abs_max = (self.absmax, themax)
            
            abs_x = np.linspace(abs_min[0], abs_max[0], 100)
            abs_y = np.linspace(abs_min[1], abs_max[1], 100)
            reg_abs = linregress(abs_x, abs_y)
            self.reg_stat_abs = pd.DataFrame(columns=['center_x','center_y','slope','intercept',
                                              'r_value','p_value','std_err','lenght_reg'])
            self.reg_stat_abs.loc[len(self.reg_stat_abs)] = reg_abs
            self.slope_abs = self.reg_stat_abs.slope[0]
            line_abs = SG.LineString([abs_min, abs_max])
            
            long_x = np.linspace(long_min[0], long_max[0], 100)
            long_y = np.linspace(long_min[1], long_max[1], 100)
            reg = linregress(long_x, long_y)
            self.reg_stat = pd.DataFrame(columns=['center_x','center_y','slope','intercept',
                                              'r_value','p_value','std_err','lenght_reg'])
            self.reg_stat.loc[len(self.reg_stat)] = reg
            self.slope = self.reg_stat.slope[0]
            
            domain = np.linspace(long_min[0], long_max[0])
            try:
                perp_line = [perpendicular_line(x, [x_m_point, y_m_point],
                                            list(long_min), list(long_max)) for x in domain]
                line_perp = SG.LineString([(min(domain), max(perp_line)), (max(domain), (min(perp_line)))])
            except:
                pass
            
            try:
                self.inters_perp_loop = np.array(line_loop.intersection(line_perp))
                if len(self.inters_perp_loop)>=2:
                    try:
                        max_xs = np.amax(self.inters_perp_loop, axis=0)[0]
                        min_xs = np.amin(self.inters_perp_loop, axis=0)[0]
                        max_ys = np.amax(self.inters_perp_loop, axis=0)[1]
                        min_ys = np.amin(self.inters_perp_loop, axis=0)[1]
                        self.short_plus = np.sqrt( (x_m_point - min_xs)**2 + (y_m_point - max_ys)**2 )
                        self.short_minus = np.sqrt( (x_m_point - max_xs)**2 + (y_m_point - min_ys)**2 )
                        self.short = self.short_plus + self.short_minus
                        self.excent = self.long / self.short
                    except:
                        self.short_plus = np.nan
                        self.short_minus = np.nan
                        self.short = np.nan
                        self.excent = np.nan
                        pass
                else:
                    self.short_plus = np.nan
                    self.short_minus = np.nan
                    self.short = np.nan
                    self.excent = np.nan
            except:
                pass
            
            polyg_loop = Polygon(tuple(self.data.itertuples(index=False, name=None)))
            line_long = SG.LineString([long_min, long_max])
            xpolyg, ypolyg = polyg_loop.exterior.xy
            maxi = max(max(x_lim),max(y_lim))
            mini = min(min(x_lim),min(y_lim))
            line_oneone = SG.LineString([(mini,mini), (maxi,maxi)])
            # areas = cut_polygon_by_line(polyg_loop, line_long)
            areas = cut_polygon_by_line(polyg_loop, line_oneone)
            try:
                self.area_plus = areas[1].area
                self.area_minus = areas[0].area
                self.area = polyg_loop.area
            except:
                self.area_plus = np.nan
                self.area_minus = np.nan
                self.area = np.nan
                pass
            
            reg = linregress(self.xlist, self.ylist)
            reg = linregress(self.xw, self.yw)
            self.reg_stat_reg = pd.DataFrame(columns=['center_x','center_y','slope','intercept',
                                              'r_value','p_value','std_err','lenght_reg'])
            self.reg_stat_reg.loc[len(self.reg_stat_reg)] = reg
            self.slope_reg = self.reg_stat_reg.slope[0]
                        
            # Storage
            self.dfmet.loc[colx, 'qmax'] = self.qmax
            self.dfmet.loc[colx, 'qmin'] = self.qmin
            self.dfmet.loc[colx, 'qmed'] = self.qmed
            self.dfmet.loc[colx, 'qmean'] = self.qmean
            self.dfmet.loc[colx, 'q10'] = self.q10
            self.dfmet.loc[colx, 'q90'] = self.q90
            self.dfmet.loc[colx, 'q0'] = self.q0
            self.dfmet.loc[colx, 'qmid'] = self.qmid
            self.dfmet.loc[colx, 'qsep'] = self.qsep
            self.dfmet.loc[colx, 'center'] = self.center
            self.dfmet.loc[colx, 'hi'] = self.hi
            self.dfmet.loc[colx, 'long'] = self.long
            try:
                self.dfmet.loc[colx, 'short'] = self.short
            except:
                pass
            try:
                self.dfmet.loc[colx, 'short_p'] = self.short_plus
                self.dfmet.loc[colx, 'short_n'] = self.short_minus
            except:
                pass
            try:
                self.dfmet.loc[colx, 'excent'] = self.excent
            except:
                pass
            self.dfmet.loc[colx, 'area'] = self.area
            self.dfmet.loc[colx, 'area_p'] = self.area_plus
            self.dfmet.loc[colx, 'area_n'] = self.area_minus
            self.dfmet.loc[colx, 'area_r'] =  self.area_minus / self.area_plus
            self.dfmet.loc[colx, 'slope'] = self.slope
            self.dfmet.loc[colx, 'slope_abs'] = self.slope_abs
            self.dfmet.loc[colx, 'slope_reg'] = self.slope_reg
            
            # if temporal == False:
                
                # fig, ax = plt.subplots(1,1, figsize=(5,5))
                # ax.plot(*line_loop.xy, lw=2, color='dodgerblue')
                # ax.plot(*line_qmid.xy, ls=':', lw=2, color='grey')
                # ax.plot(*line_long.xy, ls='-', lw=2, color='gold')
                # ax.plot(*line_oneone.xy, lw=2, color='k')
                # ax.plot(*line_perp.xy, ls='--', lw=2, color='gold')
                # ax.plot(*line_abs.xy, ls='-', lw=2, color='darkorange')
                # ax.plot(np.linspace(abs_min, abs_max, 100),
                #         self.reg_stat_reg.intercept[0] + self.slope_reg*np.linspace(abs_min, abs_max, 100),
                #         ls='-', lw=2, color='red')
                
                # # plt.gca().set_aspect('equal', adjustable='box')
                # plt.axis('square')
                # plt.xlim(mini, maxi)
                # plt.ylim(mini, maxi)
            
        # self.dfmet.to_csv('Metrics_'+'Obs_'+self.name+'_'+str(space)+'.csv', sep=';')

    def plot_xy_mod(self, ax, x_label, y_label, x_lim, y_lim, cmap, scale):
        
        ax = ax
        scat = ax.scatter(self.x, self.y, c=self.wy, cmap=cmap, marker="o", 
                          s=10, vmin=1, vmax=12, alpha=0.75, ec='none')
        ax.plot(self.xi, self.yi, marker="o", markersize=9, markeredgecolor='black', 
                markerfacecolor='white', linestyle = 'None') 
        for k in self.wyi:
            ax.annotate(k,(self.xi[k],self.yi[k]), family='sans-serif', fontsize=5, 
                        color='black', weight="bold", ha='center', va='center')
        if scale != 'log':
            try:
                maxi = max(max(x_lim),max(y_lim))
                mini = min(min(x_lim),min(y_lim))
                ax.plot((mini,maxi), (mini,maxi), 
                            linestyle='-', color='grey', linewidth=1.5, zorder=0)
            except:
                pass
        else:
            # ax.plot(np.linspace(*ax.get_xlim()), np.linspace(*ax.get_xlim()), 
            #         linestyle='-', color='grey', linewidth=1.5, zorder=0)
            ax.plot(np.linspace(0.1,max(x_lim),50), np.linspace(0.1,max(x_lim),50), 
                    linestyle='-', color='grey', linewidth=1.5, zorder=0)
        ax.errorbar(self.xi, self.yi,
                    yerr=np.vstack([self.yi-self.ye.q25, self.ye.q75-self.yi]),
                    xerr=np.vstack([self.xi-self.xe.q25, self.xe.q75-self.xi]),
                    ecolor = 'black', fmt = 'none', capsize = 1, elinewidth=0.5, 
                    capthick=0.5, zorder=1)
        ax.plot(self.xiline, self.yiline, linestyle = '-', lw=1.5, color='k', zorder=-1)
        
        ax.set_xlabel(x_label)
        ax.set_ylabel(y_label)
        ax.set_title(self.name)
        ax.set_title(str(self.first)+'-'+str(self.last))
        try:
            ax.set_xlim(x_lim[0], x_lim[1])
            ax.set_ylim(y_lim[0]+0.1, y_lim[1])
            ax.set_xticks(np.linspace(x_lim[0], x_lim[1], 5))
            ax.set_yticks(np.linspace(y_lim[0]+0.1, y_lim[1], 5))
        except:
            pass
        
        ax.set_yscale(scale)
            
        plt.tight_layout()
        
        # position = fig.add_axes([0.95,0.32,0.02,0.5])
        # cb = plt.colorbar(scat,cax=position)
        # x1 = [1,2,3,4,5,6,7,8,9,10,11,12]
        # squad = ['Oct','Nov','Dec','Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep']
        # cb.set_ticks(x1)
        # cb.set_ticklabels(squad)
        # cb.ax.tick_params(labelsize=10)
        # cb.update_ticks()


#%% ---

#%% DICHOTOMY STREAMS

from calibration import calib_root, calib_dichotomy, calib_analysis, calib_exploration, calib_basis

types_obs = ['complete','intermittent','perennial','river','drain_complete_chezecanut'] # list of shapefile name layers for clip hydrology
fields_obs = ['persistanc','fid','fid','fid','fid'] # list of shapefile name columns to translate as a tif

# types_obs = ['drain_complete_chezecanut'] # list of shapefile name layers for clip hydrology
# fields_obs = ['fid']

df = pd.DataFrame(np.nan, index=range(1), columns=types_obs)

for type_obs, field_obs in zip(types_obs, fields_obs):

    load = True
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
    
    BV.add_hydrology(hydrology_path, types_obs=[type_obs], fields_obs=[field_obs])
    
    BV.forcing.update_recharge_surfex(clim_mod = 'OLD', clim_sce='historic',
                                      first_year = 1971, last_year=2011, time_step = 'D',
                                      sim_state='steady') #
    
    # BV.forcing.update_recharge_surfex(clim_mod = 'REA', clim_sce='historic',
    #                                   first_year = 1971, last_year=2011, time_step = 'D',
    #                                   sim_state='steady') #
    # print(BV.forcing.recharge)
    
    BV.hydrodynamic.update_thickness(30)
    BV.hydrodynamic.update_porosity(0.1)
    BV.hydrodynamic.update_hyd_cond(2)
    
    params_file = 'calib_dicot_hom_1v_k1'
    # params_file = 'calib_dicot_het_2v_k1-k2'
    # params_file = 'calib_dicot_hom_2v_k1-n1'
    calib = calib_root.Calibration(params_file, BV, observations = ['streams'])
    dicot = calib.dichotomy(gap=1)
    
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
    
    df.loc[0,type_obs] = koptim / 24 / 3600
    df.loc[1,type_obs] = kr
    df.loc[2,type_obs] = obj_func
    
df.to_csv(BV.calibration_folder+'/Koptims_dichotomy_streams.csv', sep=';')

koptim = df.loc[0,'drain_complete_chezecanut']

df = pd.read_csv(BV.calibration_folder+'/Koptims_dichotomy_streams.csv', sep=';')

#%% EXPLORATION HYDROMETRY

from calibration import calib_root, calib_dichotomy, calib_analysis, calib_exploration, calib_basis, calib_params
    
first = 1990
last = 2019
var = 'EFF'
wr = True
wish = 0

for mod in ['REA'] :

    # mod = 'REA'
    
    BV.forcing.update_runoff_surfex(clim_mod = mod, clim_sce='historic',
                                      first_year = first, last_year=last, time_step = 'M',
                                      sim_state='transient')
    Runof = BV.forcing.runoff # m/month
    
    if var == 'EFF':
        BV.forcing.update_effppt_surfex(clim_mod = mod, clim_sce = 'historic',
                                        first_year = first, last_year = last, time_step = 'M',
                                        sim_state='transient')
        BV.forcing.update_recharge(BV.forcing.recharge, sim_state='transient')
        Rech = BV.forcing.recharge # m/month
        plt.plot(Rech)
    
    if var == 'REC':
        BV.forcing.update_recharge_surfex(clim_mod = mod, clim_sce='historic',
                                          first_year = first, last_year=last, time_step = 'M',
                                          sim_state='transient')
        BV.forcing.update_recharge(BV.forcing.recharge, sim_state='transient')
        Rech = BV.forcing.recharge # m/month
        plt.plot(Rech)
    
    if wr == True:
        BV.forcing.update_recharge(BV.forcing.recharge - Runof, sim_state='transient')
        Rech = BV.forcing.recharge # m/month
        plt.plot(Rech)
    
    # plt.plot(BV.forcing.recharge)
    # plt.plot(BV.forcing.runoff)
    
    BV.hydrodynamic.update_thickness(30)
    # BV.hydrodynamic.update_porosity(0.001)
    # BV.hydrodynamic.update_hyd_cond(0.08640) # 1e-6 m/s
    
    params_file = 'calib_explo_hom_2v_k1-n1'
    # params_file = 'calib_explo_hom_1v_n1'
    # params_file = 'calib_explo_hom_1v_k1'
    # params_file = 'calib_dicot_het_2v_k1-k2'
    
    # calib = calib_root.Calibration(params_file, BV, observations = ['hydrometry'])
    # calib.exploration(resolution=1000)
    
    ##########
    typ_calib = 'hydrometry_calibration'
    list_path = sorted(glob.glob(os.path.join(BV.calibration_folder, params_file, typ_calib, '*.calib')),
                        key=os.path.getmtime, reverse=True)
    name_file = list_path[wish].split('\\')[-1]
    calib_file = os.path.join(BV.calibration_folder, params_file, typ_calib, name_file)
    test = calib_analysis.CalibAnalysis(calib_file)
    # test.display_objective_function(save=None)
    # test.find_best_values()
    # test.display_best_data()
    
    # t=test.sim_results
    # x= pd.to_numeric(test.sim_results[test.params_synt[0]]['seepage_areas'])
    # plt.plot(x)
    
    path_fig = os.path.join(BV.calibration_folder, params_file, typ_calib, '_figures')
    
    # CHRONICS
    
    fig, axs = plt.subplots(3,1, figsize=(7,7))
    axs = axs.ravel()
    
    typ_name = typ_calib.split('_')[0]
    
    yearsmaj = mdates.YearLocator(5)   # every year
    yearsmin = mdates.YearLocator(1)
    # monthsmaj = mdates.MonthLocator(6)  # every month
    # monthsmin = mdates.MonthLocator(3)
    # months_fmt = mdates.DateFormatter('%m') #b = name of month ?
    years_fmt = mdates.DateFormatter('%Y')
    
    obs = test.data_obs
    sim = test.data_sim
    ind = test.data_ind
    obj = test.calib['objective_function']
    xyz = test.params_xyz
    
    synt = test.params_synt
        
    p1 = []
    for p in synt:
        p1.append(p.split(';')[0])
    p2 = []
    for p in synt:
        p2.append(p.split(';')[1])
    rout = []
    for r in sim[typ_name]:
        rout.append((r*1000*30).mean()[0])
    rsat = []
    for t in range(len(synt)):     
        sat = test.sim_results[synt[t]]['seepage_areas']
        sat = pd.to_numeric(sat)
        rsat.append(sat.mean())
    
    fig, ax = plt.subplots(1,1, figsize=(6,5))
    axb = ax.twinx()
    x = range(len(p1))
    ax.plot(x, [float(i) for i in p1], marker='.', lw=0, c='blue', label='K [m/j]')
    ax.plot(x, [float(i) for i in p2], marker='.', lw=0, c= 'green', label='Sy [-]')
    axb.plot(x, rsat, marker='.', lw=0, c= 'red', label='Saturation [%]')
    axb.plot(x, rout, marker='.', lw=0, c= 'darkorange', label='Outflow [mm/mois]')
    ax.set_xlabel('Simulations')
    ax.set_ylabel('K and Sy')
    axb.set_ylabel('Saturation and Outflow', rotation=270, labelpad=25)
    ax.legend(loc = 'upper left')
    axb.legend(loc='upper center')
    ax.grid('grey')
    ax.axhline(y=6.6E-7*24*3600, c = 'b', lw=2)
    # ax.axhline(y=0.1, c = 'g', lw=2)
    # plt.scatter(rout, rsat)
            
    nse_good = []
    sat_good = []
    
    numb = 0
    for i in range(len(obs[typ_name])):
        
        o = obs[typ_name][i] * 1000 * 30 # m/j to mm/month
        s = sim[typ_name][i] * 1000 * 30 # m/j to mm/month
        nd = ind[typ_name][i]
        sat = test.sim_results[synt[i]]['seepage_areas']
        sat = pd.to_numeric(sat)
        
        k = '{:.1e}'.format(xyz[i][0]/24/3600)
        sy = xyz[i][1] * 100
        title = 'Discharge'
        nselog = round(((nd[0]))*100,1)
        label = 'K = '+k+' m/s'+' ; '+'ɸ = '+str(round(sy,1))+'% ; '+\
                '$NSE_{log}$ = '+str(nselog)+'%'
        nse_good.append(str(k)+'_'+str(sy)+'_'+str(nselog))
                
        if nselog > 60:
            if all(i <= 50 for i in sat):
                numb += 1
                
        # c = []
        # for h in range(len(ind[typ_name])):
        #     d = ind[typ_name][h][0]
        #     c.append(d)
        c = np.linspace(0,1,len(obs[typ_name]))
        # c = np.linspace(0,1,numb)
        cmap = mpl.cm.get_cmap('jet')
        color_gradients = cmap(c)
        # vmin = min(c)
        # vmax = max(c)
        # norm = mpl.colors.Normalize(vmin=vmin, vmax=vmax)
                       
        if nselog > 70:
            if all(i <= 60 for i in sat):       
                
                ax = axs[0]
                ax.xaxis.set_major_locator(yearsmaj)
                ax.xaxis.set_minor_locator(yearsmin)
                ax.xaxis.set_major_formatter(years_fmt)
                
                ax.plot(s, color=color_gradients[i], lw=1, label=label)
                # ax.plot(s, lw=1, label=label)   
                ax.set_title(title)
                ax.plot(o, color='grey', lw=3, ls='-', zorder=0)
                # ax.set_xlim(pd.to_datetime('2000'), pd.to_datetime('2005'))
                
                ax = axs[1]
                ax.xaxis.set_major_locator(yearsmaj)
                ax.xaxis.set_minor_locator(yearsmin)
                ax.xaxis.set_major_formatter(years_fmt)
                ax.plot(o, color='grey', lw=3, ls='-', zorder=0)
                ax.set_yscale('log')
                ax.plot(s, color=color_gradients[i], lw=1, label=label)
                
                ax = axs[2]
                ax.xaxis.set_major_locator(yearsmaj)
                ax.xaxis.set_minor_locator(yearsmin)
                ax.xaxis.set_major_formatter(years_fmt)    
                sat_good.append(str(k)+'_'+str(sy)+'_'+str(round(sat.mean(),2)))
                ax.plot(sat, color=color_gradients[i], lw=0.5, label=label)
                # ax.plot(sat, lw=1, label=label) 
                ax.set_ylim(-2,100)
                title = 'Saturation'
                ax.set_title(title)
                # ax.set_xlim(pd.to_datetime('2000'), pd.to_datetime('2005'))
                            
    plt.tight_layout()
    ax.legend(bbox_to_anchor=(1.5, 3), ncol=1)
    fig.savefig(path_fig+'/'+'_chronic_'+name_file+'.png', dpi=300, bbox_inches='tight')

    # ax.plot(BV.forcing.recharge, color='grey', lw= 5)
           
    # divider = make_axes_locatable(ax)
    # cax = divider.append_axes('right', size='1.25%', pad=0.1)
    # fig.add_axes(cax)
    # norm = Normalize(vmin=vmin, vmax=vmax)
    # n_cmap = cm.ScalarMappable(norm=norm, cmap=cmap)
    # n_cmap.set_array([])
    # ax.get_figure().colorbar(n_cmap, cax=cax, orientation="vertical")
    
    # MESH
    
    fig, ax = plt.subplots(1,1, figsize=(6,5))
    X,Y = np.meshgrid(test.params_values[0], test.params_values[1])
    Z=test.obj_function
    pc = ax.pcolormesh(X,Y,Z,cmap='jet') #figadd.cmap_white_jet()
    ax.set_xscale('log')
    cb = fig.colorbar(pc)
    ax.set_ylabel('Sy [-]')
    ax.set_xlabel('K [m/j]')
    cb.set_label('$NSE_{log}$', rotation=270, labelpad=40)
    fig.savefig(path_fig+'/'+'_mesh_'+name_file+'.png', dpi=300, bbox_inches='tight')
    
    # SHADED
    
    fig, ax = plt.subplots(1,1, figsize=(6,5))
    X,Y = np.meshgrid(test.params_values[0], test.params_values[1])
    Z=test.obj_function
    pc = ax.pcolormesh(X,Y,Z,cmap='jet', shading='gouraud') #figadd.cmap_white_jet()
    ax.set_xscale('log')
    cb = fig.colorbar(pc)
    ax.set_ylabel('Sy [-]')
    ax.set_xlabel('K [m/j]')
    cb.set_label('$NSE_{log}$', rotation=270, labelpad=40)
    fig.savefig(path_fig+'/'+'_shaded_'+name_file+'.png', dpi=300, bbox_inches='tight')
    
    # CONTOUR
    
    fig, ax = plt.subplots(1,1, figsize=(6,5))
    X,Y = np.meshgrid(test.params_values[0], test.params_values[1])
    Z=test.obj_function
    Z[Z<0] = np.nan
    # np.ma.masked_where(test.obj_function<0, test.obj_function)
    # plt.pcolor(X,Y,Z,cmap='jet')#figadd.cmap_white_jet()
    pc = ax.contourf(X, Y, Z)
    # plt.imshow(Z)
    # plt.xlim(1)
    cb = fig.colorbar(pc)
    ax.set_xscale('log')
    ax.set_ylabel('Sy [-]')
    ax.set_xlabel('K [m/j]')
    cb.set_label('$NSE_{log}$', rotation=270, labelpad=40)
    fig.savefig(path_fig+'/'+'_contour_'+name_file+'.png', dpi=300, bbox_inches='tight')

#%% ---

#%% PARAMETERS MODEL

# Input recharge
bzh_rech = False
var = 'REC'
mod = 'OLD'
sce = 'historic'
typ = 'steady' # sinu / hist / proj

# Choice temporal of the simulation
sim_state = 'steady' # 'steady' or 'transient'
init_rech = 'first'
period = [1971,2011] # recharge period
first = period[0]
last = period[1]
time_step = 'M' # or 'D'
actual_date = True # False if date is conceptual
start = str(period[0])+'-01-01' # necessary to specify the first time_step date


BV.forcing.update_recharge_surfex(clim_mod = mod, clim_sce = 'historic',
                                         first_year = 2000, last_year = 2010,
                                         time_step = time_step, sim_state=sim_state)
Hist = BV.forcing.recharge


# Active of not modules
box = False # if True generate a rectangular model
sink_fill = False # permit to fill sinks
modpath_sim = False # run modpath particle tracking if True
verbose = False # add print of MODFLOW in console
post_process = False # print time_step

# Strcture of the model
lay_number = 1 # vertical discrtization
bottom = None # aquifer flat or not
thick_exp = 1 # exponential decay of K with nlay
cond_decay = 0 # exponential decay of K with depth
thick = 30 # m

# Hydraulic properties
Koptim = 4.2e-5 # koptim
Ks = np.array([Koptim/10,Koptim,Koptim*10]) * 3600 * 24 # m/second to m/month
Sys = [0.1,0.01,0.001]

Ks = np.array([Koptim]) * 3600 * 24 # m/second to m/month
Sys = [0.01]

# Ks = np.array([Koptim]) * 3600 * 24 # m/second to m/month
# Sys = [0.1,0.01,0.001]
# Sys = [0.1]

#%% RUN MODEL

list_model_name = []
list_of_success = []
list_flow_model = []

compt = 1
# Update properties
for Sy in Sys:
    for K in Ks:
        # K = 1e-5
        # Sy = 0.01
        # print(K)
        BV.hydrodynamic.update_thickness(thick)
        BV.hydrodynamic.update_hyd_cond(K) 
        BV.hydrodynamic.update_porosity(Sy)
        
        if var == 'REC':
            BV.forcing.update_recharge_surfex(clim_mod = mod, clim_sce = sce,
                                              first_year = first, last_year = last, 
                                              time_step = time_step, sim_state=sim_state)
            BV.forcing.update_recharge(BV.forcing.recharge, sim_state=sim_state)
            Rech = BV.forcing.recharge # m/month
            if (sce == 'RCP2.6') | (sce == 'RCP8.5'):
                Rech = pd.concat((Rech, Hist), axis=1).mean(axis=1)
                BV.forcing.update_recharge(Rech, sim_state=sim_state)
                Rech = BV.forcing.recharge # m/month
            plt.plot(Rech)
        
        if var == 'EFF':
            BV.forcing.update_effppt_surfex(clim_mod = mod, clim_sce = sce,
                                            first_year = first, last_year = last, 
                                            time_step = time_step, sim_state=sim_state)
            BV.forcing.update_recharge(BV.forcing.recharge, sim_state=sim_state)
            Rech = BV.forcing.recharge # m/month
            plt.plot(Rech)
        
        if bzh_rech == True:
            forc = forcing.Forcing(out_path+'Bzh/')
            forc.update_recharge_surfex(clim_mod = mod, clim_sce = sce,
                                        first_year = first, last_year = last, 
                                        time_step = time_step, sim_state=sim_state)
            BV.forcing.update_recharge(forc.recharge, sim_state=sim_state)
            Rech = BV.forcing.recharge # m/month
            plt.plot(Rech)
        
        if typ == 'conceptexplo':
            BV.forcing.update_sinusoid_recharge(Rech, 'M', 1, 1, 1, 1) # serie, period / amplitude, offset, omega, phase
            plt.plot(Rech)
            # print(Rech.sum())
            Rech = BV.forcing.recharge
            plt.plot(Rech)
            # print(Rech.sum())
  
        date_today = datetime.now().strftime("%d/%m/%Y %H:%M:%S") # just a string
        date_today = date_today.replace('/','-')
        date_today = date_today.replace(':','-')
        date_today = date_today.replace(' ','_')
        
        model_name = typ+'_'+str(compt)+'_'+\
                     var+'-'+mod+'-'+sce+'_'+\
                     str(Sy*100)+'-'+str(round(K,2))+'-'+str(thick)+'_'+\
                     str(first)+'-'+str(last)
                     
        # Run model
        try:
            print('SIM - ' + model_name)
            success, flow_model = BV.run_modflow(ident=model_name,
                                                modpath_sim=modpath_sim,
                                                sink_fill=sink_fill,
                                                box=box,
                                                lay_number=lay_number,
                                                bottom=bottom,
                                                thick_exp=thick_exp,
                                                cond_decay=cond_decay,
                                                verbose=True,
                                                post_process=post_process, 
                                                init_rech=init_rech)
            if success == True:
                print(     'Success')
            else:
                print(     'Error')
        except:
            pass
        list_model_name.append(model_name)
        list_of_success.append(success)
        list_flow_model.append(flow_model)
        compt+=1
        
print(list_of_success)

dictio = {}
dictio['list_model_name'] = list_model_name
dictio['list_of_success'] = list_of_success
dictio['list_flow_model'] = list_flow_model
h5file = simulations_folder+'/'+'list_'+typ+'_'+var+'-'+mod+'-'+sce
# dictio.to_hdf(h5file)
dd.io.save(h5file, dictio)

# BV.list_flow_model = list_flow_model
# BV.list_of_success = list_success
# BV.save_object()
        
#%% POSTPROCESS MODEL

h5file = simulations_folder+'/'+'list_'+typ+'_'+var+'-'+mod+'-'+sce
d = dd.io.load(h5file)
list_model_name = d['list_model_name'][0:1]
list_of_success = d['list_of_success'][0:1]
list_flow_model = d['list_flow_model'][0:1]

for model_name, success, flow_model in zip(list_model_name, list_of_success, list_flow_model):
        
    if success==True:
        
            BV.matrix_modflow(success,
                              flow_model,
                              first_only = False,
                              watertable_elevation = True,
                              watertable_depth = True, 
                              seepage_areas = True,
                              outflow_drain = True,
                              groundwater_flux = False,
                              specific_discharge = False,
                              accumulation_flux = True,
                              perenn_intermit_shp = False,
                              groundwater_storage = True,
                              verbose = True,
                              export_tif = True)
            
            # # Extract results
            BV.results_modflow(ident=model_name,
                               actual_date=actual_date,
                               start=start,
                               time_step=time_step)
            
            # # Plot maps
            save_gif = False # save a gif after plots
            Rech = flow_model.climatic
            surf = modflow_display.SurfaceOutputs(Rech, simulations_folder, stable_folder, model_name, 
                                                  types_obs, save_gif=save_gif, first_only=True,
                                                  outflow=True, accflux=True, intermittency=False,
                                                  chronics=True, sim_state=sim_state)

#%% 2D CROSS SECTION

interactive = False

dem_data = BV.geographic.dem_data # dem data
wt_data = imageio.imread(simulations_folder+model_name+'/_watershed/_tifs/'+'watertable_elevation_t(0).tif') # watertable data
if watershed_name == 'Conceptual':
    river_data = None
else:
    river_data = imageio.imread(stable_folder+'/hydrology/'+'complete.tif') # river data

modflow_display.interactive_cross_section(dem_data, wt_data, river_data, interactive=interactive)

#%% ---

#%% FIG a : INTERMITTENCY MAP

var = 'REC'
mod = 'OLD'
sce = 'historic'
typ = 'conceptexplo'

mod = 'IPS1'
sce = 'RCP2.6'
typ = 'projexplo'

years = BV.forcing.recharge.index.year.unique()

simul_list = glob.glob(simulations_folder+typ+'*'+sce+'*')
# simuls = fnmatch.filter(os.listdir(simulations_folder), typ+'*')

wbt.vector_lines_to_raster(stable_folder+'geographic/'+'watershed_contour.shp',
                           stable_folder+'geographic/'+'watershed_contour.tif',
                           base = stable_folder+'geographic/'+'watershed_dem.tif')
line = imageio.imread(stable_folder+'geographic/'+'watershed_contour.tif')
line = np.ma.masked_where(line <= 0, line)

fig1, axs1 = plt.subplots(3,3, figsize=(10,10))
axs1 = axs1.ravel()

mfdata= pd.DataFrame()

for ix, simul in enumerate(simul_list[0:1]):
    
    print(ix)
    mask = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
    ax = axs1[ix]
    ax.imshow(np.ma.masked_where(mask<0, mask), cmap='Greys', alpha=0.25, zorder=0)
    acc_npy = np.load(os.path.join(simul, '_watershed','accumulation_flux.npy'), allow_pickle=True).item()
    
    for key in acc_npy:
        # print(key)
        # acc = np.ma.masked_where(dem.read(1) < 0, dem.read(1))
        acc_npy[key] = np.ma.masked_array(acc_npy[key], mask=(mask<0))
    zero = acc_npy[0] * 0
    
    for i in range(len(acc_npy)):
        tempo = acc_npy[i].copy()
        tempo[tempo>0] = 1
        zero = zero + tempo
    days_flux = zero.copy() # / len(acc_npy)
    
    # fig, ax = plt.subplots(1,1, figsize=(7,6))
    # ax.imshow(np.ma.masked_where(days_flux <= 0, days_flux),
    #                cmap = 'viridis_r', vmin=1, vmax=12, alpha=1)
    # fig.savefig(simul+'_figures'+'persistency_'+str(i)+'.png', dpi=300, bbox_inches='tight')
    
    acc_npy = np.load(os.path.join(simul, '_watershed','accumulation_flux.npy'), allow_pickle=True).item()
    acc_temp = acc_npy.copy()
    inf = 0
    sup = 12
    step = int(round(len(acc_npy)/12))
    cp= 0 
    for i in range(step):
        print(str(i)+' / '+str(step))
        interv = list(acc_temp.items())[inf:sup]
        # print(interv)
        for key in range(len(interv)):
            # key = tupl[0]
            # print(key)
            mask = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
            interv[key] = np.ma.masked_array(interv[key][1], mask=(mask<0))
            
        zero = acc_npy[0] * 0
        
        for j in range(len(interv)):
            tempo = interv[j].copy()
            tempo[tempo>0] = 1
            zero = zero + tempo
        days_flux = zero.copy()
        days_flux = np.ma.masked_array(days_flux, mask=(mask<0))
        days_flux = np.ma.masked_array(days_flux, mask=(days_flux<=0))
        plt.imshow(days_flux)
        
        for k in range(len(interv)):
            tempo = np.ma.masked_where(interv[k]<=0, interv[k])
            tempo[days_flux<12] = 0
            tempo[days_flux==12] = 1
            tempo = np.ma.masked_where(interv[k]<=0, tempo)
            surflow = (((tempo >= 0).sum())) * 100
            perenn = (((tempo == 1).sum())) * 100
            intermit = (((tempo == 0).sum())) * 100
            mfdata.loc[cp,'perenn_areas'] = perenn
            mfdata.loc[cp,'intermit_areas'] = intermit
            mfdata.loc[cp,'surflow_areas'] = surflow
            
            # if i<=5:
            #     fig, ax = plt.subplots(1,1, figsize=(7,6))
            #     # image_hidden = ax.imshow(np.ma.masked_where(mask<0, mask), cmap='Greys')
            #     ax.imshow(np.ma.masked_where(mask<0, mask), cmap='Greys', alpha=0.5, zorder=0)
            #     ax.imshow(np.ma.masked_where(tempo==0, tempo), cmap = mpl.colors.ListedColormap(['dodgerblue']))
            #     ax.imshow(np.ma.masked_where(tempo==1, tempo), cmap = mpl.colors.ListedColormap(['darkorange']))
            #     ax.imshow(line, cmap=mpl.colors.ListedColormap('k'))
            #     ax.get_xaxis().set_visible(False)
            #     ax.get_yaxis().set_visible(False)
            #     mois = "%02d" % (j+1,)
            #     ax.set_title(str(years[i])+'-'+str(mois))
            #     fig.savefig(simul+'/_figures/'+'intermittency_'+str(i)+'-'+str(mois)+'.png', dpi=300, bbox_inches='tight')
            #     plt.close()
            
            if (i == 0) & (k == 0):
                # fig1, axs1 = plt.subplots(3,3, figsize=(10,10))
                # axs1 = axs1.ravel()
                ax = axs1[ix]                
                ax.imshow(np.ma.masked_where(tempo==0, tempo), cmap = mpl.colors.ListedColormap(['dodgerblue']))
                ax.imshow(np.ma.masked_where(tempo==1, tempo), cmap = mpl.colors.ListedColormap(['darkorange']))
                ax.imshow(line, cmap=mpl.colors.ListedColormap('k'))
                ax.get_xaxis().set_visible(False)
                ax.get_yaxis().set_visible(False)
                ax.axis('off')
                plt.subplots_adjust(hspace = -0.6)
                perman = (tempo == 1).sum()
                intermit = (tempo == 0).sum()
                ratio =  intermit / perman
                if ratio == float("inf"):
                    ratio = '-'
                else:
                    ratio = round(ratio, 2)
                ax.text(0.042, 0.85,
                                  '$Intermit_{ratio}$ = ' +str((ratio)),
                                  horizontalalignment='left',
                                  verticalalignment='center', 
                                  transform=ax.transAxes,
                                  fontsize = 10)
            cp += 1

        inf+=12
        sup+=12
        
        # divider = make_axes_locatable(ax)
        # cax = divider.append_axes("right", size="1%", pad=0.05)
        # fig.add_axes(cax)
        # cbar = fig.colorbar(image_hidden, cax=cax, orientation="vertical")
        # val = np.ma.masked_where(mask < 0, mask)
        # minVal =  int(round(np.min(val[np.nonzero(val)],0)))
        # maxVal =  int(round(np.max(val[np.nonzero(val)],0)))
        # meanVal = int(round(minVal+((maxVal-minVal)/2),0))
        # cbar.set_ticks([minVal, meanVal, maxVal])
        # cbar.set_ticklabels([minVal, meanVal, maxVal])
        # cbar.mappable.set_clim(minVal, maxVal)
        # cbar.ax.tick_params(labelsize=10)
                
    # begin_by = simul+'/_figures/'+'intermittency_'
    # filenames = sorted(glob.glob(begin_by+'*.png'), key=os.path.getmtime)
    # images = []
    # for filename in filenames:
    #     images.append(imageio.imread(filename))
    # imageio.mimsave(begin_by+'intermittency_gif'+'.gif', images, duration=0.5, loop=1)

# figsim_folder = simulations_folder+'_draft/'
# if not os.path.exists(figsim_folder):
#     toolbox.create_folder(figsim_folder)
# fig1.savefig(figsim_folder+typ+'_intermittency_'+model_name+'.png', dpi=300, bbox_inches='tight')

#%% FIG b : PERSISTENCY MAP

figsim_folder = simulations_folder+'_draft/'
if not os.path.exists(figsim_folder):
    toolbox.create_folder(figsim_folder)

typ = 'projexplo'
var = 'REC'
scan = 'outflow_drain'
# sce_list = ['historic','RCP2.6','RCP8.5']
sce_list = ['historic']
sce_list = ['RCP8.5']
sce_cmap = ["Greys","Blues","Reds"]
sce_color = ["k","blue","red"]
sce_pos = ["1","2","3"]
cmap_dict = dict(zip(sce_list, sce_cmap))
color_dict = dict(zip(sce_list, sce_color))
pos_dict = dict(zip(sce_list, sce_pos))

temporal = True
space = -10
norm = False

watershed_name = 'Canut'
watershed_colors = ['k']
watshd_dict = dict(zip(watershed_names, watershed_colors))

simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots


fig1, axs1 = plt.subplots(1,3, figsize=(10,10))
axs1 = axs1.ravel()

for ix in np.arange(1,3+1,1):
    # simul_list = glob.glob(simulations_folder+'*'+typ+'_'+str(i)+'*')
    
    ax = axs1[ix-1]
        
    for sce in sce_list:
        # simul_list = glob.glob(simulations_folder+'*'+typ+'_'+str(i)+'*'+sce+'*')
        
        simul = glob.glob(simulations_folder+'*'+typ+'_'+str(ix)+'*'+sce+'*')[0]
        model_name = simul.split('\\')[-1]
        Sy = float(model_name.split('_')[3].split('-')[0]) # %
        K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
        E = float(model_name.split('_')[3].split('-')[2]) # m
        D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
        params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
        
        acc_npy = np.load(os.path.join(simul, '_watershed','accumulation_flux.npy'), allow_pickle=True).item()
        acc_npy = list(acc_npy.items())[-360:]
        # acc_npy = list(acc_npy.items())[360:720]
        
        for key in range(len(acc_npy)):
            # print(key)
            mask = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
            # acc = np.ma.masked_where(dem.read(1) < 0, dem.read(1))
            acc_npy[key] = np.ma.masked_array(acc_npy[key][1], mask=(mask<0))
        zero = acc_npy[0] * 0
        for i in range(len(acc_npy)):
            tempo = acc_npy[i].copy()
            tempo[tempo>0] = 1
            zero = zero + tempo
        days_flux = zero.copy() / len(acc_npy)
        
        ############ FIG 1
        # ax = ax1

        pc = ax.imshow(np.ma.masked_where(days_flux <= 0, days_flux),
                       cmap = 'rainbow_r', vmin=0, vmax=1, alpha=1)
        ax.get_xaxis().set_visible(False)
        ax.get_yaxis().set_visible(False)
        ax.axis('off')
        
        # if ix-1 == 5:
        #     divider = make_axes_locatable(ax)
        #     cax = divider.append_axes('right', size='2%', pad=0.1)
        #     cb = plt.colorbar(pc, cax=cax, orientation="vertical")
        #     cax.set_ylabel('Persistency index [-]', rotation=270, labelpad=40)

        wbt.vector_lines_to_raster(stable_folder+'geographic/'+'watershed_contour.shp',
                                   stable_folder+'geographic/'+'watershed_contour.tif',
                                   base = stable_folder+'geographic/'+'watershed_dem.tif')
        line = imageio.imread(stable_folder+'geographic/'+'watershed_contour.tif')
        line = np.ma.masked_where(line <= 0, line)
        import matplotlib as mpl
        ax.imshow(line, cmap=mpl.colors.ListedColormap('k'))
        # ax.set_title(params, fontsize=8)
        plt.subplots_adjust(hspace = -0.6)
        
position=fig1.add_axes([0.93,0.35,0.01,0.30])  ## the parameters are the specified position you set 
fig1.colorbar(pc,cax=position, orientation="vertical")
position.set_ylabel('Persistency index [-]', rotation=270, labelpad=40)

# fig1.savefig(figsim_folder+typ+'_persistency_'+model_name+'.png', dpi=300, bbox_inches='tight')

#%% FIG c : HYSTERESIS LOOP HISTO

figsim_folder = simulations_folder+'_draft/'
if not os.path.exists(figsim_folder):
    toolbox.create_folder(figsim_folder)

typ = 'conceptexplo'
var = 'REC'
scan = 'outflow_drain'
# sce_list = ['historic','RCP2.6','RCP8.5']
sce = 'historic'
sce_cmap = ["Greys","Blues","Reds"]
sce_color = ["k","blue","red"]
sce_pos = ["1","2","3"]
bxlim = (0.5,3.5)
# sce_list = ['historic','RCP2.6','RCP4.5','RCP8.5']
# sce_cmap = ["Greys","Blues","Greens","Reds"]
# sce_color = ["dimgray","blue","green","red"]
# sce_pos = ["1","2","3","4"]
# bxlim = (0.5,4.5)
cmap_dict = dict(zip(sce_list, sce_cmap))
color_dict = dict(zip(sce_list, sce_color))
pos_dict = dict(zip(sce_list, sce_pos))

temporal = False
space = 0
norm = False
    
Fig3 = False
if Fig3 == True:
    fig3, axs3 = plt.subplots(3,3, figsize=(9,9))
    axs3 = axs3.ravel()
    bmean = []
    bmin = []
    bmax = []
    
watershed_name = 'Canut'
watershed_colors = ['k']
watshd_dict = dict(zip(watershed_names, watershed_colors))

Fig1 = True
if Fig1 == True:
    fig1, axs1 = plt.subplots(3,3, figsize=(9,9))
    axs1 = axs1.ravel()
    
    xn = -0.1
    xx = 1.5
    yn = -0.1
    yx = 1.5

simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
color = watshd_dict[watershed_name]

compt = 0
simul_list = glob.glob(simulations_folder+typ+'*'+sce+'*')

for simul in simul_list:
        
    model_name = simul.split('\\')[-1]
    Sy = float(model_name.split('_')[3].split('-')[0]) # %
    K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
    E = float(model_name.split('_')[3].split('-')[2]) # m
    D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
    params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
    Smod_path = simul+'/_watershed/_simulated_results.csv'            
    if not os.path.exists(Smod_path):
        compt += 1
        continue
    Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
    Qmod = Smod[scan] 
    Qmod = Qmod * 1000 # mm/months
    Qmod = Qmod.squeeze()    
    Cmod = Smod['recharge'] * 1000 # mm/months
    DFmod = pd.DataFrame(columns=['x','y'])
    DFmod['x'] = Cmod
    DFmod['y'] = Qmod
    first_valid_loc = DFmod[DFmod.index.month==10].apply(lambda col: col.first_valid_index()).max().year
    last_valid_loc = DFmod[DFmod.index.month==9].apply(lambda col: col.last_valid_index()).min().year
    DFmod = select_period(DFmod, first_valid_loc, last_valid_loc)
    for idx in range(len(DFmod)):
        if DFmod.index[idx].month == 10:
            DFmod = DFmod[idx:]   
            break
    DFmod = DFmod.sort_index(ascending=False)
    for idx in range(len(DFmod)):
        if DFmod.index[idx].month == 9:
            DFmod = DFmod[idx:]
            break
    DFmod = DFmod.sort_index(ascending=True)
    
    hyst = Hysteresis(DFmod, simul)
    hyst.prepare_xy_raw()
    hyst.compute_xy_metrics(temporal=temporal, space=space, norm=norm)
    columns_x = hyst.xrecapl.columns
    columns_y = hyst.yrecapl.columns
    
    n = len(columns_x)
    cmap = cmap_dict[sce]
    cmap_color = plt.get_cmap(cmap)(np.linspace(0, 1, n))
    
    if len(watershed_names) == 1:
        color = color_dict[sce]
    
    dfevol = hyst.dfmet.iloc[:-1]
    dfevol = dfevol.set_index(pd.to_datetime(dfevol.index, format='%Y'))
    dfmean = hyst.dfmet.iloc[-1]
    
    polyg_loop = Polygon(tuple(hyst.data.itertuples(index=False, name=None)))
    xpolyg, ypolyg = polyg_loop.exterior.xy
    maxi = 1.5
    mini = -0.1
    line_oneone = SG.LineString([(mini,mini), (maxi,maxi)])
    areas = cut_polygon_by_line(polyg_loop, line_oneone)
    
    ################ FIG 1 ################
    
    ax = axs1[compt]
    ax.set_aspect('equal', adjustable='box')
    
    from descartes import PolygonPatch
    ring_patch = PolygonPatch(areas[0], color='skyblue', alpha=0.5, ec="k")
    ax.add_patch(ring_patch)
    ring_patch = PolygonPatch(areas[1], color='red', alpha=0.5, ec="k")
    ax.add_patch(ring_patch)
    # ax.fill(hyst.data.inx, hyst.data.iny)
    
    # ax.set_title(params, fontsize=8)
    # fig2.suptitle(metric.upper(), y=0.98)
    for i, (colx, coly) in enumerate(zip(columns_x, columns_y)):
        # print(colx)
        data = pd.DataFrame()
        data['inx'] = hyst.xrecapl[colx]
        data['iny'] = hyst.yrecapl[coly]
        # ax.plot(data.inx, data.iny, linestyle = '-', lw=0.5, color=cmap_color[i],
        #         alpha=0.75, zorder=0)
        
    ax.plot(data.inx, data.iny, linestyle = '-', lw=3, color=color, zorder=1)
    # ax.scatter(hyst.x, hyst.y, c=hyst.wy, cmap='gist_rainbow_r', marker="o", 
    #                   s=10, vmin=1, vmax=12, alpha=0.75, ec='none', zorder=0)
    
    # ax.plot(hyst.xi, hyst.yi, marker="o", markersize=9, markeredgecolor='black', 
    #         markerfacecolor='white', linestyle = 'None') 
    # for k in hyst.wyi:
    #     ax.annotate(k,(hyst.xi[k],hyst.yi[k]), family='sans-serif', fontsize=5, 
    #                 color='black', weight="bold", ha='center', va='center')      
    
    cp = 1
    cont = 0
    
    for k in hyst.wyi:
        
        ax.plot(hyst.xi[k], hyst.yi[k], marker="o", markersize=9,
                  markeredgecolor='k', markerfacecolor='white',
                  mew=1,
                  linestyle = 'None', zorder=cp+cont)
        
        ax.annotate(k,(hyst.xi[k],hyst.yi[k]),
                      family='sans-serif', fontsize=5, 
                      color='k', weight="bold", ha='center', va='center',
                      zorder=cp+cont)
        cont+=1
        cp+=1
            
    # plt.setp(axs2, xlim=(min(xmin),max(xmax)), ylim=(min(ymin),max(ymax)))
    ax.set_xlim(xn,xx)
    ax.set_ylim(yn,yx)
    ax.plot(np.linspace(xn,xx,50), np.linspace(yn,yx,50), 
            linestyle='--', color='grey', linewidth=1.5, zorder=-1)
    # ax.set_yscale('log')
    ax.xaxis.set_ticks(np.arange(0, xx+0.1, 0.5))
    ax.yaxis.set_ticks(np.arange(0, xx+0.1, 0.5))
    
    ax.errorbar(hyst.xi, hyst.yi,
                yerr=np.vstack([hyst.yi-hyst.ye.q25, hyst.ye.q75-hyst.yi]),
                xerr=np.vstack([hyst.xi-hyst.xe.q25, hyst.xe.q75-hyst.xi]),
                ecolor = 'black', fmt = 'none', capsize = 1, elinewidth=0.5, 
                capthick=0.5, zorder=1)

    dfmean = dfmean.round(2)
        
    ax.text(0.042, 0.78, 
                      '$Q_{0}$ = ' +str(dfmean['q0']) + '\n'
                      '$Q_{mid}$ = '+str(dfmean['qmid']) + '\n'
                      'HI = '+str(dfmean['hi']) + '\n'
                      '$Area_{ratio}$ = '+str(dfmean['area_r']) + '\n',
                      horizontalalignment='left',
                      verticalalignment='center', 
                      transform=ax.transAxes,
                      fontsize = 10)
    
    ax.text(0.53, 0.14,
                      'Slope = ' +str(dfmean['slope']) + '\n'
                      'Long = ' +str(dfmean['long']) + '\n'
                      'Short = ' +str(dfmean['short']) + '\n'
                      'Eccent. = ' +str(dfmean['excent']) + '\n',
                      horizontalalignment='left',
                      verticalalignment='center', 
                      transform=ax.transAxes,
                      fontsize = 10)

    ax.grid(color='grey',alpha=0.2)
    
    if (compt==0) | (compt==3) | (compt==6):
        ax.set_ylabel('Q [mm/month]')
    if (compt==6) | (compt==7) | (compt==8):
        ax.set_xlabel('R [mm/month]')
        
    plt.tight_layout()
        
    compt+=1
    
fig1.tight_layout()
fig1.savefig(figsim_folder+typ+'_hysteresis_'+model_name+'.png', dpi=300, bbox_inches='tight')

#%% FIG d : DISCHARGE INTERMITTENCY

figsim_folder = simulations_folder+'_draft/'
if not os.path.exists(figsim_folder):
    toolbox.create_folder(figsim_folder)

typ = 'conceptexplo'
var = 'REC'
scan = 'outflow_drain'
# sce_list = ['historic','RCP2.6','RCP8.5']
sce = 'historic'
sce_cmap = ["Greys","Blues","Reds"]
sce_color = ["k","blue","red"]
sce_pos = ["1","2","3"]
bxlim = (0.5,3.5)
# sce_list = ['historic','RCP2.6','RCP4.5','RCP8.5']
# sce_cmap = ["Greys","Blues","Greens","Reds"]
# sce_color = ["dimgray","blue","green","red"]
# sce_pos = ["1","2","3","4"]
# bxlim = (0.5,4.5)
cmap_dict = dict(zip(sce_list, sce_cmap))
color_dict = dict(zip(sce_list, sce_color))
pos_dict = dict(zip(sce_list, sce_pos))

temporal = False
space = 0
norm = False
    
Fig3 = False
if Fig3 == True:
    fig3, axs3 = plt.subplots(3,3, figsize=(9,9))
    axs3 = axs3.ravel()
    bmean = []
    bmin = []
    bmax = []
    
watershed_name = 'Canut'
watershed_colors = ['k']
watshd_dict = dict(zip(watershed_names, watershed_colors))

Fig1 = True
if Fig1 == True:
    fig1, axs1 = plt.subplots(3,3, figsize=(9,9))
    axs1 = axs1.ravel()
    
    xn = -0.1
    xx = 1.5
    yn = -0.1
    yx = 1.5

simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
color = watshd_dict[watershed_name]

compt = 0
simul_list = glob.glob(simulations_folder+typ+'*'+sce+'*')

for simul in simul_list:
        
    model_name = simul.split('\\')[-1]
    Sy = float(model_name.split('_')[3].split('-')[0]) # %
    K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
    E = float(model_name.split('_')[3].split('-')[2]) # m
    D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
    params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
    Smod_path = simul+'/_watershed/_simulated_results.csv'            
    if not os.path.exists(Smod_path):
        compt += 1
        continue
    Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
    Qmod = Smod[scan] 
    Qmod = Qmod * 1000 # mm/months
    Qmod = Qmod.squeeze()    
    Cmod = Smod['recharge'] * 1000 # mm/months
    DFmod = pd.DataFrame(columns=['x','y'])
    DFmod['x'] = Cmod
    DFmod['y'] = Qmod
    first_valid_loc = DFmod[DFmod.index.month==10].apply(lambda col: col.first_valid_index()).max().year
    last_valid_loc = DFmod[DFmod.index.month==9].apply(lambda col: col.last_valid_index()).min().year
    DFmod = select_period(DFmod, first_valid_loc, last_valid_loc)
    for idx in range(len(DFmod)):
        if DFmod.index[idx].month == 10:
            DFmod = DFmod[idx:]   
            break
    DFmod = DFmod.sort_index(ascending=False)
    for idx in range(len(DFmod)):
        if DFmod.index[idx].month == 9:
            DFmod = DFmod[idx:]
            break
    DFmod = DFmod.sort_index(ascending=True)
    
    ax = axs1[compt]
    # ax.set_aspect('equal', adjustable='box')
    ax.scatter(Qmod, Smod.seepage_areas, color='grey', ec='none',
               s=30, alpha=0.5)
    ax.scatter(Qmod, Smod.surflow_areas, color='k', ec='none',
               s=30, alpha=0.5)
    ax.scatter(Qmod, Smod.perenn_areas, color='dodgerblue', ec='none',
               s=30, alpha=0.5)
    ax.scatter(Qmod, Smod.intermit_areas, color='darkorange', ec='none',
               s=30, alpha=0.5)
    
    ax.set_xlim(-0.1,2)
    ax.set_ylim(-0.1,40)
    
    ax.grid(color='grey',alpha=0.2)
    
    if (compt==0) | (compt==3) | (compt==6):
        ax.set_ylabel('A [%]')
    if (compt==6) | (compt==7) | (compt==8):
        ax.set_xlabel('Q [mm/month]')
        
    plt.tight_layout()
        
    compt+=1
    
fig1.tight_layout()
fig1.savefig(figsim_folder+typ+'_qsat_relationship_'+model_name+'.png', dpi=300, bbox_inches='tight')

#%% FIG e : INTERMITTENCY MATRIX EVOL

figsim_folder = simulations_folder+'_draft/'
if not os.path.exists(figsim_folder):
    toolbox.create_folder(figsim_folder)

sce = 'RCP8.5'
typ = 'projexplo'
var = 'REC'
scan_list = ['surflow_areas','perenn_areas','intermit_areas']
scan_list = ['intermit_areas','perenn_areas']

scan_cmap = ["Greys","Blues","Oranges"]
scan_color = ["black","dodgerblue","darkorange"]
scan_pos = ["1","2","3"]
bxlim = (0.5,3.5)
cmap_dict = dict(zip(scan_list, scan_cmap))
color_dict = dict(zip(scan_list, scan_color))
pos_dict = dict(zip(scan_list, scan_pos))

temporal = True
space = 0
norm = False

metric = 'area_r'
            
print(sce)
compt = 0
simul_list = glob.glob(simulations_folder+typ+'*'+sce+'*')

list_max = []

for it, simul in enumerate(simul_list[:]):
        
    model_name = simul.split('\\')[-1]
    Sy = float(model_name.split('_')[3].split('-')[0]) # %
    K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
    E = float(model_name.split('_')[3].split('-')[2]) # m
    D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
    params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
    Smod_path = simul+'/_watershed/_simulated_results.csv'            
    if not os.path.exists(Smod_path):
        compt += 1
        continue
    
    Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
    idx = pd.date_range(start='01/01/2000', end='31/12/2099', freq='M')
    Smod = Smod.set_index(idx)
    years = Smod.index.year.unique()
    
    Smod['prop_perenn'] = Smod['perenn_areas'] / Smod['surflow_areas']
    Smod['prop_intermit'] = Smod['intermit_areas'] / Smod['surflow_areas']
    
    Smod['year'] = Smod.index.year.values # group by month and year, get the average
    Smod['month'] = Smod.index.month.values # group by month and year, get the average
    Smod = Smod.pivot('month','year')
    
    max_per = Smod['perenn_areas'].max().max()
    max_int = Smod['intermit_areas'].max().max()
    max_tot = max(max_per,max_int)

    list_max.append(max_tot)

fig, axs = plt.subplots(3,1, figsize=(8,10))
axs = axs.ravel()

for it, simul in enumerate(simul_list[:]):
    
    ax = axs[it]
    
    model_name = simul.split('\\')[-1]
    Sy = float(model_name.split('_')[3].split('-')[0]) # %
    K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
    E = float(model_name.split('_')[3].split('-')[2]) # m
    D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
    params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
    Smod_path = simul+'/_watershed/_simulated_results.csv'            
    if not os.path.exists(Smod_path):
        compt += 1
        continue
    
    Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
    idx = pd.date_range(start='01/01/2000', end='31/12/2099', freq='M')
    Smod = Smod.set_index(idx)
    years = Smod.index.year.unique()
    
    Smod['prop_perenn'] = Smod['perenn_areas'] / Smod['surflow_areas']
    Smod['prop_intermit'] = Smod['intermit_areas'] / Smod['surflow_areas']
    
    Smod['year'] = Smod.index.year.values # group by month and year, get the average
    Smod['month'] = Smod.index.month.values # group by month and year, get the average
    Smod = Smod.pivot('month','year')
    
    max_per = Smod['perenn_areas'].max().max()
    max_int = Smod['intermit_areas'].max().max()
    max_tot = max(list_max)    
    
    # from plotnine import *
    # ggplot(Smod, aes(x=Smod.year, fill = 'prop_intermit')) + geom_bar(stat='count')

    
    # from matplotlib import colors
    # import matplotlib.cm as cmx
    # cNorm  = colors.Normalize(vmin=0, vmax=Smod['perenn_areas'].max())
    # jet = cm = plt.get_cmap('Blues') 
    # scalarMap = cmx.ScalarMappable(norm=cNorm, cmap=jet)
    
    # fig, ax = plt.subplots(1,1, figsize=(50,7))
    # for i in range(len(Smod)):
    #     start = 0
    #     h = Smod.iloc[i]['prop_perenn']
    #     colorVal = scalarMap.to_rgba(idx)  
    #     ax.bar(x = Smod.index[i], height = h, bottom=start, width = 10, color=colorVal)
        
    #     # ax.set_xticks(np.arange(0, len(Smod)+1, 5.0))
    #     # ax.set_xticklabels(np.arange(min(years), max(years)+1, 5.0).astype(int))
    
    # ax.set_xlim(pd.to_datetime('2000'), pd.to_datetime('2002'))


    # fig, ax = plt.subplots(1,1, figsize=(8,5))
    from matplotlib import colors
    import matplotlib.cm as cmx
    
    for year in years[:]:
        p = Smod[['prop_perenn','perenn_areas']]
        i = Smod[['prop_intermit','intermit_areas']]
        
        print(year)
        
        p = p.droplevel(level=0, axis=1)
        p = p[year]
        p.columns = ['prop_perenn','perenn_areas']
        p = p.sort_values('prop_perenn', ascending=False)
        p['prop_perenn'] = p.prop_perenn.cumsum() / 12
            
        p1 = p.prop_perenn.shift(+1)
        p1.iloc[0] = 0
        x1 = p1.values
        x2 = p.prop_perenn.values
        values = p.perenn_areas.values
        jet = cm = plt.get_cmap('Blues')
        cNorm  = colors.Normalize(vmin=0, vmax=max_tot)
        scalarMap = cmx.ScalarMappable(norm=cNorm, cmap=jet)
        if year == 2000:
            # divider = make_axes_locatable(ax)
            # cax = divider.append_axes("right", size="2%", pad=0.5)
            # plt.colorbar(scalarMap, cax=cax)
            if it==1:
            #     cbar2 = plt.colorbar(scalarMap, shrink=0.5)
            #     cbar2.set_ticks([])
                position=fig.add_axes([1,0.3,0.02,0.35])  ## the parameters are the specified position you set 
                cb = fig.colorbar(scalarMap,cax=position) ##
                cb.set_label('Saturation [%]', rotation=270, labelpad=30)
            
        for idx, x, y in zip(values, x1, x2):          
            colorVal = scalarMap.to_rgba(idx)  
            start = x
            endp = y
            width = endp-start
            ax.bar(x = year, height=width, bottom=start, width=1,
                    label = str(idx), color=colorVal, lw=0)
            # print(x, y, width)
        
        i = i.droplevel(level=0, axis=1)
        i = i[year]
        i.columns = ['prop_intermit','intermit_areas']
        i = i.sort_values('prop_intermit', ascending=True)
        i['prop_intermit'] = i.prop_intermit.cumsum() / 12
        
        i1 = i.prop_intermit.shift(+1)
        i1.iloc[0] = 0
        i1 = i1 + endp
        x1 = i1.values
        x2 = i.prop_intermit.values + endp
        values = i.intermit_areas.values
        jet = cm = plt.get_cmap('Oranges') 
        cNorm  = colors.Normalize(vmin=0, vmax=max_tot)
        scalarMap = cmx.ScalarMappable(norm=cNorm, cmap=jet)
        if year == 2000:
            # divider = make_axes_locatable(ax)
            # cax = divider.append_axes("right", size="2%", pad=0.5)
            # plt.colorbar(scalarMap, cax=cax)
            if it==1:
            #     cbar2 = plt.colorbar(scalarMap, shrink=0.5)
            #     cbar2.set_ticks([])
                position=fig.add_axes([0.95,0.3,0.02,0.35])  ## the parameters are the specified position you set 
                cb = fig.colorbar(scalarMap,cax=position) ## 
                cb.set_ticks([])

        for idx, x, y in zip(values, x1, x2):          
            colorVal = scalarMap.to_rgba(idx)
            start = x
            endi = y
            width = endi-start
            ax.bar(x = year, height = width, bottom=start, width = 1,
                    label = str(idx), color=colorVal, lw=0)
            
        ax.set_xticks(np.arange(min(years), max(years)+2, 25.0))
        ax.set_xticklabels(np.arange(min(years), max(years)+2, 25.0).astype(int))
        ax.set_ylim(0,1)
        ax.set_ylabel('Proportion of network')
        if it == 2:
            ax.set_xlabel('Date')
        # ax.set_xlim(pd.to_datetime('2000'),pd.to_datetime('2099'))
        
        # norm = mpl.colors.Normalize(vmin=0,vmax=max_int)
        # cb1  = mpl.colorbar.ColorbarBase(ax,cmap='jet',norm=norm,orientation='vertical')
        
        bal = ((i.prop_intermit.sum()) + (p.prop_perenn.sum())).sum()
        # print(bal)
        
fig.savefig(figsim_folder+typ+'_matrixevol_'+model_name+'.png', dpi=300, bbox_inches='tight')

#%% FIG f : INTERMITTENCY ANO FUTUR

figsim_folder = simulations_folder+'_draft/'
if not os.path.exists(figsim_folder):
    toolbox.create_folder(figsim_folder)

typ = 'projexplo'
var = 'REC'
scan_list = ['surflow_areas','perenn_areas','intermit_areas']
scan_list = ['intermit_areas','perenn_areas']

sce_list = ['RCP2.6','RCP8.5']
sce_cmap = ["Blues","Reds"]
sce_color = ["forestgreen","red"]
sce_pos = ["1","2"]
bxlim = (0.5,3.5)
cmap_dict = dict(zip(sce_list, sce_cmap))
color_dict = dict(zip(sce_list, sce_color))
pos_dict = dict(zip(sce_list, sce_pos))

seasons = ['9,10,11',
           '12,1,2',
           '3,4,5',
           '6,7,8']
string = ['SON','DJF','MAM','JJA']
seas_dict = dict(zip(seasons, string))

# scan_cmap = ["Greys","Blues","Oranges"]
# scan_color = ["black","dodgerblue","darkorange"]
# scan_pos = ["1","2","3"]
# bxlim = (0.5,3.5)
# cmap_dict = dict(zip(scan_list, scan_cmap))
# color_dict = dict(zip(scan_list, scan_color))
# pos_dict = dict(zip(scan_list, scan_pos))

temporal = True
space = -10
norm = False

metric = 'area_r'
            
compt = 0
simul_list = glob.glob(simulations_folder+typ+'*'+sce+'*')

list_max = []

fig, axs = plt.subplots(3,1, figsize=(8,7))
axs = axs.ravel()

# for it, simul in enumerate(simul_list[:]):
for ix in np.arange(1,3+1,1):
    
    ax = axs[ix-1]
    
    for sce in sce_list:
        print(sce)

        simul = glob.glob(simulations_folder+typ+'_'+str(ix)+'*'+sce+'*')[0]
    
        color = color_dict[sce]
    
        model_name = simul.split('\\')[-1]
        Sy = float(model_name.split('_')[3].split('-')[0]) # %
        K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
        E = float(model_name.split('_')[3].split('-')[2]) # m
        D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
        params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
        Smod_path = simul+'/_watershed/_simulated_results.csv'            
        if not os.path.exists(Smod_path):
            compt += 1
            continue
        
        Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
        
        BV.forcing.update_recharge_surfex(clim_mod = mod, clim_sce = 'historic',
                                                 first_year = 2000, last_year = 2010,
                                                 time_step = time_step, sim_state=sim_state)
        Hist = BV.forcing.recharge
        BV.forcing.update_recharge_surfex(clim_mod = mod, clim_sce = sce,
                                          first_year = 2000, last_year = 2099, 
                                          time_step = time_step, sim_state=sim_state)
        BV.forcing.update_recharge(BV.forcing.recharge, sim_state=sim_state)
        Rech = BV.forcing.recharge # m/month
        if (sce == 'RCP2.6') | (sce == 'RCP8.5'):
            Rech = pd.concat((Rech, Hist), axis=1).mean(axis=1)
            BV.forcing.update_recharge(Rech, sim_state=sim_state)
            Rech = BV.forcing.recharge # m/month
            
        idx = pd.date_range(start='01/01/2000', end='31/12/2099', freq='M')
        Smod = Smod.set_index(idx)
        
        Smod.recharge = Rech
        
        idx = pd.date_range(start='01/01/2000', end='31/12/2099', freq='M')
        Smod = Smod.set_index(idx)
        years = Smod.index.year.unique()
        
        Smod['prop_perenn'] = Smod['perenn_areas'] / Smod['surflow_areas']
        Smod['prop_intermit'] = Smod['intermit_areas'] / Smod['surflow_areas']
        Smod['prop_ratio'] = Smod['prop_intermit'] / Smod['prop_perenn']
        
        Smod['year'] = Smod.index.year.values # group by month and year, get the average
        Smod['month'] = Smod.index.month.values # group by month and year, get the average
        # Smod = Smod.pivot('month','year')
        
        # ax.plot(Smod.surflow_areas)
        
        max_per = Smod['perenn_areas'].max().max()
        max_int = Smod['intermit_areas'].max().max()
        max_tot = max(max_per,max_int)
    
        intm = select_period(Smod, 2000,2021)
        intm = intm.groupby([lambda x: x.month]).mean()
        
        list_max.append(max_tot)
        
        for i in intm.month.values:
            Smod.loc[Smod.index.month==i, 'ano_prop_ratio'] = Smod.loc[Smod.index.month==i,'prop_ratio'] \
                                                              - intm.loc[intm.month==i,'prop_ratio'].values[0]
            Smod.loc[Smod.index.month==i, 'ano_intermit_areas'] = Smod.loc[Smod.index.month==i,'intermit_areas'] \
                                                              - intm.loc[intm.month==i,'intermit_areas'].values[0]
            Smod.loc[Smod.index.month==i, 'ano_perenn_areas'] = Smod.loc[Smod.index.month==i,'perenn_areas'] \
                                                              - intm.loc[intm.month==i,'perenn_areas'].values[0]
            Smod.loc[Smod.index.month==i, 'ano_surflow_areas'] = Smod.loc[Smod.index.month==i,'surflow_areas'] \
                                                              - intm.loc[intm.month==i,'surflow_areas'].values[0]
                                 
        # ax.plot(Smod.outflow_drain)
        
        col = 'ano_prop_ratio'
        ax.set_ylim(-5,10)
        if (ix-1) == 1:
            ax.set_ylabel('Anomaly compared to the history' )
        if (ix-1) == 2:
            ax.set_xlabel('Date')

        plus = Smod[col][Smod[col] >= 0]
        minus = Smod[col][Smod[col] < 0]
        # data_normalizer = mpl.colors.Normalize()
        # color_map1 = plt.cm.get_cmap('Blues')
        # color_map2 = plt.cm.get_cmap('Reds')
        # c1 = color_map1(data_normalizer(plus[col]))
        # ax.bar(plus.index, plus.ano_prop_ratio, lw=2, width=1, edgecolor=c1, color=c1)
        # c2 = color_map2(data_normalizer(abs(minus)))
        # ax.bar(minus.index, minus, lw=2, width=1, edgecolor=c2, color=c2)
        # ax.plot(plus, color = color)
        # ax.plot(minus, color = color)
        ax.plot(Smod[col], color=color)
        ax.axhline(y=0, c='k')
        ax.set_xlim(pd.to_datetime(str(2000)),pd.to_datetime(str(2100)))
        plt.xticks(rotation='horizontal')
        plt.xlabel('Date')
        # plt.ylabel('Deviation')
        # plt.title(var)
        # plt.hlines(y=0, xmin=pd.to_datetime(str(ref[0])), xmax=pd.to_datetime(str(ref[1])), lw=3, color='k')
        ax.axvspan(pd.to_datetime(str(2000)), pd.to_datetime(str(2021)), color='lightgrey', alpha=0.1,
                   zorder=0)
        # ax.axvline(x=pd.to_datetime(str(ref[0])), lw=1, c='grey', zorder=0)
        # ax.axvline(x=pd.to_datetime(str(ref[1])), lw=1, c='grey', zorder=0)
        years = mdates.YearLocator(20)   # every year
        yearsmin = mdates.YearLocator(1)
        # months = mdates.MonthLocator(6)  # every month
        years_fmt = mdates.DateFormatter('%Y')
        months_fmt = mdates.DateFormatter('%m') #b = name of month ?
        ax.xaxis.set_major_locator(years)
        ax.xaxis.set_minor_locator(yearsmin)
        # ax.xaxis.set_minor_locator(months)
        ax.xaxis.set_major_formatter(years_fmt)
        # ax.plot(Smod['prop_perenn'], color=color)

plt.tight_layout()
# fig.savefig(figsim_folder+typ+'_evol_'+col+'_'+model_name+'.png', dpi=300, bbox_inches='tight')

#%% FIG g : INTERMITTENCY SEASON EVOLUTION

figsim_folder = simulations_folder+'_draft/'
if not os.path.exists(figsim_folder):
    toolbox.create_folder(figsim_folder)

typ = 'projexplo'
var = 'REC'
scan_list = ['surflow_areas','perenn_areas','intermit_areas']
scan_list = ['intermit_areas','perenn_areas']

sce_list = ['RCP2.6','RCP8.5']
sce_cmap = ["Blues","Reds"]
sce_color = ["forestgreen","red"]
sce_pos = ["1","2"]
bxlim = (0.5,3.5)
cmap_dict = dict(zip(sce_list, sce_cmap))
color_dict = dict(zip(sce_list, sce_color))
pos_dict = dict(zip(sce_list, sce_pos))

seasons = ['9,10,11',
           '12,1,2',
           '3,4,5',
           '6,7,8']
string = ['SON','DJF','MAM','JJA']
seas_dict = dict(zip(seasons, string))

# scan_cmap = ["Greys","Blues","Oranges"]
# scan_color = ["black","dodgerblue","darkorange"]
# scan_pos = ["1","2","3"]
# bxlim = (0.5,3.5)
# cmap_dict = dict(zip(scan_list, scan_cmap))
# color_dict = dict(zip(scan_list, scan_color))
# pos_dict = dict(zip(scan_list, scan_pos))

temporal = True
space = 10
norm = False

metric = 'area_r'
            
compt = 0
simul_list = glob.glob(simulations_folder+typ+'*'+sce+'*')

list_max = []

# for it, simul in enumerate(simul_list[:]):
for ix in np.arange(1,3+1,1):
    
    colb = 'surflow_areas'
    fig, axs = plt.subplots(4,1, figsize=(5,7))
    axs = axs.ravel()
    
    for it, sea in enumerate(seasons):
    
        ax = axs[it-1]
        
        for sce in sce_list:
            print(sce)
    
            simul = glob.glob(simulations_folder+typ+'_'+str(ix)+'*'+sce+'*')[0]
        
            color = color_dict[sce]
        
            model_name = simul.split('\\')[-1]
            Sy = float(model_name.split('_')[3].split('-')[0]) # %
            K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
            E = float(model_name.split('_')[3].split('-')[2]) # m
            D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
            params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
            Smod_path = simul+'/_watershed/_simulated_results.csv'            
            if not os.path.exists(Smod_path):
                compt += 1
                continue
            
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            
            BV.forcing.update_recharge_surfex(clim_mod = mod, clim_sce = 'historic',
                                                     first_year = 2000, last_year = 2010,
                                                     time_step = time_step, sim_state=sim_state)
            Hist = BV.forcing.recharge
            BV.forcing.update_recharge_surfex(clim_mod = mod, clim_sce = sce,
                                              first_year = 2000, last_year = 2099, 
                                              time_step = time_step, sim_state=sim_state)
            BV.forcing.update_recharge(BV.forcing.recharge, sim_state=sim_state)
            Rech = BV.forcing.recharge # m/month
            if (sce == 'RCP2.6') | (sce == 'RCP8.5'):
                Rech = pd.concat((Rech, Hist), axis=1).mean(axis=1)
                BV.forcing.update_recharge(Rech, sim_state=sim_state)
                Rech = BV.forcing.recharge # m/month
                
            idx = pd.date_range(start='01/01/2000', end='31/12/2099', freq='M')
            Smod = Smod.set_index(idx)
            
            Smod.recharge = Rech
            
            idx = pd.date_range(start='01/01/2000', end='31/12/2099', freq='M')
            Smod = Smod.set_index(idx)
            years = Smod.index.year.unique()
            
            Smod['prop_perenn'] = Smod['perenn_areas'] / Smod['surflow_areas']
            Smod['prop_intermit'] = Smod['intermit_areas'] / Smod['surflow_areas']
            Smod['prop_ratio'] = Smod['prop_intermit'] / Smod['prop_perenn']
            
            Smod['year'] = Smod.index.year.values # group by month and year, get the average
            Smod['month'] = Smod.index.month.values # group by month and year, get the average
            # Smod = Smod.pivot('month','year')
            
            # ax.plot(Smod.surflow_areas)
            
            max_per = Smod['perenn_areas'].max().max()
            max_int = Smod['intermit_areas'].max().max()
            max_tot = max(max_per,max_int)
        
            intm = select_period(Smod, 2000,2021)
            intm = intm.groupby([lambda x: x.month]).mean()
            
            list_max.append(max_tot)
            
            for i in intm.month.values:
                Smod.loc[Smod.index.month==i, 'ano_prop_ratio'] = Smod.loc[Smod.index.month==i,'prop_ratio'] \
                                                                  - intm.loc[intm.month==i,'prop_ratio'].values[0]
                Smod.loc[Smod.index.month==i, 'ano_intermit_areas'] = Smod.loc[Smod.index.month==i,'intermit_areas'] \
                                                                  - intm.loc[intm.month==i,'intermit_areas'].values[0]
                Smod.loc[Smod.index.month==i, 'ano_perenn_areas'] = Smod.loc[Smod.index.month==i,'perenn_areas'] \
                                                                  - intm.loc[intm.month==i,'perenn_areas'].values[0]
                Smod.loc[Smod.index.month==i, 'ano_surflow_areas'] = Smod.loc[Smod.index.month==i,'surflow_areas'] \
                                                                  - intm.loc[intm.month==i,'surflow_areas'].values[0]
    
            nam = seas_dict[sea]
            ax.set_title(nam)
            
            dfb = Smod[colb].copy().to_frame()
            dfb = dfb.groupby([(dfb.index.year),(dfb.index.month)]).mean()
            dfb = dfb.rename_axis(["year", "month"])
            
            dfb = dfb.query("month == "+"["+sea+"]")
            dfb = dfb.dropna()
            dfb = dfb.groupby('year').sum()
            dfb.index = pd.to_datetime(dfb.index, format='%Y')
            
            # dfs = pd.DataFrame(index=dfb.index)
            # # ax.plot(dfb, lw=0.1, color=color_dict[sce])
            # dfs['MEAN'] = dfb.mean(axis=1)
            # dfs['MIN'] = dfb.min(axis=1)
            # dfs['MAX'] = dfb.max(axis=1)
            # dfs['Q25'] = dfb.quantile(q=0.25, axis=1)
            # dfs['Q50'] = dfb.quantile(q=0.50, axis=1)
            # dfs['Q75'] = dfb.quantile(q=0.75, axis=1)
            # dfs['STD'] = dfb.std(axis=1)
            # dfs = dfs.iloc[1:-1]
            # dfs = dfs.rolling(window=space).mean().shift(-space)
            
            dfb = dfb.rolling(window=space).mean().shift(space)
            
            # ax.plot(rea, ls='-', color='k', lw=0.25)
            # ax.fill_between(dfb.index, dfb.max(), dfb.min(), color=color_dict[sce],
            #                 alpha=0.2, edgecolor='none')
            # ax.plot(dfs['Q50'], lw=1, color=color_dict[sce], label=sce)
            # ax.fill_between(dfs.index, dfs.MEAN-dfs['STD'], dfs.MEAN+dfs['STD'], color=color_dict[sce], alpha=0.2, edgecolor='none')
            ax.plot(dfb[colb], lw=2, color=color_dict[sce])
            ax.set_xlim(pd.to_datetime('2000'), pd.to_datetime('2100'))
            ax.grid('grey')
            # ax.set_ylim(0,30)
            years = mdates.YearLocator(20)   # every year
            yearsmin = mdates.YearLocator(1)
            # months = mdates.MonthLocator(6)  # every month
            years_fmt = mdates.DateFormatter('%Y')
            months_fmt = mdates.DateFormatter('%m') #b = name of month ?
            ax.xaxis.set_major_locator(years)
            ax.xaxis.set_minor_locator(yearsmin)
            # ax.xaxis.set_minor_locator(months)
            ax.xaxis.set_major_formatter(years_fmt)
            # ax.plot(Smod['prop_perenn'], color=color)
            
    plt.tight_layout()
            
    fig.savefig(figsim_folder+typ+'_season_'+sea+'_'+colb+'_'+model_name+'.png', dpi=300, bbox_inches='tight')

#%% FIG h : HYSTERESIS LOOP FUTUR

figsim_folder = simulations_folder+'_draft/'
if not os.path.exists(figsim_folder):
    toolbox.create_folder(figsim_folder)

typ = 'projexplo'
var = 'REC'
scan = 'outflow_drain'
sce_list = ['RCP2.6','RCP8.5']
# sce_list = ['historic']
sce_cmap = ["Blues","Reds"]
sce_color = ["forestgreen","red"]
sce_pos = ["1","2"]
bxlim = (0.5,3.5)
# sce_list = ['historic','RCP2.6','RCP4.5','RCP8.5']
# sce_cmap = ["Greys","Blues","Greens","Reds"]
# sce_color = ["dimgray","blue","green","red"]
# sce_pos = ["1","2","3","4"]
# bxlim = (0.5,4.5)
cmap_dict = dict(zip(sce_list, sce_cmap))
color_dict = dict(zip(sce_list, sce_color))
pos_dict = dict(zip(sce_list, sce_pos))

temporal = False
space = 0
norm = False
    
watershed_names = ['Le Canut', 'Le Leff', 'L Élorn']
watershed_colors = ['darkgreen','darkorange','darkmagenta']
watshd_dict = dict(zip(watershed_names, watershed_colors))

watershed_names = ['Canut']
watershed_colors = ['k']
watshd_dict = dict(zip(watershed_names, watershed_colors))

compt = 1

Fig1 = True
if Fig1 == True:
    fig1, axs1 = plt.subplots(1,3, figsize=(10,3))
    axs1 = axs1.ravel()
    
    xn = -0.1
    xx = 2.5
    yn = -0.1
    yx = 2.5

cp = 0

simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
color = watshd_dict[watershed_name]
    
f = 2022
l = 2050

for ix in np.arange(1,3+1,1):
    # simul_list = glob.glob(simulations_folder+'*'+typ+'_'+str(i)+'*')
    
    ax = axs1[ix-1]
    ax.set_aspect('equal', adjustable='box')
    log = False
    if log == True:
        ax.set_xscale('log')
        ax.set_yscale('log')
        xn = 0.001
        xx = 10
        yn = 0.001
        yx = 10
    
    csce = 20
    for sce in sce_list:
        # simul_list = glob.glob(simulations_folder+'*'+typ+'_'+str(i)+'*'+sce+'*')
        simul = glob.glob(simulations_folder+'*'+typ+'_'+str(ix)+'*'+sce+'*')[0]
        
        print(sce)

        model_name = simul.split('\\')[-1]
        Sy = float(model_name.split('_')[3].split('-')[0]) # %
        K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
        E = float(model_name.split('_')[3].split('-')[2]) # m
        D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
        params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
        Smod_path = simul+'/_watershed/_simulated_results.csv'            
        if not os.path.exists(Smod_path):
            compt += 1
            continue
        Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
        
        BV.forcing.update_recharge_surfex(clim_mod = mod, clim_sce = 'historic',
                                                 first_year = 2000, last_year = 2010,
                                                 time_step = time_step, sim_state=sim_state)
        Hist = BV.forcing.recharge
        BV.forcing.update_recharge_surfex(clim_mod = mod, clim_sce = sce,
                                          first_year = 2000, last_year = 2099, 
                                          time_step = time_step, sim_state=sim_state)
        BV.forcing.update_recharge(BV.forcing.recharge, sim_state=sim_state)
        Rech = BV.forcing.recharge # m/month
        if (sce == 'RCP2.6') | (sce == 'RCP8.5'):
            Rech = pd.concat((Rech, Hist), axis=1).mean(axis=1)
            BV.forcing.update_recharge(Rech, sim_state=sim_state)
            Rech = BV.forcing.recharge # m/month
            
        idx = pd.date_range(start='01/01/2000', end='31/12/2099', freq='M')
        Smod = Smod.set_index(idx)
        Smod = select_period(Smod, f, l)
        
        Smod.recharge = Rech
        
        Qmod = Smod[scan] 
        Qmod = Qmod * 1000 # mm/months
        # ax.plot((Smod.intermit_areas) / (Smod.perenn_areas/Smod.surflow_areas))
        # ax.set_yscale('log')
        
        Qmod = Qmod.squeeze()    
        Cmod = Smod['recharge'] * 1000 # mm/months
        DFmod = pd.DataFrame(columns=['x','y'])
        DFmod['x'] = Cmod
        DFmod['y'] = Qmod
        first_valid_loc = DFmod[DFmod.index.month==10].apply(lambda col: col.first_valid_index()).max().year
        last_valid_loc = DFmod[DFmod.index.month==9].apply(lambda col: col.last_valid_index()).min().year
        DFmod = select_period(DFmod, first_valid_loc, last_valid_loc)
        for idx in range(len(DFmod)):
            if DFmod.index[idx].month == 10:
                DFmod = DFmod[idx:]   
                break
        DFmod = DFmod.sort_index(ascending=False)
        for idx in range(len(DFmod)):
            if DFmod.index[idx].month == 9:
                DFmod = DFmod[idx:]
                break
        DFmod = DFmod.sort_index(ascending=True)
        
        hyst = Hysteresis(DFmod, simul)
        hyst.prepare_xy_raw()
        hyst.compute_xy_metrics(temporal=temporal, space=space, norm=norm)
        columns_x = hyst.xrecapl.columns
        columns_y = hyst.yrecapl.columns
        
        n = len(columns_x)
        cmap = cmap_dict[sce]
        cmap_color = plt.get_cmap(cmap)(np.linspace(0, 1, n))
        
        if len(watershed_names) == 1:
            color = color_dict[sce]
        
        dfevol = hyst.dfmet.iloc[:-1]
        dfevol = dfevol.set_index(pd.to_datetime(dfevol.index, format='%Y'))
        dfmean = hyst.dfmet.iloc[-1]
        
        ################ FIG 1 ################
                              
        # ax.set_title(params, fontsize=8)
        # fig2.suptitle(metric.upper(), y=0.98)
        for i, (colx, coly) in enumerate(zip(columns_x, columns_y)):
            # print(colx)
            data = pd.DataFrame()
            data['inx'] = hyst.xrecapl[colx]
            data['iny'] = hyst.yrecapl[coly]
            # ax.plot(data.inx, data.iny, linestyle = '-', lw=0.5, color=cmap_color[i],
            #         alpha=0.75, zorder=0)
        ax.plot(data.inx, data.iny, linestyle = '-', lw=3, color=color, zorder=1)
        # ax.scatter(hyst.x, hyst.y, c=hyst.wy, cmap='gist_rainbow_r', marker="o", 
        #                   s=10, vmin=1, vmax=12, alpha=0.75, ec='none', zorder=0)
        
        # ax.plot(hyst.xi, hyst.yi, marker="o", markersize=9, markeredgecolor='black', 
        #         markerfacecolor='white', linestyle = 'None') 
        # for k in hyst.wyi:
        #     ax.annotate(k,(hyst.xi[k],hyst.yi[k]), family='sans-serif', fontsize=5, 
        #                 color='black', weight="bold", ha='center', va='center')      
        
        cp = 1
        cont = 0
        
        for k in hyst.wyi:
            
            ax.plot(hyst.xi[k], hyst.yi[k], marker="o", markersize=9,
                      markeredgecolor=color, markerfacecolor='white',
                      mew=1,
                      linestyle = 'None', zorder=csce+cp+cont)
            
            ax.annotate(k,(hyst.xi[k],hyst.yi[k]),
                          family='sans-serif', fontsize=5, 
                          color=color, weight="bold", ha='center', va='center',
                          zorder=csce+cp+cont)
            cont+=1
            cp+=1
        
        csce += 1
                
        # plt.setp(axs2, xlim=(min(xmin),max(xmax)), ylim=(min(ymin),max(ymax)))
        ax.set_xlim(xn,xx)
        ax.set_ylim(yn,yx)
        ax.plot(np.linspace(xn,xx,50), np.linspace(yn,yx,50), 
                linestyle='--', color='grey', linewidth=1.5, zorder=-1)
        # ax.set_yscale('log')
        # ax.xaxis.set_ticks(np.arange(xn, xx+1, 25))
        # ax.yaxis.set_ticks(np.arange(yn, xx+1, 25))
        
        # ax.errorbar(hyst.xi, hyst.yi,
        #             yerr=np.vstack([hyst.yi-hyst.ye.q25, hyst.ye.q75-hyst.yi]),
        #             xerr=np.vstack([hyst.xi-hyst.xe.q25, hyst.xe.q75-hyst.xi]),
        #             ecolor = 'black', fmt = 'none', capsize = 1, elinewidth=0.5, 
        #             capthick=0.5, zorder=1)

        dfmean = dfmean.round(2)
        
        # if (watershed_name == 'Le Canut') | (watershed_name == 'Cheze'):
        
        #     ax.text(0.042, 0.81, 
        #                      'Q0 = ' +str(dfmean['q0']) + '\n'
        #                      'Qmid = '+str(dfmean['qmid']) + '\n'
        #                      'HI = '+str(dfmean['hi']) + '\n'
        #                      'Area R = '+str(dfmean['area_r']) + '\n',
        #                      horizontalalignment='left',
        #                      verticalalignment='center', 
        #                      transform=ax.transAxes,
        #                      fontsize = 10)
            
        #     ax.text(0.58, 0.14,
        #                      'Slope = ' +str(dfmean['slope']) + '\n'
        #                      'Long = ' +str(dfmean['long']) + '\n'
        #                      'Short = ' +str(dfmean['short']) + '\n'
        #                      'Eccent. = ' +str(dfmean['excent']) + '\n',
        #                      horizontalalignment='left',
        #                      verticalalignment='center', 
        #                      transform=ax.transAxes,
        #                      fontsize = 10)

        ax.grid(color='grey',alpha=0.2)
        
        if (ix-1) == 0:
            ax.set_ylabel('Q [mm/month]')
        if (ix-1) == 1:
            ax.set_xlabel('R [mm/month]')
        
        plt.tight_layout()
                    
fig1.savefig(figsim_folder+typ+'_hysteresis_loop_'+model_name+'.png', dpi=300, bbox_inches='tight')

#%% FIG i : HYSTERESIS EVOL FUTUR

figsim_folder = simulations_folder+'_draft/'
if not os.path.exists(figsim_folder):
    toolbox.create_folder(figsim_folder)

typ = 'projexplo'
var = 'REC'
scan = 'outflow_drain'
sce_list = ['RCP2.6','RCP8.5']
# sce_list = ['historic']
sce_cmap = ["Blues","Reds"]
sce_color = ["forestgreen","red"]
sce_pos = ["1","2"]
bxlim = (0.5,3.5)
# sce_list = ['historic','RCP2.6','RCP4.5','RCP8.5']
# sce_cmap = ["Greys","Blues","Greens","Reds"]
# sce_color = ["dimgray","blue","green","red"]
# sce_pos = ["1","2","3","4"]
# bxlim = (0.5,4.5)
cmap_dict = dict(zip(sce_list, sce_cmap))
color_dict = dict(zip(sce_list, sce_color))
pos_dict = dict(zip(sce_list, sce_pos))

temporal = True
space = -5
norm = False

watershed_names = ['Canut']
watershed_colors = ['k']
watshd_dict = dict(zip(watershed_names, watershed_colors))

Fig2 = True
if Fig2 == True:
    fig2, axs2 = plt.subplots(1,3, figsize=(10,3))
    xmin = []
    xmax = []
    ymin = []
    ymax = []
            
compt = 1

f = 2022
l = 2050

metric = 'excent'

for watershed_name in watershed_names:
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = watshd_dict[watershed_name]
        
    for ix in np.arange(1,3+1,1):
        # simul_list = glob.glob(simulations_folder+'*'+typ+'_'+str(i)+'*')
        
        ax = axs2[ix-1]
        
        csce = 20
        for sce in sce_list:
            # simul_list = glob.glob(simulations_folder+'*'+typ+'_'+str(i)+'*'+sce+'*')
            simul = glob.glob(simulations_folder+typ+'_'+str(ix)+'*'+sce+'*')[0]
            print(simul)
            
            print(sce)

            model_name = simul.split('\\')[-1]
            Sy = float(model_name.split('_')[3].split('-')[0]) # %
            K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
            E = float(model_name.split('_')[3].split('-')[2]) # m
            D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
            params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
            Smod_path = simul+'/_watershed/_simulated_results.csv'            
            if not os.path.exists(Smod_path):
                compt += 1
                continue
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            
            BV.forcing.update_recharge_surfex(clim_mod = mod, clim_sce = 'historic',
                                                     first_year = 2000, last_year = 2010,
                                                     time_step = time_step, sim_state=sim_state)
            Hist = BV.forcing.recharge
            BV.forcing.update_recharge_surfex(clim_mod = mod, clim_sce = sce,
                                              first_year = 2000, last_year = 2099, 
                                              time_step = time_step, sim_state=sim_state)
            BV.forcing.update_recharge(BV.forcing.recharge, sim_state=sim_state)
            Rech = BV.forcing.recharge # m/month
            if (sce == 'RCP2.6') | (sce == 'RCP8.5'):
                Rech = pd.concat((Rech, Hist), axis=1).mean(axis=1)
                BV.forcing.update_recharge(Rech, sim_state=sim_state)
                Rech = BV.forcing.recharge # m/month
                
            idx = pd.date_range(start='01/01/2000', end='31/12/2099', freq='M')
            Smod = Smod.set_index(idx)
            Smod = select_period(Smod, f, l)
            
            Smod.recharge = Rech
            
            Qmod = Smod[scan] 
            Qmod = Qmod * 1000 # mm/months
            Qmod = Qmod.squeeze()    
            Cmod = Smod['recharge'] * 1000 # mm/months
            DFmod = pd.DataFrame(columns=['x','y'])
            DFmod['x'] = Cmod
            DFmod['y'] = Qmod
            first_valid_loc = DFmod[DFmod.index.month==10].apply(lambda col: col.first_valid_index()).max().year
            last_valid_loc = DFmod[DFmod.index.month==9].apply(lambda col: col.last_valid_index()).min().year
            DFmod = select_period(DFmod, first_valid_loc, last_valid_loc)
            for idx in range(len(DFmod)):
                if DFmod.index[idx].month == 10:
                    DFmod = DFmod[idx:]   
                    break
            DFmod = DFmod.sort_index(ascending=False)
            for idx in range(len(DFmod)):
                if DFmod.index[idx].month == 9:
                    DFmod = DFmod[idx:]
                    break
            DFmod = DFmod.sort_index(ascending=True)
            
            hyst = Hysteresis(DFmod, simul)
            hyst.prepare_xy_raw()
            hyst.compute_xy_metrics(temporal=temporal, space=space, norm=norm)
            columns_x = hyst.xrecapl.columns
            columns_y = hyst.yrecapl.columns
            
            n = len(columns_x)
            cmap = cmap_dict[sce]
            cmap_color = plt.get_cmap(cmap)(np.linspace(0, 1, n))
            
            if len(watershed_names) == 1:
                color = color_dict[sce]
            
            dfevol = hyst.dfmet.iloc[:-1]
            dfevol = dfevol.set_index(pd.to_datetime(dfevol.index, format='%Y'))
            dfmean = hyst.dfmet.iloc[-1]
                
            ################ FIG 2 ################
                           
            # ax = axs2
            # ax.set_title(params, fontsize=8)
            # fig2.suptitle(metric.upper(), y=0.98)
            # ax.plot(dfevol[metric], dfevol.index, linestyle = '-', lw=2, color=color,
            #         zorder=1)
            ax.plot(dfevol.index, dfevol[metric], linestyle = '-', lw=3, color=color,
                    zorder=1)
            # metric = 'excent'
            # ax.plot(dfevol[metric], dfevol.index, linestyle = '-', lw=2, color=color,
            #         zorder=1)
            # metric1 = 'slope'
            # metric2 = 'slope_abs'
            # ax.plot(dfevol[metric1]/dfevol[metric2], dfevol.index, linestyle = '-', lw=2, color='pink',
            #         zorder=1)
            
            # ax.set_xscale('log') 
            ax.axhline(1, linestyle = '--', lw=2, color='grey', zorder=0)
            # ax.set_xlim(-10,100)
            # ax.set_ylim(0.01,100)
            years_maj = YearLocator(10)   # every x year
            # years_min = YearLocator(1)
            years_maj_fmt = DateFormatter('%Y')
            # months_maj = MonthLocator(6)  # every x month
            # months_min = MonthLocator(3)
            # months_maj_fmt = DateFormatter('%m') #b = name of month ?
            ax.xaxis.set_major_locator(years_maj)
            # ax.xaxis.set_minor_locator(years_min)
            ax.xaxis.set_major_formatter(years_maj_fmt)
            # ax.set_ylim(0,40)
            ymin.append(dfevol.index.year.min())
            ymax.append(dfevol.index.year.max())
            xmin.append(dfevol[metric].min())
            xmax.append(dfevol[metric].max())
            ax.set_xlim(pd.to_datetime(str(f-2)),pd.to_datetime(str(l)))
            # ax.set_ylim(0.5,4)
            ax.set_ylim(0,25)
            plt.tight_layout()
            # ax.set_yticks(np.arange(1,4+1,1))
            # ax.set_yticklabels(np.arange(1,4+1,1))
            ax.set_yticks(np.arange(5,25+1,5))
            ax.set_yticklabels(np.arange(5,25+1,5))
            # ax.invert_yaxis()
            ax.grid('grey')
            
            if (ix-1) == 0:
                # ax.set_ylabel('$Area_{ratio}$ [-]')
                ax.set_ylabel('$Eccent_{ratio}$ [-]')
            if (ix-1) == 1:
                ax.set_xlabel('Date')

# fig2.savefig(figsim_folder+typ+'_arearatio_'+model_name+'.png', dpi=300, bbox_inches='tight')
# fig2.savefig(figsim_folder+typ+'_eccentratio_'+model_name+'.png', dpi=300, bbox_inches='tight')

FIG

#%% FIG ap1 : INTERMITTENCY BAR

figsim_folder = simulations_folder+'_draft/'
if not os.path.exists(figsim_folder):
    toolbox.create_folder(figsim_folder)

sce = 'historic'
typ = 'conceptexplo'

sce = 'RCP8.5'
typ = 'projexplo'

var = 'REC'
scan_list = ['surflow_areas','perenn_areas','intermit_areas']
scan_list = ['intermit_areas','perenn_areas']

scan_cmap = ["Greys","Blues","Oranges"]
scan_color = ["black","dodgerblue","darkorange"]
scan_pos = ["1","2","3"]
bxlim = (0.5,3.5)
cmap_dict = dict(zip(scan_list, scan_cmap))
color_dict = dict(zip(scan_list, scan_color))
pos_dict = dict(zip(scan_list, scan_pos))

temporal = True
space = 0
norm = False

metric = 'area_r'
            
print(sce)
compt = 0
simul_list = glob.glob(simulations_folder+typ+'*'+sce+'*')

for simul in simul_list[:]:
    
    model_name = simul.split('\\')[-1]
    Sy = float(model_name.split('_')[3].split('-')[0]) # %
    K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
    E = float(model_name.split('_')[3].split('-')[2]) # m
    D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
    params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
    Smod_path = simul+'/_watershed/_simulated_results.csv'            
    if not os.path.exists(Smod_path):
        compt += 1
        continue
    Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)

    Fig1 = True
    if Fig1 == True:
        fig1, axs1 = plt.subplots(1,1, figsize=(2.5,5))
    
    for scan in scan_list:
        Qmod = Smod[scan] # %
        Qmod = Qmod.squeeze()    
        Cmod = Smod['recharge'] * 1000 # mm/months
        DFmod = pd.DataFrame(columns=['x','y'])
        DFmod['x'] = Cmod
        DFmod['y'] = Qmod
        first_valid_loc = DFmod[DFmod.index.month==10].apply(lambda col: col.first_valid_index()).max().year
        last_valid_loc = DFmod[DFmod.index.month==9].apply(lambda col: col.last_valid_index()).min().year
        DFmod = select_period(DFmod, first_valid_loc, last_valid_loc)
        for idx in range(len(DFmod)):
            if DFmod.index[idx].month == 10:
                DFmod = DFmod[idx:]   
                break
        DFmod = DFmod.sort_index(ascending=False)
        for idx in range(len(DFmod)):
            if DFmod.index[idx].month == 9:
                DFmod = DFmod[idx:]
                break
        DFmod = DFmod.sort_index(ascending=True)
        
        hyst = Hysteresis(DFmod, simul)
        hyst.prepare_xy_raw()

        hyst.compute_xy_metrics(temporal=temporal, space=space, norm=norm)

        columns_x = hyst.xrecapl.columns
        columns_y = hyst.yrecapl.columns

        n = len(columns_x)
        cmap = cmap_dict[scan]
        cmap_color = plt.get_cmap(cmap)(np.linspace(0, 1, n))
        color = color_dict[scan]
        
        dfevol = hyst.dfmet.iloc[:-1]
        dfevol = dfevol.set_index(pd.to_datetime(dfevol.index, format='%Y'))
        dfmean = hyst.dfmet.iloc[-1]
        
        ################ FIG 1 ################
        
        if Fig1 == True:
            ax = axs1
            # ax.set_title(params, fontsize=8)
            # for i, (colx, coly) in enumerate(zip(columns_x, columns_y)):
            #     # print(colx)
            #     data = pd.DataFrame()
            #     data['inx'] = hyst.xrecapl[colx]
            #     data['iny'] = hyst.yrecapl[coly]
            #     ax.plot(data.inx, data.iny, linestyle = '-', lw=0.5, color=cmap_color[i],
            #             alpha=0.5, zorder=0)    
            
            mean = hyst.y.groupby([lambda x: x.month]).mean()
            q25 = hyst.y.groupby([lambda x: x.month]).quantile(0.25)
            q75 = hyst.y.groupby([lambda x: x.month]).quantile(0.75)
            
            if scan == 'intermit_areas':
                color = "darkorange"
                axs1.barh(hyst.y.index, hyst.y, color=color, linewidth=0, height=20)
                intermit = hyst.y.copy()
                
            if scan == 'perenn_areas':
                color = "dodgerblue"
                axs1.barh(hyst.y.index, hyst.y, color=color, left=intermit, linewidth=0, height=20)
                perman = hyst.y.copy()
                
            # axs1.plot(mean, color=color)
            # axs1.fill_between(mean.index, q25, q75, alpha=0.2, color=color, linewidth=0)
            
            # ax.plot(data.inx, data.iny, linestyle = '-', lw=2, color=color, zorder=2)
            # plt.setp(axs2, xlim=(min(xmin),max(xmax)), ylim=(min(ymin),max(ymax)))
            ax.set_xlim(0.1,100)
            # ax.set_xlim(1,12)
            ax.set_ylim(pd.to_datetime(str(1971)),pd.to_datetime(str(1974)))
            # ax.set_ylim(0.1,100)
            # ax.plot(np.linspace(0.1,100,50), np.linspace(0.1,100,50), 
            #         linestyle='-', color='grey', linewidth=1.5, zorder=-1)
            ax.set_xscale('log')
            ax.tick_params(axis="y", direction='out', length=5)
            plt.tight_layout()
            plt.tick_params(top=False)
            
            ax.invert_yaxis()
            
            if scan == 'perenn_areas':
                axs1b = ax.twinx()
                axs1b.plot(intermit / perman, hyst.y.index, color='k', lw=1)    
                axs1b.set_xlim(0.1,100)
                axs1b.set_xscale('log')
                axs1b.axes.get_xaxis().set_visible(False)
                axs1b.axes.get_yaxis().set_visible(False)
                axs1b.set_ylim(pd.to_datetime(str(2012)),pd.to_datetime(str(2019)))
                axs1b.invert_yaxis()
        
        # fig1.savefig(figsim_folder+'HI_barh_'+model_name+'.png', dpi=300, bbox_inches='tight')
            
    compt += 1

#%% FIG ap2 : INTERMITTENCY INTERMENSUAL

figsim_folder = simulations_folder+'_draft/'
if not os.path.exists(figsim_folder):
    toolbox.create_folder(figsim_folder)

sce = 'historic'
typ = 'conceptexplo'
var = 'REC'
scan_list = ['surflow_areas','perenn_areas','intermit_areas']
scan_list = ['intermit_areas','perenn_areas']

sce_list = ['historic','RCP2.6','RCP8.5']
sce_list = ['historic']
sce_cmap = ["Greys","Blues","Reds"]
sce_color = ["k","blue","red"]

scan_cmap = ["Greys","Blues","Oranges"]
scan_color = ["darkorange","dodgerblue"]
scan_pos = ["1","2","3"]
bxlim = (0.5,3.5)
cmap_dict = dict(zip(scan_list, scan_cmap))
color_dict = dict(zip(scan_list, scan_color))
pos_dict = dict(zip(scan_list, scan_pos))

# color_dict = dict(zip(sce_list, sce_color))

temporal = True
space = 0
norm = False

metric = 'area'
            
print(sce)
compt = 0
simul_list = glob.glob(simulations_folder+typ+'*'+sce+'*')

for ix in np.arange(1,9+1,1):
    
    Fig1 = True
    if Fig1 == True:
        fig1, axs1 = plt.subplots(1,1, figsize=(4.5,2))
    
    for sce in sce_list:
        # simul_list = glob.glob(simulations_folder+'*'+typ+'_'+str(i)+'*'+sce+'*')
        simul = glob.glob(simulations_folder+typ+'_'+str(ix)+'*'+sce+'*')[0]

    # for simul in simul_list[0:1]:
        
        model_name = simul.split('\\')[-1]
        Sy = float(model_name.split('_')[3].split('-')[0]) # %
        K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
        E = float(model_name.split('_')[3].split('-')[2]) # m
        D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
        params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
        Smod_path = simul+'/_watershed/_simulated_results.csv'            
        if not os.path.exists(Smod_path):
            compt += 1
            continue
        Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
        
        for scan in scan_list:
            Qmod = Smod[scan] # %
            Qmod = Qmod.squeeze()    
            Cmod = Smod['recharge'] * 1000 # mm/months
            DFmod = pd.DataFrame(columns=['x','y'])
            DFmod['x'] = Cmod
            DFmod['y'] = Qmod
            first_valid_loc = DFmod[DFmod.index.month==10].apply(lambda col: col.first_valid_index()).max().year
            last_valid_loc = DFmod[DFmod.index.month==9].apply(lambda col: col.last_valid_index()).min().year
            DFmod = select_period(DFmod, first_valid_loc, last_valid_loc)
            for idx in range(len(DFmod)):
                if DFmod.index[idx].month == 10:
                    DFmod = DFmod[idx:]   
                    break
            DFmod = DFmod.sort_index(ascending=False)
            for idx in range(len(DFmod)):
                if DFmod.index[idx].month == 9:
                    DFmod = DFmod[idx:]
                    break
            DFmod = DFmod.sort_index(ascending=True)
            
            hyst = Hysteresis(DFmod, simul)
            hyst.prepare_xy_raw()
    
            hyst.compute_xy_metrics(temporal=temporal, space=space, norm=norm)
    
            columns_x = hyst.xrecapl.columns
            columns_y = hyst.yrecapl.columns
    
            n = len(columns_x)
            cmap = cmap_dict[scan]
            cmap_color = plt.get_cmap(cmap)(np.linspace(0, 1, n))
            color = color_dict[scan]
            
            dfevol = hyst.dfmet.iloc[:-1]
            dfevol = dfevol.set_index(pd.to_datetime(dfevol.index, format='%Y'))
            dfmean = hyst.dfmet.iloc[-1]
            
            ################ FIG 1 ################
            
            if Fig1 == True:
                ax = axs1
                ax.set_title(params, fontsize=8)
                # for i, (colx, coly) in enumerate(zip(columns_x, columns_y)):
                #     # print(colx)
                #     data = pd.DataFrame()
                #     data['inx'] = hyst.xrecapl[colx]
                #     data['iny'] = hyst.yrecapl[coly]
                #     ax.plot(data.inx, data.iny, linestyle = '-', lw=0.5, color=cmap_color[i],
                #             alpha=0.5, zorder=0)    
                
                # color = color_dict[sce]
                
                mean = hyst.y.groupby([lambda x: x.month]).mean()
                q25 = hyst.y.groupby([lambda x: x.month]).quantile(0.25)
                q75 = hyst.y.groupby([lambda x: x.month]).quantile(0.75)
                
                # if scan == 'perenn_areas':
                #     alpha=0.5
                axs1.plot(mean, color=color, lw=2)
                axs1.fill_between(mean.index, q25, q75, alpha=0.2, color=color,
                                  linewidth=0)
                
                # ax.plot(data.inx, data.iny, linestyle = '-', lw=2, color=color, zorder=2)
                # plt.setp(axs2, xlim=(min(xmin),max(xmax)), ylim=(min(ymin),max(ymax)))
                ax.set_ylim(0.1,100)
                # ax.set_xlim(1,12)
                # ax.set_xlim(pd.to_datetime(str(2012)),pd.to_datetime(str(2019)))
                # ax.set_ylim(0.1,100)
                # ax.plot(np.linspace(0.1,100,50), np.linspace(0.1,100,50), 
                #         linestyle='-', color='grey', linewidth=1.5, zorder=-1)
                ax.set_yscale('log')
                # ax.tick_params(axis="y", direction='out', length=5)
                plt.tight_layout()
                plt.tick_params(top=False)
                
                xticks = np.arange(12)+1
                mois = ['J','F','M','A','M','J','J','A','S','O','N','D']
                ax.set_xticks(xticks)
                ax.set_xticklabels(mois, minor=False, rotation='horizontal', fontsize=13)
                ax.set_xlim(1,12)
                
                # ax.invert_yaxis()
                
                # if scan == 'perenn_areas':
                #     axs1b = ax.twinx()
                #     axs1b.plot(intermit / perman, hyst.y.index, color='k', lw=1)    
                #     axs1b.set_xlim(0.1,100)
                #     axs1b.set_xscale('log')
                #     axs1b.axes.get_xaxis().set_visible(False)
                #     axs1b.axes.get_yaxis().set_visible(False)
                #     axs1b.set_ylim(pd.to_datetime(str(2012)),pd.to_datetime(str(2019)))
                #     axs1b.invert_yaxis()
            
            # fig1.savefig(figsim_folder+'HI_intm_'+model_name+'.png', dpi=300, bbox_inches='tight')
            
    compt += 1

#%% ---

#%% FLOPY CROSS SECTION

import flopy
import flopy.utils.binaryfile as fpu
import flopy.utils.formattedfile as ff

path_mf = simulations_folder+'/'+model_name+'/'+model_name
mf1 = flopy.modflow.Modflow.load(path_mf + '.nam', verbose=False, check=False, load_only=["bas6", "dis"])
head_fpu = fpu.HeadFile(path_mf+'.hds')
head_data = head_fpu.get_data()
head_data_mask = np.ma.masked_array(head_data, mask=(head_data==-9999))

buffMasked = imageio.imread(BV.geographic.watershed_buff_dem)
buffMasked = np.ma.masked_where(buffMasked<0, buffMasked)
# plt.imshow(buffMasked)

col = 60

fig, ax = plt.subplots(1,1, figsize=(10,5))
extent = (0, head_data_mask.shape[1]*75, 
          buffMasked[:,col].min()-10, buffMasked[:,col].max()+10) # x1, x2, y1, y2
xsect = flopy.plot.PlotCrossSection(model=mf1, line={'Column': col}, extent=extent)
pc = xsect.plot_array(head_data, masked_values=[-9999], head=head_data, cmap='Spectral', alpha=0.5)
divider = make_axes_locatable(ax)
cax = divider.append_axes("right", size="4%", pad=0.05)
cb = plt.colorbar(pc, cax=cax)
cb.set_label('Head [m]', labelpad=+10)
cb.mappable.set_clim(buffMasked[:,col].min()-10, buffMasked[:,col].max()+10)
wt = xsect.plot_surface(head_data_mask, masked_values=[-9999], color='b', lw=1)
patches = xsect.plot_ibound()
linecollection = xsect.plot_grid(alpha=0.3, zorder=0)
title = ax.set_title('Hydraulic head cross-section')
ax.set_xlabel('Distance N-S (m)')
ax.set_ylabel('Elevation (m)')
ax.set_ylim(0)
# levels = np.arange(np.nanmin(head_data), np.nanmax(head_data), 100)
# contour_set = xsect.contour_array(head_data, masked_values=[-9999], head=head_data, 
#                                   levels=levels, colors='k', alpha = 0.5)
# plt.clabel(contour_set, fmt='%.1f', colors='k', fontsize=8)
# size = 7
# import flopy.utils.postprocessing as pp
# qx,qy,qz = pp.get_specific_discharge(mf1, model=path_mf + '.cbc')
# quiver = xsect.plot_vector(qx,qy,qz, head=head_data,
#                        hstep=60, normalize=True, color='k', 
#                        scale=20, headwidth=size, headlength=size, 
#                        headaxislength=size,
#                        zorder=1, width=0.0025)
    
#%% HYSTERSIS ONE

var = 'REC'
mod = 'REA'
sce = 'historic'
typ = 'conceptexplo'

simul_list = glob.glob(simulations_folder+'*'+typ)

temporal = False
space = 0
norm = False

simuls = fnmatch.filter(os.listdir(simulations_folder), typ+'*')

fig, ax = plt.subplots(1,1, figsize=(4.5,4))

for simul in simuls:
    
        Qmod_path = simulations_folder+simul+'/_watershed/_simulated_results.csv'
        Qmod = pd.read_csv(Qmod_path, sep=';', index_col=0, parse_dates=True)
        Qmod = Qmod['outflow_drain'] * 1000 # m/month to mm/month
        # Qmod = Qmod['groundwater_storage'] # m/month to mm/month
        
        # Qmod = Qmod['seepage_areas'] # %
        Qmod = Qmod.squeeze()
        
        Cmod_path = simulations_folder+simul+'/_watershed/_simulated_results.csv'
        Cmod = pd.read_csv(Cmod_path, sep=';', index_col=0, parse_dates=True)
        Cmod = Cmod['recharge'] * 1000 # m/month to mm/month
        # Cmod = Cmod['outflow_drain'] * 1000 # m/month to mm/month
        
        DFmod = pd.DataFrame(columns=['x','y'])
        DFmod['x'] = Cmod
        DFmod['y'] = Qmod
        first_valid_loc = DFmod[DFmod.index.month==10].apply(lambda col: col.first_valid_index()).max().year
        last_valid_loc = DFmod[DFmod.index.month==9].apply(lambda col: col.last_valid_index()).min().year
        DFmod = select_period(DFmod, first_valid_loc, last_valid_loc)
        
        for idx in range(len(DFmod)):
            if DFmod.index[idx].month == 10:
                DFmod = DFmod[idx:]   
                break
        DFmod = DFmod.sort_index(ascending=False)
        for idx in range(len(DFmod)):
            if DFmod.index[idx].month == 9:
                DFmod = DFmod[idx:]
                break
        DFmod = DFmod.sort_index(ascending=True)
        
        hyst = Hysteresis(DFmod, 'Test')
        hyst.prepare_xy_raw()
        hyst.compute_xy_metrics(temporal=temporal, space=space, norm=norm)
        hyst.plot_xy_mod(ax, var + ' [mm]', 'Q [mm]', [None,None], [None,None], 
                         'gist_rainbow_r', 'linear')
                
#%% HYSTERSIS ALL

var = 'REC'

typ = 'conceptexplo'
simul_typ = glob.glob(simulations_folder+typ+'*')
simul_typ = fnmatch.filter(simul_typ, '*historic*')

scan_res = ['outflow_drain']

# fig, axs = plt.subplots(3,3,figsize=(7, 3.5))
# fig.add_subplot(111, frameon=False)
# plt.tick_params(labelcolor='none', top=False, bottom=False, left=False, right=False) # hide tick and tick label of the big axis
# axs = axs.ravel()
        
fig, axs = plt.subplots(3,3, figsize=(9,9))
axs = axs.ravel()

temporal = False
space = 0
norm = False
        
compt = 0

for simul in simul_typ:
    
    for res in scan_res:

        Smod_path = simul+'/_watershed/_simulated_results.csv'
        if not os.path.exists(Smod_path):
            continue
        Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
        Qmod = Smod[res] 
        if res == 'outflow_drain':
            Qmod = Qmod * 1000 # mm/months
        Qmod = Qmod.squeeze()    
        Cmod = Smod['recharge'] * 1000 # mm/months
        
        DFmod = pd.DataFrame(columns=['x','y'])
        DFmod['x'] = Cmod
        DFmod['y'] = Qmod
        first_valid_loc = DFmod[DFmod.index.month==10].apply(lambda col: col.first_valid_index()).max().year
        last_valid_loc = DFmod[DFmod.index.month==9].apply(lambda col: col.last_valid_index()).min().year
        DFmod = select_period(DFmod, first_valid_loc, last_valid_loc)
        
        for idx in range(len(DFmod)):
            if DFmod.index[idx].month == 10:
                DFmod = DFmod[idx:]   
                break
        DFmod = DFmod.sort_index(ascending=False)
        for idx in range(len(DFmod)):
            if DFmod.index[idx].month == 9:
                DFmod = DFmod[idx:]
                break
        DFmod = DFmod.sort_index(ascending=True)
        
        ax = axs[compt]
        
        def plancha (DFmod, name, ax):
            hyst = Hysteresis(DFmod, 'Test')
            hyst.prepare_xy_raw()
            
            if res == 'outflow_drain':
                hyst.compute_xy_metrics(temporal=temporal, space=space, norm=norm)
                hyst.plot_xy_mod(ax, var + ' [mm]', 'Q [mm]', [0,1], [0,1], 
                                 'gist_rainbow_r', 'linear')
            
            else:
                ax.scatter(hyst.x, hyst.y, c=hyst.wy, cmap='gist_rainbow_r', marker="o", 
                                  s=10, vmin=1, vmax=12, alpha=0.75, ec='none')
                ax.plot(hyst.xi, hyst.yi, marker="o", markersize=9, markeredgecolor='black', 
                        markerfacecolor='white', linestyle = 'None') 
                for k in hyst.wyi:
                    ax.annotate(k,(hyst.xi[k],hyst.yi[k]), family='sans-serif', fontsize=5, 
                                color='black', weight="bold", ha='center', va='center')
                # ax.set_ylim(0,100)
                # ax.set_xlim(-10,100)
                
        name = simul
        plancha(DFmod, name, ax)
        
        compt += 1
        
plt.tight_layout()

#%% HYSTERESIS BOX

figsim_folder = simulations_folder+'_figures/'
if not os.path.exists(figsim_folder):
    toolbox.create_folder(figsim_folder)

typ = 'conceptexplo'
var = 'REC'
scan = 'outflow_drain'
sce_list = ['historic','RCP2.6','RCP8.5']
sce_list = ['historic']
sce_cmap = ["Greys","Blues","Reds"]
sce_color = ["k","blue","red"]
sce_pos = ["1","2","3"]
bxlim = (0.5,3.5)
# sce_list = ['historic','RCP2.6','RCP4.5','RCP8.5']
# sce_cmap = ["Greys","Blues","Greens","Reds"]
# sce_color = ["dimgray","blue","green","red"]
# sce_pos = ["1","2","3","4"]
# bxlim = (0.5,4.5)
cmap_dict = dict(zip(sce_list, sce_cmap))
color_dict = dict(zip(sce_list, sce_color))
pos_dict = dict(zip(sce_list, sce_pos))

temporal = True
space = -10
norm = False

metric = 'area_r'

Fig1 = False
if Fig1 == True:
    fig1, axs1 = plt.subplots(3,3, figsize=(9,9))
    axs1 = axs1.ravel()
    xn = -0.1
    xx = 80
    yn = -0.1
    yx = 80
    
Fig2 = False
if Fig2 == True:
    fig2, axs2 = plt.subplots(3,3, figsize=(9,9))
    axs2 = axs2.ravel()
    xmin = []
    xmax = []
    ymin = []
    ymax = []
    
Fig3 = False
if Fig3 == True:
    fig3, axs3 = plt.subplots(3,3, figsize=(9,9))
    axs3 = axs3.ravel()
    bmean = []
    bmin = []
    bmax = []

fig, axs = plt.subplots(3,3, figsize=(17,17), dpi=300)
axs = axs.ravel()

watershed_names = ['Le Canut', 'Le Leff', 'L Élorn']
watershed_colors = ['darkgreen','darkorange','darkmagenta']
watshd_dict = dict(zip(watershed_names, watershed_colors))

watershed_names = ['Cheze']
watershed_colors = ['k']
watshd_dict = dict(zip(watershed_names, watershed_colors))

for watershed_name in watershed_names:
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = watshd_dict[watershed_name]
    
    for sce in sce_list:
        print(sce)
        compt = 0
        simul_list = glob.glob(simulations_folder+'*'+typ+'*'+sce+'*')
        for simul in simul_list:
            model_name = simul.split('\\')[-1]
            Sy = float(model_name.split('_')[3].split('-')[0]) # %
            K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
            E = float(model_name.split('_')[3].split('-')[2]) # m
            D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
            params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
            Smod_path = simul+'/_watershed/_simulated_results.csv'
            if not os.path.exists(Smod_path):
                compt += 1
                continue
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            Qmod = Smod[scan] 
            Qmod = Qmod * 1000 # mm/months
            Qmod = Qmod.squeeze()    
            Cmod = Smod['recharge'] * 1000 # mm/months
            DFmod = pd.DataFrame(columns=['x','y'])
            DFmod['x'] = Cmod
            DFmod['y'] = Qmod
            first_valid_loc = DFmod[DFmod.index.month==10].apply(lambda col: col.first_valid_index()).max().year
            last_valid_loc = DFmod[DFmod.index.month==9].apply(lambda col: col.last_valid_index()).min().year
            DFmod = select_period(DFmod, first_valid_loc, last_valid_loc)
            for idx in range(len(DFmod)):
                if DFmod.index[idx].month == 10:
                    DFmod = DFmod[idx:]   
                    break
            DFmod = DFmod.sort_index(ascending=False)
            for idx in range(len(DFmod)):
                if DFmod.index[idx].month == 9:
                    DFmod = DFmod[idx:]
                    break
            DFmod = DFmod.sort_index(ascending=True)
            
            hyst = Hysteresis(DFmod, simul)
            hyst.prepare_xy_raw()
            hyst.compute_xy_metrics(temporal=temporal, space=space, norm=norm)
            columns_x = hyst.xrecapl.columns
            columns_y = hyst.yrecapl.columns
            
            n = len(columns_x)
            cmap = cmap_dict[sce]
            cmap_color = plt.get_cmap(cmap)(np.linspace(0, 1, n))
            
            if len(watershed_names) == 1:
                color = color_dict[sce]
            
            dfevol = hyst.dfmet.iloc[:-1]
            dfevol = dfevol.set_index(pd.to_datetime(dfevol.index, format='%Y'))
            dfmean = hyst.dfmet.iloc[-1]
            
            ax = axs[compt]
            ax.scatter(Smod.outflow_drain, Smod.seepage_areas,
                       c='grey')
            ax.scatter(Smod.outflow_drain, Smod.surflow_areas,
                       c='k')
            ax.scatter(Smod.outflow_drain, Smod.perenn_areas,
                       c='dodgerblue')
            ax.scatter(Smod.outflow_drain, Smod.intermit_areas,
                       c='darkorange')      
            ax.set_title(params, fontsize=12)
            
            ################ FIG 1 ################
            if Fig1 == True:
                ax = axs1[compt]
                ax.set_title(params, fontsize=8)
                # fig2.suptitle(metric.upper(), y=0.98)
                for i, (colx, coly) in enumerate(zip(columns_x, columns_y)):
                    # print(colx)
                    data = pd.DataFrame()
                    data['inx'] = hyst.xrecapl[colx]
                    data['iny'] = hyst.yrecapl[coly]
                    # ax.plot(data.inx, data.iny, linestyle = '-', lw=0.5, color=cmap_color[i],
                    #         alpha=0.75, zorder=0)             
                ax.plot(data.inx, data.iny, linestyle = '-', lw=2, color=color, zorder=2)
                # plt.setp(axs2, xlim=(min(xmin),max(xmax)), ylim=(min(ymin),max(ymax)))
                ax.set_xlim(xn,xx)
                ax.set_ylim(yn,yx)
                ax.plot(np.linspace(0,xmax,50), np.linspace(0,ymax,50), 
                        linestyle='-', color='grey', linewidth=1.5, zorder=-1)
                # ax.set_yscale('log')
                
                dfmean = dfmean.round(2)
                
                if watershed_name == 'Le Canut':
                
                    ax.text(0.042, 0.81, 
                                     'Q0 = ' +str(dfmean['q0']) + '\n'
                                     'Qmid = '+str(dfmean['qmid']) + '\n'
                                     'HI = '+str(dfmean['hi']) + '\n'
                                     'Area R = '+str(dfmean['area_r']) + '\n',
                                     horizontalalignment='left',
                                     verticalalignment='center', 
                                     transform=ax.transAxes,
                                     fontsize = 10)
                    
                    ax.text(0.58, 0.14,
                                     'Slope = ' +str(dfmean['slope']) + '\n'
                                     'Long = ' +str(dfmean['long']) + '\n'
                                     'Short = ' +str(dfmean['short']) + '\n'
                                     'Eccent. = ' +str(dfmean['excent']) + '\n',
                                     horizontalalignment='left',
                                     verticalalignment='center', 
                                     transform=ax.transAxes,
                                     fontsize = 10)
    
                ax.grid(color='grey',alpha=0.2)
                
                plt.tight_layout()
                
            ################ FIG 2 ################
            if Fig2 == True:
                ax = axs2[compt]
                ax.set_title(params, fontsize=8)
                fig2.suptitle(metric.upper(), y=0.98)
                ax.plot(dfevol.index, dfevol[metric], linestyle = '-', lw=1, color=color,
                        zorder=1)
                ax.set_yscale('log') 
                ax.axhline(dfmean[metric], linestyle = ':', lw=2, color=color, zorder=2)
                # ax.set_xlim(-10,100)
                # ax.set_ylim(0.01,100)
                years_maj = YearLocator(40)   # every x year
                # years_min = YearLocator(1)
                years_maj_fmt = DateFormatter('%Y')
                # months_maj = MonthLocator(6)  # every x month
                # months_min = MonthLocator(3)
                # months_maj_fmt = DateFormatter('%m') #b = name of month ?
                ax.xaxis.set_major_locator(years_maj)
                # ax.xaxis.set_minor_locator(years_min)
                ax.xaxis.set_major_formatter(years_maj_fmt)
                # ax.set_ylim(0,40)
                xmin.append(dfevol.index.year.min())
                xmax.append(dfevol.index.year.max())
                ymin.append(dfevol[metric].min())
                ymax.append(dfevol[metric].max())
                plt.setp(axs2, xlim=(pd.to_datetime(str(min(xmin))),pd.to_datetime(str(max(xmax)))),
                                ylim=(min(ymin),max(ymax)))
                plt.tight_layout()
            
            ################ FIG 3 ################
            if Fig3 == True:
                ax = axs3[compt]
                ax.set_title(params, fontsize=8)
                fig3.suptitle(metric.upper(), y=0.98)
                boxprops = dict(linestyle='-', linewidth=1, color='black',
                                facecolor=color)
                medianprops = dict(linestyle='-', linewidth=1, color='black')
                meanpointprops = dict(markersize=3, marker='o', markeredgecolor='black',
                                      markerfacecolor='black', linestyle='-')
                bp = ax.boxplot(dfevol[metric], positions=[int(pos_dict[sce])],
                                  whis=True, showfliers=False, showmeans=True,
                                  medianprops=medianprops, meanprops=meanpointprops,
                                  patch_artist=True, boxprops=boxprops)
                ax.scatter(int(pos_dict[sce]), dfevol[metric].min(), marker='.',color='dimgrey',s = 3)
                ax.scatter(int(pos_dict[sce]), dfevol[metric].max(), marker='.',color='dimgrey',s = 3)
                ax.scatter(int(pos_dict[sce]),
                            dfevol[metric].mean()-dfevol[metric].std(),
                            marker='_',color='dimgrey',s = 7, zorder=2)
                ax.scatter(int(pos_dict[sce]),
                            dfevol[metric].mean()+dfevol[metric].std(),
                            marker='_',color='dimgrey',s = 7, zorder=2)
                for element in bp['whiskers']:
                    element.set_color('k')
                    element.set_linestyle('-')
                ax.set_xticks(np.arange(1,len(sce_list)+1,1))
                ax.set_xticklabels([x.upper() for x in sce_list], fontsize=10)
                bmin.append(dfevol[metric].min())
                bmax.append(dfevol[metric].max())
                # plt.setp(axs3, ylim=(min(bmin),max(bmax)))
                ax.set_ylim(0,15)
                ax.set_xlim(bxlim)
                plt.tight_layout()
                
            compt += 1
    
    # fig1.tight_layout()
    # fig2.tight_layout()
    # fig3.tight_layout()
    
    # fig1.savefig(figsim_folder+'3bv_'+'loop_outflow_rcps_'+metric+'.png', dpi=300, bbox_inches='tight')
    # fig2.savefig(figsim_folder+'3bv_'+'evol_'+metric+'_rcps'+'.png', dpi=300, bbox_inches='tight')
    # fig3.savefig(figsim_folder+'3bv_'+'box_'+metric+'rcps'+'.png', dpi=300, bbox_inches='tight')
         
#%% INTERMITTENCY BOX

figsim_folder = simulations_folder+'_figures/'
if not os.path.exists(figsim_folder):
    toolbox.create_folder(figsim_folder)

sce = 'historic'
typ = 'conceptexplo'
var = 'REC'
scan_list = ['surflow_areas','perenn_areas','intermit_areas']

scan_cmap = ["Greys","Blues","Oranges"]
scan_color = ["black","dodgerblue","darkorange"]
scan_pos = ["1","2","3"]
bxlim = (0.5,3.5)
cmap_dict = dict(zip(scan_list, scan_cmap))
color_dict = dict(zip(scan_list, scan_color))
pos_dict = dict(zip(scan_list, scan_pos))

temporal = True
space = 0
norm = False

metric = 'area'

Fig1 = True
if Fig1 == True:
    fig1, axs1 = plt.subplots(3,3, figsize=(9,9))
    axs1 = axs1.ravel()

Fig2 = True
if Fig2 == True:
    fig2, axs2 = plt.subplots(3,3, figsize=(9,9))
    axs2 = axs2.ravel()
    xmin = []
    xmax = []
    ymin = []
    ymax = []
    
Fig3 = True
if Fig3 == True:
    fig3, axs3 = plt.subplots(3,3, figsize=(9,9))
    axs3 = axs3.ravel()
    bmean = []
    bmin = []
    bmax = []
            
print(sce)
compt = 0
simul_list = glob.glob(simulations_folder+'*'+typ+'*'+sce+'*')
for simul in simul_list:
    model_name = simul.split('\\')[-1]
    Sy = float(model_name.split('_')[3].split('-')[0]) # %
    K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
    E = float(model_name.split('_')[3].split('-')[2]) # m
    D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
    params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
    Smod_path = simul+'/_watershed/_simulated_results.csv'            
    if not os.path.exists(Smod_path):
        compt += 1
        continue
    Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
    
    for scan in scan_list:
        Qmod = Smod[scan] # %
        Qmod = Qmod.squeeze()    
        Cmod = Smod['recharge'] * 1000 # mm/months
        DFmod = pd.DataFrame(columns=['x','y'])
        DFmod['x'] = Cmod
        DFmod['y'] = Qmod
        first_valid_loc = DFmod[DFmod.index.month==10].apply(lambda col: col.first_valid_index()).max().year
        last_valid_loc = DFmod[DFmod.index.month==9].apply(lambda col: col.last_valid_index()).min().year
        DFmod = select_period(DFmod, first_valid_loc, last_valid_loc)
        for idx in range(len(DFmod)):
            if DFmod.index[idx].month == 10:
                DFmod = DFmod[idx:]   
                break
        DFmod = DFmod.sort_index(ascending=False)
        for idx in range(len(DFmod)):
            if DFmod.index[idx].month == 9:
                DFmod = DFmod[idx:]
                break
        DFmod = DFmod.sort_index(ascending=True)
        
        hyst = Hysteresis(DFmod, simul)
        hyst.prepare_xy_raw()
            
        hyst.compute_xy_metrics(temporal=temporal, space=space, norm=norm)

        columns_x = hyst.xrecapl.columns
        columns_y = hyst.yrecapl.columns
        
        n = len(columns_x)
        cmap = cmap_dict[scan]
        cmap_color = plt.get_cmap(cmap)(np.linspace(0, 1, n))
        color = color_dict[scan]
        
        dfevol = hyst.dfmet.iloc[:-1]
        dfevol = dfevol.set_index(pd.to_datetime(dfevol.index, format='%Y'))
        dfmean = hyst.dfmet.iloc[-1]
        
        ################ FIG 1 ################
        
        if Fig1 == True:
            ax = axs1
            ax.set_title(params, fontsize=8)
            for i, (colx, coly) in enumerate(zip(columns_x, columns_y)):
                # print(colx)
                data = pd.DataFrame()
                data['inx'] = hyst.xrecapl[colx]
                data['iny'] = hyst.yrecapl[coly]
            #     ax.plot(data.inx, data.iny, linestyle = '-', lw=0.5, color=cmap_color[i],
            #             alpha=0.5, zorder=0)             
            ax.plot(data.inx, data.iny, linestyle = '-', lw=2, color=color, zorder=2)
            # plt.setp(axs2, xlim=(min(xmin),max(xmax)), ylim=(min(ymin),max(ymax)))
            ax.set_xlim(0.1,100)
            ax.set_ylim(0.1,100)
            ax.plot(np.linspace(0.1,100,50), np.linspace(0.1,100,50), 
                    linestyle='-', color='grey', linewidth=1.5, zorder=-1)
            ax.set_yscale('log')
            plt.tight_layout()
            
        ################ FIG 2 ################
        if Fig2 == True:
            ax = axs2[compt]
            ax.set_title(params, fontsize=8)
            ax.plot(Qmod, linestyle = '-', lw=1, color=color, zorder=1)
            # ax.set_yscale('log') 
            # ax.axhline(Qmod.mean(), linestyle = ':', lw=2, color=color, zorder=2)
            # ax.set_xlim(-10,100)
            ax.set_ylim(0.1,100)
            years_maj = YearLocator(10)   # every x year
            # years_min = YearLocator(1)
            years_maj_fmt = DateFormatter('%Y')
            # months_maj = MonthLocator(6)  # every x month
            # months_min = MonthLocator(3)
            # months_maj_fmt = DateFormatter('%m') #b = name of month ?
            ax.xaxis.set_major_locator(years_maj)
            # ax.xaxis.set_minor_locator(years_min)
            ax.xaxis.set_major_formatter(years_maj_fmt)
            # ax.set_ylim(0,40)
            xmin.append(Qmod.index.year.min())
            xmax.append(Qmod.index.year.max())
            plt.setp(axs2, xlim=(pd.to_datetime(str(min(xmin))),pd.to_datetime(str(max(xmax)))))
            plt.tight_layout()
        
        ################ FIG 3 ################
        if Fig3 == True:
            ax = axs3[compt]
            ax.set_title(params, fontsize=8)
            boxprops = dict(linestyle='-', linewidth=1, color='black',
                            facecolor=color)
            medianprops = dict(linestyle='-', linewidth=1, color='black')
            meanpointprops = dict(markersize=3, marker='o', markeredgecolor='black',
                                  markerfacecolor='black', linestyle='-')
            bp = ax.boxplot(Qmod, positions=[int(pos_dict[scan])],
                             whis=True, showfliers=False, showmeans=True,
                             medianprops=medianprops, meanprops=meanpointprops,
                             patch_artist=True, boxprops=boxprops)
            ax.scatter(int(pos_dict[scan]), Qmod.min(), marker='.',color='dimgrey',s = 3)
            ax.scatter(int(pos_dict[scan]), Qmod.max(), marker='.',color='dimgrey',s = 3)
            ax.scatter(int(pos_dict[scan]),
                       Qmod.mean()-Qmod.std(),
                       marker='_',color='dimgrey',s = 7, zorder=2)
            ax.scatter(int(pos_dict[scan]),
                       Qmod.mean()+Qmod.std(),
                       marker='_',color='dimgrey',s = 7, zorder=2)
            for element in bp['whiskers']:
                element.set_color('k')
                element.set_linestyle('-')
            ax.set_xticks(np.arange(1,len(scan_list)+1,1))
            ax.set_xticklabels([x.split('_')[0][:4].upper() for x in scan_list], fontsize=10)
            ax.set_ylim(0.1,100)
            ax.set_xlim(bxlim)
            ax.set_yscale('log') 
            plt.tight_layout()
        
    compt += 1

fig1.tight_layout()
fig2.tight_layout()
fig3.tight_layout()

# fig1.savefig(figsim_folder+'loop_saturation.png', dpi=300, bbox_inches='tight')
# fig2.savefig(figsim_folder+'eveol_saturation.png', dpi=300, bbox_inches='tight')
# fig3.savefig(figsim_folder+'box_saturation.png', dpi=300, bbox_inches='tight')

#%% ---

#%% DISCHARGE OBSERVED

watershed_name = 'Canut'
stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
raw_path = stable_folder+'/'+'hydrometry/'
Qobs_path = fnmatch.filter(os.listdir(raw_path), 'Hydrometric_*')[0]
Qobs = pd.read_csv(raw_path+Qobs_path, sep=';', index_col=0, parse_dates=True)
area = float(Qobs_path.split('_')[-3])
Qobs = (Qobs / (area*1000000)) * (3600 * 24) * 1000 # m3/s to mm/day
Qobs = Qobs.squeeze()

#%% DISCHARGE MONTHLY

hist = Qobs.copy().to_frame()
hist['month'] = hist.index.month.values
hist['year'] = hist.index.year.values # group by month and year, get the average
hist = hist.groupby(['month', 'year']).apply(lambda g: g.sum(skipna=False))
hist = hist.unstack(level=0, fill_value=np.nan)
hist = hist['Q']
hist[hist==0] = 0.01
hist = hist.T

lims = (hist.min(), hist.max())
vmin = np.nanmin(np.array(lims))
vmax = np.nanmax(np.array(lims))
normalize = mpl.colors.Normalize(vmin=vmin, vmax=vmax)

fig, ax = plt.subplots(1,1, figsize=(9, 2.5))
colori = "jet"
yticks = np.arange(12)+0.5
mois = ['J','F','M','A','M','J','J','A','S','O','N','D']
import matplotlib as mpl
pc = ax.pcolormesh(hist, cmap='jet_r', vmin=vmin, vmax=vmax,
              norm = mpl.colors.LogNorm(),
              edgecolor='grey', lw=0.2, alpha=0.7)
              # norm=mpl.colors.LogNorm(vmin, vmax)
              # norm=mpl.colors.CenteredNorm()
ax.set_yticks(yticks)
ax.set_yticklabels(mois, minor=False, rotation='horizontal', fontsize=13)
# ax.xaxis.tick_top()
xticks = np.arange((hist.columns[-1]+1) - hist.columns[0])+0.5
years = list(hist.columns.astype(str))[::3] 
ax.set_xticks(xticks[::3])
ax.set_xticklabels(years, minor=False, rotation='horizontal', fontsize=13)
ax.invert_yaxis()
ax.tick_params(axis="x", direction='out', length=5)
ax.tick_params(axis="y", direction='out', length=5)
plt.tick_params(right=False, top=False)
ax.set_title(Qobs_path.split('_')[2])

divider = make_axes_locatable(ax)
cax = divider.append_axes('right', size='1.25%', pad=0.1)
cb = plt.colorbar(pc, cax=cax, orientation="vertical")
cax.set_ylabel('Discharge \n [mm/month]', rotation=270, labelpad=40)

# fig.savefig(stable_folder+'_figures/hydrometry/'+
#             'monthly_discharge'+'.png', dpi=300, bbox_inches='tight')

#%% DISCHARGE DAILY 

hist = Qobs.copy().to_frame()
hist['day'] = hist.index.dayofyear.values
hist['year'] = hist.index.year.values # group by month and year, get the average
hist = hist.groupby(['day','year']).apply(lambda g: g.sum(skipna=False))
hist = hist.unstack(level=0, fill_value=np.nan)
hist = hist['Q']
hist[hist==0] = 0.01
# hist = hist.T

lims = (hist.min(), hist.max())
vmin = np.array(lims).min()
vmax = np.array(lims).max()
normalize = mpl.colors.Normalize(vmin=vmin, vmax=vmax)

fig, ax = plt.subplots(1,1, figsize=(7, 4))
colori = "jet"

import matplotlib as mpl
pc = ax.pcolormesh(hist, cmap='jet_r', vmin=vmin, vmax=vmax,
                   norm = mpl.colors.LogNorm(),
                   edgecolor='none', lw=0.2, alpha=0.7)
                  # norm=mpl.colors.LogNorm(vmin, vmax)
                  # norm=mpl.colors.CenteredNorm()
              
xticks = np.arange(0,365+1,30)
days = np.arange(0,365+1,30)              
ax.set_xticks(xticks)
ax.set_xticklabels(days, minor=False, rotation='horizontal', fontsize=13)
yticks = np.arange((hist.index[-1]+1) - hist.index[0])+0.5
years = list(hist.index.values.astype(str))[::3] 
ax.set_yticks(yticks[::3])
ax.set_yticklabels(years, minor=False, rotation='horizontal', fontsize=13)
ax.invert_yaxis()
ax.tick_params(axis="x", direction='out', length=5)
ax.tick_params(axis="y", direction='out', length=5)
plt.tick_params(right=False, top=False)
ax.set_title(Qobs_path.split('_')[2])
ax.set_xlabel('Days of the year')
ax.set_ylabel('Years')

divider = make_axes_locatable(ax)
cax = divider.append_axes('right', size='1.25%', pad=0.1)
cb = plt.colorbar(pc, cax=cax, orientation="vertical")
cax.set_ylabel('Discharge [mm/day]', rotation=270, labelpad=20)

# fig.savefig(stable_folder+'_figures/hydrometry/'+
#             'daily_discharge'+'.png', dpi=300, bbox_inches='tight')


#%% PLOT RECHARGE

def select_period(df, first, last):
    df = df[(df.index.year>=first) & (df.index.year<=last)]
    return df

climat = pd.read_csv('D:/Users/abherve/INTERMITTENCY/Canut/results_stable/climatic/_ALL_D.csv',
                     sep=';', index_col=0, parse_dates=True)

# for mod in ['OLD', 'REA']:

#     BV.forcing.update_recharge_surfex(clim_mod = mod, clim_sce = 'historic',
#                                              first_year = 2000, last_year = 2005,
#                                              time_step = time_step, sim_state='transient')
#     R = BV.forcing.recharge
#     plt.plot(R)

# for mod in ['OLD', 'REA']:

#     BV.forcing.update_effppt_surfex(clim_mod = mod, clim_sce = 'historic',
#                                     first_year = 2000, last_year = 2005, 
#                                     time_step = time_step, sim_state='transient')
#     R = BV.forcing.recharge
#     plt.plot(R)

climat = climat.resample('M').sum()
climat = select_period(climat, 2000, 2009)

watershed_name = 'Canut'
stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
raw_path = stable_folder+'/'+'hydrometry/'
Qobs_path = fnmatch.filter(os.listdir(raw_path), 'Hydrometric_*')[0]
Qobs = pd.read_csv(raw_path+Qobs_path, sep=';', index_col=0, parse_dates=True)
area = float(Qobs_path.split('_')[-3])
Qobs = (Qobs / (area*1000000)) * (3600 * 24) * 1000 # m3/s to mm/day
Qobs = Qobs.squeeze()
Qobs = Qobs.resample('M').sum()
Qobs = select_period(Qobs, 2000, 2009)

variabs = ['PPT','ETP','RUN','REC','EFF']
variabs = ['EFF']
for var in variabs:
    fig, ax = plt.subplots(1,1, figsize=(8,3))
    tp = (climat[var+'_'+'REA'+'_historic'] - climat['RUN'+'_'+'REA'+'_historic'])
    ax.plot(tp,
            color='dodgerblue', lw=2,
            label='REA : '+str(round(tp.sum()))+' mm/an')
    tp = climat[var+'_'+'OLD'+'_historic'] - climat['RUN'+'_'+'OLD'+'_historic']
    ax.plot(tp,
            color='red', lw=2,
            label='OLD : '+str(round(tp.sum()))+' mm/an')
    tp = climat[var+'_'+'IPS1'+'_historic'] - climat['RUN'+'_'+'IPS1'+'_historic']
    ax.plot(tp,
            color='k', lw=2,
            label='IPS1 : '+str(round(tp.sum()))+' mm/an')
    ax.plot(Qobs,
            color='grey', lw=2,
            label='Qobs : '+str(round(Qobs.sum()))+' mm/an')
    ax.set_title(var+'- RUN')
    ax.legend(loc='upper center')
    
variabs = ['PPT','ETP','RUN','REC','EFF']
variabs = ['REC']
for var in variabs:
    fig, ax = plt.subplots(1,1, figsize=(8,3))
    tp = (climat[var+'_'+'REA'+'_historic'] + climat['RUN'+'_'+'REA'+'_historic'])
    ax.plot(tp,
            color='dodgerblue', lw=2,
            label='REA : '+str(round(tp.sum()))+' mm/an')
    tp = climat[var+'_'+'OLD'+'_historic'] + climat['RUN'+'_'+'OLD'+'_historic']
    ax.plot(tp,
            color='red', lw=2,
            label='OLD : '+str(round(tp.sum()))+' mm/an')
    tp = climat[var+'_'+'IPS1'+'_historic'] + climat['RUN'+'_'+'IPS1'+'_historic']
    ax.plot(tp,
            color='k', lw=2,
            label='IPS1 : '+str(round(tp.sum()))+' mm/an')
    ax.plot(Qobs,
            color='grey', lw=2,
            label='Qobs : '+str(round(Qobs.sum()))+' mm/an')
    ax.set_title(var+'+ RUN')
    ax.legend(loc='upper center')    


#%% ---

#%% NOTES 
