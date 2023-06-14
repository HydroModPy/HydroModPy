# -*- coding: utf-8 -*-
"""
Created on Fri Mar  3 08:18:04 2023

@author: ronan
"""

#%% LIBRARIES

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
# import seaborn as sns
from matplotlib_scalebar.scalebar import ScaleBar
from rasterio.plot import show
from matplotlib.colors import LightSource
# import earthpy.spatial as es
# import earthpy.plot as ep
import imageio
import whitebox
wbt = whitebox.WhiteboxTools()
# wbt.verbose = True
wbt.verbose = False

# Warnings
import warnings
warnings.filterwarnings("ignore", message=".*An exception was ignored while fetching the attribute.*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*`np.object` is a deprecated alias for the builtin `object`.*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*is deprecated. Use tobytes().*", category=DeprecationWarning)
warnings.filterwarnings("ignore")
# warnings.warn("You won't see this warning")
               
# HYDROMODPY MODULES
from watershed import watershed_root, watershed_display, forcing
from watershed.data import climatic
from tools import toolbox, vtk
from groundwater_flow import visualization, modflow_display
from calibration import calib_root, calib_dichotomy, calib_analysis, calib_exploration, calib_basis
fontprop = toolbox.plot_params(8,15,18,20) # small, medium, interm, large

#%% FONCTIONS

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

def cut_polygon_by_line(polygon, line):
    merged = linemerge([polygon.boundary, line])
    borders = unary_union(merged)
    polygons = polygonize(borders)
    return list(polygons)

def perpendicular_line(x, random_point, line_point1, line_point2, get_eq=False):
    m, b = line(0, line_point1, line_point2, True)
    m2 = -1/m
    b2 = random_point[1] - m2*random_point[0]
    if get_eq:
        return m2, b2
    else:
        return m2*x + b2

#%% HYSTFONC

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
            try:
                self.area = polyg_loop.area
            except:
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
            
            '''
            if temporal == False:
                
                fig, ax = plt.subplots(1,1, figsize=(5,5))
                ax.plot(*line_loop.xy, lw=2, color='dodgerblue')
                ax.plot(*line_qmid.xy, ls=':', lw=2, color='grey')
                ax.plot(*line_long.xy, ls='-', lw=2, color='gold')
                ax.plot(*line_oneone.xy, lw=2, color='k')
                ax.plot(*line_perp.xy, ls='--', lw=2, color='gold')
                ax.plot(*line_abs.xy, ls='-', lw=2, color='darkorange')
                ax.plot(np.linspace(abs_min, abs_max, 100),
                        self.reg_stat_reg.intercept[0] + self.slope_reg*np.linspace(abs_min, abs_max, 100),
                        ls='-', lw=2, color='red')
                
                # plt.gca().set_aspect('equal', adjustable='box')
                plt.axis('square')
                plt.xlim(mini, maxi)
                plt.ylim(mini, maxi)
            '''
            
        # self.dfmet.to_csv('Metrics_'+'Obs_'+self.name+'_'+str(space)+'.csv', sep=';')

#%% ---- CATCHMENT

#%% PATH

pc = 'local'

if pc == 'local':
    git_path = "D:/Users/abherve/GITHUB/HydroModPy/CORE_COMM/"
    # Path to the data folder
    data_path = "D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/HYDRODATAPY/HydroDataPy/"
    # Path where the results will be stored
    # out_path = "D:/Users/abherve/SECPAPER/"
    out_path = "C:/Users/ronan/Documents/SIMULATIONS/SECPAPER/"
    # Figure folder outputs
    figsim_folder = 'D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/8_paper/hysteresis/figures/_vf/'
if pc == 'serv':
    git_path = "D:/abherve/GITHUB/HydroModPy/CORE_COMM/"
    # Path to the data folder
    data_path = "D:/abherve/HYDRODATAPY/"
    # Path where the results will be stored
    out_path = "D:/abherve/SECPAPERONELAY/"
    # Figure folder outputs
    figsim_folder = "D:/abherve/SECPAPERONELAY/Figures/"
    
dems_path = data_path + 'DEM/France/' # reginal DEM or conceptual DEM
shp_path = data_path + 'SHAPEFILE/' # if you want run a model from a shapefile
modflow_path = data_path + 'SOFTWARE/MODFLOW/' # add bin/ folder with necessary .exe

# surfex_path =  data_path + 'CLIMATE/France/SURFEX/Brittany/'
surfex_path =  data_path + 'CLIMATE/France/SURFEX/Rennes/' # add surfex models in .h5 format (France scale, else, specify None)
drias_path = data_path + 'CLIMATE/France/DRIAS/Bretagne/'
geology_path = data_path + 'GEOLOGY/France/Layer/' # add geologic layers
oceanic_path = data_path + 'OCEANIC/' # add specific sea level files
hydrology_path = data_path + 'HYDROLOGY/France/Hydrographic/D035/' # add hydrographic shapefiles
hydrometry_path = data_path + 'HYDROLOGY/France/Hydrometry/' # add hydrometry data for automatic download
intermittency_path = data_path + 'HYDROLOGY/France/Intermittency/' # add intermittency data for automatic download
piezometry_path = False # add piezometry data for automatic download
subbasin_path = True # generate subbasins from stations or manual points

dem_name = "BDALTI_bzh_75m.tif" # name of dem
from_shp = None # specify a path if process start from a given shapefile
from_dem = False # True or False if the process start from a given DEM of xyz file
cell_size = None # specify new resolution from a given DEM or None

# Depending on the choices
dem_path = dems_path + dem_name
# import xugrid
# dem_reg = imageio.imread(dem_path)
# section_y = 1200
# section = dem_reg.ugrid.sel(y=section_y)

library_path = git_path + 'watershed/' + 'watershed_library.csv' # each row is a study site with outlet coordinates

watershed_names = ['Canut','Nancon']
code_names = ['J7513010','J0014010']

froms_xy = [[327816.965, 6777886.670, 150, 10],
            [389285.910, 6816518.749, 150, 10]] # 389441.944, 6816812.768 Nancon small

#%% GENERATE

load = True

for watershed_name, from_xy in zip(watershed_names, froms_xy):

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
  
#%% DATA

for watershed_name in watershed_names[:]:
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True)
    BV.add_oceanic(oceanic_path)
    BV.add_hydrometry(hydrometry_path)
    BV.add_intermittency(intermittency_path)
    if not os.path.exists(stable_folder+'climatic/REA.H5'):
        BV.add_surfex(surfex_path)
        # BV.add_drias(drias_path)
    BV.add_geology(geology_path)
    if watershed_name == 'Canut':
        types_obs = ['zh_meuchezecanut','complete','river','perennial'] # list of shapefile name layers for clip hydrology
        fields_obs = ['fid','fid','fid','fid']
    if watershed_name == 'Nancon':
        types_obs = ['zh_couesnon','complete','river','perennial'] # list of shapefile name layers for clip hydrology
        fields_obs = ['fid','fid','fid','fid']
    BV.add_hydrology(hydrology_path, types_obs=types_obs, fields_obs=fields_obs)
    try:
        BV.add_piezometry()
    except:
        pass
    BV.add_subbasin()
    watershed_display.watershed_dem(BV)
    watershed_display.watershed_local(dem_path, BV)
    
#%% ---- RECHARGE

#%% NORMALIZE

recharge = pd.DataFrame()
runoff = pd.DataFrame()

compt=1
for watershed_name in watershed_names[:] :
           
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True)
    BV.add_forcing()

    BV.forcing.update_recharge_surfex(clim_mod = 'REA', clim_sce='historic',
                                  first_year = 1960, last_year=2020,
                                  time_step = 'M',
                                  sim_state='transient') #
    BV.forcing.update_runoff_surfex(clim_mod = 'REA', clim_sce='historic',
                                  first_year = 1960, last_year=2020,
                                  time_step = 'M',
                                  sim_state='transient') #
    
    recharge[str(compt)]=BV.forcing.recharge
    runoff[str(compt)]=BV.forcing.runoff
    
    compt+=1

recharge = recharge.mean(axis=1)
recharge = recharge.rename('REA_historic')
runoff = runoff.mean(axis=1)
runoff = runoff.rename('REA_historic')

fig = plt.subplots(1,1, figsize=(6,3))

dict_recharge = dict(zip(watershed_names, np.empty((2,1))))
dict_runoff = dict(zip(watershed_names, np.empty((2,1))))

for watershed_name in watershed_names[:] :
    
    print(watershed_name)
           
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True)
    BV.add_forcing()
    
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots

    raw_path = stable_folder+'/'+'hydrometry/'
    Qobs_path = fnmatch.filter(os.listdir(raw_path), 'Hydrometric_*')[0]
    Qobs = pd.read_csv(raw_path+Qobs_path, sep=';', index_col=0, parse_dates=True)
    # area = float(Qobs_path.split('_')[-3])
    area = BV.geographic.area
    area = int(round(area))
    print(area)
    Qobs = (Qobs / (area*1000000)) * (3600 * 24) # m3/s to m/day
    Qobs = Qobs.squeeze()
    Qobs = Qobs.resample('M').mean() # m/day in monthly
    tmin_Q = Qobs.first_valid_index().year+1
    tmax_Q = Qobs.last_valid_index().year-1
    
    # BV.forcing.update_recharge_surfex(clim_mod = 'REA', clim_sce='historic',
    #                               first_year = 1960, last_year=2020,
    #                               time_step = 'M',
    #                               sim_state='transient') #
    # BV.forcing.update_runoff_surfex(clim_mod = 'REA', clim_sce='historic',
    #                               first_year = 1960, last_year=2020,
    #                               time_step = 'M',
    #                               sim_state='transient') #
    # Rraw = BV.forcing.recharge
    # rraw = BV.forcing.runoff
    
    Rraw = recharge.copy()
    rraw = runoff.copy()
    tmin_R = Rraw.first_valid_index().year+1
    tmax_R = Rraw.last_valid_index().year-1
    
    year_min = max(tmin_Q, tmin_R)
    year_max = min(tmax_Q, tmax_R)
    
    Qobs_sel = select_period(Qobs, year_min, year_max)
    # print(Qobs_sel.mean() * 365 * 1000)

    R_sel = select_period(Rraw, year_min, year_max)
    r_sel = select_period(rraw, year_min, year_max)
    
    Fnorm = Qobs_sel.mean() / (R_sel.mean() + r_sel.mean())
    print(Fnorm)
    
    R_norm = R_sel * Fnorm
    r_norm = r_sel * Fnorm
    
    # fig = plt.subplots(1,1, figsize=(6,3))
    plt.plot(R_norm+r_norm)
    # plt.plot(r_norm)
    plt.yscale('log')
    
    R_norm = select_period(R_norm, 1990, 2019)
    r_norm = select_period(r_norm, 1990, 2019)
    
    dict_recharge[watershed_name] = R_norm
    dict_runoff[watershed_name] = r_norm
    
    print((R_norm).mean() * 365 * 1000)
    
#%% ---- CALIB
    
#%% DICHOTOMY STREAMS

for watershed_name in watershed_names :
    
    if watershed_name == 'Canut':
        types_obs = ['zh_streams_canut_nancon','complete','perennial'] # list of shapefile name layers for clip hydrology
        fields_obs = ['fid','fid','fid']
    if watershed_name == 'Nancon':
        types_obs = ['zh_streams_canut_nancon','complete','perennial'] # list of shapefile name layers for clip hydrology
        fields_obs = ['fid','fid','fid']
        
    df = pd.DataFrame(np.nan, index=range(1), columns=types_obs)
    
    for type_obs, field_obs in zip(types_obs, fields_obs):
   
        print('##### '+watershed_name.upper()+' #####')
        
        BV = watershed_root.Watershed(watershed_name=watershed_name,
                                      dem_path=dem_path, 
                                      out_path=out_path,
                                      load=True,
                                      modflow_path=modflow_path)
        stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
        
        BV.add_hydrology(hydrology_path, types_obs=[type_obs], fields_obs=[field_obs])

        BV.add_forcing()
        BV.forcing.update_recharge(dict_recharge[watershed_name], sim_state='steady')
        
        BV.add_hydrodynamic()
        BV.hydrodynamic.update_nlay(6)
        BV.hydrodynamic.update_thickness(30)
        BV.hydrodynamic.update_bottom(None)
        BV.hydrodynamic.update_cond_decay(0)
        BV.hydrodynamic.update_thick_exp(1)
        
        params_df = pd.DataFrame(columns=['params',
                                          'init_values','lower_bounds','higher_bounds',
                                          'units','scale'])
        params_df.loc[0] = ['k1',8.64e-01,8.64e-03,8.64e+01,'m/j','lin']
        params_file = 'calib_dicot_hom_1v_k1_'+type_obs
        params_df.to_csv(BV.calibration_folder+'/'+params_file+'.csv', sep=';', index=None)
        calib = calib_root.Calibration(params_file, BV, observations = ['streams'])
        
        # dicot = calib.dichotomy(gap=1)

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
                
        df.loc[0,type_obs] = koptim / 24 / 3600
        df.loc[1,type_obs] = kr
        df.loc[2,type_obs] = obj_func
        
    df.to_csv(BV.calibration_folder+'/'+watershed_name+'_koptims_dichotomy_streams.csv', sep=';')
    df = pd.read_csv(BV.calibration_folder+'/'+watershed_name+'_koptims_dichotomy_streams.csv', sep=';')

#%% EXPLORATION DISCHARGE

modflow_path = data_path + 'SOFTWARE/MODFLOW/'

for watershed_name in watershed_names[:] :
    print('##### '+watershed_name.upper()+' #####')
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots    
    BV.add_forcing()
    BV.add_hydrodynamic()

    BV.forcing.update_recharge(dict_recharge[watershed_name], sim_state='transient')
    BV.forcing.update_runoff(dict_runoff[watershed_name], sim_state='transient')
    
    nlay = 1
    bottom = None
    cond_decay = 0
    thick_exp = 1
    thickness = 30
        
    BV.hydrodynamic.update_nlay(nlay) # 1
    BV.hydrodynamic.update_bottom(bottom) # None
    BV.hydrodynamic.update_cond_decay(cond_decay) # 0
    BV.hydrodynamic.update_thick_exp(thick_exp) # 1
    BV.hydrodynamic.update_thickness(thickness) # 30 / intervient pas si bottom != None

    params_df = pd.DataFrame(columns=['params',
                                      'init_values','lower_bounds','higher_bounds',
                                      'units','scale'])
    if watershed_name == 'Canut':
        params_df.loc[0] = ['k1', 0, 1e-8*86400, 1e-2*86400, 'm/j', 'lin']
        params_df.loc[1] = ['n1', 0, 0.1/100, 10/100, 'm/j', 'lin']
    if watershed_name == 'Nancon':
        params_df.loc[0] = ['k1', 0, 1e-8*86400, 1e-2*86400, 'm/j', 'lin']
        params_df.loc[1] = ['n1', 0, 0.1/100, 10/100, 'm/j', 'lin']
        
    params_file = 'calib_explo_hom_2v_k1-n1'
    params_df.to_csv(BV.calibration_folder+'/'+params_file+'.csv', sep=';', index=None)
    
    calib = calib_root.Calibration(params_file, BV, observations = ['hydrometry'])
    calib.exploration(resolution=1)
    
#%% ---- MODEL
    
#%% MODELING CALIBRATED

# iD = 'test'
# iD = 'calibrated1'
iD = 'calibrated2'

# Options
sim_state = 'transient' # 'steady' or 'transient'
modpath_sim = False # run modpath particle tracking if True
run = True
time_step = 'M' # or 'D'
actual_date = True # False if date is conceptual
box = False # if True generate a rectangular model
sink_fill = False # permit to fill sinks
verbose = True # add print of MODFLOW in console
post_process = False # necessary to decompose post process of process    
init_rech = 'mean'

compt = 0

for watershed_name in watershed_names[:]:
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
    
    # Recharge and runoff
    mod = 'REA'
    sce = 'historic'
    recharge = dict_recharge[watershed_name]
    runoff = dict_runoff[watershed_name]
    BV.forcing.update_recharge(recharge, sim_state='transient')
    BV.forcing.update_runoff(runoff, sim_state='transient')
    
    # Store results
    list_model_name = []
    list_of_success = []
    list_flow_model = []

    nlay = 6
    bottom = None
    cond_decay = 0
    thick_exp = 1
    thickness = 30
    
    calib_dicot = pd.read_csv(BV.calibration_folder+'/'+watershed_name+'_koptims_dichotomy_streams.csv', sep=';')
    print('{:.2e}'.format(calib_dicot.perennial[0]))
    
    if watershed_name=='Canut':
        # Sy_optim = 0.2
        Sy_optim = 0.1
    if watershed_name=='Nancon':
        Sy_optim = 2.0
    
    hyd_cond = [5.5e-5 * 86400]
    porosity = [Sy_optim / 100]
    print(watershed_name, porosity)

    for K, Sy in zip(hyd_cond, porosity):
    
        BV.hydrodynamic.update_nlay(nlay) # 1
        BV.hydrodynamic.update_bottom(bottom) # None
        BV.hydrodynamic.update_cond_decay(cond_decay) # 0
        BV.hydrodynamic.update_thick_exp(thick_exp) # 1
        BV.hydrodynamic.update_thickness(thickness) # 30 / intervient pas si bottom != None
        BV.hydrodynamic.update_hyd_cond(K) 
        BV.hydrodynamic.update_porosity(Sy)
          
        date_today = datetime.now().strftime("%d/%m/%Y %H:%M:%S") # just a string
        date_today = date_today.replace('/','-')
        date_today = date_today.replace(':','-')
        date_today = date_today.replace(' ','_')
        
        model_name = iD+'_'+str(compt)+'_'+\
                     mod+'-'+sce+'_'+\
                     str(nlay)+'-'+str(thickness)+'_'+\
                     str(K)+'-'+str(Sy)+'_'+\
                     str(recharge.first_valid_index().year)+'-'+str(recharge.last_valid_index().year)
        
        print(model_name)
    
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

        list_model_name.append(model_name)
        list_of_success.append(success)
        list_flow_model.append(flow_model)
    
        # compt+=1
        
    print(list_of_success)
    
    dictio = {}
    dictio['list_model_name'] = list_model_name
    dictio['list_of_success'] = list_of_success
    dictio['list_flow_model'] = list_flow_model
    h5file = simulations_folder+'/'+'list_'+iD
    
    dd.io.save(h5file, dictio)

#%% POSTPROCESS CALIBRATED

iD = 'calibrated2'

for watershed_name in watershed_names[:] :
    
    print('##### '+watershed_name.upper()+' #####')
    
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' 
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)

    h5file = simulations_folder+'/'+'list_'+iD
    d = dd.io.load(h5file)
    list_model_name = d['list_model_name'][:]
    list_of_success = d['list_of_success'][:]
    list_flow_model = d['list_flow_model'][:]
    
    for model_name, success, flow_model in zip(list_model_name, list_of_success, list_flow_model):
            
        if success==True:
                print(success)
                                
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
                                  perenn_intermit_shp = True,
                                  groundwater_storage = True,
                                  residence_times = False,
                                  verbose = True,
                                  export_tif = True)
                
                # # Extract results
                BV.results_modflow(ident=model_name,
                                   recharge=dict_recharge[watershed_name],
                                   runoff=dict_runoff[watershed_name],
                                   actual_date=True,
                                   time_step='M')
                
#%% MODELING SENSITIVITY

# iD = 'test'
iD = 'matrix1'

# Options
sim_state = 'transient' # 'steady' or 'transient'
modpath_sim = False # run modpath particle tracking if True
run = False
time_step = 'M' # or 'D'
actual_date = True # False if date is conceptual
box = False # if True generate a rectangular model
sink_fill = False # permit to fill sinks
verbose = True # add print of MODFLOW in console
post_process = False # necessary to decompose post process of process    
init_rech = 'mean'

for watershed_name in watershed_names[1:]:
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
    
    # Recharge and runoff
    mod = 'REA'
    sce = 'historic'
    recharge = dict_recharge[watershed_name]
    runoff = dict_runoff[watershed_name]
    BV.forcing.update_recharge(recharge, sim_state='transient')
    BV.forcing.update_runoff(runoff, sim_state='transient')
    
    # Store results
    list_model_name = []
    list_of_success = []
    list_flow_model = []

    nlay = 6
    bottom = None
    cond_decay = 0
    thick_exp = 1
    thickness = 30
    
    calib_dicot = pd.read_csv(BV.calibration_folder+'/'+watershed_name+'_koptims_dichotomy_streams.csv', sep=';')
    print('{:.2e}'.format(calib_dicot.perennial[0]))
    
    # if watershed_name=='Canut':
    #     Sy_optim = 0.2
    # if watershed_name=='Nancon':
    #     Sy_optim = 2.0
    
    hyd_cond = [4e-6 * 86400,
                4e-5 * 86400,
                4e-4 * 86400]
    porosity = [0.1 / 100,
                1.0 / 100,
                10.0 / 100]
    print(watershed_name, porosity)

    compt = 0

    for K in hyd_cond:
        
        for Sy in porosity:
    
            BV.hydrodynamic.update_nlay(nlay) # 1
            BV.hydrodynamic.update_bottom(bottom) # None
            BV.hydrodynamic.update_cond_decay(cond_decay) # 0
            BV.hydrodynamic.update_thick_exp(thick_exp) # 1
            BV.hydrodynamic.update_thickness(thickness) # 30 / intervient pas si bottom != None
            BV.hydrodynamic.update_hyd_cond(K) 
            BV.hydrodynamic.update_porosity(Sy)
              
            date_today = datetime.now().strftime("%d/%m/%Y %H:%M:%S") # just a string
            date_today = date_today.replace('/','-')
            date_today = date_today.replace(':','-')
            date_today = date_today.replace(' ','_')
            
            model_name = iD+'_'+str(compt)+'_'+\
                         mod+'-'+sce+'_'+\
                         str(nlay)+'-'+str(thickness)+'_'+\
                         str(round(K,2))+'-'+str(Sy)+'_'+\
                         str(recharge.first_valid_index().year)+'-'+str(recharge.last_valid_index().year)
            
            print(model_name)

            success, flow_model = BV.run_modflow(run=False,
                                                  ident=model_name,
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
    
            list_model_name.append(model_name)
            list_of_success.append(success)
            list_flow_model.append(flow_model)
        
            compt+=1
        
    print(list_of_success)
    
    dictio = {}
    dictio['list_model_name'] = list_model_name
    dictio['list_of_success'] = list_of_success
    dictio['list_flow_model'] = list_flow_model
    h5file = simulations_folder+'/'+'list_'+iD
    
    dd.io.save(h5file, dictio)

#%% POSTPROCESS SENSITIVITY

iD = 'matrix1'

for watershed_name in watershed_names[1:] :
    
    print('##### '+watershed_name.upper()+' #####')
    
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' 
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)

    h5file = simulations_folder+'/'+'list_'+iD
    d = dd.io.load(h5file)
    list_model_name = d['list_model_name'][:]
    list_of_success = d['list_of_success'][:]
    list_flow_model = d['list_flow_model'][:]
    
    list_of_success[-3] = False
    list_of_success[-2] = False
    
    for model_name, success, flow_model in zip(list_model_name, list_of_success, list_flow_model):
        
        if success==True:
            print(success)
                              
            flow_model.dem_path = stable_folder+'geographic/watershed_buff_dem.tif'
            print(flow_model.dem_path)
            
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
                              perenn_intermit_shp = True,
                              groundwater_storage = True,
                              residence_times = False,
                              verbose = True,
                              export_tif = True)
            
            # # Extract results
            BV.results_modflow(ident=model_name,
                               recharge=dict_recharge[watershed_name],
                               runoff=dict_runoff[watershed_name],
                               actual_date=True,
                               time_step='M')

#%% ---- PLOT

#%% OBSERVED DISCHARGE

watershed_names = ['Canut','Nancon']
code_names = ['J7513010','J0014010']

first = 1990
last = 2019
# one = 2001

for watershed_name, code_name in zip(watershed_names[:], code_names[:]) :
       
    if watershed_name == 'Gael':
        series_path = out_path + '_data/' +'export_hydro_series_gael.csv'
        series = pd.read_csv(series_path, sep=';', index_col = 4, parse_dates= True)
        series = series.iloc[1:]
        series.index.name = None
        series.index = pd.to_datetime(series.index)
        series['<ResObsElaborHydro>'] = pd.to_numeric(series['<ResObsElaborHydro>'])
    
    print('##### '+watershed_name.upper()+' #####')
    
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True)
    area = BV.geographic.area
    
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    Qobs_path = glob.glob(stable_folder+'hydrometry/'+'Hydrometric_'+'*')[0]
    naming = Qobs_path.split('\\')[-1]
    
    Qobs = pd.read_csv(Qobs_path, sep=';', index_col=0, parse_dates=True)
    # area = float(Qobs_path.split('_')[-3])
    Qobs = Qobs.squeeze()
    Qobs = Qobs.rename('Q')
    
    Qobs = select_period(Qobs, first, last)
    
    print(Qobs.min() / (area*1000000) * (3600 * 24) * 1000)
    # print(Qobs.max() / (area*1000000) * (3600 * 24) * 1000)
    # print(Qobs.min() / (area*1000000) * (3600 * 24) * 1000)

    Qobs = (Qobs / (area*1000000)) * (3600 * 24) * 1000 # m3/s to mm/j
    
    data_index = Qobs.copy()

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
    mean_interan_days['std'] = std_interan_days
    mean_interan_days['q10'] = q10_interan_days
    mean_interan_days['q90'] = q90_interan_days
    mean_interan_days['q50'] = q50_interan_days
    mean_interan_days.index.names = ['months','days']
    mean_interan_days = mean_interan_days.reset_index()
    # mean_interan_days.months = mean_interan_days.months.replace(
    #                                     [10,11,12,1,2,3,4,5,6,7,8,9],
    #                                     [1,2,3,4,5,6,7,8,9,10,11,12])
    mean_interan_days = mean_interan_days.sort_values(['months','days'])
    mean_interan_days['counts'] = np.array(range(1,len(mean_interan_days)+1))
    # mean_interan_days.q10 = mean_interan_days.q10.replace(0,0.01)
    
    fig, ax = plt.subplots(figsize=(4,3))
    # ax.plot(mean_interan_days.counts, mean_interan_days[station+'_mmm'],
    #         lw=1, color='red', label='Mean')
    ax.plot(mean_interan_days.counts, mean_interan_days.q50,
            lw=2, color='k', label='Median')
    yerrmax = mean_interan_days.q90
    yerrmin = mean_interan_days.q10
    # ax.fill_between(mean_interan_days.counts, yerrmin, yerrmax,
    #                   color='cyan',edgecolor='grey',
    #                   alpha = 0.5, label='10-90th')
    ax.fill_between(mean_interan_days.counts, yerrmin, yerrmax,
                      color='gray',edgecolor='grey',
                      alpha = 0.5, label='10-90th')
    plt.yscale('log')
    # ax.yaxis.set_major_formatter(ScalarFormatter())
    ax.set_xlim(0,366)
    ax.set_ylim(0.01,10)
    ax.tick_params(axis='both', which='major', pad=10)
    x1 = np.linspace(0,366,13)
    squad = ['J','F','M','A','M','J','J','A','S','O','N','D','J']
    ax.set_xticks(x1)
    ax.set_xticklabels(squad, minor=False, rotation='horizontal')
    ax.set_xlabel('Months', labelpad=+10)
    ax.set_ylabel('Q / A [mm/d]',labelpad=+10)
    # ax.set_title(watershed_name + ' [' + str(first) + ' to ' + str(last) + ']')
    # ax.grid(color='grey', lw=0.5, zorder=0)
    """
    one = 2001
    dates = np.array([one],dtype=np.int64)
    colors = ['blue']
    for z in np.array(range(len(dates))):
        onlyone = data_index[(data_index.index.year==dates[z])].to_frame()
        onlyone = onlyone.groupby([onlyone.index.month,
                                    onlyone.index.day], as_index=True).mean()
        onlyone['counts'] = np.array(range(1,len(onlyone)+1))
        ax.plot(onlyone.counts, onlyone['Q'],
                color=colors[z], lw=1, label = str(dates[z]))
    one = 2003
    dates = np.array([one],dtype=np.int64)
    colors = ['red']
    for z in np.array(range(len(dates))):
        onlyone = data_index[(data_index.index.year==dates[z])].to_frame()
        onlyone = onlyone.groupby([onlyone.index.month,
                                    onlyone.index.day], as_index=True).mean()
        onlyone['counts'] = np.array(range(1,len(onlyone)+1))
        ax.plot(onlyone.counts, onlyone['Q'],
                color=colors[z], lw=1, label = str(dates[z]))
    """
    # ax.legend(loc='upper left')
    plt.tight_layout()
    # fig.savefig(path + 'plot_figures/' + site + '/' + 'regime' + '.png', dpi=300, bbox_inches='tight')
    
    base_name = figsim_folder+'01_location/'
    spec_name = watershed_name+'_observedQ'
    fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight')

#%% 2DOBJFCT DISCHARGE

sat_typ = 'surflow_areas'

params_file = 'calib_explo_hom_2v_k1-n1'

wish = 0

for watershed_name in watershed_names[:]:
    
    print('##### '+watershed_name.upper()+' #####')

    min_nse = 50
    mean_meansat = 3 # sup
    min_maxsat = 8
    max_maxsat = 25
    
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True)

    typ_calib = 'hydrometry_calibration'
    list_path = sorted(glob.glob(os.path.join(BV.calibration_folder, params_file, typ_calib, '*.calib')),
                        key=os.path.getmtime, reverse=True)
    name_file = list_path[wish].split('\\')[-1]
    calib_file = os.path.join(BV.calibration_folder, params_file, typ_calib, name_file)
    test = calib_analysis.CalibAnalysis(calib_file)
    
    df = pd.read_csv(BV.calibration_folder+'/'+watershed_name+'_koptims_dichotomy_streams.csv', sep=';')

    # test.display_objective_function(save=None)
    # test.find_best_values()
    # test.display_best_data()
    
    sim_res=test.sim_results
    print(sim_res)
    
    typ_name = typ_calib.split('_')[0]
    
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
        sat = test.sim_results[synt[t]][sat_typ]
        sat = pd.to_numeric(sat, errors='coerce').isnull()
        rsat.append(sat.mean())
    
    nse_good = []
    sat_good = []
    
    numb = 0
    for i in range(len(obs[typ_name])):
        o = obs[typ_name][i] * 1000 * 30 # m/j to mm/month
        s = sim[typ_name][i] * 1000 * 30 # m/j to mm/month
        nd = ind[typ_name][i]
        sat = test.sim_results[synt[i]][sat_typ]
        sat = pd.to_numeric(sat, errors='coerce')
        
        k = '{:.1e}'.format(float(synt[i].split(';')[0])/24/3600)
        sy = float(synt[i].split(';')[1]) * 100
        title = 'Discharge [mm/month]'
        nselog = round(((nd[0]))*100,1)
        label = 'K = '+k+' m/s'+' ; '+'ɸ = '+str(round(sy,1))+'% ; '+\
                '$NSE_{log}$ = '+str(nselog)+'%'
        nse_good.append(str(k)+'_'+str(sy)+'_'+str(nselog))
        if nselog > min_nse:
            # if all(i <= 50 for i in sat):
            if sat.max() < max_maxsat:
                if sat.max() > min_maxsat:
                    numb += 1
                # c = []
                # for h in range(len(ind[typ_name])):
                #     d = ind[typ_name][h][0]
                #     c.append(d)
        
        c = np.linspace(0,1,len(obs[typ_name]))

        # cmap = mpl.cm.get_cmap('viridis_r')
        # color_gradients = cmap(c)
        # vmin = min(c)
        # vmax = max(c)
        # norm = mpl.colors.Normalize(vmin=vmin, vmax=vmax)

    fig, ax = plt.subplots(1,1, figsize=(3.8,3.5))
    ax.set_aspect('auto')
    ax.axes.tick_params(which='both', direction='out', zorder=10)
    X,Y = np.meshgrid(test.params_values[0], test.params_values[1])
    Z=test.obj_function.copy()
    Z[Z<0] = 0
    from numpy import inf
    Z[Z == inf] = 0
    bounds = np.arange(0,1.1,0.1)
    norm = mpl.colors.Normalize(vmin=-1, vmax=1.0)
    cmap = 'jet'
    cmap = 'RdYlGn'
    # pc = ax.pcolormesh(X,Y,Z, cmap='jet', shading='gouraud', vmin=0, vmax=1) #figadd.cmap_white_jet()
    pc = ax.contourf(X/3600/24, Y*100, Z,
                      levels=np.arange(0,1.05,0.05), 
                      alpha=0.5, ec='none', cmap=cmap)    
    ax.contour(X/3600/24, Y*100, Z,
                      levels=np.arange(0,1.05,0.05), 
                      alpha=0.5, ec='none', cmap=cmap)    
    # pc = ax.pcolormesh(X/3600/24,Y*100,Z, cmap='jet', shading='gouraud', vmin=0, vmax=1)   
    
    CS = plt.contour(X/3600/24, Y*100, Z,
                      levels=[0.7], 
                      alpha=1, cmap=mpl.colors.ListedColormap('k'), linestyles=':',
                      linewidths=2)
    # ax.clabel(CS, inline=True, fontsize=0)
    
    # divider = make_axes_locatable(ax)
    # cax = divider.append_axes('right', size='5%', pad=0.05)
    
    
    position=fig.add_axes([1.05,0.33,0.03,0.5])  ##
    cb = fig.colorbar(pc, cax=position, orientation='vertical')
    cb.set_ticks(np.arange(0, 1.1, 0.2))
    cb.set_ticklabels(np.round(np.arange(0,1.1,0.2),1)) 
    cb.set_label('$NSE_{log}$ [-]', rotation=270, labelpad=40)
    cb.ax.tick_params(top=True,
                bottom=True,
                left=False,
                right=False,
                labelleft=False,
                labelbottom=True)
    
    
    ax.set_xscale('log')
    ax.set_yscale('log')
    ax.set_ylabel('θ [%]')
    ax.set_xlabel('K [m/s]')
    # ax.set_yticks(np.arange(0,11,2))
    # ax.set_yticklabels(np.arange(0,11,2))
    # ax.tick_params(direction='in')
    ax.tick_params(top=True,
               bottom=True,
               left=True,
               right=False,
               labelleft=True,
               labelbottom=True)
    
    plt.tight_layout()

    """
    X,Y = np.meshgrid(test.params_values[0], test.params_values[1])
    Z = np.empty((3,3,))
    Z[:] = np.nan
    p1 = test.params_values[0]
    p2= test.params_values[1]
    sim_sat = np.zeros((len(p1),len(p2)))
    
    compt=0
    for i in range(len(p1)):
        for j in range(len(p2)):
            temp = [p1[i],p2[j]]
            string = str(p1[i])+';'+str(+p2[j])
            try:
                sim_sat[j][i] = pd.to_numeric(sim_res[string][sat_typ], errors='coerce').min()
            except:
                sim_sat[j][i] = np.nan
                pass
            compt += 1
    Zmin = sim_sat
    
    compt=0
    for i in range(len(p1)):
        for j in range(len(p2)):
            temp = [p1[i],p2[j]]
            string = str(p1[i])+';'+str(+p2[j])
            try:
                sim_sat[j][i] = pd.to_numeric(sim_res[string][sat_typ], errors='coerce').mean()
            except:
                sim_sat[j][i] = np.nan
                pass 
            compt += 1
    Zmean = sim_sat
    
    compt=0
    for i in range(len(p1)):
        for j in range(len(p2)):
            temp = [p1[i],p2[j]]
            string = str(p1[i])+';'+str(+p2[j])
            try:
                sim_sat[j][i] = pd.to_numeric(sim_res[string][sat_typ], errors='coerce').median()
            except:
                sim_sat[j][i] = np.nan
                pass 
            compt += 1
    Zmed = sim_sat
    
    compt=0
    for i in range(len(p1)):
        for j in range(len(p2)):
            temp = [p1[i],p2[j]]
            string = str(p1[i])+';'+str(+p2[j])
            try:
                sim_sat[j][i] = pd.to_numeric(sim_res[string][sat_typ], errors='coerce').max()
            except:
                sim_sat[j][i] = np.nan
                pass
            compt += 1
    Zmax = sim_sat
    
    Z = Zmax.copy()
    Z[Zmax<min_maxsat] = np.nan
    Z[Zmax>max_maxsat] = np.nan
    Z[Zmean<mean_meansat] = np.nan
    
    Xclip = np.ma.masked_array(X, mask=np.isnan(Z)) /3600/24 # y = y.compress() # y without nan where x has nan's
    Yclip = np.ma.masked_array(Y, mask=np.isnan(Z)) *100    
    
    '''
    ax.scatter(Xclip, Yclip, c=Z, s=20, marker='s', edgecolor='k',
                cmap=mpl.colors.ListedColormap('white'))
    '''
    
    # pc = ax.pcolormesh(X/3600/24, Y*100, Z,
    #                  cmap = mpl.colors.ListedColormap('Grey'),
    #                  alpha=0.5, linewidths=1)
    # pc = ax.contour(X/3600/24, Y*100, Z, levels=np.arange(0,100,5),
    #                  cmap =  mpl.colors.ListedColormap('Grey'),
    #                  alpha=0.75, linewidths=1)
    
    # fig2, ax = plt.subplots(1,1, figsize=(3.8,3.5))
    # pc = ax.contourf(X/3600/24, Y*100, Zmax, cmap='seismic',
    #                   levels=np.arange(0,100,5), alpha=0.75) # mpl.colors.ListedColormap('Grey')
    # ax.set_xscale('log')
    # ax.set_ylabel('Φ [%]')
    # ax.set_xlabel('K [m/s]')
    # ax.tick_params(top=True,
    #            bottom=True,
    #            left=True,
    #            right=False,
    #            labelleft=True,
    #            labelbottom=True)
    # # ax.tick_params(direction='out', axis='both', which='both')
    # # position=fig2.add_axes([1.05,0.2,0.02,0.7])  ## the parameters are the specified position you set 
    # # fig2.colorbar(pc,cax=position)
    """
    
    ax.axvline(df.perennial[0], color='k', lw=1, ls='--')
    # ax.axvline(df.river[0], color='k', lw=2, ls='--')
    ax.axvline(df.complete[0], color='k', lw=1, ls='--')
    try:
        ax.axvline(df.zh_couesnon[0], color='k', lw=2, ls='--')
        ax.axvline(df.zh_meuchezecanut[0], color='k', lw=2, ls='--')
    except:
        pass
    # ax.axvline(df.zh_streams_canut_nancon[0], color='k', lw=1, ls='--')
    
    ax.set_ylim(0.1,10)
    # ax.set_yticks(np.arange(0.1,11,2))
    # ax.set_yticklabels(np.arange(0,10,2))
    
    ax.set_title(watershed_name, pad=10)
    plt.tight_layout()
    
    # fig.savefig(figsim_folder+watershed_name+'_calib2D_map'+'.png', dpi=300, bbox_inches='tight')
    # fig.savefig(fig_path + 'Qmap_NSElog_' +
    #             watershed_name + '.png', dpi=300, bbox_inches='tight')

    base_name = figsim_folder+'02_exploration/'
    spec_name = watershed_name+'_explodischarge'
    fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight')

#%% 2DOBJFCT SATURATION

params_file = 'calib_explo_hom_2v_k1-n1'

wish = 0

sat_typ = 'surflow_areas'
# sat_typ = 'seepage_areas'
# sat_typ = 'prop_ratio'

for watershed_name in watershed_names[1:]:
    
    # fig1, ax1 = plt.subplots(1,1, figsize=(3.8,3.5))

    print('##### '+watershed_name.upper()+' #####')
    
    min_nse = 60
    min_maxsat = 3
    max_maxsat = 25
    
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True)

    typ_calib = 'hydrometry_calibration'
    list_path = sorted(glob.glob(os.path.join(BV.calibration_folder, params_file, typ_calib, '*.calib')),
                        key=os.path.getmtime, reverse=True)
    name_file = list_path[wish].split('\\')[-1]
    calib_file = os.path.join(BV.calibration_folder, params_file, typ_calib, name_file)
    test = calib_analysis.CalibAnalysis(calib_file)
    
    df = pd.read_csv(BV.calibration_folder+'/'+watershed_name+'_koptims_dichotomy_streams.csv', sep=';')
    
    # test.display_objective_function(save=None)
    # test.find_best_values()
    # test.display_best_data()
    
    sim_res=test.sim_results
    for i in sim_res:
        # print(i)
        sim_res[i]['prop_ratio'] = np.nan
    
    typ_name = typ_calib.split('_')[0]
    
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
        sat = test.sim_results[synt[t]][sat_typ]
        sat = pd.to_numeric(sat, errors='coerce').isnull()
        rsat.append(sat.mean())
        # rsat.append(sat.max())

    fig, ax = plt.subplots(1,1, figsize=(3.8,3.5))
    ax.set_title(watershed_name, pad=10)
    
    ax.set_aspect('auto')
    ax.axes.tick_params(which='both', direction='out', zorder=10)
    
    X,Y = np.meshgrid(test.params_values[0], test.params_values[1])
    Z = np.empty((3,3,))
    Z[:] = np.nan
    p1 = test.params_values[0]
    p2= test.params_values[1]
    sim_sat_min = np.zeros((len(p1),len(p2)))
    sim_sat_mean = np.zeros((len(p1),len(p2)))
    sim_sat_median = np.zeros((len(p1),len(p2)))
    sim_sat_max = np.zeros((len(p1),len(p2)))
    sim_sat_var = np.zeros((len(p1),len(p2)))
    sim_sat_std = np.zeros((len(p1),len(p2)))
    sim_wte = np.zeros((len(p1),len(p2)))
    sim_wtd = np.zeros((len(p1),len(p2)))
    
    compt=0
    list_vals = pd.DataFrame()
    for i in range(len(p1)):
        for j in range(len(p2)):
            temp = [p1[i],p2[j]]
            string = str(p1[i])+';'+str(+p2[j])
            try:
                # ax.set_title('SAT MIN [%]')
                if sat_typ == 'prop_ratio':
                    sim_res[string][sat_typ] = pd.to_numeric(sim_res[string]['intermit_areas'], errors='coerce') / pd.to_numeric(sim_res[string]['surflow_areas'], errors='coerce')
                sim_sat_min[j][i] = np.nanmin(pd.to_numeric(sim_res[string][sat_typ], errors='coerce'))
            except:
                pass
            try:
                # ax.set_title('SAT MEAN [%]')
                if sat_typ == 'prop_ratio':
                    sim_res[string][sat_typ] = pd.to_numeric(sim_res[string]['intermit_areas'], errors='coerce') / pd.to_numeric(sim_res[string]['surflow_areas'], errors='coerce')
                sim_sat_mean[j][i] = np.nanmean(pd.to_numeric(sim_res[string][sat_typ], errors='coerce'))
            except:
                pass
            try:
                # ax.set_title('SAT MEAN [%]')
                if sat_typ == 'prop_ratio':
                    sim_res[string][sat_typ] = pd.to_numeric(sim_res[string]['intermit_areas'], errors='coerce') / pd.to_numeric(sim_res[string]['surflow_areas'], errors='coerce')
                sim_sat_median[j][i] = np.nanmedian(pd.to_numeric(sim_res[string][sat_typ], errors='coerce'))
            except:
                pass
            try:
                # ax.set_title('SAT MAX [%]')
                if sat_typ == 'prop_ratio':
                    sim_res[string][sat_typ] = pd.to_numeric(sim_res[string]['intermit_areas'], errors='coerce') / pd.to_numeric(sim_res[string]['surflow_areas'], errors='coerce')
                sim_sat_max[j][i] = np.nanmax(pd.to_numeric(sim_res[string][sat_typ], errors='coerce'))
            except:
                pass
            try:
                # ax.set_title('SAT MAX [%]')
                if sat_typ == 'prop_ratio':
                    sim_res[string][sat_typ] = pd.to_numeric(sim_res[string]['intermit_areas'], errors='coerce') / pd.to_numeric(sim_res[string]['surflow_areas'], errors='coerce')
                sim_sat_var[j][i] = np.nanvar(pd.to_numeric(sim_res[string][sat_typ], errors='coerce'))
            except:
                pass
            try:
                # ax.set_title('SAT MAX [%]')
                if sat_typ == 'prop_ratio':
                    sim_res[string][sat_typ] = pd.to_numeric(sim_res[string]['intermit_areas'], errors='coerce') / pd.to_numeric(sim_res[string]['surflow_areas'], errors='coerce')
                sim_sat_std[j][i] = np.nanstd(pd.to_numeric(sim_res[string][sat_typ], errors='coerce'))
            except:
                pass
            try:
                sim_wte[j][i] = np.nanmean(pd.to_numeric(sim_res[string]['watertable_elevation'], errors='coerce'))
                sim_wtd[j][i] = np.nanmean(pd.to_numeric(sim_res[string]['watertable_depth'], errors='coerce'))
            except:
                pass
            # ax1.plot(pd.to_numeric(sim_res[string]['watertable_depth'], errors='coerce'))
            # print(sim_wtd[j][i])
            
            list_vals.loc[compt, 'K'] = p1[i]
            list_vals.loc[compt, 'P'] = p2[j]
            list_vals.loc[compt, 'Smax'] = sim_sat_max[j][i]
            list_vals.loc[compt, 'Smean'] = sim_sat_mean[j][i]
            list_vals.loc[compt, 'Smed'] = sim_sat_median[j][i]
            list_vals.loc[compt, 'Smin'] = sim_sat_min[j][i]
            list_vals.loc[compt, 'Svar'] = sim_sat_var[j][i]
            list_vals.loc[compt, 'Sstd'] = sim_sat_std[j][i]
            list_vals.loc[compt, 'WTe'] = sim_wte[j][i]
            list_vals.loc[compt, 'WTd'] = sim_wtd[j][i]
            compt += 1

    sim_sat_max[np.isnan(sim_sat_max)] = 0
    sim_sat_min[np.isnan(sim_sat_min)] = 0
    
    # sim_sat_min[sim_sat_min==0] = 1/1e6
    # sim_sat_max[sim_sat_max==0] = 1/100
    # Z = (sim_sat_max / sim_sat_min) # / sim_sat_mean
    Z = (sim_sat_max - sim_sat_min) / sim_sat_mean
    # Z = (sim_sat_median) #/ sim_sat_mean
    # Z = (sim_sat_max - sim_sat_min) / (sim_sat_min)
    # Z = (sim_sat_min) #/ sim_sat_mean
    # Z = (sim_sat_mean)
    # Z = sim_sat_mean
    # Z = np.log10(Z)
    # plt.imshow(sim_sat_max)
    # plt.colorbar()
    
    
    # if watershed_name == 'Canut':
    #     Zobs = (18 - 0) / (5)
    #     Z[11,16] = 0
    # if watershed_name == 'Nancon':
    #     Zobs = (23 - 5) / (10)
    # Z[Z>10] = 10
    # # Z = sim_sat_std
    
    
    # Z[sim_sat_max==0] = 0
    # Z[sim_sat_min==0] = 0
    # Z[sim_sat_max==0] = 0
    # from numpy import inf
    # Z[np.isnan(Z)] = 0
    # Z[Z == np.inf] = 100
    # Z[Z == 0] = 0.1
    # Z[Z>100] = 100
    print(np.nanmin(Z), np.nanmax(Z))
    
    # pc = ax.contour(X/24/3600,Y*100,Z, cmap='jet', alpha=1, lw=2,
    #                  levels=np.arange(0,101,10)) #figadd.cmap_white_jet()    
    
    # pc = ax.pcolormesh(X/24/3600,Y*100,Z, cmap='jet', alpha=0.6,
    #                     # levels=np.arange(0,101,10),
    #                     norm=mpl.colors.LogNorm(vmin=1, vmax=101),
    #                   linewidths=2, shading='auto') #figadd.cmap_white_jet()     levels=np.arange(0,101,10)
    
    # pc = plt.pcolormesh(X/24/3600,Y*100,Z, cmap='jet', alpha=0.6) #figadd.cmap_white_jet()     levels=np.arange(0,101,10)
    # plt.xscale('log')
    # Z[(sim_sat_max==0)&(sim_sat_min==0)] = np.nan
    cmap = "jet"
    cmap = "RdYlGn_r"
    
    pcinf = ax.pcolormesh(X/24/3600,
                          Y*100,
                          (np.isnan(Z)), cmap=mpl.colors.ListedColormap('lightgrey'), alpha=0.5,
                        # levels=np.arange(0,11,1),
                        # norm=mpl.colors.LogNorm(vmin=1, vmax=101),
                      linewidths=0) #figadd.cmap_white_jet()     levels=np.arange(0,101,10)    
    
    # divnorm=mpl.colors.TwoSlopeNorm(vmin=0., vcenter=1., vmax=2)
    # norm = MidPointNorm(midpoint=3)
    # bounds = np.array([0, 1, 2, 3, 4,5,6,7,8,9,10])
    # norm = mpl.colors.BoundaryNorm(boundaries=bounds, ncolors=1)
    pc = ax.contourf(X/24/3600,Y*100, Z, cmap=cmap, alpha=0.5,
                        # levels=np.around(np.geomspace(1, 100, 10)).astype(int),
                        # levels=np.around(np.arange(0, 10, 1)).astype(int),
                        # levels=np.arange(0, 1.1, 0.1),
                        # levels=[0,0.5,1,1.5,2],
                        # norm=mpl.colors.CenteredNorm(),
                            # norm=mpl.colors.LogNorm(),
                        # norm = divnorm,
                            # levels=np.arange(0, 10.5, 1),
                        # levels=np.arange(0, 1.1, 0.1),
                      linewidths=0, ec='none', ls=None)
    
    
    ax.contour(X/24/3600,Y*100, Z, cmap=cmap, alpha=0.5,
                        # levels=np.around(np.geomspace(1, 100, 10)).astype(int),
                        # levels=np.around(np.arange(0, 10, 1)).astype(int),
                        # levels=np.arange(0, 1.1, 0.1),
                        # levels=[0,0.5,1,1.5,2],
                        # norm=mpl.colors.CenteredNorm(),
                            # norm=mpl.colors.LogNorm(),
                        # norm = divnorm,
                            # levels=np.arange(0, 10.5, 1),
                        # levels=np.arange(0, 1.1, 0.1),
                      linewidths=1)
    

    Z2 = (sim_sat_mean)
    # pc2 = ax.contourf(X/24/3600,Y*100,Z2, cmap=mpl.colors.ListedColormap('white'), 
    #                   alpha=0.25, linewidths=0,
    #                   levels=np.linspace(0.5,10,2),
    #                   ) #figadd.cmap_white_jet()
    '''
    pc2 = ax.contourf(X/24/3600,Y*100,Z2, cmap=mpl.colors.ListedColormap('grey'), 
                      alpha=0.25, linewidths=0,
                      levels=np.linspace(0,0.5,2),
                      ) #figadd.cmap_white_jet()
    pc2 = ax.contourf(X/24/3600,Y*100,Z2, cmap=mpl.colors.ListedColormap('grey'), 
                      alpha=0.25, linewidths=0,
                      levels=np.linspace(10,100,2),
                      ) #figadd.cmap_white_jet()   
    pc2 = ax.contour(X/24/3600,Y*100,Z2, cmap=mpl.colors.ListedColormap('k'), alpha=1, linewidths=2,
                      levels=np.linspace(0.5,10,2)
                      ) #figadd.cmap_white_jet()    
    '''
    # ax.contourf(X/24/3600,Y*100, Z2/4, cmap='jet', alpha=0.5,
    #                    norm=mpl.colors.LogNorm(vmin=0.1, vmax=101),
    #                   linewidths=2) #♠mpl.colors.ListedColormap('k')
    # pc = ax.contourf(X/24/3600,Y*100,Z, cmap='jet', alpha=0.6,
    #                   levels=np.arange(0,100,0.5)) #figadd.cmap_white_jet()     levels=np.arange(0,101,10)
    # pc = plt.pcolormesh(X/24/3600,Y*100,Z, cmap='jet', alpha=0.6) #figadd.cmap_white_jet()     levels=np.arange(0,101,10)
    plt.xscale('log')
    
    ax.set_xscale('log')
    # ax.set_yscale('log')
    ax.set_ylabel('θ [%]')
    ax.set_xlabel('K [m/s]')
    
    # Z = sim_sat_mean.copy()
    # Z[Z<1] = np.nan
    # Z[Z>10] = np.nan
    
    '''
    ax.scatter(X/24/3600,Y*100,c=Z, s=20, marker='s', edgecolor='k',
                cmap=mpl.colors.ListedColormap('white'))
    '''
        
    # position=fig.add_axes([1.05,0.2,0.02,0.7])  ## the parameters are the specified position you set 
    # norm = mpl.colors.LogNorm(vmin=1, vmax=100)
    # bounds = np.arange(1,200,5)
    # fig.colorbar(pc, ax=ax, norm=mpl.cm.ScalarMappable(norm=norm), cax=position,
    #              boundaries=bounds)
    
    
    position=fig.add_axes([1.05,0.33,0.03,0.5])  ##
    cb = fig.colorbar(pc, cax=position, orientation='vertical')
    # cb.set_ticks(np.arange(0, 11, 1))
    # cb.set_ticklabels(np.round(np.arange(0,11,1),1)) 
        # cb.set_ticks(np.arange(0, 1.1, 0.1))
        # cb.set_ticklabels(np.arange(0, 1.1, 0.1)) 
    cb.set_label('$A_{diff}$ [-]', rotation=270, labelpad=40)
    cb.ax.tick_params(top=True,
                bottom=True,
                left=False,
                right=False,
                labelleft=False,
                labelbottom=True)
    
    
    # pc = ax.pcolormesh(X/3600/24, Y*100, Z,
    #                   cmap = mpl.colors.ListedColormap('white'),
    #                   alpha=0.5, linewidths=10)
    
    # pc = ax.contourf(X/3600/24, Y*100, Z, cmap=None,
    #                   levels=np.arange(0,100,5), alpha=0.75, linewidths=5,
    #                   colors='k',interpolation='none') # mpl.colors.ListedColormap('Grey')
    
    ax.tick_params(top=True,
               bottom=True,
               left=True,
               right=False,
               labelleft=True,
               labelbottom=True)
    
    ax.axvline(df.perennial[0], color='k', lw=1, ls='--')
    # ax.axvline(df.river[0], color='k', lw=2, ls='--')
    ax.axvline(df.complete[0], color='k', lw=1, ls='--')
    # ax.axvline(df.zh_streams_canut_nancon[0], color='k', lw=1, ls='--')
    
    # position=fig.add_axes([1.05,0.33,0.03,0.5])  ##
    # cb = fig.colorbar(pc, cax=position, orientation='vertical')
    # cb.set_ticks(np.arange(0,101,20)) 
    # cb.set_label('$NSE_{log}$', rotation=270, labelpad=40)
    # cb.ax.tick_params(top=True,
    #             bottom=True,
    #             left=False,
    #             right=False,
    #             labelleft=False,
    #             labelbottom=True)
    
    ax.set_xlim(1e-8, 1e-2)
    ax.set_ylim(0.1,10)
    
    X2,Y2 = np.meshgrid(test.params_values[0], test.params_values[1])
    Z2=test.obj_function.copy()
    Z2[Z2<0] = 0
    from numpy import inf
    Z2[Z2 == inf] = 0
    
    CS = ax.contour(X2/3600/24, Y2*100, Z2,
                      levels=[0.7], 
                      alpha=1, cmap=mpl.colors.ListedColormap('k'),
                      linestyles=':',
                      linewidths=2)  
    
    ax.set_yscale('log')
    
    plt.tight_layout()    
    
    base_name = figsim_folder+'02_exploration/'
    spec_name = watershed_name+'_explosaturation_median'
    # fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight')

#%% 2D SATURATION GRAPH

##### LAUNCH 2DOBJFCT SATURATION #####

# watershed_name = 'Canut'
watershed_name = 'Nancon'

list_vals['Smax'][np.isnan(list_vals['Smax'])] = 0
list_vals['Smin'][np.isnan(list_vals['Smin'])] = 0
# sim_sat_max[np.isnan(sim_sat_max)] = 0
# sim_sat_min[np.isnan(sim_sat_min)] = 0

fig, ax = plt.subplots(1,1, figsize=(4,2), sharex=True, sharey=True)
ax.set_xscale('log')
ax.set_xlim(1e-8, 1e-3)
ax.set_ylim(0, 100)
n = len(list_vals['P'].unique())
colors = pl.cm.RdBu_r(np.linspace(0,1,n))
res = pd.DataFrame()
for txt in ['Smax', 'Smean', 'Smin']:
    for i, p in enumerate(sorted(list_vals['P'].unique(), reverse=False)):
        sel_val = list_vals[np.isin(list_vals['P'], p)]
        # if (i == 0) | (i ==19):
        # ax.plot(sel_val['K']/24/3600, sel_val[txt], c=colors[i], zorder=0, lw=0.1)
        # ax.plot(sel_val['K']/24/3600, sel_val[txt], c='grey', zorder=0, lw=0.1)
        if (i == 0) | (i ==19):
            res['K'] = sel_val['K'].values
            res[txt+'_'+str(i)] = sel_val[txt].values
            res = res.reset_index(drop=True)
zo=2
ax.fill_between(res.K/24/3600, res.Smin_0, res.Smax_0, color='dodgerblue', alpha=0.35, lw=0.5, zorder=zo)
ax.plot(res.K/24/3600, res.Smean_0, c='navy', lw=1.5, zorder=-10)
ax.plot(res.K/24/3600, res.Smax_0, c='navy', lw=1.5, zorder=zo, ls=':')
ax.plot(res.K/24/3600, res.Smin_0, c='navy', lw=1.5, zorder=zo, ls=':')
zo=2
ax.fill_between(res.K/24/3600, res.Smin_19, res.Smax_19, color='red', alpha=0.35, lw=0.5, zorder=zo)
ax.plot(res.K/24/3600, res.Smean_19, c='darkred', lw=1.5, zorder=zo)
ax.plot(res.K/24/3600, res.Smax_19, c='darkred', lw=1.5, zorder=zo, ls=':')
ax.plot(res.K/24/3600, res.Smin_19, c='darkred', lw=1.5, zorder=zo, ls=':')

base_name = figsim_folder+'02_exploration/'
spec_name = watershed_name+'_comparison sensitivity_'+'sat'
fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight', transparent=True)

for txt in ['Smax', 'Smean', 'Smin']:
    for i, p in enumerate(sorted(list_vals['P'].unique(), reverse=False)):
        sel_val = list_vals[np.isin(list_vals['P'], p)]
        # if (i != 0) | (i != 19):
        #     ax.plot(sel_val['K']/24/3600, sel_val[txt], c='grey', zorder=0, lw=0.1)

# cmap = plt.cm.jet_r  # define the colormap
cmap = plt.cm.YlGnBu
# cmap = parula_map
cmaplist = [cmap(i) for i in range(cmap.N)]
# cmaplist = ['skyblue','dodgerblue','navy']
cmaplist = ['navy','darkred']
# cmaplist = ['white','red','gold','forestgreen','dodgerblue','navy']
# cmaplist[0] = (.5, .5, .5, 1.0)
cmap = mpl.colors.LinearSegmentedColormap.from_list('Custom cmap', cmaplist, cmap.N)
bounds = np.arange(0, 1.1, 0.1)
bounds = [-1,0,0.25,0.5,0.75,1,1.1]
norm = mpl.colors.BoundaryNorm(bounds, cmap.N)

list_vals['Snorm'] = list_vals['Sstd'] #/ list_vals['Smean']
list_vals['Snorm'][np.isnan(list_vals['Snorm'])] = 0

fig, ax = plt.subplots(1,1, figsize=(4,2), sharex=True, sharey=True)
ax.set_xscale('log')
ax.set_xlim(1e-8, 1e-3)
# ax.set_ylim(-5, 105)
n = len(list_vals['P'].unique())
colors = pl.cm.jet(np.linspace(0,1,n))
# colors = cmap(np.linspace(0,1,n))
res = pd.DataFrame()
for txt in ['Snorm']:
    for i, p in enumerate(sorted(list_vals['P'].unique(), reverse=False)):
        if i>0:
            sel_preced = list_vals[np.isin(list_vals['P'], sorted(list_vals['P'].unique())[i-1])]
        sel_val = list_vals[np.isin(list_vals['P'], p)]
        # if (i == 0) | (i ==19):
        # ax.plot(sel_val['K']/24/3600, sel_val[txt], c=colors[i], zorder=0, lw=1)
        if i > 0:
            ax.fill_between(sel_val['K']/24/3600, sel_preced[txt], sel_val[txt], color=colors[i], alpha=0.35,
                            lw=0, zorder=zo)
        # ax.plot(sel_val['K']/24/3600, sel_val[txt], c='grey', zorder=0, lw=0.1)
        if (i == 0) | (i ==19):
            res['K'] = sel_val['K'].values
            res[txt+'_'+str(i)] = sel_val[txt].values
            res = res.reset_index(drop=True)
            ax.plot(sel_val['K']/24/3600, sel_val[txt], c=colors[i], zorder=0, lw=1)
ax.set_ylim(0, 35)

base_name = figsim_folder+'02_exploration/'
spec_name = watershed_name+'_comparison sensitivity_'+'std'
fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight', transparent=True)

# cmap = plt.cm.jet_r  # define the colormap
# cmap = plt.cm.YlGnBu
# cmap = parula_map
cmaplist = [cmap(i) for i in range(cmap.N)]
# cmaplist = ['skyblue','dodgerblue','navy']
cmaplist = ['navy','darkred']
# cmaplist = ['white','red','gold','forestgreen','dodgerblue','navy']
# cmaplist[0] = (.5, .5, .5, 1.0)
cmap = mpl.colors.LinearSegmentedColormap.from_list('Custom cmap', cmaplist, cmap.N)
bounds = np.arange(0, 1.1, 0.1)
bounds = [-1,0,0.25,0.5,0.75,1,1.1]
norm = mpl.colors.BoundaryNorm(bounds, cmap.N)


list_vals['Snorm'] = list_vals['Sstd'] / list_vals['Smean']
# list_vals['Snorm'] = (list_vals['Smax'] - list_vals['Smin']) / list_vals['Smean']
list_vals['Snorm'][np.isnan(list_vals['Snorm'])] = 0

fig, ax = plt.subplots(1,1, figsize=(3,2))
ax.set_xscale('log')
ax.set_xlim(1e-7, 2e-4)
# ax.set_ylim(-5, 105)
n = len(list_vals['P'].unique())
colors = pl.cm.jet(np.linspace(0,1,n))
# colors = cmap(np.linspace(0,1,n))
res = pd.DataFrame()
for txt in ['Snorm']:
    for i, p in enumerate(sorted(list_vals['P'].unique(), reverse=False)):
        if i>0:
            sel_preced = list_vals[np.isin(list_vals['P'], sorted(list_vals['P'].unique())[i-1])]
        sel_val = list_vals[np.isin(list_vals['P'], p)]
        # if (i == 0) | (i ==19):
        # ax.plot(sel_val['K']/24/3600, sel_val[txt], c=colors[i], zorder=0, lw=1)
        if i > 0:
            ax.fill_between(sel_val['K']/24/3600, sel_preced[txt], sel_val[txt], color=colors[i], alpha=0.35,
                            lw=0, zorder=zo)
        # ax.plot(sel_val['K']/24/3600, sel_val[txt], c='grey', zorder=0, lw=0.1)
        if (i == 0) | (i ==19):
            res['K'] = sel_val['K'].values
            res[txt+'_'+str(i)] = sel_val[txt].values
            res = res.reset_index(drop=True)
            ax.plot(sel_val['K']/24/3600, sel_val[txt], c=colors[i], zorder=0, lw=1)
ax.set_ylim(0, 1.20)

base_name = figsim_folder+'02_exploration/'
spec_name = watershed_name+'_comparison sensitivity_'+'stdnorm'
fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight', transparent=True)

'''
fig, ax = plt.subplots(1,1, figsize=(3,2))
sc = ax.scatter(list_vals['K']/24/3600, list_vals['Sstd']/list_vals['Smean'], c=list_vals['P'],
                ec='None', s=8, cmap='jet', alpha=0.35)
cbar = fig.colorbar(sc)
cbar.set_ticks(np.arange(list_vals['P'].min(), list_vals['P'].max(), 0.01))
'''

# list_vals['Smax']-list_vals['Smin'])/list_vals['Smean']
# axb.set_xlim(1e-8, 1e-2)
# ax.set_ylim(-5, 105)

# ax.set_yscale('log')

#%% 2D DIFFUSIVITY GRAPH

# watershed_name = 'Canut'
watershed_name = 'Nancon'

dem_mean = imageio.imread('C:/Users/ronan/Documents/SIMULATIONS/SECPAPER/'+watershed_name+'/results_stable/geographic/watershed_dem.tif')
dem_mean[dem_mean<0] = np.nan
dem_mean = np.nanmean(dem_mean)

list_vals['Smax'][np.isnan(list_vals['Smax'])] = 0
list_vals['Smin'][np.isnan(list_vals['Smin'])] = 0

list_vals['Snorm'] = list_vals['Sstd'] / list_vals['Smean']
# list_vals['Snorm'] = (list_vals['Smax'] - list_vals['Smin']) / list_vals['Smean']
list_vals['Snorm'][np.isnan(list_vals['Snorm'])] = 0

# fig, axs = plt.subplots(1,2, figsize=(7,2))
# axs = axs.ravel()
# ax = axs[0]

fig, ax = plt.subplots(1,1, figsize=(4,2))
ax.set_xscale('log')
# ax.set_xlim(1e-7, 2e-4)
# ax.set_ylim(-5, 105)
n = len(list_vals['P'].unique())
colors = pl.cm.jet(np.linspace(0,1,n))
# colors = cmap(np.linspace(0,1,n))
res = pd.DataFrame()
for txt in ['Snorm']:
    for i, p in enumerate(sorted(list_vals['P'].unique(), reverse=False)):
        if i>0:
            sel_preced = list_vals[np.isin(list_vals['P'], sorted(list_vals['P'].unique())[i-1])]
        sel_val = list_vals[np.isin(list_vals['P'], p)]
        sel_val['WTd'][sel_val['WTd']>30] = np.nan
        sel_val['WTd'][sel_val['WTd']<0] = 0
        # if (i == 0) | (i ==19):
        # ax.plot(sel_val['K']/24/3600, sel_val[txt], c=colors[i], zorder=0, lw=1)
        # if i >= 0:
        #     ax.fill_between(sel_val['K']/24/3600, sel_preced[txt], sel_val[txt], color=colors[i], alpha=0.35,
        #                     lw=0, zorder=zo)
        # ax.plot(sel_val['K']/24/3600, sel_val[txt], c='grey', zorder=0, lw=0.1)
        # if (i == 0) | (i ==19):
        res['K'] = sel_val['K'].values
        res[txt+'_'+str(i)] = sel_val[txt].values
        res = res.reset_index(drop=True)
        # ax.scatter((sel_val['K']/24/3600)*(30-sel_val['WTd'])/(sel_val['P']), sel_val[txt], c=colors[i], # 
        #            s=2, zorder=0, lw=1,
        #            # norm=mpl.colors.LogNorm(),
        #            ec='None')
        ax.scatter((sel_val['K']/24/3600)*(30-sel_val['WTd'])/(sel_val['P']), sel_val[txt], cmap=mpl.colors.ListedColormap('k'), # 
                   s=2, zorder=0, lw=1,
                   # norm=mpl.colors.LogNorm())
                   )
        ax.plot((sel_val['K']/24/3600)*(30-sel_val['WTd'])/(sel_val['P']), sel_val[txt], c=colors[i], # 
                    zorder=1, lw=1
                    # norm=mpl.colors.LogNorm()
                    )
ax.set_ylim(0, 1.20)
# ax.set_yscale('log')

base_name = figsim_folder+'02_exploration/'
spec_name = watershed_name+'_diffusivity sensitivity_'+'stdnorm_'+'K'
fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight', transparent=True)

fig, ax = plt.subplots(1,1, figsize=(4,2))
# ax = axs[1]
ax.set_xscale('log')
# ax.set_xlim(1e-7, 2e-4)
# ax.set_ylim(-5, 105)
n = len(list_vals['P'].unique())
colors = pl.cm.jet(np.linspace(0,1,n))
# colors = cmap(np.linspace(0,1,n))
res = pd.DataFrame()
for txt in ['Snorm']:
    for i, p in enumerate(sorted(list_vals['P'].unique(), reverse=False)):
        if i>0:
            sel_preced = list_vals[np.isin(list_vals['P'], sorted(list_vals['P'].unique())[i-1])]
        sel_val = list_vals[np.isin(list_vals['P'], p)]
        # if (i == 0) | (i ==19):
        # ax.plot(sel_val['K']/24/3600, sel_val[txt], c=colors[i], zorder=0, lw=1)
        # if i >= 0:
        #     ax.fill_between(sel_val['K']/24/3600, sel_preced[txt], sel_val[txt], color=colors[i], alpha=0.35,
        #                     lw=0, zorder=zo)
        # ax.plot(sel_val['K']/24/3600, sel_val[txt], c='grey', zorder=0, lw=0.1)
        # if (i == 0) | (i ==19):
        res['K'] = sel_val['K'].values
        res[txt+'_'+str(i)] = sel_val[txt].values
        res = res.reset_index(drop=True)
        # ax.scatter((sel_val['K']/24/3600)*(30-sel_val['WTd'])/(sel_val['P']), sel_val[txt], c=sel_val['K'], # colors[i]
        #            s=3, zorder=0, lw=1,
        #            norm=mpl.colors.LogNorm(),
        #            ec='None')
        ax.scatter((sel_val['K']/24/3600)*(30-sel_val['WTd'])/(sel_val['P']), sel_val[txt],
                   cmap=mpl.colors.ListedColormap('k'), # colors[i]
                   s=2, zorder=0, lw=1,
                   )
n = len(list_vals['K'].unique())
colors = pl.cm.jet(np.linspace(0,1,n))        
for txt in ['Snorm']:
    for i, k in enumerate(sorted(list_vals['K'].unique(), reverse=False)):
        sec_val = list_vals[np.isin(list_vals['K'], k)]
        sec_val['WTd'][sec_val['WTd']>30] = np.nan
        sec_val['WTd'][sec_val['WTd']<0] = 0
        ax.plot((sec_val['K']/24/3600)*(30-sec_val['WTd'])/(sec_val['P']), sec_val[txt], c=colors[i],
                lw=1)

ax.set_ylim(0, 1.20)

base_name = figsim_folder+'02_exploration/'
spec_name = watershed_name+'_diffusivity sensitivity_'+'stdnorm_'+'P'
fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight', transparent=True)
            
# ax.set_ylim(0, 1.20)
# ax.set_yscale('log')

#%% STREAMFLOW

iD = 'calibrated2'

for watershed_name in watershed_names[:]:
    print('##### '+watershed_name.upper()+' #####')
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' 
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)
    
    BV.add_forcing()
    BV.forcing.update_recharge(dict_recharge[watershed_name], sim_state='transient')
    BV.forcing.update_runoff(dict_runoff[watershed_name], sim_state='transient')
    # BV.add_intermittency(intermittency_path)
    
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    raw_path = stable_folder+'/'+'hydrometry/'
    Qobs_path = fnmatch.filter(os.listdir(raw_path), 'Hydrometric_*')[0]
    Qobs = pd.read_csv(raw_path+Qobs_path, sep=';', index_col=0, parse_dates=True)
    area = int(round(BV.geographic.area))
    Qobs = (Qobs / (area*1000000)) * (3600 * 24 * 30) * 1000  # m3/s to mm/month
    Qobs = Qobs.squeeze()
    Qobs = select_period(Qobs, 1990, 2019)
    Qobs = Qobs.resample('M').mean()
    
    simul_list = sorted(glob.glob(simulations_folder+iD+'*'), key=os.path.getmtime)
    
    for simul in simul_list:
        model_name = simul.split('\\')[-1]

        Smod_path = simul+'/_watershed/_simulated_results.csv'
        Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
        
        Qmod = Smod['outflow_drain'] 
        Qmod = Qmod.squeeze() * 1000 * 30
        Qmod = Qmod + (BV.forcing.runoff * 1000 * 30)
        
        Rmod = Smod['recharge'] * 1000 * 30
        
        ###########################################
        fig, ax = plt.subplots(1,1, figsize=(3,3))
        ax.scatter(select_period(Qobs,1990,2019),select_period(Qmod,1990,2019),
                   s=25, edgecolor='none', alpha=0.75, facecolor='forestgreen')
        ax.set_xscale('log')
        ax.set_yscale('log')
        ax.plot((0.1,1000),(0.1,1000), color='grey', zorder=-1)
        if watershed_name == 'Canut':
            ax.set_xlim(0.1,200)
            ax.set_ylim(0.1,200)
        if watershed_name == 'Nancon':
            ax.set_xlim(5,200)
            ax.set_ylim(5,200)
        # ax.set_xlim(0.1,300)
        # ax.set_ylim(0.1,300)    
        ax.set_xlabel('$Q_{obs}$ / A [mm/month]')
        ax.set_ylabel('$Q_{sim}$ / A [mm/month]')
        
        base_name = figsim_folder+'04_calibrated/'
        spec_name = watershed_name+'_observed_vs_simulated'
        fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight')
        
        ###########################################
        fig, ax = plt.subplots(1,1, figsize=(7,3))
        yearsmaj = mdates.YearLocator(5)   # every year
        yearsmin = mdates.YearLocator(1)
        # monthsmaj = mdates.MonthLocator(6)  # every month
        # monthsmin = mdates.MonthLocator(3)
        # months_fmt = mdates.DateFormatter('%m') #b = name of month ?
        years_fmt = mdates.DateFormatter('%Y')
    
        ax.set_ylabel('Q / A [mm/month]')
        axb = ax.twinx()
        axb.set_ylabel('R [mm/month]', rotation=270, labelpad=25)
        axb.bar(Rmod.index, Rmod,
                color='blue', edgecolor='blue', lw=2.5)
        axb.set_ylim(0,999)
        axb.invert_yaxis()
        axb.set_yticklabels([0,200])
        # axb.xaxis.set_major_formatter_locator(yearsmaj)
        # axb.xaxis.set_minor_locator(yearsmin)
        # axb.xaxis.set_major_formatter(years_fmt)
        # ax.plot(R, color='k', lw=2, label='recharge')
        ax.xaxis.set_major_locator(yearsmaj)
        ax.xaxis.set_minor_locator(yearsmin)
        ax.xaxis.set_major_formatter(years_fmt)
        ax.plot(Qobs, color='k', lw=2, ls='-', zorder=0, label='observed')
        # ax.set_yscale('log')
        ax.plot(Qmod, color='red', lw=2, label='modeled')
        ax.set_ylim(0.11,200)
        # ax.grid('grey')
        # ax.set_title('Discharge')
        # ax.set_xlim(pd.to_datetime('1986'))
        ax.set_xlim(pd.to_datetime('1990'), pd.to_datetime('2020'))
        # ax.set_yscale('log')
 
        import hydroeval as he
        nse = he.evaluator(he.nse, select_period(Qmod,1990,2019), Qobs)[0]
        nselog = he.evaluator(he.nse, select_period(Qmod,1990,2019), Qobs, transform='log')[0]
        rmse = np.sqrt(np.nanmean((Qobs-select_period(Qmod,1990,2019))**2))
        KGE = he.evaluator(he.kge, select_period(Qmod,1990,2019), Qobs)[0][0]
        print(round(nse,2))
        print(round(nselog,2))
        print(round(rmse,2))
        print(round(KGE,2))
        
        base_name = figsim_folder+'04_calibrated/'
        spec_name = watershed_name+'_chronicQ'
        # fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight')

#%% ONDE

iD = 'calibrated1'

for watershed_name in watershed_names[:]:
    print('##### '+watershed_name.upper()+' #####')
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' 
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)
    
    BV.add_forcing()
    BV.forcing.update_recharge(dict_recharge[watershed_name], sim_state='transient')
    BV.forcing.update_runoff(dict_runoff[watershed_name], sim_state='transient')
    # BV.add_intermittency(intermittency_path)
    
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    raw_path = stable_folder+'/'+'hydrometry/'
    Qobs_path = fnmatch.filter(os.listdir(raw_path), 'Hydrometric_*')[0]
    Qobs = pd.read_csv(raw_path+Qobs_path, sep=';', index_col=0, parse_dates=True)
    area = int(round(BV.geographic.area))
    Qobs = (Qobs / (area*1000000)) * (3600 * 24 * 30) * 1000  # m3/s to mm/month
    Qobs = Qobs.squeeze()
    Qobs = select_period(Qobs, 1990, 2019)
    Qobs = Qobs.resample('M').mean()
    
    simul_list = sorted(glob.glob(simulations_folder+iD+'*'), key=os.path.getmtime)
    
    for simul in simul_list:
        model_name = simul.split('\\')[-1]

        Smod_path = simul+'/_watershed/_simulated_results.csv'
        Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
        
        Qmod = Smod['outflow_drain'] 
        Qmod = Qmod.squeeze() * 1000 * 30
        Qmod = Qmod + (BV.forcing.runoff * 1000 * 30)
        
        Rmod = Smod['recharge'] * 1000 * 30
        
        Sonde_path = glob.glob(simul+'/_subbasins/intermittency_*')[0]+'/_simulated_results.csv'
        Sonde = pd.read_csv(Sonde_path, sep=';', index_col=0, parse_dates=True)
        # Smod = Sonde.copy()-0.6
        # Smod['perenn_areas'] = Smod['perenn_areas']-0.5
        
        d = BV.intermittency.flowing
        assec = d[d==1].dropna()
        invi = d[d==2].dropna()
        low = d[d==3].dropna()
        accep = d[d==4].dropna()
        visib = d[d==5].dropna()
        d = d.resample('M').mean()
        
        Smod['onde'] = d
        Smod['onde'][Smod['onde']>3] = 3
        Smod['axis'] = 15
        
        fig, ax = plt.subplots(1,1, figsize=(6,3))

        # lw = 4
        # for u in range(len(assec)):
        #     ax.axvline(assec.index[u], color='salmon', linewidth = lw, alpha=1, zorder=-10) # assec
        # for u in range(len(invi)):
        #     ax.axvline(invi.index[u], color='gold', linewidth = lw, alpha=1, zorder=-10) # pond
        # for u in range(len(low)):
        #     ax.axvline(low.index[u], color='lightskyblue', linewidth = lw, alpha=1, zorder=-10) # bio mal
        # for u in range(len(accep)):
        #     ax.axvline(accep.index[u], color='lightskyblue', linewidth = lw, alpha=1, zorder=-10) # bio ok
        # for u in range(len(visib)):
        #     ax.axvline(visib.index[u], color='lightskyblue', linewidth = lw, alpha=1, zorder=-10) # ecoul
        
        
        # lw = 4
        # for u in range(len(assec)):
            # ax.axvline(assec.index[u], color='salmon', linewidth = lw, alpha=1, zorder=-10) # assec
        # for u in range(len(invi)):
        #     ax.axvline(invi.index[u], color='gold', linewidth = lw, alpha=1, zorder=-10) # pond
        # for u in range(len(low)):
        #     ax.axvline(low.index[u], color='forestgreen', linewidth = lw, alpha=0.5, zorder=-10) # bio mal
        # for u in range(len(accep)):
        #     ax.axvline(accep.index[u], color='lightskyblue', linewidth = lw, alpha=1, zorder=-10) # bio ok
        # for u in range(len(visib)):
        #     ax.axvline(visib.index[u], color='lightskyblue', linewidth = lw, alpha=1, zorder=-10) # ecoul
        
        from datetime import date, timedelta
        from dateutil.relativedelta import relativedelta
        x_months = Smod.index + timedelta(days=-10)
        Smod['date'] = x_months
        
        al=0.7
        lw = 2.5
        ax.vlines(Smod['date'][Smod['onde']==3],
                        Smod['surflow_areas'][Smod['onde']==3],
                        Smod['axis'][Smod['onde']==3],
                        color='forestgreen', alpha=al, lw=lw)
        ax.vlines(Smod['date'][Smod['onde']==2],
                        Smod['surflow_areas'][Smod['onde']==2],
                        Smod['axis'][Smod['onde']==2],
                        color='darkorange', alpha=al, lw=lw)
        ax.vlines(Smod['date'][Smod['onde']==1],
                        Smod['surflow_areas'][Smod['onde']==1],
                        Smod['axis'][Smod['onde']==1],
                        color='red', alpha=al, lw=lw)
        
        # seep = Sonde['seepage_areas']
        # seep = seep.fillna(0)
        # ax.plot(seep, color='k', ls=(0, (1, 1)), lw=1.5, label='upstream')
        # tp = Sonde['surflow_areas']
        # tp = tp.fillna(0)
        # ax.plot(tp, color='k', lw=1.5, label='upstream')
        step = 'pre'
        # ax.plot(Smod['surflow_areas'], color='dodgerblue', ls='-', lw=1, label='catchment')
        # ax.fill_between(Smod.index, Smod['perenn_areas'], Smod['surflow_areas'],
        #                 interpolate=False, color='dodgerblue', alpha=0.5)
        # ax.plot(Smod['perenn_areas'], color='navy',
        #         marker=None, markeredgecolor='none',
        #         markersize=5, lw=1, label='upstream')
        ax.fill_between(Smod.index, 0, Smod['surflow_areas'],
                        interpolate=False, color='dodgerblue', alpha=0.5,
                        step=step)
        ax.fill_between(Smod.index, 0, Smod['perenn_areas'],
                        interpolate=False, color='navy', alpha=0.5,
                        step=step)
        ax.step(Smod.index, Smod['surflow_areas'], color='dodgerblue',
                marker=None, markeredgecolor='none',
                markersize=5, lw=1, label='upstream',
                where=step)
        ax.step(Smod.index, Smod['perenn_areas'], color='navy',
                marker=None, markeredgecolor='none',
                markersize=5, lw=1, label='upstream',
                where=step)
        
        
        ax.grid('grey', axis='x')
        ax.set_ylim(-0,15)
        ax.set_yticks(np.arange(0,15.05,2.5))
        ax.set_ylabel('$A_{sat}$ [%]')
        ax.set_xlim(pd.to_datetime('2012'), pd.to_datetime('2020'))

        months_maj = MonthLocator()  # every x month
        ax.xaxis.set_minor_locator(months_maj)
        
        plt.tight_layout()
        
        base_name = figsim_folder+'04_calibrated/'
        spec_name = watershed_name+'_onde_chronic'
        # fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight')
                
#%% MMINMAP

iD = 'calibrated1'

mod = 'REA'

time_step = 'M'
sim_state = 'transient'

# watershed_names = ['Canut']

types_obs = ['complete'] # list of shapefile name layers for clip hydrology
for watershed_name in watershed_names[:] :
    print('##### '+watershed_name.upper()+' #####')
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' 
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)
    wbt.vector_lines_to_raster(stable_folder+'geographic/'+'watershed_contour.shp',
                               stable_folder+'geographic/'+'watershed_contour.tif',
                               base = stable_folder+'geographic/'+'watershed_dem.tif')
    line = imageio.imread(stable_folder+'geographic/'+'watershed_contour.tif')
    line = np.ma.masked_where(line <= 0, line)
    
    mask = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
    
    # BV.add_intermittency(intermittency_path)

    BV.add_forcing()
    scan = 'outflow_drain'
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    # simul_list = glob.glob(simulations_folder+typ+'*')
    simul_list = sorted(glob.glob(simulations_folder+iD+'*'),
                       key=os.path.getmtime)
         
    for simul in simul_list[-1:]:
        model_name = simul.split('\\')[-1]
        Smod_path = simul+'/_watershed/_simulated_results.csv'
        if not os.path.exists(Smod_path):
            compt += 1
            continue
        Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
        
        stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
        
        min_area = Smod['surflow_areas'].min()
        min_idx = np.argmin(Smod['surflow_areas'])
        max_area = Smod['surflow_areas'].max()
        max_idx = np.argmax(Smod['surflow_areas'])
        max_year = Smod['surflow_areas'].index[max_idx]
        
        acc_npy = np.load(os.path.join(simul, '_watershed','accumulation_flux.npy'), allow_pickle=True).item()
        inf = 0
        sup = 12
        compt = 0
        step = int(round(len(acc_npy)/12))
        
        for i in range(step):
            print(str(i)+'/'+str(step))
            interv = list(acc_npy.items())[inf:sup]
            # print(interv)
            for key in range(len(interv)):
                # key = tupl[0]
                # print(key)
                interv[key] = np.ma.masked_array(interv[key][1], mask=(mask<0))

            zero = acc_npy[0] * 0
            for j in range(len(interv)):
                tempo = interv[j].copy()
                tempo[tempo>0] = 1
                zero = zero + tempo
            days_flux = zero.copy()
            days_flux = np.ma.masked_array(days_flux, mask=(mask<0))
            days_flux = np.ma.masked_array(days_flux, mask=(days_flux<=0))
        
        for k, j in enumerate([min_idx, max_idx]):
                
                year = Smod['surflow_areas'].index[j]
                val = Smod.iloc[j]['surflow_areas']

                days_flux = acc_npy[j]
    
                fig, ax = plt.subplots(1,1, figsize=(7,6))
                ax.set_title(str(year)[0:10] + '   ' + '$A_{sat}$ = ' + str(val.round(1)) + ' [%]',
                             pad=10)
                # image_hidden = ax.imshow(np.ma.masked_where(mask<0, mask), cmap='Greys')
                ax.imshow(np.ma.masked_where(mask<0, mask), cmap='Greys', alpha=0.5, zorder=0)
                ax.imshow(np.ma.masked_where((days_flux<=0) | (mask <0),
                                             days_flux), 
                          cmap = mpl.colors.ListedColormap(['navy'])) # dodgerblue
                ax.imshow(line, cmap=mpl.colors.ListedColormap('k'))
                ax.get_xaxis().set_visible(False)
                ax.get_yaxis().set_visible(False)
                plt.axis('off')
        
                # ax.set_title(years[i])
                
                try:
                    path_sub = glob.glob(stable_folder+'subbasin/' + '/intermittency*')[0] + '/watershed_contour.shp'
                    wbt.vector_lines_to_raster(path_sub,
                                               glob.glob(stable_folder+'subbasin/' + '/intermittency*')[0] + '/watershed_contour.tif',
                                               base = stable_folder+'geographic/'+'watershed_dem.tif')
                    line_sub = imageio.imread(glob.glob(stable_folder+'subbasin/' + '/intermittency*')[0] + '/watershed_contour.tif')
                    line_sub = np.ma.masked_where(line_sub <= 0, line_sub)
                    # ax.imshow(line_sub, cmap=mpl.colors.ListedColormap('gold'))
                except:
                    pass
                
                base_name = figsim_folder+'04_calibrated/'
                if k == 0:
                    spec_name = watershed_name+'_minmax_mapping_'+str(k)+'_'+str(min_idx)
                if k == 1:
                    spec_name = watershed_name+'_minmax_mapping_'+str(k)+'_'+str(max_idx)
                fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight')

#%% CROSSANIM

iD = 'calibrated1'

watershed_names = ['Canut','Nancon']

dates = pd.date_range(start='01/01/1990', end='31/12/2019', freq='M')

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
    
    list_path = sorted(glob.glob(simulations_folder+iD+'*'),
                        key=os.path.getmtime, reverse=True)
    model_name = list_path[-1].split('\\')[-1]
    
    mask = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
    
    import itertools            
    
    watertable_elevation = np.load(simulations_folder+model_name+'/_watershed/'+'watertable_elevation'+'.npy', allow_pickle=True).item()
    
    c = 0
    cp = 0
    dict_min_wt = {}
    dict_res_both = {}
    for key in dict(itertools.islice(watertable_elevation.items(),
                                     len(watertable_elevation)-12*8, # ONDE 8 years
                                     len(watertable_elevation))):
        dem_data = imageio.imread(BV.geographic.watershed_dem)
        # wt_data = imageio.imread(simulations_folder+model_name+'/_watershed/_tifs/'+'watertable_elevation_t(0).tif')
        wt_data = watertable_elevation[key]
        wt_data = np.ma.masked_where(wt_data < 0, wt_data)
        river_data = imageio.imread(stable_folder+'/hydrology/'+'complete.tif')
        # print(key)
        # print(c)
        dict_min_wt[c] = wt_data.mean()
        c+=1
        if c == 12:
            c=0
            minval = min(dict_min_wt.values())
            res = [k for k, v in dict_min_wt.items() if v==minval]
            res = list(filter(lambda x: dict_min_wt[x]==minval, dict_min_wt))
            res_both = min(dict_min_wt.items(), key=lambda x: x[1])
            # print(res_both)
            dict_res_both[cp] = res_both
            cp+=1
            
    cb = 0
    cpb = 0
    cpy = 0
    for key in dict(itertools.islice(watertable_elevation.items(),
                                     len(watertable_elevation)-12*8, # ONDE 8 years
                                     len(watertable_elevation))):

        dem_data = imageio.imread(BV.geographic.watershed_dem)
        # wt_data = imageio.imread(simulations_folder+model_name+'/_watershed/_tifs/'+'watertable_elevation_t(0).tif')
        wt_data = watertable_elevation[key]
        wt_data = np.ma.masked_where(wt_data < 0, wt_data)
        river_data = imageio.imread(stable_folder+'/hydrology/'+'complete.tif')
        
        # print(cpb)
        cb+=1
        if cpb == 12:
            cb=0
            cpb=0
            # print(cpy)
            cpy+=1
        res_both = dict_res_both[cpy]
        print(cpb, cpy, res_both)
        cpb+=1

        xvalues = np.linspace(-1,1,dem_data.shape[1])
        yvalues = np.linspace(-1,1,dem_data.shape[0])
        xx, yy = np.meshgrid(xvalues,yvalues)
        
        cur_x = dem_data.shape[1] /2
        cur_y = dem_data.shape[0] /2
        
        cur_x = 65
        cur_y = 39
        
        dem_max = dem_data.max()
        dem_prof = dem_data.astype(float)
        dem_prof[dem_prof<0] = np.nan
        
        wt_prof = wt_data.astype(float)
        wt_prof[wt_prof<0] = np.nan
        
        if watershed_name == 'Nancon':
            dem_h_plot = dem_prof[int(cur_y),:]
            dem_h_plot[dem_h_plot == 0] = np.nan
            wt_h_plot = wt_prof[int(cur_y),:]
            wt_h_plot[wt_h_plot == 0] = np.nan

            wt_prof_min = watertable_elevation[res_both[0]].astype(float)
            wt_prof_min[wt_prof_min<0] = np.nan
            wt_h_plot_min = wt_prof_min[int(cur_y),:]
            wt_h_plot_min[wt_h_plot_min == 0] = np.nan
                
        if watershed_name == 'Canut':
            dem_v_plot = dem_prof[:,int(cur_x)]
            dem_v_plot[dem_v_plot == 0] = np.nan
            wt_v_plot = wt_prof[:,int(cur_x)]
            wt_v_plot[wt_v_plot == 0] = np.nan

            wt_prof_min = watertable_elevation[res_both[0]].astype(float)
            wt_prof_min[wt_prof_min<0] = np.nan
            wt_v_plot_min = wt_prof_min[:,int(cur_x)]
            wt_v_plot_min[wt_v_plot_min == 0] = np.nan
                 
        dem_max = dem_data.max()
        dem_prof = dem_data.astype(float)
        dem_prof[dem_prof<0] = np.nan
        dem_plot = np.ma.masked_array(dem_data, mask=(dem_data<0))
    
        fig, ax = plt.subplots(1, 1, figsize=(5,3), dpi=300)
    
        if watershed_name == 'Nancon':
            wt_v_fill = ax.fill_between(np.arange(xx.shape[1])*75, dem_h_plot-30, wt_h_plot_min,
                                                color='navy', alpha=0.5, lw=0)
            w_prof = ax.plot(np.arange(xx.shape[1])*75, wt_h_plot_min, color='navy', lw=1)
            store_w_c_plot = wt_h_plot_min.copy()
            # store_w_c_plot = wt_h_plot.copy()
            
            wt_h_fill = ax.fill_between(np.arange(xx.shape[1])*75, dem_h_plot-30, wt_h_plot,
                                            color='dodgerblue', alpha=0.5, lw=0)
            w_prof = ax.plot(np.arange(xx.shape[1])*75, wt_h_plot, color='dodgerblue', lw=1)
            wt_h_fill = ax.fill_between(np.arange(xx.shape[1])*75, wt_h_plot, dem_h_plot,
                                            color='saddlebrown', alpha=0.5, lw=0)
            d_prof = ax.plot(np.arange(xx.shape[1])*75, dem_h_plot, 'saddlebrown', lw=1.5)
            ax.fill_between(np.arange(xx.shape[1])*75, 0, dem_h_plot-30,
                                            color='lightgrey', alpha=0.5, lw=0)
            ax.plot(np.arange(xx.shape[1])*75, dem_h_plot-30, color='dimgray', lw=1.5)
            ax.set_xlim(5500, 8500)
            ax.set_ylim(125, 170)
            ax.set_yticks([130,140,150,160,170])
                   
        if watershed_name == 'Canut':
            wt_v_fill = ax.fill_between(np.arange(xx.shape[0])*75, dem_v_plot-30, wt_v_plot_min,
                                                color='navy', alpha=0.5, lw=0)
            w_prof = ax.plot(np.arange(xx.shape[0])*75, wt_v_plot_min, color='navy', lw=1)
            store_w_c_plot = wt_v_plot_min.copy()
            # store_w_c_plot = wt_v_plot.copy()
            
            wt_v_fill = ax.fill_between(np.arange(xx.shape[0])*75, dem_v_plot-30, wt_v_plot,
                                                color='dodgerblue', alpha=0.5, lw=0)
            w_prof = ax.plot(np.arange(xx.shape[0])*75, wt_v_plot, color='dodgerblue', lw=1)
            wt_v_fill = ax.fill_between(np.arange(xx.shape[0])*75, wt_v_plot, dem_v_plot,
                                            color='saddlebrown', alpha=0.5, lw=0)
            d_prof = ax.plot(np.arange(xx.shape[0])*75, dem_v_plot, 'saddlebrown', lw=1.5)
            ax.fill_between(np.arange(xx.shape[0])*75, 0, dem_v_plot-30,
                                            color='lightgrey', alpha=0.5, lw=0)
            ax.plot(np.arange(xx.shape[0])*75, dem_v_plot-30, color='dimgray', lw=1.5)
            ax.set_xlim(1000, 4000)
            ax.set_ylim(85, 130)
            ax.set_yticks([90,100,110,120,130])
                          
        ax.set_title(str(dates[key])[:7])
        
        plt.tight_layout()
        
        base_name = figsim_folder+'05_crossmapping/'
        spec_name = 'anim_'+watershed_name+'/'+'cross_anim_'+str(key)
        fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight')
        
        # plt.close()

for watershed_name in watershed_names[:]:    
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)
    list_path = sorted(glob.glob(simulations_folder+iD+'*'),
                        key=os.path.getmtime)
    model_name = list_path[-1].split('\\')[-1]
    begin_by = figsim_folder+'05_crossmapping/'+'anim_'+watershed_name+'/'+'cross_anim_'
    filenames = sorted(glob.glob(begin_by+'*.png'), key=os.path.getmtime)
    images = []
    for filename in filenames:
        images.append(imageio.imread(filename))
    base_name = figsim_folder+'05_crossmapping/'
    gif_name = 'anim_'+watershed_name+'/'+'_cross_anim_monthly'
    imageio.mimsave(base_name+gif_name+'.gif', images,
                    duration=0.25, loop=0)

#%% MAPANIM

iD = 'calibrated1'

typ_intermit = 'monthly' # yearly or persistency or monthly
# typ_intermit = 'yearly' # yearly or persistency or monthly

gif = True

for watershed_name in watershed_names[:]:
    print('##### '+watershed_name.upper()+' #####')
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' 
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)

    years = np.arange(1990,2019+1,1)
        
    simul_list = sorted(glob.glob(simulations_folder+iD+'*'),
                       key=os.path.getmtime)
    
    wbt.vector_lines_to_raster(stable_folder+'geographic/'+'watershed_contour.shp',
                               stable_folder+'geographic/'+'watershed_contour.tif',
                               base = stable_folder+'geographic/'+'watershed_dem.tif')
    line = imageio.imread(stable_folder+'geographic/'+'watershed_contour.tif')
    line = np.ma.masked_where(line <= 0, line)
    
    mask = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
        
    for simul in simul_list:
    
        acc_npy = np.load(os.path.join(simul, '_watershed','accumulation_flux.npy'),
                          allow_pickle=True).item()
        
        for key in acc_npy:
            # print(key)
            mask = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
            # acc = np.ma.masked_where(dem.read(1) < 0, dem.read(1))
            acc_npy[key] = np.ma.masked_array(acc_npy[key], mask=(mask<0))
        zero = acc_npy[0] * 0
        for l in range(len(acc_npy)):
            tempo = acc_npy[l].copy()
            tempo[tempo>0] = 1
            zero = zero + tempo
        days_flux = zero.copy() # / len(acc_npy)
                
        acc_npy = np.load(os.path.join(simul, '_watershed','accumulation_flux.npy'), allow_pickle=True).item()
        inf = 0
        sup = 12
        compt = 0
        step = int(round(len(acc_npy)/12))
        
        for i in range(step):
            print(str(i)+'/'+str(step))
            interv = list(acc_npy.items())[inf:sup]
            # print(interv)
            for key in range(len(interv)):
                # key = tupl[0]
                # print(key)
                interv[key] = np.ma.masked_array(interv[key][1], mask=(mask<0))
                
            zero = acc_npy[0] * 0
            for j in range(len(interv)):
                tempo = interv[j].copy()
                tempo[tempo>0] = 1
                zero = zero + tempo
            days_flux = zero.copy()
            days_flux = np.ma.masked_array(days_flux, mask=(mask<0))
            days_flux = np.ma.masked_array(days_flux, mask=(days_flux<=0))
            
            if typ_intermit == 'monthly':
                if i >= 22:
                    for k in range(len(interv)):
                        to = interv[k].copy()
                        
                        to[(to>0) & (days_flux==12)] = 2
                        to[(to>0) & (days_flux<12)] = 1
                        
                        to = np.ma.masked_array(to, mask=(mask<0))
                        to = np.ma.masked_array(to, mask=(to<=0))
                        
                        fig, ax = plt.subplots(1,1, figsize=(7,6))
                        ax.imshow(np.ma.masked_where(mask<0, mask), cmap='Greys', alpha=0.5, zorder=0)
                        ax.imshow(np.ma.masked_where(to==1, to),
                                  cmap = mpl.colors.ListedColormap(['navy']))
                        ax.imshow(np.ma.masked_where(to==2, to),
                                  cmap = mpl.colors.ListedColormap(['dodgerblue']))
                        ax.imshow(line, cmap=mpl.colors.ListedColormap('k'))
                        ax.get_xaxis().set_visible(False)
                        ax.get_yaxis().set_visible(False)
                        
                        month_print = "{:02d}".format(k+1)

                        ax.set_title(str(years[i])+'-'+(month_print))
                        
                        path_sub = glob.glob(stable_folder+'subbasin/' + '/intermittency*')[0] + '/watershed_contour.shp'
                        wbt.vector_lines_to_raster(path_sub,
                                                   glob.glob(stable_folder+'subbasin/' + '/intermittency*')[0] + '/watershed_contour.tif',
                                                   base = stable_folder+'geographic/'+'watershed_dem.tif')
                        line_sub = imageio.imread(glob.glob(stable_folder+'subbasin/' + '/intermittency*')[0] + '/watershed_contour.tif')
                        line_sub = np.ma.masked_where(line_sub <= 0, line_sub)
                        # ax.imshow(line_sub, cmap=mpl.colors.ListedColormap('k'))
                        
                        ax.imshow(line, cmap=mpl.colors.ListedColormap('k'))
                        
                        # if watershed_name=='Canut':
                        #     ax.axvline(x=65, color='k', lw=1, ls='--')
                        # if watershed_name=='Nancon':
                        #     ax.axhline(y=40, color='k', lw=1, ls='--')
                        
                        # fig.savefig(simul+'/_figures/png/'+'_map_intermittent_monthly_'+str(compt)+'.png', dpi=300, bbox_inches='tight')
                        
                        compt_print = "{:02d}".format(compt)
                        print(compt_print)

                        base_name = figsim_folder+'05_crossmapping/'
                        spec_name = 'mapanim_'+watershed_name+'/'+'map_anim_'+str(compt_print)
                        fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight')
                        
                        plt.axis('off')
                        plt.close()
                        
                        compt += 1
                        
                    inf+=12
                    sup+=12

    if gif == True:
        begin_by = figsim_folder+'05_crossmapping/'+'mapanim_'+watershed_name+'/'+'map_anim_'
        filenames = sorted(glob.glob(begin_by+'*.png'), key=os.path.getmtime)
        images = []
        for filename in filenames:
            images.append(imageio.imread(filename))
        base_name = figsim_folder+'05_crossmapping/'
        gif_name = 'mapanim_'+watershed_name+'/'+'_map_anim_monthly'
        imageio.mimsave(base_name+gif_name+'.gif', images,
                        duration=0.25, loop=0)

#%% MAPANIM SHP

iD = 'calibrated1'

typ_intermit = 'monthly' # yearly or persistency or monthly
# typ_intermit = 'yearly' # yearly or persistency or monthly

gif = True

for watershed_name in watershed_names[:]:
    print('##### '+watershed_name.upper()+' #####')
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' 
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)
        
    simul_list = sorted(glob.glob(simulations_folder+iD+'*'),
                       key=os.path.getmtime)
    
    wbt.vector_lines_to_raster(stable_folder+'geographic/'+'watershed_contour.shp',
                               stable_folder+'geographic/'+'watershed_contour.tif',
                               base = stable_folder+'geographic/'+'watershed_dem.tif')
    line = gpd.read_file(stable_folder+'geographic/'+'watershed_contour.shp')
    # line = np.ma.masked_where(line <= 0, line)
    
    mask = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
    dem = rasterio.open(BV.geographic.watershed_dem)
    dem_data = np.ma.masked_where(dem.read(1) < -100, dem.read(1)) # dem data

    # plt.imshow(dem_data)

    for simul in simul_list:

        Smod_path = simul+'/_watershed/_simulated_results.csv'  
        Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
        Smod = Smod.reset_index()
        Smod['iloc'] = Smod.index
        Smod = Smod.set_index('date')
        years = np.arange(2012,2019+1,1)
        Smod = select_period(Smod, years[0], years[-1])
        
        for dt, i in zip(Smod.index, Smod['iloc']):
            
            fig, ax = plt.subplots(1,1, figsize=(7,6))
            
            show(dem_data, ax=ax, transform=dem.transform,
                  cmap='Greys', alpha=0.7, zorder=0, aspect="auto")
            
            if watershed_name == 'Nancon':
                ms=7
            if watershed_name == 'Canut':
                ms=10
                
            shp = gpd.read_file(simul+'/_watershed/_surfaceflow/'+
                                'tracept_t('+str(i)+').shp')
            shp[shp['id_persist']==0].plot(ax=ax, column='id_persist', lw=0,
                                           marker='s', color='dodgerblue',
                                           markersize=ms, zorder=1)
            shp[shp['id_persist']==1].plot(ax=ax, column='id_persist', lw=0,
                                           marker='s', color='navy',
                                           markersize=ms, zorder=1)
            line.plot(ax=ax, color='k', lw=2)
    
            ax.get_xaxis().set_visible(False)
            ax.get_yaxis().set_visible(False)
            plt.axis('off')
            
            # month_print = "{:02d}".format(k+1)
            ax.set_title(str(dt)[:7])
    
            compt_print = "{:02d}".format(compt)
            # print(compt_print)

            base_name = figsim_folder+'05_crossmapping/'
            spec_name = 'mapanim_'+watershed_name+'/'+'map_anim_'+str(i)+'_'+str(dt)[:7]
            fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight')
            
            # plt.close()
        
        compt += 1

    if gif == True:
        begin_by = figsim_folder+'05_crossmapping/'+'mapanim_'+watershed_name+'/'+'map_anim_'
        filenames = sorted(glob.glob(begin_by+'*.png'), key=os.path.getmtime)
        images = []
        for filename in filenames:
            images.append(imageio.imread(filename))
        base_name = figsim_folder+'05_crossmapping/'
        gif_name = 'mapanim_'+watershed_name+'/'+'_map_anim_monthly'
        imageio.mimsave(base_name+gif_name+'.gif', images,
                        duration=0.25, loop=0)

#%% CROSSFIX

iD = 'calibrated1'

watershed_names = ['Canut','Nancon']

dates = pd.date_range(start='01/01/1990', end='31/12/2019', freq='M')

for watershed_name in watershed_names[:]:    
    
    fig, ax = plt.subplots(1, 1, figsize=(5,3), dpi=300)

    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'

    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)
    
    dem = rasterio.open(BV.geographic.watershed_dem)
    dem_data = np.ma.masked_where(dem.read(1) < -100, dem.read(1)) # dem data
    
    list_path = sorted(glob.glob(simulations_folder+iD+'*'),
                        key=os.path.getmtime, reverse=True)
    model_name = list_path[-1].split('\\')[-1]
    
    simul_list = sorted(glob.glob(simulations_folder+iD+'*'), key=os.path.getmtime)
    
    for simul in simul_list:
    
        Smod_path = simul+'/_watershed/_simulated_results.csv'
        Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
        Smod = Smod.reset_index()
        argmin = Smod['surflow_areas'].argmin()
        argmax = Smod['surflow_areas'].argmax()
        
        mask = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
        
        import itertools            
        
        watertable_elevation = np.load(simulations_folder+model_name+'/_watershed/'+'watertable_elevation'+'.npy', allow_pickle=True).item()
        
        min_wt = dict()
        
        cp = 0
        # for key in dict(itertools.islice(watertable_elevation.items(),
        #                                  len(watertable_elevation), # ONDE 8 years
        #                                  len(watertable_elevation))):
        for i, key in enumerate([argmin, argmax]):
            print(key)
    
            dem_data = imageio.imread(BV.geographic.watershed_dem)
            # wt_data = imageio.imread(simulations_folder+model_name+'/_watershed/_tifs/'+'watertable_elevation_t(0).tif')
            wt_data = watertable_elevation[key]
            river_data = imageio.imread(stable_folder+'/hydrology/'+'complete.tif')
        
            xvalues = np.linspace(-1,1,dem_data.shape[1])
            yvalues = np.linspace(-1,1,dem_data.shape[0])
            xx, yy = np.meshgrid(xvalues,yvalues)
            
            cur_x = dem_data.shape[1] /2
            cur_y = dem_data.shape[0] /2
            
            cur_x = 65
            cur_y = 39 # 40
            
            dem_max = dem_data.max()
            dem_prof = dem_data.astype(float)
            dem_prof[dem_prof<0] = np.nan
            wt_prof = wt_data.astype(float)
            wt_prof[wt_prof<0] = np.nan
            
            if watershed_name == 'Nancon':
                dem_h_plot = dem_prof[int(cur_y),:]
                dem_h_plot[dem_h_plot == 0] = np.nan
                wt_h_plot = wt_prof[int(cur_y),:]
                wt_h_plot[wt_h_plot == 0] = np.nan
                
                # list_h_wt[cp] = wt_h_plot
                
            if watershed_name == 'Canut':
                dem_v_plot = dem_prof[:,int(cur_x)]
                dem_v_plot[dem_v_plot == 0] = np.nan
                wt_v_plot = wt_prof[:,int(cur_x)]
                wt_v_plot[wt_v_plot == 0] = np.nan
                
                # list_v_wt[cp] = wt_v_plot
                
            dem_max = dem_data.max()
            dem_prof = dem_data.astype(float)
            dem_prof[dem_prof<0] = np.nan
            dem_plot = np.ma.masked_array(dem_data, mask=(dem_data<0))
            
            wt_prof = wt_data.astype(float)
            wt_prof[wt_prof<0] = np.nan
            
            cp+=1
                
            if watershed_name == 'Nancon':
                # dem_h_prof, = ax.plot(np.arange(xx.shape[1])*75,dem_h_plot, c='saddlebrown', lw=2)
                # wt_h_prof, = ax.plot(np.arange(xx.shape[1])*75, wt_h_plot, c='dodgerblue', lw=2)
                if i == 0:
                    wt_h_fill = ax.fill_between(np.arange(xx.shape[1])*75, dem_h_plot-30, wt_h_plot,
                                                    color='navy', alpha=0.5, lw=0)
                    w_prof = ax.plot(np.arange(xx.shape[1])*75, wt_h_plot, color='navy', lw=1)
                if i == 1:
                    wt_h_fill = ax.fill_between(np.arange(xx.shape[1])*75, dem_h_plot-30, wt_h_plot,
                                                    color='dodgerblue', alpha=0.5, lw=0)
                    w_prof = ax.plot(np.arange(xx.shape[1])*75, wt_h_plot, color='dodgerblue', lw=1)
                    wt_h_fill = ax.fill_between(np.arange(xx.shape[1])*75, wt_h_plot, dem_h_plot,
                                                    color='saddlebrown', alpha=0.5, lw=0)
                    d_prof = ax.plot(np.arange(xx.shape[1])*75, dem_h_plot, 'saddlebrown', lw=1.5)
                ax.fill_between(np.arange(xx.shape[1])*75, 0, dem_h_plot-30,
                                                color='lightgrey', alpha=0.5, lw=0)
                ax.plot(np.arange(xx.shape[1])*75, dem_h_plot-30, color='dimgray', lw=1.5)
                ax.set_xlim(5500, 8500)
                ax.set_ylim(125, 170)
                ax.set_yticks([130,140,150,160,170])
                       
            if watershed_name == 'Canut':
                # dem_v_prof, = ax.plot(np.arange(xx.shape[0])*75, dem_v_plot, c='saddlebrown', lw=2)
                # wt_v_prof, = ax.plot(np.arange(xx.shape[0])*75, wt_v_plot, c='dodgerblue', lw=2)
                if i == 0:
                    wt_v_fill = ax.fill_between(np.arange(xx.shape[0])*75, dem_v_plot-30, wt_v_plot,
                                                        color='navy', alpha=0.5, lw=0)
                    w_prof = ax.plot(np.arange(xx.shape[0])*75, wt_v_plot, color='navy', lw=1)
                    store_w_c_plot = wt_v_plot.copy()
                    # store_w_c_plot = wt_v_plot.copy()
                if i == 1:
                    wt_v_fill = ax.fill_between(np.arange(xx.shape[0])*75, dem_v_plot-30, wt_v_plot,
                                                        color='dodgerblue', alpha=0.5, lw=0)
                    w_prof = ax.plot(np.arange(xx.shape[0])*75, wt_v_plot, color='dodgerblue', lw=1)
                    wt_v_fill = ax.fill_between(np.arange(xx.shape[0])*75, wt_v_plot, dem_v_plot,
                                                    color='saddlebrown', alpha=0.5, lw=0)
                    d_prof = ax.plot(np.arange(xx.shape[0])*75, dem_v_plot, 'saddlebrown', lw=1.5)
                ax.fill_between(np.arange(xx.shape[0])*75, 0, dem_v_plot-30,
                                                color='lightgrey', alpha=0.5, lw=0)
                ax.plot(np.arange(xx.shape[0])*75, dem_v_plot-30, color='dimgray', lw=1.5)
                ax.set_xlim(1000, 4000)
                ax.set_ylim(85, 130)
                ax.set_yticks([90,100,110,120,130])
                
            # ax.set_title(str(dates[key])[:7])
            print((str(dates[key])[:7]))
            
            plt.tight_layout()
            
            # fig.savefig(simulations_folder+model_name+'/_figures/png/'+'cross_'+str(key)+'.png', dpi=300, bbox_inches='tight')
    
            base_name = figsim_folder+'05_crossmapping/'
            spec_name = watershed_name+'_cross map fixed'
            # fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight')

#%% SENSITIVITY PIDMAP PLOT

iD = 'calibrated1'
iD = 'matrix1'

var = 'REC'
sce_list = ['historic']

y_name = 'surflow_areas'

for watershed_name in watershed_names[1:]:

    if watershed_name == 'Canut':
        color = 'green'
    if watershed_name == 'Nancon':
        color = 'darkmagenta'    

    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'  # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)
    
    list_simuls = glob.glob(simulations_folder+'*'+iD+'_'+'*')
    
    for ix in range(len(list_simuls))[:]:
        
        try:
        
            fig, ax = plt.subplots(1,1, figsize=(10,10), sharex=True, sharey=True)
    
            simul = glob.glob(simulations_folder+'*'+iD+'_'+str(ix)+'*')[0]
            model_name = simul.split('\\')[-1]
            
            acc_npy = np.load(os.path.join(simul, '_watershed','accumulation_flux.npy'), allow_pickle=True).item()
            acc_npy = list(acc_npy.items())[:]
            
            for key in range(len(acc_npy)):
                mask = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
                acc_npy[key] = np.ma.masked_array(acc_npy[key][1], mask=(mask<0))
            zero = acc_npy[0] * 0
            for i in range(len(acc_npy)):
                tempo = acc_npy[i].copy()
                tempo[tempo>0] = 1
                zero = zero + tempo
            days_flux = zero.copy() / len(acc_npy)
                    
            vmin = 0
            vmax = 1
            
            # cmap = plt.cm.jet_r  # define the colormap
            cmap = plt.cm.YlGnBu
            # cmap = parula_map
            cmaplist = [cmap(i) for i in range(cmap.N)]
            # cmaplist = ['skyblue','dodgerblue','navy']
            cmaplist = ['white','lightskyblue','deepskyblue','dodgerblue','navy','purple']
            # cmaplist = ['white','red','gold','forestgreen','dodgerblue','navy']
            # cmaplist[0] = (.5, .5, .5, 1.0)
            cmap = mpl.colors.LinearSegmentedColormap.from_list(
                'Custom cmap', cmaplist, cmap.N)
            bounds = np.arange(0, 1.1, 0.1)
            bounds = [-1,0,0.25,0.5,0.75,1,1.1]
            norm = mpl.colors.BoundaryNorm(bounds, cmap.N)
            
            pi = np.ma.masked_where(days_flux <= 0, days_flux)
            pc = ax.imshow(pi,
                           cmap=cmap, norm=norm, alpha=1)
            # pc = ax.imshow(np.ma.masked_where(pi != 1, pi),
            #                cmap=mpl.colors.ListedColormap('k'), norm=norm, alpha=1)
            ax.get_xaxis().set_visible(False)
            ax.get_yaxis().set_visible(False)
            ax.axis('off')
            
            wbt.vector_lines_to_raster(stable_folder+'geographic/'+'watershed_contour.shp',
                                       stable_folder+'geographic/'+'watershed_contour.tif',
                                       base = stable_folder+'geographic/'+'watershed_dem.tif')
            line = imageio.imread(stable_folder+'geographic/'+'watershed_contour.tif')
            line = np.ma.masked_where(line <= 0, line)
            import matplotlib as mpl
            ax.imshow(line, cmap=mpl.colors.ListedColormap('k'))
            plt.subplots_adjust(hspace = -0.6)
            
            base_name = figsim_folder+'03_sensitivity/'
            spec_name = watershed_name+'_pimap sensitivity_'+model_name
            fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight',
                        transparent=True)
            
            '''        
            ### Classic histogram
            # masked = days_flux[days_flux >= 0]
            # Z = masked.flatten()
            # from scipy.stats import norm
            # pdf = norm.pdf(Z, Z.mean(), Z.std())
            # ax.hist(Z, bins = 100, density=True,
            #         color = color, edgecolor = 'none', alpha = 0.5)
            # ax.set_yscale('log')
        
            Smod_path = simul+'/_watershed/_simulated_results.csv'            
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            Smod['prop_ratio'] = Smod.intermit_areas / Smod.perenn_areas
            
            ### Normalized cumulative evolution of areas in time
            X2 = np.sort(Smod[y_name])
            N = len(Smod[y_name])
            # ax.plot((1-np.arange(0,N,1)/N)*100, (X2-X2.min())/(X2.max()-X2.min()) * 100,
            #         color=color, lw=2)
            ax.plot((1-np.arange(0,N,1)/N)*100, (X2),
                    color=color, lw=2)
            ax.set_xlabel('percent_time [%]')
            ax.set_ylabel(y_name)
            # ax.set_xlim(-5,100)
            # ax.set_ylim(-5,100)
            # ax.set_xscale('log')
            # ax.set_yscale('log')
            '''
         
            days_flux = np.ma.masked_where(days_flux == 0, days_flux)
        
            count_inf = np.ma.masked_where(days_flux > 0.1, days_flux).count()
            count_sup = np.ma.masked_where(days_flux < 0.9, days_flux).count()
            
            total = np.ma.masked_where(days_flux == 0, days_flux).count()
        
            print(watershed_name, (count_inf / total)*100, (count_sup / total)*100)
          
            position=fig.add_axes([0.93,0.35,0.01,0.30])  ## the parameters are the specified position you set 
            cb = fig.colorbar(pc,cax=position, orientation="vertical")
            position.set_ylabel('Persistency index [-]', rotation=270, labelpad=40)
            cb.ax.tick_params(axis='y', direction='out')
            
            # fig1.savefig(figsim_folder+watershed_name+'_persistency_map_historic'+'.png', dpi=300, bbox_inches='tight')
        
            base_name = figsim_folder+'fig06/'
            spec_name = watershed_name+'_persistency'
            # fig1.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight') 
            
            pi_path = os.path.join(simul, '_watershed', 'persistency_index.tif')
            # toolbox.export_tif(BV.geographic.watershed_dem, pi, -99999, pi_path)
            toolbox.export_tif(stable_folder+"geographic/watershed_dem.tif", pi, -99999, pi_path)
    
            pi_shp_path = os.path.join(simul, '_watershed', 'persistency_index.shp')
            wbt.raster_to_vector_points(pi_path, pi_shp_path)
            pi_shp = gpd.read_file(pi_shp_path)
            pi_shp['VALUE'][pi_shp['VALUE']>1] = 1
            
            pi_shp.to_file(pi_shp_path)
            
            wbt.extract_raster_values_at_points(
                stable_folder+"geographic/watershed_dem.tif", 
                pi_shp_path, 
                out_text=True)
            
            pi_shp = gpd.read_file(pi_shp_path)
            pi_shp = pi_shp.rename(columns={"VALUE1": "DEM"})
            pi_shp['DEM'][pi_shp['DEM']<0] = np.nan
            
            pi_shp.to_file(pi_shp_path)
            
            wt_path = os.path.join(simul, '_watershed', '_tifs', 'watertable_elevation_t(0).tif')
            
            wbt.extract_raster_values_at_points(
                wt_path, 
                pi_shp_path, 
                out_text=True)
            
            pi_shp = gpd.read_file(pi_shp_path)
            pi_shp = pi_shp.rename(columns={"VALUE1": "WT"})
            pi_shp['WT'][pi_shp['WT']<0] = np.nan
            
            pi_shp.to_file(pi_shp_path)
            
            # fig, ax = plt.subplots(1,1, figsize=(4,4), sharex=True, sharey=True)
            # ax.scatter(pi_shp['VALUE'], pi_shp['DEM'], c='red', ec='None')
            # ax.scatter(pi_shp['VALUE'], pi_shp['WT'], c='blue', ec='None')
            # ax.set_xlim(0,1)
            # ax.set_ylim(90,120)
        except:
            pass
    
#%% SENSITIVITY PIDISTRIB PLOT

iD = 'calibrated1'
iD = 'matrix1'

var = 'REC'
sce_list = ['historic']

y_name = 'surflow_areas'

for watershed_name in watershed_names[1:]:

    if watershed_name == 'Canut':
        color = 'green'
    if watershed_name == 'Nancon':
        color = 'darkmagenta'    

    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'  # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)
    
    list_simuls = glob.glob(simulations_folder+'*'+iD+'_'+'*')
    
    for ix in range(len(list_simuls))[:]:
        
        try:
        
            fig1, axs1 = plt.subplots(1,1, figsize=(4,2),
                                    sharex=True, sharey=True)
            
            simul = glob.glob(simulations_folder+'*'+iD+'_'+str(ix)+'*')[0]
            model_name = simul.split('\\')[-1]
            
            Smod_path = simul+'/_watershed/_simulated_results.csv'    
            # Smod_path = simul+'/_subbasins/_simulated_results.csv'    
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            Smod['prop_ratio'] = Smod.intermit_areas / Smod.perenn_areas
            
            acc_npy = np.load(os.path.join(simul, '_watershed','accumulation_flux.npy'), allow_pickle=True).item()
            acc_npy = list(acc_npy.items())[:]
            # acc_npy = list(acc_npy.items())[360:720]
            
            for key in range(len(acc_npy)):
                # print(key)
                mask = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
                # mask = imageio.imread(glob.glob(stable_folder+'subbasin/'+'intermittency'+'*')[0]+'/'+'watershed_dem.tif')
                # acc = np.ma.masked_where(dem.read(1) < 0, dem.read(1))
                acc_npy[key] = np.ma.masked_array(acc_npy[key][1], mask=(mask<0))
            zero = acc_npy[0] * 0
            for i in range(len(acc_npy)):
                tempo = acc_npy[i].copy()
                tempo[tempo>0] = 1
                zero = zero + tempo
            days_flux = zero.copy() / len(acc_npy)
            print(model_name)
            print(days_flux.min())
            
            # days_flux = np.ma.masked_array(days_flux, mask=(days_flux==0))
            
            box = np.sort(days_flux[~days_flux.mask]).flatten() #.round(5)
            
            cell = np.ma.masked_array(mask, mask=(mask<0)).count()        
    
            import collections
            a = box.copy()
            counter=collections.Counter(a)
    
            df = pd.DataFrame()
            df['values'] = counter.values()
            df['values'] = (df['values'] / cell) * 100
            df['keys'] = np.array(list(counter.keys()))
            # keyss = np.array(list(counter.keys())).round(2)
            # index = (keyss.round(2)).astype(str)
            # df.index = index
            # df = df.T
            
            Z = np.sort(days_flux[~days_flux.mask]).flatten() #.round(3)
            print(len(Z))
            
            ###### NP HISTOGRAM
            ax = axs1
            bins = 100
            test = np.histogram(Z, bins=bins, density=True)
            test_bis, binval = np.histogram(Z, bins=bins, density=True)
            cum_test = np.cumsum(test[0])
            # ax.plot(test[1][1:], test[0], color=color, lw=2, label="CDF")
            # ax.scatter(test[1][1:], test[0]/sum(test[0]), s=20, marker=m,
            #             c=test[0]/sum(test[0]),
            #             cmap=cmap, lw=0.1, label="CDF",
            #             norm=normalize)
            # ax.scatter(test[1][1:], test[0]/sum(test[0]), s=20, marker=m,
            #             c=test[1][1:],
            #             cmap=cmap, lw=0.1, label="CDF",
            #             norm=normalize)
            my_cmap = plt.get_cmap("jet_r")
            rescale = lambda y: (y - 0) / (1 - 0)
            # ax.bar(test[1][1:], test[0]/sum(test[0])*100, width=0.02, lw=0,
            #        color=my_cmap(rescale(test[1][1:])))
            
            bincentres_g = np.array([(binval[i]+binval[i+1])/2. for i in range(len(binval)-1)])
            # plt.plot(bincentres_g, cum_test)
            
            w=0.01
            ax.bar(test[1][1:][test[1][1:]>=1], test[0][test[1][1:]>=1], width=w, lw=0, color='purple')
            try:
                ax.bar(test[1][1:][(test[1][1:]>0.75)&(test[0]<1)], test[0][(test[1][1:]>0.75)&(test[1][1:]<1)], width=w, lw=0, color='navy')
            except:
                pass
            ax.bar(test[1][1:][(test[1][1:]>0.5)&(test[1][1:]<0.75)], test[0][(test[1][1:]>0.5)&(test[1][1:]<0.75)], width=w, lw=0, color='dodgerblue')
            ax.bar(test[1][1:][(test[1][1:]>0.25)&(test[1][1:]<0.5)], test[0][(test[1][1:]>0.25)&(test[1][1:]<0.5)], width=w, lw=0, color='deepskyblue')
            ax.bar(test[1][:-1][(test[1][:-1]>0.0)&(test[1][:-1]<0.25)], test[0][(test[1][:-1]>0.0)&(test[1][:-1]<0.25)], width=w, lw=0, color='lightskyblue')
            ax.bar(test[1][:-1][test[1][:-1]==0], test[0][test[1][:-1]==0], width=w, lw=0, color='grey')
            
            # ax.step(test[1][1:][test[1][1:]>=1], test[0][test[1][1:]>=1],
            #         where='mid', lw=2, color='purple')
            # try:
            #     ax.step(test[1][1:][(test[1][1:]>0.75)&(test[0]<1)], test[0][(test[1][1:]>0.75)&(test[1][1:]<1)], 
            #             where='mid', lw=2, color='navy')
            # except:
            #     pass
            # ax.step(test[1][1:][(test[1][1:]>0.5)&(test[1][1:]<0.75)], test[0][(test[1][1:]>0.5)&(test[1][1:]<0.75)],
            #         where='mid', lw=2, color='dodgerblue')
            # ax.step(test[1][1:][(test[1][1:]>0.25)&(test[1][1:]<0.5)], test[0][(test[1][1:]>0.25)&(test[1][1:]<0.5)],
            #         where='mid', lw=2, color='deepskyblue')
            # ax.step(test[1][:-1][(test[1][:-1]>0.0)&(test[1][:-1]<0.25)], test[0][(test[1][:-1]>0.0)&(test[1][:-1]<0.25)],
            #         where='mid', lw=2, color='lightskyblue')
            # ax.step(test[1][:-1][test[1][:-1]==0], test[0][test[1][:-1]==0],
            #         where='mid', lw=2, color='grey')
            
            """
            bincentres_g = np.array([(binval[i]+binval[i+1])/2. for i in range(len(binval)-1)])
            eg_100 = np.ma.masked_where(bincentres_g<bincentres_g[-2], bincentres_g)
            btw_75_100 = np.ma.masked_where((bincentres_g<0.75)|(bincentres_g>=bincentres_g[-2]), bincentres_g)
            btw_50_75 = np.ma.masked_where((bincentres_g<0.50)|(bincentres_g>0.75), bincentres_g)
            btw_25_50 = np.ma.masked_where((bincentres_g<0.25)|(bincentres_g>0.50), bincentres_g)
            btw_0_25 = np.ma.masked_where((bincentres_g<bincentres_g[1])|(bincentres_g>0.25), bincentres_g)
            eg_0 = np.ma.masked_where(bincentres_g>bincentres_g[1], bincentres_g)
            
            ax.step(eg_100, test, where='mid', color='purple', linestyle='-')
            ax.step(btw_75_100, test, where='mid', color='navy', linestyle='-')
            ax.step(btw_50_75, test, where='mid', color='dodgerblue', linestyle='-')
            ax.step(btw_25_50, test, where='mid', color='deepskyblue', linestyle='-')
            ax.step(btw_0_25, test, where='mid', color='lightskyblue', linestyle='-')
            ax.step(eg_0, test, where='mid', color='grey', linestyle='-')
            """
            
            # plt.bar(binval[:-1], test, width=w, lw=0, color='purple')
            
            # ax.hist(test[0], bins=100, range=[0, 0.25], histtype='bar', edgecolor='r', linewidth=3) # step
            
            ax.set_yscale('log')
            # plt.plot()
            ax.set_xlim(-0.01,1.01)
            ax.set_ylim(1E-3*100, 1*100)
            
            ax.spines.right.set_visible(False)
            ax.spines.top.set_visible(False)
            ax.yaxis.set_ticks_position('left')
            ax.xaxis.set_ticks_position('bottom')
            
            ax.set_yticks([1,10,100])
            ax.tick_params(direction='out', which='both', colors='k',
                           grid_color='r', grid_alpha=1)
            
            """
            # Colors
            ccol = plt.cm.jet_r  # define the colormap
            # cmap = plt.cm.RdYlGn  # define the colormap
            # cmap = parula_map
            cmaplist = [cmap(i) for i in range(cmap.N)]
            # cmaplist[0] = (.5, .5, .5, 1.0)
            cmap = mpl.colors.LinearSegmentedColormap.from_list(
                'Custom cmap', cmaplist, ccol.N)
            bounds = np.arange(0, 1.1, 0.1)
            norm = mpl.colors.BoundaryNorm(bounds, cmap.N)
            normalize = matplotlib.colors.Normalize(vmin=0, vmax=1)
            
            ###### BIN FROM NP HIST NORM
            ax = axs2
            from scipy.stats import norm
            pdf = norm.pdf(Z, Z.mean(), Z.std())
            N = len(Z)
            count, bins_count = np.histogram(Z, bins=100, density=True)
            pdf = count / sum(count)
            cdf = np.cumsum(pdf)
            # cdf = pdf.copy()
            # ax.plot(cdf*100, color=color, lw=4, label="CDF")
            # ax.plot(cdf, color=color, lw=2, label="CDF")
            ax.scatter(np.arange(0, len(cdf), 1)/100, cdf, s=20, marker=m,
                        c=cdf,
                        cmap=cmap, lw=0.1, label="CDF",
                        norm=normalize)
            # ax.scatter(np.arange(0, len(pdf), 1), pdf, s=20, marker=m,
            #             c=pdf,
            #             cmap=cmap, lw=0.1, label="CDF")
            # ax.scatter(bins_count[:-1], pdf, s=20, marker=m,
            #             c=pdf,
            #             cmap=cmap, lw=0.1, label="CDF")
            """
            
            base_name = figsim_folder+'03_sensitivity/'
            spec_name = watershed_name+'_pidistrib sensitivity_'+model_name
            fig1.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight', transparent=True)
        except:
            pass
        
#%% SENSITIVITY PICUMUL ANALY

iD = 'calibrated1'
iD = 'matrix1'

var = 'REC'
sce_list = ['historic']

y_name = 'surflow_areas'

for watershed_name in watershed_names[1:]:

    if watershed_name == 'Canut':
        color = 'green'
    if watershed_name == 'Nancon':
        color = 'darkmagenta'    

    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'  # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)
    
    list_simuls = glob.glob(simulations_folder+'*'+iD+'_'+'*')
    
    d_cum = pd.DataFrame()
    
    # for ix in range(len(list_simuls))[-3:-2]:
    for ix in range(len(list_simuls))[:]:
        
        try:
        
            simul = glob.glob(simulations_folder+'*'+iD+'_'+str(ix)+'*')[0]
            model_name = simul.split('\\')[-1]
            
            KP = model_name.split('_')[-2]
            
            Smod_path = simul+'/_watershed/_simulated_results.csv'    
            # Smod_path = simul+'/_subbasins/_simulated_results.csv'    
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            Smod['prop_ratio'] = Smod.intermit_areas / Smod.perenn_areas
            
            acc_npy = np.load(os.path.join(simul, '_watershed','accumulation_flux.npy'), allow_pickle=True).item()
            acc_npy = list(acc_npy.items())[:]
            # acc_npy = list(acc_npy.items())[360:720]
            
            for key in range(len(acc_npy)):
                # print(key)
                mask = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
                # mask = imageio.imread(glob.glob(stable_folder+'subbasin/'+'intermittency'+'*')[0]+'/'+'watershed_dem.tif')
                # acc = np.ma.masked_where(dem.read(1) < 0, dem.read(1))
                acc_npy[key] = np.ma.masked_array(acc_npy[key][1], mask=(mask<0))
            zero = acc_npy[0] * 0
            for i in range(len(acc_npy)):
                tempo = acc_npy[i].copy()
                tempo[tempo>0] = 1
                zero = zero + tempo
            days_flux = zero.copy() / len(acc_npy)
            print(model_name)
            print(days_flux.min())
            
            # days_flux = np.ma.masked_array(days_flux, mask=(days_flux==0))
            
            box = np.sort(days_flux[~days_flux.mask]).flatten() #.round(5)
            
            cell = np.ma.masked_array(mask, mask=(mask<0)).count()        
    
            import collections
            a = box.copy()
            counter=collections.Counter(a)
    
            df = pd.DataFrame()
            df['values'] = counter.values()
            df['values'] = (df['values'] / cell) * 100
            df['keys'] = np.array(list(counter.keys()))
            # keyss = np.array(list(counter.keys())).round(2)
            # index = (keyss.round(2)).astype(str)
            # df.index = index
            # df = df.T
            
            Z = np.sort(days_flux[~days_flux.mask]).flatten() #.round(3)
            print(len(Z))
            
            ###### NP HISTOGRAM
            ax = axs1
            bins = 100
            test = np.histogram(Z, bins=bins, density=False)
            x = list(np.array(test[0]) / np.array(test[0]).sum())
            test_bis, binval = np.histogram(Z, bins=bins, density=True)
            cum_test =  np.cumsum(test[0]) / np.array(test[0]).sum()
            # ax.plot(test[1][1:], test[0], color=color, lw=2, label="CDF")
            # ax.scatter(test[1][1:], test[0]/sum(test[0]), s=20, marker=m,
            #             c=test[0]/sum(test[0]),
            #             cmap=cmap, lw=0.1, label="CDF",
            #             norm=normalize)
            # ax.scatter(test[1][1:], test[0]/sum(test[0]), s=20, marker=m,
            #             c=test[1][1:],
            #             cmap=cmap, lw=0.1, label="CDF",
            #             norm=normalize)
            my_cmap = plt.get_cmap("jet_r")
            rescale = lambda y: (y - 0) / (1 - 0)
            # ax.bar(test[1][1:], test[0]/sum(test[0])*100, width=0.02, lw=0,
            #        color=my_cmap(rescale(test[1][1:])))
            
            bincentres_g = np.array([(binval[i]+binval[i+1])/2. for i in range(len(binval)-1)])
            # plt.plot(bincentres_g, cum_test)
            
            d_cum[KP] = cum_test
            
        except:
            pass
        
    # d_cum.set_index = bincentres_g

#%% SENSITIVITY PICUMUL PLOT

# d_cum.iloc[:,0:3].plot()
# d_cum.iloc[:,3:6].plot()
# d_cum.iloc[:,6:9].plot()

# d_cum.iloc[:,[0,3,6]].plot()
# d_cum.iloc[:,[1,4,7]].plot()
# d_cum.iloc[:,[2,5,8]].plot()

il = [0,1,2]
c = ['darkred','darkorange','darkgreen']
dict_c = dict(zip(il, c))

fig, ax = plt.subplots(1,1, figsize=(4,2),
                            sharex=True, sharey=True)
cp = 0
for i in [0,1,2]:

    if cp==3:
        cp=0
    ax.plot(d_cum.iloc[:,i], color=dict_c[cp], lw=2)
    cp += 1
ax.set_xlim(0,100)
ax.set_xticks(np.arange(0,101,20))
ax.set_xticklabels(np.arange(0,101/100,20/100).round(2))
ax.set_ylim(0.20,1)
from matplotlib.ticker import FormatStrFormatter
ax.yaxis.set_major_formatter(FormatStrFormatter('%.2f'))
ax.set_yticks([0.20,0.40,0.60,0.80,1.00])
base_name = figsim_folder+'03_sensitivity/'
spec_name = watershed_name+'_picumul sensitivity_'+'1'
fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight', transparent=True)
        

fig, ax = plt.subplots(1,1, figsize=(4,2),
                            sharex=True, sharey=True)
cp = 0
for i in [3,4,5]:

    if cp==3:
        cp=0
    ax.plot(d_cum.iloc[:,i], color=dict_c[cp], lw=2)
    cp += 1
ax.set_xlim(0,100)
ax.set_xticks(np.arange(0,101,20))
ax.set_xticklabels(np.arange(0,101/100,20/100).round(2))
ax.set_ylim(0.75,1)
ax.set_yticks([0.75,0.80,0.85,0.90,0.95,1.00])
base_name = figsim_folder+'03_sensitivity/'
spec_name = watershed_name+'_picumul sensitivity_'+'2'
fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight', transparent=True)
        

fig, ax = plt.subplots(1,1, figsize=(4,2),
                            sharex=True, sharey=True)
cp = 0
for i in [6,7,8]:
    try:
        if cp==3:
            cp=0
        ax.plot(d_cum.iloc[:,i], color=dict_c[cp], lw=2)
        cp += 1
    except:
        pass
ax.set_xlim(0,100)
ax.set_xticks(np.arange(0,101,20))
ax.set_xticklabels(np.arange(0,101/100,20/100).round(2))
ax.set_ylim(0.90,1)
ax.set_yticks([0.90,0.92,0.94,0.96,0.98,1.00])
base_name = figsim_folder+'03_sensitivity/'
spec_name = watershed_name+'_picumul sensitivity_'+'3'
fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight', transparent=True)

#%% SENSITIVITY HYSTERESIS PLOT

iD = 'matrix1'
typ = iD

var = 'REC'
sce_list = ['historic']

# Things
time_step = 'M'
sim_state = 'transient'
var = 'REC'
scan = 'outflow_drain'

# Colored
sce_cmap = ["Greys","Greens","Reds"]
cmap_dict = dict(zip(sce_list, sce_cmap))

sce_color = ['k',"dodgerblue","red"]
color_dict = dict(zip(sce_list, sce_color))

# Hysteres
temporal = True
space = 10
norm = False

watershed_names = ['Canut','Nancon']

for watershed_name in watershed_names[1:]:
    
    color = 'k' 

    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'  # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)
    
    list_simuls = glob.glob(simulations_folder+'*'+iD+'_'+'*')
        
    xn = 0.1
    xx = 200
    yn = 0.1
    yx = 200
    
    for ix in range(len(list_simuls))[:]:
        
        try:
        
            fig1, axs1 = plt.subplots(1,1, figsize=(3,3))
            # axs1 = axs1.ravel()
            ax = axs1
            
            simul = glob.glob(simulations_folder+'*'+iD+'_'+str(ix)+'*')[0]
            model_name = simul.split('\\')[-1]
            
            Smod_path = simul+'/_watershed/_simulated_results.csv'            
            if not os.path.exists(Smod_path):
                compt += 1
                continue
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            Qmod = Smod[scan] #+ Smod['runoff']
            Qmod = Qmod * 1000 * 30 # mm/months
            Qmod = Qmod.squeeze()    
            Cmod = Smod['recharge'] * 1000 * 30 # mm/months
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
            
            # ax = axs1[compt]
            ax.set_aspect('equal', adjustable='box')
            
            """
            from descartes import PolygonPatch
            ring_patch = PolygonPatch(areas[0], color='skyblue', alpha=0.5, ec="k")
            # ax.add_patch(ring_patch)
            ring_patch = PolygonPatch(areas[1], color='red', alpha=0.5, ec="k")
            # ax.add_patch(ring_patch)
            # ax.fill(hyst.data.inx, hyst.data.iny)
            """
            
            # ax.set_title(params, fontsize=8)
            # fig2.suptitle(metric.upper(), y=0.98)
            for i, (colx, coly) in enumerate(zip(columns_x, columns_y)):
                # print(colx)
                data = pd.DataFrame()
                data['inx'] = hyst.xrecapl[colx]
                data['iny'] = hyst.yrecapl[coly]
                # ax.plot(data.inx, data.iny, linestyle = '-', lw=0.5, color=cmap_color[i],
                #         alpha=0.75, zorder=0)
                
            ax.plot(data.inx, data.iny, linestyle = '-', lw=1.5, color=color, zorder=1)
            ax.scatter(hyst.x, hyst.y, c=hyst.wy, cmap='hsv_r', marker="o", 
                              s=8, vmin=1, vmax=12, alpha=0.5, ec='none', zorder=0)
            
            # ax.plot(hyst.xi, hyst.yi, marker="o", markersize=9, markeredgecolor='black', 
            #         markerfacecolor='white', linestyle = 'None') 
            # for k in hyst.wyi:
            #     ax.annotate(k,(hyst.xi[k],hyst.yi[k]), family='sans-serif', fontsize=5, 
            #                 color='black', weight="bold", ha='center', va='center')      
            
            cp = 1
            cont = 0
            
            for k in hyst.wyi:
                
                ax.plot(hyst.xi[k], hyst.yi[k], marker="o", markersize=9,
                          markeredgecolor='k', markerfacecolor='white', lw=0.5,
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
                    linestyle='-', color='grey', linewidth=1, zorder=-1)
            # ax.set_yscale('log')
            # ax.xaxis.set_ticks(np.arange(0, xx+0.1, 0.5))
            # ax.yaxis.set_ticks(np.arange(0, xx+0.1, 0.5))
            
            # ax.errorbar(hyst.xi, hyst.yi,
            #             yerr=abs(np.vstack([hyst.yi-hyst.ye.q25, hyst.ye.q75-hyst.yi])),
            #             xerr=abs(np.vstack([hyst.xi-hyst.xe.q25, hyst.xe.q75-hyst.xi])),
            #             ecolor = 'black', fmt = 'none', capsize = 1, elinewidth=0.5, 
            #             capthick=0.5, zorder=1)
        
            dfmean = dfmean.round(2)
                
            # ax.text(0.042, 0.78, 
            #                   '$Q_{0}$ = ' +str(dfmean['q0']) + '\n'
            #                   '$Q_{mid}$ = '+str(dfmean['qmid']) + '\n'
            #                   'HI = '+str(dfmean['hi']) + '\n'
            #                   '$Area_{ratio}$ = '+str(dfmean['area_r']) + '\n',
            #                   horizontalalignment='left',
            #                   verticalalignment='center', 
            #                   transform=ax.transAxes,
            #                   fontsize = 10)
            
            # ax.text(0.53, 0.14,
            #                   'Slope = ' +str(dfmean['slope']) + '\n'
            #                   'Long = ' +str(dfmean['long']) + '\n',
            #                     # 'Short = ' +str(dfmean['short']) + '\n',
            #                   # 'Eccent. = ' +str(dfmean['excent']) + '\n',
            #                   horizontalalignment='left',
            #                   verticalalignment='center', 
            #                   transform=ax.transAxes,
            #                   fontsize = 10)
        
            ax.grid(color='grey',alpha=0.2)
            
            if (compt==0) | (compt==3) | (compt==6):
                ax.set_ylabel('Q [mm/month]')
            if (compt==6) | (compt==7) | (compt==8):
                ax.set_xlabel('R [mm/month]')
                
            ax.set_xscale('log')
            ax.set_yscale('log')
                
            plt.tight_layout()
                
            compt+=1
        
            fig1.tight_layout()
            
            base_name = figsim_folder+'03_sensitivity/'
            spec_name = watershed_name+'_hysteresis sensitivity_'+model_name
            fig1.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight', transparent=True)
            
        except:
            pass

#%% ---- CHOICE

#%% HYSTERESIS PE vs Qobs

from scipy.stats import binned_statistic

watershed_names = ['Canut','Nancon']

iD = 'calibrated1'

# Things
time_step = 'M'
sim_state = 'transient'
var = 'REC'

# Colored
mod_list = ['REA']
sce_list = ['historic']
sce_cmap = ["Greys"]
sce_color = ["k"]
cmap_dict = dict(zip(sce_list, sce_cmap))
color_dict = dict(zip(sce_list, sce_color))

c = ['darkgreen','darkred']
# c = ['blue','darkmagenta']
cmaps = ['Greens_r','Reds_r']
# cmaps = ['YlGn','RdPu']
dict_c = dict(zip(watershed_names, c))
dict_cmap = dict(zip(watershed_names, cmaps))

# Hysteres
temporal = False
space = 0
norm = False

# fig, axs = plt.subplots(1,4, figsize=(14,3))
# axs = axs.ravel()
# fig3, axs3 = plt.subplots(1,4, figsize=(14,3))
# axs3 = axs3.ravel()

xy_list = [['recharge','outflow_drain']]

# fig, axs = plt.subplots(2,1, figsize=(3.5,6))
# axs = axs.ravel()

fig, ax = plt.subplots(1,1, figsize=(4,3.5))
ax.set_yscale('log')
ax.set_xlabel('L² / D [d]')
ax.set_xlabel('P - E [mm/month]')
# ax.set_ylabel('$A_{int}$ / $A_{per}$ [-]')
ax.set_ylabel('$Q_{obs}$ / A [mm/month]')
# ax.set_xlim(-150, 150)
ax.set_xticks([-150,-75,0,75,150])
# ax.set_ylim(0.07, 150)
fig.tight_layout()
# fig3.tight_layout()
ax.set_axisbelow(True)
# ax.grid(zorder=-1000)
# ax.xaxis.grid(color='gray', zorder=-1)
# ax.yaxis.grid(color='gray', zorder=-1)
ax.axvline(x=0, color='grey', ls='--', lw= 0.5, zorder=-1000)

for watershed_name in watershed_names[:] :
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = 'k'
        
    for mod in mod_list:
        
        for sce in sce_list:
            
            simul_list = glob.glob(simulations_folder+iD+'*'+mod+'*'+sce+'*')
            simul = simul_list[0]
            """
            model_name = simul.split('\\')[-1]

            Smod_path = simul+'/_watershed/_simulated_results.csv'  
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            Smod['prop_ratio'] = Smod.intermit_areas / Smod.surflow_areas
            Smod['recharge'] = Smod['recharge'] * 1000 * 30
            Smod['outflow_drain'] = ( Smod['outflow_drain'] + Smod['runoff'] ) * 1000 * 30
            # Smod['groundwater_storage'] = Smod['groundwater_storage']/(Smod['groundwater_storage'].mean())
            Smod['groundwater_storage'] = Smod['groundwater_storage']/1e6
            Smod = select_period(Smod, 1960, 2019)
            
            for xy in xy_list:
                                
                x = Smod[xy[0]]
                y = Smod[xy[1]]
                c = Smod.index.month
                wy = pd.Series(x.index.month).replace([10,11,12,1,2,3,4,5,6,7,8,9],
                                                        [1,2,3,4,5,6,7,8,9,10,11,12])
                xi = x.groupby([lambda x: x.month]).mean()
                yi = y.groupby([lambda y: y.month]).mean()
                cmapping = mpl.colors.ListedColormap(dict_c[watershed_name])
                cmapping = dict_cmap[watershed_name]
                scat = ax.scatter(x, y, c=wy, cmap=cmapping, marker="o", 
                                  s=5, vmin=1, vmax=12, alpha=0.75, ec='none', zorder=-1)
                xiline = xi.append(xi.iloc[[0]])
                xiline.index = np.arange(1,14,1)
                yiline = yi.append(yi.iloc[[0]])
                yiline.index = np.arange(1,14,1)
                ax.plot(xiline, yiline, linestyle = '-', lw=1, 
                        color='k', zorder=0)
                wyi = np.arange(1,12+1,1)
                compt = 10
                for k in wyi:

                    ax.plot(xi[k], yi[k], marker="o", lw=2, markersize=7, 
                               markeredgecolor='k', 
                               markerfacecolor='white', markeredgewidth=1,
                               linestyle = 'None', zorder=1)
                    ax.annotate(k,(xi[k],yi[k]), family='sans-serif', fontsize=4, 
                            color=dict_c[watershed_name], weight="bold", ha='center', va='center',
                            zorder=compt)
                    compt+=1
                xe = pd.DataFrame()
                xe['q25'] = (x.groupby(x.index.month).quantile(0.25))
                xe['q75'] = (x.groupby(x.index.month).quantile(0.75))        
                ye = pd.DataFrame()
                ye['q25'] = (y.groupby(y.index.month).quantile(0.25))
                ye['q75'] = (y.groupby(y.index.month).quantile(0.75))                
                # ax.errorbar(xi, yi,
                #               yerr=np.vstack([yi-ye.q25, ye.q75-yi]),
                #               xerr=np.vstack([xi-xe.q25, xe.q75-xi]),
                #               ecolor = 'black', fmt = 'none', capsize = 1, elinewidth=0.5, 
                #               capthick=0.5, zorder=1)               
                # ax.axvline(x.median(), c=dict_c[watershed_name], ls='--')
                # ax.axhline(y.median(), c=dict_c[watershed_name], ls='--')
                
                ax.set_yscale('log')
            """
            ### OBSERVED

            BV = watershed_root.Watershed(watershed_name=watershed_name,
                                          dem_path=dem_path, 
                                          out_path=out_path,
                                          load=True)
            BV.add_forcing()
            
            stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
        
            Clim_path = stable_folder+'climatic/'+'_ALL_D.csv'
            Clim = pd.read_csv(Clim_path, sep=';', index_col=0, parse_dates=True)
            # Clim = surfex = pd.read_csv(out_path+'/'+'Frame'+'/'+'results_stable/'+
            #                             'climatic/'+'_ALL_D.csv', sep=';',
            #                       index_col=0, parse_dates=True)
            Clim = select_period(Clim, 1990, 2019)
            Cobs = Clim['EFF_REA_historic']
            Cobs = Cobs.resample('M').mean() / 1000 # m/day
            # Cobs = dict_recharge[watershed_name]

            raw_path = stable_folder+'/'+'hydrometry/'
            Qobs_path = fnmatch.filter(os.listdir(raw_path), 'Hydrometric_*')[0]
            Qobs = pd.read_csv(raw_path+Qobs_path, sep=';', index_col=0, parse_dates=True)
            # area = float(Qobs_path.split('_')[-3])
            area = BV.geographic.area
            area = int(round(area))
            print(area)
            Qobs = (Qobs / (area*1000000)) * (3600 * 24) # m3/s to m/day
            Qobs = Qobs.squeeze()
            Qobs = Qobs.resample('M').mean() # m/day in monthly
            Qobs = select_period(Qobs, 1990, 2019)
            
            DFobs = pd.DataFrame(columns=['x','y'])
            DFobs['x'] = Cobs
            DFobs['y'] = Qobs
            first_valid_loc = DFobs[DFobs.index.month==10].apply(lambda col: col.first_valid_index()).max().year
            last_valid_loc = DFobs[DFobs.index.month==9].apply(lambda col: col.last_valid_index()).min().year
            DFobs = select_period(DFobs, first_valid_loc, last_valid_loc)
            for idx in range(len(DFobs)):
                if DFobs.index[idx].month == 10:
                    DFobs = DFobs[idx:]   
                    break
            DFobs = DFobs.sort_index(ascending=False)
            for idx in range(len(DFobs)):
                if DFobs.index[idx].month == 9:
                    DFobs = DFobs[idx:]
                    break
            DFobs = DFobs.sort_index(ascending=True)
            def very_resamp(array_like):
                if any(pd.isnull(array_like)):
                    return np.nan
                else:
                    return array_like.sum()
            mask = DFobs.resample("M").count() >= 27
            # DFobs = DFobs.resample('M').apply(very_resamp)[mask]
                        
            hyst = Hysteresis(DFobs, watershed_name)
            hyst.prepare_xy_raw()
            temporal = False
            spece = -0
            norm = False
            hyst.compute_xy_metrics(temporal=temporal, space=space, norm=norm)
            
            columns_x = hyst.xrecapl.columns
            columns_y = hyst.yrecapl.columns
            
            Smod['effective'] = hyst.x
            Smod['outflow_obs'] = hyst.y
            
            x = Smod['effective'] * 30 * 1000
            y = Smod['outflow_obs'] * 30 * 1000
            c = Smod.index.month
            wy = pd.Series(x.index.month).replace([10,11,12,1,2,3,4,5,6,7,8,9],
                                                    [1,2,3,4,5,6,7,8,9,10,11,12])
            xi = x.groupby([lambda x: x.month]).mean()
            yi = y.groupby([lambda y: y.month]).mean()
            # cmapping = mpl.colors.ListedColormap(dict_c[watershed_name])
            cmapping = dict_cmap[watershed_name]
            
            cmap = plt.cm.YlGnBu
            # cmap = parula_map
            # cmaplist = [cmap(i) for i in range(cmap.N)]
            if watershed_name == 'Canut':
                cmaplist = ['limegreen','greenyellow']
            if watershed_name == 'Nancon':
                cmaplist = ['tomato', 'lightsalmon']
            # cmaplist[0] = (.5, .5, .5, 1.0)
            cmap = mpl.colors.LinearSegmentedColormap.from_list(
                'Custom cmap', cmaplist, cmap.N)
            
            scat = ax.scatter(x, y, c=wy, cmap=cmap, marker="o", 
                              s=15, vmin=1, vmax=12, alpha=0.75, ec='none', zorder=-1)
            # c = plt.cm.jet(wy)
            # scat = plt.scatter(x, y, marker="o", 
            #                   s=20, vmin=1, vmax=12, alpha=0.5, edgecolors=dict_c[watershed_name], zorder=-1,
            #                   facecolors="None", lw=0.5)
            xiline = xi.append(xi.iloc[[0]])
            xiline.index = np.arange(1,14,1)
            yiline = yi.append(yi.iloc[[0]])
            yiline.index = np.arange(1,14,1)
            ax.plot(xiline, yiline, linestyle = '-', lw=2, 
                    color=dict_c[watershed_name], zorder=0)
            wyi = np.arange(1,12+1,1)
            compt = 10
            for k in wyi:

                ax.plot(xi[k], yi[k], marker="o", lw=2, markersize=8.5, 
                           markeredgecolor='k', 
                           markerfacecolor='white', markeredgewidth=1.2,
                           linestyle = 'None', zorder=1)
                ax.annotate(k,(xi[k],yi[k]), family='sans-serif', fontsize=5.5, 
                        color=dict_c[watershed_name], weight="bold", ha='center', va='center',
                        zorder=compt)
                compt+=1
            xe = pd.DataFrame()
            xe['q25'] = (x.groupby(x.index.month).quantile(0.25))
            xe['q75'] = (x.groupby(x.index.month).quantile(0.75))        
            ye = pd.DataFrame()
            ye['q25'] = (y.groupby(y.index.month).quantile(0.25))
            ye['q75'] = (y.groupby(y.index.month).quantile(0.75))                
            # ax.errorbar(xi, yi,
            #               yerr=np.vstack([yi-ye.q25, ye.q75-yi]),
            #               xerr=np.vstack([xi-xe.q25, xe.q75-xi]),
            #               ecolor = 'black', fmt = 'none', capsize = 1, elinewidth=0.5, 
            #               capthick=0.5, zorder=1)               
            # ax.axvline(x.median(), c=dict_c[watershed_name], ls='--')
            # ax.axhline(y.median(), c=dict_c[watershed_name], ls='--')

            # ax.plot(np.linspace(0.07,max(x_lim),50), np.linspace(0.07,max(x_lim),50), 
            #          linestyle='-', color='darkgray', linewidth=1, zorder=-1000)
            
            
base_name = figsim_folder+'fig12/'
spec_name = str(watershed_names)+'_R vs Asat'
# fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight') 

#%% HYSTERESIS R vs Qsim

from scipy.stats import binned_statistic

watershed_names = ['Canut','Nancon']

iD = 'calibrated1'

# Things
time_step = 'M'
sim_state = 'transient'
var = 'REC'

# Colored
mod_list = ['REA']
sce_list = ['historic']
sce_cmap = ["Greys"]
sce_color = ["k"]
cmap_dict = dict(zip(sce_list, sce_cmap))
color_dict = dict(zip(sce_list, sce_color))

c = ['darkgreen','darkred']
# c = ['blue','darkmagenta']
cmaps = ['winter','spring']
# cmaps = ['YlGn','RdPu']
dict_c = dict(zip(watershed_names, c))
dict_cmap = dict(zip(watershed_names, cmaps))

# Hysteres
temporal = False
space = 0
norm = False

# fig, axs = plt.subplots(1,4, figsize=(14,3))
# axs = axs.ravel()
# fig3, axs3 = plt.subplots(1,4, figsize=(14,3))
# axs3 = axs3.ravel()

xy_list = [['recharge','outflow_drain']]

# fig, axs = plt.subplots(2,1, figsize=(3.5,6))
# axs = axs.ravel()

# for watershed_name in watershed_names :
#     simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
#     color = 'k'

fig, ax = plt.subplots(1,1, figsize=(4,3.5))
ax.set_xscale('log')
ax.set_xlabel('L² / D [d]')
ax.set_xlabel('R [mm/month]')
# ax.set_ylabel('$A_{int}$ / $A_{per}$ [-]')
ax.set_ylabel('$A_{sat}$ [%]')
# ax.set_xlim(0.1,250)
# ax.set_ylim(-0.05,1)
# ax.set_ylim(1,15)
# ax.set_yticks(np.arange(0,15+1,5))
fig.tight_layout()
# fig3.tight_layout()
ax.set_axisbelow(True)
# ax.grid(zorder=-1000)
# ax.xaxis.grid(color='gray', zorder=-1)
# ax.yaxis.grid(color='gray', zorder=-1)
ax.set_yscale('log')

for watershed_name in watershed_names :
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = 'k'
        
    for mod in mod_list:
        
        for sce in sce_list:
            
            simul_list = glob.glob(simulations_folder+iD+'*'+mod+'*'+sce+'*')
            simul = simul_list[0]
                
            model_name = simul.split('\\')[-1]

            Smod_path = simul+'/_watershed/_simulated_results.csv'  
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            Smod['prop_ratio'] = Smod.intermit_areas / Smod.surflow_areas
            Smod['recharge'] = Smod['recharge'] * 1000 * 30
            Smod['outflow_drain'] = ( Smod['outflow_drain'] + Smod['runoff'] ) * 1000 * 30
            # Smod['groundwater_storage'] = Smod['groundwater_storage']/(Smod['groundwater_storage'].mean())
            Smod['groundwater_storage'] = Smod['groundwater_storage']/1e6
            Smod = select_period(Smod, 1960, 2019)
            
            for xy in xy_list:
                                
                x = Smod[xy[0]]
                y = Smod[xy[1]]
                c = Smod.index.month
                wy = pd.Series(x.index.month).replace([10,11,12,1,2,3,4,5,6,7,8,9],
                                                        [1,2,3,4,5,6,7,8,9,10,11,12])
                xi = x.groupby([lambda x: x.month]).mean()
                yi = y.groupby([lambda y: y.month]).mean()
                cmapping = mpl.colors.ListedColormap(dict_c[watershed_name])
                cmapping = dict_cmap[watershed_name]
                
                cmap = plt.cm.YlGnBu
                # cmap = parula_map
                # cmaplist = [cmap(i) for i in range(cmap.N)]
                if watershed_name == 'Canut':
                    cmaplist = ['limegreen','greenyellow']
                if watershed_name == 'Nancon':
                    cmaplist = ['tomato', 'lightsalmon']
                # cmaplist[0] = (.5, .5, .5, 1.0)
                cmap = mpl.colors.LinearSegmentedColormap.from_list(
                    'Custom cmap', cmaplist, cmap.N)
                
                scat = ax.scatter(x, y, c=wy, cmap=cmap, marker="o", 
                                  s=15, vmin=1, vmax=12, alpha=0.75, ec='none', zorder=-1)
                xiline = xi.append(xi.iloc[[0]])
                xiline.index = np.arange(1,14,1)
                yiline = yi.append(yi.iloc[[0]])
                yiline.index = np.arange(1,14,1)
                ax.plot(xiline, yiline, linestyle = '-', lw=2, 
                        color=dict_c[watershed_name], zorder=0)
                wyi = np.arange(1,12+1,1)
                compt = 10
                for k in wyi:
                    ax.plot(xi[k], yi[k], marker="o", lw=2, markersize=8.5, 
                               markeredgecolor='k', 
                               markerfacecolor='white', markeredgewidth=1.2,
                               linestyle = 'None', zorder=1)
                    ax.annotate(k,(xi[k],yi[k]), family='sans-serif', fontsize=5.5, 
                            color=dict_c[watershed_name], weight="bold", ha='center', va='center',
                            zorder=compt)
                    compt+=1
                xe = pd.DataFrame()
                xe['q25'] = (x.groupby(x.index.month).quantile(0.25))
                xe['q75'] = (x.groupby(x.index.month).quantile(0.75))        
                ye = pd.DataFrame()
                ye['q25'] = (y.groupby(y.index.month).quantile(0.25))
                ye['q75'] = (y.groupby(y.index.month).quantile(0.75))                
                # ax.errorbar(xi, yi,
                #               yerr=np.vstack([yi-ye.q25, ye.q75-yi]),
                #               xerr=np.vstack([xi-xe.q25, xe.q75-xi]),
                #               ecolor = 'black', fmt = 'none', capsize = 1, elinewidth=0.5, 
                #               capthick=0.5, zorder=1)               
                # ax.axvline(x.median(), c=dict_c[watershed_name], ls='--')
                # ax.axhline(y.median(), c=dict_c[watershed_name], ls='--')
                
                # ax.set_yscale('log')
            
            ### OBSERVED
            """
            BV = watershed_root.Watershed(watershed_name=watershed_name,
                                          dem_path=dem_path, 
                                          out_path=out_path,
                                          load=True)
            BV.add_forcing()
            
            stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
        
            raw_path = stable_folder+'/'+'hydrometry/'
            Qobs_path = fnmatch.filter(os.listdir(raw_path), 'Hydrometric_*')[0]
            Qobs = pd.read_csv(raw_path+Qobs_path, sep=';', index_col=0, parse_dates=True)
            # area = float(Qobs_path.split('_')[-3])
            area = BV.geographic.area
            area = int(round(area))
            print(area)
            Qobs = (Qobs / (area*1000000)) * (3600 * 24) # m3/s to m/day
            Qobs = Qobs.squeeze()
            Qobs = Qobs.resample('M').mean() # m/day in monthly
            Qobs = select_period(Qobs, 1990, 2019)
            
            Cobs = dict_recharge[watershed_name]
            
            DFobs = pd.DataFrame(columns=['x','y'])
            DFobs['x'] = Cobs
            DFobs['y'] = Qobs
            first_valid_loc = DFobs[DFobs.index.month==10].apply(lambda col: col.first_valid_index()).max().year
            last_valid_loc = DFobs[DFobs.index.month==9].apply(lambda col: col.last_valid_index()).min().year
            DFobs = select_period(DFobs, first_valid_loc, last_valid_loc)
            for idx in range(len(DFobs)):
                if DFobs.index[idx].month == 10:
                    DFobs = DFobs[idx:]   
                    break
            DFobs = DFobs.sort_index(ascending=False)
            for idx in range(len(DFobs)):
                if DFobs.index[idx].month == 9:
                    DFobs = DFobs[idx:]
                    break
            DFobs = DFobs.sort_index(ascending=True)
            def very_resamp(array_like):
                if any(pd.isnull(array_like)):
                    return np.nan
                else:
                    return array_like.sum()
            mask = DFobs.resample("M").count() >= 27
            # DFobs = DFobs.resample('M').apply(very_resamp)[mask]
                        
            hyst = Hysteresis(DFobs, watershed_name)
            hyst.prepare_xy_raw()
            temporal = False
            spece = -0
            norm = False
            hyst.compute_xy_metrics(temporal=temporal, space=space, norm=norm)
            
            columns_x = hyst.xrecapl.columns
            columns_y = hyst.yrecapl.columns
            
            Smod['effective'] = hyst.x
            Smod['outflow_obs'] = hyst.y
            
            x = Smod['effective'] * 30 * 1000
            y = Smod['outflow_obs'] * 30 * 1000
            c = Smod.index.month
            wy = pd.Series(x.index.month).replace([10,11,12,1,2,3,4,5,6,7,8,9],
                                                    [1,2,3,4,5,6,7,8,9,10,11,12])
            xi = x.groupby([lambda x: x.month]).mean()
            yi = y.groupby([lambda y: y.month]).mean()
            cmapping = mpl.colors.ListedColormap(dict_c[watershed_name])
            cmapping = dict_cmap[watershed_name]
            # scat = ax.scatter(x, y, c=wy, cmap=cmapping, marker="o", 
            #                   s=5, vmin=1, vmax=12, alpha=0.75, ec='none', zorder=-1)
            xiline = xi.append(xi.iloc[[0]])
            xiline.index = np.arange(1,14,1)
            yiline = yi.append(yi.iloc[[0]])
            yiline.index = np.arange(1,14,1)
            ax.plot(xiline, yiline, linestyle = '-', lw=1, 
                    color='r', zorder=0)
            wyi = np.arange(1,12+1,1)
            # compt = 2
            # for k in wyi:
            #     ax.annotate(k,(xi[k],yi[k]), family='sans-serif', fontsize=4, 
            #                  color=dict_c[watershed_name], weight="bold", ha='center', va='center',
            #                  zorder=compt)
            #     ax.plot(xi[k], yi[k], marker="o", lw=2, markersize=7, 
            #                markeredgecolor='k', 
            #                markerfacecolor='white', markeredgewidth=1,
            #                linestyle = 'None', zorder=compt)
            #     compt+=1
            xe = pd.DataFrame()
            xe['q25'] = (x.groupby(x.index.month).quantile(0.25))
            xe['q75'] = (x.groupby(x.index.month).quantile(0.75))        
            ye = pd.DataFrame()
            ye['q25'] = (y.groupby(y.index.month).quantile(0.25))
            ye['q75'] = (y.groupby(y.index.month).quantile(0.75))                
            # ax.errorbar(xi, yi,
            #               yerr=np.vstack([yi-ye.q25, ye.q75-yi]),
            #               xerr=np.vstack([xi-xe.q25, xe.q75-xi]),
            #               ecolor = 'black', fmt = 'none', capsize = 1, elinewidth=0.5, 
            #               capthick=0.5, zorder=1)               
            # ax.axvline(x.median(), c=dict_c[watershed_name], ls='--')
            # ax.axhline(y.median(), c=dict_c[watershed_name], ls='--')

            # ax.plot(np.linspace(0.07,max(x_lim),50), np.linspace(0.07,max(x_lim),50), 
            #          linestyle='-', color='darkgray', linewidth=1, zorder=-1000)
            """
            
base_name = figsim_folder+'fig12/'
spec_name = str(watershed_names)+'_R vs Asat'
# fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight') 

#%% HYSTERESIS R vs Asat

from scipy.stats import binned_statistic

watershed_names = ['Canut','Nancon']

iD = 'calibrated1'

# Things
time_step = 'M'
sim_state = 'transient'
var = 'REC'

# Colored
mod_list = ['REA']
sce_list = ['historic']
sce_cmap = ["Greys"]
sce_color = ["k"]
cmap_dict = dict(zip(sce_list, sce_cmap))
color_dict = dict(zip(sce_list, sce_color))

c = ['darkgreen','darkred']
# c = ['blue','darkmagenta']
cmaps = ['winter','spring']
# cmaps = ['YlGn','RdPu']
dict_c = dict(zip(watershed_names, c))
dict_cmap = dict(zip(watershed_names, cmaps))

# Hysteres
temporal = False
space = 0
norm = False

# fig, axs = plt.subplots(1,4, figsize=(14,3))
# axs = axs.ravel()
# fig3, axs3 = plt.subplots(1,4, figsize=(14,3))
# axs3 = axs3.ravel()

xy_list = [['recharge','surflow_areas']]

for watershed_name in watershed_names :
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = 'k'

# fig, axs = plt.subplots(2,1, figsize=(3.5,6))
# axs = axs.ravel()

fig, ax = plt.subplots(1,1, figsize=(4,3.5))
ax.set_xscale('log')
ax.set_xlabel('L² / D [d]')
ax.set_xlabel('R [mm/month]')
# ax.set_ylabel('$A_{int}$ / $A_{per}$ [-]')
ax.set_ylabel('$A_{sat}$ [%]')
# ax.set_xlim(0.1,250)
# ax.set_ylim(-0.05,1)
# ax.set_ylim(1)
# ax.set_yticks(np.arange(0,15+1,5))
fig.tight_layout()
# fig3.tight_layout()
ax.set_axisbelow(True)
# ax.grid(zorder=-1000)
# ax.xaxis.grid(color='gray', zorder=-1)
# ax.yaxis.grid(color='gray', zorder=-1)
ax.set_yscale('log')
ax.set_yticks([1, 2, 5, 10])
ax.get_yaxis().set_major_formatter(mpl.ticker.ScalarFormatter())

for watershed_name in watershed_names :
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = 'k'
        
    for mod in mod_list:
        
        for sce in sce_list:
            
            simul_list = glob.glob(simulations_folder+iD+'*'+mod+'*'+sce+'*')
            simul = simul_list[0]
                
            model_name = simul.split('\\')[-1]

            Smod_path = simul+'/_watershed/_simulated_results.csv'  
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            Smod['prop_ratio'] = Smod.intermit_areas / Smod.surflow_areas
            Smod['recharge'] = Smod['recharge'] * 1000 * 30
            Smod['outflow_drain'] = ( Smod['outflow_drain'] + Smod['runoff'] ) * 1000 * 30
            # Smod['groundwater_storage'] = Smod['groundwater_storage']/(Smod['groundwater_storage'].mean())
            Smod['groundwater_storage'] = Smod['groundwater_storage']/1e6
            Smod = select_period(Smod, 1960, 2019)
            
            for xy in xy_list:
                                
                x = Smod[xy[0]]
                y = Smod[xy[1]]
                c = Smod.index.month
                wy = pd.Series(x.index.month).replace([10,11,12,1,2,3,4,5,6,7,8,9],
                                                        [1,2,3,4,5,6,7,8,9,10,11,12])
                xi = x.groupby([lambda x: x.month]).mean()
                yi = y.groupby([lambda y: y.month]).mean()
                cmapping = mpl.colors.ListedColormap(dict_c[watershed_name])
                cmapping = dict_cmap[watershed_name]
                
                cmap = plt.cm.YlGnBu
                # cmap = parula_map
                # cmaplist = [cmap(i) for i in range(cmap.N)]
                if watershed_name == 'Canut':
                    cmaplist = ['limegreen','greenyellow']
                if watershed_name == 'Nancon':
                    cmaplist = ['tomato', 'lightsalmon']
                # cmaplist[0] = (.5, .5, .5, 1.0)
                cmap = mpl.colors.LinearSegmentedColormap.from_list(
                    'Custom cmap', cmaplist, cmap.N)
                
                scat = ax.scatter(x, y, c=wy, cmap=cmap, marker="o", 
                                  s=15, vmin=1, vmax=12, alpha=0.75, ec='none', zorder=-1)
                xiline = xi.append(xi.iloc[[0]])
                xiline.index = np.arange(1,14,1)
                yiline = yi.append(yi.iloc[[0]])
                yiline.index = np.arange(1,14,1)
                ax.plot(xiline, yiline, linestyle = '-', lw=2, 
                        color=dict_c[watershed_name], zorder=0)
                wyi = np.arange(1,12+1,1)
                compt = 10
                for k in wyi:
                    ax.plot(xi[k], yi[k], marker="o", lw=2, markersize=8.5, 
                               markeredgecolor='k', 
                               markerfacecolor='white', markeredgewidth=1.2,
                               linestyle = 'None', zorder=1)
                    ax.annotate(k,(xi[k],yi[k]), family='sans-serif', fontsize=5.5, 
                            color=dict_c[watershed_name], weight="bold", ha='center', va='center',
                            zorder=compt)
                    compt+=1
                xe = pd.DataFrame()
                xe['q25'] = (x.groupby(x.index.month).quantile(0.25))
                xe['q75'] = (x.groupby(x.index.month).quantile(0.75))        
                ye = pd.DataFrame()
                ye['q25'] = (y.groupby(y.index.month).quantile(0.25))
                ye['q75'] = (y.groupby(y.index.month).quantile(0.75))                
                # ax.errorbar(xi, yi,
                #               yerr=np.vstack([yi-ye.q25, ye.q75-yi]),
                #               xerr=np.vstack([xi-xe.q25, xe.q75-xi]),
                #               ecolor = 'black', fmt = 'none', capsize = 1, elinewidth=0.5, 
                #               capthick=0.5, zorder=1)               
                # ax.axvline(x.median(), c=dict_c[watershed_name], ls='--')
                # ax.axhline(y.median(), c=dict_c[watershed_name], ls='--')
                
                # ax.set_yscale('log')
            
            ### OBSERVED
            """
            BV = watershed_root.Watershed(watershed_name=watershed_name,
                                          dem_path=dem_path, 
                                          out_path=out_path,
                                          load=True)
            BV.add_forcing()
            
            stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
        
            raw_path = stable_folder+'/'+'hydrometry/'
            Qobs_path = fnmatch.filter(os.listdir(raw_path), 'Hydrometric_*')[0]
            Qobs = pd.read_csv(raw_path+Qobs_path, sep=';', index_col=0, parse_dates=True)
            # area = float(Qobs_path.split('_')[-3])
            area = BV.geographic.area
            area = int(round(area))
            print(area)
            Qobs = (Qobs / (area*1000000)) * (3600 * 24) # m3/s to m/day
            Qobs = Qobs.squeeze()
            Qobs = Qobs.resample('M').mean() # m/day in monthly
            Qobs = select_period(Qobs, 1990, 2019)
            
            Cobs = dict_recharge[watershed_name]
            
            DFobs = pd.DataFrame(columns=['x','y'])
            DFobs['x'] = Cobs
            DFobs['y'] = Qobs
            first_valid_loc = DFobs[DFobs.index.month==10].apply(lambda col: col.first_valid_index()).max().year
            last_valid_loc = DFobs[DFobs.index.month==9].apply(lambda col: col.last_valid_index()).min().year
            DFobs = select_period(DFobs, first_valid_loc, last_valid_loc)
            for idx in range(len(DFobs)):
                if DFobs.index[idx].month == 10:
                    DFobs = DFobs[idx:]   
                    break
            DFobs = DFobs.sort_index(ascending=False)
            for idx in range(len(DFobs)):
                if DFobs.index[idx].month == 9:
                    DFobs = DFobs[idx:]
                    break
            DFobs = DFobs.sort_index(ascending=True)
            def very_resamp(array_like):
                if any(pd.isnull(array_like)):
                    return np.nan
                else:
                    return array_like.sum()
            mask = DFobs.resample("M").count() >= 27
            # DFobs = DFobs.resample('M').apply(very_resamp)[mask]
                        
            hyst = Hysteresis(DFobs, watershed_name)
            hyst.prepare_xy_raw()
            temporal = False
            spece = -0
            norm = False
            hyst.compute_xy_metrics(temporal=temporal, space=space, norm=norm)
            
            columns_x = hyst.xrecapl.columns
            columns_y = hyst.yrecapl.columns
            
            Smod['effective'] = hyst.x
            Smod['outflow_obs'] = hyst.y
            
            x = Smod['effective'] * 30 * 1000
            y = Smod['outflow_obs'] * 30 * 1000
            c = Smod.index.month
            wy = pd.Series(x.index.month).replace([10,11,12,1,2,3,4,5,6,7,8,9],
                                                    [1,2,3,4,5,6,7,8,9,10,11,12])
            xi = x.groupby([lambda x: x.month]).mean()
            yi = y.groupby([lambda y: y.month]).mean()
            cmapping = mpl.colors.ListedColormap(dict_c[watershed_name])
            cmapping = dict_cmap[watershed_name]
            # scat = ax.scatter(x, y, c=wy, cmap=cmapping, marker="o", 
            #                   s=5, vmin=1, vmax=12, alpha=0.75, ec='none', zorder=-1)
            xiline = xi.append(xi.iloc[[0]])
            xiline.index = np.arange(1,14,1)
            yiline = yi.append(yi.iloc[[0]])
            yiline.index = np.arange(1,14,1)
            ax.plot(xiline, yiline, linestyle = '-', lw=1, 
                    color='r', zorder=0)
            wyi = np.arange(1,12+1,1)
            # compt = 2
            # for k in wyi:
            #     ax.annotate(k,(xi[k],yi[k]), family='sans-serif', fontsize=4, 
            #                  color=dict_c[watershed_name], weight="bold", ha='center', va='center',
            #                  zorder=compt)
            #     ax.plot(xi[k], yi[k], marker="o", lw=2, markersize=7, 
            #                markeredgecolor='k', 
            #                markerfacecolor='white', markeredgewidth=1,
            #                linestyle = 'None', zorder=compt)
            #     compt+=1
            xe = pd.DataFrame()
            xe['q25'] = (x.groupby(x.index.month).quantile(0.25))
            xe['q75'] = (x.groupby(x.index.month).quantile(0.75))        
            ye = pd.DataFrame()
            ye['q25'] = (y.groupby(y.index.month).quantile(0.25))
            ye['q75'] = (y.groupby(y.index.month).quantile(0.75))                
            # ax.errorbar(xi, yi,
            #               yerr=np.vstack([yi-ye.q25, ye.q75-yi]),
            #               xerr=np.vstack([xi-xe.q25, xe.q75-xi]),
            #               ecolor = 'black', fmt = 'none', capsize = 1, elinewidth=0.5, 
            #               capthick=0.5, zorder=1)               
            # ax.axvline(x.median(), c=dict_c[watershed_name], ls='--')
            # ax.axhline(y.median(), c=dict_c[watershed_name], ls='--')

            # ax.plot(np.linspace(0.07,max(x_lim),50), np.linspace(0.07,max(x_lim),50), 
            #          linestyle='-', color='darkgray', linewidth=1, zorder=-1000)
            """
            
base_name = figsim_folder+'06_hysteresis/'
spec_name = str(watershed_names)+'_hysteresis_RvsAsat'
fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight')

#%% HYSTERESIS R vs Aint/Asat

from scipy.stats import binned_statistic

watershed_names = ['Canut','Nancon']

iD = 'calibrated1'

# Things
time_step = 'M'
sim_state = 'transient'
var = 'REC'

# Colored
mod_list = ['REA']
sce_list = ['historic']
sce_cmap = ["Greys"]
sce_color = ["k"]
cmap_dict = dict(zip(sce_list, sce_cmap))
color_dict = dict(zip(sce_list, sce_color))

c = ['darkgreen','darkred']
# c = ['blue','darkmagenta']
cmaps = ['winter','spring']
# cmaps = ['YlGn','RdPu']
dict_c = dict(zip(watershed_names, c))
dict_cmap = dict(zip(watershed_names, cmaps))

# Hysteres
temporal = False
space = 0
norm = False

# fig, axs = plt.subplots(1,4, figsize=(14,3))
# axs = axs.ravel()
# fig3, axs3 = plt.subplots(1,4, figsize=(14,3))
# axs3 = axs3.ravel()

xy_list = [['recharge','prop_ratio']]

# fig, axs = plt.subplots(2,1, figsize=(3.5,6))
# axs = axs.ravel()

fig, ax = plt.subplots(1,1, figsize=(4,3.5))
ax.set_xscale('log')
ax.set_xlabel('L² / D [d]')
ax.set_xlabel('R [mm/month]')
# ax.set_ylabel('$A_{int}$ / $A_{per}$ [-]')
ax.set_ylabel('$A_{sat}$ [%]')
# ax.set_xlim(0.1,250)
# ax.set_ylim(-0.05,1)
# ax.set_ylim(1,15)
# ax.set_yticks(np.arange(0,15+1,5))
fig.tight_layout()
# fig3.tight_layout()
ax.set_axisbelow(True)
# ax.grid(zorder=-1000)
# ax.xaxis.grid(color='gray', zorder=-1)
# ax.yaxis.grid(color='gray', zorder=-1)
ax.set_yscale('log')

for watershed_name in watershed_names :
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = 'k'
        
    for mod in mod_list:
        
        for sce in sce_list:
            
            simul_list = glob.glob(simulations_folder+iD+'*'+mod+'*'+sce+'*')
            simul = simul_list[0]
                
            model_name = simul.split('\\')[-1]

            Smod_path = simul+'/_watershed/_simulated_results.csv'  
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            Smod['prop_ratio'] = Smod.intermit_areas / Smod.surflow_areas
            Smod['recharge'] = Smod['recharge'] * 1000 * 30
            Smod['outflow_drain'] = ( Smod['outflow_drain'] + Smod['runoff'] ) * 1000 * 30
            # Smod['groundwater_storage'] = Smod['groundwater_storage']/(Smod['groundwater_storage'].mean())
            Smod['groundwater_storage'] = Smod['groundwater_storage']/1e6
            Smod = select_period(Smod, 1960, 2019)
            
            for xy in xy_list:
                                
                x = Smod[xy[0]]
                y = Smod[xy[1]]
                c = Smod.index.month
                wy = pd.Series(x.index.month).replace([10,11,12,1,2,3,4,5,6,7,8,9],
                                                        [1,2,3,4,5,6,7,8,9,10,11,12])
                xi = x.groupby([lambda x: x.month]).mean()
                yi = y.groupby([lambda y: y.month]).mean()
                cmapping = mpl.colors.ListedColormap(dict_c[watershed_name])
                cmapping = dict_cmap[watershed_name]
                
                cmap = plt.cm.YlGnBu
                # cmap = parula_map
                # cmaplist = [cmap(i) for i in range(cmap.N)]
                if watershed_name == 'Canut':
                    cmaplist = ['limegreen','greenyellow']
                if watershed_name == 'Nancon':
                    cmaplist = ['tomato', 'lightsalmon']
                # cmaplist[0] = (.5, .5, .5, 1.0)
                cmap = mpl.colors.LinearSegmentedColormap.from_list(
                    'Custom cmap', cmaplist, cmap.N)
                
                scat = ax.scatter(x, y, c=wy, cmap=cmap, marker="o", 
                                  s=15, vmin=1, vmax=12, alpha=0.75, ec='none', zorder=-1)
                xiline = xi.append(xi.iloc[[0]])
                xiline.index = np.arange(1,14,1)
                yiline = yi.append(yi.iloc[[0]])
                yiline.index = np.arange(1,14,1)
                ax.plot(xiline, yiline, linestyle = '-', lw=2, 
                        color=dict_c[watershed_name], zorder=0)
                wyi = np.arange(1,12+1,1)
                compt = 10
                for k in wyi:
                    ax.plot(xi[k], yi[k], marker="o", lw=2, markersize=8.5, 
                               markeredgecolor='k', 
                               markerfacecolor='white', markeredgewidth=1.2,
                               linestyle = 'None', zorder=1)
                    ax.annotate(k,(xi[k],yi[k]), family='sans-serif', fontsize=5.5, 
                            color=dict_c[watershed_name], weight="bold", ha='center', va='center',
                            zorder=compt)
                    compt+=1
                xe = pd.DataFrame()
                xe['q25'] = (x.groupby(x.index.month).quantile(0.25))
                xe['q75'] = (x.groupby(x.index.month).quantile(0.75))        
                ye = pd.DataFrame()
                ye['q25'] = (y.groupby(y.index.month).quantile(0.25))
                ye['q75'] = (y.groupby(y.index.month).quantile(0.75))                
                # ax.errorbar(xi, yi,
                #               yerr=np.vstack([yi-ye.q25, ye.q75-yi]),
                #               xerr=np.vstack([xi-xe.q25, xe.q75-xi]),
                #               ecolor = 'black', fmt = 'none', capsize = 1, elinewidth=0.5, 
                #               capthick=0.5, zorder=1)               
                # ax.axvline(x.median(), c=dict_c[watershed_name], ls='--')
                # ax.axhline(y.median(), c=dict_c[watershed_name], ls='--')
                
                # ax.set_yscale('log')
            
            ### OBSERVED
            """
            BV = watershed_root.Watershed(watershed_name=watershed_name,
                                          dem_path=dem_path, 
                                          out_path=out_path,
                                          load=True)
            BV.add_forcing()
            
            stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
        
            raw_path = stable_folder+'/'+'hydrometry/'
            Qobs_path = fnmatch.filter(os.listdir(raw_path), 'Hydrometric_*')[0]
            Qobs = pd.read_csv(raw_path+Qobs_path, sep=';', index_col=0, parse_dates=True)
            # area = float(Qobs_path.split('_')[-3])
            area = BV.geographic.area
            area = int(round(area))
            print(area)
            Qobs = (Qobs / (area*1000000)) * (3600 * 24) # m3/s to m/day
            Qobs = Qobs.squeeze()
            Qobs = Qobs.resample('M').mean() # m/day in monthly
            Qobs = select_period(Qobs, 1990, 2019)
            
            Cobs = dict_recharge[watershed_name]
            
            DFobs = pd.DataFrame(columns=['x','y'])
            DFobs['x'] = Cobs
            DFobs['y'] = Qobs
            first_valid_loc = DFobs[DFobs.index.month==10].apply(lambda col: col.first_valid_index()).max().year
            last_valid_loc = DFobs[DFobs.index.month==9].apply(lambda col: col.last_valid_index()).min().year
            DFobs = select_period(DFobs, first_valid_loc, last_valid_loc)
            for idx in range(len(DFobs)):
                if DFobs.index[idx].month == 10:
                    DFobs = DFobs[idx:]   
                    break
            DFobs = DFobs.sort_index(ascending=False)
            for idx in range(len(DFobs)):
                if DFobs.index[idx].month == 9:
                    DFobs = DFobs[idx:]
                    break
            DFobs = DFobs.sort_index(ascending=True)
            def very_resamp(array_like):
                if any(pd.isnull(array_like)):
                    return np.nan
                else:
                    return array_like.sum()
            mask = DFobs.resample("M").count() >= 27
            # DFobs = DFobs.resample('M').apply(very_resamp)[mask]
                        
            hyst = Hysteresis(DFobs, watershed_name)
            hyst.prepare_xy_raw()
            temporal = False
            spece = -0
            norm = False
            hyst.compute_xy_metrics(temporal=temporal, space=space, norm=norm)
            
            columns_x = hyst.xrecapl.columns
            columns_y = hyst.yrecapl.columns
            
            Smod['effective'] = hyst.x
            Smod['outflow_obs'] = hyst.y
            
            x = Smod['effective'] * 30 * 1000
            y = Smod['outflow_obs'] * 30 * 1000
            c = Smod.index.month
            wy = pd.Series(x.index.month).replace([10,11,12,1,2,3,4,5,6,7,8,9],
                                                    [1,2,3,4,5,6,7,8,9,10,11,12])
            xi = x.groupby([lambda x: x.month]).mean()
            yi = y.groupby([lambda y: y.month]).mean()
            cmapping = mpl.colors.ListedColormap(dict_c[watershed_name])
            cmapping = dict_cmap[watershed_name]
            # scat = ax.scatter(x, y, c=wy, cmap=cmapping, marker="o", 
            #                   s=5, vmin=1, vmax=12, alpha=0.75, ec='none', zorder=-1)
            xiline = xi.append(xi.iloc[[0]])
            xiline.index = np.arange(1,14,1)
            yiline = yi.append(yi.iloc[[0]])
            yiline.index = np.arange(1,14,1)
            ax.plot(xiline, yiline, linestyle = '-', lw=1, 
                    color='r', zorder=0)
            wyi = np.arange(1,12+1,1)
            # compt = 2
            # for k in wyi:
            #     ax.annotate(k,(xi[k],yi[k]), family='sans-serif', fontsize=4, 
            #                  color=dict_c[watershed_name], weight="bold", ha='center', va='center',
            #                  zorder=compt)
            #     ax.plot(xi[k], yi[k], marker="o", lw=2, markersize=7, 
            #                markeredgecolor='k', 
            #                markerfacecolor='white', markeredgewidth=1,
            #                linestyle = 'None', zorder=compt)
            #     compt+=1
            xe = pd.DataFrame()
            xe['q25'] = (x.groupby(x.index.month).quantile(0.25))
            xe['q75'] = (x.groupby(x.index.month).quantile(0.75))        
            ye = pd.DataFrame()
            ye['q25'] = (y.groupby(y.index.month).quantile(0.25))
            ye['q75'] = (y.groupby(y.index.month).quantile(0.75))                
            # ax.errorbar(xi, yi,
            #               yerr=np.vstack([yi-ye.q25, ye.q75-yi]),
            #               xerr=np.vstack([xi-xe.q25, xe.q75-xi]),
            #               ecolor = 'black', fmt = 'none', capsize = 1, elinewidth=0.5, 
            #               capthick=0.5, zorder=1)               
            # ax.axvline(x.median(), c=dict_c[watershed_name], ls='--')
            # ax.axhline(y.median(), c=dict_c[watershed_name], ls='--')

            # ax.plot(np.linspace(0.07,max(x_lim),50), np.linspace(0.07,max(x_lim),50), 
            #          linestyle='-', color='darkgray', linewidth=1, zorder=-1000)
            """
            
#%% DELTA dR vs d(Aint/Asat)

from scipy.stats import binned_statistic

watershed_names = ['Canut','Nancon']

typ = 'calibrated1'

# Things
time_step = 'M'
sim_state = 'transient'
var = 'REC'

# Colored
mod_list = ['REA']
sce_list = ['historic']
sce_cmap = ["Greys"]
sce_color = ["k"]
cmap_dict = dict(zip(sce_list, sce_cmap))
color_dict = dict(zip(sce_list, sce_color))

c = ['forestgreen','darkred']
# c = ['blue','darkmagenta']
cmaps = ['winter','spring']
# cmaps = ['YlGn','RdPu']
dict_c = dict(zip(watershed_names, c))
dict_cmap = dict(zip(watershed_names, cmaps))

# Hysteres
temporal = False
space = 0
norm = False

# fig, axs = plt.subplots(1,4, figsize=(14,3))
# axs = axs.ravel()
# fig3, axs3 = plt.subplots(1,4, figsize=(14,3))
# axs3 = axs3.ravel()

xy_list = [['recharge','prop_ratio']]

# fig, axs = plt.subplots(2,1, figsize=(3.5,6))
# axs = axs.ravel()

for watershed_name in watershed_names[:1]:
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = 'k'

    fig, ax = plt.subplots(1,1, figsize=(3.5,4))
    # ax.set_xscale('log')
    # ax.set_ylabel('$A_{int}$ / $A_{per}$ [-]')
    ax.set_xlabel('\u0394R [mm/month]')
    ax.set_ylabel('\u0394$ (A_{int}$ / $A_{sat}$) [-]')
    # ax.set_xlim(0,3000)
    # ax.set_ylim(-0.05,1)
    ax.set_ylim(-0.30, 0.30)
    # ax.set_yticks(np.arange(0,15+1,5))
    fig.tight_layout()
    # fig3.tight_layout()
    ax.set_axisbelow(True)
    # ax.grid(zorder=-1000)
    # ax.xaxis.grid(color='gray', zorder=-1)
    # ax.yaxis.grid(color='gray', zorder=-1)
    ax.axhline(y=0, color='grey', ls='--', zorder=-1000)
    ax.axvline(x=0, color='grey', ls='--', zorder=-1000)
    # ax.set_ylim(-4, 4)
    # ax.set_ylim(-3, 3)
    ax.set_xlim(-30, 30)

# for watershed_name in watershed_names[:]:
#     simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
#     color = 'k'
        
    for mod in mod_list:
        
        for sce in sce_list:
            
            simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+sce+'*')
            simul = simul_list[0]
                
            model_name = simul.split('\\')[-1]

            Smod_path = simul+'/_watershed/_simulated_results.csv'     
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            Smod['prop_ratio'] = Smod.intermit_areas / Smod.surflow_areas
            Smod['recharge'] = Smod['recharge'] * 1000 * 30
            Smod['outflow_drain'] = Smod['outflow_drain'] * 1000 * 30
            Smod['groundwater_storage'] = (Smod['groundwater_storage']/(Smod['groundwater_storage'].mean()))
            # Smod['groundwater_storage'] = Smod['groundwater_storage']/1e6
            Smod = select_period(Smod, 1960, 2019)
            
            for xy in xy_list:
                
                per = 1
                x = Smod[xy[0]].diff(periods=per)
                y = Smod[xy[1]].diff(periods=per)
                c = Smod.index.month
                wy = pd.Series(x.index.month).replace([10,11,12,1,2,3,4,5,6,7,8,9],
                                                        [1,2,3,4,5,6,7,8,9,10,11,12])
                xi = x.groupby([lambda x: x.month]).mean()
                yi = y.groupby([lambda y: y.month]).mean()
                cmapping = mpl.colors.ListedColormap(dict_c[watershed_name])
                cmapping = dict_cmap[watershed_name]
                
                cmap = plt.cm.YlGnBu
                # cmap = parula_map
                # cmaplist = [cmap(i) for i in range(cmap.N)]
                if watershed_name == 'Canut':
                    cmaplist = ['limegreen','greenyellow']
                if watershed_name == 'Nancon':
                    cmaplist = ['tomato', 'lightsalmon']
                # cmaplist[0] = (.5, .5, .5, 1.0)
                cmap = mpl.colors.LinearSegmentedColormap.from_list(
                    'Custom cmap', cmaplist, cmap.N)
                
                scat = ax.scatter(x, y, c=wy, cmap=cmap, marker="o", 
                                  s=15, vmin=1, vmax=12, alpha=0.75, ec='none', zorder=-1)
                xiline = xi.append(xi.iloc[[0]])
                xiline.index = np.arange(1,14,1)
                yiline = yi.append(yi.iloc[[0]])
                yiline.index = np.arange(1,14,1)
                ax.plot(xiline, yiline, linestyle = '-', lw=2, 
                        color=dict_c[watershed_name], zorder=0)
                wyi = np.arange(1,12+1,1)
                compt = 2
                for k in wyi:
                    ax.plot(xi[k], yi[k], marker="o", lw=2, markersize=8.5, 
                               markeredgecolor='k', 
                               markerfacecolor='white', markeredgewidth=1.2,
                               linestyle = 'None', zorder=compt)
                    ax.annotate(k,(xi[k],yi[k]), family='sans-serif', fontsize=5.5, 
                                 color=dict_c[watershed_name], weight="bold", ha='center', va='center',
                                 zorder=compt)
                    compt+=1
                xe = pd.DataFrame()
                xe['q25'] = (x.groupby(x.index.month).quantile(0.25))
                xe['q75'] = (x.groupby(x.index.month).quantile(0.75))        
                ye = pd.DataFrame()
                ye['q25'] = (y.groupby(y.index.month).quantile(0.25))
                ye['q75'] = (y.groupby(y.index.month).quantile(0.75))                
                # ax.errorbar(xi, yi,
                #               yerr=np.vstack([yi-ye.q25, ye.q75-yi]),
                #               xerr=np.vstack([xi-xe.q25, xe.q75-xi]),
                #               ecolor = 'black', fmt = 'none', capsize = 1, elinewidth=0.5, 
                #               capthick=0.5, zorder=1)               
                # ax.axvline(x.median(), c=dict_c[watershed_name], ls='--')
    
    base_name = figsim_folder+'06_hysteresis/'
    spec_name = watershed_name+'_hysteresis_dRvsAratio'
    # fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight')

#%% HYSTERESIS Tr vs Aint/Asat

from scipy.stats import binned_statistic

watershed_names = ['Canut','Nancon']

iD = 'calibrated1'

# Things
time_step = 'M'
sim_state = 'transient'
var = 'REC'

# Colored
mod_list = ['REA']
sce_list = ['historic']
sce_cmap = ["Greys"]
sce_color = ["k"]
cmap_dict = dict(zip(sce_list, sce_cmap))
color_dict = dict(zip(sce_list, sce_color))

c = ['darkgreen','darkred']
# c = ['blue','darkmagenta']
cmaps = ['winter','spring']
# cmaps = ['YlGn','RdPu']
dict_c = dict(zip(watershed_names, c))
dict_cmap = dict(zip(watershed_names, cmaps))

# Hysteres
temporal = False
space = 0
norm = False

# fig, axs = plt.subplots(1,4, figsize=(14,3))
# axs = axs.ravel()
# fig3, axs3 = plt.subplots(1,4, figsize=(14,3))
# axs3 = axs3.ravel()

xy_list = [['groundwater_storage','outflow_drain','prop_ratio']]

for watershed_name in watershed_names :
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = 'k'

# fig, axs = plt.subplots(2,1, figsize=(3.5,6))
# axs = axs.ravel()

fig, ax = plt.subplots(1,1, figsize=(4,3.5))
ax.set_xscale('symlog')
ax.set_xlabel('L² / D [d]')
ax.set_xlabel('R [mm/month]')
# ax.set_ylabel('$A_{int}$ / $A_{per}$ [-]')
ax.set_xlabel('\u0394$S_{gws}$ / \u0394$Q_{spe}$ [d]')
ax.set_ylabel('$A_{int}$ / $A_{sat}$ [-]')
ax.set_xlim(1,10000)
# ax.set_ylim(-0.05,1)
ax.set_ylim(-0.05,1)
# ax.set_yticks(np.arange(0,15+1,5))
fig.tight_layout()
# fig3.tight_layout()
ax.set_axisbelow(True)
# ax.grid(zorder=-1000)
# ax.xaxis.grid(color='gray', zorder=-1)
# ax.yaxis.grid(color='gray', zorder=-1)
# ax.set_yscale('log')
# ax.set_yticks([2, 5, 10])
# ax.get_yaxis().set_major_formatter(mpl.ticker.ScalarFormatter())

for watershed_name in watershed_names :
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = 'k'
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True)

    area = BV.geographic.area
    area = int(round(area))
        
    for mod in mod_list:
        
        for sce in sce_list:
            
            simul_list = glob.glob(simulations_folder+iD+'*'+mod+'*'+sce+'*')
            simul = simul_list[0]
                
            model_name = simul.split('\\')[-1]

            Smod_path = simul+'/_watershed/_simulated_results.csv'  
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            Smod['prop_ratio'] = Smod.intermit_areas / Smod.surflow_areas
            Smod['recharge'] = Smod['recharge'] * 1000 * 30
            Smod['outflow_drain'] =  ( Smod['outflow_drain'] ) * (area * 1e6) #+ Smod['runoff'] ) # * (area * 1e6)
            # Smod['groundwater_storage'] = Smod['groundwater_storage']/(Smod['groundwater_storage'].mean())
            Smod['groundwater_storage'] = Smod['groundwater_storage']
            Smod = select_period(Smod, 1960, 2019)
            
            
            for xy in xy_list:
                per = 1
                x = abs(Smod[xy[0]].diff(periods=per) / Smod[xy[1]].diff(periods=per))
                Smod['dQ'] = Smod[xy[1]].diff()
                Smod['dGW'] = Smod[xy[0]].diff()
                # plt.plot(Smod.dQ)
                # plt.plot(Smod.dGW)
                Smod['t'] = (Smod[xy[0]].diff(periods=per) / Smod[xy[1]].diff(periods=per))
                # x[Smod['t']<0] = np.nan
                y = Smod[xy[2]]
                # y[Smod['t']<0] = np.nan
                c = Smod.index.month
                wy = pd.Series(x.index.month).replace([10,11,12,1,2,3,4,5,6,7,8,9],
                                                        [1,2,3,4,5,6,7,8,9,10,11,12])
                xi = x.groupby([lambda x: x.month]).mean()
                yi = y.groupby([lambda y: y.month]).mean()
                cmapping = mpl.colors.ListedColormap(dict_c[watershed_name])
                cmapping = dict_cmap[watershed_name]
                
                count_t0 = (Smod.t < 0).sum().sum()
                count_t0_GWp_Qn = ((Smod.t < 0)&(Smod.dQ < 0)).sum().sum()
                count_t0_GWn_Qp = ((Smod.t < 0)&(Smod.dGW < 0)).sum().sum()
                print(count_t0, count_t0_GWp_Qn, count_t0_GWn_Qp)
                
                cmap = plt.cm.YlGnBu
                # cmap = parula_map
                # cmaplist = [cmap(i) for i in range(cmap.N)]
                if watershed_name == 'Canut':
                    cmaplist = ['limegreen','greenyellow']
                if watershed_name == 'Nancon':
                    cmaplist = ['tomato', 'lightsalmon']
                # cmaplist[0] = (.5, .5, .5, 1.0)
                cmap = mpl.colors.LinearSegmentedColormap.from_list(
                    'Custom cmap', cmaplist, cmap.N)
                
                scat = ax.scatter(x, y, c=wy, cmap=cmap, marker="o", 
                                  s=15, vmin=1, vmax=12, alpha=0.75, ec='none', zorder=-1)
                
                # scat = ax.scatter(x, y, c=wy, cmap=cmap, marker="o", 
                #                   s=15, vmin=1, vmax=12, alpha=0.75, ec='none', zorder=-1)
                
                xiline = xi.append(xi.iloc[[0]])
                xiline.index = np.arange(1,14,1)
                yiline = yi.append(yi.iloc[[0]])
                yiline.index = np.arange(1,14,1)
                ax.plot(xiline, yiline, linestyle = '-', lw=2, 
                        color=dict_c[watershed_name], zorder=0)
                wyi = np.arange(1,12+1,1)
                compt = 2
                for k in wyi:
                    ax.plot(xi[k], yi[k], marker="o", lw=2, markersize=8.5, 
                               markeredgecolor='k', 
                               markerfacecolor='white', markeredgewidth=1.2,
                               linestyle = 'None', zorder=compt)
                    ax.annotate(k,(xi[k],yi[k]), family='sans-serif', fontsize=5.5, 
                            color=dict_c[watershed_name], weight="bold", ha='center', va='center',
                            zorder=compt)
                    compt+=1
                xe = pd.DataFrame()
                xe['q25'] = (x.groupby(x.index.month).quantile(0.25))
                xe['q75'] = (x.groupby(x.index.month).quantile(0.75))        
                ye = pd.DataFrame()
                ye['q25'] = (y.groupby(y.index.month).quantile(0.25))
                ye['q75'] = (y.groupby(y.index.month).quantile(0.75))                
                # ax.errorbar(xi, yi,
                #               yerr=np.vstack([yi-ye.q25, ye.q75-yi]),
                #               xerr=np.vstack([xi-xe.q25, xe.q75-xi]),
                #               ecolor = 'black', fmt = 'none', capsize = 1, elinewidth=0.5, 
                #               capthick=0.5, zorder=1)               
                # ax.axvline(x.median(), c=dict_c[watershed_name], ls='--', lw=1, zorder=-1000)
                # ax.axhline(y.median(), c=dict_c[watershed_name], ls='--', lw=1, zorder=-1000)
                
                if watershed_name == 'Canut':
                    ax.axvline(x.median(), c='dimgray', ls='--', lw=1.5, zorder=0)
                    # ax.axhline(y.median(), c='dimgray', ls='--', lw=1.5, zorder=0)
                if watershed_name == 'Nancon':
                    ax.axvline(x.median(), c='dimgray', ls='--', lw=1.5, zorder=0)
                    # ax.axhline(y.median(), c='dimgray', ls='--', lw=1.5, zorder=0)
                # ax.set_yscale('log')
                print(x.median(), y.median())
                
            
base_name = figsim_folder+'06_hysteresis/'
spec_name = str(watershed_names)+'_hysteresis_TvsAratio'
fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight')

#%% DELTA dGW vs dQ

from scipy.stats import binned_statistic

watershed_names = ['Canut','Nancon']

typ = 'calibrated1'

# Things
time_step = 'M'
sim_state = 'transient'
var = 'REC'

# Colored
mod_list = ['REA']
sce_list = ['historic']
sce_cmap = ["Greys"]
sce_color = ["k"]
cmap_dict = dict(zip(sce_list, sce_cmap))
color_dict = dict(zip(sce_list, sce_color))

c = ['forestgreen','darkred']
# c = ['blue','darkmagenta']
cmaps = ['winter','spring']
# cmaps = ['YlGn','RdPu']
dict_c = dict(zip(watershed_names, c))
dict_cmap = dict(zip(watershed_names, cmaps))

# Hysteres
temporal = False
space = 0
norm = False

# fig, axs = plt.subplots(1,4, figsize=(14,3))
# axs = axs.ravel()
# fig3, axs3 = plt.subplots(1,4, figsize=(14,3))
# axs3 = axs3.ravel()

xy_list = [['groundwater_storage','outflow_drain']]

# fig, axs = plt.subplots(2,1, figsize=(3.5,6))
# axs = axs.ravel()

for watershed_name in watershed_names[:]:
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = 'k'

    fig, ax = plt.subplots(1,1, figsize=(3.5,4))
    # ax.set_xscale('log')
    # ax.set_ylabel('$A_{int}$ / $A_{per}$ [-]')
    ax.set_xlabel('\u0394R [mm/month]')
    ax.set_ylabel('\u0394$ (A_{int}$ / $A_{sat}$) [-]')
    # ax.set_xlim(0,3000)
    # ax.set_ylim(-0.05,1)
    # ax.set_ylim(-0.30, 0.30)
    # ax.set_yticks(np.arange(0,15+1,5))
    fig.tight_layout()
    # fig3.tight_layout()
    ax.set_axisbelow(True)
    # ax.grid(zorder=-1000)
    # ax.xaxis.grid(color='gray', zorder=-1)
    # ax.yaxis.grid(color='gray', zorder=-1)
    ax.axhline(y=0, color='grey', ls='--', zorder=-1000)
    ax.axvline(x=0, color='grey', ls='--', zorder=-1000)
    # ax.set_ylim(-4, 4)
    # ax.set_ylim(-3, 3)
    # ax.set_xlim(-30, 30)
    
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True)

    area = BV.geographic.area
    area = int(round(area))

# for watershed_name in watershed_names[:]:
#     simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
#     color = 'k'
        
    for mod in mod_list:
        
        for sce in sce_list:
            
            simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+sce+'*')
            simul = simul_list[0]
                
            model_name = simul.split('\\')[-1]

            Smod_path = simul+'/_watershed/_simulated_results.csv'     
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            Smod['prop_ratio'] = Smod.intermit_areas / Smod.surflow_areas
            Smod['recharge'] = Smod['recharge'] * 1000 * 30
            Smod['outflow_drain'] = Smod['outflow_drain'] *1000 *30 #* (area * 1e6) #* 1000 * 30
            # Smod['groundwater_storage'] = (Smod['groundwater_storage']/(Smod['groundwater_storage'].mean()))
            Smod['groundwater_storage'] = Smod['groundwater_storage'] / (area * 1e6) 
            Smod = select_period(Smod, 1960, 2019)
            
            for xy in xy_list:
                
                # per = 1
                # x = Smod[xy[0]].diff(periods=per)
                # y = Smod[xy[1]].diff(periods=per)
                
                x = (Smod[xy[0]].diff())
                y = (Smod[xy[1]].diff())
                
                c = Smod.index.month
                wy = pd.Series(x.index.month).replace([10,11,12,1,2,3,4,5,6,7,8,9],
                                                        [1,2,3,4,5,6,7,8,9,10,11,12])
                xi = x.groupby([lambda x: x.month]).mean()
                yi = y.groupby([lambda y: y.month]).mean()
                cmapping = mpl.colors.ListedColormap(dict_c[watershed_name])
                cmapping = dict_cmap[watershed_name]
                
                cmap = plt.cm.YlGnBu
                # cmap = parula_map
                # cmaplist = [cmap(i) for i in range(cmap.N)]
                if watershed_name == 'Canut':
                    cmaplist = ['limegreen','greenyellow']
                if watershed_name == 'Nancon':
                    cmaplist = ['tomato', 'lightsalmon']
                # cmaplist[0] = (.5, .5, .5, 1.0)
                cmap = mpl.colors.LinearSegmentedColormap.from_list(
                    'Custom cmap', cmaplist, cmap.N)
                
                scat = ax.scatter(x, y, c=wy, cmap=cmap, marker="o", 
                                  s=15, vmin=1, vmax=12, alpha=0.75, ec='none', zorder=-1)
                xiline = xi.append(xi.iloc[[0]])
                xiline.index = np.arange(1,14,1)
                yiline = yi.append(yi.iloc[[0]])
                yiline.index = np.arange(1,14,1)
                ax.plot(xiline, yiline, linestyle = '-', lw=2, 
                        color=dict_c[watershed_name], zorder=0)
                wyi = np.arange(1,12+1,1)
                compt = 2
                for k in wyi:
                    ax.plot(xi[k], yi[k], marker="o", lw=2, markersize=8.5, 
                               markeredgecolor='k', 
                               markerfacecolor='white', markeredgewidth=1.2,
                               linestyle = 'None', zorder=compt)
                    ax.annotate(k,(xi[k],yi[k]), family='sans-serif', fontsize=5.5, 
                                 color=dict_c[watershed_name], weight="bold", ha='center', va='center',
                                 zorder=compt)
                    compt+=1
                xe = pd.DataFrame()
                xe['q25'] = (x.groupby(x.index.month).quantile(0.25))
                xe['q75'] = (x.groupby(x.index.month).quantile(0.75))        
                ye = pd.DataFrame()
                ye['q25'] = (y.groupby(y.index.month).quantile(0.25))
                ye['q75'] = (y.groupby(y.index.month).quantile(0.75))                
                # ax.errorbar(xi, yi,
                #               yerr=np.vstack([yi-ye.q25, ye.q75-yi]),
                #               xerr=np.vstack([xi-xe.q25, xe.q75-xi]),
                #               ecolor = 'black', fmt = 'none', capsize = 1, elinewidth=0.5, 
                #               capthick=0.5, zorder=1)               
                # ax.axvline(x.median(), c=dict_c[watershed_name], ls='--')
    
    base_name = figsim_folder+'06_hysteresis/'
    spec_name = watershed_name+'_hysteresis_dRvsAratio'
    # fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight')

#%% ---- ANNEXES


#%% ---- NOTES

# plt.plot(test.data_obs['hydrometry'][0])
# plt.plot(x['hydrometry'][0])
# plt.yscale('log')

# cmap = plt.cm.Oranges_r
# cmaplist = [cmap(i) for i in range(cmap.N)]
# cmaplist = ['darkred','orange']
# # cmaplist[-1] = (.5, .5, .5, 1.0) # first value
# cmap = mpl.colors.LinearSegmentedColormap.from_list(
#     'Custom cmap', cmaplist, cmap.N)
# minn = -1.01 # 0 
# maxn = 0 # 1.1
# intn = 0.1 # 0.1
# bounds = np.arange(minn, maxn, intn)
# norm = mpl.colors.BoundaryNorm(bounds, cmap.N)