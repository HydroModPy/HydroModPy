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

#%% CLASS FUNCTIONS

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

#%% PATH WATERSHED

git_path = "D:/Users/abherve/GITHUB/HydroModPy/CORE_COMM/"
# Path to the data folder
data_path = "C:/Users/ronan/OneDrive/_HydroDataPy/"
# Path where the results will be stored
out_path = "D:/Users/abherve/DYNAMIC/"

# git_path = "D:/abherve/GITHUB/HydroModPy/CORE_COMM/"
# # Path to the data folder
# data_path = "D:/abherve/HYDRODATAPY/"
# # Path where the results will be stored
# out_path = "D:/abherve/DYNAMIC/"
# out_path = "D:/abherve/INTERMITTENCY/"

dems_path = data_path + 'DEM/France/' # reginal DEM or conceptual DEM
shp_path = data_path + 'SHAPEFILE/' # if you want run a model from a shapefile
modflow_path = data_path + 'SOFTWARE/MODFLOW/' # add bin/ folder with necessary .exe

surfex_path =  data_path + 'CLIMATE/France/SURFEX/Brittany/'
# surfex_path =  data_path + 'CLIMATE/France/SURFEX/Rennes/' # add surfex models in .h5 format (France scale, else, specify None)
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

from_xy = []
# Depending on the choices
dem_path = dems_path + dem_name

library_path = git_path + 'watershed/' + 'watershed_library.csv' # each row is a study site with outlet coordinates
# watershed_names = ['Pompage'] # search the name in watershed_library or just label your result folder

watershed_names = ['Horn','Leff','Canut','Nancon','Arguenon','Flume','Gael']
code_names = ['J3014330','J1803010','J7513010','J0014010','J1105810','J7214010','J7313010']

#%% GENERATE WATERSHED

watershed_names = ['Canut']
code_names = ['J7513010']

coords_list = []
# watershed_names = []
points = gpd.read_file(os.path.join(out_path, '_data', 'clipped_hydrometric.shp'))
for m in code_names:
    for i, j in enumerate(points['CdStatio_1']):
        if j == m:
            coords_list.append([points.loc[i,'CoordXStat'],points.loc[i,'CoordYStat'],200,10])
            # watershed_names.append(j)

types_obs = ['complete','intermittent','perennial','river'] # list of shapefile name layers for clip hydrology
fields_obs = ['persistanc','fid','fid','fid'] # list of shapefile name columns to translate as a tif

types_obs = ['river'] # list of shapefile name layers for clip hydrology
fields_obs = ['fid']

# x = gpd.read_file("C:/Users/ronan/OneDrive/_HydroDataPy/HYDROLOGY/France/Hydrographic/D035/complete.shp")
# c = gpd.read_file(BV.geographic.watershed_shp)
# z = gpd.clip(x, c)
# w = 'D:/Users/abherve/INTERMITTENCY/Canut/results_stable/hydrology/test.shp'
# z.to_file(w)
# y = gpd.read_file(w)

load = False

# for watershed_name, from_xy in zip(watershed_names, coords_list):
for watershed_name, coord_list in zip(watershed_names[:], coords_list[:]):

    print('##### '+watershed_name.upper()+' #####')

    if watershed_name == 'Nancon':
        coord_list[1] = str(float(coord_list[1]) + 100)
    if watershed_name == 'Canut':
        coord_list[2] = str(50)

    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  modflow_path=modflow_path,
                                  library_path=library_path,
                                  load=load,
                                  from_shp=from_shp,
                                  from_dem=from_dem,
                                  from_xy=coord_list,
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
        # if piezometry_path == True:
        try:
            BV.add_piezometry()
        except:
            pass
        # if subbasin_path == True:
        BV.add_subbasin()

    watershed_display.watershed_dem(BV)
    watershed_display.watershed_local(dem_path, BV)

#%% ----

#%% OBSERVED HYSTERESIS

code_names = ['J3014330','J1803010','J7513010','J0014010','J1105810','J7214010','J7313010']
watershed_names = ['Horn','Leff','Canut','Nancon','Arguenon','Flume','Gael']

def select_period(df, first, last):
    df = df[(df.index.year>=first) & (df.index.year<=last)]
    return df

figobs_folder = out_path+'_figures/'
if not os.path.exists(figobs_folder):
    toolbox.create_folder(figobs_folder)

out_folder = out_path + '_data/'
obs_list = glob.glob(out_folder+'*')

temporal = True
space = -5
norm = False

var = 'EFF'
mod = 'REA'
sce = 'historic'

sce_list = ['historic']
sce_cmap = ['RdBu_r']
sce_color = ['k']
cmap_dict = dict(zip(sce_list, sce_cmap))
color_dict = dict(zip(sce_list, sce_color))

# fig1, ax1 = plt.subplots(1,1, figsize=(9,5))
# ax1b = ax1.twinx()

# fig2, ax2 = plt.subplots(1,1, figsize=(9,5))
# ax2b = ax2.twinx()

series_path = out_path + '_data/' +'export_hydro_series.csv'
series = pd.read_csv(series_path, sep=';', index_col = 4, parse_dates= True)
series = series.iloc[1:]
series.index.name = None
series.index = pd.to_datetime(series.index)
series['<ResObsElaborHydro>'] = pd.to_numeric(series['<ResObsElaborHydro>'])

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
    
    serie = series[series['<CdStationHydro>']==code_name+'01']
    Qobs = serie['<ResObsElaborHydro>'] / 1000 # L/s to m3/s
    # serie = serie.resample('M').sum()
    # Qobs = serie.copy()
    
    # Qobs = pd.read_csv(Qobs_path, sep=';', index_col=0, parse_dates=True)
    # area = float(Qobs_path.split('_')[-3])
    Qobs = Qobs.squeeze()
    Qobs = Qobs.rename('Q')
    # Qobs = Qobs.resample('M').sum()
    Qobs.to_csv(stable_folder+'hydrometry/'+naming,
                sep=';')
    
    Qobs = (Qobs / (area*1000000)) * (3600 * 24) * 1000 # m3/s to mm/j

    Qobs = select_period(Qobs, 1990, 2019) # Qobs.first_valid_index().year
    # ax1.plot(Qobs, label=watershed_name)
    # ax1.set_yscale('log')
    # ax1.legend()
    
    Clim_path = stable_folder+'climatic/'+'_ALL_D.csv'
    Clim = pd.read_csv(Clim_path, sep=';', index_col=0, parse_dates=True)
    Clim = select_period(Clim, 1990, 2019)
    # Clim = Clim.resample('M').sum()

    # ax2.plot(Clim['REC_REA_historic'], ls='-', label=watershed_name)
    # ax2.set_yscale('log')
    # ax1.legend()

    Cobs = Clim['EFF_REA_historic']

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
    DFobs = DFobs.resample('M').apply(very_resamp)[mask]
                
    hyst = Hysteresis(DFobs, watershed_name)
    hyst.prepare_xy_raw()
    hyst.compute_xy_metrics(temporal=temporal, space=space, norm=norm)
    
    columns_x = hyst.xrecapl.columns
    columns_y = hyst.yrecapl.columns
    
    n = len(columns_x)
    cmap = cmap_dict[sce]
    cmap_color = plt.get_cmap(cmap)(np.linspace(0, 1, n))
    color = color_dict[sce]
    
    dfevol = hyst.dfmet.iloc[:-1]
    dfevol = dfevol.set_index(pd.to_datetime(dfevol.index, format='%Y'))
    # dfmean = hyst.dfmet.iloc[-1]
    # transp = pd.DataFrame(dfmean).transpose()
    
    # all_polygs_col = polygs_col.append(dfmean.index)
    # all_points_col = points_col.append(dfmean.index)
    
    # polygs = polygs.reindex(columns = all_polygs_col)
    # polygs.loc[polygs['watershed_']==watershed_name,dfmean.index] = transp.values
    # points = points.reindex(columns = all_points_col)
    # points.loc[polygs['watershed_']==watershed_name,dfmean.index] = transp.values
    
    ######################### AX 1 AX 2 #########################

    fig1, axs1 = plt.subplots(1,3, figsize=(10,4))
    fig1.add_subplot(111, frameon=False)
    plt.tick_params(labelcolor='none', top=False, bottom=False, left=False, right=False)
    axs1 = axs1.ravel()
    x_label = var + ' [mm]'
    y_label='Q [mm]'
    x_lim=[-150,150]
    y_lim=[0,150]

    for i, log in enumerate(['linear', 'log']):

         ax = axs1[i]
         scat = ax.scatter(hyst.x, hyst.y, c=hyst.wy, cmap='hsv_r', marker="o", 
                           s=10, vmin=1, vmax=12, alpha=0.75, ec='none', zorder=-2)
         ax.plot(hyst.xi, hyst.yi, marker="o", markersize=9, markeredgecolor='black', 
                 markerfacecolor='white', linestyle = 'None') 
         for k in hyst.wyi:
             ax.annotate(k,(hyst.xi[k],hyst.yi[k]), family='sans-serif', fontsize=5, 
                         color='black', weight="bold", ha='center', va='center')
         if log != 'log':
             maxi = max(max(x_lim),max(y_lim))
             mini = min(min(x_lim),min(y_lim))
             ax.plot((mini,maxi), (mini,maxi), 
                         linestyle='-', color='grey', linewidth=1.5, zorder=-1)
         else:
             # ax.plot(np.linspace(*ax.get_xlim()), np.linspace(*ax.get_xlim()), 
             #         linestyle='-', color='grey', linewidth=1.5, zorder=0)
             ax.plot(np.linspace(0.1,max(x_lim),50), np.linspace(0.1,max(x_lim),50), 
                     linestyle='-', color='grey', linewidth=1.5, zorder=-1)
         ax.errorbar(hyst.xi, hyst.yi,
                     yerr=np.vstack([hyst.yi-hyst.ye.q25, hyst.ye.q75-hyst.yi]),
                     xerr=np.vstack([hyst.xi-hyst.xe.q25, hyst.xe.q75-hyst.xi]),
                     ecolor = 'black', fmt = 'none', capsize = 1, elinewidth=0.5, 
                     capthick=0.5, zorder=1)
         ax.plot(hyst.xiline, hyst.yiline, linestyle = '-', lw=1.5, color='k', zorder=-1)
         
         if i == 0:
             ax.set_ylabel(y_label)
             ax.set_title(hyst.name)
         else:
             ax.set_title(str(hyst.first)+'-'+str(hyst.last))
             ax.set_xlabel(x_label)
         ax.set_xlim(x_lim[0], x_lim[1])
         ax.set_ylim(y_lim[0]+0.1, y_lim[1])
         ax.set_xticks(np.linspace(x_lim[0], x_lim[1], 5))
         ax.set_yticks(np.linspace(y_lim[0]+0.1, y_lim[1], 5))
         
         ax.set_yscale(log)
         
    plt.tight_layout()
    
    # position = fig1.add_axes([0.95,0.32,0.02,0.5])
    # cb = plt.colorbar(scat,cax=position)
    # x1 = [1,2,3,4,5,6,7,8,9,10,11,12]
    # squad = ['Oct','Nov','Dec','Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep']
    # cb.set_ticks(x1)
    # cb.set_ticklabels(squad)
    # cb.ax.tick_params(labelsize=10)
    # cb.update_ticks()
     
    ######################### AX 3 #########################
     
    ax = axs1[2]
    for i, (colx, coly) in enumerate(zip(columns_x, columns_y)):
        # print(colx)
        data = pd.DataFrame()
        data['inx'] = hyst.xrecapl[colx]
        data['iny'] = hyst.yrecapl[coly]
        ax.plot(data.inx, data.iny, linestyle = '-', lw=1, color=cmap_color[i],
                alpha=0.75, zorder=0)
    ax.plot(data.inx, data.iny, linestyle = '-', lw=2, color=color, zorder=2)
    maxi = max(max(ax.get_xlim()),max(ax.get_ylim()))
    mini = min(min(ax.get_xlim()),min(ax.get_ylim()))
    ax.plot(np.linspace(mini,maxi,50), np.linspace(mini,maxi,50), 
            linestyle='-', color='grey', linewidth=1.5, zorder=0)
    ax.set_yscale('log')
    if temporal==True:
        ax.set_title(str(abs(space))+' - years moving')
    # ax.set_xlabel(x_label)
    
    ax.set_xlim(x_lim[0], x_lim[1])
    ax.set_ylim(y_lim[0]+0.1, y_lim[1])
    ax.set_xticks(np.linspace(x_lim[0], x_lim[1], 5))
    # ax.set_yticks(np.linspace(y_lim[0]+0.1, y_lim[1], 5))
    
    path_fig = os.path.join(out_path, '_figures')
    fig1.savefig(path_fig+'/'+watershed_name+'_hysteresis'+'.png', dpi=300, bbox_inches='tight')
    
    # fig1.savefig(figobs_folder+'loop_'+watershed_name+'.png', dpi=300, bbox_inches='tight')
    
    # plt.close()
    
# polygs.to_file(os.path.join(analysis_folder, 'polygs_metrics.shp'))
# points.to_file(os.path.join(analysis_folder, 'points_metrics.shp'))

#%% OBSERVED DISCHARGE

watershed_names = ['Horn','Leff','Canut','Nancon','Arguenon','Flume','Gael']
code_names = ['J3014330','J1803010','J7513010','J0014010','J1105810','J7214010','J7313010']

first = 2008
last = 2021
one = 2021

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
    
    # serie = series[series['<CdStationHydro>']==code_name+'01']
    # Qobs = serie['<ResObsElaborHydro>'] / 1000 # L/s to m3/s
    # serie = serie.resample('M').sum()
    # Qobs = serie.copy()
    
    Qobs = pd.read_csv(Qobs_path, sep=';', index_col=0, parse_dates=True)
    # area = float(Qobs_path.split('_')[-3])
    Qobs = Qobs.squeeze()
    Qobs = Qobs.rename('Q')
    # Qobs = Qobs.resample('M').sum()
    # Qobs.to_csv(stable_folder+'hydrometry/'+naming,
    #             sep=';')
    
    Qobs = (Qobs / (area*1000000)) * (3600 * 24) * 1000 # m3/s to mm/j
    
    Qobs = select_period(Qobs, first, last)
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
    fig, ax = plt.subplots(figsize=(5,4))
    # ax.plot(mean_interan_days.counts, mean_interan_days[station+'_mmm'],
    #         lw=1, color='red', label='Mean')
    ax.plot(mean_interan_days.counts, mean_interan_days.q50,
            lw=2, color='darkred', label='Median')
    yerrmax = mean_interan_days.q90
    yerrmin = mean_interan_days.q10
    ax.fill_between(mean_interan_days.counts, yerrmin, yerrmax,
                      color='cyan',edgecolor='grey',
                      alpha = 0.5, label='10-90th')
    plt.yscale('log')
    # ax.yaxis.set_major_formatter(ScalarFormatter())
    ax.set_xlim(0,366)
    ax.set_ylim(0.01,50)
    ax.tick_params(axis='both', which='major', pad=10)
    x1 = np.linspace(0,366,13)
    squad = ['J','F','M','A','M','J','J','A','S','O','N','D','J']
    ax.set_xticks(x1)
    ax.set_xticklabels(squad, minor=False, rotation='horizontal')
    ax.set_xlabel('Months', labelpad=+10)
    ax.set_ylabel('Q / A [mm/j]',labelpad=+10)
    ax.set_title(watershed_name + ' - [' + str(first) + '-' + str(last) + ']')
    ax.grid(color='grey', lw=0.5, zorder=0)
    dates = np.array([one],dtype=np.int64)
    colors = ['blue']
    for z in np.array(range(len(dates))):
        onlyone = data_index[(data_index.index.year==dates[z])].to_frame()
        onlyone = onlyone.groupby([onlyone.index.month,
                                   onlyone.index.day], as_index=True).mean()
        onlyone['counts'] = np.array(range(1,len(onlyone)+1))
        ax.plot(onlyone.counts, onlyone['Q'],
                color=colors[z], lw=1, label = str(dates[z]))
    ax.legend(loc='upper left')
    plt.tight_layout()
    # fig.savefig(path + 'plot_figures/' + site + '/' + 'regime' + '.png', dpi=300, bbox_inches='tight')
    
    # fig.savefig(path_fig+'/'+watershed_name+'_intermensual_'+name_file+'.png', dpi=300, bbox_inches='tight')
    fig.savefig(out_path+'/_figures/'+watershed_name+'_intermensual'+'.png', dpi=300, bbox_inches='tight')

#%% OBSERVED HYDROGRAPHIC

hydrology_path = data_path + 'HYDROLOGY/France/Hydrographic/D035/' # add hydrographic shapefiles

# types_obs = ['complete','intermittent','perennial','river','drain_complete_chezecanut'] # list of shapefile name layers for clip hydrology
# fields_obs = ['persistanc','fid','fid','fid','fid'] # list of shapefile name columns to translate as a tif

watershed_names = ['Canut','Nancon']
code_names = ['J7513010','J0014010']

types_obs = ['complete','intermittent','perennial','river','zh_couesnon','zh_meuchezecanut'] # list of shapefile name layers for clip hydrology
fields_obs = ['persistanc','fid','fid','fid','fid','fid']

# types_obs = ['zh_couesnon'] # list of shapefile name layers for clip hydrology
# fields_obs = ['fid']

df = pd.DataFrame(np.nan, index=range(1), columns=types_obs)

from watershed import watershed_root, watershed_display, forcing
from matplotlib_scalebar.scalebar import ScaleBar
from rasterio.plot import show

for watershed_name, code_name in zip(watershed_names[:], code_names[:]) :
       
    print('##### '+watershed_name.upper()+' #####')
    
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)
    
    bv = gpd.read_file(BV.geographic.watershed_shp)
    area = BV.geographic.area
    area = round(area, 1)
    
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    
    # BV.add_hydrometry(hydrometry_path)
    # BV.add_intermittency(intermittency_path) 
    # BV.add_hydrology(hydrology_path, types_obs=types_obs, fields_obs=fields_obs)
    
    path_hydro = stable_folder + 'hydrology/'
    complete = gpd.read_file(path_hydro+'complete.shp')
    intermittent = gpd.read_file(path_hydro+'intermittent.shp')
    perennial = gpd.read_file(path_hydro+'perennial.shp')
    river = gpd.read_file(path_hydro+'river.shp')
    
    if watershed_name == 'Canut':
        zh = gpd.read_file(path_hydro+'zh_meuchezecanut.shp')
        zh_tif = imageio.imread(path_hydro+'zh_meuchezecanut.tif')
    if watershed_name == 'Nancon':
        zh = gpd.read_file(path_hydro+'zh_couesnon.shp')
        zh_tif = imageio.imread(path_hydro+'zh_couesnon.tif')
        
    perennial_tif = imageio.imread(path_hydro+'perennial.tif')
    intermittent_tif = imageio.imread(path_hydro+'intermittent.tif')
    river_tif = imageio.imread(path_hydro+'river.tif')
    complete_tif = imageio.imread(path_hydro+'complete.tif')
    
    area_complete = round((np.sum(complete_tif > 0) * 75**2) / 1000000 / area *100, 1)
    area_zh = round((np.sum(zh_tif > 0) * 75**2) / 1000000 / area *100, 1)
    area_intermittent = round((np.sum(intermittent_tif > 0) * 75**2) / 1000000 / area*100, 1)
    area_perennial = round((np.sum(perennial_tif > 0) * 75**2) / 1000000 / area*100, 1)
    area_river = round((np.sum(river_tif > 0) * 75**2) / 1000000 / area *100, 1)
    area_all = round(area_complete + area_zh, 1)
    drainage = round(area_all / area, 2)
    
    fig, ax = plt.subplots(1,1, figsize=(5,5))

    polyg = gpd.read_file(BV.geographic.watershed_shp)
    contour = gpd.read_file(BV.geographic.watershed_contour_shp)
    dem = rasterio.open(BV.geographic.watershed_box_buff_dem)

    bounds = dem.bounds
    xlim = ([bounds[0], bounds[2]])
    ylim = ([bounds[1], bounds[3]])
    ax.set_xlim(xlim)
    ax.set_ylim(ylim)
    scalebar = ScaleBar(1,box_alpha=0, scale_loc = 'bottom', location='upper left')
    ax.add_artist(scalebar)
    ax.get_xaxis().set_visible(False)
    ax.get_yaxis().set_visible(False)
    ax.set_title(watershed_name, fontproperties=fontprop)
    ax.set(aspect='equal')
    
    cmap = 'gist_earth' # 'Greys'
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
          cmap=cmap, alpha=0.55, zorder=2, aspect="auto")
    
    zh.plot(ax=ax, lw=0, color='darkmagenta', alpha=1, zorder=4, legend=True, label='Wetlands')

    streams = complete.copy()
    streams[streams.persistanc=='Permanent'].plot(ax=ax, lw=2, color='navy',
                                                  zorder=6,legend=True, label='Streams')
    streams[streams.persistanc=='Intermittent'].plot(ax=ax, lw=2, color='dodgerblue', ls='-',
                                                  zorder=5,legend=True, label='Streams')
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
    
    ax.text(0.015, 0.14, 
            'BV = ' +str(area) + ' [km²]' + '\n'
            'All = '+str(area_all) + ' [%]' + '\n'
            'Wetlands = '+str(area_zh) + ' [%]' + '\n'
            'Network = '+str(area_complete) + ' [%]' + '\n'
            'Standard = '+str(area_river) + ' [%]' + '\n'
            'Intermit. = '+str(area_intermittent) + ' [%]' + '\n'
            'Perenn. = '+str(area_perennial) + ' [%]',
            horizontalalignment='left',
            verticalalignment='center', 
            transform=ax.transAxes,
            fontsize = 6, zorder=10)
    
    fig.tight_layout()
    
    fig.savefig(out_path+'/_figures/'+watershed_name+'_hydromapping'+'.png', dpi=300, bbox_inches='tight')

#%% ----

#%% DICHOTOMY STREAMS

hydrology_path = data_path + 'HYDROLOGY/France/Hydrographic/' # add hydrographic shapefiles

from calibration import calib_root, calib_dichotomy, calib_analysis, calib_exploration, calib_basis

# types_obs = ['complete','intermittent','perennial','river','drain_complete_chezecanut'] # list of shapefile name layers for clip hydrology
# fields_obs = ['persistanc','fid','fid','fid','fid'] # list of shapefile name columns to translate as a tif

types_obs = ['streams_bzh'] # list of shapefile name layers for clip hydrology
fields_obs = ['fid']

df = pd.DataFrame(np.nan, index=range(1), columns=types_obs)

for watershed_name, code_name in zip(watershed_names[-1:], code_names[-1:]) :
    
    for type_obs, field_obs in zip(types_obs, fields_obs):
   
        print('##### '+watershed_name.upper()+' #####')
        
        BV = watershed_root.Watershed(watershed_name=watershed_name,
                                      dem_path=dem_path, 
                                      out_path=out_path,
                                      load=True,
                                      modflow_path=modflow_path)
        area = BV.geographic.area
        
        stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
            
        BV.add_hydrology(hydrology_path, types_obs=[type_obs], fields_obs=[field_obs])
        
        BV.forcing.update_recharge_surfex(clim_mod = 'REA', clim_sce='historic',
                                          first_year = 2001, last_year=2019, time_step = 'D',
                                          sim_state='steady') #
        
        BV.hydrodynamic.update_thickness(30)
        # BV.hydrodynamic.update_porosity(0.1)
        # BV.hydrodynamic.update_hyd_cond(2)
        
        params_df = pd.DataFrame(columns=['params',
                                          'init_values','lower_bounds','higher_bounds',
                                          'units','scale'])
        params_df.loc[0] = ['k1',8.64e-01,8.64e-03,8.64e+01,'m/j','lin']
        
        params_file = 'calib_dicot_hom_1v_k1'
        
        params_df.to_csv(BV.calibration_folder+'/'+params_file+'.csv', sep=';', index=None)

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
        
        df.loc[0,watershed_name] = koptim / 24 / 3600
        df.loc[1,watershed_name] = kr
        df.loc[2,watershed_name] = obj_func
        
# df.to_csv(out_path+'/Koptims_dichotomy_streams.csv', sep=';')
# df = pd.read_csv(BV.calibration_folder+'/Koptims_dichotomy_streams.csv', sep=';')

#%% EXPLORATION RECHARGE

code_names = ['J7513010','J0014010']
watershed_names = ['Canut','Nancon']

# watershed_names = ['Monfort']

modflow_path = data_path + 'SOFTWARE/MODFLOW/'

from watershed import watershed_root, watershed_display, forcing
from calibration import calib_root, calib_dichotomy, calib_analysis, calib_exploration, calib_basis, calib_params

for watershed_name in watershed_names[:] :
    
    print('##### '+watershed_name.upper()+' #####')
    
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)

    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots

    fcalib = 1985
    lcalib = 2011
    
    sim_state = 'transient'
    time_step = 'M'
    
    var = 'REC'
    wr = True
    wish = 0
    mod = 'REA'
    
    raw_path = stable_folder+'/'+'hydrometry/'
    Qobs_path = fnmatch.filter(os.listdir(raw_path), 'Hydrometric_*')[0]
    Qobs = pd.read_csv(raw_path+Qobs_path, sep=';', index_col=0, parse_dates=True)
    area = float(Qobs_path.split('_')[-3])
    Qobs = (Qobs / (area*1000000)) * (3600 * 24) # m3/s to m/day
    Qobs = Qobs.squeeze()
    Qobs = Qobs.resample('M').mean()
    # plt.plot(Qobs)
    # plt.yscale('log')
    
    fqobs = Qobs.first_valid_index().year+1
    lqobs = Qobs.last_valid_index().year-1
    fhist = 1985
    lhist = 2011
    year_min = max(fqobs, fhist)
    year_max = min(lqobs, lhist)
    
    # Normalize with discharge
    BV.forcing.update_recharge_surfex(clim_mod = mod, clim_sce = 'historic',
                                             first_year = year_min, last_year = year_max,
                                             time_step = time_step, sim_state=sim_state)
    Rech = BV.forcing.recharge
    BV.forcing.update_runoff_surfex(clim_mod = mod, clim_sce='historic',
                                          first_year = year_min, last_year=year_max, time_step = 'M',
                                          sim_state='transient')
    Runof = BV.forcing.runoff # m/month
    
    norm_Rea = select_period(Rech, year_min, year_max)
    norm_Qobs = select_period(Qobs, year_min, year_max)
    
    Rt_Rea_Qobs = (norm_Qobs.mean() / norm_Rea.mean())
    # print(Rt_Rea_Qobs.round(2))
    Nt = (norm_Rea * Rt_Rea_Qobs)
    
    BV.forcing.update_recharge(Nt, sim_state=sim_state)
    plt.plot(BV.forcing.recharge, c='r')
    
    BV.forcing.update_recharge(select_period(BV.forcing.recharge, fcalib, lcalib), sim_state=sim_state)
    BV.forcing.update_runoff(select_period(BV.forcing.runoff, fcalib, lcalib), sim_state=sim_state)
    
    BV.hydrodynamic.update_thickness(30)
    # BV.hydrodynamic.update_porosity(0.001)
    # BV.hydrodynamic.update_hyd_cond(0.08640) # 1e-6 m/s
    
    params_df = pd.DataFrame(columns=['params',
                                      'init_values','lower_bounds','higher_bounds',
                                      'units','scale'])
    if watershed_name == 'Canut':
        params_df.loc[0] = ['k1',4.3e+00,4.3e-01,4.3e+01,'m/j','lin']
        params_df.loc[1] = ['n1',0.01,0.001,0.02,'m/j','lin']
    if watershed_name == 'Nancon':
        params_df.loc[0] = ['k1',4.3e+00,4.3e-01,4.3e+01,'m/j','lin']
        params_df.loc[1] = ['n1',0.01,0.02,0.07,'m/j','lin']
    if watershed_name == 'Monfort':
        params_df.loc[0] = ['k1',1.7e+00,1.7e-01,1.7e+01,'m/j','lin']
        params_df.loc[1] = ['n1',0.01,0.001,0.10,'m/j','lin']
        
    params_file = 'calib_explo_hom_2v_k1-n1'
    
    params_df.to_csv(BV.calibration_folder+'/'+params_file+'.csv', sep=';', index=None)
    
    # params_file = 'calib_explo_hom_1v_n1'
    # params_file = 'calib_explo_hom_1v_k1'
    # params_file = 'calib_dicot_het_2v_k1-k2'•

# EXPLORATION LAUNCH

    # calib = calib_root.Calibration(params_file, BV, observations = ['hydrometry'])
    # calib.exploration(resolution=100)

#%% EXPLORATION PLOT

# watershed_names = ['Canut']
# watershed_names = ['Nancon']

code_names = ['J7513010','J0014010']
watershed_names = ['Canut','Nancon']

# code_names = ['J3014330','J1803010','J1105810','J7214010','J7313010']
# watershed_names = ['Horn','Leff','Arguenon','Flume','Gael']

# watershed_names = ['Horn','Leff','Canut','Nancon','Arguenon','Flume','Gael']
# code_names = ['J3014330','J1803010','J7513010','J0014010','J1105810','J7214010','J7313010']

params_file = 'calib_explo_hom_2v_k1-n1'

wish = 0

for watershed_name in watershed_names[:]:
    
    # if (watershed_name == 'Canut') | (watershed_name == 'Nancon'):
    #     wish = -1
    # else:
    #     wish = 0
    
    print('##### '+watershed_name.upper()+' #####')
    
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True)

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
    
    sim_res=test.sim_results
    # x= pd.to_numeric(test.sim_results[test.params_synt[0]]['seepage_areas'])
    # plt.plot(x)
    
    # path_fig = os.path.join(BV.calibration_folder, params_file, typ_calib, '_figures')
    path_fig = os.path.join(out_path, '_figures')
    
    # CHRONICS
    
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
        # sat = test.sim_results[synt[t]]['seepage_areas']
        sat = test.sim_results[synt[t]]['surflow_areas']
        sat = pd.to_numeric(sat, errors='coerce').isnull()
        rsat.append(sat.mean())
    
    # fig, ax = plt.subplots(1,1, figsize=(6,5))
    # axb = ax.twinx()
    # x = range(len(p1))
    # ax.plot(x, [float(i) for i in p1], marker='.', lw=0, c='blue', label='K [m/j]')
    # ax.plot(x, [float(i) for i in p2], marker='.', lw=0, c= 'green', label='Sy [-]')
    # axb.plot(x, rsat, marker='.', lw=0, c= 'red', label='Saturation [%]')
    # axb.plot(x, rout, marker='.', lw=0, c= 'darkorange', label='Outflow [mm/mois]')
    # ax.set_xlabel('Simulations')
    # ax.set_ylabel('K and Sy')
    # axb.set_ylabel('Saturation and Outflow', rotation=270, labelpad=25)
    # ax.legend(loc = 'upper left')
    # axb.legend(loc='upper center')
    # ax.grid('grey')
    # ax.axhline(y=6.6E-7*24*3600, c = 'b', lw=2)
    # # ax.axhline(y=0.1, c = 'g', lw=2)
    # # plt.scatter(rout, rsat)
            
    nse_good = []
    sat_good = []
    
    fig, axs = plt.subplots(2,2, figsize=(9,5))
    axs = axs.ravel()
    fig.suptitle(watershed_name.upper())
    
    numb = 0
    for i in range(len(obs[typ_name])):
        o = obs[typ_name][i] * 1000 * 30 # m/j to mm/month
        s = sim[typ_name][i] * 1000 * 30 # m/j to mm/month
        nd = ind[typ_name][i]
        sat = test.sim_results[synt[i]]['seepage_areas']
        sat = pd.to_numeric(sat)
        
        k = '{:.1e}'.format(float(synt[i].split(';')[0])/24/3600)
        sy = float(synt[i].split(';')[1]) * 100
        title = 'Discharge [mm/month]'
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

        cmap = mpl.cm.get_cmap('viridis_r')

        color_gradients = cmap(c)
        # vmin = min(c)
        # vmax = max(c)
        # norm = mpl.colors.Normalize(vmin=vmin, vmax=vmax)
        
        def fmt_xaxes(ax):
            yearsmaj = mdates.YearLocator(5)   # every year
            yearsmin = mdates.YearLocator(1)
            # monthsmaj = mdates.MonthLocator(6)  # every month
            # monthsmin = mdates.MonthLocator(3)
            # months_fmt = mdates.DateFormatter('%m') #b = name of month ?
            years_fmt = mdates.DateFormatter('%Y')
            ax.xaxis.set_major_locator(yearsmaj)
            ax.xaxis.set_minor_locator(yearsmin)
            ax.xaxis.set_major_formatter(years_fmt)
        
        if nselog > 60:
            if all(i <= 50 for i in sat):       
                
                ax = axs[0]
                fmt_xaxes(axs[0])
                # ax.xaxis.set_major_locator(yearsmaj)
                # ax.xaxis.set_minor_locator(yearsmin)
                # ax.xaxis.set_major_formatter(years_fmt)
                
                ax.plot(s, color=color_gradients[i], lw=1, label=label)
                # ax.plot(s, lw=1, label=label)   
                ax.set_title(title)
                ax.plot(o, color='grey', lw=3, ls='-', zorder=0)
                ax.set_xlim(pd.to_datetime('1989'), pd.to_datetime('2021'))
                
                del(ax)
                
                ax = axs[1]
                fmt_xaxes(axs[1])
                ax.set_title('Log discharge [mm/month]')
                ax.plot(select_period(o.copy(),2010,2019), color='grey', lw=3, ls='-', zorder=0)
                ax.set_yscale('log')
                ax.plot(select_period(s.copy(),2010,2019), color=color_gradients[i], lw=1, label=label)
                # ax.xaxis.set_major_locator(yearsmaj)
                # ax.xaxis.set_minor_locator(yearsmin)
                # ax.xaxis.set_major_formatter(years_fmt)

                ax = axs[2]
                fmt_xaxes(axs[2])   
                sat_good.append(str(k)+'_'+str(sy)+'_'+str(round(sat.mean(),2)))
                ax.plot(select_period(sat.copy(),2010,2019), color=color_gradients[i], lw=1, label=label)
                # ax.plot(sat, lw=1, label=label) 
                ax.set_ylim(-2,50)
                title = 'Saturation [%]'
                ax.set_title(title)
                # ax.set_xlim(pd.to_datetime('2000'), pd.to_datetime('2005'))
                            
    plt.tight_layout()
    
    if watershed_name == 'Nancon':
        ncol = 2
    else:
        ncol = 1
    ax.legend(bbox_to_anchor=(1.2,0.5), prop={'size': 5}, loc="center left", borderaxespad=0, 
              ncol=ncol)
    ax = axs[3]
    # ax.set_title('$NSE_{log}$ > 50 & $SAT_{max}$ < 50')
    plt.axis('off')

    # plt.tight_layout()

    fig.savefig(path_fig+'/'+watershed_name+'_chronics_'+name_file+'.png', dpi=300, bbox_inches='tight')

    # ax.plot(BV.forcing.recharge, color='grey', lw= 5)
           
    # divider = make_axes_locatable(ax)
    # cax = divider.append_axes('right', size='1.25%', pad=0.1)
    # fig.add_axes(cax)
    # norm = Normalize(vmin=vmin, vmax=vmax)
    # n_cmap = cm.ScalarMappable(norm=norm, cmap=cmap)
    # n_cmap.set_array([])
    # ax.get_figure().colorbar(n_cmap, cax=cax, orientation="vertical")
    
    # SAT

    fig, axs = plt.subplots(1,3, figsize=(10,3.5))
    fig.suptitle(watershed_name.upper())
    axs = axs.ravel()
    for k in range(3):
        ax = axs[k]
        ax.axes.tick_params(which='both', direction='out', zorder=10)
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
                if k == 0:
                    try:
                        ax.set_title('SAT MIN [%]')
                        # sim_sat[j][i] = pd.to_numeric(sim_res[string]['seepage_areas']).min()
                        sim_sat[j][i] = pd.to_numeric(sim_res[string]['surflow_areas']).min()
                    except:
                        pass
                if k == 1:
                    try:
                        ax.set_title('SAT MEAN [%]')
                        # sim_sat[j][i] = pd.to_numeric(sim_res[string]['seepage_areas']).mean()
                        sim_sat[j][i] = pd.to_numeric(sim_res[string]['surflow_areas']).mean()
                    except:
                        pass
                if k == 2:
                    try:
                        ax.set_title('SAT MAX [%]')
                        # sim_sat[j][i] = pd.to_numeric(sim_res[string]['seepage_areas']).max()
                        sim_sat[j][i] = pd.to_numeric(sim_res[string]['surflow_areas']).max()
                    except:
                        pass
                compt += 1
        Z=sim_sat
        pc = ax.contourf(X,Y,Z,cmap='jet', levels=np.arange(0,51,5)) #figadd.cmap_white_jet()
        ax.set_xscale('log')
        # cb = fig.colorbar(pc)
        ax.set_ylabel('Sy [-]')
        ax.set_xlabel('K [m/j]')
        # cb.set_label('Saturation [%]', rotation=270, labelpad=40)
    position=fig.add_axes([1.05,0.2,0.02,0.7])  ## the parameters are the specified position you set 
    fig.colorbar(pc,cax=position)
    plt.tight_layout()
    fig.savefig(path_fig+'/'+watershed_name+'_saturation_'+name_file+'.png', dpi=300, bbox_inches='tight')

    # DISCHARGE
    
    fig, axs = plt.subplots(1,3, figsize=(15,4))
    fig.suptitle(watershed_name.upper())
    axs = axs.ravel()
    
    ax = axs[0]
    
    X,Y = np.meshgrid(test.params_values[0], test.params_values[1])
    Z=test.obj_function.copy()
    # Z[Z<0] = 0
    from numpy import inf
    # Z[Z == inf] = 0
    pc = ax.imshow(Z, vmin = 0, vmax=1, aspect='auto') #figadd.cmap_white_jet() , shading='gouraud'
    # ax.set_xscale('log')
    ax.set_ylabel('Sy [-]')
    ax.set_xlabel('K [m/j]')
    divider = make_axes_locatable(ax)
    cax = divider.append_axes('right', size='5%', pad=0.05)
    # cb = fig.colorbar(pc)
    cb=fig.colorbar(pc, cax=cax, orientation='vertical')
    cb.set_label('$NSE_{log}$', rotation=270, labelpad=40)
    # cb.set_label('$NSE_{log}$', rotation=270, labelpad=40)
    # fig.savefig(path_fig+'/'+'_shaded_'+name_file+'.png', dpi=300, bbox_inches='tight')

    ax = axs[1]
    
    ax.axes.tick_params(which='both', direction='out', zorder=10)
    X,Y = np.meshgrid(test.params_values[0], test.params_values[1])
    Z=test.obj_function.copy()
    # Z[Z == inf] = np.nan
    # Z = np.ma.array(Z,mask=np.isnan(Z))
    # Z = np.ma.masked_invalid(Z)
    # Z = Z.replace(np.inf, np.nan)
    pc = ax.pcolormesh(X,Y,Z, cmap='jet', shading='gouraud', vmin=0, vmax=1) #figadd.cmap_white_jet()
    ax.set_xscale('log')
    ax.set_ylabel('Sy [-]')
    ax.set_xlabel('K [m/j]')
    divider = make_axes_locatable(ax)
    cax = divider.append_axes('right', size='5%', pad=0.05)
    # cb = fig.colorbar(pc)
    cb = fig.colorbar(pc, cax=cax, orientation='vertical')
    cb.set_ticks(np.arange(0,1.1,0.1)) 
    # cb.set_ticklabels(np.arange(0,1.1,0.1))
    cb.set_label('$NSE_{log}$', rotation=270, labelpad=40)
    # fig.savefig(path_fig+'/'+'_mesh_'+name_file+'.png', dpi=300, bbox_inches='tight')

    ax = axs[2]
    ax.axes.tick_params(which='both', direction='out', zorder=10)
    X,Y = np.meshgrid(test.params_values[0], test.params_values[1])
    Z=test.obj_function.copy()
    Z[Z<0] = 0
    from numpy import inf
    Z[Z == inf] = 0
    # np.ma.masked_where(test.obj_function<0, test.obj_function)
    # plt.pcolor(X,Y,Z,cmap='jet')#figadd.cmap_white_jet()
    bounds = np.arange(0,1.1,0.1)
    norm = mpl.colors.Normalize(vmin=-1, vmax=1.0)
    # norm = mpl.colors.BoundaryNorm(boundaries=bounds, ncolors=256)
    # pc = ax.contourf(X, Y, Z, vmin=0, vmax=1, norm = norm)
    pc = ax.contourf(X, Y, Z, levels=np.arange(0,1.1,0.1))    
    # plt.imshow(Z)
    # plt.xlim(1)
    divider = make_axes_locatable(ax)
    cax = divider.append_axes('right', size='5%', pad=0.05)
    # cb = fig.colorbar(pc)
    cb = fig.colorbar(pc, cax=cax, orientation='vertical')
    cb.set_ticks(np.arange(0,1.1,0.1)) 
    # cb.set_ticklabels(np.arange(0,1.1,0.1))
    cb.set_label('$NSE_{log}$', rotation=270, labelpad=40)
    ax.set_xscale('log')
    ax.set_ylabel('Sy [-]')
    ax.set_xlabel('K [m/j]')
    
    plt.tight_layout()
    
    fig.savefig(path_fig+'/'+watershed_name+'_discharge_'+name_file+'.png', dpi=300, bbox_inches='tight')

#%% ----

#%% PARAM RUN MODEL

watershed_names = ['Canut','Nancon']
code_names = ['J7513010','J0014010']
types_obs = ['complete'] # list of shapefile name layers for clip hydrology

watershed_names = ['Canut']
code_names = ['J7513010']

# watershed_names = ['Nancon']
# code_names = ['J0014010']

for watershed_name, code_name in zip(watershed_names[:], code_names[:]) :
    print('##### '+watershed_name.upper()+' #####')
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' 
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)
    
    # BV.add_hydrometry(hydrometry_path)
    # BV.add_intermittency(intermittency_path) 
    # BV.add_hydrology(hydrology_path, types_obs=types_obs, fields_obs=fields_obs)
    BV.add_subbasin()
    
    # Input recharge
    bzh_rech = False
    var = 'REC'
    mod = 'REA'
    # mod = 'NOR1'
    sce = 'historic'
    # sce = 'historic'
    typ = 'calib1' # sinu / hist / proj
    wr = True
    
    # Choice temporal of the simulation
    sim_state = 'transient' # 'steady' or 'transient'
    init_rech = None # 'first'
    period = [2010,2019] # recharge period
    first = period[0]
    last = period[1]
    time_step = 'M' # or 'D'
    actual_date = True # False if date is conceptual
    start = str(period[0])+'-01-01' # necessary to specify the first time_step date
    
    raw_path = stable_folder+'/'+'hydrometry/'
    Qobs_path = fnmatch.filter(os.listdir(raw_path), 'Hydrometric_*')[0]
    Qobs = pd.read_csv(raw_path+Qobs_path, sep=';', index_col=0, parse_dates=True)
    area = BV.geographic.area
    # area = float(Qobs_path.split('_')[-3])
    print(area)
    Qobs = (Qobs / (area*1000000)) * (3600 * 24) # m3/s to m/day
    Qobs = Qobs.squeeze()
    Qobs = Qobs.resample('M').mean()
    
    # Normalize with discharge
    BV.forcing.update_recharge_surfex(clim_mod = mod, clim_sce = 'historic',
                                             first_year = first, last_year = last,
                                             time_step = time_step, sim_state=sim_state)
    Rech = BV.forcing.recharge
    BV.forcing.update_runoff_surfex(clim_mod = mod, clim_sce='historic',
                                          first_year = first, last_year = last, time_step = 'M',
                                          sim_state='transient')
    Runof = BV.forcing.runoff # m/month
    
    norm_Rea = select_period(Rech, first, last)
    norm_Qobs = select_period(Qobs, first, last)
    
    Rt_Rea_Qobs = (norm_Qobs.mean() / norm_Rea.mean())
    print(Rt_Rea_Qobs.round(2))
    Nt = (norm_Rea * Rt_Rea_Qobs)

    BV.forcing.update_recharge(Nt, sim_state=sim_state)
    plt.plot(BV.forcing.recharge, c='r')

    BV.forcing.update_recharge(select_period(BV.forcing.recharge, first, last), sim_state=sim_state)
    BV.forcing.update_runoff(select_period(BV.forcing.runoff, first, last), sim_state=sim_state)
    
    # Active of not modules
    box = False # if True generate a rectangular model
    sink_fill = False # permit to fill sinks
    modpath_sim = False # run modpath particle tracking if True
    verbose = True # add print of MODFLOW in console
    post_process = False # necessary to decompose post process of process
    
    # Strcture of the model
    lay_number = 1 # vertical discrtization
    bottom = None # aquifer flat or not
    thick_exp = 1 # exponential decay of K with nlay
    cond_decay = 0 # exponential decay of K with depth
    thick = 30 # m
    
    # Hydraulic properties
    if watershed_name == 'Canut':
        Koptim = 1.4e-5 # koptim
        Sy = 0.001
    if watershed_name == 'Nancon':
        Koptim = 8e-6 # koptim
        Sy = 0.03
        
    Ks = np.array([Koptim]) * 3600 * 24 # m/second to m/day
    Sys = [Sy]
    
# RUN MODEL

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
                                                     verbose=verbose,
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
        
    # import pickle
    # with open(h5file, 'wb') as handle:
    #     pickle.dump(dictio, handle, protocol=pickle.HIGHEST_PROTOCOL)

    # BV.list_flow_model = list_flow_model
    # BV.list_of_success = list_success
    # BV.save_object()
    
#%% POSTPROCESS MODEL

watershed_names = ['Canut','Nancon']
code_names = ['J7513010','J0014010']
types_obs = ['complete'] # list of shapefile name layers for clip hydrology
for watershed_name, code_name in zip(watershed_names[:], code_names[:]) :
    print('##### '+watershed_name.upper()+' #####')
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' 
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)

    h5file = simulations_folder+'/'+'list_'+typ+'_'+var+'-'+mod+'-'+sce
    d = dd.io.load(h5file)
    list_model_name = d['list_model_name'][:]
    list_of_success = d['list_of_success'][:]
    list_flow_model = d['list_flow_model'][:]
    
    for model_name, success, flow_model in zip(list_model_name, list_of_success, list_flow_model):
            
        if success==True:
                print(success)
                
                BV.matrix_modflow(success,
                                  flow_model,
                                  first_only = False,
                                  watertable_elevation = True,
                                  watertable_depth = True, 
                                  seepage_areas = True,
                                  outflow_drain = True,
                                  groundwater_flux = True,
                                  specific_discharge = False,
                                  accumulation_flux = True,
                                  perenn_intermit_shp = False,
                                  groundwater_storage = True,
                                  verbose = True,
                                  export_tif = True)
                
                # # Extract results
                BV.results_modflow(ident=model_name,
                                   recharge=flow_model.climatic,
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

#%% INTERMITTENTCY MAP

typ_intermit = 'yearly' # yearly or persistency or monthly

watershed_names = ['Canut','Nancon']
code_names = ['J7513010','J0014010']
types_obs = ['complete'] # list of shapefile name layers for clip hydrology
for watershed_name, code_name in zip(watershed_names[:], code_names[:]) :
    print('##### '+watershed_name.upper()+' #####')
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' 
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)

    years = np.arange(first,last+1,1)
    
    simul_list = glob.glob(simulations_folder+typ+'*')
    # simuls = fnmatch.filter(os.listdir(simulations_folder), typ+'*')
    
    wbt.vector_lines_to_raster(stable_folder+'geographic/'+'watershed_contour.shp',
                               stable_folder+'geographic/'+'watershed_contour.tif',
                               base = stable_folder+'geographic/'+'watershed_dem.tif')
    line = imageio.imread(stable_folder+'geographic/'+'watershed_contour.tif')
    line = np.ma.masked_where(line <= 0, line)
    
    mask = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
        
    for simul in simul_list:
    
        acc_npy = np.load(os.path.join(simul, '_watershed','accumulation_flux.npy'), allow_pickle=True).item()
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
        
        if typ_intermit == 'persistency':
            fig, ax = plt.subplots(1,1, figsize=(7,6))
            
            days_flux = days_flux / len(acc_npy)
            im = ax.imshow(np.ma.masked_where(days_flux <= 0, days_flux),
                            cmap = 'coolwarm_r', vmin=0, vmax=1, alpha=1)
            ax.imshow(np.ma.masked_where(days_flux < 1, days_flux),
                      cmap = mpl.colors.ListedColormap('navy'), alpha=1)
            ax.imshow(line, cmap=mpl.colors.ListedColormap('k'))
            ax.get_xaxis().set_visible(False)
            ax.get_yaxis().set_visible(False)
            
            divider = make_axes_locatable(ax)
            cax = divider.append_axes('right', size='5%', pad=0.05)
    
            fig.colorbar(im, cax=cax, orientation='vertical',)
    
            ax.set_title(str(years[0])+' to '+str(years[-1]))
            fig.savefig(simul+'/_figures/png/'+'map_intermittent_persistency'+'.png', dpi=300, bbox_inches='tight')
            
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
    
                for k in range(len(interv)):
                    to = interv[k].copy()
                    
                    # fig, ax = plt.subplots(1,1, figsize=(7,6))
                    # ax.imshow(to)
                    
                    to[(to>0) & (days_flux==12)] = 2
                    to[(to>0) & (days_flux<12)] = 1
                    
                    to = np.ma.masked_array(to, mask=(mask<0))
                    to = np.ma.masked_array(to, mask=(to<=0))
                    
                    fig, ax = plt.subplots(1,1, figsize=(7,6))
                    # image_hidden = ax.imshow(np.ma.masked_where(mask<0, mask), cmap='Greys')
                    ax.imshow(np.ma.masked_where(mask<0, mask), cmap='Greys', alpha=0.5, zorder=0)
                    ax.imshow(np.ma.masked_where(to==1, to), cmap = mpl.colors.ListedColormap(['dodgerblue']))
                    ax.imshow(np.ma.masked_where(to==2, to), cmap = mpl.colors.ListedColormap(['darkorange']))
                    ax.imshow(line, cmap=mpl.colors.ListedColormap('k'))
                    ax.get_xaxis().set_visible(False)
                    ax.get_yaxis().set_visible(False)
                    
                    ax.set_title(str(years[i])+'-'+(str(k+1)))
                    
                    fig.savefig(simul+'/_figures/png/'+'map_intermittent_monthly_'+str(compt)+'.png', dpi=300, bbox_inches='tight')
    
                    plt.close()
                    
                    compt += 1
                    
                inf+=12
                sup+=12
            
            if typ_intermit == 'yearly':
                fig, ax = plt.subplots(1,1, figsize=(7,6))
                # image_hidden = ax.imshow(np.ma.masked_where(mask<0, mask), cmap='Greys')
                ax.imshow(np.ma.masked_where(mask<0, mask), cmap='Greys', alpha=0.5, zorder=0)
                ax.imshow(np.ma.masked_where(days_flux<12, days_flux), cmap = mpl.colors.ListedColormap(['dodgerblue']))
                ax.imshow(np.ma.masked_where(days_flux==12, days_flux), cmap = mpl.colors.ListedColormap(['darkorange']))
                ax.imshow(line, cmap=mpl.colors.ListedColormap('k'))
                ax.get_xaxis().set_visible(False)
                ax.get_yaxis().set_visible(False)
    
                ax.set_title(years[i])
            
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
            
                fig.savefig(simul+'/_figures/png/'+'map_intermittent_yearly_'+str(i)+'.png', dpi=300, bbox_inches='tight')
                plt.close()
                
                inf+=12
                sup+=12
        
        # begin_by = simul+'/_figures/png/'+'map_intermittent_streams'
        # filenames = sorted(glob.glob(begin_by+'*.png'), key=os.path.getmtime)
        # images = []
        # for filename in filenames:
        #     images.append(imageio.imread(filename))
        # imageio.mimsave(begin_by+'intermittency_gif'+'.gif', images, duration=0.5, loop=1)

#%% QUICKLY PLOT RESULTS

watershed_names = ['Canut','Nancon']
code_names = ['J7513010','J0014010']
types_obs = ['complete'] # list of shapefile name layers for clip hydrology
for watershed_name, code_name in zip(watershed_names[:], code_names[:]) :
    print('##### '+watershed_name.upper()+' #####')
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' 
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)

    scan = 'outflow_drain'
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    simul_list = glob.glob(simulations_folder+typ+'*')
    
    # Normalize with discharge
    BV.forcing.update_recharge_surfex(clim_mod = mod, clim_sce = 'historic',
                                             first_year = first, last_year = last,
                                             time_step = time_step, sim_state=sim_state)
    Rech = BV.forcing.recharge
    BV.forcing.update_runoff_surfex(clim_mod = mod, clim_sce='historic',
                                          first_year = first, last_year = last, time_step = 'M',
                                          sim_state='transient')
    Runof = BV.forcing.runoff # m/month
    norm_Rea = select_period(Rech, first, last)
    norm_Qobs = select_period(Qobs, first, last)
    Rt_Rea_Qobs = (norm_Qobs.mean() / norm_Rea.mean())
    print(Rt_Rea_Qobs.round(2))
    Nt = (norm_Rea * Rt_Rea_Qobs)
    BV.forcing.update_recharge(Nt, sim_state=sim_state)
    BV.forcing.update_recharge(select_period(BV.forcing.recharge, first, last), sim_state=sim_state)
    R = BV.forcing.recharge
    BV.forcing.update_runoff(select_period(BV.forcing.runoff, first, last), sim_state=sim_state)
    
    for simul in simul_list:
        model_name = simul.split('\\')[-1]
        Sy = float(model_name.split('_')[3].split('-')[0]) # %
        K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
        E = float(model_name.split('_')[3].split('-')[2]) # m
        D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
        params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
        Smod_path = simul+'/_watershed/_simulated_results.csv'
        # Smod_path = simul+'/_subbasins/hydrometry_J7353010/_simulated_results.csv'        
        if not os.path.exists(Smod_path):
            compt += 1
            continue
        Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
        Qmod = Smod['outflow_drain'] 
        Qmod = Qmod.squeeze() * 1000 * 30
        Qmod = Qmod + (BV.forcing.runoff * 1000 * 30)
        Cmod = Smod['recharge'] * 1000 * 30 # mm/months
    
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    raw_path = stable_folder+'/'+'hydrometry/'
    Qobs_path = fnmatch.filter(os.listdir(raw_path), 'Hydrometric_*')[0]
    Qobs = pd.read_csv(raw_path+Qobs_path, sep=';', index_col=0, parse_dates=True)
    area = float(Qobs_path.split('_')[-3])
    Qobs = (Qobs / (area*1000000)) * (3600 * 24 * 30) * 1000  # m3/s to mm/month
    Qobs = Qobs.squeeze()
    Qobs = select_period(Qobs, 2010,2019)
    Qobs = Qobs.resample('M').mean()
    
    import hydroeval as he
    nse = he.evaluator(he.nse, Qmod, Qobs, transform='log')[0]
    print(round(nse,2))
    
    # plt.plot(Cmod)
    # plt.plot(Qobs)
    # plt.plot(Qmod)
    
    fig, axs = plt.subplots(3,1, figsize=(7,7))
    axs = axs.ravel()
    
    yearsmaj = mdates.YearLocator(10)   # every year
    yearsmin = mdates.YearLocator(1)
    # monthsmaj = mdates.MonthLocator(6)  # every month
    # monthsmin = mdates.MonthLocator(3)
    # months_fmt = mdates.DateFormatter('%m') #b = name of month ?
    years_fmt = mdates.DateFormatter('%Y')
    
    o = Qobs # m/j to mm/month
    s = Qmod # m/j to mm/month
    # nd = 
    sat = Smod['seepage_areas']
    
    k = '{:.1e}'.format(K)
    sy = Sy
    title = 'Discharge'
    # nselog = round(((nd[0]))*100,1)
    # label = 'K = '+k+' m/s'+' ; '+'ɸ = '+str(round(sy,1))+'% ; '+\
    #         '$NSE_{log}$ = '+str(nselog)+'%'
    # nse_good.append(str(k)+'_'+str(sy)+'_'+str(nselog))
                 
    ax = axs[0]
    ax.xaxis.set_major_locator(yearsmaj)
    ax.xaxis.set_minor_locator(yearsmin)
    ax.xaxis.set_major_formatter(years_fmt)
    
    ax.plot(R, color='k', lw=2)
    ax.plot(s, color='red', lw=2)
    # ax.plot(s, lw=1, label=label)   
    ax.set_title(title)
    ax.plot(o, color='grey', lw=2, ls='-', zorder=0)
    ax.grid('grey')
    ax.set_ylim(-2,200)
    # ax.set_xlim(pd.to_datetime('2000'), pd.to_datetime('2005'))
    
    ax = axs[1]
    ax.plot(R, color='k', lw=2)
    ax.xaxis.set_major_locator(yearsmaj)
    ax.xaxis.set_minor_locator(yearsmin)
    ax.xaxis.set_major_formatter(years_fmt)
    ax.plot(o, color='grey', lw=2, ls='-', zorder=0)
    ax.set_yscale('log')
    ax.plot(s, color='red', lw=2)
    ax.set_ylim(0.1,200)
    ax.grid('grey')
    
    ax = axs[2]
    # ax.axhline(y=20, color='k', ls= '--', lw=2)
    ax.xaxis.set_major_locator(yearsmaj)
    ax.xaxis.set_minor_locator(yearsmin)
    ax.xaxis.set_major_formatter(years_fmt)    
    # sat_good.append(str(k)+'_'+str(sy)+'_'+str(round(sat.mean(),2)))
    ax.plot(sat, color='dodgerblue', lw=2)
    # ax.plot(sat, lw=1, label=label) 
    ax.set_ylim(-2,50)
    title = 'Saturation'
    ax.set_title(title)
    ax.grid('grey')
    # ax.set_xlim(pd.to_datetime(str(first)), pd.to_datetime(str(last)))
                            
    plt.tight_layout()
    # ax.legend(bbox_to_anchor=(1.5, 3), ncol=1)
    # fig.savefig(path_fig+'/'+'_chronic_'+name_file+'.png', dpi=300, bbox_inches='tight')
    fig.savefig(simul+'/_figures/png/'+'quickly_plot_results'+'.png', dpi=300, bbox_inches='tight')

#%% CROSS SECTION 2D

watershed_name = 'Nancon'

interactive = False

dem_data = BV.geographic.dem_data # dem data
wt_data = imageio.imread(simulations_folder+model_name+'/_watershed/_tifs/'+'watertable_elevation_t(0).tif') # watertable data
if watershed_name == 'Conceptual':
    river_data = None
else:
    river_data = imageio.imread(stable_folder+'/hydrology/'+'river.tif') # river data

modflow_display.interactive_cross_section(dem_data, wt_data, river_data, interactive=interactive)

#%% MAPS TOP VIEW STEADY

from tools import vtk
from groundwater_flow import visualization
#☻vtk.VTK(BV, 'modflow')
visu = visualization.Visualization(BV, model_name)
visu.visual2D(object_list = ['map', 'grid', 'watertable', 'watertable_depth','drain_flow',
                              'surface_flow'],
              color_scale = [(None,None),(None,None),(None,None),(0,10),
                              (None,None),(None,None)])
# visu.visual2D(object_list = ['pathlines', 'residence_times'],
#               color_scale = [(None,None),(None,None)], 
#               lines=100)

