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
# wbt.verbose = True
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

#%% ---- CATCH

#%% PATH WATERSHED

git_path = "D:/Users/abherve/GITHUB/HydroModPy/CORE_COMM/"
# Path to the data folder
data_path = "C:/Users/ronan/OneDrive/_HydroDataPy/"
# Path where the results will be stored
out_path = "D:/Users/abherve/PAPER/"
# Figure folder outputs
figsim_folder = 'D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/8_paper/hysteresis/figures/v5/'
figsim_folder = 'D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/8_paper/hysteresis/figures/v4/'


# git_path = "D:/abherve/GITHUB/HydroModPy/CORE_COMM/"
# # Path to the data folder
# data_path = "D:/abherve/HYDRODATAPY/"
# # Path where the results will be stored
# out_path = "D:/abherve/DYNAMIC/"
# out_path = "D:/abherve/INTERMITTENCY/"

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

from_xy = []

# Depending on the choices
dem_path = dems_path + dem_name
# import xugrid
# dem_reg = imageio.imread(dem_path)
# section_y = 1200
# section = dem_reg.ugrid.sel(y=section_y)

library_path = git_path + 'watershed/' + 'watershed_library.csv' # each row is a study site with outlet coordinates

# watershed_names = ['Horn','Leff','Canut','Nancon','Arguenon','Flume','Gael']
# code_names = ['J3014330','J1803010','J7513010','J0014010','J1105810','J7214010','J7313010']

watershed_names = ['Canut','Nancon']
code_names = ['J7513010','J0014010']

types_obs = ['complete'] # list of shapefile name layers for clip hydrology
fields_obs = ['fid']

#%% GENERATE WATERSHED

# watershed_names = ['Gael']

load = True

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
  
    print(BV.geographic.area.round())
    print(BV.geographic.slope.round())
    
    print(imageio.imread(BV.geographic.watershed_dem).shape[0]*
          imageio.imread(BV.geographic.watershed_dem).shape[1])
  
#%% DATA WATERSHED

for watershed_name in watershed_names[:] :
           
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True)

    BV.add_surfex(surfex_path)
    BV.add_drias(drias_path)
    BV.add_geology(geology_path)
    BV.add_hydrology(hydrology_path, types_obs=types_obs, fields_obs=fields_obs)
    BV.add_oceanic(oceanic_path)
    BV.add_hydrometry(hydrometry_path)
    BV.add_intermittency(intermittency_path)
    try:
        BV.add_piezometry()
    except:
        pass
    BV.add_subbasin()
    
    watershed_display.watershed_dem(BV)
    watershed_display.watershed_local(dem_path, BV)

#%% ---- CALIB

#%% DICHOTOMY STREAMS

hydrology_path = data_path + 'HYDROLOGY/France/Hydrographic/D035/' # add hydrographic shapefiles

from calibration import calib_root, calib_dichotomy, calib_analysis, calib_exploration, calib_basis

watershed_names = ['Canut','Nancon']
code_names = ['J7513010','J0014010']

for watershed_name, code_name in zip(watershed_names[:], code_names[:]) :
    
    if watershed_name == 'Canut':
        types_obs = ['perennial','river','complete','zh_meuchezecanut'] # list of shapefile name layers for clip hydrology
        fields_obs = ['fid','fid','fid','fid']
    if watershed_name == 'Nancon':
        types_obs = ['perennial','river','complete','zh_couesnon'] # list of shapefile name layers for clip hydrology
        fields_obs = ['fid','fid','fid','fid']
        
    df = pd.DataFrame(np.nan, index=range(1), columns=types_obs)
    
    for type_obs, field_obs in zip(types_obs, fields_obs):
   
        print('##### '+watershed_name.upper()+' #####')
        
        BV = watershed_root.Watershed(watershed_name=watershed_name,
                                      dem_path=dem_path, 
                                      out_path=out_path,
                                      load=True,
                                      modflow_path=modflow_path)
        BV.add_forcing()
        
        area = BV.geographic.area
        
        stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
            
        # BV.add_hydrology(hydrology_path, types_obs=[type_obs], fields_obs=[field_obs])
                
        BV.forcing.update_recharge_surfex(clim_mod = 'REA', clim_sce='historic',
                                          first_year = 1960, last_year=2019, time_step = 'D',
                                          sim_state='steady') #

        # BV.hydrodynamic.update_porosity(0.1)
        # BV.hydrodynamic.update_hyd_cond(2)
        BV.hydrodynamic.update_nlay(1)
        BV.hydrodynamic.update_thickness(30)
        BV.hydrodynamic.update_bottom(None)
        BV.hydrodynamic.update_cond_decay(0)
        BV.hydrodynamic.update_thick_exp(1)
        
        params_df = pd.DataFrame(columns=['params',
                                          'init_values','lower_bounds','higher_bounds',
                                          'units','scale'])
        params_df.loc[0] = ['k1',8.64e-01,8.64e-03,8.64e+01,'m/j','lin']
        
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

#%% EXPLORATION DISCHARGE

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
    
    BV.add_forcing()
    BV.add_hydrodynamic()
    
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots

    fcalib = 1985
    lcalib = 2019
    
    fhist = fcalib
    lhist = lcalib
    
    sim_state = 'transient'
    time_step = 'M'
    
    var = 'REC'
    wr = True
    wish = 0
    mod = 'REA'
    
    raw_path = stable_folder+'/'+'hydrometry/'
    Qobs_path = fnmatch.filter(os.listdir(raw_path), 'Hydrometric_*')[0]
    Qobs = pd.read_csv(raw_path+Qobs_path, sep=';', index_col=0, parse_dates=True)
    # area = float(Qobs_path.split('_')[-3])
    area = BV.geographic.area
    Qobs = (Qobs / (area*1000000)) * (3600 * 24) # m3/s to m/day
    Qobs = Qobs.squeeze()
    Qobs = Qobs.resample('M').mean()
    # plt.plot(Qobs)
    # plt.yscale('log')
    
    fqobs = Qobs.first_valid_index().year+1
    lqobs = Qobs.last_valid_index().year-1

    year_min = max(fqobs, fhist)
    year_max = min(lqobs, lhist)
    
    Qobs = select_period(Qobs, year_min, year_max)
    print(Qobs.mean() * 1000)
    
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
    print(Rt_Rea_Qobs.round(2))
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
    
    list_npy = glob.glob(BV.calibration_folder+'/'+params_file+'/hydrometry_calibration/_watershed/'+'*'+'.npy')
    for npy in list_npy:
        os.remove(npy)
    
    params_df.to_csv(BV.calibration_folder+'/'+params_file+'.csv', sep=';', index=None)
    
    # params_file = 'calib_explo_hom_1v_n1'
    # params_file = 'calib_explo_hom_1v_k1'
    # params_file = 'calib_dicot_het_2v_k1-k2'•

    print((BV.forcing.recharge*1000*365).mean())
            
# EXPLORATION LAUNCH

    calib = calib_root.Calibration(params_file, BV, observations = ['hydrometry'])
    # calib.exploration(resolution=100)

#%% NOT - EXPLORATION PLOT

from calibration import calib_root, calib_dichotomy, calib_analysis, calib_exploration, calib_basis

code_names = ['J7513010','J0014010']
watershed_names = ['Canut','Nancon']

params_file = 'calib_explo_hom_2v_k1-n1'

wish = 0

sat_typ = 'seepage_areas'

for watershed_name in watershed_names[:]:
    
    print('##### '+watershed_name.upper()+' #####')
    
    if watershed_name == 'Canut':
        min_nse = 70
        min_sat = 3
        max_sat = 25
    if watershed_name == 'Nancon':
        min_nse = 70
        min_sat = 4
        max_sat = 25
    
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
    
    # test.display_objective_function(save=None)
    # test.find_best_values()
    # test.display_best_data()
    
    sim_res=test.sim_results
    
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
    
    fig, axs = plt.subplots(2,2, figsize=(9,5))
    axs = axs.ravel()
    fig.suptitle(watershed_name.upper())
    
    numb = 0
    for i in range(len(obs[typ_name])):
        o = obs[typ_name][i] * 1000 * 30 # m/j to mm/month
        s = sim[typ_name][i] * 1000 * 30 # m/j to mm/month
        nd = ind[typ_name][i]
        sat = test.sim_results[synt[i]][sat_typ]
        sat = pd.to_numeric(sat)
        
        k = '{:.1e}'.format(float(synt[i].split(';')[0])/24/3600)
        sy = float(synt[i].split(';')[1]) * 100
        title = 'Discharge [mm/month]'
        nselog = round(((nd[0]))*100,1)
        label = 'K = '+k+' m/s'+' ; '+'ɸ = '+str(round(sy,1))+'% ; '+\
                '$NSE_{log}$ = '+str(nselog)+'%'
        nse_good.append(str(k)+'_'+str(sy)+'_'+str(nselog))
        if nselog > min_nse:
            # if all(i <= 50 for i in sat):
            if sat.max() < max_sat:
                if sat.max() > min_sat:
                    numb += 1
                # c = []
                # for h in range(len(ind[typ_name])):
                #     d = ind[typ_name][h][0]
                #     c.append(d)
        c = np.linspace(0,1,len(obs[typ_name]))

        cmap = mpl.cm.get_cmap('viridis_r')
        color_gradients = cmap(c)
        # vmin = min(c)
        # vmax = max(c)
        # norm = mpl.colors.Normalize(vmin=vmin, vmax=vmax)
        
        if nselog > min_nse:
            # if all(i <= 50 for i in sat):
            if sat.max() < max_sat:
                if sat.max() > min_sat:    
                
                    ax = axs[0]
                    fmt_xaxes(axs[0], 6, 1)                 
                    ax.plot(s, color=color_gradients[i], lw=1, label=label)
                    ax.set_title(title)
                    ax.plot(o, color='grey', lw=3, ls='-', zorder=0)
                    ax.set_xlim(pd.to_datetime('1989'), pd.to_datetime('2021'))
                    del(ax)
                
                    ax = axs[1]
                    fmt_xaxes(axs[1], 6, 1)
                    ax.set_title('Log discharge [mm/month]')
                    ax.plot(select_period(o.copy(),2010,2019), color='grey', lw=3, ls='-', zorder=0)
                    ax.set_yscale('log')
                    ax.plot(select_period(s.copy(),2010,2019), color=color_gradients[i], lw=1, label=label)

                    ax = axs[2]
                    fmt_xaxes(axs[2], 6, 1)
                    sat_good.append(str(k)+'_'+str(sy)+'_'+str(round(sat.mean(),2)))
                    ax.plot(select_period(sat.copy(),2010,2019), color=color_gradients[i], lw=1, label=label)
                    ax.set_ylim(-2,50)
                    title = 'Saturation [%]'
                    ax.set_title(title)
                    # ax.set_xlim(pd.to_datetime('2000'), pd.to_datetime('2005'))
                                
    plt.tight_layout()
    ncol = 2
    ax.legend(bbox_to_anchor=(1.2,0.5), prop={'size': 5}, loc="center left", 
              borderaxespad=0, ncol=ncol)
    ax = axs[3]
    plt.axis('off')
        
    # divider = make_axes_locatable(ax)
    # cax = divider.append_axes('right', size='1.25%', pad=0.1)
    # fig.add_axes(cax)
    # norm = Normalize(vmin=vmin, vmax=vmax)
    # n_cmap = cm.ScalarMappable(norm=norm, cmap=cmap)
    # n_cmap.set_array([])
    # ax.get_figure().colorbar(n_cmap, cax=cax, orientation="vertical")

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
                        sim_sat[j][i] = pd.to_numeric(sim_res[string][sat_typ]).min()
                    except:
                        pass
                if k == 1:
                    try:
                        ax.set_title('SAT MEAN [%]')
                        sim_sat[j][i] = pd.to_numeric(sim_res[string][sat_typ]).mean()
                    except:
                        pass
                if k == 2:
                    try:
                        ax.set_title('SAT MAX [%]')
                        sim_sat[j][i] = pd.to_numeric(sim_res[string][sat_typ]).max()
                    except:
                        pass
                compt += 1
        Z=sim_sat
        pc = ax.contourf(X,Y,Z,cmap='jet', levels=np.arange(0,51,5)) #figadd.cmap_white_jet()
        ax.set_xscale('log')
        ax.set_ylabel('Sy [-]')
        ax.set_xlabel('K [m/j]')
   
    position=fig.add_axes([1.05,0.2,0.02,0.7])  ## the parameters are the specified position you set 
    fig.colorbar(pc,cax=position)
    plt.tight_layout()

    fig, axs = plt.subplots(1,3, figsize=(15,4))
    fig.suptitle(watershed_name.upper())
    axs = axs.ravel()
    
    ax = axs[0]
    X,Y = np.meshgrid(test.params_values[0], test.params_values[1])
    Z=test.obj_function.copy()
    Z[Z<0] = 0
    from numpy import inf
    Z[Z == inf] = 0
    pc = ax.imshow(Z, vmin = 0, vmax = 1, aspect='auto') #figadd.cmap_white_jet() , shading='gouraud'
    # ax.set_xscale('log')
    ax.set_ylabel('Sy [-]')
    ax.set_xlabel('K [m/j]')
    divider = make_axes_locatable(ax)
    cax = divider.append_axes('right', size='5%', pad=0.05)
    cb=fig.colorbar(pc, cax=cax, orientation='vertical')
    cb.set_label('$NSE_{log}$', rotation=270, labelpad=40)

    ax = axs[1]
    ax.axes.tick_params(which='both', direction='out', zorder=10)
    X,Y = np.meshgrid(test.params_values[0], test.params_values[1])
    Z=test.obj_function.copy()
    Z[Z<0] = 0
    Z[Z == inf] = 0
    pc = ax.pcolormesh(X,Y,Z, cmap='jet', shading='gouraud', vmin=0, vmax=1) #figadd.cmap_white_jet()
    ax.set_xscale('log')
    ax.set_ylabel('Sy [-]')
    ax.set_xlabel('K [m/j]')
    divider = make_axes_locatable(ax)
    cax = divider.append_axes('right', size='5%', pad=0.05)
    cb = fig.colorbar(pc, cax=cax, orientation='vertical')
    cb.set_ticks(np.arange(0,1.1,0.1)) 
    cb.set_label('$NSE_{log}$', rotation=270, labelpad=40)

    ax = axs[2]
    ax.axes.tick_params(which='both', direction='out', zorder=10)
    X,Y = np.meshgrid(test.params_values[0], test.params_values[1])
    Z=test.obj_function.copy()
    Z[Z<0] = 0
    from numpy import inf
    Z[Z == inf] = 0
    bounds = np.arange(0,1.1,0.1)
    norm = mpl.colors.Normalize(vmin=-1, vmax=1.0)
    pc = ax.contourf(X, Y, Z, levels=np.arange(0,1.1,0.1))    
    divider = make_axes_locatable(ax)
    cax = divider.append_axes('right', size='5%', pad=0.05)
    cb = fig.colorbar(pc, cax=cax, orientation='vertical')
    cb.set_ticks(np.arange(0,1.1,0.1)) 
    cb.set_label('$NSE_{log}$', rotation=270, labelpad=40)
    ax.set_xscale('log')
    ax.set_ylabel('Sy [-]')
    ax.set_xlabel('K [m/j]')
    
    plt.tight_layout()

#%% ---- MODEL

#%% TYP SIM NAMING

typ = 'sce-synt-t1'
# typ = 'calibr-t6'
# typ = 'test-jr'
# typ = 'projec-test-poro'
# typ = 'reanal-1'
# typ = 'steady-1'

# mod_list = ['CNR-ALA','HAD-REG']
# mod_list = ['CNR-ALA']
# mod_list = ['MPI-R09','NOR-R15']
# mod_list = ['MPI-R09']
# mod_list = ['REA']
mod_list = ['SYNT-NORM', 'SYNT-DRY1', 'SYNT-DRY2']

sce_list = ['historic']
# sce_list = ['RCP8.5']
# sce_list = ['RCP2.6']

#%% RECHARGE FRAME EBR

load = True

surfex_path =  data_path + 'CLIMATE/France/SURFEX/Brittany/'
from_shp = 'C:/Users/ronan/OneDrive/_HydroDataPy/MISCELLANEOUS/France/frame_ebr.shp'

BV = watershed_root.Watershed(watershed_name='Frame',
                              dem_path=dem_path, 
                              out_path=out_path,
                              modflow_path=modflow_path,
                              library_path=library_path,
                              load=load,
                              from_shp=from_shp,
                              from_dem=from_dem,
                              from_xy=from_xy,
                              cell_size=cell_size)

stable_folder = out_path+'/'+'Frame'+'/'+'results_stable/' # necessary for plots
simulations_folder = out_path+'/'+'Frame'+'/'+'results_simulations/'  # necessary for plots  

# surfex = pd.read_csv(stable_folder+'climatic/'+'_ALL_D.csv', sep=';',
#                       index_col=0, parse_dates=True).resample('M').sum() / 1000
# drias = pd.read_csv(stable_folder+'drias/'+'_ALL_D.csv', sep=';', index_col=0,
#                     parse_dates=True).resample('M').sum() / 1000

surfex = pd.read_csv(stable_folder+'climatic/'+'_ALL_D.csv', sep=';',
                      index_col=0, parse_dates=True).resample('M').mean() / 1000
drias = pd.read_csv(stable_folder+'drias/'+'_ALL_D.csv', sep=';', index_col=0,
                    parse_dates=True).resample('M').mean() / 1000

my = select_period(surfex['REC_REA_historic'], 1960, 2019)

norm_years = select_period(my, 2000, 2001)
norm = norm_years.groupby([lambda x: norm_years.index.month]).mean()
dry_years = select_period(my, 1975, 1976)
dry = dry_years.groupby([lambda x: dry_years.index.month]).mean()
wet_years = select_period(my, 2000, 2001)
wet = wet_years.groupby([lambda x: wet_years.index.month]).mean()

# plt.plot(norm, c='k')
# plt.plot(dry, c='red')
# plt.plot(wet, c='b')

sce_norm = pd.concat([norm, norm, norm, norm, norm, norm, norm, norm, norm, norm,
                      norm, norm, norm, norm, norm, norm, norm, norm, norm, norm,
                      norm, norm, norm, norm, norm, norm, norm, norm, norm, norm,
                      norm, norm, norm, norm, norm, norm, norm, norm, norm, norm,
                      norm, norm, norm, norm, norm, norm, norm, norm, norm, norm,
                      norm, norm, norm, norm, norm, norm, norm, norm, norm, norm], ignore_index=True)
# sce_dry1 = pd.concat([norm, dry, norm, dry, norm, dry, norm, dry, norm, dry,
#                       norm, dry, norm, dry, norm, dry, norm, dry, norm, dry,
#                       norm, dry, norm, dry, norm, dry, norm, dry, norm, dry,
#                       norm, dry, norm, dry, norm, dry, norm, dry, norm, dry,
#                       norm, dry, norm, dry, norm, dry, norm, dry, norm, dry,
#                       norm, dry, norm, dry, norm, dry, norm, dry, norm, dry], ignore_index=True)
sce_dry1 = pd.concat([norm, dry, dry, norm, dry, dry, norm, dry, dry, norm,
                      dry, dry, norm, dry, dry, norm, dry, dry, norm, dry,
                      dry, norm, dry, dry, norm, dry, dry, norm, dry, dry,
                      norm, dry, dry, norm, dry, dry, norm, dry, dry, norm,
                      dry, dry, norm, dry, dry, norm, dry, dry, norm, dry,
                      dry, norm, dry, dry, norm, dry, dry, norm, dry, dry,], ignore_index=True)
sce_dry2 = pd.concat([norm, dry, dry, dry, dry, dry, norm, dry, dry, dry,
                      dry, dry, norm, dry, dry, dry, dry, dry, norm, dry,
                      dry, dry, dry, dry, norm, dry, dry, dry, dry, dry,
                      norm, dry, dry, dry, dry, dry, norm, dry, dry, dry,
                      dry, dry, norm, dry, dry, dry, dry, dry, norm, dry,
                      dry, dry, dry, dry, norm, dry, dry, dry, dry, dry], ignore_index=True)

# plt.plot(sce_norm, c='b', lw=3)
# plt.plot(sce_dry1, c='darkorange', lw=2)
# plt.plot(sce_dry2, c='red', lw=1)

sce_norm.index = pd.date_range(start='01/01/1960', end='31/12/2019', freq='M')
sce_dry1.index = pd.date_range(start='01/01/1960', end='31/12/2019', freq='M')
sce_dry2.index = pd.date_range(start='01/01/1960', end='31/12/2019', freq='M')

base_name = figsim_folder+'_successive/'

fig, ax = plt.subplots(1,1, figsize=(6,2))
ax.get_xaxis().set_visible(False)
ax.get_yaxis().set_visible(False)
ax.plot(select_period(sce_norm, 1960, 1972), c='k', lw=3)
spec_name = 'sce_norm'
fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight') 
fig, ax = plt.subplots(1,1, figsize=(6,2))
ax.get_xaxis().set_visible(False)
ax.get_yaxis().set_visible(False)
ax.plot(select_period(sce_dry1, 1960, 1972), c='k', lw=3)
spec_name = 'sce_dry1'
fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight') 
fig, ax = plt.subplots(1,1, figsize=(6,2))
ax.get_xaxis().set_visible(False)
ax.get_yaxis().set_visible(False)
ax.plot(select_period(sce_dry2, 1960, 1972), c='k', lw=3)
spec_name = 'sce_dry2'
fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight') 

#%% SINUSOID RECHARGES

"""
SYnthetic Sinusiodal recharge 

Parameters
----------
    input recharge
    
period : string
    D (day) or M (month)

amplitude : float
    modifies the amplitude (max-min) of the sinusoid
    
offset : float
    modifies the mean of the sinusoid
    
omega : float
    modifies the sinusoid frequency
    
phase : float
    modifies the phase of the sinusoid

"""

def sinusoid_recharge(serie, period, amplitude, offset, omega, phase):

    from scipy.optimize import curve_fit
    def sinusoid(x, A , offset, omega, phase):
        return A*np.sin(omega*x+phase) + offset
    def get_p0(Y, T):
        A0 = (max(Y[0:T]) - min(Y[0:T]))/2
        offset0 = Y[0]
        phase0 = 0
        omega0 = 2.*np.pi/T
        return [A0, offset0, omega0, phase0]
    if period=='D':
        T=365
    if period=='M':
        T=12
    date = serie.index
    serie = serie.reset_index(drop=True)
    X = serie.index
    Y = serie.values
    param, covariance = curve_fit(sinusoid, X, Y, p0=get_p0(Y, T))
    param[0] = param[0] * amplitude # Amplitude : max
    param[1] = param[1] * offset # Offset : shift v
    param[2] = param[2] * omega # Omega : cycles
    param[3] = param[3] * phase # Phase : shift h
    sinus = sinusoid(X, *param)
    sinus = pd.Series(sinus)
    sinus.index = date
    sinus[sinus < 0] = 0
    
    return sinus

# serie = select_period(surfex['REC_REA_historic'], 1960, 2019)
# period = 'M'
# amplitude = 1
# offset = 1
# omega = 1
# phase = 1
# norm = sinusoid_recharge(serie, period, amplitude, offset, omega, phase)
# norm = norm.groupby([lambda x: norm.index.month]).mean()
# sce_norm = pd.concat([norm, norm, norm, norm, norm, norm, norm, norm, norm, norm], ignore_index=True)
# plt.plot(sce_norm, 'b')

# # serie = select_period(surfex['REC_REA_historic'], 1975, 1976)
# period = 'M'
# amplitude = 1
# offset = 0.5
# omega = 1
# phase = 1
# dry = sinusoid_recharge(serie, period, amplitude, offset, omega, phase)
# dry = dry.groupby([lambda x: dry.index.month]).mean()
# sce_dry1 = pd.concat([norm, dry, norm, dry, norm, dry, norm, dry, norm, dry], ignore_index=True)
# plt.plot(sce_dry1, 'darkorange')

#%% PARAM RUN MODEL

sim_state = 'transient' # 'steady' or 'transient'
# sim_state = 'steady' # 'steady' or 'transient'
modpath_sim = False # run modpath particle tracking if True
nlay = 1

watershed_names = ['Canut','Nancon']
code_names = ['J7513010','J0014010']

# watershed_names = ['Canut']
# code_names = ['J7513010']

# watershed_names = ['Nancon']
# code_names = ['J0014010']

for watershed_name, code_name in zip(watershed_names[:], code_names[:]) :
    
    fig, ax = plt.subplots(1,1, figsize=(6,3))
    
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
    BV.add_oceanic(oceanic_path)
    
    # Observed discharge
    raw_path = stable_folder+'/'+'hydrometry/'
    Qobs_path = fnmatch.filter(os.listdir(raw_path), 'Hydrometric_*')[0]
    Qobs = pd.read_csv(raw_path+Qobs_path, sep=';', index_col=0, parse_dates=True)
    area = BV.geographic.area
    # area = float(Qobs_path.split('_')[-3])
    Qobs = (Qobs / (area*1000000)) * (3600 * 24) # m3/s to m/day
    Qobs = Qobs.squeeze()
    # Qobs = Qobs.resample('M').sum()
    Qobs = Qobs.resample('M').mean()
    
    # Input recharge
    bzh_rech = False
    var = 'REC'
    wr = True
    time_step = 'M' # or 'D'
    actual_date = True # False if date is conceptual
    
    # Active of not modules
    box = False # if True generate a rectangular model
    sink_fill = False # permit to fill sinks
    verbose = True # add print of MODFLOW in console
    post_process = False # necessary to decompose post process of process
    
    # Strcture of the model
    lay_number = nlay # vertical discrtization
    bottom = None # aquifer flat or not
    thick_exp = 1 # exponential decay of K with nlay
    cond_decay = 0 # exponential decay of K with depth
    thick = 30 # m
    
    # Hydraulic properties
    if watershed_name == 'Canut':
        Koptim = 5.5e-5 # koptim 1.4e-5 / 5.33e-5
        Sy = 0.001
    if watershed_name == 'Nancon':
        Koptim = 5.5e-5 # koptim 8e-6 / 5.82e-5
        Sy = 0.02
    Ks = np.array([Koptim]) * 3600 * 24 # m/second to m/day
    Sys = [Sy]
    
    # Model of recharge
    for mod in mod_list:           
        for sce in sce_list:    
            
            # Recharge
            if mod == 'REA':
                init_rech = None
                
                period = [1960,2019]
                first = period[0]
                last = period[1]
                start = str(period[0])+'-01-01' # necessary to specify the first time_step date

                # period_hist = [1985,2019]         
                # first_hist = period_hist[0]
                # last_hist = period_hist[1]
                
                period_norm = [1990,2019]
                first_norm = period_norm[0]
                last_norm = period_norm[1]
            else:
                init_rech = 'first'
                
                period = [1972,2098]
                first = period[0]
                last = period[1]
                start = str(period[0])+'-01-01' # necessary to specify the first time_step date
                
                period_hist = [1972,2005] # recharge period     
                first_hist = period_hist[0]
                last_hist = period_hist[1]
                
                period_norm = [1990,2004]
                first_norm = period_norm[0]
                last_norm = period_norm[1]
                                    
            Q_norm = select_period(Qobs, first_norm, last_norm)

            if mod == 'REA':
                # Normalize
                '''
                # BV.forcing.update_recharge_surfex(clim_mod = mod, clim_sce = 'historic',
                #                                   first_year = first_norm, last_year = last_norm,
                #                                   time_step = time_step, sim_state = sim_state)
                # Rech_norm = BV.forcing.recharge
                '''
                
                Rech_norm = select_period(surfex['REC_REA_historic'], first_norm, last_norm)
                Runof_norm = select_period(surfex['RUN_'+mod+'_historic'], first_norm, last_norm)

                # for t in Q_norm.index.year:
                    # Ratio_norm = (Q_norm[Q_norm.index.year==t].mean() / Rech_norm[Rech_norm.index.year==t].mean())
                    # print(Ratio_norm.round(2))
                Ratio_norm = (Q_norm.mean() / Rech_norm.mean())
                # Ratio_norm = (Q_norm.mean() / (Rech_norm.mean()+Runof_norm.mean()))
                
                print(Ratio_norm)
                
                # Historic
                '''
                BV.forcing.update_recharge_surfex(clim_mod = mod, clim_sce = sce,
                                                  first_year = first, last_year = last,
                                                  time_step = time_step, sim_state = sim_state)
                Rech = BV.forcing.recharge * Ratio_norm
                
                BV.forcing.update_runoff_surfex(clim_mod = mod, clim_sce=sce,
                                                first_year = first, last_year = last,
                                                time_step = time_step, sim_state = sim_state)
                Runof = BV.forcing.runoff
                '''
                
                Rech = select_period(surfex['REC_REA_historic'], first, last) * Ratio_norm
                Runof = select_period(surfex['RUN_REA_historic'], first, last)
                
                # Update recharge
                BV.forcing.update_recharge(Rech , sim_state = sim_state)
                BV.forcing.update_runoff(Runof, sim_state = sim_state)
                                                    
            if (mod != 'REA') & (mod.split('-')[0] != 'SYNT'):
                gcm = mod.split('-')[0]
                rcm = mod.split('-')[1]
                
                # Normalize
                '''
                BV.forcing.update_recharge_drias(gcm_mod = gcm, rcm_mod = rcm, sce_mod = 'historic',
                                                 first_year = first_norm, last_year = last_norm,
                                                 sim_state = sim_state)
                Rech_norm = BV.forcing.recharge.resample('M').mean()
                '''
                
                Rech_norm = select_period(drias['REC_'+gcm+'-'+rcm+'_historic'], first_norm, last_norm)
                # Runof_norm = select_period(drias['RUN_'+gcm+'-'+rcm+'_historic'], first_norm, last_norm)

                # for t in Q_norm.index.year:
                    # Ratio_norm = (Q_norm[Q_norm.index.year==t].mean() / Rech_norm[Rech_norm.index.year==t].mean())
                    # print(Ratio_norm.round(2))
                Ratio_norm = (Q_norm.mean() / Rech_norm.mean())
                # Ratio_norm = (Q_norm.mean() / (Rech_norm.mean()+Runof_norm))

                
                # Historic
                '''
                BV.forcing.update_recharge_drias(gcm_mod = gcm, rcm_mod = rcm, sce_mod = 'historic',
                                                 first_year = first_hist, last_year = last_hist,
                                                 sim_state = sim_state)
                Rech_hist = BV.forcing.recharge.resample('M').mean() * Ratio_norm
                BV.forcing.update_runoff_drias(gcm_mod = gcm, rcm_mod = rcm, sce_mod = 'historic',
                                                 first_year = first_hist, last_year = last_hist,
                                                 sim_state = sim_state)
                Runof_hist = BV.forcing.runoff.resample('M').mean() # m/month
                '''
                # Future
                '''
                BV.forcing.update_recharge_drias(gcm_mod = gcm, rcm_mod = rcm, sce_mod = sce,
                                                  first_year = first, last_year = last,
                                                  sim_state = sim_state)
                Rech_fut = BV.forcing.recharge.resample('M').mean() * Ratio_norm
                BV.forcing.update_runoff_drias(gcm_mod = gcm, rcm_mod = rcm, sce_mod = sce,
                                                first_year = first, last_year = last,
                                                sim_state = sim_state)
                Runof_fut = BV.forcing.runoff.resample('M').mean() # m/month
                '''
                
                Rech_hist = select_period(drias['REC_'+gcm+'-'+rcm+'_'+'historic'], first_hist, last_hist) * Ratio_norm
                Runof_hist = select_period(drias['RUN_'+gcm+'-'+rcm+'_'+'historic'], first_hist, last_hist)
                Rech_fut = select_period(drias['REC_'+gcm+'-'+rcm+'_'+sce], first, last) * Ratio_norm
                Runof_fut = select_period(drias['RUN_'+gcm+'-'+rcm+'_'+sce], first, last)
                
                Rech = pd.concat((Rech_fut, Rech_hist), axis=1).mean(axis=1)
                Runof = pd.concat((Runof_fut, Runof_hist), axis=1).mean(axis=1)
                
                # Update recharge
                BV.forcing.update_recharge(Rech, sim_state = sim_state)
                BV.forcing.update_runoff(Runof, sim_state = sim_state)
                
                # if watershed_name == 'Canut':
                #     lw=2
                # if watershed_name == 'Nancon':
                #     lw=1
            # plt.plot((BV.forcing.recharge*1000*30).resample('Y').sum(), lw=1)
            # plt.plot((Qobs*1000*30).resample('Y').sum(), lw=1)
                # ax.set_yscale('log')
            
            if mod.split('-')[0] == 'SYNT':
                # Update recharge
                init_rech = 'first'
                if mod.split('-')[1] == 'NORM':
                    Rech = sce_norm
                if mod.split('-')[1] == 'DRY1':
                    Rech = sce_dry1
                if mod.split('-')[1] == 'DRY2':
                    Rech = sce_dry2
                BV.forcing.update_recharge(Rech, sim_state = sim_state)
                BV.forcing.update_runoff(Rech*0.1, sim_state = sim_state)
                
            # print((Rech*1000).resample('Y').sum().round(2)[0])
            
            list_model_name = []
            list_of_success = []
            list_flow_model = []
            list_var_store = []

            # Update properties
            compt = 1
            for Sy in Sys:
                for K in Ks:

                    BV.hydrodynamic.update_nlay(nlay) # 1
                    BV.hydrodynamic.update_bottom(None) # None
                    BV.hydrodynamic.update_cond_decay(0) # 0
                    BV.hydrodynamic.update_thick_exp(1) # 1
                    BV.hydrodynamic.update_thickness(30) # 30 / intervient pas si bottom != None
                    
                    BV.hydrodynamic.update_hyd_cond(K) 
                    BV.hydrodynamic.update_porosity(Sy)
                      
                    date_today = datetime.now().strftime("%d/%m/%Y %H:%M:%S") # just a string
                    date_today = date_today.replace('/','-')
                    date_today = date_today.replace(':','-')
                    date_today = date_today.replace(' ','_')
                    
                    if sim_state == 'transient':
                        model_name = typ+'_'+str(compt)+'_'+\
                                     var+'-'+mod+'-'+sce+'_'+\
                                     str(Sy*100)+'-'+str(round(K,2))+'-'+str(thick)+'_'+\
                                     str(Rech.first_valid_index().year)+'-'+str(Rech.last_valid_index().year)
                    else:
                        model_name = typ+'_'+str(compt)+'_'+\
                                     var+'-'+mod+'-'+sce+'_'+\
                                     str(Sy*100)+'-'+str(round(K,2))+'-'+str(thick)
                                     
                    # Run model
                    try:
                        print('SIM - ' + model_name)
                        success, flow_model = BV.run_modflow(ident=model_name,
                                                             modpath_sim=modpath_sim,
                                                             sink_fill=sink_fill,
                                                             box=box,
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
                    list_var_store.append(BV.forcing.runoff)
                    
                    compt+=1
                    
            print(list_of_success)
            
            dictio = {}
            dictio['list_model_name'] = list_model_name
            dictio['list_of_success'] = list_of_success
            dictio['list_flow_model'] = list_flow_model
            dictio['list_var_store'] = list_var_store
            h5file = simulations_folder+'/'+'list_'+typ+'_'+var+'-'+mod+'-'+sce
            
            dd.io.save(h5file, dictio)
                        
# POSTPROCESS MODEL

watershed_names = ['Canut','Nancon']
code_names = ['J7513010','J0014010']

# watershed_names = ['Canut']
# code_names = ['J7513010']

for watershed_name, code_name in zip(watershed_names[:], code_names[:]) :
    
    print('##### '+watershed_name.upper()+' #####')
    
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' 
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)
    
    
    for mod in mod_list:
        for sce in sce_list:
    
            h5file = simulations_folder+'/'+'list_'+typ+'_'+var+'-'+mod+'-'+sce
            d = dd.io.load(h5file)
            list_model_name = d['list_model_name'][:]
            list_of_success = d['list_of_success'][:]
            list_flow_model = d['list_flow_model'][:]
            list_var_store = d['list_var_store'][:]
            
            for model_name, success, flow_model, var_store in zip(list_model_name,
                                                                 list_of_success,
                                                                 list_flow_model,
                                                                 list_var_store):
                    
                if success==True:
                        print(success)
                        
                        BV.matrix_modflow(success,
                                          flow_model,
                                          first_only = True,
                                          watertable_elevation = True,
                                          watertable_depth = True, 
                                          seepage_areas = True,
                                          outflow_drain = True,
                                          groundwater_flux = True,
                                          specific_discharge = False,
                                          accumulation_flux = True,
                                          perenn_intermit_shp = False,
                                          groundwater_storage = True,
                                          residence_times = False,
                                          verbose = True,
                                          export_tif = True)
                        
                        # Necessary for results_modflow
                        BV.forcing.update_recharge(flow_model.climatic,
                                                   sim_state=sim_state)
                        recharge = BV.forcing.recharge
                        runoff = var_store.copy()
                        
                        # # Extract results
                        BV.results_modflow(ident=model_name,
                                           recharge=recharge,
                                           runoff=runoff,
                                           actual_date=actual_date,
                                           time_step=time_step)
                        
                        ## Plot maps
                        surf = modflow_display.SurfaceOutputs(flow_model.climatic, simulations_folder, stable_folder,
                                                              model_name, types_obs,
                                                              save_gif=False,
                                                              first_only=True,
                                                              sim_state=sim_state,
                                                              outflow=True,
                                                              accflux=True,
                                                              intermittency=False,
                                                              chronics=False)

# TRACE DOWNSLOPE

wbt.surface_area_ratio(
    BV.geographic.watershed_dem, 
    'D:/Users/abherve/PAPER/Nancon\\results_stable/geographic/surface_area_ratio.tif', 
)

wbt.surface_area_ratio(
    BV.geographic.watershed_dem, 
    'D:/Users/abherve/PAPER/Canut\\results_stable/geographic/surface_area_ratio.tif', 
)

import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False

watershed_names = ['Canut','Nancon']
code_names = ['J7513010','J0014010']

# watershed_names = ['Canut']
# code_names = ['J7513010']

for watershed_name, code_name in zip(watershed_names[:], code_names[:]) :
    
    print('##### '+watershed_name.upper()+' #####')
    
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' 
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)
    
    for mod in mod_list:

        for sce in sce_list:
            
            simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+sce+'*')
            simul = simul_list[0]
    
        
            flow_folder = simul+'/_watershed/_flowpaths/'
            if not os.path.exists(flow_folder):
                toolbox.create_folder(flow_folder)
            
            outflow_paths = glob.glob(simul+'/_watershed/_tifs/'+'outflow'+'*')
            
            for time, path_od_rast in enumerate(outflow_paths):
                print(time)
    
                path_od_pts = flow_folder+'outflow_drain_t('+'x'+').shp'
                path_odtra_rast = flow_folder+'trace_outflow_drain_t('+str(time)+').tif'
                path_direc_rast = stable_folder+'geographic/'+'watershed_buff_direc.tif'
                
                wbt.raster_to_vector_points(
                        path_od_rast, 
                        path_od_pts)
        
                wbt.trace_downslope_flowpaths(
                    path_od_pts, 
                    path_direc_rast, 
                    path_odtra_rast, 
                    esri_pntr=False, 
                    zero_background=False)

#%% ---- QUICK

#%% NOT - EXTRACT RESIDENCE TIMES

watershed_names = ['Canut','Nancon']

for watershed_name in watershed_names[:] :
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = 'k'
    
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)
    
    df = pd.read_csv(BV.calibration_folder+'/'+watershed_name+'_koptims_dichotomy_streams.csv', sep=';')

    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'
    
    figsim_folder = simulations_folder + '_figures/'
    toolbox.create_folder(figsim_folder)
    dem = rasterio.open(BV.geographic.watershed_dem)
    dem_data = dem.read(1)
    
    for mod in mod_list:

        for sce in sce_list:
            
            simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+sce+'*')
            simul = simul_list[0]

            model_name = simul.split('\\')[-1]
            Sy = float(model_name.split('_')[3].split('-')[0]) # %
            K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
            E = float(model_name.split('_')[3].split('-')[2]) # m
            D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
            params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
            Smod_path = simul+'/_watershed/_simulated_results.csv'            
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            # Smod['prop_ratio'] = Smod.intermit_areas / Smod.perenn_areas

            folder_results = simulations_folder + '/' + model_name + '/' + '_watershed/_tifs/'
        
            path_res = folder_results+'residence_times_t(0).tif'
            
            res_time = rasterio.open(path_res)
            res_time_data = res_time.read(1)
            res_time_data = res_time_data
                
            if watershed_name == 'Canut':
                path_obs = stable_folder+'/add_data/'+'recap_terrain.shp'
                path_shp = simulations_folder + '/' + model_name + '/' + '_watershed/_shp/'
                toolbox.create_folder(path_shp)
                path_dat = path_shp+'residence_times_data.shp'

                shp_obs = gpd.read_file(path_obs)
                shp_obs['geometry'] = shp_obs.geometry.buffer(100)
                # shp_obs = shp_obs[['ID_station', 'geometry']]
                shp_obs.to_file(path_dat, encoding='utf-8') # mode a

                # wbt.extract_raster_values_at_points(
                #                 path_res, 
                #                 path_dat, 
                #                 out_text=False)
                
                # Mathod 1
                wbt.raster_to_vector_polygons(
                        path_res, 
                        path_shp+'raster_polygonized.shp')
                raster_polyg = gpd.read_file(path_shp+'raster_polygonized.shp')
                intersect = gpd.overlay(shp_obs, raster_polyg, how='intersection')
                intersect[intersect['VALUE']==-np.inf] = np.nan
                res_dat = gpd.read_file(path_dat)
                res_dat['RES_TIME'] = np.nan
                res_dat['STD_TIME'] = np.nan
            
                for ID in intersect['Site'].unique():
                    # threshold = 1 #year
                    # threshold = threshold*365
                    # threshold = np.log10(threshold)
                    
                    mask = (intersect[intersect['Site']==ID]['VALUE'] !=0)
                    
                    mean_ID = np.nanmean(intersect[intersect['Site']==ID]['VALUE'][mask])
                    res_dat['RES_TIME'][res_dat['Site']==ID] = mean_ID
                    
                    std_ID = np.nanstd(intersect[intersect['Site']==ID]['VALUE'][mask])
                    res_dat['STD_TIME'][res_dat['Site']==ID] = std_ID
                
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
                
                res_dat['RES_TIME'] = (10**(res_dat['RES_TIME']))/365
                res_dat['STD_TIME'] = (10**(res_dat['STD_TIME']))/365
            
            vmin = 0
            vmax = res_time_data.max()
            
            fig, ax = plt.subplots(1,1, figsize=(5,5))
            # plt.imshow(res_time_data)
            # plt.colorbar()
            
            #show(np.ma.masked_where(dem_data < -0, res_time_data), ax=ax, transform=dem.transform, 
            show(np.ma.masked_where(dem_data < -0, (10**res_time_data)/365), ax=ax, transform=dem.transform, 
                 cmap='jet', alpha=1, zorder=2, aspect="auto", vmin=vmin, vmax=vmax)

            if watershed_name=='Canut':
                shp_obs.plot(ax=ax, color=None, marker='o', markersize=10,
                             edgecolor='k', lw=1, zorder=30)
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
    
            if watershed_name=='Canut':
                res_dat['coords'] = res_dat['geometry'].apply(lambda x: x.representative_point().coords[:])
                res_dat['coords'] = [res_dat[0] for res_dat in res_dat['coords']]
                for idx, row in res_dat.iterrows():
                    row['coords'] = (row['coords'][0], row['coords'][1]+100)
                    ax.annotate(s=row['Site'], xy=row['coords'],
                                 horizontalalignment='center')
    
            fig.savefig(figsim_folder+model_name+'.png', dpi=300, bbox_inches='tight')
    
            if watershed_name=='Canut':

                fig, ax = plt.subplots(1,1, figsize=(4,4))
                mean_obs = res_dat[['Tot']].mean(axis=1)
                std_obs = res_dat[['Tot']].std(axis=1)
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
                for i, txt in enumerate(res_dat['Site']):
                    ax.annotate(txt, (x[i], y[i]))
                xn=20
                xx=80
                yn=20
                yx=80
                # ax.set_xlim(xn, xx)
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
                # ax.plot(np.linspace(mint,maxt,50),
                #         np.linspace(mint,maxt,50), 
                #         linestyle='--', color='grey', linewidth=2, zorder=-1)
                
                fig.savefig(figsim_folder+'obs_vs_sim_'+model_name+'.png', dpi=300, bbox_inches='tight')
                
            all_dat = res_dat.copy()
            all_dat[model_name] = res_dat['RES_TIME']
            
all_dat['coords'] = np.nan
all_dat.to_file(simulations_folder+'residence_times_all.shp', sep=';', encoding='utf-8')

#%% NOT - EXTRACT PATHLINES TIMES

watershed_names = ['Canut','Nancon']

for watershed_name in watershed_names[:] :
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = 'k'
    
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)
    
    df = pd.read_csv(BV.calibration_folder+'/'+watershed_name+'_koptims_dichotomy_streams.csv', sep=';')

    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'

    dem = rasterio.open(BV.geographic.watershed_dem)
    dem_data = dem.read(1)

    simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+sce+'*')
    simul = simul_list[0]

    model_name = simul.split('\\')[-1]

    folder_results = simulations_folder + '/' + model_name + '/' + '_watershed/_tifs/'
    
    ##### LOOOP 2D #####
    visu = visualization.Visualization(BV, model_name)
    # visu.visual2D(object_list = ['map','grid', 'watertable', 'watertable_depth','drain_flow','surface_flow','pathlines', 'residence_times'],
                  # color_scale = [(None,None),(0,140),(0,140),(0,2),(None,None),(None,None),(None,None),(None,None)], lines=10000)
    visu.visual2D(object_list = ['pathlines'],
                  color_scale = [(None,None)], lines=1000)

#%% NOT - CROSS SECTION 2D

watershed_names = ['Nancon']
# watershed_names = ['Canut']

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
    river_data = imageio.imread(stable_folder+'/hydrology/'+'complete.tif') # river data
    modflow_display.interactive_cross_section(dem_data, wt_data, river_data, interactive=interactive)

#%% NOT - CROSS CONTROL 1 : FROM FCT

from IPython import get_ipython

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

dem_data = imageio.imread(BV.geographic.watershed_dem)
wt_data = imageio.imread(simulations_folder+model_name+'/_watershed/_tifs/'+'watertable_elevation_t(0).tif')
river_data = imageio.imread(stable_folder+'/hydrology/'+'complete.tif')

# Modules
mpl.rcParams.update(mpl.rcParamsDefault)
get_ipython().run_line_magic('matplotlib', 'qt')

# Figure params
fig, main_ax = plt.subplots(figsize=(5, 5))
# title = plt.suptitle('Interactive cross section head',y=0.98)
divider = make_axes_locatable(main_ax)
top_ax = divider.append_axes("top",1.1, pad=0.2, sharex=main_ax)
right_ax = divider.append_axes("right",1.1, pad=0.2, sharey=main_ax)

# Axis names
top_ax.xaxis.set_tick_params(labelbottom=False)
right_ax.yaxis.set_tick_params(labelleft=False)
main_ax.set_xlabel('X [pixel]')
main_ax.set_ylabel('Y [pixel]')
top_ax.set_ylabel('Z [m]')
right_ax.set_xlabel('Z [m]')

# Dimensions
xvalues = np.linspace(-1,1,dem_data.shape[1])
yvalues = np.linspace(-1,1,dem_data.shape[0])
xx, yy = np.meshgrid(xvalues,yvalues)

# Positions
pos = np.empty(xx.shape + (2,))
pos[:, :, 0] = xx
pos[:, :, 1] = yy

# V and H lines
if interactive == True:
    cur_x = dem_data.shape[1] - 1
    cur_y = dem_data.shape[0] - 1
else:
    cur_x = dem_data.shape[1] /2
    cur_y = dem_data.shape[0] /2

# Data dem
dem_max = dem_data.max()
dem_prof = dem_data.astype(float)
dem_prof[dem_prof<0] = np.nan

# Plot dem
dem_plot = np.ma.masked_array(dem_data, mask=(dem_data<0))
main_ax.imshow(dem_plot, origin='lower', cmap='terrain')

# Plot rivers
try:
    river_plot = np.ma.masked_array(river_data, mask=(river_data<=0))
    main_ax.imshow(river_plot, origin='lower', cmap=mpl.colors.ListedColormap('navy'))
except:
    pass

plt.gca().invert_yaxis()

# Data wt
wt_prof = wt_data.astype(float)
wt_prof[wt_prof<0] = np.nan
# wt_max = wt_data.max()

# Scaling axis
main_ax.autoscale(enable=False)
right_ax.autoscale(enable=False)
top_ax.autoscale(enable=False)
right_ax.set_xlim(right=dem_max)
top_ax.set_ylim(top=dem_max)

# Plot lines
v_line = main_ax.axvline(cur_x, color='k', lw=2)
h_line = main_ax.axhline(cur_y, color='k', lw=2)
# d_line = main_ax.plot((x0,x1),(y0,y1), 'white', '-')

# Plot dem cross-sections
if interactive == True:
    lw = 1.5
else:
    lw = 1

dem_v_plot = dem_prof[:,int(cur_x)]
dem_v_plot[dem_v_plot == 0] = np.nan
dem_v_prof, = right_ax.plot(dem_v_plot,np.arange(xx.shape[0]), c='saddlebrown', lw=lw)

dem_h_plot = dem_prof[int(cur_y),:]
dem_h_plot[dem_h_plot == 0] = np.nan
dem_h_prof, = top_ax.plot(np.arange(xx.shape[1]),dem_h_plot, c='saddlebrown', lw=lw)
# dem_h_prof, = top_ax.plot(x, zi, 'b-')

# # Plot wt cross-sections
if interactive == True:
    lw = 1.5
else:
    lw = 0
    
wt_v_plot = wt_prof[:,int(cur_x)]
wt_v_plot[wt_v_plot == 0] = np.nan
wt_v_prof, = right_ax.plot(wt_v_plot,np.arange(xx.shape[0]), c='dodgerblue', lw=lw)

if interactive != True:
    wt_v_fill = right_ax.fill_betweenx(np.arange(xx.shape[0]), 0, wt_v_plot,
                                       color='deepskyblue', alpha=0.5, lw=0)
    wt_v_fill = right_ax.fill_betweenx(np.arange(xx.shape[0]), wt_v_plot, dem_v_plot,
                                       color='saddlebrown', alpha=0.5, lw=0)

wt_h_plot = wt_prof[int(cur_y),:]
wt_h_plot[wt_h_plot == 0] = np.nan
wt_h_prof, = top_ax.plot(np.arange(xx.shape[1]), wt_h_plot, c='dodgerblue', lw=lw)

if interactive != True:
    wt_h_fill = top_ax.fill_between(np.arange(xx.shape[1]), 0, wt_h_plot,
                                    color='deepskyblue', alpha=0.5, lw=0)
    wt_h_fill = top_ax.fill_between(np.arange(xx.shape[1]), wt_h_plot, dem_h_plot,
                                    color='saddlebrown', alpha=0.5, lw=0)

plt.tight_layout()

# Animation interactive

def on_move_dem(event):
    if event.inaxes is main_ax:       
        cur_x = event.xdata
        cur_y = event.ydata
        dem_v_plot = dem_prof[:,int(cur_x)]
        dem_v_plot[dem_v_plot == 0] = np.nan
        dem_h_plot = dem_prof[int(cur_y),:]
        dem_h_plot[dem_h_plot == 0] = np.nan    
        v_line.set_xdata([cur_x, cur_x])
        h_line.set_ydata([cur_y, cur_y])
        dem_v_prof.set_xdata(dem_v_plot)
        dem_h_prof.set_ydata(dem_h_plot)
        fig.canvas.draw_idle()
        
def on_move_wt(event):
    if event.inaxes is main_ax:       
        cur_x = event.xdata
        cur_y = event.ydata
        wt_v_plot = wt_prof[:,int(cur_x)]
        wt_v_plot[wt_v_plot == 0] = np.nan
        wt_h_plot = wt_prof[int(cur_y),:]
        wt_h_plot[wt_h_plot == 0] = np.nan
        v_line.set_xdata([cur_x, cur_x])
        h_line.set_ydata([cur_y, cur_y])
        wt_v_prof.set_xdata(wt_v_plot)
        wt_h_prof.set_ydata(wt_h_plot)
        wt_v_fill.set_xdata(wt_v_plot)
        wt_h_fill.set_xdata(wt_h_plot)   
        fig.canvas.draw_idle()

def on_close(event):
    get_ipython().run_line_magic('matplotlib', 'inline')

if interactive == True:
    fig.canvas.mpl_connect('motion_notify_event', on_move_dem)
    fig.canvas.mpl_connect('motion_notify_event', on_move_wt)

fig.canvas.mpl_connect('close_event', on_close)

#%% CROSS CONTROL 2 : FROM MAN

typ = 'calibr-t2'

watershed_names = ['Canut','Nancon']
# watershed_names = ['Canut']

# fig, axs = plt.subplots(2, 1, figsize=(5,4), dpi=300)

dates = pd.date_range(start='01/01/1990', end='31/12/2019', freq='M')

for watershed_name in watershed_names[:]:    
    
    # if watershed_name == 'Nancon':
    #     ax = axs[1]
    # if watershed_name == 'Canut':
    #     ax = axs[0]
    
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
        
    wbt.vector_lines_to_raster(stable_folder+'geographic/'+'watershed_contour.shp',
                               stable_folder+'geographic/'+'watershed_contour.tif',
                               base = stable_folder+'geographic/'+'watershed_dem.tif')
    line = imageio.imread(stable_folder+'geographic/'+'watershed_contour.tif')
    line = np.ma.masked_where(line <= 0, line)
        
    mask = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
    
    import itertools            
    
    watertable_elevation = np.load(simulations_folder+model_name+'/_watershed/'+'watertable_elevation'+'.npy', allow_pickle=True).item()
    # acc_npy = np.load(simulations_folder+model_name+'/_watershed/'+'accumulation_flux.npy', allow_pickle=True).item()
    # acc_npy = dict(itertools.islice(acc_npy.items(), 12))

    # for key in acc_npy:
    #     # print(key)
    #     # acc = np.ma.masked_where(dem.read(1) < 0, dem.read(1))
    #     acc_npy[key] = np.ma.masked_array(acc_npy[key], mask=(mask<0))
    # zero = acc_npy[0] * 0
    # for l in range(len(acc_npy)):
    #     tempo = acc_npy[l].copy()
    #     tempo[tempo>0] = 1
    #     zero = zero + tempo
    # days_flux = zero.copy() # / len(acc_npy)

    for key in dict(itertools.islice(watertable_elevation.items(),
                                     len(watertable_elevation)-12*10,
                                     len(watertable_elevation))):
    # for key in watertable_elevation:
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
        cur_y = 40
        
        dem_max = dem_data.max()
        dem_prof = dem_data.astype(float)
        dem_prof[dem_prof<0] = np.nan
        wt_prof = wt_data.astype(float)
        wt_prof[wt_prof<0] = np.nan
        
        # if watershed_name == 'Nancon':
        #     x0, y0 = 50, 40 # These are in _pixel_ coordinates !
        #     x1, y1 = 100, 50
        #     num = int(np.hypot(x1-x0, y1-y0))
        #     num = x1-x0
        #     # num=100
        #     x, y = np.linspace(x0, x1, num), np.linspace(y0, y1, num)
        #     zd = dem_data[y.astype(np.int), x.astype(np.int)]
        #     zw = wt_data[y.astype(np.int), x.astype(np.int)]
        # if watershed_name == 'Canut':
        #     x0, y0 = 60, 20 # These are in _pixel_ coordinates !
        #     x1, y1 = 60, 50
        #     num = int(np.hypot(x1-x0, y1-y0))
        #     num = x1-x0
        #     num=100
        #     x, y = np.linspace(x0, x1, num), np.linspace(y0, y1, num)
        #     zd = dem_data[y.astype(np.int), x.astype(np.int)]
        #     zw = wt_data[y.astype(np.int), x.astype(np.int)]
        
        if watershed_name == 'Nancon':
            dem_h_plot = dem_prof[int(cur_y),:]
            dem_h_plot[dem_h_plot == 0] = np.nan
            wt_h_plot = wt_prof[int(cur_y),:]
            wt_h_plot[wt_h_plot == 0] = np.nan
        if watershed_name == 'Canut':
            dem_v_plot = dem_prof[:,int(cur_x)]
            dem_v_plot[dem_v_plot == 0] = np.nan
            wt_v_plot = wt_prof[:,int(cur_x)]
            wt_v_plot[wt_v_plot == 0] = np.nan
            
        dem_max = dem_data.max()
        dem_prof = dem_data.astype(float)
        dem_prof[dem_prof<0] = np.nan
        dem_plot = np.ma.masked_array(dem_data, mask=(dem_data<0))
        
        wt_prof = wt_data.astype(float)
        wt_prof[wt_prof<0] = np.nan
                
        # fig, ax = plt.subplots(1, 1, figsize=(5,8))
        # # axs = axs.ravel()
        # # ax = axs[0]
        # # ax.autoscale(enable=False)
        # # ax.plot(Rech)
        # # ax = axs[1]
        # # ax.autoscale(enable=False)
        # ax.imshow(dem_plot, origin='lower', cmap='Greys', aspect="equal",)
        # ax.set_ylim(ax.get_ylim()[::-1])
        # # d_line = ax.plot((x0,x1),(y0,y1), 'b-')
        # v_line = ax.axvline(cur_x, color='k', lw=2)
        # h_line = ax.axhline(cur_y, color='k', lw=2)
        
        # if watershed_name == 'Nancon':
        #     d_prof = ax.plot(x, zd, 'r-')
        #     w_prof = ax.plot(x, zw, 'b-')
        # if watershed_name == 'Canut':
        #     d_prof = ax.plot(y, zd, 'r-')
        #     w_prof = ax.plot(y, zw, 'b-')

        # fig, axs = plt.subplots(1, 2, figsize=(8,3), dpi=300)
        # fig, ax = plt.subplots(1, 1, figsize=(6,3), dpi=300)
     
        # import matplotlib.gridspec as gridspec
        # gs = gridspec.GridSpec(1,2, width_ratios=[1], height_ratios=[1,1])
        # fig = plt.figure()
        
        # ax = plt.subplot(gs[0])
        
        # ax = axs[0]
        # # ax.autoscale(enable=False)
        # ax.imshow(dem_plot, origin='lower', cmap='Greys',
        #           aspect="equal")
        # ax.set_ylim(ax.get_ylim()[::-1])
        # # d_line = ax.plot((x0,x1),(y0,y1), 'b-')
        # if watershed_name == 'Canut':
        #     v_line = ax.axvline(cur_x, color='k', lw=2)
        # if watershed_name == 'Nancon':
        #     h_line = ax.axhline(cur_y, color='k', lw=2)
            
        # # acc_npy = np.load(os.path.join(simul, '_watershed','accumulation_flux.npy'), allow_pickle=True).item()
        # inf = 0
        # sup = 12
        # compt = 0
        # step = int(round(len(acc_npy)/12))
        
        # for i in range(step):
        #     print(str(i)+'/'+str(step))
        #     interv = list(acc_npy.items())[inf:sup]
        #     # print(interv)
        #     for l in range(len(interv)):
        #         # key = tupl[0]
        #         # print(key)
        #         interv[l] = np.ma.masked_array(interv[l][1], mask=(mask<0))
                
        #     zero = acc_npy[0] * 0
        #     for j in range(len(interv)):
        #         tempo = interv[j].copy()
        #         tempo[tempo>0] = 1
        #         zero = zero + tempo
        #     days_flux = zero.copy()
        #     days_flux = np.ma.masked_array(days_flux, mask=(mask<0))
        #     days_flux = np.ma.masked_array(days_flux, mask=(days_flux<=0))
            
        #     for k in range(len(interv)):
        #         to = interv[k].copy()
                
        #         # fig, ax = plt.subplots(1,1, figsize=(7,6))
        #         # ax.imshow(to)
                
        #         to[(to>0) & (days_flux==12)] = 2
        #         to[(to>0) & (days_flux<12)] = 1
                
        #         to = np.ma.masked_array(to, mask=(mask<0))
        #         to = np.ma.masked_array(to, mask=(to<=0))
                
        #         # fig, ax = plt.subplots(1,1, figsize=(7,6))
        #         # image_hidden = ax.imshow(np.ma.masked_where(mask<0, mask), cmap='Greys')
        #         ax.imshow(np.ma.masked_where(mask<0, mask), cmap='Greys', alpha=0.5, zorder=0)
        #         ax.imshow(np.ma.masked_where(to==1, to),
        #                   cmap = mpl.colors.ListedColormap(['dodgerblue']))
        #         ax.imshow(np.ma.masked_where(to==2, to),
        #                   cmap = mpl.colors.ListedColormap(['darkorange']))
        #         ax.imshow(line, cmap=mpl.colors.ListedColormap('k'))
        #         ax.get_xaxis().set_visible(False)
        #         ax.get_yaxis().set_visible(False)
                
        #         # ax.set_title(str(years[i])+'-'+(str(k+1)))
                
        #         # plt.close()
                
        #         # hydromet = gpd.read_file(BV.hydrometry.hydrometric_clip)
        #         # ax.plot(65, 45, zorder=7, marker='o', color='yellow', 
        #         #         markersize=5, lw=1)

        #         # intermit = gpd.read_file(BV.intermittency.onde_clip)
        #         # ax.plot(color='yellow', zorder=8, marker='s',markersize=5,
        #         #                       edgecolor='black', lw=1)

        #         compt += 1
                
        #     inf+=12
        #     sup+=12
    
        # x1,x2 = ax.get_xlim()
        # y1,y2 = ax.get_ylim()
        # xRange = abs(x2-x1)
        # yRange = abs(y2-y1)

        # ax = plt.subplot(gs[1])
        # ax = axs[1]
        # ax.autoscale(enable=False)
        
        fig, ax = plt.subplots(1, 1, figsize=(5,3), dpi=300)
    
        if watershed_name == 'Nancon':
            # dem_h_prof, = ax.plot(np.arange(xx.shape[1])*75,dem_h_plot, c='saddlebrown', lw=2)
            # wt_h_prof, = ax.plot(np.arange(xx.shape[1])*75, wt_h_plot, c='dodgerblue', lw=2)
            wt_h_fill = ax.fill_between(np.arange(xx.shape[1])*75, 0, wt_h_plot,
                                            color='deepskyblue', alpha=0.5, lw=0)
            wt_h_fill = ax.fill_between(np.arange(xx.shape[1])*75, wt_h_plot, dem_h_plot,
                                            color='saddlebrown', alpha=0.5, lw=0)
            ax.set_xlim(4000, 7000)
            ax.set_ylim(130, 170)
            ax.set_yticks([140,160])
        if watershed_name == 'Canut':
            # dem_v_prof, = ax.plot(np.arange(xx.shape[0])*75, dem_v_plot, c='saddlebrown', lw=2)
            # wt_v_prof, = ax.plot(np.arange(xx.shape[0])*75, wt_v_plot, c='dodgerblue', lw=2)
            wt_v_fill = ax.fill_between(np.arange(xx.shape[0])*75, 0, wt_v_plot,
                                                color='deepskyblue', alpha=0.5, lw=0)
            wt_v_fill = ax.fill_between(np.arange(xx.shape[0])*75, wt_v_plot, dem_v_plot,
                                                color='saddlebrown', alpha=0.5, lw=0)
            ax.set_xlim(1000, 4000)
            ax.set_ylim(90, 130)
            ax.set_yticks([100,120])
        
        # ax.set_aspect(xRange/yRange)
        # asp = np.diff(ax.get_xlim())[0] / np.diff(ax.get_ylim())[0]
        # ax.set_aspect(asp)
        
        ax.set_title(str(dates[key])[:7])
        
        plt.tight_layout()
        
        fig.savefig(simulations_folder+model_name+'/_figures/'+'cross_'+str(key)+'.png', dpi=300, bbox_inches='tight')

        # plt.plot(dem_h_plot)
        # plt.plot(wt_h_plot)

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

    begin_by = simulations_folder+model_name+'/_figures/'+'cross_'
    filenames = sorted(glob.glob(begin_by+'*.png'), key=os.path.getmtime)
    images = []
    for filename in filenames:
        images.append(imageio.imread(filename))
    imageio.mimsave(simulations_folder+model_name+'/_figures/'+'_GIF_cross_'+'.gif', images, duration=0.5, loop=0)

#%% NOT : MAPS TOP VIEW STEADY

# watershed_names = ['Nancon']
watershed_names = ['Canut']

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
    
    # visu.visual2D(object_list = ['pathlines', 'residence_times'],
    #               color_scale = [(None,None),(None,None)], 
    #               lines=100)

#%% ---- RESPONSE

#%% DATA FLOWPATHS FOR L2

hydrology_path = data_path + 'HYDROLOGY/France/Hydrographic/D035/' # add hydrographic shapefiles

watershed_names = ['Canut','Nancon']
code_names = ['J7513010','J0014010']

# watershed_names = ['Canut']
# code_names = ['J7513010']

types_obs = ['complete','intermittent','perennial','river','zh_couesnon','zh_meuchezecanut'] # list of shapefile name layers for clip hydrology
fields_obs = ['persistanc','fid','fid','fid','fid','fid']

df = pd.DataFrame(np.nan, index=range(1), columns=types_obs)

c = ['forestgreen','orchid']
dict_c = dict(zip(watershed_names, c))

# typ = 'calibr-t6'

# mod_list = ['REA']

sce_list = ['historic']

from watershed import watershed_root, watershed_display, forcing
from matplotlib_scalebar.scalebar import ScaleBar
from rasterio.plot import show

fig, ax = plt.subplots(1,1, figsize=(5,5))

for watershed_name, code_name in zip(watershed_names[:], code_names[:]) :
       
    print('##### '+watershed_name.upper()+' #####')
    
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)
    
    # BV.add_hydrology(hydrology_path, types_obs=['intermittent'], fields_obs=['fid'])

    bv = gpd.read_file(BV.geographic.watershed_shp)
    area = BV.geographic.area
    area = round(area, 1)
    
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    
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

    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = 'k'
        
    for mod in mod_list:
        
        # fig1, axs1 = plt.subplots(1,1, figsize=(5,5))
        # xn = 0.1
        # xx = 100
        # yn = 0.1
        # yx = 100
        # ax = axs1
        # ax.set_title(mod)
        # ax.set_aspect('equal', adjustable='box')

        for sce in sce_list:
            
            simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+sce+'*')
            simul = simul_list[0]
            
            # if sce == 'historic':
            #     simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+'RCP8.5'+'*')
            #     simul = simul_list[0]
                
            model_name = simul.split('\\')[-1]
            Sy = float(model_name.split('_')[3].split('-')[0]) # %
            K = float(model_name.split('_')[3].split('-')[1]) / 24 / 3600 # m/s
            E = float(model_name.split('_')[3].split('-')[2]) # m
            D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
            params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
            Smod_path = simul+'/_watershed/_simulated_results.csv'            
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            Smod_path_bis = simul+'/_watershed/_simulated_results_bis.csv'
            Smod.to_csv(Smod_path_bis, sep=';')
            Smod = pd.read_csv(Smod_path_bis, sep=';', index_col=0, parse_dates=True)
            Smod['prop_ratio'] = Smod.intermit_areas / Smod.perenn_areas
            Smod = select_period(Smod, 1960, 2019)

            wt_npy = np.load(os.path.join(simul, '_watershed','watertable_elevation.npy'), allow_pickle=True).item()
            # wt_path = os.path.join(simul, '_watershed/_tifs/','watertable_elevation_t(0).tif')
           
            for i in range(len(wt_npy)):
                print(i+1, len(wt_npy))
                
                wt_path = os.path.join(simul, '_watershed/_tifs/','watertable_elevation_t('+str(i)+').tif')
                if not os.path.exists(wt_path):
                    toolbox.export_tif(BV.geographic.watershed_dem, wt_npy[i], -9999, 
                                        wt_path)
                
                wt_fill_path = os.path.join(simul, '_watershed/_tifs/','watertable_fill_elevation_t('+str(i)+').tif')
                if not os.path.exists(wt_fill_path):
                    wbt.fill_depressions(wt_path, wt_fill_path)

                # DEM down outlet
                d_dem_outlet = os.path.join(simul, '_watershed/_tifs/','downslope_dem_outlet_t('+str(i)+').tif')
                if not os.path.exists(d_dem_outlet):
                    output = os.path.join(simul, '_watershed/_tifs/','d8pointer_dem_outlet_t(x).tif')
                    wbt.d8_pointer(
                            BV.geographic.watershed_buff_fill, 
                            output)
                    wbt.downslope_flowpath_length(
                        output, 
                        d_dem_outlet)
                
                # DEM down stream
                d_dem_stream = os.path.join(simul, '_watershed/_tifs/','downslope_dem_stream_t('+str(i)+').tif')
                if not os.path.exists(d_dem_stream):
                    streams = os.path.join(simul, '_watershed/_tifs/','accumulation_flux_t('+str(i)+').tif')                
                    wbt.downslope_distance_to_stream(
                            BV.geographic.watershed_buff_fill, 
                            streams, 
                            d_dem_stream, 
                            dinf=False, 
                        )
                
                # WR down outlet
                d_wt_outlet = os.path.join(simul, '_watershed/_tifs/','downslope_wt_outlet_t('+str(i)+').tif')
                if not os.path.exists(d_wt_outlet):
                    output = os.path.join(simul, '_watershed/_tifs/','d8pointer_wt_outlet_t(x).tif')
                    wbt.d8_pointer(
                            wt_path, 
                            output)
                    wbt.downslope_flowpath_length(
                        output, 
                        d_wt_outlet)
                
                # WT down stream
                d_wt_stream = os.path.join(simul, '_watershed/_tifs/','downslope_wt_stream_t('+str(i)+').tif')
                if not os.path.exists(d_wt_stream):
                    streams = os.path.join(simul, '_watershed/_tifs/','accumulation_flux_t('+str(i)+').tif')                
                    wbt.downslope_distance_to_stream(
                            wt_path, 
                            streams, 
                            d_wt_stream, 
                            dinf=False, 
                        )
        
                # WT fill down stream
                d_wt_fill_stream = os.path.join(simul, '_watershed/_tifs/','downslope_wt_fill_stream_t('+str(i)+').tif')
                if not os.path.exists(d_wt_fill_stream):
                    streams = os.path.join(simul, '_watershed/_tifs/','accumulation_flux_t('+str(i)+').tif')                
                    wbt.downslope_distance_to_stream(
                            wt_fill_path, 
                            streams, 
                            d_wt_fill_stream, 
                            dinf=False, 
                        )
                
                dem = imageio.imread(BV.geographic.watershed_dem)
                
                # DEM outlet
                flow_dem = imageio.imread(d_dem_outlet)
                flow_dem[flow_dem<0] = np.nan
                flow_dem = np.nan_to_num(flow_dem, nan=np.nan, posinf=np.nan)
                mean_flow_dem = np.nanmean(np.ma.masked_where(dem < 0, flow_dem))
                median_flow_dem = np.nanmedian(np.ma.masked_where(dem[~np.isnan(flow_dem)] < 0, flow_dem[~np.isnan(flow_dem)]))
                # Smod.loc[Smod.index[i], 'L_dem_mean_out'] = mean_flow_dem
                Smod.loc[Smod.index[i], 'L_dem_median_out'] = median_flow_dem
                
                # DEM stream
                flow_dem = imageio.imread(d_dem_stream)
                flow_dem[flow_dem<0] = np.nan
                mean_flow_dem = np.nanmean(np.ma.masked_where(dem < 0, flow_dem))
                median_flow_dem = np.nanmedian(np.ma.masked_where(dem < 0, flow_dem))
                # Smod.loc[Smod.index[i], 'L_dem_mean_str'] = mean_flow_dem
                Smod.loc[Smod.index[i], 'L_dem_median_str'] = median_flow_dem
                
                # Rectangle technique complete
                l_stream = complete.length.sum()
                mean_rect_dem = (area * 1e6) / (2 * l_stream)           
                Smod.loc[Smod.index[i], 'L_dem_complete'] = mean_rect_dem
                
                # WT outlet
                flow_wt = imageio.imread(d_wt_outlet)
                flow_wt[flow_wt<0] = np.nan
                mean_flow_wt = np.nanmean(np.ma.masked_where(dem < 0, flow_wt))
                median_flow_wt = np.nanmedian(np.ma.masked_where(dem < 0, flow_wt))
                # Smod.loc[Smod.index[i], 'L_wt_mean_out'] = mean_flow_wt
                Smod.loc[Smod.index[i], 'L_wt_median_out'] = median_flow_wt
                
                # WT stream
                flow_wt = imageio.imread(d_wt_stream)
                flow_wt[flow_wt<0] = np.nan
                mean_flow_wt = np.nanmean(np.ma.masked_where(dem < 0, flow_wt))
                median_flow_wt = np.nanmedian(np.ma.masked_where(dem < 0, flow_wt))
                # Smod.loc[Smod.index[i], 'L_wt_mean_str'] = mean_flow_wt
                Smod.loc[Smod.index[i], 'L_wt_median_str'] = median_flow_wt
                
                # WT stream fill
                try:
                    flow_wt = imageio.imread(d_wt_fill_stream)
                    flow_wt[flow_wt<0] = np.nan
                    mean_flow_wt = np.nanmean(np.ma.masked_where(dem < 0, flow_wt))
                    median_flow_wt = np.nanmedian(np.ma.masked_where(dem < 0, flow_wt))
                    # Smod.loc[Smod.index[i], 'L_wt_mean_str'] = mean_flow_wt
                    Smod.loc[Smod.index[i], 'L_wt_fill_median_str'] = median_flow_wt
                except:
                    Smod.loc[Smod.index[i], 'L_wt_fill_median_str'] = np.nan
                    pass
                    
                # WT tau
                dem_data = imageio.imread(BV.geographic.watershed_dem)
                wt_elev = imageio.imread(wt_path)
                wt_ep = ( wt_elev - (dem_data-E) )
                tsat = np.nanmean(np.ma.masked_where(dem_data < 0, wt_ep))
                tau = ((median_flow_wt**2) * (Sy/100)) / ((K * 3600 * 24) * tsat)                
                Smod.loc[Smod.index[i], 'tau_L_wt_median_str'] = tau
                
            # ax.plot(Smod['tau'], Smod['seepage_areas'], marker='o', color=dict_c[watershed_name], lw=0)
          
    Smod.to_csv(Smod_path_bis, sep=';')

# plt.plot(Smod['recharge'],Smod['tau'])
# plt.plot()

fig, ax = plt.subplots(1,1, figsize=(3,3))
ax.scatter(Smod['L_dem_median_str'],Smod['L_wt_median_str'],
           c=Smod.index.month, ec='none')
ax.plot((ax.get_xlim()[0], ax.get_xlim()[1]), (ax.get_ylim()[0], ax.get_ylim()[1]), c='k')

#%% MIX RELATIONS

from scipy.stats import binned_statistic

typ = 'calibr-t3'

# Things
time_step = 'M'
sim_state = 'transient'
var = 'REC'
# scan = 'outflow_drain'
scan = 'seepage_areas'

# Colored
mod_list = ['REA']
sce_list = ['historic']
sce_cmap = ["Greys"]
sce_color = ["k"]
cmap_dict = dict(zip(sce_list, sce_cmap))
color_dict = dict(zip(sce_list, sce_color))

c = ['forestgreen','orchid']
dict_c = dict(zip(watershed_names, c))

# Hysteres
temporal = False
space = 0
norm = False

watershed_names = ['Canut','Nancon']

# x_name = 'outflow_drain'
x_name = 'recharge'
y_name = 'surflow_areas'
# y_name = 'intermit_areas'
# y_name = 'prop_ratio'
# y_name = 'perenn_areas'
# y_name = 'outflow_drain'
xmin = []
xmax = []
ymin = []
ymax = []

fig, axs = plt.subplots(1,4, figsize=(14,3))
axs = axs.ravel()
fig3, axs3 = plt.subplots(1,4, figsize=(14,3))
axs3 = axs3.ravel()

xy_list = [['recharge','surflow_areas'],
           ['outflow_drain','prop_ratio'],
           ['groundwater_storage','outflow_drain'],
           ['tau','surflow_areas']]

for watershed_name in watershed_names :
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = 'k'
        
    for mod in mod_list:
        
        # fig1, axs1 = plt.subplots(1,1, figsize=(5,5))
        # xn = 0.1
        # xx = 100
        # yn = 0.1
        # yx = 100
        # ax = axs1
        # ax.set_title(mod)
        # ax.set_aspect('equal', adjustable='box')

        for sce in sce_list:
            
            simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+sce+'*')
            simul = simul_list[0]
            
            # if sce == 'historic':
            #     simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+'RCP8.5'+'*')
            #     simul = simul_list[0]
                
            model_name = simul.split('\\')[-1]
            Sy = float(model_name.split('_')[3].split('-')[0]) # %
            K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
            E = float(model_name.split('_')[3].split('-')[2]) # m
            D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
            params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
            Smod_path = simul+'/_watershed/_simulated_results.csv'            
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            Smod['prop_ratio'] = Smod.intermit_areas / Smod.perenn_areas
            
            Smod = select_period(Smod, 1960, 2019)
            Smod['groundwater_storage'] = Smod['groundwater_storage']/(Smod['groundwater_storage'].mean())

            Qmod = Smod[scan] 
          
            Qmod = Qmod # mm/months
            Qmod = Qmod.squeeze()    
            Cmod = Smod['recharge'] # mm/months
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
            
            hyst = Hysteresis(DFmod, watershed_name)
            hyst.prepare_xy_raw()
            hyst.compute_xy_metrics(temporal=temporal, space=space, norm=norm)
            
            columns_x = hyst.xrecapl.columns
            columns_y = hyst.yrecapl.columns
            
            n = len(columns_x)
            cmap = cmap_dict[sce]
            cmap_color = plt.get_cmap(cmap)(np.linspace(0, 1, n))
            color = color_dict[sce]
                        
            print('area='+str(hyst.area))
            print('slope='+str(hyst.slope))
            print('hi='+str(hyst.hi))
            print('q0='+str(hyst.q0))
            
            cpax = 0
            
            for xy in xy_list:
                
                # print(compt)
            
                ###############################################################

                ax = axs[cpax]

                x = Smod[xy[0]]  #*1000
                y = Smod[xy[1]]
                c = Smod.index.month
                wy = pd.Series(x.index.month).replace([10,11,12,1,2,3,4,5,6,7,8,9],
                                                        [1,2,3,4,5,6,7,8,9,10,11,12])
                
                ax.set_xscale('log')
                ax.set_yscale('log')
                # ax.set_xlabel('$Q_{sim}$ [mm/month]')
                # ax.set_ylabel('$A_{intermitent}$ / $A_{perennial}$ [-]')
                ax.set_xlabel(xy[0])
                ax.set_ylabel(xy[1])
                # ax.set_xlim(0.5, 1.5)
                # ax.set_ylim(0, 15)

                xi = x.groupby([lambda x: x.month]).mean()
                yi = y.groupby([lambda y: y.month]).mean()
                
                cmapping = mpl.colors.ListedColormap(dict_c[watershed_name])
                scat = ax.scatter(x, y, c=wy, cmap=cmapping, marker="o", 
                                  s=10, vmin=1, vmax=12, alpha=0.75, ec='none', zorder=-1)
                
                xiline = xi.append(xi.iloc[[0]])
                xiline.index = np.arange(1,14,1)
                yiline = yi.append(yi.iloc[[0]])
                yiline.index = np.arange(1,14,1)
                ax.plot(xiline, yiline, linestyle = '-', lw=1.5, color='k', zorder=0)
    
                wyi = np.arange(1,12+1,1)
                compt = 2
                for k in wyi:
                    ax.annotate(k,(xi[k],yi[k]), family='sans-serif', fontsize=5, 
                                 color='black', weight="bold", ha='center', va='center',
                                 zorder=compt)
                    ax.plot(xi[k], yi[k], marker="o", lw=2, markersize=9, markeredgecolor='black', 
                               markerfacecolor='white', markeredgewidth=1,
                               linestyle = 'None', zorder=compt)
                    compt+=1
    
                xe = pd.DataFrame()
                xe['q25'] = (x.groupby(x.index.month).quantile(0.25))
                xe['q75'] = (x.groupby(x.index.month).quantile(0.75))
        
                ye = pd.DataFrame()
                ye['q25'] = (y.groupby(y.index.month).quantile(0.25))
                ye['q75'] = (y.groupby(y.index.month).quantile(0.75))
                
                # ax.errorbar(xi, yi,
                #              yerr=np.vstack([yi-ye.q25, ye.q75-yi]),
                #              xerr=np.vstack([xi-xe.q25, xe.q75-xi]),
                #              ecolor = 'black', fmt = 'none', capsize = 1, elinewidth=0.5, 
                #              capthick=0.5, zorder=1)
                
                y[y==0] = 0.001
                # x = np.log(x)
                # y = np.log(y)
                maxim = max(max(x),max(y))
                minim = min(min(x),np.nanmin(y[y != -np.inf]))
                s, edges, _ = binned_statistic(x, y, statistic='mean',
                                               bins=np.geomspace(minim,maxim,25))
                the_x = edges[:-1]+np.diff(edges)/2
                the_y = s.copy()
                # ax.scatter(the_x, the_y, c="white", zorder=3)  
                
                ###############################################################
                
                ax3 = axs3[cpax]
                
                x = (Smod[xy[0]]).diff() #/ 1e6 # *1000
                y = Smod[xy[1]].diff()
                
                c = Smod.index.month
                wy = pd.Series(x.index.month).replace([10,11,12,1,2,3,4,5,6,7,8,9],
                                                        [1,2,3,4,5,6,7,8,9,10,11,12])
    
                xi = x.groupby([lambda x: x.month]).mean()
                yi = y.groupby([lambda y: y.month]).mean()
                
                xiline = xi.append(xi.iloc[[0]])
                xiline.index = np.arange(1,14,1)
                yiline = yi.append(yi.iloc[[0]])
                yiline.index = np.arange(1,14,1)
                
                
                # year = 2018
                # spe_year_x = select_period(x, year, year)
                # spe_year_y = select_period(y, year, year)
                # xiline_spe = spe_year_x.append(spe_year_x.iloc[[0]])
                # xiline_spe.index = np.arange(1,14,1)
                # yiline_spe = spe_year_y.append(spe_year_y.iloc[[0]])
                # yiline_spe.index = np.arange(1,14,1)
                # ax3.plot(xiline_spe, yiline_spe, linestyle = '-', lw=1.5, color='red', zorder=0)

                # cmapping = 'jet'
                cmapping = mpl.colors.ListedColormap(dict_c[watershed_name])
                ax3.scatter((x) , (y), c=wy, marker='o', cmap=cmapping,
                            s=10, vmin=1, vmax=12, alpha=0.75, ec='none', lw=0.2, zorder=-1)
                
                xi = xiline.diff()
                xi.iloc[0] = xi.iloc[-1]
                xi = xi[:-1]
                yi = yiline.diff()
                yi.iloc[0] = yi.iloc[-1]
                yi = yi[:-1]
                              
                wyi = np.arange(1,12+1,1)
                wyi = pd.Series(wyi).replace([10,11,12,1,2,3,4,5,6,7,8,9],
                                             [1,2,3,4,5,6,7,8,9,10,11,12])
                
                # ax3.scatter(xi, yi, c=wyi, marker='o', cmap=cmapping,
                #             s=35, vmin=1, vmax=12, alpha=1, 
                #             ec='k', lw = 0.5)
    
                cl = mpl.cm.jet(np.linspace(0,1,len(wyi)))
                compt = 2
                wyi = np.arange(1,12+1,1)
                # for k in wyi:
                #     ax3.annotate(k,(xi[k],yi[k]), family='sans-serif',
                #                  fontsize=5, 
                #                   color='black', weight="bold", ha='center', va='center',
                #                   zorder=compt)
                #     ax3.plot(xi[k], yi[k], marker=mark, lw=2, markersize=9,
                #               markeredgecolor='black', 
                #                 markerfacecolor='white', markeredgewidth=1,
                #                 linestyle = 'None', zorder=compt) # cl[k-1]
                #     compt+=1
                
                ax3.grid(zorder=-1000)
                
                ax3.axhline(y=0, color='k', zorder=-1)
                ax3.axvline(x=0, color='k', zorder=-1)
                # ax3.set_xlim(-0.3, 0.7)
                # ax3.set_ylim(-7, 8)
                
                # ax3.set_xlabel('\u0394GW storage [?]')
                # ax3.set_ylabel('\u0394$A_{sat}$ [%]')
                ax3.set_xlabel(xy[0])
                ax3.set_ylabel(xy[1])
                
                # ax3.set_xticks(np.arange(-2, 2 + 0.1, 1))
                # ax3.set_yticks(np.arange(-4, 4 + 0.1, 2))
                          
                dfevol = hyst.dfmet.iloc[:-1]
                dfevol = dfevol.set_index(pd.to_datetime(dfevol.index, format='%Y'))
                
                # fig, ax = plt.subplots(1,1)
                # axb=ax.twinx()
                # ax.plot(Smod.recharge, Smod.tau,c='b')
                # axb.plot(, c='r')
                
                cpax+=1
      
fig.tight_layout()
# fig3.tight_layout()
            
#%% DELTA TIME EVOLUTION 

from scipy.stats import binned_statistic

typ = 'calibr-t3'

# Things
time_step = 'M'
sim_state = 'transient'
var = 'REC'

scan = 'outflow_drain'

# Colored
mod_list = ['REA']
sce_list = ['historic']
sce_cmap = ["Greys"]
sce_color = ["k"]
cmap_dict = dict(zip(sce_list, sce_cmap))
color_dict = dict(zip(sce_list, sce_color))

c = ['grey','tomato']
dict_c = dict(zip(watershed_names, c))

# Hysteres
temporal = False
space = 0
norm = False

watershed_names = ['Canut','Nancon']

# fig, axs = plt.subplots(1,4, figsize=(14,3))
# axs = axs.ravel()
# fig3, axs3 = plt.subplots(1,4, figsize=(14,3))
# axs3 = axs3.ravel()

xy_list = [['outflow_drain','surflow_areas']]

fig, ax = plt.subplots(1,1, figsize=(7,4))
# axs = axs.ravel()
axb=ax.twinx()

for watershed_name in watershed_names :
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = 'k'
    
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)
    
    # BV.add_hydrology(hydrology_path, types_obs=['intermittent'], fields_obs=['fid'])

    area = BV.geographic.area
    
    for mod in mod_list:
        
        # fig1, axs1 = plt.subplots(1,1, figsize=(5,5))
        # xn = 0.1
        # xx = 100
        # yn = 0.1
        # yx = 100
        # ax = axs1
        # ax.set_title(mod)
        # ax.set_aspect('equal', adjustable='box')

        for sce in sce_list:
            
            simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+sce+'*')
            simul = simul_list[0]
            
            # if sce == 'historic':
            #     simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+'RCP8.5'+'*')
            #     simul = simul_list[0]
                
            model_name = simul.split('\\')[-1]
            Sy = float(model_name.split('_')[3].split('-')[0]) # %
            K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
            E = float(model_name.split('_')[3].split('-')[2]) # m
            D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
            params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
            Smod_path = simul+'/_watershed/_simulated_results.csv'            
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            Smod['prop_ratio'] = Smod.intermit_areas / Smod.perenn_areas
            
            Smod = select_period(Smod, 1960, 2019)
            # Smod['groundwater_storage'] = Smod['groundwater_storage']/(Smod['groundwater_storage'].mean())
            # Smod['groundwater_storage'] = Smod['groundwater_storage']
            Smod['groundwater_storage'] = Smod['groundwater_storage'] / (area * 1e6)

            Qmod = Smod[scan] 
          
            Qmod = Qmod # mm/months
            Qmod = Qmod.squeeze()    
            Cmod = Smod['recharge'] # mm/months
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
            
            hyst = Hysteresis(DFmod, watershed_name)
            hyst.prepare_xy_raw()
            hyst.compute_xy_metrics(temporal=temporal, space=space, norm=norm)
            
            columns_x = hyst.xrecapl.columns
            columns_y = hyst.yrecapl.columns
            
            n = len(columns_x)
            cmap = cmap_dict[sce]
            cmap_color = plt.get_cmap(cmap)(np.linspace(0, 1, n))
            color = color_dict[sce]
                        
            print('area='+str(hyst.area))
            print('slope='+str(hyst.slope))
            print('hi='+str(hyst.hi))
            print('q0='+str(hyst.q0))
            
            dfevol = hyst.dfmet.iloc[:-1]
            dfevol = dfevol.set_index(pd.to_datetime(dfevol.index, format='%Y'))
            
            cpax = 0
            
            for cp, xy in enumerate(xy_list):
                                
                print(cpax)
            
                ###############################################################
                ax = ax
                # Smod = select_period(Smod, 1998, 2001)
                Smod['diff_0'] = (Smod[xy[0]].diff())
                Smod['diff_1'] = (Smod[xy[1]].diff())
                # y =  (Smod['diff_0'] - Smod['diff_1'])
                # y = Smod[xy[1]]
                print(y.median())
                
                # ax.plot(y, c=dict_c[watershed_name], marker='o', ms=2)
                # ax.plot(Smod['diff_0'], c=dict_c[watershed_name], marker='o', ms=2, ls='-')
                ax.plot(Smod['diff_1'], c=dict_c[watershed_name], marker='o', ms=2, ls='--')
                # ax.set_ylim(None, 1000)
      
fig.tight_layout()
# fig3.tight_layout()

#%% ---- FIGURES

#%% 1 - STUDY SITE

hydrology_path = data_path + 'HYDROLOGY/France/Hydrographic/D035/' # add hydrographic shapefiles

watershed_names = ['Canut','Nancon']
code_names = ['J7513010','J0014010']

# watershed_names = ['Canut']
# code_names = ['J7513010']

types_obs = ['complete','intermittent','perennial','river','zh_couesnon','zh_meuchezecanut'] # list of shapefile name layers for clip hydrology
fields_obs = ['persistanc','fid','fid','fid','fid','fid']

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
    
    # BV.add_hydrology(hydrology_path, types_obs=['intermittent'], fields_obs=['fid'])

    bv = gpd.read_file(BV.geographic.watershed_shp)
    area = BV.geographic.area
    area = round(area, 1)
    
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    
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
    
    print(area_perennial)
    print(area_complete)
    
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
    cmap = 'Greys'
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
    
    zh.plot(ax=ax, lw=0, color='navy', alpha=1, zorder=4, legend=True, label='Wetlands')

    streams = complete.copy()
    streams[streams.persistanc=='Permanent'].plot(ax=ax, lw=2, color='dodgerblue',
                                                  zorder=6,legend=True, label='Streams')
    streams[streams.persistanc=='Intermittent'].plot(ax=ax, lw=1.5, color='darkorange', ls='-',
                                                  zorder=5,legend=True, label='Streams')
    contour.plot(ax=ax, lw=1.5, color='k', zorder=4,legend=True, label='Watershed')
    # try:
    #     if os.path.exists(BV.piezometry.piezos_shp):
    #         piezos = gpd.read_file(BV.piezometry.piezos_shp)
    #         piezos.plot(ax=ax, color='blue', marker='^', zorder=6, 
    #                     edgecolor='k', lw=1, legend=True, label='Piezometers: continue')
    # except:
    #     pass
    # try:
    #     if len(BV.piezometry.x_coord_discrete)>0:
    #         ax.scatter(BV.piezometry.x_coord_discrete, BV.piezometry.y_coord_discrete,
    #                    c='forestgreen',
    #                    marker='^', zorder=5, label='Piezometers: discrete')
    # except:
    #     pass   
    # try:
    #     if os.path.exists(BV.hydrometry.hydrometric_clip):
    #         hydromet = gpd.read_file(BV.hydrometry.hydrometric_clip)
    #         hydromet.plot(ax=ax, color='yellow', zorder=7, marker='o', markersize=70,
    #                       edgecolor='k', lw=1, legend=True, label='Hydrometric: continue')
    # except:
    #     pass 
    # try:
    #     if os.path.exists(BV.intermittency.onde_clip):
    #         intermit = gpd.read_file(BV.intermittency.onde_clip)
    #         intermit.plot(ax=ax, color='yellow', zorder=8, marker='s',markersize=50,
    #                       edgecolor='black', lw=1, legend=True, label='Intermittency: discrete')
    # except:
    #     pass
    
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
    
    '''
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
    '''
    
    path_sub = glob.glob(stable_folder+'subbasin/' + '/intermittency*')[0] + '/watershed.shp'
    sub = gpd.read_file(path_sub)
    # sub.plot(ax=ax, facecolor='none', edgecolor='k', lw=2,
    #          ls=':', zorder=6)
    
    # if watershed_name == 'Canut':
    #     ofb = gpd.read_file('D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/2_data/Hydrology/INTERMITTENCE/Chèze-Canut/OFB_Observations_Canut_2018-2019.shp')
    #     ofb = ofb.drop([46,47,48])
    #     ofb.plot(ax=ax, color='yellow', zorder=6, marker='d', markersize=20,
    #                   edgecolor='k', lw=1, legend=True, label='Hydrometric: continue')
    
    fig.tight_layout()
    base_name = figsim_folder+'fig01/'
    spec_name = watershed_name+'_hydromapping'
    fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight')

#%% 2 - OBSERVED DISCHARGE

watershed_names = ['Canut','Nancon']
code_names = ['J7513010','J0014010']

first = 1990
last = 2019
one = 2001

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
    
    fig, ax = plt.subplots(figsize=(4.5,4))
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
    ax.set_ylim(0.01,100)
    ax.tick_params(axis='both', which='major', pad=10)
    x1 = np.linspace(0,366,13)
    squad = ['J','F','M','A','M','J','J','A','S','O','N','D','J']
    ax.set_xticks(x1)
    ax.set_xticklabels(squad, minor=False, rotation='horizontal')
    ax.set_xlabel('Months', labelpad=+10)
    ax.set_ylabel('Q / A [mm/day]',labelpad=+10)
    # ax.set_title(watershed_name + ' [' + str(first) + ' to ' + str(last) + ']')
    # ax.grid(color='grey', lw=0.5, zorder=0)
    # dates = np.array([one],dtype=np.int64)
    # colors = ['blue']
    # for z in np.array(range(len(dates))):
    #     onlyone = data_index[(data_index.index.year==dates[z])].to_frame()
    #     onlyone = onlyone.groupby([onlyone.index.month,
    #                                onlyone.index.day], as_index=True).mean()
    #     onlyone['counts'] = np.array(range(1,len(onlyone)+1))
    #     ax.plot(onlyone.counts, onlyone['Q'],
    #             color=colors[z], lw=1, label = str(dates[z]))
    # ax.legend(loc='upper left')
    plt.tight_layout()
    # fig.savefig(path + 'plot_figures/' + site + '/' + 'regime' + '.png', dpi=300, bbox_inches='tight')
    
    base_name = figsim_folder+'fig02/'
    spec_name = watershed_name+'_intermensual'
    fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight')

#%% 2 - OBSERVED HYSTERESIS

watershed_names = ['Canut','Nancon']
code_names = ['J7513010','J0014010']

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

# series_path = out_path + '_data/' +'export_hydro_series.csv'
# series = pd.read_csv(series_path, sep=';', index_col = 4, parse_dates= True)
# series = series.iloc[1:]
# series.index.name = None
# series.index = pd.to_datetime(series.index)
# series['<ResObsElaborHydro>'] = pd.to_numeric(series['<ResObsElaborHydro>'])

for watershed_name, code_name in zip(watershed_names[:], code_names[:]) :
       
    # if watershed_name == 'Gael':
    #     series_path = out_path + '_data/' +'export_hydro_series_gael.csv'
    #     series = pd.read_csv(series_path, sep=';', index_col = 4, parse_dates= True)
    #     series = series.iloc[1:]
    #     series.index.name = None
    #     series.index = pd.to_datetime(series.index)
    #     series['<ResObsElaborHydro>'] = pd.to_numeric(series['<ResObsElaborHydro>'])
    
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
    
    # serie = series[series['<CdStationHydro>']==code_name+'01']
    # Qobs = serie['<ResObsElaborHydro>'] / 1000 # L/s to m3/s

    Qobs = Qobs.squeeze()
    Qobs = Qobs.rename('Q')

    Qobs.to_csv(stable_folder+'hydrometry/'+naming,
                sep=';')
    
    Qobs = (Qobs / (area*1000000)) * (3600 * 24) * 1000 # m3/s to mm/j

    Qobs = select_period(Qobs, 1990, 2019) # Qobs.first_valid_index().year
    
    Clim_path = stable_folder+'climatic/'+'_ALL_D.csv'
    Clim = pd.read_csv(Clim_path, sep=';', index_col=0, parse_dates=True)
    Clim = select_period(Clim, 1990, 2019)

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

    ######################### AX 1 AX 2 #########################
    '''
    fig1, axs1 = plt.subplots(1,2, figsize=(5,4))
    fig1.add_subplot(111, frameon=False)
    plt.tick_params(labelcolor='none', top=False, bottom=False, left=False, right=False)
    axs1 = axs1.ravel()
    x_label = var + ' [mm]'
    x_label = 'P - E [mm/month]'
    y_label='Q / A [mm/month]'
    x_lim=[-150,150]
    y_lim=[0.1,100]
    '''

    for i, log in enumerate(['log']):

        fig1, ax = plt.subplots(1,1, figsize=(4.5,4))
        fig1.add_subplot(111, frameon=False)
        plt.tick_params(labelcolor='none', top=False, bottom=False, left=False, right=False)
        # axs1 = axs1.ravel()
        x_label = var + ' [mm]'
        x_label = 'P - E [mm/month]'
        y_label='Q / A [mm/month]'
        x_lim=[-150,150]
        y_lim=[0.1,150]

         # ax = axs1[i]
        scat = ax.scatter(hyst.x, hyst.y, c=hyst.wy, cmap='jet', marker="o", 
                           s=15, vmin=1, vmax=12, alpha=0.75, ec='none', zorder=-2)
        ax.plot(hyst.xi, hyst.yi, marker="o", lw=2, markersize=12, markeredgecolor='black', 
                   markerfacecolor='white', markeredgewidth=1,
                   linestyle = 'None') 
         
         # coul = mpl.cm.jet(np.linspace(0,1,13))
         # for t in np.arange(1,13,1):
         #     ax.plot(hyst.xi[t], hyst.yi[t], marker="o", markersize=9, markeredgecolor='black', 
         #            markerfacecolor=coul[t], alpha=0.5, linestyle = 'None') 
           
        for k in hyst.wyi:
            ax.annotate(k,(hyst.xi[k],hyst.yi[k]), family='sans-serif', fontsize=7, 
                         color='black', weight="bold", ha='center', va='center')
        if log != 'log':
            maxi = max(max(x_lim),max(y_lim))
            mini = min(min(x_lim),min(y_lim))
            ax.plot((mini,maxi), (mini,maxi), 
                         linestyle='-', color='grey', linewidth=1.5, zorder=-1)
        else:
            ax.plot(np.linspace(0.1,max(x_lim),50), np.linspace(0.1,max(x_lim),50), 
                     linestyle='-', color='darkgray', linewidth=1.5, zorder=-1)
        ax.errorbar(hyst.xi, hyst.yi,
                     yerr=np.vstack([hyst.yi-hyst.ye.q25, hyst.ye.q75-hyst.yi]),
                     xerr=np.vstack([hyst.xi-hyst.xe.q25, hyst.xe.q75-hyst.xi]),
                     ecolor = 'black', fmt = 'none', capsize = 1, elinewidth=1, 
                     capthick=1, zorder=1)
        ax.plot(hyst.xiline, hyst.yiline, linestyle = '-', lw=3, color='k', zorder=-1)
         
         # if i == 0:
        # if watershed_name != 'Nancon':
        ax.set_ylabel(y_label)
        # ax.set_title(hyst.name)
         # else:
             # ax.set_title(str(hyst.first)+'-'+str(hyst.last))
        ax.set_xlabel(x_label)
        ax.set_xlim(x_lim[0], x_lim[1])
        ax.set_ylim(y_lim[0], y_lim[1])
        ax.set_xticks(np.linspace(x_lim[0], x_lim[1], 5))
        ax.set_yticks(np.linspace(y_lim[0], y_lim[1], 5))         
        if log != 'log':
            ax.set_ylim(0, y_lim[1])
         
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
        '''
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
        
        ax.set_xlim(x_lim[0], x_lim[1])
        ax.set_ylim(y_lim[0]+0.1, y_lim[1])
        ax.set_xticks(np.linspace(x_lim[0], x_lim[1], 5))
        # ax.set_yticks(np.linspace(y_lim[0]+0.1, y_lim[1], 5))
        '''
    
        path_fig = os.path.join(out_path, '_figures')
        base_name = figsim_folder+'fig02/'
        spec_name = watershed_name+'_hysteresis'
        fig1.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight')

#%% 2 - OBSERVED MATRIX

watershed_names = ['Canut','Nancon']

for watershed_name in watershed_names[:] :

    print('##### '+watershed_name.upper()+' #####')
    
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True)
    area = BV.geographic.area
    
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    Qobs_path = glob.glob(stable_folder+'hydrometry/'+'Hydrometric_'+'*'+'.csv')[0]
    naming = Qobs_path.split('\\')[-1]
    
    Qobs = pd.read_csv(Qobs_path, sep=';', index_col=0, parse_dates=True)
    # area = float(Qobs_path.split('_')[-3])
    Qobs = Qobs.squeeze()
    Qobs = Qobs.rename('Q')
    
    # first = Qobs.first_valid_index().year+1
    # last = Qobs.last_valid_index().year-1
    
    first = 1990
    last = 2019
    
    # if watershed_name == 'Gael':
    #     first=2009
    
    Qobs = select_period(Qobs, first, last)
    Qobs = (Qobs / (area*1000000)) * (3600 * 24) * 1000 # m3/s to mm/d

    data_index = Qobs.copy()
    
    hist = pd.DataFrame(index=pd.date_range(start='1/1/1990', end='31/12/2019'))
    hist['Q'] = Qobs
    
    hist['day'] = hist.index.dayofyear.values
    hist['year'] = hist.index.year.values # group by month and year, get the average
    hist = hist.groupby(['day','year']).apply(lambda g: g.mean(skipna=False))
    hist = hist.unstack(level=0, fill_value=np.nan)
    hist = hist['Q']
    hist[hist==0] = 0.001
    # hist = hist.T
    
    lims = (hist.min(), hist.max())
    # vmin = np.array(lims).min()
    # vmax = np.array(lims).max()
    vmin = 0.001
    vmax = 10
    normalize = mpl.colors.Normalize(vmin=vmin, vmax=vmax)
    
    fig, ax = plt.subplots(1,1, figsize=(4.5, 4))
    colori = "jet"
    
    import matplotlib as mpl
    pc = ax.pcolormesh(hist, cmap='jet_r', vmin=vmin, vmax=vmax,
                        norm = mpl.colors.LogNorm(),
                       edgecolor='none', lw=0.2, alpha=0.7)
                      # norm=mpl.colors.LogNorm(vmin, vmax)
                      # norm=mpl.colors.CenteredNorm()
                  
    xticks = np.arange(0,365+1,60)
    days = np.arange(0,365+1,60)              
    ax.set_xticks(xticks)
    ax.set_xticklabels(days, minor=False, rotation='horizontal', fontsize=13)
    yticks = np.arange((hist.index[-1]+1) - hist.index[0])+0.5+2
    years = list((hist.index.values+0).astype(str))[::5]
    ax.set_yticks(yticks[::5])
    ax.set_yticklabels(years, minor=False, rotation='horizontal', fontsize=13)
    ax.invert_yaxis()
    ax.tick_params(axis="x", direction='out', length=5)
    ax.tick_params(axis="y", direction='out', length=5)
    plt.tick_params(right=False, top=False)
    ax.set_title(watershed_name)
    ax.set_xlabel('Days of the year')
    ax.set_ylabel('Years')
    
    '''
    divider = make_axes_locatable(ax)
    cax = divider.append_axes('right', size='1.25%', pad=0.1)
    cb = plt.colorbar(pc, cax=cax, orientation="vertical")
    cax.set_ylabel('Discharge [mm/day]', rotation=270, labelpad=20)
    '''
    
    base_name = figsim_folder+'fig02/'
    spec_name = watershed_name+'_matrix'
    fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight')

#%% 3- CALIBRATION DICHOTOMY

# geol_f = gpd.read_file(geology_path+'GEO001M_CART_FR_S_FGEOL_2154_CMYK.shp')
# geol_s = gpd.read_file(geology_path+'GEO001M_CART_FR_L_STRUCT_2154_CMYK.shp')

watershed_names = [
                   'Canut',
                   'Nancon',
                   ]

marker_list = [6,
               4]
divlw_list = [
              1.5,
              2]

# watershed_names = ['Gael']

dic_marker = dict(zip(watershed_names, marker_list))
dic_divlw = dict(zip(watershed_names, divlw_list))

for idx, watershed_name in enumerate(watershed_names):

    site = watershed_name
    
    s='o'
    
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True)
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots

    df = pd.read_csv(BV.calibration_folder+'/'+watershed_name+'_koptims_dichotomy_streams.csv', sep=';')
    
    fig, ax = plt.subplots(1, 1, figsize=(4,4), dpi=300)
    
    obs = 'complete'
    
    print('#################### SITE '+str(idx)+' PLOT '+' : '+site.upper()+' ####################')

    optim = BV.calibration_folder+'/'+'calib_dicot_hom_1v_k1/'+'streams_calibration/'+'_streams/'
    simflow = gpd.read_file(optim+'/simflow.shp')
    
    streams = gpd.read_file(stable_folder+'hydrology/'+'perennial'+'.shp')
    complete = gpd.read_file(stable_folder+'hydrology/'+'complete'+'.shp')
    polyg = gpd.read_file(stable_folder+'geographic/'+'watershed.shp')
    contour = gpd.read_file(stable_folder+'geographic/'+'watershed_contour.shp')
    
    bounds = contour.geometry.total_bounds
    xlim = ([bounds[0], bounds[2]])
    ylim = ([bounds[1], bounds[3]])

    dem = stable_folder+'geographic/'+'watershed_extent.tif'
    gdal.Translate(dem, gdal.Open(dem_path), 
                    projWin=[xlim[0],ylim[1],xlim[1],ylim[0]], noData=-99999)
    hill = stable_folder+'geographic/'+'watershed_extent_hill.tif'
    wbt.hillshade(dem, hill, azimuth=315.0, altitude=45.0, zfactor=2)
    
    dem = rasterio.open(stable_folder+'geographic/'+'watershed_extent.tif')
    hill = rasterio.open(stable_folder+'geographic/'+'watershed_extent_hill.tif')
    img = imageio.imread(stable_folder+'geographic/'+'watershed_extent.tif')
    # raster =  rasterio.open(optim+'/simflow_raster.tif')
        
    ax.set_xlim(xlim)
    ax.set_ylim(ylim)
    ax.get_xaxis().set_visible(False)
    ax.get_yaxis().set_visible(False)
    ax.set_title(site, fontproperties=fontprop)

    # hil = rasterio.plot.show(np.ma.masked_where(hill.read(1) < 0, hill.read(1)), 
    #                           ax=ax, transform=dem.transform,
    #                           cmap='Greys_r', alpha=0.5, zorder=2)
    
    geol_f.plot(ax=ax, color=list(geol_f['hex']),alpha=0.3, edgecolor='grey', lw=0.5, zorder=0)
    
    geol_s.plot(ax=ax, color=list(geol_s['hex']), alpha=0.3, lw=0.5, zorder=1)
    
    xlims = ax.get_xlim()[1] - ax.get_xlim()[0]
    ylims = ax.get_ylim()[1] - ax.get_ylim()[0]
    
    bbox = ax.get_window_extent().transformed(fig.dpi_scale_trans.inverted())
    width, height = bbox.width, bbox.height
    width *= fig.dpi
    height *= fig.dpi
    
    # rast = rasterio.plot.show(np.ma.masked_where(raster.read(1) < 0, raster.read(1)), 
    #                   ax=ax, transform=dem.transform, vmin=0, vmax=1000,
    #                   cmap='RdYlGn_r', alpha=1, zorder=4)

    simflow.plot(ax=ax, alpha=1, column='VALUE1', cmap="RdYlGn_r", 
                  marker='s', markersize=dic_marker[watershed_name], lw=0.1, edgecolor='none',
                  scheme="User_Defined", 
                  classification_kwds=dict(bins=[75, 150, 225, 300]),
                  zorder=4)
    
    from collections import OrderedDict
    
    linestyles = OrderedDict(
        [('solid',               (0, ())),
         ('loosely dotted',      (0, (1, 10))),
         ('dotted',              (0, (1, 5))),
         ('densely dotted',      (0, (1, 1))),
    
         ('loosely dashed',      (0, (5, 10))),
         ('dashed',              (0, (5, 5))),
         ('densely dashed',      (0, (5, 1))),
    
         ('loosely dashdotted',  (0, (3, 10, 1, 10))),
         ('dashdotted',          (0, (3, 5, 1, 5))),
         ('densely dashdotted',  (0, (3, 1, 1, 1))),
    
         ('loosely dashdotdotted', (0, (3, 10, 1, 10, 1, 10))),
         ('dashdotdotted',         (0, (3, 5, 1, 5, 1, 5))),
         ('densely dashdotdotted', (0, (3, 1, 1, 1, 1, 1)))])
    
    complete[complete.persistanc=='Intermittent'].plot(ax=ax, lw=1/dic_divlw[watershed_name],
                                                       color='navy', zorder=5)
    complete[complete.persistanc=='Permanent'].plot(ax=ax, lw=2/dic_divlw[watershed_name],
                                                    color='b', ls='-', zorder=5)
    # streams.plot(ax=ax, lw=2, color='k', zorder=6)
    contour.plot(ax=ax, lw=1.5, color='k', zorder=6)

    fig.tight_layout()
    
    # fig.savefig(fig_path + 'dichotomy_streams_mapgeol_' + watershed_name  + '.png', dpi=300, bbox_inches='tight')

    base_name = figsim_folder+'fig03/'
    spec_name = watershed_name+'_dichotomy'
    fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight')

#%% 3 - CALIBRATION Q 2D

from calibration import calib_root, calib_dichotomy, calib_analysis, calib_exploration, calib_basis

watershed_names = [
                   'Canut',
                   'Nancon',
                   ]

# watershed_names = ['Canut']

params_file = 'calib_explo_hom_2v_k1-n1'

wish = 0

sat_typ = 'seepage_areas'

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
        sat = pd.to_numeric(sat)
        
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
    # pc = ax.pcolormesh(X,Y,Z, cmap='jet', shading='gouraud', vmin=0, vmax=1) #figadd.cmap_white_jet()
    pc = ax.contourf(X/3600/24, Y*100, Z, levels=np.arange(0,1.1,0.1), alpha=0.6, ec='none')    
    
    # divider = make_axes_locatable(ax)
    # cax = divider.append_axes('right', size='5%', pad=0.05)
    
    
    # position=fig.add_axes([1.05,0.33,0.03,0.5])  ##
    # cb = fig.colorbar(pc, cax=position, orientation='vertical')
    # cb.set_ticks(np.arange(0,1.1,0.2))
    # cb.set_ticklabels(np.arange(0,101,20)) 
    # cb.set_label('$NSE_{log}$', rotation=270, labelpad=40)
    # cb.ax.tick_params(top=True,
    #             bottom=True,
    #             left=False,
    #             right=False,
    #             labelleft=False,
    #             labelbottom=True)
    
    
    ax.set_xscale('log')
    ax.set_ylabel('Φ [%]')
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
                sim_sat[j][i] = pd.to_numeric(sim_res[string][sat_typ]).min()
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
                sim_sat[j][i] = pd.to_numeric(sim_res[string][sat_typ]).mean()
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
                sim_sat[j][i] = pd.to_numeric(sim_res[string][sat_typ]).median()
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
                sim_sat[j][i] = pd.to_numeric(sim_res[string][sat_typ]).max()
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
    
    ax.axvline(df.perennial[0], color='k', lw=2)
    ax.axvline(df.complete[0], color='k', lw=2, ls='--')
    
    ax.set_title(watershed_name, pad=10)
    plt.tight_layout()
    
    # fig.savefig(figsim_folder+watershed_name+'_calib2D_map'+'.png', dpi=300, bbox_inches='tight')
    # fig.savefig(fig_path + 'Qmap_NSElog_' +
    #             watershed_name + '.png', dpi=300, bbox_inches='tight')

    base_name = figsim_folder+'fig03/'
    spec_name = watershed_name+'_explodischarge'
    fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight')

#%% 3- CALIBRATION S 2D

from calibration import calib_root, calib_dichotomy, calib_analysis, calib_exploration, calib_basis

watershed_names = [
                   'Canut',
                   'Nancon',
                   ]

# watershed_names = ['Canut']

params_file = 'calib_explo_hom_2v_k1-n1'

wish = 0

sat_typ = 'seepage_areas'

for watershed_name in watershed_names[:]:
    
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
    sim_sat_max = np.zeros((len(p1),len(p2)))
    compt=0
    for i in range(len(p1)):
        for j in range(len(p2)):
            temp = [p1[i],p2[j]]
            string = str(p1[i])+';'+str(+p2[j])
            try:
                # ax.set_title('SAT MIN [%]')
                sim_sat_min[j][i] = pd.to_numeric(sim_res[string][sat_typ]).min()
            except:
                pass
            try:
                # ax.set_title('SAT MEAN [%]')
                sim_sat_mean[j][i] = pd.to_numeric(sim_res[string][sat_typ]).mean()
            except:
                pass
            try:
                # ax.set_title('SAT MAX [%]')
                sim_sat_max[j][i] = pd.to_numeric(sim_res[string][sat_typ]).max()
            except:
                pass
            compt += 1
    
    Z = (sim_sat_max - sim_sat_min)
    # pc = ax.contourf(X/24/3600,Y*100,Z, cmap='rainbow_r', alpha=0.9, levels=np.arange(0,101,10)) #figadd.cmap_white_jet()    
    pc = ax.contourf(X/24/3600,Y*100,Z, cmap='viridis', alpha=0.6, levels=np.arange(0,101,10)) #figadd.cmap_white_jet()    
    ax.set_xscale('log')
    ax.set_ylabel('Φ [%]')
    ax.set_xlabel('K [m/s]')
    
    Z = sim_sat_mean.copy()
    Z[Z<1] = np.nan
    Z[Z>10] = np.nan
    
    '''
    ax.scatter(X/24/3600,Y*100,c=Z, s=20, marker='s', edgecolor='k',
                cmap=mpl.colors.ListedColormap('white'))
    '''
        
    # position=fig.add_axes([1.05,0.2,0.02,0.7])  ## the parameters are the specified position you set 
    # fig.colorbar(pc,cax=position)
    
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
    
    ax.axvline(df.perennial[0], color='k', lw=2)
    ax.axvline(df.complete[0], color='k', lw=2, ls='--')
    
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
    
    plt.tight_layout()    
    
    base_name = figsim_folder+'fig03/'
    spec_name = watershed_name+'_explosaturation'
    fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight')

#%% 4 - CALIBRATION CHRONICS

typ = 'calibr-t3'

mod = 'REA'
first = 1990
last = 2019
time_step = 'M'
sim_state = 'transient'

watershed_names = ['Canut','Nancon']
code_names = ['J7513010','J0014010']

# watershed_names = ['Canut']
# code_names = ['J7513010']

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
    BV.add_forcing()
    BV.add_intermittency(intermittency_path)
    
    area = BV.geographic.area
    
    path_hydro = stable_folder+'hydrology/'
    perennial_tif = imageio.imread(path_hydro+'perennial.tif')
    complete_tif = imageio.imread(path_hydro+'complete.tif')
    
    area_complete = round((np.sum(complete_tif > 0) * 75**2) / 1000000 / area *100, 1)
    area_perennial = round((np.sum(perennial_tif > 0) * 75**2) / 1000000 / area*100, 1)
    # drainage = round(area_all / area, 2)
    
    scan = 'outflow_drain'
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    # simul_list = glob.glob(simulations_folder+typ+'*')
    simul_list = sorted(glob.glob(simulations_folder+typ+'*'),
                       key=os.path.getmtime)
     
    BV.forcing.update_runoff_surfex(clim_mod = mod, clim_sce='historic',
                                    first_year = first, last_year = last, time_step = 'M',
                                    sim_state='transient')
    Runof = BV.forcing.runoff # m/month
    
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
        Qmod = Smod['outflow_drain'] 
        Qmod = Qmod.squeeze() * 1000 * 30
        Qmod = Qmod + (BV.forcing.runoff * 1000 * 30)
        Cmod = Smod['recharge'] * 1000 * 30 # mm/months
        
        stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
        raw_path = stable_folder+'/'+'hydrometry/'
        Qobs_path = fnmatch.filter(os.listdir(raw_path), 'Hydrometric_*')[0]
        Qobs = pd.read_csv(raw_path+Qobs_path, sep=';', index_col=0, parse_dates=True)
        # area = float(Qobs_path.split('_')[-3])
        area = BV.geographic.area
        Qobs = (Qobs / (area*1000000)) * (3600 * 24 * 30) * 1000  # m3/s to mm/month
        Qobs = Qobs.squeeze()
        Qobs = select_period(Qobs, 1990, 2019)
        Qobs = Qobs.resample('M').mean()
        
        import hydroeval as he
        nse = he.evaluator(he.nse, select_period(Qmod,1990,2019), Qobs, transform='log')[0]
        print(round(nse,2))
        
        # plt.plot(Cmod)
        # plt.plot(Qobs)
        # plt.plot(Qmod)
        
        o = Qobs # m/j to mm/month
        s = Qmod # m/j to mm/month
        # nd = 
        sat = Smod['surflow_areas']
        # sat = Smod['seepage_areas']

        ###########################################
        fig, ax = plt.subplots(1,1, figsize=(3,3))
        ax.scatter(select_period(o,1990,2019),select_period(s,1990,2019),
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
        
        # fig.savefig(figsim_folder+watershed_name+'_obs_sim_compar_'+typ+'.png', dpi=300, bbox_inches='tight')
        
        base_name = figsim_folder+'fig04/'
        spec_name = watershed_name+'_obsvssim'
        fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight')
        
        ###########################################
        fig, ax = plt.subplots(1,1, figsize=(7,3))
        # axs = axs.ravel()
        
        yearsmaj = mdates.YearLocator(5)   # every year
        yearsmin = mdates.YearLocator(1)
        # monthsmaj = mdates.MonthLocator(6)  # every month
        # monthsmin = mdates.MonthLocator(3)
        # months_fmt = mdates.DateFormatter('%m') #b = name of month ?
        years_fmt = mdates.DateFormatter('%Y')
        
        k = '{:.1e}'.format(K)
        sy = Sy
        title = watershed_name
        # nselog = round(((nd[0]))*100,1)
        # label = 'K = '+k+' m/s'+' ; '+'ɸ = '+str(round(sy,1))+'% ; '+\
        #         '$NSE_{log}$ = '+str(nselog)+'%'
        # nse_good.append(str(k)+'_'+str(sy)+'_'+str(nselog))
        
        '''
        ax = axs[0]
        ax.xaxis.set_major_locator(yearsmaj)
        ax.xaxis.set_minor_locator(yearsmin)
        ax.xaxis.set_major_formatter(years_fmt)
        
        # ax.plot(R, color='k', lw=2, label='recharge')
        ax.plot(s, color='red', lw=2, label='modeled')
        # ax.plot(s, lw=1, label=label)   
        ax.set_title(title)
        ax.plot(o, color='grey', lw=2, ls='-', zorder=0, label='observed')
        ax.grid('grey')
        ax.set_ylim(-2,200)
        # ax.set_xlim(pd.to_datetime('2000'), pd.to_datetime('2005'))
        ax.legend(loc='upper left')
        '''
        
        # ax = axs[0]
        ax.set_ylabel('Q / A [mm/month]')
        axb = ax.twinx()
        axb.set_ylabel('R [mm/month]', rotation=270, labelpad=25)
        axb.bar(Cmod.index, Cmod,
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
        ax.plot(o, color='k', lw=2, ls='-', zorder=0, label='observed')
        # ax.set_yscale('log')
        ax.plot(s, color='red', lw=2, label='modeled')
        ax.set_ylim(0.11,200)
        # ax.grid('grey')
        # ax.set_title('Discharge')
        # ax.set_xlim(pd.to_datetime('1986'))
        ax.set_xlim(pd.to_datetime('1990'), pd.to_datetime('2020'))
        
        base_name = figsim_folder+'fig04/'
        spec_name = watershed_name+'_discharge'
        fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight')
        
        #######################################################################
        
        fig, ax = plt.subplots(1,1, figsize=(7,3))
        # ax = axs[1]
        ax.set_ylabel('$A_{sat}$ [%]')
        # axb = ax.twinx()
        # axb.set_ylim(0,1000)
        # axb.invert_yaxis()
        # ax.axhline(y=20, color='k', ls= '--', lw=2)
        ax.xaxis.set_major_locator(yearsmaj)
        ax.xaxis.set_minor_locator(yearsmin)
        ax.xaxis.set_major_formatter(years_fmt)    
        # sat_good.append(str(k)+'_'+str(sy)+'_'+str(round(sat.mean(),2)))
        ax.plot(Smod['surflow_areas'], color='darkorange', ls='-', lw=2, label='catchment')
        ax.fill_between(Smod.index, Smod['perenn_areas'], Smod['surflow_areas'],
                        interpolate=False, color='darkorange', alpha=0.75)
        # ax.plot(Smod['intermit_areas'], color='darkorange', lw=2, label='upstream')
        ax.plot(Smod['perenn_areas'], color='dodgerblue',
                marker=None, markeredgecolor='none', markerfacecolor='dodgerblue',
                markersize=5, lw=2, label='upstream')
        ax.fill_between(Smod.index, 0, Smod['perenn_areas'],
                        interpolate=False, color='dodgerblue', alpha=0.75)
        # ax.plot(sat, lw=1, label=label) 
        ax.set_ylim(0,20)
        # title = 'Saturation'
        # ax.set_title(title)
        ax.set_xlim(pd.to_datetime('1990'), pd.to_datetime('2020'))
        # ax.grid('grey')
        # ax.set_xlim(pd.to_datetime(str(first)), pd.to_datetime(str(last)))
        print(Smod['perenn_areas'].mean().round(2), Smod['surflow_areas'].mean().round(2), Smod['surflow_areas'].max().round(2))
        
        ax.axhline(y=area_perennial, c='blue', lw=2, ls='-')
        ax.axhline(y=area_complete, c='navy', lw=1, ls='-')
        
        base_name = figsim_folder+'fig04/'
        spec_name = watershed_name+'_saturation'
        fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight')
        
        # fig.savefig(figsim_folder+watershed_name+'_quickly_plot_results_'+typ+'.png', dpi=300, bbox_inches='tight')

#%% 5 - CALIBRATION VALIDATION

typ = 'calibr-t3'

mod = 'REA'
first = 1990
last = 2019
time_step = 'M'
sim_state = 'transient'

watershed_names = ['Canut','Nancon']
code_names = ['J7513010','J0014010']

# watershed_names = ['Canut']
# code_names = ['J7513010']

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
    BV.add_forcing()
    BV.add_intermittency(intermittency_path)
    
    scan = 'outflow_drain'
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    # simul_list = glob.glob(simulations_folder+typ+'*')
    simul_list = sorted(glob.glob(simulations_folder+typ+'*'),
                       key=os.path.getmtime)
     
    BV.forcing.update_runoff_surfex(clim_mod = mod, clim_sce='historic',
                                    first_year = first, last_year = last, time_step = 'M',
                                    sim_state='transient')
    Runof = BV.forcing.runoff # m/month
    
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
        Qmod = Smod['outflow_drain'] 
        Qmod = Qmod.squeeze() * 1000 * 30
        Qmod = Qmod + (BV.forcing.runoff * 1000 * 30)
        Cmod = Smod['recharge'] * 1000 * 30 # mm/months
        
        stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
        raw_path = stable_folder+'/'+'hydrometry/'
        Qobs_path = fnmatch.filter(os.listdir(raw_path), 'Hydrometric_*')[0]
        Qobs = pd.read_csv(raw_path+Qobs_path, sep=';', index_col=0, parse_dates=True)
        # area = float(Qobs_path.split('_')[-3])
        area = BV.geographic.area
        Qobs = (Qobs / (area*1000000)) * (3600 * 24 * 30) * 1000  # m3/s to mm/month
        Qobs = Qobs.squeeze()
        Qobs = select_period(Qobs, 1990, 2019)
        Qobs = Qobs.resample('M').mean()
        
        import hydroeval as he
        nse = he.evaluator(he.nse, select_period(Qmod,1990,2019), Qobs, transform='log')[0]
        print(round(nse,2))
        
        # plt.plot(Cmod)
        # plt.plot(Qobs)
        # plt.plot(Qmod)
        
        o = Qobs # m/j to mm/month
        s = Qmod # m/j to mm/month
        # nd = 
        sat = Smod['surflow_areas']
        # sat = Smod['seepage_areas']
        
        ###########################################
        fig, ax = plt.subplots(1,1, figsize=(6,3))
        Sub_path = glob.glob(simul+'/_subbasins/intermittency_*')[0]+'/_simulated_results.csv'
        Sub = pd.read_csv(Sub_path, sep=';', index_col=0, parse_dates=True)
        # ax.axhline(y=20, color='grey', ls='--', lw = 1, label='approxim. observed')
        # ax.plot(Sub['perenn_areas'], color='dodgerblue', lw=2)
        # ax.plot(Sub['intermit_areas'], color='darkorange', lw=2)
        # ax.legend(loc='upper left')
        d = BV.intermittency.flowing
        # print(d)s
        assec = d[d==1].dropna()
        invi = d[d==2].dropna()
        low = d[d==3].dropna()
        accep = d[d==4].dropna()
        visib = d[d==5].dropna()
        
        # for u in range(len(noflow)):
        #     ax.axvline(noflow.index[u], color='salmon', linewidth = 5, alpha=1)
        # for u in range(len(flow)):
        #     ax.axvline(flow.index[u], color='lightskyblue', linewidth = 5, alpha=1)
            
        for u in range(len(assec)):
            ax.axvline(assec.index[u], color='salmon', linewidth = 4, alpha=1) # assec
        for u in range(len(invi)):
            ax.axvline(invi.index[u], color='gold', linewidth = 4, alpha=1) # pond
        for u in range(len(low)):
            ax.axvline(low.index[u], color='lightskyblue', linewidth = 4, alpha=1) # bio mal
        for u in range(len(accep)):
            ax.axvline(accep.index[u], color='lightskyblue', linewidth = 4, alpha=1) # bio ok
        for u in range(len(visib)):
            ax.axvline(visib.index[u], color='lightskyblue', linewidth = 4, alpha=1) # ecoul
        
        ax.axhline(y=0, color='dimgray', lw= 1)

        ax.set_xlim(pd.to_datetime('2012'), pd.to_datetime('2020'))
        seep = Sub['seepage_areas']
        seep = seep.fillna(0)
        ax.plot(seep, color='k', ls=(0, (1, 1)), lw=1.5, label='upstream')
        tp = Sub['surflow_areas']
        tp = tp.fillna(0)
        ax.plot(tp, color='k', lw=1.5, label='upstream')
        # cond_coul = 0
        # flow_mod = tp.copy()
        # flow_mod[flow_mod<=cond_coul] = np.nan
        # ax.plot(flow_mod, color='navy', marker='o', markersize=3,
        #         markeredgecolor='none',
        #         lw=2, label='upstream')
        # noflow_mod = tp.copy()
        # noflow_mod[noflow_mod>cond_coul] = np.nan
        # ax.plot(noflow_mod, color='darkred', marker='o', markersize=3,
        #         markeredgecolor='none',
        #         lw=2, label='upstream')
        ax.grid('grey', axis='x')
        ax.set_ylim(-0.6,20)
        ax.set_ylabel('$A_{sat}$ [%]')
        
        months_maj = MonthLocator()  # every x month
        ax.xaxis.set_minor_locator(months_maj)
        
        plt.tight_layout()
        
        # ax.legend(bbox_to_anchor=(1.5, 3), ncol=1)
        
        # fig.savefig(figsim_folder+watershed_name+'_onde_compar_'+typ+'.png', dpi=300, bbox_inches='tight')

        base_name = figsim_folder+'fig05/'
        spec_name = watershed_name+'_validonde'
        fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight')
        
#%% 5 - CALIBRATION MAPPING

watershed_names = [
                   'Canut',
                   'Nancon',
                   ]

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
    simul_list = sorted(glob.glob(simulations_folder+typ+'*'),
                       key=os.path.getmtime)
         
    for simul in simul_list[-1:]:
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
                
                base_name = figsim_folder+'fig05/'
                spec_name = watershed_name+'_network_'+str(k)
                fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight') 
                
#%% 6 - PERSISTENCY INDEX

watershed_names = ['Canut','Nancon']

typ = 'calibr-t3'


var = 'REC'
scan = 'outflow_drain'
sce_list = ['historic']

# fig2, axs2 = plt.subplots(1,1, figsize=(5,4),
#                         sharex=True, sharey=True)

y_name = 'surflow_areas'

for watershed_name in watershed_names:

    if watershed_name == 'Canut':
        color = 'green'
    if watershed_name == 'Nancon':
        color = 'darkmagenta'    

    fig1, axs1 = plt.subplots(1,1, figsize=(10,10), sharex=True, sharey=True)
    # axs1 = axs1.ravel()
    
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'  # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots

    for ix in np.arange(1,1+1,1):
        # simul_list = glob.glob(simulations_folder+'*'+typ+'_'+str(i)+'*')
        
        ax = axs1
            
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
            acc_npy = list(acc_npy.items())[:]
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
                    
            # ax = ax1
            vmin = 0
            vmax = 1
            
            cmap = plt.cm.jet_r  # define the colormap
            # cmap = plt.cm.RdYlGn  # define the colormap
            # cmap = parula_map
            cmaplist = [cmap(i) for i in range(cmap.N)]
            # cmaplist[0] = (.5, .5, .5, 1.0)
            cmap = mpl.colors.LinearSegmentedColormap.from_list(
                'Custom cmap', cmaplist, cmap.N)
            bounds = np.arange(0, 1.1, 0.1)
            norm = mpl.colors.BoundaryNorm(bounds, cmap.N)
                    
            pc = ax.imshow(np.ma.masked_where(days_flux <= 0, days_flux),
                           cmap=cmap, norm=norm, alpha=1)
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
            # ax.set_title(params, fontsize=8)
            plt.subplots_adjust(hspace = -0.6)
            
            '''
            ax = axs2
            
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
  
    position=fig1.add_axes([0.93,0.35,0.01,0.30])  ## the parameters are the specified position you set 
    cb = fig1.colorbar(pc,cax=position, orientation="vertical")
    position.set_ylabel('Persistency index [-]', rotation=270, labelpad=40)
    cb.ax.tick_params(axis='y', direction='out')
    
    # fig1.savefig(figsim_folder+watershed_name+'_persistency_map_historic'+'.png', dpi=300, bbox_inches='tight')

    base_name = figsim_folder+'fig06/'
    spec_name = watershed_name+'_persistency'
    fig1.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight') 

#%% 6 - MATRIX DISCHARGE

hydrology_path = data_path + 'HYDROLOGY/France/Hydrographic/D035/' # add hydrographic shapefiles

watershed_names = ['Canut','Nancon']
code_names = ['J7513010','J0014010']

# watershed_names = ['Canut']
# code_names = ['J7513010']

types_obs = ['complete','intermittent','perennial','river','zh_couesnon','zh_meuchezecanut'] # list of shapefile name layers for clip hydrology
fields_obs = ['persistanc','fid','fid','fid','fid','fid']

df = pd.DataFrame(np.nan, index=range(1), columns=types_obs)

c = ['forestgreen','orchid']
dict_c = dict(zip(watershed_names, c))

typ = 'calibr-t3'

mod_list = ['REA']

sce_list = ['historic']

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
    
    # BV.add_hydrology(hydrology_path, types_obs=['intermittent'], fields_obs=['fid'])

    bv = gpd.read_file(BV.geographic.watershed_shp)
    area = BV.geographic.area
    area = round(area, 1)
    
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    
    dem = rasterio.open(BV.geographic.watershed_dem)
    dem_data = dem.read(1)
    
    cell = np.ma.masked_array(dem_data, mask=(dem_data<0)).count()        

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

    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = 'k'
        
    for mod in mod_list:
        
        # fig1, axs1 = plt.subplots(1,1, figsize=(5,5))
        # xn = 0.1
        # xx = 100
        # yn = 0.1
        # yx = 100
        # ax = axs1
        # ax.set_title(mod)
        # ax.set_aspect('equal', adjustable='box')

        for sce in sce_list:
            
            simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+sce+'*')
            simul = simul_list[0]
            
            # if sce == 'historic':
            #     simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+'RCP8.5'+'*')
            #     simul = simul_list[0]
                
            model_name = simul.split('\\')[-1]
            Sy = float(model_name.split('_')[3].split('-')[0]) # %
            K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
            E = float(model_name.split('_')[3].split('-')[2]) # m
            D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
            params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
            Smod_path = simul+'/_watershed/_simulated_results.csv'            
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            Smod['prop_ratio'] = Smod.intermit_areas / Smod.perenn_areas
            
            Smod = select_period(Smod, 1960, 2019)

            hist = Smod.copy()
            hist['month'] = hist.index.month.values
            hist['year'] = hist.index.year.values # group by month and year, get the average
            hist = hist.groupby(['month', 'year']).apply(lambda g: g.sum(skipna=False))
            hist = hist.unstack(level=0, fill_value=np.nan)
            hist = hist['surflow_areas']
            
            lims = (hist.min(), hist.max())
            vmin = 0
            vmax = 10
            
            xticks = np.arange((hist.index[-1]+1) - hist.index[0])+0.5
            years = list(hist.index.values.astype(str))[::2] 
            
            hist = hist.T
            
            ####################################################################

            acc_npy = np.load(os.path.join(simul, '_watershed','accumulation_flux.npy'), allow_pickle=True).item()
            # acc_npy = np.load(os.path.join(simul, '_watershed','outflow_drain.npy'), allow_pickle=True).item()
            
            if watershed_name == 'Canut':
                idx_x = np.arange(0, dem_data.shape[1], 1)
                flat_flux = pd.DataFrame(index=idx_x)
            if watershed_name == 'Nancon':
                idx_x = np.arange(0, dem_data.shape[0], 1)
                flat_flux = pd.DataFrame(index=idx_x)
                
            for i in range(len(acc_npy)):
                print(i+1, len(acc_npy))
                
                if watershed_name == 'Canut':
                    def flatten_on_xy(x): # [val, col-horiz, row-verti]
                        XX,YY = np.meshgrid(np.arange(x.shape[1]),np.arange(x.shape[0]))
                        table = np.vstack((x.ravel(),XX.ravel(),YY.ravel())).T
                        return table
                    acc_path = os.path.join(simul, '_watershed/_tifs/','accumulation_flux_t('+str(i)+').tif')
                    # acc_path = os.path.join(simul, '_watershed/_tifs/','outflow_drain_t('+str(i)+').tif')
                    acc = imageio.imread(acc_path)
                    acc[dem_data<0] = np.nan
                    acc[acc<=0] = np.nan
                    # acc = (acc / cell) * 100
                    # plt.imshow(acc)
                    acc = acc / 24 / 3600 * 1000
                    flat_acc = flatten_on_xy(acc)
                    flat_acc = pd.DataFrame(flat_acc)
                    # flat_acc[0][flat_acc[0]>0] = 1
                    flat_cum_acc = flat_acc.groupby(1).max() # flat_acc = flat_acc.agg({0: "nunique"})
                    flat_cum_acc = flat_cum_acc[0].to_frame()
                    flat_cum_acc[1] = flat_cum_acc[0].cumsum() # 3 is cumulated on sum xaxis in 1
                    # flat_x = flat_x.agg({0: "nunique"})
                    # flat_acc = flat_acc.reset_index()
                    # flat_acc = flat_acc.set_index(flat_acc[1])

                if watershed_name == 'Nancon':
                    def flatten_on_xy(x):
                        XX,YY = np.meshgrid(np.arange(x.shape[1]),np.arange(x.shape[0]))
                        table = np.vstack((x.ravel(),XX.ravel(),YY.ravel())).T
                        return table                    
                    acc_path = os.path.join(simul, '_watershed/_tifs/','accumulation_flux_t('+str(i)+').tif')
                    acc = imageio.imread(acc_path)
                    acc[dem_data<0] = np.nan
                    acc[acc<=0] = np.nan
                    acc = acc / 24 / 3600 * 1000 # m3 to L/s
                    flat_acc = flatten_on_xy(acc)
                    flat_acc = pd.DataFrame(flat_acc)
                    # flat_acc[0][flat_acc[0]>0] = 1
                    flat_cum_acc = flat_acc.groupby(2).max() # flat_acc = flat_acc.agg({0: "nunique"})
                    flat_cum_acc = flat_cum_acc[0].to_frame()
                    flat_cum_acc[1] = flat_cum_acc[0].cumsum() # 3 is cumulated on sum xaxis in 1
                    # flat_x = flat_x.agg({0: "nunique"})
                    # flat_acc = flat_acc.reset_index()
                    # flat_acc = flat_acc.set_index(flat_acc[1])
                    
                flat_flux[i] = flat_cum_acc[0]
                        
            flat_flux = flat_flux.T
            flat_flux.index = Smod.index
            
            flat_flux_intm = flat_flux.groupby([lambda x: x.month]).mean()
            # flat_flux_intm = flat_flux_intm.fillna(0)
            
            # vmin = np.nanmin(flat_flux_intm)
            # vmax = np.nanmax(flat_flux_intm)
            
            vmin = 0.5
            vmax = 1000

            # plt.imshow(flat_flux_intm)
            
            # flat_flux_intm = ( flat_flux_intm / cell ) * 100
            
            print(np.nanmax(flat_flux_intm))

            fig, ax = plt.subplots(1,1, figsize=(10,3))
            yticks = np.arange(12)+0.5
            mois = ['J','F','M','A','M','J','J','A','S','O','N','D']
            ax = ax
            pc = ax.pcolormesh(flat_flux_intm, cmap='RdBu', alpha=0.7, vmin=vmin, vmax=vmax,
                          shading='flat', 
                          norm=mpl.colors.LogNorm(vmin=vmin, vmax=vmax)
                          ) # 
            ax.set_yticks(yticks)
            ax.set_yticklabels(mois, minor=False, rotation='horizontal', fontsize=13)
            
            if watershed_name == 'Canut':
                ax.set_xlim(5,118)
            if watershed_name == 'Nancon':
                ax.set_xlim(8,140)
                
            # ax.invert_xaxis()
            ax.set_title(watershed_name)
            cb = plt.colorbar(pc)
            cb.ax.set_ylabel('Q [L/s]')
            ax.set_xlabel('Distance from upstream to outlet [m]')
            cb.ax.tick_params(axis='y', direction='out')
            
            ax.set_xticklabels(((ax.get_xticks()*75).astype(int)))
            
            # ax.xaxis.tick_top()
            # yticks = np.arange((hist.index[-1]+1) - hist.index[0])+0.5
            # years = list(hist.index.values.astype(str))[::2] 
            # ax.set_yticks(yticks[::2])
            # ax.set_yticklabels(years, minor=False, rotation='horizontal', fontsize=13)
            # ax.invert_yaxis()
            # ax.tick_params(axis="x", direction='out', length=5)
            # ax.tick_params(axis="y", direction='out', length=5)
            
            base_name = figsim_folder+'fig06/'
            spec_name = watershed_name+'_matrix'
            fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight') 

#%% 6 - MATRIX SATURATION

hydrology_path = data_path + 'HYDROLOGY/France/Hydrographic/D035/' # add hydrographic shapefiles

watershed_names = ['Canut','Nancon']
code_names = ['J7513010','J0014010']

# watershed_names = ['Canut']
# code_names = ['J7513010']

types_obs = ['complete','intermittent','perennial','river','zh_couesnon','zh_meuchezecanut'] # list of shapefile name layers for clip hydrology
fields_obs = ['persistanc','fid','fid','fid','fid','fid']

df = pd.DataFrame(np.nan, index=range(1), columns=types_obs)

c = ['forestgreen','orchid']
dict_c = dict(zip(watershed_names, c))

typ = 'calibr-t3'

mod_list = ['REA']

sce_list = ['historic']

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
    
    # BV.add_hydrology(hydrology_path, types_obs=['intermittent'], fields_obs=['fid'])

    bv = gpd.read_file(BV.geographic.watershed_shp)
    area = BV.geographic.area
    area = round(area, 1)
    
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    
    dem = rasterio.open(BV.geographic.watershed_dem)
    dem_data = dem.read(1)
    
    cell = np.ma.masked_array(dem_data, mask=(dem_data<0)).count()        

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

    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = 'k'
        
    for mod in mod_list:
        
        # fig1, axs1 = plt.subplots(1,1, figsize=(5,5))
        # xn = 0.1
        # xx = 100
        # yn = 0.1
        # yx = 100
        # ax = axs1
        # ax.set_title(mod)
        # ax.set_aspect('equal', adjustable='box')

        for sce in sce_list:
            
            simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+sce+'*')
            simul = simul_list[0]
            
            # if sce == 'historic':
            #     simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+'RCP8.5'+'*')
            #     simul = simul_list[0]
                
            model_name = simul.split('\\')[-1]
            Sy = float(model_name.split('_')[3].split('-')[0]) # %
            K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
            E = float(model_name.split('_')[3].split('-')[2]) # m
            D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
            params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
            Smod_path = simul+'/_watershed/_simulated_results.csv'            
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            Smod['prop_ratio'] = Smod.intermit_areas / Smod.perenn_areas
            
            Smod = select_period(Smod, 1960, 2019)

            hist = Smod.copy()
            hist['month'] = hist.index.month.values
            hist['year'] = hist.index.year.values # group by month and year, get the average
            hist = hist.groupby(['month', 'year']).apply(lambda g: g.sum(skipna=False))
            hist = hist.unstack(level=0, fill_value=np.nan)
            hist = hist['surflow_areas']
            
            lims = (hist.min(), hist.max())
            vmin = 0
            vmax = 10
            
            xticks = np.arange((hist.index[-1]+1) - hist.index[0])+0.5
            years = list(hist.index.values.astype(str))[::2] 
            
            hist = hist.T
            
            ####################################################################

            acc_npy = np.load(os.path.join(simul, '_watershed','accumulation_flux.npy'), allow_pickle=True).item()
            # acc_npy = np.load(os.path.join(simul, '_watershed','outflow_drain.npy'), allow_pickle=True).item()
            
            if watershed_name == 'Canut':
                idx_x = np.arange(0, dem_data.shape[1], 1)
                flat_flux = pd.DataFrame(index=idx_x)
            if watershed_name == 'Nancon':
                idx_x = np.arange(0, dem_data.shape[0], 1)
                flat_flux = pd.DataFrame(index=idx_x)
                
            for i in range(len(acc_npy)):
                print(i+1, len(acc_npy))
                
                if watershed_name == 'Canut':
                    def flatten_on_xy(x): # [val, col-horiz, row-verti]
                        XX,YY = np.meshgrid(np.arange(x.shape[1]),np.arange(x.shape[0]))
                        table = np.vstack((x.ravel(),XX.ravel(),YY.ravel())).T
                        return table
                    # acc_path = os.path.join(simul, '_watershed/_tifs/','accumulation_flux_t('+str(i)+').tif')
                    # acc_path = os.path.join(simul, '_watershed/_tifs/','outflow_drain_t('+str(i)+').tif')
                    acc_path = os.path.join(simul, '_watershed/_flowpaths/','trace_outflow_drain_t('+str(i)+').tif')
                    acc = imageio.imread(acc_path)
                    acc[dem_data<0] = np.nan
                    acc[acc<=0] = np.nan
                    # acc = (acc / cell) * 100
                    # plt.imshow(acc)
                        # acc = acc / 24 / 3600 * 1000
                    flat_acc = flatten_on_xy(acc)
                    flat_acc = pd.DataFrame(flat_acc)
                    # flat_acc[0][flat_acc[0]>0] = 1
                    flat_cum_acc = flat_acc.groupby(1).max() # flat_acc = flat_acc.agg({0: "nunique"})
                    flat_cum_acc = flat_cum_acc[0].to_frame()
                    flat_cum_acc[1] = flat_cum_acc[0].cumsum() # 3 is cumulated on sum xaxis in 1
                    # flat_x = flat_x.agg({0: "nunique"})
                    # flat_acc = flat_acc.reset_index()
                    # flat_acc = flat_acc.set_index(flat_acc[1])

                if watershed_name == 'Nancon':
                    def flatten_on_xy(x):
                        XX,YY = np.meshgrid(np.arange(x.shape[1]),np.arange(x.shape[0]))
                        table = np.vstack((x.ravel(),XX.ravel(),YY.ravel())).T
                        return table                    
                    # acc_path = os.path.join(simul, '_watershed/_tifs/','accumulation_flux_t('+str(i)+').tif')
                    acc_path = os.path.join(simul, '_watershed/_flowpaths/','trace_outflow_drain_t('+str(i)+').tif')
                    acc = imageio.imread(acc_path)
                    acc[dem_data<0] = np.nan
                    acc[acc<=0] = np.nan
                        # acc = acc / 24 / 3600 * 1000 # m3 to L/s
                    flat_acc = flatten_on_xy(acc)
                    flat_acc = pd.DataFrame(flat_acc)
                    # flat_acc[0][flat_acc[0]>0] = 1
                    flat_cum_acc = flat_acc.groupby(2).max() # flat_acc = flat_acc.agg({0: "nunique"})
                    flat_cum_acc = flat_cum_acc[0].to_frame()
                    flat_cum_acc[1] = flat_cum_acc[0].cumsum() # 3 is cumulated on sum xaxis in 1
                    # flat_x = flat_x.agg({0: "nunique"})
                    # flat_acc = flat_acc.reset_index()
                    # flat_acc = flat_acc.set_index(flat_acc[1])
                    
                flat_flux[i] = flat_cum_acc[0]
                        
            flat_flux = flat_flux.T
            flat_flux.index = Smod.index
            
            flat_flux_intm = flat_flux.groupby([lambda x: x.month]).mean()
            # flat_flux_intm = flat_flux_intm.fillna(0)
            
            # vmin = np.nanmin(flat_flux_intm)
            # vmax = np.nanmax(flat_flux_intm)
            
            # vmin = 0.5
            # vmax = 1000

            # plt.imshow(flat_flux_intm)
            
            flat_flux_intm = ( flat_flux_intm / cell ) * 100
            
            print(np.nanmax(flat_flux_intm))

            # vmin = 0
            # vmax = 3

            vmin = 0
            vmax = 3

            fig, ax = plt.subplots(1,1, figsize=(10,3))
            yticks = np.arange(12)+0.5
            mois = ['J','F','M','A','M','J','J','A','S','O','N','D']
            ax = ax
            pc = ax.pcolormesh(flat_flux_intm, cmap='RdBu', alpha=0.7, vmin=vmin, vmax=vmax,
                          shading='flat', 
                          #norm=mpl.colors.LogNorm(vmin=vmin, vmax=vmax)
                          ) # 
            ax.set_yticks(yticks)
            ax.set_yticklabels(mois, minor=False, rotation='horizontal', fontsize=13)
            
            if watershed_name == 'Canut':
                ax.set_xlim(5,118)
            if watershed_name == 'Nancon':
                ax.set_xlim(8,140)
                
            # ax.invert_xaxis()
            ax.set_title(watershed_name)
            cb = plt.colorbar(pc)
            cb.ax.set_ylabel('SAT [%]')
            ax.set_xlabel('Distance from upstream to outlet [m]')
            cb.ax.tick_params(axis='y', direction='out')
            
            ax.set_xticklabels(((ax.get_xticks()*75).astype(int)))
            
            # ax.xaxis.tick_top()
            # yticks = np.arange((hist.index[-1]+1) - hist.index[0])+0.5
            # years = list(hist.index.values.astype(str))[::2] 
            # ax.set_yticks(yticks[::2])
            # ax.set_yticklabels(years, minor=False, rotation='horizontal', fontsize=13)
            # ax.invert_yaxis()
            # ax.tick_params(axis="x", direction='out', length=5)
            # ax.tick_params(axis="y", direction='out', length=5)
            
            base_name = figsim_folder+'fig06/'
            spec_name = watershed_name+'_matrix_sat'
            fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight') 

#%% 6 - FLOW DURATION

typ = 'calibr-t3'

watershed_names = ['Canut','Nancon']

var = 'REC'
scan = 'outflow_drain'
sce_list = ['historic']

# fig1, axs1 = plt.subplots(1,1, figsize=(5,4),
#                         sharex=True, sharey=True)

fig2, axs2 = plt.subplots(1,1, figsize=(4,3),
                        sharex=True, sharey=True)

fig3, axs3 = plt.subplots(1,1, figsize=(3.5,3),
                        sharex=True, sharey=True)

y_name = 'surflow_areas'

# fig1, axs1 = plt.subplots(1,1, figsize=(10,10), sharex=True, sharey=True)

for watershed_name in watershed_names:

    if watershed_name == 'Canut':
        color = 'forestgreen'
    if watershed_name == 'Nancon':
        color = 'darkmagenta'    

    # axs1 = axs1.ravel()
    
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'  # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots

    ax = axs1

    for ix in np.arange(1,1+1,1):
        # simul_list = glob.glob(simulations_folder+'*'+typ+'_'+str(i)+'*')
        
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
            acc_npy = list(acc_npy.items())[:]
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
            # days_flux = days_flux.round(2)
            
            box = np.sort(days_flux[~days_flux.mask]).flatten().round(2)
            
            cell = np.ma.masked_array(mask, mask=(mask<0)).count()        
    
            import collections
            a = box.copy()
            counter=collections.Counter(a)
            # print(counter)
            # print(counter.values())
            # print(counter.keys())            
            # print(counter.most_common(3))            
            # print(dict(counter))

            df = pd.DataFrame()
            df['values'] = counter.values()
            df['values'] = (df['values'] / cell) * 100
            df['keys'] = np.array(list(counter.keys()))
            # keyss = np.array(list(counter.keys())).round(2)
            # index = (keyss.round(2)).astype(str)
            # df.index = index
            # df = df.T
            
            Smod_path = simul+'/_watershed/_simulated_results.csv'            
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            Smod['prop_ratio'] = Smod.intermit_areas / Smod.perenn_areas
            
            ax = axs1
            Z = np.sort(days_flux[~days_flux.mask]).flatten()
            test = np.histogram(Z, bins=100, density=True)
            from scipy.stats import norm
            pdf = norm.pdf(Z, Z.mean(), Z.std())
            N = len(Z)
            count, bins_count = np.histogram(Z, bins=100, density=True)
            pdf = count / sum(count)
            cdf = np.cumsum(pdf)
            ax.plot(cdf*100, color=color, lw=4, label="CDF")
            ax.plot(cdf*100, color=color, lw=4, label="CDF")
            def numfmt(x, pos): # your custom formatter function: divide by 100.0
                s = '{}'.format(x / 100.0)
                return s
            import pylab
            import matplotlib.ticker as tkr     # has classes for tick-locating and -formatting
            yfmt = tkr.FuncFormatter(numfmt)    # create your custom formatter function
            ax.xaxis.set_major_formatter(yfmt)
            plt.tight_layout()
            ax.set_xlabel('Persistency index bining [-]')
            ax.set_ylabel('Cumulated $A_{sat}$ [%]')
            ax.set_ylim(80,100)
            ax.set_xlim(0,100)
            # ax.grid('grey')
            ax.invert_yaxis()

            ax = axs2
            # axb = ax.twinx()
            y_name= 'surflow_areas'
            X2 = np.sort(Smod[y_name])
            
            if watershed_name == 'Canut':
                Xc = X2.copy()
                
            N = len(Smod[y_name])
            # ax.plot((1-np.arange(0,N,1)/N)*100, (X2-X2.min())/(X2.max()-X2.min()) * 100,
            #         color=color, lw=2)
            ax.plot((1-np.arange(0,N,1)/N)*100, (X2),
                    color=color, lw=2)
            ax.fill_between((1-np.arange(0,N,1)/N)*100,
                            Xc,
                            X2,
                             lw=0,
                            color='silver', alpha=0.5)
            # axb.plot((1-np.arange(0,N,1)/N)*100, (X2)/(X2.mean()),
            #         color=color, lw=2, ls='--')
            # axb.set_ylabel('Cumulated $A_{sat}$ normalized [-]', rotation=270, labelpad=25)
            # ax.set_xlabel('Frequency in time [%]')
            ax.set_xlabel('Frequency of occurrence [%]')
            ax.set_ylabel('Cumulated $A_{sat}$ [%]')
            ax.set_xlim(0,100)
            ax.set_ylim(0,20)
            # axb.set_ylim(0,4)
            # axb.set_yticks([0,1,2,3,4])
            # ax.set_xscale('log')
            # ax.set_yscale('log')
            # ax.grid('grey')
            
            ax = axs3
            # ax.axhline(y=1, color='grey', lw=1)
            # ax = ax.twinx()
            y_name= 'surflow_areas'
            Smod_path = simul+'/_watershed/_simulated_results.csv'            
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            Smod['prop_ratio'] = Smod.intermit_areas / Smod.perenn_areas
            X2 = np.sort(Smod[y_name])
            N = len(Smod[y_name])
            # ax.plot((1-np.arange(0,N,1)/N)*100, (X2-X2.min())/(X2.max()-X2.min()) * 100,
            #         color=color, lw=2)
            ax.plot((1-np.arange(0,N,1)/N)*100, (X2)/X2.mean(),
                    color=color, lw=2)
            
            ax.fill_between((1-np.arange(0,N,1)/N)*100,
                            Xc/Xc.mean(),
                            X2/X2.mean(),
                             lw=0,
                            color='silver', alpha=0.5)
            
            # ax.set_xlabel('Frequency in time [%]')
            # ax.set_ylabel('$A_{intermittent}$ / $A_{perennial}$ [-]')
            ax.set_xlim(0,100)
            # ax.set_xscale('log')
            ax.set_ylim(0,4)
            ax.set_yticks([0,1,2,3,4])
            # ax.set_ylabel('Cumulated $A_{sat}$ normalized [-]')

            # ax.set_xscale('log')
            # ax.set_yscale('log')
            # ax.grid('grey')

base_name = figsim_folder+'fig06/'
spec_name = str(watershed_names)+'_flowduration'
fig2.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight') 

base_name = figsim_folder+'fig06/'
spec_name = str(watershed_names)+'_flowduration_norm'
fig3.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight') 

#%% 7a - REC-SAT HYSTERESIS

from scipy.stats import binned_statistic

# typ = 'calibr-t3'

# Things
time_step = 'M'
sim_state = 'transient'
var = 'REC'
# scan = 'outflow_drain'
scan = 'surflow_areas'

# Colored
# mod_list = ['REA']
sce_list = ['historic']
sce_cmap = ["Greys"]
sce_color = ["k"]
cmap_dict = dict(zip(sce_list, sce_cmap))
color_dict = dict(zip(sce_list, sce_color))

c = ['forestgreen','orchid']
dict_c = dict(zip(watershed_names, c))

# Hysteres
temporal = False
space = 0
norm = False

watershed_names = ['Canut','Nancon']

watershed_names = ['Canut']

# x_name = 'outflow_drain'
x_name = 'recharge'
y_name = 'surflow_areas'
# y_name = 'intermit_areas'
# y_name = 'prop_ratio'
# y_name = 'perenn_areas'
# y_name = 'outflow_drain'
xmin = []
xmax = []
ymin = []
ymax = []


# fig3, ax3 = plt.subplots(1,1, figsize=(3,3))

# fig2, axs2 = plt.subplots(1,1, figsize=(3,3))

# fig3, ax3 = plt.subplots(1,1, figsize=(3,3))

for watershed_name in watershed_names :
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = 'k'
        
    for mod in mod_list:
        
        # fig1, axs1 = plt.subplots(1,1, figsize=(5,5))
        # xn = 0.1
        # xx = 100
        # yn = 0.1
        # yx = 100
        # ax = axs1
        # ax.set_title(mod)
        # ax.set_aspect('equal', adjustable='box')

        for sce in sce_list:
            
            simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+sce+'*')
            simul = simul_list[0]
            
            # if sce == 'historic':
            #     simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+'RCP8.5'+'*')
            #     simul = simul_list[0]
                
            model_name = simul.split('\\')[-1]
            Sy = float(model_name.split('_')[3].split('-')[0]) # %
            K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
            E = float(model_name.split('_')[3].split('-')[2]) # m
            D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
            params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
            Smod_path = simul+'/_watershed/_simulated_results.csv'            
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            Smod['prop_ratio'] = Smod.intermit_areas / Smod.perenn_areas
            
            Smod = select_period(Smod, 1960, 2019)

            Qmod = Smod[scan] 
          
            Qmod = Qmod # mm/months
            Qmod = Qmod.squeeze()    
            Cmod = Smod['recharge'] # mm/months
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
            
            hyst = Hysteresis(DFmod, watershed_name)
            hyst.prepare_xy_raw()
            hyst.compute_xy_metrics(temporal=temporal, space=space, norm=norm)
            
            columns_x = hyst.xrecapl.columns
            columns_y = hyst.yrecapl.columns
            
            n = len(columns_x)
            cmap = cmap_dict[sce]
            cmap_color = plt.get_cmap(cmap)(np.linspace(0, 1, n))
            color = color_dict[sce]
                        
            print('area='+str(hyst.area))
            print('slope='+str(hyst.slope))
            print('hi='+str(hyst.hi))
            print('q0='+str(hyst.q0))
            
            
            
            if watershed_name == 'Nancon':
                coul = 'orchid'
                mark = 'o'
                cmaplist = ['orchid','darkmagenta']
                import colorcet as cc
                # cmaplist[-1] = (.5, .5, .5, 1.0) # first value
                cmap = mpl.colors.LinearSegmentedColormap.from_list(
                    'Custom cmap', cmaplist)
                cmapping = 'spring'
                cmapping = cmap
            if watershed_name == 'Canut':
                coul = 'forestgreen'
                mark = 'o'
                cmaplist = ['greenyellow','green']
                import colorcet as cc
                # cmaplist[-1] = (.5, .5, .5, 1.0) # first value
                cmap = mpl.colors.LinearSegmentedColormap.from_list(
                    'Custom cmap', cmaplist)
                cmapping = 'spring'
                cmapping = cmap
                
            x = hyst.x.diff()*1000
            y = hyst.y.diff()
            c = Smod.index.month
            wy = pd.Series(x.index.month).replace([10,11,12,1,2,3,4,5,6,7,8,9],
                                                    [1,2,3,4,5,6,7,8,9,10,11,12])

            xi = hyst.x.groupby([lambda x: x.month]).mean() *1000
            yi = hyst.y.groupby([lambda y: y.month]).mean()
            
            xiline = xi.append(xi.iloc[[0]])
            xiline.index = np.arange(1,14,1)
            yiline = yi.append(yi.iloc[[0]])
            yiline.index = np.arange(1,14,1)
            
            
            # year = 2018
            # spe_year_x = select_period(x, year, year)
            # spe_year_y = select_period(y, year, year)
            # xiline_spe = spe_year_x.append(spe_year_x.iloc[[0]])
            # xiline_spe.index = np.arange(1,14,1)
            # yiline_spe = spe_year_y.append(spe_year_y.iloc[[0]])
            # yiline_spe.index = np.arange(1,14,1)
            # ax3.plot(xiline_spe, yiline_spe, linestyle = '-', lw=1.5, color='red', zorder=0)
            # year = 2002
            # spe_year_x = select_period(x, year, year)
            # spe_year_y = select_period(y, year, year)
            # xiline_spe = spe_year_x.append(spe_year_x.iloc[[0]])
            # xiline_spe.index = np.arange(1,14,1)
            # yiline_spe = spe_year_y.append(spe_year_y.iloc[[0]])
            # yiline_spe.index = np.arange(1,14,1)
            # ax3.plot(xiline_spe, yiline_spe, linestyle = '-', lw=1.5, color='blue', zorder=0)
            
            
            # xt = xiline.diff()
            # yt = yiline.diff()
            
            ##################################################################
            
            fig3, ax3 = plt.subplots(1,1, figsize=(3,3))

            cmapping = 'jet'
            ax3.scatter((x) , (y), c=wy, marker=mark, cmap=cmapping,
                        s=10, vmin=1, vmax=12, alpha=0.75, ec='none', lw=0.2, zorder=-1)
            # ax3.scatter(xt, yt)
            
            xi = xiline.diff()
            xi.iloc[0] = xi.iloc[-1]
            xi = xi[:-1]
            yi = yiline.diff()
            yi.iloc[0] = yi.iloc[-1]
            yi = yi[:-1]
                      
            # ax3.plot(xi, yi, linestyle = '-', lw=1.5, color=coul, zorder=0)

            wyi = np.arange(1,12+1,1)
            wyi = pd.Series(wyi).replace([10,11,12,1,2,3,4,5,6,7,8,9],
                                         [1,2,3,4,5,6,7,8,9,10,11,12])
            
            ax3.scatter(xi, yi, c=wyi, marker=mark, cmap=cmapping,
                        s=35, vmin=1, vmax=12, alpha=1, 
                        ec='k', lw = 0.5, zorder=1)

            cl = mpl.cm.jet(np.linspace(0,1,len(wyi)))
            compt = 2
            wyi = np.arange(1,12+1,1)
            for k in wyi:
                ax3.annotate(k,(xi[k],yi[k]), family='sans-serif',
                             fontsize=5, 
                              color='black', weight="bold", ha='center', va='center',
                              zorder=compt)
                ax3.plot(xi[k], yi[k], marker=mark, lw=2, markersize=9,
                          markeredgecolor='black', 
                            markerfacecolor='white', markeredgewidth=1,
                            linestyle = 'None', zorder=compt) # cl[k-1]
                compt+=1
            
            ax3.set_axisbelow(True)
            # ax.grid(zorder=-1000)
            ax3.xaxis.grid(color='gray', zorder=-1)
            ax3.yaxis.grid(color='gray', zorder=-1)
            
            ax3.axhline(y=0, color='k', zorder=0)
            ax3.axvline(x=0, color='k', zorder=0)
            ax3.set_xlim(-2, 2)
            ax3.set_ylim(-4, 4)
            
            ax3.set_xlabel('\u0394R [mm/month]')
            ax3.set_ylabel('\u0394$A_{sat}$ [%]')
            
            ax3.set_xticks(np.arange(-2, 2 + 0.1, 1))
            ax3.set_yticks(np.arange(-4, 4 + 0.1, 2))
                      
            dfevol = hyst.dfmet.iloc[:-1]
            dfevol = dfevol.set_index(pd.to_datetime(dfevol.index, format='%Y'))
            
            xe = pd.DataFrame()
            xe['q25'] = (x.groupby(x.index.month).quantile(0.25))
            xe['q75'] = (x.groupby(x.index.month).quantile(0.75))
    
            ye = pd.DataFrame()
            ye['q25'] = (y.groupby(y.index.month).quantile(0.25))
            ye['q75'] = (y.groupby(y.index.month).quantile(0.75))
            
            ax3.errorbar(xi, yi,
                          yerr=np.vstack([yi-ye.q25, ye.q75-yi]),
                          xerr=np.vstack([xi-xe.q25, xe.q75-xi]),
                          ecolor = 'black', fmt = 'none', capsize = 1, elinewidth=0.5, 
                          capthick=0.5, zorder=1)
            
            xiline = xi.append(xi.iloc[[0]])
            xiline.index = np.arange(1,14,1)
            yiline = yi.append(yi.iloc[[0]])
            yiline.index = np.arange(1,14,1)
            ax3.plot(xiline, yiline, linestyle = '-', lw=1.5, color='k', zorder=0)

            
            # fig3.savefig(figsim_folder+watershed_name+'_delta_saturation'+'.png', dpi=300, bbox_inches='tight')
 
            ###################################################################
    
            fig1, axs1 = plt.subplots(1,1, figsize=(3,3))
            x_name = "recharge"
            y_name = "surflow_areas"
            # xn = 1e-6
            # xx = 1e-2
            # yn = 1e-3
            # yx = 1e1
            ax = axs1
            x = Smod[x_name]*1000
            y = Smod[y_name]
            c = Smod.index.month
            wy = pd.Series(x.index.month).replace([10,11,12,1,2,3,4,5,6,7,8,9],
                                                    [1,2,3,4,5,6,7,8,9,10,11,12])

            ax.set_xscale('log')
            # ax.set_yscale('log')
            ax.set_xlabel('R [mm/month]')
            ax.set_ylabel('$A_{sat}$ [%]')
            ax.set_xlim(1e-3, 10)
            ax.set_ylim(0, 15)
            # ax.set_yscale('log')
            ax.set_yticks(np.arange(0,15+1,5))
            
            xi = x.groupby([lambda x: x.month]).mean()
            yi = y.groupby([lambda y: y.month]).mean()

            scat = ax.scatter(x, y, c=wy, cmap='jet', marker="o", 
                              s=10, vmin=1, vmax=12, alpha=0.75, ec='none', zorder=-1)

            xiline = xi.append(xi.iloc[[0]])
            xiline.index = np.arange(1,14,1)
            yiline = yi.append(yi.iloc[[0]])
            yiline.index = np.arange(1,14,1)
            ax.plot(xiline, yiline, linestyle = '-', lw=1.5, color='k', zorder=0)

            wyi = np.arange(1,12+1,1)
            compt = 2
            for k in wyi:
                ax.annotate(k,(xi[k],yi[k]), family='sans-serif', fontsize=5, 
                             color='black', weight="bold", ha='center', va='center',
                             zorder=compt)
                ax.plot(xi[k], yi[k], marker="o", lw=2, markersize=9, markeredgecolor='black', 
                           markerfacecolor='white', markeredgewidth=1,
                           linestyle = 'None', zorder=compt)
                compt+=1

            xe = pd.DataFrame()
            xe['q25'] = (x.groupby(x.index.month).quantile(0.25))
            xe['q75'] = (x.groupby(x.index.month).quantile(0.75))
    
            ye = pd.DataFrame()
            ye['q25'] = (y.groupby(y.index.month).quantile(0.25))
            ye['q75'] = (y.groupby(y.index.month).quantile(0.75))
            
            ax.errorbar(xi, yi,
                          yerr=np.vstack([yi-ye.q25, ye.q75-yi]),
                          xerr=np.vstack([xi-xe.q25, xe.q75-xi]),
                          ecolor = 'black', fmt = 'none', capsize = 1, elinewidth=0.5, 
                          capthick=0.5, zorder=1)
            
            # fig1.savefig(figsim_folder+watershed_name+'_recharge_sat'+'.png', dpi=300, bbox_inches='tight')
            
            base_name = figsim_folder+'fig07a/'
            spec_name = watershed_name+'_hysteresis_sat_delta'
            # fig3.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight') 

            base_name = figsim_folder+'fig07a/'
            spec_name = watershed_name+'_hysteresis_sat_loop'
            # fig1.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight') 

#%% 7a - REC-DIS HYSTERESIS

from scipy.stats import binned_statistic

typ = 'calibr-t3'

# Things
time_step = 'M'
sim_state = 'transient'
var = 'REC'
scan = 'outflow_drain'
# scan = 'seepage_areas'

# Colored
mod_list = ['REA']
sce_list = ['historic']
sce_cmap = ["Greys"]
sce_color = ["k"]
cmap_dict = dict(zip(sce_list, sce_cmap))
color_dict = dict(zip(sce_list, sce_color))

c = ['forestgreen','orchid']
dict_c = dict(zip(watershed_names, c))

# Hysteres
temporal = False
space = 0
norm = False

watershed_names = ['Canut','Nancon']

# x_name = 'outflow_drain'
x_name = 'recharge'
# y_name = 'surflow_areas'
# y_name = 'intermit_areas'
# y_name = 'prop_ratio'
# y_name = 'perenn_areas'
y_name = 'outflow_drain'
xmin = []
xmax = []
ymin = []
ymax = []


# fig3, ax3 = plt.subplots(1,1, figsize=(3,3))

# fig2, axs2 = plt.subplots(1,1, figsize=(3,3))

# fig3, ax3 = plt.subplots(1,1, figsize=(3,3))

for watershed_name in watershed_names :
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = 'k'
        
    for mod in mod_list:
        
        # fig1, axs1 = plt.subplots(1,1, figsize=(5,5))
        # xn = 0.1
        # xx = 100
        # yn = 0.1
        # yx = 100
        # ax = axs1
        # ax.set_title(mod)
        # ax.set_aspect('equal', adjustable='box')

        for sce in sce_list:
            
            simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+sce+'*')
            simul = simul_list[0]
            
            # if sce == 'historic':
            #     simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+'RCP8.5'+'*')
            #     simul = simul_list[0]
                
            model_name = simul.split('\\')[-1]
            Sy = float(model_name.split('_')[3].split('-')[0]) # %
            K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
            E = float(model_name.split('_')[3].split('-')[2]) # m
            D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
            params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
            Smod_path = simul+'/_watershed/_simulated_results.csv'            
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            Smod['prop_ratio'] = Smod.intermit_areas / Smod.perenn_areas
            
            Smod['outflow_drain'] = Smod['outflow_drain'] * 1000
            
            Smod = select_period(Smod, 1960, 2019)

            Qmod = Smod[scan] 
          
            Qmod = Qmod # mm/months
            Qmod = Qmod.squeeze()    
            Cmod = Smod['recharge'] # mm/months
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
            
            hyst = Hysteresis(DFmod, watershed_name)
            hyst.prepare_xy_raw()
            hyst.compute_xy_metrics(temporal=temporal, space=space, norm=norm)
            
            columns_x = hyst.xrecapl.columns
            columns_y = hyst.yrecapl.columns
            
            n = len(columns_x)
            cmap = cmap_dict[sce]
            cmap_color = plt.get_cmap(cmap)(np.linspace(0, 1, n))
            color = color_dict[sce]
                        
            print('area='+str(hyst.area))
            print('slope='+str(hyst.slope))
            print('hi='+str(hyst.hi))
            print('q0='+str(hyst.q0))
            
            
            
            if watershed_name == 'Nancon':
                coul = 'orchid'
                mark = 'o'
                cmaplist = ['orchid','darkmagenta']
                import colorcet as cc
                # cmaplist[-1] = (.5, .5, .5, 1.0) # first value
                cmap = mpl.colors.LinearSegmentedColormap.from_list(
                    'Custom cmap', cmaplist)
                cmapping = 'spring'
                cmapping = cmap
            if watershed_name == 'Canut':
                coul = 'forestgreen'
                mark = 'o'
                cmaplist = ['greenyellow','green']
                import colorcet as cc
                # cmaplist[-1] = (.5, .5, .5, 1.0) # first value
                cmap = mpl.colors.LinearSegmentedColormap.from_list(
                    'Custom cmap', cmaplist)
                cmapping = 'spring'
                cmapping = cmap
                
            x = hyst.x.diff()*1000
            y = hyst.y.diff()
            c = Smod.index.month
            wy = pd.Series(x.index.month).replace([10,11,12,1,2,3,4,5,6,7,8,9],
                                                    [1,2,3,4,5,6,7,8,9,10,11,12])

            xi = hyst.x.groupby([lambda x: x.month]).mean() *1000
            yi = hyst.y.groupby([lambda y: y.month]).mean()
            
            xiline = xi.append(xi.iloc[[0]])
            xiline.index = np.arange(1,14,1)
            yiline = yi.append(yi.iloc[[0]])
            yiline.index = np.arange(1,14,1)
            
            
            # year = 2018
            # spe_year_x = select_period(x, year, year)
            # spe_year_y = select_period(y, year, year)
            # xiline_spe = spe_year_x.append(spe_year_x.iloc[[0]])
            # xiline_spe.index = np.arange(1,14,1)
            # yiline_spe = spe_year_y.append(spe_year_y.iloc[[0]])
            # yiline_spe.index = np.arange(1,14,1)
            # ax3.plot(xiline_spe, yiline_spe, linestyle = '-', lw=1.5, color='red', zorder=0)
            # year = 2002
            # spe_year_x = select_period(x, year, year)
            # spe_year_y = select_period(y, year, year)
            # xiline_spe = spe_year_x.append(spe_year_x.iloc[[0]])
            # xiline_spe.index = np.arange(1,14,1)
            # yiline_spe = spe_year_y.append(spe_year_y.iloc[[0]])
            # yiline_spe.index = np.arange(1,14,1)
            # ax3.plot(xiline_spe, yiline_spe, linestyle = '-', lw=1.5, color='blue', zorder=0)
            
            
            # xt = xiline.diff()
            # yt = yiline.diff()
            
            ##################################################################
            
            fig3, ax3 = plt.subplots(1,1, figsize=(3,3))

            cmapping = 'jet'
            ax3.scatter((x) , (y), c=wy, marker=mark, cmap=cmapping,
                        s=10, vmin=1, vmax=12, alpha=0.75, ec='none', lw=0.2, zorder=-1)
            # ax3.scatter(xt, yt)
            
            xi = xiline.diff()
            xi.iloc[0] = xi.iloc[-1]
            xi = xi[:-1]
            yi = yiline.diff()
            yi.iloc[0] = yi.iloc[-1]
            yi = yi[:-1]
                      
            # ax3.plot(xi, yi, linestyle = '-', lw=1.5, color=coul, zorder=0)

            wyi = np.arange(1,12+1,1)
            wyi = pd.Series(wyi).replace([10,11,12,1,2,3,4,5,6,7,8,9],
                                         [1,2,3,4,5,6,7,8,9,10,11,12])
            
            ax3.scatter(xi, yi, c=wyi, marker=mark, cmap=cmapping,
                        s=35, vmin=1, vmax=12, alpha=1, 
                        ec='k', lw = 0.5, zorder=1)

            cl = mpl.cm.jet(np.linspace(0,1,len(wyi)))
            compt = 2
            wyi = np.arange(1,12+1,1)
            for k in wyi:
                ax3.annotate(k,(xi[k],yi[k]), family='sans-serif',
                             fontsize=5, 
                              color='black', weight="bold", ha='center', va='center',
                              zorder=compt)
                ax3.plot(xi[k], yi[k], marker=mark, lw=2, markersize=9,
                          markeredgecolor='black', 
                            markerfacecolor='white', markeredgewidth=1,
                            linestyle = 'None', zorder=compt) # cl[k-1]
                compt+=1
            
            ax3.set_axisbelow(True)
            # ax.grid(zorder=-1000)
            ax3.xaxis.grid(color='gray', zorder=-1)
            ax3.yaxis.grid(color='gray', zorder=-1)
            
            ax3.axhline(y=0, color='k', zorder=0)
            ax3.axvline(x=0, color='k', zorder=0)
            ax3.set_xlim(-2, 2)
            ax3.set_ylim(-4, 4)
            
            ax3.set_xlabel('\u0394R [mm/month]')
            ax3.set_ylabel('\u0394Q [mm/month]')
            
            ax3.set_xticks(np.arange(-2, 2 + 0.1, 1))
            ax3.set_yticks(np.arange(-4, 4 + 0.1, 2))
                      
            dfevol = hyst.dfmet.iloc[:-1]
            dfevol = dfevol.set_index(pd.to_datetime(dfevol.index, format='%Y'))
           
            xe = pd.DataFrame()
            xe['q25'] = (x.groupby(x.index.month).quantile(0.25))
            xe['q75'] = (x.groupby(x.index.month).quantile(0.75))
    
            ye = pd.DataFrame()
            ye['q25'] = (y.groupby(y.index.month).quantile(0.25))
            ye['q75'] = (y.groupby(y.index.month).quantile(0.75))
            
            ax3.errorbar(xi, yi,
                          yerr=np.vstack([yi-ye.q25, ye.q75-yi]),
                          xerr=np.vstack([xi-xe.q25, xe.q75-xi]),
                          ecolor = 'black', fmt = 'none', capsize = 1, elinewidth=0.5, 
                          capthick=0.5, zorder=1)
            
            xiline = xi.append(xi.iloc[[0]])
            xiline.index = np.arange(1,14,1)
            yiline = yi.append(yi.iloc[[0]])
            yiline.index = np.arange(1,14,1)
            ax3.plot(xiline, yiline, linestyle = '-', lw=1.5, color='k', zorder=0)
 
           
            # fig3.savefig(figsim_folder+watershed_name+'_delta_saturation'+'.png', dpi=300, bbox_inches='tight')
 
            ###################################################################

            fig1, axs1 = plt.subplots(1,1, figsize=(3,3))
            x_name = "recharge"
            y_name = "outflow_drain"
            # xn = 1e-6
            # xx = 1e-2
            # yn = 1e-3
            # yx = 1e1
            ax = axs1
            x = Smod[x_name]*1000
            y = Smod[y_name]
            c = Smod.index.month
            wy = pd.Series(x.index.month).replace([10,11,12,1,2,3,4,5,6,7,8,9],
                                                    [1,2,3,4,5,6,7,8,9,10,11,12])

            ax.set_xscale('log')
            ax.set_yscale('log')
            ax.set_xlabel('R [mm/month]')
            ax.set_ylabel('Q [mm/month]')
            ax.set_xlim(1e-3, 10)
            ax.set_ylim(0.01, 10)
            # ax.set_yscale('log')
            # ax.set_yticks(np.arange(2,11,2))
            
            xi = x.groupby([lambda x: x.month]).mean()
            yi = y.groupby([lambda y: y.month]).mean()

            scat = ax.scatter(x, y, c=wy, cmap='jet', marker="o", 
                              s=10, vmin=1, vmax=12, alpha=0.75, ec='none', zorder=-1)

            xiline = xi.append(xi.iloc[[0]])
            xiline.index = np.arange(1,14,1)
            yiline = yi.append(yi.iloc[[0]])
            yiline.index = np.arange(1,14,1)
            ax.plot(xiline, yiline, linestyle = '-', lw=1.5, color='k', zorder=0)

            wyi = np.arange(1,12+1,1)
            compt = 2
            for k in wyi:
                ax.annotate(k,(xi[k],yi[k]), family='sans-serif', fontsize=5, 
                             color='black', weight="bold", ha='center', va='center',
                             zorder=compt)
                ax.plot(xi[k], yi[k], marker="o", lw=2, markersize=9, markeredgecolor='black', 
                           markerfacecolor='white', markeredgewidth=1,
                           linestyle = 'None', zorder=compt)
                compt+=1

            xe = pd.DataFrame()
            xe['q25'] = (x.groupby(x.index.month).quantile(0.25))
            xe['q75'] = (x.groupby(x.index.month).quantile(0.75))
    
            ye = pd.DataFrame()
            ye['q25'] = (y.groupby(y.index.month).quantile(0.25))
            ye['q75'] = (y.groupby(y.index.month).quantile(0.75))
            
            ax.errorbar(xi, yi,
                          yerr=np.vstack([yi-ye.q25, ye.q75-yi]),
                          xerr=np.vstack([xi-xe.q25, xe.q75-xi]),
                          ecolor = 'black', fmt = 'none', capsize = 1, elinewidth=0.5, 
                          capthick=0.5, zorder=1)
            
            # fig1.savefig(figsim_folder+watershed_name+'_recharge_sat'+'.png', dpi=300, bbox_inches='tight')
            
            base_name = figsim_folder+'fig07a/'
            spec_name = watershed_name+'_hysteresis_dis_delta'
            fig3.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight') 

            base_name = figsim_folder+'fig07a/'
            spec_name = watershed_name+'_hysteresis_dis_loop'
            fig1.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight') 

#%% NOT - REC-DIS RELATION

from scipy.stats import binned_statistic

typ = 'calibr-t3'

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

c = ['forestgreen','darkmagenta']
dict_c = dict(zip(watershed_names, c))

# Hysteres
temporal = False
space = 0
norm = False

watershed_names = ['Canut','Nancon']

# x_name = 'outflow_drain'
x_name = 'recharge'
y_name = 'surflow_areas'
# y_name = 'intermit_areas'
# y_name = 'prop_ratio'
# y_name = 'perenn_areas'
# y_name = 'outflow_drain'
xmin = []
xmax = []
ymin = []
ymax = []

scan = 'outflow_drain'

# fig, axs = plt.subplots(1,4, figsize=(14,3))
# axs = axs.ravel()
# fig3, axs3 = plt.subplots(1,4, figsize=(14,3))
# axs3 = axs3.ravel()

xy_list = [['recharge','outflow_drain']]

fig, axs = plt.subplots(2,1, figsize=(3.5,6))
axs = axs.ravel()

for watershed_name in watershed_names :
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = 'k'
        
    for mod in mod_list:
        
        # fig1, axs1 = plt.subplots(1,1, figsize=(5,5))
        # xn = 0.1
        # xx = 100
        # yn = 0.1
        # yx = 100
        # ax = axs1
        # ax.set_title(mod)
        # ax.set_aspect('equal', adjustable='box')

        for sce in sce_list:
            
            simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+sce+'*')
            simul = simul_list[0]
            
            # if sce == 'historic':
            #     simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+'RCP8.5'+'*')
            #     simul = simul_list[0]
                
            model_name = simul.split('\\')[-1]
            Sy = float(model_name.split('_')[3].split('-')[0]) # %
            K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
            E = float(model_name.split('_')[3].split('-')[2]) # m
            D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
            params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
            Smod_path = simul+'/_watershed/_simulated_results.csv'            
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            Smod['prop_ratio'] = Smod.intermit_areas / Smod.perenn_areas
            
            Smod = select_period(Smod, 1960, 2019)
            Smod['groundwater_storage'] = Smod['groundwater_storage']/(Smod['groundwater_storage'].mean())
            
            
            Qmod = Smod[scan] 
          
            Qmod = Qmod # mm/months
            Qmod = Qmod.squeeze()    
            Cmod = Smod['recharge'] # mm/months
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
            
            hyst = Hysteresis(DFmod, watershed_name)
            hyst.prepare_xy_raw()
            hyst.compute_xy_metrics(temporal=temporal, space=space, norm=norm)
            
            columns_x = hyst.xrecapl.columns
            columns_y = hyst.yrecapl.columns
            
            n = len(columns_x)
            cmap = cmap_dict[sce]
            cmap_color = plt.get_cmap(cmap)(np.linspace(0, 1, n))
            color = color_dict[sce]
                        
            print('area='+str(hyst.area))
            print('slope='+str(hyst.slope))
            print('hi='+str(hyst.hi))
            print('q0='+str(hyst.q0))
            
            dfevol = hyst.dfmet.iloc[:-1]
            dfevol = dfevol.set_index(pd.to_datetime(dfevol.index, format='%Y'))
            
            cpax = 0
            
            for xy in xy_list:
                                
                # print(compt)
            
                ###############################################################
                ax = axs[0]
                x = Smod[xy[0]] *1000
                y = Smod[xy[1]] *1000
                c = Smod.index.month
                wy = pd.Series(x.index.month).replace([10,11,12,1,2,3,4,5,6,7,8,9],
                                                        [1,2,3,4,5,6,7,8,9,10,11,12])
                ax.set_xscale('log')
                ax.set_yscale('log')
                ax.set_xlabel('R [mm/month]')
                ax.set_ylabel('Q [mm/month]')
                # ax.set_xlabel(xy[0])
                # ax.set_ylabel(xy[1])
                ax.set_xlim(1e-2, 10)
                ax.set_ylim(1e-2, 10)
                xi = x.groupby([lambda x: x.month]).mean()
                yi = y.groupby([lambda y: y.month]).mean()
                cmapping = mpl.colors.ListedColormap(dict_c[watershed_name])
                scat = ax.scatter(x, y, c=wy, cmap=cmapping, marker="o", 
                                  s=5, vmin=1, vmax=12, alpha=0.75, ec='none', zorder=-1)
                xiline = xi.append(xi.iloc[[0]])
                xiline.index = np.arange(1,14,1)
                yiline = yi.append(yi.iloc[[0]])
                yiline.index = np.arange(1,14,1)
                ax.plot(xiline, yiline, linestyle = '-', lw=1.5, color='k', zorder=0)
                wyi = np.arange(1,12+1,1)
                compt = 2
                for k in wyi:
                    ax.annotate(k,(xi[k],yi[k]), family='sans-serif', fontsize=4, 
                                 color=dict_c[watershed_name], weight="bold", ha='center', va='center',
                                 zorder=compt)
                    ax.plot(xi[k], yi[k], marker="o", lw=2, markersize=7, markeredgecolor='black', 
                               markerfacecolor='white', markeredgewidth=1,
                               linestyle = 'None', zorder=compt)
                    compt+=1
                xe = pd.DataFrame()
                xe['q25'] = (x.groupby(x.index.month).quantile(0.25))
                xe['q75'] = (x.groupby(x.index.month).quantile(0.75))        
                ye = pd.DataFrame()
                ye['q25'] = (y.groupby(y.index.month).quantile(0.25))
                ye['q75'] = (y.groupby(y.index.month).quantile(0.75))                
                # ax.errorbar(xi, yi,
                #              yerr=np.vstack([yi-ye.q25, ye.q75-yi]),
                #              xerr=np.vstack([xi-xe.q25, xe.q75-xi]),
                #              ecolor = 'black', fmt = 'none', capsize = 1, elinewidth=0.5, 
                #              capthick=0.5, zorder=1)               
   
                ###############################################################
                ax = axs[1]                
                x = (Smod[xy[0]]).diff() *1000
                y = Smod[xy[1]].diff() *1000
                c = Smod.index.month
                wy = pd.Series(x.index.month).replace([10,11,12,1,2,3,4,5,6,7,8,9],
                                                        [1,2,3,4,5,6,7,8,9,10,11,12])
                xi = x.groupby([lambda x: x.month]).mean()
                yi = y.groupby([lambda y: y.month]).mean()
                xiline = xi.append(xi.iloc[[0]])
                xiline.index = np.arange(1,14,1)
                yiline = yi.append(yi.iloc[[0]])
                yiline.index = np.arange(1,14,1)            
                # year = 2018
                # spe_year_x = select_period(x, year, year)
                # spe_year_y = select_period(y, year, year)
                # xiline_spe = spe_year_x.append(spe_year_x.iloc[[0]])
                # xiline_spe.index = np.arange(1,14,1)
                # yiline_spe = spe_year_y.append(spe_year_y.iloc[[0]])
                # yiline_spe.index = np.arange(1,14,1)
                # ax3.plot(xiline_spe, yiline_spe, linestyle = '-', lw=1.5, color='red', zorder=0)
                # cmapping = 'jet'
                cmapping = mpl.colors.ListedColormap(dict_c[watershed_name])
                ax.scatter((x) , (y), c=wy, marker='o', cmap=cmapping,
                            s=5, vmin=1, vmax=12, alpha=0.75, ec='none', lw=0.2, zorder=10)
                xi = xiline.diff()
                xi.iloc[0] = xi.iloc[-1]
                xi = xi[:-1]
                yi = yiline.diff()
                yi.iloc[0] = yi.iloc[-1]
                yi = yi[:-1]        
                wyi = np.arange(1,12+1,1)
                wyi = pd.Series(wyi).replace([10,11,12,1,2,3,4,5,6,7,8,9],
                                             [1,2,3,4,5,6,7,8,9,10,11,12])
                # ax.scatter(xi, yi, c=wyi, marker='o', cmap=cmapping,
                #             s=35, vmin=1, vmax=12, alpha=1, 
                #             ec='k', lw = 0.5)
                cl = mpl.cm.jet(np.linspace(0,1,len(wyi)))
                compt = 2
                wyi = np.arange(1,12+1,1)
                # for k in wyi:
                #     ax.annotate(k,(xi[k],yi[k]), family='sans-serif',
                #                   fontsize=4, 
                #                   color='black', weight="bold", ha='center', va='center',
                #                   zorder=compt)
                #     ax.plot(xi[k], yi[k], marker='o', lw=2, markersize=7,
                #               markeredgecolor='black', 
                #                 markerfacecolor='white', markeredgewidth=1,
                #                 linestyle = 'None', zorder=compt) # cl[k-1]
                #     compt+=1
                ax.set_axisbelow(True)
                # ax.grid(zorder=-1000)
                ax.xaxis.grid(color='gray', zorder=-1)
                ax.yaxis.grid(color='gray', zorder=-1)
                
                ax.axhline(y=0, color='k', zorder=2)
                ax.axvline(x=0, color='k', zorder=2)
                ax.set_ylim(-4, 4)
                ax.set_xlim(-4, 4)
                ax.set_xlabel('\u0394R [mm/month]')
                ax.set_ylabel('\u0394Q [mm/month]')
                # ax3.set_xticks(np.arange(-2, 2 + 0.1, 1))
                # ax3.set_yticks(np.arange(-4, 4 + 0.1, 2))
                cpax+=1
      
fig.tight_layout()

base_name = figsim_folder+'fig07/'
spec_name = watershed_name+'_REC-DIS'
fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight') 

#%% NOT - REC-SAT RELATION

from scipy.stats import binned_statistic

typ = 'calibr-t3'

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

c = ['forestgreen','darkmagenta']
dict_c = dict(zip(watershed_names, c))

# Hysteres
temporal = False
space = 0
norm = False

watershed_names = ['Canut','Nancon']

# x_name = 'outflow_drain'
x_name = 'recharge'
y_name = 'surflow_areas'
# y_name = 'intermit_areas'
# y_name = 'prop_ratio'
# y_name = 'perenn_areas'
# y_name = 'outflow_drain'
xmin = []
xmax = []
ymin = []
ymax = []

scan = 'outflow_drain'

# fig, axs = plt.subplots(1,4, figsize=(14,3))
# axs = axs.ravel()
# fig3, axs3 = plt.subplots(1,4, figsize=(14,3))
# axs3 = axs3.ravel()

xy_list = [['recharge','surflow_areas']]

fig, axs = plt.subplots(2,1, figsize=(3.5,6))
axs = axs.ravel()

for watershed_name in watershed_names :
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = 'k'
        
    for mod in mod_list:
        
        # fig1, axs1 = plt.subplots(1,1, figsize=(5,5))
        # xn = 0.1
        # xx = 100
        # yn = 0.1
        # yx = 100
        # ax = axs1
        # ax.set_title(mod)
        # ax.set_aspect('equal', adjustable='box')

        for sce in sce_list:
            
            simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+sce+'*')
            simul = simul_list[0]
            
            # if sce == 'historic':
            #     simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+'RCP8.5'+'*')
            #     simul = simul_list[0]
                
            model_name = simul.split('\\')[-1]
            Sy = float(model_name.split('_')[3].split('-')[0]) # %
            K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
            E = float(model_name.split('_')[3].split('-')[2]) # m
            D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
            params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
            Smod_path = simul+'/_watershed/_simulated_results.csv'            
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            Smod['prop_ratio'] = Smod.intermit_areas / Smod.perenn_areas
            
            Smod = select_period(Smod, 1960, 2019)
            Smod['groundwater_storage'] = Smod['groundwater_storage']/(Smod['groundwater_storage'].mean())

            Qmod = Smod[scan] 
          
            Qmod = Qmod # mm/months
            Qmod = Qmod.squeeze()    
            Cmod = Smod['recharge'] # mm/months
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
            
            hyst = Hysteresis(DFmod, watershed_name)
            hyst.prepare_xy_raw()
            hyst.compute_xy_metrics(temporal=temporal, space=space, norm=norm)
            
            columns_x = hyst.xrecapl.columns
            columns_y = hyst.yrecapl.columns
            
            n = len(columns_x)
            cmap = cmap_dict[sce]
            cmap_color = plt.get_cmap(cmap)(np.linspace(0, 1, n))
            color = color_dict[sce]
                        
            print('area='+str(hyst.area))
            print('slope='+str(hyst.slope))
            print('hi='+str(hyst.hi))
            print('q0='+str(hyst.q0))
            
            dfevol = hyst.dfmet.iloc[:-1]
            dfevol = dfevol.set_index(pd.to_datetime(dfevol.index, format='%Y'))
            
            cpax = 0
            
            for xy in xy_list:
                                
                # print(compt)
            
                ###############################################################
                ax = axs[0]
                x = Smod[xy[0]] *1000
                y = Smod[xy[1]]
                c = Smod.index.month
                wy = pd.Series(x.index.month).replace([10,11,12,1,2,3,4,5,6,7,8,9],
                                                        [1,2,3,4,5,6,7,8,9,10,11,12])
                ax.set_xscale('log')
                # ax.set_yscale('log')
                ax.set_xlabel('R [mm/month]')
                ax.set_ylabel('$A_{sat}$ [%]')
                # ax.set_xlabel(xy[0])
                # ax.set_ylabel(xy[1])
                ax.set_xlim(1e-2, 10)
                ax.set_ylim(0, 15)
                ax.set_yticks(np.arange(0,15+1,5))
                xi = x.groupby([lambda x: x.month]).mean()
                yi = y.groupby([lambda y: y.month]).mean()
                cmapping = mpl.colors.ListedColormap(dict_c[watershed_name])
                scat = ax.scatter(x, y, c=wy, cmap=cmapping, marker="o", 
                                  s=5, vmin=1, vmax=12, alpha=0.75, ec='none', zorder=-1)
                xiline = xi.append(xi.iloc[[0]])
                xiline.index = np.arange(1,14,1)
                yiline = yi.append(yi.iloc[[0]])
                yiline.index = np.arange(1,14,1)
                ax.plot(xiline, yiline, linestyle = '-', lw=1.5, color='k', zorder=0)
                wyi = np.arange(1,12+1,1)
                compt = 2
                for k in wyi:
                    ax.annotate(k,(xi[k],yi[k]), family='sans-serif', fontsize=4, 
                                 color=dict_c[watershed_name], weight="bold", ha='center', va='center',
                                 zorder=compt)
                    ax.plot(xi[k], yi[k], marker="o", lw=2, markersize=7, markeredgecolor='black', 
                               markerfacecolor='white', markeredgewidth=1,
                               linestyle = 'None', zorder=compt)
                    compt+=1
                xe = pd.DataFrame()
                xe['q25'] = (x.groupby(x.index.month).quantile(0.25))
                xe['q75'] = (x.groupby(x.index.month).quantile(0.75))        
                ye = pd.DataFrame()
                ye['q25'] = (y.groupby(y.index.month).quantile(0.25))
                ye['q75'] = (y.groupby(y.index.month).quantile(0.75))                
                # ax.errorbar(xi, yi,
                #              yerr=np.vstack([yi-ye.q25, ye.q75-yi]),
                #              xerr=np.vstack([xi-xe.q25, xe.q75-xi]),
                #              ecolor = 'black', fmt = 'none', capsize = 1, elinewidth=0.5, 
                #              capthick=0.5, zorder=1)               
   
                ###############################################################
                ax = axs[1]                
                x = (Smod[xy[0]]).diff() *1000
                y = Smod[xy[1]].diff()
                c = Smod.index.month
                wy = pd.Series(x.index.month).replace([10,11,12,1,2,3,4,5,6,7,8,9],
                                                        [1,2,3,4,5,6,7,8,9,10,11,12])
                xi = x.groupby([lambda x: x.month]).mean()
                yi = y.groupby([lambda y: y.month]).mean()
                xiline = xi.append(xi.iloc[[0]])
                xiline.index = np.arange(1,14,1)
                yiline = yi.append(yi.iloc[[0]])
                yiline.index = np.arange(1,14,1)            
                # year = 2018
                # spe_year_x = select_period(x, year, year)
                # spe_year_y = select_period(y, year, year)
                # xiline_spe = spe_year_x.append(spe_year_x.iloc[[0]])
                # xiline_spe.index = np.arange(1,14,1)
                # yiline_spe = spe_year_y.append(spe_year_y.iloc[[0]])
                # yiline_spe.index = np.arange(1,14,1)
                # ax3.plot(xiline_spe, yiline_spe, linestyle = '-', lw=1.5, color='red', zorder=0)
                # cmapping = 'jet'
                cmapping = mpl.colors.ListedColormap(dict_c[watershed_name])
                ax.scatter((x) , (y), c=wy, marker='o', cmap=cmapping,
                            s=5, vmin=1, vmax=12, alpha=0.75, ec='none', lw=0.2, zorder=10)
                xi = xiline.diff()
                xi.iloc[0] = xi.iloc[-1]
                xi = xi[:-1]
                yi = yiline.diff()
                yi.iloc[0] = yi.iloc[-1]
                yi = yi[:-1]        
                wyi = np.arange(1,12+1,1)
                wyi = pd.Series(wyi).replace([10,11,12,1,2,3,4,5,6,7,8,9],
                                             [1,2,3,4,5,6,7,8,9,10,11,12])
                # ax.scatter(xi, yi, c=wyi, marker='o', cmap=cmapping,
                #             s=35, vmin=1, vmax=12, alpha=1, 
                #             ec='k', lw = 0.5)
                cl = mpl.cm.jet(np.linspace(0,1,len(wyi)))
                compt = 2
                wyi = np.arange(1,12+1,1)
                # for k in wyi:
                #     ax.annotate(k,(xi[k],yi[k]), family='sans-serif',
                #                   fontsize=4, 
                #                   color='black', weight="bold", ha='center', va='center',
                #                   zorder=compt)
                #     ax.plot(xi[k], yi[k], marker='o', lw=2, markersize=7,
                #               markeredgecolor='black', 
                #                 markerfacecolor='white', markeredgewidth=1,
                #                 linestyle = 'None', zorder=compt) # cl[k-1]
                #     compt+=1
                ax.set_axisbelow(True)
                # ax.grid(zorder=-1000)
                ax.xaxis.grid(color='gray', zorder=-1)
                ax.yaxis.grid(color='gray', zorder=-1)
                
                ax.axhline(y=0, color='k', zorder=2)
                ax.axvline(x=0, color='k', zorder=2)
                ax.set_ylim(-8, 8)
                ax.set_xlim(-4, 4)
                ax.set_xlabel('\u0394R [mm/month]')
                ax.set_ylabel('\u0394$A_{sat}$ [%]')
                # ax3.set_xticks(np.arange(-2, 2 + 0.1, 1))
                # ax3.set_yticks(np.arange(-4, 4 + 0.1, 2))
                cpax+=1
      
fig.tight_layout()
fig3.tight_layout()

base_name = figsim_folder+'fig07/'
spec_name = watershed_name+'_REC-SAT'
fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight') 

#%% 7b - DIS-SAT RELATION

from scipy.stats import binned_statistic

typ = 'calibr-t3'

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

c = ['forestgreen','darkmagenta']
cmaps = ['winter','spring']
# cmaps = ['YlGn','RdPu']
dict_c = dict(zip(watershed_names, c))
dict_cmap = dict(zip(watershed_names, cmaps))

# Hysteres
temporal = False
space = 0
norm = False

watershed_names = ['Canut','Nancon']

# fig, axs = plt.subplots(1,4, figsize=(14,3))
# axs = axs.ravel()
# fig3, axs3 = plt.subplots(1,4, figsize=(14,3))
# axs3 = axs3.ravel()

scan = 'outflow_drain'

xy_list = [['outflow_drain','surflow_areas']]

# fig, axs = plt.subplots(2,1, figsize=(3.5,6))
# axs = axs.ravel()

fig, ax = plt.subplots(1,1, figsize=(3.5,3.2))
# axs = axs.ravel()

for watershed_name in watershed_names :
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = 'k'
        
    for mod in mod_list:
        
        # fig1, axs1 = plt.subplots(1,1, figsize=(5,5))
        # xn = 0.1
        # xx = 100
        # yn = 0.1
        # yx = 100
        # ax = axs1
        # ax.set_title(mod)
        # ax.set_aspect('equal', adjustable='box')

        for sce in sce_list:
            
            simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+sce+'*')
            simul = simul_list[0]
            
            # if sce == 'historic':
            #     simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+'RCP8.5'+'*')
            #     simul = simul_list[0]
                
            model_name = simul.split('\\')[-1]
            Sy = float(model_name.split('_')[3].split('-')[0]) # %
            K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
            E = float(model_name.split('_')[3].split('-')[2]) # m
            D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
            params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
            Smod_path = simul+'/_watershed/_simulated_results.csv'            
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            Smod['prop_ratio'] = Smod.intermit_areas / Smod.perenn_areas
            
            Smod = select_period(Smod, 1960, 2019)
            # Smod['groundwater_storage'] = Smod['groundwater_storage']/(Smod['groundwater_storage'].mean())

            Qmod = Smod[scan] 
          
            Qmod = Qmod # mm/months
            Qmod = Qmod.squeeze()    
            Cmod = Smod['recharge'] # mm/months
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
            
            hyst = Hysteresis(DFmod, watershed_name)
            hyst.prepare_xy_raw()
            hyst.compute_xy_metrics(temporal=temporal, space=space, norm=norm)
            
            columns_x = hyst.xrecapl.columns
            columns_y = hyst.yrecapl.columns
            
            n = len(columns_x)
            cmap = cmap_dict[sce]
            cmap_color = plt.get_cmap(cmap)(np.linspace(0, 1, n))
            color = color_dict[sce]
                        
            print('area='+str(hyst.area))
            print('slope='+str(hyst.slope))
            print('hi='+str(hyst.hi))
            print('q0='+str(hyst.q0))
            
            dfevol = hyst.dfmet.iloc[:-1]
            dfevol = dfevol.set_index(pd.to_datetime(dfevol.index, format='%Y'))
            
            cpax = 0
            
            for xy in xy_list:
                                
                # print(compt)
            
                ###############################################################
                # ax = axs[0]
                x = Smod[xy[0]] *1000
                y = Smod[xy[1]]
                c = Smod.index.month
                wy = pd.Series(x.index.month).replace([10,11,12,1,2,3,4,5,6,7,8,9],
                                                        [1,2,3,4,5,6,7,8,9,10,11,12])
                ax.set_xscale('log')
                # ax.set_yscale('log')
                ax.set_xlabel('Q [mm/month]')
                ax.set_ylabel('$A_{sat}$ [%]')
                # ax.set_xlabel(xy[0])
                # ax.set_ylabel(xy[1])
                ax.set_xlim(1e-2, 10)
                ax.set_ylim(0, 15)
                ax.set_yticks(np.arange(0,15+1,5))
                xi = x.groupby([lambda x: x.month]).mean()
                yi = y.groupby([lambda y: y.month]).mean()
                # cmapping = mpl.colors.ListedColormap(dict_c[watershed_name])
                cmapping = dict_cmap[watershed_name]
                scat = ax.scatter(x, y, c=wy, cmap=cmapping, marker="o", 
                                  s=5, vmin=1, vmax=12, alpha=0.75, ec='none', zorder=-1)
                xiline = xi.append(xi.iloc[[0]])
                xiline.index = np.arange(1,14,1)
                yiline = yi.append(yi.iloc[[0]])
                yiline.index = np.arange(1,14,1)
                ax.plot(xiline, yiline, linestyle = '-', lw=1.5, color='k', zorder=0)
                wyi = np.arange(1,12+1,1)
                compt = 2
                for k in wyi:
                    ax.annotate(k,(xi[k],yi[k]), family='sans-serif', fontsize=4, 
                                 color='k', weight="bold", ha='center', va='center',
                                 zorder=compt)
                    ax.plot(xi[k], yi[k], marker="o", lw=2, markersize=7, markeredgecolor='black', 
                               markerfacecolor='white', markeredgewidth=1,
                               linestyle = 'None', zorder=compt)
                    compt+=1
                xe = pd.DataFrame()
                xe['q25'] = (x.groupby(x.index.month).quantile(0.25))
                xe['q75'] = (x.groupby(x.index.month).quantile(0.75))        
                ye = pd.DataFrame()
                ye['q25'] = (y.groupby(y.index.month).quantile(0.25))
                ye['q75'] = (y.groupby(y.index.month).quantile(0.75))                
                # ax.errorbar(xi, yi,
                #              yerr=np.vstack([yi-ye.q25, ye.q75-yi]),
                #              xerr=np.vstack([xi-xe.q25, xe.q75-xi]),
                #              ecolor = 'black', fmt = 'none', capsize = 1, elinewidth=0.5, 
                #              capthick=0.5, zorder=1)               
                
                ###############################################################
                '''
                ax = axs[1]                
                x = (Smod[xy[0]]).diff() *1000
                y = Smod[xy[1]].diff()
                c = Smod.index.month
                wy = pd.Series(x.index.month).replace([10,11,12,1,2,3,4,5,6,7,8,9],
                                                        [1,2,3,4,5,6,7,8,9,10,11,12])
                xi = x.groupby([lambda x: x.month]).mean()
                yi = y.groupby([lambda y: y.month]).mean()
                xiline = xi.append(xi.iloc[[0]])
                xiline.index = np.arange(1,14,1)
                yiline = yi.append(yi.iloc[[0]])
                yiline.index = np.arange(1,14,1)            
                # year = 2018
                # spe_year_x = select_period(x, year, year)
                # spe_year_y = select_period(y, year, year)
                # xiline_spe = spe_year_x.append(spe_year_x.iloc[[0]])
                # xiline_spe.index = np.arange(1,14,1)
                # yiline_spe = spe_year_y.append(spe_year_y.iloc[[0]])
                # yiline_spe.index = np.arange(1,14,1)
                # ax3.plot(xiline_spe, yiline_spe, linestyle = '-', lw=1.5, color='red', zorder=0)
                # cmapping = 'jet'
                cmapping = mpl.colors.ListedColormap(dict_c[watershed_name])
                ax.scatter((x) , (y), c=wy, marker='o', cmap=cmapping,
                            s=5, vmin=1, vmax=12, alpha=0.75, ec='none', lw=0.2, zorder=10)
                xi = xiline.diff()
                xi.iloc[0] = xi.iloc[-1]
                xi = xi[:-1]
                yi = yiline.diff()
                yi.iloc[0] = yi.iloc[-1]
                yi = yi[:-1]        
                wyi = np.arange(1,12+1,1)
                wyi = pd.Series(wyi).replace([10,11,12,1,2,3,4,5,6,7,8,9],
                                             [1,2,3,4,5,6,7,8,9,10,11,12])
                # ax.scatter(xi, yi, c=wyi, marker='o', cmap=cmapping,
                #             s=35, vmin=1, vmax=12, alpha=1, 
                #             ec='k', lw = 0.5)
                cl = mpl.cm.jet(np.linspace(0,1,len(wyi)))
                compt = 2
                wyi = np.arange(1,12+1,1)
                # for k in wyi:
                #     ax.annotate(k,(xi[k],yi[k]), family='sans-serif',
                #                   fontsize=4, 
                #                   color='black', weight="bold", ha='center', va='center',
                #                   zorder=compt)
                #     ax.plot(xi[k], yi[k], marker='o', lw=2, markersize=7,
                #               markeredgecolor='black', 
                #                 markerfacecolor='white', markeredgewidth=1,
                #                 linestyle = 'None', zorder=compt) # cl[k-1]
                #     compt+=1
                ax.set_axisbelow(True)
                # ax.grid(zorder=-1000)
                ax.xaxis.grid(color='gray', zorder=-1)
                ax.yaxis.grid(color='gray', zorder=-1)
                
                ax.axhline(y=0, color='k', zorder=2)
                ax.axvline(x=0, color='k', zorder=2)
                ax.set_ylim(-4, 4)
                ax.set_xlim(-4, 4)
                ax.set_xlabel('\u0394Q [mm/month]')
                ax.set_ylabel('\u0394($A_{int}$ / $A_{per}$) [-]')
                # ax3.set_xticks(np.arange(-2, 2 + 0.1, 1))
                # ax3.set_yticks(np.arange(-4, 4 + 0.1, 2))
                cpax+=1
                '''
      
fig.tight_layout()
# fig3.tight_layout()

base_name = figsim_folder+'fig07b/'
spec_name = str(watershed_names)+'_DIS-SAT'
fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight') 

#%% 7b - DIS-RAT RELATION

from scipy.stats import binned_statistic

typ = 'calibr-t6'

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

c = ['forestgreen','darkmagenta']
cmaps = ['winter','spring']
# cmaps = ['YlGn','RdPu']
dict_c = dict(zip(watershed_names, c))
dict_cmap = dict(zip(watershed_names, cmaps))

# Hysteres
temporal = False
space = 0
norm = False

watershed_names = ['Canut','Nancon']

# fig, axs = plt.subplots(1,4, figsize=(14,3))
# axs = axs.ravel()
# fig3, axs3 = plt.subplots(1,4, figsize=(14,3))
# axs3 = axs3.ravel()

scan = 'outflow_drain'

xy_list = [['outflow_drain','prop_ratio']]

# fig, axs = plt.subplots(2,1, figsize=(3.5,6))
# axs = axs.ravel()

fig, ax = plt.subplots(1,1, figsize=(3.5,3.2))
# axs = axs.ravel()

for watershed_name in watershed_names :
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = 'k'
        
    for mod in mod_list:
        
        # fig1, axs1 = plt.subplots(1,1, figsize=(5,5))
        # xn = 0.1
        # xx = 100
        # yn = 0.1
        # yx = 100
        # ax = axs1
        # ax.set_title(mod)
        # ax.set_aspect('equal', adjustable='box')

        for sce in sce_list:
            
            simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+sce+'*')
            simul = simul_list[0]
            
            # if sce == 'historic':
            #     simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+'RCP8.5'+'*')
            #     simul = simul_list[0]
                
            model_name = simul.split('\\')[-1]
            Sy = float(model_name.split('_')[3].split('-')[0]) # %
            K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
            E = float(model_name.split('_')[3].split('-')[2]) # m
            D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
            params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
            Smod_path = simul+'/_watershed/_simulated_results.csv'            
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            Smod['prop_ratio'] = Smod.intermit_areas / Smod.perenn_areas
            Smod['prop_ratio'] = Smod.intermit_areas / Smod.surflow_areas
            
            Smod = select_period(Smod, 1960, 2019)
            # Smod['groundwater_storage'] = Smod['groundwater_storage']/(Smod['groundwater_storage'].mean())

            Qmod = Smod[scan] 
          
            Qmod = Qmod # mm/months
            Qmod = Qmod.squeeze()    
            Cmod = Smod['recharge'] # mm/months
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
            
            hyst = Hysteresis(DFmod, watershed_name)
            hyst.prepare_xy_raw()
            hyst.compute_xy_metrics(temporal=temporal, space=space, norm=norm)
            
            columns_x = hyst.xrecapl.columns
            columns_y = hyst.yrecapl.columns
            
            n = len(columns_x)
            cmap = cmap_dict[sce]
            cmap_color = plt.get_cmap(cmap)(np.linspace(0, 1, n))
            color = color_dict[sce]
                        
            print('area='+str(hyst.area))
            print('slope='+str(hyst.slope))
            print('hi='+str(hyst.hi))
            print('q0='+str(hyst.q0))
            
            dfevol = hyst.dfmet.iloc[:-1]
            dfevol = dfevol.set_index(pd.to_datetime(dfevol.index, format='%Y'))
            
            cpax = 0
            
            for xy in xy_list:
                                
                # print(compt)
            
                ###############################################################
                # ax = axs[0]
                x = Smod[xy[0]] *1000
                y = Smod[xy[1]]
                c = Smod.index.month
                wy = pd.Series(x.index.month).replace([10,11,12,1,2,3,4,5,6,7,8,9],
                                                        [1,2,3,4,5,6,7,8,9,10,11,12])
                ax.set_xscale('log')
                ax.set_yscale('log')
                ax.set_xlabel('Q [mm/month]')
                ax.set_ylabel('$A_{int}$ / $A_{per}$ [-]')
                # ax.set_xlabel(xy[0])
                # ax.set_ylabel(xy[1])
                ax.set_xlim(1e-2, 10)
                ax.set_ylim(1e-2, 10)
                xi = x.groupby([lambda x: x.month]).mean()
                yi = y.groupby([lambda y: y.month]).mean()
                # cmapping = mpl.colors.ListedColormap(dict_c[watershed_name])
                cmapping = dict_cmap[watershed_name]
                scat = ax.scatter(x, y, c=wy, cmap=cmapping, marker="o", 
                                  s=5, vmin=1, vmax=12, alpha=0.75, ec='none', zorder=-1)
                xiline = xi.append(xi.iloc[[0]])
                xiline.index = np.arange(1,14,1)
                yiline = yi.append(yi.iloc[[0]])
                yiline.index = np.arange(1,14,1)
                ax.plot(xiline, yiline, linestyle = '-', lw=1.5, color='k', zorder=0)
                wyi = np.arange(1,12+1,1)
                compt = 2
                for k in wyi:
                    ax.annotate(k,(xi[k],yi[k]), family='sans-serif', fontsize=4, 
                                 color='k', weight="bold", ha='center', va='center',
                                 zorder=compt)
                    ax.plot(xi[k], yi[k], marker="o", lw=2, markersize=7, markeredgecolor='black', 
                               markerfacecolor='white', markeredgewidth=1,
                               linestyle = 'None', zorder=compt)
                    compt+=1
                xe = pd.DataFrame()
                xe['q25'] = (x.groupby(x.index.month).quantile(0.25))
                xe['q75'] = (x.groupby(x.index.month).quantile(0.75))        
                ye = pd.DataFrame()
                ye['q25'] = (y.groupby(y.index.month).quantile(0.25))
                ye['q75'] = (y.groupby(y.index.month).quantile(0.75))                
                # ax.errorbar(xi, yi,
                #              yerr=np.vstack([yi-ye.q25, ye.q75-yi]),
                #              xerr=np.vstack([xi-xe.q25, xe.q75-xi]),
                #              ecolor = 'black', fmt = 'none', capsize = 1, elinewidth=0.5, 
                #              capthick=0.5, zorder=1)               
                
                ###############################################################
                '''
                ax = axs[1]                
                x = (Smod[xy[0]]).diff() *1000
                y = Smod[xy[1]].diff()
                c = Smod.index.month
                wy = pd.Series(x.index.month).replace([10,11,12,1,2,3,4,5,6,7,8,9],
                                                        [1,2,3,4,5,6,7,8,9,10,11,12])
                xi = x.groupby([lambda x: x.month]).mean()
                yi = y.groupby([lambda y: y.month]).mean()
                xiline = xi.append(xi.iloc[[0]])
                xiline.index = np.arange(1,14,1)
                yiline = yi.append(yi.iloc[[0]])
                yiline.index = np.arange(1,14,1)            
                # year = 2018
                # spe_year_x = select_period(x, year, year)
                # spe_year_y = select_period(y, year, year)
                # xiline_spe = spe_year_x.append(spe_year_x.iloc[[0]])
                # xiline_spe.index = np.arange(1,14,1)
                # yiline_spe = spe_year_y.append(spe_year_y.iloc[[0]])
                # yiline_spe.index = np.arange(1,14,1)
                # ax3.plot(xiline_spe, yiline_spe, linestyle = '-', lw=1.5, color='red', zorder=0)
                # cmapping = 'jet'
                cmapping = mpl.colors.ListedColormap(dict_c[watershed_name])
                ax.scatter((x) , (y), c=wy, marker='o', cmap=cmapping,
                            s=5, vmin=1, vmax=12, alpha=0.75, ec='none', lw=0.2, zorder=10)
                xi = xiline.diff()
                xi.iloc[0] = xi.iloc[-1]
                xi = xi[:-1]
                yi = yiline.diff()
                yi.iloc[0] = yi.iloc[-1]
                yi = yi[:-1]        
                wyi = np.arange(1,12+1,1)
                wyi = pd.Series(wyi).replace([10,11,12,1,2,3,4,5,6,7,8,9],
                                             [1,2,3,4,5,6,7,8,9,10,11,12])
                # ax.scatter(xi, yi, c=wyi, marker='o', cmap=cmapping,
                #             s=35, vmin=1, vmax=12, alpha=1, 
                #             ec='k', lw = 0.5)
                cl = mpl.cm.jet(np.linspace(0,1,len(wyi)))
                compt = 2
                wyi = np.arange(1,12+1,1)
                # for k in wyi:
                #     ax.annotate(k,(xi[k],yi[k]), family='sans-serif',
                #                   fontsize=4, 
                #                   color='black', weight="bold", ha='center', va='center',
                #                   zorder=compt)
                #     ax.plot(xi[k], yi[k], marker='o', lw=2, markersize=7,
                #               markeredgecolor='black', 
                #                 markerfacecolor='white', markeredgewidth=1,
                #                 linestyle = 'None', zorder=compt) # cl[k-1]
                #     compt+=1
                ax.set_axisbelow(True)
                # ax.grid(zorder=-1000)
                ax.xaxis.grid(color='gray', zorder=-1)
                ax.yaxis.grid(color='gray', zorder=-1)
                
                ax.axhline(y=0, color='k', zorder=2)
                ax.axvline(x=0, color='k', zorder=2)
                ax.set_ylim(-4, 4)
                ax.set_xlim(-4, 4)
                ax.set_xlabel('\u0394Q [mm/month]')
                ax.set_ylabel('\u0394($A_{int}$ / $A_{per}$) [-]')
                # ax3.set_xticks(np.arange(-2, 2 + 0.1, 1))
                # ax3.set_yticks(np.arange(-4, 4 + 0.1, 2))
                cpax+=1
                '''
      
fig.tight_layout()
# fig3.tight_layout()

base_name = figsim_folder+'fig07/'
spec_name = str(watershed_names)+'_DIS-RAT'
# fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight') 

#%% 7b - GWS-SAT RELATION

from scipy.stats import binned_statistic

typ = 'calibr-t3'

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

watershed_names = ['Canut','Nancon']

c = ['forestgreen','darkmagenta']
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

scan = 'ouflow_drain'

xy_list = [['groundwater_storage','surflow_areas']]

# fig, axs = plt.subplots(2,1, figsize=(3.5,6))
# axs = axs.ravel()

fig, ax = plt.subplots(1,1, figsize=(3.5,3.2))

for watershed_name in watershed_names :
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = 'k'
        
    for mod in mod_list:
        
        # fig1, axs1 = plt.subplots(1,1, figsize=(5,5))
        # xn = 0.1
        # xx = 100
        # yn = 0.1
        # yx = 100
        # ax = axs1
        # ax.set_title(mod)
        # ax.set_aspect('equal', adjustable='box')

        for sce in sce_list:
            
            simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+sce+'*')
            simul = simul_list[0]
            
            # if sce == 'historic':
            #     simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+'RCP8.5'+'*')
            #     simul = simul_list[0]
                
            model_name = simul.split('\\')[-1]
            Sy = float(model_name.split('_')[3].split('-')[0]) # %
            K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
            E = float(model_name.split('_')[3].split('-')[2]) # m
            D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
            params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
            Smod_path = simul+'/_watershed/_simulated_results.csv'            
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            Smod['prop_ratio'] = Smod.intermit_areas / Smod.perenn_areas
            
            Smod = select_period(Smod, 1960, 2019)
            # Smod['groundwater_storage'] = Smod['groundwater_storage']/(Smod['groundwater_storage'].mean())
            Smod['groundwater_storage'] = Smod['groundwater_storage']/1e6

            scan = 'outflow_drain'
            Qmod = Smod[scan] 
          
            Qmod = Qmod # mm/months
            Qmod = Qmod.squeeze()    
            Cmod = Smod['recharge'] # mm/months
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
            
            hyst = Hysteresis(DFmod, watershed_name)
            hyst.prepare_xy_raw()
            hyst.compute_xy_metrics(temporal=temporal, space=space, norm=norm)
            
            columns_x = hyst.xrecapl.columns
            columns_y = hyst.yrecapl.columns
            
            n = len(columns_x)
            cmap = cmap_dict[sce]
            cmap_color = plt.get_cmap(cmap)(np.linspace(0, 1, n))
            color = color_dict[sce]
                        
            print('area='+str(hyst.area))
            print('slope='+str(hyst.slope))
            print('hi='+str(hyst.hi))
            print('q0='+str(hyst.q0))
            
            dfevol = hyst.dfmet.iloc[:-1]
            dfevol = dfevol.set_index(pd.to_datetime(dfevol.index, format='%Y'))
            
            cpax = 0
            
            for xy in xy_list:
                                
                # print(compt)
            
                ###############################################################
                # ax = axs[0]
                x = Smod[xy[0]].diff() #/ Smod[xy[0]].mean()
                y = Smod[xy[1]]
                c = Smod.index.month
                wy = pd.Series(x.index.month).replace([10,11,12,1,2,3,4,5,6,7,8,9],
                                                        [1,2,3,4,5,6,7,8,9,10,11,12])
                # ax.set_xscale('log')
                # ax.set_yscale('log')
                ax.set_xlabel('$GW_{storage}$ normalized [-]')
                ax.set_ylabel('$A_{sat}$ [%]')
                # ax.set_xlabel(xy[0])
                # ax.set_ylabel(xy[1])
                # ax.set_xlim(0.5, 1.5)
                ax.set_ylim(0, 15)
                ax.set_yticks(np.arange(0,15+1,5))
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
                ax.plot(xiline, yiline, linestyle = '-', lw=1.5, color='k', zorder=0)
                wyi = np.arange(1,12+1,1)
                compt = 2
                for k in wyi:
                    ax.annotate(k,(xi[k],yi[k]), family='sans-serif', fontsize=4, 
                                 color='k', weight="bold", ha='center', va='center',
                                 zorder=compt)
                    ax.plot(xi[k], yi[k], marker="o", lw=2, markersize=7, markeredgecolor='black', 
                               markerfacecolor='white', markeredgewidth=1,
                               linestyle = 'None', zorder=compt)
                    compt+=1
                xe = pd.DataFrame()
                xe['q25'] = (x.groupby(x.index.month).quantile(0.25))
                xe['q75'] = (x.groupby(x.index.month).quantile(0.75))        
                ye = pd.DataFrame()
                ye['q25'] = (y.groupby(y.index.month).quantile(0.25))
                ye['q75'] = (y.groupby(y.index.month).quantile(0.75))                
                # ax.errorbar(xi, yi,
                #              yerr=np.vstack([yi-ye.q25, ye.q75-yi]),
                #              xerr=np.vstack([xi-xe.q25, xe.q75-xi]),
                #              ecolor = 'black', fmt = 'none', capsize = 1, elinewidth=0.5, 
                #              capthick=0.5, zorder=1)               

fig.tight_layout()

base_name = figsim_folder+'fig07b/'
spec_name = str(watershed_names)+'_GWS-SAT'
# fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight') 


xy_list = [['groundwater_storage','surflow_areas']]

fig, ax = plt.subplots(1,1, figsize=(3.5,3.2))

for watershed_name in watershed_names :
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = 'k'
        
    for mod in mod_list:
        
        # fig1, axs1 = plt.subplots(1,1, figsize=(5,5))
        # xn = 0.1
        # xx = 100
        # yn = 0.1
        # yx = 100
        # ax = axs1
        # ax.set_title(mod)
        # ax.set_aspect('equal', adjustable='box')

        for sce in sce_list:
            
            simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+sce+'*')
            simul = simul_list[0]
            
            # if sce == 'historic':
            #     simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+'RCP8.5'+'*')
            #     simul = simul_list[0]
                
            model_name = simul.split('\\')[-1]
            Sy = float(model_name.split('_')[3].split('-')[0]) # %
            K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
            E = float(model_name.split('_')[3].split('-')[2]) # m
            D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
            params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
            Smod_path = simul+'/_watershed/_simulated_results.csv'            
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            Smod['prop_ratio'] = Smod.intermit_areas / Smod.perenn_areas
            
            Smod = select_period(Smod, 1960, 2019)
            # Smod['groundwater_storage'] = Smod['groundwater_storage']/(Smod['groundwater_storage'].mean())
            Smod['groundwater_storage'] = Smod['groundwater_storage']/1e6

            scan = 'outflow_drain'
            Qmod = Smod[scan] 
          
            Qmod = Qmod # mm/months
            Qmod = Qmod.squeeze()    
            Cmod = Smod['recharge'] # mm/months
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
            
            hyst = Hysteresis(DFmod, watershed_name)
            hyst.prepare_xy_raw()
            hyst.compute_xy_metrics(temporal=temporal, space=space, norm=norm)
            
            columns_x = hyst.xrecapl.columns
            columns_y = hyst.yrecapl.columns
            
            n = len(columns_x)
            cmap = cmap_dict[sce]
            cmap_color = plt.get_cmap(cmap)(np.linspace(0, 1, n))
            color = color_dict[sce]
                        
            print('area='+str(hyst.area))
            print('slope='+str(hyst.slope))
            print('hi='+str(hyst.hi))
            print('q0='+str(hyst.q0))
            
            dfevol = hyst.dfmet.iloc[:-1]
            dfevol = dfevol.set_index(pd.to_datetime(dfevol.index, format='%Y'))
            
            cpax = 0
            
            for xy in xy_list:
                                
                # print(compt)    

                ###############################################################
                # ax = axs[1]                
                x = (Smod[xy[0]]).diff()
                y = Smod[xy[1]].diff()
                c = Smod.index.month
                wy = pd.Series(x.index.month).replace([10,11,12,1,2,3,4,5,6,7,8,9],
                                                        [1,2,3,4,5,6,7,8,9,10,11,12])
                xi = x.groupby([lambda x: x.month]).mean()
                yi = y.groupby([lambda y: y.month]).mean()
                xiline = xi.append(xi.iloc[[0]])
                xiline.index = np.arange(1,14,1)
                yiline = yi.append(yi.iloc[[0]])
                yiline.index = np.arange(1,14,1)            
                # year = 2018
                # spe_year_x = select_period(x, year, year)
                # spe_year_y = select_period(y, year, year)
                # xiline_spe = spe_year_x.append(spe_year_x.iloc[[0]])
                # xiline_spe.index = np.arange(1,14,1)
                # yiline_spe = spe_year_y.append(spe_year_y.iloc[[0]])
                # yiline_spe.index = np.arange(1,14,1)
                # ax3.plot(xiline_spe, yiline_spe, linestyle = '-', lw=1.5, color='red', zorder=0)
                # cmapping = 'jet'
                cmapping = mpl.colors.ListedColormap(dict_c[watershed_name])
                cmapping = dict_cmap[watershed_name]
                ax.scatter((x) , (y), c=wy, marker='o', cmap=cmapping,
                            s=5, vmin=1, vmax=12, alpha=0.75, ec='none', lw=0.2, zorder=10)
                xi = xiline.diff()
                xi.iloc[0] = xi.iloc[-1]
                xi = xi[:-1]
                yi = yiline.diff()
                yi.iloc[0] = yi.iloc[-1]
                yi = yi[:-1]        
                wyi = np.arange(1,12+1,1)
                wyi = pd.Series(wyi).replace([10,11,12,1,2,3,4,5,6,7,8,9],
                                             [1,2,3,4,5,6,7,8,9,10,11,12])
                # ax.scatter(xi, yi, c=wyi, marker='o', cmap=cmapping,
                #             s=35, vmin=1, vmax=12, alpha=1, 
                #             ec='k', lw = 0.5)
                cl = mpl.cm.jet(np.linspace(0,1,len(wyi)))
                # compt = 10
                # wyi = np.arange(1,12+1,1)
                # for k in wyi:
                #     ax.annotate(k,(xi[k],yi[k]), family='sans-serif',
                #                   fontsize=4, 
                #                   color='black', weight="bold", ha='center', va='center',
                #                   zorder=compt)
                #     ax.plot(xi[k], yi[k], marker='o', lw=2, markersize=7,
                #               markeredgecolor='black', 
                #                 markerfacecolor='white', markeredgewidth=1,
                #                 linestyle = 'None', zorder=compt) # cl[k-1]
                #     compt+=1
                ax.set_axisbelow(True)
                # ax.grid(zorder=-1000)
                ax.xaxis.grid(color='gray', zorder=-1)
                ax.yaxis.grid(color='gray', zorder=-1)
                
                ax.axhline(y=0, color='k', zorder=2)
                ax.axvline(x=0, color='k', zorder=2)
                ax.set_ylim(-4, 4)
                ax.set_xlim(-4, 4)
                ax.set_xlabel('\u0394$GW_{storage}$ $[Mm^3$]')
                ax.set_ylabel('\u0394$A_{sat}$ [%]')
                # ax3.set_xticks(np.arange(-2, 2 + 0.1, 1))
                # ax3.set_yticks(np.arange(-4, 4 + 0.1, 2))
                cpax+=1
      
fig.tight_layout()

base_name = figsim_folder+'fig07b/'
spec_name = str(watershed_names)+'_GWS-SAT-DELTA'
# fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight') 

#%% 7b - GWS-RAT RELATION

from scipy.stats import binned_statistic

typ = 'calibr-t6'

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

watershed_names = ['Canut','Nancon']

c = ['forestgreen','darkmagenta']
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

scan = 'ouflow_drain'

xy_list = [['groundwater_storage','prop_ratio']]

# fig, axs = plt.subplots(2,1, figsize=(3.5,6))
# axs = axs.ravel()

fig, ax = plt.subplots(1,1, figsize=(3.5,3.2))

for watershed_name in watershed_names :
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = 'k'
        
    for mod in mod_list:
        
        # fig1, axs1 = plt.subplots(1,1, figsize=(5,5))
        # xn = 0.1
        # xx = 100
        # yn = 0.1
        # yx = 100
        # ax = axs1
        # ax.set_title(mod)
        # ax.set_aspect('equal', adjustable='box')

        for sce in sce_list:
            
            simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+sce+'*')
            simul = simul_list[0]
            
            # if sce == 'historic':
            #     simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+'RCP8.5'+'*')
            #     simul = simul_list[0]
                
            model_name = simul.split('\\')[-1]
            Sy = float(model_name.split('_')[3].split('-')[0]) # %
            K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
            E = float(model_name.split('_')[3].split('-')[2]) # m
            D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
            params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
            Smod_path = simul+'/_watershed/_simulated_results.csv'            
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            Smod['prop_ratio'] = Smod.intermit_areas / Smod.perenn_areas
            Smod['prop_ratio'] = Smod.intermit_areas / Smod.surflow_areas
            
            Smod = select_period(Smod, 1960, 2019)
            # Smod['groundwater_storage'] = Smod['groundwater_storage']/(Smod['groundwater_storage'].mean())
            Smod['groundwater_storage'] = Smod['groundwater_storage']/1e6

            scan = 'outflow_drain'
            Qmod = Smod[scan] 
          
            Qmod = Qmod # mm/months
            Qmod = Qmod.squeeze()    
            Cmod = Smod['recharge'] # mm/months
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
            
            hyst = Hysteresis(DFmod, watershed_name)
            hyst.prepare_xy_raw()
            hyst.compute_xy_metrics(temporal=temporal, space=space, norm=norm)
            
            columns_x = hyst.xrecapl.columns
            columns_y = hyst.yrecapl.columns
            
            n = len(columns_x)
            cmap = cmap_dict[sce]
            cmap_color = plt.get_cmap(cmap)(np.linspace(0, 1, n))
            color = color_dict[sce]
                        
            print('area='+str(hyst.area))
            print('slope='+str(hyst.slope))
            print('hi='+str(hyst.hi))
            print('q0='+str(hyst.q0))
            
            dfevol = hyst.dfmet.iloc[:-1]
            dfevol = dfevol.set_index(pd.to_datetime(dfevol.index, format='%Y'))
            
            cpax = 0
            
            for xy in xy_list:
                                
                # print(compt)
            
                ###############################################################
                # ax = axs[0]
                x = Smod[xy[0]] / Smod[xy[0]].mean()
                y = Smod[xy[1]]
                c = Smod.index.month
                wy = pd.Series(x.index.month).replace([10,11,12,1,2,3,4,5,6,7,8,9],
                                                        [1,2,3,4,5,6,7,8,9,10,11,12])
                # ax.set_xscale('log')
                ax.set_yscale('log')
                ax.set_xlabel('$GW_{storage}$ normalized [-]')
                ax.set_ylabel('$A_{int}$ / $A_{per}$ [-]')
                # ax.set_xlabel(xy[0])
                # ax.set_ylabel(xy[1])
                ax.set_xlim(0.5, 1.5)
                ax.set_ylim(0.01, 10)
                # ax.set_yticks(np.arange(0,15+1,5))
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
                ax.plot(xiline, yiline, linestyle = '-', lw=1.5, color='k', zorder=0)
                wyi = np.arange(1,12+1,1)
                compt = 2
                for k in wyi:
                    ax.annotate(k,(xi[k],yi[k]), family='sans-serif', fontsize=4, 
                                 color='k', weight="bold", ha='center', va='center',
                                 zorder=compt)
                    ax.plot(xi[k], yi[k], marker="o", lw=2, markersize=7, markeredgecolor='black', 
                               markerfacecolor='white', markeredgewidth=1,
                               linestyle = 'None', zorder=compt)
                    compt+=1
                xe = pd.DataFrame()
                xe['q25'] = (x.groupby(x.index.month).quantile(0.25))
                xe['q75'] = (x.groupby(x.index.month).quantile(0.75))        
                ye = pd.DataFrame()
                ye['q25'] = (y.groupby(y.index.month).quantile(0.25))
                ye['q75'] = (y.groupby(y.index.month).quantile(0.75))                
                # ax.errorbar(xi, yi,
                #              yerr=np.vstack([yi-ye.q25, ye.q75-yi]),
                #              xerr=np.vstack([xi-xe.q25, xe.q75-xi]),
                #              ecolor = 'black', fmt = 'none', capsize = 1, elinewidth=0.5, 
                #              capthick=0.5, zorder=1)               

fig.tight_layout()

base_name = figsim_folder+'fig07b/'
spec_name = str(watershed_names)+'_GWS-RAT'
# fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight') 


xy_list = [['groundwater_storage','prop_ratio']]

fig, ax = plt.subplots(1,1, figsize=(3.5,3.2))

for watershed_name in watershed_names :
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = 'k'
        
    for mod in mod_list:
        
        # fig1, axs1 = plt.subplots(1,1, figsize=(5,5))
        # xn = 0.1
        # xx = 100
        # yn = 0.1
        # yx = 100
        # ax = axs1
        # ax.set_title(mod)
        # ax.set_aspect('equal', adjustable='box')

        for sce in sce_list:
            
            simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+sce+'*')
            simul = simul_list[0]
            
            # if sce == 'historic':
            #     simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+'RCP8.5'+'*')
            #     simul = simul_list[0]
                
            model_name = simul.split('\\')[-1]
            Sy = float(model_name.split('_')[3].split('-')[0]) # %
            K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
            E = float(model_name.split('_')[3].split('-')[2]) # m
            D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
            params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
            Smod_path = simul+'/_watershed/_simulated_results.csv'            
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            Smod['prop_ratio'] = Smod.intermit_areas / Smod.perenn_areas
            
            Smod = select_period(Smod, 1960, 2019)
            # Smod['groundwater_storage'] = Smod['groundwater_storage']/(Smod['groundwater_storage'].mean())
            Smod['groundwater_storage'] = Smod['groundwater_storage']/1e6

            scan = 'outflow_drain'
            Qmod = Smod[scan] 
          
            Qmod = Qmod # mm/months
            Qmod = Qmod.squeeze()    
            Cmod = Smod['recharge'] # mm/months
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
            
            hyst = Hysteresis(DFmod, watershed_name)
            hyst.prepare_xy_raw()
            hyst.compute_xy_metrics(temporal=temporal, space=space, norm=norm)
            
            columns_x = hyst.xrecapl.columns
            columns_y = hyst.yrecapl.columns
            
            n = len(columns_x)
            cmap = cmap_dict[sce]
            cmap_color = plt.get_cmap(cmap)(np.linspace(0, 1, n))
            color = color_dict[sce]
                        
            print('area='+str(hyst.area))
            print('slope='+str(hyst.slope))
            print('hi='+str(hyst.hi))
            print('q0='+str(hyst.q0))
            
            dfevol = hyst.dfmet.iloc[:-1]
            dfevol = dfevol.set_index(pd.to_datetime(dfevol.index, format='%Y'))
            
            cpax = 0
            
            for xy in xy_list:
                                
                # print(compt)    

                ###############################################################
                # ax = axs[1]                
                x = (Smod[xy[0]]).diff() / (Smod[xy[0]]).diff().mean()
                y = Smod[xy[1]].diff() 
                c = Smod.index.month
                wy = pd.Series(x.index.month).replace([10,11,12,1,2,3,4,5,6,7,8,9],
                                                        [1,2,3,4,5,6,7,8,9,10,11,12])
                xi = x.groupby([lambda x: x.month]).mean()
                yi = y.groupby([lambda y: y.month]).mean()
                xiline = xi.append(xi.iloc[[0]])
                xiline.index = np.arange(1,14,1)
                yiline = yi.append(yi.iloc[[0]])
                yiline.index = np.arange(1,14,1)            
                # year = 2018
                # spe_year_x = select_period(x, year, year)
                # spe_year_y = select_period(y, year, year)
                # xiline_spe = spe_year_x.append(spe_year_x.iloc[[0]])
                # xiline_spe.index = np.arange(1,14,1)
                # yiline_spe = spe_year_y.append(spe_year_y.iloc[[0]])
                # yiline_spe.index = np.arange(1,14,1)
                # ax3.plot(xiline_spe, yiline_spe, linestyle = '-', lw=1.5, color='red', zorder=0)
                # cmapping = 'jet'
                cmapping = mpl.colors.ListedColormap(dict_c[watershed_name])
                cmapping = dict_cmap[watershed_name]
                ax.scatter((x) , (y), c=wy, marker='o', cmap=cmapping,
                            s=5, vmin=1, vmax=12, alpha=0.75, ec='none', lw=0.2, zorder=10)
                xi = xiline.diff()
                xi.iloc[0] = xi.iloc[-1]
                xi = xi[:-1]
                yi = yiline.diff()
                yi.iloc[0] = yi.iloc[-1]
                yi = yi[:-1]        
                wyi = np.arange(1,12+1,1)
                wyi = pd.Series(wyi).replace([10,11,12,1,2,3,4,5,6,7,8,9],
                                             [1,2,3,4,5,6,7,8,9,10,11,12])
                # ax.scatter(xi, yi, c=wyi, marker='o', cmap=cmapping,
                #             s=35, vmin=1, vmax=12, alpha=1, 
                #             ec='k', lw = 0.5)
                cl = mpl.cm.jet(np.linspace(0,1,len(wyi)))
                # compt = 10
                # wyi = np.arange(1,12+1,1)
                # for k in wyi:
                #     ax.annotate(k,(xi[k],yi[k]), family='sans-serif',
                #                   fontsize=4, 
                #                   color='black', weight="bold", ha='center', va='center',
                #                   zorder=compt)
                #     ax.plot(xi[k], yi[k], marker='o', lw=2, markersize=7,
                #               markeredgecolor='black', 
                #                 markerfacecolor='white', markeredgewidth=1,
                #                 linestyle = 'None', zorder=compt) # cl[k-1]
                #     compt+=1
                ax.set_axisbelow(True)
                # ax.grid(zorder=-1000)
                ax.xaxis.grid(color='gray', zorder=-1)
                ax.yaxis.grid(color='gray', zorder=-1)
                
                ax.axhline(y=0, color='k', zorder=2)
                ax.axvline(x=0, color='k', zorder=2)
                ax.set_ylim(-4, 4)
                # ax.set_xlim(-4, 4)
                ax.set_xlabel('\u0394$GW_{storage}$ $[Mm^3$]')
                ax.set_ylabel('\u0394($A_{int}$ / $A_{per}$) [-]')
                # ax3.set_xticks(np.arange(-2, 2 + 0.1, 1))
                # ax3.set_yticks(np.arange(-4, 4 + 0.1, 2))
                cpax+=1
      
fig.tight_layout()

base_name = figsim_folder+'fig07b/'
spec_name = str(watershed_names)+'_GWS-RAT-DELTA'
# fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight') 

#%% 8 - L2D-SAT RELATION

from scipy.stats import binned_statistic

watershed_names = ['Canut','Nancon']

typ = 'calibr-t6'

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

c = ['forestgreen','darkmagenta']
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

scan = 'outflow_drain'

# xy_list = [['tau_L_wt_median_str','surflow_areas']]
xy_list = [['L_wt_median_str','surflow_areas']]
xy_list = [['L_wt_median_str','prop_ratio']]
# xy_list = [['tau_L_wt_median_str','surflow_areas']]

# fig, axs = plt.subplots(2,1, figsize=(3.5,6))
# axs = axs.ravel()

fig, ax = plt.subplots(1,1, figsize=(3.5,3.2))

for watershed_name in watershed_names :
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = 'k'
        
    for mod in mod_list:
        
        # fig1, axs1 = plt.subplots(1,1, figsize=(5,5))
        # xn = 0.1
        # xx = 100
        # yn = 0.1
        # yx = 100
        # ax = axs1
        # ax.set_title(mod)
        # ax.set_aspect('equal', adjustable='box')

        for sce in sce_list:
            
            simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+sce+'*')
            simul = simul_list[0]
            
            # if sce == 'historic':
            #     simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+'RCP8.5'+'*')
            #     simul = simul_list[0]
                
            model_name = simul.split('\\')[-1]
            Sy = float(model_name.split('_')[3].split('-')[0]) # %
            K = float(model_name.split('_')[3].split('-')[1]) / 24 / 3600 # m/s
            E = float(model_name.split('_')[3].split('-')[2]) # m
            D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
            params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
            Smod_path = simul+'/_watershed/_simulated_results.csv'
            Smod_path = simul+'/_watershed/_simulated_results_bis.csv'     
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            Smod['prop_ratio'] = Smod.intermit_areas / Smod.surflow_areas
            # Smod['prop_ratio'] = Smod.perenn_areas / Smod.surflow_areas
            # Smod['prop_ratio'] = Smod.surflow_areas
            
            Smod = select_period(Smod, 1960, 2019)
            # Smod['groundwater_storage'] = Smod['groundwater_storage']/(Smod['groundwater_storage'].mean())
            Smod['groundwater_storage'] = Smod['groundwater_storage']/1e6

            Qmod = Smod[scan] 
          
            Qmod = Qmod # mm/months
            Qmod = Qmod.squeeze()    
            Cmod = Smod['recharge'] # mm/months
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
            
            hyst = Hysteresis(DFmod, watershed_name)
            hyst.prepare_xy_raw()
            hyst.compute_xy_metrics(temporal=temporal, space=space, norm=norm)
            
            columns_x = hyst.xrecapl.columns
            columns_y = hyst.yrecapl.columns
            
            n = len(columns_x)
            cmap = cmap_dict[sce]
            cmap_color = plt.get_cmap(cmap)(np.linspace(0, 1, n))
            color = color_dict[sce]
                        
            print('area='+str(hyst.area))
            print('slope='+str(hyst.slope))
            print('hi='+str(hyst.hi))
            print('q0='+str(hyst.q0))
            
            dfevol = hyst.dfmet.iloc[:-1]
            dfevol = dfevol.set_index(pd.to_datetime(dfevol.index, format='%Y'))
            
            cpax = 0
            
            for xy in xy_list:
                                
                # print(compt)
            
                ###############################################################
                # ax = axs[0]
                x = Smod[xy[0]] #/ Smod[xy[0]].mean()
                # x = ((E - Smod['watertable_depth']) * (K*30))/(Sy/100)
                # x = Smod['groundwater_storage']#/(Smod['groundwater_storage'].mean())
                x = x / (E-Smod['watertable_depth'])
                print(x.mean().round(2))
                y = Smod[xy[1]]
                # y = ((E - Smod['watertable_depth']) * (K*30))
                c = Smod.index.month
                wy = pd.Series(x.index.month).replace([10,11,12,1,2,3,4,5,6,7,8,9],
                                                        [1,2,3,4,5,6,7,8,9,10,11,12])
                # ax.set_xscale('log')
                # ax.set_yscale('log')
                ax.set_xlabel('L² / D [d]')
                ax.set_xlabel('L normalized by mean [m]')
                # ax.set_ylabel('$A_{int}$ / $A_{per}$ [-]')
                ax.set_ylabel('$A_{sat}$ [%]')
                # ax.set_xlabel(xy[0])
                # ax.set_ylabel(xy[1])
                # ax.set_xlim(0, 350)
                # ax.set_ylim(0, 15)
                # ax.set_yticks(np.arange(0,15+1,5))
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
                ax.plot(xiline, yiline, linestyle = '-', lw=1.5, color='k', zorder=0)
                wyi = np.arange(1,12+1,1)
                compt = 2
                for k in wyi:
                    ax.annotate(k,(xi[k],yi[k]), family='sans-serif', fontsize=4, 
                                 color='k', weight="bold", ha='center', va='center',
                                 zorder=compt)
                    ax.plot(xi[k], yi[k], marker="o", lw=2, markersize=7, markeredgecolor='black', 
                               markerfacecolor='white', markeredgewidth=1,
                               linestyle = 'None', zorder=compt)
                    compt+=1
                xe = pd.DataFrame()
                xe['q25'] = (x.groupby(x.index.month).quantile(0.25))
                xe['q75'] = (x.groupby(x.index.month).quantile(0.75))        
                ye = pd.DataFrame()
                ye['q25'] = (y.groupby(y.index.month).quantile(0.25))
                ye['q75'] = (y.groupby(y.index.month).quantile(0.75))                
                # ax.errorbar(xi, yi,
                #              yerr=np.vstack([yi-ye.q25, ye.q75-yi]),
                #              xerr=np.vstack([xi-xe.q25, xe.q75-xi]),
                #              ecolor = 'black', fmt = 'none', capsize = 1, elinewidth=0.5, 
                #              capthick=0.5, zorder=1)               
                ax.axvline(x.median(), c='k', ls='--')
                '''
                ###############################################################
                ax = axs[1]                
                x = (Smod[xy[0]]).diff()
                print(x.median().round(2))
                y = Smod[xy[1]].diff()
                c = Smod.index.month
                wy = pd.Series(x.index.month).replace([10,11,12,1,2,3,4,5,6,7,8,9],
                                                        [1,2,3,4,5,6,7,8,9,10,11,12])
                xi = x.groupby([lambda x: x.month]).mean()
                yi = y.groupby([lambda y: y.month]).mean()
                xiline = xi.append(xi.iloc[[0]])
                xiline.index = np.arange(1,14,1)
                yiline = yi.append(yi.iloc[[0]])
                yiline.index = np.arange(1,14,1)            
                # year = 2018
                # spe_year_x = select_period(x, year, year)
                # spe_year_y = select_period(y, year, year)
                # xiline_spe = spe_year_x.append(spe_year_x.iloc[[0]])
                # xiline_spe.index = np.arange(1,14,1)
                # yiline_spe = spe_year_y.append(spe_year_y.iloc[[0]])
                # yiline_spe.index = np.arange(1,14,1)
                # ax3.plot(xiline_spe, yiline_spe, linestyle = '-', lw=1.5, color='red', zorder=0)
                # cmapping = 'jet'
                cmapping = mpl.colors.ListedColormap(dict_c[watershed_name])
                ax.scatter((x) , (y), c=wy, marker='o', cmap=cmapping,
                            s=5, vmin=1, vmax=12, alpha=0.75, ec='none', lw=0.2, zorder=10)
                xi = xiline.diff()
                xi.iloc[0] = xi.iloc[-1]
                xi = xi[:-1]
                yi = yiline.diff()
                yi.iloc[0] = yi.iloc[-1]
                yi = yi[:-1]        
                wyi = np.arange(1,12+1,1)
                wyi = pd.Series(wyi).replace([10,11,12,1,2,3,4,5,6,7,8,9],
                                             [1,2,3,4,5,6,7,8,9,10,11,12])
                # ax.scatter(xi, yi, c=wyi, marker='o', cmap=cmapping,
                #             s=35, vmin=1, vmax=12, alpha=1, 
                #             ec='k', lw = 0.5)
                cl = mpl.cm.jet(np.linspace(0,1,len(wyi)))
                compt = 2
                wyi = np.arange(1,12+1,1)
                # for k in wyi:
                #     ax.annotate(k,(xi[k],yi[k]), family='sans-serif',
                #                   fontsize=4, 
                #                   color='black', weight="bold", ha='center', va='center',
                #                   zorder=compt)
                #     ax.plot(xi[k], yi[k], marker='o', lw=2, markersize=7,
                #               markeredgecolor='black', 
                #                 markerfacecolor='white', markeredgewidth=1,
                #                 linestyle = 'None', zorder=compt) # cl[k-1]
                #     compt+=1
                ax.set_axisbelow(True)
                # ax.grid(zorder=-1000)
                ax.xaxis.grid(color='gray', zorder=-1)
                ax.yaxis.grid(color='gray', zorder=-1)
                
                ax.axhline(y=0, color='k', zorder=2)
                ax.axvline(x=0, color='k', zorder=2)
                ax.set_ylim(-8, 8)
                ax.set_xlim(-200, 100)
                # ax.set_xlabel('\u0394Response time [d]')
                ax.set_xlabel('\u0394(L² / D) [d]')
                # ax.set_ylabel('\u0394$A_{int}$ / $A_{per}$ [-]')
                ax.set_ylabel('\u0394$A_{sat}$ [%]')
                ax.set_xticks(np.arange(-200, 101, 100))
                # ax3.set_yticks(np.arange(-4, 4 + 0.1, 2))
                cpax+=1
                '''

# ax.set_xlim(0,3000)
ax.set_ylim(-0.05,1)           
fig.tight_layout()
# fig3.tight_layout()

base_name = figsim_folder+'fig08/'
spec_name = str(watershed_names)+'_L2D-SAT'
# fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight') 

#%% 8 - DSQ-SAT RELATION

from scipy.stats import binned_statistic

typ = 'calibr-t6'

# Things
time_step = 'M'
sim_state = 'transient'
var = 'REC'

scan = 'outflow_drain'

watershed_names = ['Canut','Nancon']
# watershed_names = ['Canut']
# watershed_names = ['Nancon']

spec_name = str(watershed_names)+'_DSQ-SAT'
# spec_name = watershed_names[0]+'_DSQ-SAT'

# Colored
mod_list = ['REA']
sce_list = ['historic']
sce_cmap = ["Greys"]
sce_color = ["k"]
cmap_dict = dict(zip(sce_list, sce_cmap))
color_dict = dict(zip(sce_list, sce_color))

c = ['forestgreen','darkmagenta']
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

scan = 'outflow_drain'

xy_list = [['groundwater_storage','surflow_areas', 'outflow_drain']]
xy_list = [['groundwater_storage','prop_ratio', 'outflow_drain']]

# fig, axs = plt.subplots(2,1, figsize=(3.5,6))
# axs = axs.ravel()

fig, ax = plt.subplots(1,1, figsize=(3.5,3.2))

for watershed_name in watershed_names :
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = 'k'
    
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)
    
    # BV.add_hydrology(hydrology_path, types_obs=['intermittent'], fields_obs=['fid'])

    area = BV.geographic.area
    
    for mod in mod_list:
        
        # fig1, axs1 = plt.subplots(1,1, figsize=(5,5))
        # xn = 0.1
        # xx = 100
        # yn = 0.1
        # yx = 100
        # ax = axs1
        # ax.set_title(mod)
        # ax.set_aspect('equal', adjustable='box')

        for sce in sce_list:
            
            simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+sce+'*')
            simul = simul_list[0]
            
            gw_npy = np.load(os.path.join(simul, '_watershed','groundwater_storage.npy'),
                              allow_pickle=True).item()
            # plt.imshow(gw_npy[10])
            # plt.colorbar()
            
            # if sce == 'historic':
            #     simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+'RCP8.5'+'*')
            #     simul = simul_list[0]
                
            model_name = simul.split('\\')[-1]
            Sy = float(model_name.split('_')[3].split('-')[0]) # %
            K = float(model_name.split('_')[3].split('-')[1]) / 24 / 3600 # m/s
            E = float(model_name.split('_')[3].split('-')[2]) # m
            D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
            params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
            Smod_path = simul+'/_watershed/_simulated_results_bis.csv'            
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            Smod['prop_ratio'] = Smod.intermit_areas / Smod.perenn_areas
            Smod['prop_ratio'] = Smod.intermit_areas / Smod.surflow_areas
            # Smod['prop_ratio'] = Smod.surflow_areas
            
            Smod['outflow_drain'] = Smod['outflow_drain'] * (area * 1e6)
            
            Smod = select_period(Smod, 1960, 2019)

            # Smod['groundwater_storage'] = Smod['groundwater_storage'] / (area * 1e6)
            
            Qmod = Smod[scan] 
          
            Qmod = Qmod # mm/months
            Qmod = Qmod.squeeze()    
            Cmod = Smod['recharge'] # mm/months
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
            
            hyst = Hysteresis(DFmod, watershed_name)
            hyst.prepare_xy_raw()
            hyst.compute_xy_metrics(temporal=temporal, space=space, norm=norm)
            
            columns_x = hyst.xrecapl.columns
            columns_y = hyst.yrecapl.columns
            
            n = len(columns_x)
            cmap = cmap_dict[sce]
            cmap_color = plt.get_cmap(cmap)(np.linspace(0, 1, n))
            color = color_dict[sce]
                        
            print('area='+str(hyst.area))
            print('slope='+str(hyst.slope))
            print('hi='+str(hyst.hi))
            print('q0='+str(hyst.q0))
            
            dfevol = hyst.dfmet.iloc[:-1]
            dfevol = dfevol.set_index(pd.to_datetime(dfevol.index, format='%Y'))
            
            cpax = 0
            
            for xy in xy_list:
                                
                print(cpax)
            
                ###############################################################
                # ax = axs[0]
                # x = Smod[xy[0]] / Smod[xy[2]]
                print((Smod[xy[0]] / Smod[xy[2]]).mean().round(1))
                print('K', K)
                x = (Smod[xy[0]].diff()) / (Smod[xy[2]].diff())
                L_calc = np.sqrt((Smod[xy[0]].diff() * (K*24*3600) * (E-Smod['watertable_depth'])) / \
                          (Smod[xy[2]].diff() * (Sy/100)))
                # L_calc = ((Smod[xy[0]].diff() * (K*24*3600) * (E-Smod['watertable_depth'])) / \
                #           (Smod[xy[2]].diff() * (Sy/100)))**2
                # L_calc = ((K*24*3600) * (E-Smod['watertable_depth']))/(Sy/100)
                # L_calc = (Smod[xy[0]].diff()) / (Smod[xy[2]].diff())
                x = L_calc # / (Smod['L_dem_median_str']) #/ L_calc.mean()
                y = Smod[xy[1]]
                # y = Smod['tau_L_wt_median_str'] / 2
                c = Smod.index.month
                wy = pd.Series(x.index.month).replace([10,11,12,1,2,3,4,5,6,7,8,9],
                                                        [1,2,3,4,5,6,7,8,9,10,11,12])
                # ax.set_xscale('log')
                # ax.set_yscale('log')
                # ax.set_xlabel('Response time [d]')
                # ax.set_ylabel('$A_{int}$ / $A_{per}$ [-]')
                ax.set_ylabel('$A_{sat}$ [%]')
                # ax.set_xlabel(xy[0])
                # ax.set_ylabel(xy[1])
                # ax.set_ylim(0, 15)
                # ax.set_xlim(0, 400)
                # ax.set_ylim(0, 400)
                # ax.set_yticks(np.arange(0,15+1,5))
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
                ax.plot(xiline, yiline, linestyle = '-', lw=1.5, color='k', zorder=0)
                wyi = np.arange(1,12+1,1)
                compt = 2
                for k in wyi:
                    ax.annotate(k,(xi[k],yi[k]), family='sans-serif', fontsize=4, 
                                 color='k', weight="bold", ha='center', va='center',
                                 zorder=compt)
                    ax.plot(xi[k], yi[k], marker="o", lw=2, markersize=7, markeredgecolor=dict_c[watershed_name], 
                               markerfacecolor='white', markeredgewidth=1,
                               linestyle = 'None', zorder=compt)
                    compt+=1
                xe = pd.DataFrame()
                xe['q25'] = (x.groupby(x.index.month).quantile(0.25))
                xe['q75'] = (x.groupby(x.index.month).quantile(0.75))        
                ye = pd.DataFrame()
                ye['q25'] = (y.groupby(y.index.month).quantile(0.25))
                ye['q75'] = (y.groupby(y.index.month).quantile(0.75))                
                # ax.errorbar(xi, yi,
                #              yerr=np.vstack([yi-ye.q25, ye.q75-yi]),
                #              xerr=np.vstack([xi-xe.q25, xe.q75-xi]),
                #              ecolor = 'black', fmt = 'none', capsize = 1, elinewidth=0.5, 
                #              capthick=0.5, zorder=1)
                ax.axvline(x.median(), c=dict_c[watershed_name], ls='--')
                # ax.set_xscale('log')
                # ax.set_xlim(0, 5)
                ax.set_xlabel('\u0394S / \u0394Q [d]')
                ax.set_xlabel('L no normalized by mean [m]')
                
ax.set_xlim(0, 2500) 
# ax.set_ylim(-0.1, 1)
ax.set_yscale('linear')

base_name = figsim_folder+'fig08/'
spec_name = str(watershed_names)+'_DS_SAT'
# fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight')

"""
xy_list = [['groundwater_storage','surflow_areas', 'outflow_drain']]
# xy_list = [['groundwater_storage','prop_ratio', 'outflow_drain']]

# fig, axs = plt.subplots(2,1, figsize=(3.5,6))
# axs = axs.ravel()

fig, ax = plt.subplots(1,1, figsize=(3.5,3.2))

for watershed_name in watershed_names :
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = 'k'
    
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)
    
    # BV.add_hydrology(hydrology_path, types_obs=['intermittent'], fields_obs=['fid'])

    area = BV.geographic.area
    
    for mod in mod_list:
        
        # fig1, axs1 = plt.subplots(1,1, figsize=(5,5))
        # xn = 0.1
        # xx = 100
        # yn = 0.1
        # yx = 100
        # ax = axs1
        # ax.set_title(mod)
        # ax.set_aspect('equal', adjustable='box')

        for sce in sce_list:
            
            simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+sce+'*')
            simul = simul_list[0]
            
            gw_npy = np.load(os.path.join(simul, '_watershed','groundwater_storage.npy'),
                              allow_pickle=True).item()
            # plt.imshow(gw_npy[10])
            # plt.colorbar()
            
            # if sce == 'historic':
            #     simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+'RCP8.5'+'*')
            #     simul = simul_list[0]
                
            model_name = simul.split('\\')[-1]
            Sy = float(model_name.split('_')[3].split('-')[0]) # %
            K = float(model_name.split('_')[3].split('-')[1]) / 24 / 3600 # m/s
            E = float(model_name.split('_')[3].split('-')[2]) # m
            D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
            params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
            Smod_path = simul+'/_watershed/_simulated_results.csv'            
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            Smod['prop_ratio'] = Smod.intermit_areas / Smod.perenn_areas
            
            Smod['outflow_drain'] = Smod['outflow_drain'] * (area * 1e6)
            
            Smod = select_period(Smod, 1960, 2019)

            # Smod['groundwater_storage'] = Smod['groundwater_storage'] / (area * 1e6)
            
            Qmod = Smod[scan] 
          
            Qmod = Qmod # mm/months
            Qmod = Qmod.squeeze()    
            Cmod = Smod['recharge'] # mm/months
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
            
            hyst = Hysteresis(DFmod, watershed_name)
            hyst.prepare_xy_raw()
            hyst.compute_xy_metrics(temporal=temporal, space=space, norm=norm)
            
            columns_x = hyst.xrecapl.columns
            columns_y = hyst.yrecapl.columns
            
            n = len(columns_x)
            cmap = cmap_dict[sce]
            cmap_color = plt.get_cmap(cmap)(np.linspace(0, 1, n))
            color = color_dict[sce]
                        
            print('area='+str(hyst.area))
            print('slope='+str(hyst.slope))
            print('hi='+str(hyst.hi))
            print('q0='+str(hyst.q0))
            
            dfevol = hyst.dfmet.iloc[:-1]
            dfevol = dfevol.set_index(pd.to_datetime(dfevol.index, format='%Y'))
            
            cpax = 0
            
            for xy in xy_list:
                                
                print(cpax)

                ###############################################################
                # ax = axs[1]                
                x = ((Smod[xy[0]].diff()) / (Smod[xy[2]].diff())).diff()
                x = np.sqrt((Smod[xy[0]].diff() * (K*3600*24) * (E-Smod['watertable_depth'])) / \
                    (Smod[xy[2]].diff() * (Sy/100))).diff()
                print(x.median().round(2))
                # x = ((Smod[xy[0]]) / (Smod[xy[2]])).diff()
                # x = (Smod[xy[0]].diff()) - (Smod[xy[2]].diff())
                
                mix = (Smod[xy[0]].diff()).to_frame()
                mix.columns = [0]
                mix[1] = (Smod[xy[2]].diff())
                mix[2] = mix[0] / mix[1]
                
                mix['c'] = np.nan
                mix = mix.reset_index()
                for t in range(len(mix)):
                    if (mix.loc[t,0] < 0) & (mix.loc[t,1] < 0):
                        mix.loc[t,'c'] = 'red'
                    if (mix.loc[t,0] < 0) & (mix.loc[t,1] > 0):
                        mix.loc[t,'c'] = 'darkorange'
                    if (mix.loc[t,0] > 0) & (mix.loc[t,1] < 0):
                        mix.loc[t,'c'] = 'darkgray'
                    if (mix.loc[t,0] > 0) & (mix.loc[t,1] > 0):
                        mix.loc[t,'c'] = 'dodgerblue'
                # mix = mix.set_index('date')
             
                y = Smod[xy[1]].diff()
                # y = Smod[xy[1]]
                mix['y'] = y.values
                
                c = Smod.index.month
                wy = pd.Series(x.index.month).replace([10,11,12,1,2,3,4,5,6,7,8,9],
                                                        [1,2,3,4,5,6,7,8,9,10,11,12])
                xi = x.groupby([lambda x: x.month]).mean()
                yi = y.groupby([lambda y: y.month]).mean()
                xiline = xi.append(xi.iloc[[0]])
                xiline.index = np.arange(1,14,1)
                yiline = yi.append(yi.iloc[[0]])
                yiline.index = np.arange(1,14,1)            
                # year = 2018
                # spe_year_x = select_period(x, year, year)
                # spe_year_y = select_period(y, year, year)
                # xiline_spe = spe_year_x.append(spe_year_x.iloc[[0]])
                # xiline_spe.index = np.arange(1,14,1)
                # yiline_spe = spe_year_y.append(spe_year_y.iloc[[0]])
                # yiline_spe.index = np.arange(1,14,1)
                # ax3.plot(xiline_spe, yiline_spe, linestyle = '-', lw=1.5, color='red', zorder=0)
                # cmapping = 'jet'
                
                cmapping = mpl.colors.ListedColormap(dict_c[watershed_name])
                cmapping = dict_cmap[watershed_name]
                ax.scatter((x) , (y), c=wy, marker='o', cmap=cmapping,
                            s=5, vmin=1, vmax=12, alpha=0.75, ec='none', lw=0.2, zorder=-1)
                
                '''
                mix = mix[1:]
                for t in mix.index:
                    # print()
                    cmapping = mpl.colors.ListedColormap(mix.loc[t,'c'])
                    ax.scatter(mix.loc[t,2], mix.loc[t,'y'], c=mix.loc[t,'y'], marker='o', cmap=cmapping,
                                s=5, vmin=1, vmax=12, alpha=0.75, ec='none', lw=0.2, zorder=10)
                '''
                
                xi = xiline.diff()
                xi.iloc[0] = xi.iloc[-1]
                xi = xi[:-1]
                yi = yiline.diff()
                yi.iloc[0] = yi.iloc[-1]
                yi = yi[:-1]        
                wyi = np.arange(1,12+1,1)
                wyi = pd.Series(wyi).replace([10,11,12,1,2,3,4,5,6,7,8,9],
                                             [1,2,3,4,5,6,7,8,9,10,11,12])
                # ax.scatter(xi, yi, c=wyi, marker='o', cmap=cmapping,
                #             s=35, vmin=1, vmax=12, alpha=1, 
                #             ec='k', lw = 0.5)
                cl = mpl.cm.jet(np.linspace(0,1,len(wyi)))
                compt = 2
                wyi = np.arange(1,12+1,1)
                for k in wyi:
                    ax.annotate(k,(xi[k],yi[k]), family='sans-serif',
                                  fontsize=4, 
                                  color='black', weight="bold", ha='center', va='center',
                                  zorder=compt)
                    ax.plot(xi[k], yi[k], marker='o', lw=2, markersize=7,
                              markeredgecolor='black', 
                                markerfacecolor='white', markeredgewidth=1,
                                linestyle = 'None', zorder=compt) # cl[k-1]
                    compt+=1
                ax.set_axisbelow(True)
                # ax.grid(zorder=-1000)
                ax.xaxis.grid(color='gray', zorder=-1)
                ax.yaxis.grid(color='gray', zorder=-1)
                
                ax.axhline(y=0, color='k', zorder=2)
                ax.axvline(x=0, color='k', zorder=2)
                ax.set_ylim(-4,4)
                # ax.set_xlim(-1000, 1000)
                ax.set_xlabel('\u0394Response time [d]')
                ax.set_xlabel('\u0394'+'(\u0394S / \u0394Q) [d]')
                # ax.set_ylabel('\u0394$A_{int}$ / $A_{per}$ [-]')
                ax.set_ylabel('\u0394$A_{sat}$ [%]')
                # ax.set_xticks(np.arange(-1000, 501, 500))
                # ax3.set_yticks(np.arange(-4, 4 + 0.1, 2))
                # ax.set_xscale('symlog')
                # ax.set_xscale('log')
                # ax.set_xlim(-200, 200)
                # ax.set_xticks(np.arange(-200,201,100))
                ax.set_xlim(-1000, 1000)
                cpax+=1
      
fig.tight_layout()

base_name = figsim_folder+'fig08/'
spec_name = str(watershed_names)+'_DS_SAT-DELTA'
# fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight') 
"""

#%% 9 - REHCARGE DISCHARGE CONVOL

from scipy.stats import binned_statistic

typ = 'calibr-t6'

# Things
time_step = 'M'
sim_state = 'transient'
var = 'REC'

scan = 'outflow_drain'

watershed_names = ['Canut','Nancon']
# watershed_names = ['Canut']
# watershed_names = ['Nancon']

spec_name = str(watershed_names)+'_DSQ-SAT'
# spec_name = watershed_names[0]+'_DSQ-SAT'

# Colored
mod_list = ['REA']
sce_list = ['historic']
sce_cmap = ["Greys"]
sce_color = ["k"]
cmap_dict = dict(zip(sce_list, sce_cmap))
color_dict = dict(zip(sce_list, sce_color))

c = ['forestgreen','darkmagenta']
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

scan = 'outflow_drain'

# fig, axs = plt.subplots(2,1, figsize=(3.5,6))
# axs = axs.ravel()


for tau_typ in [1, 'calc']:

    fig, ax = plt.subplots(1,1, figsize=(3.5,3.2))

    for watershed_name in watershed_names :
        simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
        color = 'k'
        
        BV = watershed_root.Watershed(watershed_name=watershed_name,
                                      dem_path=dem_path, 
                                      out_path=out_path,
                                      load=True,
                                      modflow_path=modflow_path)
        
        # BV.add_hydrology(hydrology_path, types_obs=['intermittent'], fields_obs=['fid'])
    
        area = BV.geographic.area
        
        for mod in mod_list:
            
            # fig1, axs1 = plt.subplots(1,1, figsize=(5,5))
            # xn = 0.1
            # xx = 100
            # yn = 0.1
            # yx = 100
            # ax = axs1
            # ax.set_title(mod)
            # ax.set_aspect('equal', adjustable='box')
    
            for sce in sce_list:
                
                simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+sce+'*')
                simul = simul_list[0]
                
                gw_npy = np.load(os.path.join(simul, '_watershed','groundwater_storage.npy'),
                                  allow_pickle=True).item()
                # plt.imshow(gw_npy[10])
                # plt.colorbar()
                
                # if sce == 'historic':
                #     simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+'RCP8.5'+'*')
                #     simul = simul_list[0]
                    
                model_name = simul.split('\\')[-1]
                Sy = float(model_name.split('_')[3].split('-')[0]) # %
                K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
                E = float(model_name.split('_')[3].split('-')[2]) # m
                D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
                params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
                Smod_path = simul+'/_watershed/_simulated_results.csv'            
                Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
                Smod['prop_ratio'] = Smod.intermit_areas / Smod.perenn_areas
                
                # Smod['outflow_drain'] = Smod['outflow_drain'] * (area * 1e6)
                
                Smod = select_period(Smod, 1960, 2019)
    
                Smod['groundwater_storage'] = Smod['groundwater_storage'] / (area * 1e6)
                
                Qmod = Smod[scan] 
              
                Qmod = Qmod # mm/months
                Qmod = Qmod.squeeze()    
                Cmod = Smod['recharge'] # mm/months
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
                
                hyst = Hysteresis(DFmod, watershed_name)
                hyst.prepare_xy_raw()
                hyst.compute_xy_metrics(temporal=temporal, space=space, norm=norm)
                
                columns_x = hyst.xrecapl.columns
                columns_y = hyst.yrecapl.columns
                
                n = len(columns_x)
                cmap = cmap_dict[sce]
                cmap_color = plt.get_cmap(cmap)(np.linspace(0, 1, n))
                color = color_dict[sce]
                            
                print('area='+str(hyst.area))
                print('slope='+str(hyst.slope))
                print('hi='+str(hyst.hi))
                print('q0='+str(hyst.q0))
                
                dfevol = hyst.dfmet.iloc[:-1]
                dfevol = dfevol.set_index(pd.to_datetime(dfevol.index, format='%Y'))
    
                Smod['tau_stock'] = (Smod['groundwater_storage'].diff() / Smod['outflow_drain'].diff())
                
                Smod['convol'] = np.nan
                
                Smod = Smod[1:]
                
                Smod = Smod.reset_index()
                
                for i in range(len(Smod)):
                    if tau_typ == 'calc':
                        the_tau = int(round(Smod.iloc[i]['tau_stock']))
                    else:
                        the_tau = tau_typ
                    Smod.loc[i,'convol_rec'] = Smod.iloc[i-the_tau:i]['recharge'].sum()
                    Smod.loc[i,'convol_dis'] = Smod.iloc[i-the_tau:i]['outflow_drain'].sum()
                    # print(Smod.iloc[i-the_tau:i]['recharge'].sum())
                    # .rolling(min_periods=None,window=the_tau).sum()
    
                Smod = Smod.set_index('date')
                
                c = Smod.index.month
                wy = pd.Series(c).replace([10,11,12,1,2,3,4,5,6,7,8,9],
                                                        [1,2,3,4,5,6,7,8,9,10,11,12])
                
        cmapping = dict_cmap[watershed_name]
        ax.scatter(Smod.convol_rec, Smod.convol_dis, c=wy, marker='o', cmap=cmapping,
                    s=5, vmin=1, vmax=12, alpha=0.75, ec='none', lw=0.2)
        # ax.scatter(Smod.convol_rec, Smod.outflow_drain, c=wy, marker='o', cmap=cmapping,
        #             s=5, vmin=1, vmax=12, alpha=0.75, ec='none', lw=0.2)
        # cmapping = mpl.colors.ListedColormap(dict_c[watershed_name])
        # ax.scatter(Smod.recharge, Smod.outflow_drain, c=wy, marker='o', cmap=cmapping,
        #             s=5, vmin=1, vmax=12, alpha=0.75, ec='none', lw=0.2)
        ax.set_xscale('log')
        ax.set_yscale('log')
        
        ax.set_aspect('equal')
        
        minimum = np.min((ax.get_xlim(),ax.get_ylim()))
        maximum = np.max((ax.get_xlim(),ax.get_ylim()))
        
        ax.set_xlim(minimum*1.2,maximum*1.2)
        ax.set_ylim(minimum*1.2,maximum*1.2)
        
        ax.set_xlabel('$R_{convol}$ [mm/month]')
        ax.set_ylabel('$Q_{convol}$ [mm/month]')
        
    fig.tight_layout()
    
    base_name = figsim_folder+'fig09/'
    spec_name = str(watershed_names)+'_CONV_REC-DIS_'+str(tau_typ)
    # fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight') 

#%% 10 - FOCUS YEARS

hydrology_path = data_path + 'HYDROLOGY/France/Hydrographic/D035/' # add hydrographic shapefiles

watershed_names = ['Canut','Nancon']
code_names = ['J7513010','J0014010']

# watershed_names = ['Canut']
# code_names = ['J7513010']

types_obs = ['complete','intermittent','perennial','river','zh_couesnon','zh_meuchezecanut'] # list of shapefile name layers for clip hydrology
fields_obs = ['persistanc','fid','fid','fid','fid','fid']

df = pd.DataFrame(np.nan, index=range(1), columns=types_obs)

c = ['forestgreen','orchid']
dict_c = dict(zip(watershed_names, c))

typ = 'calibr-t3'

mod_list = ['REA']

sce_list = ['historic']

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
    
    # BV.add_hydrology(hydrology_path, types_obs=['intermittent'], fields_obs=['fid'])

    bv = gpd.read_file(BV.geographic.watershed_shp)
    area = BV.geographic.area
    area = round(area, 1)
    
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    
    dem = rasterio.open(BV.geographic.watershed_dem)
    dem_data = dem.read(1)
    
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

    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = 'k'
        
    for mod in mod_list:
        
        # fig1, axs1 = plt.subplots(1,1, figsize=(5,5))
        # xn = 0.1
        # xx = 100
        # yn = 0.1
        # yx = 100
        # ax = axs1
        # ax.set_title(mod)
        # ax.set_aspect('equal', adjustable='box')

        for sce in sce_list:
            
            simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+sce+'*')
            simul = simul_list[0]
            
            # if sce == 'historic':
            #     simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+'RCP8.5'+'*')
            #     simul = simul_list[0]
                
            model_name = simul.split('\\')[-1]
            Sy = float(model_name.split('_')[3].split('-')[0]) # %
            K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
            E = float(model_name.split('_')[3].split('-')[2]) # m
            D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
            params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
            Smod_path = simul+'/_watershed/_simulated_results.csv'            
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            Smod['prop_ratio'] = Smod.intermit_areas / Smod.perenn_areas
            
            Smod = select_period(Smod, 1960, 2019)

            hist = Smod.copy()
            hist['month'] = hist.index.month.values
            hist['year'] = hist.index.year.values # group by month and year, get the average
            hist = hist.groupby(['month', 'year']).apply(lambda g: g.sum(skipna=False))
            hist = hist.unstack(level=0, fill_value=np.nan)
            hist = hist['surflow_areas']
            
            lims = (hist.min(), hist.max())
            vmin = 0
            vmax = 10
            
            xticks = np.arange((hist.index[-1]+1) - hist.index[0])+0.5
            years = list(hist.index.values.astype(str))[::5] 
            
            hist = hist.T
            
            ####################################################################
            
            fig, ax = plt.subplots(1,1, figsize=(10, 3))
            # axs = axs.ravel()
            colori = "jet_r"
            yticks = np.arange(12)+0.5
            mois = ['J','F','M','A','M','J','J','A','S','O','N','D']
            ax = ax
            pc = ax.pcolormesh(hist, cmap=colori, vmin=vmin, vmax=vmax, edgecolor='grey', lw=0.2, alpha=0.7) # norm=mpl.colors.LogNorm(vmin, vmax)
            ax.set_yticks(yticks)
            ax.set_yticklabels(mois, minor=False, rotation='horizontal', fontsize=13)
            # ax.yaxis.tick_top()
            ax.set_xticks(xticks[::5])
            ax.set_xticklabels(years, minor=False, rotation='horizontal', fontsize=13)
            # ax.invert_yaxis()
            ax.tick_params(axis="x", direction='out', length=5)
            ax.tick_params(axis="y", direction='out', length=5)
            cb = fig.colorbar(pc)
            cb.ax.set_ylabel('$A_{sat}$ [%]')

            base_name = figsim_folder+'fig10/'
            spec_name = watershed_name+'_saturpano'
            fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight') 

#%% 11 - GIF CROSS

typ = 'calibr-t3'

watershed_names = ['Canut','Nancon']
# watershed_names = ['Canut']

# fig, axs = plt.subplots(2, 1, figsize=(5,4), dpi=300)

dates = pd.date_range(start='01/01/1960', end='31/12/2019', freq='M')

for watershed_name in watershed_names[:]:    
    
    # if watershed_name == 'Nancon':
    #     ax = axs[1]
    # if watershed_name == 'Canut':
    #     ax = axs[0]
    
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
        
    wbt.vector_lines_to_raster(stable_folder+'geographic/'+'watershed_contour.shp',
                               stable_folder+'geographic/'+'watershed_contour.tif',
                               base = stable_folder+'geographic/'+'watershed_dem.tif')
    line = imageio.imread(stable_folder+'geographic/'+'watershed_contour.tif')
    line = np.ma.masked_where(line <= 0, line)
        
    mask = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
    
    import itertools            
    
    watertable_elevation = np.load(simulations_folder+model_name+'/_watershed/'+'watertable_elevation'+'.npy', allow_pickle=True).item()
    # acc_npy = np.load(simulations_folder+model_name+'/_watershed/'+'accumulation_flux.npy', allow_pickle=True).item()
    # acc_npy = dict(itertools.islice(acc_npy.items(), 12))

    # for key in acc_npy:
    #     # print(key)
    #     # acc = np.ma.masked_where(dem.read(1) < 0, dem.read(1))
    #     acc_npy[key] = np.ma.masked_array(acc_npy[key], mask=(mask<0))
    # zero = acc_npy[0] * 0
    # for l in range(len(acc_npy)):
    #     tempo = acc_npy[l].copy()
    #     tempo[tempo>0] = 1
    #     zero = zero + tempo
    # days_flux = zero.copy() # / len(acc_npy)

    for key in dict(itertools.islice(watertable_elevation.items(),
                                     len(watertable_elevation)-12*8,
                                     len(watertable_elevation))):
    # for key in watertable_elevation:
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
        cur_y = 40
        
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
        if watershed_name == 'Canut':
            dem_v_plot = dem_prof[:,int(cur_x)]
            dem_v_plot[dem_v_plot == 0] = np.nan
            wt_v_plot = wt_prof[:,int(cur_x)]
            wt_v_plot[wt_v_plot == 0] = np.nan
            
        dem_max = dem_data.max()
        dem_prof = dem_data.astype(float)
        dem_prof[dem_prof<0] = np.nan
        dem_plot = np.ma.masked_array(dem_data, mask=(dem_data<0))
        
        wt_prof = wt_data.astype(float)
        wt_prof[wt_prof<0] = np.nan
                        
        fig, ax = plt.subplots(1, 1, figsize=(5,3), dpi=300)
    
        if watershed_name == 'Nancon':
            # dem_h_prof, = ax.plot(np.arange(xx.shape[1])*75,dem_h_plot, c='saddlebrown', lw=2)
            # wt_h_prof, = ax.plot(np.arange(xx.shape[1])*75, wt_h_plot, c='dodgerblue', lw=2)
            wt_h_fill = ax.fill_between(np.arange(xx.shape[1])*75, 0, wt_h_plot,
                                            color='dodgerblue', alpha=0.5, lw=0)
            wt_h_fill = ax.fill_between(np.arange(xx.shape[1])*75, wt_h_plot, dem_h_plot,
                                            color='saddlebrown', alpha=0.5, lw=0)
            ax.set_xlim(4000, 7000)
            ax.set_ylim(130, 170)
            ax.set_yticks([140,160])
            
            d_prof = ax.plot(np.arange(xx.shape[1])*75, dem_h_plot, 'saddlebrown', lw=2)
            w_prof = ax.plot(np.arange(xx.shape[1])*75, wt_h_plot, color='navy', lw=2)
            
        if watershed_name == 'Canut':
            # dem_v_prof, = ax.plot(np.arange(xx.shape[0])*75, dem_v_plot, c='saddlebrown', lw=2)
            # wt_v_prof, = ax.plot(np.arange(xx.shape[0])*75, wt_v_plot, c='dodgerblue', lw=2)
            wt_v_fill = ax.fill_between(np.arange(xx.shape[0])*75, 0, wt_v_plot,
                                                color='dodgerblue', alpha=0.5, lw=0)
            wt_v_fill = ax.fill_between(np.arange(xx.shape[0])*75, wt_v_plot, dem_v_plot,
                                                color='saddlebrown', alpha=0.5, lw=0)
            ax.set_xlim(1000, 4000)
            ax.set_ylim(90, 130)
            ax.set_yticks([100,120])
            
            d_prof = ax.plot(np.arange(xx.shape[0])*75, dem_v_plot, 'saddlebrown', lw=2)
            w_prof = ax.plot(np.arange(xx.shape[0])*75, wt_v_plot, color='navy', lw=2)
            
        # ax.set_aspect(xRange/yRange)
        # asp = np.diff(ax.get_xlim())[0] / np.diff(ax.get_ylim())[0]
        # ax.set_aspect(asp)
        
        ax.set_title(str(dates[key])[:7])
        
        plt.tight_layout()
        
        fig.savefig(simulations_folder+model_name+'/_figures/png/'+'cross_'+str(key)+'.png', dpi=300, bbox_inches='tight')

        plt.close()

        # plt.plot(dem_h_plot)
        # plt.plot(wt_h_plot)

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

    begin_by = simulations_folder+model_name+'/_figures/png/'+'cross_'
    filenames = sorted(glob.glob(begin_by+'*.png'), key=os.path.getmtime)
    images = []
    for filename in filenames:
        images.append(imageio.imread(filename))
    base_name = figsim_folder+'fig11/'
    spec_name = watershed_name+'_cross_intermittent_monthly'
    imageio.mimsave(base_name+spec_name+'.gif', images,
                    duration=0.25, loop=0)

#%% 11 - GIF MAP

typ = 'calibr-t3'

# typ_intermit = 'monthly' # yearly or persistency or monthly
typ_intermit = 'monthly' # yearly or persistency or monthly
# typ_intermit = 'yearly' # yearly or persistency or monthly
gif = True

watershed_names = ['Canut','Nancon']
code_names = ['J7513010','J0014010']

# watershed_names = ['Canut']
# code_names = ['J7513010']

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

    years = np.arange(1960,2019+1,1)
        
    simul_list = glob.glob(simulations_folder+typ+'*')
    simul_list = sorted(glob.glob(simulations_folder+typ+'*'),
                       key=os.path.getmtime)
    # simuls = fnmatch.filter(os.listdir(simulations_folder), typ+'*')
    
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
        
        '''
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
        '''
        
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
                if i >= 52:
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
                        ax.imshow(np.ma.masked_where(to==1, to),
                                  cmap = mpl.colors.ListedColormap(['dodgerblue']))
                        ax.imshow(np.ma.masked_where(to==2, to),
                                  cmap = mpl.colors.ListedColormap(['darkorange']))
                        ax.imshow(line, cmap=mpl.colors.ListedColormap('k'))
                        ax.get_xaxis().set_visible(False)
                        ax.get_yaxis().set_visible(False)
                        
                        ax.set_title(str(years[i])+'-'+(str(k+1)))
                        
                        path_sub = glob.glob(stable_folder+'subbasin/' + '/intermittency*')[0] + '/watershed_contour.shp'
                        wbt.vector_lines_to_raster(path_sub,
                                                   glob.glob(stable_folder+'subbasin/' + '/intermittency*')[0] + '/watershed_contour.tif',
                                                   base = stable_folder+'geographic/'+'watershed_dem.tif')
                        line_sub = imageio.imread(glob.glob(stable_folder+'subbasin/' + '/intermittency*')[0] + '/watershed_contour.tif')
                        line_sub = np.ma.masked_where(line_sub <= 0, line_sub)
                        # ax.imshow(line_sub, cmap=mpl.colors.ListedColormap('k'))
                        
                        ax.imshow(line, cmap=mpl.colors.ListedColormap('k'))
                        
                        if watershed_name=='Canut':
                            ax.axvline(x=65, color='k', lw=1, ls='--')
                        if watershed_name=='Nancon':
                            ax.axhline(y=40, color='k', lw=1, ls='--')
                        
                        fig.savefig(simul+'/_figures/png/'+'_map_intermittent_monthly_'+str(compt)+'.png', dpi=300, bbox_inches='tight')
        
                        plt.close()
                        
                        compt += 1
                        
                    inf+=12
                    sup+=12

    if gif == True:
        begin_by = simul+'/_figures/png/'+'_map_intermittent_monthly'
        filenames = sorted(glob.glob(begin_by+'*.png'), key=os.path.getmtime)
        images = []
        for filename in filenames:
            images.append(imageio.imread(filename))
        base_name = figsim_folder+'fig11/'
        spec_name = watershed_name+'_map_intermittent_monthly'
        imageio.mimsave(base_name+spec_name+'.gif', images,
                        duration=0.25, loop=0)

#%% ---- NEWLY

#%% R vs Asat

from scipy.stats import binned_statistic

watershed_names = ['Canut','Nancon']

typ = 'calibr-t6'

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

c = ['darkgreen','darkmagenta']
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

# fig, axs = plt.subplots(2,1, figsize=(3.5,6))
# axs = axs.ravel()

fig, ax = plt.subplots(1,1, figsize=(3.5,3.2))
ax.set_xscale('log')
ax.set_xlabel('L² / D [d]')
ax.set_xlabel('R [mm/month]')
# ax.set_ylabel('$A_{int}$ / $A_{per}$ [-]')
ax.set_ylabel('$A_{sat}$ [%]')
# ax.set_xlim(0.1,250)
# ax.set_ylim(-0.05,1)
ax.set_ylim(0, 15)
ax.set_yticks(np.arange(0,15+1,5))
fig.tight_layout()
# fig3.tight_layout()
ax.set_axisbelow(True)
# ax.grid(zorder=-1000)
# ax.xaxis.grid(color='gray', zorder=-1)
# ax.yaxis.grid(color='gray', zorder=-1)

for watershed_name in watershed_names :
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = 'k'
        
    for mod in mod_list:
        
        for sce in sce_list:
            
            simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+sce+'*')
            simul = simul_list[0]
                
            model_name = simul.split('\\')[-1]
            Sy = float(model_name.split('_')[3].split('-')[0]) # %
            K = float(model_name.split('_')[3].split('-')[1]) / 24 / 3600 # m/s
            E = float(model_name.split('_')[3].split('-')[2]) # m
            D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
            params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
            Smod_path = simul+'/_watershed/_simulated_results_bis.csv'     
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            Smod['prop_ratio'] = Smod.intermit_areas / Smod.surflow_areas
            Smod['recharge'] = Smod['recharge'] * 1000 * 30
            Smod['outflow_drain'] = Smod['outflow_drain'] * 1000 * 30
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
                compt = 2
                for k in wyi:
                    ax.annotate(k,(xi[k],yi[k]), family='sans-serif', fontsize=4, 
                                 color=dict_c[watershed_name], weight="bold", ha='center', va='center',
                                 zorder=compt)
                    ax.plot(xi[k], yi[k], marker="o", lw=2, markersize=7, 
                               markeredgecolor='k', 
                               markerfacecolor='white', markeredgewidth=1,
                               linestyle = 'None', zorder=compt)
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

base_name = figsim_folder+'fig12/'
spec_name = str(watershed_names)+'_R vs Asat'
fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight') 

#%% dGW vs dA

from scipy.stats import binned_statistic

watershed_names = ['Canut','Nancon']

typ = 'calibr-t6'

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

c = ['forestgreen','darkmagenta']
c = ['blue','darkmagenta']
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

xy_list = [['groundwater_storage','surflow_areas']]

# fig, axs = plt.subplots(2,1, figsize=(3.5,6))
# axs = axs.ravel()

fig, ax = plt.subplots(1,1, figsize=(3.5,3.2))
# ax.set_xscale('log')
# ax.set_ylabel('$A_{int}$ / $A_{per}$ [-]')
ax.set_xlabel('\u0394$S_{gws}$ $[Mm^3$]')
ax.set_ylabel('\u0394$A_{sat}$ [%]')
# ax.set_xlim(0,3000)
# ax.set_ylim(-0.05,1)
ax.set_ylim(-4, 4)
# ax.set_yticks(np.arange(0,15+1,5))
fig.tight_layout()
# fig3.tight_layout()
ax.set_axisbelow(True)
# ax.grid(zorder=-1000)
ax.xaxis.grid(color='gray', zorder=-1)
ax.yaxis.grid(color='gray', zorder=-1)
ax.axhline(y=0, color='k', zorder=2)
ax.axvline(x=0, color='k', zorder=2)
ax.set_ylim(-4, 4)
# ax.set_xlim(-4, 4)
ax.set_xlim(-0.25, 0.25)

for watershed_name in watershed_names :
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = 'k'
        
    for mod in mod_list:
        
        for sce in sce_list:
            
            simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+sce+'*')
            simul = simul_list[0]
                
            model_name = simul.split('\\')[-1]
            Sy = float(model_name.split('_')[3].split('-')[0]) # %
            K = float(model_name.split('_')[3].split('-')[1]) / 24 / 3600 # m/s
            E = float(model_name.split('_')[3].split('-')[2]) # m
            D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
            params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
            Smod_path = simul+'/_watershed/_simulated_results_bis.csv'     
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            Smod['prop_ratio'] = Smod.intermit_areas / Smod.surflow_areas
            Smod['recharge'] = Smod['recharge'] * 1000 * 30
            Smod['outflow_drain'] = Smod['outflow_drain'] * 1000 * 30
            Smod['groundwater_storage'] = (Smod['groundwater_storage']/(Smod['groundwater_storage'].mean()))
            # Smod['groundwater_storage'] = Smod['groundwater_storage']/1e6
            Smod = select_period(Smod, 1960, 2019)
            
            for xy in xy_list:
                                
                x = Smod[xy[0]].diff()
                y = Smod[xy[1]].diff()
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
                compt = 2
                for k in wyi:
                    ax.annotate(k,(xi[k],yi[k]), family='sans-serif', fontsize=4, 
                                 color=dict_c[watershed_name], weight="bold", ha='center', va='center',
                                 zorder=compt)
                    ax.plot(xi[k], yi[k], marker="o", lw=2, markersize=7, 
                               markeredgecolor='k', 
                               markerfacecolor='white', markeredgewidth=1,
                               linestyle = 'None', zorder=compt)
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

base_name = figsim_folder+'fig12/'
spec_name = str(watershed_names)+'_dGWnorm vs dA'
fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight') 

#%% Q vs Aint

from scipy.stats import binned_statistic

watershed_names = ['Canut','Nancon']

typ = 'calibr-t6'

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

c = ['forestgreen','darkmagenta']
c = ['blue','darkmagenta']
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

xy_list = [['outflow_drain','prop_ratio']]

# fig, axs = plt.subplots(2,1, figsize=(3.5,6))
# axs = axs.ravel()

fig, ax = plt.subplots(1,1, figsize=(3.7,3.2))
# ax.set_xscale('log')
ax.set_xlabel('$Q_{spe}$ [mm/month]')
ax.set_ylabel('$A_{int}$ / $A_{sat}$ [-]')
# ax.set_xlim(0,3000)
# ax.set_ylim(-0.05,1)
# ax.set_xlim(-10, 200)
# ax.set_ylim(None, 1)
# plt.gca().set_ylim(top=1)
# ax.set_yticks(np.arange(0,15+1,5))
fig.tight_layout()
# fig3.tight_layout()
ax.set_axisbelow(True)
# ax.grid(zorder=-1000)
# ax.xaxis.grid(color='gray', zorder=-1)
# ax.yaxis.grid(color='gray', zorder=-1)
# ax.axhline(y=0, color='k', zorder=2)
# ax.axvline(x=0, color='k', zorder=2)
# ax.set_ylim(-4, 4)
# ax.set_xlim(-4, 4)
# ax.set_xlabel('\u0394$GW_{storage}$ $[Mm^3$]')
# ax.set_ylabel('\u0394$A_{sat}$ [-]')

for watershed_name in watershed_names :
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = 'k'
        
    for mod in mod_list:
        
        for sce in sce_list:
            
            simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+sce+'*')
            simul = simul_list[0]
                
            model_name = simul.split('\\')[-1]
            Sy = float(model_name.split('_')[3].split('-')[0]) # %
            K = float(model_name.split('_')[3].split('-')[1]) / 24 / 3600 # m/s
            E = float(model_name.split('_')[3].split('-')[2]) # m
            D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
            params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
            Smod_path = simul+'/_watershed/_simulated_results_bis.csv'     
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            Smod['prop_ratio'] = Smod.intermit_areas / Smod.surflow_areas
            Smod['recharge'] = Smod['recharge'] * 1000 * 30
            Smod['outflow_drain'] = Smod['outflow_drain'] * 1000 * 30
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
                compt = 2
                for k in wyi:
                    ax.annotate(k,(xi[k],yi[k]), family='sans-serif', fontsize=4, 
                                 color=dict_c[watershed_name], weight="bold", ha='center', va='center',
                                 zorder=compt)
                    ax.plot(xi[k], yi[k], marker="o", lw=2, markersize=7, 
                               markeredgecolor='k', 
                               markerfacecolor='white', markeredgewidth=1,
                               linestyle = 'None', zorder=compt)
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

ax.set_ylim(bottom=None, top=1)

base_name = figsim_folder+'fig12/'
spec_name = str(watershed_names)+'_Q vs Aint'
fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight') 

#%% Q vs Asat

from scipy.stats import binned_statistic

watershed_names = ['Canut','Nancon']

typ = 'calibr-t6'

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

c = ['forestgreen','darkmagenta']
c = ['blue','darkmagenta']
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

xy_list = [['outflow_drain','surflow_areas']]

# fig, axs = plt.subplots(2,1, figsize=(3.5,6))
# axs = axs.ravel()

fig, ax = plt.subplots(1,1, figsize=(3.7,3.2))
ax.set_xscale('log')
ax.set_xlabel('$Q_{spe}$ [mm/month]')
ax.set_ylabel('$A_{sat}$ [%]')
# ax.set_xlim(0,3000)
# ax.set_ylim(-0.05,1)
# ax.set_xlim(-10, 200)
ax.set_ylim(0, 15)
# plt.gca().set_ylim(top=1)
ax.set_yticks(np.arange(0,15+1,5))
fig.tight_layout()
# fig3.tight_layout()
ax.set_axisbelow(True)
# ax.grid(zorder=-1000)
# ax.xaxis.grid(color='gray', zorder=-1)
# ax.yaxis.grid(color='gray', zorder=-1)
# ax.axhline(y=0, color='k', zorder=2)
# ax.axvline(x=0, color='k', zorder=2)
# ax.set_ylim(-4, 4)
# ax.set_xlim(-4, 4)
# ax.set_xlabel('\u0394$GW_{storage}$ $[Mm^3$]')
# ax.set_ylabel('\u0394$A_{sat}$ [-]')
# ax.set_xlim(0,100)

for watershed_name in watershed_names :
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = 'k'
        
    for mod in mod_list:
        
        for sce in sce_list:
            
            simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+sce+'*')
            simul = simul_list[0]
                
            model_name = simul.split('\\')[-1]
            Sy = float(model_name.split('_')[3].split('-')[0]) # %
            K = float(model_name.split('_')[3].split('-')[1]) / 24 / 3600 # m/s
            E = float(model_name.split('_')[3].split('-')[2]) # m
            D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
            params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
            Smod_path = simul+'/_watershed/_simulated_results_bis.csv'     
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            Smod['prop_ratio'] = Smod.intermit_areas / Smod.surflow_areas
            Smod['recharge'] = Smod['recharge'] * 1000 * 30
            Smod['outflow_drain'] = Smod['outflow_drain'] * 1000 * 30
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
                compt = 2
                for k in wyi:
                    ax.annotate(k,(xi[k],yi[k]), family='sans-serif', fontsize=4, 
                                 color=dict_c[watershed_name], weight="bold", ha='center', va='center',
                                 zorder=compt)
                    ax.plot(xi[k], yi[k], marker="o", lw=2, markersize=7, 
                               markeredgecolor='k', 
                               markerfacecolor='white', markeredgewidth=1,
                               linestyle = 'None', zorder=compt)
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

# ax.set_ylim(bottom=None, top=1)

base_name = figsim_folder+'fig12/'
spec_name = str(watershed_names)+'_Q vs Asat'
# fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight') 

#%% t vs Aint

from scipy.stats import binned_statistic

watershed_names = ['Canut','Nancon']

typ = 'calibr-t6'

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

c = ['forestgreen','darkmagenta']
c = ['blue','darkmagenta']
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

# fig, axs = plt.subplots(2,1, figsize=(3.5,6))
# axs = axs.ravel()

fig, ax = plt.subplots(1,1, figsize=(3.7,3.2))
ax.set_xscale('log')
ax.set_xlabel('\u0394$S_{gws}$ / \u0394$Q_{spe}$ [d]')
ax.set_ylabel('$A_{int}$ / $A_{sat}$ [-]')
ax.set_axisbelow(True)
# ax.axhline(y=0, color='k', zorder=2)
# ax.axvline(x=0, color='k', zorder=2)
ax.set_xlim(1, 1000)
# ax.set_ylim(0, 15)
# ax.set_yticks(np.arange(0,15+1,5))
# ax.grid(zorder=-1000)
# ax.xaxis.grid(color='gray', zorder=-1)
# ax.yaxis.grid(color='gray', zorder=-1)

for watershed_name in watershed_names :
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = 'k'
    
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)
    
    area = BV.geographic.area
        
    for mod in mod_list:
        
        for sce in sce_list:
            
            simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+sce+'*')
            simul = simul_list[0]
                
            model_name = simul.split('\\')[-1]
            Sy = float(model_name.split('_')[3].split('-')[0]) # %
            K = float(model_name.split('_')[3].split('-')[1]) / 24 / 3600 # m/s
            E = float(model_name.split('_')[3].split('-')[2]) # m
            D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
            params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
            Smod_path = simul+'/_watershed/_simulated_results_bis.csv'     
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            Smod['prop_ratio'] = Smod.intermit_areas / Smod.surflow_areas
            Smod['recharge'] = Smod['recharge'] * 1000 * 30
            Smod['outflow_drain'] = Smod['outflow_drain'] * (area * 1e6)
            # Smod['groundwater_storage'] = Smod['groundwater_storage']/(Smod['groundwater_storage'].mean())
            Smod['groundwater_storage'] = Smod['groundwater_storage'] #/1e6
            Smod = select_period(Smod, 1960, 2019)
            
            for xy in xy_list:
                                
                x = Smod[xy[0]].diff() / Smod[xy[1]].diff()
                y = Smod[xy[2]]
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
                # ax.plot(xiline, yiline, linestyle = '-', lw=1, 
                #         color='k', zorder=0)
                wyi = np.arange(1,12+1,1)
                compt = 2
                for k in wyi:
                    ax.annotate(k,(xi[k],yi[k]), family='sans-serif', fontsize=4, 
                                 color=dict_c[watershed_name], weight="bold", ha='center', va='center',
                                 zorder=compt)
                    ax.plot(xi[k], yi[k], marker="o", lw=2, markersize=7, 
                               markeredgecolor='k', 
                               markerfacecolor='white', markeredgewidth=1,
                               linestyle = 'None', zorder=compt)
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
                ax.axvline(x.median(), c=dict_c[watershed_name], ls='--')

ax.set_ylim(bottom=None, top=1)

base_name = figsim_folder+'fig12/'
spec_name = str(watershed_names)+'_t vs Aint'
fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight') 

#%% t vs Asat

from scipy.stats import binned_statistic

watershed_names = ['Canut','Nancon']

typ = 'calibr-t6'

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

c = ['darkgreen','darkmagenta']
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

xy_list = [['groundwater_storage','outflow_drain','surflow_areas']]

# fig, axs = plt.subplots(2,1, figsize=(3.5,6))
# axs = axs.ravel()

fig, ax = plt.subplots(1,1, figsize=(3.5,3.2))
ax.set_xscale('log')
ax.set_xlabel('L² / D [d]')
ax.set_xlabel('R [mm/month]')
# ax.set_ylabel('$A_{int}$ / $A_{per}$ [-]')
ax.set_ylabel('$A_{sat}$ [%]')
# ax.set_xlim(0.1,250)
# ax.set_ylim(-0.05,1)
ax.set_ylim(0, 15)
ax.set_yticks(np.arange(0,15+1,5))
fig.tight_layout()
# fig3.tight_layout()
ax.set_axisbelow(True)
# ax.grid(zorder=-1000)
# ax.xaxis.grid(color='gray', zorder=-1)
# ax.yaxis.grid(color='gray', zorder=-1)
ax.set_xlim(0.1, 1000)

for watershed_name in watershed_names :
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = 'k'
        
    for mod in mod_list:
        
        for sce in sce_list:
            
            simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+sce+'*')
            simul = simul_list[0]
                
            model_name = simul.split('\\')[-1]
            Sy = float(model_name.split('_')[3].split('-')[0]) # %
            K = float(model_name.split('_')[3].split('-')[1]) / 24 / 3600 # m/s
            E = float(model_name.split('_')[3].split('-')[2]) # m
            D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
            params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
            Smod_path = simul+'/_watershed/_simulated_results_bis.csv'     
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            Smod['prop_ratio'] = Smod.intermit_areas / Smod.surflow_areas
            Smod['recharge'] = Smod['recharge'] * 1000 * 30
            Smod['outflow_drain'] = Smod['outflow_drain'] * (area * 1e6)
            # Smod['groundwater_storage'] = Smod['groundwater_storage']/(Smod['groundwater_storage'].mean())
            Smod['groundwater_storage'] = Smod['groundwater_storage'] #/1e6
            Smod = select_period(Smod, 1960, 2019)
            
            for xy in xy_list:
                                
                x = Smod[xy[0]].diff() / Smod[xy[1]].diff()
                y = Smod[xy[2]]
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
                # ax.plot(xiline, yiline, linestyle = '-', lw=1, 
                #         color='k', zorder=0)
                wyi = np.arange(1,12+1,1)
                compt = 2
                for k in wyi:
                    ax.annotate(k,(xi[k],yi[k]), family='sans-serif', fontsize=4, 
                                 color=dict_c[watershed_name], weight="bold", ha='center', va='center',
                                 zorder=compt)
                    ax.plot(xi[k], yi[k], marker="o", lw=2, markersize=7, 
                               markeredgecolor='k', 
                               markerfacecolor='white', markeredgewidth=1,
                               linestyle = 'None', zorder=compt)
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
                ax.axvline(x.median(), c=dict_c[watershed_name], ls='--', lw= 1.5)
                # ax.axhline(y.median(), c=dict_c[watershed_name], ls='--')
                print(x.median())

base_name = figsim_folder+'fig12/'
spec_name = str(watershed_names)+'_t vs Asat'
fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight') 

#%% Rt vs Qt

from scipy.stats import binned_statistic

watershed_names = ['Canut','Nancon']

typ = 'calibr-t6'

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

c = ['forestgreen','darkmagenta']
c = ['blue','darkmagenta']
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

xy_list = [['groundwater_storage','outflow_drain','surflow_areas']]

# fig, axs = plt.subplots(2,1, figsize=(3.5,6))
# axs = axs.ravel()

fig, ax = plt.subplots(1,1, figsize=(3.7,3.2))
ax.set_xscale('log')
ax.set_yscale('log')
ax.set_xlabel(r'$\int_{n-t}^{n}R$', labelpad=5)
ax.set_ylabel(r'$\int_{n-t}^{n}Q_{spe}$')
ax.set_ylabel(r'$\int_{n-t}^{n}Q_{spe}$')
ax.set_axisbelow(True)
# ax.axhline(y=0, color='k', zorder=2)
# ax.axvline(x=0, color='k', zorder=2)
# ax.set_xlim(1, 1000)
# ax.set_ylim(0, 15)
# ax.set_yticks(np.arange(0,15+1,5))
# ax.grid(zorder=-1000)
# ax.xaxis.grid(color='gray', zorder=-1)
# ax.yaxis.grid(color='gray', zorder=-1)
ax.set_aspect('equal')

tau_typ = 1
# tau_typ = 'calc'

for watershed_name in watershed_names :
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = 'k'
    
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)
    
    area = BV.geographic.area
        
    for mod in mod_list:
        
        for sce in sce_list:
            
            simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+sce+'*')
            simul = simul_list[0]
                
            model_name = simul.split('\\')[-1]
            Sy = float(model_name.split('_')[3].split('-')[0]) # %
            K = float(model_name.split('_')[3].split('-')[1]) / 24 / 3600 # m/s
            E = float(model_name.split('_')[3].split('-')[2]) # m
            D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
            params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
            Smod_path = simul+'/_watershed/_simulated_results_bis.csv'     
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            Smod['prop_ratio'] = Smod.intermit_areas / Smod.surflow_areas
            Smod['recharge'] = Smod['recharge'] # * 1000 * 30
            Smod['outflow_drain'] = Smod['outflow_drain'] # * 1000 * 30
            # Smod['groundwater_storage'] = Smod['groundwater_storage']/(Smod['groundwater_storage'].mean())
            Smod['groundwater_storage'] = Smod['groundwater_storage'] / (area * 1e6)
            Smod = select_period(Smod, 1960, 2019)
        
            Smod['tau_stock'] = (Smod['groundwater_storage'].diff() / Smod['outflow_drain'].diff())
            
            Smod['recharge'] = Smod['recharge'] * 1000 * 30
            Smod['outflow_drain'] = Smod['outflow_drain'] * 1000 * 30
            
            Smod['convol'] = np.nan
            
            Smod = Smod[1:]
            
            Smod = Smod.reset_index()
            
            for i in range(len(Smod)):
                if tau_typ == 'calc':
                    the_tau = int(round(Smod.iloc[i]['tau_stock']))
                else:
                    the_tau = tau_typ
                Smod.loc[i,'convol_rec'] = Smod.iloc[i-the_tau:i]['recharge'].sum()
                Smod.loc[i,'convol_dis'] = Smod.iloc[i-the_tau:i]['outflow_drain'].sum()
                # print(Smod.iloc[i-the_tau:i]['recharge'].sum())
                # .rolling(min_periods=None,window=the_tau).sum()

            Smod = Smod.set_index('date')
            
            c = Smod.index.month
            wy = pd.Series(c).replace([10,11,12,1,2,3,4,5,6,7,8,9],
                                                    [1,2,3,4,5,6,7,8,9,10,11,12])
            
    cmapping = dict_cmap[watershed_name]
    ax.scatter(Smod.convol_rec,
               Smod.convol_dis, c=wy, marker='o', cmap=cmapping,
                s=5, vmin=1, vmax=12, alpha=0.75, ec='none', lw=0.2)

    minimum = np.min((ax.get_xlim(),ax.get_ylim()))
    maximum = np.max((ax.get_xlim(),ax.get_ylim()))
    
    ax.plot((minimum, maximum+1000), (minimum, maximum+1000), c='k', zorder=-10)
    
    ax.set_xlim(minimum*1.2,maximum*1.2)
    ax.set_ylim(minimum*1.2,maximum*1.2)
    
    # ax.set_xlim(10,maximum*1.2)
    # ax.set_ylim(10,maximum*1.2)
    
    if tau_typ == 'calc':
        list_lims = [10,maximum*1.2]
        
    # if tau_typ != 'calc':
    #     ax.set_xlim(list_lims[0],list_lims[1])
    #     ax.set_ylim(list_lims[0],list_lims[1])
    
base_name = figsim_folder+'fig12/'
spec_name = str(watershed_names)+'_Rt vs Qt_one day'
fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight') 

#%% Lphy vs Aint

from scipy.stats import binned_statistic

watershed_names = ['Canut','Nancon']

typ = 'calibr-t6'

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

c = ['forestgreen','darkmagenta']
c = ['blue','darkmagenta']
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

# fig, axs = plt.subplots(2,1, figsize=(3.5,6))
# axs = axs.ravel()

fig, ax = plt.subplots(1,1, figsize=(3.7,3.2))
# ax.set_xscale('log')
ax.set_xlabel('$L_{phy}$ [m]')
ax.set_xlabel('$L_{phy}$ norm [m]')
ax.set_ylabel('$A_{int}$ / $A_{sat}$ [%]')
ax.set_axisbelow(True)
# ax.axhline(y=0, color='k', zorder=2)
# ax.axvline(x=0, color='k', zorder=2)
ax.set_xlim(0, 6)
# ax.set_xticks(np.arange(0,3001,1000))
ax.set_ylim(-0.05, 1)
# ax.set_yticks(np.arange(0,15+1,5))
# ax.grid(zorder=-1000)
# ax.xaxis.grid(color='gray', zorder=-1)
# ax.yaxis.grid(color='gray', zorder=-1)

for watershed_name in watershed_names :
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = 'k'
    
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)
    
    area = BV.geographic.area
        
    for mod in mod_list:
        
        for sce in sce_list:
            
            simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+sce+'*')
            simul = simul_list[0]
                
            model_name = simul.split('\\')[-1]
            Sy = float(model_name.split('_')[3].split('-')[0]) # %
            K = float(model_name.split('_')[3].split('-')[1]) / 24 / 3600 # m/s
            E = float(model_name.split('_')[3].split('-')[2]) # m
            D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
            params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
            Smod_path = simul+'/_watershed/_simulated_results_bis.csv'     
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            Smod['prop_ratio'] = Smod.intermit_areas / Smod.surflow_areas
            Smod['recharge'] = Smod['recharge'] * 1000 * 30
            Smod['outflow_drain'] = Smod['outflow_drain'] * (area * 1e6)
            # Smod['groundwater_storage'] = Smod['groundwater_storage']/(Smod['groundwater_storage'].mean())
            Smod['groundwater_storage'] = Smod['groundwater_storage'] #/1e6
            Smod = select_period(Smod, 1960, 2019)
            
            for xy in xy_list:
                                
                x = np.sqrt((Smod[xy[0]].diff() *
                             (K*24*3600) *
                             (E-Smod['watertable_depth'])) /
                             (Smod[xy[1]].diff() * (Sy/100))) / Smod['L_dem_complete']
                y = Smod[xy[2]]
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
                compt = 2
                for k in wyi:
                    ax.annotate(k,(xi[k],yi[k]), family='sans-serif', fontsize=4, 
                                 color=dict_c[watershed_name], weight="bold", ha='center', va='center',
                                 zorder=compt)
                    ax.plot(xi[k], yi[k], marker="o", lw=2, markersize=7, 
                               markeredgecolor='k', 
                               markerfacecolor='white', markeredgewidth=1,
                               linestyle = 'None', zorder=compt)
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
                ax.axvline(x.median(), c=dict_c[watershed_name], ls='--')

# ax.set_ylim(bottom=None, top=1)

base_name = figsim_folder+'fig12/'
spec_name = str(watershed_names)+'_Lphy vs Aint norm'
fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight') 

#%% Lapp vs Aint

from scipy.stats import binned_statistic

watershed_names = ['Canut','Nancon']

typ = 'calibr-t6'

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

c = ['forestgreen','darkmagenta']
c = ['blue','darkmagenta']
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

# xy_list = [['groundwater_storage','outflow_drain','prop_ratio']]
xy_list = [['L_wt_median_str','prop_ratio']]

# fig, axs = plt.subplots(2,1, figsize=(3.5,6))
# axs = axs.ravel()

fig, ax = plt.subplots(1,1, figsize=(3.7,3.2))
# ax.set_xscale('log')
ax.set_xlabel('$L_{app}$ norm [m]')
ax.set_ylabel('$A_{int}$ / $A_{sat}$ [%]')
ax.set_axisbelow(True)
# ax.axhline(y=0, color='k', zorder=2)
# ax.axvline(x=0, color='k', zorder=2)
# ax.set_xlim(0, 3000)
ax.set_xlim(0, 10)
# ax.set_xticks(np.arange(0,3001,1000))
ax.set_ylim(-0.05, 1)
# ax.set_yticks(np.arange(0,15+1,5))
# ax.grid(zorder=-1000)
# ax.xaxis.grid(color='gray', zorder=-1)
# ax.yaxis.grid(color='gray', zorder=-1)

for watershed_name in watershed_names :
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = 'k'
    
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)
    
    area = BV.geographic.area
        
    for mod in mod_list:
        
        for sce in sce_list:
            
            simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+sce+'*')
            simul = simul_list[0]
                
            model_name = simul.split('\\')[-1]
            Sy = float(model_name.split('_')[3].split('-')[0]) # %
            K = float(model_name.split('_')[3].split('-')[1]) / 24 / 3600 # m/s
            E = float(model_name.split('_')[3].split('-')[2]) # m
            D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
            params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
            Smod_path = simul+'/_watershed/_simulated_results_bis.csv'     
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            Smod['prop_ratio'] = Smod.intermit_areas / Smod.surflow_areas
            Smod['recharge'] = Smod['recharge'] * 1000 * 30
            Smod['outflow_drain'] = Smod['outflow_drain'] * (area * 1e6)
            # Smod['groundwater_storage'] = Smod['groundwater_storage']/(Smod['groundwater_storage'].mean())
            Smod['groundwater_storage'] = Smod['groundwater_storage'] #/1e6
            Smod = select_period(Smod, 1960, 2019)
            
            for xy in xy_list:
                                
                x = Smod[xy[0]] / Smod['L_dem_complete']
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
                compt = 2
                for k in wyi:
                    ax.annotate(k,(xi[k],yi[k]), family='sans-serif', fontsize=4, 
                                 color=dict_c[watershed_name], weight="bold", ha='center', va='center',
                                 zorder=compt)
                    ax.plot(xi[k], yi[k], marker="o", lw=2, markersize=7, 
                               markeredgecolor='k', 
                               markerfacecolor='white', markeredgewidth=1,
                               linestyle = 'None', zorder=compt)
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
                ax.axvline(x.median(), c=dict_c[watershed_name], ls='--', zorder=-10)

# ax.set_ylim(bottom=None, top=1)

base_name = figsim_folder+'fig12/'
spec_name = str(watershed_names)+'_Lapp vs Aint norm'
fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight') 

#%% Hand

from scipy.stats import binned_statistic

watershed_names = ['Canut','Nancon']

# watershed_names = ['Nancon']

typ = 'calibr-t6'

# Things
time_step = 'M'
sim_state = 'transient'
var = 'REC'
mod_list = ['REA']
sce_list = ['historic']

# list_R = np.geomspace(0.01, 2, 10).round(3)

list_R = [1/100, 2/100, 3/100, 6/100, 10/100,
          20/100, 40/100, 60/100, 100/100, 200/100]

dict_hand = {}

for watershed_name in watershed_names :
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = 'k'
    
    df_hand = pd.DataFrame()
    
    # fig, ax = plt.subplots(1,1, figsize=(3.5,3.2))
    
    fig, axs = plt.subplots(2,5, figsize=(6,4))
    axs = axs.ravel()

    for mod in mod_list:
        
        # fig1, axs1 = plt.subplots(1,1, figsize=(5,5))
        # xn = 0.1
        # xx = 100
        # yn = 0.1
        # yx = 100
        # ax = axs1
        # ax.set_title(mod)
        # ax.set_aspect('equal', adjustable='box')

        for sce in sce_list:
            
            simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+sce+'*')
            simul = simul_list[0]
            
            # if sce == 'historic':
            #     simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+'RCP8.5'+'*')
            #     simul = simul_list[0]
                
            model_name = simul.split('\\')[-1]
            Sy = float(model_name.split('_')[3].split('-')[0]) # %
            K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
            E = float(model_name.split('_')[3].split('-')[2]) # m
            D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
            params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
            Smod_path = simul+'/_watershed/_simulated_results.csv'            
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            Smod['prop_ratio'] = Smod.intermit_areas / Smod.perenn_areas
            
            Smod = select_period(Smod, 1960, 2019)
            # Smod['groundwater_storage'] = Smod['groundwater_storage']/(Smod['groundwater_storage'].mean())
            Smod['groundwater_storage'] = Smod['groundwater_storage']/1e6

            R = Smod['recharge'].mean() * 1000 * 365
            print(R)

            for i, rat in enumerate(list_R):
                
                ax = axs[i]
                
                print(rat)

                hand_nancon = imageio.imread(out_path+'/'+watershed_name+'/'+'results_stable/geographic/'+'Vertical Distance to Channel Network'+'.tif') 
                hand_nancon[hand_nancon==-99999] = np.nan
                hand_nancon[hand_nancon<0] = 0

                hand_nancon = ((R*rat)/1000) / ((hand_nancon)*(Sy/100))
                
                hand_store = hand_nancon.copy()
                hand_store[hand_store==np.inf] = -1
                df_hand[watershed_name+'_'+str(rat)] = hand_store.flatten()
                
                count_nofill = np.ma.masked_where(hand_nancon > 1, hand_nancon).count()
                count_fill = np.ma.masked_where(hand_nancon < 1, hand_nancon).count()
                
                ax.imshow(np.ma.masked_where(hand_nancon > 1, hand_nancon),
                            cmap=mpl.colors.ListedColormap('red'), alpha=0.60)
                ax.imshow(np.ma.masked_where(hand_nancon < 1, hand_nancon),
                            cmap=mpl.colors.ListedColormap('dodgerblue'), alpha=0.60)
                
                hand_nancon[hand_nancon!=np.inf] = np.nan
                hand_nancon[hand_nancon==np.inf] = 1
                count_hand = np.count_nonzero(hand_nancon[hand_nancon==1])
                
                ax.imshow(hand_nancon, cmap=mpl.colors.ListedColormap('k'), alpha=1)
                # ax.imshow(np.ma.masked_where((hand_nancon < 1)&(hand_nancon > 1), hand_nancon),
                #         cmap=mpl.colors.ListedColormap('green'))
                
                # df_hand[watershed_name+'_'+str(rat)] = count_fill
                # df_hand[watershed_name+'_'+str(rat)] = count_hand

                # plt.imshow(np.ma.masked_where(hand_nancon < 1, hand_nancon))
                
                ax.get_xaxis().set_visible(False)
                ax.get_yaxis().set_visible(False)
                
                # ax.set_title((rat*100).round(0).astype(int), fontsize=7)
                ax.set_title(int((rat*100)), fontsize=7)

            dict_hand[watershed_name] = df_hand
            
    plt.tight_layout()
    
    base_name = figsim_folder+'fig12/'
    spec_name = watershed_name+'_Hand map'
    # fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight') 
    
fig, ax = plt.subplots(1,1, figsize=(6,4))
ax.set_xlabel('Proportion of the actual recharge [%]')
ax.set_ylabel('$R_{range}$ / (HAND * Φ)')
ax.set_yscale('log')
c = ['forestgreen','darkmagenta']
dict_c = dict(zip(watershed_names, c))
ax.xaxis.grid(color='gray', zorder=-1)

for watershed_name in watershed_names :
        
    df_hand = dict_hand[watershed_name]
    
    if watershed_name == 'Canut':
        pos = -0.20
    if watershed_name == 'Nancon':
        pos = +0.20
    
    for i, j in enumerate(df_hand):
        print(i)
    
        boxprops = dict(linestyle='-', linewidth=1, color='black',
                        facecolor=dict_c[watershed_name], alpha=0.5)
        medianprops = dict(linestyle='-', linewidth=0, color='black')
        meanpointprops = dict(markersize=0, marker='o', markeredgecolor='black',
                              markerfacecolor='k', linestyle='-')
        
        bp = ax.boxplot(df_hand[j].dropna(), widths=0.32,
                         positions=[i+1+pos],
                         whis=False, showfliers=False, showmeans=False,
                         medianprops=medianprops, meanprops=meanpointprops,
                         patch_artist=True, boxprops=boxprops)
        
        ax.plot(i+1+pos, df_hand[j].dropna().median(), marker='o', mec='k', ms=3, lw=0,
                mfc=dict_c[watershed_name], mew=0.5,
                color='k', zorder=1000)
        
        for element in bp['whiskers']:
            element.set_color(dict_c[watershed_name])
            element.set_linestyle('-')
        
        d = df_hand[j].copy()
        
        ax.vlines(x=i+1+pos, 
                    ymin=d.quantile(0.75), 
                    ymax=d.quantile(0.90), color=dict_c[watershed_name], zorder=2)
        ax.vlines(x=i+1+pos, 
                    ymin=d.quantile(0.10), 
                    ymax=d.quantile(0.25), color=dict_c[watershed_name], zorder=2)
        ax.plot(i+1+pos, 
                
                  d.quantile(0.10), color=dict_c[watershed_name], zorder=2, lw=0,
                  marker='_', mew=1)
        ax.plot(i+1+pos, 
                  d.quantile(0.90), color=dict_c[watershed_name], zorder=2, lw=0,
                  marker='_', mew=1)
                  
        i += 1
    
    ax.axhline(1, c='k', lw=2, zorder=0)
    ax.set_xticks(np.arange(1,len(df_hand.columns)+1,1))
    ax.set_ylim(0.01,100)
    ax.set_xticklabels((np.array(list_R)*100).round(0).astype(int))

base_name = figsim_folder+'fig12/'
spec_name = str(watershed_names)+'_Hand boxplot'
fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight') 

#%% Successive

from scipy.stats import binned_statistic

watershed_names = ['Canut','Nancon']
# watershed_names = ['Canut']
# watershed_names = ['Nancon']

typ = 'sce-synt-t1'

# Things
time_step = 'M'
sim_state = 'transient'
var = 'REC'

# Colored
# mod_list = ['REA']
mod_list = ['SYNT-NORM', 'SYNT-DRY1', 'SYNT-DRY2']
# mod_list = ['SYNT-NORM']
# mod_list = ['SYNT-DRY2']
sce_list = ['historic']
sce_cmap = ["Greys"]
sce_color = ["k"]
cmap_dict = dict(zip(sce_list, sce_cmap))
color_dict = dict(zip(sce_list, sce_color))

c = ['forestgreen','darkmagenta']
c = ['forestgreen','darkmagenta']
cmaps = ['winter','spring']
# cmaps = ['YlGn','RdPu']
dict_c = dict(zip(watershed_names, c))
dict_cmap = dict(zip(watershed_names, cmaps))

dict_mod = dict(zip(mod_list,['-','--',':']))

# Hysteres
temporal = False
space = 0
norm = False

# fig, axs = plt.subplots(1,4, figsize=(14,3))
# axs = axs.ravel()
# fig3, axs3 = plt.subplots(1,4, figsize=(14,3))
# axs3 = axs3.ravel()

xy_list = [['groundwater_storage','outflow_drain','surflow_areas']]

# fig, axs = plt.subplots(2,1, figsize=(3.5,6))
# axs = axs.ravel()

# fig, ax = plt.subplots(1,1, figsize=(3.7,3.2))
# ax.set_xscale('log')
# # ax.set_yscale('log')
# ax.set_xlabel('\u0394$S_{gws}$ / \u0394$Q_{spe}$ [d]')
# ax.set_xlabel('R [mm/mois]')
# ax.set_ylabel('$A_{sat}$ [%]')
# ax.set_axisbelow(True)
# ax.axhline(y=0, color='k', zorder=2)
# ax.axvline(x=0, color='k', zorder=2)
# ax.set_xlim(1, 100)
# ax.set_ylim(0, 15)
# ax.set_yticks(np.arange(0,15+1,5))
# ax.grid(zorder=-1000)
# ax.xaxis.grid(color='gray', zorder=-1)
# ax.yaxis.grid(color='gray', zorder=-1)

# figb, axb = plt.subplots(1,1, figsize=(5,3))

for watershed_name in watershed_names :
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = 'k'
    
    fig, ax = plt.subplots(1,1, figsize=(3.7,3.2))
    ax.set_xscale('log')
    # ax.set_yscale('log')
    ax.set_xlabel('\u0394$S_{gws}$ / \u0394$Q_{spe}$ [d]')
    ax.set_xlabel('R [mm/mois]')
    ax.set_ylabel('$A_{int}$ / $A_{sat}$ [-]')
    ax.set_axisbelow(True)
    ax.set_ylim(-0.1,1)
    
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)
    
    area = BV.geographic.area
        
    for mod in mod_list:
        
        for sce in sce_list:
            
            simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+sce+'*')
            simul = simul_list[0]
                
            model_name = simul.split('\\')[-1]
            Sy = float(model_name.split('_')[3].split('-')[0]) # %
            K = float(model_name.split('_')[3].split('-')[1]) / 24 / 3600 # m/s
            E = float(model_name.split('_')[3].split('-')[2]) # m
            D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
            params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
            Smod_path = simul+'/_watershed/_simulated_results_bis.csv'     
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            Smod['prop_ratio'] = Smod.intermit_areas / Smod.surflow_areas
            Smod['recharge'] = Smod['recharge'] * 1000 * 30
            Smod['outflow_drain'] = Smod['outflow_drain'] * (area * 1e6)
            # Smod['groundwater_storage'] = Smod['groundwater_storage']/(Smod['groundwater_storage'].mean())
            Smod['groundwater_storage'] = Smod['groundwater_storage'] #/1e6
            Smod = select_period(Smod, 1960, 2019)
            
            Smod['counts'] = 0
            Smod['counts'][Smod['recharge']<Smod.recharge.max()/2] = 1

            for xy in xy_list:
                
                Smod['tau_phy'] = abs(Smod[xy[0]].diff() / Smod[xy[1]].diff())  
                
                x = Smod['recharge'] #/ (Smod.recharge.median())
                # x = Smod['groundwater_storage'] / Smod['groundwater_storage'].mean() #/ (Smod.recharge.median())
                # x = Smod['recharge']
                # x = Smod['tau_phy']
                
                # y = Smod['outflow_drain']
                y = Smod['prop_ratio']
                # y = Smod['surflow_areas']
                
                # y = Smod['recharge']
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
                
                # if mod != 'SYNT-NORM':
                ax.plot(xiline, yiline, linestyle = dict_mod[mod], lw=2, 
                        color=dict_c[watershed_name], zorder=0)
                    
                data = pd.DataFrame()
                data['inx'] = xiline
                data['iny'] = yiline
                polyg_loop = Polygon(tuple(data.itertuples(index=False, name=None)))
                xpolyg, ypolyg = polyg_loop.exterior.xy
                maxi = 1.5
                mini = -0.1
                line_oneone = SG.LineString([(mini,mini), (maxi,maxi)])
                areas = cut_polygon_by_line(polyg_loop, line_oneone)
                from descartes import PolygonPatch
                for i in range(len(areas)):
                    ring_patch = PolygonPatch(areas[i], color=dict_c[watershed_name], alpha=0.5, lw=0, ec="k", zorder=1000)
                if mod == 'SYNT-DRY2':
                    ax.add_patch(ring_patch)
                if mod == 'SYNT-NORM':
                    # ax.add_patch(ring_patch)
                    wyi = np.arange(1,12+1,1)
                    compt = 1000
                    for k in wyi:
                        ax.annotate(k,(xi[k],yi[k]), family='sans-serif', fontsize=4, 
                                      color=dict_c[watershed_name], weight="bold", ha='center', va='center',
                                      zorder=compt)
                        ax.plot(xi[k], yi[k], marker="o", lw=2, markersize=7, 
                                    markeredgecolor='k', 
                                    markerfacecolor='white', markeredgewidth=1,
                                    linestyle = 'None', zorder=compt)
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

#                 axb.plot(Smod['outflow_drain'], c=dict_c[watershed_name], ls = dict_mod[mod])

# axb.set_xlim(pd.to_datetime('2010'), pd.to_datetime('2019'))
                
# ax.set_ylim(bottom=None, top=1)

    base_name = figsim_folder+'_successive/'
    spec_name = str(watershed_name)+'_R vs Aint'
    fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight') 

#%% Pi statistics

watershed_names = ['Canut','Nancon']

typ = 'calibr-t6'


var = 'REC'
scan = 'outflow_drain'
sce_list = ['historic']

# fig2, axs2 = plt.subplots(1,1, figsize=(5,4),
#                         sharex=True, sharey=True)

y_name = 'surflow_areas'

# fig1, axs1 = plt.subplots(1,1, figsize=(4,3),
#                         sharex=True, sharey=True)

# fig2, axs2 = plt.subplots(1,1, figsize=(4,3),
#                         sharex=True, sharey=True)

# fig3, axs3 = plt.subplots(1,1, figsize=(3.5,3),
#                         sharex=True, sharey=True)

for watershed_name in watershed_names:

    if watershed_name == 'Canut':
        color = 'green'
        m = '^'
    if watershed_name == 'Nancon':
        color = 'darkmagenta'
        m = 'o'

    fig1, axs1 = plt.subplots(1,1, figsize=(4,2),
                            sharex=True, sharey=True)

    # fig1, axs1 = plt.subplots(1,1, figsize=(10,10), sharex=True, sharey=True)
    # axs1 = axs1.ravel()
    
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'  # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
        
    for ix in np.arange(1,1+1,1):
        # simul_list = glob.glob(simulations_folder+'*'+typ+'_'+str(i)+'*')
                    
        for sce in sce_list:
            # simul_list = glob.glob(simulations_folder+'*'+typ+'_'+str(i)+'*'+sce+'*')
            
            simul = glob.glob(simulations_folder+'*'+typ+'_'+str(ix)+'*'+sce+'*')[0]
            model_name = simul.split('\\')[-1]
            Sy = float(model_name.split('_')[3].split('-')[0]) # %
            K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
            E = float(model_name.split('_')[3].split('-')[2]) # m
            D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
            params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
            
            Smod_path = simul+'/_watershed/_simulated_results.csv'            
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            Smod['prop_ratio'] = Smod.intermit_areas / Smod.perenn_areas
            
            acc_npy = np.load(os.path.join(simul, '_watershed','accumulation_flux.npy'), allow_pickle=True).item()
            acc_npy = list(acc_npy.items())[:]
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
            
            days_flux = np.ma.masked_array(days_flux, mask=(days_flux==0))
                    
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
            
            ###### NP HISTOGRAM
            ax = axs1
            bins = 100
            test = np.histogram(Z, bins=bins, density=True)
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
            ax.bar(test[1][1:], test[0]/sum(test[0])*100, width=0.02, lw=0,
                   color=my_cmap(rescale(test[1][1:])))
            ax.set_yscale('log')
            # plt.plot()
            ax.set_xlim(0.0,1.01)
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
    figsim_folder = 'D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/8_paper/hysteresis/figures/v5/'
    base_name = figsim_folder+'2_fig_mod_pi/'
    spec_name = str(watershed_name)+'_histog'
    fig1.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight') 

#%% Asat statistics

watershed_names = ['Canut','Nancon']

typ = 'calibr-t6'


var = 'REC'
scan = 'outflow_drain'
sce_list = ['historic']

# fig2, axs2 = plt.subplots(1,1, figsize=(5,4),
#                         sharex=True, sharey=True)

y_name = 'surflow_areas'
y_name = 'prop_ratio'

fig2, axs2 = plt.subplots(1,1, figsize=(4,3),
                        sharex=True, sharey=True)

fig3, axs3 = plt.subplots(1,1, figsize=(3.5,3),
                        sharex=True, sharey=True)

for watershed_name in watershed_names:

    if watershed_name == 'Canut':
        color = 'green'
        m = '^'
    if watershed_name == 'Nancon':
        color = 'darkmagenta'
        m = 'o'

    # fig1, axs1 = plt.subplots(1,1, figsize=(10,10), sharex=True, sharey=True)
    # axs1 = axs1.ravel()
    
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'  # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
        
    for ix in np.arange(1,1+1,1):
        # simul_list = glob.glob(simulations_folder+'*'+typ+'_'+str(i)+'*')
                    
        for sce in sce_list:
            # simul_list = glob.glob(simulations_folder+'*'+typ+'_'+str(i)+'*'+sce+'*')
            
            simul = glob.glob(simulations_folder+'*'+typ+'_'+str(ix)+'*'+sce+'*')[0]
            model_name = simul.split('\\')[-1]
            Sy = float(model_name.split('_')[3].split('-')[0]) # %
            K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
            E = float(model_name.split('_')[3].split('-')[2]) # m
            D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
            params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
            
            Smod_path = simul+'/_watershed/_simulated_results.csv'            
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            Smod['prop_ratio'] = Smod.intermit_areas / Smod.surflow_areas
            

            ax = axs2
            # axb = ax.twinx()
            y_name= 'surflow_areas'
            X2 = np.sort(Smod[y_name])
            
            if watershed_name == 'Canut':
                Xc = X2.copy()
                
            N = len(Smod[y_name])
            # ax.plot((1-np.arange(0,N,1)/N)*100, (X2-X2.min())/(X2.max()-X2.min()) * 100,
            #         color=color, lw=2)
            ax.plot((1-np.arange(0,N,1)/N)*100, (X2),
                    color=color, lw=2)
            ax.fill_between((1-np.arange(0,N,1)/N)*100,
                            Xc,
                            X2,
                             lw=0,
                            color='silver', alpha=0.5)
            # axb.plot((1-np.arange(0,N,1)/N)*100, (X2)/(X2.mean()),
            #         color=color, lw=2, ls='--')
            # axb.set_ylabel('Cumulated $A_{sat}$ normalized [-]', rotation=270, labelpad=25)
            # ax.set_xlabel('Frequency in time [%]')
            ax.set_xlabel('Frequency of occurrence [%]')
            ax.set_ylabel('Cumulated $A_{sat}$ [%]')
            ax.set_xlim(0,100)
            ax.set_ylim(0,20)
            # axb.set_ylim(0,4)
            # axb.set_yticks([0,1,2,3,4])
            # ax.set_xscale('log')
            # ax.set_yscale('log')
            # ax.grid('grey')

            ax = axs3
            # ax.axhline(y=1, color='grey', lw=1)
            # ax = ax.twinx()
            y_name= 'prop_ratio'
            X2 = np.sort(Smod[y_name])
            N = len(Smod[y_name])
            # ax.plot((1-np.arange(0,N,1)/N)*100, (X2-X2.min())/(X2.max()-X2.min()) * 100,
            #         color=color, lw=2)
            ax.plot((1-np.arange(0,N,1)/N)*100, (X2),
                    color=color, lw=2)
            
            if watershed_name == 'Canut':
                Xc = X2.copy()
            
            ax.fill_between((1-np.arange(0,N,1)/N)*100,
                            Xc,
                            X2,
                             lw=0,
                            color='silver', alpha=0.5)
            
            # ax.set_xlabel('Frequency in time [%]')
            # ax.set_ylabel('$A_{intermittent}$ / $A_{perennial}$ [-]')
            # ax.set_xlim(0,100)
            # ax.set_xscale('log')
            # ax.set_ylim(0,4)
            # ax.set_yticks([0,1,2,3,4])
            # ax.set_ylabel('Cumulated $A_{sat}$ normalized [-]')

            # ax.set_xscale('log')
            # ax.set_yscale('log')
            # ax.grid('grey')

            
# fig1.savefig(figsim_folder+'both'+'_freqcumul_pi'+'.png', dpi=300, bbox_inches='tight')
# fig2.savefig(figsim_folder+'both'+'_freqcumul_sat'+'.png', dpi=300, bbox_inches='tight')
# fig3.savefig(figsim_folder+'both'+'_freqcumul_ratio'+'.png', dpi=300, bbox_inches='tight')

#%% R vs Qobs

from scipy.stats import binned_statistic

watershed_names = ['Canut','Nancon']

typ = 'calibr-t6'

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

c = ['darkgreen','darkmagenta']
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

xy_list = [['recharge','outflow_obs']]

# fig, axs = plt.subplots(2,1, figsize=(3.5,6))
# axs = axs.ravel()

fig, ax = plt.subplots(1,1, figsize=(3.5,3.2))
# ax.set_xscale('log')
ax.set_yscale('log')
ax.set_xlabel('L² / D [d]')
ax.set_xlabel('R [mm/month]')
# ax.set_ylabel('$A_{int}$ / $A_{per}$ [-]')
ax.set_ylabel('$Q_{obs}$ [mm/month]')
# ax.set_xlim(0.1,250)
ax.set_xlim(-150, 150)
ax.set_xticks([-150,-75,0,75,150])
ax.set_ylim(0.07, 150)
x_lim=[0.07,250]
y_lim=[0.07,250]
"""
ax.set_xlim(0.1, 250)
ax.set_ylim(0.1, 250)
"""
fig.tight_layout()
# fig3.tight_layout()
ax.set_axisbelow(True)
# ax.grid(zorder=-1000)
# ax.xaxis.grid(color='gray', zorder=-1)
# ax.yaxis.grid(color='gray', zorder=-1)

for watershed_name in watershed_names :
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = 'k'
        
    for mod in mod_list:
        
        for sce in sce_list:
            
            BV = watershed_root.Watershed(watershed_name=watershed_name,
                                          dem_path=dem_path, 
                                          out_path=out_path,
                                          load=True)
            
            simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+sce+'*')
            simul = simul_list[0]
                
            model_name = simul.split('\\')[-1]
            Sy = float(model_name.split('_')[3].split('-')[0]) # %
            K = float(model_name.split('_')[3].split('-')[1]) / 24 / 3600 # m/s
            E = float(model_name.split('_')[3].split('-')[2]) # m
            D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
            params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
            Smod_path = simul+'/_watershed/_simulated_results_bis.csv'     
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            Smod['prop_ratio'] = Smod.intermit_areas / Smod.surflow_areas
            Smod['recharge'] = Smod['recharge'] * 1000 * 30
            Smod['outflow_drain'] = Smod['outflow_drain'] * 1000 * 30
            # Smod['groundwater_storage'] = Smod['groundwater_storage']/(Smod['groundwater_storage'].mean())
            Smod['groundwater_storage'] = Smod['groundwater_storage']/1e6
            Smod = select_period(Smod, 1960, 2019)
            
            area = BV.geographic.area
            stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
            Qobs_path = glob.glob(stable_folder+'hydrometry/'+'Hydrometric_'+'*')[0]
            naming = Qobs_path.split('\\')[-1]
            Qobs = pd.read_csv(Qobs_path, sep=';', index_col=0, parse_dates=True)
            # serie = series[series['<CdStationHydro>']==code_name+'01']
            # Qobs = serie['<ResObsElaborHydro>'] / 1000 # L/s to m3/s
            Qobs = Qobs.squeeze()
            Qobs = Qobs.rename('Q')
            # Qobs.to_csv(stable_folder+'hydrometry/'+naming,
            #             sep=';')
            Qobs = (Qobs / (area*1000000)) * (3600 * 24) * 1000 # m3/s to mm/month
            Qobs = select_period(Qobs, 1960, 2019) # Qobs.first_valid_index().year
            
            # Clim_path = stable_folder+'climatic/'+'_ALL_D.csv'
            # Clim = pd.read_csv(Clim_path, sep=';', index_col=0, parse_dates=True)
            Clim = surfex = pd.read_csv(out_path+'/'+'Frame'+'/'+'results_stable/'+
                                        'climatic/'+'_ALL_D.csv', sep=';',
                                  index_col=0, parse_dates=True)
            Clim = select_period(Clim, 1990, 2019)
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
            temporal = False
            spece = -0
            norm = False
            hyst.compute_xy_metrics(temporal=temporal, space=space, norm=norm)
            
            columns_x = hyst.xrecapl.columns
            columns_y = hyst.yrecapl.columns
            
            Smod['effective'] = hyst.x
            Smod['outflow_obs'] = hyst.y
            
            for xy in xy_list:
                                
                x = Smod['effective']
                y = Smod['outflow_obs']
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
                compt = 2
                for k in wyi:
                    ax.annotate(k,(xi[k],yi[k]), family='sans-serif', fontsize=4, 
                                 color=dict_c[watershed_name], weight="bold", ha='center', va='center',
                                 zorder=compt)
                    ax.plot(xi[k], yi[k], marker="o", lw=2, markersize=7, 
                               markeredgecolor='k', 
                               markerfacecolor='white', markeredgewidth=1,
                               linestyle = 'None', zorder=compt)
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

                ax.plot(np.linspace(0.07,max(x_lim),50), np.linspace(0.07,max(x_lim),50), 
                         linestyle='-', color='darkgray', linewidth=1, zorder=-1000)
                
figsim_folder = 'D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/8_paper/hysteresis/figures/v5/'

base_name = figsim_folder+'4_fig_tau_process/'
spec_name = str(watershed_names)+'_R vs Qobs'
fig.savefig(base_name+spec_name+'.png', dpi=300, bbox_inches='tight') 


#%% ---- NOTES

